"""Visual console for the PepsiCo Foundry demo.

A single-page app that makes the whole story visible on screen:

* both agents side by side - the **hosted** LangGraph container and the
  **prompt** agent - with their live version, kind, and image;
* both routines with their triggers;
* a **Run now** button per routine that dispatches it, streams the run phases as
  Foundry reports them, and then shows the agent's output;
* the routine run history, straight from Foundry.

Run it:

    python webapp/app.py            # http://127.0.0.1:8000
"""

from __future__ import annotations

import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import uvicorn  # noqa: E402
from fastapi import FastAPI, HTTPException  # noqa: E402
from fastapi.responses import FileResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

from common import (  # noqa: E402
    HOSTED_AGENT_NAME,
    HOSTED_ROUTINE_NAME,
    MODEL_DEPLOYMENT,
    PROJECT_ENDPOINT,
    PROMPT_AGENT_NAME,
    PROMPT_ROUTINE_NAME,
    get_client,
)
from invoke_agent import HOSTED_INPUT, PROMPT_INPUT, invoke_agent  # noqa: E402

TERMINAL_PHASES = {"completed", "succeeded", "failed", "cancelled", "canceled", "skipped"}

app = FastAPI(title="PepsiCo x Foundry - Hosted Agents + Routines")

# job_id -> job state, shared with the background dispatch threads
JOBS: dict[str, dict[str, Any]] = {}
JOBS_LOCK = threading.Lock()


def _enum(value) -> str:
    return str(getattr(value, "value", value) or "")


def _phase(run) -> str:
    return _enum(run.phase).rsplit(".", 1)[-1].lower()


def _iso(dt) -> str | None:
    return dt.isoformat(timespec="seconds") if dt else None


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%H:%M:%S")


def _agent_card(client, agent_name: str) -> dict[str, Any]:
    try:
        details = client.agents.get(agent_name).as_dict()
    except Exception as exc:  # noqa: BLE001
        return {"name": agent_name, "error": str(exc)}

    latest = (details.get("versions") or {}).get("latest") or {}
    definition = latest.get("definition") or {}
    container = definition.get("container_configuration") or {}
    return {
        "name": agent_name,
        "kind": definition.get("kind", ""),
        "version": latest.get("version") or details.get("version"),
        "description": latest.get("description") or details.get("description"),
        "model": definition.get("model") or MODEL_DEPLOYMENT,
        "image": container.get("image"),
        "cpu": definition.get("cpu"),
        "memory": definition.get("memory"),
        "identity": (details.get("instance_identity") or {}).get("principal_id"),
    }


def _routine_card(client, routine_name: str) -> dict[str, Any]:
    try:
        routine = client.beta.routines.get(routine_name)
    except Exception as exc:  # noqa: BLE001
        return {"name": routine_name, "error": str(exc)}

    triggers = []
    for name, trigger in (routine.triggers or {}).items():
        at = getattr(trigger, "at", None)
        triggers.append({
            "name": name,
            "type": _enum(trigger.type),
            "cron": getattr(trigger, "cron_expression", None),
            "at": _iso(at) if at else None,
            "time_zone": getattr(trigger, "time_zone", None),
        })

    return {
        "name": routine.name,
        "description": routine.description,
        "enabled": routine.enabled,
        "triggers": triggers,
        "action_type": _enum(routine.action.type),
        "agent_name": routine.action.agent_name,
        "input": routine.action.input,
    }


def _runs(client, routine_name: str, limit: int = 8) -> list[dict[str, Any]]:
    try:
        runs = list(client.beta.routines.list_runs(routine_name, limit=limit))
    except Exception:  # noqa: BLE001
        return []
    return [
        {
            "id": run.id,
            "phase": _phase(run),
            "source": _enum(run.attempt_source),
            "trigger": run.trigger_name,
            "started_at": _iso(run.started_at),
            "ended_at": _iso(run.ended_at),
            "response_id": run.response_id,
            "error": run.error_message,
        }
        for run in runs
    ]


@app.get("/api/state")
def state() -> dict[str, Any]:
    """Everything the page needs: project, agents, routines, recent runs."""
    client = get_client()
    with client:
        return {
            "project_endpoint": PROJECT_ENDPOINT,
            "model": MODEL_DEPLOYMENT,
            "pairs": [
                {
                    "id": "hosted",
                    "title": "Hosted Agent",
                    "subtitle": "LangGraph in a container - Foundry is the runtime",
                    "agent": _agent_card(client, HOSTED_AGENT_NAME),
                    "routine": _routine_card(client, HOSTED_ROUTINE_NAME),
                    "runs": _runs(client, HOSTED_ROUTINE_NAME),
                },
                {
                    "id": "prompt",
                    "title": "Prompt Agent",
                    "subtitle": "Model + instructions - the shape PepGPT runs today",
                    "agent": _agent_card(client, PROMPT_AGENT_NAME),
                    "routine": _routine_card(client, PROMPT_ROUTINE_NAME),
                    "runs": _runs(client, PROMPT_ROUTINE_NAME),
                },
            ],
        }


def _log(job_id: str, message: str, kind: str = "info") -> None:
    with JOBS_LOCK:
        JOBS[job_id]["events"].append({"time": _now(), "message": message, "kind": kind})


def _update(job_id: str, **fields) -> None:
    with JOBS_LOCK:
        JOBS[job_id].update(fields)


def _dispatch_worker(job_id: str, routine_name: str) -> None:
    """Dispatch a routine, follow the run, then surface the agent's output."""
    try:
        client = get_client()
        with client:
            routine = client.beta.routines.get(routine_name)
            agent_name = routine.action.agent_name
            text = routine.action.input

            _log(job_id, f"Dispatching routine '{routine_name}'")
            _log(job_id, f"Action: {_enum(routine.action.type)} -> {agent_name}")

            before = {r.id for r in client.beta.routines.list_runs(routine_name)}
            result = client.beta.routines.dispatch(
                routine_name, payload={"type": _enum(routine.action.type), "input": text}
            )
            _log(job_id, f"Dispatch accepted (id {result.dispatch_id})", "ok")

            run = None
            last_phase = None
            deadline = time.time() + 300
            while time.time() < deadline:
                time.sleep(3)
                new = [r for r in client.beta.routines.list_runs(routine_name)
                       if r.id not in before]
                if not new:
                    continue
                run = new[0]
                phase = _phase(run)
                _update(job_id, run={
                    "id": run.id,
                    "phase": phase,
                    "trigger": run.trigger_name,
                    "source": _enum(run.attempt_source),
                    "started_at": _iso(run.started_at),
                    "ended_at": _iso(run.ended_at),
                    "response_id": run.response_id,
                    "error": run.error_message,
                })
                if phase != last_phase:
                    _log(job_id, f"Run {run.id[:8]} phase = {phase}",
                         "ok" if phase == "completed" else "info")
                    last_phase = phase
                if phase in TERMINAL_PHASES:
                    break

            if run is None:
                _log(job_id, "No run appeared before the timeout.", "error")
                _update(job_id, status="failed")
                return

            if run.error_message:
                _log(job_id, run.error_message, "error")

            # The response from a routine run is written to the agent's own
            # session and is not readable by the caller in preview, so replay the
            # identical input against the same agent to show what it produces.
            _log(job_id, f"Replaying the same input against '{agent_name}' to show its output")
            started = time.time()
            response = invoke_agent(client, agent_name, text)
            _log(job_id, f"Agent responded in {time.time() - started:.1f}s", "ok")
            _update(job_id, output=response.output_text, status="done")
    except Exception as exc:  # noqa: BLE001
        _log(job_id, f"{type(exc).__name__}: {exc}", "error")
        _update(job_id, status="failed")


def _invoke_worker(job_id: str, agent_name: str, text: str) -> None:
    """Invoke an agent directly, with no routine involved."""
    try:
        client = get_client()
        with client:
            _log(job_id, f"Invoking agent '{agent_name}' directly (no routine)")
            started = time.time()
            response = invoke_agent(client, agent_name, text)
            _log(job_id, f"Agent responded in {time.time() - started:.1f}s", "ok")
            _update(job_id, output=response.output_text, status="done")
    except Exception as exc:  # noqa: BLE001
        _log(job_id, f"{type(exc).__name__}: {exc}", "error")
        _update(job_id, status="failed")


def _start_job(target, *args) -> dict[str, str]:
    job_id = uuid.uuid4().hex[:12]
    with JOBS_LOCK:
        JOBS[job_id] = {"id": job_id, "status": "running", "events": [],
                        "run": None, "output": None}
    threading.Thread(target=target, args=(job_id, *args), daemon=True).start()
    return {"job_id": job_id}


@app.post("/api/dispatch/{pair_id}")
def dispatch(pair_id: str) -> dict[str, str]:
    routine_name = HOSTED_ROUTINE_NAME if pair_id == "hosted" else PROMPT_ROUTINE_NAME
    return _start_job(_dispatch_worker, routine_name)


@app.post("/api/invoke/{pair_id}")
def invoke(pair_id: str) -> dict[str, str]:
    if pair_id == "hosted":
        return _start_job(_invoke_worker, HOSTED_AGENT_NAME, HOSTED_INPUT)
    return _start_job(_invoke_worker, PROMPT_AGENT_NAME, PROMPT_INPUT)


@app.get("/api/job/{job_id}")
def job(job_id: str) -> dict[str, Any]:
    with JOBS_LOCK:
        current = JOBS.get(job_id)
        if current is None:
            raise HTTPException(status_code=404, detail="unknown job")
        return dict(current)


STATIC_DIR = Path(__file__).resolve().parent / "static"


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


if __name__ == "__main__":
    import os

    port = int(os.environ.get("PORT", "8000"))
    print(f"PepsiCo x Foundry demo console -> http://127.0.0.1:{port}")
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="warning")
