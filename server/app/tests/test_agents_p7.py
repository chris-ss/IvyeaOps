"""P7 tests: TaskMaster file-based endpoints (tasks/PRD/templates/detection)
and graceful handling when the task-master CLI is absent."""
from __future__ import annotations

import importlib
import json
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
    from app.core import config as cfg_mod
    importlib.reload(cfg_mod)
    from app.core import security as sec_mod
    importlib.reload(sec_mod)
    from app.agents import db as db_mod
    importlib.reload(db_mod); db_mod.init_db()

    proj = tmp_path / "proj"
    (proj / ".taskmaster" / "tasks").mkdir(parents=True)
    (proj / ".taskmaster" / "tasks" / "tasks.json").write_text(json.dumps({
        "master": {"tasks": [
            {"id": 1, "title": "T1", "status": "pending", "priority": "high"},
            {"id": 2, "title": "T2", "status": "done"},
        ]}}), encoding="utf-8")
    proj2 = tmp_path / "proj2"; proj2.mkdir()  # no .taskmaster
    with db_mod.db_conn() as conn:
        conn.execute("INSERT INTO projects(project_id, project_path, isStarred, isArchived) VALUES(?,?,0,0)",
                     ("p1", str(proj)))
        conn.execute("INSERT INTO projects(project_id, project_path, isStarred, isArchived) VALUES(?,?,0,0)",
                     ("p2", str(proj2)))

    from app.agents.routers import taskmaster as tm_mod
    importlib.reload(tm_mod)
    # Force "CLI not installed" deterministically regardless of host.
    monkeypatch.setattr(tm_mod, "_which", lambda b: None)
    from app.agents import router as router_mod
    importlib.reload(router_mod)
    from app import main as main_mod
    importlib.reload(main_mod)
    cookie = sec_mod.issue_session("admin", "admin")
    c = TestClient(main_mod.app)
    c.cookies.set(cfg_mod.settings.session_cookie_name, cookie)
    return c


def test_get_tasks(ctx):
    body = ctx.get("/api/agents/taskmaster/tasks/p1").json()
    assert body["totalTasks"] == 2
    assert body["tasksByStatus"]["pending"] == 1 and body["tasksByStatus"]["done"] == 1
    assert {t["title"] for t in body["tasks"]} == {"T1", "T2"}


def test_tasks_empty_when_no_file(ctx):
    body = ctx.get("/api/agents/taskmaster/tasks/p2").json()
    assert body["tasks"] == []


def test_installation_status_not_installed(ctx):
    body = ctx.get("/api/agents/taskmaster/installation-status").json()
    assert body["isInstalled"] is False and body["isReady"] is False


def test_prd_write_list_read(ctx):
    assert ctx.post("/api/agents/taskmaster/prd/p1", json={"fileName": "spec.md", "content": "# Spec"}, headers=_HDR).json()["fileName"] == "spec.md"
    listing = ctx.get("/api/agents/taskmaster/prd/p1").json()["prdFiles"]
    assert any(f["name"] == "spec.md" for f in listing)
    read = ctx.get("/api/agents/taskmaster/prd/p1/spec.md").json()
    assert read["content"] == "# Spec"


def test_templates_and_apply(ctx):
    templates = ctx.get("/api/agents/taskmaster/prd-templates").json()["templates"]
    assert any(t["id"] == "web-app" for t in templates)
    r = ctx.post("/api/agents/taskmaster/apply-template/p1",
                 json={"templateId": "web-app", "fileName": "prd.txt"}, headers=_HDR)
    assert r.status_code == 200 and r.json()["fileName"] == "prd.txt"
    read = ctx.get("/api/agents/taskmaster/prd/p1/prd.txt").json()
    assert "Product Requirements Document" in read["content"]


def test_project_taskmaster_detection(ctx):
    assert ctx.get("/api/agents/projects/p1/taskmaster").json()["hasTaskmaster"] is True
    body2 = ctx.get("/api/agents/projects/p2/taskmaster").json()
    assert body2["hasTaskmaster"] is False


def test_cli_endpoint_not_installed(ctx):
    r = ctx.post("/api/agents/taskmaster/init/p1", headers=_HDR)
    assert r.status_code == 400
    assert "not installed" in r.json()["detail"].lower()
