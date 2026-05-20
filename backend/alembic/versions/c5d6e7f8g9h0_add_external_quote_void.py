"""Add void columns to external_quote_commits (TD-SQB-A8)

Revision ID: c5d6e7f8g9h0
Revises: b4c5d6e7f8g9
Create Date: 2026-05-19 16:55:00.000000

Adds two columns to `external_quote_commits` so the new
`POST /api/external/quotes/{external_quote_id}/void` endpoint can be
idempotent the same way commit + convert-to-order already are. Replay
rules:

    voided_at IS NOT NULL: return cached void result (no BC traffic).
    voided_at IS NULL on a row in status='committed' (and not yet
        converted): run BC's delete_sales_quote, persist voided_at on
        success. On BC failure, leave the column null so the next call
        retries; the endpoint does NOT mark the row as 'failed' on void
        failure (the commit itself succeeded — only the void didn't).

A voided row keeps bc_quote_id + supplier_quote_ref populated for
audit, but those refs point to a deleted BC document and should not
be used for further BC traffic.
"""
from alembic import op
import sqlalchemy as sa


revision = 'c5d6e7f8g9h0'
down_revision = 'b4c5d6e7f8g9'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'external_quote_commits',
        sa.Column('voided_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        'external_quote_commits',
        sa.Column('void_reason', sa.Text(), nullable=True),
    )


def downgrade():
    op.drop_column('external_quote_commits', 'void_reason')
    op.drop_column('external_quote_commits', 'voided_at')
