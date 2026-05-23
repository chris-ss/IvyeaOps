"""Filesystem layout for Skill Studio.

Two roots are kept strictly separate:

  SKILLS_ROOT  = ~/.hermes/skills/
      The real skills the Hermes runtime loads. We only read/write actual
      skill directories here (no hidden metadata dirs). This keeps the
      Hermes skill scanner blind to our bookkeeping.

  STUDIO_ROOT  = ~/.hermes/skill-studio/
      All Studio state lives here — snapshots, trash, settings, audit log.
      Completely outside the scanner's path.

Both paths are override-able via env vars for tests; production just uses
the defaults.
"""
from __future__ import annotations

import os
from pathlib import Path


# --- Roots -----------------------------------------------------------------

# Allow overrides in tests; fall back to ~/.hermes/... in production.
_HERMES_HOME = Path(
    os.getenv("HERMES_HOME", str(Path.home() / ".hermes"))
).resolve()

SKILLS_ROOT: Path = Path(
    os.getenv("OPSHUB_SKILLS_ROOT", str(_HERMES_HOME / "skills"))
).resolve()

STUDIO_ROOT: Path = Path(
    os.getenv("OPSHUB_STUDIO_ROOT", str(_HERMES_HOME / "skill-studio"))
).resolve()


# --- Studio sub-paths ------------------------------------------------------

SNAPSHOTS_DIR: Path = STUDIO_ROOT / "snapshots"
TRASH_DIR: Path = STUDIO_ROOT / "trash"
SETTINGS_FILE: Path = STUDIO_ROOT / "settings.json"
AUDIT_LOG_FILE: Path = STUDIO_ROOT / "audit.log"


# --- Setup -----------------------------------------------------------------

def ensure_studio_dirs() -> None:
    """Create Studio directories on startup. Idempotent.

    Intentionally does NOT touch SKILLS_ROOT: that's Hermes' territory and
    will already exist when Hermes is installed. If it's missing we surface
    that as an error rather than silently creating an empty skills dir.
    """
    STUDIO_ROOT.mkdir(parents=True, exist_ok=True)
    SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    TRASH_DIR.mkdir(parents=True, exist_ok=True)
    # settings.json and audit.log are created on first write.


def studio_paths_summary() -> dict[str, str]:
    """Debug helper: return current path layout for logging."""
    return {
        "skills_root": str(SKILLS_ROOT),
        "skills_root_exists": str(SKILLS_ROOT.exists()),
        "studio_root": str(STUDIO_ROOT),
        "snapshots_dir": str(SNAPSHOTS_DIR),
        "trash_dir": str(TRASH_DIR),
        "settings_file": str(SETTINGS_FILE),
        "audit_log": str(AUDIT_LOG_FILE),
    }
