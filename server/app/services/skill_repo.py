"""Skill repository: models + listing + detail + path security.

SKILL NAME CONVENTION
---------------------
A skill's ``name`` is its forward-slash-separated path relative to
``SKILLS_ROOT``. Examples::

    dogfood
    research/arxiv
    mlops/inference/llama-cpp

Each **segment** must match ``^[a-z][a-z0-9_-]{1,63}$``. Any path that
contains a hidden segment (starts with ``.``) is excluded from the listing
entirely (e.g. ``.archive/``, ``.snapshots/``).

PATH SECURITY
-------------
``_safe_path`` is the single choke point for turning an untrusted
``(skill_name, rel_path)`` pair into a concrete filesystem path. It:

  * validates every segment of ``skill_name``,
  * refuses ``rel_path`` with absolute paths, ``..`` segments, or hidden
    segments,
  * resolves the final path and asserts it lives under the skill dir,
    catching symlink escapes (Path.resolve follows symlinks).

Callers pass arbitrary user input to this helper — do NOT build paths any
other way.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

import yaml
from fastapi import HTTPException
from pydantic import BaseModel

from app.core.skill_paths import SKILLS_ROOT


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

_SEGMENT_RE = re.compile(r"^[a-z][a-z0-9_-]{1,63}$")

# Cheap sniff for binaries: a NUL byte in the first 8KB is a dead giveaway.
# Real file(1) magic-number detection would be nicer but pulls in libmagic.
_BIN_SNIFF_BYTES = 8192


def validate_skill_name(name: str) -> list[str]:
    """Validate a skill name and return its segments.

    Raises HTTPException(400) with a human-readable message on failure.
    """
    if not name or not isinstance(name, str):
        raise HTTPException(400, "skill name must be a non-empty string")
    if name.startswith("/") or "\\" in name:
        raise HTTPException(400, "skill name must not contain absolute/backslash paths")
    segments = [s for s in name.split("/") if s != ""]
    if not segments:
        raise HTTPException(400, "skill name is empty")
    for seg in segments:
        if seg in (".", ".."):
            raise HTTPException(400, f"skill name segment '{seg}' is not allowed")
        if seg.startswith("."):
            raise HTTPException(400, f"hidden segment '{seg}' is not allowed")
        if not _SEGMENT_RE.match(seg):
            raise HTTPException(
                400,
                f"invalid skill name segment '{seg}'; must match ^[a-z][a-z0-9_-]{{1,63}}$",
            )
    return segments


# ---------------------------------------------------------------------------
# Safe path resolution
# ---------------------------------------------------------------------------

def _resolved_skills_root() -> Path:
    """Resolve once per call; env overrides in tests need this fresh."""
    return SKILLS_ROOT.resolve()


def _safe_skill_dir(name: str) -> Path:
    """Resolve and return the skill directory, raising if missing or escaped."""
    validate_skill_name(name)
    root = _resolved_skills_root()
    candidate = (root / name).resolve()
    if not _is_under(candidate, root):
        raise HTTPException(403, "skill path escape detected")
    if not candidate.is_dir():
        raise HTTPException(404, f"skill not found: {name}")
    return candidate


def _safe_path(name: str, rel_path: str | None) -> Path:
    """Resolve a safe (skill_name, rel_path) pair.

    If rel_path is None/empty, returns the skill directory itself.
    """
    skill_dir = _safe_skill_dir(name)
    if not rel_path:
        return skill_dir

    # Reject obviously hostile inputs BEFORE any filesystem access.
    if rel_path.startswith("/") or "\\" in rel_path:
        raise HTTPException(400, "rel_path must be relative with forward slashes")
    parts = [p for p in rel_path.split("/") if p != ""]
    for p in parts:
        if p in (".", "..") or p.startswith("."):
            raise HTTPException(400, f"rel_path segment '{p}' is not allowed")

    candidate = (skill_dir / "/".join(parts)).resolve()
    if not _is_under(candidate, skill_dir):
        raise HTTPException(403, "path escape detected")
    return candidate


def _is_under(child: Path, parent: Path) -> bool:
    """Path.is_relative_to exists in 3.9+, but we go string-based for safety
    across symlinked roots (both already resolved by caller)."""
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class FileEntry(BaseModel):
    path: str            # relative to the skill dir, forward slashes
    size: int
    mtime: datetime
    is_binary: bool


class SkillMeta(BaseModel):
    name: str            # forward-slash path, e.g. "research/arxiv"
    category: str | None
    description: str | None
    description_zh: str | None = None
    pinned: bool
    editable: bool
    source: str          # "user" for MVP; "plugin:..."/"system" reserved
    updated_at: datetime
    size_bytes: int
    file_count: int


class SkillDetail(SkillMeta):
    frontmatter: dict
    content_body: str
    linked_files: list[FileEntry]


# ---------------------------------------------------------------------------
# Frontmatter parsing
# ---------------------------------------------------------------------------


_FRONTMATTER_RE = re.compile(
    r"^---\s*\n(.*?)\n---\s*\n(.*)$", re.DOTALL
)


def _parse_skill_md(text: str) -> tuple[dict, str]:
    """Return (frontmatter_dict, body). Malformed frontmatter yields ({}, text)."""
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return {}, text
    try:
        fm = yaml.safe_load(m.group(1)) or {}
        if not isinstance(fm, dict):
            fm = {}
    except yaml.YAMLError:
        fm = {}
    return fm, m.group(2)


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _SkillCandidate:
    name: str
    dir: Path
    skill_md: Path


def _iter_skill_candidates(root: Path) -> Iterable[_SkillCandidate]:
    """Walk SKILLS_ROOT and yield every SKILL.md, skipping hidden segments.

    Depth isn't fixed — Hermes mixes 2/3/4-level layouts (``dogfood``,
    ``research/arxiv``, ``mlops/inference/llama-cpp``). We just recurse and
    emit on every ``SKILL.md`` found, with the relative path as the name.
    """
    if not root.is_dir():
        return
    for skill_md in root.rglob("SKILL.md"):
        try:
            rel = skill_md.parent.relative_to(root)
        except ValueError:
            continue
        parts = rel.parts
        if not parts:
            continue  # SKILL.md directly at root — not a real skill layout
        if any(p.startswith(".") for p in parts):
            continue  # .archive, .snapshots, etc.
        # Only emit candidates whose segments are all valid names. Invalid
        # names are simply skipped (rather than raising) so a single malformed
        # directory can't break the whole listing.
        if not all(_SEGMENT_RE.match(p) for p in parts):
            continue
        name = "/".join(parts)
        yield _SkillCandidate(name=name, dir=skill_md.parent, skill_md=skill_md)


def _dir_stats(directory: Path) -> tuple[int, int]:
    """Return (total_size_bytes, file_count) for directory, recursively."""
    total = 0
    count = 0
    for p in directory.rglob("*"):
        if p.is_file():
            try:
                total += p.stat().st_size
                count += 1
            except OSError:
                pass
    return total, count


def _is_binary_file(path: Path) -> bool:
    try:
        with path.open("rb") as f:
            chunk = f.read(_BIN_SNIFF_BYTES)
    except OSError:
        return False
    return b"\x00" in chunk


def _meta_from_candidate(cand: _SkillCandidate) -> SkillMeta:
    try:
        text = cand.skill_md.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        text = ""
    fm, _body = _parse_skill_md(text)
    size, count = _dir_stats(cand.dir)

    # Category: frontmatter wins; otherwise derive from parent path segments.
    category = fm.get("category")
    if not category:
        segs = cand.name.split("/")
        category = "/".join(segs[:-1]) if len(segs) > 1 else None

    try:
        mtime = datetime.fromtimestamp(cand.skill_md.stat().st_mtime)
    except OSError:
        mtime = datetime.fromtimestamp(0)

    return SkillMeta(
        name=cand.name,
        category=category,
        description=(fm.get("description") or "").strip() or None,
        description_zh=(fm.get("description_zh") or "").strip() or None,
        pinned=bool(fm.get("pinned", False)),
        editable=True,  # MVP: everything under SKILLS_ROOT is editable
        source="user",
        updated_at=mtime,
        size_bytes=size,
        file_count=count,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def list_skills() -> list[SkillMeta]:
    """Return every skill under SKILLS_ROOT, excluding hidden paths."""
    root = _resolved_skills_root()
    metas: list[SkillMeta] = []
    for cand in _iter_skill_candidates(root):
        metas.append(_meta_from_candidate(cand))
    # Stable sort: recently edited first, ties broken by name.
    metas.sort(key=lambda m: (-m.updated_at.timestamp(), m.name))
    return metas


def get_skill(name: str) -> SkillDetail:
    """Load full skill detail (metadata + SKILL.md body + linked files)."""
    skill_dir = _safe_skill_dir(name)
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.is_file():
        raise HTTPException(404, f"SKILL.md missing in {name}")

    try:
        text = skill_md.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        raise HTTPException(500, f"failed to read SKILL.md: {e}") from e
    fm, body = _parse_skill_md(text)
    size, count = _dir_stats(skill_dir)

    segs = name.split("/")
    category = fm.get("category") or ("/".join(segs[:-1]) if len(segs) > 1 else None)

    try:
        mtime = datetime.fromtimestamp(skill_md.stat().st_mtime)
    except OSError:
        mtime = datetime.fromtimestamp(0)

    # Enumerate linked files from the conventional sub-dirs.
    linked: list[FileEntry] = []
    for sub in ("references", "templates", "scripts", "assets"):
        sub_dir = skill_dir / sub
        if not sub_dir.is_dir():
            continue
        for p in sorted(sub_dir.rglob("*")):
            if p.is_file():
                try:
                    rel = p.relative_to(skill_dir)
                    st = p.stat()
                except OSError:
                    continue
                linked.append(
                    FileEntry(
                        path=str(rel).replace("\\", "/"),
                        size=st.st_size,
                        mtime=datetime.fromtimestamp(st.st_mtime),
                        is_binary=_is_binary_file(p),
                    )
                )

    return SkillDetail(
        name=name,
        category=category,
        description=(fm.get("description") or "").strip() or None,
        description_zh=(fm.get("description_zh") or "").strip() or None,
        pinned=bool(fm.get("pinned", False)),
        editable=True,
        source="user",
        updated_at=mtime,
        size_bytes=size,
        file_count=count,
        frontmatter=fm,
        content_body=body,
        linked_files=linked,
    )


# ---------------------------------------------------------------------------
# Write helpers
# ---------------------------------------------------------------------------


_MAX_WRITE_BYTES = 2 * 1024 * 1024       # 2 MB per file
_MAX_FILES_PER_SKILL = 500


def _serialize_skill_md(frontmatter: dict, body: str) -> str:
    """Emit `---\\n<yaml>---\\n\\n<body>`. YAML uses safe_dump."""
    yml = yaml.safe_dump(
        frontmatter or {},
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
    ).rstrip() + "\n"
    body = body or ""
    if not body.endswith("\n"):
        body += "\n"
    return f"---\n{yml}---\n\n{body}"


def create_skill(
    name: str,
    description: str | None = None,
    body: str = "",
    frontmatter_extras: dict | None = None,
) -> SkillMeta:
    """Create a new skill dir containing a minimal SKILL.md. Fails if exists."""
    validate_skill_name(name)
    root = _resolved_skills_root()
    target = (root / name).resolve()
    if not _is_under(target, root):
        raise HTTPException(403, "skill path escape detected")
    if target.exists():
        raise HTTPException(409, f"skill '{name}' already exists")

    fm: dict = {
        "name": name.split("/")[-1],
        "description": (description or "").strip(),
    }
    if frontmatter_extras:
        # Never let the caller override the canonical name field.
        for k, v in frontmatter_extras.items():
            if k == "name":
                continue
            fm[k] = v

    target.parent.mkdir(parents=True, exist_ok=True)
    target.mkdir()
    (target / "SKILL.md").write_text(
        _serialize_skill_md(fm, body), encoding="utf-8"
    )

    # Re-stat and return a meta so caller can jump straight to the new skill.
    return _meta_from_candidate(_SkillCandidate(
        name=name, dir=target, skill_md=target / "SKILL.md",
    ))


def update_skill_md(name: str, frontmatter: dict, body: str) -> SkillMeta:
    """Overwrite SKILL.md with the given frontmatter+body."""
    skill_dir = _safe_skill_dir(name)
    skill_md = skill_dir / "SKILL.md"
    content = _serialize_skill_md(frontmatter or {}, body or "")
    _atomic_write(skill_md, content.encode("utf-8"))
    return _meta_from_candidate(_SkillCandidate(
        name=name, dir=skill_dir, skill_md=skill_md,
    ))


def write_file(name: str, rel_path: str, content: str) -> FileEntry:
    """Create or overwrite a file inside a skill. rel_path goes through _safe_path."""
    # SKILL.md must go through update_skill_md, not this generic writer.
    if rel_path in ("SKILL.md", "./SKILL.md"):
        raise HTTPException(400, "use the update endpoint for SKILL.md")
    target = _safe_path(name, rel_path)

    # Count existing files to enforce per-skill cap.
    skill_dir = _safe_skill_dir(name)
    existing = sum(1 for p in skill_dir.rglob("*") if p.is_file())
    if not target.exists() and existing >= _MAX_FILES_PER_SKILL:
        raise HTTPException(
            413, f"skill exceeds {_MAX_FILES_PER_SKILL} file limit"
        )

    data = content.encode("utf-8")
    if len(data) > _MAX_WRITE_BYTES:
        raise HTTPException(413, f"content exceeds {_MAX_WRITE_BYTES} byte limit")

    target.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write(target, data)

    st = target.stat()
    return FileEntry(
        path=str(target.relative_to(skill_dir)).replace("\\", "/"),
        size=st.st_size,
        mtime=datetime.fromtimestamp(st.st_mtime),
        is_binary=False,
    )


def delete_file(name: str, rel_path: str) -> None:
    """Delete a file inside a skill. Rejects SKILL.md deletion."""
    if rel_path in ("SKILL.md", "./SKILL.md"):
        raise HTTPException(400, "cannot delete SKILL.md; delete the whole skill instead")
    target = _safe_path(name, rel_path)
    if target.is_dir():
        raise HTTPException(400, "rel_path is a directory, not a file")
    if not target.is_file():
        raise HTTPException(404, f"file not found: {rel_path}")
    target.unlink()


def rename_skill(name: str, new_name: str) -> SkillMeta:
    """Rename a skill directory (possibly across categories)."""
    src = _safe_skill_dir(name)
    validate_skill_name(new_name)
    if new_name == name:
        raise HTTPException(400, "new name equals current name")

    root = _resolved_skills_root()
    dst = (root / new_name).resolve()
    if not _is_under(dst, root):
        raise HTTPException(403, "target path escape detected")
    if dst.exists():
        raise HTTPException(409, f"skill '{new_name}' already exists")

    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        src.rename(dst)
    except OSError as e:
        raise HTTPException(500, f"rename failed: {e}") from e

    return _meta_from_candidate(_SkillCandidate(
        name=new_name, dir=dst, skill_md=dst / "SKILL.md",
    ))


def _atomic_write(target: Path, data: bytes) -> None:
    """Write then fsync then atomic-rename. Limits blast radius of partial writes."""
    import os
    tmp = target.with_suffix(target.suffix + ".tmp")
    try:
        with open(tmp, "wb") as f:
            f.write(data)
            f.flush()
            try:
                os.fsync(f.fileno())
            except OSError:
                pass
        os.replace(tmp, target)
    except OSError as e:
        # Best-effort cleanup of the staging file.
        try:
            tmp.unlink()
        except OSError:
            pass
        raise HTTPException(500, f"write failed: {e}") from e
