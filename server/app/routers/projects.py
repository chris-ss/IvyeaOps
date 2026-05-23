"""GET /api/projects — list workspace projects + their sessions.

Plus transcript reading and "继续会话" (resume external Claude/Codex
rollouts via PTY).
"""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.core.security import require_user
from app.services import projects as proj_svc
from app.services import transcript as transcript_svc

router = APIRouter()


@router.get("/projects")
def list_projects(_user: str = Depends(require_user)) -> dict:
    """List all known projects (workspaces). Aggregates ops-hub
    agent_sessions, Claude jsonl logs, and Codex jsonl logs by cwd."""
    items = [p.to_dict() for p in proj_svc.list_projects()]
    return {"projects": items, "total": len(items)}


@router.post("/projects/refresh")
def refresh_projects(_user: str = Depends(require_user)) -> dict:
    """Force the in-memory project list cache to rebuild on next read."""
    proj_svc.refresh()
    return {"ok": True}


@router.get("/projects/{project_id}")
def get_project(project_id: str, _user: str = Depends(require_user)) -> dict:
    p = proj_svc.get_project(project_id)
    if p is None:
        raise HTTPException(404, "project not found")
    return p.to_dict()


@router.get("/projects/{project_id}/sessions")
def list_sessions(project_id: str, _user: str = Depends(require_user)) -> dict:
    p = proj_svc.get_project(project_id)
    if p is None:
        raise HTTPException(404, "project not found")
    sessions = [s.to_dict() for s in proj_svc.list_project_sessions(project_id)]
    return {
        "project": p.to_dict(),
        "sessions": sessions,
        "total": len(sessions),
    }


def _find_session(project_id: str, session_id: str):
    """Lookup a session within a project; returns the ProjectSession or
    raises 404."""
    p = proj_svc.get_project(project_id)
    if p is None:
        raise HTTPException(404, "project not found")
    for s in proj_svc.list_project_sessions(project_id):
        if s.id == session_id:
            return p, s
    raise HTTPException(404, "session not found")


@router.get("/projects/{project_id}/sessions/{session_id}/transcript")
def get_transcript(project_id: str, session_id: str, _user: str = Depends(require_user)) -> dict:
    """Parse an external jsonl session into a list of structured messages.

    Only returns content for `source in ('claude','codex')` — hub sessions
    have their own message history served via /api/agent-sessions/{id}/messages.
    """
    project, session = _find_session(project_id, session_id)
    if session.source == "hub":
        raise HTTPException(400, "hub sessions use /api/agent-sessions/{id}/messages")
    if not session.raw_path:
        raise HTTPException(404, "session has no on-disk transcript")
    path = Path(session.raw_path)
    if not path.is_file():
        raise HTTPException(404, "transcript file missing")
    if session.source == "claude":
        messages = transcript_svc.read_claude_jsonl(path)
    elif session.source == "codex":
        messages = transcript_svc.read_codex_jsonl(path)
    else:
        raise HTTPException(400, f"unsupported source: {session.source}")
    return {
        "project": project.to_dict(),
        "session": session.to_dict(),
        "messages": messages,
        "total": len(messages),
    }


class ResumeRequest(BaseModel):
    """Optional override fields when starting the resumed session."""
    title: str | None = None
    model: str | None = None


@router.post("/projects/{project_id}/sessions/{session_id}/resume")
def resume_session(
    project_id: str,
    session_id: str,
    body: ResumeRequest | None = None,
    _user: str = Depends(require_user),
) -> dict:
    """Create a new ops-hub agent_session that wraps the resumed CLI.

    What this does:
      1. Look up the external session (must be claude/codex; hub sessions
         have no need to "resume" — they already are interactive).
      2. Insert a new hub agent_session row with resume_target=<src>:<sid>.
      3. Caller then opens the agent CLI tab as usual; pty_manager will
         consume resume_target on first spawn and pass --resume / `codex
         resume <id>` to the binary.

    Returns the new hub session's id so the frontend can navigate to it.
    """
    from app.services import agent_session_service as svc

    project, session = _find_session(project_id, session_id)
    if session.source not in ("claude", "codex"):
        raise HTTPException(400, "only claude / codex sessions can be resumed")
    if not session.agent:
        raise HTTPException(400, "session has no agent attribution")

    title = (body.title if body and body.title else f"[继续] {session.title}")[:120]
    new_sess = svc.create_session(
        user_id="root",
        agent_id=session.agent,
        model=(body.model if body and body.model else None),
        title=title,
        workdir=project.path if project.path and project.path != "(unknown)" else None,
        resume_target=f"{session.source}:{session.id}",
    )
    # Bust the projects cache so the new hub session shows up immediately
    # under this project in the sidebar.
    proj_svc.refresh()
    return {
        "ok": True,
        "session_id": new_sess["id"],
        "project_id": project_id,
        "resume_target": f"{session.source}:{session.id}",
        "session": new_sess,
    }
