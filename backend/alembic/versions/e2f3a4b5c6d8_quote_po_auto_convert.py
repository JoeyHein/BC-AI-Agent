"""Customer purchase-order emails that can convert a sales quote

Revision ID: e2f3a4b5c6d8
Revises: d1e2f3a4b5c7
Create Date: 2026-11-13 16:10:00.000000

The switch itself lives in app_settings (quote_po_auto_convert) and
defaults to off, so this table stays empty until that switch is shadow
or on. One row per Graph message. A second delivery of the same message
hits the unique graph_message_id and does not convert again.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e2f3a4b5c6d8"
down_revision: Union[str, None] = "d1e2f3a4b5c7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "quote_po_intakes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("graph_message_id", sa.String(length=500), nullable=True),
        sa.Column("email_log_id", sa.Integer(), sa.ForeignKey("email_logs.id"), nullable=True),
        sa.Column("mailbox", sa.String(length=255), nullable=True),
        sa.Column("from_address", sa.String(length=255), nullable=True),
        sa.Column("subject", sa.Text(), nullable=True),
        sa.Column("received_at", sa.DateTime(), nullable=True),
        sa.Column("customer_po", sa.String(length=80), nullable=True),
        sa.Column("po_source", sa.String(length=120), nullable=True),
        sa.Column("referenced_quotes", sa.JSON(), nullable=True),
        sa.Column("amount_cents", sa.Integer(), nullable=True),
        sa.Column("line_hints", sa.JSON(), nullable=True),
        sa.Column("excerpt", sa.Text(), nullable=True),
        sa.Column("attachment_names", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="review"),
        sa.Column("review_reason", sa.String(length=40), nullable=True),
        sa.Column("confidence", sa.String(length=20), nullable=True),
        sa.Column("match_method", sa.String(length=40), nullable=True),
        sa.Column("bc_quote_number", sa.String(length=50), nullable=True),
        sa.Column("quote_request_id", sa.Integer(), sa.ForeignKey("quote_requests.id"), nullable=True),
        sa.Column("candidates", sa.JSON(), nullable=True),
        sa.Column("bc_order_number", sa.String(length=50), nullable=True),
        sa.Column("bc_order_id", sa.String(length=100), nullable=True),
        sa.Column("planned_action", sa.Text(), nullable=True),
        sa.Column("overdue", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("decided_at", sa.DateTime(), nullable=True),
        sa.Column("decided_by", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_quote_po_intakes_graph_message_id", "quote_po_intakes", ["graph_message_id"], unique=True)
    op.create_index("ix_quote_po_intakes_email_log_id", "quote_po_intakes", ["email_log_id"])
    op.create_index("ix_quote_po_intakes_received_at", "quote_po_intakes", ["received_at"])
    op.create_index("ix_quote_po_intakes_status", "quote_po_intakes", ["status"])
    op.create_index("ix_quote_po_intakes_quote_request_id", "quote_po_intakes", ["quote_request_id"])
    op.create_index("ix_quote_po_intakes_overdue", "quote_po_intakes", ["overdue"])


def downgrade() -> None:
    op.drop_index("ix_quote_po_intakes_overdue", table_name="quote_po_intakes")
    op.drop_index("ix_quote_po_intakes_quote_request_id", table_name="quote_po_intakes")
    op.drop_index("ix_quote_po_intakes_status", table_name="quote_po_intakes")
    op.drop_index("ix_quote_po_intakes_received_at", table_name="quote_po_intakes")
    op.drop_index("ix_quote_po_intakes_email_log_id", table_name="quote_po_intakes")
    op.drop_index("ix_quote_po_intakes_graph_message_id", table_name="quote_po_intakes")
    op.drop_table("quote_po_intakes")
