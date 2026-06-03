"""P8 tests: slash commands (list/execute), settings (credentials / prefs /
push stubs / api-keys), mcp-utils, and system/update."""
from __future__ import annotations

import importlib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

_ORIGIN = "https://test.example.com"
_HDR = {"Origin": _ORIGIN}


@pytest.fixture
def ctx(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("IVYEA_OPS_SECRET", "test-secret")
    monkeypatch.setenv("IVYEA_OPS_ALLOWED_ORIGINS", _ORIGIN)
    monkeypatch.setenv("AGENTS_DB_PATH", str(tmp_path / "agents.db"))
    home = tmp_path / "home"
    cmds = home / ".claude" / "commands"
    cmds.mkdir(parents=True)
    (cmds / "greet.md").write_text("---\ndescription: Greet someone\n---\nHello $ARGUMENTS, welcome!\n", encoding="utf-8")
    monkeypatch.setenv("HOME", str(home))

    from app.core import config as cfg_mod
    importlib.reload(cfg_mod)
    from app.core import security as sec_mod
    importlib.reload(sec_mod)
    from app.agents import db as db_mod
    importlib.reload(db_mod); db_mod.init_db()
    from app.agents import synchronizer as sync_mod
    importlib.reload(sync_mod)
    from app.agents import router as router_mod
    importlib.reload(router_mod)
    from app import main as main_mod
    importlib.reload(main_mod)
    cookie = sec_mod.issue_session("admin", "admin")
    c = TestClient(main_mod.app)
    c.cookies.set(cfg_mod.settings.session_cookie_name, cookie)
    return c, str(cmds)


def test_commands_list(ctx):
    c, _ = ctx
    body = c.post("/api/agents/commands/list", json={}, headers=_HDR).json()
    assert any(b["name"] == "/help" for b in body["builtIn"])
    assert any(cmd["name"] == "/greet" for cmd in body["custom"])


def test_commands_execute_custom(ctx):
    c, cmds = ctx
    r = c.post("/api/agents/commands/execute", headers=_HDR, json={
        "commandName": "/greet", "commandPath": f"{cmds}/greet.md", "args": ["World"]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["type"] == "custom"
    assert "Hello World, welcome!" in body["content"]


def test_commands_execute_builtin(ctx):
    c, _ = ctx
    body = c.post("/api/agents/commands/execute", json={"commandName": "/help"}, headers=_HDR).json()
    assert body["type"] == "builtin" and body["action"] == "help"


def test_commands_execute_path_escape_blocked(ctx):
    c, _ = ctx
    r = c.post("/api/agents/commands/execute", headers=_HDR, json={
        "commandName": "/x", "commandPath": "/etc/passwd", "args": []})
    assert r.status_code == 403


def test_credentials_crud(ctx):
    c, _ = ctx
    assert c.get("/api/agents/settings/credentials").json()["credentials"] == []
    add = c.post("/api/agents/settings/credentials", headers=_HDR,
                 json={"provider": "claude", "name": "k1", "value": "secret"}).json()
    cid = add["credential"]["id"]
    assert "value" not in add["credential"]  # secret never returned
    creds = c.get("/api/agents/settings/credentials").json()["credentials"]
    assert len(creds) == 1 and creds[0]["provider"] == "claude"
    assert c.request("DELETE", f"/api/agents/settings/credentials/{cid}", headers=_HDR).json()["success"]
    assert c.get("/api/agents/settings/credentials").json()["credentials"] == []


def test_notification_prefs(ctx):
    c, _ = ctx
    assert "enabled" in c.get("/api/agents/settings/notification-preferences").json()["preferences"]
    r = c.put("/api/agents/settings/notification-preferences", json={"enabled": True}, headers=_HDR)
    assert r.json()["preferences"]["enabled"] is True


def test_push_stubs(ctx):
    c, _ = ctx
    assert c.get("/api/agents/settings/push/vapid-public-key").json()["enabled"] is False
    assert c.post("/api/agents/settings/push/subscribe", json={}, headers=_HDR).json()["success"] is True


def test_mcp_utils_and_system(ctx):
    c, _ = ctx
    assert c.get("/api/agents/mcp-utils/taskmaster-server").json()["hasMCPServer"] is False
    assert c.post("/api/agents/system/update", headers=_HDR).json()["success"] is False
