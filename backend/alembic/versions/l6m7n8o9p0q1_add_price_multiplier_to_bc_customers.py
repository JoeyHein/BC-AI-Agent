"""Add price_multiplier to bc_customers table

Revision ID: l6m7n8o9p0q1
Revises: k5l6m7n8o9p0
Create Date: 2026-02-18 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'l6m7n8o9p0q1'
down_revision = 'k5l6m7n8o9p0'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('bc_customers', sa.Column('price_multiplier', sa.Float(), nullable=True))


def downgrade():
    op.drop_column('bc_customers', 'price_multiplier')
