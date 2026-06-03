"""Provider info routes (mounted at ``/providers``) — auth status, models,
skills, and MCP servers, port of the provider routes in claudecodeui's
provider.routes.ts.

claude gets a real auth/credential check and the real model catalog (port of
claude-auth.provider.ts / claude-models.provider.ts). Other providers
(codex / cursor / gemini / opencode / hermes / agy) get a best-effort
"is the CLI installed" status and a minimal model list so the frontend's
provider panel renders; full driving for non-claude providers is incremental.
Skills/MCP return empty (stub) so the UI doesn't 404.
"""
from __future__ import annotations

import json
import os
import shutil
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()

# provider id -> CLI binary name used for the install check.
_PROVIDER_BIN = {
    "claude": "claude", "codex": "codex", "cursor": "cursor-agent",
    "gemini": "gemini", "opencode": "opencode", "hermes": "hermes", "agy": "antigravity",
}

_CLAUDE_MODELS = {
    "OPTIONS": [
        {"value": "default", "label": "Default (recommended)",
         "description": "Use the default model · $5/$25 per Mtok"},
        {"value": "sonnet", "label": "Sonnet", "description": "Best for everyday tasks · $3/$15 per Mtok"},
        {"value": "sonnet[1m]", "label": "Sonnet (1M context)", "description": "For long sessions · $3/$15 per Mtok"},
        {"value": "haiku", "label": "Haiku", "description": "Fastest for quick answers · $1/$5 per Mtok"},
    ],
    "DEFAULT": "default",
}
_DEFAULT_MODELS = {"OPTIONS": [{"value": "default", "label": "Default"}], "DEFAULT": "default"}


def _opts(values: list[str]) -> dict:
    return {"OPTIONS": [{"value": v, "label": v} for v in values], "DEFAULT": values[0]}


# agents provider id -> ops agent_registry agent id. For these we return the
# REAL configured/live model list (claude ~/.claude/settings, hermes
# ~/.hermes/config.yaml, codex its config) the user already maintains, instead
# of a hardcoded guess.
_PROVIDER_TO_AGENT = {"claude": "claude", "codex": "codex", "hermes": "hermes", "agy": "antigravity"}


def _agent_models(provider: str) -> Optional[dict]:
    agent_id = _PROVIDER_TO_AGENT.get(provider)
    if not agent_id:
        return None
    try:
        from app.services import agent_session_service as svc
        for a in svc.list_agents_db():
            if a.get("id") == agent_id and a.get("models"):
                models = [m for m in a["models"] if isinstance(m, str)]
                if not models:
                    return None
                default = a.get("default_model") or models[0]
                if default not in models:
                    models = [default] + models
                return {"OPTIONS": [{"value": m, "label": m} for m in models], "DEFAULT": default}
    except Exception:
        pass
    return None


# Real model catalogs for the providers we actually drive (mirrors ops
# agent_registry static_models). Others fall back to a single "default".
_PROVIDER_MODELS = {
    "claude": _CLAUDE_MODELS,
    "hermes": _opts(["default", "gpt-5.5", "gpt-5.4", "anthropic/claude-sonnet-4.6",
                     "anthropic/claude-opus-4.7", "anthropic/deepseek-3.2",
                     "anthropic/qwen3-coder-next", "mimo-v2.5-pro", "mimo-v2.5"]),
    "codex": _opts(["gpt-5.5", "gpt-5", "gpt-5-codex", "o3", "o4-mini", "codex-mini"]),
}


def _ok(data) -> dict:
    return {"success": True, "data": data}


def _which(bin_name: str) -> bool:
    search = ":".join([os.path.expanduser("~/.hermes/node/bin"), os.environ.get("PATH", "")])
    return shutil.which(bin_name, path=search) is not None


def _claude_credentials() -> dict:
    """Mirror ClaudeProviderAuth.checkCredentials priority order."""
    if (os.environ.get("ANTHROPIC_API_KEY") or "").strip():
        return {"authenticated": True, "email": "API Key Auth", "method": "api_key"}
    # ~/.claude/settings.json env block
    try:
        settings = json.loads((Path.home() / ".claude" / "settings.json").read_text(encoding="utf-8"))
        env = settings.get("env") if isinstance(settings.get("env"), dict) else {}
        if (env.get("ANTHROPIC_API_KEY") or "").strip():
            return {"authenticated": True, "email": "API Key Auth", "method": "api_key"}
        if (env.get("ANTHROPIC_AUTH_TOKEN") or "").strip():
            return {"authenticated": True, "email": "Configured via settings.json", "method": "api_key"}
    except (OSError, ValueError):
        pass
    # ~/.claude/.credentials.json -> claudeAiOauth.accessToken
    try:
        creds = json.loads((Path.home() / ".claude" / ".credentials.json").read_text(encoding="utf-8"))
        oauth = creds.get("claudeAiOauth") if isinstance(creds.get("claudeAiOauth"), dict) else {}
        token = (oauth.get("accessToken") or "").strip()
        if token:
            expires_at = oauth.get("expiresAt")
            email = creds.get("email") or creds.get("user")
            if not isinstance(expires_at, (int, float)) or time.time() * 1000 < expires_at:
                return {"authenticated": True, "email": email, "method": "credentials_file"}
            return {"authenticated": False, "email": None, "method": None,
                    "error": "Claude login has expired. Run claude /login again."}
    except FileNotFoundError:
        pass
    except ValueError:
        return {"authenticated": False, "email": None, "method": None,
                "error": "Claude credentials are unreadable. Run claude /login again."}
    except OSError:
        pass
    return {"authenticated": False, "email": None, "method": None,
            "error": "Claude CLI is not authenticated. Run claude /login or configure ANTHROPIC_API_KEY."}


@router.get("/{provider}/auth/status")
async def auth_status(provider: str) -> dict:
    provider = provider.strip().lower()
    installed = _which(_PROVIDER_BIN.get(provider, provider))
    if provider == "claude":
        if not installed:
            return _ok({"installed": False, "provider": "claude", "authenticated": False,
                        "email": None, "method": None, "error": "Claude Code CLI is not installed"})
        creds = _claude_credentials()
        return _ok({"installed": True, "provider": "claude",
                    "authenticated": creds["authenticated"],
                    "email": creds["email"] if not creds["authenticated"] else (creds["email"] or "Authenticated"),
                    "method": creds.get("method"),
                    "error": None if creds["authenticated"] else creds.get("error")})
    # Best-effort for other providers: installed CLI is treated as usable.
    return _ok({"installed": installed, "provider": provider, "authenticated": installed,
                "email": None, "method": None,
                "error": None if installed else f"{provider} CLI is not installed"})


@router.get("/{provider}/models")
async def models(provider: str, bypassCache: bool = False) -> dict:
    provider = provider.strip().lower()
    # Prefer the real registry models; fall back to claude's rich catalog or a
    # static list, then a bare default.
    catalog = _agent_models(provider) or _PROVIDER_MODELS.get(provider) or _DEFAULT_MODELS
    # The frontend discards the catalog unless `cache` is a truthy
    # ProviderModelsCacheInfo {updatedAt, expiresAt, source} — so always send one.
    now = datetime.now(timezone.utc)
    cache = {"updatedAt": now.isoformat(),
             "expiresAt": (now + timedelta(hours=1)).isoformat(),
             "source": "fresh"}
    return _ok({"provider": provider, "models": catalog, "cache": cache})


@router.get("/{provider}/skills")
async def skills(provider: str, workspacePath: str | None = None) -> dict:
    return _ok({"provider": provider.strip().lower(), "skills": []})


@router.get("/{provider}/mcp/servers")
async def mcp_servers(provider: str, scope: str | None = None, workspacePath: str | None = None) -> dict:
    provider = provider.strip().lower()
    if scope:
        return _ok({"provider": provider, "scope": scope, "servers": []})
    return _ok({"provider": provider, "scopes": {"user": [], "project": [], "local": []}})


class _McpBody(BaseModel):
    name: str | None = None


@router.post("/{provider}/mcp/servers")
async def add_mcp_server(provider: str, body: _McpBody) -> dict:
    # Stub: accept and report no-op (full MCP management is not ported yet).
    return _ok({"server": {"name": body.name, "provider": provider.strip().lower()}})


@router.delete("/{provider}/mcp/servers/{name}")
async def delete_mcp_server(provider: str, name: str, scope: str | None = None) -> dict:
    return _ok({"removed": name})


@router.post("/mcp/servers/global")
async def add_mcp_global(body: _McpBody) -> dict:
    return _ok({"results": []})


class _ActiveModelBody(BaseModel):
    model: str | None = None


@router.post("/{provider}/sessions/{session_id}/active-model")
async def change_active_model(provider: str, session_id: str, body: _ActiveModelBody) -> dict:
    # Acknowledge; the resume-model override store is not ported yet, so this is
    # a no-op beyond echoing the requested model.
    return _ok({"provider": provider.strip().lower(), "sessionId": session_id,
                "supported": True, "changed": bool(body.model), "model": body.model})
