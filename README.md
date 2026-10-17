# MedStockIQ

**AI-assisted inventory intelligence for pharmacies and stockists.**

MedStockIQ is an early-stage platform that profiles business files, suggests canonical field mappings, validates user-confirmed schemas, and transforms the files into common internal records before inventory analysis.

## Current working slice

- `GET /health` — API process health check.
- `POST /api/v1/profile` — profiles CSV/XLSX files up to 10 MB and 20,000 rows, suggesting canonical mappings without persisting uploads.
- `GET /api/v1/schema/fields` — lists canonical fields and required mapping metadata.
- `POST /api/v1/schema/confirm` — validates explicit mapping/ignore decisions for every profiled column.
- `POST /api/v1/normalize` — applies the confirmed mapping to a matching CSV/XLSX upload and returns canonical table counts and limited previews without persistence.
- `normalize_dataframe` — reusable Python service returning full canonical Product, Batch, SourceDocument, Transaction and InventorySnapshot records, including transformation logs and data-quality issues.
- Synthetic data generator for fictional products, batches, transactions, snapshots, replenishment orders and separate test-only evaluation truth.

## Canonical normalization boundaries

Mappings are not guessed again during normalization. Quantity units, movement types, date formats, and composite quantity splitting must be supplied explicitly. Month/year expiry such as `03/30` requires the explicit convention `month_end` before normalization. Invalid values and conflicting batch/product attributes are surfaced as issues. This stage does not perform forecasts or risk scoring and does not persist input or output.

PDF/OCR, a visual confirmation UI, database persistence, risk calculations, forecasting, reporting, chat, authentication, tenant isolation and production deployment remain future work.

## Quick start

See [Development setup](docs/development_setup.md) and [the profiling, confirmation and normalization API guide](docs/profiling_api.md).

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

Normalization stays preview-only by default. Submit `persist=true` and an explicit organization ID in `options_json` to save the confirmed schema, normalized canonical tables, quality issues, and transformations in one database transaction. Uploaded file bytes are not stored. Run `docker compose up -d postgres` and `alembic upgrade head` for local setup. Saved previews are available through `GET /api/v1/normalization-runs/{run_id}?organization_id=...`. The organization parameter is a filter, not authentication; do not expose this prototype to untrusted clients until authentication and tenant authorization are implemented.
