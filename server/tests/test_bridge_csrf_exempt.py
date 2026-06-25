"""The agent↔ops bridge is server-to-server (token-authed, no Origin) — it must be
exempt from the CSRF Origin guard, or every agent→board tool call 403s."""
from __future__ import annotations

from fastapi.testclient import TestClient

import app.main as main


def test_bridge_exempt_but_normal_api_guarded(monkeypatch):
    # Simulate a deployment with an Origin allow-list configured.
    monkeypatch.setattr(main, "_ALLOWED", {"https://ivyea.com"})
    client = TestClient(main.app)

    # Bridge call with no Origin must NOT be origin-blocked (401 for missing token
    # is fine — the point is it's not a 403 "origin not allowed").
    r = client.post("/api/ivyea-agent-bridge/tools", json={"module": "market", "query": ""})
    assert r.status_code != 403, r.text

    # A normal state-changing /api write with no Origin is still guarded.
    r2 = client.post("/api/market/research", json={"query": "x"})
    assert r2.status_code == 403
    assert "origin" in r2.json().get("detail", "").lower()
