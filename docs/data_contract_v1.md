# MedStockIQ — Data Contract v1

**Status:** Draft for implementation  
**Version:** 1.0  
**Scope:** Pharmacy and stockist/distributor inventory analysis  
**Purpose:** Define a common internal representation for different CSV, Excel, and invoice-derived inputs so the system can validate, analyze, and eventually forecast inventory risk across organizations.

## 1. Product objective

The platform accepts business files, profiles their structure, proposes mappings from source columns to canonical fields, asks the user to confirm ambiguous mappings, normalizes the data, checks data quality, and runs supported inventory analyses.

Initial risk areas:

1. **Overstock risk** — inventory is projected to exceed reasonable future need or an explicitly configured stock policy.
2. **Expiry risk** — a batch may have quantity remaining when it expires.
3. **Stock-out risk** — available stock may be insufficient before replenishment can arrive.

The system must distinguish observed facts, calculated metrics, and predictions. It must report when the uploaded data is insufficient for a reliable conclusion rather than invent missing values.

## 2. Design principles

- **Organization-independent:** organizations may use different column names, layouts, and source systems.
- **Canonical internally, source-preserving externally:** map uploads to a stable internal model while retaining source values and transformation metadata, subject to the retention policy.
- **User-confirmed ambiguity:** never silently decide the meaning of ambiguous fields such as QTY, RATE, AMOUNT, EXP, or QTY+FREE.
- **Explicit quantity semantics:** quantities must include a known unit/context; packs, strips, bottles, and individual units must not be mixed without a verified conversion.
- **Separate documents from movements:** an invoice is a source document; each invoice line is a separate transaction line.
- **Separate product from batch:** one product may have multiple batches and expiry dates.
- **Reproducibility:** each report references input files, confirmed mappings, data version, assumptions, and model/rule versions.
- **Privacy by minimization:** do not ingest patient/customer personal data when it is not needed for inventory analysis.

## 3. Observed source formats

### 3.1 Pharmacy purchase invoice (supplier/stockist to pharmacy)

Reported line-item columns:

- SL
- MFG
- HSN code
- Product name
- pack
- batch
- exp
- old mrp
- new mrp
- rate
- qty+free
- disc%
- dis. amt
- amount
- gst%
- total amt

### 3.2 Stockist outward invoice (stockist to retailer/pharmacy)

Reported line-item columns:

- SN
- hsn
- mfg
- product
- old_mrp
- pack
- batch no
- exp
- qty
- mrp
- rate
- disc
- disc2
- gst%
- amount

The supplied invoice PDF contains additional layout and label variations, including separate free-quantity fields, split tax fields, and different labels for net/total amount. Handle them using schema mapping and user confirmation.

**Important limitation:** purchase and distribution invoices do not, by themselves, establish retail sell-through, current on-hand stock, or historical stock snapshots.

## 4. Canonical entities

The conceptual model below may be implemented as normalized SQL tables. Field meanings should remain stable even when source column names differ.

### 4.1 Organization

| Field | Suggested type | Required | Meaning |
|---|---|---|---|
| organization_id | UUID/string | Yes | Internal organization identifier. |
| organization_type | enum/string | Yes | pharmacy, stockist, distributor, or other. |
| display_name | string | No | User-provided display name; may be pseudonymized. |
| default_quantity_unit_policy | string/config | No | Organization-approved unit policy. |
| inventory_policy | JSON/config | No | Optional target-days-of-stock or risk thresholds. |

### 4.2 Product

| Field | Suggested type | Required | Meaning |
|---|---|---|---|
| product_id | UUID/string | Yes | Internal canonical product identifier. |
| organization_id | UUID/string | Yes | Owning organization/tenant. |
| source_product_code | string | No | Product code from source system. |
| product_name | string | Required for useful analysis | Confirmed product name. |
| manufacturer_name | string | No | Manufacturer, often labelled MFG. |
| hsn_code | string | No | Preserve HSN as text. |
| pack_description | string | No | Source value such as 10'S, 100ML, or 1VL. |
| quantity_unit | string | Required for quantity analysis | Confirmed unit, e.g. pack, strip, bottle, tablet, vial. |
| units_per_pack | decimal | No | Only when known and confirmed. |
| product_match_status | enum/string | Yes | confirmed, suggested, or unmatched. |

Do not merge products solely because their names look similar. Use product code, name, manufacturer, pack, and user confirmation to suggest matches. Leave ambiguous matches unresolved.

### 4.3 Batch

| Field | Suggested type | Required | Meaning |
|---|---|---|---|
| batch_record_id | UUID/string | Yes | Internal batch record identifier. |
| organization_id | UUID/string | Yes | Organization whose inventory/transactions reference the batch. |
| product_id | UUID/string | Yes | Product link. |
| batch_code | string | Preferred | Source batch/lot identifier, preserved as text. |
| manufacturing_date | date | No | If available and interpretable. |
| expiry_raw | string | Preferred if supplied | Original expiry text exactly as received. |
| expiry_date | date | Required for expiry-risk calculation | Normalized expiry date after the convention is confirmed. |
| expiry_date_precision | enum/string | Yes when expiry is mapped | For example day or month. |

Expiry values such as 03/30 must not be silently interpreted. Retain the raw value, propose a format, and ask for confirmation when ambiguous. If only month and year are provided, document the agreed convention and disclose it in analysis.

### 4.4 SourceDocument

| Field | Suggested type | Required | Meaning |
|---|---|---|---|
| document_id | UUID/string | Yes | Internal source-document identifier. |
| organization_id | UUID/string | Yes | Organization that owns the upload. |
| source_file_id | UUID/string | Yes | Reference to original file or ingestion artifact. |
| document_type | enum/string | When known | purchase_invoice, outward_invoice, sales_report, inventory_report, or unknown. |
| document_number | string | No | Invoice/document number, if present. |
| document_date | date | Required for time-series analysis | Confirmed invoice/transaction date. |
| counterparty_id | string | No | Pseudonymous supplier/retailer identifier, if needed. |
| currency_code | string | No | Currency, e.g. INR, when confirmed. |
| source_format | enum/string | Yes | csv, xlsx, pdf, etc. |
| ingested_at | timestamp | Yes | Ingestion timestamp. |

Do not import names, addresses, tax identifiers, phone numbers, or other unnecessary identifiers into the analytical model by default. Use pseudonymous counterpart IDs where sufficient.

### 4.5 InventoryTransaction

Each invoice line or stock movement is represented as a transaction linked to a source document when available.

| Field | Suggested type | Required | Meaning |
|---|---|---|---|
| transaction_id | UUID/string | Yes | Internal identifier. |
| organization_id | UUID/string | Yes | Organization whose movement is represented. |
| document_id | UUID/string | Preferred for invoice-derived records | Source document. |
| transaction_date | date | Required for time-based analysis | Confirmed movement/invoice date. |
| transaction_type | enum/string | Required for stock-flow calculations | purchase_receipt, retailer_dispatch, retail_sale, customer_return, supplier_return, stock_adjustment, damaged_writeoff, expiry_writeoff, or unknown. |
| product_id | UUID/string | Yes for product-level analysis | Product reference. |
| batch_record_id | UUID/string | Preferred; required for batch movement analysis | Batch reference. |
| quantity | decimal | Yes for movement analysis | Quantity in a source-confirmed unit; quantity must be finite. |
| quantity_unit | string | Yes | Unit for quantity. |
| free_quantity | decimal | No | Separate free quantity when source distinguishes it. |
| effective_quantity | decimal | Derived only when semantics confirmed | Total movement quantity under the confirmed rule. |
| unit_rate | decimal | No | Transaction rate; purchase/sale meaning and tax basis must be confirmed. |
| mrp | decimal | No | MRP applicable to the line. |
| previous_mrp | decimal | No | Old MRP where available. |
| discount_percent | decimal | No | Percentage, only where source meaning is clear. |
| discount_amount | decimal | No | Discount amount, where clear. |
| secondary_discount | decimal | No | Field such as DISC2, retained until meaning is confirmed. |
| tax_rate | decimal | No | GST/tax rate. |
| line_amount | decimal | No | Line amount; pre-tax/post-tax basis must be established. |
| tax_amount | decimal | No | Tax amount, where separately available. |
| line_total_amount | decimal | No | Final line total under the source's tax/adjustment convention. |
| source_row_number | integer | No | Original line number for traceability. |

Transaction type determines movement direction. A purchase receipt is an inflow to the organization; retailer dispatch is an outflow from a stockist. Do not infer direction from the QTY column alone—use confirmed document context.

### 4.6 InventorySnapshot

| Field | Suggested type | Required | Meaning |
|---|---|---|---|
| snapshot_id | UUID/string | Yes | Internal identifier. |
| organization_id | UUID/string | Yes | Organization. |
| snapshot_date | date/timestamp | Yes | Date/time the quantity applies to. |
| product_id | UUID/string | Yes | Product. |
| batch_record_id | UUID/string | Preferred for expiry risk | Batch, if available. |
| quantity_on_hand | decimal | Yes | Recorded on-hand stock. |
| quantity_unit | string | Yes | Confirmed unit. |
| stock_basis | enum/string | Yes | physical, system, or unknown. |

Do not label a quantity as current_stock unless its source and timestamp establish that it is current inventory. Purchased quantity is not on-hand quantity.

### 4.7 Optional ReplenishmentOrder

| Field | Suggested type | Required | Meaning |
|---|---|---|---|
| order_id | UUID/string | Yes when available | Internal order identifier. |
| organization_id | UUID/string | Yes | Organization. |
| product_id | UUID/string | Yes | Product ordered. |
| order_date | date | Yes when available | Date order was placed. |
| quantity_ordered | decimal | Yes when available | Ordered quantity. |
| quantity_unit | string | Yes | Unit of measure. |
| expected_arrival_date | date | No | Expected receipt date. |
| actual_arrival_date | date | No | Actual receipt date. |
| order_status | enum/string | No | pending, partially_received, received, cancelled, or unknown. |
| supplier_id | string | No | Pseudonymous supplier identifier. |

Lead time can be derived from order and receipt dates when both are available. If not, manually supplied lead time must be labelled an estimate/configuration.

## 5. Source-column mapping rules

### 5.1 Pharmacy purchase invoice

| Source column | Candidate canonical field | Important notes |
|---|---|---|
| SL | source_row_number | Not a product ID. |
| MFG | manufacturer_name | Confirm meaning. |
| HSN code | hsn_code | Preserve as text. |
| Product name | product_name | Matching may need confirmation. |
| pack | pack_description | Do not guess unit conversions. |
| batch | batch_code | Preserve as text. |
| exp | expiry_raw to expiry_date | Confirm format. |
| old mrp | previous_mrp | Separate from current MRP. |
| new mrp | mrp | Confirm current pricing meaning. |
| rate | unit_rate | Confirm purchase rate and tax/discount semantics. |
| qty+free | quantity/free quantity fields | Composite field; confirm interpretation before parsing. |
| disc% | discount_percent | Confirm whether line or unit basis. |
| dis. amt | discount_amount | Confirm meaning. |
| amount | line_amount | Establish pre-tax/post-tax basis. |
| gst% | tax_rate | Confirm combined or component rate. |
| total amt | line_total_amount | Confirm line-level vs document-level total. |

### 5.2 Stockist-to-retailer invoice

| Source column | Candidate canonical field | Important notes |
|---|---|---|
| SN | source_row_number | Not a product ID. |
| hsn | hsn_code | Preserve as text. |
| mfg | manufacturer_name | Confirm abbreviation. |
| product | product_name | Matching may need confirmation. |
| old_mrp | previous_mrp | Preserve separately. |
| pack | pack_description | Do not guess unit conversions. |
| batch no | batch_code | Preserve as text. |
| exp | expiry_raw to expiry_date | Confirm format. |
| qty | quantity | Likely dispatched quantity; confirm unit and free-quantity handling. |
| mrp | mrp | Product MRP, not necessarily transaction rate. |
| rate | unit_rate | Likely stockist sale rate; confirm. |
| disc | discount field | Confirm percentage vs amount. |
| disc2 | secondary_discount | Preserve until semantics confirmed. |
| gst% | tax_rate | Confirm combined/component rate. |
| amount | line_amount | Confirm basis. |

Invoice-level fields such as invoice number, invoice date, supplier, and retailer identifier should map to source-document metadata. Retain pseudonymous counterparty IDs when identity is not needed for analysis.

## 6. Schema-mapping metadata

For each uploaded file, preserve mapping records with:

- file_id
- source_column
- source_column_index (zero-based; disambiguates repeated header names)
- sample_values, limited to the minimum necessary
- detected_data_type
- proposed_canonical_field
- mapping_confidence, explicitly not a guarantee
- mapping_status: suggested, confirmed, corrected, ignored, or unmapped
- mapping_origin: suggestion_confirmed, user_corrected, manual, or user_ignored
- confirmed_by_user or equivalent audit reference
- transformation_rule
- confirmed source date/quantity format

The UI should ask about unclear mappings. Unknown columns should be preserved as unmapped metadata rather than silently discarded.

### Canonical normalization implementation notes

The current normalization service consumes a `SchemaConfirmationRequest` plus a source dataframe and confirmed organization/document context. It returns canonical Products, Batches, SourceDocuments, Transactions, and InventorySnapshots with generated within-run IDs, source-row traceability, a transformation log, and structured data-quality issues.

Normalization does not infer values from column names after confirmation. It checks that the current file's column names and order match the confirmed profile. It supports a small explicit date-format catalogue; month/year expiry values require the explicit `month_end` convention. A composite `QTY+FREE` field is split only when the confirmed transformation rule is supplied. Duplicate or conflicting batch/product information is reported rather than silently overwritten. This prototype returns data in memory and does not persist it or calculate inventory risks.

## 7. Minimum data readiness by risk module

A file can be ingested successfully without supporting every analysis. Each risk module must return its own readiness status.

### 7.1 Overstock risk

Preferred inputs:
- dated demand/outflow history (retail sales for a pharmacy; retailer dispatches for a stockist);
- dated current inventory;
- inward purchases and pending/incoming orders, where available;
- consistent product identity and quantity units;
- organization-approved stock policy or a clearly labelled assumption.

Possible outputs: demand forecast, days of inventory, projected inventory, estimated surplus, risk level, and evidence.

Limitations: purchase invoices alone do not reveal retail sell-through. Stockist-to-retailer invoices reflect stockist outflow and retailer ordering, not necessarily the pharmacy's customer demand. Do not present an assumed stock target as an organization policy.

### 7.2 Expiry risk

Preferred inputs:
- product and batch identifier;
- normalized expiry date;
- current remaining quantity for the batch;
- demand history and expected demand before expiry;
- consistent quantity unit.

Possible outputs: days until expiry, expected demand before expiry, estimated quantity at risk, risk level.

Limitations: expiry date supports a calendar alert, not a prediction of unsold quantity. If only product-level demand is available, any batch depletion estimate must disclose its assumptions (e.g. FEFO allocation) and uncertainty.

### 7.3 Stock-out risk (later stage)

Preferred inputs:
- current inventory;
- dated demand history;
- supplier/order lead time or confirmed estimate;
- incoming and pending replenishment quantities/dates where available.

Possible outputs: estimated time to depletion, demand during lead time, projected shortage, risk level.

Limitations: without current inventory and replenishment-time information, reliable stock-out prediction may not be possible.

## 8. Core validation rules

1. Preserve source values before transformations.
2. Validate dates and record the confirmed format; flag ambiguous/invalid dates.
3. Quantities must be numeric, finite and expressed in a known unit. Negative quantities require a recognized return/adjustment type rather than being treated silently as ordinary sales/purchases.
4. Validate numeric prices, discounts, taxes and amounts; flag suspicious values rather than auto-correcting them.
5. Never treat SL/SN as product ID.
6. Do not treat MRP, transaction rate, purchase cost and line amount as interchangeable.
7. Do not merge products on fuzzy name similarity alone.
8. Batch expiry analysis requires a matched batch and usable expiry date.
9. Purchased quantity is not current stock. Current stock requires a dated inventory record or defensible reconstruction from a known opening balance and complete movements.
10. Missing required data results in insufficient_data with missing-field guidance, not fabricated risk predictions.
11. Record input file IDs, mapping version, transformations, assumptions, analysis time, and model/rule versions for reproducibility.
12. Avoid ingesting patient/customer personal data unless a documented requirement justifies it.

## 9. Output contract

### AnalysisRun

- analysis_id
- organization_id
- created_at
- input_file_ids
- mapping_version
- data_quality_status
- modules_requested
- modules_ready
- modules_insufficient_data
- algorithm_versions
- assumptions

### RiskFinding

- finding_id
- analysis_id
- organization_id
- product_id
- batch_record_id (nullable when not applicable)
- risk_type: overstock, expiry, stockout
- risk_level (configured categorical level)
- risk_score (nullable unless defined and calibrated)
- observed_metrics
- forecast_metrics with horizon, where applicable
- reason_codes
- limitations

### Recommendation

- recommendation_id
- finding_id
- action_text
- priority
- evidence_references
- assumptions_or_caveats

The LLM may turn validated results into readable reports and chat responses; it must not invent metrics or unsupported causes. Recommendations are decision support, not automatic actions.

## 10. Scope for v1

### In scope
- CSV and Excel ingestion first.
- PDF invoice parsing behind a parser interface, with OCR/table extraction and human verification when needed.
- Schema inference and user confirmation.
- Canonical product, batch, document, transaction and inventory representation.
- Data-quality report.
- Initial overstock and expiry analysis.
- Baseline demand forecasting when enough dated demand history exists.
- Structured findings, downloadable report and conversational questions grounded in analytical evidence.

### Later / dependent on data validation
- Stock-out prediction.
- Generalization testing across independent organizations.
- RAG over policies/manuals.
- Pharmacy ERP/POS integrations.
- Automatic order placement/remediation.
- Advanced tenant administration and enterprise deployment.

## 11. Decisions awaiting business confirmation

Keep these configurable or unresolved until the pharmacy/stockist confirms them:

- Whether QTY means packs, strips, bottles, or another unit.
- How QTY+FREE is represented and whether free units are included in printed quantity.
- Meaning/tax basis of RATE, AMOUNT, TOTAL AMT, DISC and DISC2 for each source.
- How expiry values such as 03/30 should be interpreted.
- Whether product codes/names are consistent across files.
- Whether current and historical inventory reports exist.
- Whether retail sales history or only supplier invoices are available.
- Whether batch-wise remaining quantity is available.
- Whether pending orders and lead times are recorded.
- What target stock policy/risk thresholds the organization accepts.

Do not hard-code answers until confirmed or explicitly documented as assumptions.

## 12. Implementation sequence

1. Profile files and store mapping metadata.
2. Implement canonical Product, Batch, SourceDocument, InventoryTransaction, and InventorySnapshot models.
3. Add user review for ambiguous mappings.
4. Build synthetic data consistent with this contract.
5. Implement data-quality checks and reporting.
6. Implement deterministic inventory calculations and expiry alerts.
7. Add forecasting baselines and use time-based evaluation where dated demand exists.
8. Add evidence-backed overstock/expiry findings and recommendations.
9. Add reports and analytical chat.
10. Add stock-out analysis when data supports it and validate with authorized real records.

## 13. Acceptance criteria

- [ ] Profile source files without silently dropping unknown columns.
- [ ] Suggest mappings for both observed invoice layouts.
- [ ] Require user confirmation of ambiguous mappings.
- [ ] Preserve source values and transformation metadata.
- [ ] Define Product, Batch, SourceDocument, InventoryTransaction and InventorySnapshot with clear keys.
- [ ] Do not silently guess quantity units, expiry parsing or monetary field semantics.
- [ ] Distinguish import success from per-module analysis readiness.
- [ ] Missing required fields produce explicit insufficient_data status.
- [ ] Generate synthetic scenarios for normal inventory, overstock, near-expiry batches and potential stock-outs.

**Contract status:** This is the initial implementation contract, not a claim that the presently available invoices contain every required field. Revise it when businesses confirm the reports and semantics of ambiguous fields.
