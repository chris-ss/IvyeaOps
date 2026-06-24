"""Amazon operations endpoints.

Two groups:
1. Stub endpoints kept for the existing frontend (asin/inspect, listing/demo).
2. Real ASIN audit job API backed by claude CLI + sorftime/sif MCP.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.core.security import require_user
from app.services import asin_audit

router = APIRouter()

ASIN_RE = re.compile(r"^[A-Z0-9]{10}$")
MARKETPLACES = {"US", "UK", "DE", "FR", "CA", "JP", "ES", "IT", "MX", "AU", "AE", "BR", "SA"}


# ---------- legacy stub endpoints (do not break existing UI) ----------

class AsinInspectBody(BaseModel):
    asin: str = Field(..., description="10-char Amazon ASIN, e.g. B08N5WRWNW")


class AsinInspectResult(BaseModel):
    asin: str
    valid: bool
    marketplace_hint: str
    note: str


@router.post("/asin/inspect", response_model=AsinInspectResult)
def asin_inspect(
    body: AsinInspectBody,
    _user: str = Depends(require_user),
) -> AsinInspectResult:
    asin = body.asin.strip().upper()
    if not ASIN_RE.match(asin):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="ASIN must be exactly 10 alphanumeric characters",
        )
    hint = "US" if asin.startswith("B0") else "unknown"
    return AsinInspectResult(
        asin=asin,
        valid=True,
        marketplace_hint=hint,
        note="格式有效。使用下方「深度审计」启动完整分析。",
    )


class ListingDemoResult(BaseModel):
    title_score: int
    bullet_count: int
    suggestions: List[str]


@router.get("/listing/demo", response_model=ListingDemoResult)
def listing_demo(_user: str = Depends(require_user)) -> ListingDemoResult:
    return ListingDemoResult(
        title_score=72,
        bullet_count=5,
        suggestions=[
            "title too long, trim below 200 chars",
            "bullet 3 lacks a benefit keyword",
            "missing material keyword in title",
        ],
    )


# ---------- ASIN deep audit job API ----------


class AuditStartBody(BaseModel):
    asin: str = Field(..., min_length=10, max_length=10)
    marketplace: str = Field(default="US", min_length=2, max_length=3)
    mode: str = Field(default="full", description="full | rewrite_only")
    runner: str = Field(
        default="auto",
        description="auto | ivyea-agent | hermes | codex | claude",
    )


class AuditStartResult(BaseModel):
    job_id: str
    status: str
    created_at: str
    runner_used: Optional[str] = None


@router.get("/audit/runners")
def audit_runners(_user: str = Depends(require_user)) -> Dict[str, Any]:
    """Return availability of each agent CLI for the UI selector."""
    return {"runners": asin_audit.runner_status()}


@router.post("/audit/start", response_model=AuditStartResult)
async def audit_start(
    body: AuditStartBody,
    _user: str = Depends(require_user),
) -> AuditStartResult:
    asin = body.asin.strip().upper()
    if not ASIN_RE.match(asin):
        raise HTTPException(status_code=400, detail="invalid ASIN")
    market = body.marketplace.strip().upper() or "US"
    if market not in MARKETPLACES:
        raise HTTPException(status_code=400, detail=f"unsupported marketplace {market}")
    mode = body.mode if body.mode in ("full", "rewrite_only") else "full"
    runner_pref = (body.runner or "auto").lower()
    if runner_pref not in ("auto", "ivyea-agent", "hermes", "codex", "claude"):
        raise HTTPException(status_code=400, detail=f"unknown runner: {runner_pref}")

    if asin_audit.is_busy():
        raise HTTPException(status_code=409, detail="另一个 ASIN 审计任务正在运行，请稍后")

    try:
        job = await asin_audit.start_job(asin, market, mode, runner_pref=runner_pref)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        # 409 for busy, 400 for "runner not available".
        msg = str(e)
        code = 400 if "not available" in msg else 409
        raise HTTPException(status_code=code, detail=msg)
    return AuditStartResult(
        job_id=job.job_id,
        status=job.status,
        created_at=job.created_at,
        runner_used=job.runner_used,
    )


class AuditStatusResult(BaseModel):
    job_id: str
    asin: str
    marketplace: str
    mode: str
    status: str
    progress: Optional[str] = None
    created_at: str
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    error: Optional[str] = None
    raw_md: Optional[str] = None
    structured: Optional[Dict[str, Any]] = None
    runner_pref: Optional[str] = None
    runner_used: Optional[str] = None


@router.get("/audit/list")
def audit_list(
    limit: int = 20,
    _user: str = Depends(require_user),
) -> Dict[str, Any]:
    limit = max(1, min(int(limit), 100))
    return {"items": asin_audit.list_jobs(limit=limit), "busy": asin_audit.is_busy()}


@router.post("/audit/clear-failed")
def audit_clear_failed(
    _user: str = Depends(require_user),
) -> Dict[str, Any]:
    removed = asin_audit.clear_failed()
    return {"removed": removed}


@router.delete("/audit/{job_id}")
def audit_delete(
    job_id: str,
    _user: str = Depends(require_user),
) -> Dict[str, Any]:
    ok = asin_audit.delete_job(job_id)
    if not ok:
        raise HTTPException(status_code=404, detail="job not found or still running")
    return {"deleted": True}


@router.get("/audit/{job_id}", response_model=AuditStatusResult)
def audit_get(
    job_id: str,
    _user: str = Depends(require_user),
) -> AuditStatusResult:
    data = asin_audit.get_job(job_id)
    if data is None:
        raise HTTPException(status_code=404, detail="job not found")
    return AuditStatusResult(**data)


@router.get("/audit/{job_id}/download")
def audit_download(
    job_id: str,
    fmt: str = "md",
    _user: str = Depends(require_user),
) -> FileResponse:
    if fmt not in ("md", "json", "xlsx", "html"):
        raise HTTPException(status_code=400, detail="fmt must be md, json, xlsx or html")
    path = asin_audit.download_path(job_id, fmt)
    if path is None:
        if fmt == "xlsx":
            detail = "artifact not available (xlsx 需要 report.json；请先等任务跑完再下载)"
        elif fmt == "html":
            detail = "artifact not available (html 需要 report.md 或 report.json；请先等任务跑完再下载)"
        else:
            detail = "artifact not available"
        raise HTTPException(status_code=404, detail=detail)
    media_map = {
        "md": "text/markdown",
        "json": "application/json",
        "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "html": "text/html; charset=utf-8",
    }
    filename = f"asin-audit-{job_id}.{fmt}"
    return FileResponse(
        path,
        media_type=media_map[fmt],
        filename=filename,
    )
