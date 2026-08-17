# Copyright (c) Microsoft. All rights reserved.

"""PepsiCo Retail Execution Ops agent — LangGraph on Foundry Hosted Agents.

A LangGraph ReAct agent built with `langchain.agents.create_agent` and hosted on
Microsoft Foundry over the **Responses** protocol using
`langchain_azure_ai.agents.hosting.ResponsesHostServer`.

The agent automates a recurring retail-execution process:

  1. Pull overnight out-of-stock (OOS) alerts for a region.
  2. Pull promotion compliance exceptions for the same region.
  3. Decide what actually needs action and open replenishment tasks.
  4. Return a short, prioritized brief for the field team.

The tools below return deterministic simulated data so the demo runs anywhere
without back-end dependencies. Swap them for real PepsiCo systems (SAP, retail
execution platform, Databricks) without changing the hosting or Routines wiring.
"""

from __future__ import annotations

import json
import os
import random
from datetime import datetime, timezone
from typing import Annotated

from azure.ai.projects import AIProjectClient
from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI

from langchain_azure_ai.agents.hosting import ResponsesHostServer

load_dotenv()

_AZURE_AI_SCOPE = "https://ai.azure.com/.default"

SYSTEM_PROMPT = """\
You are the PepsiCo Retail Execution Ops agent.

You run as an unattended automation: a Foundry Routine invokes you on a schedule,
so there is no human in the loop to answer follow-up questions. Never ask
clarifying questions - make reasonable assumptions and act.

Your job, every run:
1. Call `get_out_of_stock_alerts` for the requested region (default ALL).
2. Call `get_promo_compliance` for the same region.
3. Open replenishment tasks with `create_replenishment_task` for every
   out-of-stock alert that is HIGH severity, or MEDIUM severity at a store with
   a currently running promotion. Do not open tasks for anything else.
4. Produce the final brief.

Final brief format (keep it under 250 words, plain text, no markdown tables):

RETAIL EXECUTION BRIEF - <region> - <UTC date>
PRIORITY ACTIONS:   numbered list of the replenishment tasks you opened, each
                    with store, SKU, cases, and a one-line reason.
PROMO RISK:         promotions at risk because the promoted SKU is out of stock.
WATCH LIST:         issues you deliberately did not action, one line each.
SUMMARY:            one sentence a sales director can read on their phone.

Always take the date from the `as_of_utc` field returned by the tools. Never
invent a date.

Be specific and quantitative. Cite store IDs and SKU codes.
"""

# Deterministic per-day simulated data so demo runs are reproducible.
_REGIONS = ["NORTHEAST", "SOUTHEAST", "MIDWEST", "WEST"]
_SKUS = [
    ("PEP-CL-12OZ-12PK", "Pepsi Cola 12oz 12-pack"),
    ("LAY-CC-8OZ", "Lay's Classic 8oz"),
    ("GAT-FRT-32OZ", "Gatorade Fruit Punch 32oz"),
    ("DOR-NCH-9OZ", "Doritos Nacho Cheese 9.25oz"),
    ("MTD-DEW-2L", "Mountain Dew 2L"),
    ("QKR-OAT-18OZ", "Quaker Oats 18oz"),
]


def _rng(salt: str) -> random.Random:
    """Seed on the UTC date so a demo day is stable but days differ."""
    return random.Random(f"{datetime.now(timezone.utc):%Y-%m-%d}-{salt}")


def _stores_for(region: str) -> list[str]:
    prefix = region[:2].upper()
    return [f"{prefix}-{1000 + i}" for i in range(1, 9)]


@tool
def get_out_of_stock_alerts(
    region: Annotated[
        str, "Region to pull alerts for: NORTHEAST, SOUTHEAST, MIDWEST, WEST, or ALL."
    ] = "ALL",
) -> str:
    """Return overnight out-of-stock alerts from the retail execution platform."""
    region = (region or "ALL").upper()
    regions = _REGIONS if region == "ALL" else [region]
    alerts = []
    for reg in regions:
        if reg not in _REGIONS:
            return f"Unknown region '{reg}'. Valid regions: {', '.join(_REGIONS)}, ALL."
        rnd = _rng(f"oos-{reg}")
        for store in _stores_for(reg):
            if rnd.random() < 0.45:
                sku, desc = rnd.choice(_SKUS)
                alerts.append(
                    {
                        "store_id": store,
                        "region": reg,
                        "sku": sku,
                        "description": desc,
                        "shelf_qty": rnd.randint(0, 3),
                        "avg_daily_units": rnd.randint(8, 40),
                        "hours_out": rnd.randint(6, 72),
                        "severity": rnd.choice(["HIGH", "HIGH", "MEDIUM", "LOW"]),
                    }
                )
    return json.dumps(
        {
            "as_of_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "region": region,
            "alert_count": len(alerts),
            "alerts": alerts,
        }
    )


@tool
def get_promo_compliance(
    region: Annotated[
        str, "Region to check: NORTHEAST, SOUTHEAST, MIDWEST, WEST, or ALL."
    ] = "ALL",
) -> str:
    """Return active promotions and their in-store display compliance status."""
    region = (region or "ALL").upper()
    regions = _REGIONS if region == "ALL" else [region]
    promos = []
    for reg in regions:
        if reg not in _REGIONS:
            return f"Unknown region '{reg}'. Valid regions: {', '.join(_REGIONS)}, ALL."
        rnd = _rng(f"promo-{reg}")
        for store in _stores_for(reg):
            if rnd.random() < 0.5:
                sku, desc = rnd.choice(_SKUS)
                promos.append(
                    {
                        "store_id": store,
                        "region": reg,
                        "promo_id": f"PROMO-{rnd.randint(4000, 4999)}",
                        "sku": sku,
                        "description": desc,
                        "mechanic": rnd.choice(
                            ["2 for $7", "BOGO", "$1 off", "Endcap feature"]
                        ),
                        "display_compliant": rnd.random() < 0.7,
                        "ends_in_days": rnd.randint(1, 14),
                    }
                )
    return json.dumps(
        {
            "as_of_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "region": region,
            "promo_count": len(promos),
            "promotions": promos,
        }
    )


@tool
def create_replenishment_task(
    store_id: Annotated[str, "Store identifier, e.g. 'NO-1003'."],
    sku: Annotated[str, "SKU code to replenish, e.g. 'PEP-CL-12OZ-12PK'."],
    cases: Annotated[int, "Number of cases to ship on the next DSD route."],
    reason: Annotated[str, "Short justification recorded on the task."],
) -> str:
    """Open a replenishment task for the next direct-store-delivery route."""
    rnd = _rng(f"task-{store_id}-{sku}")
    task_id = f"RPL-{rnd.randint(100000, 999999)}"
    return json.dumps(
        {
            "task_id": task_id,
            "store_id": store_id,
            "sku": sku,
            "cases": cases,
            "reason": reason,
            "status": "OPEN",
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
    )


def _build_chat_model() -> ChatOpenAI:
    project_endpoint = os.environ["FOUNDRY_PROJECT_ENDPOINT"].rstrip("/")
    deployment = os.environ.get("AZURE_AI_MODEL_DEPLOYMENT_NAME", "gpt-4.1-mini")
    credential = DefaultAzureCredential()
    project = AIProjectClient(endpoint=project_endpoint, credential=credential)
    openai_client = project.get_openai_client()
    token_provider = get_bearer_token_provider(credential, _AZURE_AI_SCOPE)

    return ChatOpenAI(
        model=deployment,
        base_url=str(openai_client.base_url),
        api_key=token_provider,
    )


def main() -> None:
    graph = create_agent(
        _build_chat_model(),
        tools=[get_out_of_stock_alerts, get_promo_compliance, create_replenishment_task],
        system_prompt=SYSTEM_PROMPT,
    )

    port = int(os.environ.get("PORT", "8088"))
    ResponsesHostServer(graph).run(port=port)


if __name__ == "__main__":
    main()
