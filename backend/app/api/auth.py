"""Account registration, login, tenant creation, and membership administration."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from pwdlib import PasswordHash
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import Organization, OrganizationMembership, UserAccount
from app.db.session import get_db_session
from app.security import (
    ACCESS_TOKEN_TTL_MINUTES,
    AuthenticatedUser,
    create_access_token,
    get_current_principal,
    get_token_secret,
)

router = APIRouter(prefix="/api/v1", tags=["authentication and organizations"])
_password_hash = PasswordHash.recommended()
_DUMMY_PASSWORD_HASH = _password_hash.hash("not-a-real-password-used-for-timing-only")
_EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
ALLOWED_ROLES = {"owner", "admin", "member", "viewer"}
WRITER_ROLES = {"owner", "admin", "member"}


class CredentialsRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=12, max_length=128)

    @field_validator("email")
    @classmethod
    def normalize_and_validate_email(cls, value: str) -> str:
        normalized = value.strip().casefold()
        if not _EMAIL_PATTERN.fullmatch(normalized):
            raise ValueError("Enter a valid email address.")
        return normalized


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: dict[str, str]


class OrganizationCreateRequest(BaseModel):
    display_name: str = Field(min_length=2, max_length=200)

    @field_validator("display_name")
    @classmethod
    def clean_display_name(cls, value: str) -> str:
        normalized = value.strip()
        if len(normalized) < 2:
            raise ValueError("Organization name must contain at least two characters.")
        return normalized


class AddMemberRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    role: str = "member"

    @field_validator("email")
    @classmethod
    def normalize_and_validate_email(cls, value: str) -> str:
        normalized = value.strip().casefold()
        if not _EMAIL_PATTERN.fullmatch(normalized):
            raise ValueError("Enter a valid email address.")
        return normalized

    @field_validator("role")
    @classmethod
    def validate_role(cls, value: str) -> str:
        normalized = value.strip().casefold()
        if normalized not in ALLOWED_ROLES:
            raise ValueError("Role must be owner, admin, member, or viewer.")
        return normalized


def _auth_response(account: UserAccount) -> AuthResponse:
    token, _expires_at = create_access_token(account.user_id)
    return AuthResponse(
        access_token=token,
        expires_in=ACCESS_TOKEN_TTL_MINUTES * 60,
        user={"user_id": account.user_id, "email": account.email},
    )


def _require_membership(
    session: Session,
    user_id: str,
    organization_id: str,
    allowed_roles: set[str] | None = None,
) -> OrganizationMembership:
    organization = session.get(Organization, organization_id)
    membership = session.get(OrganizationMembership, (organization_id, user_id))
    # Conceal both tenant existence and membership from users outside that tenant.
    if organization is None or not organization.is_active or membership is None:
        raise HTTPException(status_code=404, detail="Organization was not found.")
    if allowed_roles is not None and membership.role not in allowed_roles:
        raise HTTPException(status_code=403, detail="Your organization role cannot perform this action.")
    return membership


@router.post("/auth/register", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
def register_account(
    payload: CredentialsRequest,
    session: Session = Depends(get_db_session),
) -> AuthResponse:
    """Create a standalone account. Registration never grants organization access."""
    get_token_secret()  # fail closed before inserting an account if JWT is misconfigured
    account = UserAccount(
        user_id=str(uuid4()),
        email=payload.email,
        password_hash=_password_hash.hash(payload.password),
        is_active=True,
    )
    session.add(account)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail="An account with this email already exists.") from exc
    return _auth_response(account)


@router.post("/auth/token", response_model=AuthResponse)
def login(
    payload: CredentialsRequest,
    session: Session = Depends(get_db_session),
) -> AuthResponse:
    """Verify credentials and return a short-lived bearer access token."""
    get_token_secret()
    account = session.scalar(select(UserAccount).where(UserAccount.email == payload.email))
    if account is None:
        _password_hash.verify(payload.password, _DUMMY_PASSWORD_HASH)
        raise HTTPException(status_code=401, detail="Email or password is incorrect.")
    if not _password_hash.verify(payload.password, account.password_hash) or not account.is_active:
        raise HTTPException(status_code=401, detail="Email or password is incorrect.")

    account.last_login_at = datetime.now(timezone.utc)
    session.commit()
    return _auth_response(account)


@router.post("/organizations", status_code=status.HTTP_201_CREATED)
def create_organization(
    payload: OrganizationCreateRequest,
    principal: AuthenticatedUser = Depends(get_current_principal),
    session: Session = Depends(get_db_session),
) -> dict[str, str]:
    """Create a tenant for the authenticated user, who becomes its owner."""
    organization = Organization(
        organization_id=str(uuid4()),
        display_name=payload.display_name,
        is_active=True,
    )
    session.add(organization)
    session.add(
        OrganizationMembership(
            organization_id=organization.organization_id,
            user_id=principal.user_id,
            role="owner",
        )
    )
    session.commit()
    return {
        "organization_id": organization.organization_id,
        "display_name": organization.display_name,
        "role": "owner",
    }


@router.get("/organizations")
def list_my_organizations(
    principal: AuthenticatedUser = Depends(get_current_principal),
    session: Session = Depends(get_db_session),
) -> dict[str, list[dict[str, str]]]:
    """List only organizations in which the authenticated account is a member."""
    rows = session.execute(
        select(Organization, OrganizationMembership.role)
        .join(
            OrganizationMembership,
            OrganizationMembership.organization_id == Organization.organization_id,
        )
        .where(
            OrganizationMembership.user_id == principal.user_id,
            Organization.is_active.is_(True),
        )
        .order_by(Organization.display_name)
    ).all()
    return {
        "organizations": [
            {
                "organization_id": organization.organization_id,
                "display_name": organization.display_name,
                "role": role,
            }
            for organization, role in rows
        ]
    }


@router.post("/organizations/{organization_id}/members", status_code=status.HTTP_201_CREATED)
def add_organization_member(
    organization_id: str,
    payload: AddMemberRequest,
    principal: AuthenticatedUser = Depends(get_current_principal),
    session: Session = Depends(get_db_session),
) -> dict[str, str]:
    """Grant access to an already registered user; organization IDs are never self-asserted."""
    actor = _require_membership(
        session, principal.user_id, organization_id, allowed_roles={"owner", "admin"}
    )
    if actor.role == "admin" and payload.role in {"owner", "admin"}:
        raise HTTPException(status_code=403, detail="Admins cannot grant owner or admin roles.")

    target = session.scalar(select(UserAccount).where(UserAccount.email == payload.email))
    if target is None or not target.is_active:
        raise HTTPException(
            status_code=404,
            detail="No active account exists for that email; the user must register first.",
        )
    if session.get(OrganizationMembership, (organization_id, target.user_id)) is not None:
        raise HTTPException(status_code=409, detail="That account is already a member of this organization.")

    membership = OrganizationMembership(
        organization_id=organization_id,
        user_id=target.user_id,
        role=payload.role,
    )
    session.add(membership)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail="Could not create the organization membership.") from exc
    return {
        "organization_id": organization_id,
        "user_id": target.user_id,
        "email": target.email,
        "role": membership.role,
    }


@router.delete("/organizations/{organization_id}/members/{user_id}")
def remove_organization_member(
    organization_id: str,
    user_id: str,
    principal: AuthenticatedUser = Depends(get_current_principal),
    session: Session = Depends(get_db_session),
) -> dict[str, str | bool]:
    """Revoke tenant access without deleting the user's account or other memberships."""
    actor = _require_membership(
        session, principal.user_id, organization_id, allowed_roles={"owner", "admin"}
    )
    target = session.get(OrganizationMembership, (organization_id, user_id))
    if target is None:
        raise HTTPException(status_code=404, detail="Organization membership was not found.")
    if actor.role == "admin" and target.role in {"owner", "admin"}:
        raise HTTPException(status_code=403, detail="Admins cannot remove owners or other admins.")
    if target.role == "owner":
        owner_count = session.scalar(
            select(func.count())
            .select_from(OrganizationMembership)
            .where(
                OrganizationMembership.organization_id == organization_id,
                OrganizationMembership.role == "owner",
            )
        )
        if owner_count is not None and owner_count <= 1:
            raise HTTPException(status_code=409, detail="An organization must retain at least one owner.")

    session.delete(target)
    session.commit()
    return {"organization_id": organization_id, "user_id": user_id, "removed": True}


@router.get("/organizations/{organization_id}/members")
def list_organization_members(
    organization_id: str,
    principal: AuthenticatedUser = Depends(get_current_principal),
    session: Session = Depends(get_db_session),
) -> dict[str, list[dict[str, str]]]:
    """List member identities only for an organization the caller administers."""
    _require_membership(
        session, principal.user_id, organization_id, allowed_roles={"owner", "admin"}
    )
    rows = session.execute(
        select(UserAccount, OrganizationMembership.role)
        .join(OrganizationMembership, OrganizationMembership.user_id == UserAccount.user_id)
        .where(OrganizationMembership.organization_id == organization_id)
        .order_by(UserAccount.email)
    ).all()
    return {
        "members": [
            {"user_id": account.user_id, "email": account.email, "role": role}
            for account, role in rows
        ]
    }
