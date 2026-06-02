"""Tests for conversation search (claude transcripts) — the module generator
and the SSE endpoint, against an isolated temp DB + transcript file."""
from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

_ORIGIN = "https://test.example.com"


@pytest.fixture
def ctx(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OPSHUB_SECRET", "test-secret")
    monkeypatch.setenv("OPSHUB_ALLOWED_ORIGINS", _ORIGIN)
    monkeypatch.setenv("CCUI_DB_PATH", str(tmp_path / "ccui.db"))
    from app.core import config as cfg_mod
    importlib.reload(cfg_mod)
    from app.core import security as sec_mod
    importlib.reload(sec_mod)
    from app.ccui import db as db_mod
    importlib.reload(db_mod); db_mod.init_db()

    proj = tmp_path / "proj"; proj.mkdir()
    transcript = tmp_path / "sess.jsonl"
    transcript.write_text("\n".join(json.dumps(e) for e in [
        {"sessionId": "s1", "uuid": "u1", "timestamp": "2026-01-01T00:00:00Z",
         "message": {"role": "user", "content": "please find the magicneedle in the haystack"}},
        {"sessionId": "s1", "uuid": "u2", "timestamp": "2026-01-01T00:00:01Z",
         "message": {"role": "assistant", "content": [{"type": "text", "text": "no needle here"}]}},
    ]), encoding="utf-8")
    with db_mod.db_conn() as conn:
        conn.execute("INSERT INTO projects(project_id, project_path, custom_project_name, isStarred, isArchived)"
                     " VALUES(?,?,?,0,0)", ("p1", str(proj), "My Proj"))
        conn.execute("INSERT INTO sessions(session_id, provider, custom_name, project_path, jsonl_path,"
                     " isArchived, created_at, updated_at) VALUES(?,?,?,?,?,0,?,?)",
                     ("s1", "claude", "Sess One", str(proj), str(transcript),
                      "2026-01-01T00:00:00Z", "2026-01-01T00:00:02Z"))

    from app.ccui import search as search_mod
    importlib.reload(search_mod)
    from app.ccui.routers import sessions as sessions_mod
    importlib.reload(sessions_mod)
    from app.ccui import router as router_mod
    importlib.reload(router_mod)
    from app import main as main_mod
    importlib.reload(main_mod)
    cookie = sec_mod.issue_session("admin", "admin")
    c = TestClient(main_mod.app)
    c.cookies.set(cfg_mod.settings.session_cookie_name, cookie)
    return c, search_mod


def test_search_generator_finds_match(ctx):
    _c, search_mod = ctx
    events = list(search_mod.search_conversations("magicneedle", 50))
    assert events, "expected at least one event"
    result = next((d for ev, d in events if ev == "result"), None)
    assert result is not None
    pr = result["projectResult"]
    assert pr["projectDisplayName"] == "My Proj"
    sess = pr["sessions"][0]
    assert sess["sessionId"] == "s1" and sess["sessionSummary"] == "Sess One"
    m = sess["matches"][0]
    assert "magicneedle" in m["snippet"].lower()
    assert m["highlights"] and m["highlights"][0]["end"] > m["highlights"][0]["start"]
    assert result["totalMatches"] >= 1


def test_search_no_match(ctx):
    _c, search_mod = ctx
    events = list(search_mod.search_conversations("zzznotpresent", 50))
    assert not any(ev == "result" for ev, _ in events)


def test_sse_endpoint(ctx):
    c, _search = ctx
    r = c.get("/api/ccui/providers/search/sessions", params={"q": "magicneedle"})
    assert r.status_code == 200, r.text
    body = r.text
    assert "event: result" in body
    assert "magicneedle" in body.lower()
    assert "event: done" in body


def test_sse_short_query_rejected(ctx):
    c, _search = ctx
    r = c.get("/api/ccui/providers/search/sessions", params={"q": "a"})
    assert r.status_code == 400
