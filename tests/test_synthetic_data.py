import csv
from pathlib import Path

from synthetic_data.generate_dataset import generate_dataset


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def test_generator_writes_required_files(tmp_path: Path) -> None:
    outputs = generate_dataset(tmp_path / "dataset")

    assert len(_read_csv(outputs["products"])) == 8
    assert _read_csv(outputs["batches"])
    assert _read_csv(outputs["transactions"])
    assert _read_csv(outputs["inventory_snapshots"])
    assert _read_csv(outputs["replenishment_orders"])
    assert outputs["demand_truth_DO_NOT_USE_AS_INPUT"].exists()
    assert outputs["scenario_labels_DO_NOT_USE_AS_INPUT"].exists()


def test_generator_is_reproducible(tmp_path: Path) -> None:
    first = generate_dataset(tmp_path / "first", seed=123)
    second = generate_dataset(tmp_path / "second", seed=123)

    assert set(first) == set(second)
    for name in first:
        assert first[name].read_bytes() == second[name].read_bytes()


def test_inventory_snapshots_reconcile_to_transaction_ledger(tmp_path: Path) -> None:
    outputs = generate_dataset(tmp_path / "dataset")
    transactions = _read_csv(outputs["transactions"])
    snapshots = _read_csv(outputs["inventory_snapshots"])

    ledger: dict[tuple[str, str], int] = {}
    for row in transactions:
        key = (row["product_id"], row["batch_record_id"])
        quantity = int(row["effective_quantity"])
        if row["transaction_type"] in {"opening_balance", "purchase_receipt", "customer_return"}:
            ledger[key] = ledger.get(key, 0) + quantity
        elif row["transaction_type"] in {
            "retail_sale", "retailer_dispatch", "supplier_return", "damaged_writeoff", "expiry_writeoff"
        }:
            ledger[key] = ledger.get(key, 0) - quantity

    snapshot_values = {
        (row["product_id"], row["batch_record_id"]): int(row["quantity_on_hand"])
        for row in snapshots
    }
    assert ledger == snapshot_values
    assert all(quantity >= 0 for quantity in snapshot_values.values())


def test_test_oracle_labels_are_separate_from_analytical_inputs(tmp_path: Path) -> None:
    outputs = generate_dataset(tmp_path / "dataset")
    labels = _read_csv(outputs["scenario_labels_DO_NOT_USE_AS_INPUT"])
    scenarios = {row["product_id"]: row["expected_signal"] for row in labels}

    assert scenarios["SKU-004"] == "overstock"
    assert scenarios["SKU-005"] == "expiry"
    assert scenarios["SKU-006"] == "stockout"
    assert "DO_NOT_USE_AS_INPUT" in outputs["demand_truth_DO_NOT_USE_AS_INPUT"].name
