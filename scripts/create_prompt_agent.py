"""Create the PepGPT-style **Prompt Agent** used by the weekly routine.

A prompt agent is fully managed by Foundry: a model deployment plus instructions
(and optionally tools). There is no container and no runtime to operate, which is
why PepsiCo already uses this shape today.

This is the agent the second Routine invokes, proving that Routines drive the
agents PepsiCo already has in production - not just new hosted ones.
"""

from __future__ import annotations

from azure.ai.projects.models import PromptAgentDefinition

from common import MODEL_DEPLOYMENT, PROMPT_AGENT_NAME, banner, get_client

INSTRUCTIONS = """\
You are the PepGPT Executive Digest agent for PepsiCo commercial leadership.

You are invoked unattended by a Foundry Routine on a weekly schedule. There is no
human available to answer questions, so never ask any - make defensible
assumptions and produce the finished artifact.

Write a weekly commercial digest for a PepsiCo sales director covering the four
US regions (Northeast, Southeast, Midwest, West). Unless the request supplies
figures, generate a realistic illustrative example and label it clearly as
"ILLUSTRATIVE DEMO DATA".

Structure the digest exactly as:

WEEKLY COMMERCIAL DIGEST - <week label>
1. HEADLINE          - one sentence on the week's commercial story.
2. REGIONAL SCORECARD - one line per region: volume vs plan, biggest mover.
3. EXECUTION RISKS    - up to three risks, each with a concrete owner action.
4. NEXT WEEK'S FOCUS  - three bullets, imperative voice.

Rules:
- Under 350 words total. Plain text, no markdown tables.
- Every claim carries a number.
- For <week label>, use a date only if one appears in the request. Otherwise
  write "current week" - never invent a specific date.
- Close with: "Generated automatically by PepGPT - Foundry Routine."
"""


def main() -> None:
    banner(f"Creating prompt agent: {PROMPT_AGENT_NAME}")
    client = get_client()

    with client:
        agent = client.agents.create_version(
            agent_name=PROMPT_AGENT_NAME,
            definition=PromptAgentDefinition(
                model=MODEL_DEPLOYMENT,
                instructions=INSTRUCTIONS,
                temperature=0.3,
            ),
            description="PepGPT weekly executive digest agent (invoked by a Foundry Routine).",
        )

    print(f"  name    : {agent.name}")
    print(f"  version : {agent.version}")
    print(f"  id      : {agent.id}")
    print()
    print("Prompt agent ready. It is now addressable by name from a Routine action.")


if __name__ == "__main__":
    main()
