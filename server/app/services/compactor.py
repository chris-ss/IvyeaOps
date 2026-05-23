"""Session compactor.

Hooks the LLM gateway (kiro-gateway, /v1/messages) to compress the running
chat history into a short summary when:

  - The user explicitly hits "compact" in the UI.
  - We're about to wake a dormant session (so the new PTY starts with a
    fresh, lossy-but-coherent context).
  - The token estimate for the live trail crosses a threshold (auto).

Failure mode: any exception is reported back to the caller so the router can
surface it as a non-fatal toast. We never fall back silently to the full
unsummarized history because that would defeat the purpose of compaction
when the trail is already too big to fit in the agent's context window.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from app.services import agent_session_service as svc

# Auto-compact when uncompressed token estimate exceeds this. Tunable per
# deployment via env. ~32k matches Claude/GPT context windows comfortably.
AUTO_COMPACT_THRESHOLD = int(os.environ.get("OPSHUB_AUTOCOMPACT_TOKENS", "32000"))

# Model used for the summarization step. Route explicitly to GPT so we no
# longer depend on the retired localhost:8000 gateway.
SUMMARY_MODEL = os.environ.get("OPSHUB_SUMMARY_MODEL", "gpt-5.4")
SUMMARY_PROVIDER = os.environ.get("OPSHUB_SUMMARY_PROVIDER", "openai-codex")
SUMMARY_MAX_TOKENS = int(os.environ.get("OPSHUB_SUMMARY_MAX_TOKENS", "1200"))


SYSTEM_PROMPT = """You are a session compactor. Compress the agent conversation
into a structured Markdown brief. Keep:

  • Goal — what the user is trying to accomplish.
  • Decisions — confirmed conclusions, file paths, parameters.
  • Progress — what is done and what is in flight.
  • Open items — unfinished sub-tasks, errors, blockers.
  • Next step — the immediate action when the session resumes.

Drop pleasantries, acknowledgments, retried prompts, and redundant logs.
Keep concrete commands, identifiers, and short code snippets that the agent
will need to continue. Output Chinese if the conversation is in Chinese,
else match the dominant language. Do NOT invent details that are not
already present in the messages.
"""


class CompactorError(RuntimeError):
    pass


def _gather_messages(session_id: str) -> list[dict[str, str]]:
    """Build the LLM payload from this session's history.

    We prefer messages produced *after* the last summary (so summaries don't
    cascade and we don't grow indefinitely). If there is no prior summary
    we just include everything since seq=0.
    """
    last = svc.latest_summary(session_id)
    after_seq = int(last["upto_seq"]) if last else 0
    rows = svc.list_messages(session_id, after_seq=after_seq, include_branch_inheritance=False)
    payload: list[dict[str, str]] = []
    if last:
        # Seed with the prior summary as a system note so the model carries
        # forward older context without us re-shipping it.
        payload.append({
            "role": "user",
            "content": f"[Prior summary]\n{last['content']}",
        })
    for row in rows:
        # Skip our own summary system messages — the gateway sees the prior
        # summary above; including them again just dilutes signal.
        if row["role"] == "system" and row.get("kind") == "summary":
            continue
        # CLI frames are noisy ANSI; we keep them but clipped, since they
        # often contain command outputs that matter for context recovery.
        content = row["content"]
        if row.get("kind") == "cli_frame" and len(content) > 4000:
            content = content[:2000] + "\n[...trimmed...]\n" + content[-1500:]
        # Map our internal roles into a simple role/content pair for the CLI
        # summarizer. Anything that's not user/assistant becomes a "user" turn
        # with a label so the model still sees it.
        role = row["role"] if row["role"] in {"user", "assistant"} else "user"
        prefix = "" if row["role"] in {"user", "assistant"} else f"[{row['role']}/{row.get('kind','text')}] "
        payload.append({"role": role, "content": prefix + content})
    return payload


def _hermes_bin() -> str:
    from app.core import integrations
    # Legacy override kept for backward compat; new code should use hub_settings.
    legacy = os.environ.get("BRAIN_CHAT_HERMES_BIN", "").strip()
    if legacy and Path(legacy).exists():
        return legacy
    resolved = integrations.hermes_bin()
    if resolved:
        return resolved
    raise CompactorError("Hermes CLI 不可用：没有找到 hermes 可执行文件。")


def _hermes_env() -> dict[str, str]:
    from app.core import integrations
    env = os.environ.copy()
    extra_paths = [*integrations.extra_path_dirs(), "/usr/local/bin", "/usr/bin"]
    env["PATH"] = ":".join(extra_paths + [env.get("PATH", "")])
    env.setdefault("PYTHONUNBUFFERED", "1")
    env.setdefault("HERMES_ACCEPT_HOOKS", "1")
    return env


def _messages_to_prompt(messages: list[dict[str, str]]) -> str:
    chunks = [SYSTEM_PROMPT.strip(), "", "下面是需要压缩的会话消息。请直接输出结构化 Markdown 摘要，不要解释：", ""]
    for msg in messages:
        role = (msg.get("role") or "user").upper()
        chunks.append(f"--- {role} ---\n{msg.get('content', '')}")
    return "\n\n".join(chunks).strip()


def _strip_hermes_output(output: str) -> str:
    lines = [line for line in output.splitlines() if not line.strip().startswith("session_id:")]
    text = "\n".join(lines).strip()
    if not text:
        raise CompactorError("Hermes 返回了空响应")
    return text


def _call_summary_model(messages: list[dict[str, str]]) -> tuple[str, int]:
    """Call Hermes CLI and return (summary, token_estimate)."""
    if not messages:
        raise CompactorError("没有可压缩的消息")
    prompt = _messages_to_prompt(messages)
    cmd = [
        _hermes_bin(),
        "chat",
        "-q",
        prompt,
        "-Q",
        "--source",
        "ops-hub-session-compactor",
        "--max-turns",
        "1",
        "--toolsets",
        "",
        "--provider",
        SUMMARY_PROVIDER,
        "-m",
        SUMMARY_MODEL,
    ]
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(Path.home()),
            env=_hermes_env(),
            text=True,
            capture_output=True,
            timeout=180,
        )
    except subprocess.TimeoutExpired as e:
        raise CompactorError("压缩请求超时") from e
    except Exception as e:
        raise CompactorError(f"压缩请求失败: {e}") from e
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()[-1200:]
        raise CompactorError(f"压缩失败: {detail or '未知错误'}")
    summary = _strip_hermes_output(proc.stdout)
    token_estimate = max(1, len(summary) // 4)
    return summary, token_estimate


def compact_session(session_id: str) -> dict[str, Any]:
    """Run the compactor for this session and persist the result.

    Returns the new summary dict. Caller is responsible for surfacing this
    back to the user.
    """
    sess = svc.get_session(session_id)
    upto_seq = svc.get_max_seq(session_id)
    if upto_seq == 0:
        raise CompactorError("会话还没有消息，无需压缩")
    messages = _gather_messages(session_id)
    summary, est = _call_summary_model(messages)
    return svc.add_summary(
        session_id,
        upto_seq=upto_seq,
        content=summary,
        token_estimate=est,
    )


def maybe_auto_compact(session_id: str) -> dict[str, Any] | None:
    """Auto-trigger compaction if the running token estimate has crossed
    the threshold. Idempotent on undersized sessions."""
    sess = svc.get_session(session_id)
    if int(sess.get("token_estimate") or 0) < AUTO_COMPACT_THRESHOLD:
        return None
    try:
        return compact_session(session_id)
    except CompactorError:
        # Don't crash the request path; the user can retry manually.
        return None


def build_resume_prompt(session_id: str, max_recent: int = 5) -> str:
    """Construct a single text blob that re-anchors a fresh agent instance
    on the prior context. Combines the latest summary with the most recent
    raw turns (because some details only land in last-mile messages).

    Returns an empty string when the session has no summary and no prior
    user/assistant messages — there's nothing to "resume" from.
    """
    last = svc.latest_summary(session_id)
    recent = svc.list_messages(session_id, after_seq=last["upto_seq"] if last else 0)
    # Filter to just user/assistant turns; system summaries already covered.
    recent = [r for r in recent if r["role"] in ("user", "assistant") and r.get("kind") == "text"]
    recent = recent[-max_recent:]
    if not last and not recent:
        return ""
    parts: list[str] = []
    if last:
        parts.append(f"[会话恢复 / 任务摘要]\n{last['content']}")
    if recent:
        parts.append("[最近消息]")
        for m in recent:
            tag = m["role"].upper()
            parts.append(f"--- {tag} ---\n{m['content']}")
    parts.append(
        "[继续指令] 请基于以上上下文继续之前的任务。如有不确定的地方，请先简短确认再行动。"
    )
    return "\n\n".join(parts)
