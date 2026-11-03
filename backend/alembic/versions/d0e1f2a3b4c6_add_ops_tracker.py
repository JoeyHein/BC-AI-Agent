"""Order tracker, action list, and approval-gated outbound mail.

Revision ID: d0e1f2a3b4c6
Revises: c9e0f1a2b3c4
Create Date: 2026-11-03

Adds the internal production tracker tables. Does not drop production_tasks
or sales_orders.scheduled_date — the calendar UI is gone, the rows stay.
"""
from alembic import op
import sqlalchemy as sa


revision = "d0e1f2a3b4c6"
down_revision = "c9e0f1a2b3c4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ops_tracker_meta",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("last_sync_at", sa.DateTime(), nullable=True),
        sa.Column("last_sync_error", sa.Text(), nullable=True),
        sa.Column("mail_available", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("mail_reason", sa.Text(), nullable=True),
        sa.Column("last_mail_check_at", sa.DateTime(), nullable=True),
        sa.Column("vendors_json", sa.JSON(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "ops_tracked_orders",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("so_number", sa.String(50), nullable=False),
        sa.Column("bc_order_id", sa.String(100), nullable=True),
        sa.Column("customer_number", sa.String(50), nullable=True),
        sa.Column("customer_name", sa.String(255), nullable=True),
        sa.Column("customer_email", sa.String(255), nullable=True),
        sa.Column("external_document_number", sa.String(100), nullable=True),
        sa.Column("order_date", sa.Date(), nullable=True),
        sa.Column("po_date", sa.Date(), nullable=True),
        sa.Column("bc_status", sa.String(40), nullable=True),
        sa.Column("fulfillment", sa.String(40), nullable=False, server_default="Buy Complete"),
        sa.Column("upwardor_po_number", sa.String(200), nullable=True),
        sa.Column("order_status", sa.String(40), nullable=False, server_default="Waiting to Order"),
        sa.Column("expected_receipt", sa.Date(), nullable=True),
        sa.Column("expected_receipt_locked", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("supplier_expected", sa.Date(), nullable=True),
        sa.Column("customer_update_baseline", sa.Date(), nullable=True),
        sa.Column("updates_baselined", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("operators", sa.String(40), nullable=False, server_default=""),
        sa.Column("window_kits", sa.String(40), nullable=False, server_default=""),
        sa.Column("emergency_build", sa.String(40), nullable=False, server_default=""),
        sa.Column("shipping_status", sa.String(40), nullable=False, server_default="Not Ready"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("fully_shipped", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("bc_open", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("po_links_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("updated_by_user_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["updated_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("so_number", name="uq_ops_tracked_order_so"),
    )
    op.create_index("ix_ops_tracked_orders_so_number", "ops_tracked_orders", ["so_number"])
    op.create_index("ix_ops_tracked_orders_customer_number", "ops_tracked_orders", ["customer_number"])
    op.create_index("ix_ops_tracked_orders_bc_open", "ops_tracked_orders", ["bc_open"])

    op.create_table(
        "ops_tracked_lines",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("order_id", sa.Integer(), nullable=False),
        sa.Column("so_number", sa.String(50), nullable=False),
        sa.Column("bc_line_no", sa.Integer(), nullable=False),
        sa.Column("item_no", sa.String(100), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("quantity", sa.Float(), nullable=False, server_default="0"),
        sa.Column("quantity_shipped", sa.Float(), nullable=False, server_default="0"),
        sa.Column("line_type", sa.String(20), nullable=True),
        sa.Column("source_code", sa.String(40), nullable=False, server_default="UPW"),
        sa.Column("source_label", sa.String(120), nullable=False, server_default="Upwardor"),
        sa.Column("source_locked", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("linked_po_number", sa.String(40), nullable=True),
        sa.Column("po_locked", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("ack_status", sa.String(20), nullable=False, server_default="none"),
        sa.Column("ack_locked", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("expected_date", sa.Date(), nullable=True),
        sa.Column("expected_date_locked", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("supplier_expected", sa.Date(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["order_id"], ["ops_tracked_orders.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("so_number", "bc_line_no", name="uq_ops_tracked_line"),
    )
    op.create_index("ix_ops_tracked_lines_order_id", "ops_tracked_lines", ["order_id"])
    op.create_index("ix_ops_tracked_lines_so_number", "ops_tracked_lines", ["so_number"])
    op.create_index("ix_ops_tracked_lines_linked_po_number", "ops_tracked_lines", ["linked_po_number"])

    op.create_table(
        "ops_tracked_pos",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("po_number", sa.String(40), nullable=False),
        sa.Column("vendor_number", sa.String(40), nullable=True),
        sa.Column("vendor_name", sa.String(255), nullable=True),
        sa.Column("vendor_email", sa.String(255), nullable=True),
        sa.Column("vendor_email_locked", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("status", sa.String(40), nullable=True),
        sa.Column("order_date", sa.Date(), nullable=True),
        sa.Column("expected_date", sa.Date(), nullable=True),
        sa.Column("receipt_date", sa.Date(), nullable=True),
        sa.Column("vendor_order_no", sa.String(40), nullable=True),
        sa.Column("ack_status", sa.String(20), nullable=False, server_default="none"),
        sa.Column("ack_received_at", sa.DateTime(), nullable=True),
        sa.Column("so_numbers_json", sa.JSON(), nullable=True),
        sa.Column("fully_received", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("bc_open", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("po_number", name="uq_ops_tracked_po"),
    )
    op.create_index("ix_ops_tracked_pos_po_number", "ops_tracked_pos", ["po_number"])
    op.create_index("ix_ops_tracked_pos_vendor_number", "ops_tracked_pos", ["vendor_number"])

    op.create_table(
        "ops_field_audit",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("entity_type", sa.String(20), nullable=False),
        sa.Column("entity_key", sa.String(80), nullable=False),
        sa.Column("field_name", sa.String(60), nullable=False),
        sa.Column("old_value", sa.Text(), nullable=True),
        sa.Column("new_value", sa.Text(), nullable=True),
        sa.Column("actor_user_id", sa.Integer(), nullable=True),
        sa.Column("actor_email", sa.String(255), nullable=True),
        sa.Column("source", sa.String(20), nullable=False, server_default="portal"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_ops_field_audit_entity_key", "ops_field_audit", ["entity_key"])
    op.create_index("ix_ops_field_audit_created_at", "ops_field_audit", ["created_at"])

    op.create_table(
        "ops_action_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("auto_key", sa.String(160), nullable=True),
        sa.Column("auto_managed", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("so_number", sa.String(50), nullable=True),
        sa.Column("po_number", sa.String(40), nullable=True),
        sa.Column("line_id", sa.Integer(), nullable=True),
        sa.Column("due_at", sa.DateTime(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="open"),
        sa.Column("source_ref", sa.String(300), nullable=True),
        sa.Column("payload_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("closed_at", sa.DateTime(), nullable=True),
        sa.Column("closed_by_user_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["closed_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("auto_key", name="uq_ops_action_auto_key"),
    )
    op.create_index("ix_ops_action_items_status", "ops_action_items", ["status"])
    op.create_index("ix_ops_action_items_kind", "ops_action_items", ["kind"])
    op.create_index("ix_ops_action_items_so_number", "ops_action_items", ["so_number"])

    op.create_table(
        "ops_outbound_messages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("dedupe_key", sa.String(160), nullable=False),
        sa.Column("to_email", sa.String(255), nullable=True),
        sa.Column("subject", sa.String(300), nullable=False),
        sa.Column("body_text", sa.Text(), nullable=False),
        sa.Column("so_number", sa.String(50), nullable=True),
        sa.Column("po_number", sa.String(40), nullable=True),
        sa.Column("context_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("approved_by_user_id", sa.Integer(), nullable=True),
        sa.Column("approved_at", sa.DateTime(), nullable=True),
        sa.Column("sent_at", sa.DateTime(), nullable=True),
        sa.Column("rejected_at", sa.DateTime(), nullable=True),
        sa.Column("send_error", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["approved_by_user_id"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_ops_outbound_messages_status", "ops_outbound_messages", ["status"])
    op.create_index("ix_ops_outbound_messages_dedupe_key", "ops_outbound_messages", ["dedupe_key"])
    op.create_index("ix_ops_outbound_messages_so_number", "ops_outbound_messages", ["so_number"])


def downgrade() -> None:
    op.drop_table("ops_outbound_messages")
    op.drop_table("ops_action_items")
    op.drop_table("ops_field_audit")
    op.drop_table("ops_tracked_pos")
    op.drop_table("ops_tracked_lines")
    op.drop_table("ops_tracked_orders")
    op.drop_table("ops_tracker_meta")
