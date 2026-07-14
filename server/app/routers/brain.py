"""GBrain web API for the IvyeaOps knowledge base UI."""
from __future__ import annotations

import asyncio
import codecs
import json
import time
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.core.proc import no_window_kwargs
from app.core.security import require_user
from app.services import brain_chat_service as bc
from app.services import gbrain_service as gb
from app.services import ivyea_agent_service as ia


router = APIRouter(dependencies=[Depends(require_user)])


class SearchBody(BaseModel):
    query: str = Field(..., min_length=1, max_length=gb.MAX_QUERY_CHARS)
    mode: str = Field("search", pattern="^(search|query)$")


class FileWriteBody(BaseModel):
    path: str = Field(..., min_length=1, max_length=240)
    content: str = Field(..., max_length=gb.MAX_WRITE_BYTES)


class PageBody(BaseModel):
    slug: str = Field(..., min_length=1, max_length=200)


class ChatSessionCreateBody(BaseModel):
    title: str | None = Field(default=None, max_length=80)
    mode: str = Field(default="knowledge", pattern="^(knowledge|general|amazon_operator)$")


class ChatSessionUpdateBody(BaseModel):
    title: str | None = Field(default=None, max_length=80)
    archived: bool | None = None


class ChatMessageBody(BaseModel):
    content: str = Field(..., min_length=1, max_length=bc.MAX_CHAT_CHARS)


class ChatStreamBody(BaseModel):
    content: str = Field("", max_length=bc.MAX_CHAT_CHARS)
    regenerate: bool = False
    category: str | None = Field(None, max_length=40)


class IngestTextBody(BaseModel):
    text: str = Field(..., min_length=1, max_length=bc.MAX_INGEST_TEXT_CHARS)
    import_after_save: bool = True


class IngestUrlBody(BaseModel):
    url: str = Field(..., min_length=8, max_length=2000)
    import_after_save: bool = True


def _handle(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except (gb.GBrainError, bc.BrainChatError) as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


def _ivyea_front_door() -> bool:
    """The governed IvyeaAgent knowledge base is the front door for search and
    pages; the legacy GBrain markdown store is only a fallback when the local
    IvyeaAgent service is down."""
    return bc.ivyea_chat_available()


def _ia_search(query: str, mode: str) -> dict[str, Any]:
    res = ia.knowledge_search(query, limit=12)
    items: list[dict[str, Any]] = []
    for r in (res.get("results") or []):
        items.append({
            "slug": r.get("id"),
            "score": r.get("score", 0),
            "snippet": r.get("snippet") or "",
            "title": r.get("title") or "",
            "source_url": r.get("source_url") or "",
            "marketplaces": r.get("marketplaces") or [],
        })
    return {"mode": mode, "query": query, "raw": "", "items": items, "source": "ivyea-agent"}


def _ia_page(slug: str) -> dict[str, Any]:
    res = ia.knowledge_card(slug)
    card = res.get("card") or {}
    body = str(card.get("body") or "")
    src = card.get("source_url") or ""
    header = f"> 来源：{src}\n\n" if src else ""
    return {"slug": slug, "content": (header + body) if body else body,
            "title": card.get("title") or "", "source_url": src, "source": "ivyea-agent"}


def _ia_list_files() -> dict[str, Any]:
    res = ia.knowledge_cards(limit=1000)
    files: list[dict[str, Any]] = []
    for c in (res.get("cards") or []):
        cid = c.get("id") or ""
        files.append({
            "path": cid,                       # card id doubles as the read key
            "name": c.get("title") or cid,
            "summary": (c.get("snippet") or "")[:100],
            "size": 0,
            "category": c.get("category") or "",
            "scope": c.get("scope") or "",
            "marketplaces": c.get("marketplaces") or [],
        })
    files.sort(key=lambda f: (str(f.get("category")), str(f.get("name"))))
    return {"files": files, "source": "ivyea-agent"}


def _ia_read_file(path: str) -> dict[str, Any]:
    # The pages tab is an editor; return the raw card body (no injected "> 来源"
    # header) so an edit round-trips cleanly through write_file.
    res = ia.knowledge_card(path)
    card = res.get("card") or {}
    return {"path": path, "content": str(card.get("body") or ""),
            "title": card.get("title") or "", "source_url": card.get("source_url") or "", "source": "ivyea-agent"}


def _strip_source_header(text: str) -> str:
    """Defensively drop a leading '> 来源：…' blockquote (added by _ia_page) if it
    slipped into an edited body."""
    lines = text.split("\n")
    i = 0
    while i < len(lines) and (lines[i].startswith("> 来源：") or not lines[i].strip()):
        if lines[i].startswith("> 来源："):
            i += 1
            while i < len(lines) and not lines[i].strip():
                i += 1
            return "\n".join(lines[i:])
        i += 1
    return text


def _ia_upload_result(resp: dict[str, Any], preview: str = "") -> dict[str, Any]:
    # With confirm=True the applied card lands under resp["apply"]["card"];
    # otherwise only a draft/upload record exists.
    apply = resp.get("apply") or {}
    card = apply.get("card") or resp.get("card") or {}
    up = resp.get("upload") or {}
    card_id = card.get("id") or ""
    saved = card.get("path") or card_id or up.get("extracted_path") or "已保存到 IvyeaAgent 知识库"
    # The applied card only carries a body_hash, not the body, so fall back to the
    # source text the caller ingested for the preview/summary.
    body = str(card.get("body") or preview or "")
    # Align with BrainUploadResponse so the RESULT panel renders (the frontend
    # reads warnings/markdown_preview/analysis unconditionally).
    return {
        "saved_path": saved,
        "import_status": "ok",
        "card_id": card_id,
        "warnings": list(apply.get("warnings") or []),
        "markdown_preview": body[:4000],
        "analysis": {
            "title": card.get("title") or "",
            "directory": card.get("category") or "inbox",
            "tags": card.get("tags") or [],
            "summary": (card.get("snippet") or body[:200]),
            "content_type": card.get("content_type") or "note",
            "confidence": 1.0,
            "source": "ivyea-agent",
        },
        "source": "ivyea-agent",
    }


def _ia_upload_bytes(filename: str, data: bytes, title: str | None, category: str | None) -> dict[str, Any]:
    import base64
    payload = {
        "filename": filename or "upload.txt",
        "content_base64": base64.b64encode(data).decode("ascii"),
        "title": (title or "").strip(),
        "source_type": "user",
        "tags": [category] if category else [],
        "confirm": True,   # save + apply into the governed knowledge base in one step
        "rebuild": True,
    }
    try:
        preview = data.decode("utf-8")  # text uploads; binary (pdf/xlsx) → no preview
    except UnicodeDecodeError:
        preview = ""
    return _ia_upload_result(ia.knowledge_upload(payload), preview=preview)


def _ia_ingest_text(text: str) -> dict[str, Any]:
    first = next((ln.strip().lstrip("# ").strip() for ln in text.splitlines() if ln.strip()), "note")
    stem = (first[:40] or "note")
    return _ia_upload_bytes(f"{stem}.md", text.encode("utf-8"), title=first[:80], category="inbox")


@router.get("/overview")
def overview() -> dict[str, Any]:
    # Self-heal first: auto-init the DB + auto-wire Ollama embedding so the board
    # works without manual setup. If the DB still can't come up (e.g. incompatible
    # gbrain version), return the readiness info — with an actionable hint — instead
    # of letting gb.overview() raise the raw "No database URL" error.
    try:
        ready = gb.ensure_ready()
    except Exception as e:  # noqa: BLE001 — never let self-heal break the board
        ready = {"db_ready": False, "version_compatible": True, "actions": [], "hint": str(e)}
    if not ready.get("db_ready"):
        return {"ready": ready, "embed_configured": False, "stats": {},
                "brain_root": "", "gbrain_bin": "", "doctor_status": "not_ready",
                "search_mode": "unknown", "git_dirty": False, "git_status": ""}
    ov = _handle(gb.overview)
    ov["ready"] = ready
    return ov


@router.get("/stats")
def stats() -> dict[str, Any]:
    return _handle(gb.stats)


@router.get("/doctor")
def doctor() -> dict[str, Any]:
    return _handle(gb.doctor)


@router.post("/search")
def search(body: SearchBody) -> dict[str, Any]:
    if _ivyea_front_door():
        try:
            return _ia_search(body.query, body.mode)
        except Exception:  # noqa: BLE001 — degrade to legacy GBrain search
            pass
    return _handle(gb.search, body.query, body.mode)


@router.get("/page/{slug:path}")
def get_page(slug: str) -> dict[str, Any]:
    if _ivyea_front_door():
        try:
            return _ia_page(slug)
        except Exception:  # noqa: BLE001 — degrade to legacy GBrain page
            pass
    return _handle(gb.get_page, slug)


@router.post("/page")
def get_page_post(body: PageBody) -> dict[str, Any]:
    if _ivyea_front_door():
        try:
            return _ia_page(body.slug)
        except Exception:  # noqa: BLE001 — degrade to legacy GBrain page
            pass
    return _handle(gb.get_page, body.slug)


@router.get("/files")
def list_files() -> dict[str, Any]:
    if _ivyea_front_door():
        try:
            return _ia_list_files()
        except Exception:  # noqa: BLE001 — degrade to legacy GBrain file list
            pass
    return _handle(gb.list_files)


@router.get("/file")
def read_file(path: str = Query(..., min_length=1, max_length=240)) -> dict[str, Any]:
    # A card id (e.g. "policies.account_health_ca") has no path separator; a
    # legacy GBrain file always does. Route card ids to the governed KB.
    if _ivyea_front_door() and "/" not in path:
        try:
            return _ia_read_file(path)
        except Exception:  # noqa: BLE001 — degrade to legacy GBrain read
            pass
    return _handle(gb.read_file, path)


@router.put("/file")
def write_file(body: FileWriteBody, user: str = Depends(require_user)) -> dict[str, Any]:
    _ = user
    # IvyeaAgent front door: card ids have no path separator. Route user-card
    # edits through the governed update/apply flow; official (builtin) cards are
    # not editable here — they go through the governance review/publish flow.
    if _ivyea_front_door() and "/" not in body.path:
        cid = body.path
        if not cid.startswith("user."):
            raise HTTPException(status_code=400, detail="这是 IvyeaAgent 官方治理知识卡，请在「治理中心」走审核发布流程编辑，不能直接改写。")
        try:
            title = (ia.knowledge_card(cid).get("card") or {}).get("title") or cid
        except Exception:  # noqa: BLE001
            title = cid
        try:
            resp = ia.knowledge_card_update(cid, title, _strip_source_header(body.content))
        except ia.IvyeaAgentError as e:
            raise HTTPException(status_code=400, detail=f"保存到 IvyeaAgent 失败：{e}") from e
        if not resp.get("ok"):
            raise HTTPException(status_code=400, detail=f"保存失败：{resp.get('result') or resp}")
        return {"ok": True, "path": cid, "saved_path": cid, "source": "ivyea-agent"}
    return _handle(gb.write_file, body.path, body.content)


@router.delete("/file")
def delete_file(path: str = Query(..., min_length=1, max_length=240), user: str = Depends(require_user)) -> dict[str, Any]:
    _ = user
    if _ivyea_front_door() and "/" not in path:
        cid = path
        if not cid.startswith("user."):
            raise HTTPException(status_code=400, detail="IvyeaAgent 官方治理知识卡不能在此删除，请到「治理中心」处理。")
        try:
            real = ia.knowledge_user_card_path(cid)
            if not real:
                raise HTTPException(status_code=404, detail="未找到该用户知识卡对应的文件，无法删除。")
            resp = ia.knowledge_delete_file(real)
        except ia.IvyeaAgentError as e:
            raise HTTPException(status_code=400, detail=f"从 IvyeaAgent 删除失败：{e}") from e
        if not resp.get("ok"):
            raise HTTPException(status_code=400, detail="删除失败。")
        return {"ok": True, "removed": [cid], "removed_card_ids": resp.get("removed_card_ids") or [cid], "source": "ivyea-agent"}
    return _handle(gb.delete_file, path)


@router.post("/import")
def import_brain() -> dict[str, Any]:
    return _handle(gb.import_brain)


@router.get("/git/status")
def git_status() -> dict[str, str]:
    return _handle(gb.git_status)


@router.post("/upload")
async def upload_knowledge(
    file: UploadFile = File(...),
    category: str = Form("inbox"),
    title: str | None = Form(None),
    import_after_save: bool = Form(True),
) -> dict[str, Any]:
    data = await file.read(bc.MAX_UPLOAD_BYTES + 1)
    if _ivyea_front_door():
        try:
            return _ia_upload_bytes(file.filename or "upload.txt", data, title, category)
        except Exception:  # noqa: BLE001 — degrade to legacy GBrain upload
            pass
    return _handle(bc.upload_knowledge, file.filename or "upload", data, category, title, import_after_save)


@router.get("/uploads")
def uploads(limit: int = Query(50, ge=1, le=100)) -> dict[str, Any]:
    return _handle(bc.list_uploads, limit)


@router.post("/ingest/text")
def ingest_text(body: IngestTextBody) -> dict[str, Any]:
    if _ivyea_front_door():
        try:
            return _ia_ingest_text(body.text)
        except Exception:  # noqa: BLE001 — degrade to legacy GBrain ingest
            pass
    return _handle(bc.ingest_pasted_text, body.text, body.import_after_save)


@router.post("/ingest/url")
async def ingest_url(body: IngestUrlBody) -> dict[str, Any]:
    """Fetch URL, extract content via AI into clean Markdown, then ingest."""
    import httpx
    import re

    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            resp = await client.get(body.url, headers={"User-Agent": "Mozilla/5.0 (compatible; IvyeaOps/1.0)"})
            resp.raise_for_status()
            html = resp.text
    except Exception as e:
        raise HTTPException(400, f"抓取失败: {e}")

    # Basic HTML to text extraction
    html = re.sub(r"<(script|style|noscript|header|footer|nav)[^>]*>.*?</\1>", "", html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "\n", html)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]+", " ", text).strip()

    if len(text) < 30:
        raise HTTPException(400, "页面内容为空或无法解析")

    # Truncate for AI processing
    raw_text = text[:12000]

    # Call AI to reformat into clean Markdown
    prompt = f"""你是一个内容整理专家。请将以下从网页抓取的原始文本整理成一篇干净、排版良好的 Markdown 文章。

要求：
1. 只保留文章正文内容，去除所有导航、广告、页脚、cookie提示等无关信息
2. 用合适的 Markdown 标题层级（#, ##, ###）组织内容结构
3. 保留关键信息，去除重复和冗余
4. 如有列表内容用 Markdown 列表格式
5. 直接输出 Markdown 内容，不要加任何解释或前言
6. 保持原文语言（中文内容用中文，英文内容用英文）

来源URL: {body.url}

原始文本：
{raw_text}"""

    # Route the AI cleaning step through the unified text fallback chain
    # (IvyeaAgent → global fallback model → DeepSeek …) instead of the old
    # hard-wired Codex CLI, which is fragile and failed with an opaque
    # "session_id: …" error whenever that one provider was unavailable.
    from app.services import ai_synthesis_service

    markdown = ""
    try:
        markdown = (await ai_synthesis_service.generate_text(prompt)).strip()
    except Exception:  # noqa: BLE001 — surface a friendly message below
        markdown = ""

    if not markdown:
        raise HTTPException(
            502,
            "AI 整理失败：本地未配置可用文本模型，请在系统配置 → 全局兜底大模型设置后重试。",
        )

    # Ingest through the IvyeaAgent front door (consistent with paste/file
    # upload); fall back to the legacy GBrain store only when it is down.
    if _ivyea_front_door():
        try:
            return _ia_ingest_text(markdown)
        except Exception:  # noqa: BLE001 — degrade to legacy GBrain ingest
            pass
    return _handle(bc.ingest_pasted_text, markdown, body.import_after_save)


@router.get("/chat/status")
def chat_status() -> dict[str, Any]:
    return _handle(bc.chat_model_status)


@router.get("/chat/sessions")
def chat_sessions(include_archived: bool = False) -> dict[str, Any]:
    return _handle(bc.list_sessions, include_archived)


@router.post("/chat/sessions")
def chat_session_create(body: ChatSessionCreateBody) -> dict[str, Any]:
    return _handle(bc.create_session, body.title, body.mode)


@router.get("/chat/sessions/{session_id}")
def chat_session_get(session_id: str) -> dict[str, Any]:
    return _handle(bc.get_session, session_id)


@router.patch("/chat/sessions/{session_id}")
def chat_session_update(session_id: str, body: ChatSessionUpdateBody) -> dict[str, Any]:
    return _handle(bc.update_session, session_id, body.title, body.archived)


@router.post("/chat/sessions/{session_id}/messages")
def chat_message_send(session_id: str, body: ChatMessageBody) -> dict[str, Any]:
    return _handle(bc.send_message, session_id, body.content)


def _sse(evt: dict[str, Any]) -> str:
    return f"data: {json.dumps(evt, ensure_ascii=False)}\n\n"


async def _bridge_ivyea_stream(question: str, session_id: str):
    """Drive IvyeaAgent /v1/chat/stream (blocking, stdlib urllib) from a worker
    thread and yield its (event, data) frames into the async SSE handler."""
    q: asyncio.Queue = asyncio.Queue()
    sentinel = object()
    loop = asyncio.get_running_loop()

    def _produce() -> None:
        try:
            payload = {
                "message": question,
                "session_id": session_id or "",
                "plan_mode": True,   # read-only knowledge turn, no side effects
                "persist": False,    # IvyeaOps owns session persistence
            }
            for event, data in ia.chat_stream_events(payload):
                loop.call_soon_threadsafe(q.put_nowait, (event, data))
        except Exception as exc:  # noqa: BLE001 — surface as an error frame
            loop.call_soon_threadsafe(q.put_nowait, ("error", {"detail": str(exc)}))
        finally:
            loop.call_soon_threadsafe(q.put_nowait, sentinel)

    task = loop.run_in_executor(None, _produce)
    try:
        while True:
            item = await q.get()
            if item is sentinel:
                break
            yield item
    finally:
        await task


_STREAM_DEADLINE_S = int(__import__("os").environ.get("BRAIN_CHAT_HERMES_TIMEOUT", "180"))


@router.post("/chat/sessions/{session_id}/messages/stream")
async def chat_message_stream(session_id: str, body: ChatStreamBody):
    """Stream a hermes answer token-by-token over SSE. Emits:
    start{user_message,citations} → token{text}* → done{assistant_message} | error{detail}."""

    async def gen():
        # Front door: route the knowledge chat through the governed IvyeaAgent
        # brain (its built-in Amazon knowledge base) when the local service is
        # up; skip the legacy GBrain citation retrieval in that case. Hermes /
        # the global text chain remain only as fallbacks when IvyeaAgent is down.
        use_ivyea = bc.ivyea_chat_available()
        try:
            turn = bc.begin_chat_turn(
                session_id, body.content, regenerate=body.regenerate,
                category=body.category, retrieve=not use_ivyea,
            )
        except (gb.GBrainError, bc.BrainChatError) as e:
            yield _sse({"type": "error", "detail": str(e)})
            return
        except Exception as e:  # noqa: BLE001
            yield _sse({"type": "error", "detail": f"准备对话失败：{e}"})
            return

        yield _sse({
            "type": "start",
            "user_message": turn["user_message"],
            "citations": turn["citations"],
            "regenerated": turn.get("regenerated", False),
        })

        parts: list[str] = []
        timed_out = False
        engine = ""  # which engine produced the answer: ivyea-agent | hermes | global

        # 1) IvyeaAgent brain (token-by-token over the local bridge).
        if use_ivyea:
            try:
                async for event, data in _bridge_ivyea_stream(turn.get("question") or body.content, session_id):
                    if event == "token":
                        text = str(data.get("text") or "")
                        if text:
                            parts.append(text)
                            yield _sse({"type": "token", "text": text})
                    elif event == "event":
                        # tool/thinking narration — keep the SSE connection warm
                        # during a long agent turn without polluting the answer.
                        yield ":hb\n\n"
                    elif event == "final":
                        full = str(data.get("text") or "")
                        if full and not "".join(parts).strip():
                            parts.append(full)
                            yield _sse({"type": "token", "text": full})
                    elif event == "error":
                        # degrade to the global chain below (do not surface yet)
                        break
                if "".join(parts).strip():
                    engine = "ivyea-agent"
            except Exception:  # noqa: BLE001 — degrade to fallbacks below
                pass

        # 2) Hermes (only when IvyeaAgent is unavailable), token-by-token.
        if not "".join(parts).strip() and not use_ivyea and bc.hermes_available():
            spec = bc.stream_spec(turn["prompt"])
            proc = None
            try:
                proc = await asyncio.create_subprocess_exec(
                    *spec["argv"],
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.DEVNULL,
                    cwd=spec["cwd"],
                    env=spec["env"],
                    **no_window_kwargs(),  # no black console flash on Windows
                )
            except Exception:  # noqa: BLE001 — degrade to the global chain below
                proc = None

            if proc is not None:
                try:
                    proc.stdin.write(spec["stdin"])
                    await proc.stdin.drain()
                    proc.stdin.close()
                except Exception:
                    pass

                decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
                deadline = time.monotonic() + _STREAM_DEADLINE_S
                try:
                    while True:
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            timed_out = True
                            break
                        try:
                            data = await asyncio.wait_for(proc.stdout.read(1024), timeout=min(remaining, 15))
                        except asyncio.TimeoutError:
                            yield ":hb\n\n"  # heartbeat keeps proxies from closing the stream
                            continue
                        if not data:
                            break
                        text = decoder.decode(data)
                        if text:
                            parts.append(text)
                            yield _sse({"type": "token", "text": text})
                finally:
                    if proc.returncode is None:
                        try:
                            proc.kill()
                        except Exception:
                            pass
                    try:
                        await proc.wait()
                    except Exception:
                        pass

        if not engine and "".join(parts).strip():
            engine = "hermes"

        # Fall back to the unified global text chain (DeepSeek → Apimart → 全局兜底
        # 大模型) when IvyeaAgent/Hermes are absent or produced nothing — so the
        # knowledge-base chat still answers without any local agent.
        if not "".join(parts).strip():
            fallback_prompt = turn.get("prompt") or (turn.get("question") or body.content)
            try:
                async for chunk in bc.stream_global_answer(fallback_prompt):
                    parts.append(chunk)
                    yield _sse({"type": "token", "text": chunk})
                timed_out = False
                if "".join(parts).strip():
                    engine = "global"
            except Exception as e:  # noqa: BLE001
                if not "".join(parts).strip():
                    yield _sse({"type": "error", "detail": f"对话失败（IvyeaAgent 与全局兜底均不可用）：{e}"})
                    return

        answer = "".join(parts)
        if not answer.strip():
            yield _sse({"type": "error", "detail": "未能生成回答：请确认 IvyeaAgent 服务在运行，或在「系统配置 → 全局兜底大模型」配置一个文本模型。"})
            return
        try:
            assistant = bc.commit_chat_answer(session_id, answer, turn["citations"])
        except (gb.GBrainError, bc.BrainChatError) as e:
            yield _sse({"type": "error", "detail": str(e)})
            return
        yield _sse({
            "type": "done",
            "assistant_message": assistant,
            "truncated": timed_out,
            "engine": engine,
            "citations_count": len(turn["citations"]),
        })

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )


@router.delete("/chat/messages/{message_id}")
def chat_message_delete(message_id: str) -> dict[str, Any]:
    return _handle(bc.delete_message, message_id)
