"""Create the two Foundry **Routines** that drive the demo.

A Routine is a project-scoped automation rule: **one trigger + one action**.
Foundry owns the scheduler, the retries, and the run history - PepsiCo writes no
orchestration code and operates no scheduler.

    Routine 1  pepsico-daily-store-ops     schedule -> HOSTED LangGraph agent
    Routine 2  pepsico-weekly-exec-digest  schedule -> PROMPT agent (PepGPT)

Both actions reference their agent **by name**, which is why the same Routines
surface drives a containerized LangGraph agent and a fully managed prompt agent
identically.
"""

from __future__ import annotations

from azure.ai.projects.models import (
    InvokeAgentResponsesApiRoutineAction,
    ScheduleRoutineTrigger,
)

from common import (
    HOSTED_AGENT_NAME,
    HOSTED_ROUTINE_NAME,
    PROMPT_AGENT_NAME,
    PROMPT_ROUTINE_NAME,
    banner,
    get_client,
)

DAILY_INPUT = (
    "Run the daily retail execution review for ALL regions. Open replenishment "
    "tasks per your operating rules and return the prioritized brief."
)

WEEKLY_INPUT = (
    "Produce this week's PepsiCo executive commercial digest for the four US "
    "regions. Use illustrative demo data and label it as such."
)


def main() -> None:
    client = get_client()

    with client:
        # ── Routine 1: schedule -> hosted LangGraph agent ─────────────
        banner(f"Routine 1: {HOSTED_ROUTINE_NAME}  ->  hosted agent '{HOSTED_AGENT_NAME}'")
        hosted = client.beta.routines.create_or_update(
            routine_name=HOSTED_ROUTINE_NAME,
            description=(
                "Every weekday at 07:00 ET, run the LangGraph retail execution "
                "ops agent and open replenishment tasks."
            ),
            enabled=True,
            triggers={
                "weekday-morning": ScheduleRoutineTrigger(
                    cron_expression="0 7 * * 1-5",
                    time_zone="America/New_York",
                ),
            },
            action=InvokeAgentResponsesApiRoutineAction(
                agent_name=HOSTED_AGENT_NAME,
                input=DAILY_INPUT,
            ),
        )
        print(f"  created : {hosted.name}")
        print(f"  enabled : {hosted.enabled}")
        print("  trigger : weekdays 07:00 America/New_York  (cron '0 7 * * 1-5')")
        print(f"  action  : invoke_agent_responses_api -> {HOSTED_AGENT_NAME}")

        # ── Routine 2: schedule -> prompt agent ───────────────────────
        banner(f"Routine 2: {PROMPT_ROUTINE_NAME}  ->  prompt agent '{PROMPT_AGENT_NAME}'")
        prompt = client.beta.routines.create_or_update(
            routine_name=PROMPT_ROUTINE_NAME,
            description=(
                "Every Friday at 09:00 UTC, have the PepGPT prompt agent write "
                "the weekly executive commercial digest."
            ),
            enabled=True,
            triggers={
                "friday-morning": ScheduleRoutineTrigger(
                    cron_expression="0 9 * * 5",
                    time_zone="UTC",
                ),
            },
            action=InvokeAgentResponsesApiRoutineAction(
                agent_name=PROMPT_AGENT_NAME,
                input=WEEKLY_INPUT,
            ),
        )
        print(f"  created : {prompt.name}")
        print(f"  enabled : {prompt.enabled}")
        print("  trigger : Fridays 09:00 UTC  (cron '0 9 * * 5')")
        print(f"  action  : invoke_agent_responses_api -> {PROMPT_AGENT_NAME}")

        banner("All routines in this project")
        for r in client.beta.routines.list():
            print(f"  - {r.name:<32} enabled={r.enabled}")


if __name__ == "__main__":
    main()
