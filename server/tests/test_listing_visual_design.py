"""3C 套图设计系统：出场光谱、版式编译、配件排除、文案锚与复核降级。"""
import asyncio

from app.routers import listing as L
from app.routers.listing import images as I
from app.routers.listing import visuals as V


def _plan(images, **extra):
    return V._normalize_shot_plan({"images": images, **extra}, 0)


def test_presence_defaults_and_quota_rebalance():
    # 7 张全部声明 hero → 配额把第 3 个及之后的 hero 降级为 supporting
    plan = _plan([
        {"shot_type": t, "product_presence": "hero", "render_prompt": "x", "evidence": "f"}
        for t in ("white_main", "hero_feature", "lifestyle", "detail", "comparison", "specs", "trust")
    ])
    presences = [img["product_presence"] for img in plan["images"]]
    assert presences.count("hero") <= 2
    # ≥5 张必须至少 1 张 absent/environmental（配额自动转换）
    assert any(p in ("absent", "environmental") for p in presences)


def test_absent_card_has_no_product_and_layout_prompt():
    plan = _plan([
        {"shot_type": "white_main", "render_prompt": "w"},
        {"shot_type": "comparison", "product_presence": "absent", "layout": "split_compare",
         "headline": "Day And Night Clarity", "big_number": "0.1s", "evidence": "trigger fact"},
    ])
    card = plan["images"][1]
    assert card["show_product"] is False and card["product_presence"] == "absent"
    prompt = card["render_prompt"]
    assert "does NOT appear" in prompt                      # 产品缺席指令
    assert "Two-panel comparison layout" in prompt          # 版式家族段落
    assert '"big_number": "0.1s"' in prompt                 # 大数字进文案合同
    bound = V._bind_reference_templates(plan, "p", {"reference_images": ["https://img/w.jpg"],
                                                    "white_product_source": "https://img/w.jpg"}, "gallery")
    assert bound["images"][1]["product_source_url"] == ""   # absent 卡不绑产品真值
    assert bound["images"][0]["product_source_url"]         # 主图仍绑


def test_headline_fragment_is_blocked_by_quality_gate():
    plan = _plan([
        {"shot_type": "white_main", "render_prompt": "w"},
        {"shot_type": "hero_feature", "headline": "[Trigger Speed]: A", "evidence": "f",
         "text_on_image": True},
    ])
    assert any(i["code"] == "headline_fragment" for i in plan["quality"]["issues"])


def test_fidelity_preamble_excludes_bundle_accessories():
    # 非 in_box：捆绑参考图里的散件（SD 卡等）明确排除
    p = I._fidelity_preamble("scene prompt", 1, "product", presence="supporting",
                             product_scale=0.3, include_accessories=False)
    assert "IGNORE the loose extras" in p and "memory cards" in p
    # in_box：要求完整套装
    p2 = I._fidelity_preamble("box prompt", 1, "product", presence="hero",
                              product_scale=0.7, include_accessories=True)
    assert "every item that belongs to the purchased set" in p2
    # environmental：产品占比小写进指令
    p3 = I._fidelity_preamble("scene", 1, "product", presence="environmental", product_scale=0.1)
    assert "SMALL" in p3
    # absent（无参考）不加保真前置
    assert I._fidelity_preamble("pure", 0, "product", presence="absent") == "pure"


def test_template_story_binds_dual_reference():
    plan = _plan([
        {"shot_type": "white_main", "render_prompt": "w"},
        {"shot_type": "hero_feature", "evidence": "f", "render_prompt": "h"},
    ], template_story=[
        {"index": 2, "url": "https://img/t2.jpg", "shot_type": "hero_feature",
         "product_presence": "supporting", "layout": "poster_hero",
         "visual_structure": "标题带+产品右置", "role": "核心利益"},
    ])
    bound = V._bind_reference_templates(plan, "p", {
        "reference_images": ["https://img/w.jpg", "https://img/t2.jpg"],
        "white_product_source": "https://img/w.jpg",
    }, "gallery")
    assert bound["template_mode"] is True
    assert bound["images"][0]["template_url"] == ""          # 白底主图永不绑模板
    assert bound["images"][1]["template_url"] == "https://img/t2.jpg"
    assert bound["images"][1]["template_index"] == 2


def test_review_degrades_to_manual_when_vision_unavailable(monkeypatch):
    import io
    from PIL import Image
    raw = io.BytesIO()
    Image.new("RGB", (1600, 1600), "white").save(raw, "PNG")

    async def fake_fetch(client, url):
        return raw.getvalue()

    async def fake_review(candidate, source, body):
        return {"available": False, "reason": "visual_review_provider_unconfigured"}

    monkeypatch.setattr(V, "_fetch_image_bytes", fake_fetch)
    monkeypatch.setattr(V, "_render_vision_review", fake_review)
    result = asyncio.run(V.review_render_core("p", L.ReviewRenderReq(
        url="candidate", source_url="source", show_product=True,
        product_presence="supporting",
    )))
    # 机审不可用：不再 error 卡死，降级为人工复核门槛
    assert result["ready"] is True
    assert result["manual_visual_review_required"] is True
    assert any(i["code"] == "product_fidelity_unverified" and i["severity"] == "warning"
               for i in result["issues"])


def test_environmental_presence_lowers_fidelity_floor(monkeypatch):
    import io
    from PIL import Image
    raw = io.BytesIO()
    Image.new("RGB", (1600, 1600), "white").save(raw, "PNG")

    async def fake_fetch(client, url):
        return raw.getvalue()

    async def fake_review(candidate, source, body):
        return {"available": True, "result": {
            "scores": {"product_fidelity": 85, "realism": 92, "composition": 92,
                       "typography": 95, "copy_accuracy": 100, "commercial_readiness": 90},
            "copy_check": {"exact": True, "unexpected_copy": False},
            "fatal_issues": [], "improvements": [], "verdict": "pass",
        }}

    monkeypatch.setattr(V, "_fetch_image_bytes", fake_fetch)
    monkeypatch.setattr(V, "_render_vision_review", fake_review)
    # 85 分：supporting 卡（门槛 92）不通过，environmental 卡（门槛 80）通过
    failed = asyncio.run(V.review_render_core("p", L.ReviewRenderReq(
        url="c", source_url="s", show_product=True, product_presence="supporting")))
    assert any(i["code"] == "product_fidelity_failed" for i in failed["issues"])
    passed = asyncio.run(V.review_render_core("p", L.ReviewRenderReq(
        url="c", source_url="s", show_product=True, product_presence="environmental")))
    assert not any(i["code"] == "product_fidelity_failed" for i in passed["issues"])


def test_fallback_extracts_complete_headlines_not_fragments():
    headline, subline, number = V._extract_fallback_copy(
        "[Quiet Night Coverage] [Night Vision]: Low-glow infrared LEDs record nocturnal movement up to 75 ft."
    )
    assert headline == "Quiet Night Coverage"
    assert not headline.endswith(":")
    assert number  # 75 ft 之类的规格锚
    h2, s2, n2 = V._extract_fallback_copy("CATCH FAST MOVEMENT: A 0.1s motion response keeps you ready.")
    assert h2 == "Catch Fast Movement"
    assert n2 == "0.1s"


def test_fallback_plan_uses_varied_layouts_and_presences():
    class Row(dict):
        def __getitem__(self, key):
            return dict.get(self, key)
        def keys(self):
            return dict.keys(self)
    row = Row(asin="B0TEST", marketplace="US", copy_result=None, title=None, bullets=None)
    plan = V._shot_plan_fallback(row, {"title": "Trail Camera", "bullets": [
        "[Detailed Scouting]: Capture 36MP photos to review deer trails",
        "[Night Vision]: Low-glow infrared records movement up to 75 ft",
    ]}, {}, 7, "", "gallery")
    layouts = [img["layout"] for img in plan["images"]]
    presences = [img["product_presence"] for img in plan["images"]]
    assert len(set(layouts)) >= 5                # 版式多样
    assert presences.count("hero") <= 2          # 出场配额
    assert any(p == "absent" for p in presences)
    for img in plan["images"][1:]:
        h = str(img.get("headline") or "")
        assert not h.startswith("[") and not h.endswith(":")  # 无碎片标题
