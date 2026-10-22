"""Conservative rule-based overstock review; not a trained forecast."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
from math import isfinite
from typing import Any

from app.inventory.history import (
    build_inventory_history_ledger,
    product_identity_reference,
    resolve_product_identity_keys,
)

ENGINE_VERSION = "1.0.0"
MIN_HISTORY_DAYS = 28
STALE_AFTER_DAYS = 30


def _date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10]) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _number(value: Any) -> float | None:
    try:
        result = float(value)
        return result if isfinite(result) else None
    except (TypeError, ValueError):
        return None


def _text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _norm(value: Any) -> str:
    return " ".join(_text(value).casefold().split())


def _r(value: float | None) -> float | None:
    return round(value, 6) if value is not None and isfinite(value) else None


def _stock_for_product(series: list[dict], complete_runs: dict[str, bool], as_of: date) -> tuple[dict | None, str]:
    product = [x for x in series if x["inventory_level"] == "product"]
    batches = [x for x in series if x["inventory_level"] == "batch"]

    def latest(x: dict) -> date | None:
        return _date((x.get("latest_observation") or {}).get("snapshot_date"))

    pd = max((latest(x) for x in product if latest(x)), default=None)
    bd = max((latest(x) for x in batches if latest(x)), default=None)
    if pd is not None and (bd is None or pd >= bd):
        candidates = [x for x in product if latest(x) == pd]
        if len(candidates) != 1:
            return None, "Multiple product-level balances conflict."
        x = candidates[0]
        obs = x.get("latest_observation") or {}
        if not x.get("latest_quantity_known") or obs.get("status") != "observed":
            return None, "The latest product-level stock balance is conflicted or unknown."
        if x.get("unit_status") != "consistent":
            return None, "Product-level stock history has conflicting units."
        age = (as_of - pd).days
        if age > STALE_AFTER_DAYS:
            return None, f"Latest stock snapshot is stale (older than {STALE_AFTER_DAYS} days)."
        if _norm(obs.get("stock_basis")) not in {"physical", "system"}:
            return None, "Stock basis is not confirmed as physical or system-reported."
        run_ids = obs.get("source_run_ids") or []
        if not any(complete_runs.get(r, False) for r in run_ids):
            return None, "Inventory source run did not attest that the snapshot is complete."
        return {
            "quantity": float(obs["quantity_on_hand"]), "unit": obs.get("quantity_unit"),
            "date": pd.isoformat(), "age": age, "level": "product", "basis": obs.get("stock_basis"),
            "batch_count": 0,
        }, ""

    if not batches:
        return None, "No usable dated inventory snapshot exists."
    if any(x.get("batch_matching_method") == "ambiguous_batch_code" for x in batches):
        return None, "Batch identity conflicts prevent a safe total."
    if any(not x.get("latest_quantity_known") for x in batches):
        return None, "At least one batch balance is conflicted or unknown."
    dates = {latest(x) for x in batches}
    if len(dates) != 1 or None in dates:
        return None, "Batch balances do not share one latest date."
    stock_date = next(iter(dates))
    age = (as_of - stock_date).days
    if age > STALE_AFTER_DAYS:
        return None, f"Latest batch snapshot is stale (older than {STALE_AFTER_DAYS} days)."
    obs = [x.get("latest_observation") or {} for x in batches]
    units = {_norm(x.get("quantity_unit")) for x in obs}
    bases = {_norm(x.get("stock_basis")) for x in obs}
    if len(units) != 1 or "" in units or any(x.get("unit_status") != "consistent" for x in batches):
        return None, "Batch balances have missing or conflicting units."
    if not bases.issubset({"physical", "system"}):
        return None, "At least one batch has an unknown stock basis."
    common: set[str] | None = None
    for point in obs:
        complete = {r for r in (point.get("source_run_ids") or []) if complete_runs.get(r, False)}
        common = complete if common is None else common & complete
    if not common:
        return None, "Batch positions do not share a source run attested as a complete inventory snapshot."
    return {
        "quantity": sum(float(x["quantity_on_hand"]) for x in obs),
        "unit": obs[0].get("quantity_unit"), "date": stock_date.isoformat(),
        "age": age, "level": "batch_aggregate", "basis": next(iter(bases)),
        "batch_count": len(batches),
    }, ""


def evaluate_overstock_review(
    inventory_observations: list[dict[str, Any]],
    sales_observations: list[dict[str, Any]],
    *,
    sales_run_id: str,
    organization_id: str,
    as_of_date: date,
    sales_history_complete: bool,
    sales_history_start_date: date | str | None,
    sales_history_end_date: date | str | None,
    target_days_of_supply: float | None,
) -> dict[str, Any]:
    """Compare fresh stock against average daily sales for one confirmed sales run."""
    start, end = _date(sales_history_start_date), _date(sales_history_end_date)
    days = (end - start).days + 1 if start and end and start <= end else None
    blockers = []
    if not sales_history_complete:
        blockers.append("The selected sales run has not confirmed every sale and every no-sale day in its continuous reporting window.")
    if start is None or end is None:
        blockers.append("Set the complete sales-history start and end dates on the selected run.")
    elif start > end:
        blockers.append("Sales-history start date must be on or before the end date.")
    elif end > as_of_date:
        blockers.append("Sales-history end date must be on or before the review as-of date.")
    if days is not None and days < MIN_HISTORY_DAYS:
        blockers.append(f"At least {MIN_HISTORY_DAYS} days of complete sales history are required.")
    if target_days_of_supply is None:
        blockers.append("Supply target_days_of_supply; MedStockIQ does not assume the pharmacy's stock policy.")
    elif not isfinite(float(target_days_of_supply)) or not 1 <= float(target_days_of_supply) <= 365:
        blockers.append("target_days_of_supply must be between 1 and 365 days.")
    if not sales_observations:
        blockers.append("The selected sales run has no transaction rows, so its complete window cannot be checked.")

    catalog: dict[tuple[str, str], dict[str, Any]] = {}
    for row in [*inventory_observations, *sales_observations]:
        entity = (_text(row.get("run_id")), _text(row.get("product_id")))
        if all(entity):
            catalog.setdefault(entity, {
                "run_id": entity[0], "product_id": entity[1],
                **{field: _text(row.get(field)) or None for field in (
                    "source_product_code", "product_name", "manufacturer_name", "hsn_code", "pack_description"
                )},
            })
    keys, _methods, _ = resolve_product_identity_keys(catalog)
    invalid: dict[str, int] = defaultdict(int)
    by_product: dict[tuple, list[dict]] = defaultdict(list)
    units_by_product: dict[tuple, set[str]] = defaultdict(set)
    outside = 0
    for row in sales_observations:
        if _text(row.get("transaction_type")).casefold() != "retail_sale":
            invalid["non_retail_sale_transaction"] += 1
            continue
        run_id, product_id = _text(row.get("run_id")) or sales_run_id, _text(row.get("product_id"))
        tx_date = _date(row.get("transaction_date"))
        qty = _number(row.get("effective_quantity"))
        if qty is None and row.get("free_quantity") is None:
            qty = _number(row.get("quantity"))
        unit = _text(row.get("quantity_unit"))
        if not product_id:
            invalid["missing_product_id"] += 1
        elif tx_date is None:
            invalid["missing_transaction_date"] += 1
        elif qty is None:
            invalid["invalid_quantity"] += 1
        elif qty < 0:
            invalid["negative_quantity"] += 1
        elif not unit:
            invalid["missing_quantity_unit"] += 1
        elif start and end and not start <= tx_date <= end:
            outside += 1
        else:
            key = keys.get((run_id, product_id))
            if key is None:
                invalid["unresolved_product_identity"] += 1
            else:
                by_product[key].append({"date": tx_date, "qty": qty, "unit": unit})
                units_by_product[key].add(_norm(unit))
    if outside:
        blockers.append(f"{outside} retail-sale row(s) fall outside the declared complete sales window.")
    if invalid:
        blockers.append(f"{sum(invalid.values())} invalid or non-retail-sale row(s) must be resolved before review.")

    report = {
        "engine_version": ENGINE_VERSION,
        "status": "insufficient_data",
        "organization_id": organization_id,
        "sales_run_id": sales_run_id,
        "as_of_date": as_of_date.isoformat(),
        "coverage": {
            "sales_history_complete_confirmed": sales_history_complete,
            "sales_history_start_date": start.isoformat() if start else None,
            "sales_history_end_date": end.isoformat() if end else None,
            "sales_history_days": days,
            "valid_retail_sale_row_count": sum(map(len, by_product.values())),
            "invalid_retail_sale_row_count": sum(invalid.values()),
            "inventory_snapshot_count": len(inventory_observations),
        },
        "policy": {
            "target_days_of_supply": target_days_of_supply,
            "minimum_sales_history_days": MIN_HISTORY_DAYS,
            "stale_snapshot_after_days": STALE_AFTER_DAYS,
            "low_sales_activity_threshold_fraction": 0.2,
            "extreme_days_of_supply_review_threshold": 365,
            "excess_rule": "max(0, confirmed on-hand quantity - average daily sales multiplied by caller-supplied target days of supply)",
        },
        "findings": [],
        "blockers": blockers,
        "warnings": [
            "This is a transparent average-demand rule, not a trained or validated forecasting model.",
            "Observed sales may be lower than true demand during stock-outs; no lost-demand correction is applied.",
            "Pending orders, lead times, seasonality, promotions, returns policy and expiry allocation are not modeled.",
            "Estimated excess is not a monetary-loss estimate or an order/cancellation instruction.",
            "Per-product review flags are screening cues. They do not establish stock-outs or latent demand by themselves.",
        ],
        "excluded_row_reasons": dict(sorted(invalid.items())),
        "limitations": [
            "No demand-based excess is calculated when no sales are observed in the window.",
            "The target days of supply is caller-provided, not assumed to be an organization-approved policy.",
            "Stock is used only from fresh, unit-consistent, complete and dated snapshots with a physical/system basis.",
        ],
    }
    if blockers:
        return report

    assert start is not None and end is not None and days is not None
    ledger = build_inventory_history_ledger(
        inventory_observations,
        organization_id=organization_id,
        as_of_date=as_of_date,
        max_series=20_000,
        identity_catalog=list(catalog.values()),
    )
    if ledger["summary"]["series_truncated"]:
        report["blockers"].append("Inventory history has too many series for a complete review.")
        return report
    completeness = {
        _text(row.get("run_id")): bool(row.get("inventory_snapshot_complete", False))
        for row in inventory_observations
    }
    stock_map: dict[str, list[dict]] = defaultdict(list)
    for series in ledger.get("series", []):
        stock_map[series["product_identity_ref"]].append(series)
    candidates = set(by_product)
    candidates.update(keys[(row["run_id"], row["product_id"])] for row in inventory_observations)
    product_info = {}
    for entity, key in keys.items():
        product_info.setdefault(key, catalog[entity])
    daily: dict[tuple, dict[date, float]] = defaultdict(lambda: defaultdict(float))
    for key, rows in by_product.items():
        if len(units_by_product[key]) == 1:
            for row in rows:
                daily[key][row["date"]] += row["qty"]

    findings = []
    for key in sorted(candidates, key=str):
        product = product_info.get(key, {})
        ref = product_identity_reference(organization_id, key)
        name = _text(product.get("product_name")) or None
        code = _text(product.get("source_product_code")) or None
        rows, units = by_product.get(key, []), units_by_product.get(key, set())
        if len(units) > 1:
            findings.append({"product_identity_ref": ref, "product_name": name, "status": "insufficient_data",
                             "reason_code": "mixed_sales_units", "reason": "Retail sales use mixed units.",
                             "sales_row_count": len(rows)})
            continue
        stock_series = stock_map.get(ref, [])
        sold = sum(daily[key].values())
        adu = sold / days
        if not stock_series:
            findings.append({"product_identity_ref": ref, "product_name": name, "status": "insufficient_data",
                             "reason_code": "missing_current_inventory_snapshot",
                             "reason": "No conservatively matched current inventory snapshot exists.",
                             "total_quantity_sold": _r(sold), "average_daily_demand": _r(adu)})
            continue
        stock, reason = _stock_for_product(stock_series, completeness, as_of_date)
        if stock is None:
            findings.append({"product_identity_ref": ref, "product_name": name, "status": "insufficient_data",
                             "reason_code": "inventory_not_usable", "reason": reason,
                             "total_quantity_sold": _r(sold), "average_daily_demand": _r(adu)})
            continue
        demand_unit = next(iter(units)) if units else None
        if demand_unit and demand_unit != _norm(stock["unit"]):
            findings.append({"product_identity_ref": ref, "product_name": name, "status": "insufficient_data",
                             "reason_code": "sales_inventory_unit_mismatch",
                             "reason": "Sales and stock use different units; no conversion is inferred.",
                             "sales_quantity_unit": demand_unit, "inventory_quantity_unit": stock["unit"]})
            continue
        days_with_sales = sum(v > 0 for v in daily[key].values())
        review_flags: list[str] = []
        if days and days_with_sales / days < 0.2:
            review_flags.append(
                f"Sparse observed sales: positive sales on {days_with_sales} of {days} history days; "
                "the days-of-supply estimate may be unstable."
            )
        base = {
            "product_identity_ref": ref, "product_name": name, "source_product_code": code,
            "inventory_quantity": _r(stock["quantity"]), "quantity_unit": stock["unit"],
            "inventory_snapshot_date": stock["date"], "inventory_snapshot_age_days": stock["age"],
            "inventory_basis": stock["basis"], "stock_level": stock["level"],
            "batch_position_count": stock["batch_count"], "sales_row_count": len(rows),
            "sales_history_days": days, "days_with_sales": days_with_sales,
            "total_quantity_sold": _r(sold), "average_daily_demand": _r(adu),
            "target_days_of_supply": _r(float(target_days_of_supply)),
            "review_flags": review_flags,
        }
        if sold <= 0:
            findings.append({**base, "status": "insufficient_demand_signal",
                             "reason_code": "no_sales_observed_in_window",
                             "reason": "No sales were observed; a demand-based excess quantity cannot be estimated.",
                             "target_stock_quantity": None, "days_of_supply": None, "estimated_excess_quantity": None})
            continue
        target = adu * float(target_days_of_supply)
        excess = max(0.0, float(stock["quantity"]) - target)
        days_of_supply = float(stock["quantity"]) / adu
        if days_of_supply > 365:
            review_flags.append(
                "Estimated days of supply exceeds one year; validate inventory and observed demand before interpreting it."
            )
        findings.append({
            **base,
            "target_stock_quantity": _r(target),
            "days_of_supply": _r(days_of_supply),
            "estimated_excess_quantity": _r(excess),
            "review_flags": review_flags,
            "status": "above_target" if excess > 0.000001 else "within_target",
            "reason_code": "stock_above_target" if excess > 0.000001 else "stock_within_target",
            "reason": "On-hand stock compared with the configured target supply period.",
        })
    findings.sort(key=lambda x: (0 if x["status"] == "above_target" else 1,
                                 -float(x.get("estimated_excess_quantity") or 0), str(x.get("product_name") or "")))
    report["findings"] = findings[:500]
    report["findings_truncated"] = len(findings) > 500
    report["summary"] = {
        "finding_count": len(findings),
        "above_target_count": sum(x["status"] == "above_target" for x in findings),
        "within_target_count": sum(x["status"] == "within_target" for x in findings),
        "insufficient_demand_signal_count": sum(x["status"] == "insufficient_demand_signal" for x in findings),
        "insufficient_data_count": sum(x["status"] == "insufficient_data" for x in findings),
    }
    report["status"] = "ready_with_warnings"
    report["inventory_ledger_summary"] = ledger["summary"]
    return report
