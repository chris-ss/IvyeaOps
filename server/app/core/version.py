"""Application version helpers."""
from __future__ import annotations

import sys
from pathlib import Path


def runtime_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[3]


def app_version() -> str:
    version_file = runtime_root() / "VERSION"
    try:
        value = version_file.read_text(encoding="utf-8").strip()
        if value:
            return value
    except Exception:
        pass
    return "dev"
