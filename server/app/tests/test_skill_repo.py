"""Unit tests for skill_repo: listing, path security, name validation."""
from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi import HTTPException


# IMPORTANT: point skill_paths to a sandbox BEFORE importing skill_repo,
# because skill_paths captures SKILLS_ROOT at import time from the env.
@pytest.fixture
def sandbox_skills(tmp_path: Path, monkeypatch):
    skills = tmp_path / "skills"
    studio = tmp_path / "skill-studio"
    skills.mkdir()
    studio.mkdir()
    monkeypatch.setenv("OPSHUB_SKILLS_ROOT", str(skills))
    monkeypatch.setenv("OPSHUB_STUDIO_ROOT", str(studio))

    # Reload modules so they pick up the new env.
    import importlib
    from app.core import skill_paths as sp_mod
    importlib.reload(sp_mod)
    from app.services import skill_repo as sr_mod
    importlib.reload(sr_mod)
    return skills, sr_mod


def _make_skill(root: Path, rel: str, description: str = "desc", body: str = "body"):
    """Create a minimal valid skill at root/rel/SKILL.md."""
    d = root / rel
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(
        f"---\nname: {rel.split('/')[-1]}\ndescription: \"{description}\"\n---\n\n{body}\n",
        encoding="utf-8",
    )
    return d


def test_list_skills_discovers_nested_and_flat(sandbox_skills):
    skills, sr = sandbox_skills
    _make_skill(skills, "dogfood")
    _make_skill(skills, "research/arxiv")
    _make_skill(skills, "mlops/inference/llama-cpp")

    # Hidden (.archive) skills must be excluded.
    _make_skill(skills, ".archive/old-skill")

    metas = sr.list_skills()
    names = {m.name for m in metas}
    assert names == {"dogfood", "research/arxiv", "mlops/inference/llama-cpp"}

    # Category derivation from path.
    by_name = {m.name: m for m in metas}
    assert by_name["dogfood"].category is None
    assert by_name["research/arxiv"].category == "research"
    assert by_name["mlops/inference/llama-cpp"].category == "mlops/inference"


def test_path_traversal_is_rejected(sandbox_skills):
    skills, sr = sandbox_skills
    _make_skill(skills, "dogfood")

    # Classic traversal attempts — all must 403 or 400, never escape.
    with pytest.raises(HTTPException) as e:
        sr._safe_path("dogfood", "../../../etc/passwd")
    assert e.value.status_code in (400, 403)

    with pytest.raises(HTTPException) as e:
        sr._safe_path("dogfood", "/etc/passwd")
    assert e.value.status_code == 400

    with pytest.raises(HTTPException) as e:
        sr._safe_path("dogfood", "references/../../../../etc/passwd")
    assert e.value.status_code == 400

    # Hidden segment rejection.
    with pytest.raises(HTTPException) as e:
        sr._safe_path("dogfood", ".git/config")
    assert e.value.status_code == 400


def test_symlink_escape_is_rejected(sandbox_skills, tmp_path):
    skills, sr = sandbox_skills
    skill_dir = _make_skill(skills, "dogfood")

    # Plant a symlink inside the skill pointing OUTSIDE the skills root.
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    link = skill_dir / "escape.txt"
    os.symlink(outside, link)

    # Resolving through the symlink must detect the escape.
    with pytest.raises(HTTPException) as e:
        sr._safe_path("dogfood", "escape.txt")
    assert e.value.status_code == 403


def test_name_validation(sandbox_skills):
    _, sr = sandbox_skills

    # Valid cases
    assert sr.validate_skill_name("dogfood") == ["dogfood"]
    assert sr.validate_skill_name("research/arxiv") == ["research", "arxiv"]
    assert sr.validate_skill_name("mlops/inference/llama-cpp") == [
        "mlops", "inference", "llama-cpp",
    ]

    # Invalid cases
    for bad in ["", "UPPER", "bad name", "../x", "x/..", "x/./y",
                ".hidden", "x/.hidden", "1leading-digit",
                "/absolute", "x\\y", "x/" + "a" * 65]:
        with pytest.raises(HTTPException):
            sr.validate_skill_name(bad)


def test_get_skill_returns_frontmatter_and_body(sandbox_skills):
    skills, sr = sandbox_skills
    d = _make_skill(skills, "research/arxiv", description="Find papers")
    (d / "references").mkdir()
    (d / "references" / "api.md").write_text("# API notes\n", encoding="utf-8")

    detail = sr.get_skill("research/arxiv")
    assert detail.name == "research/arxiv"
    assert detail.description == "Find papers"
    assert detail.frontmatter.get("name") == "arxiv"
    assert "body" in detail.content_body
    paths = {f.path for f in detail.linked_files}
    assert "references/api.md" in paths


def test_missing_skill_returns_404(sandbox_skills):
    _, sr = sandbox_skills
    with pytest.raises(HTTPException) as e:
        sr.get_skill("does-not-exist")
    assert e.value.status_code == 404
