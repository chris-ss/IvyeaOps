"""P5 tests: shell PTY WebSocket. Drives a real bash PTY with plain-shell
commands (no model/network) and checks output streaming, input, and exit."""
from __future__ import annotations

import importlib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

_ORIGIN = "https://test.example.com"


@pytest.fixture
def client(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OPSHUB_SECRET", "test-secret")
    monkeypatch.setenv("OPSHUB_ALLOWED_ORIGINS", _ORIGIN)
    monkeypatch.setenv("CCUI_DB_PATH", str(tmp_path / "ccui.db"))
    from app.core import config as cfg_mod
    importlib.reload(cfg_mod)
    from app.core import security as sec_mod
    importlib.reload(sec_mod)
    from app.ccui import db as db_mod
    importlib.reload(db_mod); db_mod.init_db()
    from app.ccui import shell_pty as shell_mod
    importlib.reload(shell_mod)
    from app.ccui import ws as ws_mod
    importlib.reload(ws_mod)
    from app.ccui import router as router_mod
    importlib.reload(router_mod)
    from app import main as main_mod
    importlib.reload(main_mod)
    cookie = sec_mod.issue_session("admin", "admin")
    c = TestClient(main_mod.app)
    c.cookies.set(cfg_mod.settings.session_cookie_name, cookie)
    return c, str(tmp_path)


def _collect_until(ws, token, max_frames=40):
    acc = ""
    for _ in range(max_frames):
        msg = ws.receive_json()
        if msg.get("type") == "output":
            acc += msg.get("data", "")
            if token in acc:
                return acc
        if "exited with code" in (msg.get("data") or ""):
            break
    return acc


def test_plain_shell_echo_streams_output(client):
    c, root = client
    with c.websocket_connect("/api/ccui/shell") as ws:
        ws.send_json({"type": "init", "projectPath": root, "isPlainShell": True,
                      "initialCommand": "echo CCUI_PTY_OK", "cols": 80, "rows": 24})
        out = _collect_until(ws, "CCUI_PTY_OK")
        assert "CCUI_PTY_OK" in out
        assert f"Starting terminal in: {root}" in out


def test_input_round_trip(client):
    c, root = client
    with c.websocket_connect("/api/ccui/shell") as ws:
        ws.send_json({"type": "init", "projectPath": root, "isPlainShell": True,
                      "initialCommand": "cat", "cols": 80, "rows": 24})
        # prime: read the welcome frame
        ws.receive_json()
        ws.send_json({"type": "input", "data": "PING_INPUT\n"})
        out = _collect_until(ws, "PING_INPUT")
        assert "PING_INPUT" in out
        # Ctrl-D closes cat's stdin so it exits and the PTY cleans up.
        ws.send_json({"type": "input", "data": "\x04"})


def test_resize_before_init_is_noop(client):
    c, root = client
    with c.websocket_connect("/api/ccui/shell") as ws:
        ws.send_json({"type": "resize", "cols": 100, "rows": 30})  # no session yet
        ws.send_json({"type": "init", "projectPath": root, "isPlainShell": True,
                      "initialCommand": "echo AFTER_RESIZE", "cols": 100, "rows": 30})
        assert "AFTER_RESIZE" in _collect_until(ws, "AFTER_RESIZE")


def test_build_command_hermes_agy_claude():
    from app.ccui import shell_pty as sp
    assert sp._build_command({"provider": "hermes"}) == "hermes chat"
    assert sp._build_command({"provider": "hermes", "hasSession": True, "sessionId": "20260602_x9"}) \
        == 'hermes chat --resume "20260602_x9"'
    assert sp._build_command({"provider": "agy"}) == "bash"  # not claude
    # claude path unchanged
    assert "claude" in sp._build_command({"provider": "claude"})
    assert sp._build_command({"provider": "claude", "hasSession": True, "sessionId": "s1"}) \
        == 'claude --resume "s1" || claude'


def test_invalid_project_path(client):
    c, _root = client
    with c.websocket_connect("/api/ccui/shell") as ws:
        ws.send_json({"type": "init", "projectPath": "/nonexistent/zzz", "isPlainShell": True,
                      "initialCommand": "echo X", "cols": 80, "rows": 24})
        msg = ws.receive_json()
        assert msg["type"] == "error" and "Invalid project path" in msg["message"]
