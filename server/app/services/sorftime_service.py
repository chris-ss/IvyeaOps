"""Sorftime MCP HTTP client + two-phase data pipelines.

Keyword pipeline  (10 calls, 2 phases):
  Phase 1 (concurrent): keyword_detail, keyword_trend, keyword_extends,
                         keyword_search_results, category_search_from_product_name,
                         similar_product_feature
  Phase 2 (depends on phase 1): product_detail×2, potential_product,
                                  category_report (top-100 products in category)

ASIN pipeline (8 calls, 2 phases):
  Phase 1 (concurrent): product_report, product_trend, product_traffic_terms,
                         product_reviews, product_variations
  Phase 2 (depends on main keyword from phase 1): keyword_detail, keyword_search_results,
                                                   competitor_product_keywords
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Callable, Coroutine, Dict, List, Optional, Tuple

import httpx

_log = logging.getLogger(__name__)

_SORFTIME_BASE = "https://mcp.sorftime.com"

_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
}

_TOOL_TIMEOUT = 30.0
_CONN_TIMEOUT = 10.0


def _url() -> str:
    from app.core import hub_settings
    key = hub_settings.get("sorftime_key") or os.getenv("SORFTIME_KEY", "")
    return f"{_SORFTIME_BASE}?key={key}"


async def _call_tool(
    client: httpx.AsyncClient,
    tool_name: str,
    arguments: Dict[str, Any],
    call_id: int = 1,
) -> Any:
    """Call a single Sorftime MCP tool. Returns parsed result content or raises."""
    import json as _json

    payload = {
        "jsonrpc": "2.0",
        "id": call_id,
        "method": "tools/call",
        "params": {"name": tool_name, "arguments": arguments},
    }
    resp = await client.post(_url(), json=payload, headers=_HEADERS)
    resp.raise_for_status()

    # Sorftime returns SSE format: "event: message\ndata: {...}\n\n"
    body = None
    for line in resp.text.splitlines():
        line = line.strip()
        if line.startswith("data:"):
            raw = line[5:].strip()
            if raw:
                try:
                    body = _json.loads(raw)
                    break
                except Exception:
                    pass

    if body is None:
        raise RuntimeError(f"sorftime/{tool_name}: could not parse SSE response")

    if "error" in body:
        raise RuntimeError(f"sorftime/{tool_name} error: {body['error']}")

    result = body.get("result", {})

    # isError flag indicates auth failure or tool-level error
    if result.get("isError"):
        content_list = result.get("content", [])
        msg = next(
            (c.get("text", "") for c in content_list if isinstance(c, dict) and c.get("type") == "text"),
            "unknown error",
        )
        raise RuntimeError(f"sorftime/{tool_name}: {msg}")

    content = result.get("content", [])
    if isinstance(content, list) and content:
        first = content[0]
        if isinstance(first, dict) and first.get("type") == "text":
            text = first.get("text", "")
            try:
                return _json.loads(text)
            except Exception:
                return text
    return result


async def _safe_call(
    client: httpx.AsyncClient,
    tool_name: str,
    arguments: Dict[str, Any],
    call_id: int = 1,
) -> Tuple[str, Any, Optional[str]]:
    """Wrapper that returns (tool_name, result_or_None, error_or_None)."""
    try:
        data = await asyncio.wait_for(
            _call_tool(client, tool_name, arguments, call_id),
            timeout=_TOOL_TIMEOUT,
        )
        return tool_name, data, None
    except asyncio.TimeoutError:
        _log.warning("sorftime/%s timed out", tool_name)
        return tool_name, None, f"{tool_name} 超时"
    except Exception as exc:
        _log.warning("sorftime/%s failed: %s", tool_name, exc)
        return tool_name, None, f"{tool_name}: {exc}"


def _make_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=httpx.Timeout(_TOOL_TIMEOUT, connect=_CONN_TIMEOUT),
        limits=httpx.Limits(max_connections=20),
    )


# ─── Progress callback type ───────────────────────────────────────────────────

ProgressCb = Callable[[str, int, int], Coroutine[Any, Any, None]]


async def keyword_pipeline(
    keyword: str,
    marketplace: str,
    on_progress: Optional[ProgressCb] = None,
) -> Tuple[Dict[str, Any], List[str]]:
    """Run full keyword research pipeline. Returns (data_dict, error_list)."""
    total = 10
    done = 0
    errors: List[str] = []
    data: Dict[str, Any] = {}

    async def progress(step: str) -> None:
        nonlocal done
        done += 1
        if on_progress:
            await on_progress(step, done, total)

    async with _make_client() as client:
        # ── Phase 1: 6 concurrent calls ──────────────────────────────────────
        phase1_tasks = [
            _safe_call(client, "keyword_detail",
                       {"keyword": keyword, "keywordSupportSite": marketplace}, 1),
            _safe_call(client, "keyword_trend",
                       {"keyword": keyword, "keywordSupportSite": marketplace}, 2),
            _safe_call(client, "keyword_extends",
                       {"keyword": keyword, "keywordSupportSite": marketplace}, 3),
            _safe_call(client, "keyword_search_results",
                       {"keyword": keyword, "keywordSupportSite": marketplace}, 4),
            _safe_call(client, "category_search_from_product_name",
                       {"productName": keyword, "amzSite": marketplace}, 5),
            _safe_call(client, "similar_product_feature",
                       {"productName": keyword, "amzSite": marketplace}, 6),
        ]
        results = await asyncio.gather(*phase1_tasks)
        for name, val, err in results:
            if err:
                errors.append(err)
            else:
                data[name] = val
            await progress(name)

        # ── Phase 2: depends on phase 1 results ──────────────────────────────
        top_asins: List[str] = []
        search_res = data.get("keyword_search_results")
        if isinstance(search_res, dict):
            items = search_res.get("data", search_res.get("items", search_res.get("results", [])))
            if isinstance(items, list):
                for item in items[:2]:
                    if isinstance(item, dict):
                        asin = item.get("asin") or item.get("ASIN", "")
                        if asin:
                            top_asins.append(str(asin))

        # Extract category nodeId from category_search_from_product_name
        node_id = ""
        cat_res = data.get("category_search_from_product_name")
        if isinstance(cat_res, dict):
            node_id = str(
                cat_res.get("nodeid") or cat_res.get("nodeId") or cat_res.get("node_id") or ""
            )
            if not node_id:
                for key in ("data", "items", "categories", "results"):
                    items_inner = cat_res.get(key)
                    if isinstance(items_inner, list) and items_inner:
                        first = items_inner[0]
                        if isinstance(first, dict):
                            node_id = str(
                                first.get("nodeid") or first.get("nodeId") or first.get("node_id") or ""
                            )
                        break
        elif isinstance(cat_res, list) and cat_res:
            first = cat_res[0]
            if isinstance(first, dict):
                node_id = str(
                    first.get("nodeid") or first.get("nodeId") or first.get("node_id") or ""
                )

        phase2_tasks = []
        if top_asins:
            for i, asin in enumerate(top_asins[:2]):
                phase2_tasks.append(
                    _safe_call(client, "product_detail",
                               {"asin": asin, "amzSite": marketplace}, 10 + i)
                )
        phase2_tasks.append(
            _safe_call(client, "potential_product",
                       {"searchName": keyword, "amzSite": marketplace}, 12)
        )
        if node_id:
            phase2_tasks.append(
                _safe_call(client, "category_report",
                           {"nodeId": node_id, "amzSite": marketplace}, 13)
            )
        else:
            # No nodeId found — skip category_report and pad progress counter
            await progress("(category_report_skipped)")

        results2 = await asyncio.gather(*phase2_tasks)
        for i, (name, val, err) in enumerate(results2):
            if err:
                errors.append(err)
            else:
                if name == "product_detail":
                    existing = data.get("product_detail_list", [])
                    existing.append(val)
                    data["product_detail_list"] = existing
                else:
                    data[name] = val
            await progress(name)

    return data, errors


async def asin_pipeline(
    asin: str,
    marketplace: str,
    on_progress: Optional[ProgressCb] = None,
) -> Tuple[Dict[str, Any], List[str]]:
    """Run full ASIN research pipeline. Returns (data_dict, error_list)."""
    total = 8
    done = 0
    errors: List[str] = []
    data: Dict[str, Any] = {}

    async def progress(step: str) -> None:
        nonlocal done
        done += 1
        if on_progress:
            await on_progress(step, done, total)

    async with _make_client() as client:
        # ── Phase 1: 5 concurrent calls ──────────────────────────────────────
        phase1_tasks = [
            _safe_call(client, "product_report",
                       {"asin": asin, "amzSite": marketplace}, 1),
            _safe_call(client, "product_trend",
                       {"asin": asin, "amzSite": marketplace}, 2),
            _safe_call(client, "product_traffic_terms",
                       {"asin": asin, "amzSite": marketplace}, 3),
            _safe_call(client, "product_reviews",
                       {"asin": asin, "amzSite": marketplace}, 4),
            _safe_call(client, "product_variations",
                       {"asin": asin, "amzSite": marketplace}, 5),
        ]
        results = await asyncio.gather(*phase1_tasks)
        for name, val, err in results:
            if err:
                errors.append(err)
            else:
                data[name] = val
            await progress(name)

        # ── Phase 2: use main traffic keyword for market context ──────────────
        main_kw = ""
        traffic = data.get("product_traffic_terms")
        if isinstance(traffic, dict):
            terms = traffic.get("data", traffic.get("terms", traffic.get("results", [])))
            if isinstance(terms, list) and terms:
                first = terms[0]
                if isinstance(first, dict):
                    main_kw = str(first.get("keyword") or first.get("term") or first.get("search_term") or "")
                elif isinstance(first, str):
                    main_kw = first

        phase2_tasks = []
        if main_kw:
            phase2_tasks = [
                _safe_call(client, "keyword_detail",
                           {"keyword": main_kw, "keywordSupportSite": marketplace}, 10),
                _safe_call(client, "keyword_search_results",
                           {"keyword": main_kw, "keywordSupportSite": marketplace}, 11),
                _safe_call(client, "competitor_product_keywords",
                           {"asin": asin, "keywordSupportSite": marketplace}, 12),
            ]
        else:
            phase2_tasks = [
                _safe_call(client, "competitor_product_keywords",
                           {"asin": asin, "keywordSupportSite": marketplace}, 12),
            ]
            # Pad progress for skipped calls
            for _ in range(2):
                await progress("(skipped)")

        results2 = await asyncio.gather(*phase2_tasks)
        for name, val, err in results2:
            if err:
                errors.append(err)
            else:
                data[name] = val
            await progress(name)

    return data, errors
