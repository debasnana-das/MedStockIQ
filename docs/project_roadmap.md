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

## Phase 2.5 — PostgreSQL persistence and workflow integration
- [x] Add SQLAlchemy models for run metadata, canonical tables, issues, and transformation traces.
- [x] Add the initial Alembic migration; verify migration execution in CI.
- [x] Add opt-in transactional persistence to normalization; keep preview-only as default.
- [x] Add bounded saved-run retrieval after authenticated tenant-membership checks.
- [x] Test transaction rollback, persisted previews, API workflow, SQLite migration, and PostgreSQL round-trip in CI.
- [x] Add authenticated user identity, organization membership, roles, and server-enforced tenant authorization.
- [x] Add access-controlled normalization-run retrieval and writer-only persistence.
- [ ] Add rate limiting, MFA/account recovery, token refresh/revocation strategy, audit logging, retention controls, and deployment security before production.

## Phase 3 — Data quality and deterministic analysis
- [x] Add deterministic findings from normalization issues, key-field coverage, possible duplicates, ignored columns, unknown stock basis, and suspicious tax/discount values.
- [x] Implement per-module readiness checks with explicit blockers and transparent sales-history guardrails.
- [ ] Expand date, unit and cross-document consistency rules as more source formats and authorized sanitized files become available.
- [x] Implement dated snapshot selection, duplicate/conflict/unit validation, basic snapshot-to-movement reconciliation, and batch-level expiry alerts.
- [x] Return explicit insufficient_data statuses and provisional-value explanations where evidence is insufficient.
- [x] Add a read-only cross-upload inventory-history ledger using conservative source-code/exact-attribute matching, with ambiguity/conflict reporting and tenant-scoped access.
- [ ] Validate matching with authorized sanitized exports and define a user-confirmed durable product/batch catalog before using cross-upload balances for risk estimates.

## Phase 4 — Forecasting and risk analysis
- [x] Add daily retail-sales aggregation and naïve/7-day seasonal baseline comparison.
- [x] Add a chronological 7-day holdout, MAE/RMSE/WAPE metrics, and 7-day baseline forecast.
- [x] Require explicit complete-history confirmation and date boundaries before zero-filling or forecasting.
- [x] Add expanding-window rolling-origin evaluation with at least two validation windows and a separate untouched final holdout.
- [x] Select a baseline using rolling-origin metrics, and report macro-averaged comparison metrics without pooling unlike product units.
- [ ] Evaluate forecast performance using an authorized, verified retail-sales history and add ongoing error monitoring.
- [ ] Evaluate alert usefulness and only then consider more complex models.
- [x] Provide basic batch expiry alerts with evidence, severity windows and explicit provisional MRP-exposure semantics.
- [ ] Build overstock findings and validated expiry-loss estimates with evidence, assumptions and uncertainty.
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
- [x] Baseline authentication, tenant isolation and role-based access.
- [ ] Production-grade rate limiting, MFA, audit logging, secret management and account recovery.
- [ ] Private file storage, encryption and retention/deletion controls.
- [ ] Audit logging and reproducible analysis versions.
- [ ] Deployment, backups, monitoring and operational documentation.
- [ ] Reassess RAG or integrations only when a real use case exists.

## Scope principle
Build the smallest end-to-end slice that can be tested. Prioritize CSV/Excel ingestion and overstock/expiry foundations; postpone complex deployment and advanced AI features until they are justified.
