"""Shared configuration and client helpers for the PepsiCo demo scripts."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from urllib.parse import urlparse

from azure.ai.projects import AIProjectClient
from azure.identity import DefaultAzureCredential
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent

load_dotenv(REPO_ROOT / ".env")

# Agent output contains characters (curly quotes, box drawing) that the default
# Windows console codepage cannot encode. Force UTF-8 so demo output is clean.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):  # pragma: no cover - non-standard stream
        pass


def _require(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        sys.exit(
            f"Missing required environment variable: {name}\n"
            f"Copy .env.example to .env and fill it in, or set it in your shell."
        )
    return value


# ── Foundry ──────────────────────────────────────────────────────────
PROJECT_ENDPOINT = _require("FOUNDRY_PROJECT_ENDPOINT").rstrip("/")
MODEL_DEPLOYMENT = os.environ.get("AZURE_AI_MODEL_DEPLOYMENT_NAME", "gpt-4.1-mini")

# ── Agent + routine names ────────────────────────────────────────────
HOSTED_AGENT_NAME = os.environ.get("HOSTED_AGENT_NAME", "pepsico-store-ops-agent")
PROMPT_AGENT_NAME = os.environ.get("PROMPT_AGENT_NAME", "pepsico-exec-digest-agent")

HOSTED_ROUTINE_NAME = os.environ.get("HOSTED_ROUTINE_NAME", "pepsico-daily-store-ops")
PROMPT_ROUTINE_NAME = os.environ.get("PROMPT_ROUTINE_NAME", "pepsico-weekly-exec-digest")

# ── Container build (Azure Container Registry, built in Azure) ───────
ACR_NAME = os.environ.get("ACR_NAME", "")
IMAGE_REPOSITORY = os.environ.get("IMAGE_REPOSITORY", "pepsico/store-ops-agent")
# Base tag. Each deploy appends a UTC timestamp so every build is an immutable
# image and therefore produces a genuinely new hosted-agent version.
IMAGE_TAG = os.environ.get("IMAGE_TAG", "v1")

# ── Azure control plane ──────────────────────────────────────────────
SUBSCRIPTION_ID = os.environ.get("AZURE_SUBSCRIPTION_ID", "")
RESOURCE_GROUP = os.environ.get("AZURE_RESOURCE_GROUP", "")
FOUNDRY_ACCOUNT_NAME = os.environ.get("FOUNDRY_ACCOUNT_NAME", "")
# .../api/projects/<project-name>
FOUNDRY_PROJECT_NAME = os.environ.get("FOUNDRY_PROJECT_NAME", "") or (
    urlparse(PROJECT_ENDPOINT).path.rstrip("/").rsplit("/", 1)[-1]
)


def get_client() -> AIProjectClient:
    """Return an AIProjectClient authenticated with DefaultAzureCredential."""
    return AIProjectClient(
        endpoint=PROJECT_ENDPOINT,
        credential=DefaultAzureCredential(),
    )


def banner(text: str) -> None:
    print()
    print("=" * 78)
    print(f"  {text}")
    print("=" * 78)
