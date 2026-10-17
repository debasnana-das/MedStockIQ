import io

from app.main import app
from app.schema.mapping import suggest_column_mapping
from app.schema.profiler import profile_dataframe
from fastapi.testclient import TestClient
import pandas as pd


def test_product_and_expiry_headers_get_mapping_suggestions() -> None:
    product = suggest_column_mapping("PRODUCT")
    expiry = suggest_column_mapping("EXP")

    assert product["canonical_field"] == "product_name"
    assert expiry["canonical_field"] == "expiry_date"
    assert expiry["requires_confirmation"] is True


def test_qty_free_is_marked_ambiguous() -> None:
    suggestion = suggest_column_mapping("QTY+FREE")

    assert suggestion["canonical_field"] == "quantity"
    assert suggestion["requires_confirmation"] is True
    assert "free units" in suggestion["rationale"]


def test_profile_reports_missing_values_and_duplicate_rows() -> None:
    frame = pd.DataFrame(
        {
            "PRODUCT": ["SYNTHETIC A", "SYNTHETIC A"],
            "BATCH": ["B001", "B001"],
            "EXP": ["03/30", "03/30"],
            "QTY+FREE": [None, "2+1"],
        }
    )

    report = profile_dataframe(frame)

    assert report["row_count_profiled"] == 2
    assert report["duplicate_rows_profiled"] == 1
    qty = next(col for col in report["columns"] if col["source_column"] == "QTY+FREE")
    assert qty["mapping"]["requires_confirmation"] is True
    assert qty["missing_count"] == 1


def test_profile_endpoint_accepts_csv_in_memory() -> None:
    client = TestClient(app)
    payload = b"PRODUCT,BATCH,EXP,QTY\nSYNTHETIC A,B001,03/30,4\n"
    response = client.post(
        "/api/v1/profile",
        files={"file": ("sample.csv", io.BytesIO(payload), "text/csv")},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["storage"] == "in_memory_not_persisted"
    assert body["row_count_profiled"] == 1
    assert {column["source_column"] for column in body["columns"]} == {"PRODUCT", "BATCH", "EXP", "QTY"}


def test_profile_endpoint_rejects_unsupported_files() -> None:
    client = TestClient(app)
    response = client.post(
        "/api/v1/profile",
        files={"file": ("invoice.pdf", b"fake-pdf-bytes", "application/pdf")},
    )

    assert response.status_code == 415
