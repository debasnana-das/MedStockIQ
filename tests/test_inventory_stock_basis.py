from __future__ import annotations

from datetime import date

import pandas as pd
import pytest
from pydantic import ValidationError

from app.normalization.normalizer import NormalizationOptions, normalize_dataframe
from app.schema.confirmation import SchemaConfirmationRequest


def _schema() -> SchemaConfirmationRequest:
    return SchemaConfirmationRequest.model_validate({
        "profiled_columns": [
            {"column_index": 0, "source_column": "SKU"},
            {"column_index": 1, "source_column": "Product Name"},
            {"column_index": 2, "source_column": "Batch"},
            {"column_index": 3, "source_column": "Expiry Date"},
            {"column_index": 4, "source_column": "On Hand"},
        ],
        "mappings": [
            {"column_index": 0, "source_column": "SKU", "action": "map",
             "canonical_field": "source_product_code"},
            {"column_index": 1, "source_column": "Product Name", "action": "map",
             "canonical_field": "product_name"},
            {"column_index": 2, "source_column": "Batch", "action": "map",
             "canonical_field": "batch_code"},
            {"column_index": 3, "source_column": "Expiry Date", "action": "map",
             "canonical_field": "expiry_date", "date_format": "YYYY-MM-DD"},
            {"column_index": 4, "source_column": "On Hand", "action": "map",
             "canonical_field": "quantity_on_hand", "quantity_unit": "pack"},
        ],
    })


def test_inventory_stock_basis_is_only_allowed_for_inventory_reports() -> None:
    with pytest.raises(ValidationError, match="inventory_stock_basis is only valid"):
        NormalizationOptions(document_type="retail_sales", inventory_stock_basis="physical")


def test_explicit_inventory_stock_basis_is_used_in_saved_snapshot_record() -> None:
    frame = pd.DataFrame(
        [["SRC-001", "SYNTHETIC PRODUCT 001", "B-001", "2026-10-31", 25]],
        columns=["SKU", "Product Name", "Batch", "Expiry Date", "On Hand"],
    )
    result = normalize_dataframe(
        frame,
        _schema(),
        NormalizationOptions(
            organization_id="ORG-TEST",
            document_type="inventory_report",
            snapshot_date=date(2026, 9, 30),
            inventory_snapshot_complete=True,
            inventory_stock_basis="physical",
        ),
        source_file_name="inventory_snapshot_upload.csv",
        source_format="csv",
    )
    assert result["tables"]["inventory_snapshots"][0]["stock_basis"] == "physical"


def test_stock_basis_stays_unknown_when_not_attested() -> None:
    frame = pd.DataFrame(
        [["SRC-001", "SYNTHETIC PRODUCT 001", "B-001", "2026-10-31", 25]],
        columns=["SKU", "Product Name", "Batch", "Expiry Date", "On Hand"],
    )
    result = normalize_dataframe(
        frame,
        _schema(),
        NormalizationOptions(
            organization_id="ORG-TEST",
            document_type="inventory_report",
            snapshot_date=date(2026, 9, 30),
            inventory_snapshot_complete=True,
        ),
        source_file_name="inventory_snapshot_upload.csv",
        source_format="csv",
    )
    assert result["tables"]["inventory_snapshots"][0]["stock_basis"] == "unknown"
