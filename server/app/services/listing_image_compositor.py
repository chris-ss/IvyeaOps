"""Deterministic image preparation for the Listing visual studio.

Generative models are useful for backgrounds, people and atmosphere, but they
must not be trusted to redraw a sellable product.  This module keeps source
pixels intact, normalises every deliverable to its declared canvas, and can
place a transparent/white-background product photograph over a generated
background.
"""
from __future__ import annotations

import io
import re
from collections import deque

from PIL import Image, ImageChops, ImageFilter, ImageOps


_SIZE_RE = re.compile(r"^(\d{2,5})x(\d{2,5})$")


def parse_size(value: str, fallback: tuple[int, int] = (1600, 1600)) -> tuple[int, int]:
    match = _SIZE_RE.match(str(value or "").strip().lower())
    if not match:
        return fallback
    width, height = int(match.group(1)), int(match.group(2))
    if not (320 <= width <= 4096 and 320 <= height <= 4096):
        return fallback
    return width, height


def _open(raw: bytes) -> Image.Image:
    return Image.open(io.BytesIO(raw)).convert("RGBA")


def _png(image: Image.Image) -> bytes:
    output = io.BytesIO()
    # Pillow's exhaustive PNG optimiser can add tens of seconds on 1600px art
    # while changing no pixels. Normal compression keeps production requests bounded.
    image.convert("RGB").save(output, "PNG", compress_level=6)
    return output.getvalue()


def normalise_canvas(
    raw: bytes,
    size: str,
    *,
    mode: str = "cover",
    background: str = "#FFFFFF",
) -> bytes:
    """Return an exact-size canvas without stretching the source image.

    ``contain`` is used for main/in-box source photography so no purchased item
    can be cropped away.  Generated scenes use ``cover`` to fill the canvas.
    """
    target = parse_size(size)
    image = _open(raw)
    if mode == "contain":
        fitted = ImageOps.contain(image, target, Image.Resampling.LANCZOS)
        canvas = Image.new("RGBA", target, background)
        canvas.alpha_composite(fitted, ((target[0] - fitted.width) // 2, (target[1] - fitted.height) // 2))
    else:
        canvas = ImageOps.fit(image, target, Image.Resampling.LANCZOS, centering=(0.5, 0.5))
    return _png(canvas)


def _border_colour(image: Image.Image) -> tuple[int, int, int]:
    rgb = image.convert("RGB")
    w, h = rgb.size
    band = max(2, min(w, h) // 100)
    strips = [
        rgb.crop((0, 0, w, band)), rgb.crop((0, h - band, w, h)),
        rgb.crop((0, 0, band, h)), rgb.crop((w - band, 0, w, h)),
    ]
    tiny = Image.new("RGB", (sum(s.width for s in strips), 1))
    x = 0
    for strip in strips:
        sample = strip.resize((max(1, strip.width), 1), Image.Resampling.BOX)
        tiny.paste(sample, (x, 0))
        x += sample.width
    pixels = sorted(tiny.getdata(), key=lambda p: sum(p))
    return pixels[len(pixels) // 2] if pixels else (255, 255, 255)


def product_cutout(raw: bytes) -> Image.Image:
    """Extract a product from transparent or near-uniform light-background art.

    This is intentionally conservative.  If the border is not a clean light
    studio background, the source is returned as a normal rectangular asset
    rather than destroying product pixels with an aggressive segmentation.
    """
    image = _open(raw)
    alpha = image.getchannel("A")
    if alpha.getextrema()[0] < 245:
        bbox = alpha.getbbox()
        return image.crop(bbox) if bbox else image

    bg = _border_colour(image)
    if min(bg) < 225 or max(bg) - min(bg) > 24:
        return image

    flat = Image.new("RGB", image.size, bg)
    diff = ImageChops.difference(image.convert("RGB"), flat)
    # Max-channel distance preserves neutral black/grey products and gives a
    # soft edge around antialiased source pixels and natural contact shadows.
    channels = diff.split()
    distance = ImageChops.lighter(ImageChops.lighter(channels[0], channels[1]), channels[2])
    mask = distance.point(lambda value: 0 if value < 5 else min(255, (value - 5) * 7))
    mask = mask.filter(ImageFilter.GaussianBlur(max(1, min(image.size) // 900)))
    image.putalpha(mask)
    bbox = mask.getbbox()
    return image.crop(bbox) if bbox else image


def primary_product_cutout(raw: bytes) -> Image.Image:
    """Extract the largest connected foreground object from a white source.

    Marketplace reference images often contain an SD card, phone mock-up, hand
    or accessory beside the product. Those are useful in the white bundle image
    but must not be pasted into every lifestyle scene with the main product.
    """
    layer = product_cutout(raw)
    if layer.width < 40 or layer.height < 40:
        return layer
    alpha = layer.getchannel("A")
    preview = alpha.copy()
    preview.thumbnail((320, 320), Image.Resampling.NEAREST)
    width, height = preview.size
    binary = preview.point(lambda value: 255 if value >= 28 else 0)
    pixels = binary.load()
    seen = bytearray(width * height)
    best: tuple[int, int, int, int, int] | None = None
    best_points: list[tuple[int, int]] = []
    for sy in range(height):
        for sx in range(width):
            offset = sy * width + sx
            if seen[offset] or not pixels[sx, sy]:
                continue
            seen[offset] = 1
            queue = deque([(sx, sy)])
            points: list[tuple[int, int]] = []
            min_x = max_x = sx
            min_y = max_y = sy
            area = 0
            while queue:
                x, y = queue.popleft()
                points.append((x, y))
                area += 1
                min_x, max_x = min(min_x, x), max(max_x, x)
                min_y, max_y = min(min_y, y), max(max_y, y)
                for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                    if 0 <= nx < width and 0 <= ny < height:
                        no = ny * width + nx
                        if not seen[no] and pixels[nx, ny]:
                            seen[no] = 1
                            queue.append((nx, ny))
            candidate = (area, min_x, min_y, max_x + 1, max_y + 1)
            if best is None or candidate[0] > best[0]:
                best = candidate
                best_points = points
    if not best or best[0] < width * height * .015:
        return layer
    component = Image.new("L", (width, height), 0)
    component_pixels = component.load()
    for x, y in best_points:
        component_pixels[x, y] = 255
    component = component.resize(layer.size, Image.Resampling.NEAREST)
    component = component.filter(ImageFilter.MaxFilter(3))
    selected_alpha = ImageChops.multiply(alpha, component)
    layer.putalpha(selected_alpha)
    bbox = selected_alpha.getbbox()
    return layer.crop(bbox) if bbox else layer


def composite_product(
    background_raw: bytes,
    product_raw: bytes,
    size: str,
    *,
    text_zone: str = "top-left",
    product_scale: float = 0.52,
) -> bytes:
    """Place unchanged source product pixels over a generated background."""
    width, height = parse_size(size)
    background = _open(normalise_canvas(background_raw, size, mode="cover"))
    product = primary_product_cutout(product_raw)
    scale = max(0.24, min(float(product_scale or 0.52), 0.72))
    max_w, max_h = int(width * scale), int(height * 0.76)
    product.thumbnail((max_w, max_h), Image.Resampling.LANCZOS)

    margin = int(min(width, height) * 0.075)
    if text_zone.endswith("left"):
        x = width - margin - product.width
    elif text_zone.endswith("right"):
        x = margin
    else:
        x = (width - product.width) // 2
    if text_zone.startswith("bottom"):
        y = margin
    else:
        y = height - margin - product.height
    x, y = max(0, x), max(0, y)

    # A restrained grounding shadow prevents the exact source layer from
    # looking pasted on while leaving the product itself untouched.
    alpha = product.getchannel("A")
    shadow = Image.new("RGBA", background.size, (0, 0, 0, 0))
    shadow_mask = Image.new("L", background.size, 0)
    shadow_mask.paste(alpha, (x + int(width * .008), y + int(height * .012)))
    shadow_mask = shadow_mask.filter(ImageFilter.GaussianBlur(max(8, int(min(width, height) * .018))))
    shadow.putalpha(shadow_mask.point(lambda value: int(value * .28)))
    background = Image.alpha_composite(background, shadow)
    background.alpha_composite(product, (x, y))
    return _png(background)


def technical_quality(raw: bytes, expected_size: str) -> dict:
    """Cheap deterministic checks that must pass before aesthetic review."""
    image = Image.open(io.BytesIO(raw))
    expected = parse_size(expected_size)
    issues: list[dict] = []
    if image.size != expected:
        issues.append({
            "code": "wrong_dimensions", "severity": "error",
            "message": f"画布为 {image.width}×{image.height}，要求 {expected[0]}×{expected[1]}",
        })
    if min(image.size) < 1000:
        issues.append({"code": "low_resolution", "severity": "error", "message": "图片短边不足 1000px"})
    return {"ready": not issues, "score": 100 if not issues else 0, "issues": issues, "mode": "technical"}
