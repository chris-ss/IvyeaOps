"""Trash (recycle bin) for deleted skills, with 7-day TTL.

``trash_skill(name)`` atomically renames the skill dir into
``STUDIO_ROOT/trash/<name>.<ts>/`` and drops a sidecar with metadata.

``restore_from_trash(trash_id, target_name=None)`` moves it back under
SKILLS_ROOT. If the original name is now taken, the caller must pick a
new one via ``target_name`` (or we'll 409).

``purge_expired(now=None)`` is a best-effort sweeper that removes trash
entries older than ``TTL_DAYS`` days. Called on startup and on demand.

The trash ID format mirrors snapshots: ``<flattened_name>.<YYYYMMDD_HHMMSS_<6hex>>``.
Skills with slashes get flattened to underscores in the trash ID only;
the sidecar records the original forward-slash name for restore.
"""
from __future__ import annotations

import json
import os
import re
import secrets
import shutil
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import HTTPException
from pydantic import BaseModel

from app.core.skill_paths import TRASH_DIR
from app.services.skill_repo import (
    _is_under,
    _resolved_skills_root,
    validate_skill_name,
)


TTL_DAYS = 7
_SIDECAR = ".trash.json"
_TRASH_ID_RE = re.compile(r"^[a-z0-9_-]+\.\d{8}_\d{6}_[0-9a-f]{6}$")


class TrashEntry(BaseModel):
    id: str
    original_name: str
    trashed_at: datetime
    expires_at: datetime
    size_bytes: int
    file_count: int


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------


def _resolved_trash_root() -> Path:
    return TRASH_DIR.resolve()


def _validate_trash_id(tid: str) -> None:
    if not tid or not isinstance(tid, str) or not _TRASH_ID_RE.match(tid):
        raise HTTPException(400, f"invalid trash id: {tid!r}")


def _trash_entry_dir(trash_id: str) -> Path:
    _validate_trash_id(trash_id)
    root = _resolved_trash_root()
    d = (root / trash_id).resolve()
    if not _is_under(d, root):
        raise HTTPException(403, "trash path escape detected")
    if not d.is_dir():
        raise HTTPException(404, f"trash entry not found: {trash_id}")
    return d


def _skill_dir(name: str) -> Path:
    validate_skill_name(name)
    root = _resolved_skills_root()
    d = (root / name).resolve()
    if not _is_under(d, root):
        raise HTTPException(403, "skill path escape detected")
    if not d.is_dir():
        raise HTTPException(404, f"skill not found: {name}")
    return d


def _flatten_name(name: str) -> str:
    return name.replace("/", "_")


def _new_trash_id(name: str) -> str:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{_flatten_name(name)}.{ts}_{secrets.token_hex(3)}"


def _read_sidecar(d: Path) -> dict:
    sc = d / _SIDECAR
    if not sc.is_file():
        return {}
    try:
        return json.loads(sc.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _dir_stats(directory: Path) -> tuple[int, int]:
    total = 0
    count = 0
    for p in directory.rglob("*"):
        if p.is_file() and p.name != _SIDECAR:
            try:
                total += p.stat().st_size
                count += 1
            except OSError:
                pass
    return total, count


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def trash_skill(name: str) -> TrashEntry:
    """Move a skill into the trash and return the entry metadata."""
    src = _skill_dir(name)
    trash_root = _resolved_trash_root()
    trash_root.mkdir(parents=True, exist_ok=True)

    trash_id = _new_trash_id(name)
    dst = trash_root / trash_id

    # Atomic rename if same FS; fall back to copy+rmtree otherwise.
    try:
        os.rename(src, dst)
    except OSError:
        shutil.copytree(src, dst, symlinks=False)
        shutil.rmtree(src, ignore_errors=True)

    now = datetime.now()
    sidecar = {
        "id": trash_id,
        "original_name": name,
        "trashed_at": now.isoformat(),
        "expires_at": (now + timedelta(days=TTL_DAYS)).isoformat(),
    }
    (dst / _SIDECAR).write_text(
        json.dumps(sidecar, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return _entry_for(dst)


def _entry_for(d: Path) -> TrashEntry:
    sc = _read_sidecar(d)
    size, count = _dir_stats(d)
    try:
        trashed_at = datetime.fromisoformat(sc.get("trashed_at")) if sc.get("trashed_at") \
            else datetime.fromtimestamp(d.stat().st_mtime)
    except (ValueError, OSError):
        trashed_at = datetime.fromtimestamp(0)
    try:
        expires_at = datetime.fromisoformat(sc.get("expires_at")) if sc.get("expires_at") \
            else trashed_at + timedelta(days=TTL_DAYS)
    except ValueError:
        expires_at = trashed_at + timedelta(days=TTL_DAYS)
    return TrashEntry(
        id=d.name,
        original_name=sc.get("original_name", d.name),
        trashed_at=trashed_at,
        expires_at=expires_at,
        size_bytes=size,
        file_count=count,
    )


def list_trash() -> list[TrashEntry]:
    root = _resolved_trash_root()
    if not root.is_dir():
        return []
    entries: list[TrashEntry] = []
    for d in root.iterdir():
        if d.is_dir() and _TRASH_ID_RE.match(d.name):
            entries.append(_entry_for(d))
    entries.sort(key=lambda e: e.trashed_at, reverse=True)
    return entries


def restore_from_trash(trash_id: str, target_name: str | None = None) -> str:
    """Restore a trashed skill back under SKILLS_ROOT. Returns the restored name."""
    d = _trash_entry_dir(trash_id)
    sc = _read_sidecar(d)
    name = target_name or sc.get("original_name")
    if not name:
        raise HTTPException(500, "trash entry missing original_name; pass target_name")
    validate_skill_name(name)

    root = _resolved_skills_root()
    target = (root / name).resolve()
    if not _is_under(target, root):
        raise HTTPException(403, "restore target escape detected")
    if target.exists():
        raise HTTPException(409, f"skill '{name}' already exists; pick another target_name")

    target.parent.mkdir(parents=True, exist_ok=True)

    # Remove sidecar before moving — we don't want to pollute SKILLS_ROOT with it.
    sidecar_path = d / _SIDECAR
    if sidecar_path.is_file():
        try:
            sidecar_path.unlink()
        except OSError:
            pass

    try:
        os.rename(d, target)
    except OSError:
        shutil.copytree(d, target, symlinks=False)
        shutil.rmtree(d, ignore_errors=True)
    return name


def delete_permanently(trash_id: str) -> None:
    d = _trash_entry_dir(trash_id)
    shutil.rmtree(d)


def purge_expired(now: datetime | None = None) -> int:
    """Delete trash entries past their TTL. Returns number purged."""
    now = now or datetime.now()
    purged = 0
    for entry in list_trash():
        if entry.expires_at <= now:
            try:
                delete_permanently(entry.id)
                purged += 1
            except HTTPException:
                continue
            except OSError:
                continue
    return purged
