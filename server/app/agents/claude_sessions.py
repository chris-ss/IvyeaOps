"""Claude session transcript reader + message normalizer.

Direct port of ``modules/providers/list/claude/claude-sessions.provider.ts``
(and the ``createNormalizedMessage``/``generateMessageId`` helpers from
shared/utils.ts). Reads Claude's native JSONL transcripts and converts each
entry into the normalized message shape the frontend's chat/tool renderers
consume. ``normalize_message`` is reused by P2 for live stream events.
"""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from app.agents import repos

PROVIDER = "claude"

_INTERNAL_CONTENT_PREFIXES = ("<system-reminder>", "Caveat:", "[Request interrupted")


def generate_message_id(prefix: str = "msg") -> str:
    return f"{prefix}_{uuid.uuid4()}"


def create_normalized_message(**fields: Any) -> dict:
    """Fill the shared envelope (id/sessionId/timestamp/provider)."""
    out = dict(fields)
    out["id"] = fields.get("id") or generate_message_id(str(fields.get("kind") or "msg"))
    out["sessionId"] = fields.get("sessionId") or ""
    out["timestamp"] = fields.get("timestamp") or datetime.now(timezone.utc).isoformat()
    out["provider"] = fields.get("provider")
    return out


def _is_internal_content(content: str) -> bool:
    return any(content.startswith(p) for p in _INTERNAL_CONTENT_PREFIXES)


def _extract_tagged(content: str, tag: str) -> Optional[str]:
    import re
    m = re.search(rf"<{re.escape(tag)}>([\s\S]*?)</{re.escape(tag)}>", content)
    return m.group(1) if m else None


def _parse_local_command(content: str) -> Optional[dict]:
    name = _extract_tagged(content, "command-name")
    message = _extract_tagged(content, "command-message")
    args = _extract_tagged(content, "command-args")
    if name is None and message is None and args is None:
        return None
    return {"commandName": name or "", "commandMessage": message or "", "commandArgs": args or ""}


def _build_local_command_display(payload: dict) -> str:
    base = payload["commandName"].strip() or payload["commandMessage"].strip()
    if not base:
        return ""
    args = payload["commandArgs"].strip()
    return f"{base} {args}" if args else base


def _strip_ansi(text: str) -> str:
    import re
    return re.sub(r"\x1B\[[0-9;?]*[ -/]*[@-~]", "", text)


def _as_dict(value: Any) -> Optional[dict]:
    return value if isinstance(value, dict) else None


def normalize_message(raw_message: Any, session_id: Optional[str]) -> list[dict]:
    """Port of ClaudeSessionsProvider.normalizeMessage."""
    raw = _as_dict(raw_message)
    if raw is None:
        return []

    delta = _as_dict(raw.get("delta"))
    if raw.get("type") == "content_block_delta" and delta and delta.get("text"):
        return [create_normalized_message(kind="stream_delta", content=delta["text"],
                                          sessionId=session_id, provider=PROVIDER)]
    if raw.get("type") == "content_block_stop":
        return [create_normalized_message(kind="stream_end", sessionId=session_id, provider=PROVIDER)]

    messages: list[dict] = []
    ts = raw.get("timestamp") or datetime.now(timezone.utc).isoformat()
    base_id = raw.get("uuid") or generate_message_id("claude")
    message = _as_dict(raw.get("message")) or {}
    role = message.get("role")
    content = message.get("content")

    if role == "user" and content is not None and raw.get("isMeta") is not True:
        if isinstance(content, list):
            for part_index, part in enumerate(content):
                if not isinstance(part, dict):
                    continue
                if part.get("type") == "tool_result":
                    c = part.get("content")
                    messages.append(create_normalized_message(
                        id=f"{base_id}_tr_{part.get('tool_use_id')}", sessionId=session_id,
                        timestamp=ts, provider=PROVIDER, kind="tool_result",
                        toolId=part.get("tool_use_id"),
                        content=c if isinstance(c, str) else json.dumps(c),
                        isError=bool(part.get("is_error")),
                        subagentTools=raw.get("subagentTools"),
                        toolUseResult=raw.get("toolUseResult"),
                    ))
                elif part.get("type") == "text":
                    text = part.get("text") or ""
                    if text and not _is_internal_content(text):
                        messages.append(create_normalized_message(
                            id=f"{base_id}_text_{part_index}", sessionId=session_id, timestamp=ts,
                            provider=PROVIDER, kind="text", role="user", content=text,
                        ))
            if not messages:
                text_parts = "\n".join(
                    p.get("text") for p in content
                    if isinstance(p, dict) and p.get("type") == "text" and p.get("text")
                )
                if text_parts and not _is_internal_content(text_parts):
                    messages.append(create_normalized_message(
                        id=f"{base_id}_text", sessionId=session_id, timestamp=ts,
                        provider=PROVIDER, kind="text", role="user", content=text_parts,
                    ))
        elif isinstance(content, str):
            text = content
            if raw.get("isCompactSummary") is True and text.strip():
                messages.append(create_normalized_message(
                    id=base_id, sessionId=session_id, timestamp=ts, provider=PROVIDER,
                    kind="text", role="assistant", content=text, isCompactSummary=True,
                ))
                return messages
            local_cmd = _parse_local_command(text)
            if local_cmd:
                display = _build_local_command_display(local_cmd)
                if display:
                    messages.append(create_normalized_message(
                        id=base_id, sessionId=session_id, timestamp=ts, provider=PROVIDER,
                        kind="text", role="user", content=display,
                        commandName=local_cmd["commandName"], commandMessage=local_cmd["commandMessage"],
                        commandArgs=local_cmd["commandArgs"], isLocalCommand=True,
                    ))
                return messages
            stdout = _extract_tagged(text, "local-command-stdout")
            if stdout is not None:
                stdout_text = _strip_ansi(stdout).strip()
                if stdout_text:
                    messages.append(create_normalized_message(
                        id=base_id, sessionId=session_id, timestamp=ts, provider=PROVIDER,
                        kind="text", role="assistant", content=stdout_text, isLocalCommandStdout=True,
                    ))
                return messages
            if text and not _is_internal_content(text):
                messages.append(create_normalized_message(
                    id=base_id, sessionId=session_id, timestamp=ts, provider=PROVIDER,
                    kind="text", role="user", content=text,
                ))
        return messages

    if raw.get("type") == "thinking" and message.get("content"):
        messages.append(create_normalized_message(
            id=base_id, sessionId=session_id, timestamp=ts, provider=PROVIDER,
            kind="thinking", content=message.get("content"),
        ))
        return messages

    if raw.get("type") == "tool_use" and raw.get("toolName"):
        messages.append(create_normalized_message(
            id=base_id, sessionId=session_id, timestamp=ts, provider=PROVIDER, kind="tool_use",
            toolName=raw.get("toolName"), toolInput=raw.get("toolInput"),
            toolId=raw.get("toolCallId") or base_id,
        ))
        return messages

    if raw.get("type") == "tool_result":
        messages.append(create_normalized_message(
            id=base_id, sessionId=session_id, timestamp=ts, provider=PROVIDER, kind="tool_result",
            toolId=raw.get("toolCallId") or "", content=raw.get("output") or "", isError=False,
        ))
        return messages

    if role == "assistant" and content is not None:
        if isinstance(content, list):
            for part_index, part in enumerate(content):
                if not isinstance(part, dict):
                    continue
                if part.get("type") == "text" and part.get("text"):
                    messages.append(create_normalized_message(
                        id=f"{base_id}_{part_index}", sessionId=session_id, timestamp=ts,
                        provider=PROVIDER, kind="text", role="assistant", content=part["text"],
                    ))
                elif part.get("type") == "tool_use":
                    messages.append(create_normalized_message(
                        id=f"{base_id}_{part_index}", sessionId=session_id, timestamp=ts,
                        provider=PROVIDER, kind="tool_use", toolName=part.get("name"),
                        toolInput=part.get("input"), toolId=part.get("id"),
                    ))
                elif part.get("type") == "thinking" and part.get("thinking"):
                    messages.append(create_normalized_message(
                        id=f"{base_id}_{part_index}", sessionId=session_id, timestamp=ts,
                        provider=PROVIDER, kind="thinking", content=part["thinking"],
                    ))
        elif isinstance(content, str):
            messages.append(create_normalized_message(
                id=base_id, sessionId=session_id, timestamp=ts, provider=PROVIDER,
                kind="text", role="assistant", content=content,
            ))
        return messages

    return messages


# --- transcript reading -----------------------------------------------------

def _read_jsonl(path: str) -> list[dict]:
    out: list[dict] = []
    try:
        with open(path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except (ValueError, TypeError):
                    continue  # tolerate partial lines from concurrent writes
    except OSError:
        pass
    return out


def _parse_agent_tools(file_path: str) -> list[dict]:
    tools: list[dict] = []
    for entry in _read_jsonl(file_path):
        msg = _as_dict(entry.get("message")) or {}
        content = msg.get("content")
        if msg.get("role") == "assistant" and isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and part.get("type") == "tool_use":
                    tools.append({"toolId": part.get("id"), "toolName": part.get("name"),
                                  "toolInput": part.get("input"), "timestamp": entry.get("timestamp")})
        if msg.get("role") == "user" and isinstance(content, list):
            for part in content:
                if not isinstance(part, dict) or part.get("type") != "tool_result":
                    continue
                tool = next((t for t in tools if t["toolId"] == part.get("tool_use_id")), None)
                if not tool:
                    continue
                pc = part.get("content")
                tool["toolResult"] = {
                    "content": pc if isinstance(pc, str)
                    else ("\n".join(cp.get("text", "") for cp in pc if isinstance(cp, dict))
                          if isinstance(pc, list) else json.dumps(pc)),
                    "isError": bool(part.get("is_error")),
                }
    return tools


def _ts_key(value: Any) -> float:
    if not value:
        return 0.0
    try:
        s = str(value).replace("Z", "+00:00")
        return datetime.fromisoformat(s).timestamp()
    except (ValueError, TypeError):
        return 0.0


def get_session_messages(conn, session_id: str, limit: Optional[int], offset: int):
    """Returns the raw transcript entries for a session (list when limit is None,
    else a paginated dict). Port of getSessionMessages."""
    session = repos.get_session_by_id(conn, session_id)
    jsonl_path = session["jsonl_path"] if session else None
    if not jsonl_path:
        return {"messages": [], "total": 0, "hasMore": False}

    project_dir = os.path.dirname(jsonl_path)
    try:
        agent_files = [f for f in os.listdir(project_dir)
                       if f.endswith(".jsonl") and f.startswith("agent-")]
    except OSError:
        agent_files = []

    messages = [e for e in _read_jsonl(jsonl_path) if e.get("sessionId") == session_id]

    agent_ids = {str((_as_dict(m.get("toolUseResult")) or {}).get("agentId"))
                 for m in messages if (_as_dict(m.get("toolUseResult")) or {}).get("agentId")}
    agent_tools_cache: dict[str, list[dict]] = {}
    for agent_id in agent_ids:
        fname = f"agent-{agent_id}.jsonl"
        if fname in agent_files:
            agent_tools_cache[agent_id] = _parse_agent_tools(os.path.join(project_dir, fname))
    for m in messages:
        agent_id = (_as_dict(m.get("toolUseResult")) or {}).get("agentId")
        if agent_id and agent_tools_cache.get(str(agent_id)):
            m["subagentTools"] = agent_tools_cache[str(agent_id)]

    messages.sort(key=lambda m: _ts_key(m.get("timestamp")))
    total = len(messages)
    if limit is None:
        return messages
    start = max(0, total - offset - limit)
    end = total - offset
    return {"messages": messages[start:end], "total": total, "hasMore": start > 0,
            "offset": offset, "limit": limit}


def fetch_history(conn, session_id: str, limit: Optional[int] = None, offset: int = 0) -> dict:
    """Port of ClaudeSessionsProvider.fetchHistory: normalize the full transcript,
    stitch tool_results onto their tool_use, then paginate over normalized msgs."""
    try:
        result = get_session_messages(conn, session_id, None, 0)
    except Exception:
        return {"messages": [], "total": 0, "hasMore": False, "offset": 0, "limit": None}

    raw_messages = result if isinstance(result, list) else result.get("messages", [])

    tool_result_map: dict[str, dict] = {}
    for raw in raw_messages:
        msg = _as_dict(raw.get("message")) or {}
        if msg.get("role") == "user" and isinstance(msg.get("content"), list):
            for part in msg["content"]:
                if isinstance(part, dict) and part.get("type") == "tool_result" and part.get("tool_use_id"):
                    tool_result_map[part["tool_use_id"]] = {
                        "content": part.get("content"), "isError": bool(part.get("is_error")),
                        "subagentTools": raw.get("subagentTools"), "toolUseResult": raw.get("toolUseResult"),
                    }

    normalized: list[dict] = []
    for raw in raw_messages:
        normalized.extend(normalize_message(raw, session_id))

    for msg in normalized:
        if msg.get("kind") == "tool_use" and msg.get("toolId") in tool_result_map:
            tr = tool_result_map[msg["toolId"]]
            c = tr["content"]
            msg["toolResult"] = {
                "content": c if isinstance(c, str) else json.dumps(c),
                "isError": tr["isError"], "toolUseResult": tr["toolUseResult"],
            }
            msg["subagentTools"] = tr["subagentTools"]

    total_normalized = len(normalized)
    total = sum(1 for m in normalized if m.get("kind") != "tool_result")
    norm_offset = max(0, offset)
    norm_limit = None if limit is None else max(0, limit)
    if norm_limit is None:
        out_messages = normalized
        has_more = False
    else:
        start = max(0, total_normalized - norm_offset - norm_limit)
        end = max(0, total_normalized - norm_offset)
        out_messages = normalized[start:end]
        has_more = start > 0

    return {"messages": out_messages, "total": total, "hasMore": has_more,
            "offset": norm_offset, "limit": norm_limit}
