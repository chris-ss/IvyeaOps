"""领星 广告数据大盘 — cross-store/campaign aggregation for the dashboard.

Reuses the gateway read layer (cache-friendly: past-day reports are immutable)
to aggregate SP campaign reports over a window into: headline totals, per-store
rollup, top campaigns, and a per-day trend. Pure read; no writes.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from app.services import lingxing_data as _data
from app.services import lingxing_service as _gw

_REPORT_TTL_S = 7 * 86400  # past-day reports never change


def _f(v: Any) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _derive(m: Dict[str, float]) -> Dict[str, Any]:
    spend, sales, clicks, impr, orders = (m["spend"], m["sales"], m["clicks"], m["impressions"], m["orders"])
    return {
        "spend": round(spend, 2), "sales": round(sales, 2), "orders": int(orders),
        "clicks": int(clicks), "impressions": int(impr),
        "acos": round(spend / sales, 4) if sales else None,
        "roas": round(sales / spend, 2) if spend else None,
        "ctr": round(clicks / impr, 4) if impr else None,
        "cvr": round(orders / clicks, 4) if clicks else None,
    }


def _bucket() -> Dict[str, float]:
    return {"spend": 0.0, "sales": 0.0, "orders": 0.0, "clicks": 0.0, "impressions": 0.0}


def _add(b: Dict[str, float], r: Dict[str, Any]) -> None:
    b["spend"] += _f(r.get("cost"))
    b["sales"] += _f(r.get("sales"))
    b["orders"] += _f(r.get("orders"))
    b["clicks"] += _f(r.get("clicks"))
    b["impressions"] += _f(r.get("impressions"))


async def _resolve_sids(sids: Optional[List[int]]) -> Dict[int, str]:
    """Return {sid: store_name} for the requested sids (or all if None/empty)."""
    sellers = await _data.fetch_dataset("sellers")
    name_by_sid = {int(s["sid"]): s.get("name") for s in (sellers.get("rows") or [])
                   if str(s.get("sid", "")).isdigit()}
    if sids:
        return {sid: name_by_sid.get(sid, str(sid)) for sid in sids}
    return name_by_sid


async def dashboard(sids: Optional[List[int]] = None, days: int = 7) -> Dict[str, Any]:
    if not _gw.is_master_enabled():
        raise _gw.LingXingError("领星集成未启用（总开关关闭）")
    days = max(1, min(int(days), 60))
    store_names = await _resolve_sids(sids)

    totals = _bucket()
    by_store: Dict[int, Dict[str, float]] = {}
    by_campaign: Dict[str, Dict[str, Any]] = {}
    by_day: Dict[str, Dict[str, float]] = {}

    for sid, sname in store_names.items():
        # campaign names for nicer labels
        try:
            camps = await _data.fetch_dataset("sp_campaigns", {"sid": sid, "length": 300})
            cname = {str(c.get("campaign_id")): c.get("name") for c in (camps.get("rows") or [])}
        except _gw.LingXingError:
            cname = {}
        sb = by_store.setdefault(sid, _bucket())
        for d in range(1, days + 1):
            day = (datetime.now(timezone.utc) - timedelta(days=d)).strftime("%Y-%m-%d")
            try:
                rep = await _data.fetch_dataset(
                    "sp_campaign_report", {"sid": sid, "report_date": day, "length": 300},
                    ttl=_REPORT_TTL_S)
            except _gw.LingXingError:
                continue
            db = by_day.setdefault(day, _bucket())
            for r in (rep.get("rows") or []):
                cid = str(r.get("campaign_id"))
                _add(totals, r); _add(sb, r); _add(db, r)
                key = f"{sid}:{cid}"
                cb = by_campaign.setdefault(key, {"sid": sid, "store": sname, "campaign_id": cid,
                                                  "name": cname.get(cid), **_bucket()})
                _add(cb, r)

    stores = [{"sid": sid, "store": store_names.get(sid, str(sid)), **_derive(b)}
              for sid, b in by_store.items()]
    stores.sort(key=lambda x: x["spend"], reverse=True)

    campaigns = []
    for v in by_campaign.values():
        d = _derive(v)
        campaigns.append({"sid": v["sid"], "store": v["store"], "campaign_id": v["campaign_id"],
                          "name": v["name"], **d})
    campaigns.sort(key=lambda x: x["spend"], reverse=True)

    trend = [{"date": day, **_derive(b)} for day, b in sorted(by_day.items())]

    return {
        "scope": {"sids": list(store_names.keys()), "days": days, "store_count": len(store_names)},
        "totals": _derive(totals),
        "by_store": stores,
        "by_campaign": campaigns[:25],
        "trend": trend,
    }
