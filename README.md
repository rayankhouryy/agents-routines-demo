# PepsiCo — Foundry Hosted Agents + Routines

A working, deployable demo of **workflow automation on Microsoft Foundry**:

1. A **LangGraph** agent deployed to **Foundry Hosted Agents** — Foundry is the runtime, so there is no cluster, no App Service, and no scheduler to operate.
2. A **Foundry Routine** that invokes that hosted agent on a schedule.
3. A **Foundry Routine** that invokes a **Prompt Agent** — the agent shape PepsiCo already runs in PepGPT today.

The point of the demo: **the same automation surface drives both agent types.** What you already have in PepGPT keeps working, and new LangGraph code gets a managed runtime — without writing orchestration or standing up a scheduler.

---

## The scenario

A recurring retail-execution process that runs every weekday morning, plus a weekly executive digest.

| | Agent | Runtime | Automated by |
|---|---|---|---|
| **Daily** | `pepsico-store-ops-agent` — LangGraph ReAct agent that reviews overnight out-of-stock alerts, cross-checks promo compliance, and opens replenishment tasks | **Hosted Agent** (container, built in Azure) | Routine `pepsico-daily-store-ops`, weekdays 07:00 ET |
| **Weekly** | `pepsico-exec-digest-agent` — PepGPT-style executive commercial digest writer | **Prompt Agent** (fully managed, no container) | Routine `pepsico-weekly-exec-digest`, Fridays 09:00 UTC |

The agent's tools return deterministic simulated retail data so the demo runs anywhere. Swap them for SAP / retail-execution / Databricks calls without touching the hosting or Routines wiring.

---

## What a Routine actually is

> **One trigger + one action.** Foundry owns the scheduler, the retries, and the run history.

```python
client.beta.routines.create_or_update(
    routine_name="pepsico-daily-store-ops",
    enabled=True,
    triggers={
        "weekday-morning": ScheduleRoutineTrigger(
            cron_expression="0 7 * * 1-5",
            time_zone="America/New_York",
        ),
    },
    action=InvokeAgentResponsesApiRoutineAction(
        agent_name="pepsico-store-ops-agent",   # <- hosted OR prompt agent, by name
        input="Run the daily retail execution review for ALL regions.",
    ),
)
```

That is the entire automation. The action references the agent **by name**, which is why pointing a routine at a prompt agent instead of a hosted agent is a one-line change.

**Triggers available:** `schedule` (cron, 5-minute minimum), `timer` (one-shot), `github_issue`, and `custom` (e.g. a Teams channel message).

---

## Repo layout

```
hosted_agent/          LangGraph agent hosted on Foundry (Responses protocol)
  main.py              create_agent(...) + ResponsesHostServer
  Dockerfile           built in Azure by ACR — no local Docker needed
  agent.yaml           hosted agent descriptor
scripts/
  common.py                 shared config + client
  deploy_hosted_agent.py    ACR build -> AcrPull grant -> register hosted agent
  create_prompt_agent.py    create the PepGPT prompt agent
  create_routines.py        create both routines
  dispatch.py               fire a routine now, wait, optionally show output
  invoke_agent.py           call an agent directly and print its output
  show_runs.py              routines and their run history
  cleanup.py                delete everything
demo/RUNBOOK.md        run-of-show for the customer call
```

---

## Prerequisites

- Python 3.10+
- Azure CLI, signed in (`az login`)
- A Foundry project in a **Routines-supported region** — East US, East US 2, West US, West US 2, West Central US, North Central US, Sweden Central, Japan East
- A model deployment in that project
- An Azure Container Registry — the image is built **in Azure**, so local Docker is not required

Routines is in **public preview** and requires `azure-ai-projects >= 2.4.0`.

---

## Setup

```powershell
git clone https://github.com/rayankhouryy/agents-routines-demo.git
cd agents-routines-demo

python -m venv .venv
.\.venv\Scripts\Activate
pip install -r requirements.txt

copy .env.example .env   # then fill it in
az login
```

`.env`:

```
FOUNDRY_PROJECT_ENDPOINT=https://<account>.services.ai.azure.com/api/projects/<project>
AZURE_AI_MODEL_DEPLOYMENT_NAME=gpt-4.1-mini
AZURE_SUBSCRIPTION_ID=<subscription-id>
AZURE_RESOURCE_GROUP=<resource-group>
FOUNDRY_ACCOUNT_NAME=<foundry-account-name>
ACR_NAME=<acr-name>
```

---

## Run it

```powershell
# 1. Build the container in Azure and register the LangGraph hosted agent
python scripts\deploy_hosted_agent.py

# 2. Create the PepGPT prompt agent
python scripts\create_prompt_agent.py

# 3. Create both routines
python scripts\create_routines.py

# 4. Fire them now instead of waiting for 07:00 ET
python scripts\dispatch.py --show-output            # -> hosted LangGraph agent
python scripts\dispatch.py --prompt --show-output   # -> prompt agent

# 5. Or invoke an agent directly, with no routine involved
python scripts\invoke_agent.py            # -> hosted LangGraph agent
python scripts\invoke_agent.py --prompt   # -> prompt agent

# 6. Show run history
python scripts\show_runs.py
```

> **Preview note — reading routine output.** A routine run records the `response_id` of the agent invocation, but that response is **not readable by the caller**. The agent runs under its own identity and its session is scoped to that identity, so `responses.retrieve(...)` returns `session_not_accessible` / `404`. Attaching a caller-created conversation to the action doesn't help either — the agent can't see it and the run fails with `conversation_not_found`.
>
> So the run record proves the automation fired, and `--show-output` replays the same input directly against the same agent to show what that run produced.

Tear down with `python scripts\cleanup.py`.

---

## Notes on the hosted agent

- **Images are tagged per build.** `deploy_hosted_agent.py` appends a UTC timestamp to `IMAGE_TAG`. Foundry de-duplicates agent versions by definition, so reusing a mutable tag like `:v1` silently keeps the old code running.
- **A hosted agent runs under its own Entra identity**, not yours. Each version gets a new one, so the deploy script grants it `Cognitive Services OpenAI User` on the Foundry account *and* project after every deploy. Allow ~30–60s for RBAC to propagate before the first call.
- **`FOUNDRY_PROJECT_ENDPOINT` is injected by the platform.** `FOUNDRY_*` and `AGENT_*` environment variable names are reserved and rejected if you set them yourself.
- **Hosted agents are called on their own endpoint** — `{project-endpoint}/agents/{name}/endpoint/protocols/openai` with `api-version=v1` — not via `agent_reference` on the project endpoint. Prompt agents use the project endpoint with `agent_reference`. `invoke_agent.py` handles both.

---

## How the pieces fit

```
                    ┌──────────────────────────────────────────┐
                    │            Microsoft Foundry             │
                    │                                          │
  cron 0 7 * * 1-5  │   Routine: pepsico-daily-store-ops       │
  ─────────────────►│      trigger: schedule                   │
                    │      action:  invoke_agent_responses_api ├──┐
                    │                                          │  │
  cron 0 9 * * 5    │   Routine: pepsico-weekly-exec-digest    │  │
  ─────────────────►│      trigger: schedule                   │  │
                    │      action:  invoke_agent_responses_api ├──┼──┐
                    │                                          │  │  │
                    │   ┌──────────────────────────────────┐   │  │  │
                    │   │ HOSTED AGENT                     │◄──┼──┘  │
                    │   │ pepsico-store-ops-agent          │   │     │
                    │   │ LangGraph + ResponsesHostServer  │   │     │
                    │   │ container image from ACR         │   │     │
                    │   └──────────────────────────────────┘   │     │
                    │                                          │     │
                    │   ┌──────────────────────────────────┐   │     │
                    │   │ PROMPT AGENT                     │◄──┼─────┘
                    │   │ pepsico-exec-digest-agent        │   │
                    │   │ model + instructions, no runtime │   │
                    │   └──────────────────────────────────┘   │
                    └──────────────────────────────────────────┘
```

Foundry records every execution — trigger, phase, timing, and the response id of the agent invocation — in the routine's run history (`scripts/show_runs.py`).

---

## Deploying the hosted agent with `azd` instead

The scripted path above uses ACR + the SDK so it is fully reproducible and CI-friendly. The `azd` path is the shortest interactive route and is what the product docs lead with:

```bash
azd ai agent init -m https://github.com/microsoft-foundry/foundry-samples/blob/main/samples/python/hosted-agents/langgraph/responses/01-langgraph-chat/agent.manifest.yaml
azd up
```

Requires `azd` 1.31+ and the `azure.ai.agents` extension (`azd extension install azure.ai.agents`).

---

## References

- [Routines concepts](https://learn.microsoft.com/en-us/azure/foundry/agents/concepts/routines)
- [Use routines](https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/use-routines)
- [Hosted agents](https://learn.microsoft.com/en-us/azure/foundry/agents/concepts/hosted-agents)
- [Deploy a hosted agent](https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/deploy-hosted-agent)
- [foundry-samples: LangGraph hosted agents](https://github.com/microsoft-foundry/foundry-samples/tree/main/samples/python/hosted-agents/langgraph)