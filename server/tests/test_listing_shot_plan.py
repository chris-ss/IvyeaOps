"""套图美术指导 — shot-plan 策划层:JSON 解析/修复、归一化(主图优先+无字+张数夹取)、
结构化成功路径、畸形 JSON 回退(绝不报错)。"""
import asyncio
import json
import time

from app.routers import listing as L


def test_strip_json_variants():
    assert L._strip_json('```json\n{"images":[{"render_prompt":"x"}]}\n```')["images"]
    assert L._strip_json('Sure, here it is: {"a":1} done')["a"] == 1
    assert L._strip_json("not json at all") is None
    assert L._strip_json("") is None


def test_normalize_main_first_no_text_and_clamp():
    plan = {"style": {"palette": "warm"}, "product_lock": "keep shape", "images": [
        {"slot": "x", "role": "卖点", "callout": "30 Day", "text_on_image": True, "render_prompt": "a"},
        {"callout": "Waterproof", "text_on_image": True, "render_prompt": "b"},
        {"render_prompt": ""},  # dropped (no prompt)
    ]}
    n = L._normalize_shot_plan(plan, 0)
    assert len(n["images"]) == 2
    m = n["images"][0]
    assert m["slot"] == "main" and m["role"] == "主图"
    assert m["text_on_image"] is False and m["callout"] is None      # main never carries text
    assert n["images"][1]["callout"] == "Waterproof" and n["images"][1]["text_on_image"] is True
    # explicit count clamps
    big = {"images": [{"render_prompt": str(i)} for i in range(12)]}
    assert len(L._normalize_shot_plan(big, 5)["images"]) == 5
    # adaptive caps at 8
    assert len(L._normalize_shot_plan(big, 0)["images"]) == 8


def test_normalize_archetypes_and_show_product():
    plan = {"images": [
        {"slot": "x", "shot_type": "feature", "callout": "A", "render_prompt": "p"},
        {"shot_type": "scene", "headline": "Beautiful Footage", "render_prompt": "a landscape"},
        {"shot_type": "bogus", "render_prompt": "q"},   # invalid → defaulted
    ]}
    n = L._normalize_shot_plan(plan, 0)["images"]
    # main forced white_main, shows product, no text
    assert n[0]["shot_type"] == "white_main" and n[0]["show_product"] is True and n[0]["text_on_image"] is False
    # scene never carries the product (deterministic, not trusting the LLM)
    assert n[1]["shot_type"] == "scene" and n[1]["show_product"] is False
    assert n[1]["headline"] == "Beautiful Footage" and n[1]["text_on_image"] is True
    # invalid shot_type falls back to a valid one
    assert n[2]["shot_type"] in L._SHOT_TYPES


def _insert_project(pid: str):
    conn = L._db()
    now = time.time()
    conn.execute(
        "INSERT OR REPLACE INTO listing_projects "
        "(id,asin,marketplace,status,created_at,updated_at,scrape_data,analysis_data,copy_result) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (pid, "B0TEST", "US", "scraped", now, now,
         json.dumps({"title": "Test Bottle", "bullets": ["30 day battery", "waterproof IPX8"]}),
         json.dumps({"image_insights": "sleek matte black bottle"}),
         json.dumps({"titles": ["Test"], "bullets_a": ["30 Day Battery", "Waterproof IPX8"]})),
    )
    conn.commit()
    conn.close()


def _cleanup(pid: str):
    conn = L._db()
    conn.execute("DELETE FROM listing_projects WHERE id = ?", (pid,))
    conn.commit()
    conn.close()


def test_plan_image_set_structured(monkeypatch):
    pid = "test_shotplan_ok"
    _insert_project(pid)
    good = json.dumps({
        "style": {"palette": "warm minimal"}, "product_lock": "black bottle",
        "images": [
            {"slot": "main", "role": "主图", "render_prompt": "white bg studio bottle", "text_on_image": False},
            {"slot": "sub1", "role": "核心卖点", "callout": "30 Day Battery", "text_on_image": True,
             "text_pos": "top-right", "render_prompt": "bottle on a desk, warm light"},
        ],
    })

    async def fake_call(prompt, max_tokens=2000, web_search=True):
        return "```json\n" + good + "\n```"

    monkeypatch.setattr(L, "_call_ai", fake_call)
    try:
        res = asyncio.run(L.plan_image_set(pid, L.PlanImageSetReq(target_count=0), _user="t"))
        assert res["ok"] is True and res["fallback"] is False
        imgs = res["plan"]["images"]
        assert imgs[0]["slot"] == "main" and imgs[0]["text_on_image"] is False
        assert imgs[1]["callout"] == "30 Day Battery" and imgs[1]["text_pos"] == "top-right"
        # persisted to shot_plan
        conn = L._db()
        row = conn.execute("SELECT shot_plan FROM listing_projects WHERE id = ?", (pid,)).fetchone()
        conn.close()
        assert row["shot_plan"] and "main" in row["shot_plan"]
    finally:
        _cleanup(pid)


def test_plan_image_set_fallback_on_garbage(monkeypatch):
    pid = "test_shotplan_fb"
    _insert_project(pid)

    async def fake_call(prompt, max_tokens=2000, web_search=True):
        return "I'm sorry, I can't produce that."

    monkeypatch.setattr(L, "_call_ai", fake_call)
    try:
        res = asyncio.run(L.plan_image_set(pid, L.PlanImageSetReq(target_count=5), _user="t"))
        assert res["ok"] is True and res["fallback"] is True       # degraded, never errors
        assert len(res["plan"]["images"]) >= 1
        assert res["plan"]["images"][0]["slot"] == "main"
    finally:
        _cleanup(pid)
