from __future__ import annotations

from datetime import date

from app.inventory.arithmetic import calculate_inventory_arithmetic


AS_OF = date(2026, 10, 17)


def _result(*, qty: float = 5, expiry: str = "2026-11-05", snapshot_date: str = "2026-10-15",
            stock_basis: str = "physical", transactions: list[dict] | None = None) -> dict:
    return {
        "tables": {
            "products": [{
                "product_id": "P1",
                "source_product_code": "SKU-001",
                "product_name": "Synthetic Medicine",
            }],
            "batches": [{
                "batch_record_id": "B1", "product_id": "P1", "batch_code": "LOT-A",
                "expiry_date": expiry, "expiry_date_precision": "day",
            }],
            "source_documents": [{"document_id": "D1", "currency_code": "INR"}],
            "inventory_snapshots": [{
                "snapshot_id": "S1", "product_id": "P1", "batch_record_id": "B1",
                "snapshot_date": snapshot_date, "quantity_on_hand": qty,
                "quantity_unit": "pack", "stock_basis": stock_basis,
            }],
            "transactions": transactions or [{
                "transaction_id": "T1", "document_id": "D1", "product_id": "P1",
                "batch_record_id": "B1", "transaction_date": "2026-10-10",
                "transaction_type": "purchase_receipt", "quantity": 5,
                "effective_quantity": 5, "quantity_unit": "pack", "mrp": 20,
            }],
        },
        "issues": [],
    }


def test_near_expiry_alert_reports_quantity_days_and_qualified_mrp_exposure() -> None:
    report = calculate_inventory_arithmetic(_result(), as_of_date=AS_OF)
    assert report["summary"]["expiry_alert_count"] == 1
    alert = report["expiry_alerts"][0]
    assert alert["alert_type"] == "expires_within_30_days"
    assert alert["severity"] == "high"
    assert alert["days_to_expiry"] == 19
    assert alert["quantity_on_hand"] == 5
    assert alert["source_product_code"] == "SKU-001"
    assert alert["indicative_mrp_value"] == 100
    assert alert["currency_code"] == "INR"
    assert alert["confidence"] == "based_on_available_records"


def test_expired_stock_is_critical_but_zero_stock_does_not_alert() -> None:
    expired = calculate_inventory_arithmetic(
        _result(expiry="2026-10-16"), as_of_date=AS_OF
    )
    assert expired["expiry_alerts"][0]["alert_type"] == "expired_stock"
    assert expired["expiry_alerts"][0]["severity"] == "critical"
    assert expired["expiry_alerts"][0]["days_to_expiry"] == -1

    zero = calculate_inventory_arithmetic(_result(qty=0), as_of_date=AS_OF)
    assert zero["summary"]["expiry_alert_count"] == 0
    assert zero["summary"]["zero_stock_batches_skipped"] == 1


def test_missing_currency_omits_value_and_marks_alert_provisional() -> None:
    result = _result()
    result["tables"]["source_documents"][0]["currency_code"] = None
    report = calculate_inventory_arithmetic(result, as_of_date=AS_OF)
    alert = report["expiry_alerts"][0]
    assert alert["indicative_mrp_value"] is None
    assert alert["confidence"] == "provisional"
    assert any("MRP value" in reason for reason in alert["provisional_reasons"])


def test_stale_snapshot_and_unknown_stock_basis_make_alert_provisional() -> None:
    report = calculate_inventory_arithmetic(
        _result(snapshot_date="2026-08-01", stock_basis="unknown"),
        as_of_date=AS_OF,
        stale_after_days=30,
    )
    alert = report["expiry_alerts"][0]
    assert alert["snapshot_age_days"] == 77
    assert alert["confidence"] == "provisional"
    assert any("stale" in reason.lower() for reason in alert["provisional_reasons"])


def test_conflicting_latest_snapshots_exclude_position_and_alert() -> None:
    result = _result()
    result["tables"]["inventory_snapshots"].append({
        "snapshot_id": "S2", "product_id": "P1", "batch_record_id": "B1",
        "snapshot_date": "2026-10-15", "quantity_on_hand": 8,
        "quantity_unit": "pack", "stock_basis": "physical",
    })
    report = calculate_inventory_arithmetic(result, as_of_date=AS_OF)
    assert report["summary"]["conflicted_latest_position_count"] == 1
    assert report["summary"]["current_position_count"] == 0
    assert report["summary"]["expiry_alert_count"] == 0
    assert any(row["code"] == "conflicting_snapshot_rows" for row in report["findings"])


def test_identical_duplicate_snapshot_rows_are_not_summed_twice() -> None:
    result = _result(qty=5)
    result["tables"]["inventory_snapshots"].append({
        **result["tables"]["inventory_snapshots"][0], "snapshot_id": "S2"
    })
    report = calculate_inventory_arithmetic(result, as_of_date=AS_OF)
    assert report["summary"]["current_position_count"] == 1
    assert report["current_positions_preview"][0]["quantity_on_hand"] == 5
    assert any(row["code"] == "duplicate_snapshot_rows" for row in report["findings"])


def test_unit_conflict_prevents_current_position_and_expiry_estimate() -> None:
    result = _result()
    result["tables"]["inventory_snapshots"].append({
        "snapshot_id": "S2", "product_id": "P1", "batch_record_id": "B1",
        "snapshot_date": "2026-10-16", "quantity_on_hand": 50,
        "quantity_unit": "strip", "stock_basis": "physical",
    })
    report = calculate_inventory_arithmetic(result, as_of_date=AS_OF)
    assert report["summary"]["inconsistent_unit_position_count"] == 1
    assert report["summary"]["expiry_alert_count"] == 0


def test_reconciliation_matches_explicit_supply_and_sale_movements() -> None:
    result = _result(snapshot_date="2026-10-01", qty=10, expiry="2027-06-30")
    result["tables"]["inventory_snapshots"].append({
        "snapshot_id": "S2", "product_id": "P1", "batch_record_id": "B1",
        "snapshot_date": "2026-10-10", "quantity_on_hand": 13,
        "quantity_unit": "pack", "stock_basis": "physical",
    })
    result["tables"]["transactions"] = [
        {
            "transaction_id": "T1", "product_id": "P1", "batch_record_id": "B1",
            "transaction_date": "2026-10-05", "transaction_type": "purchase_receipt",
            "quantity": 5, "effective_quantity": 5, "quantity_unit": "pack",
        },
        {
            "transaction_id": "T2", "product_id": "P1", "batch_record_id": "B1",
            "transaction_date": "2026-10-09", "transaction_type": "retail_sale",
            "quantity": 2, "effective_quantity": 2, "quantity_unit": "pack",
        },
    ]
    report = calculate_inventory_arithmetic(result, as_of_date=AS_OF)
    item = report["reconciliations_preview"][0]
    assert item["status"] == "matched"
    assert item["previous_quantity"] == 10
    assert item["net_movement"] == 3
    assert item["expected_quantity"] == 13
    assert item["variance"] == 0


def test_reconciliation_flags_variance_and_not_enough_movement_evidence() -> None:
    result = _result(snapshot_date="2026-10-01", qty=10, expiry="2027-06-30")
    result["tables"]["inventory_snapshots"].append({
        "snapshot_id": "S2", "product_id": "P1", "batch_record_id": "B1",
        "snapshot_date": "2026-10-10", "quantity_on_hand": 17,
        "quantity_unit": "pack", "stock_basis": "physical",
    })
    result["tables"]["transactions"] = [{
        "transaction_id": "T1", "product_id": "P1", "batch_record_id": "B1",
        "transaction_date": "2026-10-05", "transaction_type": "purchase_receipt",
        "quantity": 5, "effective_quantity": 5, "quantity_unit": "pack",
    }]
    report = calculate_inventory_arithmetic(result, as_of_date=AS_OF)
    assert report["reconciliations_preview"][0]["status"] == "mismatch"
    assert report["reconciliations_preview"][0]["variance"] == 2

    result["tables"]["transactions"] = []
    unchecked = calculate_inventory_arithmetic(result, as_of_date=AS_OF)
    assert unchecked["reconciliations_preview"][0]["status"] == "not_checkable"


def test_future_snapshots_are_excluded_from_current_stock() -> None:
    result = _result(snapshot_date="2026-10-15", expiry="2027-06-30")
    result["tables"]["inventory_snapshots"].append({
        "snapshot_id": "FUTURE", "product_id": "P1", "batch_record_id": "B1",
        "snapshot_date": "2026-10-20", "quantity_on_hand": 99,
        "quantity_unit": "pack", "stock_basis": "physical",
    })
    report = calculate_inventory_arithmetic(result, as_of_date=AS_OF)
    assert report["current_positions_preview"][0]["quantity_on_hand"] == 5
    assert report["snapshot_policy"]["future_snapshots_excluded"] == 1
