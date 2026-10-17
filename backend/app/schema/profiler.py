"""Profile table structure and propose conservative canonical mappings."""

from __future__ import annotations

from typing import Any

import pandas as pd
from app.ingestion.readers import MAX_PROFILE_ROWS
from app.schema.mapping import suggest_column_mapping
from pandas.api.types import (
    is_bool_dtype,
    is_datetime64_any_dtype,
    is_integer_dtype,
    is_numeric_dtype,
)


DATE_FIELDS = {"expiry_date", "manufacturing_date", "transaction_date", "document_date"}


def _safe_sample(value: Any, max_length: int = 80) -> str | int | float | bool | None:
    if value is None or pd.isna(value):
        return None
    if hasattr(value, "isoformat") and callable(value.isoformat):
        return str(value.isoformat())
    if hasattr(value, "item") and callable(value.item):
        value = value.item()
    if isinstance(value, (str, int, float, bool)):
        text_value = value
    else:
        text_value = str(value)
    if isinstance(text_value, str) and len(text_value) > max_length:
        return text_value[: max_length - 1] + "…"
    if isinstance(text_value, float) and not pd.notna(text_value):
        return None
    return text_value


def _detected_type(series: pd.Series, canonical_field: str | None) -> str:
    non_null = series.dropna()
    if non_null.empty:
        return "unknown"
    if is_bool_dtype(series):
        return "boolean"
    if is_datetime64_any_dtype(series):
        return "datetime"
    if is_integer_dtype(series):
        return "integer"
    if is_numeric_dtype(series):
        return "decimal"
    if canonical_field in DATE_FIELDS:
        return "date-like string (format requires confirmation)"
    return "string or mixed"


def profile_dataframe(frame: pd.DataFrame, truncated: bool = False) -> dict[str, Any]:
    """Return profiling metadata only; source data itself is not returned."""
    column_profiles: list[dict[str, Any]] = []
    warnings: list[str] = []

    for column in frame.columns:
        series = frame[column]
        source_name = str(column)
        samples = [_safe_sample(value) for value in series.dropna().head(5).tolist()]
        mapping = suggest_column_mapping(source_name, samples)
        canonical_field = mapping["canonical_field"]
        missing_count = int(series.isna().sum())
        total_rows = len(frame.index)
        missing_percent = round(missing_count * 100 / total_rows, 2) if total_rows else 0.0

        column_profiles.append(
            {
                "source_column": source_name,
                "detected_type": _detected_type(series, canonical_field),
                "non_null_count": int(series.notna().sum()),
                "missing_count": missing_count,
                "missing_percent": missing_percent,
                "unique_count": int(series.nunique(dropna=True)),
                "sample_values": samples,
                "mapping": mapping,
            }
        )

    if truncated:
        warnings.append(
            f"Only the first {MAX_PROFILE_ROWS:,} rows were profiled. Run a full-data validation before analysis."
        )
    suggested_fields = {
        item["mapping"]["canonical_field"]
        for item in column_profiles
        if item["mapping"]["canonical_field"] is not None
    }
    if not {"product_id", "product_name"}.intersection(suggested_fields):
        warnings.append("No recognizable product code or product name column was found.")
    if not {"transaction_date", "document_date"}.intersection(suggested_fields):
        warnings.append("No recognizable transaction/document date column was found.")
    if not {"quantity", "current_quantity", "quantity_on_hand"}.intersection(suggested_fields):
        warnings.append("No recognizable quantity or stock column was found.")

    return {
        "row_count_profiled": len(frame.index),
        "column_count": len(frame.columns),
        "duplicate_rows_profiled": int(frame.duplicated().sum()),
        "profiling_row_limit": MAX_PROFILE_ROWS,
        "truncated": truncated,
        "columns": column_profiles,
        "warnings": warnings,
    }
