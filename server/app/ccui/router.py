"""Aggregate routers for the CloudCLI native backend.

Exposes two routers that main.py mounts under ``/api/ccui``:
  • ``api_router`` — all REST endpoints; mounted WITH the ops module dependency
    so access aligns with the existing "agents" board permission.
  • ``ws_router``  — WebSocket endpoints; mounted WITHOUT that dependency (they
    do their own cookie auth at handshake time, see ws.py).

The frontend's ``api.js`` rewrites ``/api/*`` → ``/api/ccui/*``, so the sub-route
prefixes below reproduce the original claudecodeui paths (``/projects``,
``/providers/sessions``, ``/user``, ``/auth`` ...).
"""
from __future__ import annotations

from fastapi import APIRouter

from app.ccui import ws as ws_module
from app.ccui.routers import (auth, commands, core, files, git, mcp_utils, projects,
                              providers, sessions, settings, taskmaster, user)

api_router = APIRouter()
api_router.include_router(core.router, tags=["ccui"])
api_router.include_router(auth.router, prefix="/auth", tags=["ccui-auth"])
api_router.include_router(user.router, prefix="/user", tags=["ccui-user"])
api_router.include_router(projects.router, prefix="/projects", tags=["ccui-projects"])
api_router.include_router(sessions.router, prefix="/providers", tags=["ccui-sessions"])
api_router.include_router(providers.router, prefix="/providers", tags=["ccui-providers"])
api_router.include_router(git.router, prefix="/git", tags=["ccui-git"])
api_router.include_router(taskmaster.router, prefix="/taskmaster", tags=["ccui-taskmaster"])
api_router.include_router(settings.router, prefix="/settings", tags=["ccui-settings"])
api_router.include_router(commands.router, prefix="/commands", tags=["ccui-commands"])
api_router.include_router(mcp_utils.router, prefix="/mcp-utils", tags=["ccui-mcp-utils"])
# File ops use full paths (/projects/{id}/file..., /browse-filesystem, /create-folder).
api_router.include_router(files.router, tags=["ccui-files"])

ws_router = ws_module.router
