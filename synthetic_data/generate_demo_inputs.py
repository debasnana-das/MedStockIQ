"""Generate reproducible pharmacy-style CSV uploads for the MedStockIQ API demo.

The generated upload files are fictional. Evaluation truth is generated in a temporary
directory by the base fixture generator and is never copied into the upload folder.
"""

from __future__ import annotations

import argparse
import csv
import json
import tempfile
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from synthetic_data.generate_dataset import DEFAULT_AS_OF, generate_dataset


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _write_csv(path: Path, fields: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _integer(value: Any) -> int:
    if value in (None, ""):
        return 0
    return int(round(float(value)))


def generate_demo_inputs(
    output_dir: Path | str,
    as_of_date: date = DEFAULT_AS_OF,
    seed: int = 42,
) -> dict[str, Path]:
    """Build source-shaped retail sales, inventory and pharmacy purchase-invoice CSVs."""
    outdir = Path(output_dir)
    outdir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="medstockiq-synthetic-internal-") as temporary:
        internal_files = generate_dataset(Path(temporary), as_of_date=as_of_date, seed=seed)
        products_rows = _read_csv(internal_files["products"])
        batch_rows = _read_csv(internal_files["batches"])
        transaction_rows = _read_csv(internal_files["transactions"])
        snapshot_rows = _read_csv(internal_files["inventory_snapshots"])

        products = {row["product_id"]: row for row in products_rows}
        batches = {row["batch_record_id"]: row for row in batch_rows}

        observed_sales: dict[tuple[str, str], int] = defaultdict(int)
        for transaction in transaction_rows:
            if transaction["transaction_type"] != "retail_sale":
                continue
            key = (transaction["transaction_date"], transaction["product_id"])
            observed_sales[key] += _integer(
                transaction["effective_quantity"] or transaction["quantity"]
            )

        first_date = as_of_date - timedelta(days=364)
        sales_fields = [
            "Sale Date", "SKU", "Product Name", "Manufacturer", "HSN Code",
            "Pack", "Quantity Sold",
        ]
        sales_upload: list[dict[str, Any]] = []
        for offset in range(365):
            day = first_date + timedelta(days=offset)
            for product in products_rows:
                sales_upload.append({
                    "Sale Date": day.isoformat(),
                    "SKU": product["source_product_code"],
                    "Product Name": product["product_name"],
                    "Manufacturer": product["manufacturer_name"],
                    "HSN Code": product["hsn_code"],
                    "Pack": product["pack_description"],
                    # The row is present even when sales are zero. This represents a
                    # complete daily export; it is not a claim about latent demand.
                    "Quantity Sold": observed_sales.get((day.isoformat(), product["product_id"]), 0),
                })

        inventory_fields = [
            "SKU", "Product Name", "Manufacturer", "HSN Code", "Pack",
            "Batch", "Expiry Date", "Manufacturing Date", "On Hand",
        ]
        inventory_upload: list[dict[str, Any]] = []
        for snapshot in snapshot_rows:
            product = products[snapshot["product_id"]]
            batch = batches[snapshot["batch_record_id"]]
            inventory_upload.append({
                "SKU": product["source_product_code"],
                "Product Name": product["product_name"],
                "Manufacturer": product["manufacturer_name"],
                "HSN Code": product["hsn_code"],
                "Pack": product["pack_description"],
                "Batch": batch["batch_code"],
                "Expiry Date": batch["expiry_date"],
                "Manufacturing Date": batch["manufacturing_date"],
                "On Hand": _integer(snapshot["quantity_on_hand"]),
            })

        purchase_fields = [
            "SL", "SKU", "Product Name", "Manufacturer", "HSN Code", "Pack",
            "Batch", "Expiry", "Manufacturing Date", "Invoice Date", "Invoice No",
            "Rate", "MRP", "QTY+FREE", "Disc%", "Amount", "GST%", "Total Amt",
        ]
        purchase_upload: list[dict[str, Any]] = []
        for transaction in transaction_rows:
            if transaction["transaction_type"] != "purchase_receipt":
                continue
            product = products[transaction["product_id"]]
            batch = batches[transaction["batch_record_id"]]
            purchase_upload.append({
                "SL": len(purchase_upload) + 1,
                "SKU": product["source_product_code"],
                "Product Name": product["product_name"],
                "Manufacturer": product["manufacturer_name"],
                "HSN Code": product["hsn_code"],
                "Pack": product["pack_description"],
                "Batch": batch["batch_code"],
                "Expiry": batch["expiry_raw"],
                "Manufacturing Date": batch["manufacturing_date"],
                "Invoice Date": transaction["transaction_date"],
                "Invoice No": transaction["document_id"],
                "Rate": transaction["unit_rate"],
                "MRP": transaction["mrp"],
                "QTY+FREE": (
                    f"{_integer(transaction['quantity'])}+"
                    f"{_integer(transaction['free_quantity'])}"
                ),
                "Disc%": transaction["discount_percent"],
                "Amount": transaction["line_amount"],
                "GST%": transaction["tax_rate"],
                "Total Amt": transaction["line_total_amount"],
            })

    output_files = {
        "retail_sales_upload": outdir / "retail_sales_upload.csv",
        "inventory_snapshot_upload": outdir / "inventory_snapshot_upload.csv",
        "purchase_invoice_upload": outdir / "purchase_invoice_upload.csv",
    }
    _write_csv(output_files["retail_sales_upload"], sales_fields, sales_upload)
    _write_csv(output_files["inventory_snapshot_upload"], inventory_fields, inventory_upload)
    _write_csv(output_files["purchase_invoice_upload"], purchase_fields, purchase_upload)

    manifest_path = outdir / "manifest.json"
    manifest = {
        "dataset_type": "fictional_pharmacy_api_demo",
        "seed": seed,
        "as_of_date": as_of_date.isoformat(),
        "sales_history_start_date": first_date.isoformat(),
        "sales_history_days": 365,
        "product_count": len(products_rows),
        "row_counts": {
            "retail_sales_upload.csv": len(sales_upload),
            "inventory_snapshot_upload.csv": len(inventory_upload),
            "purchase_invoice_upload.csv": len(purchase_upload),
        },
        "notes": [
            "All product, manufacturer, batch, invoice and quantity records are fictional.",
            "Retail sales includes an explicit row for every product and calendar day, including zero-sales days.",
            "The inventory snapshot is complete within this synthetic fixture and must be explicitly attested in the API options.",
            "Temporary model-evaluation truth and scenario labels are not copied into this upload directory.",
            "Observed sales can be lower than latent demand during simulated stock-outs.",
        ],
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    output_files["manifest"] = manifest_path
    return output_files


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path("data/demo-inputs"))
    parser.add_argument("--as-of-date", type=date.fromisoformat, default=DEFAULT_AS_OF)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    for name, path in generate_demo_inputs(args.output_dir, args.as_of_date, args.seed).items():
        print(f"{name}: {path}")


if __name__ == "__main__":
    main()
