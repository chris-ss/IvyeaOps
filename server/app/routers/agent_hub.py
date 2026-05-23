"""HTTP + WebSocket routes for the multi-agent hub.

Endpoint groups (all under /api):
  • /agents                       Agent catalog (registered + discovered).
  • /agent-sessions/*             Session CRUD, branch, compact.
  • /agent-chat/sessions/*        Send a chat message; SSE stream of agent
                                   reply.  Backed by the per-session PTY.
  • /agent-cli/{sid}/ws           Live PTY bridge (xterm.js on the front).

All HTTP routes require a logged-in session (cookie).  WebSocket auth
re-uses the same cookie verification at upgrade time.
"""
from __future__ import annotations

import asyncio
import json
import re
import time
from typing import Any

from fastapi import (
    APIRouter,
    Cookie,
    Depends,
    HTTPException,
    Query,
    UploadFile,
    File,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from fastapi.responses import FileResponse
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.core.config import settings
from app.core.security import require_user, verify_session
from app.services import agent_registry as registry
from app.services import agent_session_service as svc
from app.services import compactor
from app.services.pty_manager import manager as pty_manager
from app.services.pty_manager import split_ansi_safe, strip_ansi


router = APIRouter()


# ===========================================================================
# /api/agents
# ===========================================================================
@router.get("/agents")
def list_agents(_user: str = Depends(require_user)) -> dict[str, Any]:
    """Catalog of agents with model lists and binary status."""
    return {"agents": registry.list_agents()}


@router.post("/agents/rediscover")
def rediscover_agents(_user: str = Depends(require_user)) -> dict[str, Any]:
    """Force a fresh probe.  Useful after installing a new CLI."""
    return {"agents": registry.discover_agents()}


# ===========================================================================
# /api/agent-sessions
# ===========================================================================
class CreateSessionBody(BaseModel):
    agent_id: str = Field(..., min_length=1, max_length=64)
    model: str | None = Field(None, max_length=128)
    title: str | None = Field(None, max_length=120)
    workdir: str | None = Field(None, max_length=512)


class UpdateSessionBody(BaseModel):
    title: str | None = None
    archived: bool | None = None
    model: str | None = None


class BranchBody(BaseModel):
    anchor_seq: int = Field(..., ge=1)
    title: str | None = None


@router.get("/agent-sessions")
def list_sessions(
    user: str = Depends(require_user),
    archived: bool = Query(False),
    parent_id: str | None = Query(None),
) -> dict[str, Any]:
    rows = svc.list_sessions(user_id=user, include_archived=archived)
    if parent_id is not None:
        rows = [r for r in rows if r.get("parent_id") == parent_id]
    return {"sessions": rows}


@router.post("/agent-sessions")
def create_session(body: CreateSessionBody, user: str = Depends(require_user)) -> dict[str, Any]:
    # Validate the agent against the registry.  We let unknown agents through
    # gracefully (in case the registry is mid-boot) but flag binary-missing
    # cases to keep error messages clear.
    try:
        adef = registry.get_agent_def(body.agent_id)
    except KeyError:
        raise HTTPException(status_code=400, detail="未知 agent")
    model = body.model or adef.default_model
    sess = svc.create_session(
        user_id=user,
        agent_id=body.agent_id,
        model=model,
        title=body.title,
        workdir=body.workdir,
    )
    return sess


@router.get("/agent-sessions/{sid}")
def get_session(sid: str, _user: str = Depends(require_user)) -> dict[str, Any]:
    sess = svc.get_session(sid)
    sess["children"] = svc.list_children(sid)
    sess["live"] = pty_manager.is_live(sid)
    return sess


@router.patch("/agent-sessions/{sid}")
def update_session(sid: str, body: UpdateSessionBody, _user: str = Depends(require_user)) -> dict[str, Any]:
    return svc.update_session(
        sid,
        title=body.title,
        archived=body.archived,
        model=body.model,
    )


@router.delete("/agent-sessions/{sid}")
def delete_session(sid: str, _user: str = Depends(require_user)) -> dict[str, Any]:
    try:
        svc.delete_session(sid)
    except svc.AgentSessionError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return {"ok": True}


@router.get("/agent-sessions/{sid}/messages")
def list_messages(
    sid: str,
    after_seq: int = Query(0, ge=0),
    limit: int = Query(500, ge=1, le=2000),
    include_cli: bool = Query(True),
    include_inherited: bool = Query(True),
    _user: str = Depends(require_user),
) -> dict[str, Any]:
    rows = svc.list_messages(
        sid,
        after_seq=after_seq,
        limit=limit,
        include_branch_inheritance=include_inherited,
    )
    if not include_cli:
        rows = [r for r in rows if r.get("kind") != "cli_frame"]
    return {"messages": rows, "live": pty_manager.is_live(sid)}


@router.post("/agent-sessions/{sid}/branch")
def branch_session(sid: str, body: BranchBody, _user: str = Depends(require_user)) -> dict[str, Any]:
    try:
        return svc.branch_from(sid, body.anchor_seq, title=body.title)
    except svc.AgentSessionError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/agent-sessions/{sid}/compact")
def compact_session_now(sid: str, _user: str = Depends(require_user)) -> dict[str, Any]:
    try:
        return compactor.compact_session(sid)
    except compactor.CompactorError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/agent-sessions/{sid}/stop")
async def stop_session_pty(sid: str, _user: str = Depends(require_user)) -> dict[str, Any]:
    """Force-quit the PTY without archiving the session."""
    if not pty_manager.is_live(sid):
        return {"ok": True, "was_live": False}
    await pty_manager._kill(sid, reason="user_stop")
    return {"ok": True, "was_live": True}


# ===========================================================================
# /api/agent-chat/sessions/{sid}/messages — SSE stream
# ===========================================================================
class ChatBody(BaseModel):
    content: str = Field(..., min_length=1, max_length=20000)
    # If true, force PTY restart (e.g. user wants a clean slate without
    # creating a new session).  Default is to attach to the existing PTY.
    reset_pty: bool = False


def _sse(event: str, data: Any) -> bytes:
    """Encode an SSE event line."""
    payload = json.dumps(data, ensure_ascii=False) if not isinstance(data, str) else data
    return f"event: {event}\ndata: {payload}\n\n".encode("utf-8")


# Conservative end-of-turn detection. We watch for the agent's interactive
# prompt regex; if that doesn't match within READ_TURN_TIMEOUT we still
# return whatever we have so the client doesn't hang forever.
READ_TURN_TIMEOUT = 240.0  # seconds — long enough for tool runs
QUIET_PERIOD = 1.5         # if no output for this long, treat as turn end


def _build_chat_context(sid: str, user_text: str) -> str:
    """Build a single self-contained prompt that re-states the task context
    plus the new user turn.  Used in oneshot chat mode so each subprocess
    call is stateless (the agent doesn't need to remember earlier turns).

    The prompt is intentionally explicit ("[Task summary]", "[Recent
    messages]", "[New user message]") so the agent treats this as a single
    coherent input rather than thinking it's mid-conversation.
    """
    parts: list[str] = []
    try:
        resume = compactor.build_resume_prompt(sid, max_recent=8)
        if resume.strip():
            parts.append(resume)
    except Exception:
        # build_resume_prompt may fail on a brand-new session with no
        # summary and no prior messages; that's fine.
        pass
    parts.append(f"[New user message]\n{user_text}")
    return "\n\n".join(parts)


@router.post("/agent-chat/sessions/{sid}/messages")
async def chat_message(sid: str, body: ChatBody, _user: str = Depends(require_user)) -> StreamingResponse:
    sess = svc.get_session(sid)
    agent_id = sess["agent_id"]
    try:
        adef = registry.get_agent_def(agent_id)
    except KeyError:
        raise HTTPException(status_code=400, detail="未知 agent")

    # Persist the user message AFTER constructing the prompt context, so the
    # context (which reads recent messages from DB) doesn't include this same
    # turn twice. We also add it before the subprocess starts so the row is
    # visible if the client cancels mid-stream.
    full_prompt_context = _build_chat_context(sid, body.content)
    user_msg = svc.add_message(sid, role="user", kind="text", source="chat", content=body.content)

    # Pick implementation:
    #   Has chat_args  -> oneshot subprocess (clean stdout, stateless).
    #   No chat_args   -> fall back to writing into the per-session PTY.
    if adef.chat_args is not None:
        return await _chat_oneshot(sid, sess, adef, body.content, user_msg, full_prompt_context)
    return await _chat_via_pty(sid, sess, adef, body.content, user_msg, body.reset_pty)


async def _chat_oneshot(
    sid: str,
    sess: dict[str, Any],
    adef: registry.AgentDef,
    user_text: str,
    user_msg: dict[str, Any],
    full_prompt: str,
) -> StreamingResponse:
    """Run the agent as a one-shot subprocess and stream stdout to the client.

    Each invocation is stateless: we re-ship the current task summary and
    recent turns as part of the prompt so the agent has the context.  This
    mirrors how a stateless OpenAI-style API call works and avoids the
    fragility of trying to pin a TUI's prompt boundary.
    """
    try:
        argv, env_extra = registry.build_argv(
            adef.id,
            mode="chat",
            model=sess.get("model"),
            prompt=full_prompt,
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"无法构造命令: {e}")

    # Spawn the subprocess with a captured stdout so we can stream tokens
    # to the SSE client as they arrive.  stderr is folded into stdout via
    # PIPE so error messages also surface.
    import os as _os
    env = _os.environ.copy()
    env.update(env_extra)
    env.setdefault("TERM", "dumb")  # most agents respect this and skip ANSI
    env.setdefault("FORCE_COLOR", "0")
    env.setdefault("NO_COLOR", "1")
    # Ensure the agent's binary directory and any sibling node runtime are
    # reachable on PATH.  Some agents (codex) are #!/usr/bin/env node shell
    # scripts that need `node` to be discoverable.  systemd defaults to a
    # minimal PATH so we augment it here.
    bin_dir = _os.path.dirname(argv[0])
    from app.core import integrations
    extra_paths = [bin_dir, *integrations.extra_path_dirs()]
    cur_path = env.get("PATH", "")
    env["PATH"] = ":".join([p for p in extra_paths if p] + ([cur_path] if cur_path else []))
    cwd = sess.get("workdir") if sess.get("workdir") and _os.path.isdir(sess["workdir"]) else _os.path.expanduser("~")

    try:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=cwd,
            env=env,
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=400, detail=f"agent binary 不存在: {e}")

    accumulated: list[str] = []

    async def gen() -> Any:
        yield _sse("user_message", user_msg)
        # Stream by line so the user sees progress without waiting for EOF.
        # We hold back any incomplete trailing ANSI escape across reads so
        # strip_ansi sees complete sequences and doesn't leak `\x1B[` into
        # the user-visible chat bubble.
        hold = ""
        try:
            assert proc.stdout is not None
            while True:
                chunk = await proc.stdout.read(4096)
                if not chunk:
                    break
                text = hold + chunk.decode("utf-8", errors="replace")
                safe, hold = split_ansi_safe(text)
                if not safe:
                    continue
                cleaned = strip_ansi(safe)
                accumulated.append(cleaned)
                yield _sse("token", {"text": cleaned})
            # flush any leftover (probably a stray bare ESC at EOF).
            if hold:
                cleaned = strip_ansi(hold)
                if cleaned:
                    accumulated.append(cleaned)
                    yield _sse("token", {"text": cleaned})
        except asyncio.CancelledError:
            proc.terminate()
            raise
        rc = await proc.wait()
        # Apply per-agent post-processing.  These regexes operate on the
        # full assembled text (not per-chunk), so multi-line patterns work.
        full = "".join(accumulated)
        if adef.chat_extract_pattern:
            m = re.search(adef.chat_extract_pattern, full, flags=re.DOTALL)
            if m:
                full = m.group("answer")
        for pat in adef.chat_strip_patterns:
            full = re.sub(pat, "", full, flags=re.MULTILINE)
        full = full.strip()
        if full:
            asst = svc.add_message(
                sid,
                role="assistant",
                kind="text",
                source="chat",
                content=full,
                meta={"return_code": rc, "argv0": argv[0]},
            )
            yield _sse("assistant_message", asst)
        if rc != 0:
            yield _sse("warning", {"detail": f"agent 进程返回非 0 退出码 ({rc})"})
        try:
            comp = compactor.maybe_auto_compact(sid)
            if comp:
                yield _sse("auto_compacted", {"summary_id": comp["id"]})
        except Exception:
            pass
        yield _sse("done", {"ok": True})

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
        },
    )


async def _chat_via_pty(
    sid: str,
    sess: dict[str, Any],
    adef: registry.AgentDef,
    user_text: str,
    user_msg: dict[str, Any],
    reset_pty: bool,
) -> StreamingResponse:
    """Fallback for agents without a non-interactive mode.  Writes to the
    per-session PTY and streams its output, terminating the turn on quiet
    period or prompt regex.
    """
    resume_prompt: str | None = None
    if not pty_manager.is_live(sid):
        try:
            resume_prompt = compactor.build_resume_prompt(sid)
        except Exception:
            resume_prompt = None
    if reset_pty and pty_manager.is_live(sid):
        await pty_manager._kill(sid, reason="user_reset")
    try:
        await pty_manager.start(
            sid,
            agent_id=adef.id,
            model=sess.get("model"),
            workdir=sess.get("workdir"),
            resume_prompt=resume_prompt,
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"无法启动 agent: {e}")

    queue = pty_manager.subscribe(sid)
    prompt_regex = re.compile(adef.prompt_regex)
    accumulated: list[str] = []

    async def gen() -> Any:
        yield _sse("user_message", user_msg)
        try:
            await pty_manager.write(sid, user_text + "\n")
        except RuntimeError as e:
            yield _sse("error", {"detail": str(e)})
            return

        deadline = time.time() + READ_TURN_TIMEOUT
        try:
            while True:
                remaining = deadline - time.time()
                if remaining <= 0:
                    yield _sse("warning", {"detail": "回复超时"})
                    break
                try:
                    item = await asyncio.wait_for(queue.get(), timeout=min(remaining, QUIET_PERIOD))
                except asyncio.TimeoutError:
                    if accumulated:
                        break
                    continue
                if item["type"] == "exit":
                    yield _sse("exit", {"code": item.get("code")})
                    break
                if item["type"] == "snapshot":
                    continue
                if item["type"] == "output":
                    cleaned = strip_ansi(item["data"])
                    accumulated.append(cleaned)
                    yield _sse("token", {"text": cleaned})
                    tail = "".join(accumulated)[-200:]
                    if prompt_regex.search(tail):
                        break
        finally:
            pty_manager.unsubscribe(sid, queue)

        full = "".join(accumulated)
        head = user_text.strip()
        if head and full.lstrip().startswith(head):
            full = full.lstrip()[len(head):].lstrip("\n\r")
        m = prompt_regex.search(full[-200:])
        if m:
            full = full[: len(full) - 200 + m.start()].rstrip()
        full = full.strip()
        if full:
            asst = svc.add_message(sid, role="assistant", kind="text", source="chat", content=full)
            yield _sse("assistant_message", asst)
        try:
            comp = compactor.maybe_auto_compact(sid)
            if comp:
                yield _sse("auto_compacted", {"summary_id": comp["id"]})
        except Exception:
            pass
        yield _sse("done", {"ok": True})

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
        },
    )


# ===========================================================================
# /api/agent-cli/{sid}/ws — terminal bridge
# ===========================================================================
async def _ws_authenticate(websocket: WebSocket) -> str | None:
    """Verify the cookie at WS upgrade.  Returns username on success."""
    cookie = websocket.cookies.get(settings.session_cookie_name)
    if not cookie:
        return None
    return verify_session(cookie)


@router.websocket("/agent-cli/{sid}/ws")
async def cli_ws(websocket: WebSocket, sid: str) -> None:
    user = await _ws_authenticate(websocket)
    if not user:
        await websocket.close(code=4401)
        return
    # Validate session existence.
    try:
        sess = svc.get_session(sid)
    except svc.AgentSessionError:
        await websocket.close(code=4404)
        return
    await websocket.accept()

    # Lazily start the PTY if the user opened the CLI tab on a dormant
    # session.  Inject a resume prompt to wake the agent gracefully.
    if not pty_manager.is_live(sid):
        try:
            resume_prompt = None
            try:
                resume_prompt = compactor.build_resume_prompt(sid)
            except Exception:
                pass
            await pty_manager.start(
                sid,
                agent_id=sess["agent_id"],
                model=sess.get("model"),
                workdir=sess.get("workdir"),
                resume_prompt=resume_prompt,
            )
        except Exception as e:
            # Instead of closing immediately, try once more without resume
            try:
                await pty_manager.start(
                    sid,
                    agent_id=sess["agent_id"],
                    model=sess.get("model"),
                    workdir=sess.get("workdir"),
                    resume_prompt=None,
                )
            except Exception as e2:
                await websocket.send_json({"type": "error", "detail": str(e2)})
                await websocket.close(code=4500)
                return

    queue = pty_manager.subscribe(sid)
    send_task: asyncio.Task | None = None

    async def pump_to_client() -> None:
        try:
            while True:
                item = await queue.get()
                await websocket.send_json(item)
                if item.get("type") == "exit":
                    break
        except (WebSocketDisconnect, RuntimeError):
            return

    send_task = asyncio.create_task(pump_to_client(), name=f"ws-pump-{sid[:6]}")
    try:
        while True:
            msg = await websocket.receive_text()
            try:
                payload = json.loads(msg)
            except json.JSONDecodeError:
                # Plain-text fallback: treat as raw input.
                payload = {"type": "input", "data": msg}
            t = payload.get("type")
            if t == "input":
                data = payload.get("data") or ""
                if data:
                    try:
                        await pty_manager.write(sid, data)
                    except RuntimeError as e:
                        await websocket.send_json({"type": "error", "detail": str(e)})
            elif t == "resize":
                cols = int(payload.get("cols") or 80)
                rows = int(payload.get("rows") or 24)
                await pty_manager.resize(sid, cols, rows)
            elif t == "ping":
                await websocket.send_json({"type": "pong", "t": time.time()})
            else:
                await websocket.send_json({"type": "error", "detail": f"未知消息类型: {t}"})
    except WebSocketDisconnect:
        pass
    finally:
        pty_manager.unsubscribe(sid, queue)
        if send_task and not send_task.done():
            send_task.cancel()


# ===========================================================================
# /api/agent-files — simple file manager for session workdir
# ===========================================================================
import os as _os
from pathlib import Path as _Path

# Paths that must never be written to (or read from) via the agent file API.
# Includes obvious kernel interfaces plus base OS directories that, even when
# the process runs as root, should not be mutated through a web UI — moving
# /etc/passwd is the canonical "oops" incident this list defends against.
_FORBIDDEN_PREFIXES = (
    "/proc", "/sys", "/dev", "/boot",
    "/etc", "/usr", "/lib", "/lib64", "/sbin", "/bin",
    "/var/lib", "/var/log",
    # /run holds systemd state; touching it can wedge services.
    "/run",
)


def _safe_path(base: str, rel: str) -> _Path:
    """Resolve a relative path under base, preventing traversal."""
    resolved = (_Path(base) / rel).resolve()
    base_resolved = _Path(base).resolve()
    if not str(resolved).startswith(str(base_resolved)):
        raise HTTPException(403, "路径越界")
    for prefix in _FORBIDDEN_PREFIXES:
        if str(resolved).startswith(prefix):
            raise HTTPException(403, "禁止访问系统目录")
    return resolved


@router.get("/agent-files/list")
def list_files(
    path: str = Query("/root"),
    _user: str = Depends(require_user),
) -> dict[str, Any]:
    """List directory contents."""
    target = _Path(path).resolve()
    for prefix in _FORBIDDEN_PREFIXES:
        if str(target).startswith(prefix):
            raise HTTPException(403, "禁止访问系统目录")
    if not target.is_dir():
        raise HTTPException(404, "目录不存在")
    items = []
    try:
        for entry in sorted(target.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower())):
            try:
                st = entry.stat()
                items.append({
                    "name": entry.name,
                    "is_dir": entry.is_dir(),
                    "size": st.st_size if not entry.is_dir() else None,
                    "mtime": st.st_mtime,
                })
            except (PermissionError, OSError):
                continue
    except PermissionError:
        raise HTTPException(403, "无权限读取目录")
    return {"path": str(target), "items": items}


@router.get("/agent-files/download")
def download_file(
    path: str = Query(...),
    _user: str = Depends(require_user),
):
    """Download a single file."""
    target = _Path(path).resolve()
    for prefix in _FORBIDDEN_PREFIXES:
        if str(target).startswith(prefix):
            raise HTTPException(403, "禁止访问系统目录")
    if not target.is_file():
        raise HTTPException(404, "文件不存在")
    return FileResponse(str(target), filename=target.name)


@router.post("/agent-files/upload")
async def upload_file(
    dest: str = Query(""),
    file: UploadFile = File(...),
    _user: str = Depends(require_user),
) -> dict[str, Any]:
    """Upload a file. Defaults to ~/saved-images when no dest given."""
    if not dest:
        target_dir = _Path.home() / "saved-images"
        target_dir.mkdir(parents=True, exist_ok=True)
    else:
        target_dir = _Path(dest).resolve()
    for prefix in _FORBIDDEN_PREFIXES:
        if str(target_dir).startswith(prefix):
            raise HTTPException(403, "禁止访问系统目录")
    if not target_dir.is_dir():
        raise HTTPException(404, "目标目录不存在")
    filename = _Path(file.filename).name if file.filename else "upload"
    target_file = target_dir / filename
    content = await file.read()
    target_file.write_bytes(content)
    return {"ok": True, "path": str(target_file), "size": len(content)}


@router.post("/agent-files/delete")
def delete_file(
    path: str = Query(...),
    _user: str = Depends(require_user),
) -> dict[str, Any]:
    """Delete a file or directory (recursive)."""
    import shutil
    target = _Path(path).resolve()
    for prefix in _FORBIDDEN_PREFIXES:
        if str(target).startswith(prefix):
            raise HTTPException(403, "禁止访问系统目录")
    if not target.exists():
        raise HTTPException(404, "文件不存在")
    if target.is_dir():
        shutil.rmtree(str(target))
    else:
        target.unlink()
    return {"ok": True}


@router.post("/agent-files/mkdir")
def mkdir(
    path: str = Query(..., description="Parent directory the new folder lives in"),
    name: str = Query(..., description="Folder name (no slashes)"),
    _user: str = Depends(require_user),
) -> dict[str, Any]:
    """Create a new directory under ``path/``. Refuses if the new folder
    would land in a forbidden system prefix, or if a file already exists
    at the target path (we don't overwrite)."""
    if "/" in name or "\\" in name or name in ("", ".", ".."):
        raise HTTPException(400, "非法目录名")
    parent = _Path(path).resolve()
    for prefix in _FORBIDDEN_PREFIXES:
        if str(parent).startswith(prefix):
            raise HTTPException(403, "禁止访问系统目录")
    if not parent.is_dir():
        raise HTTPException(404, "父目录不存在")
    target = (parent / name).resolve()
    # Re-check resolved path to defeat ../ trickery.
    if not str(target).startswith(str(parent)):
        raise HTTPException(400, "路径越界")
    for prefix in _FORBIDDEN_PREFIXES:
        if str(target).startswith(prefix):
            raise HTTPException(403, "禁止访问系统目录")
    if target.exists():
        raise HTTPException(409, "同名条目已存在")
    target.mkdir(parents=False)
    return {"ok": True, "path": str(target)}


@router.post("/agent-files/rename")
def rename(
    path: str = Query(..., description="Existing file or directory to rename"),
    new_name: str = Query(..., description="New basename (no slashes)"),
    _user: str = Depends(require_user),
) -> dict[str, Any]:
    """Rename an entry within its parent directory. Cross-directory moves
    are intentionally not allowed via this endpoint — use a separate move
    operation if/when needed."""
    if "/" in new_name or "\\" in new_name or new_name in ("", ".", ".."):
        raise HTTPException(400, "非法文件名")
    source = _Path(path).resolve()
    for prefix in _FORBIDDEN_PREFIXES:
        if str(source).startswith(prefix):
            raise HTTPException(403, "禁止访问系统目录")
    if not source.exists():
        raise HTTPException(404, "源文件不存在")
    target = (source.parent / new_name).resolve()
    if not str(target).startswith(str(source.parent)):
        raise HTTPException(400, "路径越界")
    for prefix in _FORBIDDEN_PREFIXES:
        if str(target).startswith(prefix):
            raise HTTPException(403, "禁止访问系统目录")
    if target.exists():
        raise HTTPException(409, "同名条目已存在")
    source.rename(target)
    return {"ok": True, "path": str(target)}
