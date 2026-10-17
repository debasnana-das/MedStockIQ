"""Inventory position arithmetic and batch-level expiry alerts.

Only explicit dated stock snapshots are treated as on-hand inventory. The service
never reconstructs "current stock" from invoices alone, mixes units, or silently
deduplicates conflicting records.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime
from math import isfinite
from typing import Any

ENGINE_VERSION = "1.0.0"
DEFAULT_STALE_AFTER_DAYS = 30
EXPIRY_ALERT_WINDOWS = (30, 90, 180)
PREVIEW_LIMIT = 100
MOVEMENT_SIGNS = {
    "purchase_receipt": 1,
    "customer_return": 1,
    "retailer_dispatch": -1,
    "retail_sale": -1,
    "supplier_return": -1,
    "damaged_writeoff": -1,
    "expiry_writeoff": -1,
}
ALERT_SEVERITY = {
    "expired_stock": "critical",
    "expires_within_30_days": "high",
    "expires_within_90_days": "medium",
    "expires_within_180_days": "low",
}


def _date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if value is None or value == "":
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def _number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if isfinite(parsed) else None


def _text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _position_key(product_id: str, batch_id: str | None) -> tuple[str, str]:
    return product_id, batch_id or ""


def _round(value: float | None) -> float | None:
    return round(value, 6) if value is not None and isfinite(value) else None


def calculate_inventory_arithmetic(
    normalization_result: dict[str, Any],
    *,
    currency_code: str | None = None,
    as_of_date: date | None = None,
    stale_after_days: int = DEFAULT_STALE_AFTER_DAYS,
    expiry_alert_windows: tuple[int, ...] = EXPIRY_ALERT_WINDOWS,
) -> dict[str, Any]:
    """Summarize dated inventory positions, reconcile snapshots where possible, and alert on expiry.

    Reconciliation checks use only matching product/batch/unit transactions supplied
    in this normalization result. They are not proof that the source ledger is complete.
    MRP valuation is provided only where a same-batch, same-unit, dated MRP and known
    currency are present; it is an indicative retail-price exposure, not cost or loss.
    """
    as_of = as_of_date or date.today()
    stale_days = max(0, int(stale_after_days))
    windows = tuple(sorted({int(x) for x in expiry_alert_windows if int(x) >= 0}))
    tables = normalization_result.get("tables") or {}
    products = list(tables.get("products") or [])
    batches = list(tables.get("batches") or [])
    snapshots = list(tables.get("inventory_snapshots") or [])
    transactions = list(tables.get("transactions") or [])
    documents = list(tables.get("source_documents") or [])

    products_by_id = {str(row.get("product_id")): row for row in products if row.get("product_id")}
    batches_by_id = {str(row.get("batch_record_id")): row for row in batches if row.get("batch_record_id")}
    docs_by_id = {str(row.get("document_id")): row for row in documents if row.get("document_id")}

    finding_counts: Counter[str] = Counter()
    finding_samples: dict[str, list[str]] = defaultdict(list)
    finding_specs = {
        "invalid_snapshot": ("error", "A stock snapshot has missing or invalid identity, date, quantity, or unit."),
        "negative_on_hand": ("error", "A negative on-hand quantity was excluded from inventory calculations."),
        "future_snapshot": ("info", "A stock snapshot dated after the report date was excluded from current inventory."),
        "duplicate_snapshot_rows": ("warning", "Identical same-date snapshot rows were counted once to avoid double counting."),
        "conflicting_snapshot_rows": ("error", "Different quantities exist for the same product/batch/unit on the same date; the position was excluded."),
        "inconsistent_snapshot_units": ("error", "A product/batch has snapshots in multiple units; conversion must be confirmed before calculations."),
        "missing_batch_record": ("warning", "An on-hand snapshot references a batch without normalized batch metadata; expiry alerts cannot be generated."),
        "missing_expiry_date": ("warning", "A stocked batch has no valid normalized expiry date; expiry alerts cannot be generated."),
        "stale_snapshot": ("warning", "The latest available stock snapshot is old; treat the current quantity as provisional."),
        "unknown_stock_basis": ("warning", "The snapshot does not establish whether stock is a physical count or a system-reported balance."),
        "reconciliation_not_checkable": ("info", "Snapshot reconciliation was not possible because movement evidence was missing or incomplete."),
        "stock_reconciliation_mismatch": ("warning", "The next stock snapshot does not equal the previous snapshot plus the supplied movements."),
        "expired_stock_alert": ("error", "Positive on-hand quantity remains in a batch whose normalized expiry date has passed."),
        "near_expiry_alert": ("warning", "Positive on-hand quantity is in a batch within the configured expiry-alert window."),
        "mrp_value_unavailable": ("info", "An indicative MRP value was omitted because same-batch/unit price evidence or currency was unavailable or ambiguous."),
    }

    def add_finding(code: str, sample: str | None = None, count: int = 1) -> None:
        finding_counts[code] += count
        if sample and sample not in finding_samples[code] and len(finding_samples[code]) < 5:
            finding_samples[code].append(sample)

    valid_rows: list[dict[str, Any]] = []
    future_snapshot_count = 0
    for index, row in enumerate(snapshots):
        product_id = _text(row.get("product_id"))
        batch_id = _text(row.get("batch_record_id")) or None
        snapshot_date = _date(row.get("snapshot_date"))
        quantity = _number(row.get("quantity_on_hand"))
        unit = _text(row.get("quantity_unit"))
        sample = batch_id or product_id or f"snapshot-row-{index + 1}"
        if not product_id or not snapshot_date or quantity is None or not unit:
            add_finding("invalid_snapshot", sample)
            continue
        if quantity < 0:
            add_finding("negative_on_hand", sample)
            continue
        if snapshot_date > as_of:
            future_snapshot_count += 1
            add_finding("future_snapshot", sample)
            continue
        valid_rows.append({
            "product_id": product_id,
            "batch_record_id": batch_id,
            "snapshot_date": snapshot_date,
            "quantity_on_hand": quantity,
            "quantity_unit": unit,
            "unit_key": unit.casefold(),
            "stock_basis": _text(row.get("stock_basis")) or "unknown",
            "snapshot_id": _text(row.get("snapshot_id")) or None,
        })

    by_position: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in valid_rows:
        by_position[_position_key(row["product_id"], row["batch_record_id"])].append(row)

    position_histories: dict[tuple[str, str], list[dict[str, Any]]] = {}
    current_positions: list[dict[str, Any]] = []
    inconsistent_unit_positions: set[tuple[str, str]] = set()
    conflicted_latest_positions: set[tuple[str, str]] = set()

    for key, rows in by_position.items():
        unit_keys = {row["unit_key"] for row in rows}
        if len(unit_keys) > 1:
            inconsistent_unit_positions.add(key)
            add_finding("inconsistent_snapshot_units", key[1] or key[0])
            continue

        by_date: dict[date, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            by_date[row["snapshot_date"]].append(row)
        history = []
        latest_date = max(by_date)
        for day in sorted(by_date):
            same_day = by_date[day]
            distinct_quantities = {row["quantity_on_hand"] for row in same_day}
            if len(same_day) > 1 and len(distinct_quantities) == 1:
                add_finding("duplicate_snapshot_rows", key[1] or key[0], len(same_day) - 1)
                history.append(dict(same_day[0]))
            elif len(distinct_quantities) > 1:
                add_finding("conflicting_snapshot_rows", key[1] or key[0])
                # Conflicting duplicates on the latest date invalidate the current position.
                if day == latest_date:
                    conflicted_latest_positions.add(key)
            else:
                history.append(dict(same_day[0]))
        position_histories[key] = history
        if key in conflicted_latest_positions:
            continue
        if not history or history[-1]["snapshot_date"] != latest_date:
            continue
        current = dict(history[-1])
        age = (as_of - current["snapshot_date"]).days
        current["snapshot_age_days"] = age
        current["is_stale"] = age > stale_days
        current["product_name"] = _text(products_by_id.get(key[0], {}).get("product_name")) or None
        current["batch_code"] = _text(batches_by_id.get(key[1], {}).get("batch_code")) or None if key[1] else None
        current["inventory_level"] = "batch" if key[1] else "product"
        if current["is_stale"]:
            add_finding("stale_snapshot", key[1] or key[0])
        if current["stock_basis"].casefold() not in {"physical", "system"}:
            add_finding("unknown_stock_basis", key[1] or key[0])
        current_positions.append(current)

    # Check each consecutive pair of unambiguous, unit-consistent snapshots.
    reconciliations: list[dict[str, Any]] = []
    for key, history in position_histories.items():
        if key in inconsistent_unit_positions or key in conflicted_latest_positions or len(history) < 2:
            continue
        history = sorted(history, key=lambda row: row["snapshot_date"])
        for previous, current in zip(history, history[1:]):
            start_date = previous["snapshot_date"]
            end_date = current["snapshot_date"]
            product_id, batch_id_or_empty = key
            batch_id = batch_id_or_empty or None
            candidate_movements = []
            block_reason = None
            for tx in transactions:
                if _text(tx.get("product_id")) != product_id:
                    continue
                tx_batch_id = _text(tx.get("batch_record_id")) or None
                if batch_id:
                    if tx_batch_id not in {None, batch_id}:
                        continue
                # A movement without a date could belong to this interval; do not assume it did not.
                tx_date = _date(tx.get("transaction_date"))
                if tx_date is None:
                    block_reason = "A relevant transaction has no usable date."
                    break
                if not (start_date < tx_date <= end_date):
                    continue
                if batch_id and tx_batch_id is None:
                    block_reason = "A product movement has no batch ID, so its effect on this batch is unknown."
                    break
                tx_unit = _text(tx.get("quantity_unit"))
                if not tx_unit or tx_unit.casefold() != current["unit_key"]:
                    block_reason = "A movement has a missing or mismatched quantity unit."
                    break
                tx_type = _text(tx.get("transaction_type"))
                if tx_type not in MOVEMENT_SIGNS and tx_type != "stock_adjustment":
                    block_reason = f"Movement type {tx_type or 'unknown'} has no safe arithmetic rule."
                    break
                if tx_type == "opening_balance":
                    block_reason = "Opening balances cannot be treated as movements between snapshots."
                    break
                amount = _number(tx.get("effective_quantity"))
                if amount is None:
                    amount = _number(tx.get("quantity")) if tx.get("free_quantity") is None else None
                if amount is None:
                    block_reason = "A movement has no unambiguous effective quantity."
                    break
                candidate_movements.append((tx_type, amount, tx_date))

            if block_reason is None and not candidate_movements:
                block_reason = "No matching dated transaction rows were supplied for this interval."
            if block_reason:
                reconciliations.append({
                    "product_id": product_id,
                    "batch_record_id": batch_id,
                    "quantity_unit": current["quantity_unit"],
                    "previous_snapshot_date": start_date.isoformat(),
                    "next_snapshot_date": end_date.isoformat(),
                    "status": "not_checkable",
                    "reason": block_reason,
                    "previous_quantity": _round(previous["quantity_on_hand"]),
                    "observed_quantity": _round(current["quantity_on_hand"]),
                    "expected_quantity": None,
                    "variance": None,
                    "movement_row_count": len(candidate_movements),
                })
                add_finding("reconciliation_not_checkable", batch_id or product_id)
                continue

            net_movement = 0.0
            for tx_type, amount, _tx_date in candidate_movements:
                if tx_type == "stock_adjustment":
                    net_movement += amount
                else:
                    net_movement += MOVEMENT_SIGNS[tx_type] * abs(amount)
            expected = previous["quantity_on_hand"] + net_movement
            observed = current["quantity_on_hand"]
            variance = observed - expected
            status = "matched" if abs(variance) <= 0.000001 else "mismatch"
            reconciliations.append({
                "product_id": product_id,
                "batch_record_id": batch_id,
                "quantity_unit": current["quantity_unit"],
                "previous_snapshot_date": start_date.isoformat(),
                "next_snapshot_date": end_date.isoformat(),
                "status": status,
                "reason": None,
                "previous_quantity": _round(previous["quantity_on_hand"]),
                "net_movement": _round(net_movement),
                "expected_quantity": _round(expected),
                "observed_quantity": _round(observed),
                "variance": _round(variance),
                "movement_row_count": len(candidate_movements),
            })
            if status == "mismatch":
                add_finding("stock_reconciliation_mismatch", batch_id or product_id)

    # Indicative price is only available with same-batch/same-unit MRP and one known currency.
    def indicative_mrp(position: dict[str, Any]) -> tuple[float | None, str | None, str | None]:
        batch_id = position["batch_record_id"]
        if not batch_id:
            return None, None, "Product-level snapshot has no batch-specific price evidence."
        prices = []
        for tx in transactions:
            if (
                _text(tx.get("product_id")) != position["product_id"]
                or _text(tx.get("batch_record_id")) != batch_id
                or _text(tx.get("quantity_unit")).casefold() != position["unit_key"]
            ):
                continue
            tx_date = _date(tx.get("transaction_date"))
            mrp = _number(tx.get("mrp"))
            if tx_date is None or tx_date > as_of or mrp is None or mrp < 0:
                continue
            doc_id = _text(tx.get("document_id"))
            tx_currency = currency_code or _text(docs_by_id.get(doc_id, {}).get("currency_code")) or None
            prices.append((tx_date, mrp, tx_currency))
        if not prices:
            return None, None, "No dated MRP record matches this batch and quantity unit."
        latest_price_date = max(row[0] for row in prices)
        latest_prices = [row for row in prices if row[0] == latest_price_date]
        if len({row[1] for row in latest_prices}) != 1:
            return None, None, "Conflicting MRPs on the latest matching date."
        currencies = {row[2] for row in latest_prices}
        if len(currencies) != 1 or None in currencies:
            return None, None, "Currency is not confirmed or is inconsistent."
        return latest_prices[0][1], next(iter(currencies)), latest_price_date.isoformat()

    alerts: list[dict[str, Any]] = []
    alert_batch_count = 0
    no_stock_batch_count = 0
    missing_batch_positions = 0
    missing_expiry_positions = 0
    for position in current_positions:
        batch_id = position["batch_record_id"]
        if not batch_id:
            continue
        batch = batches_by_id.get(batch_id)
        if batch is None:
            missing_batch_positions += 1
            add_finding("missing_batch_record", batch_id)
            continue
        expiry = _date(batch.get("expiry_date"))
        if expiry is None:
            missing_expiry_positions += 1
            add_finding("missing_expiry_date", batch_id)
            continue
        quantity = position["quantity_on_hand"]
        if quantity <= 0:
            no_stock_batch_count += 1
            continue
        alert_batch_count += 1
        days_to_expiry = (expiry - as_of).days
        if days_to_expiry < 0:
            alert_type = "expired_stock"
        elif days_to_expiry <= (windows[0] if windows else 0):
            alert_type = "expires_within_30_days"
        elif days_to_expiry <= (windows[1] if len(windows) > 1 else windows[0]):
            alert_type = "expires_within_90_days"
        elif days_to_expiry <= (windows[2] if len(windows) > 2 else windows[-1]):
            alert_type = "expires_within_180_days"
        else:
            continue

        mrp, price_currency, price_date = indicative_mrp(position)
        indicative_value = _round(quantity * mrp) if mrp is not None else None
        provisional_reasons = []
        if position["is_stale"]:
            provisional_reasons.append("The latest snapshot is stale.")
        if position["stock_basis"].casefold() not in {"physical", "system"}:
            provisional_reasons.append("Stock-count basis is unknown.")
        if indicative_value is None:
            provisional_reasons.append("An indicative MRP value could not be established.")
            add_finding("mrp_value_unavailable", batch_id)
        alerts.append({
            "alert_type": alert_type,
            "severity": ALERT_SEVERITY[alert_type],
            "product_id": position["product_id"],
            "product_name": position["product_name"],
            "batch_record_id": batch_id,
            "batch_code": _text(batch.get("batch_code")) or None,
            "expiry_date": expiry.isoformat(),
            "expiry_date_precision": batch.get("expiry_date_precision"),
            "days_to_expiry": days_to_expiry,
            "snapshot_date": position["snapshot_date"].isoformat(),
            "snapshot_age_days": position["snapshot_age_days"],
            "quantity_on_hand": _round(quantity),
            "quantity_unit": position["quantity_unit"],
            "stock_basis": position["stock_basis"],
            "indicative_mrp_per_unit": _round(mrp),
            "indicative_mrp_date": price_date,
            "indicative_mrp_value": indicative_value,
            "currency_code": price_currency,
            "value_basis": (
                "quantity_on_hand × latest dated batch-linked MRP with matching unit; "
                "indicative retail-price exposure only, not purchase cost, expiry loss, or recoverable value"
            ) if indicative_value is not None else None,
            "confidence": "provisional" if provisional_reasons else "based_on_available_records",
            "provisional_reasons": provisional_reasons,
        })
        add_finding(
            "expired_stock_alert" if alert_type == "expired_stock" else "near_expiry_alert",
            batch_id,
        )

    severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    alerts.sort(key=lambda item: (
        severity_order.get(item["severity"], 9),
        item["days_to_expiry"],
        item["product_name"] or "",
        item["batch_code"] or "",
    ))

    totals: dict[tuple[str, str], float] = defaultdict(float)
    for row in current_positions:
        totals[(row["inventory_level"], row["quantity_unit"])] += row["quantity_on_hand"]
    totals_by_unit = [
        {
            "inventory_level": level,
            "quantity_unit": unit,
            "position_count": sum(
                row["inventory_level"] == level and row["quantity_unit"].casefold() == unit.casefold()
                for row in current_positions
            ),
            "quantity_on_hand_total": _round(total),
        }
        for (level, unit), total in sorted(totals.items())
    ]

    findings = []
    for code in sorted(finding_counts):
        severity, message = finding_specs[code]
        findings.append({
            "code": code,
            "severity": severity,
            "category": "inventory_arithmetic" if "reconciliation" not in code and "stock" not in code and "expiry" not in code else "inventory",
            "message": message,
            "affected_count": finding_counts[code],
            "sample_identifiers": finding_samples[code],
        })

    expired_count = sum(row["alert_type"] == "expired_stock" for row in alerts)
    near_expiry_counts = Counter(row["alert_type"] for row in alerts if row["alert_type"] != "expired_stock")
    status = "insufficient_data" if not current_positions else (
        "ready_with_warnings" if findings else "ready"
    )
    return {
        "engine_version": ENGINE_VERSION,
        "status": status,
        "as_of_date": as_of.isoformat(),
        "snapshot_policy": {
            "latest_snapshot_on_or_before_as_of_date": True,
            "future_snapshots_excluded": future_snapshot_count,
            "stale_after_days": stale_days,
            "quantity_tolerance_for_reconciliation": 0.000001,
            "note": "Current inventory comes only from an explicit dated snapshot; invoice quantities are not treated as on-hand stock.",
        },
        "summary": {
            "input_snapshot_rows": len(snapshots),
            "valid_snapshot_rows_on_or_before_as_of_date": len(valid_rows),
            "current_position_count": len(current_positions),
            "batch_level_position_count": sum(row["inventory_level"] == "batch" for row in current_positions),
            "product_level_position_count": sum(row["inventory_level"] == "product" for row in current_positions),
            "inconsistent_unit_position_count": len(inconsistent_unit_positions),
            "conflicted_latest_position_count": len(conflicted_latest_positions),
            "positions_by_unit_and_level": totals_by_unit,
            "reconciliation_count": len(reconciliations),
            "reconciliations_matched": sum(row["status"] == "matched" for row in reconciliations),
            "reconciliations_mismatched": sum(row["status"] == "mismatch" for row in reconciliations),
            "reconciliations_not_checkable": sum(row["status"] == "not_checkable" for row in reconciliations),
            "positive_stock_batches_with_expiry_evidence": alert_batch_count,
            "zero_stock_batches_skipped": no_stock_batch_count,
            "positions_missing_batch_metadata": missing_batch_positions,
            "positions_missing_expiry": missing_expiry_positions,
            "expiry_alert_count": len(alerts),
            "expired_stock_alert_count": expired_count,
            "near_expiry_alert_counts": dict(near_expiry_counts),
            "mrp_valued_alert_count": sum(row["indicative_mrp_value"] is not None for row in alerts),
            "finding_group_count": len(findings),
        },
        "findings": findings,
        "expiry_alerts": alerts[:PREVIEW_LIMIT],
        "expiry_alerts_truncated": len(alerts) > PREVIEW_LIMIT,
        "current_positions_preview": [
            {
                "product_id": row["product_id"],
                "product_name": row["product_name"],
                "batch_record_id": row["batch_record_id"],
                "batch_code": row["batch_code"],
                "inventory_level": row["inventory_level"],
                "snapshot_date": row["snapshot_date"].isoformat(),
                "snapshot_age_days": row["snapshot_age_days"],
                "quantity_on_hand": _round(row["quantity_on_hand"]),
                "quantity_unit": row["quantity_unit"],
                "stock_basis": row["stock_basis"],
                "is_stale": row["is_stale"],
            }
            for row in sorted(current_positions, key=lambda item: (
                item["inventory_level"], item["product_id"], item["batch_record_id"] or ""
            ))[:PREVIEW_LIMIT]
        ],
        "current_positions_truncated": len(current_positions) > PREVIEW_LIMIT,
        "reconciliations_preview": reconciliations[:PREVIEW_LIMIT],
        "reconciliations_truncated": len(reconciliations) > PREVIEW_LIMIT,
        "scope_note": (
            "Arithmetic and expiry alerts use only normalized records in this upload. "
            "Reconciliation is a cross-check of supplied records, not proof of a complete ledger. "
            "MRP values are indicative retail-price exposure, not cost or expiry loss."
        ),
    }
