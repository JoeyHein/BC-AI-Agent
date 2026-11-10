"""Queue for customer quote approvals

Revision ID: b9c0d1e2f4a5
Revises: a8b9c0d1e2f3
Create Date: 2026-11-10 18:00:00.000000

A go-ahead email can wait here until staff convert one SQ to a sales
order. The inbox switches themselves live in app_settings and default
to off, so this table is unused until that switch is on.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b9c0d1e2f4a5"
down_revision: Union[str, None] = "a8b9c0d1e2f3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "customer_order_approvals",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("email_log_id", sa.Integer(), sa.ForeignKey("email_logs.id"), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="needs_choice"),
        sa.Column("match_method", sa.String(length=40), nullable=True),
        sa.Column("bc_quote_number", sa.String(length=50), nullable=True),
        sa.Column("quote_request_id", sa.Integer(), sa.ForeignKey("quote_requests.id"), nullable=True),
        sa.Column("candidates", sa.JSON(), nullable=True),
        sa.Column("customer_po", sa.String(length=80), nullable=True),
        sa.Column("po_source", sa.String(length=120), nullable=True),
        sa.Column("excerpt", sa.Text(), nullable=True),
        sa.Column("from_address", sa.String(length=255), nullable=True),
        sa.Column("subject", sa.Text(), nullable=True),
        sa.Column("graph_message_id", sa.String(length=500), nullable=True),
        sa.Column("mailbox", sa.String(length=255), nullable=True),
        sa.Column("bc_order_number", sa.String(length=50), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("decided_at", sa.DateTime(), nullable=True),
        sa.Column("decided_by", sa.String(length=255), nullable=True),
    )
    op.create_index("ix_customer_order_approvals_email_log_id", "customer_order_approvals", ["email_log_id"])
    op.create_index("ix_customer_order_approvals_status", "customer_order_approvals", ["status"])
    op.create_index("ix_customer_order_approvals_quote_request_id", "customer_order_approvals", ["quote_request_id"])


def downgrade() -> None:
    op.drop_index("ix_customer_order_approvals_quote_request_id", table_name="customer_order_approvals")
    op.drop_index("ix_customer_order_approvals_status", table_name="customer_order_approvals")
    op.drop_index("ix_customer_order_approvals_email_log_id", table_name="customer_order_approvals")
    op.drop_table("customer_order_approvals")
