"""P4 tests: git endpoints, driven against a THROWAWAY repo created under
tmp_path. Hard isolation per the git-in-tests rule: every git command runs with
cwd inside the temp repo and local-only config — the real repo is never touched.
"""
from __future__ import annotations

import importlib
import os
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

_ORIGIN = "https://test.example.com"
_HDR = {"Origin": _ORIGIN}


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=str(repo), check=True, capture_output=True,
                   env={**os.environ, "GIT_TERMINAL_PROMPT": "0"})


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

    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.name", "Tester")
    _git(repo, "config", "user.email", "tester@example.com")
    _git(repo, "config", "commit.gpgsign", "false")
    (repo / "a.txt").write_text("one\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "init commit")

    with db_mod.db_conn() as conn:
        conn.execute("INSERT INTO projects(project_id, project_path, isStarred, isArchived)"
                     " VALUES(?,?,0,0)", ("p1", str(repo)))

    from app.agents import router as router_mod
    importlib.reload(router_mod)
    from app import main as main_mod
    importlib.reload(main_mod)
    cookie = sec_mod.issue_session("admin", "admin")
    c = TestClient(main_mod.app)
    c.cookies.set(cfg_mod.settings.session_cookie_name, cookie)
    return c, repo


def test_status_clean_then_modified(ctx):
    c, repo = ctx
    r = c.get("/api/agents/git/status", params={"project": "p1"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["hasCommits"] is True
    assert body["branch"]  # some branch name
    assert body["modified"] == []
    # modify a tracked file
    (repo / "a.txt").write_text("two\n", encoding="utf-8")
    assert "a.txt" in c.get("/api/agents/git/status", params={"project": "p1"}).json()["modified"]


def test_branches_and_create_checkout(ctx):
    c, _ = ctx
    base = c.get("/api/agents/git/status", params={"project": "p1"}).json()["branch"]
    assert c.post("/api/agents/git/create-branch", json={"project": "p1", "branch": "feature-x"}, headers=_HDR).json()["success"]
    assert "feature-x" in c.get("/api/agents/git/branches", params={"project": "p1"}).json()["localBranches"]
    assert c.post("/api/agents/git/checkout", json={"project": "p1", "branch": base}, headers=_HDR).json()["success"]


def test_diff_and_commit_and_log(ctx):
    c, repo = ctx
    (repo / "a.txt").write_text("changed\n", encoding="utf-8")
    diff = c.get("/api/agents/git/diff", params={"project": "p1", "file": "a.txt"}).json()["diff"]
    assert "+changed" in diff
    r = c.post("/api/agents/git/commit", json={"project": "p1", "message": "update a", "files": ["a.txt"]}, headers=_HDR)
    assert r.status_code == 200 and r.json()["success"], r.text
    commits = c.get("/api/agents/git/commits", params={"project": "p1"}).json()["commits"]
    assert commits[0]["message"] == "update a" and commits[0]["author"] == "Tester"
    cd = c.get("/api/agents/git/commit-diff", params={"project": "p1", "commit": commits[0]["hash"]}).json()
    assert "isTruncated" in cd and "update a" in cd["diff"]


def test_discard_restores_file(ctx):
    c, repo = ctx
    (repo / "a.txt").write_text("dirty\n", encoding="utf-8")
    assert c.post("/api/agents/git/discard", json={"project": "p1", "file": "a.txt"}, headers=_HDR).json()["success"]
    assert (repo / "a.txt").read_text() == "one\n"


def test_remote_status_no_remote(ctx):
    c, _ = ctx
    body = c.get("/api/agents/git/remote-status", params={"project": "p1"}).json()
    assert body["hasRemote"] is False and body["hasUpstream"] is False


def test_untracked_in_status(ctx):
    c, repo = ctx
    (repo / "new.txt").write_text("x", encoding="utf-8")
    assert "new.txt" in c.get("/api/agents/git/status", params={"project": "p1"}).json()["untracked"]


def test_invalid_branch_name_rejected(ctx):
    c, _ = ctx
    r = c.post("/api/agents/git/checkout", json={"project": "p1", "branch": "bad;name"}, headers=_HDR)
    assert r.status_code == 500
    assert "Invalid branch name" in r.json()["error"]


def test_missing_params(ctx):
    c, _ = ctx
    assert c.get("/api/agents/git/status").status_code == 400
    assert c.get("/api/agents/git/diff", params={"project": "p1"}).status_code == 400
