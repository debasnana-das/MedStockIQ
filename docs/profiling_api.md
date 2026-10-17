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
