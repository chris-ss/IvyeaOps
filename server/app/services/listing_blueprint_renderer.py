"""Structured ecommerce infographic renderer.

The image model supplies photography only.  This module owns the repeatable
design work: panel geometry, exact product compositing, diagrams, comparison
frames, badges and short factual labels.  Keeping those layers deterministic is
what makes a gallery read as one designed set instead of unrelated AI posters.
"""
from __future__ import annotations

import io
import math
from typing import Iterable

from PIL import Image, ImageDraw, ImageFilter, ImageOps

from app.services.listing_image_compositor import parse_size, primary_product_cutout
from app.services.listing_typography import _load_font, _wrap_text


def _open(raw: bytes) -> Image.Image:
    return Image.open(io.BytesIO(raw)).convert("RGBA")


def _cover(raw: bytes, size: tuple[int, int]) -> Image.Image:
    return ImageOps.fit(_open(raw), size, Image.Resampling.LANCZOS, centering=(.5, .5))


def _hex(value: str) -> tuple[int, int, int]:
    text = str(value or "#66C85A").strip().lstrip("#")
    if len(text) == 3:
        text = "".join(char * 2 for char in text)
    try:
        return tuple(int(text[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]
    except Exception:
        return (102, 200, 90)


def _png(image: Image.Image) -> bytes:
    output = io.BytesIO()
    image.convert("RGB").save(output, "PNG", compress_level=6)
    return output.getvalue()


def _rounded_mask(size: tuple[int, int], radius: int) -> Image.Image:
    mask = Image.new("L", size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, size[0] - 1, size[1] - 1), radius=radius, fill=255)
    return mask


def _panel(canvas: Image.Image, raw: bytes, box: tuple[int, int, int, int], *,
           radius: int = 24, monochrome: bool = False, darken: float = 0) -> None:
    x0, y0, x1, y1 = box
    image = _cover(raw, (max(1, x1 - x0), max(1, y1 - y0)))
    if monochrome:
        image = ImageOps.grayscale(image).convert("RGBA")
    if darken:
        shade = Image.new("RGBA", image.size, (0, 0, 0, int(255 * darken)))
        image = Image.alpha_composite(image, shade)
    canvas.paste(image, (x0, y0), _rounded_mask(image.size, radius))


def _bottom_gradient(canvas: Image.Image, strength: int = 170) -> None:
    width, height = canvas.size
    overlay = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    start = int(height * .58)
    for y in range(start, height):
        t = (y - start) / max(1, height - start)
        draw.line((0, y, width, y), fill=(6, 12, 8, int(strength * t * t)))
    canvas.alpha_composite(overlay)


def _label(draw: ImageDraw.ImageDraw, text: str, box: tuple[int, int, int, int], *,
           size: int, fill=(255, 255, 255), align: str = "left",
           stroke: int = 2, max_lines: int = 2) -> None:
    if not str(text or "").strip():
        return
    x0, y0, x1, _ = box
    font = _load_font(size, True)
    lines = _wrap_text(draw, str(text), font, x1 - x0, max_lines)
    line_h = int(size * 1.18)
    for line in lines:
        tw = draw.textlength(line, font=font)
        x = x0 if align == "left" else (x1 - tw if align == "right" else x0 + (x1 - x0 - tw) / 2)
        draw.text((x, y0), line, font=font, fill=(*fill, 255), stroke_width=stroke,
                  stroke_fill=(0, 0, 0, 150))
        y0 += line_h


def _place_product(canvas: Image.Image, raw: bytes, box: tuple[int, int, int, int], *,
                   align: str = "center", floor: bool = True) -> None:
    x0, y0, x1, y1 = box
    product = primary_product_cutout(raw)
    product.thumbnail((max(1, x1 - x0), max(1, y1 - y0)), Image.Resampling.LANCZOS)
    x = x0 if align == "left" else x1 - product.width if align == "right" else x0 + (x1 - x0 - product.width) // 2
    y = y1 - product.height if floor else y0 + (y1 - y0 - product.height) // 2
    alpha = product.getchannel("A")
    shadow_mask = Image.new("L", canvas.size, 0)
    shadow_mask.paste(alpha, (x + max(4, canvas.width // 180), y + max(7, canvas.height // 130)))
    shadow_mask = shadow_mask.filter(ImageFilter.GaussianBlur(max(10, min(canvas.size) // 70)))
    shadow = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    shadow.putalpha(shadow_mask.point(lambda value: int(value * .32)))
    canvas.alpha_composite(shadow)
    canvas.alpha_composite(product, (x, y))


def _wifi(draw: ImageDraw.ImageDraw, center: tuple[int, int], radius: int, color) -> None:
    cx, cy = center
    width = max(4, radius // 10)
    for scale in (.95, .68, .4):
        r = int(radius * scale)
        draw.arc((cx - r, cy - r, cx + r, cy + r), 210, 330, fill=color, width=width)
    draw.ellipse((cx - width, cy + radius // 4 - width, cx + width, cy + radius // 4 + width), fill=color)


def _reticle(draw: ImageDraw.ImageDraw, center: tuple[int, int], radius: int, color) -> None:
    cx, cy = center
    width = max(3, radius // 24)
    draw.line((cx - radius, cy, cx - radius // 3, cy), fill=color, width=width)
    draw.line((cx + radius // 3, cy, cx + radius, cy), fill=color, width=width)
    draw.line((cx, cy - radius, cx, cy - radius // 3), fill=color, width=width)
    draw.line((cx, cy + radius // 3, cx, cy + radius), fill=color, width=width)


def _snowflake(draw: ImageDraw.ImageDraw, center: tuple[int, int], radius: int, color) -> None:
    cx, cy = center
    width = max(3, radius // 10)
    for angle in (0, math.pi / 3, math.pi * 2 / 3):
        dx, dy = math.cos(angle) * radius, math.sin(angle) * radius
        draw.line((cx - dx, cy - dy, cx + dx, cy + dy), fill=color, width=width)


def _weather(draw: ImageDraw.ImageDraw, center: tuple[int, int], radius: int, color) -> None:
    cx, cy = center
    width = max(3, radius // 10)
    draw.arc((cx - radius, cy - radius // 2, cx, cy + radius // 2), 170, 350, fill=color, width=width)
    draw.arc((cx - radius // 3, cy - radius, cx + radius, cy + radius // 2), 180, 350, fill=color, width=width)
    draw.line((cx - radius * .75, cy + radius * .28, cx + radius * .72, cy + radius * .28), fill=color, width=width)
    for dx in (-.5, 0, .5):
        draw.line((cx + radius * dx, cy + radius * .48, cx + radius * (dx - .12), cy + radius * .78), fill=color, width=width)


def _wind(draw: ImageDraw.ImageDraw, center: tuple[int, int], radius: int, color) -> None:
    cx, cy = center
    width = max(3, radius // 11)
    for offset, scale in ((-.45, .85), (0, 1), (.45, .72)):
        y = cy + radius * offset
        draw.arc((cx - radius * scale, y - radius * .22, cx + radius * scale, y + radius * .22), 185, 345, fill=color, width=width)


def _storage(draw: ImageDraw.ImageDraw, center: tuple[int, int], radius: int, color) -> None:
    cx, cy = center
    width = max(3, radius // 10)
    box = (cx - radius * .62, cy - radius * .78, cx + radius * .62, cy + radius * .78)
    draw.rounded_rectangle(box, radius=radius // 7, outline=color, width=width)
    draw.line((cx - radius * .35, cy - radius * .48, cx + radius * .35, cy - radius * .48), fill=color, width=width)
    draw.rectangle((cx - radius * .30, cy + radius * .10, cx + radius * .30, cy + radius * .48), outline=color, width=width)


def _download(draw: ImageDraw.ImageDraw, center: tuple[int, int], radius: int, color) -> None:
    cx, cy = center
    width = max(3, radius // 10)
    draw.line((cx, cy - radius * .72, cx, cy + radius * .25), fill=color, width=width)
    draw.line((cx - radius * .35, cy - radius * .05, cx, cy + radius * .30, cx + radius * .35, cy - radius * .05), fill=color, width=width)
    draw.rounded_rectangle((cx - radius * .62, cy + radius * .35, cx + radius * .62, cy + radius * .70), radius=radius // 10, outline=color, width=width)


def _badge_row(canvas: Image.Image, labels: list[str], *, y: int, accent, max_items: int = 4) -> None:
    labels = [str(label) for label in labels if str(label).strip()][:max_items]
    if not labels:
        return
    draw = ImageDraw.Draw(canvas)
    width, height = canvas.size
    cell = width / len(labels)
    circle = int(min(width, height) * .045)
    for index, text in enumerate(labels):
        cx = int(cell * (index + .5))
        cy = y
        draw.ellipse((cx - circle, cy - circle, cx + circle, cy + circle),
                     fill=(5, 14, 9, 190), outline=(*accent, 255), width=max(3, circle // 10))
        lower = text.lower()
        if "wi-fi" in lower or "wifi" in lower or "bluetooth" in lower:
            _wifi(draw, (cx, cy), int(circle * .65), (*accent, 255))
        elif any(token in lower for token in ("ice", "snow", "freeze")):
            _snowflake(draw, (cx, cy), int(circle * .58), (*accent, 255))
        elif any(token in lower for token in ("rain", "fog", "water", "weather")):
            _weather(draw, (cx, cy), int(circle * .60), (*accent, 255))
        elif any(token in lower for token in ("dust", "mud", "wind")):
            _wind(draw, (cx, cy), int(circle * .62), (*accent, 255))
        elif any(token in lower for token in ("storage", "card", "gb", "memory")):
            _storage(draw, (cx, cy), int(circle * .58), (*accent, 255))
        elif any(token in lower for token in ("download", "share", "save", "view")):
            _download(draw, (cx, cy), int(circle * .58), (*accent, 255))
        elif any(token in lower for token in ("0.1", "trigger", "speed", "capture")):
            _reticle(draw, (cx, cy), int(circle * .6), (*accent, 255))
        else:
            draw.ellipse((cx - circle * .16, cy - circle * .16, cx + circle * .16, cy + circle * .16), fill=(*accent, 255))
            draw.ellipse((cx - circle * .47, cy - circle * .47, cx + circle * .47, cy + circle * .47), outline=(*accent, 255), width=max(3, circle // 11))
        _label(draw, text, (int(cx - cell * .42), cy + circle + 10, int(cx + cell * .42), height),
               size=max(18, int(height * .018)), align="center", stroke=2, max_lines=2)


def _scene(scene_raws: list[bytes], index: int) -> bytes:
    if not scene_raws:
        raise ValueError("blueprint requires generated scene photography")
    return scene_raws[min(index, len(scene_raws) - 1)]


def render_blueprint(scene_raws: list[bytes], product_raw: bytes, size: str, *,
                     blueprint: str, accent_color: str = "#66C85A",
                     labels: Iterable[str] = ()) -> bytes:
    width, height = parse_size(size)
    accent = _hex(accent_color)
    labels = [str(value).strip() for value in labels if str(value).strip()]
    margin = max(8, int(min(width, height) * .012))
    radius = max(16, int(min(width, height) * .022))

    if blueprint == "white_bundle":
        fitted = ImageOps.contain(_open(product_raw), (width, height), Image.Resampling.LANCZOS)
        white = Image.new("RGBA", (width, height), "white")
        white.alpha_composite(fitted, ((width - fitted.width) // 2, (height - fitted.height) // 2))
        return _png(white)

    canvas = Image.new("RGBA", (width, height), (245, 247, 244, 255))
    draw = ImageDraw.Draw(canvas)

    if blueprint == "media_proof_split":
        top = int(height * .14)
        gap = margin
        panel_h = (height - top - gap - margin) // 2
        boxes = [(0, top, width, top + panel_h), (0, top + panel_h + gap, width, height)]
        for index, box in enumerate(boxes):
            _panel(canvas, _scene(scene_raws, index), box, radius=radius)
            panel_labels = (labels + ["Video detail", "Photo detail"])[:2]
            if index < len(panel_labels):
                _label(draw, panel_labels[index], (int(width * .045), box[1] + int(height * .025), int(width * .58), box[3]),
                       size=max(28, int(height * .035)), fill=accent)

    elif blueprint == "connectivity_diagram":
        canvas = _cover(_scene(scene_raws, 0), (width, height))
        shade = Image.new("RGBA", canvas.size, (2, 10, 5, 55))
        canvas = Image.alpha_composite(canvas, shade)
        _place_product(canvas, product_raw, (int(width * .58), int(height * .22), int(width * .96), int(height * .84)))
        draw = ImageDraw.Draw(canvas)
        phone = (int(width * .06), int(height * .44), int(width * .31), int(height * .90))
        draw.rounded_rectangle(phone, radius=radius, fill=(12, 16, 14, 235), outline=(245, 247, 245, 255), width=max(4, width // 300))
        inset = (phone[0] + margin, phone[1] + margin * 2, phone[2] - margin, phone[3] - margin * 3)
        phone_scene = _cover(_scene(scene_raws, 0), (inset[2] - inset[0], inset[3] - inset[1]))
        canvas.paste(phone_scene, inset[:2], _rounded_mask(phone_scene.size, radius // 2))
        y = int(height * .60)
        draw.line((phone[2], y, int(width * .60), y), fill=(*accent, 255), width=max(4, width // 250))
        _wifi(draw, (int(width * .45), y), int(width * .055), (*accent, 255))
        _bottom_gradient(canvas, 210)
        _badge_row(canvas, labels, y=int(height * .83), accent=accent, max_items=4)

    elif blueprint == "environmental_proof":
        canvas = _cover(_scene(scene_raws, 0), (width, height))
        _place_product(canvas, product_raw, (int(width * .60), int(height * .22), int(width * .94), int(height * .76)))
        _bottom_gradient(canvas, 210)
        _badge_row(canvas, labels, y=int(height * .82), accent=accent, max_items=3)

    elif blueprint == "coverage_diagram":
        canvas = _cover(_scene(scene_raws, 0), (width, height))
        _place_product(canvas, product_raw, (int(width * .44), int(height * .30), int(width * .57), int(height * .48)))
        draw = ImageDraw.Draw(canvas)
        origin = (width // 2, int(height * .45))
        targets = [(int(width * .05), int(height * .92)), (int(width * .28), int(height * .92)),
                   (int(width * .72), int(height * .92)), (int(width * .95), int(height * .92))]
        for target in targets:
            draw.line((*origin, *target), fill=(235, 255, 238, 220), width=max(3, width // 420))
        for scale in (.16, .28, .40):
            r = int(width * scale)
            draw.arc((origin[0] - r, origin[1] - r // 3, origin[0] + r, origin[1] + r),
                     20, 160, fill=(*accent, 235), width=max(4, width // 300))
        if labels:
            _label(draw, labels[0], (int(width * .34), int(height * .50), int(width * .66), int(height * .62)),
                   size=max(28, int(height * .038)), fill=accent, align="center")

    elif blueprint == "speed_comparison":
        source = _scene(scene_raws, 0)
        _panel(canvas, source, (0, 0, width, int(height * .69)), radius=0)
        draw = ImageDraw.Draw(canvas)
        _reticle(draw, (width // 2, int(height * .38)), int(min(width, height) * .11), (*accent, 255))
        gap = margin
        y0 = int(height * .68)
        left_box = (0, y0, width // 2 - gap // 2, height)
        right_box = (width // 2 + gap // 2, y0, width, height)
        _panel(canvas, source, left_box, radius=radius)
        blurred = _cover(source, (right_box[2] - right_box[0], right_box[3] - right_box[1])).filter(ImageFilter.GaussianBlur(max(5, width // 260)))
        canvas.paste(blurred, right_box[:2], _rounded_mask(blurred.size, radius))
        draw = ImageDraw.Draw(canvas)
        defaults = (labels + ["Accurate capture", "Reference comparison"])[:2]
        _label(draw, defaults[0], (left_box[0] + margin * 2, left_box[1] + margin, left_box[2] - margin, height),
               size=max(22, int(height * .026)), fill=accent, align="center")
        if len(defaults) > 1:
            _label(draw, defaults[1], (right_box[0] + margin, right_box[1] + margin, right_box[2] - margin * 2, height),
                   size=max(22, int(height * .026)), fill=accent, align="center")

    elif blueprint == "day_night_split":
        gap = margin
        half = (height - gap) // 2
        _panel(canvas, _scene(scene_raws, 0), (0, 0, width, half), radius=radius, monochrome=True, darken=.08)
        _panel(canvas, _scene(scene_raws, 1), (0, half + gap, width, height), radius=radius)
        draw = ImageDraw.Draw(canvas)
        defaults = (labels + ["Night vision", "Daylight detail"])[:2]
        _label(draw, defaults[0], (int(width * .055), int(height * .055), int(width * .70), half),
               size=max(28, int(height * .038)))
        if len(defaults) > 1:
            _label(draw, defaults[1], (int(width * .055), half + int(height * .055), int(width * .70), height),
                   size=max(28, int(height * .038)), fill=accent)

    elif blueprint == "use_case_mosaic":
        gap = margin
        top_h = int(height * .64)
        left_w = int(width * .66)
        boxes = [
            (0, 0, left_w - gap // 2, top_h),
            (left_w + gap // 2, 0, width, top_h // 2 - gap // 2),
            (left_w + gap // 2, top_h // 2 + gap // 2, width, top_h),
            (0, top_h + gap, width // 3 - gap, height),
            (width // 3, top_h + gap, width * 2 // 3 - gap // 2, height),
            (width * 2 // 3, top_h + gap, width, height),
        ]
        # Five generated scenes fill six cells by reusing the primary scene in
        # the large anchor and using all remaining scenes once.
        for index, box in enumerate(boxes):
            raw = _scene(scene_raws, 0 if index == 0 else min(index, len(scene_raws) - 1))
            _panel(canvas, raw, box, radius=radius)
            if index < len(labels):
                _label(ImageDraw.Draw(canvas), labels[index],
                       (box[0] + margin * 2, box[3] - int(height * .07), box[2] - margin * 2, box[3] - margin),
                       size=max(18, int(height * .021)), align="center")

    else:
        canvas = _cover(_scene(scene_raws, 0), (width, height))
        _place_product(canvas, product_raw, (int(width * .55), int(height * .2), int(width * .94), int(height * .86)))

    return _png(canvas)
