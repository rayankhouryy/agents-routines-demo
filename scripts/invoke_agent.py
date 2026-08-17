"""Invoke an agent directly through the Responses API.

Routines prove the *automation*; this script shows the *output*. Use it to test
an agent before wiring a routine to it, and to display what a scheduled run
actually produces.

The two agent kinds are reached differently:

* **prompt agent**  - call the project's OpenAI endpoint and pass an
  `agent_reference` in the body.
* **hosted agent**  - call the agent's own endpoint,
  `{project}/agents/{name}/endpoint/protocols/openai`.

This script detects the kind and routes accordingly, so the same command works
for both.

Usage:
    python scripts/invoke_agent.py                    # hosted LangGraph agent
    python scripts/invoke_agent.py --prompt           # PepGPT prompt agent
    python scripts/invoke_agent.py --agent <name>
    python scripts/invoke_agent.py --input "..."
"""

from __future__ import annotations

import argparse
import time

from azure.identity import DefaultAzureCredential
from openai import OpenAI

from common import (
    HOSTED_AGENT_NAME,
    MODEL_DEPLOYMENT,
    PROJECT_ENDPOINT,
    PROMPT_AGENT_NAME,
    banner,
    get_client,
)

_AZURE_AI_SCOPE = "https://ai.azure.com/.default"
HOSTED_AGENT_API_VERSION = "v1"

HOSTED_INPUT = (
    "Run the daily retail execution review for ALL regions. Open replenishment "
    "tasks per your operating rules and return the prioritized brief."
)

PROMPT_INPUT = (
    "Produce this week's PepsiCo executive commercial digest for the four US "
    "regions. Use illustrative demo data and label it as such."
)


def agent_kind(client, agent_name: str) -> str:
    """Return 'hosted' or 'prompt' for the agent's latest version."""
    details = client.agents.get(agent_name).as_dict()
    return details.get("versions", {}).get("latest", {}).get("definition", {}).get("kind", "")


def invoke_hosted(agent_name: str, text: str):
    """Hosted agents are reachable only on their own agent endpoint."""
    token = DefaultAzureCredential().get_token(_AZURE_AI_SCOPE).token
    openai_client = OpenAI(
        base_url=f"{PROJECT_ENDPOINT}/agents/{agent_name}/endpoint/protocols/openai",
        api_key=token,
        default_query={"api-version": HOSTED_AGENT_API_VERSION},
    )
    return openai_client.responses.create(input=text, model=MODEL_DEPLOYMENT)


def invoke_prompt(client, agent_name: str, text: str):
    """Prompt agents are invoked on the project endpoint via agent_reference."""
    return client.get_openai_client().responses.create(
        model=MODEL_DEPLOYMENT,
        input=text,
        extra_body={"agent_reference": {"type": "agent_reference", "name": agent_name}},
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Invoke a Foundry agent directly.")
    parser.add_argument("--prompt", action="store_true", help="Use the prompt agent.")
    parser.add_argument("--agent", help="Invoke a specific agent by name.")
    parser.add_argument("--input", help="Override the input text.")
    args = parser.parse_args()

    agent_name = args.agent or (PROMPT_AGENT_NAME if args.prompt else HOSTED_AGENT_NAME)
    text = args.input or (PROMPT_INPUT if args.prompt else HOSTED_INPUT)

    client = get_client()
    with client:
        kind = agent_kind(client, agent_name)
        banner(f"Invoking {kind or 'unknown'} agent: {agent_name}")
        print(f"  input: {text}\n")

        started = time.time()
        if kind == "hosted":
            response = invoke_hosted(agent_name, text)
        else:
            response = invoke_prompt(client, agent_name, text)
        elapsed = time.time() - started

        banner("Agent output")
        print(response.output_text)
        print()
        print(f"  response id : {response.id}")
        print(f"  elapsed     : {elapsed:.1f}s")


if __name__ == "__main__":
    main()
