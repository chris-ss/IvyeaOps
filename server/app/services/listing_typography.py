"""Crisp on-image callout typography (Pillow).

Render callout text SEPARATELY from the image model, so the 套图 callouts are
legible, correctly spelled, editable and re-renderable in any language — instead
of letting gpt-image draw (often garbled) text into the picture. Used by the
Listing 套图 flow: the image is generated product+scene only, then the callout is
overlaid here.
"""
from __future__ import annotations

import io
import os
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw, ImageFont

# anchor → (x_frac, y_frac, h-align). y<0.2 = top, >0.8 = bottom.
_POS = {
    "top-left": (0.06, 0.06, "left"), "top-center": (0.5, 0.06, "center"), "top-right": (0.94, 0.06, "right"),
    "center": (0.5, 0.5, "center"),
    "bottom-left": (0.06, 0.94, "left"), "bottom-center": (0.5, 0.94, "center"), "bottom-right": (0.94, 0.94, "right"),
}

# CJK + Latin fonts across the platforms IvyeaOps runs on (Linux server / Windows
# frozen exe / macOS .app). First hit wins; env override beats all.
_FONT_CANDIDATES = [
    "/usr/share/fonts/google-noto-cjk/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc",
    "C:/Windows/Fonts/msyhbd.ttc", "C:/Windows/Fonts/msyh.ttc",
    "/System/Library/Fonts/PingFang.ttc",
    "/usr/share/fonts/dejavu-sans-fonts/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
]


def _font_path() -> Optional[str]:
    env = (os.getenv("IVYEA_OPS_CALLOUT_FONT") or "").strip()
    if env and Path(env).exists():
        return env
    for c in _FONT_CANDIDATES:
        if Path(c).exists():
            return c
    return None


def _load_font(size: int) -> ImageFont.FreeTypeFont:
    p = _font_path()
    if p:
        try:
            return ImageFont.truetype(p, size)
        except Exception:
            pass
    return ImageFont.load_default()


def _hex(h: str) -> tuple[int, int, int]:
    h = (h or "#FFFFFF").lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    try:
        return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
    except Exception:
        return (255, 255, 255)


def overlay_callout(img_bytes: bytes, text: str, position: str = "bottom-center", *,
                    color: str = "#FFFFFF", plate: str = "#101418") -> bytes:
    """Return a copy of img_bytes with `text` typeset at `position` (a crisp,
    high-contrast block with a translucent plate + stroke). No-op if text empty."""
    text = (text or "").strip()
    if not text:
        return img_bytes
    im = Image.open(io.BytesIO(img_bytes)).convert("RGBA")
    W, H = im.size
    size = max(22, int(H * 0.062))
    font = _load_font(size)
    draw = ImageDraw.Draw(im)

    # wrap to ~70% width
    max_w = int(W * 0.70)
    lines: list[str] = []
    cur = ""
    for word in text.split():
        trial = (cur + " " + word).strip()
        if draw.textlength(trial, font=font) <= max_w or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)

    line_h = int(size * 1.28)
    block_w = max((draw.textlength(ln, font=font) for ln in lines), default=0)
    block_h = line_h * len(lines)
    xf, yf, align = _POS.get(position, _POS["bottom-center"])
    pad = int(size * 0.45)
    cx, cy = xf * W, yf * H
    x0 = cx if align == "left" else (cx - block_w if align == "right" else cx - block_w / 2)
    y0 = cy if yf < 0.2 else (cy - block_h if yf > 0.8 else cy - block_h / 2)
    x0 = max(pad, min(x0, W - block_w - pad))
    y0 = max(pad, min(y0, H - block_h - pad))

    # translucent plate for legibility on any background
    overlay = Image.new("RGBA", im.size, (0, 0, 0, 0))
    pr, pg, pb = _hex(plate)
    ImageDraw.Draw(overlay).rounded_rectangle(
        [x0 - pad, y0 - pad * 0.7, x0 + block_w + pad, y0 + block_h + pad * 0.7],
        radius=pad, fill=(pr, pg, pb, 140),
    )
    im = Image.alpha_composite(im, overlay)
    draw = ImageDraw.Draw(im)

    cr, cg, cb = _hex(color)
    sy = y0
    for ln in lines:
        lw = draw.textlength(ln, font=font)
        lx = x0 if align == "left" else (x0 + block_w - lw if align == "right" else x0 + (block_w - lw) / 2)
        draw.text((lx, sy), ln, font=font, fill=(cr, cg, cb, 255),
                  stroke_width=max(2, int(size * 0.06)), stroke_fill=(0, 0, 0, 210))
        sy += line_h

    out = io.BytesIO()
    im.convert("RGB").save(out, format="PNG")
    return out.getvalue()
