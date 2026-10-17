from datetime import date

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.normalization.normalizer import NormalizationOptions, normalize_dataframe
from app.schema.confirmation import SchemaConfirmationRequest

client = TestClient(app)


def _confirmed_schema() -> SchemaConfirmationRequest:
    return SchemaConfirmationRequest.model_validate(
        {
            "profiled_columns": [
                {"column_index": 0, "source_column": "PRODUCT"},
                {"column_index": 1, "source_column": "MFG"},
                {"column_index": 2, "source_column": "HSN"},
                {"column_index": 3, "source_column": "PACK"},
                {"column_index": 4, "source_column": "BATCH"},
                {"column_index": 5, "source_column": "EXP"},
                {"column_index": 6, "source_column": "QTY+FREE"},
                {"column_index": 7, "source_column": "RATE"},
                {"column_index": 8, "source_column": "MRP"},
                {"column_index": 9, "source_column": "INVOICE DATE"},
                {"column_index": 10, "source_column": "INVOICE NO"},
            ],
            "mappings": [
                {
                    "column_index": 0,
                    "source_column": "PRODUCT",
                    "action": "map",
                    "proposed_canonical_field": "product_name",
                    "canonical_field": "product_name",
                },
                {
                    "column_index": 1,
                    "source_column": "MFG",
                    "action": "map",
                    "canonical_field": "manufacturer_name",
                },
                {
                    "column_index": 2,
                    "source_column": "HSN",
                    "action": "map",
                    "canonical_field": "hsn_code",
                },
                {
                    "column_index": 3,
                    "source_column": "PACK",
                    "action": "map",
                    "canonical_field": "pack_description",
                },
                {
                    "column_index": 4,
                    "source_column": "BATCH",
                    "action": "map",
                    "canonical_field": "batch_code",
                },
                {
                    "column_index": 5,
                    "source_column": "EXP",
                    "action": "map",
                    "canonical_field": "expiry_date",
                    "date_format": "MM/YY",
                    "date_convention": "month_end",
                },
                {
                    "column_index": 6,
                    "source_column": "QTY+FREE",
                    "action": "map",
                    "canonical_field": "quantity",
                    "quantity_unit": "pack",
                    "transaction_type": "purchase_receipt",
                    "transformation_rule": "split_quantity_and_free",
                    "additional_canonical_fields": ["free_quantity"],
                },
                {
                    "column_index": 7,
                    "source_column": "RATE",
                    "action": "map",
                    "canonical_field": "unit_rate",
                },
                {
                    "column_index": 8,
                    "source_column": "MRP",
                    "action": "map",
                    "canonical_field": "mrp",
                },
                {
                    "column_index": 9,
                    "source_column": "INVOICE DATE",
                    "action": "map",
                    "canonical_field": "document_date",
                    "date_format": "DD/MM/YYYY",
                },
                {
                    "column_index": 10,
                    "source_column": "INVOICE NO",
                    "action": "map",
                    "canonical_field": "document_number",
                },
            ],
        }
    )


def test_normalizer_creates_canonical_entities_and_splits_confirmed_qty_free() -> None:
    frame = pd.DataFrame(
        [
            ["Synthetic A", "Maker A", 300490, "10'S", "B001", "03/30", "10+2", "25.5", "40", "13/10/2026", "INV-001"],
            ["Synthetic A", "Maker A", 300490, "10'S", "B001", "03/30", "2+0", "25.5", "40", "13/10/2026", "INV-001"],
            ["Synthetic B", "Maker B", 300490, "5'S", "B002", "06/27", "5+1", "18", "30", "13/10/2026", "INV-001"],
        ],
        columns=[
            "PRODUCT", "MFG", "HSN", "PACK", "BATCH", "EXP", "QTY+FREE",
            "RATE", "MRP", "INVOICE DATE", "INVOICE NO",
        ],
    )

    result = normalize_dataframe(
        frame,
        _confirmed_schema(),
        NormalizationOptions(
            organization_id="ORG-TEST",
            document_type="purchase_invoice",
            counterparty_id="SUP-ANON-01",
        ),
        source_file_name="synthetic_invoice.xlsx",
        source_format="xlsx",
    )

    assert result["summary"]["product_count"] == 2
    assert result["summary"]["batch_count"] == 2
    assert result["summary"]["source_document_count"] == 1
    assert result["summary"]["transaction_count"] == 3
    assert result["normalization_status"] == "completed"
    assert result["tables"]["batches"][0]["expiry_date"] == "2030-03-31"
    assert result["tables"]["batches"][0]["expiry_date_precision"] == "month"
    assert result["tables"]["transactions"][0]["quantity"] == 10
    assert result["tables"]["transactions"][0]["free_quantity"] == 2
    assert result["tables"]["transactions"][0]["effective_quantity"] == 12
    assert result["tables"]["transactions"][0]["transaction_date"] == "2026-10-13"
    assert result["tables"]["transactions"][0]["batch_record_id"] == result["tables"]["batches"][0]["batch_record_id"]


def test_normalizer_flags_invalid_date_and_missing_batch_code() -> None:
    schema = _confirmed_schema()
    data = [
        ["Synthetic A", "Maker A", 300490, "10'S", "", "13/30", "10+2", "25.5", "40", "13/10/2026", "INV-001"],
    ]
    frame = pd.DataFrame(
        data,
        columns=[c.source_column for c in schema.profiled_columns],
    )

    result = normalize_dataframe(frame, schema, NormalizationOptions(document_type="purchase_invoice"))

    assert result["summary"]["batch_count"] == 0
    assert result["summary"]["error_count"] >= 1
    assert any(issue["code"] == "invalid_expiry_date" for issue in result["issues"])
    assert any(issue["code"] == "expiry_without_batch_code" for issue in result["issues"])


def test_normalizer_rejects_a_mismatched_upload_header() -> None:
    schema = _confirmed_schema()
    frame = pd.DataFrame([["x"]], columns=["OTHER"])

    with pytest.raises(ValueError, match="do not match the confirmed profile"):
        normalize_dataframe(frame, schema, NormalizationOptions())


def test_schema_requires_expiry_convention_for_month_year() -> None:
    payload = _confirmed_schema().model_dump(mode="json")
    expiry_mapping = next(item for item in payload["mappings"] if item["canonical_field"] == "expiry_date")
    expiry_mapping.pop("date_convention")
    with pytest.raises(ValueError, match="date_convention='month_end'"):
        SchemaConfirmationRequest.model_validate(payload)


def test_normalize_endpoint_returns_preview_and_does_not_claim_persistence() -> None:
    schema = _confirmed_schema()
    payload = schema.model_dump(mode="json")
    csv_bytes = (
        b"PRODUCT,MFG,HSN,PACK,BATCH,EXP,QTY+FREE,RATE,MRP,INVOICE DATE,INVOICE NO\n"
        b"Synthetic A,Maker A,300490,10'S,B001,03/30,10+2,25.5,40,13/10/2026,INV-001\n"
    )
    import json

    response = client.post(
        "/api/v1/normalize",
        data={
            "confirmed_schema_json": json.dumps(payload),
            "options_json": json.dumps({"organization_id": "ORG-TEST", "document_type": "purchase_invoice"}),
        },
        files={"file": ("synthetic.csv", csv_bytes, "text/csv")},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["summary"]["product_count"] == 1
    assert body["summary"]["transaction_count"] == 1
    assert body["persistence"] == "stateless_not_saved"
    assert body["previews"]["transactions"][0]["effective_quantity"] == 12
