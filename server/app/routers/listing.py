"""Listing Generator — proxy to imgflow backend + AI copywriting + skill-enhanced analysis."""
from __future__ import annotations

import asyncio
import io
import json
import os
import re
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.core.config import settings
from app.core.security import require_user
from app.services.runners import _build_runner_cmd, _find_bin, build_child_env
from app.services.skill_repo import get_skill

router = APIRouter()

DB_PATH = settings.data_dir / "listing.sqlite3"
IMAGES_DIR = settings.data_dir / "listing_images"
IMAGES_DIR.mkdir(parents=True, exist_ok=True)

def _imgflow_base() -> str:
    from app.core import hub_settings
    url = hub_settings.get("imgflow_url") or "http://127.0.0.1:3001"
    return str(url).rstrip("/") + "/api"


def _apimart_key() -> str:
    """Return configured Apimart key, empty when unset. Image-generation
    callers should surface a clear 'not configured' error rather than
    falling back to a hardcoded shared key (those got banned upstream)."""
    from app.core import hub_settings
    val = hub_settings.get("apimart_key")
    return str(val) if val else ""


def _apimart_base() -> str:
    from app.core import hub_settings
    val = hub_settings.get("apimart_base")
    return str(val) if val else "https://api.apimart.ai/v1"


# ─── SQLite ───────────────────────────────────────────────────────────────────

def _db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("""CREATE TABLE IF NOT EXISTS listing_projects (
        id TEXT PRIMARY KEY,
        asin TEXT NOT NULL,
        marketplace TEXT DEFAULT 'US',
        imgflow_project_id TEXT,
        status TEXT DEFAULT 'created',
        title TEXT,
        bullets TEXT,
        search_terms TEXT,
        aplus_copy TEXT,
        scrape_data TEXT,
        analysis_data TEXT,
        image_slots TEXT,
        created_at REAL,
        updated_at REAL
    )""")
    conn.commit()
    return conn

_db().close()

# Migration: add columns if missing
for _col in ["image_slots TEXT", "templates TEXT"]:
    try:
        conn = _db()
        conn.execute(f"ALTER TABLE listing_projects ADD COLUMN {_col}")
        conn.commit()
        conn.close()
    except Exception:
        pass


# ─── Models ───────────────────────────────────────────────────────────────────

class CreateProjectReq(BaseModel):
    asin: str
    marketplace: str = "US"
    supplier_url: Optional[str] = None

class GenerateCopyReq(BaseModel):
    type: str
    context: Optional[str] = None

class ProductInfoReq(BaseModel):
    product_name: Optional[str] = None
    description: Optional[str] = None
    selling_points: Optional[str] = None
    target_audience: Optional[str] = None

class ImageGenReq(BaseModel):
    prompt: str
    slot: str
    size: str = "1024x1024"
    reference_urls: list[str] = []


# ─── Project CRUD ─────────────────────────────────────────────────────────────

@router.get("/projects")
def list_projects(_user: str = Depends(require_user)):
    conn = _db()
    rows = conn.execute(
        "SELECT id, asin, marketplace, status, title, created_at, updated_at "
        "FROM listing_projects ORDER BY updated_at DESC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@router.post("/projects")
async def create_project(body: CreateProjectReq, _user: str = Depends(require_user)):
    pid = str(uuid.uuid4())[:8]
    now = time.time()
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(f"{_imgflow_base()}/projects", json={
            "asin": body.asin, "marketplace": body.marketplace,
            "supplierUrl": body.supplier_url or "",
        })
        if resp.status_code not in (200, 201):
            raise HTTPException(502, f"imgflow create failed: {resp.text}")
        imgflow_data = resp.json()
        imgflow_id = imgflow_data.get("id") or imgflow_data.get("project", {}).get("id")
    conn = _db()
    conn.execute(
        "INSERT INTO listing_projects (id,asin,marketplace,imgflow_project_id,status,created_at,updated_at) VALUES (?,?,?,?,'created',?,?)",
        (pid, body.asin, body.marketplace, str(imgflow_id), now, now)
    )
    conn.commit()
    conn.close()
    return {"id": pid, "imgflow_id": imgflow_id, "asin": body.asin}


@router.get("/projects/{project_id}")
def get_project(project_id: str, _user: str = Depends(require_user)):
    conn = _db()
    row = conn.execute("SELECT * FROM listing_projects WHERE id = ?", (project_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "project not found")
    return dict(row)


@router.delete("/projects/{project_id}")
def delete_project(project_id: str, _user: str = Depends(require_user)):
    conn = _db()
    conn.execute("DELETE FROM listing_projects WHERE id = ?", (project_id,))
    conn.commit()
    conn.close()
    return {"ok": True}


# ─── Scrape (enhanced: saves reference images) ───────────────────────────────

@router.post("/projects/{project_id}/scrape")
async def scrape(project_id: str, _user: str = Depends(require_user)):
    conn = _db()
    row = conn.execute("SELECT imgflow_project_id FROM listing_projects WHERE id = ?", (project_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404)
    imgflow_id = row["imgflow_project_id"]

    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(f"{_imgflow_base()}/scrape/{imgflow_id}")
        if resp.status_code != 200:
            raise HTTPException(502, f"scrape failed: {resp.text}")
        data = resp.json()

    # Extract image URLs as reference images
    image_urls = data.get("imageUrls") or data.get("images") or []
    if image_urls:
        data["reference_images"] = image_urls

    conn = _db()
    conn.execute(
        "UPDATE listing_projects SET scrape_data = ?, status = 'scraped', updated_at = ? WHERE id = ?",
        (json.dumps(data, ensure_ascii=False), time.time(), project_id)
    )
    conn.commit()
    conn.close()
    return data


# ─── Product Info (manual) ────────────────────────────────────────────────────

@router.post("/projects/{project_id}/product-info")
def save_product_info(project_id: str, body: ProductInfoReq, _user: str = Depends(require_user)):
    conn = _db()
    row = conn.execute("SELECT scrape_data FROM listing_projects WHERE id = ?", (project_id,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404)
    existing = json.loads(row["scrape_data"]) if row["scrape_data"] else {}
    existing["manual"] = {
        "product_name": body.product_name or "",
        "description": body.description or "",
        "selling_points": body.selling_points or "",
        "target_audience": body.target_audience or "",
    }
    conn.execute(
        "UPDATE listing_projects SET scrape_data = ?, updated_at = ? WHERE id = ?",
        (json.dumps(existing, ensure_ascii=False), time.time(), project_id)
    )
    conn.commit()
    conn.close()
    return {"ok": True}


# ─── Image Slots Persistence ──────────────────────────────────────────────────

@router.post("/projects/{project_id}/image-slots")
def save_image_slots(project_id: str, body: dict, _user: str = Depends(require_user)):
    """Save image slot data (prompts, urls, sizes) for cross-device sync."""
    conn = _db()
    row = conn.execute("SELECT id FROM listing_projects WHERE id = ?", (project_id,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404)
    conn.execute(
        "UPDATE listing_projects SET image_slots = ?, updated_at = ? WHERE id = ?",
        (json.dumps(body, ensure_ascii=False), time.time(), project_id)
    )
    conn.commit()
    conn.close()
    return {"ok": True}


# ─── Image Upload & Reference ─────────────────────────────────────────────────

@router.post("/projects/{project_id}/upload-image")
async def upload_product_image(project_id: str, file: UploadFile = File(...), _user: str = Depends(require_user)):
    """Upload a product reference image."""
    conn = _db()
    row = conn.execute("SELECT id FROM listing_projects WHERE id = ?", (project_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404)

    proj_dir = IMAGES_DIR / project_id
    proj_dir.mkdir(parents=True, exist_ok=True)
    ext = Path(file.filename or "img.jpg").suffix or ".jpg"
    fname = f"{int(time.time())}_{uuid.uuid4().hex[:6]}{ext}"
    dest = proj_dir / fname
    content = await file.read()
    dest.write_bytes(content)

    # Add to scrape_data.uploaded_images
    conn = _db()
    row = conn.execute("SELECT scrape_data FROM listing_projects WHERE id = ?", (project_id,)).fetchone()
    existing = json.loads(row["scrape_data"]) if row and row["scrape_data"] else {}
    uploaded = existing.get("uploaded_images", [])
    uploaded.append(str(dest))
    existing["uploaded_images"] = uploaded
    conn.execute(
        "UPDATE listing_projects SET scrape_data = ?, updated_at = ? WHERE id = ?",
        (json.dumps(existing, ensure_ascii=False), time.time(), project_id)
    )
    conn.commit()
    conn.close()
    return {"path": str(dest), "filename": fname}


@router.get("/projects/{project_id}/reference-images")
def get_reference_images(project_id: str, _user: str = Depends(require_user)):
    """Get all reference images (scraped URLs + uploaded files)."""
    conn = _db()
    row = conn.execute("SELECT scrape_data FROM listing_projects WHERE id = ?", (project_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404)
    data = json.loads(row["scrape_data"]) if row["scrape_data"] else {}
    return {
        "scraped": data.get("reference_images", []),
        "uploaded": data.get("uploaded_images", []),
    }


# ─── AI Provider Fallback Chain ───────────────────────────────────────────────

_ANSI_RE = re.compile(r"\x1B\[[0-?]*[ -/]*[@-~]")


def _strip_agent_output(runner: str, output: str) -> str:
    """Normalize CLI output from Hermes/Codex into the assistant answer."""
    text = _ANSI_RE.sub("", output or "").strip()
    if not text:
        return ""

    # Codex exec often prints session/reasoning metadata before the final answer.
    if runner == "codex":
        match = re.search(r"\ncodex(?:[^\n]*)?\n(?P<answer>.+?)(?:\ntokens used\n|\Z)", text, re.S)
        if match:
            return match.group("answer").strip()
        lines = [
            line for line in text.splitlines()
            if not line.startswith("OpenAI Codex")
            and not line.startswith("workdir:")
            and not line.startswith("model:")
            and not line.startswith("approval:")
            and not line.startswith("sandbox:")
            and not line.startswith("reasoning")
            and not line.startswith("session")
            and line.strip() != "codex"
        ]
        text = "\n".join(lines).strip()

    if runner == "hermes":
        lines = [line for line in text.splitlines() if not line.strip().startswith("session_id:")]
        text = "\n".join(lines).strip()

    return text


def _agent_error_from_output(output: str) -> Optional[str]:
    text = _ANSI_RE.sub("", output or "").strip()
    low = text.lower()
    if not text:
        return None
    if "http 429" in low or "usage limit" in low or "the usage limit has been reached" in low:
        return "额度限制/429：Hermes 或 Codex 当前不可用"
    if "api call failed" in low:
        return text[-500:]
    if "failed to initialize" in low or "read-only file system" in low:
        return text[-500:]
    if any(line.strip().lower().startswith("error:") for line in text.splitlines()):
        return text[-500:]
    return None


async def _call_agent_runner(runner: str, prompt: str, timeout: int) -> str:
    binary = _find_bin(runner)
    if not binary:
        raise RuntimeError(f"{runner} CLI 不可用")

    argv = _build_runner_cmd(runner, binary, prompt)
    env = build_child_env(binary)
    env.setdefault("TERM", "dumb")
    env.setdefault("FORCE_COLOR", "0")
    env.setdefault("NO_COLOR", "1")
    env.setdefault("HERMES_ACCEPT_HOOKS", "1")

    proc = await asyncio.create_subprocess_exec(
        *argv,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        cwd=os.environ.get("OPSHUB_LISTING_AI_CWD", "/root"),
        env=env,
    )
    try:
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError as e:
        proc.kill()
        await proc.communicate()
        raise RuntimeError(f"{runner} CLI 超时") from e

    raw = stdout.decode("utf-8", errors="replace")
    output_error = _agent_error_from_output(raw)
    if output_error:
        raise RuntimeError(f"{runner} CLI 返回错误: {output_error}")
    if proc.returncode != 0:
        raise RuntimeError(f"{runner} CLI 退出码 {proc.returncode}: {raw[-1200:].strip()}")

    content = _strip_agent_output(runner, raw)
    if not content:
        raise RuntimeError(f"{runner} CLI 返回空内容")
    return content


async def _call_ai(prompt: str, max_tokens: int = 2000, web_search: bool = True) -> str:
    """Call the currently available local agent CLIs: Hermes → Codex."""
    timeout = int(os.environ.get("OPSHUB_LISTING_AI_TIMEOUT", "180"))
    runner_order = [x.strip().lower() for x in os.environ.get("OPSHUB_LISTING_AI_RUNNERS", "hermes,codex").split(",") if x.strip()]
    runner_order = [x for x in runner_order if x in ("hermes", "codex")]
    if not runner_order:
        runner_order = ["hermes", "codex"]

    task_prompt = (
        "你正在作为 Listing 生成板块的纯文本生成引擎。"
        "禁止执行命令、禁止读写文件、禁止修改系统、禁止调用工具；只根据提示词内容返回最终文本。\n\n"
        + prompt
    )
    if not web_search:
        task_prompt = "不要联网搜索，不要调用工具，只基于下面提供的信息回答。\n\n" + task_prompt
    task_prompt = (
        f"{task_prompt}\n\n"
        "输出要求：直接输出最终内容，不要解释调用过程，不要添加 Markdown 代码块。"
    )

    errors = []
    for runner in runner_order:
        try:
            return await _call_agent_runner(runner, task_prompt, timeout)
        except Exception as e:
            errors.append(f"{runner}: {e}")

    raise HTTPException(502, f"Hermes/Codex 均不可用: {'; '.join(errors)}")


async def _review_single_prompt(
    initial_prompt: str,
    slot_label: str,
    slot_size: str,
    color_scheme: str = "",
) -> str:
    """Self-check and optimize one generated image prompt — cosmetic fixes only, no invented content."""
    color_rule = (
        f"\n- MUST keep the color scheme '{color_scheme}' if already present; do not remove it."
        if color_scheme else ""
    )
    review_prompt = f"""You are a prompt EDITOR. Your ONLY job is cosmetic syntax improvements — you must NOT invent or change any facts.

SLOT: {slot_label}  |  CANVAS: {slot_size or "not specified"}

━━━ ABSOLUTE PROHIBITIONS (violation = output the draft unchanged) ━━━
• DO NOT add, change, or remove any reference image URL ("Reference: https://..." lines must appear verbatim)
• DO NOT modify the product's physical description — keep every color, material, shape, size, and feature exactly as written
• DO NOT invent any spec, feature, or scene detail that is not already present in the draft
• DO NOT change what the image is supposed to show or its scene/setting{color_rule}

━━━ ALLOWED FIXES (cosmetic only) ━━━
1. LIGHTING: Replace vague phrases ("good lighting", "bright light") with a concrete rig description ONLY if you can infer it from the existing scene context — e.g., white-background studio → "3-point studio lighting, 45° softbox key, fill reflector"
2. CANVAS: If "{slot_size}" is not already mentioned in the draft, append a sentence like "Compose for {slot_size} canvas." at the end
3. FILLER REMOVAL: Remove hollow adjectives ("beautiful", "stunning", "perfect", "amazing") — do NOT replace them with invented specifics, just remove them
4. COMPOSITION: If no camera angle is specified, add one neutral descriptor (e.g., "eye-level hero angle") that fits the existing scene

DRAFT PROMPT:
{initial_prompt}

OUTPUT: Edited prompt text only. If no valid fix is needed, return the draft unchanged. No prefix, no explanation."""

    try:
        reviewed = await _call_ai(review_prompt, max_tokens=1000, web_search=False)
        return reviewed.strip() if reviewed.strip() else initial_prompt
    except Exception:
        return initial_prompt


async def _review_batch_prompts(
    prompts: dict,
    slot_details: list,
    color_scheme: str = "",
) -> dict:
    """Batch self-check and optimize all generated prompts in a single AI call."""
    if not prompts:
        return prompts

    slot_map = {s["id"]: s for s in slot_details}
    color_rule = (
        f"\n- MANDATORY: Maintain the '{color_scheme}' color scheme throughout all prompts."
        if color_scheme else ""
    )

    prompts_block = "\n\n".join(
        f'SLOT: {sid}\nLABEL: {slot_map.get(sid, {}).get("label", sid)}\n'
        f'CANVAS: {slot_map.get(sid, {}).get("size", "")}\nDRAFT:\n{txt}'
        for sid, txt in prompts.items()
    )
    slot_ids_json = ", ".join(f'"{s}":"improved_prompt_here"' for s in prompts)

    review_prompt = f"""You are a prompt EDITOR reviewing {len(prompts)} image prompts. Your ONLY job is cosmetic syntax fixes — you must NOT invent or change any facts.

━━━ ABSOLUTE PROHIBITIONS (violation = output that prompt unchanged) ━━━
• DO NOT add, change, or remove any reference image URL ("Reference: https://..." lines must appear verbatim in every prompt that already has them)
• DO NOT modify the product's physical description — keep every color, material, shape, size, and feature exactly as written
• DO NOT invent any spec, feature, or scene detail that is not already present in the draft
• DO NOT change what any image is supposed to show or its scene/setting{color_rule}

━━━ ALLOWED FIXES (cosmetic only, apply to every prompt) ━━━
1. LIGHTING: Replace vague phrases ("good lighting", "bright light") with a concrete rig description ONLY if inferable from the existing scene context
2. CANVAS: If the slot's canvas size is not already mentioned, append a sentence like "Compose for <size> canvas." at the end
3. FILLER REMOVAL: Remove hollow adjectives ("beautiful", "stunning", "perfect", "amazing") — do NOT replace with invented specifics, just remove them
4. COMPOSITION: If no camera angle is specified, add one neutral descriptor that fits the existing scene

DRAFT PROMPTS:
{prompts_block}

OUTPUT FORMAT (valid JSON, no other text):
{{"prompts":{{{slot_ids_json}}}}}"""

    try:
        content = await _call_ai(review_prompt, max_tokens=8000, web_search=False)
        result = _parse_json_response(content)
        if result and isinstance(result.get("prompts"), dict):
            reviewed = result["prompts"]
            return {
                sid: str(reviewed[sid]).strip()
                if reviewed.get(sid) and str(reviewed[sid]).strip()
                else orig
                for sid, orig in prompts.items()
            }
    except Exception:
        pass

    return prompts


def _reference_images(scrape_data: dict) -> list[str]:
    refs = scrape_data.get("reference_images") or scrape_data.get("imageUrls") or []
    if isinstance(refs, str):
        return [refs]
    return [str(x) for x in refs if str(x).strip()] if isinstance(refs, list) else []


def _slot_purpose(slot_id: str, label: str) -> str:
    key = slot_id.lower()
    if key == "main":
        return "pure white Amazon main image, product centered, no text, shopper can inspect the full product"
    if key.startswith("sub1"):
        return "lifestyle scene showing the primary use case and buyer outcome"
    if key.startswith("sub2"):
        return "feature detail image with concise benefit callouts"
    if key.startswith("sub3"):
        return "size, scale, specification, or usage clarity image"
    if key.startswith("sub4"):
        return "multi-angle, structure, technology, or material detail image"
    if key.startswith("sub5"):
        return "package, accessories, kit contents, or value summary image"
    if key.startswith("sub6"):
        return "multi-scenario benefit summary image"
    if "banner" in key:
        return "Premium A+ hero banner with brand-level composition"
    if "compare" in key or key.endswith("_4"):
        return "A+ comparison, trust, specification, or advantage module"
    if "brand" in key:
        return "brand story and trust-building A+ module"
    return f"{label or slot_id} product image module"


def _fallback_image_prompt(
    slot_id: str,
    label: str,
    size: str,
    row,
    scrape_data: dict,
    analysis_data: dict,
    color_scheme: str = "",
    template_hint: str = "",
) -> str:
    src = _copy_source(row, scrape_data, analysis_data)
    refs = _reference_images(scrape_data)
    ref = refs[0] if refs else "no reference image available"
    product_lock = _clean_text(
        analysis_data.get("product_lock")
        or f"{src['title']} exactly as shown in the reference image; keep the real shape, color, materials, proportions, logo placement, and included accessories unchanged."
    )
    features = src["usp"] + src["bullets"]
    feature = _clean_text(features[0]) if features else _clean_text(src["description"] or src["title"])
    canvas = size or ("1400x1400 or larger square" if slot_id == "main" else "configured slot size")
    purpose = _slot_purpose(slot_id, label)
    color_line = f" Use a {color_scheme} palette for backgrounds, props, lighting, and typography." if color_scheme else ""
    template_line = f" Adapt this template direction without copying unsupported claims: {template_hint[:420]}." if template_hint else ""
    text_rule = "no text, no badges, no icons" if slot_id == "main" else "short English text callouts that communicate the benefit"
    return (
        f"{product_lock} Reference: {ref}. Create a {purpose} for slot \"{label or slot_id}\". "
        f"Target canvas: {canvas}; compose specifically for this size and orientation. "
        f"Image goal: communicate {feature[:220]}. "
        f"Use commercial Amazon product photography with accurate product rendering, controlled studio lighting, natural shadows, sharp focus, realistic materials, and clean premium composition.{color_line} "
        f"Composition: product remains visually dominant, with enough negative space for {text_rule}. "
        f"For A+ desktop modules use a wide 1464x600 layout when requested; for mobile modules use a compact 600x450 layout when requested. "
        f"Do not invent specs, certifications, accessories, colors, or features not present in the product data. {template_line}".strip()
    )


def _fallback_prompts_for_slots(row, scrape_data: dict, analysis_data: dict, slot_details: list[dict], color_scheme: str = "", template_hint: str = "") -> dict:
    prompts = {}
    for s in slot_details:
        prompts[s["id"]] = _fallback_image_prompt(
            s["id"],
            s.get("label") or s["id"],
            s.get("size") or "",
            row,
            scrape_data,
            analysis_data,
            color_scheme,
            template_hint,
        )
    return {
        "product_lock": analysis_data.get("product_lock") or _copy_source(row, scrape_data, analysis_data)["title"],
        "visual_style": analysis_data.get("visual_style") or "Premium Amazon commercial photography with consistent product appearance.",
        "prompts": prompts,
        "fallback": True,
        "warning": "Hermes/Codex 当前不可用，已用本地规则生成可编辑图片提示词；恢复额度后可重新智能生成。",
    }


def _fallback_template_content(content: str) -> str:
    text = content.strip()
    text = re.sub(r"https?://\S+", "{reference_url}", text)
    text = re.sub(r"\b(#[0-9a-fA-F]{3,8})\b", "{color_scheme}", text)
    if "{product_lock}" not in text:
        text = "{product_lock}\nReference: {reference_url}\n" + text
    if "{visual_style}" not in text:
        text += "\nVisual style: {visual_style}. Color direction: {color_scheme}."
    return text


def _fallback_analysis(row, scrape_data: dict, analysis_data: dict) -> dict:
    src = _copy_source(row, scrape_data, analysis_data)
    features = src["usp"] + src["bullets"] or [src["description"] or src["title"]]
    return {
        "usp": [f[:120] for f in features[:3]],
        "target_audience": src["audience"],
        "scenarios": ["Primary product use case", "Everyday comparison shopping", "Gift, home, work, travel, or category-relevant use"],
        "keywords": (src["keywords"] + _keywords_from_text(" ".join([src["title"], src["description"], " ".join(src["bullets"])])))[:15],
        "image_strategy": {
            "main": "Show the exact product clearly on a pure white Amazon-ready background.",
            "sub1": "Show the primary buyer outcome in context.",
            "sub2": "Highlight the strongest feature with concise callouts.",
            "sub3": "Clarify size, use, or compatibility from available data.",
            "sub4": "Show details, structure, or material quality.",
            "sub5": "Show included items or value summary.",
            "sub6": "Close with scenarios, trust, or benefit summary.",
        },
        "cosmo_score": "local-fallback",
        "optimization_suggestions": ["补充真实规格和卖点", "上传清晰参考图", "恢复 Hermes/Codex 后重新运行智能分析"],
    }


# ─── Skill-Enhanced AI Analysis ───────────────────────────────────────────────

def _load_skill_knowledge() -> str:
    """Load relevant skill knowledge for analysis prompts."""
    parts = []
    try:
        creative = get_skill("amazon/amazon-listing-creative")
        parts.append(f"[LISTING CREATIVE STRATEGY]\n{creative.content_body[:3000]}")
    except Exception:
        pass
    try:
        audit = get_skill("amazon/amazon-asin-cosmo-rufus-audit")
        parts.append(f"[ASIN AUDIT METHODOLOGY]\n{audit.content_body[:2000]}")
    except Exception:
        pass
    return "\n\n".join(parts)


@router.post("/projects/{project_id}/ai-analyze")
async def ai_analyze(project_id: str, _user: str = Depends(require_user)):
    """Run skill-enhanced AI analysis + imgflow deep analysis (COSMO/Rufus/SIF)."""
    conn = _db()
    row = conn.execute("SELECT * FROM listing_projects WHERE id = ?", (project_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404)

    scrape_data = json.loads(row["scrape_data"]) if row["scrape_data"] else {}
    product_context = _build_product_context(row, scrape_data, {})
    skill_knowledge = _load_skill_knowledge()

    # 1. Call imgflow deep analysis (COSMO/Rufus/SIF/Sorftime)
    imgflow_analysis = {}
    imgflow_id = row["imgflow_project_id"]
    if imgflow_id:
        try:
            async with httpx.AsyncClient(timeout=180) as client:
                resp = await client.post(f"{_imgflow_base()}/analysis/{imgflow_id}")
                if resp.status_code == 200:
                    imgflow_analysis = resp.json()
        except Exception:
            pass

    # 2. Skill-enhanced AI analysis
    prompt = f"""你是Amazon产品分析专家。基于以下专业知识和产品信息，进行深度分析。

## 专业知识参考
{skill_knowledge[:4000]}

## 产品信息
{product_context}

## imgflow深度分析数据
{json.dumps(imgflow_analysis, ensure_ascii=False)[:2000] if imgflow_analysis else "未获取到"}

请输出结构化分析（JSON格式）：
{{
  "usp": ["核心卖点1", "核心卖点2", "核心卖点3"],
  "target_audience": "目标受众描述",
  "scenarios": ["使用场景1", "使用场景2", "使用场景3"],
  "keywords": ["关键词1", "关键词2", ...最多15个],
  "image_strategy": {{
    "main": "主图策略建议",
    "sub1": "副图1策略(USP概览)",
    "sub2": "副图2策略(对比图)",
    "sub3": "副图3策略(场景图)",
    "sub4": "副图4策略(技术/细节)",
    "sub5": "副图5策略(效果展示)",
    "sub6": "副图6策略(包装/配件)"
  }},
  "cosmo_score": "基于分析的COSMO评分估计(0-100)",
  "optimization_suggestions": ["建议1", "建议2", "建议3"]
}}

直接输出JSON，不要其他文字。"""

    fallback_used = False
    warning = None
    try:
        content = await _call_ai(prompt, max_tokens=3000)
    except HTTPException as e:
        structured = _fallback_analysis(row, scrape_data, analysis_data)
        content = json.dumps(structured, ensure_ascii=False)
        fallback_used = True
        warning = f"Hermes/Codex 当前不可用，已使用本地规则生成基础分析。原因：{str(e.detail)[:220]}"

    # Merge imgflow data with AI analysis
    combined = {"ai_analysis": content, "imgflow": imgflow_analysis}
    if fallback_used:
        combined["fallback"] = True
        combined["warning"] = warning
    try:
        parsed = json.loads(content.strip().strip("```json").strip("```"))
        combined["structured"] = parsed
    except Exception:
        combined["structured"] = None

    conn = _db()
    conn.execute(
        "UPDATE listing_projects SET analysis_data = ?, status = 'analyzed', updated_at = ? WHERE id = ?",
        (json.dumps(combined, ensure_ascii=False), time.time(), project_id)
    )
    conn.commit()
    conn.close()
    return combined


# ─── Proxy: imgflow analysis (legacy) ────────────────────────────────────────

@router.post("/projects/{project_id}/analyze")
async def analyze(project_id: str, _user: str = Depends(require_user)):
    conn = _db()
    row = conn.execute("SELECT imgflow_project_id FROM listing_projects WHERE id = ?", (project_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404)
    imgflow_id = row["imgflow_project_id"]
    async with httpx.AsyncClient(timeout=180) as client:
        resp = await client.post(f"{_imgflow_base()}/analysis/{imgflow_id}")
        if resp.status_code != 200:
            raise HTTPException(502, f"analysis failed: {resp.text}")
        data = resp.json()
    conn = _db()
    conn.execute(
        "UPDATE listing_projects SET analysis_data = ?, status = 'analyzed', updated_at = ? WHERE id = ?",
        (json.dumps(data, ensure_ascii=False), time.time(), project_id)
    )
    conn.commit()
    conn.close()
    return data


# ─── Copy Generation ──────────────────────────────────────────────────────────

@router.post("/projects/{project_id}/copy")
async def generate_copy(project_id: str, body: GenerateCopyReq, _user: str = Depends(require_user)):
    conn = _db()
    row = conn.execute("SELECT * FROM listing_projects WHERE id = ?", (project_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404)

    scrape_data = json.loads(row["scrape_data"]) if row["scrape_data"] else {}
    analysis_data = json.loads(row["analysis_data"]) if row["analysis_data"] else {}
    product_context = _build_product_context(row, scrape_data, analysis_data)

    prompts = {
        "title": f"""你是Amazon Listing优化专家。生成3个优化后的产品标题候选。
要求：每个≤200字符，品牌+核心关键词+特性+规格，英文输出。
产品信息：
{product_context}
{f"额外要求：{body.context}" if body.context else ""}
输出3个标题，数字编号，每个单独一行。""",

        "bullets": f"""你是Amazon Listing优化专家。生成5条Bullet Points。
要求：大写关键词开头(如 PREMIUM QUALITY:)，每条150-250字符，英文输出。
产品信息：
{product_context}
{f"额外要求：{body.context}" if body.context else ""}""",

        "search_terms": f"""你是Amazon SEO专家。生成后台搜索词。
要求：≤250字节，不重复标题词，空格分隔，英文输出。
产品信息：
{product_context}
直接输出搜索词。""",

        "aplus": f"""你是Amazon A+内容策划专家。生成A+ Content文案。
输出：1.品牌故事 2.横幅标题 3.三个特性模块 4.对比图文案 5.三个场景描述。英文输出。
产品信息：
{product_context}
{f"额外要求：{body.context}" if body.context else ""}""",
    }

    if body.type not in prompts:
        raise HTTPException(400, f"type must be one of: {list(prompts.keys())}")

    fallback_used = False
    warning = None
    try:
        content = await _call_ai(prompts[body.type])
    except HTTPException as e:
        detail = str(e.detail)
        content = _fallback_copy(body.type, row, scrape_data, analysis_data)
        fallback_used = True
        warning = f"Hermes/Codex 当前不可用，已使用本地规则生成一版可编辑文案。原因：{detail[:220]}"

    field_map = {"title": "title", "bullets": "bullets", "search_terms": "search_terms", "aplus": "aplus_copy"}
    conn = _db()
    conn.execute(
        f"UPDATE listing_projects SET {field_map[body.type]} = ?, updated_at = ? WHERE id = ?",
        (content, time.time(), project_id)
    )
    conn.commit()
    conn.close()
    return {"type": body.type, "content": content, "fallback": fallback_used, "warning": warning}


# ─── Generate ALL Prompts at Once (unified style) ─────────────────────────────

@router.post("/projects/{project_id}/generate-all-prompts")
async def generate_all_prompts(project_id: str, body: dict, _user: str = Depends(require_user)):
    """Generate image prompts using 8-step methodology in a single AI call."""
    conn = _db()
    row = conn.execute("SELECT * FROM listing_projects WHERE id = ?", (project_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404)

    scrape_data = json.loads(row["scrape_data"]) if row["scrape_data"] else {}
    analysis_data = json.loads(row["analysis_data"]) if row["analysis_data"] else {}
    product_context = _build_product_context(row, scrape_data, analysis_data)

    ref_images = scrape_data.get("reference_images", []) or scrape_data.get("imageUrls", [])
    ref_urls_text = "\n".join(ref_images[:3]) if ref_images else "No reference images."

    sizes = body.get("sizes", {})
    if isinstance(sizes, dict) and "sizes" in sizes:
        sizes = sizes["sizes"]
    color_scheme = body.get("color_scheme", "")
    all_slots = [
        ("main", "白底主图"), ("sub1", "副图1"), ("sub2", "副图2"), ("sub3", "副图3"),
        ("sub4", "副图4"), ("sub5", "副图5"), ("sub6", "副图6"),
        ("aplus_banner", "A+横幅"), ("aplus_1", "A+模块1"), ("aplus_2", "A+模块2"),
        ("aplus_3", "A+模块3"), ("aplus_4", "A+对比"), ("brand_story", "品牌故事"),
    ]

    color_scheme_rule = f"\n- MANDATORY COLOR SCHEME: All images must use '{color_scheme}' as the dominant color palette. Backgrounds, props, lighting gels, and color grading must align with this palette." if color_scheme else ""

    prompt = f"""You are an Amazon listing image strategist. Complete ALL steps below in one response.

IMPORTANT: Do NOT use web search. Do NOT look up any information online. Work ONLY with the product information provided below. Respond immediately with the JSON output.

## PRODUCT INFO
{product_context}

## REFERENCE IMAGES (only source of truth for product appearance)
{ref_urls_text}

## STEPS TO FOLLOW:
1. IDENTIFY product appearance from reference images (shape, color, material, features, accessories)
2. Determine CATEGORY and top 5 BUYER CONCERNS before purchase
3. Assign each of 7 main images a DIFFERENT sales task solving one buyer concern
4. Write PRODUCT LOCK: strict appearance description + what NOT to add/change
5. Choose VISUAL STYLE based on category buyer psychology
6. Write 13 PROMPTS (120-180 words each) with structure below

## VISUAL QUALITY RULES (apply to EVERY prompt):
- Use cinematic photography language: specify focal length (85mm, 50mm, 35mm), aperture (f/1.8, f/2.8), depth of field
- Specify lighting precisely: "soft key light from upper left with warm fill", "golden hour rim lighting", "three-point studio lighting with hair light"
- Include color grading: "warm amber tones", "cool teal shadows with warm highlights", "rich earth tones with orange accents"
- Add texture/material rendering: "visible surface texture", "light catching micro-details", "condensation droplets"
- For lifestyle scenes: "shot on Sony A7IV", "editorial photography", "National Geographic style"
- For main image: "commercial product photography", "phase-one medium format quality", "razor sharp focus"
- AVOID flat infographic style. Instead of "infographic background with callouts", use "premium 3D render environment with floating glass panels containing text" or "cinematic split-screen composition"
- Text overlays should be described as: "bold modern sans-serif typography, large point size, high contrast against background"
{color_scheme_rule}

## CRITICAL RULES:
- Main image: pure white background, product 85%, no text, studio lighting that reveals every texture
- Every prompt MUST start with the product appearance description (same across all 13)
- Every prompt MUST include this reference URL: {ref_images[0] if ref_images else 'none'}
- Do NOT invent specs not in product info
- For images with text: describe text as part of a premium graphic design composition, not cheap stickers
- Keep product consistent across ALL images
- Each scene should feel like a $10,000 commercial photoshoot, not a stock photo

## OUTPUT FORMAT (valid JSON, no other text):
{{"product_lock":"strict appearance description and prohibitions","visual_style":"style + color palette + why","category":"exact Amazon category","buyer_concerns":["c1","c2","c3","c4","c5"],"prompts":{{"main":"prompt...","sub1":"prompt...","sub2":"prompt...","sub3":"prompt...","sub4":"prompt...","sub5":"prompt...","sub6":"prompt...","aplus_banner":"prompt...","aplus_1":"prompt...","aplus_2":"prompt...","aplus_3":"prompt...","aplus_4":"prompt...","brand_story":"prompt..."}}}}"""

    try:
        content = await _call_ai(prompt, max_tokens=16000, web_search=False)
    except HTTPException:
        slot_details = _slot_details_from_body(body, [sid for sid, _ in all_slots])
        return _fallback_prompts_for_slots(row, scrape_data, analysis_data, slot_details, color_scheme)
    result = _parse_json_response(content)

    if not result or not result.get("prompts"):
        return {"raw": content[:2000], "error": "Failed to parse response"}

    # Save product_lock to DB
    if result.get("product_lock"):
        conn = _db()
        existing = json.loads(row["analysis_data"]) if row["analysis_data"] else {}
        existing["product_lock"] = result["product_lock"]
        existing["visual_style"] = result.get("visual_style", "")
        existing["category"] = result.get("category", "")
        conn.execute(
            "UPDATE listing_projects SET analysis_data = ?, updated_at = ? WHERE id = ?",
            (json.dumps(existing, ensure_ascii=False), time.time(), project_id)
        )
        conn.commit()
        conn.close()

    return result


# ─── Separate Generation Endpoints ────────────────────────────────────────────

MAIN_SLOTS = ["main", "sub1", "sub2", "sub3", "sub4", "sub5", "sub6"]
APLUS_SLOTS = [
    "aplus_banner_desktop", "aplus_banner_mobile",
    "aplus_1_desktop", "aplus_1_mobile",
    "aplus_2_desktop", "aplus_2_mobile",
    "aplus_3_desktop", "aplus_3_mobile",
    "aplus_compare_desktop", "aplus_compare_mobile",
    "brand_story_desktop", "brand_story_mobile",
]


def _slot_details_from_body(body: dict, default_slots: list[str]) -> list[dict]:
    """Normalize dynamic frontend slot config while keeping legacy defaults."""
    raw_slots = body.get("slots")
    if isinstance(raw_slots, list) and raw_slots:
        details = []
        for item in raw_slots:
            if isinstance(item, str):
                sid = item.strip()
                if sid:
                    details.append({"id": sid, "label": sid, "size": ""})
            elif isinstance(item, dict):
                sid = str(item.get("id", "")).strip()
                if sid:
                    details.append({
                        "id": sid,
                        "label": str(item.get("label") or sid).strip(),
                        "size": str(item.get("size") or "").strip(),
                    })
        if details:
            return details

    sizes = body.get("sizes", {})
    if isinstance(sizes, dict) and "sizes" in sizes:
        sizes = sizes["sizes"]
    if not isinstance(sizes, dict):
        sizes = {}
    return [{"id": sid, "label": sid, "size": str(sizes.get(sid, "")).strip()} for sid in default_slots]


async def _generate_prompts_for_slots(project_id: str, slots: list[str], body: dict):
    """Shared logic for generating prompts for a subset of slots."""
    conn = _db()
    row = conn.execute("SELECT * FROM listing_projects WHERE id = ?", (project_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404)

    scrape_data = json.loads(row["scrape_data"]) if row["scrape_data"] else {}
    analysis_data = json.loads(row["analysis_data"]) if row["analysis_data"] else {}
    product_context = _build_product_context(row, scrape_data, analysis_data)

    ref_images = scrape_data.get("reference_images", []) or scrape_data.get("imageUrls", [])
    ref_urls_text = "\n".join(ref_images[:3]) if ref_images else "No reference images."

    slot_details = _slot_details_from_body(body, slots)
    slot_ids = [s["id"] for s in slot_details]
    slot_text = "\n".join(
        f'- {s["id"]}: label="{s["label"]}", target_canvas="{s["size"] or "not specified"}"'
        for s in slot_details
    )

    color_scheme = body.get("color_scheme", "")
    color_scheme_rule = f"\n- MANDATORY COLOR SCHEME: All images must use '{color_scheme}' as the dominant color palette. Backgrounds, props, lighting gels, and color grading must align with this palette." if color_scheme else ""

    slots_json = ", ".join(f'"{s}":"prompt..."' for s in slot_ids)

    prompt = f"""You are an Amazon listing image strategist. Generate prompts ONLY for these slots: {', '.join(slot_ids)}.

IMPORTANT: Do NOT use web search. Work ONLY with the product information provided below.

## PRODUCT INFO
{product_context}

## REFERENCE IMAGES
{ref_urls_text}

## TARGET SLOTS, LABELS, AND CANVAS SIZES
{slot_text}

## VISUAL QUALITY RULES (apply to EVERY prompt):
- Use cinematic photography language: specify focal length, aperture, depth of field
- Specify lighting precisely
- Include color grading
- Add texture/material rendering
- For lifestyle scenes: "shot on Sony A7IV", "editorial photography"
- For main image: "commercial product photography", "phase-one medium format quality", "razor sharp focus"
- AVOID flat infographic style
- Text overlays: "bold modern sans-serif typography, large point size, high contrast"
{color_scheme_rule}

## CRITICAL RULES:
- Main image (if included): pure white background, product 85%, no text
- Every prompt MUST start with product appearance description
- Every prompt MUST include reference URL: {ref_images[0] if ref_images else 'none'}
- Each prompt MUST be composed for its target_canvas size. Mention the exact canvas size and layout orientation inside the prompt.
- For Amazon main images, use a high-resolution square canvas suitable for 1400x1400+ delivery when requested.
- For Premium A+ modules, respect desktop 1464x600 and mobile 600x450 layouts when requested.
- Do NOT invent specs not in product info
- Each scene should feel like a $10,000 commercial photoshoot

## OUTPUT FORMAT (valid JSON, no other text):
{{"product_lock":"strict appearance description","visual_style":"style + color palette","prompts":{{{slots_json}}}}}"""

    try:
        content = await _call_ai(prompt, max_tokens=8000, web_search=False)
    except HTTPException:
        return _fallback_prompts_for_slots(row, scrape_data, analysis_data, slot_details, color_scheme)
    result = _parse_json_response(content)

    if not result or not result.get("prompts"):
        raise HTTPException(502, f"提示词生成失败，AI没有返回可用JSON: {content[:500]}")

    prompts = result.get("prompts", {})
    if isinstance(prompts, dict):
        cleaned = {sid: str(prompts[sid]).strip() for sid in slot_ids if sid in prompts and str(prompts[sid]).strip()}
        if cleaned:
            reviewed = await _review_batch_prompts(cleaned, slot_details, color_scheme)
            result["prompts"] = reviewed
            return result

    raise HTTPException(502, f"提示词生成失败，AI没有返回当前图片位的提示词: {content[:500]}")


@router.post("/projects/{project_id}/generate-main-prompts")
async def generate_main_prompts(project_id: str, body: dict, _user: str = Depends(require_user)):
    """Generate prompts for 7 main images only (main + sub1-sub6)."""
    return await _generate_prompts_for_slots(project_id, MAIN_SLOTS, body)


@router.post("/projects/{project_id}/generate-aplus-prompts")
async def generate_aplus_prompts(project_id: str, body: dict, _user: str = Depends(require_user)):
    """Generate prompts for 6 A+ images only (aplus_banner + aplus_1-4 + brand_story)."""
    return await _generate_prompts_for_slots(project_id, APLUS_SLOTS, body)


# ─── Template CRUD ─────────────────────────────────────────────────────────────

@router.post("/projects/{project_id}/templates")
async def create_template(project_id: str, body: dict, _user: str = Depends(require_user)):
    """Upload a prompt text and have AI convert it to a reusable template."""
    conn = _db()
    row = conn.execute("SELECT id, templates FROM listing_projects WHERE id = ?", (project_id,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404)

    name = body.get("name", "Untitled")
    content = body.get("content", "")
    if not content:
        conn.close()
        raise HTTPException(400, "content is required")

    # Use AI to convert specific prompt into a generic template
    ai_prompt = f"""Convert the following product image prompt into a REUSABLE TEMPLATE by replacing specific details with placeholders.

Replace:
- Specific product descriptions → {{product_lock}}
- Reference URLs → {{reference_url}}
- Visual style descriptions → {{visual_style}}
- Color scheme/palette mentions → {{color_scheme}}

Keep the structure, composition instructions, lighting, and camera settings intact.
Output ONLY the template text with placeholders, nothing else.

ORIGINAL PROMPT:
{content}"""

    fallback_used = False
    warning = None
    try:
        template_content = await _call_ai(ai_prompt, max_tokens=2000, web_search=False)
    except HTTPException as e:
        template_content = _fallback_template_content(content)
        fallback_used = True
        warning = f"Hermes/Codex 当前不可用，模板已按本地规则保存；恢复额度后可重新保存为 AI 泛化模板。原因：{str(e.detail)[:220]}"

    templates = json.loads(row["templates"]) if row["templates"] else []
    template_entry = {
        "id": str(uuid.uuid4())[:8],
        "name": name,
        "content": template_content.strip(),
        "original": content,
        "created_at": time.time(),
        "fallback": fallback_used,
        "warning": warning,
    }
    templates.append(template_entry)

    conn.execute(
        "UPDATE listing_projects SET templates = ?, updated_at = ? WHERE id = ?",
        (json.dumps(templates, ensure_ascii=False), time.time(), project_id)
    )
    conn.commit()
    conn.close()
    return template_entry


@router.get("/projects/{project_id}/templates")
def list_templates(project_id: str, _user: str = Depends(require_user)):
    """Get all templates for a project."""
    conn = _db()
    row = conn.execute("SELECT templates FROM listing_projects WHERE id = ?", (project_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404)
    return json.loads(row["templates"]) if row["templates"] else []


@router.post("/projects/{project_id}/apply-template")
async def apply_template(project_id: str, body: dict, _user: str = Depends(require_user)):
    """Apply a template intelligently to one slot or a full slot group."""
    conn = _db()
    row = conn.execute("SELECT * FROM listing_projects WHERE id = ?", (project_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404)

    template_id = body.get("template_id")
    slot = body.get("slot", "main")
    target_group = body.get("target_group", "main")
    color_scheme = body.get("color_scheme", "natural tones")
    if not template_id:
        raise HTTPException(400, "template_id is required")

    templates = json.loads(row["templates"]) if row["templates"] else []
    template = next((t for t in templates if t["id"] == template_id), None)
    if not template:
        raise HTTPException(404, "template not found")

    analysis_data = json.loads(row["analysis_data"]) if row["analysis_data"] else {}
    scrape_data = json.loads(row["scrape_data"]) if row["scrape_data"] else {}
    ref_images = scrape_data.get("reference_images", []) or scrape_data.get("imageUrls", [])
    product_context = _build_product_context(row, scrape_data, analysis_data)

    filled = template.get("content", "")
    filled = filled.replace("{product_lock}", analysis_data.get("product_lock", "product as shown in reference"))
    filled = filled.replace("{reference_url}", ref_images[0] if ref_images else "")
    filled = filled.replace("{visual_style}", analysis_data.get("visual_style", "professional product photography"))
    filled = filled.replace("{color_scheme}", color_scheme or "natural tones")

    default_main_defs = {
        "main": "Amazon main image: pure white background, product 85%, no text.",
        "sub1": "Lifestyle or use-case image.",
        "sub2": "Detail or key feature image.",
        "sub3": "Size, specification, or scale image.",
        "sub4": "Multi-angle, technology, or structure image.",
        "sub5": "Package, accessories, or what-is-in-the-box image.",
        "sub6": "Multi-scenario, benefits, or closing sales image.",
    }
    default_aplus_defs = {
        "aplus_banner": "Wide A+ hero banner.",
        "aplus_banner_desktop": "Premium A+ hero banner for desktop, wide 1464x600 layout.",
        "aplus_banner_mobile": "Premium A+ hero banner for mobile, compact 600x450 layout.",
        "aplus_1": "A+ module 1, primary feature.",
        "aplus_1_desktop": "A+ module 1 desktop version, primary feature in 1464x600 layout.",
        "aplus_1_mobile": "A+ module 1 mobile version, same feature adapted to 600x450 layout.",
        "aplus_2": "A+ module 2, secondary feature.",
        "aplus_2_desktop": "A+ module 2 desktop version, secondary feature in 1464x600 layout.",
        "aplus_2_mobile": "A+ module 2 mobile version, same feature adapted to 600x450 layout.",
        "aplus_3": "A+ module 3, tertiary feature.",
        "aplus_3_desktop": "A+ module 3 desktop version, tertiary feature in 1464x600 layout.",
        "aplus_3_mobile": "A+ module 3 mobile version, same feature adapted to 600x450 layout.",
        "aplus_4": "A+ comparison, trust, specs, or advantage module.",
        "aplus_compare_desktop": "A+ comparison, trust, specs, or advantage module for desktop 1464x600 layout.",
        "aplus_compare_mobile": "A+ comparison, trust, specs, or advantage module for mobile 600x450 layout.",
        "brand_story": "Brand story or final trust-building module.",
        "brand_story_desktop": "Brand story or final trust-building module for desktop 1464x600 layout.",
        "brand_story_mobile": "Brand story or final trust-building module for mobile 600x450 layout.",
    }
    default_defs = default_aplus_defs if target_group == "aplus" else default_main_defs
    default_slots = list(default_defs.keys())
    target_slot_details = _slot_details_from_body(body, default_slots)
    slot_defs = {
        s["id"]: f'{s["label"]}; target canvas {s["size"] or "not specified"}; {default_defs.get(s["id"], "")}'
        for s in target_slot_details
    }

    slot_lines = "\n".join(f"- {k}: {v}" for k, v in slot_defs.items())
    ref_text = "\n".join(ref_images[:3]) if ref_images else "No reference image URL available."

    ai_prompt = f"""You are an Amazon listing image prompt strategist.

Apply the user's reusable template to the CURRENT PRODUCT. Do NOT paste the template verbatim.

## CURRENT PRODUCT DATA
{product_context}

## PRODUCT LOCK
{analysis_data.get("product_lock", "Describe the product exactly as shown in reference images. Do not change appearance.")}

## VISUAL STYLE
{analysis_data.get("visual_style", "Professional Amazon product photography.")}

## REFERENCE IMAGES
{ref_text}

## TARGET SLOT GROUP
{target_group}

## AVAILABLE SLOTS
{slot_lines}

## REQUESTED SLOT
{slot}

## FILLED TEMPLATE TO ANALYZE
{filled}

## TASK
1. First decide whether the template describes a single image or a multi-image set / full A+ sequence.
2. If it is a multi-image set, split and adapt it across the relevant available slots. For a full A+ poster/template, create separate prompts for aplus_banner, aplus_1, aplus_2, aplus_3, aplus_4, and brand_story when possible.
3. If it is a single-image template, adapt it only to the requested slot.
4. Every output prompt must be for GPT Image generation, not instructions about the template itself.
5. Use real current product data, product_lock, visual_style, color scheme, and reference images.
6. Keep product appearance consistent. Do not invent unsupported specs.
7. For each prompt: 100-220 words, include the reference image URL when available, include clear composition/lighting/text instructions.
8. Respect each slot's target canvas and orientation. For Premium A+ desktop use 1464x600 when configured; for mobile use 600x450 when configured.
9. If the user's template is a full A+ desktop/mobile system, distribute it across all configured A+ desktop and mobile slots instead of putting everything into one prompt.
10. Do not output placeholder braces like {{product_lock}} or {{reference_url}}.

## OUTPUT FORMAT
Return valid JSON only:
{{"mode":"single_or_multi","prompts":{{"slot_id":"adapted prompt text"}}}}"""

    try:
        content = await _call_ai(ai_prompt, max_tokens=12000, web_search=False)
    except HTTPException:
        result = _fallback_prompts_for_slots(row, scrape_data, analysis_data, target_slot_details, color_scheme, filled)
        prompts = result["prompts"]
        return {
            "slot": slot,
            "prompt": prompts.get(slot, next(iter(prompts.values()))),
            "prompts": prompts,
            "mode": "fallback_multi" if len(prompts) > 1 else "fallback_single",
            "fallback": True,
            "warning": result["warning"],
        }
    result = _parse_json_response(content)
    prompts = result.get("prompts") if isinstance(result, dict) else None
    if isinstance(prompts, dict):
        cleaned = {k: str(v).strip() for k, v in prompts.items() if k in slot_defs and str(v).strip()}
        if cleaned:
            return {"slot": slot, "prompt": cleaned.get(slot, next(iter(cleaned.values()))), "prompts": cleaned, "mode": result.get("mode", "")}

    raise HTTPException(502, f"模板智能套用失败，AI没有返回可用的槽位提示词: {content[:500]}")


def _parse_json_response(content: str) -> Optional[dict]:
    """Robustly parse JSON from AI response, handling markdown fences and formatting issues."""
    if not content:
        return None

    # Strip markdown code fences
    cleaned = content.strip()
    if cleaned.startswith("```"):
        # Remove first line (```json or ```)
        first_newline = cleaned.find("\n")
        if first_newline != -1:
            cleaned = cleaned[first_newline + 1:]
        else:
            cleaned = cleaned[3:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        cleaned = cleaned.strip()

    # Try direct parse
    try:
        return json.loads(cleaned)
    except Exception:
        pass

    # Try brace-depth matching to find the outermost JSON object
    depth = 0
    start_idx = None
    end_idx = None
    in_string = False
    escape_next = False
    for i, c in enumerate(content):
        if escape_next:
            escape_next = False
            continue
        if c == '\\' and in_string:
            escape_next = True
            continue
        if c == '"' and not escape_next:
            in_string = not in_string
            continue
        if in_string:
            continue
        if c == '{':
            if depth == 0:
                start_idx = i
            depth += 1
        elif c == '}':
            depth -= 1
            if depth == 0 and start_idx is not None:
                end_idx = i + 1
                break

    if start_idx is not None and end_idx is not None:
        try:
            return json.loads(content[start_idx:end_idx])
        except Exception:
            pass

    return None


# ─── Single Image Prompt ───────────────────────────────────────────────────────

@router.post("/projects/{project_id}/generate-image-prompt")
async def generate_image_prompt(project_id: str, body: dict, _user: str = Depends(require_user)):
    conn = _db()
    row = conn.execute("SELECT * FROM listing_projects WHERE id = ?", (project_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404)

    slot = body.get("slot", "main")
    slot_label = str(body.get("label") or slot).strip()
    slot_size = str(body.get("size") or "").strip()
    color_scheme = body.get("color_scheme", "")
    scrape_data = json.loads(row["scrape_data"]) if row["scrape_data"] else {}
    analysis_data = json.loads(row["analysis_data"]) if row["analysis_data"] else {}
    product_context = _build_product_context(row, scrape_data, analysis_data)

    # Get product_lock and image_tasks from previous pipeline analysis
    product_lock = analysis_data.get("product_lock", "")
    visual_style = analysis_data.get("visual_style", "")
    image_tasks = analysis_data.get("image_tasks", {})
    slot_task = image_tasks.get(slot, "")

    # Reference images
    ref_images = scrape_data.get("reference_images", []) or scrape_data.get("imageUrls", [])
    ref_urls_text = "\n".join(ref_images[:3]) if ref_images else ""

    slot_descriptions = {
        "main": "White background main image. Pure white (#FFFFFF), product centered 85%, no text, no icons. Include accessories if they show kit value. Soft studio shadow.",
        "sub1": "Outdoor/lifestyle scene showing the product in real use. Authentic environment, natural lighting.",
        "sub2": "Detail/feature image highlighting key selling point. Can include clean text callouts.",
        "sub3": "Specifications/size image. Clean infographic style with dimensions or scale reference.",
        "sub4": "Technology/multi-angle image. Show internal features or multiple views.",
        "sub5": "Package/accessories image. Show everything included in the kit.",
        "sub6": "Multi-scenario image. Show 3-4 different use cases around the product.",
        "aplus_banner": "Wide-format A+ banner. Cinematic, brand-level imagery.",
        "aplus_banner_desktop": "Wide-format Premium A+ desktop banner. Cinematic brand-level imagery composed for 1464x600.",
        "aplus_banner_mobile": "Mobile Premium A+ banner. Same hero idea adapted to a compact 600x450 layout.",
        "aplus_1": "A+ feature module highlighting primary selling point.",
        "aplus_1_desktop": "A+ desktop feature module highlighting primary selling point in a wide 1464x600 layout.",
        "aplus_1_mobile": "A+ mobile feature module highlighting primary selling point in a compact 600x450 layout.",
        "aplus_2": "A+ feature module highlighting secondary selling point.",
        "aplus_2_desktop": "A+ desktop feature module highlighting secondary selling point in a wide 1464x600 layout.",
        "aplus_2_mobile": "A+ mobile feature module highlighting secondary selling point in a compact 600x450 layout.",
        "aplus_3": "A+ feature module highlighting tertiary selling point.",
        "aplus_3_desktop": "A+ desktop feature module highlighting tertiary selling point in a wide 1464x600 layout.",
        "aplus_3_mobile": "A+ mobile feature module highlighting tertiary selling point in a compact 600x450 layout.",
        "aplus_4": "A+ comparison image showing product advantages.",
        "aplus_compare_desktop": "A+ desktop comparison, specs, trust, or advantage module in a wide 1464x600 layout.",
        "aplus_compare_mobile": "A+ mobile comparison, specs, trust, or advantage module in a compact 600x450 layout.",
        "brand_story": "Brand story image communicating brand values and mission.",
        "brand_story_desktop": "Desktop brand story or trust-building module in a wide 1464x600 layout.",
        "brand_story_mobile": "Mobile brand story or trust-building module in a compact 600x450 layout.",
    }
    slot_desc = slot_descriptions.get(slot, f"{slot_label}. Product showcase image.")

    prompt = f"""You are an Amazon product image prompt engineer. Write ONE image generation prompt for this slot.

## SLOT TYPE
{slot_desc}

## CURRENT SLOT CONFIG
- Slot id: {slot}
- Slot label: {slot_label}
- Target canvas: {slot_size or "not specified"}

## SALES TASK FOR THIS IMAGE
{slot_task if slot_task else "Attract buyer attention and communicate product value."}

## PRODUCT LOCK (you MUST start your prompt with this — do not change the product appearance)
{product_lock if product_lock else "Describe the product exactly as shown in reference images. Do not alter its design."}

## VISUAL STYLE
{visual_style if visual_style else "Professional Amazon product photography style appropriate for this category."}
{"" if not color_scheme else f"MANDATORY COLOR SCHEME: Use '{color_scheme}' as the dominant color palette for backgrounds, props, lighting, and color grading."}

## PRODUCT INFORMATION
{product_context}

## REFERENCE IMAGES (include these URLs in your prompt so the image generator can see the real product)
{ref_urls_text if ref_urls_text else "No reference images available."}

## PROMPT STRUCTURE (follow this exactly):
1. Product appearance lock — exact physical description from product lock above
2. Reference image instruction — "Reference: [URL]" (use actual URL from above)
3. Image goal — what this image must communicate (from sales task)
4. Scene/background — specific environment or background
5. Composition — product position, size in frame, camera angle
6. Canvas/layout — compose for target canvas {slot_size or "not specified"} and mention that exact size in the prompt
7. Text/callouts — specific text to show on image (English, short, impactful) OR "no text" for main image
8. Style/lighting — colors, lighting setup, mood
9. Negative constraints — what NOT to include

## RULES
- Output ONLY the prompt text, no explanations, no prefixes
- 100-200 words
- First sentence MUST be the product lock (exact appearance description)
- MUST include at least one reference image URL
- MUST respect the current slot label and target canvas
- For infographic images: include specific text callouts that communicate the selling point
- Do NOT invent specs not mentioned in product info
- Do NOT use generic language like "high quality" or "professional" alone"""

    try:
        content = await _call_ai(prompt, max_tokens=16000)
    except HTTPException as e:
        content = _fallback_image_prompt(slot, slot_label, slot_size, row, scrape_data, analysis_data, color_scheme)
        return {
            "slot": slot,
            "prompt": content.strip(),
            "fallback": True,
            "warning": f"Hermes/Codex 当前不可用，已用本地规则生成可编辑图片提示词。原因：{str(e.detail)[:220]}",
        }
    return {"slot": slot, "prompt": content.strip()}


@router.post("/projects/{project_id}/review-image-prompt")
async def review_image_prompt(project_id: str, body: dict, _user: str = Depends(require_user)):
    """Accept a user-submitted prompt draft, self-review and return an improved version."""
    conn = _db()
    row = conn.execute("SELECT id FROM listing_projects WHERE id = ?", (project_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404)

    slot = body.get("slot", "main")
    draft = body.get("prompt", "").strip()
    label = str(body.get("label") or slot).strip()
    size = str(body.get("size") or "").strip()
    color_scheme = body.get("color_scheme", "")

    if not draft:
        raise HTTPException(400, "prompt is required")

    reviewed = await _review_single_prompt(draft, label, size, color_scheme)
    return {"slot": slot, "prompt": reviewed}


# ─── Image Generation ─────────────────────────────────────────────────────────

@router.post("/projects/{project_id}/generate-image")
async def generate_single_image(project_id: str, body: ImageGenReq, _user: str = Depends(require_user)):
    conn = _db()
    row = conn.execute("SELECT id, scrape_data, analysis_data FROM listing_projects WHERE id = ?", (project_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404)

    # Get reference image URLs to pass as image_urls parameter
    ref_urls = body.reference_urls
    if not ref_urls:
        scrape_data = json.loads(row["scrape_data"]) if row["scrape_data"] else {}
        ref_urls = (scrape_data.get("reference_images") or scrape_data.get("imageUrls") or [])[:2]

    if not _apimart_key():
        raise HTTPException(
            400,
            "Apimart 密钥未配置 — 请在「系统配置 → AI 服务」填入有 gpt-image-2 权限的密钥。",
        )

    try:
        async with httpx.AsyncClient(timeout=180) as client:
            req_body = {
                "model": "gpt-image-2",
                "prompt": body.prompt,
                "n": 1,
                "size": body.size,
            }
            if ref_urls:
                req_body["image_urls"] = ref_urls[:4]

            import logging
            logging.info(f"[generate-image] slot={body.slot} ref_urls={len(ref_urls)} image_urls={req_body.get('image_urls', 'NONE')}")

            resp = await client.post(
                f"{_apimart_base()}/images/generations",
                headers={"Authorization": f"Bearer {_apimart_key()}", "Content-Type": "application/json"},
                json=req_body,
            )
            if resp.status_code != 200:
                raise HTTPException(502, f"图片生成提交失败: {resp.text[:300]}")

            submit_data = resp.json()
            task_id = submit_data.get("data", [{}])[0].get("task_id")
            if not task_id:
                raise HTTPException(502, f"未返回task_id: {resp.text[:300]}")

            url = await _poll_task(client, task_id)
            if url:
                return {"slot": body.slot, "url": url}
            raise HTTPException(504, "图片生成超时(120s)")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, f"图片生成失败: {str(e)}")


async def _poll_task(client: httpx.AsyncClient, task_id: str) -> Optional[str]:
    """Poll APIMart task until completion."""
    for _ in range(24):
        await asyncio.sleep(5)
        poll = await client.get(
            f"{_apimart_base()}/tasks/{task_id}",
            headers={"Authorization": f"Bearer {_apimart_key()}"},
        )
        if poll.status_code != 200:
            continue
        task_data = poll.json().get("data", {})
        status = task_data.get("status")
        if status == "completed":
            images = task_data.get("result", {}).get("images", [])
            if images and images[0].get("url"):
                url = images[0]["url"]
                if isinstance(url, list):
                    url = url[0]
                return url
            raise HTTPException(502, "任务完成但未返回图片URL")
        elif status == "failed":
            raise HTTPException(502, f"图片生成失败: {task_data}")
    return None


# ─── PSD Download ─────────────────────────────────────────────────────────────

@router.post("/projects/{project_id}/download-psd")
async def download_psd(project_id: str, body: dict, _user: str = Depends(require_user)):
    """Download an image as PSD format."""
    image_url = body.get("url")
    slot = body.get("slot", "image")
    if not image_url:
        raise HTTPException(400, "url is required")

    # Download the image
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(image_url)
            if resp.status_code != 200:
                raise HTTPException(502, "Failed to download image")
            image_bytes = resp.content
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, f"Download failed: {e}")

    # Convert to PSD
    from PIL import Image
    from psd_tools import PSDImage

    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    psd = PSDImage.frompil(img)
    buf = io.BytesIO()
    psd.save(buf)
    buf.seek(0)

    filename = f"{project_id}_{slot}.psd"
    return StreamingResponse(
        buf,
        media_type="application/octet-stream",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


# ─── Serve uploaded images ─────────────────────────────────────────────────────

@router.get("/images/{project_id}/{filename}")
def serve_image(project_id: str, filename: str):
    """Serve uploaded listing images."""
    fpath = IMAGES_DIR / project_id / filename
    if not fpath.exists():
        raise HTTPException(404)
    import mimetypes
    mime = mimetypes.guess_type(str(fpath))[0] or "image/png"
    return StreamingResponse(open(fpath, "rb"), media_type=mime)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _clean_text(value) -> str:
    return " ".join(str(value or "").replace("\n", " ").split())


def _scrape_field(scrape_data: dict, key: str, default=""):
    product = scrape_data.get("product") if isinstance(scrape_data.get("product"), dict) else {}
    return scrape_data.get(key) or product.get(key) or default


def _copy_source(row, scrape_data: dict, analysis_data: dict) -> dict:
    title = _clean_text(_scrape_field(scrape_data, "title") or row["asin"])
    raw_bullets = _scrape_field(scrape_data, "bullets", [])
    if isinstance(raw_bullets, str):
        bullets = [raw_bullets]
    elif isinstance(raw_bullets, list):
        bullets = raw_bullets
    else:
        bullets = []
    manual = scrape_data.get("manual", {}) if isinstance(scrape_data.get("manual"), dict) else {}
    manual_points = [x.strip() for x in str(manual.get("selling_points") or "").splitlines() if x.strip()]
    bullets = [_clean_text(x) for x in (manual_points or bullets) if _clean_text(x)]
    description = _clean_text(manual.get("description") or _scrape_field(scrape_data, "description") or "")
    audience = _clean_text(manual.get("target_audience") or "Amazon shoppers looking for reliable, easy-to-use product performance")
    structured = analysis_data.get("structured") if isinstance(analysis_data.get("structured"), dict) else {}
    keywords = structured.get("keywords") if isinstance(structured.get("keywords"), list) else []
    usp = structured.get("usp") if isinstance(structured.get("usp"), list) else []
    return {
        "asin": row["asin"],
        "marketplace": row["marketplace"],
        "title": title,
        "bullets": bullets[:8],
        "description": description,
        "audience": audience,
        "keywords": [_clean_text(k).lower() for k in keywords if _clean_text(k)],
        "usp": [_clean_text(u) for u in usp if _clean_text(u)],
    }


def _keywords_from_text(text: str, limit: int = 36) -> list[str]:
    stop = {
        "with", "from", "that", "this", "your", "their", "and", "for", "the", "our",
        "are", "you", "not", "can", "has", "have", "will", "all", "new", "use",
        "amazon", "about", "choose", "quality", "product", "products",
    }
    words = []
    for raw in text.lower().replace("/", " ").replace("-", " ").replace(",", " ").split():
        word = "".join(ch for ch in raw if ch.isalnum())
        if len(word) < 3 or word in stop or word.isdigit():
            continue
        if word not in words:
            words.append(word)
        if len(words) >= limit:
            break
    return words


def _fallback_copy(copy_type: str, row, scrape_data: dict, analysis_data: dict) -> str:
    """Deterministic copy fallback for AI gateway 429. Output is intentionally editable."""
    src = _copy_source(row, scrape_data, analysis_data)
    title = src["title"]
    bullets = src["bullets"] or ([src["description"]] if src["description"] else [])
    feature_pool = src["usp"] + bullets
    if not feature_pool:
        feature_pool = [
            f"Designed for dependable everyday performance for ASIN {src['asin']}",
            "Built to help shoppers solve the core need shown in the product listing",
            "Easy to use, practical, and suitable for the intended Amazon marketplace",
        ]

    if copy_type == "title":
        base = title[:180].strip()
        return "\n".join([
            f"1. {base}",
            f"2. {base} for {src['audience'][:55]}".strip()[:200],
            f"3. {base} with Practical Features and Everyday Value".strip()[:200],
        ])

    if copy_type == "bullets":
        heads = ["CORE BENEFIT", "RELIABLE DESIGN", "EASY TO USE", "PRACTICAL VALUE", "BUYER READY"]
        lines = []
        for i, head in enumerate(heads):
            detail = feature_pool[i % len(feature_pool)]
            lines.append(f"{head}: {detail[:220]}")
        return "\n".join(lines)

    if copy_type == "search_terms":
        text = " ".join([title, src["description"], " ".join(bullets), " ".join(src["keywords"])])
        terms = src["keywords"] + _keywords_from_text(text)
        deduped = []
        for term in terms:
            if term and term not in deduped:
                deduped.append(term)
        out = " ".join(deduped)
        return out[:250].strip()

    if copy_type == "aplus":
        f1 = feature_pool[0]
        f2 = feature_pool[1 % len(feature_pool)]
        f3 = feature_pool[2 % len(feature_pool)]
        return f"""Brand Story
Built around practical performance and buyer confidence, this product is designed to support {src['audience']}.

Hero Banner
{title[:120]}

Feature Module 1
{f1[:260]}

Feature Module 2
{f2[:260]}

Feature Module 3
{f3[:260]}

Comparison / Advantage
Clear value, useful features, and a straightforward experience for shoppers comparing similar options.

Usage Scenarios
1. Everyday use for the primary product need.
2. Giftable or household-ready use where reliability matters.
3. Outdoor, work, travel, or category-relevant use depending on the product context."""

    raise HTTPException(400, f"type must be one of: title, bullets, search_terms, aplus")


def _build_product_context(row, scrape_data: dict, analysis_data: dict) -> str:
    """Build text context from scrape + analysis data for AI prompts."""
    parts = [f"ASIN: {row['asin']}", f"Marketplace: {row['marketplace']}"]

    if scrape_data:
        if scrape_data.get("title"):
            parts.append(f"Current Title: {scrape_data['title']}")
        if scrape_data.get("bullets"):
            bullets = scrape_data["bullets"]
            if isinstance(bullets, list):
                parts.append("Current Bullets:\n" + "\n".join(f"- {b}" for b in bullets))
        if scrape_data.get("description"):
            parts.append(f"Description: {scrape_data['description'][:500]}")
        manual = scrape_data.get("manual", {})
        if manual.get("product_name"):
            parts.append(f"Product Name: {manual['product_name']}")
        if manual.get("description"):
            parts.append(f"Product Description: {manual['description']}")
        if manual.get("selling_points"):
            parts.append(f"Selling Points: {manual['selling_points']}")
        if manual.get("target_audience"):
            parts.append(f"Target Audience: {manual['target_audience']}")

    if analysis_data:
        # Support both old format and new structured format
        if analysis_data.get("structured"):
            s = analysis_data["structured"]
            if s.get("usp"):
                parts.append(f"USP: {', '.join(s['usp'])}")
            if s.get("keywords"):
                parts.append(f"Keywords: {', '.join(s['keywords'][:15])}")
            if s.get("target_audience"):
                parts.append(f"Target Audience: {s['target_audience']}")
            if s.get("scenarios"):
                parts.append(f"Use Scenarios: {', '.join(s['scenarios'])}")
        elif analysis_data.get("analysis"):
            parts.append(f"AI Analysis: {str(analysis_data['analysis'])[:800]}")
        # imgflow data
        if analysis_data.get("imgflow"):
            imgf = analysis_data["imgflow"]
            if imgf.get("sifKeywords"):
                parts.append(f"SIF Keywords: {', '.join(imgf['sifKeywords'][:15])}")
            if imgf.get("uspExtraction"):
                parts.append(f"USP (imgflow): {imgf['uspExtraction'][:300]}")
            if imgf.get("sorftimeData"):
                parts.append(f"Sorftime Trends: {str(imgf['sorftimeData'])[:200]}")

    return "\n\n".join(parts)
