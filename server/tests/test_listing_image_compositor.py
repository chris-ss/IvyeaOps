import io

from PIL import Image

from app.services import listing_image_compositor as C


def _image(size=(900, 600), color=(220, 225, 230), product=False) -> bytes:
    image = Image.new("RGB", size, color)
    if product:
        from PIL import ImageDraw
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle((220, 90, 680, 540), radius=35, fill=(25, 28, 31))
    output = io.BytesIO()
    image.save(output, "PNG")
    return output.getvalue()


def test_normalise_canvas_produces_exact_declared_size_without_stretching():
    out = C.normalise_canvas(_image(), "1600x1600", mode="contain")
    image = Image.open(io.BytesIO(out))
    assert image.size == (1600, 1600)
    assert C.technical_quality(out, "1600x1600")["ready"] is True


def test_white_background_product_composites_as_source_pixels():
    product = _image(color=(255, 255, 255), product=True)
    background = _image(size=(1200, 1200), color=(185, 194, 200))
    out = C.composite_product(background, product, "1600x1600", text_zone="top-left")
    image = Image.open(io.BytesIO(out)).convert("RGB")
    assert image.size == (1600, 1600)
    # Product is placed opposite the text zone and retains its near-black source colour.
    right = image.crop((800, 300, 1550, 1500))
    assert min(pixel[0] for pixel in right.getdata()) < 45


def test_technical_quality_rejects_wrong_provider_dimensions():
    qa = C.technical_quality(_image(size=(1536, 1024)), "1600x1600")
    assert qa["ready"] is False
    assert qa["issues"][0]["code"] == "wrong_dimensions"


def test_primary_product_cutout_excludes_disconnected_accessory():
    from PIL import ImageDraw
    image = Image.new("RGB", (900, 600), "white")
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((50, 70, 500, 560), radius=35, fill=(24, 30, 28))
    draw.rectangle((730, 180, 850, 330), fill=(35, 55, 170))
    raw = io.BytesIO()
    image.save(raw, "PNG")
    cutout = C.primary_product_cutout(raw.getvalue())
    assert cutout.width < 600
    assert cutout.height > 400
