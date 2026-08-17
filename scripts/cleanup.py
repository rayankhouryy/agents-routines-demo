"""Delete everything this demo created: routines, prompt agent, hosted agent.

Usage:
    python scripts/cleanup.py            # prompt before deleting
    python scripts/cleanup.py --yes      # no confirmation
"""

from __future__ import annotations

import argparse

from common import (
    HOSTED_AGENT_NAME,
    HOSTED_ROUTINE_NAME,
    PROMPT_AGENT_NAME,
    PROMPT_ROUTINE_NAME,
    banner,
    get_client,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Tear down the PepsiCo demo resources.")
    parser.add_argument("--yes", action="store_true", help="Skip confirmation.")
    args = parser.parse_args()

    targets = (
        f"  routines : {HOSTED_ROUTINE_NAME}, {PROMPT_ROUTINE_NAME}\n"
        f"  agents   : {HOSTED_AGENT_NAME}, {PROMPT_AGENT_NAME}"
    )
    banner("Cleanup")
    print(targets)

    if not args.yes:
        if input("\nDelete these? [y/N] ").strip().lower() not in {"y", "yes"}:
            print("Aborted.")
            return

    client = get_client()
    with client:
        for name in (HOSTED_ROUTINE_NAME, PROMPT_ROUTINE_NAME):
            try:
                client.beta.routines.delete(name)
                print(f"  deleted routine {name}")
            except Exception as exc:  # noqa: BLE001
                print(f"  skip routine {name}: {exc}")

        for name in (HOSTED_AGENT_NAME, PROMPT_AGENT_NAME):
            try:
                client.agents.delete(name)
                print(f"  deleted agent {name}")
            except Exception as exc:  # noqa: BLE001
                print(f"  skip agent {name}: {exc}")

    print("\nDone.")


if __name__ == "__main__":
    main()
