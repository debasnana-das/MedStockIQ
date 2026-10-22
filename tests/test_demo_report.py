from __future__ import annotations

from pathlib import Path

from synthetic_data.demo_report import write_demo_report


def test_write_demo_report_includes_demo_sections_and_escapes_source_text(tmp_path: Path) -> None:
    output = tmp_path / "demo-report.html"
    data = {
        "as_of_date": "2026-09-30",
        "seed": 42,
        "organization_id": "demo-org",
        "target_days_of_supply": 30,
        "row_counts": {
            "inventory_snapshot_upload.csv": 81,
            "purchase_invoice_upload.csv": 73,
            "retail_sales_upload.csv": 2920,
        },
        "runs": [
            {
                "label": "Retail sales",
                "source_rows": 2920,
                "summary": {
                    "product_count": 8,
                    "batch_count": 0,
                    "transaction_count": 2920,
                    "inventory_snapshot_count": 0,
                    "issue_count": 0,
                },
                "run_id": "synthetic-run-id",
            }
        ],
        "inventory_analysis": {
            "status": "ready_with_warnings",
            "summary": {"expiry_alert_count": 1},
            "expiry_alerts": [
                {
                    "alert_type": "expires_within_30_days",
                    "product_name": "<img src=x onerror=alert(1)>",
                    "source_product_code": "SRC-005",
                    "batch_code": "B-005-0075",
                    "expiry_date": "2026-10-31",
                    "quantity_on_hand": 139,
                    "quantity_unit": "pack",
                }
            ],
        },
        "forecasting": {
            "status": "ready",
            "series_count": 1,
            "forecasts": [
                {
                    "product_id": "product-5",
                    "product_name": "Synthetic Product 005",
                    "selected_baseline": "seasonal_naive_7_day",
                    "quantity_unit": "pack",
                    "predicted_total_quantity": 32,
                    "rolling_origin_mae": 2.1,
                    "rolling_origin_rmse": 2.8,
                    "rolling_origin_wape_percent": 12.5,
                    "final_holdout_mae": 2.3,
                    "forecast_status": "baseline_only",
                    "daily_forecast": [
                        {"date": "2026-10-01", "predicted_quantity": 4},
                    ],
                }
            ],
            "blockers": [],
            "warnings": [],
        },
        "inventory_history": {"status": "ready", "series": [{"product_id": "product-5"}]},
        "overstock": {
            "status": "ready_with_warnings",
            "summary": {
                "above_target_count": 1,
                "within_target_count": 0,
                "insufficient_data_count": 0,
            },
            "findings": [
                {
                    "status": "above_target",
                    "source_product_code": "SRC-005",
                    "product_name": "Synthetic Product 005",
                    "inventory_quantity": 139,
                    "quantity_unit": "pack",
                    "target_stock_quantity": 2,
                    "estimated_excess_quantity": 137,
                }
            ],
        },
    }

    assert write_demo_report(output, data) == output
    report = output.read_text(encoding="utf-8")

    assert "MedStockIQ Demo Report" in report
    assert "Upload and normalization summary" in report
    assert "Expiry review" in report
    assert "Demand baseline" in report
    assert "Inventory history" in report
    assert "Overstock review" in report
    assert "2,920" in report
    assert "&lt;img src=x onerror=alert(1)&gt;" in report
    assert "<img src=x onerror=alert(1)>" not in report
    assert "https://" not in report
