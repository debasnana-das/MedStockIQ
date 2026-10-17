"""Endpoints for canonical field discovery and explicit schema confirmation."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.security import AuthenticatedUser, get_current_principal

from app.schema.confirmation import (
    CANONICAL_FIELD_DESCRIPTIONS,
    DATE_FIELDS,
    QUANTITY_FIELDS,
    SchemaConfirmationRequest,
    build_confirmation_response,
)

router = APIRouter(prefix="/api/v1/schema", tags=["schema confirmation"])


@router.get("/fields")
def list_canonical_fields(
    principal: AuthenticatedUser = Depends(get_current_principal),
) -> dict:
    """Return canonical fields and the metadata needed when a user maps them."""
    fields = []
    for name, description in CANONICAL_FIELD_DESCRIPTIONS.items():
        requires: list[str] = []
        if name in DATE_FIELDS:
            requires.append("date_format")
        if name in QUANTITY_FIELDS:
            requires.append("quantity_unit")
        if name == "quantity":
            requires.append("transaction_type")
        fields.append(
            {
                "name": name,
                "description": description,
                "requires": requires,
            }
        )
    return {
        "fields": fields,
        "supported_transformation_rules": ["split_quantity_and_free"],
    }


@router.post("/confirm")
def confirm_schema(
    payload: SchemaConfirmationRequest,
    principal: AuthenticatedUser = Depends(get_current_principal),
) -> dict:
    """Validate explicit user choices for every column in a profiling response."""
    return build_confirmation_response(payload)
