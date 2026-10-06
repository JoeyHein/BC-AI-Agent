"""Add vendor_order_acks for Upwardor order-acknowledgement intake

Revision ID: o5p6q7r8s9t0
Revises: n4o5p6q7r8s9
Create Date: 2026-10-06

Tracks Upwardor (UPW) order acknowledgements pulled from joey@ and Finance@.
vendor_order_acks is one row per (vendor_no, vendor_order_no); a revision
updates that row. vendor_order_ack_sources is the email+attachment
idempotency key (the latest source is copied onto the ack row, so it cannot
also be unique there).
"""
from alembic import op
import sqlalchemy as sa


revision = "o5p6q7r8s9t0"
down_revision = "n4o5p6q7r8s9"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "vendor_order_acks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source_email_id", sa.String(300), nullable=False),
        sa.Column("attachment_filename", sa.String(255), nullable=False),
        sa.Column("mailbox", sa.String(255), nullable=True),
        sa.Column("sender_email", sa.String(255), nullable=True),
        sa.Column("vendor_no", sa.String(20), nullable=False, server_default="UPW"),
        sa.Column("vendor_order_no", sa.String(40), nullable=False),
        sa.Column("our_po_number", sa.String(40), nullable=True),
        sa.Column("our_so_numbers", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("completion_date", sa.Date(), nullable=True),
        sa.Column("received_at", sa.DateTime(), nullable=True),
        sa.Column("parsed_json", sa.JSON(), nullable=True),
        sa.Column("bc_po_id", sa.String(100), nullable=True),
        sa.Column("bc_write_status", sa.String(20), nullable=True),
        sa.Column("bc_write_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("vendor_no", "vendor_order_no", name="uq_vendor_order_ack_vendor_order"),
        sa.CheckConstraint(
            "status IN ('confirmed', 'revised', 'cancelled', 'pending', 'error')",
            name="vendor_order_acks_status_chk",
        ),
    )
    op.create_index("ix_vendor_order_acks_source_email_id", "vendor_order_acks", ["source_email_id"])
    op.create_index("ix_vendor_order_acks_vendor_no", "vendor_order_acks", ["vendor_no"])
    op.create_index("ix_vendor_order_acks_vendor_order_no", "vendor_order_acks", ["vendor_order_no"])
    op.create_index("ix_vendor_order_acks_our_po_number", "vendor_order_acks", ["our_po_number"])
    op.create_index("ix_vendor_order_acks_status", "vendor_order_acks", ["status"])

    op.create_table(
        "vendor_order_ack_sources",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source_email_id", sa.String(300), nullable=False),
        sa.Column("attachment_filename", sa.String(255), nullable=False),
        sa.Column("mailbox", sa.String(255), nullable=True),
        sa.Column("outcome", sa.String(20), nullable=False, server_default="parsed"),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("ack_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["ack_id"], ["vendor_order_acks.id"], ondelete="SET NULL"),
        sa.UniqueConstraint(
            "source_email_id", "attachment_filename", name="uq_vendor_order_ack_source"
        ),
        sa.CheckConstraint(
            "outcome IN ('parsed', 'skipped', 'error')",
            name="vendor_order_ack_sources_outcome_chk",
        ),
    )
    op.create_index(
        "ix_vendor_order_ack_sources_ack_id", "vendor_order_ack_sources", ["ack_id"]
    )


def downgrade():
    op.drop_index("ix_vendor_order_ack_sources_ack_id", table_name="vendor_order_ack_sources")
    op.drop_table("vendor_order_ack_sources")
    op.drop_index("ix_vendor_order_acks_status", table_name="vendor_order_acks")
    op.drop_index("ix_vendor_order_acks_our_po_number", table_name="vendor_order_acks")
    op.drop_index("ix_vendor_order_acks_vendor_order_no", table_name="vendor_order_acks")
    op.drop_index("ix_vendor_order_acks_vendor_no", table_name="vendor_order_acks")
    op.drop_index("ix_vendor_order_acks_source_email_id", table_name="vendor_order_acks")
    op.drop_table("vendor_order_acks")
