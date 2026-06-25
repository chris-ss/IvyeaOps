"""Application version helpers."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def runtime_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[3]


_CACHED: str | None = None


def _git_tag(root: Path) -> str:
    """Latest tag reachable from HEAD on a git checkout, or '' if unavailable."""
    if not (root / ".git").exists():
        return ""
    try:
        out = subprocess.run(
            ["git", "-C", str(root), "describe", "--tags", "--abbrev=0"],
            capture_output=True, text=True, timeout=3,
        )
        return (out.stdout or "").strip()
    except Exception:
        return ""


def app_version() -> str:
    """Reported version.

    On a git checkout, the latest *tag* is the source of truth — the release
    workflow overwrites the VERSION file at build time but never commits it back,
    so a stale VERSION file used to make a freshly-pulled server think it was
    behind. Frozen bundles have no .git, so they fall back to the baked VERSION
    file (which the release jobs DO set to the tag)."""
    global _CACHED
    if _CACHED is not None:
        return _CACHED
    root = runtime_root()
    tag = "" if getattr(sys, "frozen", False) else _git_tag(root)
    if tag:
        _CACHED = tag
        return tag
    try:
        value = (root / "VERSION").read_text(encoding="utf-8").strip()
        if value:
            _CACHED = value
            return value
    except Exception:
        pass
    _CACHED = "dev"
    return _CACHED
