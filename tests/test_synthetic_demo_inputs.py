from __future__ import annotations

import csv
import json
from datetime import date, timedelta
from pathlib import Path

from synthetic_data.generate_demo_inputs import generate_demo_inputs


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def test_demo_inputs_are_reproducible_and_cover_zero_sales_days(tmp_path: Path) -> None:
    first = generate_demo_inputs(tmp_path / "first", as_of_date=date(2026, 9, 30), seed=17)
    second = generate_demo_inputs(tmp_path / "second", as_of_date=date(2026, 9, 30), seed=17)
    assert set(first) == set(second)
    for name in first:
        assert first[name].read_bytes() == second[name].read_bytes()

    sales = _rows(first["retail_sales_upload"])
    inventory = _rows(first["inventory_snapshot_upload"])
    purchases = _rows(first["purchase_invoice_upload"])
    manifest = json.loads(first["manifest"].read_text(encoding="utf-8"))

    assert len(sales) == 365 * 8
    assert len(inventory) > 0
    assert len(purchases) > 0
    assert manifest["row_counts"]["retail_sales_upload.csv"] == len(sales)
    assert "DO_NOT_USE_AS_INPUT" not in " ".join(path.name for path in first.values())

    observed_products = {row["SKU"] for row in sales}
    assert len(observed_products) == 8
    day_counts: dict[str, int] = {}
    for row in sales:
        day_counts[row["Sale Date"]] = day_counts.get(row["Sale Date"], 0) + 1
    assert len(day_counts) == 365
    assert set(day_counts.values()) == {8}
    start = date.fromisoformat(min(day_counts))
    end = date.fromisoformat(max(day_counts))
    assert start == date(2025, 10, 1)
    assert end == date(2026, 9, 30)
    assert end - start == timedelta(days=364)
    assert any(int(row["Quantity Sold"]) == 0 for row in sales)
    assert all("SYNTH" in row["Product Name"] for row in sales)
