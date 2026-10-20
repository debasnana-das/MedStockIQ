"""Atomic writes and organization-scoped reads for normalization runs."""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    InventorySnapshot, InventoryTransaction, NormalizationIssue, NormalizationRun,
    NormalizationTransformation, NormalizedBatch, NormalizedProduct, SourceDocument,
)
from app.normalization.normalizer import NormalizationOptions
from app.schema.confirmation import SchemaConfirmationRequest


def _as_date(value: Any) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def _as_datetime(value: Any) -> datetime:
    if value is None or value == "":
        return datetime.now(timezone.utc)
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _as_decimal(value: Any) -> Decimal | None:
    return None if value is None or value == "" else Decimal(str(value))


def persist_normalization_result(
    session: Session,
    result: dict[str, Any],
    confirmed_schema: SchemaConfirmationRequest,
    options: NormalizationOptions,
    source_file_name: str,
    source_format: str,
    source_file_bytes: int,
) -> str:
    """Save a complete normalization result in one transaction; return its UUID.

    Uploaded bytes are never stored. Run-scoped canonical IDs cannot collide across
    uploads, and database constraints enforce references within the same run.
    """
    run_id = str(uuid4())
    tables = result.get("tables", {})
    # Organization checks may already have opened a request transaction. Use a
    # savepoint inside that transaction; otherwise own a transaction for direct callers.
    transaction = session.begin_nested() if session.in_transaction() else session.begin()
    with transaction:
        session.add(
            NormalizationRun(
                run_id=run_id,
                organization_id=options.organization_id,
                source_file_name=source_file_name,
                source_format=source_format,
                source_file_bytes=source_file_bytes,
                document_type=options.document_type,
                normalization_status=result.get("normalization_status", "unknown"),
                input_row_count=int(result.get("input_row_count", 0)),
                confirmed_schema_json=confirmed_schema.model_dump(mode="json"),
                options_json=options.model_dump(mode="json"),
                summary_json=dict(result.get("summary", {})),
                quality_report_json=result.get("quality_report"),
            )
        )
        session.flush()

        session.add_all([
            NormalizedProduct(
                run_id=run_id, product_id=row["product_id"],
                organization_id=row["organization_id"],
                source_product_code=row.get("source_product_code"),
                product_name=row.get("product_name"), manufacturer_name=row.get("manufacturer_name"),
                hsn_code=row.get("hsn_code"), pack_description=row.get("pack_description"),
                quantity_unit=row.get("quantity_unit"),
                units_per_pack=_as_decimal(row.get("units_per_pack")),
                product_match_status=row.get("product_match_status", "unknown"),
            )
            for row in tables.get("products", [])
        ])
        session.flush()

        session.add_all([
            NormalizedBatch(
                run_id=run_id, batch_record_id=row["batch_record_id"],
                organization_id=row["organization_id"], product_id=row["product_id"],
                batch_code=row["batch_code"],
                manufacturing_date=_as_date(row.get("manufacturing_date")),
                expiry_raw=row.get("expiry_raw"), expiry_date=_as_date(row.get("expiry_date")),
                expiry_date_precision=row.get("expiry_date_precision"),
            )
            for row in tables.get("batches", [])
        ])
        session.flush()

        session.add_all([
            SourceDocument(
                run_id=run_id, document_id=row["document_id"],
                organization_id=row["organization_id"], source_file_id=row.get("source_file_id"),
                source_file_name=row.get("source_file_name", source_file_name),
                document_type=row.get("document_type", options.document_type),
                document_number=row.get("document_number"),
                document_date=_as_date(row.get("document_date")),
                counterparty_id=row.get("counterparty_id"), currency_code=row.get("currency_code"),
                source_format=row.get("source_format", source_format),
                ingested_at=_as_datetime(row.get("ingested_at")),
            )
            for row in tables.get("source_documents", [])
        ])
        session.flush()

        session.add_all([
            InventoryTransaction(
                run_id=run_id, transaction_id=row["transaction_id"],
                organization_id=row["organization_id"], document_id=row["document_id"],
                transaction_date=_as_date(row.get("transaction_date")),
                transaction_type=row.get("transaction_type", "unknown"),
                product_id=row["product_id"], batch_record_id=row.get("batch_record_id"),
                quantity=_as_decimal(row.get("quantity")) or Decimal("0"),
                quantity_unit=row.get("quantity_unit"),
                free_quantity=_as_decimal(row.get("free_quantity")),
                effective_quantity=_as_decimal(row.get("effective_quantity")),
                unit_rate=_as_decimal(row.get("unit_rate")), mrp=_as_decimal(row.get("mrp")),
                previous_mrp=_as_decimal(row.get("previous_mrp")),
                discount_percent=_as_decimal(row.get("discount_percent")),
                discount_amount=_as_decimal(row.get("discount_amount")),
                secondary_discount=_as_decimal(row.get("secondary_discount")),
                tax_rate=_as_decimal(row.get("tax_rate")), line_amount=_as_decimal(row.get("line_amount")),
                tax_amount=_as_decimal(row.get("tax_amount")),
                line_total_amount=_as_decimal(row.get("line_total_amount")),
                source_row_number=row.get("source_row_number"),
            )
            for row in tables.get("transactions", [])
        ])
        session.flush()

        session.add_all([
            InventorySnapshot(
                run_id=run_id, snapshot_id=row["snapshot_id"],
                organization_id=row["organization_id"],
                snapshot_date=_as_date(row.get("snapshot_date")), product_id=row["product_id"],
                batch_record_id=row.get("batch_record_id"),
                quantity_on_hand=_as_decimal(row.get("quantity_on_hand")) or Decimal("0"),
                quantity_unit=row["quantity_unit"], stock_basis=row.get("stock_basis", "unknown"),
            )
            for row in tables.get("inventory_snapshots", [])
        ])
        session.add_all([
            NormalizationIssue(
                issue_id=str(uuid4()), run_id=run_id, code=row.get("code", "unknown"),
                severity=row.get("severity", "warning"), row_index=row.get("row_index"),
                source_column=row.get("source_column"), canonical_field=row.get("canonical_field"),
                message=row.get("message", ""),
            )
            for row in result.get("issues", [])
        ])
        session.add_all([
            NormalizationTransformation(
                transformation_id=str(uuid4()), run_id=run_id,
                row_index=int(row.get("row_index", 0)), source_column=row.get("source_column"),
                rule=row.get("rule", "unknown"), targets_json=list(row.get("targets", [])),
            )
            for row in result.get("transformations", [])
        ])
        session.flush()
    return run_id


def _number(value: Decimal | None) -> float | None:
    return float(value) if value is not None else None


def _product_json(row: NormalizedProduct) -> dict[str, Any]:
    return {
        "product_id": row.product_id, "organization_id": row.organization_id,
        "source_product_code": row.source_product_code, "product_name": row.product_name,
        "manufacturer_name": row.manufacturer_name, "hsn_code": row.hsn_code,
        "pack_description": row.pack_description, "quantity_unit": row.quantity_unit,
        "units_per_pack": _number(row.units_per_pack), "product_match_status": row.product_match_status,
    }


def _batch_json(row: NormalizedBatch) -> dict[str, Any]:
    return {
        "batch_record_id": row.batch_record_id, "organization_id": row.organization_id,
        "product_id": row.product_id, "batch_code": row.batch_code,
        "manufacturing_date": row.manufacturing_date.isoformat() if row.manufacturing_date else None,
        "expiry_raw": row.expiry_raw,
        "expiry_date": row.expiry_date.isoformat() if row.expiry_date else None,
        "expiry_date_precision": row.expiry_date_precision,
    }


def _document_json(row: SourceDocument) -> dict[str, Any]:
    return {
        "document_id": row.document_id, "organization_id": row.organization_id,
        "source_file_id": row.source_file_id, "source_file_name": row.source_file_name,
        "document_type": row.document_type, "document_number": row.document_number,
        "document_date": row.document_date.isoformat() if row.document_date else None,
        "counterparty_id": row.counterparty_id, "currency_code": row.currency_code,
        "source_format": row.source_format, "ingested_at": row.ingested_at.isoformat(),
    }


def _transaction_json(row: InventoryTransaction) -> dict[str, Any]:
    return {
        "transaction_id": row.transaction_id, "organization_id": row.organization_id,
        "document_id": row.document_id,
        "transaction_date": row.transaction_date.isoformat() if row.transaction_date else None,
        "transaction_type": row.transaction_type, "product_id": row.product_id,
        "batch_record_id": row.batch_record_id, "quantity": _number(row.quantity),
        "quantity_unit": row.quantity_unit, "free_quantity": _number(row.free_quantity),
        "effective_quantity": _number(row.effective_quantity), "unit_rate": _number(row.unit_rate),
        "mrp": _number(row.mrp), "previous_mrp": _number(row.previous_mrp),
        "discount_percent": _number(row.discount_percent), "discount_amount": _number(row.discount_amount),
        "secondary_discount": _number(row.secondary_discount), "tax_rate": _number(row.tax_rate),
        "line_amount": _number(row.line_amount), "tax_amount": _number(row.tax_amount),
        "line_total_amount": _number(row.line_total_amount), "source_row_number": row.source_row_number,
    }


def _snapshot_json(row: InventorySnapshot) -> dict[str, Any]:
    return {
        "snapshot_id": row.snapshot_id, "organization_id": row.organization_id,
        "snapshot_date": row.snapshot_date.isoformat(), "product_id": row.product_id,
        "batch_record_id": row.batch_record_id, "quantity_on_hand": _number(row.quantity_on_hand),
        "quantity_unit": row.quantity_unit, "stock_basis": row.stock_basis,
    }


def get_persisted_normalization_preview(
    session: Session, run_id: str, organization_id: str,
    preview_limit: int = 10, issue_limit: int = 50,
) -> dict[str, Any] | None:
    """Return a saved run only for matching organization_id; this is not authentication."""
    run = session.scalar(select(NormalizationRun).where(
        NormalizationRun.run_id == run_id,
        NormalizationRun.organization_id == organization_id,
    ))
    if run is None:
        return None

    def fetch(model: Any, order_by: Any) -> list[Any]:
        return list(session.scalars(
            select(model).where(model.run_id == run_id).order_by(order_by).limit(preview_limit)
        ))

    products = fetch(NormalizedProduct, NormalizedProduct.product_id)
    batches = fetch(NormalizedBatch, NormalizedBatch.batch_record_id)
    documents = fetch(SourceDocument, SourceDocument.document_id)
    transactions = fetch(InventoryTransaction, InventoryTransaction.transaction_id)
    snapshots = fetch(InventorySnapshot, InventorySnapshot.snapshot_id)
    issues = list(session.scalars(
        select(NormalizationIssue).where(NormalizationIssue.run_id == run_id)
        .order_by(NormalizationIssue.row_index, NormalizationIssue.issue_id).limit(issue_limit)
    ))
    transformations = list(session.scalars(
        select(NormalizationTransformation).where(NormalizationTransformation.run_id == run_id)
        .order_by(NormalizationTransformation.row_index, NormalizationTransformation.transformation_id)
        .limit(issue_limit)
    ))

    return {
        "normalization_run_id": run.run_id, "organization_id": run.organization_id,
        "source_file_name": run.source_file_name, "source_format": run.source_format,
        "source_file_bytes": run.source_file_bytes, "document_type": run.document_type,
        "normalization_status": run.normalization_status, "persistence": "saved_to_postgresql",
        "created_at": run.created_at.isoformat() if run.created_at else None,
        "summary": run.summary_json,
        "quality_report": run.quality_report_json,
        "previews": {
            "products": [_product_json(row) for row in products],
            "batches": [_batch_json(row) for row in batches],
            "source_documents": [_document_json(row) for row in documents],
            "transactions": [_transaction_json(row) for row in transactions],
            "inventory_snapshots": [_snapshot_json(row) for row in snapshots],
        },
        "issues_preview": [
            {"code": row.code, "severity": row.severity, "row_index": row.row_index,
             "source_column": row.source_column, "canonical_field": row.canonical_field,
             "message": row.message}
            for row in issues
        ],
        "transformations_preview": [
            {"row_index": row.row_index, "source_column": row.source_column,
             "rule": row.rule, "targets": row.targets_json}
            for row in transformations
        ],
        "issue_preview_truncated": int(run.summary_json.get("issue_count", 0)) > len(issues),
        "transformation_preview_truncated": int(run.summary_json.get("transformation_count", 0)) > len(transformations),
    }


def get_persisted_inventory_history_observations(
    session: Session,
    organization_id: str,
    *,
    as_of_date: date,
    start_date: date | None = None,
    end_date: date | None = None,
    row_limit: int = 20_000,
    document_type: str | None = None,
) -> tuple[list[dict[str, Any]], bool]:
    """Read cross-run snapshot evidence for one tenant, with an explicit safety cap.

    The returned identifiers remain run-scoped. This query returns product/batch
    attributes needed by the pure ledger policy; it never updates or links records.
    The boolean is true when more rows exist than the requested cap.
    """
    statement = (
        select(
            InventorySnapshot.run_id.label("run_id"),
            InventorySnapshot.snapshot_id.label("snapshot_id"),
            InventorySnapshot.organization_id.label("organization_id"),
            InventorySnapshot.snapshot_date.label("snapshot_date"),
            InventorySnapshot.product_id.label("product_id"),
            InventorySnapshot.batch_record_id.label("batch_record_id"),
            InventorySnapshot.quantity_on_hand.label("quantity_on_hand"),
            InventorySnapshot.quantity_unit.label("quantity_unit"),
            InventorySnapshot.stock_basis.label("stock_basis"),
            NormalizedProduct.source_product_code.label("source_product_code"),
            NormalizedProduct.product_name.label("product_name"),
            NormalizedProduct.manufacturer_name.label("manufacturer_name"),
            NormalizedProduct.hsn_code.label("hsn_code"),
            NormalizedProduct.pack_description.label("pack_description"),
            NormalizedBatch.batch_code.label("batch_code"),
            NormalizedBatch.expiry_date.label("expiry_date"),
            NormalizedBatch.manufacturing_date.label("manufacturing_date"),
            NormalizationRun.source_file_name.label("source_file_name"),
            NormalizationRun.document_type.label("document_type"),
            NormalizationRun.options_json.label("run_options"),
        )
        .select_from(InventorySnapshot)
        .join(
            NormalizationRun,
            NormalizationRun.run_id == InventorySnapshot.run_id,
        )
        .join(
            NormalizedProduct,
            (NormalizedProduct.run_id == InventorySnapshot.run_id)
            & (NormalizedProduct.product_id == InventorySnapshot.product_id),
        )
        .outerjoin(
            NormalizedBatch,
            (NormalizedBatch.run_id == InventorySnapshot.run_id)
            & (NormalizedBatch.batch_record_id == InventorySnapshot.batch_record_id),
        )
        .where(
            InventorySnapshot.organization_id == organization_id,
            NormalizationRun.organization_id == organization_id,
            NormalizedProduct.organization_id == organization_id,
            InventorySnapshot.snapshot_date <= as_of_date,
        )
    )
    if document_type is not None:
        statement = statement.where(NormalizationRun.document_type == document_type)
    if start_date is not None:
        statement = statement.where(InventorySnapshot.snapshot_date >= start_date)
    if end_date is not None:
        statement = statement.where(InventorySnapshot.snapshot_date <= end_date)

    rows = list(session.execute(
        statement.order_by(
            InventorySnapshot.snapshot_date.asc(),
            InventorySnapshot.run_id.asc(),
            InventorySnapshot.snapshot_id.asc(),
        ).limit(row_limit + 1)
    ).mappings())
    truncated = len(rows) > row_limit
    observations = []
    for row in rows[:row_limit]:
        observations.append({
            "run_id": row["run_id"],
            "snapshot_id": row["snapshot_id"],
            "organization_id": row["organization_id"],
            "snapshot_date": row["snapshot_date"].isoformat() if row["snapshot_date"] else None,
            "product_id": row["product_id"],
            "batch_record_id": row["batch_record_id"],
            "quantity_on_hand": _number(row["quantity_on_hand"]),
            "quantity_unit": row["quantity_unit"],
            "stock_basis": row["stock_basis"],
            "source_product_code": row["source_product_code"],
            "product_name": row["product_name"],
            "manufacturer_name": row["manufacturer_name"],
            "hsn_code": row["hsn_code"],
            "pack_description": row["pack_description"],
            "batch_code": row["batch_code"],
            "expiry_date": row["expiry_date"].isoformat() if row["expiry_date"] else None,
            "manufacturing_date": (
                row["manufacturing_date"].isoformat() if row["manufacturing_date"] else None
            ),
            "source_file_name": row["source_file_name"],
            "document_type": row["document_type"],
            "inventory_snapshot_complete": bool(
                (row["run_options"] or {}).get("inventory_snapshot_complete", False)
            ),
        })
    return observations, truncated


def get_persisted_overstock_sales_run(
    session: Session, organization_id: str, run_id: str,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    """Read one selected sales run after matching its tenant."""
    run = session.scalar(select(NormalizationRun).where(
        NormalizationRun.run_id == run_id,
        NormalizationRun.organization_id == organization_id,
    ))
    if run is None:
        return None, []
    statement = (
        select(
            InventoryTransaction.run_id.label("run_id"),
            InventoryTransaction.transaction_id.label("transaction_id"),
            InventoryTransaction.transaction_date.label("transaction_date"),
            InventoryTransaction.transaction_type.label("transaction_type"),
            InventoryTransaction.product_id.label("product_id"),
            InventoryTransaction.batch_record_id.label("batch_record_id"),
            InventoryTransaction.quantity.label("quantity"),
            InventoryTransaction.effective_quantity.label("effective_quantity"),
            InventoryTransaction.free_quantity.label("free_quantity"),
            InventoryTransaction.quantity_unit.label("quantity_unit"),
            InventoryTransaction.source_row_number.label("source_row_number"),
            NormalizedProduct.source_product_code.label("source_product_code"),
            NormalizedProduct.product_name.label("product_name"),
            NormalizedProduct.manufacturer_name.label("manufacturer_name"),
            NormalizedProduct.hsn_code.label("hsn_code"),
            NormalizedProduct.pack_description.label("pack_description"),
        )
        .select_from(InventoryTransaction)
        .join(
            NormalizedProduct,
            (NormalizedProduct.run_id == InventoryTransaction.run_id)
            & (NormalizedProduct.product_id == InventoryTransaction.product_id),
        )
        .where(
            InventoryTransaction.run_id == run_id,
            InventoryTransaction.organization_id == organization_id,
            NormalizedProduct.organization_id == organization_id,
        )
        .order_by(InventoryTransaction.source_row_number, InventoryTransaction.transaction_id)
    )
    sales_rows = []
    for row in session.execute(statement).mappings():
        sales_rows.append({
            "run_id": row["run_id"],
            "transaction_id": row["transaction_id"],
            "transaction_date": row["transaction_date"].isoformat() if row["transaction_date"] else None,
            "transaction_type": row["transaction_type"],
            "product_id": row["product_id"],
            "batch_record_id": row["batch_record_id"],
            "quantity": _number(row["quantity"]),
            "effective_quantity": _number(row["effective_quantity"]),
            "free_quantity": _number(row["free_quantity"]),
            "quantity_unit": row["quantity_unit"],
            "source_row_number": row["source_row_number"],
            "source_product_code": row["source_product_code"],
            "product_name": row["product_name"],
            "manufacturer_name": row["manufacturer_name"],
            "hsn_code": row["hsn_code"],
            "pack_description": row["pack_description"],
        })
    return {
        "run_id": run.run_id,
        "organization_id": run.organization_id,
        "document_type": run.document_type,
        "source_file_name": run.source_file_name,
        "options": dict(run.options_json or {}),
    }, sales_rows
