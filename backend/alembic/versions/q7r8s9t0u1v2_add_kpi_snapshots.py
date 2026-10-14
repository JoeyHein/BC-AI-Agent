"""Store nightly and frozen monthly KPI snapshots

Revision ID: q7r8s9t0u1v2
Revises: p6q7r8s9t0u1
Create Date: 2026-10-14

The staff dashboard reads this table instead of calling Business Central
on each page load.
"""
from alembic import op
import sqlalchemy as sa


revision = "q7r8s9t0u1v2"
down_revision = "p6q7r8s9t0u1"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "kpi_snapshots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("month_key", sa.String(length=7), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("frozen", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="missing"),
        sa.Column("generated_at", sa.DateTime(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column("trace", sa.JSON(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_kpi_snapshots_month_key", "kpi_snapshots", ["month_key"], unique=True)


def downgrade():
    op.drop_index("ix_kpi_snapshots_month_key", table_name="kpi_snapshots")
    op.drop_table("kpi_snapshots")
