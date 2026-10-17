"""Convert source tables into explicit canonical entity records.

The normalizer consumes a user-confirmed schema. It never infers movement type,
quantity units, date formats, or composite quantity semantics from values alone.
"""

from __future__ import annotations

import calendar
import math
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field

from app.schema.confirmation import (
    MONTH_YEAR_FORMATS,
    ColumnMappingChoice,
    SchemaConfirmationRequest,
)


class NormalizationOptions(BaseModel):
    """Context confirmed by the caller for one uploaded dataset."""

    model_config = ConfigDict(extra="forbid")

    organization_id: str = Field(default="ORG-UNSPECIFIED", min_length=1, max_length=100)
    document_type: Literal[
        "purchase_invoice", "outward_invoice", "retail_sales", "inventory_report", "unknown"
    ] = "unknown"
    source_file_id: str | None = Field(default=None, max_length=200)
    document_number: str | None = Field(default=None, max_length=200)
    document_date: date | None = None
    snapshot_date: date | None = None
    counterparty_id: str | None = Field(default=None, max_length=200)
    currency_code: str | None = Field(default=None, min_length=3, max_length=3)


_NUMERIC_FIELDS = {
    "unit_rate",
    "mrp",
    "previous_mrp",
    "discount_percent",
    "discount_amount",
    "secondary_discount",
    "tax_rate",
    "line_amount",
    "line_total_amount",
    "tax_amount",
}
_DATE_PY_FORMAT = {
    "MM/YY": "%m/%y",
    "MM/YYYY": "%m/%Y",
    "DD/MM/YY": "%d/%m/%y",
    "DD/MM/YYYY": "%d/%m/%Y",
    "YYYY-MM-DD": "%Y-%m-%d",
    "DD-MM-YYYY": "%d-%m-%Y",
    "DD.MM.YYYY": "%d.%m.%Y",
    "YYYY/MM/DD": "%Y/%m/%d",
}
_RETURN_TYPES = {"customer_return", "supplier_return"}
_OUTFLOW_TYPES = {"retailer_dispatch", "retail_sale", "damaged_writeoff", "expiry_writeoff"}
_ALLOWED_NEGATIVE_TYPES = _RETURN_TYPES | {"stock_adjustment"} | {"damaged_writeoff", "expiry_writeoff"}


def _is_missing(value: Any) -> bool:
    if value is None:
        return True
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def _as_text(value: Any) -> str | None:
    if _is_missing(value):
        return None
    if isinstance(value, float) and math.isfinite(value) and value.is_integer():
        return str(int(value))
    text = str(value).strip()
    return text or None


def _serializable(value: Any) -> Any:
    if _is_missing(value):
        return None
    if isinstance(value, (pd.Timestamp, datetime, date)):
        return value.isoformat()
    if hasattr(value, "item") and callable(value.item):
        value = value.item()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _parse_number(value: Any) -> float | None:
    """Parse decimals and valid Western/Indian grouping without guessing comma decimals."""
    if _is_missing(value):
        return None
    if isinstance(value, bool):
        raise ValueError("Boolean values are not valid numeric quantities or amounts.")

    text = str(value).strip()
    if not text:
        return None
    sign = ""
    if text[0] in {"+", "-"}:
        sign, text = text[0], text[1:]
    if not text or text == "." or text.count(".") > 1:
        raise ValueError("Value is not a recognizable number.")

    integer_part, decimal_point, fractional_part = text.partition(".")
    if not integer_part and not fractional_part:
        raise ValueError("Value is not a recognizable number.")
    if not integer_part:
        integer_part = "0"
    if decimal_point and fractional_part and not fractional_part.isdigit():
        raise ValueError("Value is not a recognizable number.")
    if decimal_point and not fractional_part:
        fractional_part = "0"

    if "," in integer_part:
        western_grouping = re.fullmatch(r"\d{1,3}(?:,\d{3})+", integer_part)
        indian_grouping = re.fullmatch(r"\d{1,2}(?:,\d{2})*,\d{3}", integer_part)
        if not (western_grouping or indian_grouping):
            raise ValueError(
                "Number uses an ambiguous or invalid comma grouping; use standard grouping "
                "and a period for decimals."
            )
        integer_part = integer_part.replace(",", "")
    elif not integer_part.isdigit():
        raise ValueError("Value is not a recognizable number.")

    normalized = sign + integer_part
    if decimal_point:
        normalized += "." + fractional_part
    try:
        decimal_value = Decimal(normalized)
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("Value is not a recognizable number.") from exc
    if not decimal_value.is_finite():
        raise ValueError("Numeric values must be finite.")
    number = float(decimal_value)
    if not math.isfinite(number):
        raise ValueError("Numeric values must be finite.")
    return number


def _parse_date(
    value: Any,
    date_format: str,
    date_convention: str | None = None,
) -> tuple[str | None, str | None]:
    """Return (ISO date, precision) using only a confirmed source format/convention."""
    if _is_missing(value):
        return None, None
    if date_format not in _DATE_PY_FORMAT:
        raise ValueError(f"Unsupported date format: {date_format!r}")

    if date_format in MONTH_YEAR_FORMATS:
        if date_convention != "month_end":
            raise ValueError("Month/year expiry needs the explicitly confirmed month_end convention.")
        # Excel may return a datetime for an MM/YY cell; its day component must not
        # override the explicitly confirmed month-end expiry convention.
        if isinstance(value, (pd.Timestamp, datetime, date)):
            year, month = value.year, value.month
        else:
            raw = str(value).strip()
            if not raw:
                return None, None
            parsed = datetime.strptime(raw, _DATE_PY_FORMAT[date_format]).date()
            year, month = parsed.year, parsed.month
        last_day = calendar.monthrange(year, month)[1]
        return date(year, month, last_day).isoformat(), "month"

    if isinstance(value, pd.Timestamp):
        return value.date().isoformat(), "day"
    if isinstance(value, datetime):
        return value.date().isoformat(), "day"
    if isinstance(value, date):
        return value.isoformat(), "day"

    raw = str(value).strip()
    if not raw:
        return None, None
    parsed = datetime.strptime(raw, _DATE_PY_FORMAT[date_format]).date()
    return parsed.isoformat(), "day"


def _composite_quantity(value: Any) -> tuple[float | None, float | None]:
    """Split only simple numeric pairs after the user explicitly selects the rule."""
    if _is_missing(value):
        return None, None
    raw = str(value).strip()
    match = re.fullmatch(
        r"\s*([+-]?\d+(?:[.,]\d+)?)\s*\+\s*([+-]?\d+(?:[.,]\d+)?)\s*",
        raw,
    )
    if not match:
        raise ValueError("Expected a composite numeric value like '10+2'.")
    quantity = _parse_number(match.group(1))
    free_quantity = _parse_number(match.group(2))
    if quantity is None or free_quantity is None:
        raise ValueError("Both billed quantity and free quantity are required.")
    return quantity, free_quantity


def _field_map(confirmation: SchemaConfirmationRequest) -> dict[str, ColumnMappingChoice]:
    return {
        target: mapping
        for mapping in confirmation.mappings
        if mapping.action == "map" and mapping.canonical_field is not None
        for target in (mapping.canonical_field, *mapping.additional_canonical_fields)
    }


def normalize_dataframe(
    frame: pd.DataFrame,
    confirmation: SchemaConfirmationRequest,
    options: NormalizationOptions,
    source_file_name: str = "uploaded-file",
    source_format: str = "unknown",
) -> dict[str, Any]:
    """Normalize an uploaded table into canonical entities and report quality issues.

    The function is stateless and returns Python dictionaries. It does not write files,
    persist rows, infer business semantics, or run inventory-risk calculations.
    """
    profiled_names = [column.source_column for column in confirmation.profiled_columns]
    actual_names = [str(column) for column in frame.columns]
    if actual_names != profiled_names:
        raise ValueError(
            "Uploaded file columns do not match the confirmed profile by name and order. "
            "Profile the current file again and confirm its schema."
        )
    if len(frame.columns) != len(confirmation.profiled_columns):
        raise ValueError("Uploaded file column count differs from the confirmed profile.")

    mappings = _field_map(confirmation)
    issues: list[dict[str, Any]] = []
    transformations: list[dict[str, Any]] = []
    products: list[dict[str, Any]] = []
    batches: list[dict[str, Any]] = []
    documents: list[dict[str, Any]] = []
    transactions: list[dict[str, Any]] = []
    snapshots: list[dict[str, Any]] = []

    product_keys: dict[tuple[Any, ...], str] = {}
    product_by_id: dict[str, dict[str, Any]] = {}
    batch_keys: dict[tuple[str, str], str] = {}
    batch_by_id: dict[str, dict[str, Any]] = {}
    document_keys: dict[tuple[Any, ...], str] = {}
    document_by_id: dict[str, dict[str, Any]] = {}

    date_cache: dict[tuple[int, str], tuple[str | None, str | None]] = {}

    def add_issue(
        code: str,
        severity: Literal["warning", "error"],
        message: str,
        row_index: int | None = None,
        source_column: str | None = None,
        canonical_field: str | None = None,
    ) -> None:
        issues.append(
            {
                "code": code,
                "severity": severity,
                "row_index": row_index,
                "source_column": source_column,
                "canonical_field": canonical_field,
                "message": message,
            }
        )

    def raw_value(row_index: int, mapping: ColumnMappingChoice | None) -> Any:
        if mapping is None:
            return None
        return frame.iloc[row_index, mapping.column_index]

    def get_text(row_index: int, field: str) -> str | None:
        return _as_text(raw_value(row_index, mappings.get(field)))

    def get_number(
        row_index: int,
        field: str,
        required: bool = False,
    ) -> float | None:
        mapping = mappings.get(field)
        if mapping is None:
            return None
        value = raw_value(row_index, mapping)
        try:
            parsed = _parse_number(value)
        except ValueError as exc:
            add_issue(
                f"invalid_{field}",
                "error",
                str(exc),
                row_index,
                mapping.source_column,
                field,
            )
            return None
        if required and parsed is None:
            add_issue(
                f"missing_{field}",
                "error",
                f"Required value for {field} is missing.",
                row_index,
                mapping.source_column,
                field,
            )
        return parsed

    def get_date(row_index: int, field: str) -> tuple[str | None, str | None]:
        cache_key = (row_index, field)
        if cache_key in date_cache:
            return date_cache[cache_key]
        mapping = mappings.get(field)
        if mapping is None:
            date_cache[cache_key] = (None, None)
            return date_cache[cache_key]
        value = raw_value(row_index, mapping)
        try:
            result = _parse_date(
                value, mapping.date_format or "", mapping.date_convention
            )
            date_cache[cache_key] = result
            return result
        except (ValueError, OverflowError) as exc:
            add_issue(
                f"invalid_{field}",
                "error",
                str(exc),
                row_index,
                mapping.source_column,
                field,
            )
            date_cache[cache_key] = (None, None)
            return date_cache[cache_key]

    def build_product(row_index: int) -> dict[str, Any] | None:
        product_code = get_text(row_index, "source_product_code")
        product_name = get_text(row_index, "product_name")
        manufacturer = get_text(row_index, "manufacturer_name")
        hsn = get_text(row_index, "hsn_code")
        pack = get_text(row_index, "pack_description")
        if not product_code and not product_name:
            add_issue(
                "missing_product_identity",
                "error",
                "No product code or product name is mapped and populated; this row cannot be linked to a product.",
                row_index,
            )
            return None

        if product_code:
            key = ("code", product_code.casefold())
        else:
            key = (
                "attributes",
                (product_name or "").casefold(),
                (manufacturer or "").casefold(),
                (pack or "").casefold(),
                (hsn or "").casefold(),
            )
        if key in product_keys:
            product_id = product_keys[key]
            existing = product_by_id[product_id]
            for field, current in (
                ("product_name", product_name),
                ("manufacturer_name", manufacturer),
                ("hsn_code", hsn),
                ("pack_description", pack),
            ):
                if current and existing.get(field) and current != existing[field]:
                    add_issue(
                        "conflicting_product_attributes",
                        "warning",
                        f"Repeated product identity has conflicting {field}; the first non-empty value is retained.",
                        row_index,
                        mappings.get(field).source_column if mappings.get(field) else None,
                        field,
                    )
                elif current and not existing.get(field):
                    existing[field] = current
            return existing

        product_id = f"PRODUCT-{len(products) + 1:06d}"
        quantity_mapping = next(
            (
                mapping
                for target, mapping in mappings.items()
                if target in {"quantity", "free_quantity", "current_quantity", "quantity_on_hand", "opening_stock"}
                and mapping.quantity_unit
            ),
            None,
        )
        record = {
            "product_id": product_id,
            "organization_id": options.organization_id,
            "source_product_code": product_code,
            "product_name": product_name,
            "manufacturer_name": manufacturer,
            "hsn_code": hsn,
            "pack_description": pack,
            "quantity_unit": quantity_mapping.quantity_unit if quantity_mapping else None,
            "units_per_pack": None,
            "product_match_status": "source_code" if product_code else "attribute_match_within_upload",
        }
        products.append(record)
        product_keys[key] = product_id
        product_by_id[product_id] = record
        return record

    def build_batch(
        row_index: int,
        product_id: str,
    ) -> dict[str, Any] | None:
        batch_code = get_text(row_index, "batch_code")
        expiry_date, expiry_precision = get_date(row_index, "expiry_date")
        manufacturing_date, _ = get_date(row_index, "manufacturing_date")
        expiry_mapping = mappings.get("expiry_date")
        expiry_raw_value = raw_value(row_index, expiry_mapping) if expiry_mapping else None
        expiry_raw = _as_text(expiry_raw_value)

        if not batch_code:
            if expiry_raw:
                add_issue(
                    "expiry_without_batch_code",
                    "warning",
                    "Expiry was supplied without a batch code, so a stable batch record was not created.",
                    row_index,
                    expiry_mapping.source_column if expiry_mapping else None,
                    "expiry_date",
                )
            return None

        key = (product_id, batch_code.casefold())
        if key in batch_keys:
            batch_id = batch_keys[key]
            existing = batch_by_id[batch_id]
            if expiry_date and existing.get("expiry_date") and expiry_date != existing["expiry_date"]:
                add_issue(
                    "conflicting_batch_expiry",
                    "error",
                    "The same product/batch has conflicting normalized expiry dates; this row is not linked to the existing batch.",
                    row_index,
                    expiry_mapping.source_column if expiry_mapping else None,
                    "expiry_date",
                )
                return None
            elif expiry_date and not existing.get("expiry_date"):
                existing["expiry_date"] = expiry_date
                existing["expiry_date_precision"] = expiry_precision
                existing["expiry_raw"] = expiry_raw
            if manufacturing_date and not existing.get("manufacturing_date"):
                existing["manufacturing_date"] = manufacturing_date
            return existing

        batch_id = f"BATCH-{len(batches) + 1:06d}"
        record = {
            "batch_record_id": batch_id,
            "organization_id": options.organization_id,
            "product_id": product_id,
            "batch_code": batch_code,
            "manufacturing_date": manufacturing_date,
            "expiry_raw": expiry_raw,
            "expiry_date": expiry_date,
            "expiry_date_precision": expiry_precision,
        }
        batches.append(record)
        batch_keys[key] = batch_id
        batch_by_id[batch_id] = record
        return record

    def build_document(row_index: int) -> dict[str, Any]:
        document_number = get_text(row_index, "document_number") or options.document_number
        mapped_doc_date, _ = get_date(row_index, "document_date")
        document_date = mapped_doc_date or (
            options.document_date.isoformat() if options.document_date else None
        )
        counterparty_id = (
            get_text(row_index, "supplier_id")
            if options.document_type == "purchase_invoice"
            else get_text(row_index, "retailer_id")
            if options.document_type == "outward_invoice"
            else options.counterparty_id
        ) or options.counterparty_id
        source_file_id = options.source_file_id or f"IN_MEMORY:{source_file_name}"
        if document_number or document_date:
            key = (
                options.document_type,
                document_number,
                document_date,
                counterparty_id,
                source_file_id,
            )
        else:
            key = (options.document_type, None, None, counterparty_id, source_file_id)
        if key in document_keys:
            return document_by_id[document_keys[key]]

        document_id = f"DOCUMENT-{len(documents) + 1:06d}"
        record = {
            "document_id": document_id,
            "organization_id": options.organization_id,
            "source_file_id": source_file_id,
            "source_file_name": source_file_name,
            "document_type": options.document_type,
            "document_number": document_number,
            "document_date": document_date,
            "counterparty_id": counterparty_id,
            "currency_code": options.currency_code,
            "source_format": source_format,
            "ingested_at": datetime.now().astimezone().isoformat(),
        }
        documents.append(record)
        document_keys[key] = document_id
        document_by_id[document_id] = record
        return record

    numeric_mapping_names = {
        field: mappings.get(field)
        for field in _NUMERIC_FIELDS
        if mappings.get(field) is not None
    }
    _ = numeric_mapping_names  # documents that all monetary fields are optional mappings.

    for row_index in range(len(frame.index)):
        row_start_issue_count = len(issues)
        canonical_numbers = {
            field: get_number(row_index, field)
            for field in _NUMERIC_FIELDS
            if field in mappings
        }

        quantity_mapping = mappings.get("quantity")
        opening_mapping = mappings.get("opening_stock")
        current_mapping = mappings.get("current_quantity")
        on_hand_mapping = mappings.get("quantity_on_hand")
        free_mapping = mappings.get("free_quantity")

        quantity_value: float | None = None
        is_composite_quantity = bool(
            quantity_mapping
            and quantity_mapping.transformation_rule == "split_quantity_and_free"
        )
        # A composite source maps to both quantity and free_quantity. Do not try to
        # parse that same "10+2" value as a standalone numeric free quantity first.
        free_value: float | None = (
            None if is_composite_quantity else get_number(row_index, "free_quantity")
        )
        if quantity_mapping:
            raw_quantity = raw_value(row_index, quantity_mapping)
            if is_composite_quantity:
                try:
                    quantity_value, composite_free = _composite_quantity(raw_quantity)
                    free_value = composite_free
                    transformations.append(
                        {
                            "row_index": row_index,
                            "source_column": quantity_mapping.source_column,
                            "rule": "split_quantity_and_free",
                            "targets": ["quantity", "free_quantity"],
                        }
                    )
                except ValueError as exc:
                    add_issue(
                        "invalid_composite_quantity",
                        "error",
                        str(exc),
                        row_index,
                        quantity_mapping.source_column,
                        "quantity",
                    )
            else:
                quantity_value = get_number(row_index, "quantity", required=True)

        # A separately mapped free-quantity column must use the same unit as the
        # billed quantity; otherwise combined/effective quantity is not meaningful.
        quantity_units_conflict = bool(
            free_mapping
            and quantity_mapping
            and free_mapping.column_index != quantity_mapping.column_index
            and free_mapping.quantity_unit != quantity_mapping.quantity_unit
        )
        if quantity_units_conflict:
            add_issue(
                "conflicting_free_quantity_units",
                "error",
                "Billed and free quantities use different declared units; they cannot be added without a verified conversion.",
                row_index,
                free_mapping.source_column,
                "free_quantity",
            )
        if free_mapping and not is_composite_quantity and free_value is None:
            raw_free = raw_value(row_index, free_mapping)
            if _is_missing(raw_free) or not str(raw_free).strip():
                add_issue(
                    "missing_free_quantity",
                    "warning",
                    "Free quantity is mapped but missing; effective_quantity is left unknown rather than assuming zero.",
                    row_index,
                    free_mapping.source_column,
                    "free_quantity",
                )
        if free_value is not None and free_value < 0:
            add_issue(
                "negative_free_quantity",
                "error",
                "Free quantity cannot be negative.",
                row_index,
                free_mapping.source_column if free_mapping else None,
                "free_quantity",
            )

        product = build_product(row_index)
        if product is None:
            continue
        product_id = product["product_id"]
        batch = build_batch(row_index, product_id)
        document = build_document(row_index)
        source_row_number = get_number(row_index, "source_row_number")
        if source_row_number is not None and source_row_number.is_integer():
            row_number = int(source_row_number)
        else:
            row_number = row_index + 2
        transaction_date, _ = get_date(row_index, "transaction_date")
        document_date, _ = get_date(row_index, "document_date")
        if document_date is None and options.document_date:
            document_date = options.document_date.isoformat()

        transaction_records: list[tuple[str, float, ColumnMappingChoice | None]] = []
        if quantity_mapping and quantity_value is not None and not quantity_units_conflict:
            transaction_records.append(
                (quantity_mapping.transaction_type or "unknown", quantity_value, quantity_mapping)
            )
        if opening_mapping:
            opening_quantity = get_number(row_index, "opening_stock", required=True)
            if opening_quantity is not None:
                transaction_records.append(("opening_balance", opening_quantity, opening_mapping))

        for tx_type, quantity, tx_mapping in transaction_records:
            if quantity < 0 and tx_type not in _ALLOWED_NEGATIVE_TYPES:
                add_issue(
                    "negative_quantity_for_movement",
                    "error",
                    f"Negative quantity is not valid for transaction_type={tx_type!r}; confirm whether this is a return/adjustment.",
                    row_index,
                    tx_mapping.source_column if tx_mapping else None,
                    "quantity",
                )
                continue
            normalized_quantity = abs(quantity) if tx_type in _RETURN_TYPES | _OUTFLOW_TYPES else quantity
            if not free_mapping:
                effective_quantity = normalized_quantity
            elif free_value is not None and free_value >= 0 and not quantity_units_conflict:
                effective_quantity = normalized_quantity + free_value
            else:
                effective_quantity = None
            if tx_type in _RETURN_TYPES and quantity < 0:
                transformations.append(
                    {
                        "row_index": row_index,
                        "source_column": tx_mapping.source_column if tx_mapping else None,
                        "rule": "absolute_quantity_for_explicit_return_type",
                        "targets": ["quantity"],
                    }
                )
            if not transaction_date:
                if document_date and options.document_type in {
                    "purchase_invoice",
                    "outward_invoice",
                }:
                    transaction_date = document_date
                    transformations.append(
                        {
                            "row_index": row_index,
                            "source_column": mappings.get("document_date").source_column
                            if mappings.get("document_date")
                            else None,
                            "rule": "use_confirmed_invoice_date_as_transaction_date",
                            "targets": ["transaction_date"],
                        }
                    )
                else:
                    add_issue(
                        "missing_transaction_date",
                        "warning",
                        "Transaction date is unavailable; this row cannot be used for reliable time-series analysis.",
                        row_index,
                        tx_mapping.source_column if tx_mapping else None,
                        "transaction_date",
                    )

            records = {
                "transaction_id": f"TRANSACTION-{len(transactions) + 1:08d}",
                "organization_id": options.organization_id,
                "document_id": document["document_id"],
                "transaction_date": transaction_date,
                "transaction_type": tx_type,
                "product_id": product_id,
                "batch_record_id": batch["batch_record_id"] if batch else None,
                "quantity": normalized_quantity,
                "quantity_unit": tx_mapping.quantity_unit if tx_mapping else None,
                "free_quantity": free_value,
                "effective_quantity": effective_quantity,
                "unit_rate": canonical_numbers.get("unit_rate"),
                "mrp": canonical_numbers.get("mrp"),
                "previous_mrp": canonical_numbers.get("previous_mrp"),
                "discount_percent": canonical_numbers.get("discount_percent"),
                "discount_amount": canonical_numbers.get("discount_amount"),
                "secondary_discount": canonical_numbers.get("secondary_discount"),
                "tax_rate": canonical_numbers.get("tax_rate"),
                "line_amount": canonical_numbers.get("line_amount"),
                "tax_amount": canonical_numbers.get("tax_amount"),
                "line_total_amount": canonical_numbers.get("line_total_amount"),
                "source_row_number": row_number,
            }
            transactions.append(records)

        stock_mappings = [
            mapping for mapping in (current_mapping, on_hand_mapping) if mapping is not None
        ]
        if stock_mappings:
            stock_values: list[tuple[ColumnMappingChoice, float | None]] = [
                (mapping, get_number(row_index, mapping.canonical_field, required=True))
                for mapping in stock_mappings
            ]
            non_null_stock_values = [value for _, value in stock_values if value is not None]
            units = {mapping.quantity_unit for mapping, _ in stock_values}
            if len(units) > 1:
                add_issue(
                    "conflicting_stock_units",
                    "error",
                    "Current-stock fields use different declared units; no snapshot was created for this row.",
                    row_index,
                )
            elif (
                len(non_null_stock_values) == len(stock_values)
                and len(non_null_stock_values) > 1
                and len(set(non_null_stock_values)) > 1
            ):
                add_issue(
                    "conflicting_stock_values",
                    "error",
                    "Mapped current_quantity and quantity_on_hand disagree; no snapshot was created for this row.",
                    row_index,
                )
            elif non_null_stock_values and non_null_stock_values[0] < 0:
                add_issue(
                    "negative_quantity_on_hand",
                    "error",
                    "On-hand stock cannot be negative; no inventory snapshot was created.",
                    row_index,
                    stock_mappings[0].source_column,
                    stock_mappings[0].canonical_field,
                )
            elif non_null_stock_values and len(units) == 1:
                snapshot_date = options.snapshot_date.isoformat() if options.snapshot_date else None
                if not snapshot_date:
                    add_issue(
                        "missing_snapshot_date",
                        "error",
                        "Current stock requires an explicit snapshot_date; document date is not assumed to be the stock-as-of date.",
                        row_index,
                    )
                else:
                    selected_mapping, stock_quantity = stock_values[0]
                    snapshots.append(
                        {
                            "snapshot_id": f"SNAPSHOT-{len(snapshots) + 1:08d}",
                            "organization_id": options.organization_id,
                            "snapshot_date": snapshot_date,
                            "product_id": product_id,
                            "batch_record_id": batch["batch_record_id"] if batch else None,
                            "quantity_on_hand": stock_quantity,
                            "quantity_unit": selected_mapping.quantity_unit,
                            "stock_basis": "unknown",
                        }
                    )

        if len(issues) > row_start_issue_count:
            continue

    # Convert accidental non-JSON scalars while preserving the normalized data types.
    tables = {
        "products": products,
        "batches": batches,
        "source_documents": documents,
        "transactions": transactions,
        "inventory_snapshots": snapshots,
    }
    for records in tables.values():
        for record in records:
            for key, value in list(record.items()):
                record[key] = _serializable(value)

    warning_count = sum(issue["severity"] == "warning" for issue in issues)
    error_count = sum(issue["severity"] == "error" for issue in issues)
    return {
        "normalization_status": "completed_with_issues" if issues else "completed",
        "persistence": "stateless_not_saved",
        "organization_id": options.organization_id,
        "source_file_name": source_file_name,
        "input_row_count": int(len(frame.index)),
        "tables": tables,
        "summary": {
            "input_row_count": int(len(frame.index)),
            "product_count": len(products),
            "batch_count": len(batches),
            "source_document_count": len(documents),
            "transaction_count": len(transactions),
            "inventory_snapshot_count": len(snapshots),
            "issue_count": len(issues),
            "warning_count": warning_count,
            "error_count": error_count,
            "transformation_count": len(transformations),
        },
        "issues": issues,
        "transformations": transformations,
        "limitations": [
            "Normalized data and mapping choices are returned for this request only and are not persisted.",
            "No stock forecasting or risk calculation is performed by normalization.",
            "Product matching is limited to an exact source product code or a conservative within-file attribute key; no external product master is consulted.",
        ],
    }
