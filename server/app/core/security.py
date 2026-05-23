"""Session token and authentication dependencies.

Simple personal-use scheme:
- Password stored as a bcrypt hash in env.
- On successful login we issue a signed session token stored in an HTTP-only cookie.
- Token is an itsdangerous signed payload containing (username, issued_at).
"""
from __future__ import annotations

import time
from typing import Optional

import bcrypt
from fastapi import Cookie, HTTPException, status
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app.core.config import settings

_serializer = URLSafeTimedSerializer(settings.secret_key, salt="opshub.session")


def verify_password(plain: str, hashed: str) -> bool:
    if not hashed:
        return False
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except ValueError:
        return False


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def issue_session(username: str) -> str:
    return _serializer.dumps({"u": username, "t": int(time.time())})


def verify_session(token: str) -> Optional[str]:
    try:
        data = _serializer.loads(token, max_age=settings.session_max_age_seconds)
    except SignatureExpired:
        return None
    except BadSignature:
        return None
    if not isinstance(data, dict):
        return None
    return data.get("u")


def require_user(
    session: Optional[str] = Cookie(default=None, alias=settings.session_cookie_name),
) -> str:
    """FastAPI dependency: raise 401 if no valid session."""
    if not session:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="not authenticated")
    user = verify_session(session)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid session")
    return user
