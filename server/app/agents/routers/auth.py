"""Auth shims for platform-embedded mode.

The agents frontend runs with ``IS_PLATFORM = true``, so it never shows its
own login screen — it trusts the surrounding ops session (the ``ivyea_ops_session``
cookie). The whole agents router is already gated by ops auth at mount time, so by
the time these handlers run the caller is authenticated. We only need to answer
the few status/identity probes the frontend's AuthContext may issue.
"""
from __future__ import annotations

from fastapi import APIRouter

from app.core.security import current_user

router = APIRouter()


@router.get("/status")
async def auth_status() -> dict:
    # Platform mode: setup is never needed and the user is already authenticated
    # via the ops cookie (enforced by the router-level dependency).
    return {"needsSetup": False, "isAuthenticated": True}


@router.get("/user")
async def auth_user() -> dict:
    cu = current_user.get() or {}
    username = cu.get("email") or cu.get("id") or "platform-user"
    return {"user": {"username": username, "id": cu.get("id")}}


@router.post("/logout")
async def auth_logout() -> dict:
    # Session lifecycle is owned by ops; nothing to tear down here.
    return {"success": True}
