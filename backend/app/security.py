"""JWT authentication and database-backed identity validation."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.models import UserAccount
from app.db.session import get_db_session

TOKEN_ISSUER = "medstockiq"
TOKEN_AUDIENCE = "medstockiq-api"
ACCESS_TOKEN_TTL_MINUTES = 30
_bearer_scheme = HTTPBearer(auto_error=False)


class AuthenticatedUser(BaseModel):
    """Identity loaded from a verified access token and active database account."""

    user_id: str
    email: str


def get_token_secret() -> str:
    """Return a strong configured JWT key; never silently fall back to a known default."""
    secret = os.getenv("AUTH_TOKEN_SECRET", "").strip()
    if (
        len(secret.encode("utf-8")) < 32
        or "replace-me" in secret.casefold()
        or "change-this" in secret.casefold()
    ):
        raise HTTPException(
            status_code=503,
            detail="Authentication is not configured. Set AUTH_TOKEN_SECRET to a random secret of at least 32 bytes.",
        )
    return secret


def create_access_token(user_id: str) -> tuple[str, datetime]:
    """Issue a short-lived signed access token for a verified account."""
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(minutes=ACCESS_TOKEN_TTL_MINUTES)
    claims = {
        "sub": user_id,
        "iss": TOKEN_ISSUER,
        "aud": TOKEN_AUDIENCE,
        "iat": now,
        "exp": expires_at,
        "typ": "access",
    }
    token = jwt.encode(claims, get_token_secret(), algorithm="HS256")
    return token, expires_at


def get_current_principal(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    session: Session = Depends(get_db_session),
) -> AuthenticatedUser:
    """Validate token signature and expiry, then reject deleted/disabled accounts."""
    if credentials is None or credentials.scheme.casefold() != "bearer":
        raise HTTPException(
            status_code=401,
            detail="A valid bearer access token is required.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        claims = jwt.decode(
            credentials.credentials,
            get_token_secret(),
            algorithms=["HS256"],
            issuer=TOKEN_ISSUER,
            audience=TOKEN_AUDIENCE,
            options={"require": ["sub", "iss", "aud", "iat", "exp", "typ"]},
        )
    except HTTPException:
        raise
    except jwt.InvalidTokenError as exc:
        raise HTTPException(
            status_code=401,
            detail="The access token is invalid or expired.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    if claims.get("typ") != "access" or not isinstance(claims.get("sub"), str):
        raise HTTPException(
            status_code=401,
            detail="The access token is invalid or expired.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    account = session.get(UserAccount, claims["sub"])
    if account is None or not account.is_active:
        raise HTTPException(
            status_code=401,
            detail="The account is unavailable.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return AuthenticatedUser(user_id=account.user_id, email=account.email)
