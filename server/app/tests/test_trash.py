"""Unit tests for trash: trash/list/restore/purge_expired."""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest
from fastapi import HTTPException


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
    from app.services import skill_repo as sr_mod
    importlib.reload(sr_mod)
    from app.services import trash as trash_mod
    importlib.reload(trash_mod)
    return skills, trash_mod


def _make_skill(root: Path, name: str):
    d = root / name
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(
        f"---\nname: {name.split('/')[-1]}\ndescription: d\n---\nbody\n",
        encoding="utf-8",
    )
    return d


def test_trash_moves_skill_out_of_skills_root(sandbox):
    skills, trash = sandbox
    d = _make_skill(skills, "dogfood")
    entry = trash.trash_skill("dogfood")

    assert not d.exists()  # original gone
    assert entry.original_name == "dogfood"
    listed = trash.list_trash()
    assert len(listed) == 1
    assert listed[0].id == entry.id


def test_restore_from_trash(sandbox):
    skills, trash = sandbox
    _make_skill(skills, "dogfood")
    entry = trash.trash_skill("dogfood")

    restored = trash.restore_from_trash(entry.id)
    assert restored == "dogfood"
    assert (skills / "dogfood" / "SKILL.md").is_file()
    # Sidecar must NOT leak into the restored skill.
    assert not (skills / "dogfood" / ".trash.json").exists()
    # Trash entry gone.
    assert trash.list_trash() == []


def test_restore_refuses_when_target_exists(sandbox):
    skills, trash = sandbox
    _make_skill(skills, "dogfood")
    entry = trash.trash_skill("dogfood")

    # Recreate a skill with the same name before restoring.
    _make_skill(skills, "dogfood")

    with pytest.raises(HTTPException) as e:
        trash.restore_from_trash(entry.id)
    assert e.value.status_code == 409

    # But caller can rename on restore.
    restored = trash.restore_from_trash(entry.id, target_name="dogfood-v2")
    assert restored == "dogfood-v2"
    assert (skills / "dogfood-v2" / "SKILL.md").is_file()


def test_nested_skill_name_flattens_in_trash_id(sandbox):
    skills, trash = sandbox
    _make_skill(skills, "research/arxiv")
    entry = trash.trash_skill("research/arxiv")
    assert entry.id.startswith("research_arxiv.")
    assert entry.original_name == "research/arxiv"

    restored = trash.restore_from_trash(entry.id)
    assert restored == "research/arxiv"
    assert (skills / "research" / "arxiv" / "SKILL.md").is_file()


def test_purge_expired_removes_old_entries(sandbox):
    skills, trash = sandbox
    _make_skill(skills, "dogfood")
    entry = trash.trash_skill("dogfood")

    # Simulate 8 days passing — entry should be purged.
    future = datetime.fromisoformat(entry.expires_at.isoformat()) + timedelta(days=1)
    purged = trash.purge_expired(now=future)
    assert purged == 1
    assert trash.list_trash() == []


def test_purge_does_not_touch_fresh_entries(sandbox):
    skills, trash = sandbox
    _make_skill(skills, "dogfood")
    trash.trash_skill("dogfood")

    purged = trash.purge_expired(now=datetime.now())
    assert purged == 0
    assert len(trash.list_trash()) == 1
