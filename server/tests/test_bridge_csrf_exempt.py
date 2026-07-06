"""The agent↔ops bridge is server-to-server (token-authed, no Origin) — it must be
exempt from the CSRF Origin guard, or every agent→board tool call 403s."""
from __future__ import annotations

import json

import pytest
from fastapi import Request
from starlette.responses import Response

import app.main as main


def _post_request(path: str) -> Request:
    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "headers": [],
        "client": ("127.0.0.1", 12345),
        "server": ("testserver", 80),
    }

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    return Request(scope, receive)


@pytest.mark.asyncio
async def test_bridge_exempt_but_normal_api_guarded(monkeypatch):
    # Simulate a deployment with an Origin allow-list configured.
    monkeypatch.setattr(main, "_ALLOWED", {"https://ivyea.com"})
    downstream: list[str] = []

    async def call_next(request: Request):
        downstream.append(request.url.path)
        return Response(status_code=204)

    # Bridge requests without Origin pass through to bearer-token authentication.
    r = await main._origin_guard(_post_request("/api/ivyea-agent-bridge/tools"), call_next)
    assert r.status_code == 204
    assert downstream == ["/api/ivyea-agent-bridge/tools"]

    # A normal state-changing /api write with no Origin is still guarded before routing.
    r2 = await main._origin_guard(_post_request("/api/market/research"), call_next)
    assert r2.status_code == 403
    assert "origin" in json.loads(r2.body).get("detail", "").lower()
    assert downstream == ["/api/ivyea-agent-bridge/tools"]
