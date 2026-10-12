# MedStockIQ

**AI-assisted inventory intelligence for pharmacies and stockists.**

MedStockIQ is a planned data-driven platform that accepts business files, proposes a canonical schema, asks the user to validate ambiguous mappings, checks data quality, and analyzes inventory risks.

## Initial capabilities

- File ingestion for CSV and Excel, with PDF invoice extraction planned.
- Schema inference and user-confirmed mapping.
- Canonical product, batch, transaction, and inventory representations.
- Data-quality reporting.
- Overstock and expiry-risk analysis.
- Demand forecasting when sufficient dated history is available.
- Evidence-backed recommendations, downloadable reports, and conversational analytics.
- Stock-out analysis when inventory and replenishment data support it.

## Current status

Early development. The data contract and project scaffold are being established. Development will initially use synthetic data based on observed invoice structures. Synthetic results are for engineering tests only and do not establish real-world predictive performance.

## Repository layout

- docs/ — data contract, architecture, and roadmap
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

See docs/data_contract_v1.md for the canonical data contract.
