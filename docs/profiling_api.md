# CSV/XLSX profiling and schema-confirmation API

The API is a local development prototype. It does not yet authenticate users, persist uploads/mappings, normalize the source rows, or run inventory-risk analysis.

## 1. Profile an upload

`POST /api/v1/profile`

- Accepts `.csv` and `.xlsx` files.
- Maximum upload: 10 MB.
- Profiles up to 20,000 rows; XLSX uses the first worksheet.
- Upload bytes are processed in memory and are not persisted by this endpoint.
- PDF/OCR is not implemented.

Example:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/profile \
  -F "file=@sample.csv"
```

The result includes a `columns` array with a zero-based `column_index`, original `source_column`, detected type, null/unique counts, sample values, and a candidate mapping. Column index plus header name is used because real files can contain duplicate column labels.

## 2. Read the canonical field catalogue

`GET /api/v1/schema/fields`

Returns supported canonical field names, their descriptions, and metadata required during confirmation.

Examples:

- Date fields require a user-confirmed `date_format`, for example `MM/YY`.
- Quantity/stock fields require a `quantity_unit`, for example `pack`, `strip`, or `tablet`.
- The transaction `quantity` field requires `transaction_type`, such as `purchase_receipt`, `retailer_dispatch`, or `retail_sale`.
- A composite `QTY+FREE` source column must explicitly select `split_quantity_and_free` and map its additional value to `free_quantity`.

## 3. Confirm schema mappings

`POST /api/v1/schema/confirm`

Send back the list of source columns returned by the profiler and exactly one decision for every column.

Each column choice is either:

- `action: "map"`: provide a supported `canonical_field` and any required metadata; or
- `action: "ignore"`: explicitly exclude the source column from this canonical mapping.

Example request:

```json
{
  "profiled_columns": [
    {"column_index": 0, "source_column": "PRODUCT"},
    {"column_index": 1, "source_column": "EXP"},
    {"column_index": 2, "source_column": "QTY+FREE"},
    {"column_index": 3, "source_column": "INTERNAL NOTE"}
  ],
  "mappings": [
    {
      "column_index": 0,
      "source_column": "PRODUCT",
      "action": "map",
      "proposed_canonical_field": "product_name",
      "canonical_field": "product_name"
    },
    {
      "column_index": 1,
      "source_column": "EXP",
      "action": "map",
      "proposed_canonical_field": "expiry_date",
      "canonical_field": "expiry_date",
      "date_format": "MM/YY"
    },
    {
      "column_index": 2,
      "source_column": "QTY+FREE",
      "action": "map",
      "proposed_canonical_field": "quantity",
      "canonical_field": "quantity",
      "quantity_unit": "pack",
      "transaction_type": "purchase_receipt",
      "transformation_rule": "split_quantity_and_free",
      "additional_canonical_fields": ["free_quantity"]
    },
    {
      "column_index": 3,
      "source_column": "INTERNAL NOTE",
      "action": "ignore"
    }
  ]
}
```

The endpoint validates that every profiled column has exactly one decision, the index/header pair matches the submitted profile, all target fields are supported, and two columns do not map to the same canonical field. It also checks that dates have a format, quantity fields have a unit, transactional quantity has a movement type, and `QTY+FREE` has an explicitly selected split rule.

A successful response reports the count of mapped and ignored columns, and each decision's status/origin:

- `confirmed` / `suggestion_confirmed`
- `corrected` / `user_corrected`
- `confirmed` / `manual`
- `ignored` / `user_ignored`

A successful response means the schema choices passed validation; it does not mean the file is ready for every inventory analysis.

## 4. Current boundaries

The confirmation endpoint is stateless. It validates the submitted column list and choices, but does not retrieve the original uploaded profile. It does not save the mapping, persist a file, parse date values, split quantity values, normalize the dataset, or calculate inventory risk. Those are later implementation stages.

Until authentication, tenant isolation, retention controls, and deployment protections are implemented and tested, use synthetic/sanitized files locally. Do not expose this development API to the internet or use confidential live data.
