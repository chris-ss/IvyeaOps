"""Git operations confined to a workspace project's cwd.

Endpoint surface mirrors what claudecodeui's git panel uses, scoped down
to the subset we implement (status / diff / stage / unstage / discard /
commit / log). All operations resolve the cwd from the project_id, so
the client never passes a raw filesystem path.
"""
from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.core.security import require_user
from app.services import git_ops

router = APIRouter()


class StageBody(BaseModel):
    project_id: str
    paths: List[str]


class CommitBody(BaseModel):
    project_id: str
    message: str
    allow_empty: bool = False


def _exec_git(call):
    """Wrap a call into the typical GitError → HTTPException mapping."""
    try:
        return call()
    except git_ops.GitError as e:
        raise HTTPException(400, str(e))


@router.get("/git/status")
def status(project_id: str = Query(...), _u: str = Depends(require_user)):
    return _exec_git(lambda: git_ops.get_status(project_id))


@router.get("/git/diff")
def diff(
    project_id: str = Query(...),
    file: str = Query(...),
    staged: bool = Query(False),
    _u: str = Depends(require_user),
):
    return _exec_git(lambda: git_ops.get_diff(project_id, file, staged=staged))


@router.post("/git/stage")
def stage(body: StageBody, _u: str = Depends(require_user)):
    return _exec_git(lambda: git_ops.stage(body.project_id, body.paths))


@router.post("/git/unstage")
def unstage(body: StageBody, _u: str = Depends(require_user)):
    return _exec_git(lambda: git_ops.unstage(body.project_id, body.paths))


@router.post("/git/discard")
def discard(body: StageBody, _u: str = Depends(require_user)):
    return _exec_git(lambda: git_ops.discard(body.project_id, body.paths))


@router.post("/git/commit")
def commit(body: CommitBody, _u: str = Depends(require_user)):
    return _exec_git(lambda: git_ops.commit(body.project_id, body.message, allow_empty=body.allow_empty))


@router.get("/git/log")
def log(
    project_id: str = Query(...),
    limit: int = Query(20, ge=1, le=200),
    _u: str = Depends(require_user),
):
    return _exec_git(lambda: git_ops.get_log(project_id, limit))
