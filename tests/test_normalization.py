from datetime import date

import pandas as pd
import pytest
from app.normalization.normalizer import NormalizationOptions, normalize_dataframe, _parse_number
from app.schema.confirmation import SchemaConfirmationRequest


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


def test_normalize_endpoint_returns_preview_and_does_not_claim_persistence(client) -> None:
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
            "options_json": json.dumps({"document_type": "purchase_invoice"}),
        },
        files={"file": ("synthetic.csv", csv_bytes, "text/csv")},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["summary"]["product_count"] == 1
    assert body["summary"]["transaction_count"] == 1
    assert body["persistence"] == "stateless_not_saved"
    assert body["previews"]["transactions"][0]["effective_quantity"] == 12
    assert body["quality_report"]["engine_version"] == "1.0.0"
    assert "analysis_readiness" in body["quality_report"]
    assert body["quality_report"]["analysis_readiness"]["demand_forecasting"]["status"] == "insufficient_data"
    assert body["quality_report"]["inventory_analysis"]["status"] == "insufficient_data"
    assert body["quality_report"]["inventory_analysis"]["summary"]["expiry_alert_count"] == 0



def test_numeric_parser_accepts_standard_western_and_indian_grouping() -> None:
    assert _parse_number("1,234.50") == 1234.5
    assert _parse_number("1,23,456.78") == 123456.78


def test_numeric_parser_rejects_ambiguous_comma_decimal() -> None:
    with pytest.raises(ValueError, match="ambiguous or invalid comma grouping"):
        _parse_number("1,5")


def test_month_year_expiry_in_excel_datetime_keeps_month_precision() -> None:
    frame = pd.DataFrame(
        [["Synthetic A", "Maker A", 300490, "10'S", "B001", pd.Timestamp("2030-03-01"), "10+2", "25.5", "40", "13/10/2026", "INV-001"]],
        columns=[c.source_column for c in _confirmed_schema().profiled_columns],
    )
    result = normalize_dataframe(
        frame, _confirmed_schema(), NormalizationOptions(document_type="purchase_invoice")
    )
    assert result["tables"]["batches"][0]["expiry_date"] == "2030-03-31"
    assert result["tables"]["batches"][0]["expiry_date_precision"] == "month"


def test_conflicting_expiry_for_same_product_batch_is_not_linked_to_existing_batch() -> None:
    frame = pd.DataFrame(
        [
            ["Synthetic A", "Maker A", 300490, "10'S", "B001", "03/30", "10+0", "25.5", "40", "13/10/2026", "INV-001"],
            ["Synthetic A", "Maker A", 300490, "10'S", "B001", "04/30", "2+0", "25.5", "40", "13/10/2026", "INV-001"],
        ],
        columns=[c.source_column for c in _confirmed_schema().profiled_columns],
    )
    result = normalize_dataframe(
        frame, _confirmed_schema(), NormalizationOptions(document_type="purchase_invoice")
    )
    assert result["summary"]["batch_count"] == 1
    assert result["tables"]["transactions"][0]["batch_record_id"] is not None
    assert result["tables"]["transactions"][1]["batch_record_id"] is None
    assert any(issue["code"] == "conflicting_batch_expiry" for issue in result["issues"])


def test_document_date_parse_error_is_reported_once_per_row() -> None:
    frame = pd.DataFrame(
        [["Synthetic A", "Maker A", 300490, "10'S", "B001", "03/30", "10+0", "25.5", "40", "31/31/2026", "INV-001"]],
        columns=[c.source_column for c in _confirmed_schema().profiled_columns],
    )
    result = normalize_dataframe(
        frame, _confirmed_schema(), NormalizationOptions(document_type="purchase_invoice")
    )
    assert sum(issue["code"] == "invalid_document_date" for issue in result["issues"]) == 1


def test_inventory_snapshot_requires_explicit_snapshot_date() -> None:
    schema = SchemaConfirmationRequest.model_validate({
        "profiled_columns": [
            {"column_index": 0, "source_column": "PRODUCT"},
            {"column_index": 1, "source_column": "BATCH"},
            {"column_index": 2, "source_column": "CURRENT STOCK"},
            {"column_index": 3, "source_column": "DOCUMENT DATE"},
        ],
        "mappings": [
            {"column_index": 0, "source_column": "PRODUCT", "action": "map", "canonical_field": "product_name"},
            {"column_index": 1, "source_column": "BATCH", "action": "map", "canonical_field": "batch_code"},
            {"column_index": 2, "source_column": "CURRENT STOCK", "action": "map", "canonical_field": "current_quantity", "quantity_unit": "pack"},
            {"column_index": 3, "source_column": "DOCUMENT DATE", "action": "map", "canonical_field": "document_date", "date_format": "YYYY-MM-DD"},
        ],
    })
    frame = pd.DataFrame(
        [["Synthetic A", "B001", 8, "2026-10-01"]],
        columns=["PRODUCT", "BATCH", "CURRENT STOCK", "DOCUMENT DATE"],
    )
    result = normalize_dataframe(
        frame, schema, NormalizationOptions(document_type="inventory_report")
    )
    assert result["summary"]["inventory_snapshot_count"] == 0
    assert any(issue["code"] == "missing_snapshot_date" for issue in result["issues"])


def test_negative_on_hand_quantity_does_not_create_snapshot() -> None:
    schema = SchemaConfirmationRequest.model_validate({
        "profiled_columns": [
            {"column_index": 0, "source_column": "PRODUCT"},
            {"column_index": 1, "source_column": "BATCH"},
            {"column_index": 2, "source_column": "CURRENT STOCK"},
        ],
        "mappings": [
            {"column_index": 0, "source_column": "PRODUCT", "action": "map", "canonical_field": "product_name"},
            {"column_index": 1, "source_column": "BATCH", "action": "map", "canonical_field": "batch_code"},
            {"column_index": 2, "source_column": "CURRENT STOCK", "action": "map", "canonical_field": "current_quantity", "quantity_unit": "pack"},
        ],
    })
    frame = pd.DataFrame([["Synthetic A", "B001", -2]], columns=["PRODUCT", "BATCH", "CURRENT STOCK"])
    result = normalize_dataframe(
        frame,
        schema,
        NormalizationOptions(document_type="inventory_report", snapshot_date=date(2026, 10, 1)),
    )
    assert result["summary"]["inventory_snapshot_count"] == 0
    assert any(issue["code"] == "negative_quantity_on_hand" for issue in result["issues"])


def test_quantity_and_free_quantity_with_different_units_are_not_added() -> None:
    schema = SchemaConfirmationRequest.model_validate({
        "profiled_columns": [
            {"column_index": 0, "source_column": "PRODUCT"},
            {"column_index": 1, "source_column": "BATCH"},
            {"column_index": 2, "source_column": "QTY"},
            {"column_index": 3, "source_column": "FREE"},
        ],
        "mappings": [
            {"column_index": 0, "source_column": "PRODUCT", "action": "map", "canonical_field": "product_name"},
            {"column_index": 1, "source_column": "BATCH", "action": "map", "canonical_field": "batch_code"},
            {"column_index": 2, "source_column": "QTY", "action": "map", "canonical_field": "quantity", "quantity_unit": "pack", "transaction_type": "purchase_receipt"},
            {"column_index": 3, "source_column": "FREE", "action": "map", "canonical_field": "free_quantity", "quantity_unit": "tablet"},
        ],
    })
    frame = pd.DataFrame([["Synthetic A", "B001", 10, 2]], columns=["PRODUCT", "BATCH", "QTY", "FREE"])
    result = normalize_dataframe(frame, schema, NormalizationOptions(document_type="purchase_invoice"))
    assert result["summary"]["transaction_count"] == 1
    transaction = result["tables"]["transactions"][0]
    assert transaction["quantity"] == 10
    assert transaction["free_quantity"] == 2
    assert transaction["effective_quantity"] is None
    assert any(issue["code"] == "conflicting_free_quantity_units" for issue in result["issues"])


def test_month_year_format_is_restricted_to_expiry_date() -> None:
    with pytest.raises(ValueError, match="supported only for expiry_date"):
        SchemaConfirmationRequest.model_validate({
            "profiled_columns": [{"column_index": 0, "source_column": "DOC DATE"}],
            "mappings": [{
                "column_index": 0,
                "source_column": "DOC DATE",
                "action": "map",
                "canonical_field": "document_date",
                "date_format": "MM/YY",
            }],
        })



def test_empty_composite_quantity_is_reported() -> None:
    frame = pd.DataFrame(
        [["Synthetic A", "Maker A", 300490, "10'S", "B001", "03/30", None, "25.5", "40", "13/10/2026", "INV-001"]],
        columns=[c.source_column for c in _confirmed_schema().profiled_columns],
    )
    result = normalize_dataframe(
        frame, _confirmed_schema(), NormalizationOptions(document_type="purchase_invoice")
    )
    assert result["summary"]["transaction_count"] == 0
    assert any(issue["code"] == "missing_composite_quantity" for issue in result["issues"])


def test_incomplete_redundant_stock_fields_do_not_create_snapshot() -> None:
    schema = SchemaConfirmationRequest.model_validate({
        "profiled_columns": [
            {"column_index": 0, "source_column": "PRODUCT"},
            {"column_index": 1, "source_column": "BATCH"},
            {"column_index": 2, "source_column": "CURRENT STOCK"},
            {"column_index": 3, "source_column": "STOCK ON HAND"},
        ],
        "mappings": [
            {"column_index": 0, "source_column": "PRODUCT", "action": "map", "canonical_field": "product_name"},
            {"column_index": 1, "source_column": "BATCH", "action": "map", "canonical_field": "batch_code"},
            {"column_index": 2, "source_column": "CURRENT STOCK", "action": "map", "canonical_field": "current_quantity", "quantity_unit": "pack"},
            {"column_index": 3, "source_column": "STOCK ON HAND", "action": "map", "canonical_field": "quantity_on_hand", "quantity_unit": "pack"},
        ],
    })
    frame = pd.DataFrame(
        [["Synthetic A", "B001", None, 4]],
        columns=["PRODUCT", "BATCH", "CURRENT STOCK", "STOCK ON HAND"],
    )
    result = normalize_dataframe(
        frame,
        schema,
        NormalizationOptions(document_type="inventory_report", snapshot_date=date(2026, 10, 1)),
    )
    assert result["summary"]["inventory_snapshot_count"] == 0
    assert any(issue["code"] == "incomplete_redundant_stock_fields" for issue in result["issues"])



def test_stockist_outward_invoice_layout_normalizes() -> None:
    columns = [
        "SN", "HSN", "MFG", "PRODUCT", "OLD_MRP", "PACK", "BATCH NO", "EXP",
        "QTY", "MRP", "RATE", "DISC", "DISC2", "GST%", "AMOUNT",
    ]
    canonical_by_source = {
        "SN": "source_row_number",
        "HSN": "hsn_code",
        "MFG": "manufacturer_name",
        "PRODUCT": "product_name",
        "OLD_MRP": "previous_mrp",
        "PACK": "pack_description",
        "BATCH NO": "batch_code",
        "EXP": "expiry_date",
        "QTY": "quantity",
        "MRP": "mrp",
        "RATE": "unit_rate",
        "DISC": "discount_percent",
        "DISC2": "secondary_discount",
        "GST%": "tax_rate",
        "AMOUNT": "line_amount",
    }
    mappings = []
    for index, column in enumerate(columns):
        mapping = {
            "column_index": index,
            "source_column": column,
            "action": "map",
            "canonical_field": canonical_by_source[column],
        }
        if column == "EXP":
            mapping.update({"date_format": "MM/YY", "date_convention": "month_end"})
        if column == "QTY":
            mapping.update({"quantity_unit": "pack", "transaction_type": "retailer_dispatch"})
        mappings.append(mapping)

    schema = SchemaConfirmationRequest.model_validate({
        "profiled_columns": [
            {"column_index": i, "source_column": column}
            for i, column in enumerate(columns)
        ],
        "mappings": mappings,
    })
    frame = pd.DataFrame(
        [[1, 300490, "Maker B", "Synthetic B", 31.5, "10'S", "SB-20", "06/27", 3, 45, 27.5, 5, 1.5, 12, 82.5]],
        columns=columns,
    )

    result = normalize_dataframe(
        frame,
        schema,
        NormalizationOptions(
            organization_id="ORG-STOCKIST-TEST",
            document_type="outward_invoice",
            document_number="OUT-TEST-001",
            document_date=date(2026, 10, 14),
            counterparty_id="PHARMACY-ANON-01",
        ),
        source_file_name="synthetic_stockist_invoice.csv",
        source_format="csv",
    )

    assert result["summary"]["product_count"] == 1
    assert result["summary"]["batch_count"] == 1
    assert result["summary"]["source_document_count"] == 1
    assert result["summary"]["transaction_count"] == 1
    assert result["tables"]["products"][0]["product_name"] == "Synthetic B"
    assert result["tables"]["products"][0]["manufacturer_name"] == "Maker B"
    assert result["tables"]["batches"][0]["expiry_date"] == "2027-06-30"
    assert result["tables"]["transactions"][0]["transaction_type"] == "retailer_dispatch"
    assert result["tables"]["transactions"][0]["quantity"] == 3
    assert result["tables"]["transactions"][0]["transaction_date"] == "2026-10-14"
