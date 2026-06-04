"""领星 controlled write execution (P3) — the safety-critical path.

A write never happens casually. Each proposed change becomes a **ticket** that
must clear, in order:

1. **Triple independent review** — three fresh LLM passes with distinct personas
   (data-rigour / devil's-advocate / business-balance); ALL must approve and the
   worst risk score must stay under threshold. (generate_text is single-provider,
   so independence = separate calls + adversarial framing — honest about that.)
2. **Deterministic guardrails** (code, not LLM, cannot be reasoned around):
   operate switch active, store in scope (empty scope = nothing writable),
   magnitude ≤ max_change_pct, sane budget/state.
3. **Human final confirmation** in the UI (locked on by decision).

Only then does it execute via the gateway (``allow_write=True``), after capturing
a rollback snapshot. Failures trip a circuit breaker (auto-disable operate +
alert). Everything is audited.
"""
from __future__ import annotations

import asyncio
import json
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import httpx

from app.core import hub_settings as _hs
from app.services import ai_synthesis_service as _ai
from app.services import lingxing_data as _data
from app.services import lingxing_service as _gw

PUT_SP_CAMPAIGN_ROUTE = "/basicOpen/adReport/manage/putSpCampaign"
_RISK_THRESHOLD = 0.5

_REVIEWERS = [
    ("数据严谨派", "你是只看数据、最严谨的审核员。只有当数据充分支撑该调整、且改动幅度与依据匹配时才批准。"),
    ("魔鬼代言人", "你是风险厌恶的魔鬼代言人。先假设这个调整是有害的，竭力找出它可能造成的负面后果、被数据噪声误导的可能、以及最坏情况；只有在找不到重大风险时才勉强批准。"),
    ("业务平衡派", "你是资深运营，权衡投入产出与业务目标，判断该调整是否真正划算、是否符合常识。"),
]

_op_lock = asyncio.Lock()


# --- persistence ------------------------------------------------------------
def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _save(t: Dict[str, Any]) -> None:
    t["updated_at"] = _now()
    conn = _gw.connect()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO lingxing_op_ticket "
            "(id,created_at,updated_at,source,status,intent_json,reviews_json,"
            "guardrail_json,snapshot_json,result_json,decided_by,error) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (t["id"], t.get("created_at"), t["updated_at"], t.get("source"), t.get("status"),
             _j(t.get("intent")), _j(t.get("reviews")), _j(t.get("guardrail")),
             _j(t.get("snapshot")), _j(t.get("result")), t.get("decided_by", ""), t.get("error", "")))
        conn.commit()
    finally:
        conn.close()


def _j(v: Any) -> str:
    return json.dumps(v, ensure_ascii=False, default=str) if v is not None else ""


def list_tickets(limit: int = 50) -> List[Dict[str, Any]]:
    conn = _gw.connect()
    try:
        cur = conn.execute(
            "SELECT id,created_at,source,status,intent_json,decided_by,error "
            "FROM lingxing_op_ticket ORDER BY created_at DESC LIMIT ?", (int(limit),))
        cols = [c[0] for c in cur.description]
        out = []
        for r in cur.fetchall():
            d = dict(zip(cols, r))
            try:
                d["intent"] = json.loads(d.pop("intent_json") or "null")
            except Exception:
                d["intent"] = None
            out.append(d)
        return out
    finally:
        conn.close()


def get_ticket(tid: str) -> Optional[Dict[str, Any]]:
    conn = _gw.connect()
    try:
        cur = conn.execute("SELECT * FROM lingxing_op_ticket WHERE id=?", (tid,))
        row = cur.fetchone()
        if not row:
            return None
        cols = [c[0] for c in cur.description]
        d = dict(zip(cols, row))
    finally:
        conn.close()
    for k in ("intent", "reviews", "guardrail", "snapshot", "result"):
        try:
            d[k] = json.loads(d.pop(k + "_json") or "null")
        except Exception:
            d[k] = None
    return d


# --- best-effort alert ------------------------------------------------------
async def send_alert(text: str) -> None:
    url = (_hs.get("alert_webhook") or "").strip()
    if not url:
        return
    try:
        async with httpx.AsyncClient(timeout=8) as c:
            await c.post(url, json={"msg_type": "text", "content": {"text": f"[领星操作] {text}"}})
    except Exception:
        pass


# --- operate switch ---------------------------------------------------------
def enable_operate() -> Dict[str, Any]:
    ttl = int(_hs.get("lingxing_operate_ttl_minutes") or 120)
    exp = (datetime.now(timezone.utc) + timedelta(minutes=ttl)).isoformat()
    # re-enabling acknowledges + clears any tripped circuit breaker
    _hs.save({"lingxing_operate_enabled": True, "lingxing_operate_expires_at": exp,
              "lingxing_circuit_reason": ""})
    return _gw.status()


def disable_operate() -> Dict[str, Any]:
    _hs.save({"lingxing_operate_enabled": False, "lingxing_operate_expires_at": ""})
    return _gw.status()


# --- deterministic guardrails ----------------------------------------------
def check_guardrails(intent: Dict[str, Any]) -> Dict[str, Any]:
    cfg = _hs.load()
    checks: List[Dict[str, Any]] = []

    def add(name: str, ok: bool, detail: str = ""):
        checks.append({"name": name, "ok": bool(ok), "detail": detail})

    # store scope (empty whitelist = nothing writable — fail closed)
    scope = str(cfg.get("lingxing_scope_stores") or "").replace("，", ",")
    allowed = {s.strip() for s in scope.split(",") if s.strip()}
    sid = str(intent.get("sid"))
    add("store_scope", bool(allowed) and sid in allowed,
        "店铺在白名单" if (allowed and sid in allowed) else
        ("scope 为空，默认禁止所有写操作" if not allowed else f"店铺 {sid} 不在白名单"))

    # magnitude
    max_pct = float(cfg.get("lingxing_max_change_pct") or 20)
    change = intent.get("change") or {}
    before = intent.get("before") or {}
    pct_ok, pct_detail = True, "无预算变更"
    if change.get("daily_budget") is not None and before.get("daily_budget"):
        try:
            old, new = float(before["daily_budget"]), float(change["daily_budget"])
            pct = abs(new - old) / old * 100 if old else 999
            pct_ok = pct <= max_pct
            pct_detail = f"幅度 {pct:.1f}% ≤ {max_pct}%" if pct_ok else f"幅度 {pct:.1f}% 超过上限 {max_pct}%"
        except (TypeError, ValueError, ZeroDivisionError):
            pct_ok, pct_detail = False, "无法计算幅度"
    add("change_magnitude", pct_ok, pct_detail)

    # sane budget / state
    nb = change.get("daily_budget")
    add("budget_positive", nb is None or float(nb) > 0, "" if nb is None else f"新预算 {nb}")
    ns = change.get("state")
    add("state_valid", ns is None or ns in ("enabled", "paused"), "" if ns is None else f"state={ns}")

    ok = all(c["ok"] for c in checks)
    return {"ok": ok, "checks": checks}


# --- triple independent review ---------------------------------------------
def _parse_review(text: str) -> Dict[str, Any]:
    t = text.strip()
    m = re.search(r"\{.*\}", t, re.DOTALL)
    if m:
        t = m.group(0)
    try:
        obj = json.loads(t)
        return {"approve": bool(obj.get("approve")),
                "risk_score": float(obj.get("risk_score", 1)),
                "reasons": str(obj.get("reasons", ""))[:600]}
    except Exception:
        return {"approve": False, "risk_score": 1.0, "reasons": "复核响应解析失败（fail-closed 视为不通过）"}


async def _one_review(persona: str, framing: str, intent: Dict[str, Any]) -> Dict[str, Any]:
    prompt = f"""{framing}

待审操作（仅审核，不要执行）：
{json.dumps(intent, ensure_ascii=False, indent=1)}

只输出 JSON：{{"approve": true/false, "risk_score": 0~1, "reasons": "中文理由"}}
approve=是否批准；risk_score=重大风险概率(越高越危险)；理由要具体。"""
    try:
        raw = await _ai.generate_text(prompt)
        r = _parse_review(raw)
    except Exception as e:  # noqa: BLE001
        r = {"approve": False, "risk_score": 1.0, "reasons": f"复核模型不可用：{e}（fail-closed）"}
    r["reviewer"] = persona
    return r


async def review_intent(intent: Dict[str, Any]) -> Dict[str, Any]:
    reviews = []
    for persona, framing in _REVIEWERS:
        reviews.append(await _one_review(persona, framing, intent))
    approved = all(r["approve"] for r in reviews) and max(r["risk_score"] for r in reviews) <= _RISK_THRESHOLD
    return {"approved": approved, "reviews": reviews,
            "max_risk": max(r["risk_score"] for r in reviews)}


# --- ticket lifecycle -------------------------------------------------------
def _verdict_status(reviewed_ok: bool, guard_ok: bool) -> str:
    if not guard_ok:
        return "guardrail_blocked"
    if not reviewed_ok:
        return "review_rejected"
    return "awaiting_human"


async def create_ticket(intent: Dict[str, Any], source: str = "manual") -> Dict[str, Any]:
    """Create + auto-process a ticket: triple review + guardrails → awaiting_human
    (or blocked/rejected). Nothing executes here."""
    t: Dict[str, Any] = {
        "id": uuid.uuid4().hex[:12], "created_at": _now(), "source": source,
        "status": "reviewing", "intent": intent, "reviews": None, "guardrail": None,
        "snapshot": None, "result": None, "decided_by": "", "error": "",
    }
    _save(t)
    guard = check_guardrails(intent)
    rev = await review_intent(intent)
    t["guardrail"] = guard
    t["reviews"] = rev
    t["status"] = _verdict_status(rev["approved"], guard["ok"])
    _save(t)
    return t


async def create_tickets_from_run(run_id: str) -> Dict[str, Any]:
    from app.services import lingxing_automation as _auto
    run = _auto.get_run(run_id)
    if not run:
        raise _gw.LingXingError("未找到该分析运行")
    max_ops = int(_hs.get("lingxing_max_ops_per_run") or 10)
    created = []
    for p in (run.get("proposals") or [])[:max_ops]:
        action = p.get("action")
        if action in (None, "keep"):
            continue
        change: Dict[str, Any] = {}
        prop = p.get("proposed") or {}
        if action in ("increase_budget", "decrease_budget") and prop.get("daily_budget") is not None:
            change["daily_budget"] = prop["daily_budget"]
        if action in ("pause", "enable"):
            change["state"] = "paused" if action == "pause" else "enabled"
        if not change:
            continue
        intent = {
            "sid": p.get("sid"), "campaign_id": str(p.get("campaign_id")),
            "campaign_name": p.get("campaign_name"), "op_type": "+".join(change.keys()),
            "change": change, "before": p.get("current") or {},
            "change_pct": p.get("change_pct"), "rationale": p.get("rationale"),
            "source_proposal": p,
        }
        created.append(await create_ticket(intent, source=f"run:{run_id}"))
    return {"created": len(created), "tickets": [t["id"] for t in created]}


async def _current_campaign(sid: int, campaign_id: str) -> Dict[str, Any]:
    res = await _data.fetch_dataset("sp_campaigns", {"sid": sid, "length": 300}, force=True)
    for c in (res.get("rows") or []):
        if str(c.get("campaign_id")) == str(campaign_id):
            return {"daily_budget": c.get("daily_budget"), "state": c.get("state")}
    return {}


def _build_put_body(intent: Dict[str, Any]) -> Dict[str, Any]:
    change = intent.get("change") or {}
    camp: Dict[str, Any] = {"campaignId": int(intent["campaign_id"]), "isBaseValue": 0}
    if change.get("state"):
        camp["state"] = change["state"]
    if change.get("daily_budget") is not None:
        camp["budget"] = {"budgetType": "DAILY", "budget": float(change["daily_budget"])}
    return {"sid": int(intent["sid"]), "campaigns": [camp]}


async def confirm_ticket(tid: str, decided_by: str = "human", dry_run: bool = False) -> Dict[str, Any]:
    """Human-confirm + execute. Re-checks every gate at execution time."""
    async with _op_lock:
        t = get_ticket(tid)
        if not t:
            raise _gw.LingXingError("未找到工单")
        if t["status"] != "awaiting_human":
            raise _gw.LingXingError(f"工单状态 {t['status']} 不可确认")
        if not _gw.is_operate_active():
            raise _gw.LingXingError("操作开关未开启（或已超时失效）")
        # re-verify guardrails at execution time (defence in depth)
        guard = check_guardrails(t["intent"])
        if not guard["ok"]:
            t["status"] = "guardrail_blocked"; t["guardrail"] = guard
            _save(t)
            raise _gw.LingXingError("执行前护栏复检未通过")

        t["decided_by"] = decided_by
        # capture rollback snapshot from live state
        intent = t["intent"]
        snap = await _current_campaign(int(intent["sid"]), intent["campaign_id"])
        t["snapshot"] = snap
        body = _build_put_body(intent)

        if dry_run:
            t["status"] = "awaiting_human"  # unchanged; this is a preview
            t["result"] = {"dry_run": True, "route": PUT_SP_CAMPAIGN_ROUTE, "body": body}
            _save(t)
            return t

        t["status"] = "executing"
        _save(t)
        try:
            res = await _gw.call_openapi(PUT_SP_CAMPAIGN_ROUTE, body, method="POST",
                                         caller="operate", allow_write=True)
            t["result"] = res
            t["status"] = "executed"
            _save(t)
            await send_alert(f"已执行：店铺{intent['sid']} 活动{intent.get('campaign_name') or intent['campaign_id']} → {intent['change']}")
        except _gw.LingXingError as e:
            t["status"] = "failed"; t["error"] = str(e)
            _save(t)
            # circuit breaker: API-level failure auto-disables the operate switch
            disable_operate()
            await send_alert(f"执行失败已熔断（操作开关已关闭）：{e}")
            raise
        return t


async def reject_ticket(tid: str, decided_by: str = "human") -> Dict[str, Any]:
    t = get_ticket(tid)
    if not t:
        raise _gw.LingXingError("未找到工单")
    t["status"] = "rejected"; t["decided_by"] = decided_by
    _save(t)
    return t


async def rollback_ticket(tid: str, decided_by: str = "human") -> Dict[str, Any]:
    """Revert an executed ticket to its captured pre-execution snapshot."""
    async with _op_lock:
        t = get_ticket(tid)
        if not t:
            raise _gw.LingXingError("未找到工单")
        if t["status"] != "executed":
            raise _gw.LingXingError(f"工单状态 {t['status']} 不可回滚")
        if not _gw.is_operate_active():
            raise _gw.LingXingError("操作开关未开启，无法回滚")
        snap = t.get("snapshot") or {}
        if not snap:
            raise _gw.LingXingError("无回滚快照")
        intent = t["intent"]
        change = {}
        if snap.get("daily_budget") is not None:
            change["daily_budget"] = snap["daily_budget"]
        if snap.get("state"):
            change["state"] = snap["state"]
        body = _build_put_body({"sid": intent["sid"], "campaign_id": intent["campaign_id"], "change": change})
        res = await _gw.call_openapi(PUT_SP_CAMPAIGN_ROUTE, body, method="POST",
                                     caller="operate-rollback", allow_write=True)
        t["status"] = "rolled_back"; t["result"] = {"rollback": res, "prev": t.get("result")}
        t["decided_by"] = decided_by
        _save(t)
        await send_alert(f"已回滚：店铺{intent['sid']} 活动{intent.get('campaign_name') or intent['campaign_id']} → {change}")
        return t
