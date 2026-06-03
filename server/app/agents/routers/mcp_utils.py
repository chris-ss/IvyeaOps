"""MCP utilities (mounted at ``/mcp-utils``) — port of routes/mcp-utils.js.

Only the taskmaster MCP-server detection probe is used by the frontend; we
report "no MCP server" (full MCP management isn't ported)."""
from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()


@router.get("/taskmaster-server")
async def taskmaster_server() -> dict:
    return {"hasMCPServer": False, "servers": []}
