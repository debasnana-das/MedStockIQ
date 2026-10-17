"""Deterministic data-quality diagnostics and analysis readiness checks.

This layer reports what the submitted canonical data can and cannot support. It
never imputes missing values or calculates inventory risks/forecasts.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime
from math import isfinite
from typing import Any

ENGINE_VERSION = "1.0.0"
MIN_SALES_ROWS = 10
MIN_DISTINCT_SALES_DATES = 7
MIN_SALES_SPAN_DAYS = 28
MAX_SAMPLE_ROWS = 5


def _date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if value in (None, ""):
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def _number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if isfinite(result) else None


def _present(value: Any) -> bool:
    return value is not None and str(value).strip() != ""


def _coverage(present: int, total: int) -> dict[str, Any]:
    return {
        "present": present,
        "total": total,
        "percent": round(present * 100 / total, 1) if total else None,
    }


def _module(
    blockers: list[str],
    warnings: list[str],
    required_inputs: list[str],
    available_inputs: dict[str, Any],
) -> dict[str, Any]:
    status = "insufficient_data" if blockers else (
        "ready_with_warnings" if warnings else "ready"
    )
    return {
        "status": status,
        "ready": not blockers,
        "required_inputs": required_inputs,
        "available_inputs": available_inputs,
        "blockers": blockers,
        "warnings": warnings,
    }


def _normalization_findings(issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str, str, str], list[int]] = defaultdict(list)
    unlocated_counts: Counter[tuple[str, str, str, str]] = Counter()
    for issue in issues:
        key = (
            str(issue.get("code") or "unknown"),
            str(issue.get("severity") or "warning"),
            str(issue.get("canonical_field") or ""),
            str(issue.get("message") or ""),
        )
        row = issue.get("row_index")
        if isinstance(row, int):
            groups[key].append(row)
        else:
            unlocated_counts[key] += 1

    findings = []
    for key in set(groups) | set(unlocated_counts):
        code, severity, field, message = key
        rows = groups.get(key, [])
        affected = len(rows) + unlocated_counts.get(key, 0)
        findings.append({
            "code": code,
            "severity": severity if severity in {"error", "warning", "info"} else "warning",
            "category": "normalization",
            "message": message or code.replace("_", " "),
            "affected_count": max(affected, 1),
            "sample_rows": sorted(set(rows))[:MAX_SAMPLE_ROWS],
            "canonical_field": field or None,
        })
    return findings


def evaluate_data_quality_and_readiness(
    normalization_result: dict[str, Any],
    document_type: str = "unknown",
    confirmed_schema: Any | None = None,
) -> dict[str, Any]:
    """Return structured quality findings, field coverage, and per-module readiness.

    The sales-data cutoffs are explicit software guardrails, not claims that a
    forecast based on this amount of data will be statistically reliable.
    """
    tables = normalization_result.get("tables") or {}
    products = list(tables.get("products") or [])
    batches = list(tables.get("batches") or [])
    documents = list(tables.get("source_documents") or [])
    transactions = list(tables.get("transactions") or [])
    snapshots = list(tables.get("inventory_snapshots") or [])
    issues = list(normalization_result.get("issues") or [])
    findings = _normalization_findings(issues)
    existing_codes = {item["code"] for item in findings}

    def add_finding(
        code: str, severity: str, category: str, message: str,
        count: int, field: str | None = None, columns: list[str] | None = None,
    ) -> None:
        item = {
            "code": code, "severity": severity, "category": category,
            "message": message, "affected_count": count, "sample_rows": [],
            "canonical_field": field,
        }
        if columns:
            item["columns"] = columns[:10]
        findings.append(item)
        existing_codes.add(code)

    product_identity_count = sum(
        _present(row.get("product_name")) or _present(row.get("source_product_code"))
        for row in products
    )
    product_name_count = sum(_present(row.get("product_name")) for row in products)
    dated_transaction_count = sum(_date(row.get("transaction_date")) is not None for row in transactions)
    transaction_unit_count = sum(_present(row.get("quantity_unit")) for row in transactions)
    dated_snapshot_count = sum(_date(row.get("snapshot_date")) is not None for row in snapshots)
    snapshot_unit_count = sum(_present(row.get("quantity_unit")) for row in snapshots)
    valid_expiry_count = sum(_date(row.get("expiry_date")) is not None for row in batches)

    if products and product_name_count < len(products) and "missing_product_name" not in existing_codes:
        add_finding("missing_product_name", "warning", "completeness",
                    "Some product records have no display name.", len(products) - product_name_count,
                    "product_name")
    if batches and valid_expiry_count < len(batches) and "missing_or_unparsed_expiry_date" not in existing_codes:
        add_finding("missing_or_unparsed_expiry_date", "warning", "completeness",
                    "Some batch records have no normalized expiry date and cannot participate in expiry monitoring.",
                    len(batches) - valid_expiry_count, "expiry_date")
    if transactions and transaction_unit_count < len(transactions) and "missing_transaction_quantity_unit" not in existing_codes:
        add_finding("missing_transaction_quantity_unit", "warning", "semantics",
                    "Some transaction quantities have no declared unit and must not be combined across units.",
                    len(transactions) - transaction_unit_count, "quantity_unit")
    if snapshots and snapshot_unit_count < len(snapshots) and "missing_snapshot_quantity_unit" not in existing_codes:
        add_finding("missing_snapshot_quantity_unit", "error", "semantics",
                    "Some inventory snapshots have no declared quantity unit.", len(snapshots) - snapshot_unit_count,
                    "quantity_unit")

    unknown_basis_rows = [
        row for row in snapshots
        if str(row.get("stock_basis") or "unknown").casefold() not in {"physical", "system"}
    ]
    if unknown_basis_rows and "unknown_stock_basis" not in existing_codes:
        add_finding("unknown_stock_basis", "warning", "provenance",
                    "The source does not establish whether on-hand stock is a physical count or a system-reported balance.",
                    len(unknown_basis_rows), "stock_basis")

    signatures: Counter[tuple[Any, ...]] = Counter()
    for row in transactions:
        signature = tuple(row.get(field) for field in (
            "document_id", "product_id", "batch_record_id", "transaction_date",
            "transaction_type", "quantity", "quantity_unit", "unit_rate",
            "line_amount", "line_total_amount",
        ))
        if any(_present(value) for value in signature):
            signatures[signature] += 1
    duplicate_rows = sum(count - 1 for count in signatures.values() if count > 1)
    if duplicate_rows:
        add_finding("possible_duplicate_transaction_lines", "warning", "duplicate_detection",
                    "Transaction lines share identical business-field signatures. Review them; identical lines may be legitimate and are not automatically removed.",
                    duplicate_rows)

    discount_bad = sum(
        (value := _number(row.get("discount_percent"))) is not None and not 0 <= value <= 100
        for row in transactions
    )
    if discount_bad:
        add_finding("discount_percent_out_of_range", "warning", "range_validation",
                    "Discount percentages outside 0–100 were found; confirm source units and semantics.",
                    discount_bad, "discount_percent")
    tax_bad = sum(
        (value := _number(row.get("tax_rate"))) is not None and not 0 <= value <= 100
        for row in transactions
    )
    if tax_bad:
        add_finding("tax_rate_out_of_range", "warning", "range_validation",
                    "Tax rates outside 0–100 were found; confirm this field is a rate rather than an amount.",
                    tax_bad, "tax_rate")
    negative_price_rows = sum(
        any((value := _number(row.get(field))) is not None and value < 0
            for field in ("unit_rate", "mrp"))
        for row in transactions
    )
    if negative_price_rows:
        add_finding("negative_price_value", "warning", "range_validation",
                    "Negative unit rate or MRP values were found; verify returns, adjustments, or mapping semantics.",
                    negative_price_rows)

    mappings = getattr(confirmed_schema, "mappings", None)
    if mappings is None and isinstance(confirmed_schema, dict):
        mappings = confirmed_schema.get("mappings", [])
    ignored = []
    for mapping in mappings or []:
        action = getattr(mapping, "action", None)
        source = getattr(mapping, "source_column", None)
        if isinstance(mapping, dict):
            action, source = mapping.get("action"), mapping.get("source_column")
        if action == "ignore" and source:
            ignored.append(str(source))
    if ignored:
        add_finding("source_columns_ignored", "info", "mapping",
                    "Review ignored columns to confirm they do not contain required analysis inputs.",
                    len(ignored), columns=ignored)

    sales = [
        row for row in transactions
        if row.get("transaction_type") == "retail_sale"
        and _date(row.get("transaction_date")) is not None
        and _number(row.get("quantity")) is not None
        and _present(row.get("quantity_unit")) and _present(row.get("product_id"))
    ]
    sales_dates = sorted({_date(row.get("transaction_date")) for row in sales})
    span_days = (sales_dates[-1] - sales_dates[0]).days if len(sales_dates) >= 2 else 0
    sales_products = {str(row["product_id"]) for row in sales}
    units_by_product: dict[str, set[str]] = defaultdict(set)
    for row in sales:
        units_by_product[str(row["product_id"])].add(str(row["quantity_unit"]).strip().casefold())
    mixed_unit_products = sorted(key for key, units in units_by_product.items() if len(units) > 1)

    sales_guardrails = {
        "minimum_valid_dated_sale_lines": MIN_SALES_ROWS,
        "minimum_distinct_sales_dates": MIN_DISTINCT_SALES_DATES,
        "minimum_first_to_last_sale_span_days": MIN_SALES_SPAN_DAYS,
        "valid_dated_sale_lines": len(sales),
        "distinct_sales_dates": len(sales_dates),
        "first_sale_date": sales_dates[0].isoformat() if sales_dates else None,
        "last_sale_date": sales_dates[-1].isoformat() if sales_dates else None,
        "span_days": span_days,
    }
    sales_blockers = []
    if len(sales) < MIN_SALES_ROWS:
        sales_blockers.append(f"Need at least {MIN_SALES_ROWS} dated retail-sale lines with product, quantity and unit; found {len(sales)}.")
    if len(sales_dates) < MIN_DISTINCT_SALES_DATES:
        sales_blockers.append(f"Need at least {MIN_DISTINCT_SALES_DATES} distinct retail-sale dates; found {len(sales_dates)}.")
    if span_days < MIN_SALES_SPAN_DAYS:
        sales_blockers.append(f"Need sale dates spanning at least {MIN_SALES_SPAN_DAYS} days; observed {span_days}.")
    if mixed_unit_products:
        sales_blockers.append("Some products have sale quantities in multiple units; confirm a conversion or separate their series.")

    snapshots_by_product: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in snapshots:
        if _present(row.get("product_id")) and _date(row.get("snapshot_date")):
            snapshots_by_product[str(row["product_id"])].append(row)
    latest_snapshot = {
        product_id: max(rows, key=lambda row: _date(row.get("snapshot_date")) or date.min)
        for product_id, rows in snapshots_by_product.items()
    }
    snapshot_products = set(latest_snapshot)
    matched_products = sales_products & snapshot_products
    mismatched_units = {
        product_id for product_id in matched_products
        if str(latest_snapshot[product_id].get("quantity_unit") or "").strip().casefold()
        not in units_by_product.get(product_id, set())
    }
    compatible_products = matched_products - mismatched_units

    valid_batch_pairs = {
        (str(row.get("product_id")), str(row.get("batch_record_id")))
        for row in batches if _date(row.get("expiry_date")) and _present(row.get("batch_record_id"))
    }
    snapshot_batch_rows = [
        row for row in snapshots
        if _present(row.get("batch_record_id")) and _date(row.get("snapshot_date"))
    ]
    snapshot_pairs = {(str(row.get("product_id")), str(row.get("batch_record_id"))) for row in snapshot_batch_rows}
    expiry_pairs = valid_batch_pairs & snapshot_pairs
    expiry_units_missing = sum(
        not _present(row.get("quantity_unit"))
        for row in snapshot_batch_rows
        if (str(row.get("product_id")), str(row.get("batch_record_id"))) in expiry_pairs
    )
    expiry_blockers = []
    expiry_warnings = []
    if not batches:
        expiry_blockers.append("No normalized batch records are available.")
    if not valid_expiry_count:
        expiry_blockers.append("No batch has a valid normalized expiry date.")
    if not snapshots:
        expiry_blockers.append("No dated inventory snapshot is available.")
    if not expiry_pairs:
        expiry_blockers.append("No batch has both a normalized expiry date and a linked dated on-hand snapshot.")
    if expiry_units_missing:
        expiry_blockers.append("Some matched batch snapshots have no declared quantity unit.")
    if expiry_pairs and unknown_basis_rows:
        expiry_warnings.append("Stock basis is unknown for one or more snapshots; treat exposure as provisional.")
    if expiry_pairs and valid_expiry_count < len(batches):
        expiry_warnings.append("Some batches have missing or unparsed expiry dates and are excluded.")

    expiry_module = _module(expiry_blockers, expiry_warnings, [
        "Normalized batch code and expiry date",
        "Dated on-hand snapshot linked to the same product and batch",
        "Declared quantity unit",
    ], {
        "batch_count": len(batches),
        "batches_with_valid_expiry": valid_expiry_count,
        "dated_inventory_snapshot_products": len(snapshots_by_product),
        "expiry_and_stock_matched_batches": len(expiry_pairs),
        "matched_batches_missing_quantity_unit": expiry_units_missing,
        "unknown_stock_basis_snapshots": len(unknown_basis_rows),
    })
    demand_module = _module(list(sales_blockers), [], [
        "Confirmed retail-sale movement type",
        "Product, dated quantity and quantity unit on each sale",
        f"At least {MIN_SALES_ROWS} valid dated sale lines",
        f"At least {MIN_DISTINCT_SALES_DATES} dates spanning {MIN_SALES_SPAN_DAYS} days",
        "One consistent quantity unit per product",
    ], sales_guardrails)

    overstock_blockers = list(sales_blockers)
    overstock_warnings = []
    if not snapshots:
        overstock_blockers.append("No on-hand inventory snapshots are available.")
    if snapshots and not matched_products:
        overstock_blockers.append("No product has both a dated retail-sale history and a dated inventory snapshot.")
    elif matched_products and not compatible_products:
        overstock_blockers.append("Sales and on-hand stock units do not match for products with both datasets.")
    elif mismatched_units:
        overstock_warnings.append(f"{len(mismatched_units)} product(s) with conflicting sales/stock units must be excluded.")
    if snapshots and unknown_basis_rows:
        overstock_warnings.append("Stock basis is unknown; on-hand quantities are not verified as physical counts.")
    overstock_module = _module(overstock_blockers, overstock_warnings, [
        "Dated product-level on-hand snapshot",
        "Dated retail-sale history meeting published guardrails",
        "Comparable sales and stock units",
    ], {
        "dated_snapshot_products": len(snapshot_products),
        "products_with_sales_and_snapshot": len(matched_products),
        "products_with_unit_mismatch": len(mismatched_units),
        "products_with_compatible_units": len(compatible_products),
        "sales_guardrails": sales_guardrails,
    })

    replenishment = list(tables.get("replenishment_orders") or [])
    replenishment_timing_rows = sum(
        _date(row.get("expected_arrival_date")) is not None
        or (_date(row.get("order_date")) is not None and _date(row.get("actual_arrival_date")) is not None)
        or ((_number(row.get("lead_time_days")) is not None) and _number(row.get("lead_time_days")) >= 0)
        for row in replenishment
    )
    stockout_blockers = list(overstock_blockers)
    if not replenishment_timing_rows:
        stockout_blockers.append("No confirmed replenishment lead-time or order/arrival timing evidence is available.")
    stockout_module = _module(stockout_blockers, list(overstock_warnings), [
        "Dated on-hand stock",
        "Dated retail sales with consistent units",
        "Confirmed supplier lead time or order/arrival data",
    ], {
        "dated_snapshot_products": len(snapshot_products),
        "products_with_sales_and_snapshot": len(matched_products),
        "replenishment_records": len(replenishment),
        "replenishment_records_with_timing_evidence": replenishment_timing_rows,
    })

    for finding in findings:
        field = finding.get("canonical_field")
        if field in {"expiry_date", "batch_code"}:
            finding["analysis_modules"] = ["expiry_monitoring"]
        elif field in {"transaction_date", "quantity", "quantity_unit"}:
            finding["analysis_modules"] = ["demand_forecasting", "overstock_review", "stockout_review"]
        elif field in {"stock_basis", "quantity_on_hand"}:
            finding["analysis_modules"] = ["overstock_review", "expiry_monitoring", "stockout_review"]
        else:
            finding["analysis_modules"] = []

    error_count = sum(item["severity"] == "error" for item in findings)
    warning_count = sum(item["severity"] == "warning" for item in findings)
    info_count = sum(item["severity"] == "info" for item in findings)
    modules = {
        "expiry_monitoring": expiry_module,
        "demand_forecasting": demand_module,
        "overstock_review": overstock_module,
        "stockout_review": stockout_module,
    }
    ready_modules = [item for item in modules.values() if item["ready"]]
    overall_status = "insufficient_data"
    if ready_modules:
        overall_status = (
            "ready_with_warnings"
            if any(item["status"] == "ready_with_warnings" for item in ready_modules)
            or error_count or warning_count
            else "ready"
        )

    return {
        "engine_version": ENGINE_VERSION,
        "overall_status": overall_status,
        "document_type": document_type,
        "quality_summary": {
            "input_rows": int(normalization_result.get("input_row_count", 0)),
            "product_count": len(products),
            "batch_count": len(batches),
            "source_document_count": len(documents),
            "transaction_count": len(transactions),
            "inventory_snapshot_count": len(snapshots),
            "normalization_issue_count": len(issues),
            "error_finding_count": error_count,
            "warning_finding_count": warning_count,
            "info_finding_count": info_count,
            "finding_group_count": len(findings),
        },
        "field_coverage": {
            "product_identity": _coverage(product_identity_count, len(products)),
            "product_name": _coverage(product_name_count, len(products)),
            "transaction_date": _coverage(dated_transaction_count, len(transactions)),
            "transaction_quantity_unit": _coverage(transaction_unit_count, len(transactions)),
            "batch_expiry_date": _coverage(valid_expiry_count, len(batches)),
            "inventory_snapshot_date": _coverage(dated_snapshot_count, len(snapshots)),
            "inventory_snapshot_quantity_unit": _coverage(snapshot_unit_count, len(snapshots)),
        },
        "quality_findings": sorted(findings, key=lambda item: (
            {"error": 0, "warning": 1, "info": 2}.get(item["severity"], 3),
            item["code"], item["message"],
        )),
        "analysis_readiness": modules,
        "readiness_guardrails": {
            "demand_forecasting": {
                "minimum_valid_dated_sale_lines": MIN_SALES_ROWS,
                "minimum_distinct_sales_dates": MIN_DISTINCT_SALES_DATES,
                "minimum_first_to_last_sale_span_days": MIN_SALES_SPAN_DAYS,
                "note": "These are conservative software guardrails, not a guarantee of forecast reliability.",
            },
            "scope_note": "Readiness only. No inventory risk score, forecast, or recommendation is calculated.",
        },
    }
