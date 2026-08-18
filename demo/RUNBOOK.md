# Run-of-show — PepsiCo demo

Target: ~12 minutes. Three beats — hosted agents, routines, prompt agents — ending on "this is the same surface for all of it."

**Drive the demo from the Foundry portal.** It fires routines with **Test run** and shows the run output when you open a response ID — which the SDK can't do in preview. Keep the code in a second window for the "here's what created this" moments.

## 10 minutes before the call

```powershell
cd agents-routines-demo
.\.venv\Scripts\Activate
python scripts\show_runs.py      # both routines exist and are enabled
python scripts\invoke_agent.py   # warms the hosted container so the live run is fast
```

Then, in the portal (https://ai.azure.com → project **project76a3**):

1. Open **Routines** → `pepsico-daily-store-ops` → **Test run**, let it reach **Completed**, and click the **response ID** to confirm the run detail renders the output. Do this once beforehand — it's the only step you haven't personally clicked.
2. Leave three tabs open: **Agents**, `pepsico-daily-store-ops`, `pepsico-weekly-exec-digest`.

Optional backup, in case the portal is slow or a blade misbehaves:

```powershell
python webapp\app.py             # http://127.0.0.1:8000 — same story, local UI
```

### Portal links (this deployment)

| What | Where |
|---|---|
| Agents (hosted + prompt), Routines | [Foundry portal](https://ai.azure.com/) → project **project76a3** → **Agents** / **Routines** |
| Foundry account resource | [portal.azure.com → aiservices76a3](https://portal.azure.com/#@/resource/subscriptions/a71e73e0-6235-4a56-ba1b-f21ef82062dd/resourceGroups/rayankhoury/providers/Microsoft.CognitiveServices/accounts/aiservices76a3/overview) |
| Container image the hosted agent runs | [ACR rayankhouryacr → Repositories](https://portal.azure.com/#@/resource/subscriptions/a71e73e0-6235-4a56-ba1b-f21ef82062dd/resourceGroups/rayankhoury/providers/Microsoft.ContainerRegistry/registries/rayankhouryacr/repository) → `pepsico/store-ops-agent` |
| The Azure-side container builds | [ACR → Tasks / Runs](https://portal.azure.com/#@/resource/subscriptions/a71e73e0-6235-4a56-ba1b-f21ef82062dd/resourceGroups/rayankhoury/providers/Microsoft.ContainerRegistry/registries/rayankhouryacr/taskRuns) |
| Agent identity role assignments | Foundry account → **Access control (IAM)** → Role assignments → `Cognitive Services OpenAI User` |

CLI equivalents if the portal is slow:

```powershell
python scripts\show_runs.py
python scripts\dispatch.py --show-output            # hosted
python scripts\dispatch.py --prompt --show-output   # prompt
```

---

## Beat 0 — The problem (30s, no screen)

> "You have a lot of recurring processes. Today, automating one means someone builds a scheduler, hosts the agent somewhere, and wires up retries and logging. We want that to be a configuration, not a project."

---

## Beat 1 — Hosted Agents: Foundry as the runtime (4 min)

**Do:** open `hosted_agent/main.py` in your editor.

> "This is an ordinary LangGraph agent — `create_agent` with three tools that hit the retail execution system. Nothing Foundry-specific in the agent logic."

**Do:** scroll to the last line.

```python
ResponsesHostServer(graph).run(port=port)
```

> "That one line is the whole integration. It exposes the graph over the Responses protocol, and Foundry handles conversation state, streaming, and session lifecycle."

**Do:** open `scripts/deploy_hosted_agent.py`.

> "The container is built **in Azure** by ACR — nobody needs Docker on their laptop — then registered as a hosted agent version. No cluster, no App Service, no scale rules. This is the runtime story for the LangGraph agents you want to move over. `azd up` is the one-command version of the same thing."

**Do:** switch to the portal → **Agents** → click `pepsico-store-ops-agent`.

> "Here it is running in the project — kind is *hosted*, version 2, and that's the exact container image out of our registry."

---

## Beat 2 — Routines: automation without orchestration code (5 min)

**Do:** portal → **Routines** → open `pepsico-daily-store-ops`.

> "A Routine is one trigger plus one action. The trigger is a cron schedule — weekdays 7am Eastern — and the action invokes the hosted agent **by name**. That's the entire automation. Foundry owns the scheduler, the retries, and the run history."

**Do:** show `scripts/create_routines.py` for two seconds so they see it's ~10 lines of config.

**Do:** back in the portal, click **Test run**.

> "Nobody wants to wait until 7am, so we'll fire it now — same routine, same execution path, same run history."

While it moves **Queued → Completed**, narrate: pulling overnight out-of-stock alerts, cross-checking promo compliance, opening replenishment tasks only where the rules say to.

**Do:** click the **response ID** on the new row to open the run and show the brief.

> "Nobody wrote orchestration code. The scheduling, the retry policy, and the audit trail are the platform's job."

**Do:** scroll the runs table.

> "Every run is recorded — when it triggered, how long it took, and its state — so this is auditable from day one."

---

## Beat 3 — Routines drive Prompt Agents too (2 min)

This is the beat that matters most, because it covers what PepsiCo runs today.

**Do:** portal → **Agents** → click `pepsico-exec-digest-agent`.

> "This is a prompt agent — a model deployment plus instructions. No container, nothing to operate. This is the shape you already have in PepGPT."

**Do:** **Routines** → `pepsico-weekly-exec-digest` → **Test run** → open the response ID.

> "Identical routine structure. The only difference is the agent name in the action."

**Do:** show the two lines side by side.

```python
action=InvokeAgentResponsesApiRoutineAction(agent_name="pepsico-store-ops-agent")     # hosted LangGraph
action=InvokeAgentResponsesApiRoutineAction(agent_name="pepsico-exec-digest-agent")   # prompt agent
```

> "So you don't have to migrate anything to start automating. Your existing prompt agents become scheduled workflows today, and when a process needs real code, LangGraph on hosted agents is the same one-line change."

---

## Beat 4 — What this means for the next PepGPT iteration (1 min)

> "You wanted to give your users the ability to create and complete workflows. The building block is a routine: pick a trigger, pick an agent, give it an input. That's a form in PepGPT, not a platform project. And because triggers also include events — a new Teams message, a GitHub issue — the same surface covers event-driven processes, not just scheduled ones."

---

## Likely questions

**How often can routines run?** Cron schedules, minimum 5-minute interval. Also one-shot timers and event triggers.

**What if a run fails?** Foundry retries — 3 attempts with exponential backoff — and the failure is recorded in run history with error type and message.

**Multi-step workflows with branching or approvals?** A routine is deliberately one trigger + one action. For branching, multi-agent handoffs, and approvals, use **Workflows**, and let a routine be the thing that starts the workflow.

**Does it work with our existing agents?** Yes — that's Beat 3. Prompt agents and hosted agents are both referenced by name.

**Is this GA?** Routines is public preview. Requires `azure-ai-projects >= 2.4.0` and a supported region.

**Where does our data go?** Everything runs inside the Foundry project in your subscription and region.

**Can we see the output of a scheduled run?** In the portal, yes — open the response ID on the run. Programmatically it's a preview gap: the agent runs under its own identity and its session isn't readable by the caller, so `scripts/dispatch.py --show-output` replays the same input against the same agent to show what a run produces.

---

## If something goes wrong mid-demo

| Symptom | Do this |
|---|---|
| **Test run** sits in Queued | Keep talking; it's ~5–20s. If >60s, switch to `python scripts\dispatch.py --show-output`. |
| Hosted agent is slow on first call | It's a cold container — that's why you warm it beforehand. Say so; it's honest and expected. |
| Portal blade won't load | `python webapp\app.py` → http://127.0.0.1:8000, same story with live data. |
| A run shows **Failed** | Open it and read the error out loud, then re-run. Retries are part of the value story. |

---

## Reset between runs

```powershell
python scripts\cleanup.py --yes
python scripts\deploy_hosted_agent.py
python scripts\create_prompt_agent.py
python scripts\create_routines.py
```
