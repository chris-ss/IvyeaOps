"""Execution-history store tests (skill_runs) + param substitution."""
from __future__ import annotations

import time

from app.services import skill_runs
from app.routers import skill_tools as st


def _rec(name="amazon/keyword-report", output="hello world", status="done"):
    return skill_runs.record_run(
        skill_name=name, user="tester", params={"keyword": "yoga mat"},
        output=output, provider="deepseek", runtime="llm-only",
        status=status, started_at=time.time(), elapsed_s=1.2, error=None,
    )


def test_record_list_get_delete():
    rec = _rec()
    assert rec["id"]
    assert rec["skill_name"] == "amazon/keyword-report"

    runs = skill_runs.list_runs("amazon/keyword-report")
    assert len(runs) == 1
    # list view is a summary: preview, no full output key
    assert "output" not in runs[0]
    assert runs[0]["preview"].startswith("hello")

    full = skill_runs.get_run("amazon/keyword-report", rec["id"])
    assert full["output"] == "hello world"

    assert skill_runs.delete_run("amazon/keyword-report", rec["id"]) is True
    assert skill_runs.get_run("amazon/keyword-report", rec["id"]) is None


def test_retention_prune(monkeypatch):
    monkeypatch.setattr(skill_runs, "_MAX_PER_SKILL", 2)
    for i in range(4):
        skill_runs.record_run(
            skill_name="cat/prune-me", user="t", params={}, output=f"run{i}",
            provider="deepseek", runtime="llm-only", status="done",
            started_at=time.time() + i, elapsed_s=0.1,
        )
    runs = skill_runs.list_runs("cat/prune-me")
    assert len(runs) == 2  # capped


def test_get_run_rejects_path_escape():
    assert skill_runs.get_run("x", "../../etc/passwd") is None
    assert skill_runs.delete_run("x", "..") is False


def test_fill_params():
    body = "针对 {{keyword}} 在 {{site}} 生成报告"
    out = st._fill_params(body, {"keyword": "mat", "site": "US"})
    assert out == "针对 mat 在 US 生成报告"
