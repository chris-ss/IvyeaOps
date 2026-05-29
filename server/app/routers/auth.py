"""Auth: register / login / logout / me + admin user management."""
from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel

from app.core.config import settings
from app.core.security import (
    ADMIN_ID,
    hash_password,
    issue_session,
    require_admin,
    require_user,
    require_user_info,
    verify_password,
)
from app.services import users_service

router = APIRouter()


def _set_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=settings.session_cookie_name,
        value=token,
        max_age=settings.session_max_age_seconds,
        httponly=True,
        samesite="lax",
        secure=bool(settings.cookie_domain),
        path="/",
        domain=settings.cookie_domain or None,
    )


class LoginBody(BaseModel):
    username: str            # admin username OR a registered user's email
    password: str


class LoginOk(BaseModel):
    username: str
    role: str
    permissions: List[str] = []
    position: str = ""


@router.post("/login", response_model=LoginOk)
def login(body: LoginBody, response: Response) -> LoginOk:
    from app.core import hub_settings as _hs
    account = body.username.strip()

    # Admin path (env / hub_settings password).
    effective_hash = _hs.get("password_hash") or settings.admin_password_hash
    if account == settings.admin_user and verify_password(body.password, effective_hash):
        _set_cookie(response, issue_session(ADMIN_ID, "admin"))
        return LoginOk(username=settings.admin_user, role="admin")

    # Registered-user path (email + password, must be active).
    try:
        u = users_service.verify_login(account, body.password)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(e))
    _set_cookie(response, issue_session(u["id"], u.get("role", "user")))
    return LoginOk(
        username=u["email"],
        role=u.get("role", "user"),
        permissions=u.get("permissions", []) or [],
        position=u.get("position", ""),
    )


class RegisterBody(BaseModel):
    email: str
    password: str


@router.post("/register")
def register(body: RegisterBody) -> dict:
    try:
        users_service.create_user(body.email, body.password)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    return {"ok": True, "message": "注册成功，待管理员审批后即可登录"}


@router.post("/logout")
def logout(response: Response) -> dict:
    response.delete_cookie(
        key=settings.session_cookie_name,
        path="/",
        domain=settings.cookie_domain or None,
    )
    return {"ok": True}


@router.get("/me", response_model=LoginOk)
def me(cu: dict = Depends(require_user_info)) -> LoginOk:
    return LoginOk(
        username=cu["email"],
        role=cu.get("role", "user"),
        permissions=cu.get("permissions", []) or [],
        position=cu.get("position", ""),
    )


class ChangePasswordBody(BaseModel):
    old_password: str
    new_password: str


@router.post("/change-password")
def change_password(body: ChangePasswordBody, _user: str = Depends(require_admin)) -> dict:
    if not verify_password(body.old_password, settings.admin_password_hash):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="旧密码错误")
    if len(body.new_password) < 8:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="新密码至少8位")
    new_hash = hash_password(body.new_password)
    from app.core import hub_settings as _hs
    _hs.save({"password_hash": new_hash})
    settings.admin_password_hash = new_hash
    return {"ok": True}


@router.get("/verify", status_code=204)
def verify(_user: str = Depends(require_user)) -> None:
    return None


# ── Admin: user management ────────────────────────────────────────────────────

@router.get("/admin/users")
def admin_list_users(_user: str = Depends(require_admin)) -> List[dict]:
    return users_service.list_users()


class StatusBody(BaseModel):
    status: str


@router.post("/admin/users/{uid}/status")
def admin_set_status(uid: int, body: StatusBody, _user: str = Depends(require_admin)) -> dict:
    try:
        users_service.set_status(uid, body.status)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    return {"ok": True}


class ResetPwBody(BaseModel):
    new_password: str


@router.post("/admin/users/{uid}/reset-password")
def admin_reset_password(uid: int, body: ResetPwBody, _user: str = Depends(require_admin)) -> dict:
    try:
        users_service.reset_password(uid, body.new_password)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    return {"ok": True}


@router.delete("/admin/users/{uid}")
def admin_delete_user(uid: int, _user: str = Depends(require_admin)) -> dict:
    users_service.delete_user(uid)
    return {"ok": True}


# ── Admin: module authorization ───────────────────────────────────────────────

@router.get("/admin/permissions-catalog")
def admin_permissions_catalog(_user: str = Depends(require_admin)) -> dict:
    """Grantable modules + position presets — the source of truth for the UI."""
    from app.core import permissions as perm
    return {"modules": perm.MODULE_CATALOG, "positions": perm.POSITION_PRESETS}


class PermissionsBody(BaseModel):
    position: str = ""
    permissions: List[str] = []


@router.post("/admin/users/{uid}/permissions")
def admin_set_permissions(uid: int, body: PermissionsBody, _user: str = Depends(require_admin)) -> dict:
    from app.core import permissions as perm
    clean = perm.sanitize_permissions(body.permissions)
    try:
        u = users_service.set_permissions(uid, body.position, clean)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    return {"ok": True, "position": u.get("position", ""), "permissions": u.get("permissions", [])}
