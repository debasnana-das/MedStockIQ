# Synthetic end-to-end API demo

This demo tests the existing API rather than bypassing it. It generates source-shaped CSV files, profiles each upload, submits explicit schema decisions, normalizes and saves each run, reads the saved inventory run, builds an inventory-history ledger, and calls the overstock-review endpoint.

All records are fictional. This workflow is for local development and software-behavior checks only; it does not establish real-world model performance. Do not point it at a production tenant or supply real pharmacy data.

## 1. Start the API

Follow [Development setup](development_setup.md): configure your private `.env`, start PostgreSQL, run migrations, and start the server.

```powershell
docker compose up -d postgres
alembic upgrade head
uvicorn app.main:app --reload --app-dir backend
```

Keep the server running in one terminal.

## 2. Configure a demo account

In a second PowerShell terminal, set the credentials for a local demo-only user. Use a strong throwaway password. Registration requires at least 12 characters.

```powershell
$env:MEDSTOCKIQ_DEMO_EMAIL = "medstockiq-demo@example.test"
$env:MEDSTOCKIQ_DEMO_PASSWORD = "use-a-unique-local-demo-password"
```

Run the workflow with `--register` the first time. If the account already exists, the script logs in using the supplied password.

```powershell
python -m synthetic_data.run_api_demo --register --seed 42 --as-of-date 2026-09-30
```

The script creates a new demo organization by default. The signed-in account must be a writer in any organization supplied via `--organization-id`.

## 3. Generated files

The generator writes only these source-shaped files to `data/demo-inputs/`:

- `retail_sales_upload.csv`: 365 days for eight fictional SKUs; every product/date appears, including zero-sales days.
- `inventory_snapshot_upload.csv`: batch-level on-hand quantities with expiry and manufacturing dates.
- `purchase_invoice_upload.csv`: pharmacy-style invoice columns, including `QTY+FREE`, rate, MRP, discount and tax.
- `manifest.json`: the seed, as-of date and row counts.

The low-level generator uses a temporary directory for its internal simulation and test oracles. Files named `DO_NOT_USE_AS_INPUT` are not copied into the demo upload directory or submitted to the API.

Reproduce the files independently without calling the API:

```powershell
python -m synthetic_data.generate_demo_inputs --output-dir data/demo-inputs --seed 42 --as-of-date 2026-09-30
```

## 4. What the API workflow exercises

For each CSV the runner executes:

1. `POST /api/v1/profile` to inspect columns and values.
2. `POST /api/v1/schema/confirm` with one explicit map/ignore decision per column and required date/unit/movement metadata.
3. `POST /api/v1/normalize` with persistence enabled and an organization-scoped writer identity.

It then:

- reads the saved inventory normalization run;
- prints the expiry alerts and demand-baseline readiness/forecast summary from normalization results;
- calls `GET /api/v1/inventory-history`;
- calls `GET /api/v1/overstock-review` using the single saved retail-sales run and a 30-day target supply period by default.

The complete inventory snapshot and physical-stock basis are explicit caller attestations in the inventory request options. The normalizer's default stock basis remains `unknown`; the system does not infer it from the column values. Never mark a real source as complete or physical/system unless the person responsible for that export has confirmed it.

## 5. Expected behavior and limitations

With the default seed and date, the workflow should report nonzero normalized sales rows, inventory snapshots, expiry alerts, baseline results, and at least one product above the configured stock target. The stock target is a user-supplied policy assumption, not an automatic recommendation. Output depends on the selected seed/date and current software rules.

Retail sales are the observed fulfilled quantities in the synthetic simulation. During simulated stock-outs, actual demand can exceed observed sales. The endpoint is a conservative arithmetic comparison against a selected sales window, not a demand-aware order recommendation. Purchase orders, supplier lead times, substitutions, returns, clinical suitability, and regulatory constraints are not incorporated into the current overstock review.

The two `DO_NOT_USE_AS_INPUT` oracle files from the internal generator are temporary evaluation artifacts. Never use the truth/label columns as model features. Synthetic tests do not validate model accuracy for real pharmacy data.

## 6. Local HTML report

After the API workflow completes, the runner writes a self-contained HTML report to `data/demo-report.html` by default. Open that file in a browser to review normalization run summaries, expiry alerts, baseline forecast metrics and daily predictions, inventory-history coverage, and overstock findings.

You can choose another local path with `--report-path`:

```powershell
python -m synthetic_data.run_api_demo --register --seed 42 --as-of-date 2026-09-30 --report-path data/reports/medstockiq-demo.html
```

The report uses only results returned by the local API, has no external assets or network calls, and escapes source-derived text before rendering. Keep generated reports local; do not commit business data or reports made from authorized real pharmacy records to Git.
