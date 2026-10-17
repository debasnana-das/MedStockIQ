"""Conservative column-name mapping suggestions for uploaded tabular data."""

from __future__ import annotations

import re
from typing import Any


def normalize_column_name(value: object) -> str:
    """Normalize a header for alias matching without changing the original header."""
    return re.sub(r"[^a-z0-9]+", "", str(value).strip().casefold())


# canonical field, confidence, requires confirmation, explanation, transaction type hint
_ALIASES: dict[str, tuple[str, float, bool, str, str | None]] = {}


def _register(
    canonical_field: str,
    aliases: tuple[str, ...],
    confidence: float = 0.95,
    requires_confirmation: bool = False,
    rationale: str = "Column name matches a recognized alias.",
    transaction_type_hint: str | None = None,
) -> None:
    for alias in aliases:
        _ALIASES[normalize_column_name(alias)] = (
            canonical_field,
            confidence,
            requires_confirmation,
            rationale,
            transaction_type_hint,
        )


_register("source_row_number", ("sl", "sn", "serial", "serial number", "sno"), 0.98)
_register("source_product_code", ("product id", "product_id", "sku", "sku id", "item code", "product code"), 0.94)
_register("product_name", ("product", "product name", "item name", "medicine name", "drug name"), 0.96)
_register("product_name", ("item", "medicine", "drug"), 0.76, True, "Generic product label; confirm that this identifies the medicine.")
_register("manufacturer_name", ("manufacturer", "manufacturer name"), 0.95)
_register("manufacturer_name", ("mfg",), 0.70, True, "MFG can mean manufacturer or manufacturing date in different systems.")
_register("hsn_code", ("hsn", "hsn code"), 0.98)
_register("pack_description", ("pack", "packing", "pack size", "package size"), 0.90, True, "Confirm whether this is a pack description or a normalized unit.")
_register("batch_code", ("batch", "batch no", "batch number", "lot", "lot no", "lot number"), 0.96)
_register("expiry_date", ("exp", "expiry", "expiry date", "expiration date"), 0.82, True, "Expiry text may use month/year or day/month/year; confirm the date convention.")
_register("manufacturing_date", ("mfg date", "manufacturing date", "manufacture date"), 0.90, True, "Confirm the source date format.")
_register("previous_mrp", ("old mrp", "previous mrp", "old_mrp"), 0.94)
_register("mrp", ("mrp", "new mrp", "current mrp"), 0.93)
_register("unit_rate", ("rate", "purchase rate", "sale rate", "selling rate", "unit rate"), 0.75, True, "Rate may mean purchase or selling rate; confirm document context and tax basis.")
_register("quantity", ("quantity sold", "qty sold", "units sold", "sales quantity"), 0.93, True, "Confirm unit of measure and that this is sales/outflow quantity.", "retail_sale")
_register("quantity", ("quantity purchased", "qty purchased", "quantity received", "qty received"), 0.93, True, "Confirm unit and whether this is an inward receipt.", "purchase_receipt")
_register("quantity", ("quantity dispatched", "qty dispatched", "dispatch quantity", "outward quantity"), 0.93, True, "Confirm unit and whether this is an outward dispatch.", "retailer_dispatch")
_register("quantity", ("quantity", "qty", "qnty"), 0.70, True, "Quantity alone does not identify movement direction or unit.")
_register("quantity", ("qty+free", "qty + free", "quantity free", "qtyfree"), 0.48, True, "Composite quantity may include free units. Confirm how to split billed and free quantity before use.")
_register("free_quantity", ("free qty", "free quantity", "free units"), 0.86, True, "Confirm whether free quantity is already included in the main quantity.")
_register("transaction_date", ("sale date", "sales date", "purchase date", "dispatch date", "transaction date", "date of transaction"), 0.90, True, "Confirm the meaning and date format for this report.")
_register("document_date", ("invoice date", "bill date", "voucher date", "document date"), 0.94, True, "Confirm date format; invoice date may be used as transaction date only when appropriate.")
_register("document_number", ("invoice no", "invoice number", "bill no", "bill number", "document number"), 0.91)
_register("current_quantity", ("current stock", "current qty", "quantity on hand", "qty on hand", "closing stock", "closing quantity", "closing qty"), 0.92, True, "Confirm stock date, unit, and whether this is physical or system stock.")
_register("quantity_on_hand", ("stock quantity", "stock qty", "on hand"), 0.80, True, "Confirm the effective date, unit, and stock basis.")
_register("unit_rate", ("purchase cost", "cost per unit"), 0.78, True, "Confirm whether this is cost per pack/unit and whether tax is included.")
_register("discount_percent", ("disc%", "discount%", "discount percent", "discount percentage"), 0.90, True, "Confirm the discount base.")
_register("discount_percent", ("disc", "discount"), 0.62, True, "Discount may be a percentage or amount; confirm.")
_register("discount_amount", ("dis amt", "disc amt", "discount amount", "dis. amt"), 0.86, True, "Confirm whether this is a line-level monetary discount.")
_register("secondary_discount", ("disc2", "discount 2", "secondary discount"), 0.84, True, "Meaning and calculation order of this field need confirmation.")
_register("tax_rate", ("gst%", "gst %", "gst rate", "tax rate", "tax %"), 0.88, True, "Confirm whether the rate is combined GST or a tax component.")
_register("line_amount", ("amount", "line amount", "taxable amount"), 0.72, True, "Confirm whether the amount is pre-tax, post-discount, and line-level.")
_register("line_total_amount", ("total amt", "total amount", "line total", "net amount", "net amount line"), 0.78, True, "Confirm whether this is a line total or invoice/document total.")
_register("tax_amount", ("gst amount", "tax amount", "gst amt"), 0.87, True, "Confirm whether this is a line-level or document-level tax amount.")
_register("opening_stock", ("opening stock", "opening quantity", "opening qty"), 0.84, True, "Map to an inventory position at the start of the reporting period.")
_register("supplier_id", ("supplier id", "supplier code", "vendor id", "vendor code"), 0.90)
_register("retailer_id", ("retailer id", "pharmacy id", "store id", "outlet id"), 0.90)


def suggest_column_mapping(
    column_name: object,
    sample_values: list[Any] | None = None,
) -> dict[str, Any]:
    """Return a candidate mapping, never a silently confirmed mapping."""
    normalized = normalize_column_name(column_name)
    match = _ALIASES.get(normalized)
    if match is None:
        return {
            "canonical_field": None,
            "confidence": 0.0,
            "requires_confirmation": True,
            "mapping_status": "unmapped",
            "transaction_type_hint": None,
            "rationale": "No exact column-name mapping is known. Review sample values and map manually if appropriate.",
        }

    canonical, confidence, requires_confirmation, rationale, transaction_hint = match
    samples = sample_values or []
    if canonical in {"expiry_date", "manufacturing_date", "transaction_date", "document_date"}:
        rationale = f"{rationale} Raw values will be retained until date parsing is confirmed."
        requires_confirmation = True
    if canonical in {"quantity", "current_quantity", "quantity_on_hand", "opening_stock"}:
        rationale = f"{rationale} Unit and inventory/movement semantics must be confirmed."
        requires_confirmation = True
    if canonical == "line_total_amount":
        rationale = f"{rationale} Do not confuse a line total with an invoice grand total."
        requires_confirmation = True

    return {
        "canonical_field": canonical,
        "confidence": round(confidence, 2),
        "requires_confirmation": requires_confirmation,
        "mapping_status": "suggested",
        "transaction_type_hint": transaction_hint,
        "rationale": rationale,
    }
