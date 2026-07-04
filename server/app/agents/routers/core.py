"""Misc top-level endpoints (health, and later browse-filesystem etc.)."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
async def health() -> dict:
    return {
        "status": "ok",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "backend": "ops-native-agents",
    }


@router.post("/system/update")
async def system_update() -> dict:
    # Updates are managed by the ops deployment, not from inside agents.
    return {
        "success": False,
        "message": "Updates are managed by the IvyeaOps deployment; in-app update is disabled.",
    }


# Provider ids the native agents UI can actually open a chat with (mirrors the
# hardcoded set in ProviderSelectionEmptyState.tsx / providers.py _PROVIDER_BIN).
# We intersect the registry catalog with this so the deep-analysis picker never
# offers an agent the chat view can't drive (e.g. kiro).
_NATIVE_PROVIDERS = {"claude", "codex", "cursor", "gemini", "opencode", "hermes", "agy", "ivyea"}


@router.get("/catalog")
async def agent_catalog() -> dict:
    """Lightweight agent catalog for external pickers (e.g. the market-research
    "深入分析" panel).

    Replaces the decommissioned agent_hub ``GET /api/agents`` endpoint. Reads the
    persisted registry projection (cheap) and returns only agents that are both
    enabled (binary found) and openable by the native chat view.
    """
    from app.services import agent_registry

    agents = [
        {
            "id": a.get("id", ""),
            "display_name": a.get("display_name") or a.get("id", ""),
            "default_model": a.get("default_model"),
            "enabled": bool(a.get("enabled")),
        }
        for a in agent_registry.list_agents()
        if a.get("enabled") and a.get("id") in _NATIVE_PROVIDERS
    ]
    return {"agents": agents}
