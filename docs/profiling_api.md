# CSV/XLSX profiling API

## Endpoint

`POST /api/v1/profile`

- Accepts `.csv` and `.xlsx` files.
- Maximum uploaded size: 10 MB.
- Profiles up to the first 20,000 rows.
- XLSX profiling reads the first worksheet.
- The current endpoint processes the upload in memory and does not persist it.
- PDF/OCR, schema-confirmation writes, normalization, and inventory analysis are not implemented in this endpoint yet.

## Example

```bash
curl -X POST http://127.0.0.1:8000/api/v1/profile \
  -F "file=@sample.csv"
```

## Response shape

The response includes:

- `filename`, `format`, and `storage` (currently `in_memory_not_persisted`).
- `row_count_profiled`, `column_count`, and `duplicate_rows_profiled`.
- `truncated`, indicating that the row cap may have limited profiling.
- A `columns` array with original column name, detected type, non-null count, missing count/percentage, unique count, up to five sample values, and a candidate mapping.
- `warnings` about missing recognizable fields.

Each candidate mapping contains `canonical_field`, `confidence`, `requires_confirmation`, `mapping_status`, an optional `transaction_type_hint`, and a rationale.

## Interpretation

Mappings are suggestions, not accepted schema decisions. In particular:

- `QTY` does not establish whether a number is purchased, sold, or dispatched, nor its unit.
- `QTY+FREE` is a composite field and must be clarified before normalization.
- `EXP` can contain ambiguous month/year text such as `03/30`; raw values must be retained and the date convention confirmed.
- `RATE`, `AMOUNT`, discounts, and tax columns need contextual confirmation.
- Unknown columns are reported as unmapped rather than being silently discarded.

## Safety limitation

This endpoint is a development prototype without authentication, tenant isolation, database persistence, retention controls, or production deployment protections. Use synthetic/sanitized files locally; do not expose this endpoint to the internet or use confidential live data until the relevant protections are implemented and tested.
