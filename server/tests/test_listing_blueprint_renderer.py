import io

from PIL import Image, ImageDraw

from app.services.listing_blueprint_renderer import render_blueprint


def _raw(color, size=(700, 700)) -> bytes:
    image = Image.new("RGB", size, color)
    draw = ImageDraw.Draw(image)
    draw.ellipse((120, 130, 560, 570), fill=(min(255, color[0] + 35), color[1], color[2]))
    output = io.BytesIO()
    image.save(output, "JPEG", quality=90)
    return output.getvalue()


def _product() -> bytes:
    image = Image.new("RGB", (700, 700), "white")
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((130, 80, 500, 640), radius=45, fill=(28, 42, 34))
    draw.ellipse((245, 165, 385, 305), fill=(8, 12, 10), outline=(120, 150, 135), width=12)
    # Disconnected accessory must not follow the product into scene layouts.
    draw.rectangle((570, 120, 650, 230), fill=(30, 60, 180))
    output = io.BytesIO()
    image.save(output, "PNG")
    return output.getvalue()


def test_all_structured_blueprints_render_exact_canvas():
    scenes = [
        _raw((55 + index * 10, 105 + index * 8, 72 + index * 5))
        for index in range(6)
    ]
    counts = {
        "media_proof_split": 2,
        "connectivity_diagram": 1,
        "environmental_proof": 1,
        "coverage_diagram": 1,
        "speed_comparison": 1,
        "day_night_split": 2,
        "use_case_mosaic": 6,
    }
    for blueprint, count in counts.items():
        output = render_blueprint(
            scenes[:count], _product(), "640x640", blueprint=blueprint,
            labels=["Wi-Fi", "0.1s Trigger", "IP67", "Night Vision", "Farm", "Home"],
        )
        image = Image.open(io.BytesIO(output))
        assert image.size == (640, 640), blueprint
        assert image.convert("RGB").getbbox(), blueprint
