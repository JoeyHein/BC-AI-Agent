"""Add pick tracking fields to sales_order_line_items

Revision ID: i3j4k5l6m7n8
Revises: h2i3j4k5l6m7
Create Date: 2026-02-03

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'i3j4k5l6m7n8'
down_revision = 'h2i3j4k5l6m7'
branch_labels = None
depends_on = None


def upgrade():
    # Add pick tracking columns to sales_order_line_items
    op.add_column('sales_order_line_items',
        sa.Column('quantity_picked', sa.Float(), nullable=True, server_default='0')
    )
    op.add_column('sales_order_line_items',
        sa.Column('picked_at', sa.DateTime(), nullable=True)
    )
    op.add_column('sales_order_line_items',
        sa.Column('picked_by', sa.String(100), nullable=True)
    )


def downgrade():
    op.drop_column('sales_order_line_items', 'picked_by')
    op.drop_column('sales_order_line_items', 'picked_at')
    op.drop_column('sales_order_line_items', 'quantity_picked')
