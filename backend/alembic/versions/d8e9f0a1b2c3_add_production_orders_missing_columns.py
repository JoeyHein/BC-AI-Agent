"""Add missing columns to production_orders table

Revision ID: d8e9f0a1b2c3
Revises: c7d8e9f0a1b2
Create Date: 2026-01-30 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd8e9f0a1b2c3'
down_revision: Union[str, Sequence[str], None] = 'c7d8e9f0a1b2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add missing columns to production_orders table (idempotent — columns may already exist)."""
    conn = op.get_bind()
    existing = {row[0] for row in conn.execute(sa.text(
        "SELECT column_name FROM information_schema.columns WHERE table_name='production_orders'"
    ))}

    if 'item_type' not in existing:
        op.add_column('production_orders', sa.Column('item_type', sa.String(50), nullable=True))
    # Index may already exist too
    op.execute("CREATE INDEX IF NOT EXISTS ix_production_orders_item_type ON production_orders (item_type)")

    if 'specifications' not in existing:
        op.add_column('production_orders', sa.Column('specifications', sa.JSON(), nullable=True))
    if 'inventory_allocated' not in existing:
        op.add_column('production_orders', sa.Column('inventory_allocated', sa.Boolean(), nullable=True, server_default='false'))
    if 'inventory_allocation_id' not in existing:
        op.add_column('production_orders', sa.Column('inventory_allocation_id', sa.String(100), nullable=True))
    if 'stock_available' not in existing:
        op.add_column('production_orders', sa.Column('stock_available', sa.Integer(), nullable=True))
    if 'stock_reserved' not in existing:
        op.add_column('production_orders', sa.Column('stock_reserved', sa.Integer(), nullable=True, server_default='0'))


def downgrade() -> None:
    """Remove added columns from production_orders table."""
    op.drop_index('ix_production_orders_item_type', table_name='production_orders')
    op.drop_column('production_orders', 'item_type')
    op.drop_column('production_orders', 'specifications')
    op.drop_column('production_orders', 'inventory_allocated')
    op.drop_column('production_orders', 'inventory_allocation_id')
    op.drop_column('production_orders', 'stock_available')
    op.drop_column('production_orders', 'stock_reserved')
