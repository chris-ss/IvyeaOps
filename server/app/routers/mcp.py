"""MCP server management endpoints (Claude Code user-scope servers)."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.core.security import require_user
from app.services import mcp_config

router = APIRouter()


class AddServerBody(BaseModel):
    name: str = Field(..., min_length=1)
    config: dict[str, Any]


def _exec(call):
    try:
        return call()
    except mcp_config.MCPError as e:
        raise HTTPException(400, str(e))


@router.get("/mcp/servers")
def list_servers(_u: str = Depends(require_user)) -> dict[str, Any]:
    return {"servers": _exec(mcp_config.list_servers)}


@router.post("/mcp/servers")
def add_server(body: AddServerBody, _u: str = Depends(require_user)) -> dict[str, Any]:
    return _exec(lambda: mcp_config.add_server(body.name, body.config))


@router.delete("/mcp/servers/{name}")
def remove_server(name: str, _u: str = Depends(require_user)) -> dict[str, Any]:
    return _exec(lambda: mcp_config.remove_server(name))
