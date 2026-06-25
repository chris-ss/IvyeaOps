"""SellerSprite MCP client + data pipelines for 市场调研.

SellerSprite's open platform is an MCP server (streamable HTTP) — same shape as
Sorftime: POST JSON-RPC to https://mcp.sellersprite.com/mcp?secret-key=<key>,
responses come back as SSE (`data: {...}`). Each tool returns
`{"code":"OK","message":"成功","data":...}` inside the MCP text content. The
collected `data` flows straight into ai_synthesis_service (data-driven prompt),
so no field-by-field mapping is needed.

Tools used (verified against the live MCP):
  keyword: keyword_research_trends, aba_research_trend
  asin:    asin_detail, asin_sales_trend, traffic_keyword_stat
"""
from __future__ import annotations

import datetime
import json as _json
from typing import Any, Awaitable, Callable

import httpx

_BASE = "https://mcp.sellersprite.com/mcp"
_HEADERS = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
_TOOL_TIMEOUT = 40.0
_CONN_TIMEOUT = 10.0

ProgressFn = Callable[[str, int, int], Awaitable[None]]


def _key() -> str:
    from app.core import hub_settings
    return str(hub_settings.get("sellersprite_key") or "").strip()


def _url() -> str:
    return f"{_BASE}?secret-key={_key()}"


def recent_month() -> str:
    """Most recently completed month as yyyyMM (SellerSprite data lags ~1 month)."""
    return (datetime.date.today().replace(day=1) - datetime.timedelta(days=1)).strftime("%Y%m")


def parse_sse(text: str) -> dict:
    """Pull the JSON-RPC object out of an SSE (`data: {...}`) or plain JSON body."""
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("data:"):
            raw = line[5:].strip()
            if raw:
                try:
                    return _json.loads(raw)
                except Exception:
                    pass
    try:
        return _json.loads(text)
    except Exception:
        return {}


async def _initialize(client: httpx.AsyncClient) -> None:
    try:
        await client.post(_url(), headers=_HEADERS, json={
            "jsonrpc": "2.0", "id": 0, "method": "initialize",
            "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                       "clientInfo": {"name": "IvyeaOps", "version": "1.0"}},
        })
    except Exception:
        pass  # best-effort; tools/call still works on most servers


async def _call_tool(client: httpx.AsyncClient, name: str, args: dict, call_id: int = 1) -> Any:
    if not _key():
        raise RuntimeError("卖家精灵 key 未配置（系统配置 → 数据源 → 卖家精灵 Key）")
    r = await client.post(_url(), headers=_HEADERS, json={
        "jsonrpc": "2.0", "id": call_id, "method": "tools/call",
        "params": {"name": name, "arguments": args},
    })
    body = parse_sse(r.text)
    if body.get("error"):
        raise RuntimeError(f"{name}: {body['error']}")
    result = body.get("result") or {}
    content = result.get("content") or []
    text = content[0].get("text", "") if content and isinstance(content[0], dict) else ""
    if result.get("isError"):
        raise RuntimeError(f"{name}: {(text or '工具返回错误')[:200]}")
    # text content is the tool payload: {"code":"OK","data":...}
    try:
        parsed = _json.loads(text) if text else {}
    except Exception:
        return {"_raw": text[:4000]}
    code = str(parsed.get("code") or "")
    if code and code != "OK":
        raise RuntimeError(f"{name} {code}: {parsed.get('message', '')}")
    return parsed.get("data", parsed)


async def _run_steps(steps: list[tuple[str, str, dict]], progress: ProgressFn) -> tuple[dict, list[str]]:
    data: dict[str, Any] = {}
    errors: list[str] = []
    total = len(steps)
    async with httpx.AsyncClient(timeout=httpx.Timeout(_TOOL_TIMEOUT, connect=_CONN_TIMEOUT)) as client:
        await _initialize(client)
        for i, (label, name, args) in enumerate(steps):
            await progress(label, i, total)
            try:
                data[label] = await _call_tool(client, name, args, i + 1)
            except Exception as exc:  # noqa: BLE001 — collect, don't abort the whole run
                errors.append(f"{label}: {exc}")
    await progress("完成", total, total)
    return data, errors


async def keyword_pipeline(query: str, marketplace: str, progress: ProgressFn) -> tuple[dict, list[str]]:
    month = recent_month()
    return await _run_steps([
        ("关键词搜索/购买趋势", "keyword_research_trends",
         {"marketplace": marketplace, "keyword": query, "month": month}),
        ("ABA 排名趋势", "aba_research_trend",
         {"marketplace": marketplace, "keyword": query, "timeGranularity": "month"}),
    ], progress)


async def asin_pipeline(asin: str, marketplace: str, progress: ProgressFn) -> tuple[dict, list[str]]:
    month = recent_month()
    return await _run_steps([
        ("商品详情", "asin_detail", {"marketplace": marketplace, "asin": asin}),
        ("销量趋势", "asin_sales_trend", {"marketplace": marketplace, "asin": asin}),
        ("流量关键词概览", "traffic_keyword_stat", {"marketplace": marketplace, "asin": asin, "month": month}),
    ], progress)
