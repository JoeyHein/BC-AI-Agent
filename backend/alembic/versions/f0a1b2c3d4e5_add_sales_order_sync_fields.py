"""Add sales order sync fields

Revision ID: f0a1b2c3d4e5
Revises: e9f0a1b2c3d4
Create Date: 2026-02-02 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f0a1b2c3d4e5'
down_revision: Union[str, Sequence[str], None] = 'e9f0a1b2c3d4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add new fields to sales_orders for BC sync (idempotent)."""
    existing = {row[0] for row in op.get_bind().execute(sa.text(
        "SELECT column_name FROM information_schema.columns WHERE table_name='sales_orders'"
    ))}

    if 'bc_id' not in existing:
        op.add_column('sales_orders', sa.Column('bc_id', sa.String(100), nullable=True))
    if 'bc_customer_id' not in existing:
        op.add_column('sales_orders', sa.Column('bc_customer_id', sa.String(100), nullable=True))
    if 'customer_number' not in existing:
        op.add_column('sales_orders', sa.Column('customer_number', sa.String(50), nullable=True))
    if 'order_date' not in existing:
        op.add_column('sales_orders', sa.Column('order_date', sa.DateTime(), nullable=True))
    if 'requested_delivery_date' not in existing:
        op.add_column('sales_orders', sa.Column('requested_delivery_date', sa.DateTime(), nullable=True))
    if 'shipping_address' not in existing:
        op.add_column('sales_orders', sa.Column('shipping_address', sa.Text(), nullable=True))
    if 'billing_address' not in existing:
        op.add_column('sales_orders', sa.Column('billing_address', sa.Text(), nullable=True))

    # Indexes (IF NOT EXISTS is safe)
    op.execute("CREATE INDEX IF NOT EXISTS ix_sales_orders_bc_id ON sales_orders (bc_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_sales_orders_bc_customer_id ON sales_orders (bc_customer_id)")


def downgrade() -> None:
    """Remove the new fields."""
    op.drop_index('ix_sales_orders_bc_customer_id', table_name='sales_orders')
    op.drop_index('ix_sales_orders_bc_id', table_name='sales_orders')

    op.drop_column('sales_orders', 'billing_address')
    op.drop_column('sales_orders', 'shipping_address')
    op.drop_column('sales_orders', 'requested_delivery_date')
    op.drop_column('sales_orders', 'order_date')
    op.drop_column('sales_orders', 'customer_number')
    op.drop_column('sales_orders', 'bc_customer_id')
    op.drop_column('sales_orders', 'bc_id')
