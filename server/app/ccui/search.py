"""Conversation search across Claude session transcripts — a pragmatic,
claude-focused port of session-conversations-search.service.ts.

Scans the indexed claude sessions' JSONL files for the query (all query words
must appear, or the exact phrase for multi-word queries), builds snippets with
highlight offsets, groups matches by project, and yields SSE events
(``result`` / ``progress``) the sidebar's EventSource consumes. No ripgrep —
direct file scans are fast enough at personal scale. codex/gemini search is a
follow-up (only claude transcripts are scanned here).
"""
from __future__ import annotations

import json
import os
import re
from typing import Iterator, Optional

from app.ccui import repos
from app.ccui.db import db_conn

_MAX_MATCHES_PER_SESSION = 2
_SNIPPET_LEN = 150
_INTERNAL_PREFIXES = ("<system-reminder>", "Caveat:", "Invalid API key", "[Request interrupted")
_ANSI_RE = re.compile(r"\x1B\[[0-9;?]*[ -/]*[@-~]")


def _strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)


def _extract_tagged(content: str, tag: str) -> Optional[str]:
    m = re.search(rf"<{re.escape(tag)}>([\s\S]*?)</{re.escape(tag)}>", content)
    return m.group(1) if m else None


def _searchable_text(entry: dict) -> Optional[tuple[str, str]]:
    """Return (text, role) for a claude JSONL entry, or None if not user-visible.
    Mirrors extractClaudeSearchableMessage (compact summary / local command /
    stdout handling)."""
    msg = entry.get("message")
    if not isinstance(msg, dict) or entry.get("isApiErrorMessage"):
        return None
    role = msg.get("role")
    if role not in ("user", "assistant"):
        return None
    content = msg.get("content")
    if isinstance(content, str):
        if entry.get("isCompactSummary") is True and content.strip():
            return content, "assistant"
        cmd_name = _extract_tagged(content, "command-name")
        cmd_msg = _extract_tagged(content, "command-message")
        cmd_args = _extract_tagged(content, "command-args")
        if cmd_name is not None or cmd_msg is not None or cmd_args is not None:
            base = (cmd_name or cmd_msg or "").strip()
            disp = (f"{base} {cmd_args.strip()}" if cmd_args and cmd_args.strip() else base) if base else ""
            return (disp, "user") if disp else None
        stdout = _extract_tagged(content, "local-command-stdout")
        if stdout is not None:
            s = _strip_ansi(stdout).strip()
            return (s, "assistant") if s else None
        if not content or any(content.startswith(p) for p in _INTERNAL_PREFIXES):
            return None
        return content, role
    if isinstance(content, list):
        text = " ".join(p.get("text", "") for p in content
                        if isinstance(p, dict) and p.get("type") == "text" and p.get("text"))
        if not text:
            return None
        if entry.get("isCompactSummary") is True:
            return text, "assistant"
        if any(text.startswith(p) for p in _INTERNAL_PREFIXES):
            return None
        return text, role
    return None


def _matches(text: str, words: list[str], phrase: Optional[str]) -> bool:
    low = text.lower()
    if phrase and len(words) > 1:
        return phrase in low
    return all(w in low for w in words)


def _build_snippet(text: str, words: list[str]) -> tuple[str, list[dict]]:
    low = text.lower()
    first = -1
    word_len = 0
    for w in words:
        idx = low.find(w)
        if idx != -1 and (first == -1 or idx < first):
            first, word_len = idx, len(w)
    if first == -1:
        first = 0
    half = _SNIPPET_LEN // 2
    start = max(0, first - half)
    end = min(len(text), first + half + word_len)
    prefix = "..." if start > 0 else ""
    suffix = "..." if end < len(text) else ""
    body = text[start:end].replace("\n", " ")
    snippet = f"{prefix}{body}{suffix}"
    # highlight every query word within the snippet
    snip_low = snippet.lower()
    highlights: list[dict] = []
    for w in words:
        pos = snip_low.find(w)
        while pos != -1:
            highlights.append({"start": pos, "end": pos + len(w)})
            pos = snip_low.find(w, pos + len(w))
    highlights.sort(key=lambda h: h["start"])
    merged: list[dict] = []
    for h in highlights:
        if merged and h["start"] <= merged[-1]["end"]:
            merged[-1]["end"] = max(merged[-1]["end"], h["end"])
        else:
            merged.append(dict(h))
    return snippet, merged


def _summary(custom_name: Optional[str], fallback: Optional[str]) -> str:
    if custom_name and custom_name.strip():
        return custom_name.strip()
    fb = (fallback or "").strip()
    if not fb:
        return "New Session"
    return fb[:50] + "..." if len(fb) > 50 else fb


def _scan_session(jsonl_path: str, words: list[str], phrase: Optional[str],
                  custom_name: Optional[str], remaining: int) -> Optional[dict]:
    """Scan one session file; return a session result dict if any match, else None."""
    matches: list[dict] = []
    fallback_user = None
    try:
        with open(jsonl_path, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if len(matches) >= _MAX_MATCHES_PER_SESSION or len(matches) >= remaining:
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except (ValueError, TypeError):
                    continue
                st = _searchable_text(entry)
                if not st:
                    continue
                text, role = st
                if role == "user" and fallback_user is None:
                    fallback_user = text
                if not _matches(text, words, phrase):
                    continue
                snippet, highlights = _build_snippet(text, words)
                matches.append({"role": role, "snippet": snippet, "highlights": highlights,
                                "timestamp": entry.get("timestamp"), "provider": "claude",
                                "messageUuid": entry.get("uuid")})
    except OSError:
        return None
    if not matches:
        return None
    return {"matches": matches, "summary": _summary(custom_name, fallback_user)}


def search_conversations(query: str, limit: int) -> Iterator[tuple[str, dict]]:
    """Yield ('result'|'progress', data) events. Done is emitted by the caller."""
    words = [w for w in query.lower().split() if w]
    if not words:
        return
    phrase = " ".join(words) if len(words) > 1 else None

    with db_conn() as conn:
        rows = repos.get_all_sessions(conn)
        # project archive state cache
        archived: dict[str, bool] = {}
        proj_meta: dict[str, dict] = {}
        buckets: dict[str, list] = {}
        for s in rows:
            if s["provider"] != "claude":
                continue
            jp = (s["jsonl_path"] or "").strip()
            if not jp or not os.path.exists(jp):
                continue
            pp = (s["project_path"] or "").strip() or "__unknown__"
            if pp != "__unknown__":
                if pp not in archived:
                    prow = repos.get_project_by_path(conn, pp)
                    archived[pp] = bool(prow["isArchived"]) if prow else False
                    proj_meta[pp] = {"projectId": prow["project_id"] if prow else None,
                                     "displayName": (prow["custom_project_name"].strip() if prow and prow["custom_project_name"]
                                                     else os.path.basename(pp) or pp)}
                if archived[pp]:
                    continue
            buckets.setdefault(pp, []).append(s)

    total_projects = len(buckets)
    total_matches = 0
    scanned = 0
    for pp, sessions in buckets.items():
        if total_matches >= limit:
            break
        meta = proj_meta.get(pp, {"projectId": None, "displayName": "Unknown Project"})
        project_result = {"projectId": meta["projectId"], "projectName": pp,
                          "projectDisplayName": meta["displayName"], "sessions": []}
        for s in sessions:
            if total_matches >= limit:
                break
            res = _scan_session(s["jsonl_path"], words, phrase, s["custom_name"], limit - total_matches)
            if res:
                project_result["sessions"].append({
                    "sessionId": s["session_id"], "provider": "claude",
                    "sessionSummary": res["summary"], "matches": res["matches"]})
                total_matches += len(res["matches"])
        scanned += 1
        if project_result["sessions"]:
            yield ("result", {"projectResult": project_result, "totalMatches": total_matches,
                              "scannedProjects": scanned, "totalProjects": total_projects})
        elif scanned % 10 == 0:
            yield ("progress", {"totalMatches": total_matches, "scannedProjects": scanned,
                                "totalProjects": total_projects})
