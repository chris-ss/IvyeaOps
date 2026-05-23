"""Login / logout / me."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel

from app.core.config import settings
from app.core.security import (
    hash_password,
    issue_session,
    require_user,
    verify_password,
)

router = APIRouter()


class LoginBody(BaseModel):
    username: str
    password: str


class LoginOk(BaseModel):
    username: str


@router.post("/login", response_model=LoginOk)
def login(body: LoginBody, response: Response) -> LoginOk:
    from app.core import hub_settings as _hs
    # Hub-settings password_hash takes precedence (set via UI change-password)
    effective_hash = _hs.get("password_hash") or settings.admin_password_hash
    if body.username != settings.admin_user or not verify_password(body.password, effective_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid credentials",
        )
    token = issue_session(body.username)
    response.set_cookie(
        key=settings.session_cookie_name,
        value=token,
        max_age=settings.session_max_age_seconds,
        httponly=True,
        samesite="lax",
        secure=not settings.dev_mode,
        path="/",
        domain=settings.cookie_domain or None,
    )
    return LoginOk(username=body.username)


@router.post("/logout")
def logout(response: Response) -> dict:
    response.delete_cookie(
        key=settings.session_cookie_name,
        path="/",
        domain=settings.cookie_domain or None,
    )
    return {"ok": True}


@router.get("/me", response_model=LoginOk)
def me(user: str = Depends(require_user)) -> LoginOk:
    return LoginOk(username=user)


class ChangePasswordBody(BaseModel):
    old_password: str
    new_password: str


@router.post("/change-password")
def change_password(body: ChangePasswordBody, _user: str = Depends(require_user)) -> dict:
    if not verify_password(body.old_password, settings.admin_password_hash):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="旧密码错误")
    if len(body.new_password) < 8:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="新密码至少8位")
    new_hash = hash_password(body.new_password)
    # Persist to hub_settings so it survives without .env edits
    from app.core import hub_settings as _hs
    _hs.save({"password_hash": new_hash})
    # Also update the live settings object so the current process validates correctly
    settings.admin_password_hash = new_hash
    return {"ok": True}


@router.get("/verify", status_code=204)
def verify(_user: str = Depends(require_user)) -> None:
    """Lightweight auth check for nginx auth_request.

    Returns 204 when session is valid, 401 otherwise (via require_user).
    No body, no JSON serialisation — minimal overhead.
    """
    return None
