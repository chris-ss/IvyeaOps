"""分析工具 5 个面板端点：结果持久化到历史 + 自定义 prompt 真正传给合成层。"""
from __future__ import annotations

import asyncio
import json

import app.routers.deep_analysis as da
from app.services import ai_synthesis_service, sif_service


def test_keyword_endpoint_saves_structured_history(tmp_path, monkeypatch):
    monkeypatch.setattr(da, "_history_db_path", lambda: str(tmp_path / "dh.sqlite3"))

    async def fake_kw(q, c, a):
        assert a == "B0COMPARE1"          # 对标 ASIN 透传
        return {"detail": {"月搜索量": 1000}, "extends": []}

    monkeypatch.setattr(sif_service, "keyword_competition", fake_kw)

    res = asyncio.run(da.keyword_competition(
        da.KeywordReq(keyword="yoga mat", country="US", asin="B0COMPARE1")))
    assert res["ok"] is True

    hist = da.get_history(_user="t")
    assert len(hist) == 1
    e = hist[0]
    assert e["tool"] == "keyword" and e["provider"] == "sorftime" and e["query"] == "yoga mat"
    parsed = json.loads(e["report"])   # report 存的是结构化 JSON
    assert parsed["detail"]["月搜索量"] == 1000


def test_traffic_endpoint_saves_structured_history(tmp_path, monkeypatch):
    monkeypatch.setattr(da, "_history_db_path", lambda: str(tmp_path / "dh.sqlite3"))

    async def fake_traffic(asin, country):
        return {"trend": {"w1": 10}}

    monkeypatch.setattr(sif_service, "traffic_anomaly", fake_traffic)

    res = asyncio.run(da.traffic_diagnosis(da.TrafficReq(asin="B0TESTASIN", country="US")))
    assert res["ok"] is True
    hist = da.get_history(_user="t")
    assert len(hist) == 1 and hist[0]["tool"] == "traffic"
    assert json.loads(hist[0]["report"])["trend"]["w1"] == 10


async def _drain_sse(resp) -> str:
    chunks = []
    async for chunk in resp.body_iterator:
        chunks.append(chunk if isinstance(chunk, str) else chunk.decode())
    return "".join(chunks)


def test_reviews_sse_uses_custom_prompt_and_saves_history(tmp_path, monkeypatch):
    monkeypatch.setattr(da, "_history_db_path", lambda: str(tmp_path / "dh.sqlite3"))
    seen = {}

    async def fake_native(mode, query, marketplace, prompt_override=None):
        seen["prompt"] = prompt_override
        yield ("_attempt", "hermes")
        yield ("hermes", "# 评论聚类\n| 主题 | 占比 |")

    monkeypatch.setattr(ai_synthesis_service, "synthesize_native", fake_native)

    resp = asyncio.run(da.review_clustering(da.ReviewsReq(asin="B0TESTASIN", country="US")))
    body = asyncio.run(_drain_sse(resp))
    assert '"type": "done"' in body
    # 修复点：评论聚类的专用 prompt 必须真正传给合成层（此前是死代码）
    assert seen["prompt"] and "聚类" in seen["prompt"] and "B0TESTASIN" in seen["prompt"]

    hist = da.get_history(_user="t")
    assert len(hist) == 1
    e = hist[0]
    assert e["tool"] == "reviews" and e["provider"] == "hermes"
    assert e["report"].startswith("# 评论聚类")


def test_listing_rewrite_sse_prompt_carries_fields_and_style(tmp_path, monkeypatch):
    monkeypatch.setattr(da, "_history_db_path", lambda: str(tmp_path / "dh.sqlite3"))
    seen = {}

    async def fake_native(mode, query, marketplace, prompt_override=None):
        seen["prompt"] = prompt_override
        yield ("hermes", "# 改写结果")

    monkeypatch.setattr(ai_synthesis_service, "synthesize_native", fake_native)

    resp = asyncio.run(da.listing_rewrite(da.ListingRewriteReq(
        asins=["B0AAA", "B0BBB"], marketplace="US", fields=["title", "qa"], style="luxury")))
    asyncio.run(_drain_sse(resp))
    # 修复点：用户选的字段与风格必须体现在 prompt 里（此前选什么都不影响输出）
    assert seen["prompt"] and "title, qa" in seen["prompt"] and "luxury" in seen["prompt"]
    assert "B0AAA, B0BBB" in seen["prompt"]

    hist = da.get_history(_user="t")
    assert len(hist) == 1 and hist[0]["tool"] == "listing_rewrite"


def test_sse_error_does_not_save_history(tmp_path, monkeypatch):
    monkeypatch.setattr(da, "_history_db_path", lambda: str(tmp_path / "dh.sqlite3"))

    async def fake_native(mode, query, marketplace, prompt_override=None):
        yield ("error", "hermes 不可用")

    monkeypatch.setattr(ai_synthesis_service, "synthesize_native", fake_native)

    resp = asyncio.run(da.review_clustering(da.ReviewsReq(asin="B0TESTASIN", country="US")))
    body = asyncio.run(_drain_sse(resp))
    assert '"type": "error"' in body
    assert da.get_history(_user="t") == []
