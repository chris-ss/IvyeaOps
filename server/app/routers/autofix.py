"""Auto bug-fix router (admin-only).

Drives the review-first repair flow backed by ``autofix_service``:

    diagnose → (review diff) → apply → restart   ·   reject / rollback

Everything is single-flight and runs hermes in an isolated git worktree; see
``app.services.autofix_service`` for the safety model.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.core import hub_settings as _hs
from app.core.security import require_admin
from app.services import autofix_service as svc

router = APIRouter(prefix="/autofix", dependencies=[Depends(require_admin)])


class DiagnoseRequest(BaseModel):
    feature: Optional[str] = ""
    endpoint: Optional[str] = ""
    method: Optional[str] = ""
    status: Optional[int] = None
    detail: Optional[str] = ""


@router.get("/status")
async def status() -> Dict[str, Any]:
    return {"enabled": bool(_hs.get("autofix_enabled")), "job": svc.current_job()}


@router.post("/diagnose")
async def diagnose(body: DiagnoseRequest) -> Dict[str, Any]:
    if not _hs.get("autofix_enabled"):
        raise HTTPException(403, "自动修复未开启")
    try:
        return await svc.start_diagnose(body.model_dump())
    except RuntimeError as e:
        raise HTTPException(409, str(e))


@router.get("/{job_id}")
async def get_job(job_id: str) -> Dict[str, Any]:
    job = svc.current_job()
    if not job or job["id"] != job_id:
        raise HTTPException(404, "任务不存在或已失效")
    return job


@router.post("/{job_id}/apply")
async def apply(job_id: str) -> Dict[str, Any]:
    try:
        return await svc.apply(job_id)
    except KeyError as e:
        raise HTTPException(404, str(e))
    except RuntimeError as e:
        raise HTTPException(409, str(e))


@router.post("/{job_id}/restart")
async def restart(job_id: str) -> Dict[str, Any]:
    try:
        return svc.restart(job_id)
    except KeyError as e:
        raise HTTPException(404, str(e))
    except RuntimeError as e:
        raise HTTPException(409, str(e))


@router.post("/{job_id}/rollback")
async def rollback(job_id: str) -> Dict[str, Any]:
    try:
        return await svc.rollback(job_id)
    except KeyError as e:
        raise HTTPException(404, str(e))
    except RuntimeError as e:
        raise HTTPException(409, str(e))


@router.post("/{job_id}/reject")
async def reject(job_id: str) -> Dict[str, Any]:
    try:
        return svc.reject(job_id)
    except KeyError as e:
        raise HTTPException(404, str(e))
