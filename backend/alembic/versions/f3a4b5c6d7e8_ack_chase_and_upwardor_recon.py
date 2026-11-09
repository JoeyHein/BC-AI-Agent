"""Promised dates, ack snooze, and stored Upwardor reconciliations.

Revision ID: f3a4b5c6d7e8
Revises: e1f2a3b4c5d7
Create Date: 2026-11-09

The order tracker already holds purchase orders and the approval queue.
These columns are the dates and the snooze the chase rules read, plus one
table per Upwardor open-order comparison.
"""
from alembic import op
import sqlalchemy as sa


revision = "f3a4b5c6d7e8"
down_revision = "e1f2a3b4c5d7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("ops_tracked_orders", sa.Column("promised_date", sa.Date(), nullable=True))
    op.add_column("ops_tracked_orders", sa.Column("shipment_date", sa.Date(), nullable=True))
    op.add_column("ops_tracked_pos", sa.Column("ack_snooze_until", sa.Date(), nullable=True))
    op.create_table(
        "upwardor_recon_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column("created_by_email", sa.String(255), nullable=True),
        sa.Column("source", sa.String(20), nullable=False),
        sa.Column("filename", sa.String(255), nullable=True),
        sa.Column("column_map_json", sa.JSON(), nullable=True),
        sa.Column("row_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("exceptions_json", sa.JSON(), nullable=True),
        sa.Column("summary_json", sa.JSON(), nullable=True),
        sa.Column("comparison_json", sa.JSON(), nullable=True),
        sa.Column("previous_run_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["previous_run_id"], ["upwardor_recon_runs.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_upwardor_recon_runs_created_at", "upwardor_recon_runs", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_upwardor_recon_runs_created_at", table_name="upwardor_recon_runs")
    op.drop_table("upwardor_recon_runs")
    op.drop_column("ops_tracked_pos", "ack_snooze_until")
    op.drop_column("ops_tracked_orders", "shipment_date")
    op.drop_column("ops_tracked_orders", "promised_date")
