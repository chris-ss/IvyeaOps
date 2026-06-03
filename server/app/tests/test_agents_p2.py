"""P2 tests: claude chat WS driven against FAKE claude binaries that emit canned
stream-json — exercising the driver + WS contract end to end without the model.

Covers Stage A (streaming to complete, bypass path) and Stage B (interactive
permission: can_use_tool control_request -> permission_request -> user decision
-> control_response), plus the pure helpers.
"""
from __future__ import annotations

import importlib
import stat
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

_ORIGIN = "https://test.example.com"


def _fake_stream(tmp_path: Path) -> Path:
    """Fake claude: emit init + one assistant text + result (no tools)."""
    p = tmp_path / "fake_stream.py"
    p.write_text(
        "import sys, json\n"
        "for line in sys.stdin:\n"        # consume user msg (bypass: stdin closes)
        "    break\n"
        "sid='fake-sess-001'\n"
        "for ev in [\n"
        "  {'type':'system','subtype':'init','session_id':sid},\n"
        "  {'type':'assistant','session_id':sid,'message':{'role':'assistant',"
        "   'content':[{'type':'text','text':'Hello from fake claude'}]}},\n"
        "  {'type':'result','subtype':'success','session_id':sid,'is_error':False,"
        "   'usage':{'input_tokens':10,'output_tokens':5}},\n"
        "]:\n"
        "  sys.stdout.write(json.dumps(ev)+'\\n'); sys.stdout.flush()\n",
        encoding="utf-8")
    p.chmod(p.stat().st_mode | stat.S_IEXEC)
    return p


def _fake_permission(tmp_path: Path) -> Path:
    """Fake claude (interactive): read initialize + user msg, emit a tool_use,
    then a can_use_tool control_request, read the control_response, and echo the
    granted behavior back as assistant text before the result."""
    p = tmp_path / "fake_perm.py"
    p.write_text(
        "import sys, json\n"
        "sid='fake-sess-perm'\n"
        "def emit(o): sys.stdout.write(json.dumps(o)+'\\n'); sys.stdout.flush()\n"
        "sys.stdin.readline()  # initialize\n"
        "sys.stdin.readline()  # user message\n"
        "emit({'type':'system','subtype':'init','session_id':sid})\n"
        "emit({'type':'assistant','session_id':sid,'message':{'role':'assistant',"
        "  'content':[{'type':'tool_use','id':'tu1','name':'Write','input':{'file_path':'/tmp/x'}}]}})\n"
        "emit({'type':'control_request','request_id':'creq-1','request':{'subtype':'can_use_tool',"
        "  'tool_name':'Write','input':{'file_path':'/tmp/x'},'tool_use_id':'tu1'}})\n"
        "resp = json.loads(sys.stdin.readline())\n"
        "beh = resp['response']['response']['behavior']\n"
        "emit({'type':'assistant','session_id':sid,'message':{'role':'assistant',"
        "  'content':[{'type':'text','text':'decision='+beh}]}})\n"
        "emit({'type':'result','subtype':'success','session_id':sid,'is_error':False})\n",
        encoding="utf-8")
    p.chmod(p.stat().st_mode | stat.S_IEXEC)
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
    from app.agents import claude_driver as cd_mod
    importlib.reload(cd_mod)
    from app.agents import ws as ws_mod
    importlib.reload(ws_mod)
    from app.agents import router as router_mod
    importlib.reload(router_mod)
    from app import main as main_mod
    importlib.reload(main_mod)
    cookie = sec_mod.issue_session("admin", "admin")
    client = TestClient(main_mod.app)
    client.cookies.set(cfg_mod.settings.session_cookie_name, cookie)
    return client, cd_mod, cfg_mod


def _patch_fake(monkeypatch, cd_mod, fake: Path):
    real = cd_mod._build_argv

    def _argv(options):
        argv, interactive = real(options)
        return [sys.executable, str(fake)] + argv[1:], interactive
    monkeypatch.setattr(cd_mod, "_build_argv", _argv)


def test_chat_command_streams_to_complete(env, tmp_path, monkeypatch):
    client, cd_mod, _ = env
    _patch_fake(monkeypatch, cd_mod, _fake_stream(tmp_path))
    with client.websocket_connect("/api/agents/ws") as ws:
        # skipPermissions -> bypass path (stdin closed after user msg).
        ws.send_json({"type": "claude-command", "command": "hi",
                      "options": {"toolsSettings": {"skipPermissions": True}}})
        kinds, texts, new_sid = [], [], None
        for _ in range(20):
            msg = ws.receive_json()
            kinds.append(msg.get("kind") or msg.get("type"))
            if msg.get("kind") == "session_created":
                new_sid = msg.get("newSessionId")
            if msg.get("kind") == "text":
                texts.append(msg.get("content"))
            if msg.get("kind") == "complete":
                break
        assert "session_created" in kinds and new_sid == "fake-sess-001"
        assert "Hello from fake claude" in texts
        assert "complete" in kinds and "status" in kinds


def test_interactive_permission_round_trip(env, tmp_path, monkeypatch):
    client, cd_mod, _ = env
    _patch_fake(monkeypatch, cd_mod, _fake_permission(tmp_path))
    with client.websocket_connect("/api/agents/ws") as ws:
        ws.send_json({"type": "claude-command", "command": "write a file",
                      "options": {"permissionMode": "default"}})
        got_permission = False
        texts = []
        for _ in range(30):
            msg = ws.receive_json()
            if msg.get("kind") == "permission_request":
                got_permission = True
                assert msg.get("toolName") == "Write"
                assert msg.get("requestId") == "creq-1"
                # User approves the tool.
                ws.send_json({"type": "claude-permission-response",
                              "requestId": "creq-1", "allow": True})
            if msg.get("kind") == "text":
                texts.append(msg.get("content"))
            if msg.get("kind") == "complete":
                break
        assert got_permission, "expected a permission_request event"
        assert "decision=allow" in texts, f"claude did not receive allow; texts={texts}"


def test_build_argv_bypass_and_resume():
    from app.agents import claude_driver as cd
    argv, interactive = cd._build_argv({"sessionId": "abc", "model": "opus",
                                        "toolsSettings": {"skipPermissions": True}})
    assert interactive is False
    assert "--resume" in argv and "abc" in argv
    assert "--model" in argv and "opus" in argv
    assert argv[argv.index("--permission-mode") + 1] == "bypassPermissions"
    assert "--permission-prompt-tool" not in argv


def test_build_argv_interactive_default():
    from app.agents import claude_driver as cd
    argv, interactive = cd._build_argv({"permissionMode": "default"})
    assert interactive is True
    assert argv[argv.index("--permission-mode") + 1] == "default"
    assert argv[argv.index("--permission-prompt-tool") + 1] == "stdio"


def test_token_budget_extraction():
    from app.agents import claude_driver as cd
    b = cd._extract_token_budget({"usage": {"input_tokens": 100, "output_tokens": 20}})
    assert b["used"] == 120 and b["inputTokens"] == 100 and b["outputTokens"] == 20
