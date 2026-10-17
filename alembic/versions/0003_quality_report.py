"""Persist deterministic data-quality and readiness reports.

Revision ID: 0003_quality_report
Revises: 0002_auth_tenants
"""
from alembic import op
import sqlalchemy as sa

revision = "0003_quality_report"
down_revision = "0002_auth_tenants"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("normalization_runs", sa.Column("quality_report_json", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("normalization_runs", "quality_report_json")
