"""SellerSprite REST data pipelines for 市场调研 / 打法.

Mirrors sorftime_service's two-phase contract — keyword_pipeline / asin_pipeline
return (data, errors) and drive the same on_progress(step, done, total) callback —
so a board can swap data sources without touching its SSE/synthesis code. The
collected data dict is fed straight to ai_synthesis_service (data-driven prompt),
so no field-by-field mapping is required.

API surface reused from server/tools/sellersprite_mcp.py:
  POST /traffic/keyword            关键词流量/搜索量/趋势
  POST /keyword/research           关键词拓展（相关词）
  POST /product/keyword            ASIN 关键词反查
  POST /product/keywords/competitor 竞品词重叠
Auth: header `secret-key: <sellersprite_key>`.
"""
from __future__ import annotations

import datetime
from typing import Any, Awaitable, Callable

import httpx

_BASE = "https://api.sellersprite.com/v1"
_TIMEOUT = 30.0

ProgressFn = Callable[[str, int, int], Awaitable[None]]


def _key() -> str:
    from app.core import hub_settings
    return str(hub_settings.get("sellersprite_key") or "").strip()


def recent_month() -> str:
    """Most recently completed month as yyyyMM (SellerSprite traffic data lags ~1 month)."""
    first_of_this = datetime.date.today().replace(day=1)
    last_month = first_of_this - datetime.timedelta(days=1)
    return last_month.strftime("%Y%m")


async def _post(path: str, payload: dict) -> Any:
    """POST a SellerSprite endpoint. NOTE: SellerSprite returns HTTP 200 even on
    errors — the real status is in the body's `code` (success == "OK"), so we must
    inspect the body, not the HTTP status, or an error would be fed to the report
    as if it were data."""
    key = _key()
    if not key:
        raise RuntimeError("卖家精灵 key 未配置（系统配置 → 图片生成服务 / 数据源 → 卖家精灵 Key）")
    async with httpx.AsyncClient(timeout=_TIMEOUT) as c:
        r = await c.post(_BASE + path, json=payload,
                         headers={"Content-Type": "application/json", "secret-key": key})
    try:
        body = r.json()
    except Exception:
        raise RuntimeError(f"卖家精灵返回非 JSON（HTTP {r.status_code}）：{r.text[:160]}")
    code = str(body.get("code") or "")
    if code and code != "OK":
        msg = str(body.get("message") or "")
        if code == "ERROR_UNAUTHORIZED" or "未授权" in msg:
            raise RuntimeError("卖家精灵未授权：该 key 没有开放平台 API 权限——请在 "
                               "open.sellersprite.com 申请 API 并由客服开通对应接口")
        raise RuntimeError(f"卖家精灵 {code}：{msg}")
    if r.status_code != 200:
        raise RuntimeError(f"卖家精灵 HTTP {r.status_code}：{r.text[:160]}")
    return body.get("data", body)


async def _run_steps(steps: list[tuple[str, str, dict]], progress: ProgressFn) -> tuple[dict, list[str]]:
    data: dict[str, Any] = {}
    errors: list[str] = []
    total = len(steps)
    for i, (label, path, payload) in enumerate(steps):
        await progress(label, i, total)
        try:
            data[label] = await _post(path, payload)
        except Exception as exc:  # noqa: BLE001 — collect, don't abort the whole run
            errors.append(f"{label}: {exc}")
    await progress("完成", total, total)
    return data, errors


# /traffic/source (MCP traffic_source) returns a keyword/ASIN's traffic keywords:
# search vs ad split, source breakdown, asinInfo. `includeKeywords` accepts a
# keyword or an ASIN, so it covers both modes. (Verified endpoint + params per
# open.sellersprite.com/api/17.)
async def keyword_pipeline(query: str, marketplace: str, progress: ProgressFn) -> tuple[dict, list[str]]:
    return await _run_steps([
        ("关键词流量来源", "/traffic/source",
         {"marketplace": marketplace, "date": recent_month(), "includeKeywords": query, "page": 1, "size": 50}),
    ], progress)


async def asin_pipeline(asin: str, marketplace: str, progress: ProgressFn) -> tuple[dict, list[str]]:
    return await _run_steps([
        ("ASIN 流量来源", "/traffic/source",
         {"marketplace": marketplace, "date": recent_month(), "includeKeywords": asin, "page": 1, "size": 50}),
    ], progress)
