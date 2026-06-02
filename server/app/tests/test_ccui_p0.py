"""P0 smoke tests for the native CloudCLI backend scaffold.

Verifies the /api/ccui mount: auth gating, the load-bearing endpoints the
sidebar/AuthContext hit on first paint (empty but well-shaped), and that the
chat WebSocket accepts an authenticated client and answers the connect-time
state probes. Uses a real admin session cookie so the actual cookie-auth path
(require_module for REST, verify_session for WS) is exercised end to end.
"""
from __future__ import annotations

import importlib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

_ORIGIN = "https://test.example.com"
_HDR = {"Origin": _ORIGIN}


@pytest.fixture
def client(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OPSHUB_SECRET", "test-secret")
    monkeypatch.setenv("OPSHUB_ALLOWED_ORIGINS", _ORIGIN)
    monkeypatch.setenv("CCUI_DB_PATH", str(tmp_path / "ccui.db"))
    # Isolate HOME so the projects-list synchronizer scans an empty ~/.claude.
    (tmp_path / "home").mkdir()
    monkeypatch.setenv("HOME", str(tmp_path / "home"))

    from app.core import config as cfg_mod
    importlib.reload(cfg_mod)
    from app.core import security as sec_mod
    importlib.reload(sec_mod)
    from app.ccui import db as db_mod
    importlib.reload(db_mod)
    from app.ccui import synchronizer as sync_mod
    importlib.reload(sync_mod)
    from app.ccui import ws as ws_mod
    importlib.reload(ws_mod)
    from app.ccui import router as ccui_router_mod
    importlib.reload(ccui_router_mod)
    from app import main as main_mod
    importlib.reload(main_mod)

    cookie = sec_mod.issue_session("admin", "admin")
    with TestClient(main_mod.app) as c:
        c.cookies.set(cfg_mod.settings.session_cookie_name, cookie)
        yield c


def test_health(client):
    r = client.get("/api/ccui/health")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "ok"


def test_requires_auth(client):
    # Same request without the session cookie must be rejected by the gate.
    bare = TestClient(client.app)
    r = bare.get("/api/ccui/projects")
    assert r.status_code in (401, 403), r.text


def test_projects_empty(client):
    r = client.get("/api/ccui/projects")
    assert r.status_code == 200, r.text
    assert r.json() == []


def test_archived_sessions_empty(client):
    r = client.get("/api/ccui/providers/sessions/archived")
    assert r.status_code == 200, r.text
    # P1 wraps the (empty) list in the standard success envelope.
    assert r.json() == {"success": True, "data": {"sessions": []}}


def test_onboarding_defaults_completed(client):
    r = client.get("/api/ccui/user/onboarding-status")
    assert r.status_code == 200, r.text
    assert r.json()["hasCompletedOnboarding"] is True


def test_complete_onboarding(client):
    r = client.post("/api/ccui/user/complete-onboarding", headers=_HDR)
    assert r.status_code == 200, r.text
    assert r.json()["success"] is True


def test_chat_ws_state_probes(client):
    with client.websocket_connect("/api/ccui/ws") as ws:
        ws.send_json({"type": "get-active-sessions"})
        msg = ws.receive_json()
        assert msg["type"] == "active-sessions"
        assert msg["sessions"]["claude"] == []  # provider-bucketed

        ws.send_json({"type": "check-session-status", "sessionId": "abc"})
        msg = ws.receive_json()
        assert msg["type"] == "session-status"
        assert msg["sessionId"] == "abc"
        assert msg["isProcessing"] is False


def test_chat_ws_rejects_unauthenticated(client):
    bare = TestClient(client.app)
    with pytest.raises(Exception):
        with bare.websocket_connect("/api/ccui/ws"):
            pass
