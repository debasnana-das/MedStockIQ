from __future__ import annotations

from contextlib import contextmanager
import os
from datetime import date
from typing import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, event, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api import normalization as normalization_api
from app.db.base import Base
from app.db.models import NormalizationRun
from app.db.persistence import get_persisted_normalization_preview, persist_normalization_result
from app.main import app
from app.normalization.normalizer import NormalizationOptions
from app.schema.confirmation import SchemaConfirmationRequest


@pytest.fixture
def database_engine():
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
    yield engine
    Base.metadata.drop_all(engine)
    engine.dispose()


def _schema() -> SchemaConfirmationRequest:
    return SchemaConfirmationRequest.model_validate(
        {
            "profiled_columns": [{"column_index": 0, "source_column": "PRODUCT"}],
            "mappings": [
                {
                    "column_index": 0,
                    "source_column": "PRODUCT",
                    "action": "map",
                    "canonical_field": "product_name",
                }
            ],
        }
    )


def _options(organization_id: str = "ORG-PERSIST-TEST") -> NormalizationOptions:
    return NormalizationOptions(
        organization_id=organization_id,
        document_type="purchase_invoice",
        document_number="INV-DB-001",
        document_date=date(2026, 10, 15),
        counterparty_id="SUPPLIER-ANON",
    )


def _full_result(organization_id: str = "ORG-PERSIST-TEST") -> dict:
    return {
        "normalization_status": "completed_with_issues",
        "input_row_count": 1,
        "summary": {
            "input_row_count": 1,
            "product_count": 1,
            "batch_count": 1,
            "source_document_count": 1,
            "transaction_count": 1,
            "inventory_snapshot_count": 1,
            "issue_count": 1,
            "warning_count": 1,
            "error_count": 0,
            "transformation_count": 1,
        },
        "tables": {
            "products": [
                {
                    "product_id": "PRODUCT-000001",
                    "organization_id": organization_id,
                    "source_product_code": "SKU-01",
                    "product_name": "Synthetic Medicine",
                    "manufacturer_name": "Synthetic Manufacturer",
                    "hsn_code": "300490",
                    "pack_description": "10'S",
                    "quantity_unit": "pack",
                    "units_per_pack": None,
                    "product_match_status": "source_code",
                }
            ],
            "batches": [
                {
                    "batch_record_id": "BATCH-000001",
                    "organization_id": organization_id,
                    "product_id": "PRODUCT-000001",
                    "batch_code": "B001",
                    "manufacturing_date": "2026-01-01",
                    "expiry_raw": "06/27",
                    "expiry_date": "2027-06-30",
                    "expiry_date_precision": "month",
                }
            ],
            "source_documents": [
                {
                    "document_id": "DOCUMENT-000001",
                    "organization_id": organization_id,
                    "source_file_id": "FILE-ANON-001",
                    "source_file_name": "synthetic.csv",
                    "document_type": "purchase_invoice",
                    "document_number": "INV-DB-001",
                    "document_date": "2026-10-15",
                    "counterparty_id": "SUPPLIER-ANON",
                    "currency_code": "INR",
                    "source_format": "csv",
                    "ingested_at": "2026-10-17T05:00:00+00:00",
                }
            ],
            "transactions": [
                {
                    "transaction_id": "TRANSACTION-00000001",
                    "organization_id": organization_id,
                    "document_id": "DOCUMENT-000001",
                    "transaction_date": "2026-10-15",
                    "transaction_type": "purchase_receipt",
                    "product_id": "PRODUCT-000001",
                    "batch_record_id": "BATCH-000001",
                    "quantity": 3,
                    "quantity_unit": "pack",
                    "free_quantity": 1,
                    "effective_quantity": 4,
                    "unit_rate": 20.5,
                    "mrp": 35,
                    "previous_mrp": None,
                    "discount_percent": 2,
                    "discount_amount": 1,
                    "secondary_discount": None,
                    "tax_rate": 12,
                    "line_amount": 61.5,
                    "tax_amount": 7.38,
                    "line_total_amount": 68.88,
                    "source_row_number": 2,
                }
            ],
            "inventory_snapshots": [
                {
                    "snapshot_id": "SNAPSHOT-00000001",
                    "organization_id": organization_id,
                    "snapshot_date": "2026-10-15",
                    "product_id": "PRODUCT-000001",
                    "batch_record_id": "BATCH-000001",
                    "quantity_on_hand": 18,
                    "quantity_unit": "pack",
                    "stock_basis": "batch_level",
                }
            ],
        },
        "issues": [
            {
                "code": "example_data_quality_warning",
                "severity": "warning",
                "row_index": 0,
                "source_column": "MFG",
                "canonical_field": "manufacturer_name",
                "message": "Synthetic test issue.",
            }
        ],
        "transformations": [
            {
                "row_index": 0,
                "source_column": "QTY+FREE",
                "rule": "split_quantity_and_free",
                "targets": ["quantity", "free_quantity"],
            }
        ],
    }


def test_persist_and_read_normalization_run_with_organization_scope(database_engine) -> None:
    with Session(database_engine) as session:
        run_id = persist_normalization_result(
            session, _full_result(), _schema(), _options(), "synthetic.csv", "csv", 512
        )

    with Session(database_engine) as session:
        preview = get_persisted_normalization_preview(
            session, run_id, "ORG-PERSIST-TEST", preview_limit=10, issue_limit=50
        )
        forbidden = get_persisted_normalization_preview(
            session, run_id, "ORG-DIFFERENT", preview_limit=10, issue_limit=50
        )

    assert preview is not None
    assert preview["persistence"] == "saved_to_postgresql"
    assert preview["summary"]["transaction_count"] == 1
    assert preview["previews"]["products"][0]["product_name"] == "Synthetic Medicine"
    assert preview["previews"]["batches"][0]["expiry_date"] == "2027-06-30"
    assert preview["previews"]["transactions"][0]["effective_quantity"] == 4.0
    assert preview["previews"]["inventory_snapshots"][0]["quantity_on_hand"] == 18.0
    assert preview["issues_preview"][0]["code"] == "example_data_quality_warning"
    assert preview["transformations_preview"][0]["rule"] == "split_quantity_and_free"
    assert forbidden is None


def test_failed_persistence_rolls_back_the_entire_run(database_engine) -> None:
    result = _full_result()
    result["tables"]["transactions"][0]["product_id"] = "PRODUCT-DOES-NOT-EXIST"
    with Session(database_engine) as session:
        with pytest.raises(IntegrityError):
            persist_normalization_result(
                session, result, _schema(), _options(), "synthetic.csv", "csv", 512
            )

    with Session(database_engine) as session:
        run_count = session.scalar(select(func.count()).select_from(NormalizationRun))
    assert run_count == 0


def test_normalize_endpoint_can_persist_and_retrieve_a_run(
    database_engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    @contextmanager
    def test_session_scope() -> Iterator[Session]:
        with Session(database_engine) as session:
            yield session

    monkeypatch.setattr(normalization_api, "session_scope", test_session_scope)
    client = TestClient(app)
    schema = _schema()

    response = client.post(
        "/api/v1/normalize",
        data={
            "confirmed_schema_json": schema.model_dump_json(),
            "options_json": '{"organization_id":"ORG-API-TEST","document_type":"unknown"}',
            "persist": "true",
        },
        files={"file": ("synthetic.csv", b"PRODUCT\nSynthetic API Product\n", "text/csv")},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["persistence"] == "saved_to_postgresql"
    assert body["normalization_run_id"]
    assert body["previews"]["products"][0]["product_name"] == "Synthetic API Product"

    retrieved = client.get(
        f"/api/v1/normalization-runs/{body['normalization_run_id']}",
        params={"organization_id": "ORG-API-TEST"},
    )
    assert retrieved.status_code == 200, retrieved.text
    assert retrieved.json()["previews"]["products"][0]["product_name"] == "Synthetic API Product"

    wrong_org = client.get(
        f"/api/v1/normalization-runs/{body['normalization_run_id']}",
        params={"organization_id": "ORG-WRONG"},
    )
    assert wrong_org.status_code == 404



def test_postgresql_persistence_round_trip_when_enabled() -> None:
    database_url = os.getenv("DATABASE_URL", "")
    if (
        os.getenv("MEDSTOCKIQ_RUN_POSTGRES_INTEGRATION") != "1"
        or not database_url.startswith("postgresql")
    ):
        pytest.skip("PostgreSQL integration test is enabled only by the CI PostgreSQL service.")

    engine = create_engine(database_url, pool_pre_ping=True)
    run_id = None
    try:
        with Session(engine) as session:
            run_id = persist_normalization_result(
                session,
                _full_result("ORG-PG-CI"),
                _schema(),
                _options("ORG-PG-CI"),
                "synthetic-postgres.csv",
                "csv",
                512,
            )
        with Session(engine) as session:
            preview = get_persisted_normalization_preview(
                session, run_id, "ORG-PG-CI", preview_limit=10, issue_limit=50
            )
        assert preview is not None
        assert preview["previews"]["products"][0]["product_name"] == "Synthetic Medicine"
        assert preview["previews"]["transactions"][0]["quantity"] == 3.0
    finally:
        if run_id is not None:
            with engine.begin() as connection:
                connection.execute(
                    delete(NormalizationRun).where(NormalizationRun.run_id == run_id)
                )
        engine.dispose()
