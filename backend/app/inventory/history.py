"""Conservative, read-only history across separately persisted inventory uploads.

IDs produced by normalization are run-local. This module therefore derives cross-run
identity from strict evidence, keeps weak identities separate, and treats same-day
conflicts as unknown rather than picking a convenient quantity.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
from hashlib import sha256
from math import isfinite
import json
import re
from typing import Any

ENGINE_VERSION = "1.0.0"
CORE_IDENTITY_FIELDS = (
    "product_name",
    "manufacturer_name",
    "hsn_code",
    "pack_description",
)
PRODUCT_CONFLICT_GUARD_FIELDS = (
    "product_name",
    "manufacturer_name",
    "hsn_code",
    "pack_description",
)
MAX_SOURCE_REFERENCES = 10


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
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if isfinite(result) else None


def _text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _norm(value: Any) -> str:
    return re.sub(r"\s+", " ", _text(value)).casefold()


def _complete_product_identity(product: dict[str, Any]) -> tuple[str, ...] | None:
    parts = tuple(_norm(product.get(field)) for field in CORE_IDENTITY_FIELDS)
    return parts if all(parts) else None


def _key_json(value: Any) -> Any:
    if isinstance(value, tuple):
        return [_key_json(item) for item in value]
    if isinstance(value, list):
        return [_key_json(item) for item in value]
    if isinstance(value, (str, int, float)) or value is None:
        return value
    return str(value)


def _identity_ref(organization_id: str, key: tuple[Any, ...]) -> str:
    serial = json.dumps(_key_json(key), separators=(",", ":"), ensure_ascii=True)
    digest = sha256(f"{organization_id}|{serial}".encode("utf-8")).hexdigest()[:16]
    return f"inv-{digest}"


def _sorted_values(values: set[str]) -> list[str]:
    return sorted(values)


def resolve_product_identity_keys(
    products: dict[tuple[str, str], dict[str, Any]],
) -> tuple[
    dict[tuple[str, str], tuple[Any, ...]],
    dict[tuple[str, str], str],
    dict[tuple[Any, ...], set[str]],
]:
    """Resolve product identity with one policy shared by ledger and risk modules."""
    code_groups: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for entity, product in products.items():
        code = _norm(product.get("source_product_code"))
        if code:
            code_groups[code].append(entity)

    code_conflicts: dict[str, list[str]] = {}
    for code, entities in code_groups.items():
        conflicting_fields = []
        for field in PRODUCT_CONFLICT_GUARD_FIELDS:
            values = {_norm(products[entity].get(field)) for entity in entities}
            values.discard("")
            if len(values) > 1:
                conflicting_fields.append(field)
        if conflicting_fields:
            code_conflicts[code] = conflicting_fields

    product_keys: dict[tuple[str, str], tuple[Any, ...]] = {}
    product_methods: dict[tuple[str, str], str] = {}
    for entity, product in products.items():
        code = _norm(product.get("source_product_code"))
        exact = _complete_product_identity(product)
        if code and code not in code_conflicts:
            key = ("source_code", code)
            method = "source_product_code"
        elif exact:
            key = ("exact_attributes", *exact)
            method = "exact_product_attributes"
            if code and code in code_conflicts:
                method = "exact_attributes_after_code_conflict"
        else:
            key = ("run_local_product", entity[0], entity[1])
            method = "ambiguous_source_product_code" if code else "run_local_only"
        product_keys[entity] = key
        product_methods[entity] = method

    identity_runs: dict[tuple[Any, ...], set[str]] = defaultdict(set)
    for entity, key in product_keys.items():
        identity_runs[key].add(entity[0])
    return product_keys, product_methods, identity_runs


def product_identity_reference(organization_id: str, identity_key: tuple[Any, ...]) -> str:
    """Return the deterministic reference used for a conservative product identity."""
    return _identity_ref(organization_id, identity_key)


def build_inventory_history_ledger(
    observations: list[dict[str, Any]],
    *,
    organization_id: str,
    as_of_date: date | None = None,
    max_series: int = 100,
    identity_catalog: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build inventory timelines from persisted snapshot rows for one organization.

    Accepted product matches:
    1. A source product code that has no contradictory known core attributes.
    2. An exact normalized tuple of product name, manufacturer, HSN and pack.
    Otherwise the product remains scoped to its original normalization run.

    Batch matches require a batch code under an already matched product identity.
    A known expiry-date disagreement makes that batch code ambiguous. No quantities
    from two observations on the same date are summed: duplicates are counted once;
    conflicting values leave that date's quantity unknown.
    """
    as_of = as_of_date or date.today()
    series_limit = max(1, min(int(max_series), 20_000))
    warnings: list[str] = []
    invalid_rows = 0
    future_snapshot_count = 0
    usable: list[dict[str, Any]] = []

    for index, source in enumerate(observations):
        snapshot_date = _date(source.get("snapshot_date"))
        if snapshot_date is not None and snapshot_date > as_of:
            future_snapshot_count += 1
            continue
        run_id = _text(source.get("run_id"))
        product_id = _text(source.get("product_id"))
        quantity = _number(source.get("quantity_on_hand"))
        quantity_unit = _text(source.get("quantity_unit"))
        if (
            not snapshot_date or not run_id or not product_id
            or quantity is None or quantity < 0 or not quantity_unit
        ):
            invalid_rows += 1
            continue
        row = dict(source)
        row.update({
            "snapshot_date_parsed": snapshot_date,
            "run_id": run_id,
            "product_id": product_id,
            "batch_record_id": _text(source.get("batch_record_id")) or None,
            "batch_code": _text(source.get("batch_code")) or None,
            "expiry_date_parsed": _date(source.get("expiry_date")),
            "quantity_value": round(quantity, 6),
            "quantity_unit_text": quantity_unit,
            "quantity_unit_key": _norm(quantity_unit),
            "organization_id": _text(source.get("organization_id")) or organization_id,
        })
        if row["organization_id"] != organization_id:
            invalid_rows += 1
            continue
        usable.append(row)

    # One product entity is a normalized product ID within one saved run.
    products: dict[tuple[str, str], dict[str, Any]] = {}
    for row in usable:
        entity = (row["run_id"], row["product_id"])
        if entity not in products:
            products[entity] = {
                "run_id": row["run_id"],
                "product_id": row["product_id"],
                **{
                    field: _text(row.get(field)) or None
                    for field in (
                        "source_product_code", "product_name", "manufacturer_name",
                        "hsn_code", "pack_description",
                    )
                },
            }
    for row in identity_catalog or []:
        entity = (_text(row.get("run_id")), _text(row.get("product_id")))
        if all(entity) and entity not in products:
            products[entity] = {
                "run_id": entity[0],
                "product_id": entity[1],
                **{
                    field: _text(row.get(field)) or None
                    for field in (
                        "source_product_code", "product_name", "manufacturer_name",
                        "hsn_code", "pack_description",
                    )
                },
            }

    product_keys, product_methods, product_identity_runs = resolve_product_identity_keys(products)

    # Resolve batch identities only after products have been matched conservatively.
    batches: dict[tuple[str, str], dict[str, Any]] = {}
    for row in usable:
        batch_id = row["batch_record_id"]
        if not batch_id:
            continue
        entity = (row["run_id"], batch_id)
        if entity not in batches:
            batches[entity] = {
                "run_id": row["run_id"],
                "batch_record_id": batch_id,
                "product_key": product_keys[(row["run_id"], row["product_id"])],
                "batch_code": _text(row.get("batch_code")) or None,
                "expiry_date": row["expiry_date_parsed"],
                "manufacturing_date": _date(row.get("manufacturing_date")),
            }

    batch_code_groups: dict[tuple[tuple[Any, ...], str], list[tuple[str, str]]] = defaultdict(list)
    for entity, batch in batches.items():
        code = _norm(batch.get("batch_code"))
        if code:
            batch_code_groups[(batch["product_key"], code)].append(entity)

    batch_conflicts: set[tuple[tuple[Any, ...], str]] = set()
    for group_key, entities in batch_code_groups.items():
        expiries = {
            batch["expiry_date"].isoformat()
            for entity in entities
            if (batch := batches[entity]).get("expiry_date") is not None
        }
        manufacturing_dates = {
            batch["manufacturing_date"].isoformat()
            for entity in entities
            if (batch := batches[entity]).get("manufacturing_date") is not None
        }
        if len(expiries) > 1 or len(manufacturing_dates) > 1:
            batch_conflicts.add(group_key)

    batch_keys: dict[tuple[str, str], tuple[Any, ...]] = {}
    batch_methods: dict[tuple[str, str], str] = {}
    for entity, batch in batches.items():
        code = _norm(batch.get("batch_code"))
        if code and (batch["product_key"], code) not in batch_conflicts:
            key = ("batch_code", batch["product_key"], code)
            method = "batch_code_under_matched_product"
        elif code:
            key = ("run_local_batch", entity[0], entity[1])
            method = "ambiguous_batch_code"
        else:
            key = ("run_local_batch", entity[0], entity[1])
            method = "run_local_only"
        batch_keys[entity] = key
        batch_methods[entity] = method

    # Position key separates product-level totals from batch-level observations.
    grouped: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in usable:
        product_entity = (row["run_id"], row["product_id"])
        product_key = product_keys[product_entity]
        row["product_identity_key"] = product_key
        row["product_matching_method"] = product_methods[product_entity]
        batch_id = row["batch_record_id"]
        if batch_id:
            batch_entity = (row["run_id"], batch_id)
            batch_key = batch_keys.get(batch_entity, ("run_local_batch", row["run_id"], batch_id))
            group_key = ("batch_position", product_key, batch_key)
            row["batch_matching_method"] = batch_methods.get(batch_entity, "run_local_only")
        else:
            group_key = ("product_position", product_key)
            row["batch_matching_method"] = None
        grouped[group_key].append(row)

    all_series = []
    duplicate_observation_count = 0
    conflicting_snapshot_date_count = 0
    unit_conflict_series_count = 0
    latest_quantity_unknown_series_count = 0
    cross_upload_matched_series_count = 0
    run_local_only_series_count = 0
    ambiguous_identity_series_count = 0

    for group_key, rows in grouped.items():
        rows = sorted(
            rows,
            key=lambda row: (
                row["snapshot_date_parsed"],
                row["run_id"],
                row.get("snapshot_id") or "",
            ),
        )
        product_key = rows[0]["product_identity_key"]
        product_rows = [
            product for entity, product in products.items()
            if product_keys[entity] == product_key
        ]
        product_rows = sorted(product_rows, key=lambda row: (row["run_id"], row["product_id"]))
        display_product = product_rows[0] if product_rows else {}
        methods = {row["product_matching_method"] for row in rows}
        product_method = (
            "source_product_code" if "source_product_code" in methods
            else "exact_product_attributes" if any(
                method in {"exact_product_attributes", "exact_attributes_after_code_conflict"}
                for method in methods
            )
            else sorted(methods)[0] if methods else "run_local_only"
        )
        run_ids = sorted({row["run_id"] for row in rows})
        source_files = sorted({_text(row.get("source_file_name")) for row in rows if _text(row.get("source_file_name"))})
        units = {row["quantity_unit_key"] for row in rows}
        unit_conflict = len(units) > 1
        if unit_conflict:
            unit_conflict_series_count += 1

        by_date: dict[date, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            by_date[row["snapshot_date_parsed"]].append(row)
        history: list[dict[str, Any]] = []
        for day in sorted(by_date):
            day_rows = by_date[day]
            quantities = {row["quantity_value"] for row in day_rows}
            day_units = {row["quantity_unit_key"] for row in day_rows}
            conflict = len(quantities) > 1 or len(day_units) > 1
            if conflict:
                conflicting_snapshot_date_count += 1
                point_quantity = None
                point_status = "conflict"
                duplicate_count = 0
            else:
                point_quantity = next(iter(quantities))
                point_status = "observed"
                duplicate_count = max(0, len(day_rows) - 1)
                duplicate_observation_count += duplicate_count
            bases = {_norm(row.get("stock_basis")) or "unknown" for row in day_rows}
            source_runs = sorted({row["run_id"] for row in day_rows})
            point = {
                "snapshot_date": day.isoformat(),
                "status": point_status,
                "quantity_on_hand": point_quantity,
                "candidate_quantities": sorted(quantities) if conflict else [],
                "quantity_unit": (
                    next(iter({row["quantity_unit_text"] for row in day_rows}))
                    if len(day_units) == 1 else None
                ),
                "stock_basis": next(iter(bases)) if len(bases) == 1 else "conflict",
                "observation_count": len(day_rows),
                "duplicate_observation_count": duplicate_count,
                "source_run_ids": source_runs[:MAX_SOURCE_REFERENCES],
                "source_file_names": sorted({
                    _text(row.get("source_file_name")) for row in day_rows
                    if _text(row.get("source_file_name"))
                })[:MAX_SOURCE_REFERENCES],
                "source_references_truncated": len(source_runs) > MAX_SOURCE_REFERENCES,
                "change_since_previous_snapshot": None,
            }
            history.append(point)

        # This is only a difference between recorded balances, not a reconstructed movement.
        if not unit_conflict:
            for previous, current in zip(history, history[1:]):
                if previous["status"] == current["status"] == "observed":
                    current["change_since_previous_snapshot"] = round(
                        current["quantity_on_hand"] - previous["quantity_on_hand"], 6
                    )

        latest = history[-1] if history else None
        latest_known = bool(
            latest
            and latest["status"] == "observed"
            and not unit_conflict
        )
        if not latest_known:
            latest_quantity_unknown_series_count += 1

        product_method_codes = {
            "ambiguous_source_product_code", "exact_attributes_after_code_conflict"
        }
        batch_method = rows[0].get("batch_matching_method")
        ambiguous = bool(methods & product_method_codes) or batch_method == "ambiguous_batch_code"
        if ambiguous:
            ambiguous_identity_series_count += 1
        run_local = (
            product_method == "run_local_only"
            or batch_method == "run_local_only"
            or product_method == "ambiguous_source_product_code"
            or batch_method == "ambiguous_batch_code"
        )
        if run_local:
            run_local_only_series_count += 1
        cross_matched = (
            len(run_ids) > 1
            and product_method in {"source_product_code", "exact_product_attributes"}
            and batch_method != "run_local_only"
            and batch_method != "ambiguous_batch_code"
        )
        if cross_matched:
            cross_upload_matched_series_count += 1

        batch_identities = [
            batches[(row["run_id"], row["batch_record_id"])]
            for row in rows
            if row.get("batch_record_id") and (row["run_id"], row["batch_record_id"]) in batches
        ]
        batch_codes = sorted({_text(batch.get("batch_code")) for batch in batch_identities if _text(batch.get("batch_code"))})
        expiry_dates = sorted({
            batch["expiry_date"].isoformat()
            for batch in batch_identities if batch.get("expiry_date") is not None
        })
        display_name = _text(display_product.get("product_name")) or None
        series = {
            "identity_ref": _identity_ref(organization_id, group_key),
            "product_identity_ref": _identity_ref(organization_id, product_key),
            "product": {
                "product_name": display_name,
                "source_product_code": _text(display_product.get("source_product_code")) or None,
                "manufacturer_name": _text(display_product.get("manufacturer_name")) or None,
                "hsn_code": _text(display_product.get("hsn_code")) or None,
                "pack_description": _text(display_product.get("pack_description")) or None,
            },
            "product_matching_method": product_method,
            "product_matching_status": (
                "matched_across_uploads"
                if len(product_identity_runs.get(product_key, set())) > 1
                and product_method in {"source_product_code", "exact_product_attributes"}
                else "ambiguous" if ambiguous else "run_local_only"
                if product_method in {"run_local_only", "ambiguous_source_product_code"}
                else "matched_within_available_history"
            ),
            "inventory_level": "batch" if group_key[0] == "batch_position" else "product",
            "batch_codes": batch_codes,
            "expiry_dates": expiry_dates,
            "batch_matching_method": batch_method,
            "source_run_ids": run_ids[:MAX_SOURCE_REFERENCES],
            "source_file_names": source_files[:MAX_SOURCE_REFERENCES],
            "source_references_truncated": len(run_ids) > MAX_SOURCE_REFERENCES or len(source_files) > MAX_SOURCE_REFERENCES,
            "observation_count": len(rows),
            "distinct_snapshot_dates": len(history),
            "distinct_run_count": len(run_ids),
            "quantity_units": sorted({row["quantity_unit_text"] for row in rows}),
            "unit_status": "conflict" if unit_conflict else "consistent",
            "series_status": (
                "unit_conflict" if unit_conflict
                else "latest_snapshot_conflict" if latest and latest["status"] == "conflict"
                else "ready_with_warnings" if any(point["status"] == "conflict" for point in history)
                else "ready"
            ),
            "latest_quantity_known": latest_known,
            "latest_observation": latest,
            "history": history,
        }
        if len(run_ids) > 1 and not cross_matched:
            series["identity_warning"] = (
                "Multiple runs are present, but this series does not have enough unambiguous identity evidence to claim a safe cross-upload match."
            )
        if unit_conflict:
            series["identity_warning"] = (
                "The same derived product/batch position has multiple quantity units; no balance comparison or latest-quantity claim is made."
            )
        all_series.append(series)

    all_series.sort(
        key=lambda item: (
            item["latest_observation"]["snapshot_date"] if item["latest_observation"] else "",
            item["identity_ref"],
        ),
        reverse=True,
    )
    if invalid_rows:
        warnings.append(f"{invalid_rows} invalid or cross-organization snapshot row(s) were excluded.")
    if future_snapshot_count:
        warnings.append(f"{future_snapshot_count} future-dated snapshot row(s) were excluded from the as-of ledger.")
    if duplicate_observation_count:
        warnings.append("Identical same-date observations were counted once; quantities from repeated uploads were not added.")
    if conflicting_snapshot_date_count:
        warnings.append("One or more same-date snapshot groups conflict; their quantities are unknown and were not resolved automatically.")
    if unit_conflict_series_count:
        warnings.append("Some derived positions contain multiple quantity units; balances were not converted.")
    if run_local_only_series_count:
        warnings.append("Some products or batches lack sufficient stable identifiers and remain separate by normalization run.")
    if any("ambiguous" in item["product_matching_status"] or item["batch_matching_method"] == "ambiguous_batch_code" for item in all_series):
        warnings.append("Some source codes or batch codes have conflicting identity attributes; those records were not merged automatically.")
    series_truncated = len(all_series) > series_limit
    visible_series = all_series[:series_limit]

    if not usable:
        status = "insufficient_data"
        warnings.append("No valid non-future inventory snapshot was available for the requested as-of date.")
    elif warnings or series_truncated or latest_quantity_unknown_series_count:
        status = "ready_with_warnings"
    else:
        status = "ready"

    return {
        "engine_version": ENGINE_VERSION,
        "status": status,
        "organization_id": organization_id,
        "as_of_date": as_of.isoformat(),
        "matching_policy": {
            "product": (
                "Compatible normalized source product code; otherwise exact normalized product name, "
                "manufacturer, HSN and pack; otherwise run-local only. Contradictory known attributes block code matching."
            ),
            "batch": (
                "Normalized batch code matched only under the same product identity; conflicting known expiry dates block batch-code matching."
            ),
            "snapshot": (
                "Same-date identical quantities count once; differing quantities or units create an unresolved conflict. "
                "No same-date quantities are summed and no latest conflicting balance is selected."
            ),
            "quantity_unit": "No unit conversion is inferred; mixed units make the derived position's latest quantity unknown.",
            "scope": "Read-only derived view over persisted snapshots. Identity references are derived, not durable user-confirmed catalog IDs.",
        },
        "summary": {
            "input_snapshot_count": len(observations),
            "eligible_snapshot_count": len(usable),
            "invalid_snapshot_count": invalid_rows,
            "future_snapshot_count": future_snapshot_count,
            "series_count": len(all_series),
            "series_returned": len(visible_series),
            "series_truncated": series_truncated,
            "cross_upload_matched_series_count": cross_upload_matched_series_count,
            "run_local_only_series_count": run_local_only_series_count,
            "ambiguous_identity_series_count": ambiguous_identity_series_count,
            "duplicate_observation_count": duplicate_observation_count,
            "conflicting_snapshot_date_count": conflicting_snapshot_date_count,
            "unit_conflict_series_count": unit_conflict_series_count,
            "latest_quantity_unknown_series_count": latest_quantity_unknown_series_count,
        },
        "series": visible_series,
        "blockers": [] if usable else ["At least one valid dated inventory snapshot is needed for a history ledger."],
        "warnings": warnings,
        "limitations": [
            "This ledger compares recorded on-hand balances only; it does not reconstruct inventory from invoices.",
            "Source-code and exact-attribute matches are deterministic heuristics, not user-approved permanent catalog links.",
            "A quantity difference between two dates is not proof of sales, shrinkage, expiry loss, or any particular movement.",
            "Corrected reports and revisions are not automatically recognized; conflicting same-date balances remain unresolved.",
        ],
    }
