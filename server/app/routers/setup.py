"""First-run Setup Wizard endpoints.

GET  /api/setup/status              — check whether the wizard needs to run
GET  /api/setup/install-stream      — SSE stream: install codex or claude via npm
POST /api/setup/complete            — mark setup as done (write setup_done flag)

Design notes
------------
- needs_setup is True only when setup_done is explicitly False AND no password
  has been set yet (covers fresh installs).  Users who already configured the
  server manually before this feature existed will have setup_done=False but
  a password set, so they won't be forced through the wizard.
- The install-stream endpoint runs `npm install -g <package>` in a subprocess
  and streams stdout/stderr as SSE events so the frontend can show a live log.
- All endpoints require authentication so an unauthenticated visitor cannot
  trigger package installations.
"""
from __future__ import annotations

import asyncio
import os
import shutil
import sys
from pathlib import Path
from typing import AsyncGenerator

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app.core import hub_settings as _hs
from app.core.security import require_user

router = APIRouter()

# Mapping from the agent name the frontend sends to the npm package to install.
_INSTALLABLE: dict[str, str] = {
    "codex":  "@openai/codex",
    "claude": "@anthropic-ai/claude-code",
}


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------

@router.get("/setup/status")
def setup_status(_u: str = Depends(require_user)):
    """Return whether the first-run wizard needs to run and what's configured."""
    from app.services.runners import _find_bin, RUNNER_ORDER
    from app.core.config import settings as _cfg

    cfg = _hs.load()
    setup_done: bool = bool(cfg.get("setup_done"))

    # Password is either in hub_settings.json or the startup .env
    password_set: bool = bool(
        cfg.get("password_hash") or _cfg.admin_password_hash
    )

    agents_found = {name: bool(_find_bin(name)) for name in RUNNER_ORDER}
    any_agent_found = any(agents_found.values())
    apimart_set: bool = bool(cfg.get("apimart_key"))

    # Trigger the wizard only for genuine fresh installs.
    needs_setup = not setup_done and not password_set

    return {
        "needs_setup": needs_setup,
        "setup_done": setup_done,
        "checks": {
            "password_set": password_set,
            "any_agent_found": any_agent_found,
            "agents": agents_found,
            "apimart_set": apimart_set,
        },
    }


# ---------------------------------------------------------------------------
# Agent install — SSE stream
# ---------------------------------------------------------------------------

def _npm_bin() -> str | None:
    """Locate npm, searching PATH augmentations that systemd strips."""
    w = shutil.which("npm")
    if w:
        return w
    home = Path.home()
    candidates = [
        home / ".hermes" / "node" / "bin" / "npm",
        Path("/usr/local/bin/npm"),
        Path("/usr/bin/npm"),
    ]
    for c in candidates:
        if c.is_file():
            return str(c)
    return None


async def _install_stream(agent: str) -> AsyncGenerator[str, None]:
    package = _INSTALLABLE.get(agent)
    if not package:
        yield f"data: ERROR: unknown agent '{agent}'. Supported: {', '.join(_INSTALLABLE)}\n\n"
        return

    npm = _npm_bin()
    if not npm:
        yield "data: ERROR: npm not found. Please install Node.js first.\n\n"
        yield "data: Download: https://nodejs.org/\n\n"
        return

    # Build a rich PATH so npm can find node and write to the right global prefix.
    env = {**os.environ}
    home = Path.home()
    extra = [
        str(home / ".hermes" / "node" / "bin"),
        str(home / ".local" / "bin"),
        "/usr/local/bin",
        "/usr/bin",
    ]
    path_parts = extra + env.get("PATH", "").split(os.pathsep)
    env["PATH"] = os.pathsep.join(dict.fromkeys(p for p in path_parts if p))
    env.setdefault("HOME", str(home))

    cmd = [npm, "install", "-g", package]
    yield f"data: > {' '.join(cmd)}\n\n"

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env=env,
        )
        assert proc.stdout is not None
        async for raw in proc.stdout:
            line = raw.decode("utf-8", errors="replace").rstrip()
            if line:
                yield f"data: {line}\n\n"
        await proc.wait()
        if proc.returncode == 0:
            yield "data: \n\n"
            yield f"data: ✓ {package} installed successfully.\n\n"
            yield "data: __DONE__\n\n"
        else:
            yield f"data: ✗ npm exited with code {proc.returncode}\n\n"
            yield "data: __ERROR__\n\n"
    except Exception as exc:
        yield f"data: ERROR: {exc}\n\n"
        yield "data: __ERROR__\n\n"


@router.get("/setup/install-stream")
async def install_stream(agent: str, _u: str = Depends(require_user)):
    """SSE endpoint: stream npm install output for the given agent."""
    return StreamingResponse(
        _install_stream(agent),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # disable nginx buffering
        },
    )


# ---------------------------------------------------------------------------
# Complete setup
# ---------------------------------------------------------------------------

@router.post("/setup/complete")
def setup_complete(_u: str = Depends(require_user)):
    """Mark the first-run wizard as complete."""
    _hs.save({"setup_done": True})
    return {"ok": True}
