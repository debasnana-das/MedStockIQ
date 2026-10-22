# MedStockIQ local browser workspace

The initial frontend is a dependency-free HTML/CSS/JavaScript dashboard served by FastAPI on the same origin. It is intended for local development and synthetic/sanitized data review; it is not production-hardened.

## Run it

From the repository root, follow [development setup](../docs/development_setup.md). Once PostgreSQL migrations have completed and the API is running, open:

- Workspace: http://127.0.0.1:8000/
- API docs: http://127.0.0.1:8000/docs
- Process health: http://127.0.0.1:8000/health

Sign in with an account registered through MedStockIQ. Existing organizations and saved run summaries load through the authenticated API. For a new account, create a workspace first.

## Upload workflow

1. Choose the document type and CSV/XLSX file.
2. Profile the file and review suggested column mappings.
3. Confirm one explicit map-or-ignore decision per column and required date/unit/movement metadata.
4. Confirm source context and whether to persist normalized records.
5. Review saved run summaries, expiry analysis, demand baselines, inventory history and the rule-based overstock comparison.

The access token is held in page memory only and is not written to local storage. Upload bytes are sent to the API in memory and are not stored by the current normalization workflow.

## Scope limits

This is an MVP around the current API contracts. Demand forecasts are baseline models; stock targets are caller-provided; ambiguous units, stock basis and source mappings must not be guessed. Rate limiting, MFA, recovery, auditing, retention/deletion controls and a full security review remain outstanding. Do not expose this prototype publicly or use it as a clinical or autonomous purchasing system.
