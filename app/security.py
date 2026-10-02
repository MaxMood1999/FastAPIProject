import hashlib
import secrets
from datetime import timedelta
from typing import Annotated

import jwt
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pwdlib import PasswordHash
from sqlalchemy import select

from app.common import DB, APIError
from app.config import get_settings
from app.models import RefreshSession, User, utcnow

passwords = PasswordHash.recommended()
dummy_hash = passwords.hash("dummy-password-for-timing-only")
bearer = HTTPBearer(auto_error=False)


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def issue_tokens(db, user):
    cfg = get_settings()
    now = utcnow()
    token = jwt.encode(
        {
            "sub": str(user.id),
            "ver": user.token_version,
            "type": "access",
            "iat": now,
            "exp": now + timedelta(minutes=cfg.access_token_minutes),
            "iss": "education-crm",
            "aud": "crm-api",
        },
        cfg.jwt_secret,
        algorithm="HS256",
    )
    refresh = secrets.token_urlsafe(48)
    db.add(
        RefreshSession(
            user_id=user.id,
            token_hash=digest(refresh),
            token_version=user.token_version,
            expires_at=now + timedelta(days=cfg.refresh_token_days),
        )
    )
    return {
        "access_token": token,
        "refresh_token": refresh,
        "token_type": "bearer",
        "expires_in": cfg.access_token_minutes * 60,
    }


def current_user(
    db: DB, credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]
):
    try:
        if credentials is None:
            raise ValueError()
        data = jwt.decode(
            credentials.credentials,
            get_settings().jwt_secret,
            algorithms=["HS256"],
            issuer="education-crm",
            audience="crm-api",
            options={"require": ["sub", "exp", "iat", "ver", "type"]},
        )
        user = db.scalar(select(User).where(User.id == int(data["sub"])))
        if (
            not user
            or not user.is_active
            or data["type"] != "access"
            or data["ver"] != user.token_version
        ):
            raise ValueError()
        return user
    except (jwt.PyJWTError, ValueError, TypeError, KeyError):
        raise APIError(401, "unauthorized", "Avtorizatsiya talab qilinadi") from None


Current = Annotated[User, Depends(current_user)]


def roles(*allowed):
    def check(user: Current):
        if user.role not in allowed:
            raise APIError(403, "forbidden", "Ruxsat yo'q")
        return user

    return check


Staff = Annotated[User, Depends(roles("admin", "manager"))]
Admin = Annotated[User, Depends(roles("admin"))]
