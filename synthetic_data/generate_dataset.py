"""Generate deterministic synthetic inventory data for MedStockIQ development.

These files are synthetic fixtures for software testing, not real pharmacy data.
"""

from __future__ import annotations

import argparse
import csv
import math
import random
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

DEFAULT_AS_OF = date(2026, 9, 30)
ORG_ID = "SYNTH-ORG-001"
UNIT = "pack"


@dataclass(frozen=True)
class ProductSpec:
    product_id: str
    name: str
    manufacturer: str
    mean_demand: float
    pattern: str
    scenario: str


SPECS = (
    ProductSpec("SKU-001", "SYNTHETIC PRODUCT 001", "SYNTH-MFG-A", 4.0, "steady", "balanced"),
    ProductSpec("SKU-002", "SYNTHETIC PRODUCT 002", "SYNTH-MFG-B", 8.0, "steady", "fast_moving"),
    ProductSpec("SKU-003", "SYNTHETIC PRODUCT 003", "SYNTH-MFG-C", 0.8, "steady", "slow_moving"),
    ProductSpec("SKU-004", "SYNTHETIC PRODUCT 004", "SYNTH-MFG-A", 0.8, "steady", "overstock_risk"),
    ProductSpec("SKU-005", "SYNTHETIC PRODUCT 005", "SYNTH-MFG-B", 0.7, "steady", "expiry_risk"),
    ProductSpec("SKU-006", "SYNTHETIC PRODUCT 006", "SYNTH-MFG-C", 8.0, "steady", "stockout_risk"),
    ProductSpec("SKU-007", "SYNTHETIC PRODUCT 007", "SYNTH-MFG-A", 4.0, "seasonal", "seasonal"),
    ProductSpec("SKU-008", "SYNTHETIC PRODUCT 008", "SYNTH-MFG-B", 0.8, "intermittent", "intermittent"),
)

FIELDS = {
    "products": [
        "product_id", "organization_id", "source_product_code", "product_name",
        "manufacturer_name", "hsn_code", "pack_description", "quantity_unit",
        "units_per_pack", "product_match_status",
    ],
    "batches": [
        "batch_record_id", "organization_id", "product_id", "batch_code",
        "manufacturing_date", "expiry_raw", "expiry_date", "expiry_date_precision",
    ],
    "transactions": [
        "transaction_id", "organization_id", "document_id", "transaction_date",
        "transaction_type", "product_id", "batch_record_id", "quantity",
        "quantity_unit", "free_quantity", "effective_quantity", "unit_rate", "mrp",
        "discount_percent", "tax_rate", "line_amount", "line_total_amount",
        "source_row_number",
    ],
    "inventory_snapshots": [
        "snapshot_id", "organization_id", "snapshot_date", "product_id",
        "batch_record_id", "quantity_on_hand", "quantity_unit", "stock_basis",
    ],
    "replenishment_orders": [
        "order_id", "organization_id", "product_id", "order_date",
        "quantity_ordered", "quantity_unit", "expected_arrival_date",
        "actual_arrival_date", "order_status", "supplier_id",
    ],
    "demand_truth_DO_NOT_USE_AS_INPUT": [
        "date", "product_id", "latent_demand_units", "fulfilled_units",
        "unmet_demand_units",
    ],
    "scenario_labels_DO_NOT_USE_AS_INPUT": [
        "product_id", "scenario", "expected_signal", "notes",
    ],
}


def _month_end(value: date) -> date:
    next_month = date(value.year + (value.month == 12), 1 if value.month == 12 else value.month + 1, 1)
    return next_month - timedelta(days=1)


def _expiry_after(value: date, days: int) -> date:
    # Synthetic expiry labels mimic invoices with month/year precision.
    return _month_end(value + timedelta(days=days))


def _demand(spec: ProductSpec, day: date, rng: random.Random) -> int:
    if spec.pattern == "intermittent":
        return rng.randint(1, 4) if rng.random() < 0.30 else 0
    multiplier = 1.0
    if spec.pattern == "seasonal":
        if day.month in {11, 12, 1, 2}:
            multiplier = 1.4
        elif day.month in {6, 7, 8}:
            multiplier = 0.8
    mean = spec.mean_demand * multiplier
    return max(0, int(round(rng.gauss(mean, max(0.5, math.sqrt(mean) * 0.55)))))


def _receipts(spec: ProductSpec, start: date, as_of: date) -> list[dict[str, Any]]:
    supplier_id = f"SYN-SUP-{(int(spec.product_id[-1]) - 1) % 3 + 1:03d}"
    events: list[dict[str, Any]] = []
    if spec.scenario in {"overstock_risk", "expiry_risk"}:
        receipt_date = as_of - timedelta(days=20)
        expiry = _expiry_after(as_of, 500 if spec.scenario == "overstock_risk" else 15)
        events.append({
            "date": receipt_date,
            "quantity": 400 if spec.scenario == "overstock_risk" else 150,
            "expiry": expiry,
            "lead_time": 4,
            "supplier": supplier_id,
        })
        return events

    last_regular = as_of - timedelta(days=40) if spec.scenario == "stockout_risk" else as_of
    receipt_date = start + timedelta(days=30)
    while receipt_date <= last_regular:
        lead = 3 + (receipt_date.day % 4)
        events.append({
            "date": receipt_date,
            "quantity": max(10, int(math.ceil(spec.mean_demand * 30))),
            "expiry": _expiry_after(receipt_date, 540),
            "lead_time": lead,
            "supplier": supplier_id,
        })
        receipt_date += timedelta(days=30)

    if spec.scenario == "stockout_risk":
        receipt_date = as_of - timedelta(days=7)
        events.append({
            "date": receipt_date,
            "quantity": 90,
            "expiry": _expiry_after(as_of, 540),
            "lead_time": 5,
            "supplier": supplier_id,
        })
    return events


def _write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def generate_dataset(
    output_dir: Path | str,
    as_of_date: date = DEFAULT_AS_OF,
    seed: int = 42,
) -> dict[str, Path]:
    """Generate deterministic CSVs with batch-level stock reconciliation."""
    outdir = Path(output_dir)
    start = as_of_date - timedelta(days=364)
    rng = random.Random(seed)
    rows = {name: [] for name in FIELDS}
    states: dict[str, list[dict[str, Any]]] = {s.product_id: [] for s in SPECS}
    counters = {"tx": 0, "batch": 0, "order": 0, "snapshot": 0}

    def add_transaction(
        spec: ProductSpec, batch: dict[str, Any], when: date, kind: str,
        qty: int, free_qty: int = 0, rate: float | None = None, row_num: int | str = "",
    ) -> None:
        counters["tx"] += 1
        mrp = prices[spec.product_id][1]
        discount = 3.0 if kind == "purchase_receipt" else 0.0
        amount = round(qty * (rate or 0.0) * (1 - discount / 100), 2)
        rows["transactions"].append({
            "transaction_id": f"TX-{counters['tx']:07d}",
            "organization_id": ORG_ID,
            "document_id": f"{kind.upper()}-{spec.product_id}-{when.isoformat()}",
            "transaction_date": when.isoformat(),
            "transaction_type": kind,
            "product_id": spec.product_id,
            "batch_record_id": batch["batch_record_id"],
            "quantity": qty,
            "quantity_unit": UNIT,
            "free_quantity": free_qty,
            "effective_quantity": qty + free_qty,
            "unit_rate": "" if rate is None else round(rate, 2),
            "mrp": mrp,
            "discount_percent": discount,
            "tax_rate": 5.0 if rate is not None else 0.0,
            "line_amount": amount,
            "line_total_amount": round(amount * 1.05, 2) if rate is not None else 0,
            "source_row_number": row_num,
        })

    def add_batch(spec: ProductSpec, received: date, expiry: date, qty: int) -> dict[str, Any]:
        counters["batch"] += 1
        code = f"B-{spec.product_id[-3:]}-{counters['batch']:04d}"
        batch = {
            "batch_record_id": f"{spec.product_id}-BATCH-{counters['batch']:04d}",
            "organization_id": ORG_ID,
            "product_id": spec.product_id,
            "batch_code": code,
            "manufacturing_date": (expiry - timedelta(days=900)).isoformat(),
            "expiry_raw": expiry.strftime("%m/%y"),
            "expiry_date": expiry.isoformat(),
            "expiry_date_precision": "month",
            "_expiry": expiry,
            "_remaining": qty,
        }
        rows["batches"].append({k: v for k, v in batch.items() if not k.startswith("_")})
        states[spec.product_id].append(batch)
        return batch

    prices: dict[str, tuple[float, float]] = {}
    for index, spec in enumerate(SPECS, start=1):
        rate = round(30.0 + index * 17.35, 2)
        mrp = round(rate * 1.25, 2)
        prices[spec.product_id] = (rate, mrp)
        rows["products"].append({
            "product_id": spec.product_id,
            "organization_id": ORG_ID,
            "source_product_code": f"SRC-{index:03d}",
            "product_name": spec.name,
            "manufacturer_name": spec.manufacturer,
            "hsn_code": "300490",
            "pack_description": "10'S",
            "quantity_unit": UNIT,
            "units_per_pack": 10,
            "product_match_status": "confirmed_synthetic",
        })
        expected = {
            "overstock_risk": ("overstock", "large recent purchase"),
            "expiry_risk": ("expiry", "large batch with near-term expiry"),
            "stockout_risk": ("stockout", "low stock relative to demand during pending lead time"),
        }.get(spec.scenario, ("no_forced_label", "background behavior; no fixed risk label asserted"))
        rows["scenario_labels_DO_NOT_USE_AS_INPUT"].append({
            "product_id": spec.product_id,
            "scenario": spec.scenario,
            "expected_signal": expected[0],
            "notes": expected[1],
        })

        opening_qty = 20 if spec.scenario == "overstock_risk" else 12 if spec.scenario == "expiry_risk" else max(15, int(math.ceil(spec.mean_demand * 30)))
        opening_batch = add_batch(spec, start, _expiry_after(as_of_date, 600), opening_qty)
        add_transaction(spec, opening_batch, start, "opening_balance", opening_qty)

    events_by_product: dict[str, dict[date, list[dict[str, Any]]]] = {}
    for spec in SPECS:
        grouped: dict[date, list[dict[str, Any]]] = {}
        for event in _receipts(spec, start, as_of_date):
            grouped.setdefault(event["date"], []).append(event)
        events_by_product[spec.product_id] = grouped

    for offset in range(365):
        current = start + timedelta(days=offset)
        for index, spec in enumerate(SPECS, start=1):
            rate, _ = prices[spec.product_id]
            for event_index, event in enumerate(events_by_product[spec.product_id].get(current, []), start=1):
                free_qty = 1 if (index + event_index + offset) % 5 == 0 else 0
                batch = add_batch(spec, current, event["expiry"], event["quantity"] + free_qty)
                add_transaction(spec, batch, current, "purchase_receipt", event["quantity"], free_qty, rate, event_index)
                counters["order"] += 1
                rows["replenishment_orders"].append({
                    "order_id": f"PO-{counters['order']:06d}",
                    "organization_id": ORG_ID,
                    "product_id": spec.product_id,
                    "order_date": (current - timedelta(days=event["lead_time"])).isoformat(),
                    "quantity_ordered": event["quantity"],
                    "quantity_unit": UNIT,
                    "expected_arrival_date": current.isoformat(),
                    "actual_arrival_date": current.isoformat(),
                    "order_status": "received",
                    "supplier_id": event["supplier"],
                })

            latent = _demand(spec, current, rng)
            unmet = latent
            eligible = sorted(
                (b for b in states[spec.product_id] if b["_expiry"] >= current),
                key=lambda b: b["_expiry"],
            )
            sales: list[tuple[dict[str, Any], int]] = []
            for batch in eligible:
                if unmet <= 0:
                    break
                sold = min(batch["_remaining"], unmet)
                if sold:
                    batch["_remaining"] -= sold
                    unmet -= sold
                    sales.append((batch, sold))
            fulfilled = latent - unmet
            for batch, sold in sales:
                sale_rate = round(prices[spec.product_id][1] * 0.85, 2)
                add_transaction(spec, batch, current, "retail_sale", sold, rate=sale_rate)
            rows["demand_truth_DO_NOT_USE_AS_INPUT"].append({
                "date": current.isoformat(),
                "product_id": spec.product_id,
                "latent_demand_units": latent,
                "fulfilled_units": fulfilled,
                "unmet_demand_units": unmet,
            })

    # One pending purchase order deliberately creates a lead-time risk scenario.
    pending_spec = next(s for s in SPECS if s.scenario == "stockout_risk")
    counters["order"] += 1
    rows["replenishment_orders"].append({
        "order_id": f"PO-{counters['order']:06d}",
        "organization_id": ORG_ID,
        "product_id": pending_spec.product_id,
        "order_date": (as_of_date - timedelta(days=1)).isoformat(),
        "quantity_ordered": 150,
        "quantity_unit": UNIT,
        "expected_arrival_date": (as_of_date + timedelta(days=9)).isoformat(),
        "actual_arrival_date": "",
        "order_status": "pending",
        "supplier_id": "SYN-SUP-003",
    })

    for spec in SPECS:
        for batch in states[spec.product_id]:
            counters["snapshot"] += 1
            rows["inventory_snapshots"].append({
                "snapshot_id": f"SNAP-{counters['snapshot']:06d}",
                "organization_id": ORG_ID,
                "snapshot_date": as_of_date.isoformat(),
                "product_id": spec.product_id,
                "batch_record_id": batch["batch_record_id"],
                "quantity_on_hand": batch["_remaining"],
                "quantity_unit": UNIT,
                "stock_basis": "simulated_physical",
            })

    outdir.mkdir(parents=True, exist_ok=True)
    outputs: dict[str, Path] = {}
    for name, fields in FIELDS.items():
        path = outdir / f"{name}.csv"
        _write_csv(path, rows[name], fields)
        outputs[name] = path
    return outputs


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path("data/synthetic"))
    parser.add_argument("--as-of-date", type=date.fromisoformat, default=DEFAULT_AS_OF)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    for name, path in generate_dataset(args.output_dir, args.as_of_date, args.seed).items():
        print(f"{name}: {path}")


if __name__ == "__main__":
    main()
