"""Deploy the LangGraph agent to Microsoft Foundry as a **Hosted Agent**.

Container path, built entirely in Azure:

  1. `az acr build` streams the build context to Azure Container Registry and
     builds the image on ACR compute - no local Docker daemon required.
  2. The Foundry account's managed identity is granted `AcrPull` on the registry
     so the hosting service can pull the image.
  3. `agents.create_version(...)` registers a new version of the hosted agent
     pointing at that image, exposing the Responses protocol.

After this, the agent is addressable **by name** - which is exactly how a
Routine action references it.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone

from azure.ai.projects.models import (
    ContainerConfiguration,
    HostedAgentDefinition,
    ProtocolVersionRecord,
)

from common import (
    ACR_NAME,
    FOUNDRY_ACCOUNT_NAME,
    FOUNDRY_PROJECT_NAME,
    HOSTED_AGENT_NAME,
    IMAGE_REPOSITORY,
    IMAGE_TAG,
    MODEL_DEPLOYMENT,
    REPO_ROOT,
    RESOURCE_GROUP,
    SUBSCRIPTION_ID,
    banner,
    get_client,
)

AGENT_DIR = REPO_ROOT / "hosted_agent"


def build_tag() -> str:
    """Unique, immutable tag per build.

    Foundry de-duplicates hosted-agent versions by definition. Reusing a mutable
    tag such as ``:v1`` means a rebuilt image does **not** produce a new agent
    version, so the old code keeps serving. Timestamping the tag guarantees each
    deploy rolls out the code you just built.
    """
    return f"{IMAGE_TAG}-{datetime.now(timezone.utc):%Y%m%d%H%M%S}"


def _resolve(program: str) -> str:
    """Resolve an executable, tolerating Windows .cmd/.bat shims such as az.cmd."""
    found = shutil.which(program)
    if not found:
        sys.exit(f"Could not find '{program}' on PATH. Install the Azure CLI and retry.")
    return found


def _run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    print(f"  $ {' '.join(cmd)}")
    resolved = [_resolve(cmd[0]), *cmd[1:]]
    # az streams ACR build logs containing non-cp1252 glyphs; force UTF-8 so the
    # CLI does not crash on Windows consoles.
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
    return subprocess.run(
        resolved, check=False, text=True, encoding="utf-8", errors="replace", env=env, **kwargs
    )


def _az_json(cmd: list[str]):
    proc = _run(cmd, capture_output=True)
    if proc.returncode != 0:
        sys.exit(f"Command failed:\n{proc.stderr}")
    return json.loads(proc.stdout) if proc.stdout.strip() else None


def build_image(tag: str) -> str:
    """Build the agent container image on ACR (remote build, no local Docker)."""
    banner(f"1/3  Building container image in Azure ({ACR_NAME})")
    if not ACR_NAME:
        sys.exit("ACR_NAME is not set. Add it to .env.")

    login_server = _az_json(
        ["az", "acr", "show", "-n", ACR_NAME, "--query", "loginServer", "-o", "json"]
    )
    image = f"{login_server}/{IMAGE_REPOSITORY}:{tag}"

    proc = _run(
        [
            "az", "acr", "build",
            "--registry", ACR_NAME,
            "--image", f"{IMAGE_REPOSITORY}:{tag}",
            "--file", "Dockerfile",
            # --no-logs: the build still runs (and is waited on) in Azure, but the
            # CLI does not stream build logs. Streaming crashes on Windows consoles
            # because the Azure CLI's colorama writer cannot encode the log glyphs
            # in cp1252.
            "--no-logs",
            ".",
        ],
        cwd=str(AGENT_DIR),
        capture_output=True,
    )
    print((proc.stdout or "").strip())
    if proc.returncode != 0:
        print(proc.stderr or "")
        sys.exit("ACR build failed.")

    print(f"\n  Image built in Azure: {image}")
    return image


def grant_acr_pull() -> None:
    """Give the Foundry account's managed identity permission to pull the image."""
    banner("2/3  Granting AcrPull to the Foundry account identity")
    if not (FOUNDRY_ACCOUNT_NAME and RESOURCE_GROUP and SUBSCRIPTION_ID):
        print("  Skipped - FOUNDRY_ACCOUNT_NAME / AZURE_RESOURCE_GROUP / "
              "AZURE_SUBSCRIPTION_ID not all set.")
        return

    principal_id = _az_json([
        "az", "cognitiveservices", "account", "show",
        "-n", FOUNDRY_ACCOUNT_NAME, "-g", RESOURCE_GROUP,
        "--query", "identity.principalId", "-o", "json",
    ])
    if not principal_id:
        print("  Foundry account has no system-assigned identity; enabling one.")
        _run([
            "az", "resource", "update",
            "--ids",
            f"/subscriptions/{SUBSCRIPTION_ID}/resourceGroups/{RESOURCE_GROUP}"
            f"/providers/Microsoft.CognitiveServices/accounts/{FOUNDRY_ACCOUNT_NAME}",
            "--set", "identity.type=SystemAssigned",
        ], capture_output=True)
        time.sleep(10)
        principal_id = _az_json([
            "az", "cognitiveservices", "account", "show",
            "-n", FOUNDRY_ACCOUNT_NAME, "-g", RESOURCE_GROUP,
            "--query", "identity.principalId", "-o", "json",
        ])

    acr_id = _az_json(["az", "acr", "show", "-n", ACR_NAME, "--query", "id", "-o", "json"])
    proc = _run([
        "az", "role", "assignment", "create",
        "--assignee-object-id", str(principal_id),
        "--assignee-principal-type", "ServicePrincipal",
        "--role", "AcrPull",
        "--scope", str(acr_id),
    ], capture_output=True)
    if proc.returncode == 0:
        print("  AcrPull granted.")
    elif "RoleAssignmentExists" in (proc.stderr or "") + (proc.stdout or ""):
        print("  AcrPull already assigned.")
    else:
        print(f"  Warning: could not assign AcrPull:\n{proc.stderr}")


def grant_model_access(agent) -> None:
    """Let the agent's own managed identity call the project's model deployment.

    A hosted agent runs under its own Entra identity, not the caller's. Without
    this role it starts fine but every model call fails with PermissionDenied.
    Each new agent version gets a **new** identity, so this runs on every deploy.
    The role is granted at both the account and the project scope - the project
    scope is what the agent's data-plane calls are actually authorized against.
    """
    banner("3b/3  Granting the agent identity access to the model")
    identity = (agent.as_dict().get("instance_identity") or {})
    principal_id = identity.get("principal_id")
    if not principal_id:
        print("  Skipped - agent has no instance identity yet.")
        return
    if not (FOUNDRY_ACCOUNT_NAME and RESOURCE_GROUP and SUBSCRIPTION_ID):
        print("  Skipped - Azure control-plane settings not all present in .env.")
        return

    account_scope = (
        f"/subscriptions/{SUBSCRIPTION_ID}/resourceGroups/{RESOURCE_GROUP}"
        f"/providers/Microsoft.CognitiveServices/accounts/{FOUNDRY_ACCOUNT_NAME}"
    )
    scopes = [account_scope]
    if FOUNDRY_PROJECT_NAME:
        scopes.append(f"{account_scope}/projects/{FOUNDRY_PROJECT_NAME}")

    for scope in scopes:
        proc = _run([
            "az", "role", "assignment", "create",
            "--assignee-object-id", principal_id,
            "--assignee-principal-type", "ServicePrincipal",
            "--role", "Cognitive Services OpenAI User",
            "--scope", scope,
        ], capture_output=True)
        combined = (proc.stderr or "") + (proc.stdout or "")
        if proc.returncode == 0:
            print(f"  Granted 'Cognitive Services OpenAI User' at {scope.rsplit('/', 2)[-2]}"
                  f"/{scope.rsplit('/', 1)[-1]}.")
        elif "RoleAssignmentExists" in combined:
            print("  Role already assigned at this scope.")
        else:
            print(f"  Warning: could not assign the role at {scope}:\n{proc.stderr}")
    print("  Note: RBAC can take ~30-60s to propagate before the first call succeeds.")


def register_agent(image: str) -> None:
    """Register a new version of the hosted agent pointing at the image."""
    banner(f"3/3  Registering hosted agent version: {HOSTED_AGENT_NAME}")
    client = get_client()

    with client:
        agent = client.agents.create_version(
            agent_name=HOSTED_AGENT_NAME,
            definition=HostedAgentDefinition(
                cpu="1",
                memory="2Gi",
                container_configuration=ContainerConfiguration(image=image),
                protocol_versions=[
                    ProtocolVersionRecord(protocol="responses", version="1.0.0"),
                ],
                environment_variables={
                    # FOUNDRY_PROJECT_ENDPOINT is injected by the platform at
                    # runtime; FOUNDRY_* and AGENT_* names are reserved.
                    "AZURE_AI_MODEL_DEPLOYMENT_NAME": MODEL_DEPLOYMENT,
                },
            ),
            description="PepsiCo retail execution ops agent (LangGraph, Responses protocol).",
        )

        print(f"  name    : {agent.name}")
        print(f"  version : {agent.version}")
        print(f"  id      : {agent.id}")

        grant_model_access(agent)

    print()
    print("Hosted agent registered. A Routine can now invoke it by name.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--tag",
        default=None,
        help="Container image tag. Defaults to a timestamped tag so every deploy "
             "produces a new, immutable hosted-agent version.",
    )
    args = parser.parse_args()

    tag = args.tag or build_tag()
    image = build_image(tag)
    grant_acr_pull()
    register_agent(image)


if __name__ == "__main__":
    main()
