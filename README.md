# MedStockIQ

**AI-assisted inventory intelligence for pharmacies and stockists.**

MedStockIQ is a data-driven platform in development that accepts business files, proposes a canonical schema, asks the user to validate ambiguous mappings, checks data quality, and then analyzes supported inventory risks.

## Current working slice

- `GET /health` — API process health check.
- `POST /api/v1/profile` — accepts CSV/XLSX files up to 10 MB, profiles up to 20,000 rows, and returns column/type/missingness/duplicate summaries plus candidate canonical mappings. The upload is processed in memory and is not persisted by this endpoint.
- `GET /api/v1/schema/fields` — returns the supported canonical field catalogue and the additional metadata needed for each field.
- `POST /api/v1/schema/confirm` — validates one explicit map/ignore decision for every profiled source column, flags conflicting target fields, and records whether a suggestion was confirmed, corrected, manually mapped, or ignored.
- A deterministic synthetic-data generator for fictional product, batch, transaction, inventory-snapshot, replenishment and separate test-only evaluation-truth CSV files.

The schema-confirmation API is currently stateless: it validates the column list and choices supplied by the client, but does not save mappings or uploaded files. It does not yet perform date parsing, composite-value splitting, canonical data normalization, database persistence or inventory analysis.

## Roadmap

- Build a user-facing schema-confirmation UI.
- Normalize confirmed mappings into canonical Product, Batch, SourceDocument, InventoryTransaction and InventorySnapshot records.
- Implement comprehensive data-quality/readiness checks.
- Add expiry, overstock and later stock-out analysis when required inputs are available.
- Add forecasting, recommendations, reports, conversational analytics, authentication, tenant isolation and production deployment.

## Quick start

See [Development setup](docs/development_setup.md) and the [profiling and schema-confirmation API guide](docs/profiling_api.md).

Generate a local synthetic dataset:

```powershell
python -m synthetic_data.generate_dataset --output-dir data/synthetic --seed 42
```

Files containing `DO_NOT_USE_AS_INPUT` are test oracles/labels and must never be included as model features. Synthetic data is for software testing and does not establish real-world predictive performance.

## Repository layout

- docs/ — data contract, architecture, API notes, and roadmap
- backend/app/ — FastAPI application and modular processing components
- synthetic_data/ — synthetic data generator and test scenarios
- ml/ — forecasting experiments and evaluation
- database/ — SQL schema and migrations
- frontend/ — planned user interface
- tests/ — unit and integration tests

## Development principles

1. Ask the user to confirm ambiguous column mappings.
2. Preserve source values and transformation metadata.
3. Keep calculations deterministic and forecasts reproducible.
4. Report insufficient data instead of inventing findings.
5. Keep real pharmacy/stockist data, credentials, and uploaded invoices out of Git.
6. Do not claim model performance on real operations until validated with authorized real-world data.

## Planned stack

- Python and FastAPI
- PostgreSQL
- Pandas initially; additional analytical tools only when justified
- scikit-learn and appropriate forecasting baselines
- React frontend, planned
- Docker for reproducible local development

See [Data Contract v1](docs/data_contract_v1.md) for canonical entities and field semantics.
