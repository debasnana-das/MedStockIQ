"""Validated, explicit schema-confirmation contract for profiled columns."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schema.mapping import normalize_column_name

CANONICAL_FIELD_DESCRIPTIONS: dict[str, str] = {
    "source_row_number": "Row/line number from the source file; not a product identifier.",
    "source_product_code": "Source-system product/SKU code.",
    "product_name": "Product or medicine name.",
    "manufacturer_name": "Manufacturer name.",
    "hsn_code": "HSN classification code, preserved as text.",
    "pack_description": "Original pack description such as 10'S or 100ML.",
    "batch_code": "Manufacturer/distributor batch or lot code.",
    "expiry_date": "Normalized expiry date; parsing format must be confirmed.",
    "manufacturing_date": "Manufacturing date; parsing format must be confirmed.",
    "previous_mrp": "Old/previous maximum retail price.",
    "mrp": "MRP applicable to the row.",
    "unit_rate": "Transaction rate; purchase/sale meaning and tax basis need context.",
    "quantity": "Quantity moved in a transaction; direction and unit must be specified.",
    "free_quantity": "Free quantity associated with a purchase/sale line.",
    "transaction_date": "Date on which the transaction/movement occurred.",
    "document_date": "Date printed on an invoice or source document.",
    "document_number": "Invoice or source document number.",
    "current_quantity": "Current stock quantity; stock date and unit are important.",
    "quantity_on_hand": "Recorded on-hand inventory quantity.",
    "discount_percent": "Discount percentage.",
    "discount_amount": "Monetary discount amount.",
    "secondary_discount": "Secondary discount whose calculation semantics should be confirmed.",
    "tax_rate": "GST/tax rate.",
    "line_amount": "Line amount; pre-tax/post-tax semantics must be known.",
    "line_total_amount": "Line total, not necessarily an invoice grand total.",
    "tax_amount": "Tax amount for the line/document, as confirmed.",
    "opening_stock": "Opening inventory at the start of a known period.",
    "supplier_id": "Supplier/vendor identifier, preferably pseudonymous.",
    "retailer_id": "Retailer/pharmacy/outlet identifier, preferably pseudonymous.",
}

CANONICAL_FIELDS = frozenset(CANONICAL_FIELD_DESCRIPTIONS)
DATE_FIELDS = frozenset(
    {"expiry_date", "manufacturing_date", "transaction_date", "document_date"}
)
QUANTITY_FIELDS = frozenset(
    {"quantity", "free_quantity", "current_quantity", "quantity_on_hand", "opening_stock"}
)
SUPPORTED_DATE_FORMATS = frozenset(
    {
        "MM/YY",
        "MM/YYYY",
        "DD/MM/YY",
        "DD/MM/YYYY",
        "YYYY-MM-DD",
        "DD-MM-YYYY",
        "DD.MM.YYYY",
        "YYYY/MM/DD",
    }
)
MONTH_YEAR_FORMATS = frozenset({"MM/YY", "MM/YYYY"})


class ProfiledColumnReference(BaseModel):
    """Column identity returned by the profiler; index disambiguates repeated headers."""

    model_config = ConfigDict(extra="forbid")

    column_index: int = Field(ge=0)
    source_column: str = Field(min_length=1, max_length=200)

    @field_validator("source_column")
    @classmethod
    def validate_source_column(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("source_column must not be blank.")
        return value


class ColumnMappingChoice(BaseModel):
    """An explicit user decision for one source column."""

    model_config = ConfigDict(extra="forbid")

    column_index: int = Field(ge=0)
    source_column: str = Field(min_length=1, max_length=200)
    action: Literal["map", "ignore"]
    proposed_canonical_field: str | None = None
    canonical_field: str | None = None
    additional_canonical_fields: list[str] = Field(default_factory=list, max_length=3)
    quantity_unit: str | None = Field(default=None, min_length=1, max_length=50)
    transaction_type: Literal[
        "opening_balance",
        "purchase_receipt",
        "retailer_dispatch",
        "retail_sale",
        "customer_return",
        "supplier_return",
        "stock_adjustment",
        "damaged_writeoff",
        "expiry_writeoff",
    ] | None = None
    date_format: str | None = Field(default=None, min_length=2, max_length=50)
    date_convention: Literal["month_end"] | None = None
    transformation_rule: Literal["split_quantity_and_free"] | None = None

    @field_validator("source_column")
    @classmethod
    def validate_source_column(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("source_column must not be blank.")
        return value

    @field_validator("quantity_unit", "date_format", mode="before")
    @classmethod
    def trim_optional_text(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @model_validator(mode="after")
    def validate_choice_semantics(self) -> "ColumnMappingChoice":
        if (
            self.proposed_canonical_field is not None
            and self.proposed_canonical_field not in CANONICAL_FIELDS
        ):
            raise ValueError(
                f"Unsupported proposed canonical field: {self.proposed_canonical_field}"
            )

        if self.action == "ignore":
            if self.canonical_field is not None:
                raise ValueError("Ignored columns must not specify canonical_field.")
            if self.additional_canonical_fields:
                raise ValueError("Ignored columns must not specify additional canonical fields.")
            if any(
                value is not None
                for value in (
                    self.quantity_unit,
                    self.transaction_type,
                    self.date_format,
                    self.date_convention,
                    self.transformation_rule,
                )
            ):
                raise ValueError("Ignored columns must not specify mapping metadata.")
            return self

        if self.canonical_field not in CANONICAL_FIELDS:
            raise ValueError(
                f"Choose a supported canonical_field. Received: {self.canonical_field!r}"
            )
        for additional in self.additional_canonical_fields:
            if additional not in CANONICAL_FIELDS:
                raise ValueError(f"Unsupported additional canonical field: {additional}")
            if additional != "free_quantity":
                raise ValueError(
                    "Only free_quantity is currently supported as an additional target field."
                )
        if len(set(self.additional_canonical_fields)) != len(
            self.additional_canonical_fields
        ):
            raise ValueError("additional_canonical_fields must not contain duplicates.")

        if self.canonical_field in DATE_FIELDS and not self.date_format:
            raise ValueError(
                f"{self.canonical_field} requires an explicit date_format, such as MM/YY."
            )
        if self.date_format and self.canonical_field not in DATE_FIELDS:
            raise ValueError("date_format is only valid for a date canonical field.")
        if self.date_format and self.date_format not in SUPPORTED_DATE_FORMATS:
            raise ValueError(
                f"Unsupported date_format {self.date_format!r}. "
                f"Choose from: {', '.join(sorted(SUPPORTED_DATE_FORMATS))}."
            )

        if self.canonical_field == "expiry_date" and self.date_format in MONTH_YEAR_FORMATS:
            if self.date_convention != "month_end":
                raise ValueError(
                    "Expiry values containing only month/year require "
                    "date_convention='month_end' to make the convention explicit."
                )
        elif self.date_convention is not None:
            raise ValueError(
                "date_convention='month_end' is only valid for month/year expiry formats."
            )

        targets = {self.canonical_field, *self.additional_canonical_fields}
        if targets.intersection(QUANTITY_FIELDS) and not self.quantity_unit:
            raise ValueError(
                "Quantity/stock fields require quantity_unit, such as pack, strip, or tablet."
            )
        if self.canonical_field == "quantity" and not self.transaction_type:
            raise ValueError(
                "quantity requires transaction_type to identify the stock movement direction."
            )
        if self.transaction_type and self.canonical_field != "quantity":
            raise ValueError("transaction_type is only valid when canonical_field is quantity.")

        is_composite_qty_free = normalize_column_name(self.source_column) in {
            "qtyfree",
            "quantityfree",
        }
        if is_composite_qty_free and self.canonical_field == "quantity":
            if self.transformation_rule != "split_quantity_and_free":
                raise ValueError(
                    "QTY+FREE requires transformation_rule='split_quantity_and_free'."
                )
            if "free_quantity" not in self.additional_canonical_fields:
                raise ValueError(
                    "QTY+FREE must also map to free_quantity after explicit confirmation."
                )
        if self.transformation_rule:
            if not is_composite_qty_free:
                raise ValueError(
                    "split_quantity_and_free is only valid for a composite QTY+FREE column."
                )
            if self.canonical_field != "quantity" or "free_quantity" not in (
                self.additional_canonical_fields
            ):
                raise ValueError(
                    "split_quantity_and_free requires quantity plus additional free_quantity."
                )

        return self


class SchemaConfirmationRequest(BaseModel):
    """The complete set of profiling columns and user choices for one tabular file."""

    model_config = ConfigDict(extra="forbid")

    profiled_columns: list[ProfiledColumnReference] = Field(min_length=1, max_length=200)
    mappings: list[ColumnMappingChoice] = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def validate_complete_schema(self) -> "SchemaConfirmationRequest":
        profile_by_index = {
            column.column_index: column.source_column for column in self.profiled_columns
        }
        if len(profile_by_index) != len(self.profiled_columns):
            raise ValueError("profiled_columns contains duplicate column_index values.")
        if sorted(profile_by_index) != list(range(len(profile_by_index))):
            raise ValueError("profiled_columns indexes must be continuous and start at zero.")

        mapping_by_index = {mapping.column_index: mapping for mapping in self.mappings}
        if len(mapping_by_index) != len(self.mappings):
            raise ValueError("mappings contains duplicate column_index values.")
        if set(profile_by_index) != set(mapping_by_index):
            missing = sorted(set(profile_by_index) - set(mapping_by_index))
            extra = sorted(set(mapping_by_index) - set(profile_by_index))
            raise ValueError(
                f"Every profiled column needs exactly one decision. Missing indexes: {missing}; "
                f"unexpected indexes: {extra}."
            )

        targets: dict[str, str] = {}
        for index, mapping in mapping_by_index.items():
            expected_name = profile_by_index[index]
            if mapping.source_column != expected_name:
                raise ValueError(
                    f"Column index {index} is {expected_name!r}, not {mapping.source_column!r}."
                )
            if mapping.action == "ignore":
                continue
            for target in [mapping.canonical_field, *mapping.additional_canonical_fields]:
                if target in targets:
                    raise ValueError(
                        f"Canonical field {target!r} is mapped by both "
                        f"{targets[target]!r} and {mapping.source_column!r}. Resolve the conflict."
                    )
                targets[target] = mapping.source_column

        return self


def build_confirmation_response(request: SchemaConfirmationRequest) -> dict[str, Any]:
    """Summarize validated choices without persisting or transforming uploaded data."""
    results: list[dict[str, Any]] = []
    corrected_count = 0
    ignored_count = 0
    mapped_count = 0

    for mapping in sorted(request.mappings, key=lambda item: item.column_index):
        if mapping.action == "ignore":
            status = "ignored"
            origin = "user_ignored"
            ignored_count += 1
        else:
            mapped_count += 1
            if mapping.proposed_canonical_field is None:
                status = "confirmed"
                origin = "manual"
            elif mapping.proposed_canonical_field == mapping.canonical_field:
                status = "confirmed"
                origin = "suggestion_confirmed"
            else:
                status = "corrected"
                origin = "user_corrected"
                corrected_count += 1

        results.append(
            {
                "column_index": mapping.column_index,
                "source_column": mapping.source_column,
                "proposed_canonical_field": mapping.proposed_canonical_field,
                "canonical_field": mapping.canonical_field,
                "additional_canonical_fields": mapping.additional_canonical_fields,
                "mapping_status": status,
                "mapping_origin": origin,
                "quantity_unit": mapping.quantity_unit,
                "transaction_type": mapping.transaction_type,
                "date_format": mapping.date_format,
                "date_convention": mapping.date_convention,
                "transformation_rule": mapping.transformation_rule,
            }
        )

    warnings = [
        "This endpoint validates the submitted choices against the submitted profiling columns; it does not retrieve a stored profile.",
        "No file or schema mapping is persisted, and no data conversion or inventory analysis is executed by this endpoint.",
    ]
    if any(item["canonical_field"] in DATE_FIELDS for item in results if item["canonical_field"]):
        warnings.append(
            "Date formats are recorded as user choices; date values have not yet been parsed or normalized."
        )
    if any(
        item["canonical_field"] in QUANTITY_FIELDS or item["additional_canonical_fields"]
        for item in results
        if item["canonical_field"]
    ):
        warnings.append(
            "Units and movement types are recorded as metadata; no unit conversion or stock arithmetic has run."
        )
    if ignored_count:
        warnings.append(
            "One or more columns were explicitly ignored. Ensure those fields are not needed by a downstream analysis."
        )

    return {
        "schema_status": "confirmed",
        "persistence": "stateless_not_saved",
        "summary": {
            "profiled_column_count": len(request.profiled_columns),
            "mapped_column_count": mapped_count,
            "ignored_column_count": ignored_count,
            "corrected_suggestion_count": corrected_count,
        },
        "mappings": results,
        "warnings": warnings,
    }
