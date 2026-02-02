"""Add sales order line items table

Revision ID: e9f0a1b2c3d4
Revises: d8e9f0a1b2c3
Create Date: 2026-01-30 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e9f0a1b2c3d4'
down_revision: Union[str, Sequence[str], None] = 'd8e9f0a1b2c3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add sales_order_line_items table and link to production_orders."""
    # Create sales_order_line_items table
    op.create_table(
        'sales_order_line_items',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('sales_order_id', sa.Integer(), nullable=False),
        sa.Column('bc_line_no', sa.Integer(), nullable=False),
        sa.Column('bc_document_no', sa.String(50), nullable=True),
        sa.Column('item_no', sa.String(100), nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('quantity', sa.Float(), nullable=True, server_default='1'),
        sa.Column('unit_of_measure', sa.String(20), nullable=True),
        sa.Column('unit_price', sa.Numeric(12, 2), nullable=True),
        sa.Column('line_amount', sa.Numeric(12, 2), nullable=True),
        sa.Column('line_type', sa.String(20), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('last_synced_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['sales_order_id'], ['sales_orders.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_sales_order_line_items_id', 'sales_order_line_items', ['id'])
    op.create_index('ix_sales_order_line_items_sales_order_id', 'sales_order_line_items', ['sales_order_id'])
    op.create_index('ix_sales_order_line_items_bc_document_no', 'sales_order_line_items', ['bc_document_no'])
    op.create_index('ix_sales_order_line_items_item_no', 'sales_order_line_items', ['item_no'])

    # Add line_item_id to production_orders
    op.add_column('production_orders', sa.Column('line_item_id', sa.Integer(), nullable=True))
    op.create_index('ix_production_orders_line_item_id', 'production_orders', ['line_item_id'])
    # Note: SQLite doesn't support adding foreign key constraints after table creation
    # The constraint is enforced at the application level


def downgrade() -> None:
    """Remove sales_order_line_items table and production_orders.line_item_id."""
    op.drop_index('ix_production_orders_line_item_id', table_name='production_orders')
    op.drop_column('production_orders', 'line_item_id')

    op.drop_index('ix_sales_order_line_items_item_no', table_name='sales_order_line_items')
    op.drop_index('ix_sales_order_line_items_bc_document_no', table_name='sales_order_line_items')
    op.drop_index('ix_sales_order_line_items_sales_order_id', table_name='sales_order_line_items')
    op.drop_index('ix_sales_order_line_items_id', table_name='sales_order_line_items')
    op.drop_table('sales_order_line_items')
