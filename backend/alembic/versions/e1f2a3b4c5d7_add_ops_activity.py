"""Activity log for purchasing notes and tracker events.

Revision ID: e1f2a3b4c5d7
Revises: d0e1f2a3b4c6
Create Date: 2026-11-03

Notes and automatic events live in the portal. Sales orders and purchase
orders stay in Business Central.
"""
from alembic import op
import sqlalchemy as sa


revision = "e1f2a3b4c5d7"
down_revision = "d0e1f2a3b4c6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ops_activity",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("so_number", sa.String(50), nullable=True),
        sa.Column("po_number", sa.String(40), nullable=True),
        sa.Column("vendor_number", sa.String(40), nullable=True),
        sa.Column("vendor_name", sa.String(255), nullable=True),
        sa.Column("event_type", sa.String(40), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("dedupe_key", sa.String(200), nullable=True),
        sa.Column("follow_up_on", sa.Date(), nullable=True),
        sa.Column("action_id", sa.Integer(), nullable=True),
        sa.Column("actor_user_id", sa.Integer(), nullable=True),
        sa.Column("actor_email", sa.String(255), nullable=True),
        sa.Column("direction", sa.String(20), nullable=True),
        sa.Column("web_link", sa.String(500), nullable=True),
        sa.Column("message_id", sa.String(300), nullable=True),
        sa.Column("needs_review", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("confidence", sa.String(20), nullable=True),
        sa.Column("extracted_json", sa.JSON(), nullable=True),
        sa.Column("attachment_name", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["action_id"], ["ops_action_items.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("dedupe_key", name="uq_ops_activity_dedupe"),
    )
    op.create_index("ix_ops_activity_so_number", "ops_activity", ["so_number"])
    op.create_index("ix_ops_activity_po_number", "ops_activity", ["po_number"])
    op.create_index("ix_ops_activity_event_type", "ops_activity", ["event_type"])
    op.create_index("ix_ops_activity_created_at", "ops_activity", ["created_at"])

    op.add_column("ops_tracked_lines", sa.Column("missing_flag", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("ops_tracked_lines", sa.Column("missing_detail", sa.Text(), nullable=True))
    op.add_column("ops_tracked_lines", sa.Column("stock_qty", sa.Float(), nullable=True))
    op.add_column("ops_tracked_lines", sa.Column("stock_location", sa.String(80), nullable=True))
    op.add_column("ops_tracked_lines", sa.Column("stock_source", sa.String(40), nullable=True))

    op.add_column("ops_tracked_pos", sa.Column("lifecycle", sa.String(30), nullable=False, server_default="drafted"))
    op.add_column("ops_tracked_pos", sa.Column("lifecycle_locked", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("ops_tracked_pos", sa.Column("sent_at", sa.DateTime(), nullable=True))
    op.add_column("ops_tracked_pos", sa.Column("sent_source", sa.String(20), nullable=True))
    op.add_column("ops_tracked_pos", sa.Column("ack_confidence", sa.String(20), nullable=True))
    op.add_column("ops_tracked_pos", sa.Column("ack_needs_review", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("ops_tracked_pos", sa.Column("ack_extracted_json", sa.JSON(), nullable=True))
    op.add_column("ops_tracked_pos", sa.Column("missing_summary", sa.Text(), nullable=True))
    op.create_index("ix_ops_tracked_pos_lifecycle", "ops_tracked_pos", ["lifecycle"])


def downgrade() -> None:
    op.drop_index("ix_ops_tracked_pos_lifecycle", table_name="ops_tracked_pos")
    for column in (
        "missing_summary", "ack_extracted_json", "ack_needs_review", "ack_confidence",
        "sent_source", "sent_at", "lifecycle_locked", "lifecycle",
    ):
        op.drop_column("ops_tracked_pos", column)
    for column in ("stock_source", "stock_location", "stock_qty", "missing_detail", "missing_flag"):
        op.drop_column("ops_tracked_lines", column)
    op.drop_table("ops_activity")
