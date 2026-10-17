from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select, update
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.models import UserAccount
from app.db.session import get_db_session
from app.main import app
from app.security import get_current_principal
from pwdlib import PasswordHash


@pytest.fixture
def auth_context(monkeypatch: pytest.MonkeyPatch):
    """Run the real registration, token, account, and tenant checks against isolated SQLite."""
    monkeypatch.setenv(
        "AUTH_TOKEN_SECRET",
        "test-only-secret-for-the-medstockiq-auth-test-suite-123456789",
    )
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    @event.listens_for(engine, "connect")
    def enable_sqlite_foreign_keys(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)

    def override_db_session():
        with Session(engine) as session:
            try:
                yield session
            except Exception:
                session.rollback()
                raise

    old_db_override = app.dependency_overrides.get(get_db_session)
    old_principal_override = app.dependency_overrides.get(get_current_principal)
    app.dependency_overrides[get_db_session] = override_db_session
    app.dependency_overrides.pop(get_current_principal, None)
    try:
        with TestClient(app) as client:
            yield client, engine
    finally:
        if old_db_override is None:
            app.dependency_overrides.pop(get_db_session, None)
        else:
            app.dependency_overrides[get_db_session] = old_db_override
        if old_principal_override is None:
            app.dependency_overrides.pop(get_current_principal, None)
        else:
            app.dependency_overrides[get_current_principal] = old_principal_override
        Base.metadata.drop_all(engine)
        engine.dispose()


def _register(client: TestClient, email: str) -> tuple[str, dict]:
    response = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "Correct-horse-battery-42"},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    return body["access_token"], body


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_protected_endpoints_require_valid_access_token(auth_context) -> None:
    client, _engine = auth_context
    unauthenticated = client.get("/api/v1/schema/fields")
    assert unauthenticated.status_code == 401

    token, body = _register(client, " New.User@Example.Test ")
    assert body["expires_in"] == 1800
    assert client.get("/api/v1/schema/fields", headers=_headers(token)).status_code == 200
    assert client.get("/api/v1/schema/fields", headers=_headers(token[:-5] + "xxxxx")).status_code == 401


def test_registration_hashes_password_and_grants_no_organization_access(auth_context) -> None:
    client, engine = auth_context
    token, body = _register(client, "private@example.test")
    assert client.get("/api/v1/organizations", headers=_headers(token)).json() == {"organizations": []}

    with Session(engine) as session:
        account = session.scalar(
            select(UserAccount).where(UserAccount.email == "private@example.test")
        )
        assert account is not None
        assert account.password_hash != "Correct-horse-battery-42"
        assert PasswordHash.recommended().verify(
            "Correct-horse-battery-42", account.password_hash
        )

    duplicate = client.post(
        "/api/v1/auth/register",
        json={"email": "PRIVATE@example.test", "password": "Correct-horse-battery-42"},
    )
    assert duplicate.status_code == 409

    correct_login = client.post(
        "/api/v1/auth/token",
        json={"email": "PRIVATE@example.test", "password": "Correct-horse-battery-42"},
    )
    assert correct_login.status_code == 200, correct_login.text
    assert client.get(
        "/api/v1/schema/fields",
        headers=_headers(correct_login.json()["access_token"]),
    ).status_code == 200

    wrong_password = client.post(
        "/api/v1/auth/token",
        json={"email": "private@example.test", "password": "Incorrect-password-123"},
    )
    assert wrong_password.status_code == 401


def test_organization_roles_are_isolated_and_viewers_cannot_administer_or_write(auth_context) -> None:
    client, _engine = auth_context
    owner_a_token, owner_a_body = _register(client, "owner-a@example.test")
    owner_b_token, _ = _register(client, "owner-b@example.test")
    viewer_token, viewer_body = _register(client, "viewer@example.test")

    org_a_response = client.post(
        "/api/v1/organizations",
        json={"display_name": "Pharmacy A"},
        headers=_headers(owner_a_token),
    )
    org_b_response = client.post(
        "/api/v1/organizations",
        json={"display_name": "Stockist B"},
        headers=_headers(owner_b_token),
    )
    assert org_a_response.status_code == 201, org_a_response.text
    assert org_b_response.status_code == 201, org_b_response.text
    org_a = org_a_response.json()["organization_id"]
    org_b = org_b_response.json()["organization_id"]
    assert org_b != org_a

    add_viewer = client.post(
        f"/api/v1/organizations/{org_a}/members",
        json={"email": "viewer@example.test", "role": "viewer"},
        headers=_headers(owner_a_token),
    )
    assert add_viewer.status_code == 201, add_viewer.text
    assert add_viewer.json()["role"] == "viewer"

    viewer_orgs = client.get("/api/v1/organizations", headers=_headers(viewer_token)).json()
    assert [item["organization_id"] for item in viewer_orgs["organizations"]] == [org_a]

    # A user from another tenant cannot learn whether a run or member list exists.
    cross_tenant_run = client.get(
        "/api/v1/normalization-runs/00000000-0000-4000-8000-000000000099",
        params={"organization_id": org_a},
        headers=_headers(owner_b_token),
    )
    assert cross_tenant_run.status_code == 404

    cross_tenant_members = client.get(
        f"/api/v1/organizations/{org_a}/members",
        headers=_headers(owner_b_token),
    )
    assert cross_tenant_members.status_code == 404

    viewer_admin = client.get(
        f"/api/v1/organizations/{org_a}/members",
        headers=_headers(viewer_token),
    )
    assert viewer_admin.status_code == 403

    remove_sole_owner = client.delete(
        f"/api/v1/organizations/{org_a}/members/{owner_a_body['user']['user_id']}",
        headers=_headers(owner_a_token),
    )
    assert remove_sole_owner.status_code == 409

    confirmed_schema = {
        "profiled_columns": [{"column_index": 0, "source_column": "PRODUCT"}],
        "mappings": [{
            "column_index": 0,
            "source_column": "PRODUCT",
            "action": "map",
            "canonical_field": "product_name",
        }],
    }
    viewer_persist = client.post(
        "/api/v1/normalize",
        headers=_headers(viewer_token),
        data={
            "confirmed_schema_json": json.dumps(confirmed_schema),
            "options_json": json.dumps({
                "organization_id": org_a,
                "document_type": "unknown",
            }),
            "persist": "true",
        },
        files={"file": ("sample.csv", b"PRODUCT\nExample medicine\n", "text/csv")},
    )
    assert viewer_persist.status_code == 403, viewer_persist.text

    revoked = client.delete(
        f"/api/v1/organizations/{org_a}/members/{viewer_body['user']['user_id']}",
        headers=_headers(owner_a_token),
    )
    assert revoked.status_code == 200, revoked.text
    assert client.get("/api/v1/organizations", headers=_headers(viewer_token)).json() == {
        "organizations": []
    }
    after_revocation = client.get(
        f"/api/v1/organizations/{org_a}/members",
        headers=_headers(viewer_token),
    )
    assert after_revocation.status_code == 404


def test_disabled_account_cannot_continue_using_existing_token(auth_context) -> None:
    client, engine = auth_context
    token, body = _register(client, "disable-me@example.test")
    user_id = body["user"]["user_id"]
    with Session(engine) as session:
        session.execute(update(UserAccount).where(UserAccount.user_id == user_id).values(is_active=False))
        session.commit()

    response = client.get("/api/v1/schema/fields", headers=_headers(token))
    assert response.status_code == 401
