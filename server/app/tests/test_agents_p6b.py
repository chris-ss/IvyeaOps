"""P6b tests: hermes chat over the WS, driven against a FAKE hermes executable
that prints a canned reply + a trailing `session_id:` line (verifies the pipe:
session_created -> assistant text with session_id line stripped -> complete)."""
from __future__ import annotations

import importlib
import stat
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

_ORIGIN = "https://test.example.com"


def _fake_codex(tmp_path: Path) -> Path:
    p = tmp_path / "fake_codex.py"
    p.write_text(
        "#!/usr/bin/env python3\n"
        "import sys, json\n"
        "sid='codex-thread-1'\n"
        "def emit(o): sys.stdout.write(json.dumps(o)+'\\n'); sys.stdout.flush()\n"
        "emit({'type':'thread.started','thread_id':sid})\n"
        "emit({'type':'turn.started'})\n"
        "emit({'type':'item.completed','item':{'id':'i0','type':'agent_message','text':'PONG from codex'}})\n"
        "emit({'type':'turn.completed','usage':{'input_tokens':100,'output_tokens':5}})\n",
        encoding="utf-8")
    p.chmod(p.stat().st_mode | stat.S_IEXEC | stat.S_IRUSR)
    return p


def _fake_hermes(tmp_path: Path) -> Path:
    p = tmp_path / "fake_hermes.sh"
    p.write_text("#!/bin/bash\n"
                 "echo 'Hello from fake hermes'\n"
                 "echo 'session_id: 20260101_fake'\n", encoding="utf-8")
    p.chmod(p.stat().st_mode | stat.S_IEXEC | stat.S_IRUSR)
    return p


@pytest.fixture
def env(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("IVYEA_OPS_SECRET", "test-secret")
    monkeypatch.setenv("IVYEA_OPS_ALLOWED_ORIGINS", _ORIGIN)
    monkeypatch.setenv("AGENTS_DB_PATH", str(tmp_path / "agents.db"))
    from app.core import config as cfg_mod
    importlib.reload(cfg_mod)
    from app.core import security as sec_mod
    importlib.reload(sec_mod)
    from app.agents import db as db_mod
    importlib.reload(db_mod); db_mod.init_db()
    from app.agents import claude_sessions as cs_mod
    importlib.reload(cs_mod)
    from app.agents import hermes_driver as hd_mod
    importlib.reload(hd_mod)
    from app.agents import claude_driver as cd_mod
    importlib.reload(cd_mod)
    from app.agents import codex_driver as cx_mod
    importlib.reload(cx_mod)
    from app.agents import ws as ws_mod
    importlib.reload(ws_mod)
    from app.agents import router as router_mod
    importlib.reload(router_mod)
    from app import main as main_mod
    importlib.reload(main_mod)
    monkeypatch.setattr(hd_mod, "_hermes_bin", lambda: str(_fake_hermes(tmp_path)))
    monkeypatch.setattr(cx_mod, "_codex_bin", lambda: str(_fake_codex(tmp_path)))
    cookie = sec_mod.issue_session("admin", "admin")
    c = TestClient(main_mod.app)
    c.cookies.set(cfg_mod.settings.session_cookie_name, cookie)
    return c


def test_hermes_command_round_trip(env):
    c = env
    with c.websocket_connect("/api/agents/ws") as ws:
        ws.send_json({"type": "hermes-command", "command": "hi", "options": {}})
        kinds, texts, new_sid = [], [], None
        for _ in range(15):
            msg = ws.receive_json()
            kinds.append(msg.get("kind") or msg.get("type"))
            if msg.get("kind") == "session_created":
                new_sid = msg.get("newSessionId")
            if msg.get("kind") == "text":
                texts.append((msg.get("content"), msg.get("provider")))
            if msg.get("kind") == "complete":
                break
        assert "session_created" in kinds and new_sid
        assert ("Hello from fake hermes", "hermes") in texts
        # the trailing "session_id:" line must be stripped from the reply
        assert all("session_id:" not in (t or "") for t, _ in texts)
        assert "complete" in kinds


def test_codex_command_round_trip(env):
    c = env
    with c.websocket_connect("/api/agents/ws") as ws:
        ws.send_json({"type": "codex-command", "command": "hi", "options": {"model": "gpt-5.5"}})
        kinds, texts, new_sid = [], [], None
        for _ in range(15):
            msg = ws.receive_json()
            kinds.append(msg.get("kind") or msg.get("type"))
            if msg.get("kind") == "session_created":
                new_sid = msg.get("newSessionId")
            if msg.get("kind") == "text":
                texts.append((msg.get("content"), msg.get("provider")))
            if msg.get("kind") == "complete":
                break
        assert "session_created" in kinds and new_sid == "codex-thread-1"
        assert ("PONG from codex", "codex") in texts
        assert "status" in kinds and "complete" in kinds


def test_hermes_error_output_classified_as_error(env, tmp_path, monkeypatch):
    c = env
    err = tmp_path / "fake_hermes_err.sh"
    err.write_text("#!/bin/bash\necho 'Error code: 401 - Invalid API Key'\necho 'session_id: zz'\n",
                   encoding="utf-8")
    err.chmod(err.stat().st_mode | stat.S_IEXEC | stat.S_IRUSR)
    from app.agents import hermes_driver as hd
    monkeypatch.setattr(hd, "_hermes_bin", lambda: str(err))
    with c.websocket_connect("/api/agents/ws") as ws:
        ws.send_json({"type": "hermes-command", "command": "hi", "options": {}})
        kinds = []
        for _ in range(15):
            m = ws.receive_json()
            kinds.append(m.get("kind"))
            if m.get("kind") == "error":
                assert "401" in (m.get("content") or "")
                assert "session_id:" not in (m.get("content") or "")  # trailing line stripped
            if m.get("kind") == "complete":
                break
        # 401 output must be surfaced as an error, NOT as a normal assistant bubble.
        assert "error" in kinds and "text" not in kinds


def test_hermes_read_history_from_json(tmp_path, monkeypatch):
    import importlib, json as _json
    home = tmp_path / "home"
    sdir = home / ".hermes" / "sessions"
    sdir.mkdir(parents=True)
    (sdir / "session_20260101_abc.json").write_text(_json.dumps({
        "session_id": "20260101_abc",
        "messages": [{"role": "user", "content": "hi hermes"},
                     {"role": "assistant", "content": "hello back"}],
    }), encoding="utf-8")
    monkeypatch.setenv("HOME", str(home))
    from app.agents import hermes_driver as hd
    importlib.reload(hd)  # re-evaluate _HERMES_SESSIONS_DIR against the temp HOME
    h = hd.read_history("20260101_abc")
    assert h["total"] == 2
    assert h["messages"][0]["role"] == "user" and h["messages"][0]["content"] == "hi hermes"
    assert h["messages"][1]["role"] == "assistant"


def test_get_active_sessions_includes_hermes_bucket(env):
    c = env
    with c.websocket_connect("/api/agents/ws") as ws:
        ws.send_json({"type": "get-active-sessions"})
        msg = ws.receive_json()
        assert msg["type"] == "active-sessions"
        assert "hermes" in msg["sessions"] and "claude" in msg["sessions"]
