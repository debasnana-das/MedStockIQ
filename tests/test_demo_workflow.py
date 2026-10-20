from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.session import get_db_session
from app.main import app
from app.security import get_current_principal
from synthetic_data.generate_dataset import DEFAULT_AS_OF
from synthetic_data.generate_demo_inputs import generate_demo_inputs
from synthetic_data.run_api_demo import profile_and_normalize


@pytest.fixture
def authenticated_demo_client(monkeypatch: pytest.MonkeyPatch):
    """Exercise real bearer auth and persistence against isolated in-memory SQLite."""
    monkeypatch.setenv(
        "AUTH_TOKEN_SECRET",
        "test-only-demo-workflow-secret-never-use-outside-ci-123456789",
    )
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(dbapi_connection, _connection_record) -> None:
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
            yield client
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


def test_synthetic_uploads_run_through_profile_confirm_normalize_and_analysis(
    authenticated_demo_client: TestClient,
    tmp_path: Path,
) -> None:
    client = authenticated_demo_client
    as_of = DEFAULT_AS_OF
    files = generate_demo_inputs(tmp_path / "demo-inputs", as_of_date=as_of, seed=42)

    registration = client.post(
        "/api/v1/auth/register",
        json={"email": "synthetic-demo@example.test", "password": "Synthetic-demo-password-42!"},
    )
    assert registration.status_code == 201, registration.text
    headers = {"Authorization": f"Bearer {registration.json()['access_token']}"}
    organization_response = client.post(
        "/api/v1/organizations",
        headers=headers,
        json={"display_name": "Synthetic End-to-End Demo"},
    )
    assert organization_response.status_code == 201, organization_response.text
    organization_id = organization_response.json()["organization_id"]

    first_date = as_of - timedelta(days=364)
    purchase_profile, purchase_confirm, purchase_run = profile_and_normalize(
        client, headers, files["purchase_invoice_upload"],
        {
            "organization_id": organization_id,
            "document_type": "purchase_invoice",
            "counterparty_id": "SYN-SUPPLIER-001",
            "currency_code": "INR",
        },
    )
    inventory_profile, inventory_confirm, inventory_run = profile_and_normalize(
        client, headers, files["inventory_snapshot_upload"],
        {
            "organization_id": organization_id,
            "document_type": "inventory_report",
            "snapshot_date": as_of.isoformat(),
            "inventory_snapshot_complete": True,
            "inventory_stock_basis": "physical",
            "currency_code": "INR",
        },
    )
    sales_profile, sales_confirm, sales_run = profile_and_normalize(
        client, headers, files["retail_sales_upload"],
        {
            "organization_id": organization_id,
            "document_type": "retail_sales",
            "sales_history_complete": True,
            "sales_history_start_date": first_date.isoformat(),
            "sales_history_end_date": as_of.isoformat(),
        },
    )

    assert purchase_confirm["schema_status"] == "confirmed"
    assert inventory_confirm["schema_status"] == "confirmed"
    assert sales_confirm["schema_status"] == "confirmed"
    assert purchase_run["summary"]["transaction_count"] > 0
    assert inventory_run["summary"]["inventory_snapshot_count"] > 0
    assert sales_profile["row_count_profiled"] == 365 * 8
    assert sales_run["summary"]["transaction_count"] == 365 * 8
    assert sales_run["quality_report"]["forecasting_baseline"]["status"] != "insufficient_data"

    inventory_analysis = inventory_run["quality_report"]["inventory_analysis"]
    assert inventory_analysis["summary"]["expiry_alert_count"] > 0
    assert all(row["stock_basis"] == "physical"
               for row in inventory_run["previews"]["inventory_snapshots"])

    saved_run = client.get(
        f"/api/v1/normalization-runs/{inventory_run['normalization_run_id']}",
        headers=headers,
        params={"organization_id": organization_id},
    )
    assert saved_run.status_code == 200, saved_run.text
    history = client.get(
        "/api/v1/inventory-history",
        headers=headers,
        params={"organization_id": organization_id, "as_of_date": as_of.isoformat()},
    )
    assert history.status_code == 200, history.text
    assert history.json()["series"]

    overstock = client.get(
        "/api/v1/overstock-review",
        headers=headers,
        params={
            "organization_id": organization_id,
            "sales_run_id": sales_run["normalization_run_id"],
            "as_of_date": as_of.isoformat(),
            "target_days_of_supply": 30,
        },
    )
    assert overstock.status_code == 200, overstock.text
    report = overstock.json()
    assert report["summary"]["above_target_count"] > 0
    assert any(
        item.get("source_product_code") == "SRC-004" and item["status"] == "above_target"
        for item in report["findings"]
    )
