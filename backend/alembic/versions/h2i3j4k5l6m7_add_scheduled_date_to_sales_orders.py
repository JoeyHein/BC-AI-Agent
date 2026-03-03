"""Add scheduled_date to sales_orders

Revision ID: h2i3j4k5l6m7
Revises: g1h2i3j4k5l6
Create Date: 2026-02-02 13:35:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'h2i3j4k5l6m7'
down_revision = 'g1h2i3j4k5l6'
branch_labels = None
depends_on = None


def upgrade():
    # Add scheduled_date column to sales_orders (idempotent)
    existing = {row[0] for row in op.get_bind().execute(sa.text(
        "SELECT column_name FROM information_schema.columns WHERE table_name='sales_orders'"
    ))}
    if 'scheduled_date' not in existing:
        op.add_column('sales_orders', sa.Column('scheduled_date', sa.DateTime(), nullable=True))
    op.execute("CREATE INDEX IF NOT EXISTS ix_sales_orders_scheduled_date ON sales_orders (scheduled_date)")


def downgrade():
    op.drop_index(op.f('ix_sales_orders_scheduled_date'), table_name='sales_orders')
    op.drop_column('sales_orders', 'scheduled_date')
