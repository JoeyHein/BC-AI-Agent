"""nightly auto-PO: snapshot table + POAgentLog allocation columns

Revision ID: n4o5p6q7r8s9
Revises: l2g3h4i5j6k7
Create Date: 2026-08-31

Adds:
  * auto_po_snapshot — per-open-SO-line watermark so the nightly job acts
    only on new committed demand and never drafts the same line twice.
  * po_agent_log.is_auto / so_allocations / bc_status — mark and describe
    the POs the nightly job drafts straight into BC (Draft, never emailed),
    including which sales orders each line was bought for.

Offline-safe / deterministic — no BC calls, no backfill. Existing
po_agent_log rows get is_auto=False and NULL allocations, which is correct
(they were all created by hand through the tool).
"""
from alembic import op
import sqlalchemy as sa


revision = "n4o5p6q7r8s9"
down_revision = "l2g3h4i5j6k7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "auto_po_snapshot",
        sa.Column("so_number", sa.String(length=50), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("item_no", sa.String(length=50), nullable=False),
        sa.Column("outstanding_seen", sa.Float(), nullable=False, server_default="0"),
        sa.Column("covered_qty", sa.Float(), nullable=False, server_default="0"),
        sa.Column("first_seen_at", sa.DateTime(), nullable=False,
                  server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("last_seen_at", sa.DateTime(), nullable=False,
                  server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("last_run_id", sa.String(length=50), nullable=True),
        sa.PrimaryKeyConstraint("so_number", "sequence"),
    )
    op.create_index("ix_auto_po_snapshot_item_no", "auto_po_snapshot", ["item_no"])

    op.add_column(
        "po_agent_log",
        sa.Column("is_auto", sa.Boolean(), nullable=False, server_default="0"),
    )
    op.add_column("po_agent_log", sa.Column("so_allocations", sa.JSON(), nullable=True))
    op.add_column("po_agent_log", sa.Column("bc_status", sa.String(length=20), nullable=True))


def downgrade() -> None:
    op.drop_column("po_agent_log", "bc_status")
    op.drop_column("po_agent_log", "so_allocations")
    op.drop_column("po_agent_log", "is_auto")
    op.drop_index("ix_auto_po_snapshot_item_no", table_name="auto_po_snapshot")
    op.drop_table("auto_po_snapshot")
