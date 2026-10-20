"""Run an end-to-end synthetic workflow against a locally running MedStockIQ API.

This script creates test uploads, confirms their source-column mapping explicitly,
persists runs to the selected organization, and calls the inventory/overstock endpoints.
Never point it at a production tenant or upload real pharmacy records.
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import httpx

from synthetic_data.generate_dataset import DEFAULT_AS_OF
from synthetic_data.generate_demo_inputs import generate_demo_inputs


COLUMN_RULES: dict[str, dict[str, dict[str, Any]]] = {
    "retail_sales_upload.csv": {
        "Sale Date": {"canonical_field": "transaction_date", "date_format": "YYYY-MM-DD"},
        "SKU": {"canonical_field": "source_product_code"},
        "Product Name": {"canonical_field": "product_name"},
        "Manufacturer": {"canonical_field": "manufacturer_name"},
        "HSN Code": {"canonical_field": "hsn_code"},
        "Pack": {"canonical_field": "pack_description"},
        "Quantity Sold": {
            "canonical_field": "quantity",
            "quantity_unit": "pack",
            "transaction_type": "retail_sale",
        },
    },
    "inventory_snapshot_upload.csv": {
        "SKU": {"canonical_field": "source_product_code"},
        "Product Name": {"canonical_field": "product_name"},
        "Manufacturer": {"canonical_field": "manufacturer_name"},
        "HSN Code": {"canonical_field": "hsn_code"},
        "Pack": {"canonical_field": "pack_description"},
        "Batch": {"canonical_field": "batch_code"},
        "Expiry Date": {"canonical_field": "expiry_date", "date_format": "YYYY-MM-DD"},
        "Manufacturing Date": {
            "canonical_field": "manufacturing_date",
            "date_format": "YYYY-MM-DD",
        },
        "On Hand": {"canonical_field": "quantity_on_hand", "quantity_unit": "pack"},
    },
    "purchase_invoice_upload.csv": {
        "SL": {"canonical_field": "source_row_number"},
        "SKU": {"canonical_field": "source_product_code"},
        "Product Name": {"canonical_field": "product_name"},
        "Manufacturer": {"canonical_field": "manufacturer_name"},
        "HSN Code": {"canonical_field": "hsn_code"},
        "Pack": {"canonical_field": "pack_description"},
        "Batch": {"canonical_field": "batch_code"},
        "Expiry": {
            "canonical_field": "expiry_date",
            "date_format": "MM/YY",
            "date_convention": "month_end",
        },
        "Manufacturing Date": {
            "canonical_field": "manufacturing_date",
            "date_format": "YYYY-MM-DD",
        },
        "Invoice Date": {"canonical_field": "document_date", "date_format": "YYYY-MM-DD"},
        "Invoice No": {"canonical_field": "document_number"},
        "Rate": {"canonical_field": "unit_rate"},
        "MRP": {"canonical_field": "mrp"},
        "QTY+FREE": {
            "canonical_field": "quantity",
            "quantity_unit": "pack",
            "transaction_type": "purchase_receipt",
            "transformation_rule": "split_quantity_and_free",
            "additional_canonical_fields": ["free_quantity"],
        },
        "Disc%": {"canonical_field": "discount_percent"},
        "Amount": {"canonical_field": "line_amount"},
        "GST%": {"canonical_field": "tax_rate"},
        "Total Amt": {"canonical_field": "line_total_amount"},
    },
}


def build_confirmation(profile: dict[str, Any], filename: str) -> dict[str, Any]:
    """Construct the reviewable mapping payload for these known synthetic fixtures."""
    rules = COLUMN_RULES.get(filename)
    if rules is None:
        raise ValueError(f"No explicit synthetic-demo mapping rules exist for {filename!r}.")
    profiled_columns = [
        {
            "column_index": int(column["column_index"]),
            "source_column": str(column["source_column"]),
        }
        for column in profile["columns"]
    ]
    mappings: list[dict[str, Any]] = []
    for column in profile["columns"]:
        source_name = str(column["source_column"])
        mapping = {
            "column_index": int(column["column_index"]),
            "source_column": source_name,
        }
        rule = rules.get(source_name)
        if rule is None:
            mapping["action"] = "ignore"
        else:
            mapping.update(rule)
            mapping["action"] = "map"
            suggested = (column.get("mapping") or {}).get("canonical_field")
            if suggested:
                mapping["proposed_canonical_field"] = suggested
        mappings.append(mapping)
    return {"profiled_columns": profiled_columns, "mappings": mappings}


def _require_success(response: Any, action: str) -> dict[str, Any]:
    try:
        body = response.json()
    except Exception:
        body = {"detail": response.text}
    if response.status_code < 200 or response.status_code >= 300:
        raise RuntimeError(
            f"{action} failed with HTTP {response.status_code}: "
            f"{json.dumps(body, ensure_ascii=False)[:1200]}"
        )
    return body


def profile_and_normalize(
    client: Any,
    headers: dict[str, str],
    file_path: Path,
    options: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Profile, explicitly confirm each source column, then normalize and persist."""
    file_bytes = file_path.read_bytes()
    files = {"file": (file_path.name, file_bytes, "text/csv")}
    profile = _require_success(
        client.post("/api/v1/profile", headers=headers, files=files),
        f"Profile {file_path.name}",
    )
    schema = build_confirmation(profile, file_path.name)
    confirmation = _require_success(
        client.post("/api/v1/schema/confirm", headers=headers, json=schema),
        f"Confirm schema for {file_path.name}",
    )
    if confirmation.get("schema_status") != "confirmed":
        raise RuntimeError(f"Schema confirmation did not succeed for {file_path.name}.")
    normalized = _require_success(
        client.post(
            "/api/v1/normalize",
            headers=headers,
            data={
                "confirmed_schema_json": json.dumps(schema, separators=(",", ":")),
                "options_json": json.dumps(options, separators=(",", ":")),
                "persist": "true",
            },
            files={"file": (file_path.name, file_bytes, "text/csv")},
        ),
        f"Normalize {file_path.name}",
    )
    if not normalized.get("normalization_run_id"):
        raise RuntimeError(f"API did not persist a run for {file_path.name}.")
    return profile, confirmation, normalized


def _print_run(label: str, profile: dict[str, Any], run: dict[str, Any]) -> None:
    summary = run.get("summary") or {}
    print(
        f"{label}: {profile.get('row_count_profiled')} source rows -> "
        f"{summary.get('product_count', 0)} products, "
        f"{summary.get('batch_count', 0)} batches, "
        f"{summary.get('transaction_count', 0)} transactions, "
        f"{summary.get('inventory_snapshot_count', 0)} snapshots; "
        f"issues={summary.get('issue_count', 0)}; run={run['normalization_run_id']}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--output-dir", type=Path, default=Path("data/demo-inputs"))
    parser.add_argument("--as-of-date", type=date.fromisoformat, default=DEFAULT_AS_OF)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--target-days-of-supply", type=float, default=30)
    parser.add_argument("--email", default=os.getenv("MEDSTOCKIQ_DEMO_EMAIL"))
    parser.add_argument("--password", default=os.getenv("MEDSTOCKIQ_DEMO_PASSWORD"))
    parser.add_argument("--register", action="store_true", help="Register this demo account if it does not exist.")
    parser.add_argument(
        "--organization-id",
        help="Use an existing organization you belong to; otherwise a new demo organization is created.",
    )
    args = parser.parse_args()
    if not args.email or not args.password:
        parser.error(
            "Set MEDSTOCKIQ_DEMO_EMAIL and MEDSTOCKIQ_DEMO_PASSWORD, or pass --email and --password."
        )
    if len(args.password) < 12:
        parser.error("The API requires a password of at least 12 characters.")

    outputs = generate_demo_inputs(args.output_dir, args.as_of_date, args.seed)
    print(f"Synthetic inputs generated in {args.output_dir.resolve()}")
    print(f"Rows: {json.loads(outputs['manifest'].read_text(encoding='utf-8'))['row_counts']}")

    try:
        with httpx.Client(base_url=args.base_url.rstrip("/"), timeout=120) as client:
            _require_success(client.get("/health"), "Check API health")
            if args.register:
                registration = client.post(
                    "/api/v1/auth/register",
                    json={"email": args.email, "password": args.password},
                )
                if registration.status_code == 409:
                    auth = _require_success(
                        client.post(
                            "/api/v1/auth/token",
                            json={"email": args.email, "password": args.password},
                        ),
                        "Log in to existing demo account",
                    )
                else:
                    auth = _require_success(registration, "Register demo account")
            else:
                auth = _require_success(
                    client.post(
                        "/api/v1/auth/token",
                        json={"email": args.email, "password": args.password},
                    ),
                    "Log in",
                )
            headers = {"Authorization": f"Bearer {auth['access_token']}"}

            if args.organization_id:
                organization_id = args.organization_id
            else:
                org = _require_success(
                    client.post(
                        "/api/v1/organizations",
                        headers=headers,
                        json={
                            "display_name": (
                                f"MedStockIQ synthetic demo {args.as_of_date.isoformat()} "
                                f"seed-{args.seed}-{secrets.token_hex(3)}"
                            )
                        },
                    ),
                    "Create demo organization",
                )
                organization_id = org["organization_id"]
            print(f"Organization: {organization_id}")

            first_date = args.as_of_date - timedelta(days=364)
            purchase_profile, _purchase_confirm, purchase_run = profile_and_normalize(
                client,
                headers,
                outputs["purchase_invoice_upload"],
                {
                    "organization_id": organization_id,
                    "document_type": "purchase_invoice",
                    "counterparty_id": "SYN-SUPPLIER-001",
                    "currency_code": "INR",
                },
            )
            inventory_profile, _inventory_confirm, inventory_run = profile_and_normalize(
                client,
                headers,
                outputs["inventory_snapshot_upload"],
                {
                    "organization_id": organization_id,
                    "document_type": "inventory_report",
                    "snapshot_date": args.as_of_date.isoformat(),
                    "inventory_snapshot_complete": True,
                    # Explicit demo attestation; unknown remains the production default.
                    "inventory_stock_basis": "physical",
                    "currency_code": "INR",
                },
            )
            sales_profile, _sales_confirm, sales_run = profile_and_normalize(
                client,
                headers,
                outputs["retail_sales_upload"],
                {
                    "organization_id": organization_id,
                    "document_type": "retail_sales",
                    "sales_history_complete": True,
                    "sales_history_start_date": first_date.isoformat(),
                    "sales_history_end_date": args.as_of_date.isoformat(),
                },
            )
            _print_run("Purchase invoice", purchase_profile, purchase_run)
            _print_run("Inventory snapshot", inventory_profile, inventory_run)
            _print_run("Retail sales", sales_profile, sales_run)

            inventory_analysis = (
                (inventory_run.get("quality_report") or {}).get("inventory_analysis") or {}
            )
            inventory_summary = inventory_analysis.get("summary") or {}
            expiry_alerts = inventory_analysis.get("expiry_alerts") or []
            print(
                "Expiry review: "
                f"{inventory_summary.get('expiry_alert_count', 0)} alert(s), "
                f"status={inventory_analysis.get('status', 'unknown')}"
            )
            for alert in expiry_alerts[:5]:
                print(
                    f"  - {alert.get('alert_type')}: {alert.get('product_name')} / "
                    f"{alert.get('batch_code')} expires {alert.get('expiry_date')} "
                    f"(on hand {alert.get('quantity_on_hand')} {alert.get('quantity_unit')})"
                )

            forecast = (
                (sales_run.get("quality_report") or {}).get("forecasting_baseline") or {}
            )
            print(
                "Demand baseline: "
                f"status={forecast.get('status', 'unknown')}, "
                f"series={forecast.get('series_count', 0)}, "
                f"7-day forecasts={len(forecast.get('forecasts') or [])}"
            )
            for blocker in (forecast.get("blockers") or [])[:3]:
                print(f"  - blocked: {blocker}")

            _require_success(
                client.get(
                    "/api/v1/normalization-runs/" + inventory_run["normalization_run_id"],
                    headers=headers,
                    params={"organization_id": organization_id},
                ),
                "Read saved inventory run",
            )
            history = _require_success(
                client.get(
                    "/api/v1/inventory-history",
                    headers=headers,
                    params={"organization_id": organization_id, "as_of_date": args.as_of_date.isoformat()},
                ),
                "Review inventory history",
            )
            print(
                "Inventory history: "
                f"status={history.get('status', 'unknown')}, "
                f"series={len(history.get('series') or [])}"
            )

            overstock = _require_success(
                client.get(
                    "/api/v1/overstock-review",
                    headers=headers,
                    params={
                        "organization_id": organization_id,
                        "sales_run_id": sales_run["normalization_run_id"],
                        "as_of_date": args.as_of_date.isoformat(),
                        "target_days_of_supply": args.target_days_of_supply,
                    },
                ),
                "Run overstock review",
            )
            overstock_summary = overstock.get("summary") or {}
            print(
                "Overstock review: "
                f"status={overstock.get('status', 'unknown')}, "
                f"above_target={overstock_summary.get('above_target_count', 0)}, "
                f"within_target={overstock_summary.get('within_target_count', 0)}, "
                f"insufficient_data={overstock_summary.get('insufficient_data_count', 0)}"
            )
            for finding in (overstock.get("findings") or [])[:5]:
                if finding.get("status") == "above_target":
                    print(
                        f"  - {finding.get('source_product_code')} {finding.get('product_name')}: "
                        f"on hand={finding.get('inventory_quantity')} {finding.get('quantity_unit')}, "
                        f"target={finding.get('target_stock_quantity')}, "
                        f"estimated excess={finding.get('estimated_excess_quantity')}"
                    )

            print("\nDemo finished. All records are fictional; results test software behavior only.")
            print(f"Saved normalization run IDs: purchase={purchase_run['normalization_run_id']}, "
                  f"inventory={inventory_run['normalization_run_id']}, sales={sales_run['normalization_run_id']}")
            return 0
    except (httpx.HTTPError, RuntimeError, ValueError) as exc:
        print(f"Demo failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
