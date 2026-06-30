"""Home dashboard provider routing and cache isolation."""
from __future__ import annotations

import asyncio
import sqlite3

import app.routers.home as home
from app.services import asin_pulse_service, sellersprite_service


def _use_temp_home_db(tmp_path, monkeypatch) -> None:
    path = str(tmp_path / "home.sqlite3")
    monkeypatch.setattr(home, "_db_path", lambda: path)
    home._INITED.discard(path)


def _pulse_payload(asin: str, marketplace: str, *, price: float, source: str) -> dict:
    return {
        "asin": asin,
        "marketplace": marketplace,
        "data_source": source,
        "error": None,
        "title": f"{source} product",
        "brand": "Ivyea",
        "image": None,
        "price": price,
        "bsr": 10,
        "bsr_category": "Test",
        "sub_rank": 2,
        "sub_category": "Sub",
        "est_sales": 500,
        "rating": 4.6,
        "review_count": 100,
        "variations": 1,
        "coupon": None,
        "deal": None,
        "inventory": None,
    }


def test_legacy_home_database_migrates_existing_rows_to_sorftime(tmp_path, monkeypatch):
    path = tmp_path / "home.sqlite3"
    with sqlite3.connect(path) as conn:
        conn.execute(
            "CREATE TABLE home_keyword (id TEXT PRIMARY KEY, keyword TEXT NOT NULL, "
            "marketplace TEXT NOT NULL, label TEXT NOT NULL DEFAULT '', ts INTEGER NOT NULL, "
            "data TEXT NOT NULL DEFAULT '', data_ts INTEGER)"
        )
        conn.execute(
            "INSERT INTO home_keyword (id,keyword,marketplace,label,ts,data,data_ts) "
            "VALUES ('US:yoga mat','yoga mat','US','',1,'',NULL)"
        )
    monkeypatch.setattr(home, "_db_path", lambda: str(path))
    home._INITED.discard(str(path))

    with home._connect() as conn:
        row = conn.execute(
            "SELECT data_source FROM home_keyword WHERE id='US:yoga mat'",
        ).fetchone()
        columns = {item["name"] for item in conn.execute("PRAGMA table_info(home_snapshot)")}

    assert row["data_source"] == "sorftime"
    assert "data_source" in columns


def test_sellersprite_asin_dispatch_and_snapshot_isolation(tmp_path, monkeypatch):
    _use_temp_home_db(tmp_path, monkeypatch)
    seen: list[str] = []

    async def seller(asin: str, marketplace: str):
        seen.append("sellersprite")
        return _pulse_payload(asin, marketplace, price=29.99, source="sellersprite")

    async def sorftime(asin: str, marketplace: str):
        seen.append("sorftime")
        return _pulse_payload(asin, marketplace, price=19.99, source="sorftime")

    monkeypatch.setattr(sellersprite_service, "home_asin_pulse", seller)
    monkeypatch.setattr(asin_pulse_service, "fetch_asin_pulse", sorftime)

    home.add_watch(home.WatchIn(
        asin="B07XNTHHBP", marketplace="US", kind="competitor", data_source="sellersprite",
    ), _user="test")
    result = asyncio.run(home.pulse(home.PulseReq(
        asin="B07XNTHHBP", marketplace="US", data_source="sellersprite",
    ), _user="test"))

    assert seen == ["sellersprite"]
    assert result["current"]["price"] == 29.99
    assert len(home.watch_snapshots("sellersprite", _user="test")) == 1
    assert home.watch_snapshots("sorftime", _user="test") == []
    assert home.alerts("sorftime", _user="test") == []


def test_keyword_watch_and_cache_are_source_isolated(tmp_path, monkeypatch):
    _use_temp_home_db(tmp_path, monkeypatch)

    async def seller(keyword: str, marketplace: str):
        return {
            "keyword": keyword,
            "marketplace": marketplace,
            "data_source": "sellersprite",
            "detail": {"月搜索量": 1234, "推荐cpc竞价": 2.5},
            "detail_error": None,
            "trend": {"data": [{"searchVolume": 1000}, {"searchVolume": 1234}]},
            "trend_error": None,
        }

    monkeypatch.setattr(sellersprite_service, "home_keyword_pulse", seller)

    sf = home.add_keyword(home.KeywordIn(
        keyword="wireless earbuds", marketplace="US", data_source="sorftime",
    ), _user="test")
    ss = home.add_keyword(home.KeywordIn(
        keyword="wireless earbuds", marketplace="US", data_source="sellersprite",
    ), _user="test")
    assert sf["id"] != ss["id"]

    asyncio.run(home.keyword_pulse(home.KeywordPulseReq(
        keyword="wireless earbuds", marketplace="US", data_source="sellersprite",
    ), _user="test"))

    seller_rows = home.list_keywords("sellersprite", _user="test")
    sorftime_rows = home.list_keywords("sorftime", _user="test")
    assert seller_rows[0]["data"]["data_source"] == "sellersprite"
    assert sorftime_rows[0]["data"] is None


def test_category_uses_selected_source_and_isolates_cache(tmp_path, monkeypatch):
    _use_temp_home_db(tmp_path, monkeypatch)
    seen: list[str] = []

    async def seller(query: str, marketplace: str, mode: str):
        seen.append("sellersprite")
        return {
            "query": query,
            "marketplace": marketplace,
            "mode": mode,
            "data_source": "sellersprite",
            "error": None,
            "node_id": "689995011",
            "category_name": "Electronics:Preamplifiers",
            "source": "asin",
            "summary": {"count": 1, "avg_price": 69.99, "total_sales": 640},
            "bands": [],
            "top": [{"rank": 1, "asin": "B07XNTHHBP"}],
        }

    monkeypatch.setattr(sellersprite_service, "home_category", seller)
    result = asyncio.run(home.category(home.CategoryReq(
        query="B07XNTHHBP", marketplace="US", mode="category", data_source="sellersprite",
    ), _user="test"))

    assert seen == ["sellersprite"]
    assert result["data_source"] == "sellersprite"
    assert home.category_result(
        "B07XNTHHBP", "US", "category", "sellersprite", _user="test",
    )["cached"]["summary"]["total_sales"] == 640
    assert home.category_result(
        "B07XNTHHBP", "US", "category", "sorftime", _user="test",
    )["cached"] is None


def test_market_baseline_uses_sellersprite_without_sorftime_fallback(tmp_path, monkeypatch):
    _use_temp_home_db(tmp_path, monkeypatch)
    seen: list[str] = []

    async def seller(query: str, marketplace: str):
        seen.append("sellersprite")
        return {
            "query": query,
            "marketplace": marketplace,
            "data_source": "sellersprite",
            "search_volume": 330028,
            "total_sales": 7009,
            "avg_price": 27.99,
            "node_id": "689995011",
            "error": None,
        }

    async def forbidden(*args, **kwargs):
        raise AssertionError("Sorftime must not run for a SellerSprite request")

    monkeypatch.setattr(sellersprite_service, "home_market_metrics", seller)
    monkeypatch.setattr(home.market_traffic_service, "fetch_market_metrics", forbidden)

    created = asyncio.run(home.add_market_watch(home.MarketWatchIn(
        query="wireless earbuds", marketplace="US", data_source="sellersprite",
    ), _user="test"))
    assert created["id"].startswith("sellersprite:")
    assert seen == ["sellersprite"]
    assert len(home.list_market_watch("sellersprite", _user="test")) == 1
    assert home.list_market_watch("sorftime", _user="test") == []

    series = home.market_series(
        "wireless earbuds", "US", "sellersprite", _user="test",
    )
    assert series["data_source"] == "sellersprite"
    assert series["market"][0]["search_volume"] == 330028
    assert home.market_series(
        "wireless earbuds", "US", "sorftime", _user="test",
    )["market"] == []


def test_sellersprite_daily_backfill_is_explicitly_unsupported(tmp_path, monkeypatch):
    _use_temp_home_db(tmp_path, monkeypatch)
    result = asyncio.run(home.market_daily_backfill(home.DailyBackfillReq(
        query="wireless earbuds",
        marketplace="US",
        category="B07XNTHHBP",
        data_source="sellersprite",
    ), _user="test"))
    assert result["data_source"] == "sellersprite"
    assert result["filled"] == 0
    assert "不提供" in result["error"]


def test_sellersprite_keyword_normalization():
    detail = sellersprite_service._normalize_keyword_detail({
        "keywords": "wireless earbuds",
        "searches": 330028,
        "products": 25670,
        "bid": 3.39,
        "purchaseRate": 0.0305,
    })
    assert detail is not None
    assert detail["月搜索量"] == 330028
    assert detail["推荐cpc竞价"] == 3.39
    assert detail["purchaseRate"] == 0.0305
    assert 0 <= detail["competitionIndex"] <= 100

    trend = sellersprite_service._normalize_keyword_trend([
        {"time": "2026年04月", "search": 100},
        {"time": "2026年05月", "search": 120},
    ])
    assert [point["searchVolume"] for point in trend["data"]] == [100, 120]
