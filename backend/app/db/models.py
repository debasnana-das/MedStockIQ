"""Persistent tables for normalization provenance and canonical output."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean, CheckConstraint, Date, DateTime, ForeignKey, ForeignKeyConstraint, Index, Integer, JSON,
    Numeric, String, Text, func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class NormalizationRun(Base):
    """One normalization attempt with its confirmed schema and outcome summary."""
    __tablename__ = "normalization_runs"
    run_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    organization_id: Mapped[str] = mapped_column(String(100), nullable=False)
    source_file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    source_format: Mapped[str] = mapped_column(String(20), nullable=False)
    source_file_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    document_type: Mapped[str] = mapped_column(String(40), nullable=False)
    normalization_status: Mapped[str] = mapped_column(String(40), nullable=False)
    input_row_count: Mapped[int] = mapped_column(Integer, nullable=False)
    confirmed_schema_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    options_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    summary_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    quality_report_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    __table_args__ = (Index("ix_normalization_runs_organization_id", "organization_id"),)


class NormalizedProduct(Base):
    """Product identity within one run; run-local IDs cannot collide across uploads."""
    __tablename__ = "normalized_products"
    run_id: Mapped[str] = mapped_column(
        ForeignKey("normalization_runs.run_id", ondelete="CASCADE"), primary_key=True
    )
    product_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    organization_id: Mapped[str] = mapped_column(String(100), nullable=False)
    source_product_code: Mapped[str | None] = mapped_column(String(200))
    product_name: Mapped[str | None] = mapped_column(String(500))
    manufacturer_name: Mapped[str | None] = mapped_column(String(300))
    hsn_code: Mapped[str | None] = mapped_column(String(100))
    pack_description: Mapped[str | None] = mapped_column(String(200))
    quantity_unit: Mapped[str | None] = mapped_column(String(50))
    units_per_pack: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    product_match_status: Mapped[str] = mapped_column(String(60), nullable=False)
    __table_args__ = (Index("ix_normalized_products_organization_id", "organization_id"),)


class NormalizedBatch(Base):
    """Batch metadata linked to a product from the same normalization run."""
    __tablename__ = "normalized_batches"
    __table_args__ = (
        ForeignKeyConstraint(
            ["run_id", "product_id"],
            ["normalized_products.run_id", "normalized_products.product_id"],
            ondelete="CASCADE",
        ),
        Index("ix_normalized_batches_organization_id", "organization_id"),
        Index("ix_normalized_batches_run_expiry", "run_id", "expiry_date"),
    )
    run_id: Mapped[str] = mapped_column(
        ForeignKey("normalization_runs.run_id", ondelete="CASCADE"), primary_key=True
    )
    batch_record_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    organization_id: Mapped[str] = mapped_column(String(100), nullable=False)
    product_id: Mapped[str] = mapped_column(String(40), nullable=False)
    batch_code: Mapped[str] = mapped_column(String(200), nullable=False)
    manufacturing_date: Mapped[date | None] = mapped_column(Date)
    expiry_raw: Mapped[str | None] = mapped_column(String(100))
    expiry_date: Mapped[date | None] = mapped_column(Date)
    expiry_date_precision: Mapped[str | None] = mapped_column(String(20))


class SourceDocument(Base):
    """Source-document metadata; uploaded file bytes are deliberately not stored."""
    __tablename__ = "source_documents"
    __table_args__ = (
        Index("ix_source_documents_organization_id", "organization_id"),
        Index("ix_source_documents_run_number", "run_id", "document_number"),
    )
    run_id: Mapped[str] = mapped_column(
        ForeignKey("normalization_runs.run_id", ondelete="CASCADE"), primary_key=True
    )
    document_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    organization_id: Mapped[str] = mapped_column(String(100), nullable=False)
    source_file_id: Mapped[str | None] = mapped_column(String(200))
    source_file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    document_type: Mapped[str] = mapped_column(String(40), nullable=False)
    document_number: Mapped[str | None] = mapped_column(String(200))
    document_date: Mapped[date | None] = mapped_column(Date)
    counterparty_id: Mapped[str | None] = mapped_column(String(200))
    currency_code: Mapped[str | None] = mapped_column(String(3))
    source_format: Mapped[str] = mapped_column(String(20), nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class InventoryTransaction(Base):
    """Transaction line tied to its document/product and optional batch from that run."""
    __tablename__ = "inventory_transactions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["run_id", "document_id"],
            ["source_documents.run_id", "source_documents.document_id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["run_id", "product_id"],
            ["normalized_products.run_id", "normalized_products.product_id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["run_id", "batch_record_id"],
            ["normalized_batches.run_id", "normalized_batches.batch_record_id"],
            ondelete="CASCADE",
        ),
        Index("ix_inventory_transactions_organization_id", "organization_id"),
        Index("ix_inventory_transactions_run_product_date", "run_id", "product_id", "transaction_date"),
        Index("ix_inventory_transactions_organization_date", "organization_id", "transaction_date"),
    )
    run_id: Mapped[str] = mapped_column(
        ForeignKey("normalization_runs.run_id", ondelete="CASCADE"), primary_key=True
    )
    transaction_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    organization_id: Mapped[str] = mapped_column(String(100), nullable=False)
    document_id: Mapped[str] = mapped_column(String(40), nullable=False)
    transaction_date: Mapped[date | None] = mapped_column(Date)
    transaction_type: Mapped[str] = mapped_column(String(50), nullable=False)
    product_id: Mapped[str] = mapped_column(String(40), nullable=False)
    batch_record_id: Mapped[str | None] = mapped_column(String(40))
    quantity: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    quantity_unit: Mapped[str | None] = mapped_column(String(50))
    free_quantity: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    effective_quantity: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    unit_rate: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    mrp: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    previous_mrp: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    discount_percent: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))
    discount_amount: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    secondary_discount: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    tax_rate: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))
    line_amount: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    tax_amount: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    line_total_amount: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    source_row_number: Mapped[int | None] = mapped_column(Integer)


class InventorySnapshot(Base):
    """On-hand stock observed at an explicitly identified date."""
    __tablename__ = "inventory_snapshots"
    __table_args__ = (
        ForeignKeyConstraint(
            ["run_id", "product_id"],
            ["normalized_products.run_id", "normalized_products.product_id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["run_id", "batch_record_id"],
            ["normalized_batches.run_id", "normalized_batches.batch_record_id"],
            ondelete="CASCADE",
        ),
        Index("ix_inventory_snapshots_organization_id", "organization_id"),
        Index("ix_inventory_snapshots_run_date_product", "run_id", "snapshot_date", "product_id"),
    )
    run_id: Mapped[str] = mapped_column(
        ForeignKey("normalization_runs.run_id", ondelete="CASCADE"), primary_key=True
    )
    snapshot_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    organization_id: Mapped[str] = mapped_column(String(100), nullable=False)
    snapshot_date: Mapped[date] = mapped_column(Date, nullable=False)
    product_id: Mapped[str] = mapped_column(String(40), nullable=False)
    batch_record_id: Mapped[str | None] = mapped_column(String(40))
    quantity_on_hand: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    quantity_unit: Mapped[str] = mapped_column(String(50), nullable=False)
    stock_basis: Mapped[str] = mapped_column(String(40), nullable=False, default="unknown")


class NormalizationIssue(Base):
    """A data-quality issue produced by normalization."""
    __tablename__ = "normalization_issues"
    __table_args__ = (Index("ix_normalization_issues_run_row", "run_id", "row_index"),)
    issue_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("normalization_runs.run_id", ondelete="CASCADE"), nullable=False
    )
    code: Mapped[str] = mapped_column(String(100), nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    row_index: Mapped[int | None] = mapped_column(Integer)
    source_column: Mapped[str | None] = mapped_column(String(200))
    canonical_field: Mapped[str | None] = mapped_column(String(100))
    message: Mapped[str] = mapped_column(Text, nullable=False)


class NormalizationTransformation(Base):
    """Traceable transformation applied to a source row."""
    __tablename__ = "normalization_transformations"
    __table_args__ = (Index("ix_normalization_transformations_run_row", "run_id", "row_index"),)
    transformation_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("normalization_runs.run_id", ondelete="CASCADE"), nullable=False
    )
    row_index: Mapped[int] = mapped_column(Integer, nullable=False)
    source_column: Mapped[str | None] = mapped_column(String(200))
    rule: Mapped[str] = mapped_column(String(100), nullable=False)
    targets_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)


class Organization(Base):
    """Organization or tenant that owns inventory data."""

    __tablename__ = "organizations"

    organization_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class UserAccount(Base):
    """Login identity; organization access is granted separately via memberships."""

    __tablename__ = "user_accounts"

    user_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    email: Mapped[str] = mapped_column(String(254), nullable=False, unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(500), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OrganizationMembership(Base):
    """Explicit per-user access to a single organization."""

    __tablename__ = "organization_memberships"
    __table_args__ = (
        Index("ix_organization_memberships_user_id", "user_id"),
        Index("ix_organization_memberships_organization_role", "organization_id", "role"),
        CheckConstraint("role IN ('owner', 'admin', 'member', 'viewer')", name="valid_role"),
    )

    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.organization_id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[str] = mapped_column(
        ForeignKey("user_accounts.user_id", ondelete="CASCADE"), primary_key=True
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
