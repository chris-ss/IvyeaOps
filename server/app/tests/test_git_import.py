"""Unit tests for git_import: URL validation, extraction safety, import flow.

We test against an in-memory tarball so we don't need network or github.
"""
from __future__ import annotations

import io
import tarfile
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
    from app.services import snapshot as snap_mod
    importlib.reload(snap_mod)
    from app.services import git_import as gi_mod
    importlib.reload(gi_mod)
    return skills, gi_mod


# ---------------------------------------------------------------------------
# Tarball builders
# ---------------------------------------------------------------------------


def _build_tar_gz(entries: list[tuple[str, bytes | None, str]]) -> bytes:
    """Build a .tar.gz from a list of (name, content_or_None, type) tuples.

    type is one of "file", "dir", "sym" (symlink, target stored in content as str),
    "link" (hardlink), "abs" (writes an absolute path for traversal tests).
    """
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name, content, kind in entries:
            if kind == "dir":
                info = tarfile.TarInfo(name=name)
                info.type = tarfile.DIRTYPE
                info.mode = 0o755
                tar.addfile(info)
            elif kind == "sym":
                info = tarfile.TarInfo(name=name)
                info.type = tarfile.SYMTYPE
                info.linkname = content.decode() if isinstance(content, bytes) else content
                tar.addfile(info)
            elif kind == "link":
                info = tarfile.TarInfo(name=name)
                info.type = tarfile.LNKTYPE
                info.linkname = content.decode() if isinstance(content, bytes) else content
                tar.addfile(info)
            else:  # file or abs
                data = content if isinstance(content, bytes) else (content or "").encode()
                info = tarfile.TarInfo(name=name)
                info.size = len(data)
                info.mode = 0o644
                tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def _good_skill_tarball(branch: str = "main", repo_name: str = "my-skill") -> bytes:
    """Build a well-formed tarball matching GitHub's layout."""
    top = f"{repo_name}-{branch}"
    return _build_tar_gz([
        (f"{top}/", None, "dir"),
        (f"{top}/SKILL.md", b"---\nname: imported\ndescription: d\n---\n\nbody\n", "file"),
        (f"{top}/references/", None, "dir"),
        (f"{top}/references/notes.md", b"notes\n", "file"),
    ])


# ---------------------------------------------------------------------------
# URL / input validation
# ---------------------------------------------------------------------------


def test_parse_repo_accepts_short_and_url(sandbox):
    _, gi = sandbox
    for good in ["owner/repo", "https://github.com/owner/repo",
                 "https://github.com/owner/repo.git",
                 "https://github.com/owner/repo/"]:
        p = gi._parse_repo(good)
        assert p.owner == "owner" and p.repo == "repo"


def test_parse_repo_rejects_bad(sandbox):
    _, gi = sandbox
    for bad in ["", "justone", "a/../b", "https://gitlab.com/x/y",
                "owner/repo;rm -rf", "owner/repo/extra"]:
        with pytest.raises(HTTPException):
            gi._parse_repo(bad)


def test_validate_branch_and_subdir(sandbox):
    _, gi = sandbox
    assert gi._validate_branch("main") == "main"
    assert gi._validate_branch("release/1.0") == "release/1.0"

    for bad in ["", "../x", "x/..", "x;y", "/abs"]:
        with pytest.raises(HTTPException):
            gi._validate_branch(bad)

    assert gi._validate_subdir(None) == ""
    assert gi._validate_subdir("") == ""
    assert gi._validate_subdir("skills/foo") == "skills/foo"
    for bad in ["../x", "/abs", "x/../y", "x;y"]:
        with pytest.raises(HTTPException):
            gi._validate_subdir(bad)


# ---------------------------------------------------------------------------
# Extraction safety
# ---------------------------------------------------------------------------


def test_extract_rejects_symlink(sandbox, tmp_path):
    _, gi = sandbox
    mal = _build_tar_gz([
        ("repo-main/", None, "dir"),
        ("repo-main/escape", b"/etc/passwd", "sym"),
    ])
    with pytest.raises(HTTPException) as e:
        gi._safe_extract(mal, tmp_path / "out")
    assert e.value.status_code == 400
    assert "symlink" in str(e.value.detail)


def test_extract_rejects_path_traversal(sandbox, tmp_path):
    _, gi = sandbox
    mal = _build_tar_gz([
        ("repo-main/../../../etc/passwd", b"pwned", "file"),
    ])
    with pytest.raises(HTTPException) as e:
        gi._safe_extract(mal, tmp_path / "out")
    assert e.value.status_code == 400


def test_extract_rejects_absolute_path(sandbox, tmp_path):
    _, gi = sandbox
    mal = _build_tar_gz([
        ("/etc/passwd", b"pwned", "file"),
    ])
    with pytest.raises(HTTPException) as e:
        gi._safe_extract(mal, tmp_path / "out")
    assert e.value.status_code == 400


def test_extract_rejects_oversized_file(sandbox, tmp_path):
    _, gi = sandbox
    big = b"A" * (gi._MAX_FILE_BYTES + 1)
    mal = _build_tar_gz([
        ("repo-main/", None, "dir"),
        ("repo-main/huge.bin", big, "file"),
    ])
    with pytest.raises(HTTPException) as e:
        gi._safe_extract(mal, tmp_path / "out")
    assert e.value.status_code == 413


def test_extract_succeeds_on_clean_tarball(sandbox, tmp_path):
    _, gi = sandbox
    out = tmp_path / "out"
    count = gi._safe_extract(_good_skill_tarball(), out)
    assert count == 2   # SKILL.md + notes.md
    assert (out / "my-skill-main" / "SKILL.md").is_file()


# ---------------------------------------------------------------------------
# End-to-end import
# ---------------------------------------------------------------------------


def test_import_happy_path(sandbox):
    skills, gi = sandbox
    tar = _good_skill_tarball(repo_name="my-skill")

    req = gi.GitHubImportRequest(repo="me/my-skill", branch="main")
    res = gi.import_from_github(req, fetcher=lambda _url: tar)

    assert res.imported_name == "my-skill"
    assert res.file_count == 2
    assert res.snapshot_id is not None  # import auto-snapshots
    assert (skills / "my-skill" / "SKILL.md").is_file()
    assert (skills / "my-skill" / "references" / "notes.md").is_file()


def test_import_custom_target_name(sandbox):
    skills, gi = sandbox
    tar = _good_skill_tarball(repo_name="my-skill")

    req = gi.GitHubImportRequest(
        repo="me/my-skill", branch="main", target_name="renamed-skill"
    )
    res = gi.import_from_github(req, fetcher=lambda _url: tar)
    assert res.imported_name == "renamed-skill"
    assert (skills / "renamed-skill" / "SKILL.md").is_file()


def test_import_missing_skill_md_fails(sandbox):
    skills, gi = sandbox
    # Tarball without SKILL.md.
    tar = _build_tar_gz([
        ("repo-main/", None, "dir"),
        ("repo-main/README.md", b"no skill here\n", "file"),
    ])
    req = gi.GitHubImportRequest(repo="me/repo", branch="main")
    with pytest.raises(HTTPException) as e:
        gi.import_from_github(req, fetcher=lambda _url: tar)
    assert e.value.status_code == 400
    assert "SKILL.md" in str(e.value.detail)
    # Nothing should have been written under skills/.
    assert list(skills.iterdir()) == []


def test_import_refuses_existing_target(sandbox):
    skills, gi = sandbox
    (skills / "my-skill").mkdir()
    (skills / "my-skill" / "SKILL.md").write_text("existing", encoding="utf-8")

    tar = _good_skill_tarball(repo_name="my-skill")
    req = gi.GitHubImportRequest(repo="me/my-skill", branch="main")
    with pytest.raises(HTTPException) as e:
        gi.import_from_github(req, fetcher=lambda _url: tar)
    assert e.value.status_code == 409


def test_default_target_name_sanitization(sandbox):
    _, gi = sandbox
    from app.services.git_import import _ParsedRepo, _default_target_name
    assert _default_target_name(_ParsedRepo("u", "My.Skill"), "") == "my-skill"
    assert _default_target_name(_ParsedRepo("u", "repo"), "skills/FooBar") == "foobar"
    # Fallback for non-letter leading:
    assert _default_target_name(_ParsedRepo("u", "123"), "").startswith("imported-")
