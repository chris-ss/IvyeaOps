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

from typing import Any, Awaitable, Callable

import httpx

_BASE = "https://api.sellersprite.com/v1"
_TIMEOUT = 30.0

ProgressFn = Callable[[str, int, int], Awaitable[None]]


def _key() -> str:
    from app.core import hub_settings
    return str(hub_settings.get("sellersprite_key") or "").strip()


async def _post(path: str, payload: dict) -> Any:
    key = _key()
    if not key:
        raise RuntimeError("卖家精灵 key 未配置（系统配置 → 图片/数据源 → 卖家精灵 Key）")
    async with httpx.AsyncClient(timeout=_TIMEOUT) as c:
        r = await c.post(_BASE + path, json=payload,
                         headers={"Content-Type": "application/json", "secret-key": key})
    if r.status_code in (401, 403):
        raise RuntimeError("卖家精灵 key 无效或无权限")
    if r.status_code != 200:
        raise RuntimeError(f"SellerSprite HTTP {r.status_code}: {r.text[:200]}")
    return r.json()


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


async def keyword_pipeline(query: str, marketplace: str, progress: ProgressFn) -> tuple[dict, list[str]]:
    return await _run_steps([
        ("关键词流量", "/traffic/keyword", {"keyword": query, "marketplace": marketplace}),
        ("关键词拓展", "/keyword/research", {"keyword": query, "marketplace": marketplace, "page": 1, "size": 30}),
    ], progress)


async def asin_pipeline(asin: str, marketplace: str, progress: ProgressFn) -> tuple[dict, list[str]]:
    return await _run_steps([
        ("ASIN 关键词反查", "/product/keyword", {"asin": asin, "marketplace": marketplace, "page": 1, "size": 30}),
        ("竞品词重叠", "/product/keywords/competitor", {"asins": [asin], "marketplace": marketplace}),
    ], progress)
