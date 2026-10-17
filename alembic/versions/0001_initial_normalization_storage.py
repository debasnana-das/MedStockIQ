"""Create normalization run and canonical entity storage.

Revision ID: 0001_initial
Revises:
"""

from alembic import op
import sqlalchemy as sa

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "normalization_runs",
        sa.Column("run_id", sa.String(36), nullable=False),
        sa.Column("organization_id", sa.String(100), nullable=False),
        sa.Column("source_file_name", sa.String(255), nullable=False),
        sa.Column("source_format", sa.String(20), nullable=False),
        sa.Column("source_file_bytes", sa.Integer(), nullable=False),
        sa.Column("document_type", sa.String(40), nullable=False),
        sa.Column("normalization_status", sa.String(40), nullable=False),
        sa.Column("input_row_count", sa.Integer(), nullable=False),
        sa.Column("confirmed_schema_json", sa.JSON(), nullable=False),
        sa.Column("options_json", sa.JSON(), nullable=False),
        sa.Column("summary_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.PrimaryKeyConstraint("run_id", name="pk_normalization_runs"),
    )
    op.create_index("ix_normalization_runs_organization_id", "normalization_runs", ["organization_id"])

    op.create_table(
        "normalized_products",
        sa.Column("run_id", sa.String(36), nullable=False),
        sa.Column("product_id", sa.String(40), nullable=False),
        sa.Column("organization_id", sa.String(100), nullable=False),
        sa.Column("source_product_code", sa.String(200)),
        sa.Column("product_name", sa.String(500)),
        sa.Column("manufacturer_name", sa.String(300)),
        sa.Column("hsn_code", sa.String(100)),
        sa.Column("pack_description", sa.String(200)),
        sa.Column("quantity_unit", sa.String(50)),
        sa.Column("units_per_pack", sa.Numeric(20, 6)),
        sa.Column("product_match_status", sa.String(60), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["normalization_runs.run_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("run_id", "product_id", name="pk_normalized_products"),
    )
    op.create_index("ix_normalized_products_organization_id", "normalized_products", ["organization_id"])

    op.create_table(
        "normalized_batches",
        sa.Column("run_id", sa.String(36), nullable=False),
        sa.Column("batch_record_id", sa.String(40), nullable=False),
        sa.Column("organization_id", sa.String(100), nullable=False),
        sa.Column("product_id", sa.String(40), nullable=False),
        sa.Column("batch_code", sa.String(200), nullable=False),
        sa.Column("manufacturing_date", sa.Date()),
        sa.Column("expiry_raw", sa.String(100)),
        sa.Column("expiry_date", sa.Date()),
        sa.Column("expiry_date_precision", sa.String(20)),
        sa.ForeignKeyConstraint(["run_id"], ["normalization_runs.run_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["run_id", "product_id"], ["normalized_products.run_id", "normalized_products.product_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("run_id", "batch_record_id", name="pk_normalized_batches"),
    )
    op.create_index("ix_normalized_batches_organization_id", "normalized_batches", ["organization_id"])
    op.create_index("ix_normalized_batches_run_expiry", "normalized_batches", ["run_id", "expiry_date"])

    op.create_table(
        "source_documents",
        sa.Column("run_id", sa.String(36), nullable=False),
        sa.Column("document_id", sa.String(40), nullable=False),
        sa.Column("organization_id", sa.String(100), nullable=False),
        sa.Column("source_file_id", sa.String(200)),
        sa.Column("source_file_name", sa.String(255), nullable=False),
        sa.Column("document_type", sa.String(40), nullable=False),
        sa.Column("document_number", sa.String(200)),
        sa.Column("document_date", sa.Date()),
        sa.Column("counterparty_id", sa.String(200)),
        sa.Column("currency_code", sa.String(3)),
        sa.Column("source_format", sa.String(20), nullable=False),
        sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["normalization_runs.run_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("run_id", "document_id", name="pk_source_documents"),
    )
    op.create_index("ix_source_documents_organization_id", "source_documents", ["organization_id"])
    op.create_index("ix_source_documents_run_number", "source_documents", ["run_id", "document_number"])

    op.create_table(
        "inventory_transactions",
        sa.Column("run_id", sa.String(36), nullable=False),
        sa.Column("transaction_id", sa.String(40), nullable=False),
        sa.Column("organization_id", sa.String(100), nullable=False),
        sa.Column("document_id", sa.String(40), nullable=False),
        sa.Column("transaction_date", sa.Date()),
        sa.Column("transaction_type", sa.String(50), nullable=False),
        sa.Column("product_id", sa.String(40), nullable=False),
        sa.Column("batch_record_id", sa.String(40)),
        sa.Column("quantity", sa.Numeric(20, 6), nullable=False),
        sa.Column("quantity_unit", sa.String(50)),
        sa.Column("free_quantity", sa.Numeric(20, 6)),
        sa.Column("effective_quantity", sa.Numeric(20, 6)),
        sa.Column("unit_rate", sa.Numeric(20, 6)),
        sa.Column("mrp", sa.Numeric(20, 6)),
        sa.Column("previous_mrp", sa.Numeric(20, 6)),
        sa.Column("discount_percent", sa.Numeric(12, 6)),
        sa.Column("discount_amount", sa.Numeric(20, 6)),
        sa.Column("secondary_discount", sa.Numeric(20, 6)),
        sa.Column("tax_rate", sa.Numeric(12, 6)),
        sa.Column("line_amount", sa.Numeric(20, 6)),
        sa.Column("tax_amount", sa.Numeric(20, 6)),
        sa.Column("line_total_amount", sa.Numeric(20, 6)),
        sa.Column("source_row_number", sa.Integer()),
        sa.ForeignKeyConstraint(["run_id"], ["normalization_runs.run_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["run_id", "document_id"], ["source_documents.run_id", "source_documents.document_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["run_id", "product_id"], ["normalized_products.run_id", "normalized_products.product_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["run_id", "batch_record_id"], ["normalized_batches.run_id", "normalized_batches.batch_record_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("run_id", "transaction_id", name="pk_inventory_transactions"),
    )
    op.create_index("ix_inventory_transactions_organization_id", "inventory_transactions", ["organization_id"])
    op.create_index("ix_inventory_transactions_run_product_date", "inventory_transactions", ["run_id", "product_id", "transaction_date"])
    op.create_index("ix_inventory_transactions_organization_date", "inventory_transactions", ["organization_id", "transaction_date"])

    op.create_table(
        "inventory_snapshots",
        sa.Column("run_id", sa.String(36), nullable=False),
        sa.Column("snapshot_id", sa.String(40), nullable=False),
        sa.Column("organization_id", sa.String(100), nullable=False),
        sa.Column("snapshot_date", sa.Date(), nullable=False),
        sa.Column("product_id", sa.String(40), nullable=False),
        sa.Column("batch_record_id", sa.String(40)),
        sa.Column("quantity_on_hand", sa.Numeric(20, 6), nullable=False),
        sa.Column("quantity_unit", sa.String(50), nullable=False),
        sa.Column("stock_basis", sa.String(40), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["normalization_runs.run_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["run_id", "product_id"], ["normalized_products.run_id", "normalized_products.product_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["run_id", "batch_record_id"], ["normalized_batches.run_id", "normalized_batches.batch_record_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("run_id", "snapshot_id", name="pk_inventory_snapshots"),
    )
    op.create_index("ix_inventory_snapshots_organization_id", "inventory_snapshots", ["organization_id"])
    op.create_index("ix_inventory_snapshots_run_date_product", "inventory_snapshots", ["run_id", "snapshot_date", "product_id"])

    op.create_table(
        "normalization_issues",
        sa.Column("issue_id", sa.String(36), nullable=False),
        sa.Column("run_id", sa.String(36), nullable=False),
        sa.Column("code", sa.String(100), nullable=False),
        sa.Column("severity", sa.String(20), nullable=False),
        sa.Column("row_index", sa.Integer()),
        sa.Column("source_column", sa.String(200)),
        sa.Column("canonical_field", sa.String(100)),
        sa.Column("message", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["normalization_runs.run_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("issue_id", name="pk_normalization_issues"),
    )
    op.create_index("ix_normalization_issues_run_row", "normalization_issues", ["run_id", "row_index"])

    op.create_table(
        "normalization_transformations",
        sa.Column("transformation_id", sa.String(36), nullable=False),
        sa.Column("run_id", sa.String(36), nullable=False),
        sa.Column("row_index", sa.Integer(), nullable=False),
        sa.Column("source_column", sa.String(200)),
        sa.Column("rule", sa.String(100), nullable=False),
        sa.Column("targets_json", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["normalization_runs.run_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("transformation_id", name="pk_normalization_transformations"),
    )
    op.create_index("ix_normalization_transformations_run_row", "normalization_transformations", ["run_id", "row_index"])


def downgrade() -> None:
    op.drop_table("normalization_transformations")
    op.drop_table("normalization_issues")
    op.drop_table("inventory_snapshots")
    op.drop_table("inventory_transactions")
    op.drop_table("source_documents")
    op.drop_table("normalized_batches")
    op.drop_table("normalized_products")
    op.drop_table("normalization_runs")
