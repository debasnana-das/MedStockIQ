# MedStockIQ Architecture

## Current target architecture

1. **Frontend**: upload workflow, schema confirmation, data-quality display, risk dashboard, reports, and analytical chat.
2. **API/backend**: FastAPI routes and orchestration.
3. **Ingestion**: CSV and Excel first; PDF parsing/OCR behind a parser interface.
4. **Schema intelligence**: profile columns and values, propose canonical mappings, and require user confirmation when ambiguous.
5. **Normalization and quality**: convert to canonical entities and produce explicit data-quality/readiness results.
6. **Analytics and ML**: deterministic inventory calculations and forecasting where enough dated demand exists.
7. **Risk engine**: overstock, expiry and later stock-out findings with evidence and limitations.
8. **Reporting/chat**: create readable reports; ground chat answers in stored analysis results.
9. **Persistence**: PostgreSQL for structured application/analysis state; private file storage for originals and intermediate artifacts.

## Request lifecycle

Upload → parse/profile → propose schema mappings → user confirms → normalize → validate → run only supported analyses → persist findings → report → chat over evidence.

## Separation of responsibilities

- LLM: propose/describe mappings and explain evidence-backed results.
- Deterministic Python code: parsing rules, validation, stock arithmetic, risk calculations and policy checks.
- ML/statistics: demand forecasts and uncertainty-aware predictions.
- PostgreSQL: organizations, metadata, confirmed mappings, normalized records, analysis runs, findings and recommendations.
- File storage: original uploads and generated artifacts, subject to retention controls.

## Architectural constraints

- Unknown source columns must not be silently discarded.
- User-confirmed mappings and transformations must be traceable.
- Each analysis module declares required inputs and returns insufficient_data when prerequisites are absent.
- Raw user data must not be committed to the repository.
- Do not treat synthetic data metrics as real-world validation.
- Continue hardening authentication and tenant isolation before using real organization data in a shared deployment. This implementation does not yet include rate limiting, MFA, account recovery, token refresh, dedicated secret management, comprehensive auditing, retention/deletion controls, or a full security review.

## Initial deployment shape

Start as a modular monolith: one FastAPI application with separate Python modules. Do not introduce microservices, RAG, queues, or a vector database until a verified requirement justifies them.


## Implemented persistence slice

The current backend can persist normalization runs when the caller explicitly submits `persist=true` to `POST /api/v1/normalize`. It stores the confirmed mapping and run options, summary, products, batches, source-document metadata, transactions, inventory snapshots, quality issues, and transformation traces in one database transaction. The initial schema is versioned with Alembic. Original uploaded bytes are deliberately not stored by this workflow.

Authentication and tenant-access baseline: accounts are stored with Argon2 password hashes; login returns a signed 30-minute bearer token; each protected request checks token signature/expiry and confirms the account remains active. Organizations and user memberships are stored explicitly with owner/admin/member/viewer roles. Registration does not grant organization access; the organization creator becomes owner and owners/admins grant membership to already-registered accounts. The profiling, schema, normalization, and run-review APIs require bearer authentication. Tenant-scoped operations verify membership on the server; only owner/admin/member roles may persist normalization runs, and run retrieval requires active tenant membership. A supplied organization ID is a selector, not proof of authorization.
