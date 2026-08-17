# Run-of-show — PepsiCo demo

Target: ~12 minutes. Three beats — hosted agents, routines, prompt agents — ending on "this is the same surface for all of it."

Before the call:

```powershell
cd agents-routines-demo
.\.venv\Scripts\Activate
python scripts\show_runs.py      # confirm both routines exist and are enabled
```

Have two terminals open and the Foundry portal on the project's **Agents** blade.

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
az cognitiveservices account show -n aiservices76a3 -g rayankhoury -o table
az acr repository show-tags -n rayankhouryacr --repository pepsico/store-ops-agent -o table
python scripts\show_runs.py
```

---

## Beat 0 — The problem (30s, no screen)

> "You have a lot of recurring processes. Today automating one means someone builds a scheduler, hosts the agent somewhere, and wires up retries and logging. We want that to be a configuration, not a project."

---

## Beat 1 — Hosted Agents: Foundry as the runtime (4 min)

Show `hosted_agent/main.py`.

> "This is an ordinary LangGraph agent — `create_agent` with three tools that hit the retail execution system. Nothing Foundry-specific in the agent logic."

Scroll to the bottom:

```python
ResponsesHostServer(graph).run(port=port)
```

> "That one line is the whole integration. It exposes the graph over the Responses protocol, and Foundry handles conversation state, streaming, and session lifecycle."

Then show `scripts/deploy_hosted_agent.py`:

> "The container is built **in Azure** by ACR — nobody needs Docker on their laptop — and then registered as a hosted agent version. No cluster, no App Service, no scale rules. This is the runtime story for the LangGraph agents you want to move over."

Show the agent in the portal, and mention: `azd up` is the one-command version of the same thing.

---

## Beat 2 — Routines: automation without orchestration code (5 min)

Show `scripts/create_routines.py`.

> "A Routine is one trigger plus one action. Here the trigger is a cron schedule — weekdays 7am Eastern — and the action invokes the hosted agent **by name**. That's the entire automation. Foundry owns the scheduler, the retries, and the run history."

Nobody wants to wait until 7am, so fire it now:

```powershell
python scripts\dispatch.py --show-output
```

> "Same routine, same execution path, same run history — just triggered on demand."

While it runs, narrate what the agent is doing: pulling overnight out-of-stock alerts, cross-checking promo compliance, and opening replenishment tasks only where the rules say to.

Note on what you're seeing: the routine run record is the proof the automation fired. Foundry runs the agent under **its own identity**, so the response from that run isn't readable by you as the caller in preview — `--show-output` replays the same input against the same agent so the room sees the actual brief. If asked, say exactly that; it's a preview gap, not a design constraint.

When the brief prints, land the point:

> "Nobody wrote orchestration code. The scheduling, the retry policy, and the audit trail are the platform's job."

Then show the receipts:

```powershell
python scripts\show_runs.py
```

> "Every run is recorded — trigger, phase, timing, and the response id, so it links straight to the trace."

---

## Beat 3 — Routines drive Prompt Agents too (2 min)

This is the beat that matters most, because it covers what PepsiCo runs today.

Show `scripts/create_prompt_agent.py`:

> "This is a prompt agent — a model deployment plus instructions. No container, no runtime to operate. This is the shape you already have in PepGPT."

Then:

```powershell
python scripts\dispatch.py --prompt --show-output
```

> "Identical routine structure. The only difference is the agent name in the action."

Put the two side by side:

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

---

## Reset between runs

```powershell
python scripts\cleanup.py --yes
python scripts\deploy_hosted_agent.py
python scripts\create_prompt_agent.py
python scripts\create_routines.py
```
