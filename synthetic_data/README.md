# Synthetic data generator

Generate a reproducible, internally reconcilable synthetic dataset for testing MedStockIQ's ingestion and analysis pipeline.

## Generate a dataset

From the repository root:

```powershell
python -m synthetic_data.generate_dataset --output-dir data/synthetic --seed 42
```

The default as-of date is fixed (`2026-09-30`) so repeated runs are comparable. Override it with `--as-of-date YYYY-MM-DD` when testing another analysis date.

## Files generated

- `products.csv` — synthetic product master.
- `batches.csv` — batch identifiers and month/year-style expiry values.
- `transactions.csv` — opening balances, purchase receipts and fulfilled retail sales.
- `inventory_snapshots.csv` — end-date batch stock that reconciles to the movement ledger.
- `replenishment_orders.csv` — received orders and one pending order for testing.
- `demand_truth_DO_NOT_USE_AS_INPUT.csv` — latent demand, fulfilled demand and unmet demand for test evaluation only.
- `scenario_labels_DO_NOT_USE_AS_INPUT.csv` — labels for intentionally constructed scenarios.

## Important limitations

- Product names, organizations, suppliers and transactions are fictional.
- Scenarios include balanced, fast/slow-moving, overstock, near-expiry, stock-out-risk, seasonal and intermittent demand.
- Files with `DO_NOT_USE_AS_INPUT` in their name contain evaluation truth. They must never be supplied to a model as input or used as model features.
- Synthetic data validates software behavior and arithmetic only. It is not evidence of forecast accuracy or representativeness for real pharmacies/distributors.
- Quantities use the simplified `pack` unit; real unit conversions and free-quantity conventions must be confirmed with the business.
