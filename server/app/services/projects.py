"""Project abstraction for the workspace view.

A "project" here means "a working directory where one or more AI sessions
were run". We never persist this — it's derived from three sources at
read time and cached briefly:

  1. ops-hub's own ``agent_sessions`` table (``workdir`` column)
  2. Claude Code's ``~/.claude/projects/<encoded-cwd>/<session>.jsonl``
  3. Codex's ``~/.codex/sessions/YYYY/MM/DD/*.jsonl`` (each session_meta
     line carries a ``cwd`` field in its payload)

The grouping key is the canonical absolute path of the cwd; the project
id is a short stable hash of that path so the frontend can use it in URLs
without worrying about escaping. The same workspace appears once even
when multiple agents have used it.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.core import integrations


# --- Cache --------------------------------------------------------------------
# Filesystem scans + sqlite reads happen on every Workspace mount; we cache
# the merged list for a short window so navigating quickly doesn't hammer
# disk. The cache is invalidated by refresh() (called after session
# create/delete in agent_hub).

_CACHE_TTL_S = 30.0
_cache: dict[str, Any] = {"ts": 0.0, "projects": None}


def refresh() -> None:
    _cache["ts"] = 0.0
    _cache["projects"] = None


# --- Data classes -------------------------------------------------------------

@dataclass
class ProjectSession:
    """A single session row within a project, merged across sources."""
    id: str                       # ops-hub session id, claude sessionId, or codex uuid
    source: str                   # "hub" | "claude" | "codex"
    title: str
    agent: str | None             # human-readable agent name
    last_active: float            # unix ts
    workdir: str
    raw_path: str | None = None   # for jsonl-backed sources, the file path

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "source": self.source,
            "title": self.title,
            "agent": self.agent,
            "last_active": self.last_active,
            "last_active_iso": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(self.last_active)),
            "workdir": self.workdir,
        }


@dataclass
class Project:
    id: str
    name: str
    path: str
    sources: dict[str, bool] = field(default_factory=lambda: {"hub": False, "claude": False, "codex": False})
    session_count: int = 0
    last_active: float = 0.0

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "path": self.path,
            "sources": self.sources,
            "session_count": self.session_count,
            "last_active": self.last_active,
            "last_active_iso": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(self.last_active)) if self.last_active else "",
        }


def _project_id(cwd: str) -> str:
    return hashlib.sha1(cwd.encode("utf-8")).hexdigest()[:12]


def _normalize_cwd(raw: str | None) -> str | None:
    if not raw:
        return None
    raw = raw.strip()
    if not raw or raw in (".", "..", "-"):
        return None
    # claudecodeui-style encoded names ("-root", "-Users-foo-bar") use dash
    # in place of slash. We don't decode them — instead the file paths
    # themselves carry the real cwd inside each jsonl record (the `cwd`
    # field), and that's what we use.
    try:
        p = Path(raw).expanduser().resolve()
    except Exception:
        return None
    return str(p)


# --- Source scanners ----------------------------------------------------------

def _scan_hub_sessions() -> dict[str, dict]:
    """Return {workdir: {sessions: [...], last_active: ts}} from agent_sessions."""
    from app.core.config import settings as _settings
    db_path = _settings.data_dir / "agent_sessions.sqlite3"
    if not db_path.exists():
        return {}
    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
    except Exception:
        return {}
    grouped: dict[str, dict] = {}
    try:
        for r in conn.execute(
            """SELECT id, agent_id, workdir, title, updated_at, archived
                 FROM agent_sessions
                WHERE COALESCE(archived, 0) = 0"""
        ).fetchall():
            cwd = _normalize_cwd(r["workdir"]) or "(unknown)"
            ts = _parse_iso(r["updated_at"]) or 0.0
            entry = grouped.setdefault(cwd, {"sessions": [], "last_active": 0.0})
            entry["sessions"].append(ProjectSession(
                id=r["id"],
                source="hub",
                title=r["title"] or "(无标题)",
                agent=r["agent_id"],
                last_active=ts,
                workdir=cwd,
            ))
            if ts > entry["last_active"]:
                entry["last_active"] = ts
    finally:
        conn.close()
    return grouped


def _scan_claude_sessions() -> dict[str, dict]:
    """Walk ~/.claude/projects/*/*.jsonl and group by the cwd field
    inside each session."""
    root = integrations.claude_projects_dir()
    if root is None:
        return {}
    grouped: dict[str, dict] = {}
    for proj_dir in sorted(root.iterdir()) if root.is_dir() else []:
        if not proj_dir.is_dir():
            continue
        for jsonl in sorted(proj_dir.glob("*.jsonl"), key=lambda p: -p.stat().st_mtime)[:100]:
            cwd, title = _claude_session_summary(jsonl)
            if not cwd:
                continue
            ts = jsonl.stat().st_mtime
            entry = grouped.setdefault(cwd, {"sessions": [], "last_active": 0.0})
            entry["sessions"].append(ProjectSession(
                id=jsonl.stem,
                source="claude",
                title=title or jsonl.stem,
                agent="claude",
                last_active=ts,
                workdir=cwd,
                raw_path=str(jsonl),
            ))
            if ts > entry["last_active"]:
                entry["last_active"] = ts
    return grouped


def _claude_session_summary(jsonl: Path) -> tuple[str | None, str | None]:
    """Pull the cwd and a short title from a Claude session jsonl.

    Returns (cwd, title). Reads at most the first ~80 lines so a 100MB
    log doesn't drag the listing down. Title is the first user prompt's
    leading words (skipping `<command-name>` / `<local-command-*>` shell
    helpers which would otherwise dominate every list entry).
    """
    cwd: str | None = None
    title: str | None = None
    try:
        with jsonl.open("r", encoding="utf-8", errors="ignore") as f:
            for i, line in enumerate(f):
                if i >= 80:
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                if cwd is None and isinstance(rec.get("cwd"), str):
                    cwd = _normalize_cwd(rec["cwd"])
                # Prefer Claude's own ai-title record when present.
                if title is None and rec.get("type") == "ai-title":
                    ai_title = rec.get("aiTitle") or rec.get("title")
                    if isinstance(ai_title, str) and ai_title.strip():
                        title = _clip_title(ai_title)
                # Fall back to first real user prompt (skip <command>* helpers).
                if title is None and rec.get("type") == "user":
                    msg = rec.get("message")
                    if isinstance(msg, dict):
                        raw_text = ""
                        content = msg.get("content")
                        if isinstance(content, str):
                            raw_text = content
                        elif isinstance(content, list):
                            for part in content:
                                if isinstance(part, dict) and part.get("type") == "text":
                                    raw_text = part.get("text", "")
                                    break
                        # Skip slash-commands / output-only records so we
                        # land on the actual first prompt the user typed.
                        if raw_text and not raw_text.lstrip().startswith(("<command-", "<local-command-")):
                            title = _clip_title(raw_text)
                if cwd and title:
                    break
    except Exception:
        return None, None
    return cwd, title


def _scan_codex_sessions() -> dict[str, dict]:
    """Walk ~/.codex/sessions/YYYY/MM/DD/*.jsonl and group by session_meta cwd."""
    root = integrations.codex_db()  # codex DB lives at /root/.codex/state_5.sqlite,
    # but the session jsonl files live alongside it in ~/.codex/sessions.
    base = Path.home() / ".codex" / "sessions"
    if not base.is_dir():
        return {}
    grouped: dict[str, dict] = {}
    # Scan only the last few weeks to keep listing snappy.
    cutoff = time.time() - 60 * 86400
    # Walk year/month/day tree manually so we can skip old months entirely.
    for year_dir in sorted(base.iterdir(), reverse=True):
        if not year_dir.is_dir():
            continue
        for month_dir in sorted(year_dir.iterdir(), reverse=True):
            if not month_dir.is_dir():
                continue
            for day_dir in sorted(month_dir.iterdir(), reverse=True):
                if not day_dir.is_dir():
                    continue
                if day_dir.stat().st_mtime < cutoff:
                    continue
                for jsonl in sorted(day_dir.glob("*.jsonl"), key=lambda p: -p.stat().st_mtime):
                    cwd, title, sid = _codex_session_summary(jsonl)
                    if not cwd:
                        continue
                    ts = jsonl.stat().st_mtime
                    entry = grouped.setdefault(cwd, {"sessions": [], "last_active": 0.0})
                    entry["sessions"].append(ProjectSession(
                        id=sid or jsonl.stem,
                        source="codex",
                        title=title or jsonl.stem,
                        agent="codex",
                        last_active=ts,
                        workdir=cwd,
                        raw_path=str(jsonl),
                    ))
                    if ts > entry["last_active"]:
                        entry["last_active"] = ts
    return grouped


def _codex_session_summary(jsonl: Path) -> tuple[str | None, str | None, str | None]:
    """Read the first few lines of a Codex rollout jsonl and extract
    (cwd, title, sid). ``session_meta`` payload is a proper JSON object
    in newer Codex versions, so we access it via .get rather than regex.
    """
    cwd: str | None = None
    sid: str | None = None
    title: str | None = None
    try:
        with jsonl.open("r", encoding="utf-8", errors="ignore") as f:
            for i, line in enumerate(f):
                if i >= 30:
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                rec_type = rec.get("type")
                payload = rec.get("payload")
                if rec_type == "session_meta" and isinstance(payload, dict):
                    if cwd is None and isinstance(payload.get("cwd"), str):
                        cwd = _normalize_cwd(payload["cwd"])
                    if sid is None and isinstance(payload.get("id"), str):
                        sid = payload["id"]
                if title is None and rec_type == "response_item" and isinstance(payload, dict):
                    # First "real" user-text message becomes the title — skip
                    # Codex's <environment_context> / <permissions> wrappers
                    # which would otherwise dominate the listing.
                    if payload.get("role") == "user":
                        for part in payload.get("content") or []:
                            if not isinstance(part, dict): continue
                            if part.get("type") != "input_text": continue
                            text = part.get("text", "")
                            stripped = text.lstrip()
                            if stripped.startswith(("<environment_context", "<permissions")):
                                continue  # try the next response_item
                            title = _clip_title(text)
                            break
                if cwd and sid and title:
                    break
    except Exception:
        return None, None, None
    return cwd, title, sid


# --- Helpers ------------------------------------------------------------------

_TITLE_MAX = 64


def _clip_title(text: str) -> str:
    if not text:
        return ""
    # Collapse whitespace
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > _TITLE_MAX:
        return text[: _TITLE_MAX - 1] + "…"
    return text


def _parse_iso(s: str | None) -> float | None:
    if not s:
        return None
    try:
        # Handle both "2026-05-21T10:00:00" and ISO with timezone.
        from datetime import datetime
        return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except Exception:
        return None


# --- Public API ---------------------------------------------------------------

def list_projects(force: bool = False) -> list[Project]:
    """Return all known projects, newest first.

    Aggregates ops-hub agent_sessions + claude + codex; merges by cwd.
    Result is cached for _CACHE_TTL_S; pass ``force=True`` to bypass.
    """
    now = time.time()
    if not force and _cache.get("projects") is not None and (now - _cache["ts"]) < _CACHE_TTL_S:
        return _cache["projects"]

    hub = _scan_hub_sessions()
    claude_data = _scan_claude_sessions()
    codex_data = _scan_codex_sessions()

    projects: dict[str, Project] = {}
    for source_name, group in (("hub", hub), ("claude", claude_data), ("codex", codex_data)):
        for cwd, entry in group.items():
            pid = _project_id(cwd)
            proj = projects.get(pid)
            if proj is None:
                name = os.path.basename(cwd) or cwd or "(root)"
                proj = Project(id=pid, name=name, path=cwd)
                projects[pid] = proj
            proj.sources[source_name] = True
            proj.session_count += len(entry["sessions"])
            if entry["last_active"] > proj.last_active:
                proj.last_active = entry["last_active"]

    # Sort: real projects first by last_active desc; the synthetic
    # "(unknown)" bucket (workdir-less hub sessions) always lands at the
    # bottom regardless of how recent its sessions are — it's a catch-all,
    # not a real workspace, so it shouldn't push real projects down.
    def _sort_key(p: Project):
        is_unknown = p.path == "(unknown)"
        return (1 if is_unknown else 0, -p.last_active)
    ordered = sorted(projects.values(), key=_sort_key)
    _cache["projects"] = ordered
    _cache["ts"] = now
    return ordered


def get_project(project_id: str) -> Project | None:
    for p in list_projects():
        if p.id == project_id:
            return p
    return None


def list_project_sessions(project_id: str) -> list[ProjectSession]:
    """Return all sessions inside one project, newest first, merged across sources."""
    target = get_project(project_id)
    if target is None:
        return []
    target_path = target.path

    hub = _scan_hub_sessions().get(target_path, {"sessions": []})
    claude = _scan_claude_sessions().get(target_path, {"sessions": []})
    codex = _scan_codex_sessions().get(target_path, {"sessions": []})

    merged = hub["sessions"] + claude["sessions"] + codex["sessions"]
    merged.sort(key=lambda s: s.last_active, reverse=True)
    return merged
