"""Claude session synchronizer — port of claudecodeui's
ClaudeSessionSynchronizer (+ the session-synchronizer orchestration).

Scans ``~/.claude/projects/**/*.jsonl``, reads each transcript's first valid
line for ``sessionId`` + ``cwd`` (the real project path), resolves a session
name (existing custom_name → ~/.claude/history.jsonl display map → AI title
scanned from the file end), and upserts projects/sessions rows. This makes the
native backend self-sufficient — projects/sessions appear without relying on the
old Node service to keep the DB fresh (the P9 cutover prerequisite).

``maybe_synchronize`` throttles full scans (default 3s) using the scan_state
table so the projects-list endpoints can call it cheaply on every request, the
way the Node list path did.
"""
from __future__ import annotations

from app.core.proc import no_window_kwargs

import json
import os
import logging
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from app.agents import repos
from app.agents.db import db_conn

logger = logging.getLogger("agents.sync")

_CLAUDE_HOME = Path.home() / ".claude"
_CODEX_HOME = Path.home() / ".codex"
# Hermes sessions have no project cwd, so group them under one synthetic project.
_HERMES_PROJECT = str(Path.home() / ".hermes" / "sessions")
_HERMES_PROJECT_NAME = "Hermes 会话"
_UNTITLED = "Untitled Claude Session"


def _config_get(conn, key: str, default: Optional[str] = None) -> Optional[str]:
    row = conn.execute("SELECT value FROM app_config WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def _config_set(conn, key: str, value: str) -> None:
    conn.execute("INSERT INTO app_config(key, value) VALUES(?, ?) "
                 "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, value))


def _to_iso(value) -> Optional[str]:
    """Epoch seconds (int/float/str) -> ISO; pass through ISO-ish strings; else None."""
    if value is None:
        return None
    try:
        return datetime.fromtimestamp(float(value), tz=timezone.utc).isoformat()
    except (ValueError, TypeError, OSError):
        return str(value) if isinstance(value, str) and value.strip() else None


def _normalize_session_name(raw: Optional[str], fallback: str) -> str:
    normalized = " ".join((raw or "").split()).strip()
    return normalized[:120] if normalized else fallback


def _file_timestamps(path: str) -> tuple[Optional[str], Optional[str]]:
    try:
        st = os.stat(path)
        created = getattr(st, "st_birthtime", st.st_ctime)
        return (datetime.fromtimestamp(created, tz=timezone.utc).isoformat(),
                datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).isoformat())
    except OSError:
        return None, None


def _build_name_map() -> dict[str, str]:
    """sessionId -> display, first-seen wins (from ~/.claude/history.jsonl)."""
    lookup: dict[str, str] = {}
    try:
        with open(_CLAUDE_HOME / "history.jsonl", "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except (ValueError, TypeError):
                    continue
                sid, display = entry.get("sessionId"), entry.get("display")
                if isinstance(sid, str) and isinstance(display, str) and sid not in lookup:
                    lookup[sid] = display
    except OSError:
        pass
    return lookup


def _find_jsonl_files(root: Path, since: Optional[float]) -> list[str]:
    out: list[str] = []
    if not root.is_dir():
        return out
    for dirpath, _dirs, files in os.walk(root):
        for name in files:
            if not name.endswith(".jsonl"):
                continue
            fp = os.path.join(dirpath, name)
            if since is None:
                out.append(fp)
            else:
                try:
                    st = os.stat(fp)
                    if getattr(st, "st_birthtime", st.st_ctime) > since:
                        out.append(fp)
                except OSError:
                    pass
    return out


def _first_session_and_cwd(path: str) -> Optional[dict]:
    """First valid JSONL line carrying both sessionId and cwd."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                except (ValueError, TypeError):
                    continue
                sid, cwd = data.get("sessionId"), data.get("cwd")
                if isinstance(sid, str) and isinstance(cwd, str):
                    return {"sessionId": sid, "projectPath": cwd}
    except OSError:
        pass
    return None


def _ai_title_from_end(path: str, session_id: str) -> Optional[str]:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            lines = fh.read().splitlines()
    except OSError:
        return None
    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
        except (ValueError, TypeError):
            continue
        etype = data.get("type")
        esid = data.get("sessionId")
        if esid != session_id:
            continue
        if etype == "ai-title" and (data.get("aiTitle") or "").strip():
            return data["aiTitle"]
        if etype == "last-prompt" and (data.get("lastPrompt") or "").strip():
            return data["lastPrompt"]
        if etype == "custom-title" and (data.get("customTitle") or "").strip():
            return data["customTitle"]
    return None


def synchronize(since: Optional[float] = None) -> int:
    """Scan and upsert all claude sessions (optionally only files created after
    ``since`` epoch seconds). Returns the number of sessions processed."""
    name_map = _build_name_map()
    files = _find_jsonl_files(_CLAUDE_HOME / "projects", since)
    processed = 0
    with db_conn() as conn:
        for fp in files:
            parsed = _first_session_and_cwd(fp)
            if not parsed:
                continue
            sid = parsed["sessionId"]
            existing = repos.get_session_by_id(conn, sid)
            existing_name = existing["custom_name"] if existing else None
            if existing_name and existing_name != _UNTITLED:
                name = _normalize_session_name(existing_name, _UNTITLED)
            else:
                name = name_map.get(sid) or _ai_title_from_end(fp, sid)
                name = _normalize_session_name(name, _UNTITLED)
            created, updated = _file_timestamps(fp)
            repos.create_session(conn, sid, "claude", parsed["projectPath"],
                                 name, created, updated, fp)
            processed += 1
    return processed


def _codex_name_map() -> dict[str, str]:
    """id -> thread_name from ~/.codex/session_index.jsonl."""
    lookup: dict[str, str] = {}
    try:
        with open(_CODEX_HOME / "session_index.jsonl", "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    e = json.loads(line)
                except (ValueError, TypeError):
                    continue
                sid, name = e.get("id"), e.get("thread_name")
                if isinstance(sid, str) and isinstance(name, str) and sid not in lookup:
                    lookup[sid] = name
    except OSError:
        pass
    return lookup


def _codex_session_meta(path: str) -> Optional[dict]:
    """Codex rollout: first line type=session_meta, payload={id, cwd}."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                except (ValueError, TypeError):
                    continue
                if ev.get("type") == "session_meta":
                    payload = ev.get("payload") or {}
                    sid, cwd = payload.get("id"), payload.get("cwd")
                    if isinstance(sid, str) and isinstance(cwd, str):
                        return {"sessionId": sid, "projectPath": cwd}
                    return None
    except OSError:
        pass
    return None


def synchronize_codex(since: Optional[float] = None) -> int:
    """Index ~/.codex/sessions/**/rollout-*.jsonl into the sessions table."""
    name_map = _codex_name_map()
    files = _find_jsonl_files(_CODEX_HOME / "sessions", since)
    processed = 0
    with db_conn() as conn:
        for fp in files:
            parsed = _codex_session_meta(fp)
            if not parsed:
                continue
            sid = parsed["sessionId"]
            existing = repos.get_session_by_id(conn, sid)
            existing_name = existing["custom_name"] if existing else None
            if existing_name and existing_name != "Codex Session":
                name = existing_name
            else:
                name = _normalize_session_name(name_map.get(sid), "Codex Session")
            created, updated = _file_timestamps(fp)
            repos.create_session(conn, sid, "codex", parsed["projectPath"],
                                 name, created, updated, fp)
            processed += 1
    return processed


def _hermes_bin() -> str:
    search = os.pathsep.join([os.path.expanduser("~/.local/bin"),
                       os.path.expanduser("~/.hermes/node/bin"), os.environ.get("PATH", "")])
    return shutil.which("hermes", path=search) or "hermes"


def _synchronize_hermes_from_files() -> int:
    """Index hermes sessions by scanning ~/.hermes/sessions/session_*.json directly.
    No CLI needed — `hermes sessions export` fails on Windows (CLI/node not found),
    which is why hermes chat history vanished on refresh there. The JSON files are
    written by hermes on every platform, so scanning them is robust."""
    sessions_dir = Path.home() / ".hermes" / "sessions"
    if not sessions_dir.is_dir():
        return 0
    # Without the CLI's --source filter we can't tell user sessions from IvyeaOps'
    # own internal hermes calls (brain chat / analysis / PONG health checks), so
    # bound the scan to recently-active files + a hard cap. Recent user sessions
    # (the thing that vanished on refresh) show up; the years-long backlog doesn't.
    cutoff = time.time() - 14 * 86400
    recent = sorted(
        (p for p in sessions_dir.glob("session_*.json") if p.stat().st_mtime >= cutoff),
        key=lambda p: p.stat().st_mtime, reverse=True)[:200]
    # Skip IvyeaOps' own engine sessions by their known system-prompt / probe text.
    _INTERNAL = ("IvyeaOps Web 知识库", "Reply with exactly: PONG", "你是亚马逊跨境电商市场分析专家")
    processed = 0
    with db_conn() as conn:
        for fp in recent:
            try:
                d = json.loads(fp.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            sid = d.get("session_id") or d.get("id")
            if not isinstance(sid, str) or not sid:
                continue
            if int(d.get("message_count") or 0) <= 0:
                continue
            blob = (str(d.get("system_prompt") or "")[:400]
                    + str((d.get("messages") or [{}])[0].get("content") or "")[:200])
            if any(marker in blob for marker in _INTERNAL):
                continue
            name = (d.get("title") or "").strip()
            if not name:
                for m in (d.get("messages") or []):
                    if isinstance(m, dict) and m.get("role") == "user":
                        c = m.get("content")
                        if isinstance(c, list):
                            c = " ".join(p.get("text", "") for p in c
                                         if isinstance(p, dict) and isinstance(p.get("text"), str))
                        if isinstance(c, str) and c.strip():
                            name = c.strip()
                            break
            name = _normalize_session_name(name, "Hermes 会话")
            created = _to_iso(d.get("session_start") or d.get("started_at"))
            updated = _to_iso(d.get("last_updated") or d.get("last_active")) or created
            existing = repos.get_session_by_id(conn, sid)
            if existing and existing["isArchived"]:
                continue
            repos.create_session(conn, sid, "hermes", _HERMES_PROJECT, name, created, updated, str(fp))
            processed += 1
        row = repos.get_project_by_path(conn, _HERMES_PROJECT)
        if row and (row["custom_project_name"] or "") != _HERMES_PROJECT_NAME:
            repos.update_custom_project_name_by_id(conn, row["project_id"], _HERMES_PROJECT_NAME)
    return processed


def synchronize_hermes() -> int:
    """Index hermes sessions into the sessions table under one synthetic
    'Hermes 会话' project. Tries `hermes sessions export` (source=cli, no cron) and
    falls back to scanning the session JSON files directly when the CLI is
    unavailable (e.g. Windows). Best-effort: any failure returns 0."""
    binary = _hermes_bin()
    env = os.environ.copy()
    env["PATH"] = os.pathsep.join([os.path.expanduser("~/.local/bin"),
                            os.path.expanduser("~/.hermes/node/bin"), env.get("PATH", "")])
    try:
        proc = subprocess.run([binary, "sessions", "export", "-", "--source", "cli"],
                              capture_output=True, text=True, timeout=30, env=env,
                              **no_window_kwargs())
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as e:
        logger.warning("hermes export failed (%s); scanning session files instead", e)
        return _synchronize_hermes_from_files()
    if proc.returncode != 0:
        logger.warning("hermes export rc=%s (%s); scanning session files instead",
                       proc.returncode, (proc.stderr or "")[:120])
        return _synchronize_hermes_from_files()

    sessions_dir = Path.home() / ".hermes" / "sessions"
    processed = 0
    with db_conn() as conn:
        for line in proc.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                s = json.loads(line)
            except (ValueError, TypeError):
                continue
            sid = s.get("id")
            if not isinstance(sid, str) or not sid:
                continue
            if int(s.get("message_count") or 0) <= 0:
                continue  # skip empty sessions
            # name: title -> first user message -> fallback
            name = (s.get("title") or "").strip()
            if not name:
                for m in (s.get("messages") or []):
                    if isinstance(m, dict) and m.get("role") == "user":
                        c = m.get("content")
                        if isinstance(c, str) and c.strip():
                            name = c.strip()
                            break
            name = _normalize_session_name(name, "Hermes 会话")
            created = _to_iso(s.get("started_at"))
            updated = _to_iso(s.get("last_active")) or created
            json_path = sessions_dir / f"session_{sid}.json"
            jsonl_path = str(json_path) if json_path.exists() else None
            # Don't resurrect a session the user archived: create_session would
            # otherwise reset isArchived=0 on every sync.
            existing = repos.get_session_by_id(conn, sid)
            if existing and existing["isArchived"]:
                continue
            repos.create_session(conn, sid, "hermes", _HERMES_PROJECT, name, created, updated, jsonl_path)
            processed += 1
        # Give the synthetic project a friendly display name (once).
        row = repos.get_project_by_path(conn, _HERMES_PROJECT)
        if row and (row["custom_project_name"] or "") != _HERMES_PROJECT_NAME:
            repos.update_custom_project_name_by_id(conn, row["project_id"], _HERMES_PROJECT_NAME)
    logger.info("hermes sync indexed %s sessions", processed)
    # Export ran but found nothing (e.g. the user's session isn't tagged source=cli,
    # or the store path differs on Windows) → supplement from the session files.
    if processed == 0:
        return _synchronize_hermes_from_files()
    return processed


def index_hermes_session(session_id: str, name: Optional[str] = None) -> bool:
    """Index ONE hermes session into the DB immediately (no CLI export), so a
    freshly-created session shows up in the sidebar without waiting for the
    throttled (60s) full hermes sync. `name` is the user's first prompt, used as
    the title for brand-new sessions; pass None to keep an existing title.
    Best-effort — any failure returns False."""
    sid = "".join(c for c in str(session_id) if c.isalnum() or c in "_-")
    if not sid:
        return False
    json_path = Path.home() / ".hermes" / "sessions" / f"session_{sid}.json"
    jsonl_path = str(json_path) if json_path.exists() else None
    title = _normalize_session_name(name, "") if name else None
    try:
        with db_conn() as conn:
            existing = repos.get_session_by_id(conn, sid)
            if existing and existing["isArchived"]:
                return False  # respect an archived/deleted session
            # Keep an existing custom title unless we have a fresh one.
            final_name = title or (existing["custom_name"] if existing else None) or _HERMES_PROJECT_NAME
            # Write an explicit tz-aware UTC timestamp (not NULL → CURRENT_TIMESTAMP,
            # which is tz-naive and renders ~8h off in the browser). The full sync
            # later refines these from hermes' started_at/last_active.
            now_iso = datetime.now(timezone.utc).isoformat()
            created = existing["created_at"] if existing and existing["created_at"] else now_iso
            repos.create_session(conn, sid, "hermes", _HERMES_PROJECT, final_name, created, now_iso, jsonl_path)
            row = repos.get_project_by_path(conn, _HERMES_PROJECT)
            if row and (row["custom_project_name"] or "") != _HERMES_PROJECT_NAME:
                repos.update_custom_project_name_by_id(conn, row["project_id"], _HERMES_PROJECT_NAME)
        return True
    except Exception:
        logger.exception("index_hermes_session failed for %s", session_id)
        return False


def maybe_synchronize(min_interval: float = 3.0) -> int:
    """Throttled full sync (default once per 3s), tracked in scan_state."""
    now = time.time()
    with db_conn() as conn:
        row = conn.execute("SELECT last_scanned_at FROM scan_state WHERE id = 1").fetchone()
    last = None
    if row and row["last_scanned_at"]:
        try:
            last = float(row["last_scanned_at"])
        except (ValueError, TypeError):
            last = None
    if last is not None and now - last < min_interval:
        return 0
    try:
        n = synchronize()
        try:
            n += synchronize_codex()
        except Exception:
            logger.exception("codex sync failed")  # best-effort; never block claude
        # hermes sync spawns the hermes CLI (~1s), so throttle it separately (60s).
        try:
            with db_conn() as conn:
                hlast = _config_get(conn, "hermes_last_scan", "0")
            if now - float(hlast or 0) >= 60:
                n += synchronize_hermes()
                with db_conn() as conn:
                    _config_set(conn, "hermes_last_scan", str(now))
        except Exception:
            logger.exception("hermes sync failed")  # best-effort
    finally:
        with db_conn() as conn:
            conn.execute(
                "INSERT INTO scan_state(id, last_scanned_at) VALUES(1, ?) "
                "ON CONFLICT(id) DO UPDATE SET last_scanned_at = excluded.last_scanned_at",
                (str(now),))
    return n
