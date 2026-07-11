"""套图美术指导：产品画像 → 整套策划 → 提示词编译 → 质检门槛。

复核（单图/整套）走统一视觉链（stream_vision），不再直连 apimart /messages
（该端点恒 403，老实现导致复核永远"未返回"）。
"""
from __future__ import annotations

import asyncio
import base64
import io
import json
import re
import time
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.core.security import require_user

from .ai import _call_ai, _collect_vision, has_vision
from .common import (
    IMAGES_DIR, _approved_copy, _build_product_context, _cached_white_product_source,
    _clean_text, _copy_source, _db, _detect_white_product_source, _fetch_image_bytes,
    _img_datauri_from_path, _img_datauri_from_url, _reference_images, _strip_json,
    project_row, update_project,
)
from .jobs import JobHandle, start_job

router = APIRouter()


class PlanImageSetReq(BaseModel):
    target_count: int = 0           # 0 = let the AI pick (5–8); else exact count
    color_scheme: str = ""
    language: str = "en"            # callout language hint (for typography)
    deliverable: str = "gallery"    # gallery | aplus; both use the same engine
    visual_tone: str = "natural"    # natural | studio | editorial
    brief: str = ""


class ReviewRenderReq(BaseModel):
    url: str
    size: str = "1600x1600"
    slot: str = ""
    role: str = ""
    shot_type: str = ""
    layout_blueprint: str = ""
    eyebrow: str = ""
    headline: str = ""
    callout: str = ""
    supporting_text: str = ""
    proof: str = ""
    source_url: str = ""
    show_product: bool = True
    product_fidelity_anchors: list[str] = []


class ReviewSetReq(BaseModel):
    deliverable: str = "gallery"


# ─── 视觉词汇表 ───────────────────────────────────────────────────────────────

_DEFAULT_ROLES = ["主图", "核心利益", "真实使用", "关键细节", "对比证明", "规格/兼容", "包装清单", "信任收口"]
_APLUS_ROLES = ["品牌首屏", "核心利益", "使用方式", "技术/细节", "信任收口"]

_SHOT_TYPES = {
    "white_main", "hero_feature", "lifestyle", "detail", "comparison",
    "specs", "in_box", "trust", "aplus_banner",
}
_LEGACY_SHOT_TYPE = {"feature": "hero_feature", "scene": "lifestyle"}
_DEFAULT_TYPE_ORDER = [
    "white_main", "hero_feature", "lifestyle", "detail",
    "comparison", "specs", "in_box", "trust",
]
_APLUS_TYPE_ORDER = ["aplus_banner", "hero_feature", "lifestyle", "detail", "trust"]
_TEXT_ZONES = {
    "top-left", "top-center", "top-right", "center-left", "center-right",
    "bottom-left", "bottom-center", "bottom-right",
}
_LAYOUT_STYLES = {"editorial", "minimal", "split", "proof", "grid"}
_LAYOUT_BLUEPRINTS = {
    "white_bundle", "media_proof_split", "connectivity_diagram",
    "environmental_proof", "coverage_diagram", "speed_comparison",
    "day_night_split", "use_case_mosaic",
}
_DEFAULT_BLUEPRINT_ORDER = [
    "white_bundle", "media_proof_split", "connectivity_diagram",
    "environmental_proof", "coverage_diagram", "speed_comparison",
    "day_night_split", "use_case_mosaic",
]
_BLUEPRINT_PANEL_COUNTS = {
    "white_bundle": 0, "media_proof_split": 2, "connectivity_diagram": 1,
    "environmental_proof": 1, "coverage_diagram": 1,
    "speed_comparison": 1, "day_night_split": 2, "use_case_mosaic": 6,
}
# The studio renders every planned card through the image model.  Keeping this
# set empty is important: review_render must compare generated main/in-box
# images with the product truth instead of treating them as untouched pixels.
_SOURCE_LOCKED_TYPES: set[str] = set()
_INTERNAL_PUBLIC_COPY_RE = re.compile(
    r"\b(approved copy|approved title|product facts?|claim(?:s)?|image should|"
    r"do not fabricate|source material|evidence|supported by|supports? (?:the|this))\b",
    re.I,
)
_HYPE_PROMPT_RE = re.compile(
    r"\b(neon|cyber|sci[- ]?fi|light trails?|floating (?:glass )?panels?|"
    r"hologra(?:m|phic)|futuristic platform|epic cinematic|hyperreal fantasy|"
    r"10,?000 commercial|national geographic style)\b",
    re.I,
)

# Reproduce the real product instead of re-imagining it. The reference photos are
# sent to the image model as actual image inputs at generation time, so URLs in the
# text prompt are useless noise and are explicitly forbidden here.
_FIDELITY_RULE = (
    "- PRODUCT FIDELITY: The real product photos are supplied to the image model directly as image inputs. "
    "Reproduce the product EXACTLY as shown there — identical shape, proportions, colors, materials, logos and "
    "any text printed on the product. Do NOT redesign, recolor, relabel or restyle the product itself; only "
    "change the background, scene, props and lighting. Never put a URL inside the prompt."
)


# ─── 提示词整地 ───────────────────────────────────────────────────────────────

def _ground_render_prompt(value: str) -> str:
    """Remove known prompt habits that systematically create synthetic ad art."""
    text = str(value or "").strip()
    replacements = {
        r"\bno neon(?: light trails?)?\b": "avoid stylized lighting",
        r"\bno floating (?:glass )?panels?\b": "avoid decorative overlays",
        r"\bneon light trails?\b": "subtle practical light",
        r"\bneon\b": "stylized colored lighting",
        r"\blight trails?\b": "natural motion blur",
        r"\bcyber(?:punk)?\b": "contemporary",
        r"\bsci[- ]?fi\b": "contemporary",
        r"\bfloating (?:glass )?panels?\b": "clean negative space",
        r"\bhologra(?:m|phic)\w*\b": "subtle graphic depth",
        r"\bfuturistic platform\b": "simple real surface",
        r"\bepic cinematic\b": "natural editorial",
        r"\bhyperreal fantasy\b": "realistic photography",
        r"\b(?:a )?\$?10,?000 commercial photoshoot\b": "restrained ecommerce photography",
        r"\bnational geographic style\b": "documentary photography",
    }
    for pattern, replacement in replacements.items():
        text = re.sub(pattern, replacement, text, flags=re.I)
    return re.sub(r"\s{2,}", " ", text).strip()


def _remove_legacy_textless_directions(value: str) -> str:
    """Remove obsolete 'generate a blank plate' instructions before compiling
    an exact-text final-artwork prompt.

    Existing projects and the deterministic fallback can contain these phrases.
    Keeping them beside the new copy contract gives the image model mutually
    exclusive instructions and is a major source of missing or garbled type.
    """
    text = str(value or "")
    patterns = (
        r"[^.\n]*(?:typography|copy|text)\s+(?:is|will be)\s+(?:added|typeset)\s+(?:later|separately)[^.\n]*[.\n]?",
        r"[^.\n]*(?:reserve|keep)\s+[^.\n]*(?:for later typography|for separately typeset copy)[^.\n]*[.\n]?",
        r"[^.\n]*render\s+no\s+(?:added\s+marketing\s+)?(?:copy|text|words|letters)[^.\n]*[.\n]?",
        r"[^.\n]*\bno\s+(?:added\s+)?(?:text|words|letters|marketing copy)\b[^.\n]*[.\n]?",
        r"[^.\n]*no\s+words,?\s+no\s+icons[^.\n]*[.\n]?",
    )
    for pattern in patterns:
        text = re.sub(pattern, " ", text, flags=re.I)
    return re.sub(r"\s{2,}", " ", text).strip()


def _public_text(value, limit: int) -> Optional[str]:
    """Keep only concise shopper-facing copy; internal chain-of-thought is never art."""
    text = re.sub(r"\s+", " ", str(value or "").strip())
    if not text or _INTERNAL_PUBLIC_COPY_RE.search(text):
        return None
    return text[:limit].rstrip()


def _public_proof(value) -> Optional[str]:
    from app.services.listing_typography import public_proof
    return public_proof(str(value or "")) or None


def _clamped_float(value, default: float, low: float, high: float) -> float:
    try:
        return max(low, min(float(value), high))
    except (TypeError, ValueError):
        return default


def _readable_accent(value: str) -> str:
    text = str(value or "#67C95B").strip().lstrip("#")
    if len(text) != 6 or not re.fullmatch(r"[0-9a-fA-F]{6}", text):
        return "#67C95B"
    rgb = [int(text[index:index + 2], 16) for index in (0, 2, 4)]
    peak = max(rgb)
    if peak < 150:
        factor = 185 / max(1, peak)
        rgb = [min(230, round(channel * factor)) for channel in rgb]
    return "#" + "".join(f"{channel:02X}" for channel in rgb)


_DEFAULT_SET_PALETTES = {
    "soft_goods": ["#F4F0E8", "#D8C7B5", "#8A6F56", "#4E5B4B", "#282622"],
    "spatial_gear": ["#E9E3D6", "#A7AD8C", "#667151", "#B97645", "#252A23"],
    "rigid_device": ["#EEF1F3", "#C8D0D6", "#657581", "#6E8D72", "#22292E"],
    "category_specific": ["#F2EFE9", "#D7D0C5", "#8A7967", "#66736B", "#292A28"],
}


def _normalise_set_style(style: dict, product_profile: dict) -> dict:
    """Create one concrete, reusable colour grammar for the whole set."""
    source = dict(style) if isinstance(style, dict) else {}
    behaviour = _clean_text(product_profile.get("object_behavior")) or "category_specific"
    requested = " ".join(str(source.get(key) or "") for key in ("palette", "direction"))
    profile_palette = product_profile.get("supporting_palette") or []
    requested += " " + " ".join(str(value) for value in profile_palette)
    colours: list[str] = []
    for value in re.findall(r"#[0-9a-fA-F]{6}\b", requested):
        upper = value.upper()
        if upper not in colours:
            colours.append(upper)
    defaults = _DEFAULT_SET_PALETTES.get(behaviour, _DEFAULT_SET_PALETTES["category_specific"])
    for value in defaults:
        if len(colours) >= 5:
            break
        if value not in colours:
            colours.append(value)
    colours = colours[:5]
    product_colours = [
        _clean_text(value) for value in (product_profile.get("product_colours") or [])
        if _clean_text(value)
    ][:5]
    source.update({
        "direction": _clean_text(source.get("direction")) or (
            f"Product-led {behaviour.replace('_', ' ')} commercial photography with realistic materials"
        ),
        "palette": (
            f"background {colours[0]}; surface {colours[1]}; supporting tone {colours[2]}; "
            f"brand accent {colours[3]}; deep neutral {colours[4]}"
        ),
        "palette_hex": colours,
        "product_colours": product_colours,
        "lighting": _clean_text(source.get("lighting")) or "soft directional key light with consistent neutral white balance",
        "materials": _clean_text(source.get("materials")) or "real category-appropriate materials with restrained supporting props",
        "type_system": _clean_text(source.get("type_system")) or "clean high-contrast ecommerce typography",
        "accent_color": _readable_accent(source.get("accent_color") or colours[3]),
    })
    return source


def _replace_prompt_section(prompt: str, name: str, content: str) -> str:
    """Replace a canonical prompt section so repeated saves never grow prompts."""
    pattern = rf"\s*\[{re.escape(name)}\].*?\[/{re.escape(name)}\]\s*"
    base = re.sub(pattern, " ", str(prompt or ""), flags=re.I | re.S).strip()
    return _ground_render_prompt(f"{base}\n[{name}] {content.strip()} [/{name}]")


def _set_colour_prompt(style: dict, shot_type: str) -> str:
    palette = str(style.get("palette") or "")
    product_colours = ", ".join(style.get("product_colours") or []) or "the exact colours visible in the reference"
    if shot_type == "white_main":
        application = (
            "Amazon main-image exception: use a pure #FFFFFF seamless background with neutral light and a natural soft shadow. "
            "Do not tint the white background or recolour the product."
        )
    else:
        application = (
            "Use these same colours naturally across the background, supporting surface, restrained props, ambient grade and integrated typography. "
            "Not every colour must appear in every frame; preserve the same white balance and visual family without making the set look templated."
        )
    return (
        f"One locked colour system for the entire image set: {palette}. Lighting: {style.get('lighting')}. "
        f"Material direction: {style.get('materials')}. Product colours are immutable ({product_colours}) and are not replaced by the set palette. "
        f"{application}"
    )


def _infer_layout_blueprint(item: dict, index: int, shot_type: str) -> str:
    explicit = str(item.get("layout_blueprint") or "").strip()
    if explicit in _LAYOUT_BLUEPRINTS:
        return explicit
    facts = " ".join(str(item.get(key) or "") for key in (
        "headline", "supporting_text", "proof", "selling_point", "buyer_question", "evidence", "scene",
    )).lower()
    if shot_type in {"white_main", "in_box"}:
        return "white_bundle"
    if re.search(r"\b(wi[ -]?fi|bluetooth|app control|remote app)\b", facts) and not re.search(r"\b(no app|no wi[ -]?fi)\b", facts):
        return "connectivity_diagram"
    if re.search(r"\b(night vision|low[- ]?glow|infrared|\d+\s*nm|day (?:or|and) night)\b", facts):
        return "day_night_split"
    if re.search(r"\b(0\.\d+\s*s|trigger speed|burst|fast[- ]?moving|response time)\b", facts):
        return "speed_comparison"
    if re.search(r"\b(ip\d{2}|waterproof|weatherproof|rain|snow|dust|mud|temperature)\b", facts):
        return "environmental_proof"
    if re.search(r"\b(\d+\s*°(?!\s*[fc])|\d+\s*degree|detection angle|pir|field of view|coverage)\b", facts):
        return "coverage_diagram"
    if re.search(r"\b(\d+\s*(?:mp|k)|photo|video|resolution|image quality|detail)\b", facts):
        return "media_proof_split"
    if re.search(r"\b(use cases?|scenarios?|wildlife|hunting|farm|camping|home security|garden|monitoring)\b", facts):
        return "use_case_mosaic"
    return {
        "hero_feature": "media_proof_split", "comparison": "speed_comparison",
        "specs": "coverage_diagram", "lifestyle": "use_case_mosaic",
        "detail": "environmental_proof", "trust": "environmental_proof",
    }.get(shot_type, _DEFAULT_BLUEPRINT_ORDER[min(index, len(_DEFAULT_BLUEPRINT_ORDER) - 1)])


# ─── 产品视觉画像 ─────────────────────────────────────────────────────────────

def _fallback_product_visual_profile(product_context: str) -> dict:
    """Build a category-aware visual identity when the vision call is unavailable.

    The profile describes how the physical product behaves in an image.  It is
    deliberately not a gallery template: a soft towel, an occupied tent and a
    rigid camera require different scale cues, contact physics and useful shots.
    """
    text = str(product_context or "").lower()
    if re.search(r"\b(towel|bath towel|hand towel|washcloth|microfiber cloth)\b|毛巾|浴巾", text):
        return {
            "category_family": "towel / soft home textile",
            "object_behavior": "soft_goods",
            "form_and_scale": "Flexible rectangular textile shown folded, draped or naturally handled; thickness and edge finish must stay credible.",
            "materials_and_finish": ["visible weave or pile", "soft compressible volume", "real stitched edges"],
            "product_colours": ["preserve the exact textile colour from the reference"],
            "supporting_palette": ["#F4F0E8", "#D8C7B5", "#8A6F56", "#4E5B4B", "#282622"],
            "fidelity_anchors": ["exact colour", "weave or pile character", "border and stitching", "set quantity", "true proportions"],
            "natural_interactions": ["folding", "draping", "drying", "gentle hand contact", "stacked storage"],
            "scene_families": ["quiet bathroom", "linen shelf", "spa-like but lived-in home", "pool or travel bag when supported"],
            "visual_opportunities": ["tactile macro", "layered folds", "absorbency context without fake test data", "colour-coordinated stack", "human scale cue"],
            "avoid": ["rigid floating slab", "impossible folds", "plastic fibres", "invented embroidery", "luxury marble cliché"],
        }
    if re.search(r"\b(tent|camping tent|backpacking tent|canopy|shelter)\b|帐篷|天幕", text):
        return {
            "category_family": "tent / spatial outdoor gear",
            "object_behavior": "spatial_gear",
            "form_and_scale": "Large occupiable shelter whose panel geometry, poles, doors, windows, guy lines and footprint define product identity.",
            "materials_and_finish": ["tensioned technical fabric", "credible seams", "real poles and stakes", "ground contact"],
            "product_colours": ["preserve every fabric and pole colour block from the reference"],
            "supporting_palette": ["#E9E3D6", "#A7AD8C", "#667151", "#B97645", "#252A23"],
            "fidelity_anchors": ["exact silhouette", "panel and door count", "pole architecture", "window placement", "colour blocking", "capacity and packed items only when supported"],
            "natural_interactions": ["pitching", "entering", "resting inside", "ventilating", "packing"],
            "scene_families": ["real campsite", "forest clearing", "open grassland", "car-camping pitch", "interior sleeping setup"],
            "visual_opportunities": ["environmental hero", "human scale", "interior spatial view", "setup sequence", "weather readiness", "packed-versus-pitched story"],
            "avoid": ["changing the tent architecture", "impossible interior volume", "missing guy lines", "floating shelter", "extreme fantasy landscape"],
        }
    if re.search(r"\b(camera|trail cam|action camera|security camera)\b|相机|摄像机|监控", text):
        return {
            "category_family": "camera / compact rigid device",
            "object_behavior": "rigid_device",
            "form_and_scale": "Compact precision device; controls, lenses, screens, ports and mounting orientation are identity-critical.",
            "materials_and_finish": ["real glass optics", "controlled matte surfaces", "precise seams", "credible screen reflections"],
            "product_colours": ["preserve the exact body, lens, control and logo colours from the reference"],
            "supporting_palette": ["#EEF1F3", "#C8D0D6", "#657581", "#6E8D72", "#22292E"],
            "fidelity_anchors": ["lens count and position", "body silhouette", "buttons and ports", "screen and logo placement", "mounting hardware", "included quantity"],
            "natural_interactions": ["mounting", "handheld operation", "field use", "screen review", "packing"],
            "scene_families": ["category-appropriate field location", "restrained technical studio", "real use environment", "gear preparation surface"],
            "visual_opportunities": ["precision hero", "operational close-up", "credible use scale", "captured-result context", "day/night context when supported"],
            "avoid": ["extra lenses", "invented ports", "fake app UI", "oversized device", "neon technology effects"],
        }
    return {
        "category_family": "general consumer product",
        "object_behavior": "category_specific",
        "form_and_scale": "Infer the real product's rigidity, scale, contact points and normal orientation from the white-background source.",
        "materials_and_finish": ["physically accurate material", "credible surface response", "real construction details"],
        "product_colours": ["preserve every exact product colour from the reference"],
        "supporting_palette": ["#F2EFE9", "#D7D0C5", "#8A7967", "#66736B", "#292A28"],
        "fidelity_anchors": ["silhouette", "proportions", "colour", "material", "visible controls or construction", "included quantity"],
        "natural_interactions": ["normal handling", "primary real-world use", "storage or setup"],
        "scene_families": ["real home, workplace or outdoor setting appropriate to the category", "restrained studio"],
        "visual_opportunities": ["material detail", "human scale", "primary use", "benefit-led hero", "configuration or storage"],
        "avoid": ["generic pedestal ad", "impossible physics", "invented features", "decorative AI effects", "unrelated luxury props"],
    }


def _normalise_product_visual_profile(value: dict, fallback: dict) -> dict:
    if not isinstance(value, dict):
        return fallback
    result = dict(fallback)
    for key in ("category_family", "object_behavior", "form_and_scale"):
        cleaned = _clean_text(value.get(key))
        if cleaned:
            result[key] = cleaned[:500]
    for key in (
        "materials_and_finish", "product_colours", "supporting_palette",
        "fidelity_anchors", "natural_interactions", "scene_families", "visual_opportunities", "avoid",
    ):
        items = value.get(key)
        if isinstance(items, list):
            cleaned = [_clean_text(item)[:220] for item in items if _clean_text(item)]
            if cleaned:
                result[key] = cleaned[:10]
    return result


async def _analyze_product_visual_identity(
    scrape_data: dict, product_context: str, white_source: str,
) -> dict:
    """Stage 1 of visual planning: understand this product before designing shots."""
    fallback = _fallback_product_visual_profile(product_context)
    if not has_vision():
        return fallback

    candidates: list[str] = []
    for value in [white_source, *_reference_images(scrape_data)[:4]]:
        value = str(value or "").strip()
        if value and value not in candidates:
            candidates.append(value)
    images: list[str] = []
    # User uploads are deliberate product truth and take priority even when the
    # background is not pure white. Feed them to visual identity analysis before
    # scraped gallery images.
    for path_str in (scrape_data.get("uploaded_images") or [])[:2]:
        data_uri = _img_datauri_from_path(str(path_str))
        if data_uri and data_uri not in images:
            images.append(data_uri)
    for value in candidates[:4]:
        data_uri: Optional[str] = None
        if value.startswith("data:"):
            data_uri = value
        elif value.startswith("/api/listing/images/"):
            rel = value.split("/api/listing/images/", 1)[1].split("?", 1)[0]
            parts = [part for part in rel.split("/") if part and part not in {".", ".."}]
            if len(parts) >= 2:
                data_uri = _img_datauri_from_path(str(IMAGES_DIR / parts[0] / parts[-1]))
        else:
            data_uri = await _img_datauri_from_url(value)
        if data_uri and data_uri not in images:
            images.append(data_uri)
    if not images:
        return fallback

    prompt = f"""You are stage 1 of an ecommerce visual-director pipeline. Analyze the PHYSICAL PRODUCT before any gallery is designed.
Image 1 is the white-background product truth when available. Other images are evidence of use and features only.

PRODUCT FACTS:
{product_context[:9000]}

Return JSON only:
{{"category_family":"specific product family","object_behavior":"soft_goods|rigid_device|spatial_gear|wearable|furniture|consumable|other",
"form_and_scale":"physical form, orientation, flexibility and real scale behaviour",
"materials_and_finish":["visible material/finish"],
"product_colours":["exact product colours and colour blocking visible in the references"],
"supporting_palette":["five product-compatible #RRGGBB colours for background, surface, supporting tone, accent and deep neutral"],
"fidelity_anchors":["details that must remain exactly unchanged"],
"natural_interactions":["physically normal ways people/environment contact the product"],
"scene_families":["real settings that reveal value"],
"visual_opportunities":["category-specific photographic ideas, not fixed layouts"],
"avoid":["category-specific visual mistakes and AI failure modes"]}}

Be concrete. A towel must be treated as flexible textile, a tent as occupiable architecture, and a camera as a rigid precision device.
Do not design image slots, do not copy the collected gallery's composition, and do not infer unsupported specifications."""
    try:
        parsed = _strip_json(await _collect_vision(prompt, images)) or {}
    except Exception:
        parsed = {}
    return _normalise_product_visual_profile(parsed, fallback)


# ─── 策略质检 ─────────────────────────────────────────────────────────────────

def _creative_plan_quality(images: list[dict], deliverable: str) -> dict:
    """Deterministic strategy QA.  This intentionally does not claim the rendered
    pixels are commercially safe; product fidelity remains a human delivery gate."""
    issues: list[dict] = []

    def add(code: str, message: str, severity: str = "warning") -> None:
        issues.append({"code": code, "message": message, "severity": severity})

    if not images:
        add("empty", "方案中没有可生成的分镜", "error")
    if deliverable == "gallery" and images:
        main = images[0]
        if main.get("shot_type") != "white_main" or main.get("text_on_image"):
            add("main_compliance", "首图必须是纯白底、无文字主图", "error")
        if not 5 <= len(images) <= 8:
            add("gallery_count", "商品套图建议保留 5–8 张", "warning")
    seen_points: set[str] = set()
    seen_concepts: set[str] = set()
    seen_cameras: set[str] = set()
    for idx, image in enumerate(images):
        point = str(image.get("selling_point") or "").strip().lower()
        if point and point in seen_points:
            add("duplicate_story", f"第 {idx + 1} 张与其他分镜重复表达同一卖点")
        seen_points.add(point)
        if image.get("asset_mode") == "generate":
            concept = re.sub(r"\s+", " ", str(image.get("visual_concept") or "").strip().lower())
            camera = re.sub(r"\s+", " ", str(image.get("camera_direction") or "").strip().lower())
            treatment = str(image.get("product_treatment") or "").strip()
            if not concept or not camera or not treatment:
                add("missing_art_direction", f"第 {idx + 1} 张缺少独立视觉概念、镜头或产品物理处理说明", "error")
            if concept and concept in seen_concepts:
                add("duplicate_visual_concept", f"第 {idx + 1} 张重复使用同一视觉概念", "error")
            if camera and camera in seen_cameras:
                add("duplicate_camera_direction", f"第 {idx + 1} 张重复使用同一镜头构图", "error")
            seen_concepts.add(concept)
            seen_cameras.add(camera)
        if _HYPE_PROMPT_RE.search(str(image.get("render_prompt") or "")):
            add("ai_aesthetic", f"第 {idx + 1} 张仍包含容易产生 AI 感的夸张场景词", "error")
        if len(str(image.get("headline") or "")) > 48:
            add("headline_length", f"第 {idx + 1} 张标题偏长，手机端可读性较差")
        for field in ("headline", "eyebrow", "supporting_text", "proof", "callout"):
            if _INTERNAL_PUBLIC_COPY_RE.search(str(image.get(field) or "")):
                add("internal_copy", f"第 {idx + 1} 张把内部审核说明写进了消费者文案", "error")
                break
        public_copy = [
            str(image.get(field) or "").strip()
            for field in ("eyebrow", "headline", "callout", "supporting_text", "proof")
            if str(image.get(field) or "").strip()
        ]
        if image.get("text_on_image"):
            prompt = str(image.get("render_prompt") or "")
            if not public_copy:
                add("missing_artwork_copy", f"第 {idx + 1} 张启用了图上文字但没有可生成的公开文案", "error")
            elif "[FINAL ARTWORK COPY]" not in prompt or any(value not in prompt for value in public_copy):
                add("copy_not_compiled", f"第 {idx + 1} 张公开文案尚未完整编译进最终生图提示词", "error")
        if image.get("proof") and not _public_proof(image.get("proof")):
            add("invalid_public_proof", f"第 {idx + 1} 张的证明数字不是简短、可公开的事实", "error")
        expected_size = "1464x600" if deliverable == "aplus" else "1600x1600"
        if image.get("size") != expected_size:
            add("canvas_mismatch", f"第 {idx + 1} 张画布必须统一为 {expected_size}", "error")
        if image.get("asset_mode") != "generate":
            add("direct_generation_required", f"第 {idx + 1} 张未使用统一的模型直出策略", "error")
        if not image.get("product_source_url"):
            add("product_pending", f"第 {idx + 1} 张需要上传或采集的产品真值图，禁止无参考生成", "error")
        if image.get("requires_source"):
            add("missing_evidence", f"第 {idx + 1} 张依赖未提供的真实证据，应换成有事实支撑的直出画面", "error")
        if idx and not image.get("evidence"):
            add("missing_claim_source", f"第 {idx + 1} 张缺少卖点依据")
        if image.get("final_url"):
            render_qa = image.get("render_qa") if isinstance(image.get("render_qa"), dict) else {}
            if not render_qa:
                add("render_unreviewed", f"第 {idx + 1} 张尚未通过成图质检", "error")
            elif render_qa.get("ready") is not True:
                add("render_failed", f"第 {idx + 1} 张成图质检未通过", "error")
    error_count = sum(i["severity"] == "error" for i in issues)
    score = max(0, 100 - error_count * 22 - (len(issues) - error_count) * 6)
    return {
        "score": score,
        "ready": not error_count and bool(images),
        "issues": issues,
        "note": "策略、公开文案、画布和已生成图片的质检结果；生成图还需通过产品一致性硬门槛并由人工终审。",
    }


# ─── 计划规范化 ───────────────────────────────────────────────────────────────

def _normalize_shot_plan(plan: dict, target_count: int, deliverable: str = "gallery") -> dict:
    """Clamp/repair an LLM visual plan into the shape used by the studio."""
    deliverable = "aplus" if deliverable == "aplus" else "gallery"
    plan_style = plan.get("style") if isinstance(plan.get("style"), dict) else {}
    product_profile = plan.get("product_profile") if isinstance(plan.get("product_profile"), dict) else {}
    if not product_profile and _clean_text(plan.get("product_lock")):
        product_profile = _fallback_product_visual_profile(_clean_text(plan.get("product_lock")))
    profile_anchors = [
        _clean_text(value) for value in (product_profile.get("fidelity_anchors") or [])
        if _clean_text(value)
    ][:8]
    profile_opportunities = [
        _clean_text(value) for value in (product_profile.get("visual_opportunities") or []) if _clean_text(value)
    ]
    profile_interactions = [
        _clean_text(value) for value in (product_profile.get("natural_interactions") or []) if _clean_text(value)
    ]
    default_cameras = [
        "eye-level three-quarter hero with accurate scale",
        "close three-quarter feature view with selective depth of field",
        "honest human-scale use view with natural contact",
        "macro detail connected to the complete product context",
        "slightly elevated comparison view with clear spatial hierarchy",
        "orthographic configuration view with realistic perspective",
        "wide environmental view with deliberate negative space",
        "alternate-side trust close with restrained depth",
    ]
    plan_style = _normalise_set_style(plan_style, product_profile)
    creative_brief = _clean_text(plan.get("creative_brief"))
    artwork_language = _clean_text(plan.get("language")) or "en"
    raw = plan.get("images") if isinstance(plan, dict) else None
    accent_candidates = [
        str(item.get("accent_color")) for item in (raw or [])
        if isinstance(item, dict) and str(item.get("accent_color") or "").strip()
    ]
    set_accent_raw = str(plan_style.get("accent_color") or (
        max(set(accent_candidates), key=accent_candidates.count) if accent_candidates else "#4F8CFF"
    ))
    clean: list[dict] = []
    for i, it in enumerate(raw or []):
        if not isinstance(it, dict):
            continue
        rp = _ground_render_prompt(str(it.get("render_prompt") or ""))
        if not rp:
            continue
        callout = _public_text(it.get("callout"), 90)
        headline = _public_text(it.get("headline"), 48)
        supporting_text = _public_text(it.get("supporting_text"), 90)
        eyebrow = _public_text(it.get("eyebrow"), 24)
        proof = _public_proof(it.get("proof"))
        stype = str(it.get("shot_type") or "").strip().lower()
        stype = _LEGACY_SHOT_TYPE.get(stype, stype)
        if stype not in _SHOT_TYPES:
            order = _APLUS_TYPE_ORDER if deliverable == "aplus" else _DEFAULT_TYPE_ORDER
            stype = order[i] if i < len(order) else "hero_feature"
        # Direct-generation policy: every card is built around the verified
        # product reference. Result-only fantasy scenes are no longer planned.
        show_product = True
        text_zone = str(it.get("text_zone") or it.get("text_pos") or "top-left")
        if text_zone not in _TEXT_ZONES:
            text_zone = "top-left"
        layout_style = str(it.get("layout_style") or "editorial")
        if layout_style not in _LAYOUT_STYLES:
            layout_style = "editorial"
        roles = _APLUS_ROLES if deliverable == "aplus" else _DEFAULT_ROLES
        role = str(it.get("role") or roles[min(i, len(roles) - 1)])
        if deliverable == "gallery" and i == 0:
            role = "主图"
        text_on_image = bool(it.get(
            "text_on_image", bool(callout or headline or supporting_text or eyebrow or proof),
        )) and not (deliverable == "gallery" and i == 0)
        opportunity = profile_opportunities[i % len(profile_opportunities)] if profile_opportunities else f"product-specific {stype}"
        interaction = profile_interactions[i % len(profile_interactions)] if profile_interactions else "natural real-world use"
        visual_concept = _clean_text(it.get("visual_concept")) or f"{opportunity} for {role}"
        camera_direction = _clean_text(it.get("camera_direction")) or default_cameras[i % len(default_cameras)]
        product_treatment = _clean_text(it.get("product_treatment")) or (
            f"{_clean_text(product_profile.get('form_and_scale')) or 'accurate real-world scale and orientation'}; {interaction}"
        )
        asset_mode = "generate"
        anchor_text = ", ".join(profile_anchors) or "silhouette, proportions, colour, material, visible construction, markings and included quantity"
        behaviour = _clean_text(product_profile.get("object_behavior")) or "category-specific physical behaviour"
        treatment = product_treatment
        product_lock = _clean_text(plan.get("product_lock"))
        rp = _replace_prompt_section(
            rp,
            "PRODUCT IDENTITY LOCK",
            f"REFERENCE IMAGE 1 is the only immutable product truth. {product_lock + '. ' if product_lock else ''}"
            f"Preserve exactly: {anchor_text}. Physical behaviour: {behaviour}. Product treatment: "
            f"{treatment or 'natural real-world orientation, scale and contact'}. Change only the environment, camera, "
            "composition, lighting, supporting design and explicitly requested artwork copy. Do not redesign, recolour, "
            "relabel, simplify, crop away, add or remove any product part, "
            "opening, control, accessory or unit. Preserve existing logos, labels and printed product markings exactly where visible.",
        )
        layout_direction = (
            f"Build a deliberate {layout_style} hierarchy with the primary copy group in the {text_zone} area and keep "
            "that area visually calm enough for immediate reading."
            if text_on_image else
            "Use the full canvas for a clean product-led composition with no reserved caption or empty text plate."
        )
        rp = _replace_prompt_section(
            rp,
            "SHOT DESIGN",
            f"Role: {role}; shot type: {stype}; product-specific visual concept: {visual_concept}. "
            f"Camera and composition: {camera_direction}. Scene: {_clean_text(it.get('scene')) or opportunity}. "
            f"Physical product interaction: {product_treatment}. {layout_direction}",
        )
        rp = _replace_prompt_section(rp, "SET COLOR SYSTEM", _set_colour_prompt(plan_style, stype))
        rp = _replace_prompt_section(
            rp,
            "USER CREATIVE DIRECTION",
            (
                f"Highest-priority creative requirement after product identity, factual accuracy and marketplace rules: "
                f"{creative_brief}. Follow it for audience, mood, scene, emphasis, exclusions and design character. "
                if creative_brief else
                "No additional manual creative requirement was supplied; follow the product-specific set direction. "
            ) + f"The requested language for added artwork copy is {artwork_language}.",
        )
        if text_on_image:
            rp = _remove_legacy_textless_directions(rp)
            exact_copy = {
                key: value for key, value in (
                    ("eyebrow", eyebrow), ("headline", headline), ("callout", callout),
                    ("supporting_text", supporting_text), ("proof", proof),
                ) if value
            }
            copy_contract = json.dumps(exact_copy, ensure_ascii=False)
            rp = _replace_prompt_section(
                rp,
                "FINAL ARTWORK COPY",
                f"This is final pixel artwork, not a blank background. Render every string in this JSON exactly once and "
                f"character-for-character: {copy_contract}. Do not translate, paraphrase, abbreviate, add, omit or repeat any "
                f"character. Use {plan_style.get('type_system')} with clean commercial kerning and a clear hierarchy: eyebrow "
                f"small, headline dominant, supporting text secondary, proof prominent only when present. Place the complete "
                f"copy group in the {text_zone} zone using the {layout_style} layout language. Keep all type inside an 8% safe "
                "margin, high contrast, unobstructed, correctly spelled and readable at mobile thumbnail size. Integrate the "
                "typography into the composition as intentional final design, never as a pasted caption or placeholder.",
            )
        else:
            rp = _replace_prompt_section(
                rp,
                "FINAL ARTWORK COPY",
                "This artwork intentionally contains no added marketing copy. Do not render headlines, captions, letters, "
                "numbers, badges, icons, diagrams, app UI or watermarks.",
            )
        rp = _replace_prompt_section(
            rp,
            "OUTPUT SAFETY",
            "Do not invent additional copy, claims, certifications, logos, labels, icons, badges, diagrams, app UI or "
            "watermarks. The exact public copy in FINAL ARTWORK COPY is the only added text allowed. Product labels and "
            "markings already visible in the reference are part of the immutable product and must remain unchanged.",
        )
        background_prompt = ""
        expected_size = "1464x600" if deliverable == "aplus" else "1600x1600"
        layout_blueprint = ""
        panel_prompts: list[str] = []
        graphic_labels = [
            _public_text(value, 34) for value in (it.get("graphic_labels") or [])
            if _public_text(value, 34)
        ][:6]
        if not graphic_labels:
            graphic_labels = [value for value in (
                proof,
                _public_text(supporting_text, 34),
            ) if value][:6]
        accent_color = set_accent_raw
        fact_text = " ".join(str(it.get(key) or "") for key in ("scene", "headline", "evidence", "selling_point")).lower()
        if accent_color.upper() == "#4F8CFF" and re.search(r"\b(outdoor|forest|wildlife|hunting|garden|farm|nature)\b", fact_text):
            accent_color = "#67C95B"
        accent_color = _readable_accent(accent_color)
        versions = [v for v in (it.get("versions") or []) if isinstance(v, dict)][-8:]
        base_url = str(it.get("base_url") or "")
        final_url = str(it.get("final_url") or "")
        render_qa = it.get("render_qa") if isinstance(it.get("render_qa"), dict) else None
        human_reviewed = bool(it.get("human_reviewed", False)) and bool((render_qa or {}).get("ready"))
        clean.append({
            "slot": str(it.get("slot") or (("main" if i == 0 else f"sub{len(clean)}") if deliverable == "gallery" else f"aplus_{len(clean) + 1}")),
            "role": role,
            "shot_type": stype,
            "show_product": show_product,
            "angle": str(it.get("angle") or ""),
            "scene": str(it.get("scene") or ""),
            "selling_point": (str(it.get("selling_point")).strip() or None) if it.get("selling_point") else None,
            "buyer_question": str(it.get("buyer_question") or ""),
            "evidence": str(it.get("evidence") or ""),
            "headline": headline,
            "callout": callout,
            "supporting_text": supporting_text,
            "eyebrow": eyebrow,
            "proof": proof,
            "text_on_image": text_on_image,
            "text_pos": text_zone,  # legacy consumer alias
            "text_zone": text_zone,
            "layout_style": layout_style,
            "layout_blueprint": layout_blueprint,
            "panel_prompts": panel_prompts,
            "graphic_labels": graphic_labels,
            "theme": str(it.get("theme") or "auto"),
            "accent_color": accent_color,
            "composition": str(it.get("composition") or ""),
            "visual_concept": visual_concept,
            "camera_direction": camera_direction,
            "product_treatment": product_treatment,
            "asset_mode": asset_mode,
            "manual_template": False,
            "requires_source": False,
            "source_requirement": "使用上传图优先的产品真值参考；仅允许改变场景、镜头、构图、光线、辅助设计和指定图上文案",
            "source_url": "",
            "product_source_url": str(it.get("product_source_url") or ""),
            "template_url": "",
            "template_index": 0,
            "template_analysis": None,
            "background_prompt": background_prompt,
            "product_scale": _clamped_float(it.get("product_scale"), .52, .24, .72),
            "acceptance_criteria": [str(v) for v in (it.get("acceptance_criteria") or []) if str(v).strip()][:6],
            "size": expected_size,
            "render_prompt": rp,
            "base_url": base_url,
            "final_url": final_url,
            "versions": versions,
            "render_qa": render_qa,
            "auto_retry_count": 1 if it.get("auto_retry_count") else 0,
            "last_retry_guidance": [
                str(value) for value in (it.get("last_retry_guidance") or []) if str(value).strip()
            ][:6],
            "human_reviewed": human_reviewed,
        })
    if clean and deliverable == "gallery":  # 第一张永远是纯白底无字主图
        clean[0].update(slot="main", role="主图", shot_type="white_main", show_product=True,
                        text_on_image=False, callout=None, headline=None, supporting_text=None,
                        eyebrow=None, proof=None, text_zone="top-left", text_pos="top-left",
                        layout_style="minimal", layout_blueprint="",
                        panel_prompts=[], graphic_labels=[], requires_source=False, asset_mode="generate",
                        source_requirement="以上传或采集主图为不可变产品真值，模型直接生成合规纯白底主图")
    clean = clean[:target_count] if target_count and target_count > 0 else clean[:8]
    normalized = {
        "deliverable": deliverable,
        "planning_mode": "adaptive_direct_text",
        "style": plan_style,
        "product_profile": product_profile,
        "product_lock": str(plan.get("product_lock") or "").strip(),
        "story": str(plan.get("story") or "").strip(),
        "creative_brief": creative_brief,
        "language": artwork_language,
        "template_mode": False,
        "product_source_url": str(plan.get("product_source_url") or ""),
        "template_images": [],
        "template_story": [],
        "images": clean,
        "set_qa": plan.get("set_qa") if isinstance(plan.get("set_qa"), dict) else None,
    }
    if normalized["style"] is not None:
        normalized["style"]["accent_color"] = clean[0]["accent_color"] if clean else _readable_accent(set_accent_raw)
    normalized["quality"] = _creative_plan_quality(clean, deliverable)
    return normalized


def _bind_reference_templates(plan: dict, project_id: str, scrape_data: dict,
                              deliverable: str) -> dict:
    """Bind one uploaded-first product truth to every directly generated card."""
    product_source = _cached_white_product_source(scrape_data)
    images = plan.get("images") if isinstance(plan.get("images"), list) else []
    plan["product_source_url"] = product_source
    plan["template_images"] = []
    plan["template_story"] = []
    plan["template_mode"] = False

    for image in images:
        if not isinstance(image, dict):
            continue
        previous_product = str(image.get("product_source_url") or "")

        def invalidate_render() -> None:
            if image.get("final_url"):
                history = list(image.get("versions") or [])
                history.append({
                    "url": image.get("final_url"), "base_url": image.get("base_url") or "",
                    "render_qa": image.get("render_qa"), "created_at": "invalidated-by-source-migration",
                })
                image["versions"] = history[-8:]
            image["base_url"] = ""
            image["final_url"] = ""
            image["render_qa"] = None
            image["human_reviewed"] = False

        # One production path only: whole-image generation from the immutable
        # product truth. Existing renders survive a strategy migration; they are
        # invalidated only when an already-bound truth source actually changes.
        image["asset_mode"] = "generate"
        image["show_product"] = True
        image["requires_source"] = False
        image["source_url"] = ""
        image["source_requirement"] = "以上传图优先的产品真值为高保真参考；仅改变场景、镜头、构图、光线、辅助设计和指定图上文案"
        image["product_source_url"] = product_source
        image["template_index"] = 0
        image["template_url"] = ""
        image["template_analysis"] = None
        image["layout_blueprint"] = ""
        image["panel_prompts"] = []
        image["manual_template"] = False
        if image.get("final_url") and previous_product and previous_product != product_source:
            invalidate_render()

    plan["quality"] = _creative_plan_quality(images, deliverable)
    return plan


# ─── 兜底方案（AI 不可用时依然给出可编辑整套）─────────────────────────────────

def _slot_purpose(slot_id: str, label: str) -> str:
    key = slot_id.lower()
    if key == "main":
        return "pure white Amazon main image, product centered, no text, shopper can inspect the full product"
    if key.startswith("sub1"):
        return "lifestyle scene showing the primary use case and buyer outcome"
    if key.startswith("sub2"):
        return "feature detail image with a clean reserved area for later benefit copy"
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
    text_rule = "no words, letters, numbers, badges, icons, UI overlays or watermarks"
    return (
        f"{product_lock} Reference: {ref}. Create a {purpose} for slot \"{label or slot_id}\". "
        f"Target canvas: {canvas}; compose specifically for this size and orientation. "
        f"Image goal: communicate {feature[:220]}. "
        f"Use commercial Amazon product photography with accurate product rendering, controlled studio lighting, natural shadows, sharp focus, realistic materials, and clean premium composition.{color_line} "
        f"Composition: product remains visually dominant, with deliberate low-detail negative space for later typography; render {text_rule}. "
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
        "warning": "AI 当前不可用，已用本地规则生成可编辑图片提示词；恢复后可重新智能生成。",
    }


def _color_directive(color_scheme: str, analysis_data: dict) -> str:
    """Color instruction shared by all prompt builders.

    - explicit scheme  → lock to it across every slot
    - empty / 'auto'   → reuse a palette already locked on the project, else
                         tell the model to pick ONE palette and emit exact hex codes
    Keeping the palette identical across slots (and across single-slot
    regeneration) is what stops the color drift between generated images.
    """
    cs = (color_scheme or "").strip()
    saved = str((analysis_data or {}).get("palette") or (analysis_data or {}).get("visual_style") or "").strip()
    if cs and cs.lower() != "auto":
        return (f"- MANDATORY COLOR PALETTE: Use '{cs}' as the dominant palette for EVERY image — same "
                f"backgrounds, props, lighting and color grading. Express it as 4-6 explicit HEX codes in "
                f"visual_style and reuse those exact codes in every prompt.")
    if saved:
        return (f"- MANDATORY COLOR PALETTE (locked for consistency): {saved}\n  Reuse these EXACT colors in "
                f"every prompt. Do not introduce a new dominant color.")
    return ("- COLOR PALETTE: Choose ONE cohesive palette for the whole set, express it as 4-6 explicit HEX "
            "codes inside visual_style, and apply that SAME hex palette to EVERY image so the set looks unified.")


def _persist_visual_anchor(project_id: str, row, result: dict) -> None:
    """Save product_lock / visual_style / palette onto the project's analysis_data
    so later single-slot regenerations reuse the same product description and colors."""
    if not isinstance(result, dict):
        return
    lock = str(result.get("product_lock") or "").strip()
    style = str(result.get("visual_style") or "").strip()
    if not lock and not style:
        return
    try:
        conn = _db()
        cur = conn.execute("SELECT analysis_data FROM listing_projects WHERE id = ?", (project_id,)).fetchone()
        existing = json.loads(cur["analysis_data"]) if cur and cur["analysis_data"] else {}
        if lock:
            existing["product_lock"] = lock
        if style:
            existing["visual_style"] = style
            existing["palette"] = style
        conn.execute(
            "UPDATE listing_projects SET analysis_data = ?, updated_at = ? WHERE id = ?",
            (json.dumps(existing, ensure_ascii=False), time.time(), project_id),
        )
        conn.commit()
        conn.close()
    except Exception:
        pass


def _auto_product_source(project_id: str, scrape_data: dict) -> str:
    """Choose the one source that passed white-background verification.

    Uploaded files are not automatically trusted: a lifestyle or infographic
    upload is useful evidence but is not the clean product identity anchor this
    workflow requires. upload_product_image stores a passing upload as the
    selected white_product_source, so deliberate verified uploads still win.
    """
    return _cached_white_product_source(scrape_data)


def _shot_plan_fallback(row, scrape_data: dict, analysis_data: dict, target_count: int,
                        color_scheme: str, deliverable: str = "gallery",
                        product_profile: Optional[dict] = None) -> dict:
    """LLM JSON unparsable → build a usable structured plan from the deterministic
    slot helpers so the user still gets a set (never a hard error)."""
    deliverable = "aplus" if deliverable == "aplus" else "gallery"
    n = target_count if target_count and target_count > 0 else (5 if deliverable == "aplus" else 7)
    slot_ids = (["main"] + [f"sub{i}" for i in range(1, n)] if deliverable == "gallery"
                else [f"aplus_{i + 1}" for i in range(n)])
    fallback_size = "1464x600" if deliverable == "aplus" else "1600x1600"
    details = [{"id": s, "label": s, "size": fallback_size} for s in slot_ids]
    try:
        prompts = _fallback_prompts_for_slots(row, scrape_data, analysis_data, details, color_scheme=color_scheme)["prompts"]
    except Exception:
        prompts = {}
    bullets = [ln[2:] for ln in _approved_copy(row).splitlines() if ln.startswith("- ")][:n]
    profile = product_profile if isinstance(product_profile, dict) and product_profile else _fallback_product_visual_profile(
        _build_product_context(row, scrape_data, analysis_data)
    )
    opportunities = [str(value) for value in (profile.get("visual_opportunities") or []) if str(value).strip()]
    scenes = [str(value) for value in (profile.get("scene_families") or []) if str(value).strip()]
    interactions = [str(value) for value in (profile.get("natural_interactions") or []) if str(value).strip()]
    anchors = [str(value) for value in (profile.get("fidelity_anchors") or []) if str(value).strip()]
    avoid = [str(value) for value in (profile.get("avoid") or []) if str(value).strip()]
    camera_directions = [
        "eye-level environmental hero with a clear foreground-to-background path",
        "close tactile three-quarter view with selective depth of field",
        "honest human-scale use view with natural contact and posture",
        "overhead or orthographic configuration view only when physically useful",
        "quiet editorial wide shot with asymmetrical negative space",
        "macro construction detail anchored to the complete product context",
        "alternate-side use view that does not repeat the hero angle",
    ]
    imgs = []
    for i, s in enumerate(slot_ids):
        sp = bullets[i - 1] if i > 0 and i - 1 < len(bullets) else None
        order = _APLUS_TYPE_ORDER if deliverable == "aplus" else _DEFAULT_TYPE_ORDER
        stype = order[i] if i < len(order) else "hero_feature"
        has_copy = bool(sp) and (deliverable == "aplus" or i > 0)
        role = (_APLUS_ROLES if deliverable == "aplus" else _DEFAULT_ROLES)[
            min(i, len(_APLUS_ROLES if deliverable == "aplus" else _DEFAULT_ROLES) - 1)
        ]
        headline = " ".join(sp.split()[:6]) if has_copy else None
        callout = " ".join(sp.split()[6:14]) if has_copy and len(sp.split()) > 6 else None
        base_prompt = str(prompts.get(s) or (
            "Realistic ecommerce product photograph in a physically plausible everyday setting, "
            "natural materials, restrained color, soft directional light, accurate scale and contact shadow, "
            "a deliberate commercial layout with clear information hierarchy, no stylized effects or levitating objects."
        ))
        opportunity = opportunities[i % len(opportunities)] if opportunities else "category-specific primary use"
        visual_concept = f"{opportunity} for {role}"
        scene = scenes[i % len(scenes)] if scenes else "a real category-appropriate environment"
        interaction = interactions[i % len(interactions)] if interactions else "normal real-world use"
        camera = camera_directions[i % len(camera_directions)]
        identity = ", ".join(anchors[:6]) or "silhouette, proportions, colour, material and visible construction"
        avoid_text = ", ".join(avoid[:4]) or "invented features, impossible physics and decorative AI effects"
        rp = _ground_render_prompt(
            f"{base_prompt} Product family: {profile.get('category_family') or 'consumer product'}; physical behaviour: "
            f"{profile.get('object_behavior') or 'category-specific'}. Visual concept: {opportunity}. Scene: {scene}. "
            f"Natural interaction: {interaction}. Camera: {camera}. Reproduce the reference product without changing "
            f"{identity}. Avoid {avoid_text}. Leave enough visual calm for an integrated, readable final design."
        )
        imgs.append({
            "slot": s, "role": role,
            "shot_type": stype, "angle": "", "scene": "", "selling_point": sp,
            "buyer_question": "", "evidence": sp or "",
            "headline": headline, "callout": callout, "supporting_text": None,
            "text_on_image": bool(headline or callout), "text_zone": "top-left",
            "layout_style": "editorial", "composition": camera,
            "visual_concept": visual_concept, "camera_direction": camera,
            "product_treatment": f"{profile.get('form_and_scale') or 'Natural real-world scale'}; {interaction}",
            "asset_mode": "generate", "requires_source": False,
            "acceptance_criteria": ["产品外观与参考图一致", "尺度和阴影自然", "手机端文字可读"],
            "size": "1464x600" if deliverable == "aplus" else "1600x1600",
            "render_prompt": rp,
        })
    return _normalize_shot_plan({
        "images": imgs,
        "style": {"palette": color_scheme} if color_scheme else {},
        "product_lock": analysis_data.get("product_lock", ""),
        "product_profile": profile, "planning_mode": "adaptive_direct_text",
    }, n, deliverable)


def _persist_shot_plan(project_id: str, plan: dict, deliverable: str = "gallery") -> None:
    try:
        conn = _db()
        row = conn.execute("SELECT creative_sets FROM listing_projects WHERE id = ?", (project_id,)).fetchone()
        sets = {}
        if row and row["creative_sets"]:
            try:
                sets = json.loads(row["creative_sets"])
            except Exception:
                sets = {}
        deliverable = "aplus" if deliverable == "aplus" else "gallery"
        sets[deliverable] = plan
        if deliverable == "gallery":
            conn.execute(
                "UPDATE listing_projects SET creative_sets=?, shot_plan=?, updated_at=? WHERE id=?",
                (json.dumps(sets, ensure_ascii=False), json.dumps(plan, ensure_ascii=False), time.time(), project_id),
            )
        else:
            conn.execute(
                "UPDATE listing_projects SET creative_sets=?, updated_at=? WHERE id=?",
                (json.dumps(sets, ensure_ascii=False), time.time(), project_id),
            )
        conn.commit()
        conn.close()
    except Exception:
        pass


# ─── 整套策划（后台 job）─────────────────────────────────────────────────────

async def run_plan_image_set(project_id: str, body: PlanImageSetReq,
                             handle: Optional[JobHandle] = None) -> dict:
    """Plan either a gallery or A+ set through the same evidence-led engine."""

    def progress(stage: str, message: str, value: float) -> None:
        if handle:
            handle.update(stage=stage, message=message, progress=value)

    row = project_row(project_id)
    if not row:
        raise HTTPException(404)
    scrape_data = json.loads(row["scrape_data"]) if row["scrape_data"] else {}
    analysis_data = json.loads(row["analysis_data"]) if row["analysis_data"] else {}
    product_context = _build_product_context(row, scrape_data, analysis_data)
    ref_images = scrape_data.get("reference_images", []) or scrape_data.get("imageUrls", [])
    ref_text = "\n".join(ref_images[:3]) if ref_images else "(no reference images)"
    progress("white", "校验白底产品真值…", 0.08)
    try:
        white_source, white_report = await asyncio.wait_for(
            _detect_white_product_source(project_id, scrape_data), timeout=120,
        )
    except Exception:
        white_source, white_report = "", []
    scrape_data["white_product_source"] = white_source
    scrape_data["white_product_source_check"] = {
        "ready": bool(white_source),
        "selected": white_source,
        "candidates": white_report,
    }
    try:
        update_project(project_id, scrape_data=json.dumps(scrape_data, ensure_ascii=False))
    except Exception:
        pass
    progress("identity", "分析产品视觉身份…", 0.25)
    try:
        product_profile = await asyncio.wait_for(
            _analyze_product_visual_identity(scrape_data, product_context, white_source), timeout=150,
        )
    except Exception:
        product_profile = _fallback_product_visual_profile(product_context)
    product_profile_text = json.dumps(product_profile, ensure_ascii=False, indent=2)
    uploaded_count = len(scrape_data.get("uploaded_images", []) or [])
    img_sp = analysis_data.get("image_insights", "")
    approved = _approved_copy(row)
    color_directive = _color_directive(body.color_scheme, analysis_data)
    deliverable = "aplus" if body.deliverable == "aplus" else "gallery"
    max_count = 6 if deliverable == "aplus" else 8
    n = max(0, min(int(body.target_count or 0), max_count))
    count_rule = (
        f"Produce EXACTLY {n} modules." if n else
        ("Produce 4–6 A+ modules." if deliverable == "aplus" else "Choose 5–8 images; default to 7 when the facts support it.")
    )
    deliverable_rules = (
        "A+ modules use a wide 1464x600 canvas. Build one brand story across a banner, primary benefit, "
        "usage/education, detail or comparison, and trust close. Do not create a white Amazon main image."
        if deliverable == "aplus" else
        "The first image is the Amazon white main image. The remaining images form a mobile-first sales story."
    )

    prompt = f"""You are a senior ecommerce creative director planning a commercially usable Amazon {deliverable} set. {count_rule}

This is a production brief, not a prompt-writing showcase. Every decision must be restrained, physically plausible,
supported by product facts, and useful to a shopper. {deliverable_rules}

## PRODUCT INFO
{product_context}

## APPROVED LISTING COPY (the source of truth for exact on-image text)
{approved or "(none — derive concise callouts from the bullets/selling points above)"}

## REFERENCE IMAGES
{ref_text}
The verified white-background image is the only product-identity truth. Other collected images are evidence for visible
features and normal use only. Do not copy their composition, grid, camera angle, background, typography or gallery order.
Design a new art direction from the current product's physical behaviour and buyer decisions.
Uploaded product assets available: {uploaded_count}. Scraped ASIN references available: {len(ref_images)}.

## PRODUCT VISUAL IDENTITY — STAGE 1 ANALYSIS
{product_profile_text}
Treat this profile as a physical design constraint. The category, object behaviour, material response, normal interaction,
scale cues and fidelity anchors must drive every shot. A flexible textile must fold and compress naturally; an occupiable
shelter must have credible footprint and interior scale; a precision device must preserve controls, openings and geometry.
Do not reduce unrelated categories to the same product-on-pedestal composition.

## VISUAL ANALYSIS (selling points / style / scenes from scraped + uploaded images)
{img_sp or "(not available)"}

## STORY AND SHOT TYPES
Use different jobs rather than repeating the product in the same pose:
- white_main: pure #FFFFFF, complete purchased set, product fills 80–90%, no text (gallery image 1 only)
- hero_feature: product in a restrained studio or plausible context, one primary benefit
- lifestyle: product used naturally at correct scale; believable hand/body/environment relationships
- detail: macro or close crop of a real visible material, control, interface, or construction detail
- comparison: only when the supplied facts support a fair comparison; never fabricate a test result
- specs: size, compatibility, capacity, or configuration using supplied facts
- in_box: exact included items, no invented accessories
- trust: care, material, certification, warranty, or brand close only when supported
- aplus_banner: wide brand opening for A+ only

## DYNAMIC ART DIRECTION — STAGE 2
- Invent a distinct visual concept for every image from the product profile and that image's buyer question.
- Vary camera height, lens feel, crop, subject scale, depth, lighting logic and product interaction across the set.
- Composition must follow the product: drape/fold/stack soft goods, show credible occupied scale and ground contact for
  spatial gear, and use precise close views or operational handling for rigid devices.
- Use one coherent brand world across the set without repeating one layout. The set should feel designed, not templated.
- Design the typography and image as one final composition. Use clear type hierarchy, intentional alignment and enough
  visual calm for legibility; avoid generic floating cards unless the requested design specifically needs one.
- The model may integrate the exact reference product into a realistic scene. It may not redesign, relabel or simplify it.

## USER CREATIVE DIRECTION — HIGHEST PRIORITY AFTER FACTS AND PRODUCT IDENTITY
- Tone requested by the user: {body.visual_tone}.
- Manual requirement: {body.brief or "none"}.
- Follow the manual requirement for style, audience, mood, scenes, emphasis and exclusions. It may not override the exact
  product reference, supplied facts, Amazon main-image rules or claim safety.

## ART DIRECTION
- Prefer a real studio, home, workplace, outdoors, or other category-appropriate location with ordinary materials.
- Use believable perspective, product scale, contact shadow, reflection, depth of field, and time-of-day lighting.
- Derive ONE product-specific set palette from the reference product's exact colours, material, category and positioning.
  style.palette must define five concrete #RRGGBB colours with roles: background, surface, supporting tone, brand accent,
  and deep neutral. Reuse that same colour grammar, white balance and lighting family in every image.
- Apply the shared palette naturally to backgrounds, supporting surfaces, restrained props, ambient grade and typography.
  Do not recolour the product and do not force all five colours into every frame. Gallery white_main keeps #FFFFFF.
- Never use neon light trails, sci-fi spaces, holograms, floating glass panels, fantasy panoramas, impossible scene mashups,
  levitating products, fake interfaces, or generic "cinematic luxury" decoration.
- Product appearance, labels, ports, controls, proportions, color, texture, logo, accessories, and quantities must not change.

## COPY AND EVIDENCE
- Each image answers one buyer_question and cites an evidence string from the approved copy/product facts.
- headline is 2–5 words; supporting_text is optional and no longer than 9 words. Do not paste a whole bullet.
- evidence and source_requirement are INTERNAL production notes and must never appear on the artwork.
- proof is optional PUBLIC copy and may only be a short numeric fact such as "8K/30fps", "120MP" or "2 Batteries".
  Never put phrases such as "approved copy supports", "product facts", "image should" or claim-review explanations in proof.
- For every non-main image with text_on_image=true, render_prompt must contain the final exact strings and instruct the
  image model to draw them directly into the final pixels. Text is not added later by code.
- Use the requested artwork language: {body.language}. Keep every public string concise so the image model can spell it reliably.
- If a claim would require a sample, before/after, lab test, certificate, screenshot or measured proof that is not supplied,
  omit that claim and design a different supported product-led image. AI must not generate fake evidence.
- text_zone must be deliberately low-detail negative space: top-left/top-center/top-right/center-left/center-right/
  bottom-left/bottom-center/bottom-right.

## OUTPUT — valid JSON only
{{"deliverable":"{deliverable}",
 "style":{{"direction":"product-specific art direction","palette":"background #RRGGBB; surface #RRGGBB; supporting tone #RRGGBB; brand accent #RRGGBB; deep neutral #RRGGBB","lighting":"one shared lighting family","materials":"category-specific real materials","type_system":"...","accent_color":"#RRGGBB"}},
 "story":"one sentence describing the set's sales narrative",
 "product_lock":"strict appearance description and explicit things that must not change",
 "images":[
   {{"slot":"...","role":"...","shot_type":"...","buyer_question":"...","selling_point":"...",
    "evidence":"exact supporting fact or approved-copy phrase","headline":"...","eyebrow":"...",
    "supporting_text":"...","proof":"...","text_on_image":true,"text_zone":"top-left",
    "layout_style":"editorial|minimal|split|proof|grid","theme":"auto","accent_color":"#RRGGBB",
    "show_product":true,"angle":"...","scene":"...","composition":"...","asset_mode":"generate",
    "visual_concept":"one category-specific art idea","camera_direction":"lens, height, crop, depth and subject scale",
    "product_treatment":"how the unchanged product contacts, folds, mounts, opens, is occupied or is handled",
    "requires_source":false,"source_requirement":"","acceptance_criteria":["...","..."],
    "size":"{'1464x600' if deliverable == 'aplus' else '1600x1600'}",
    "render_prompt":"180–280 words: final-pixel instruction containing exact product identity, category physics, scene, camera, light, shared design system, exact public copy strings, type hierarchy and placement"}}
 ]}}

## HARD RULES
- Every module uses asset_mode="generate", show_product=true and requires_source=false. The model directly generates the
  whole image with the uploaded-first product truth attached at high input fidelity. Do not request source, composite,
  template or blueprint modes.
- Do not invent claims, certifications, dimensions, accessories, UI, screenshots, or results.
- A generated image is not proof. Omit evidence-dependent modules that cannot be supported by supplied product facts.
- Gallery white_main is also generated directly: pure #FFFFFF, complete product/set, no added text, with the same immutable
  reference-product identity. in_box may only show quantities and accessories visibly supported by the reference/product facts.
- Never use a fixed blueprint name, a collected-image template, a generic feature-card grid, or the same composition twice.
- Each render_prompt must explicitly preserve the profile's fidelity anchors and describe believable category physics.
- Write a genuinely different visual_concept, camera_direction and product_treatment for every module.
- Every non-main render_prompt explicitly says the named public copy strings are the only added text, must appear exactly
  once and character-for-character, and forbids all unrequested copy, invented claims, extra logos, badges and watermarks.
- Gallery white_main remains the only forced text-free frame.
{color_directive}
{_FIDELITY_RULE}
"""
    progress("plan", "AI 创意总监策划整套方案…", 0.4)
    try:
        # The shared provider chain may otherwise stack several 5–10 minute
        # provider timeouts. A visual brief must resolve inside a sane budget;
        # deterministic fallback remains editable and evidence-safe.
        raw = await asyncio.wait_for(
            _call_ai(prompt, max_tokens=4000, web_search=False),
            timeout=240,
        )
    except (HTTPException, asyncio.TimeoutError):
        raw = ""
    progress("compile", "编译与质检方案…", 0.85)
    parsed = _strip_json(raw)
    used_fallback = True
    plan = None
    if parsed and isinstance(parsed.get("images"), list) and parsed["images"]:
        parsed["product_profile"] = product_profile
        parsed["planning_mode"] = "adaptive_direct_text"
        parsed["creative_brief"] = body.brief
        parsed["language"] = body.language
        parsed["template_story"] = []
        parsed["template_images"] = []
        plan = _normalize_shot_plan(parsed, n, deliverable)
        used_fallback = not plan["images"]
    if used_fallback:
        plan = _shot_plan_fallback(
            row, scrape_data, analysis_data, n, body.color_scheme, deliverable, product_profile,
        )
        plan["creative_brief"] = body.brief
        plan["language"] = body.language
        plan["template_story"] = []
        plan["template_images"] = []
        # The deterministic fallback still compiles the user's manual brief and
        # artwork language into every final prompt instead of silently dropping
        # the highest-priority creative input when the planner is unavailable.
        plan = _normalize_shot_plan(plan, n, deliverable)
    plan = _bind_reference_templates(plan, project_id, scrape_data, deliverable)
    _persist_shot_plan(project_id, plan, deliverable)
    _persist_visual_anchor(project_id, row, {"product_lock": plan.get("product_lock"),
                                             "visual_style": json.dumps(plan.get("style") or {}, ensure_ascii=False)})
    return {"ok": True, "plan": plan, "fallback": used_fallback, "deliverable": deliverable}


@router.post("/projects/{project_id}/plan-image-set")
async def plan_image_set_endpoint(project_id: str, body: PlanImageSetReq,
                                  _user: str = Depends(require_user)):
    """启动整套策划后台任务，立即返回 job。"""
    if not project_row(project_id, "id"):
        raise HTTPException(404)
    return start_job(
        "plan", project_id, body.model_dump(),
        lambda handle: run_plan_image_set(project_id, body, handle),
    )


@router.post("/projects/{project_id}/creative-set")
async def save_creative_set(project_id: str, body: dict, _user: str = Depends(require_user)):
    """Persist storyboard edits, generated URLs, versions and review state."""
    if not project_row(project_id, "id"):
        raise HTTPException(404, "project not found")
    deliverable = "aplus" if body.get("deliverable") == "aplus" else "gallery"
    raw_plan = body.get("plan") if isinstance(body.get("plan"), dict) else {}
    target_count = len(raw_plan.get("images") or [])
    plan = _normalize_shot_plan(raw_plan, target_count, deliverable)
    _persist_shot_plan(project_id, plan, deliverable)
    return {"ok": True, "plan": plan}


# ─── 成图复核（统一视觉链）────────────────────────────────────────────────────

def _vision_datauri(raw: bytes) -> str:
    """Downsize review inputs so visual QA is fast and bounded."""
    from PIL import Image
    image = Image.open(io.BytesIO(raw)).convert("RGB")
    image.thumbnail((1024, 1024), Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    image.save(buf, "JPEG", quality=86, optimize=True)
    return f"data:image/jpeg;base64,{base64.b64encode(buf.getvalue()).decode()}"


async def _render_vision_review(candidate: bytes, source: bytes | None, body: ReviewRenderReq) -> dict:
    """Use a vision model as an art director, not as the generator grading itself."""
    if not has_vision():
        return {"available": False, "reason": "visual_review_provider_unconfigured"}
    expected_copy = {
        key: value for key, value in (
            ("eyebrow", body.eyebrow), ("headline", body.headline), ("callout", body.callout),
            ("supporting_text", body.supporting_text), ("proof", body.proof),
        ) if str(value or "").strip()
    }
    images = ([_vision_datauri(source)] if source else []) + [_vision_datauri(candidate)]
    prompt = (
        "You are a strict senior ecommerce art director and Amazon image QA reviewer. "
        "Reject generic AI-looking scenes, pasted typography, incorrect product geometry, unreadable copy, "
        "weak selling-point communication, fake evidence and layouts that do not look commercially designed. "
        + ("Image 1 is the exact product/source truth; image 2 is the candidate listing image. "
           if source else "The single image below is the candidate listing image (no source reference supplied). ")
        + "Product fidelity is an identity check, not a general similarity score. OCR every added artwork string carefully.\n\n"
        f"Role: {body.role}; shot type: {body.shot_type}; product should appear: {body.show_product}; "
        f"legacy structured blueprint: {body.layout_blueprint or 'none'}. "
        f"EXPECTED ADDED ARTWORK COPY (exact JSON): {json.dumps(expected_copy, ensure_ascii=False)}. "
        "Every expected string must appear exactly once, character-for-character, with no misspelling, paraphrase, "
        "translation, omission, duplication or extra marketing text. Existing labels printed on the source product are "
        "immutable product details and are not unexpected artwork copy. If expected JSON is empty, there must be no "
        "added headline, caption, number, badge or marketing text. "
        f"Product fidelity anchors: {', '.join(body.product_fidelity_anchors[:8]) or 'silhouette, proportions, colour, material and visible details'}. "
        "When product should appear is true, compare every visible product part against the source: silhouette, proportions, "
        "colour blocking, material, seams, openings, controls, logo/label placement, accessories and quantity. Any redesign, "
        "missing/extra part, changed geometry or materially wrong detail is a fatal issue. When product should appear is false, "
        "do not penalize its intentional absence and return product_fidelity 100. "
        "Return JSON only: {\"scores\":{\"product_fidelity\":0-100,\"realism\":0-100,"
        "\"composition\":0-100,\"typography\":0-100,\"copy_accuracy\":0-100,\"commercial_readiness\":0-100},"
        "\"copy_check\":{\"exact\":true|false,\"unexpected_copy\":true|false,\"transcribed\":[\"...\"]},"
        "\"fatal_issues\":[\"...\"],\"improvements\":[\"...\"],\"verdict\":\"pass|fail\"}. "
        "Use pass only when every visible product detail matches the source, copy is concise and consumer-facing, "
        "all expected copy is exact, the layout has deliberate hierarchy, and the image could ship on a strong brand "
        "listing without repair."
    )
    text = await asyncio.wait_for(_collect_vision(prompt, images), timeout=180)
    parsed = _strip_json(text)
    return {"available": bool(parsed), "result": parsed or {}, "raw": (text or "")[:500]}


async def review_render_core(project_id: str, body: ReviewRenderReq) -> dict:
    """Technical + visual review.  A generated image cannot self-declare success."""
    source_locked = body.shot_type in _SOURCE_LOCKED_TYPES and bool(body.source_url)
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            candidate = await _fetch_image_bytes(client, body.url)
            source = await _fetch_image_bytes(client, body.source_url) if body.source_url and not source_locked else None
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"读取成图失败：{exc}") from exc

    from app.services.listing_image_compositor import technical_quality
    technical = technical_quality(candidate, body.size)
    issues = list(technical["issues"])
    public_values = [body.eyebrow, body.headline, body.callout, body.supporting_text, body.proof]
    if any(_INTERNAL_PUBLIC_COPY_RE.search(str(value or "")) for value in public_values):
        issues.append({"code": "internal_copy", "severity": "error",
                       "message": "成图文案包含内部审核说明，禁止交付"})
    if body.proof and not _public_proof(body.proof):
        issues.append({"code": "invalid_proof", "severity": "error",
                       "message": "证明数字不是简短、面向消费者的事实"})

    # Exact source artwork needs technical checks only; no model should second-
    # guess seller-owned pixels. All generated/composited art receives vision QA.
    vision = {"available": False, "reason": "exact_source_asset"}
    if not source_locked and not any(issue.get("severity") == "error" for issue in issues):
        try:
            vision = await _render_vision_review(candidate, source, body)
        except Exception as exc:  # noqa: BLE001
            vision = {"available": False, "reason": str(exc)[:240]}
        if vision.get("available"):
            result = vision.get("result") or {}
            scores = result.get("scores") if isinstance(result.get("scores"), dict) else {}
            fatal = [str(value) for value in (result.get("fatal_issues") or []) if str(value).strip()]
            improvements = [str(value) for value in (result.get("improvements") or []) if str(value).strip()]

            def score_value(key: str) -> int:
                try:
                    return max(0, min(100, round(float(scores.get(key, 0)))))
                except (TypeError, ValueError):
                    return 0

            product_fidelity = score_value("product_fidelity")
            visual_scores = [score_value(key) for key in (
                "realism", "composition", "typography", "commercial_readiness",
            )]
            retry_notes = [*fatal, *improvements]
            if source and body.show_product and product_fidelity < 92:
                issues.append({"code": "product_fidelity_failed", "severity": "error",
                               "message": f"产品外观一致性 {product_fidelity}/100，低于硬门槛 92"})
                retry_notes.append(
                    "Rebuild the product from the source reference without changing silhouette, proportions, colour, material, visible construction, labels or part count."
                )
            expected_copy = [
                str(value).strip() for value in public_values if str(value or "").strip()
            ]
            copy_check = result.get("copy_check") if isinstance(result.get("copy_check"), dict) else {}
            copy_accuracy = score_value("copy_accuracy")
            copy_failed = (
                (bool(expected_copy) and (copy_accuracy < 96 or copy_check.get("exact") is not True))
                or (not expected_copy and copy_check.get("unexpected_copy") is True)
            )
            if copy_failed:
                issues.append({"code": "artwork_copy_failed", "severity": "error",
                               "message": "图中文字与目标文案不完全一致，存在错字、漏字、重复或额外文字"})
                if expected_copy:
                    retry_notes.append(
                        "Preserve the composition but redraw the typography. Render exactly once and character-for-character: "
                        + " | ".join(expected_copy)
                    )
                else:
                    retry_notes.append("Remove every added headline, caption, number and marketing badge; preserve source-product labels only.")
            if result.get("verdict") != "pass" or fatal or min(visual_scores or [0]) < 80:
                issues.append({"code": "visual_review_failed", "severity": "error",
                               "message": fatal[0] if fatal else "成图审美、真实性或商业完成度未达标"})
                if not fatal and not improvements:
                    retry_notes.append("Improve realism, visual hierarchy, intentional negative space and commercial finish while preserving the product exactly.")
            vision["retry_guidance"] = retry_notes[:6]
        else:
            fidelity_required = bool(source and body.show_product)
            issues.append({
                "code": "product_fidelity_unverified" if fidelity_required else "visual_review_unavailable",
                "severity": "error" if fidelity_required else "warning",
                "message": "产品一致性复核未返回，生成图不能交付" if fidelity_required else "远程审美复核未返回，必须由人工完成审美复核",
            })
    elif not source_locked:
        vision = {"available": False, "reason": "deterministic_quality_failure"}

    errors = [issue for issue in issues if issue.get("severity") == "error"]
    score_values = (vision.get("result") or {}).get("scores") if vision.get("available") else {}
    score_numbers = []
    for value in (score_values or {}).values():
        try:
            score_numbers.append(max(0, min(100, round(float(value)))))
        except (TypeError, ValueError):
            continue
    score = round(sum(score_numbers) / len(score_numbers)) if score_numbers else (
        100 if source_locked and technical["ready"] else (70 if technical["ready"] else 0)
    )
    return {
        "ready": not errors,
        "score": score,
        "issues": issues,
        "technical": technical,
        "vision": vision,
        "retry_guidance": vision.get("retry_guidance") or [],
        "manual_visual_review_required": not source_locked and not vision.get("available"),
        "reviewed_at": time.time(),
    }


@router.post("/projects/{project_id}/review-render")
async def review_render(project_id: str, body: ReviewRenderReq, _user: str = Depends(require_user)):
    return await review_render_core(project_id, body)


def _contact_sheet(items: list[bytes]) -> bytes:
    from PIL import Image, ImageDraw, ImageOps
    tile = 360
    cols = min(3, max(1, len(items)))
    rows = (len(items) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * tile, rows * tile), "#E9EAEC")
    draw = ImageDraw.Draw(sheet)
    for index, raw in enumerate(items):
        image = Image.open(io.BytesIO(raw)).convert("RGB")
        fitted = ImageOps.fit(image, (tile - 12, tile - 12), Image.Resampling.LANCZOS)
        x, y = (index % cols) * tile + 6, (index // cols) * tile + 6
        sheet.paste(fitted, (x, y))
        draw.rectangle((x + 8, y + 8, x + 42, y + 38), fill=(0, 0, 0))
        draw.text((x + 19, y + 14), str(index + 1), fill=(255, 255, 255))
    output = io.BytesIO()
    sheet.save(output, "JPEG", quality=88, optimize=True)
    return output.getvalue()


async def _set_vision_review(sheet: bytes, plan: dict) -> dict:
    if not has_vision():
        return {"available": False, "reason": "visual_review_provider_unconfigured"}
    roles = [str(item.get("role") or item.get("slot") or "") for item in plan.get("images") or []]
    prompt = (
        "Act as a demanding ecommerce creative director reviewing this numbered contact sheet as ONE Amazon "
        "image set. Judge it against strong premium-brand listings. Reject sets that are merely unrelated AI "
        "renders, repeat the same product pose, use inconsistent aspect ratios/type scales/colour grading, have "
        "no visual narrative, contain pasted-looking copy, or fail to demonstrate the promised buyer benefit. "
        f"Intended sequence: {' | '.join(roles)}. Story: {plan.get('story') or ''}.\n\n"
        "Return JSON only: {\"scores\":{\"suite_cohesion\":0-100,\"design_system\":0-100,"
        "\"story_progression\":0-100,\"commercial_readiness\":0-100},\"fatal_issues\":[\"...\"],"
        "\"improvements\":[\"...\"],\"verdict\":\"pass|fail\"}. Pass requires every score >=80 and no "
        "fatal issue. Do not be generous."
    )
    text = await asyncio.wait_for(_collect_vision(prompt, [_vision_datauri(sheet)]), timeout=180)
    parsed = _strip_json(text)
    return {"available": bool(parsed), "result": parsed or {}, "raw": (text or "")[:500]}


async def run_review_image_set(project_id: str, deliverable: str,
                               handle: Optional[JobHandle] = None) -> dict:
    """Review the contact sheet so isolated acceptable images cannot masquerade as a coherent set."""
    deliverable = "aplus" if deliverable == "aplus" else "gallery"
    row = project_row(project_id, "creative_sets")
    if not row:
        raise HTTPException(404, "project not found")
    try:
        sets = json.loads(row["creative_sets"] or "{}")
        plan = sets.get(deliverable) or {}
    except Exception:
        plan = {}
    images = plan.get("images") or []
    complete = [item for item in images if item.get("final_url")]
    failed_individual = [item for item in complete if not (item.get("render_qa") or {}).get("ready")]
    issues: list[dict] = []
    if len(complete) != len(images) or not images:
        issues.append({"code": "incomplete_set", "severity": "error", "message": "整套图片尚未全部完成"})
    if failed_individual:
        issues.append({"code": "individual_failures", "severity": "error",
                       "message": f"仍有 {len(failed_individual)} 张未通过单图质检"})
    vision = {"available": False, "reason": "set_not_ready"}
    if not issues:
        if handle:
            handle.update(stage="review", message="AI 创意总监整套审阅中…", progress=0.5)
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                raws = await asyncio.gather(*[_fetch_image_bytes(client, item["final_url"]) for item in complete])
            vision = await _set_vision_review(_contact_sheet(raws), plan)
        except Exception as exc:  # noqa: BLE001
            vision = {"available": False, "reason": str(exc)[:240]}
        if vision.get("available"):
            result = vision.get("result") or {}
            scores = result.get("scores") if isinstance(result.get("scores"), dict) else {}
            values = [int(value) for value in scores.values() if str(value).isdigit()]
            fatal = [str(value) for value in (result.get("fatal_issues") or []) if str(value).strip()]
            if result.get("verdict") != "pass" or fatal or min(values or [0]) < 80:
                issues.append({"code": "suite_review_failed", "severity": "error",
                               "message": fatal[0] if fatal else "整套设计一致性和叙事未达到商业标准"})
        else:
            issues.append({"code": "suite_review_unavailable", "severity": "warning",
                           "message": "远程整套审美复核未返回，必须由人工检查套图一致性"})
    scores = (vision.get("result") or {}).get("scores") if vision.get("available") else {}
    values = [int(value) for value in (scores or {}).values() if str(value).isdigit()]
    set_qa = {
        "ready": not any(issue.get("severity") == "error" for issue in issues),
        "score": round(sum(values) / len(values)) if values else (70 if not any(
            issue.get("severity") == "error" for issue in issues) else 0),
        "issues": issues,
        "vision": vision,
        "reviewed_at": time.time(),
    }
    plan["set_qa"] = set_qa
    _persist_shot_plan(project_id, plan, deliverable)
    return {"set_qa": set_qa, "plan": plan, "deliverable": deliverable}


@router.post("/projects/{project_id}/review-image-set")
async def review_image_set_endpoint(project_id: str, body: ReviewSetReq,
                                    _user: str = Depends(require_user)):
    """整套复核也走后台 job（视觉链可能要几十秒）。"""
    if not project_row(project_id, "id"):
        raise HTTPException(404)
    return start_job(
        "review_set", project_id, body.model_dump(),
        lambda handle: run_review_image_set(project_id, body.deliverable, handle),
    )
