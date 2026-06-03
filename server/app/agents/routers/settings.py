"""Settings API (mounted at ``/settings``) — port of routes/settings.js.

agents's own settings UI was largely removed ("去壳") in favor of ops config,
and Web Push was dropped from this rewrite — so:
  • credentials + notification-preferences persist as JSON in app_config
    (lightweight, no per-user tables);
  • push/* are graceful no-op stubs (push disabled) so useWebPush doesn't error;
  • api-keys returns an empty list (the agent API-key flow isn't exposed here).
"""
from __future__ import annotations

import json
import uuid
from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel

from app.agents.db import db_conn

router = APIRouter()


def _cfg_get_json(key: str, default):
    with db_conn() as conn:
        row = conn.execute("SELECT value FROM app_config WHERE key = ?", (key,)).fetchone()
    if not row:
        return default
    try:
        return json.loads(row["value"])
    except (ValueError, TypeError):
        return default


def _cfg_set_json(key: str, value) -> None:
    with db_conn() as conn:
        conn.execute(
            "INSERT INTO app_config(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, json.dumps(value, ensure_ascii=False)))


# --- credentials (provider API keys; secrets are never returned) ------------

_CRED_KEY = "agents_credentials"


@router.get("/credentials")
async def list_credentials() -> dict:
    creds = _cfg_get_json(_CRED_KEY, [])
    public = [{"id": c["id"], "provider": c.get("provider"), "name": c.get("name"),
               "enabled": c.get("enabled", True)} for c in creds]
    return {"success": True, "credentials": public}


class CredentialBody(BaseModel):
    provider: Optional[str] = None
    name: Optional[str] = None
    value: Optional[str] = None


@router.post("/credentials")
async def add_credential(body: CredentialBody) -> dict:
    creds = _cfg_get_json(_CRED_KEY, [])
    entry = {"id": str(uuid.uuid4()), "provider": body.provider, "name": body.name,
             "value": body.value, "enabled": True}
    creds.append(entry)
    _cfg_set_json(_CRED_KEY, creds)
    return {"success": True, "credential": {k: entry[k] for k in ("id", "provider", "name", "enabled")}}


@router.delete("/credentials/{credential_id}")
async def delete_credential(credential_id: str) -> dict:
    creds = [c for c in _cfg_get_json(_CRED_KEY, []) if c.get("id") != credential_id]
    _cfg_set_json(_CRED_KEY, creds)
    return {"success": True}


@router.patch("/credentials/{credential_id}/toggle")
async def toggle_credential(credential_id: str) -> dict:
    creds = _cfg_get_json(_CRED_KEY, [])
    for c in creds:
        if c.get("id") == credential_id:
            c["enabled"] = not c.get("enabled", True)
    _cfg_set_json(_CRED_KEY, creds)
    return {"success": True}


# --- notification preferences ----------------------------------------------

_NOTIF_KEY = "agents_notification_preferences"
_NOTIF_DEFAULT = {"enabled": False, "runFailed": True, "runStopped": True, "actionRequired": True}


@router.get("/notification-preferences")
async def get_notification_prefs() -> dict:
    return {"success": True, "preferences": _cfg_get_json(_NOTIF_KEY, dict(_NOTIF_DEFAULT))}


@router.put("/notification-preferences")
async def update_notification_prefs(body: dict) -> dict:
    prefs = {**_NOTIF_DEFAULT, **(body or {})}
    _cfg_set_json(_NOTIF_KEY, prefs)
    return {"success": True, "preferences": prefs}


# --- Web Push (dropped — graceful no-op stubs) ------------------------------

@router.get("/push/vapid-public-key")
async def vapid_public_key() -> dict:
    return {"publicKey": None, "enabled": False}


@router.post("/push/subscribe")
async def push_subscribe(body: dict = None) -> dict:
    return {"success": True, "enabled": False}


@router.post("/push/unsubscribe")
async def push_unsubscribe(body: dict = None) -> dict:
    return {"success": True}


# --- agent API keys (not exposed in platform mode) --------------------------

@router.get("/api-keys")
async def list_api_keys() -> dict:
    return {"success": True, "apiKeys": []}
