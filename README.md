# MedStockIQ

**AI-assisted inventory intelligence for pharmacies and stockists.**

MedStockIQ is a planned data-driven platform that accepts business files, proposes a canonical schema, asks the user to validate ambiguous mappings, checks data quality, and analyzes inventory risks.

## Initial capabilities

- CSV/XLSX file profiling and schema-mapping suggestions (first backend slice implemented).
- Schema inference and user-confirmed mapping (confirmation UI is still to be built).
- Canonical product, batch, transaction, and inventory representations.
- Data-quality reporting.
- Overstock and expiry-risk analysis.
- Demand forecasting when sufficient dated history is available.
- Evidence-backed recommendations, downloadable reports, and conversational analytics.
- Stock-out analysis when inventory and replenishment data support it.

## Current development status

The project is in early development. The current working slice includes:

- `GET /health` — API process health check.
- `POST /api/v1/profile` — accepts CSV/XLSX files up to 10 MB, profiles up to 20,000 rows, and returns column/type/missingness/duplicate summaries plus candidate canonical mappings. The upload is processed in memory and is not persisted by this endpoint.
- A deterministic synthetic-data generator that writes product, batch, transaction, inventory snapshot, replenishment-order, and separate testing-only evaluation-truth CSV files.

PDF invoice extraction, the mapping-confirmation UI, canonical normalization, database persistence, risk calculations, forecasting, reporting, chat, authentication, and production deployment remain future implementation work.

Synthetic results are for engineering tests only and do not establish real-world predictive performance.

## Quick start

See [Development setup](docs/development_setup.md) and the [profiling API guide](docs/profiling_api.md).

Generate a local synthetic dataset:

```powershell
python -m synthetic_data.generate_dataset --output-dir data/synthetic --seed 42
```

Files containing `DO_NOT_USE_AS_INPUT` are test oracles/labels and must never be included as model features.

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
2. Preserve source values and record transformations.
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

See [Data Contract v1](docs/data_contract_v1.md) for the canonical data contract.
