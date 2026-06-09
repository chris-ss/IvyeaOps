"""Health check endpoint."""
from __future__ import annotations

from fastapi import APIRouter

from app.core.version import app_version

router = APIRouter()


@router.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "IvyeaOps", "version": app_version()}
