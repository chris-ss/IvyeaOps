"""生图执行层（后台 job 化）。

老架构：浏览器提交任务后自己每 5 秒轮询 8 分钟、批量生成是前端 for 循环 ——
刷新/断网/切页全部前功尽弃。新架构：提交 + 轮询 + 画布规范化 + 成图质检 +
按质检意见自动重画一次，全部在服务端 job 里跑完并逐张落库；前端只订阅进度。
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import mimetypes
import re
from pathlib import Path
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.core.security import require_user

from .common import (
    _apimart_base, _apimart_key, _fetch_image_bytes, project_row,
)
from .jobs import JobHandle, start_job
from .visuals import (
    ReviewRenderReq, _persist_shot_plan, review_render_core,
)

router = APIRouter()


class RenderImageReq(BaseModel):
    deliverable: str = "gallery"     # gallery | aplus
    index: int                       # 分镜序号（0 起）
    prompt_override: str = ""        # 编辑过的最终提示词（可选）


class RenderSetReq(BaseModel):
    deliverable: str = "gallery"
    only_missing: bool = False       # True = 只补没生成的


# ─── Apimart 提交与轮询 ───────────────────────────────────────────────────────

def _parse_image_task_payload(payload: dict) -> dict:
    """Convert Apimart's task payload into a stable client-facing state."""
    task_data = payload.get("data") if isinstance(payload, dict) else {}
    task_data = task_data if isinstance(task_data, dict) else {}
    status = str(task_data.get("status") or "processing").strip().lower()
    if status == "completed":
        result = task_data.get("result") if isinstance(task_data.get("result"), dict) else {}
        images = result.get("images") if isinstance(result.get("images"), list) else []
        url = images[0].get("url") if images and isinstance(images[0], dict) else ""
        if isinstance(url, list):
            url = url[0] if url else ""
        if url:
            return {"status": "completed", "provider_url": str(url)}
        return {"status": "failed", "error": "任务完成但未返回图片 URL"}
    if status == "failed":
        detail = task_data.get("error") or task_data.get("message") or task_data.get("result") or "上游生图任务失败"
        return {"status": "failed", "error": str(detail)[:500]}
    return {"status": status or "processing"}


async def _materialise_refs(ref_urls: list[str]) -> list[str]:
    """Browser-facing workspace URLs are not reachable by the external image
    provider. Materialise local references as data URIs while preserving list
    order (product truth first)."""
    materialised: list[str] = []
    async with httpx.AsyncClient(timeout=60) as ref_client:
        for url in ref_urls[:2]:
            value = str(url or "").strip()
            if value.startswith("/api/"):
                try:
                    raw_ref = await _fetch_image_bytes(ref_client, value)
                    mime = mimetypes.guess_type(value.split("?", 1)[0])[0] or "image/png"
                    materialised.append(f"data:{mime};base64,{base64.b64encode(raw_ref).decode()}")
                except Exception as exc:  # noqa: BLE001
                    raise HTTPException(502, f"本地参考图读取失败：{exc}") from exc
            elif value:
                materialised.append(value)
    return materialised


def _fidelity_preamble(prompt: str, ref_count: int, reference_mode: str) -> str:
    """Deterministic product-fidelity preamble: the per-slot prompt is LLM-written
    and may drift, so we always prepend a hard "reproduce the real product exactly"
    instruction whenever reference photos are attached. This is the main lever for
    keeping the generated product consistent with the user's real product."""
    if not ref_count:
        return prompt
    if reference_mode == "template" and ref_count >= 2:
        return (
            "CRITICAL REFERENCE ROLES — DO NOT MIX THEM. REFERENCE 1 is the ONLY PRODUCT TRUTH: reproduce its "
            "product identically, including shape, proportions, color, material, controls, ports and included parts. "
            "REFERENCE 2 is ONLY A VISUAL TEMPLATE: reuse its content hierarchy, shot category, camera/view type, "
            "subject scale, negative-space map and design density, but do not copy its product identity, brand, logo, "
            "written text, person identity or exact pixels. Replace the template's product with REFERENCE 1. "
            "Create one coherent commercial photograph with believable perspective, contact, shadow and lighting. "
            "Render no words, letters, numbers, badges, diagrams or watermarks; typography is added later.\n\n"
        ) + prompt
    return (
        "CRITICAL — IMMUTABLE PRODUCT TRUTH: REFERENCE IMAGE 1 shows the EXACT sellable product. "
        "Reproduce it identically: same silhouette, geometry, proportions, colors, color blocking, materials, "
        "surface finish, seams, openings, lenses, controls, ports, logos, labels, printed product markings, "
        "accessories and quantity. Change ONLY the environment, camera, composition, lighting, supporting graphic "
        "design and the exact artwork copy explicitly requested by the prompt. "
        "Do NOT redesign, recolor, relabel, simplify, crop away, add or remove any product part. "
        "When the prompt bans text, that means no ADDED marketing text; existing markings on the reference product "
        "must remain unchanged. If a requested composition conflicts with product fidelity, preserve the product.\n\n"
    ) + prompt


async def _submit_generation(prompt: str, size: str, ref_urls: list[str],
                             slot: str) -> str:
    """提交生图任务，返回 task_id。"""
    if not _apimart_key():
        raise HTTPException(
            400,
            "Apimart 密钥未配置 — 请在「系统配置 → AI 服务」填入有 gpt-image-2 权限的密钥。",
        )
    from app.services.listing_image_compositor import parse_size
    target_w, target_h = parse_size(size)
    if abs(target_w / target_h - 1) < .12:
        provider_size = "1024x1024"
    elif target_w > target_h:
        provider_size = "1536x1024"
    else:
        provider_size = "1024x1536"
    base_body = {"model": "gpt-image-2", "prompt": prompt, "n": 1, "size": provider_size}
    if ref_urls:
        base_body["image_urls"] = ref_urls[:2]

    # gpt-image's `input_fidelity:"high"` preserves details of the input image (the
    # real product). Apimart may or may not pass it through, so try high-fidelity
    # first and gracefully fall back to a plain request if it is rejected.
    attempts = [{**base_body, "input_fidelity": "high"}, base_body] if ref_urls else [base_body]

    async with httpx.AsyncClient(timeout=httpx.Timeout(45, connect=20)) as client:
        logging.info(f"[generate-image] slot={slot} ref_urls={len(ref_urls)} fidelity={'high' if ref_urls else 'n/a'}")
        resp = None
        for idx, attempt in enumerate(attempts):
            resp = await client.post(
                f"{_apimart_base()}/images/generations",
                headers={"Authorization": f"Bearer {_apimart_key()}", "Content-Type": "application/json"},
                json=attempt,
            )
            if resp.status_code == 200:
                break  # accepted (with or without high fidelity)
            logging.info(f"[generate-image] attempt {idx} -> HTTP {resp.status_code}: {resp.text[:160]}")
            # The plain retry exists only for providers that reject the optional
            # input_fidelity field. Retrying 5xx/rate-limit errors with the same
            # payload just doubles the request time.
            if not (idx == 0 and resp.status_code in {400, 422}):
                break
        if resp is None or resp.status_code != 200:
            raise HTTPException(502, f"图片生成提交失败: {resp.text[:300] if resp is not None else 'no response'}")
        submit_data = resp.json()
        task_id = submit_data.get("data", [{}])[0].get("task_id")
        if not task_id:
            raise HTTPException(502, f"未返回task_id: {resp.text[:300]}")
        return str(task_id)


async def _await_generation(project_id: str, task_id: str, size: str,
                            on_tick=None, deadline_seconds: int = 8 * 60) -> dict:
    """服务端轮询直到任务完成，画布规范化后保存到工作区，返回 {url, technical_qa}。"""
    if not re.fullmatch(r"[A-Za-z0-9_-]{6,160}", task_id):
        raise HTTPException(400, "无效的生图任务 ID")
    loop = asyncio.get_event_loop()
    deadline = loop.time() + deadline_seconds
    tick = 0
    async with httpx.AsyncClient(timeout=httpx.Timeout(45, connect=20)) as client:
        while loop.time() < deadline:
            await asyncio.sleep(5)
            tick += 1
            if on_tick:
                on_tick(tick)
            try:
                poll = await client.get(
                    f"{_apimart_base()}/tasks/{task_id}",
                    headers={"Authorization": f"Bearer {_apimart_key()}"},
                )
            except Exception:
                continue  # transient network failure — keep waiting, task is paid
            # Rate limits and transient provider failures are retryable.
            if poll.status_code == 429 or poll.status_code >= 500:
                continue
            if poll.status_code != 200:
                raise HTTPException(502, f"生图任务查询失败 HTTP {poll.status_code}: {poll.text[:240]}")
            state = _parse_image_task_payload(poll.json())
            if state["status"] == "failed":
                raise HTTPException(502, state.get("error") or "上游生图任务失败")
            if state["status"] != "completed":
                continue
            # Providers may return a different aspect ratio. Normalise locally.
            raw = await _fetch_image_bytes(client, state["provider_url"])
            from app.services.listing_image_compositor import normalise_canvas, technical_quality
            normalised = normalise_canvas(raw, size, mode="cover")
            from app.routers.image_translate import save_bytes_to_workspace
            item = save_bytes_to_workspace(normalised, source="listing", project_id=project_id)
            return {
                "url": item["url"],
                "provider_url": state["provider_url"],
                "technical_qa": technical_quality(normalised, size),
            }
    raise HTTPException(504, "生图任务等待超过 8 分钟，请稍后在历史里重试（任务未重复提交）")


async def generate_image_core(project_id: str, prompt: str, slot: str, size: str,
                              ref_urls: list[str], reference_mode: str = "product",
                              on_tick=None) -> dict:
    """一次完整生成：物化参考 → 保真前置 → 提交 → 轮询 → 规范化。"""
    refs = await _materialise_refs(ref_urls)
    if reference_mode != "template":
        # Direct studio generation has one immutable product truth. Multiple
        # angles/competitor images encourage the model to blend identities.
        refs = refs[:1]
    full_prompt = _fidelity_preamble(prompt, len(refs), reference_mode)
    task_id = await _submit_generation(full_prompt, size, refs, slot)
    return await _await_generation(project_id, task_id, size, on_tick=on_tick)


# ─── 单张分镜渲染（生成 + 质检 + 自动重画一次）────────────────────────────────

def _now_version(image: dict) -> Optional[dict]:
    if not image.get("final_url"):
        return None
    import datetime
    return {
        "url": image["final_url"],
        "base_url": image.get("base_url") or "",
        "render_qa": image.get("render_qa"),
        "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }


def _load_plan(project_id: str, deliverable: str) -> dict:
    row = project_row(project_id, "creative_sets")
    if not row:
        raise HTTPException(404, "project not found")
    try:
        sets = json.loads(row["creative_sets"] or "{}")
    except Exception:
        sets = {}
    plan = sets.get("aplus" if deliverable == "aplus" else "gallery")
    if not isinstance(plan, dict) or not plan.get("images"):
        raise HTTPException(400, "请先生成整套方案")
    return plan


async def _render_card(project_id: str, plan: dict, index: int, deliverable: str,
                       handle: Optional[JobHandle], *, prompt_override: str = "",
                       progress_base: float = 0.0, progress_span: float = 1.0) -> dict:
    """渲染一张分镜卡：生成 → 复核 → 需要时按质检意见自动重画一次 → 落库。
    返回更新后的 plan。"""
    images = plan.get("images") or []
    if index < 0 or index >= len(images):
        raise HTTPException(400, f"分镜序号越界：{index}")
    image = images[index]
    product_source = str(image.get("product_source_url") or plan.get("product_source_url") or "")
    if not product_source:
        raise HTTPException(400, f"「{image.get('role') or index + 1}」未找到产品真值素材，请先上传产品图或采集可用主图")
    size = str(image.get("size") or ("1464x600" if deliverable == "aplus" else "1600x1600"))
    render_prompt = prompt_override.strip() or str(image.get("render_prompt") or "")
    role = str(image.get("role") or f"第 {index + 1} 张")

    def report(message: str, fraction: float) -> None:
        if handle:
            handle.update(stage=f"card-{index}", message=message,
                          progress=progress_base + progress_span * fraction)

    async def review(final_url: str) -> dict:
        from app.services.listing_typography import public_proof
        return await review_render_core(project_id, ReviewRenderReq(
            url=final_url,
            size=size,
            slot=str(image.get("slot") or ""),
            role=role,
            shot_type=str(image.get("shot_type") or ""),
            layout_blueprint=str(image.get("layout_blueprint") or ""),
            eyebrow=str(image.get("eyebrow") or ""),
            headline=str(image.get("headline") or ""),
            callout=str(image.get("callout") or ""),
            supporting_text=str(image.get("supporting_text") or ""),
            proof=public_proof(str(image.get("proof") or "")) or "",
            source_url=product_source,
            show_product=image.get("show_product") is not False,
            product_fidelity_anchors=(plan.get("product_profile") or {}).get("fidelity_anchors") or [],
        ))

    report(f"{role}：生成中…", 0.05)
    generated = await generate_image_core(
        project_id, render_prompt, str(image.get("slot") or f"slot{index}"), size,
        [product_source], "product",
        on_tick=lambda t: report(f"{role}：生成中（约 {t * 5} 秒）…", min(0.05 + t * 0.02, 0.5)),
    )
    base_url = generated["url"]
    final_url = base_url
    report(f"{role}：成图质检中…", 0.6)
    render_qa = await review(final_url)

    generated_history: list[dict] = []
    auto_retry_count = 0
    retry_guidance = [g for g in (render_qa.get("retry_guidance") or []) if g][:6]
    if not render_qa.get("ready") and retry_guidance:
        auto_retry_count = 1
        report(f"{role}：按质检意见自动重画一次…", 0.65)
        retry_prompt = (
            f"{render_prompt}\n\nMANDATORY QA REVISION — this is the single repair attempt. "
            "Keep the original buyer question and art direction, but correct every issue below. "
            "Reference image 1 remains the only immutable product truth. "
            "Do not solve a fidelity issue by hiding, cropping away, redesigning or replacing the product.\n- "
            + "\n- ".join(retry_guidance)
        )
        try:
            retried = await generate_image_core(
                project_id, retry_prompt, f"{image.get('slot')}_qa_retry", size,
                [product_source], "product",
                on_tick=lambda t: report(f"{role}：重画中（约 {t * 5} 秒）…", min(0.65 + t * 0.015, 0.9)),
            )
            report(f"{role}：重画质检中…", 0.92)
            retry_qa = await review(retried["url"])
            use_retry = retry_qa.get("ready") or float(retry_qa.get("score") or 0) >= float(render_qa.get("score") or 0)
            import datetime
            stamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
            if use_retry:
                generated_history.append({"url": final_url, "base_url": base_url,
                                          "render_qa": render_qa, "created_at": stamp})
                base_url = retried["url"]
                final_url = retried["url"]
                render_qa = retry_qa
            else:
                generated_history.append({"url": retried["url"], "base_url": retried["url"],
                                          "render_qa": retry_qa, "created_at": stamp})
        except HTTPException:
            pass  # 重画失败不吞掉首图 —— 保留第一次结果与其质检结论

    old_version = _now_version(image)
    versions = [
        *(image.get("versions") or []),
        *([old_version] if old_version else []),
        *generated_history,
    ][-8:]
    # 并行 job 防覆盖：落库前重读最新 plan，只合并本卡的结果。
    try:
        latest = _load_plan(project_id, deliverable)
        if len(latest.get("images") or []) == len(images):
            plan = latest
            images = plan["images"]
            image = images[index]
    except HTTPException:
        pass
    images[index] = {
        **image,
        "asset_mode": "generate",
        "show_product": True,
        "requires_source": False,
        "source_url": "",
        "product_source_url": product_source,
        "template_url": "",
        "layout_blueprint": "",
        "base_url": base_url,
        "final_url": final_url,
        "render_qa": render_qa,
        "auto_retry_count": auto_retry_count,
        "last_retry_guidance": retry_guidance,
        "versions": versions,
        "human_reviewed": False,
    }
    plan["images"] = images
    plan["set_qa"] = None
    # Image generation is slow and paid. Persist after each completed card so a
    # later-card failure or restart never loses the work already paid for.
    _persist_shot_plan(project_id, plan, deliverable)
    report(f"{role}：完成", 1.0)
    return plan


async def run_render_image(project_id: str, body: RenderImageReq,
                           handle: Optional[JobHandle] = None) -> dict:
    deliverable = "aplus" if body.deliverable == "aplus" else "gallery"
    plan = _load_plan(project_id, deliverable)
    plan = await _render_card(project_id, plan, body.index, deliverable, handle,
                              prompt_override=body.prompt_override)
    image = plan["images"][body.index]
    return {"plan": plan, "deliverable": deliverable, "index": body.index,
            "ready": bool((image.get("render_qa") or {}).get("ready"))}


async def run_render_set(project_id: str, body: RenderSetReq,
                         handle: Optional[JobHandle] = None) -> dict:
    """整套顺序生成（服务端编排），逐张落库、失败继续，最后自动整套复核。"""
    from .visuals import run_review_image_set
    deliverable = "aplus" if body.deliverable == "aplus" else "gallery"
    plan = _load_plan(project_id, deliverable)
    images = plan.get("images") or []
    targets = [i for i, item in enumerate(images)
               if not (body.only_missing and item.get("final_url"))]
    total = len(targets)
    if handle:
        handle.update(total=total, done_count=0)
    succeeded = 0
    failures: list[str] = []
    for order, index in enumerate(targets):
        try:
            plan = await _render_card(
                project_id, plan, index, deliverable, handle,
                progress_base=order / max(1, total) * 0.9,
                progress_span=0.9 / max(1, total),
            )
            succeeded += 1
        except HTTPException as exc:
            failures.append(f"第 {index + 1} 张：{exc.detail}")
        except Exception as exc:  # noqa: BLE001
            failures.append(f"第 {index + 1} 张：{exc}")
        if handle:
            handle.update(done_count=order + 1)

    set_qa = None
    if images and all(item.get("final_url") and (item.get("render_qa") or {}).get("ready")
                      for item in plan.get("images") or []):
        if handle:
            handle.update(stage="set-review", message="整套一致性复核中…", progress=0.92)
        try:
            outcome = await run_review_image_set(project_id, deliverable)
            plan = outcome["plan"]
            set_qa = outcome["set_qa"]
        except Exception as exc:  # noqa: BLE001
            failures.append(f"整套复核失败：{exc}")
    return {
        "plan": plan, "deliverable": deliverable,
        "succeeded": succeeded, "total": total,
        "failures": failures, "set_qa": set_qa,
    }


@router.post("/projects/{project_id}/render-image")
async def render_image_endpoint(project_id: str, body: RenderImageReq,
                                _user: str = Depends(require_user)):
    """单张分镜后台渲染 job。singleton=False：不同分镜可以并行各自的 job。"""
    if not project_row(project_id, "id"):
        raise HTTPException(404)
    return start_job(
        "render_image", project_id, body.model_dump(),
        lambda handle: run_render_image(project_id, body, handle),
        singleton=False,
    )


@router.post("/projects/{project_id}/render-set")
async def render_set_endpoint(project_id: str, body: RenderSetReq,
                              _user: str = Depends(require_user)):
    if not project_row(project_id, "id"):
        raise HTTPException(404)
    return start_job(
        "render_set", project_id, body.model_dump(),
        lambda handle: run_render_set(project_id, body, handle),
    )
