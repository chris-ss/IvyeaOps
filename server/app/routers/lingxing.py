"""领星 (LingXing) gateway API (mounted at ``/api/lingxing``, admin-only).

P0 surface:
* ``GET /status``  — config/switch snapshot (no secrets) for the UI.
* ``POST /probe``  — live ``tools/list`` against LingXing, classified read/write.
                     This is the step that resolves whether ad-write tools exist.
* ``GET /audit``   — recent gateway call log.

The write-execution endpoints (operate switch toggle, op tickets, triple
review, human confirm) land in P3.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.core import hub_settings as _hs
from app.services import lingxing_service as lx
from app.services import lingxing_data as lxd
from app.services import lingxing_automation as lxa
from app.services import lingxing_operate as lxo

router = APIRouter()


class ReadRequest(BaseModel):
    params: Dict[str, Any] = {}
    force: bool = False


_AUTO_CONFIG_KEYS = [
    "lingxing_auto_enabled", "lingxing_auto_weekday", "lingxing_auto_hour",
    "lingxing_auto_report_days", "lingxing_auto_stores", "lingxing_auto_max_campaigns",
    "lingxing_max_change_pct",
]


class AutoConfigPatch(BaseModel):
    config: Dict[str, Any] = {}


@router.get("/status")
async def status() -> Dict[str, Any]:
    return lx.status()


@router.post("/probe")
async def probe() -> Dict[str, Any]:
    """Verify both backends end-to-end: OpenAPI (token + signed read) and, if an
    X-Mcp-Key is configured, MCP (tools/list classified read/write)."""
    out: Dict[str, Any] = {"openapi": None, "mcp": None}
    from app.services import lingxing_openapi as lo
    if lo.is_configured():
        try:
            out["openapi"] = await lx.openapi_verify(caller="probe")
        except lx.LingXingError as e:
            out["openapi"] = {"ok": False, "error": str(e)}
    if lx._key():
        try:
            out["mcp"] = await lx.probe(caller="probe")
        except lx.LingXingError as e:
            out["mcp"] = {"ok": False, "error": str(e)}
    if out["openapi"] is None and out["mcp"] is None:
        raise HTTPException(status_code=400, detail="未配置任何领星后端（OpenAPI 凭证或 MCP key）")
    return out


@router.get("/audit")
async def audit(limit: int = 100) -> Dict[str, Any]:
    return {"rows": lx.recent_audit(limit=max(1, min(limit, 500)))}


@router.get("/dashboard")
async def dashboard(sids: str = "", days: int = 7) -> Dict[str, Any]:
    """广告数据大盘聚合（按店铺/活动/天）。sids 逗号分隔，空=全部店铺。"""
    from app.services import lingxing_dashboard as lxdash
    sid_list = [int(x) for x in sids.replace("，", ",").split(",") if x.strip().isdigit()] or None
    try:
        return await lxdash.dashboard(sid_list, days)
    except lx.LingXingError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/datasets")
async def datasets() -> Dict[str, Any]:
    """Read-dataset registry that drives the 浏览/分析 panels."""
    return {"datasets": lxd.catalog()}


@router.post("/read/{dataset}")
async def read(dataset: str, body: ReadRequest) -> Dict[str, Any]:
    try:
        return await lxd.fetch_dataset(dataset, body.params, force=body.force, caller="panel")
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    except lx.LingXingError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


# --- weekly advisory automation (P2) ---------------------------------------
@router.get("/auto/config")
async def auto_config() -> Dict[str, Any]:
    cfg = _hs.load()
    return {"config": {k: cfg.get(k) for k in _AUTO_CONFIG_KEYS}}


@router.patch("/auto/config")
async def auto_config_patch(body: AutoConfigPatch) -> Dict[str, Any]:
    updates = {k: v for k, v in body.config.items() if k in _AUTO_CONFIG_KEYS}
    _hs.save(updates)
    cfg = _hs.load()
    return {"config": {k: cfg.get(k) for k in _AUTO_CONFIG_KEYS}}


@router.get("/auto/runs")
async def auto_runs(limit: int = 30) -> Dict[str, Any]:
    return {"runs": lxa.list_runs(limit=max(1, min(limit, 100)))}


@router.get("/auto/runs/{run_id}")
async def auto_run_detail(run_id: str) -> Dict[str, Any]:
    run = lxa.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="未找到该运行记录")
    return run


@router.post("/auto/run")
async def auto_run_now() -> Dict[str, Any]:
    """Trigger one advisory run in the background (analyse + recommend, no writes)."""
    if not lx.is_master_enabled():
        raise HTTPException(status_code=400, detail="领星集成未启用（总开关关闭）")
    run_id = lxa.start_background_run(trigger="manual")
    return {"ok": True, "run_id": run_id}


# --- controlled write operations (P3) --------------------------------------
class ConfirmRequest(BaseModel):
    dry_run: bool = False


@router.post("/operate/enable")
async def operate_enable() -> Dict[str, Any]:
    st = lxo.enable_operate()
    await lxo.send_alert("🔓 操作开关已开启（进入可写态，写操作仍需三重复核+人工确认）")
    return {"status": st}


@router.post("/operate/disable")
async def operate_disable() -> Dict[str, Any]:
    st = lxo.disable_operate()
    await lxo.send_alert("🔒 操作开关已关闭（恢复只读）")
    return {"status": st}


@router.get("/operate/tickets")
async def operate_tickets(limit: int = 50) -> Dict[str, Any]:
    return {"tickets": lxo.list_tickets(limit=max(1, min(limit, 200)))}


@router.get("/operate/tickets/{tid}")
async def operate_ticket_detail(tid: str) -> Dict[str, Any]:
    t = lxo.get_ticket(tid)
    if not t:
        raise HTTPException(status_code=404, detail="未找到工单")
    return t


@router.post("/operate/from-run/{run_id}")
async def operate_from_run(run_id: str) -> Dict[str, Any]:
    """Turn a run's advisory proposals into review-gated tickets."""
    try:
        return await lxo.create_tickets_from_run(run_id)
    except lx.LingXingError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/operate/tickets/{tid}/confirm")
async def operate_confirm(tid: str, body: ConfirmRequest) -> Dict[str, Any]:
    try:
        return await lxo.confirm_ticket(tid, decided_by="human", dry_run=body.dry_run)
    except lx.LingXingError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/operate/tickets/{tid}/reject")
async def operate_reject(tid: str) -> Dict[str, Any]:
    try:
        return await lxo.reject_ticket(tid, decided_by="human")
    except lx.LingXingError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/operate/tickets/{tid}/rollback")
async def operate_rollback(tid: str) -> Dict[str, Any]:
    try:
        return await lxo.rollback_ticket(tid, decided_by="human")
    except lx.LingXingError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
