"""Lightweight execution-history store for skill tools.

Every run of a skill tool (via ``/api/skill-tools/run``) is persisted as one
JSON file under ``STUDIO_ROOT/runs/<safe_skill>/<run_id>.json`` so report-type
tools no longer throw away their (often valuable) output. Retention is capped
per skill so the store can't grow unbounded.

This lives under STUDIO_ROOT (studio bookkeeping), deliberately outside
SKILLS_ROOT so the Hermes skill scanner never sees it.
"""
from __future__ import annotations

import json
import re
import time
import uuid
from pathlib import Path
from typing import Any

from app.core.skill_paths import STUDIO_ROOT

_MAX_PER_SKILL = 50
_PREVIEW_CHARS = 240
_SAFE_RE = re.compile(r"[^a-zA-Z0-9_-]+")


def _runs_root() -> Path:
    return STUDIO_ROOT / "runs"


def _skill_dir(skill_name: str) -> Path:
    """Flatten a slash-separated skill name into a single safe directory key."""
    key = _SAFE_RE.sub("_", skill_name or "").strip("_") or "_unnamed"
    return _runs_root() / key


def _summary(rec: dict) -> dict:
    """List view: drop the full output, keep a short preview."""
    out = rec.get("output") or ""
    return {
        "id": rec.get("id"),
        "skill_name": rec.get("skill_name"),
        "status": rec.get("status"),
        "provider": rec.get("provider"),
        "runtime": rec.get("runtime"),
        "started_at": rec.get("started_at"),
        "elapsed_s": rec.get("elapsed_s"),
        "error": rec.get("error"),
        "params": rec.get("params") or {},
        "preview": out[:_PREVIEW_CHARS],
    }


def record_run(
    *,
    skill_name: str,
    user: str,
    params: dict[str, Any],
    output: str,
    provider: str,
    runtime: str,
    status: str,
    started_at: float,
    elapsed_s: float,
    error: str | None = None,
) -> dict:
    """Persist one run record and return it. Best-effort: prunes old runs."""
    d = _skill_dir(skill_name)
    d.mkdir(parents=True, exist_ok=True)
    # Timestamp prefix keeps filenames chronologically sortable.
    run_id = time.strftime("%Y%m%d-%H%M%S", time.localtime(started_at)) + "-" + uuid.uuid4().hex[:6]
    rec = {
        "id": run_id,
        "skill_name": skill_name,
        "user": user,
        "params": params or {},
        "output": output or "",
        "provider": provider,
        "runtime": runtime,
        "status": status,
        "started_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(started_at)),
        "elapsed_s": elapsed_s,
        "error": error,
    }
    (d / f"{run_id}.json").write_text(
        json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    _prune(d)
    return rec


def _prune(d: Path) -> None:
    files = sorted(d.glob("*.json"))  # chronological by name
    excess = len(files) - _MAX_PER_SKILL
    for f in files[:max(0, excess)]:
        try:
            f.unlink()
        except OSError:
            pass


def list_runs(skill_name: str, limit: int = 50) -> list[dict]:
    d = _skill_dir(skill_name)
    if not d.is_dir():
        return []
    out: list[dict] = []
    for f in sorted(d.glob("*.json"), reverse=True)[:limit]:
        try:
            out.append(_summary(json.loads(f.read_text(encoding="utf-8"))))
        except (OSError, ValueError):
            continue
    return out


def get_run(skill_name: str, run_id: str) -> dict | None:
    # run_id is filename-derived; reject anything that could escape the dir.
    if not re.fullmatch(r"[A-Za-z0-9_-]+", run_id or ""):
        return None
    f = _skill_dir(skill_name) / f"{run_id}.json"
    if not f.is_file():
        return None
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def delete_run(skill_name: str, run_id: str) -> bool:
    if not re.fullmatch(r"[A-Za-z0-9_-]+", run_id or ""):
        return False
    f = _skill_dir(skill_name) / f"{run_id}.json"
    if not f.is_file():
        return False
    try:
        f.unlink()
        return True
    except OSError:
        return False
