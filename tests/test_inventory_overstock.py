from __future__ import annotations

from datetime import date, timedelta

from app.inventory.overstock import evaluate_overstock_review

AS_OF = date(2026, 10, 20)
START = date(2026, 9, 1)
END = START + timedelta(days=27)


def inventory(*, quantity=40, snapshot_date="2026-10-15", complete=True, unit="pack", code="SKU-1"):
    return [{
        "run_id": "STOCK-RUN", "snapshot_id": "S1", "organization_id": "ORG-1",
        "snapshot_date": snapshot_date, "product_id": "INV-P1", "batch_record_id": "INV-B1",
        "quantity_on_hand": quantity, "quantity_unit": unit, "stock_basis": "physical",
        "source_product_code": code, "product_name": "Synthetic Medicine",
        "manufacturer_name": "Synthetic Manufacturer", "hsn_code": "300490",
        "pack_description": "10'S", "batch_code": "B001", "expiry_date": "2027-06-30",
        "manufacturing_date": "2026-01-01", "source_file_name": "inventory.csv",
        "document_type": "inventory_report", "inventory_snapshot_complete": complete,
    }]


def sales(*, days=28, quantity=2, unit="pack", code="SKU-1"):
    return [{
        "run_id": "SALES-RUN", "transaction_id": f"T{i}",
        "transaction_date": (START + timedelta(days=i)).isoformat(),
        "transaction_type": "retail_sale", "product_id": "SALE-P1",
        "quantity": quantity, "effective_quantity": quantity, "free_quantity": None,
        "quantity_unit": unit, "source_row_number": i + 2, "source_product_code": code,
        "product_name": "Synthetic Medicine", "manufacturer_name": "Synthetic Manufacturer",
        "hsn_code": "300490", "pack_description": "10'S",
    } for i in range(days)]


def evaluate(stock=None, sale=None, *, complete=True, start=START, end=END, target=10):
    return evaluate_overstock_review(
        inventory() if stock is None else stock,
        sales() if sale is None else sale,
        sales_run_id="SALES-RUN", organization_id="ORG-1", as_of_date=AS_OF,
        sales_history_complete=complete, sales_history_start_date=start,
        sales_history_end_date=end, target_days_of_supply=target,
    )


def test_complete_compatible_history_calculates_target_and_excess():
    report = evaluate()
    row = report["findings"][0]
    assert row["status"] == "above_target"
    assert row["average_daily_demand"] == 2
    assert row["target_stock_quantity"] == 20
    assert row["days_of_supply"] == 20
    assert row["estimated_excess_quantity"] == 20
    assert row["stock_level"] == "batch_aggregate"


def test_unconfirmed_sales_history_blocks_calculation():
    report = evaluate(complete=False)
    assert report["status"] == "insufficient_data"
    assert report["findings"] == []


def test_inventory_snapshot_must_be_attested_complete():
    row = evaluate(stock=inventory(complete=False))["findings"][0]
    assert row["status"] == "insufficient_data"
    assert "did not attest" in row["reason"]


def test_stale_snapshot_is_not_used():
    row = evaluate(stock=inventory(snapshot_date="2026-09-01"))["findings"][0]
    assert row["status"] == "insufficient_data"
    assert "stale" in row["reason"]


def test_sales_stock_units_must_match():
    row = evaluate(stock=inventory(unit="strip"))["findings"][0]
    assert row["reason_code"] == "sales_inventory_unit_mismatch"


def test_no_sales_does_not_create_excess_estimate():
    row = evaluate(sale=sales(quantity=0))["findings"][0]
    assert row["status"] == "insufficient_demand_signal"
    assert row["estimated_excess_quantity"] is None


def test_short_history_and_missing_target_are_blocked():
    report = evaluate(sale=sales(days=20), end=START + timedelta(days=19))
    assert report["status"] == "insufficient_data"
    assert report["blockers"]
    assert evaluate(target=None)["status"] == "insufficient_data"


def test_mixed_sales_units_are_not_combined():
    rows = sales()
    rows[-1]["quantity_unit"] = "strip"
    row = evaluate(sale=rows)["findings"][0]
    assert row["reason_code"] == "mixed_sales_units"


def test_misclassified_or_out_of_window_sales_rows_block_review():
    rows = sales()
    rows[0]["transaction_type"] = "retailer_dispatch"
    assert evaluate(sale=rows)["status"] == "insufficient_data"
    rows = sales()
    rows[-1]["transaction_date"] = "2026-10-01"
    assert evaluate(sale=rows)["status"] == "insufficient_data"


def test_empty_sales_run_blocks_review():
    report = evaluate(sale=[])
    assert report["status"] == "insufficient_data"
    assert report["findings"] == []


def test_no_matching_stock_and_product_code_conflicts_do_not_fake_an_excess():
    assert evaluate(stock=[])["findings"][0]["reason_code"] == "missing_current_inventory_snapshot"
    stock, sale = inventory(code="SHARED"), sales(code="SHARED")
    stock[0]["product_name"] = "Different Medicine"
    report = evaluate(stock=stock, sale=sale)
    assert report["summary"]["above_target_count"] == 0
    assert report["summary"]["insufficient_data_count"] >= 1
