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
        "backend": "ops-native-ccui",
    }


@router.post("/system/update")
async def system_update() -> dict:
    # Updates are managed by the ops deployment, not from inside cloudcli.
    return {
        "success": False,
        "message": "Updates are managed by the ops-hub deployment; in-app update is disabled.",
    }
