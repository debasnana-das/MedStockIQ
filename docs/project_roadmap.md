# MedStockIQ Development Roadmap

## Phase 0 — Contract and scaffold
- [x] Draft canonical data contract based on observed invoice structures.
- [ ] Review unresolved fields and definitions as businesses confirm data availability.
- [ ] Set up repository, Python package, tests and formatting/linting.
- [ ] Keep confidential files and credentials out of Git.

## Phase 1 — Synthetic data and profiling
- [ ] Generate synthetic products, batches, transactions and inventory snapshots.
- [ ] Include normal, overstock, near-expiry, return and stock-out scenarios.
- [ ] Implement CSV/Excel file profiling.
- [ ] Report column names, inferred types, missing values, duplicates and sample formats.

## Phase 2 — Schema mapping and normalization
- [ ] Build candidate mappings from source columns to canonical fields.
- [ ] Require explicit confirmation for ambiguous mappings.
- [x] Implement initial normalization for products, batches, source documents, transactions and stock snapshots.
- [ ] Preserve unmapped columns and transformation metadata.
- [x] Add baseline regression tests for both observed invoice layouts; additional label variations and field semantics remain to be validated.

## Phase 3 — Data quality and deterministic analysis
- [ ] Implement date, quantity, unit, duplicate and monetary validation.
- [ ] Implement data-readiness checks for each risk module.
- [ ] Implement inventory arithmetic and basic expiry-date alerts.
- [ ] Return explicit insufficient_data statuses where appropriate.

## Phase 4 — Forecasting and risk analysis
- [ ] Create simple time-series baselines before selecting advanced models.
- [ ] Use chronological train/validation/test splits to avoid leakage.
- [ ] Evaluate forecast error and alert usefulness.
- [ ] Build overstock/expiry findings with evidence, assumptions and uncertainty.
- [ ] Add stock-out only when current inventory and replenishment data are available.

## Phase 5 — Product interface
- [ ] Add upload and schema confirmation screens.
- [ ] Add data-quality and analysis dashboards.
- [ ] Generate downloadable, traceable reports.
- [ ] Add chat grounded in actual analysis findings.
- [ ] Test empty, malformed, ambiguous and unsupported uploads.

## Phase 6 — Real data and pilot
- [ ] Obtain appropriate permission for any business data used.
- [ ] Audit real-data schema and quality before modelling.
- [ ] Validate forecasts against held-out later periods.
- [ ] Pilot in a controlled setting and collect user feedback.
- [ ] Document limitations and measured outcomes honestly.

## Phase 7 — Production hardening
- [ ] Authentication, tenant isolation and role-based access.
- [ ] Private file storage, encryption and retention/deletion controls.
- [ ] Audit logging and reproducible analysis versions.
- [ ] Deployment, backups, monitoring and operational documentation.
- [ ] Reassess RAG or integrations only when a real use case exists.

## Scope principle
Build the smallest end-to-end slice that can be tested. Prioritize CSV/Excel ingestion and overstock/expiry foundations; postpone complex deployment and advanced AI features until they are justified.
