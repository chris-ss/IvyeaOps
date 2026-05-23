"""Read an external (Claude / Codex) jsonl session into structured messages.

Used by the Workspace's transcript viewer when the user clicks a non-hub
session. We don't need full fidelity — just enough to render a readable
"who said what" view: role, text, timestamp, occasional tool annotation.

Both formats differ enough that each gets its own parser, but the output
is a uniform list of TranscriptMessage dicts.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


def read_claude_jsonl(jsonl_path: Path, limit: int = 2000) -> list[dict[str, Any]]:
    """Parse a Claude Code rollout. Each line is a JSON object with `type`
    in {user, assistant, system, attachment, tool_use, tool_result, ...}
    and a `message` or `content` field.

    Returns at most ``limit`` messages, newest first dropped if exceeded.
    """
    out: list[dict[str, Any]] = []
    try:
        with jsonl_path.open("r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                msg = _claude_record_to_message(rec)
                if msg is None:
                    continue
                out.append(msg)
                if len(out) > limit:
                    # Drop oldest in the middle to keep both head and tail.
                    out.pop(len(out) // 2)
    except Exception:
        return out
    return out


def _claude_record_to_message(rec: dict) -> dict | None:
    """Map one Claude jsonl record → uniform message dict.

    The interesting records are ``type='user'`` and ``type='assistant'``
    where the actual chat payload lives under ``record.message`` as
    ``{role, content}``. ``content`` can be a string or a list of
    content blocks (text / tool_use / tool_result / image).
    """
    t = rec.get("type")
    ts = rec.get("timestamp") or rec.get("created_at")
    if t in ("user", "assistant"):
        msg = rec.get("message")
        if not isinstance(msg, dict):
            return None
        role = msg.get("role") or t
        content = msg.get("content")
        # Claude's slash-command bookkeeping records leak the caveat / stdout
        # blocks into the user role. They're not human-typed messages, so
        # drop them from the transcript to keep it readable.
        if isinstance(content, str):
            stripped = content.lstrip()
            if stripped.startswith(("<local-command-stdout", "<local-command-caveat", "<command-stdout", "<command-message")):
                return None
        # content may itself be a list with embedded tool_use / tool_result
        # blocks; render them inline so the transcript stays readable.
        if isinstance(content, list):
            chunks: list[str] = []
            for part in content:
                if not isinstance(part, dict):
                    if part:
                        chunks.append(str(part))
                    continue
                pt = part.get("type")
                if pt == "text":
                    chunks.append(str(part.get("text") or ""))
                elif pt == "tool_use":
                    name = part.get("name") or "tool"
                    args = part.get("input")
                    chunks.append(f"[工具调用: {name}] {_clip(_flatten_content(args), 200)}")
                elif pt == "tool_result":
                    chunks.append(f"[工具结果] {_clip(_flatten_content(part.get('content')), 600)}")
                elif pt in ("image", "input_image"):
                    chunks.append("[图片]")
                elif "text" in part:
                    chunks.append(str(part["text"]))
            text = "\n".join(c for c in chunks if c).strip()
        else:
            text = _flatten_content(content)
        if not text:
            return None
        return {
            "role": role if role in ("user", "assistant", "system") else t,
            "text": text,
            "ts": ts,
            "kind": "text",
        }
    if t == "system":
        # Skip noisy permission / config events; keep ones with visible text.
        msg = rec.get("message")
        if isinstance(msg, dict):
            text = _flatten_content(msg.get("content"))
        else:
            text = _flatten_content(rec.get("content") or rec.get("text"))
        if not text or len(text) < 4:
            return None
        return {"role": "system", "text": text, "ts": ts, "kind": "system"}
    # Skip permission-mode, attachment, file-history-snapshot, ai-title, summary, etc.
    return None


def read_codex_jsonl(jsonl_path: Path, limit: int = 2000) -> list[dict[str, Any]]:
    """Parse a Codex rollout. Each line is `{timestamp, type, payload}`.
    payload is a JSON object (newer versions) or stringified dict (older);
    we only handle the JSON-object form. The interesting types are
    ``response_item`` (the actual exchange) and ``event_msg`` (status)."""
    out: list[dict[str, Any]] = []
    try:
        with jsonl_path.open("r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                msg = _codex_record_to_message(rec)
                if msg is None:
                    continue
                out.append(msg)
                if len(out) > limit:
                    out.pop(len(out) // 2)
    except Exception:
        return out
    return out


def _codex_record_to_message(rec: dict) -> dict | None:
    rec_type = rec.get("type")
    ts = rec.get("timestamp")
    payload = rec.get("payload")

    if rec_type == "response_item" and isinstance(payload, dict):
        # response_item: message, function_call, function_call_output, reasoning
        kind = payload.get("type")
        if kind == "message":
            role = payload.get("role") or "user"
            text = _flatten_content(payload.get("content"))
            if not text:
                return None
            return {"role": role if role in ("user", "assistant", "system") else "system",
                    "text": text, "ts": ts, "kind": "text"}
        if kind == "function_call":
            name = payload.get("name") or "tool"
            args = payload.get("arguments")
            return {"role": "assistant",
                    "text": f"[工具调用: {name}] {_clip(_flatten_content(args), 200)}",
                    "ts": ts, "kind": "tool_call"}
        if kind == "function_call_output":
            return {"role": "system",
                    "text": f"[工具结果] {_clip(_flatten_content(payload.get('output')), 600)}",
                    "ts": ts, "kind": "tool_result"}
        if kind == "reasoning":
            # Skip — reasoning blocks are private and noisy.
            return None
    if rec_type == "event_msg" and isinstance(payload, dict):
        # Status events: task_started, agent_message_delta. Skip everything
        # except agent_message which contains the final user-visible text.
        evt = payload.get("type")
        if evt == "agent_message":
            text = payload.get("message") or ""
            if text:
                return {"role": "assistant", "text": text, "ts": ts, "kind": "text"}
    return None


# ─── Helpers ───────────────────────────────────────────────────────────────

def _flatten_content(content: Any) -> str:
    """Reduce a Claude/Codex `content` field to a single string.

    Acceptable shapes:
      - str
      - list[{type:'text', text:'...'}] / [{type:'input_text', text:'...'}]
      - list[{type:'image', ...}] (we replace with "[image]")
      - dict (rare) — json-dumped
    """
    if content is None:
        return ""
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, dict):
        try:
            return json.dumps(content, ensure_ascii=False)[:1200]
        except Exception:
            return str(content)[:1200]
    if isinstance(content, list):
        parts: list[str] = []
        for p in content:
            if isinstance(p, str):
                parts.append(p)
            elif isinstance(p, dict):
                pt = p.get("type")
                if pt in ("text", "input_text", "output_text"):
                    parts.append(str(p.get("text") or ""))
                elif pt in ("image", "input_image", "image_url"):
                    parts.append("[图片]")
                elif "text" in p:
                    parts.append(str(p["text"]))
                else:
                    parts.append(json.dumps(p, ensure_ascii=False)[:200])
        return " ".join(s for s in parts if s).strip()
    return str(content)[:1200]


_WS_RE = re.compile(r"\s+")


def _clip(text: str, max_len: int) -> str:
    if not text:
        return ""
    text = _WS_RE.sub(" ", text).strip()
    if len(text) > max_len:
        return text[: max_len - 1] + "…"
    return text
