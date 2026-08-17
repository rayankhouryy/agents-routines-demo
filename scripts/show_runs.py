"""Show every routine in the project and its recent run history.

This is the "prove it actually ran" view: Foundry records each routine run with
its trigger, phase, timing, and the response id of the agent invocation.

Usage:
    python scripts/show_runs.py                  # all routines
    python scripts/show_runs.py --routine <name> # one routine, with output text
"""

from __future__ import annotations

import argparse

from common import banner, get_client


def _fmt(dt) -> str:
    return dt.isoformat(timespec="seconds") if dt else "-"


def _enum(value) -> str:
    """Render SDK enums as their wire value (``completed``, not ``RoutineRunPhase.COMPLETED``)."""
    return str(getattr(value, "value", value) or "-")


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect Foundry Routine run history.")
    parser.add_argument("--routine", help="Limit to a single routine name.")
    parser.add_argument("--limit", type=int, default=10, help="Runs to show per routine.")
    parser.add_argument("--show-output", action="store_true", help="Print agent output text.")
    args = parser.parse_args()

    client = get_client()
    with client:
        routines = (
            [client.beta.routines.get(args.routine)]
            if args.routine
            else list(client.beta.routines.list())
        )

        if not routines:
            print("No routines found in this project.")
            return

        for routine in routines:
            banner(f"{routine.name}   (enabled={routine.enabled})")
            print(f"  description : {routine.description}")
            action = routine.action
            print(f"  action      : {action.type} -> {action.agent_name}")
            for name, trigger in (routine.triggers or {}).items():
                detail = getattr(trigger, "cron_expression", None) or getattr(trigger, "at", "")
                tz = getattr(trigger, "time_zone", "")
                print(f"  trigger     : {name} [{trigger.type}] {detail} {tz}".rstrip())

            runs = list(client.beta.routines.list_runs(routine.name, limit=args.limit))
            print(f"\n  runs ({len(runs)}):")
            if not runs:
                print("    (none yet - dispatch one with scripts/dispatch.py)")
            for run in runs:
                print(
                    f"    {run.id}  phase={_enum(run.phase):<10} "
                    f"source={_enum(run.attempt_source):<16} "
                    f"started={_fmt(run.started_at)}  ended={_fmt(run.ended_at)}"
                )
                if run.error_message:
                    print(f"      ERROR: {run.error_type} - {run.error_message}")

            if args.show_output:
                for run in runs:
                    if not run.response_id:
                        continue
                    try:
                        response = client.get_openai_client().responses.retrieve(run.response_id)
                    except Exception:  # noqa: BLE001
                        print(
                            f"\n    [{run.id}] output lives in the agent's own session and is "
                            f"not caller-readable in preview;\n"
                            f"    use scripts/invoke_agent.py to show agent output."
                        )
                        break
                    print(f"\n    --- output of run {run.id} ---")
                    print("    " + (response.output_text or "").replace("\n", "\n    "))
                    break


if __name__ == "__main__":
    main()
