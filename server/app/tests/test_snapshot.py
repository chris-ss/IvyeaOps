"""Unit tests for snapshot: create/list/diff/restore/prune."""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import HTTPException


@pytest.fixture
def sandbox(tmp_path: Path, monkeypatch):
    """Point both roots at a fresh tmp dir and reload the modules."""
    skills = tmp_path / "skills"
    studio = tmp_path / "skill-studio"
    skills.mkdir()
    studio.mkdir()
    monkeypatch.setenv("OPSHUB_SKILLS_ROOT", str(skills))
    monkeypatch.setenv("OPSHUB_STUDIO_ROOT", str(studio))

    import importlib
    from app.core import skill_paths as sp_mod
    importlib.reload(sp_mod)
    # ensure_studio_dirs was called at app startup only — replicate here.
    sp_mod.ensure_studio_dirs()
    from app.services import skill_repo as sr_mod
    importlib.reload(sr_mod)
    from app.services import snapshot as snap_mod
    importlib.reload(snap_mod)
    return skills, snap_mod


def _make_skill(root: Path, name: str, body: str = "original body"):
    d = root / name
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(
        f"---\nname: {name.split('/')[-1]}\ndescription: \"d\"\n---\n\n{body}\n",
        encoding="utf-8",
    )
    return d


def test_create_and_list_snapshot(sandbox):
    skills, snap = sandbox
    _make_skill(skills, "dogfood")

    meta = snap.create_snapshot("dogfood", label="initial")
    assert meta.label == "initial"
    assert meta.file_count == 1  # only SKILL.md, sidecar excluded

    metas = snap.list_snapshots("dogfood")
    assert len(metas) == 1
    assert metas[0].id == meta.id


def test_diff_detects_modifications(sandbox):
    skills, snap = sandbox
    d = _make_skill(skills, "dogfood", body="version A")

    s1 = snap.create_snapshot("dogfood", label="A")

    # Mutate the skill
    (d / "SKILL.md").write_text(
        "---\nname: dogfood\ndescription: \"d\"\n---\n\nversion B\n",
        encoding="utf-8",
    )
    (d / "newfile.md").write_text("hello", encoding="utf-8")

    diff = snap.diff_snapshot("dogfood", s1.id)
    by_path = {f.path: f for f in diff.files}

    assert by_path["SKILL.md"].status == "modified"
    assert "version A" in by_path["SKILL.md"].diff
    assert "version B" in by_path["SKILL.md"].diff
    assert by_path["newfile.md"].status == "added"


def test_restore_roundtrips_content(sandbox):
    skills, snap = sandbox
    d = _make_skill(skills, "dogfood", body="before")

    s1 = snap.create_snapshot("dogfood", label="before")

    # Mutate
    (d / "SKILL.md").write_text(
        "---\nname: dogfood\ndescription: \"d\"\n---\n\nafter\n",
        encoding="utf-8",
    )
    (d / "stray.md").write_text("junk", encoding="utf-8")

    result = snap.restore_snapshot("dogfood", s1.id)
    assert result["restored_from"] == s1.id
    assert result["pre_restore_snapshot_id"] is not None

    # Content reverted, stray file gone, sidecar not restored.
    assert "before" in d.joinpath("SKILL.md").read_text()
    assert not (d / "stray.md").exists()
    assert not (d / ".snapshot.json").exists()

    # A pre-restore snapshot now exists alongside the original.
    metas = snap.list_snapshots("dogfood")
    labels = [m.label for m in metas]
    assert any(l and "pre-restore" in l for l in labels)


def test_prune_respects_retention(sandbox):
    skills, snap = sandbox
    _make_skill(skills, "dogfood")

    # Create 25 snapshots; retention default is 20.
    for i in range(25):
        snap.create_snapshot("dogfood", label=f"s{i}")

    metas = snap.list_snapshots("dogfood")
    assert len(metas) == 20  # pruned to retention
    # Newest preserved, oldest 5 dropped.
    labels = [m.label for m in metas]
    assert "s24" in labels
    assert "s0" not in labels


def test_invalid_snapshot_id_is_rejected(sandbox):
    skills, snap = sandbox
    _make_skill(skills, "dogfood")

    for bad in ["", "abc", "../../../etc", "../x", "20260101_120000"]:
        with pytest.raises(HTTPException) as e:
            snap._snapshot_dir("dogfood", bad)
        assert e.value.status_code in (400, 404)
