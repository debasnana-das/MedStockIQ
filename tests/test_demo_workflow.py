from __future__ import annotations

from datetime import date, timedelta
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
    baseline = sales_run["quality_report"]["forecasting_baseline"]
    assert baseline["status"] != "insufficient_data"
    assert baseline["coverage"]["start_date"] == first_date.isoformat()
    assert baseline["coverage"]["end_date"] == as_of.isoformat()
    sales_products = {
        row["product_id"]: row for row in sales_run["previews"]["products"]
    }
    forecast_series_by_code = {
        sales_products[row["product_id"]]["source_product_code"]: row
        for row in baseline["series"]
    }
    for forecast_row in baseline["forecasts"]:
        expected_dates = [
            (as_of + timedelta(days=offset)).isoformat()
            for offset in range(1, 8)
        ]
        assert forecast_row["trained_through_date"] == as_of.isoformat()
        assert [item["date"] for item in forecast_row["daily_forecast"]] == expected_dates
        assert abs(
            forecast_row["predicted_total_quantity"]
            - sum(item["predicted_quantity"] for item in forecast_row["daily_forecast"])
        ) < 0.00001

    inventory_analysis = inventory_run["quality_report"]["inventory_analysis"]
    assert inventory_analysis["as_of_date"] == as_of.isoformat()
    assert inventory_analysis["summary"]["expiry_alert_count"] > 0
    october_batch_alert = next(
        alert for alert in inventory_analysis["expiry_alerts"]
        if alert["batch_code"] == "B-005-0075"
    )
    assert october_batch_alert["alert_type"] == "expires_within_90_days"
    assert october_batch_alert["source_product_code"] == "SRC-005"
    assert october_batch_alert["days_to_expiry"] == (
        date.fromisoformat(october_batch_alert["expiry_date"]) - as_of
    ).days
    assert all(row["stock_basis"] == "physical"
               for row in inventory_run["previews"]["inventory_snapshots"])

    inventory_products = {
        row["product_id"]: row for row in inventory_run["previews"]["products"]
    }
    inventory_batches = {
        row["batch_record_id"]: row for row in inventory_run["previews"]["batches"]
    }
    inventory_snapshots = inventory_run["previews"]["inventory_snapshots"]
    assert inventory_run["summary"]["inventory_snapshot_count"] == len(inventory_snapshots)
    assert all(date.fromisoformat(row["snapshot_date"]) <= as_of for row in inventory_snapshots)
    snapshot_by_code_batch = {
        (
            inventory_products[row["product_id"]]["source_product_code"],
            inventory_batches[row["batch_record_id"]]["batch_code"],
        ): row
        for row in inventory_snapshots
    }
    for alert in inventory_analysis["expiry_alerts"]:
        assert alert["source_product_code"] == inventory_products[alert["product_id"]]["source_product_code"]
        snapshot = snapshot_by_code_batch[(alert["source_product_code"], alert["batch_code"])]
        assert alert["quantity_on_hand"] == snapshot["quantity_on_hand"]
        assert alert["quantity_unit"] == snapshot["quantity_unit"]

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
    history_payload = history.json()
    assert history_payload["as_of_date"] == as_of.isoformat()
    assert history_payload["series"]
    assert history_payload["summary"]["input_snapshot_count"] == len(inventory_snapshots)
    assert {
        point["snapshot_date"]
        for item in history_payload["series"]
        for point in item["history"]
        if point.get("snapshot_date")
    } == {as_of.isoformat()}
    # Every series exposes product metadata through the documented nested object.
    assert all(isinstance(item.get("product"), dict) for item in history_payload["series"])
    assert all(item["product"].get("product_name") for item in history_payload["series"])
    assert all(item["product"].get("source_product_code") for item in history_payload["series"])
    for item in history_payload["series"]:
        if item["latest_quantity_known"] is False:
            latest = item["latest_observation"]
            assert latest["status"] == "conflict" or item["unit_status"] == "conflict"

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
    assert report["as_of_date"] == as_of.isoformat()
    assert report["summary"]["above_target_count"] > 0
    assert report["as_of_date"] == inventory_analysis["as_of_date"] == history_payload["as_of_date"]
    assert any(
        item.get("source_product_code") == "SRC-004" and item["status"] == "above_target"
        for item in report["findings"]
    )

    stock_quantity_by_code_unit = {}
    for snapshot in inventory_snapshots:
        code = inventory_products[snapshot["product_id"]]["source_product_code"]
        key = (code, snapshot["quantity_unit"].casefold())
        stock_quantity_by_code_unit[key] = stock_quantity_by_code_unit.get(key, 0) + snapshot["quantity_on_hand"]
    findings_by_code = {
        item["source_product_code"]: item
        for item in report["findings"]
        if item.get("source_product_code") and item.get("inventory_quantity") is not None
    }
    for code, finding in findings_by_code.items():
        key = (code, finding["quantity_unit"].casefold())
        if key in stock_quantity_by_code_unit:
            assert abs(finding["inventory_quantity"] - stock_quantity_by_code_unit[key]) < 0.00001
        if code in forecast_series_by_code and finding.get("average_daily_demand") is not None:
            assert abs(
                finding["average_daily_demand"]
                - forecast_series_by_code[code]["average_daily_demand"]
            ) < 0.00001

    for item in report["findings"]:
        if item.get("inventory_snapshot_date"):
            assert item["inventory_snapshot_date"] <= as_of.isoformat()
        if item.get("total_quantity_sold") is not None and item.get("average_daily_demand") is not None:
            expected_adu = item["total_quantity_sold"] / item["sales_history_days"]
            assert abs(item["average_daily_demand"] - expected_adu) < 0.00001

    saved_runs = client.get(
        "/api/v1/normalization-runs",
        headers=headers,
        params={"organization_id": organization_id, "limit": 10},
    )
    assert saved_runs.status_code == 200, saved_runs.text
    listed = saved_runs.json()["runs"]
    assert len(listed) == 3
    assert {row["document_type"] for row in listed} == {
        "purchase_invoice", "inventory_report", "retail_sales"
    }
    assert all(row["organization_id"] == organization_id for row in listed)
