"""Dispatch a Routine on demand and watch the run complete.

The schedules in `create_routines.py` are the real production shape, but nobody
wants to wait until 07:00 ET during a customer call. `dispatch` fires the exact
same routine action immediately, through the same execution path, and produces a
real entry in the routine's run history.

Usage:
    python scripts/dispatch.py                      # dispatch the hosted-agent routine
    python scripts/dispatch.py --prompt             # dispatch the prompt-agent routine
    python scripts/dispatch.py --routine <name>     # dispatch any routine by name
    python scripts/dispatch.py --input "..."        # override the input for this run
"""

from __future__ import annotations

import argparse
import time

from common import (
    HOSTED_ROUTINE_NAME,
    PROMPT_ROUTINE_NAME,
    banner,
    get_client,
)

TERMINAL_PHASES = {"completed", "succeeded", "failed", "cancelled", "canceled", "skipped"}


def _phase(run) -> str:
    """Normalize RoutineRunPhase (an enum) to a bare lowercase string."""
    raw = getattr(run.phase, "value", run.phase)
    return str(raw).rsplit(".", 1)[-1].lower()


def _enum(value) -> str:
    """Render SDK enums as their wire value (``completed``, not ``RoutineRunPhase.COMPLETED``)."""
    return str(getattr(value, "value", value) or "-")


def _print_run(run) -> None:
    print(
        f"  run {run.id}\n"
        f"    phase   : {_enum(run.phase)}\n"
        f"    status  : {_enum(run.status)}\n"
        f"    trigger : {_enum(run.trigger_type)} / {run.trigger_name}\n"
        f"    source  : {_enum(run.attempt_source)}\n"
        f"    agent   : {run.agent_id or run.agent_endpoint_id}\n"
        f"    response: {run.response_id}\n"
        f"    conv    : {run.conversation_id}"
    )
    if run.error_message:
        print(f"    ERROR   : {run.error_type} ({run.error_status_code}) {run.error_message}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Dispatch a Foundry Routine on demand.")
    parser.add_argument("--prompt", action="store_true", help="Dispatch the prompt-agent routine.")
    parser.add_argument("--routine", help="Dispatch a specific routine by name.")
    parser.add_argument("--input", help="Override the input text for this dispatch.")
    parser.add_argument("--timeout", type=int, default=300, help="Seconds to wait for completion.")
    args = parser.parse_args()

    routine_name = args.routine or (PROMPT_ROUTINE_NAME if args.prompt else HOSTED_ROUTINE_NAME)

    client = get_client()
    with client:
        routine = client.beta.routines.get(routine_name)
        banner(f"Dispatching routine: {routine_name}")
        print(f"  description : {routine.description}")
        print(f"  action      : {routine.action.type} -> {routine.action.agent_name}")

        # The dispatch payload must carry an input for invoke_agent_responses_api,
        # so fall back to the input the routine is configured with.
        payload = {
            "type": routine.action.type,
            "input": args.input or routine.action.input,
        }

        before = {r.id for r in client.beta.routines.list_runs(routine_name)}

        result = client.beta.routines.dispatch(routine_name, payload=payload)
        print(f"\n  dispatch_id           : {result.dispatch_id}")
        print(f"  action_correlation_id : {result.action_correlation_id}")
        print(f"  task_id               : {result.task_id}")
        print("\n  Dispatch accepted. Waiting for the run to finish...")

        deadline = time.time() + args.timeout
        run = None
        while time.time() < deadline:
            time.sleep(5)
            runs = list(client.beta.routines.list_runs(routine_name))
            new = [r for r in runs if r.id not in before]
            candidates = new or runs
            if candidates:
                run = candidates[0]
                print(f"    ... phase={_phase(run)}")
                if _phase(run) in TERMINAL_PHASES:
                    break

        banner("Run result")
        if run is None:
            print("  No run appeared before the timeout.")
            return
        _print_run(run)

        if run.response_id:
            banner("Agent output")
            # In preview, the response produced by a routine run belongs to the
            # agent's own session and is not retrievable by the caller. The run
            # record above is the proof the automation fired; use
            # scripts/invoke_agent.py to show what the agent actually produces.
            try:
                openai_client = client.get_openai_client()
                response = openai_client.responses.retrieve(run.response_id)
                print(response.output_text)
            except Exception:  # noqa: BLE001
                print(
                    f"  Response {run.response_id} was produced inside the agent's own\n"
                    f"  session and is not readable by the caller in preview.\n\n"
                    f"  The run above (phase={_phase(run)}) is the proof the routine fired.\n"
                    f"  To show the agent's actual output, run:\n\n"
                    f"      python scripts\\invoke_agent.py"
                    + ("  --prompt" if args.prompt else "")
                )


if __name__ == "__main__":
    main()
