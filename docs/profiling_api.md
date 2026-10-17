# Profiling, schema confirmation, and normalization APIs

All `/api/v1` endpoints except account registration and login require `Authorization: Bearer <access_token>`. These endpoints are early-stage prototypes; use synthetic or sanitized data and do not expose the service publicly.

## 0. Register, log in, and create an organization

`POST /api/v1/auth/register` accepts JSON with an email and a 12–128 character password. Email is normalized to lowercase; duplicate accounts return `409`. Registration never grants membership in an organization. `POST /api/v1/auth/token` verifies the same credentials and returns a signed bearer access token. Tokens expire after 30 minutes. Authentication requires a configured `AUTH_TOKEN_SECRET` of at least 32 bytes; see [Development setup](development_setup.md).

For example, after registration/login, send the returned token as an HTTP `Authorization: Bearer` header. The authenticated user can call `POST /api/v1/organizations` with `{"display_name":"Example Pharmacy"}`; the creator becomes the organization owner. `GET /api/v1/organizations` returns only the caller's memberships.

To add another user, that user must register first. An owner/admin calls `POST /api/v1/organizations/{organization_id}/members` with `{"email":"registered@example.test","role":"member"}`. The allowed roles are `owner`, `admin`, `member`, and `viewer`; admins may only grant `member` or `viewer`. Only owners/admins can list members or manage membership, including removing a member. An organization must retain at least one owner. Owners, admins, and members can persist normalization; viewers cannot write. A tenant ID alone never grants access.

## 1. Profile a file

`POST /api/v1/profile`

Accepts CSV/XLSX up to 10 MB and profiles at most 20,000 rows. Excel uses the first worksheet. Response includes source column indexes/names, candidate mappings, detected types, missing/unique counts, sample values, duplicates, and warnings. Upload is processed in memory; original upload bytes are not stored.

## 2. Get the canonical field catalogue

`GET /api/v1/schema/fields`

Returns supported canonical fields and the extra metadata required during confirmation. Quantity fields need explicit units; movement quantities need an explicit transaction type. Date mappings need a supported date format.

For expiry columns containing only month/year (e.g. `03/30`), the user must also explicitly select `date_convention: "month_end"` before the date can normalize to the last calendar day of that month. This is a stated domain convention, not an automatic inference.

## 3. Confirm a schema

`POST /api/v1/schema/confirm`

Send `profiled_columns` exactly as returned by profiling, including each zero-based `column_index` and original `source_column`, plus one mapping decision per column.

A choice has `action: "map"` with a supported canonical field and required metadata, or `action: "ignore"`. The API rejects missing decisions, mismatched column identity, unsupported target fields, conflicting targets, unknown date formats, missing units, and unresolved `QTY+FREE` semantics.

## 4. Normalize a file

`POST /api/v1/normalize` (multipart form)

Form fields:

- `file`: CSV or XLSX upload.
- `confirmed_schema_json`: JSON serialization of the full schema-confirmation request (the `profiled_columns` and `mappings` used in the previous step).
- `options_json`: optional JSON object with context:
  - `organization_id` (default `ORG-UNSPECIFIED` for preview-only processing)
  - `document_type`: `purchase_invoice`, `outward_invoice`, `retail_sales`, `inventory_report`, or `unknown`
  - `source_file_id`, `document_number`, `document_date`, `snapshot_date`, `counterparty_id`, and `currency_code` as available/confirmed.
- `persist`: `false` by default. Set `true` to save the result, subject to verified organization membership and writer role.

When an organization ID is supplied, the API checks the signed-in user's active membership; a caller cannot gain access by inventing or copying an ID. Saving requires `owner`, `admin`, or `member` in that organization. `viewer` membership is read-only. The uploaded file must have the same column names and order as the confirmed profile. Files that reach the 20,000-row profile cap are currently rejected by normalization until full-file validation is implemented.

The response returns counts and up to 10 preview records per canonical table, plus up to 50 data-quality issues and transformations. The Python function `normalize_dataframe` returns the full canonical tables for programmatic integration.

### Canonical output tables

- `products`
- `batches`
- `source_documents`
- `transactions`
- `inventory_snapshots`

The normalizer creates internal IDs, links transaction/batch/product/document records, preserves raw expiry text, uses only confirmed quantity/date semantics, and reports invalid values and conflicts. It rejects ambiguous comma-decimal formats, preserves month precision for Excel expiry cells formatted as month/year, does not link a row to a batch after an expiry conflict, does not calculate effective quantity when free quantity is invalid/missing or uses a different unit, and requires an explicit snapshot date for inventory snapshots. It does not guess product equivalence across external files. Product matching is limited to source product codes or a conservative exact attribute key within the current upload.

For invoice types `purchase_invoice` and `outward_invoice`, a confirmed document date is used as transaction date when no transaction date was mapped; this is recorded in the transformation list. Other document types do not receive this fallback.

## 5. Review a saved normalization run

`GET /api/v1/normalization-runs/{run_id}?organization_id=...`

Returns bounded previews for a saved run only after the request's bearer token is validated and the signed-in user is confirmed as a member of that organization. The ID is still a filter and is not itself an authorization credential. Users outside the organization receive `404`; authenticated viewers and writers can read previews if they belong to the tenant.

## 6. Current security and product limitations

Passwords are hashed with Argon2. Signed access tokens expire after 30 minutes, and each protected request checks that the underlying account still exists and is active. The database stores organization memberships and roles; write and read routes enforce those memberships on the server. Registration does not grant membership, and only an existing tenant owner/admin can add a registered account.

This is a security baseline for controlled development, not a production identity service. Rate limiting, MFA, account recovery, token refresh, dedicated secret management, detailed audit logging, deployment/proxy hardening, data retention/deletion workflows, and an independent security review remain outstanding. Normalization persists only when explicitly requested. Original file bytes are not stored by this workflow. Invalid/missing values are reported as issues rather than silently imputed. No inventory-risk calculations, forecasts, or recommendations are run by this endpoint.


## 7. Data quality and analysis readiness

Each normalization response includes a deterministic `quality_report`. The same report is saved with a normalization run and returned when that saved run is retrieved. The report separates grouped findings from module readiness.

- `quality_findings` carries forward normalization issues and adds checks for missing product names/expiry, missing quantity units, unknown stock basis, possible duplicate transaction signatures, suspicious discount/tax rates, negative prices, and ignored source columns. Possible duplicates are flagged for review, never automatically removed.
- `field_coverage` reports counts and percentages for important canonical fields.
- `analysis_readiness` gives each module a `ready`, `ready_with_warnings`, or `insufficient_data` status, required inputs, available-input counts, blockers, and warnings.
- `overall_status` describes whether any supported analysis path has enough inputs to proceed. It is not a risk score, a forecast, or a guarantee of statistical reliability.

Current modules: expiry monitoring, demand forecasting, overstock review, and stock-out review. Demand readiness requires at least 10 dated retail-sale lines, 7 distinct sale dates, at least 28 days between the first and last sale, and one consistent quantity unit per product. These are conservative engineering guardrails, not a statistical sufficiency claim. Expiry monitoring needs a normalized batch expiry and a dated on-hand snapshot linked to the same batch. Overstock review additionally needs comparable dated retail-sale quantities and stock units. Stock-out review is blocked until confirmed replenishment timing evidence is available; the current normalization ingestion does not yet create replenishment-order records.

A purchase invoice alone is not treated as verified sell-through or current inventory. The quality engine does not infer missing values, calculate inventory risks, reconcile monetary amounts when the source's tax/amount semantics are unconfirmed, or automatically deduplicate rows.


## 8. Inventory arithmetic and batch expiry alerts

The `quality_report.inventory_analysis` object is calculated for preview responses and stored inside the saved quality report. The arithmetic uses a fixed report date of the server's current date unless the Python service is called directly with an explicit `as_of_date`. The expiry alert windows are 30, 90 and 180 days.

- **Current positions:** select the latest valid stock snapshot on or before the report date per product/batch/quantity unit. Future-dated snapshots are excluded; stale snapshots are still shown but clearly flagged. Product-level and batch-level totals are reported separately to help prevent double counting.
- **Snapshot validation:** negative or incomplete snapshots are excluded. Conflicting same-date balances or mixed units exclude the affected position; identical same-date duplicates are counted once and flagged.
- **Reconciliation:** where there are at least two dated snapshots and movements with interpretable dates, movement types and matching units, the engine compares the next balance with previous balance plus net movements. Ambiguous or incomplete movement evidence returns `not_checkable`; a variance is flagged rather than silently corrected.
- **Expiry alerts:** only positive stock in a batch with normalized expiry data is eligible. Expired positive stock is `critical`; batches expiring in 0–30 days are `high`, 31–90 days `medium`, and 91–180 days `low`. Batches outside the window are not listed as alerts. The response includes batch identity, date, days remaining, snapshot date/age, quantity, unit and confidence/provisional reasons.
- **Indicative MRP value:** calculated only where a dated same-batch transaction supplies an unambiguous MRP, matching declared quantity unit, and confirmed currency. This assumes the mapped MRP is per that quantity unit. It is **indicative retail-price exposure**, not purchase cost, expected loss, write-off value or recoverable value. If price/currency evidence is missing or conflicting, the value is omitted.

The report only evaluates data present in the current normalization run. It does not merge inventory history across separate uploaded files, and a reconciliation match is not proof that the movement ledger is complete. Uploads containing only supplier or stockist invoices do not create stock-on-hand estimates; an explicit dated stock snapshot is required.
