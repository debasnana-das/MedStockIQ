# MedStockIQ

**AI-assisted inventory intelligence for pharmacies and stockists.**

MedStockIQ is an early-stage platform that profiles business files, suggests canonical field mappings, validates user-confirmed schemas, and transforms the files into common internal records before inventory analysis.

## Current working slice

- `GET /health` and `GET /health/database` — process and database health checks.
- `POST /api/v1/auth/register` and `POST /api/v1/auth/token` — create an account or exchange credentials for a short-lived bearer token.
- `POST /api/v1/organizations` — create a tenant; the authenticated creator becomes its owner.
- `GET /api/v1/organizations` — list only the caller's organization memberships.
- `POST /api/v1/organizations/{organization_id}/members` — owners/admins grant access to an existing account with a role.
- `DELETE /api/v1/organizations/{organization_id}/members/{user_id}` — revoke one user's membership without deleting the account.
- `POST /api/v1/profile` — profiles CSV/XLSX files up to 10 MB and 20,000 rows, suggesting canonical mappings without persisting uploads (bearer token required).
- `GET /api/v1/schema/fields` — lists canonical fields and required mapping metadata (bearer token required).
- `POST /api/v1/schema/confirm` — validates explicit mapping/ignore decisions for every profiled column (bearer token required).
- `POST /api/v1/normalize` — applies the confirmed mapping to a matching CSV/XLSX upload and returns canonical table counts and limited previews; saving requires a writer role in the selected organization.
- `normalize_dataframe` — reusable Python service returning full canonical Product, Batch, SourceDocument, Transaction and InventorySnapshot records, including transformation logs and data-quality issues.
- Synthetic data generator for fictional products, batches, transactions, snapshots, replenishment orders and separate test-only evaluation truth.

## Canonical normalization boundaries

Mappings are not guessed again during normalization. Quantity units, movement types, date formats, and composite quantity splitting must be supplied explicitly. Month/year expiry such as `03/30` requires the explicit convention `month_end` before normalization. Invalid values and conflicting batch/product attributes are surfaced as issues. The normalizer does not perform forecasts or risk scoring; the API persistence path is opt-in and requires an authenticated organization writer.

PDF/OCR, a visual confirmation UI, risk calculations, forecasting, reporting, chat, and production deployment remain future work.

## Authentication and tenant access

All API routes under `/api/v1` except registration and login require `Authorization: Bearer <access_token>`. Passwords are hashed with Argon2 and access tokens expire after 30 minutes. New accounts receive no organization membership automatically. A user creates an organization and becomes its owner; an owner/admin can add already-registered users as `admin`, `member`, or `viewer` (admins may only grant `member` or `viewer`). Only owners/admins can manage membership or revoke access. The final owner cannot be removed. Owners, admins, and members may persist normalization runs; viewers have read-only organization access.

Tenant IDs are checked against the authenticated account's active membership on the server. Run lookup requires membership and still uses the organization ID as a filter. The prototype does not yet include rate limiting, MFA, account recovery, refresh tokens, or a full production security review.


## Quick start

See [Development setup](docs/development_setup.md) and [the profiling, confirmation and normalization API guide](docs/profiling_api.md).

For the source-shaped, end-to-end API demo (profile, schema confirmation, persistence, expiry, demand baseline, inventory history and overstock review), follow [the synthetic demo workflow](docs/synthetic_demo.md).

Generate local synthetic data:

```powershell
python -m synthetic_data.generate_dataset --output-dir data/synthetic --seed 42
```

Files containing `DO_NOT_USE_AS_INPUT` are test oracles/labels and must never be included as model features. Synthetic data tests software behavior only and does not establish real-world predictive performance.

## Project structure

- docs/ — data contract, architecture, API notes and roadmap
- backend/app/ — FastAPI API and domain modules
- synthetic_data/ — reproducible synthetic fixtures generator
- ml/ — planned forecasting experiments/evaluation
- database/ — planned SQL schema and migrations
- frontend/ — planned user interface
- tests/ — automated tests

## Development principles

1. Require user confirmation for ambiguous mappings.
2. Preserve source values and transformation metadata.
3. Use deterministic, traceable transformations.
4. Report insufficient or invalid data instead of silently guessing.
5. Keep real business data, uploaded invoices, credentials and private datasets out of Git.
6. Do not claim real-world predictive performance until validated with authorized real data.

## Planned stack

Python, FastAPI, pandas, PostgreSQL, scikit-learn baselines, React (planned), and Docker for reproducible local development.

See [Data Contract v1](docs/data_contract_v1.md) for the canonical schema.


## PostgreSQL persistence workflow

Normalization stays preview-only by default. Requests require a bearer token. Submit `persist=true` and an organization ID in `options_json` only for an organization where the authenticated user has a writer role; the server checks membership rather than trusting the ID. Saves are transactional and uploaded file bytes are not stored. Run `docker compose up -d postgres` and `alembic upgrade head` for local setup. Saved previews are available through `GET /api/v1/normalization-runs/{run_id}?organization_id=...`, after the server verifies tenant membership. This is an early-stage security layer, not production certification; use synthetic or sanitized data and do not expose the API publicly.


## Data quality and analysis readiness

Normalization responses include a deterministic `quality_report` with grouped quality findings, key-field coverage, and independent readiness statuses for expiry monitoring, demand forecasting, overstock review, and stock-out review. It is persisted alongside saved normalization runs. The readiness layer reports missing evidence rather than guessing: invoices alone are not treated as retail sell-through or current stock, and stock-out analysis remains blocked until replenishment timing data is available. This step assesses readiness only; it does not yet calculate inventory risk or forecast demand. See [API and readiness details](docs/profiling_api.md).


## Inventory arithmetic and expiry monitoring

Normalization's `quality_report.inventory_analysis` contains current-position previews, stock-snapshot validation findings, snapshot-to-movement reconciliation results, and positive-stock batch expiry alerts for fixed 30/90/180-day windows. Current stock comes from dated inventory snapshots only—invoice quantities are never assumed to be on hand. The service omits ambiguous positions, marks stale/unknown stock basis as provisional, and labels any calculated MRP value as indicative retail-price exposure rather than purchase cost or expected expiry loss. Run-level alerts remain distinct from the new read-only cross-upload history view; the ledger derives conservative identities from source codes or exact product attributes and flags duplicate/conflicting snapshots rather than summing them.


## Demand forecasting baseline

MedStockIQ includes an initial time-series benchmark for confirmed retail-sale history: daily per-product aggregation, a chronological 7-day holdout, naive-last-value and seven-day seasonal-naive baselines, MAE/RMSE/WAPE metrics, and a 7-day daily baseline forecast. Zero-sales days are filled only when the caller explicitly confirms the extract is complete for a continuous date window. Forecasts are reported as `baseline_only` and are not production-validated; rolling-origin evaluation remains future work. See [demand baseline API guidance](docs/profiling_api.md).


## Rolling-origin forecast evaluation

The demand baseline now uses expanding-window rolling-origin evaluation with multiple seven-day validation windows before a separate final seven-day holdout. Per-product baseline selection is based on rolling-origin MAE (with RMSE/model-name tie-breaks), and the final holdout remains a separate report. At least 49 days of explicitly complete history are required. Aggregate metrics are macro-averaged across products rather than pooling quantities with different units/scales. Evaluation on authorized real sales history and ongoing error monitoring remain future work.


## Cross-upload inventory history ledger

`GET /api/v1/inventory-history?organization_id=...` returns a tenant-scoped, read-only timeline from saved stock snapshots across separate uploads, with optional `as_of_date`, `start_date`, and `end_date` query parameters. Product and batch matching are conservative; generated IDs are run-local and are not treated as global identities. Repeated same-date balances are counted once, conflicts are left unresolved, mixed units are not converted, and product-level snapshots are kept separate from batch-level snapshots. The endpoint caps a query at 20,000 matched snapshots and asks for a narrower date window rather than returning partial history. See [cross-upload history API guidance](docs/profiling_api.md).


## Overstock review

A read-only rule-based review is available at `GET /api/v1/overstock-review?organization_id=...&sales_run_id=...&target_days_of_supply=30`. It uses one saved retail-sales run with a confirmed complete 28-day-or-longer reporting window and inventory snapshots from runs explicitly attested as complete. Stock must be fresh, have a known basis, and use units compatible with retail sales. The target days of supply is caller-provided, not a presumed pharmacy policy. When demand or stock evidence is incomplete, ambiguous or zero, no excess estimate is made. This is a transparent baseline rule and does not account for incoming orders, lead times, seasonality or monetary loss; see [overstock review API guidance](docs/profiling_api.md).
