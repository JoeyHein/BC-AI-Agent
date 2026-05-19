"""Add order-conversion columns to external_quote_commits (QOC-03)

Revision ID: b4c5d6e7f8g9
Revises: a3b4c5d6e7f8
Create Date: 2026-05-18 10:00:00.000000

Adds three columns to track quote-to-order conversion on the same row
that already tracks the commit. One BC quote → one BC order (BC's
makeOrder is 1:1), so we reuse the row rather than introducing a
parallel external_order_conversions table.

* bc_order_id      — BC's sales-order GUID, indexed for joins.
* bc_order_ref     — BC's human-facing SO-XXXXXX number.
* converted_at     — when convert_quote_to_order succeeded; null until then.

Replay rules:
    converted_at IS NOT NULL: return cached bc_order_ref + bc_order_id
        on every subsequent /convert-to-order call (no BC traffic).
    converted_at IS NULL on a row in status='committed': run the BC
        conversion now and persist on success. On BC failure, leave the
        columns null so the next call retries; the BC AI Agent endpoint
        does NOT mark the row as 'failed' on conversion failure (the
        commit itself succeeded — only the order step didn't).
"""
from alembic import op
import sqlalchemy as sa


revision = 'b4c5d6e7f8g9'
down_revision = 'a3b4c5d6e7f8'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'external_quote_commits',
        sa.Column('bc_order_id', sa.String(100), nullable=True),
    )
    op.add_column(
        'external_quote_commits',
        sa.Column('bc_order_ref', sa.String(100), nullable=True),
    )
    op.add_column(
        'external_quote_commits',
        sa.Column('converted_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        'ix_external_quote_commits_bc_order_id',
        'external_quote_commits',
        ['bc_order_id'],
    )


def downgrade():
    op.drop_index(
        'ix_external_quote_commits_bc_order_id',
        table_name='external_quote_commits',
    )
    op.drop_column('external_quote_commits', 'converted_at')
    op.drop_column('external_quote_commits', 'bc_order_ref')
    op.drop_column('external_quote_commits', 'bc_order_id')
