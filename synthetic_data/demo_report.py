"""Create a safe, self-contained HTML report for the local synthetic demo."""

from __future__ import annotations

import json
from html import escape
from pathlib import Path
from typing import Any


def _display(value: Any) -> str:
    """Format API values for display without treating source text as markup."""
    if value is None or value == "":
        return "—"
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, int):
        return f"{value:,}"
    if isinstance(value, float):
        rendered = f"{value:,.3f}".rstrip("0").rstrip(".")
        return rendered
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def _table(headers: list[str], rows: list[list[Any]], empty_message: str) -> str:
    """Render a compact accessible table; all dynamic values are HTML-escaped."""
    if not rows:
        return f'<p class="muted">{escape(empty_message)}</p>'
    header_html = "".join(f"<th scope=\"col\">{escape(label)}</th>" for label in headers)
    rows_html = "".join(
        "<tr>" + "".join(f"<td>{escape(_display(value))}</td>" for value in row) + "</tr>"
        for row in rows
    )
    return (
        '<div class="table-wrap"><table><thead><tr>'
        + header_html
        + "</tr></thead><tbody>"
        + rows_html
        + "</tbody></table></div>"
    )


def _status(value: Any) -> str:
    return f'<span class="status">{escape(_display(value))}</span>'


def write_demo_report(output_path: Path, data: dict[str, Any]) -> Path:
    """Write a self-contained HTML report using only data returned by the local API.

    The file is intended for local demo review. It includes no external assets,
    JavaScript, network calls, or data uploads.
    """
    inventory = data.get("inventory_analysis") or {}
    expiry_alerts = inventory.get("expiry_alerts") or []
    forecasting = data.get("forecasting") or {}
    forecasts = forecasting.get("forecasts") or []
    history = data.get("inventory_history") or {}
    overstock = data.get("overstock") or {}
    overstock_summary = overstock.get("summary") or {}
    findings = overstock.get("findings") or []
    runs = data.get("runs") or []
    row_counts = data.get("row_counts") or {}

    total_source_rows = sum(
        count for count in row_counts.values() if isinstance(count, (int, float))
    )
    above_target_count = overstock_summary.get("above_target_count", 0)

    run_rows = [
        [
            run.get("label"),
            run.get("source_rows"),
            (run.get("summary") or {}).get("product_count", 0),
            (run.get("summary") or {}).get("batch_count", 0),
            (run.get("summary") or {}).get("transaction_count", 0),
            (run.get("summary") or {}).get("inventory_snapshot_count", 0),
            (run.get("summary") or {}).get("issue_count", 0),
            run.get("run_id"),
        ]
        for run in runs
    ]

    expiry_rows = [
        [
            item.get("alert_type"),
            item.get("product_name"),
            item.get("source_product_code"),
            item.get("batch_code"),
            item.get("expiry_date"),
            item.get("quantity_on_hand"),
            item.get("quantity_unit"),
        ]
        for item in expiry_alerts
    ]

    forecast_rows = [
        [
            item.get("product_name") or item.get("product_id"),
            item.get("selected_baseline"),
            item.get("quantity_unit"),
            item.get("predicted_total_quantity"),
            item.get("rolling_origin_mae"),
            item.get("rolling_origin_rmse"),
            item.get("rolling_origin_wape_percent"),
            item.get("final_holdout_mae"),
            item.get("forecast_status"),
        ]
        for item in forecasts
    ]

    daily_forecast_rows = [
        [
            item.get("product_name") or item.get("product_id"),
            day.get("date"),
            day.get("predicted_quantity"),
            item.get("quantity_unit"),
        ]
        for item in forecasts
        for day in (item.get("daily_forecast") or [])
    ]

    overstock_rows = [
        [
            item.get("status"),
            item.get("source_product_code"),
            item.get("product_name"),
            item.get("inventory_quantity"),
            item.get("quantity_unit"),
            item.get("target_stock_quantity"),
            item.get("estimated_excess_quantity"),
        ]
        for item in findings
    ]

    blockers = forecasting.get("blockers") or []
    forecast_warnings = forecasting.get("warnings") or []
    notes: list[str] = [
        "All records in this report are fictional. This demo verifies software workflow only; it does not establish real-world forecast accuracy.",
        (
            "Overstock is a rule-based comparison against the selected "
            f"{_display(data.get('target_days_of_supply'))}-day target. It does not account for "
            "purchase orders, supplier lead times, seasonality, substitutions, or expiry-aware allocation."
        ),
        (
            "Expiry flags use the inventory analysis as-of date "
            f"{_display(inventory.get('as_of_date') or data.get('as_of_date'))}; interpret alert windows relative to that date."
        ),
    ]

    meta = (
        f"As-of date: {_display(data.get('as_of_date'))} · "
        f"Seed: {_display(data.get('seed'))} · "
        f"Organization: {_display(data.get('organization_id'))}"
    )

    html = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>MedStockIQ — Local Demo Report</title>
<style>
:root {{ color-scheme: light; --ink: #172b3a; --muted: #5f7180; --line: #dce4ea; --paper: #ffffff; --wash: #f3f6f8; --accent: #176b57; }}
* {{ box-sizing: border-box; }}
body {{ margin: 0; background: var(--wash); color: var(--ink); font: 15px/1.55 system-ui, -apple-system, "Segoe UI", sans-serif; }}
main {{ max-width: 1180px; margin: 0 auto; padding: 28px 20px 48px; }}
header {{ padding: 26px; border-radius: 18px; background: var(--paper); border: 1px solid var(--line); }}
.eyebrow {{ color: var(--accent); font-weight: 750; text-transform: uppercase; letter-spacing: .09em; font-size: 12px; }}
h1 {{ margin: 6px 0 8px; font-size: clamp(28px, 4vw, 40px); line-height: 1.12; }}
h2 {{ margin: 0 0 16px; font-size: 21px; }}
h3 {{ margin: 22px 0 10px; font-size: 16px; }}
.meta, .muted {{ color: var(--muted); overflow-wrap: anywhere; }}
.notice {{ margin-top: 16px; padding: 12px 14px; border-left: 4px solid var(--accent); background: #edf6f2; border-radius: 6px; }}
.kpis {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(175px, 1fr)); gap: 12px; margin: 16px 0; }}
.kpi, section {{ background: var(--paper); border: 1px solid var(--line); border-radius: 14px; }}
.kpi {{ padding: 17px; }}
.kpi strong {{ display: block; font-size: 27px; line-height: 1.15; margin-bottom: 5px; }}
.kpi span {{ color: var(--muted); font-size: 13px; }}
section {{ margin-top: 16px; padding: 22px; }}
.status {{ display: inline-block; padding: 2px 9px; border: 1px solid var(--line); border-radius: 999px; background: #f7f9fa; font-size: 12px; }}
.table-wrap {{ overflow-x: auto; }}
table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
th, td {{ text-align: left; vertical-align: top; border-bottom: 1px solid var(--line); padding: 10px 11px; overflow-wrap: anywhere; }}
th {{ background: #f6f8f9; color: #405463; font-size: 12px; white-space: nowrap; }}
tbody tr:last-child td {{ border-bottom: 0; }}
details {{ margin-top: 18px; }}
summary {{ cursor: pointer; font-weight: 700; }}
.notes {{ padding-left: 20px; }}
.notes li {{ margin: 8px 0; }}
footer {{ color: var(--muted); text-align: center; font-size: 12px; padding: 22px 0 0; }}
@page {{ size: A4 landscape; margin: 10mm; }}
@media print {{
  body {{ background: white; font-size: 10px; }}
  main {{ max-width: none; padding: 0; }}
  .table-wrap {{ overflow: visible; }}
  table {{ width: 100%; table-layout: fixed; font-size: 8px; }}
  th, td {{ padding: 4px 5px; white-space: normal; overflow-wrap: anywhere; }}
  th {{ font-size: 8px; }}
  section, header, .kpi {{ break-inside: avoid; box-shadow: none; }}
  tr {{ break-inside: avoid; }}
  details {{ display: none; }}
}}
</style>
</head>
<body>
<main>
<header>
  <div class="eyebrow">Local synthetic run · Software behavior check</div>
  <h1>MedStockIQ Demo Report</h1>
  <p class="meta">{escape(meta)}</p>
  <div class="notice">This report was generated from the local API demo. It contains fictional records and is not an operational purchasing or clinical recommendation.</div>
</header>
<div class="kpis">
  <div class="kpi"><strong>{escape(_display(total_source_rows))}</strong><span>Source rows processed</span></div>
  <div class="kpi"><strong>{escape(_display(len(forecasts)))}</strong><span>Product demand baselines</span></div>
  <div class="kpi"><strong>{escape(_display(len(expiry_alerts)))}</strong><span>Expiry alert(s) as of inventory report date</span></div>
  <div class="kpi"><strong>{escape(_display(above_target_count))}</strong><span>Products above target supply</span></div>
</div>

<section>
  <h2>Upload and normalization summary</h2>
  <p class="muted">Each source is profiled, explicitly mapped, normalized, and persisted as a separate run.</p>
  {_table(["Input", "Source rows", "Products", "Batches", "Transactions", "Snapshots", "Issues", "Saved run ID"], run_rows, "No normalization-run summaries were supplied.")}
</section>

<section>
  <h2>Expiry review</h2>
  <p>Analysis status: {_status(inventory.get("status", "unknown"))} · Report date: <strong>{escape(_display(inventory.get("as_of_date") or data.get("as_of_date")))}</strong> · Alert count: <strong>{escape(_display((inventory.get("summary") or {}).get("expiry_alert_count", len(expiry_alerts))))}</strong></p>
  {_table(["Alert", "Product", "SKU", "Batch", "Expiry date", "On hand", "Unit"], expiry_rows, "No expiry alerts were returned for this synthetic run.")}
</section>

<section>
  <h2>Demand baseline</h2>
  <p>Status: {_status(forecasting.get("status", "unknown"))} · Product series: <strong>{escape(_display(forecasting.get("series_count", 0)))}</strong> · Forecast rows: <strong>{escape(_display(len(forecasts)))}</strong></p>
  <p class="muted">The model is a baseline benchmark using the declared complete retail-sales history. MAE/RMSE/WAPE are historical evaluation metrics, not guarantees of future accuracy.</p>
  {_table(["Product", "Selected baseline", "Unit", "Next 7-day total", "Rolling MAE", "Rolling RMSE", "Rolling WAPE %", "Holdout MAE", "Scope"], forecast_rows, "No product forecasts were produced.")}
  <details>
    <summary>View daily 7-day forecast values</summary>
    {_table(["Product", "Date", "Predicted quantity", "Unit"], daily_forecast_rows, "No daily forecast values are available.")}
  </details>
  {"<h3>Forecast blockers</h3><ul>" + "".join(f"<li>{escape(_display(item))}</li>" for item in blockers) + "</ul>" if blockers else ""}
  {"<h3>Forecast warnings</h3><ul>" + "".join(f"<li>{escape(_display(item))}</li>" for item in forecast_warnings) + "</ul>" if forecast_warnings else ""}
</section>

<section>
  <h2>Inventory history</h2>
  <p>Status: {_status(history.get("status", "unknown"))} · Inventory series returned: <strong>{escape(_display(len(history.get("series") or [])))}</strong></p>
  <p class="muted">History is a conservative view of saved stock snapshots. It does not infer missing balances or convert unlike units.</p>
</section>

<section>
  <h2>Overstock review</h2>
  <p>Status: {_status(overstock.get("status", "unknown"))} · Above target: <strong>{escape(_display(overstock_summary.get("above_target_count", 0)))}</strong> · Within target: <strong>{escape(_display(overstock_summary.get("within_target_count", 0)))}</strong> · Insufficient data: <strong>{escape(_display(overstock_summary.get("insufficient_data_count", 0)))}</strong></p>
  {_table(["Status", "SKU", "Product", "On hand", "Unit", "Target stock", "Estimated excess"], overstock_rows, "No overstock findings were returned.")}
</section>

<section>
  <h2>Scope and interpretation</h2>
  <ul class="notes">{"".join(f"<li>{escape(note)}</li>" for note in notes)}</ul>
</section>
<footer>MedStockIQ · Generated locally · No external assets or network calls</footer>
</main>
</body>
</html>
"""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")
    return output_path
