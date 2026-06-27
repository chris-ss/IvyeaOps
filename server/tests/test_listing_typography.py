"""文字排版独立化 — Pillow 叠字:产出合法图、指定区域确有文字像素、空文案 no-op。"""
import io

from PIL import Image

from app.services import listing_typography as T


def _blank(w=1024, h=1024, color=(255, 255, 255)) -> bytes:
    b = io.BytesIO()
    Image.new("RGB", (w, h), color).save(b, "PNG")
    return b.getvalue()


def _dark_pixels(im: Image.Image, box, thresh=240) -> int:
    band = im.crop(box).convert("L")
    return sum(1 for p in band.getdata() if p < thresh)


def test_overlay_renders_text_bottom():
    out = T.overlay_callout(_blank(), "30天超长续航 30-Day Battery", "bottom-center")
    im = Image.open(io.BytesIO(out))
    assert im.size == (1024, 1024) and im.mode == "RGB"
    assert _dark_pixels(im, (100, 850, 924, 1000)) > 500     # plate + glyphs present


def test_overlay_top_right_region():
    out = T.overlay_callout(_blank(), "Waterproof", "top-right")
    im = Image.open(io.BytesIO(out))
    assert _dark_pixels(im, (520, 30, 1010, 210)) > 300


def test_overlay_empty_is_noop():
    b = _blank()
    assert T.overlay_callout(b, "") == b
    assert T.overlay_callout(b, "   ") == b


def test_font_loader_never_crashes():
    # NotoCJK exists on this box; even on a font-less host _load_font must return something
    assert T._load_font(40) is not None
