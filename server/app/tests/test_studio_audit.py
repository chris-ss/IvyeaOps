"""Unit tests for studio_audit: append, tail, silent failure on I/O."""
from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def sandbox(tmp_path: Path, monkeypatch):
    skills = tmp_path / "skills"
    studio = tmp_path / "skill-studio"
    skills.mkdir()
    studio.mkdir()
    monkeypatch.setenv("OPSHUB_SKILLS_ROOT", str(skills))
    monkeypatch.setenv("OPSHUB_STUDIO_ROOT", str(studio))

    import importlib
    from app.core import skill_paths as sp_mod
    importlib.reload(sp_mod)
    sp_mod.ensure_studio_dirs()
    from app.services import studio_audit as audit_mod
    importlib.reload(audit_mod)
    return studio, audit_mod


def test_record_and_tail_roundtrip(sandbox):
    _, audit = sandbox
    audit.record("skill.create", actor="alice", skill_name="foo",
                 details={"size": 123})
    audit.record("skill.update", actor="alice", skill_name="foo",
                 details={"file": "SKILL.md"})

    events = audit.tail(limit=10)
    assert len(events) == 2
    # Newest first.
    assert events[0]["event_type"] == "skill.update"
    assert events[0]["actor"] == "alice"
    assert events[1]["event_type"] == "skill.create"
    assert events[1]["details"]["size"] == 123


def test_tail_limit_caps(sandbox):
    _, audit = sandbox
    for i in range(20):
        audit.record("test.event", actor="bot", details={"i": i})

    events = audit.tail(limit=5)
    assert len(events) == 5
    # Most recent first: i=19, 18, 17, 16, 15
    assert [e["details"]["i"] for e in events] == [19, 18, 17, 16, 15]


def test_tail_ignores_malformed_lines(sandbox):
    studio, audit = sandbox
    from app.core.skill_paths import AUDIT_LOG_FILE as AUDIT_LOG

    audit.record("good.event", actor="a", details={})
    # Inject a malformed line directly.
    with open(AUDIT_LOG, "a", encoding="utf-8") as f:
        f.write("not-json-at-all\n")
    audit.record("another.good", actor="b", details={})

    events = audit.tail(limit=10)
    # Malformed line dropped; two good lines survive.
    assert len(events) == 2
    types = [e["event_type"] for e in events]
    assert "good.event" in types and "another.good" in types


def test_record_swallows_io_errors(sandbox, monkeypatch):
    _, audit = sandbox
    # Make open() fail; record() must not raise.
    def boom(*a, **kw):
        raise OSError("disk full")
    monkeypatch.setattr("builtins.open", boom)
    # No raise expected.
    audit.record("skill.create", actor="alice")
