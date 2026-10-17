# Profiling, schema confirmation, and normalization APIs

These endpoints are local development prototypes. They do not authenticate users or persist uploaded files or normalized records.

## 1. Profile a file

`POST /api/v1/profile`

Accepts CSV/XLSX up to 10 MB and profiles at most 20,000 rows. Excel uses the first worksheet. Response includes source column indexes/names, candidate mappings, detected types, missing/unique counts, sample values, duplicates, and warnings. Upload is processed in memory.

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
  - `organization_id` (default `ORG-UNSPECIFIED`)
  - `document_type`: `purchase_invoice`, `outward_invoice`, `retail_sales`, `inventory_report`, or `unknown`
  - `source_file_id`, `document_number`, `document_date`, `snapshot_date`, `counterparty_id`, and `currency_code` as available/confirmed.

The uploaded file must have the same column names and order as the confirmed profile. Files that reach the 20,000-row profile cap are currently rejected by normalization until full-file validation is implemented.

The response returns counts and up to 10 preview records per canonical table, plus up to 50 data-quality issues and transformations. The Python function `normalize_dataframe` returns the full canonical tables for programmatic integration.

### Canonical output tables

- `products`
- `batches`
- `source_documents`
- `transactions`
- `inventory_snapshots`

The normalizer creates internal IDs, links transaction/batch/product/document records, preserves raw expiry text, uses only confirmed quantity/date semantics, and reports invalid values and conflicts. It does not guess product equivalence across external files. Product matching is limited to source product codes or a conservative exact attribute key within the current upload.

For invoice types `purchase_invoice` and `outward_invoice`, a confirmed document date is used as transaction date when no transaction date was mapped; this is recorded in the transformation list. Other document types do not receive this fallback.

## 5. Current limitations and safety

Normalization is stateless; no file, schema, or output is saved. The API response is a preview, not a downloadable normalized dataset. Invalid/missing values are reported as issues rather than silently imputed. No inventory-risk calculations, forecasts, or recommendations are run by this endpoint.

Until authentication, tenant isolation, retention controls, full-file validation, and production protections are implemented and tested, use synthetic/sanitized files locally. Do not expose the development API to the internet or use confidential live data.
