"""Add bc_price_group to bc_customers table

Revision ID: m7n8o9p0q1r2
Revises: l6m7n8o9p0q1
Create Date: 2026-02-25 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'm7n8o9p0q1r2'
down_revision = 'l6m7n8o9p0q1'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('bc_customers', sa.Column('bc_price_group', sa.String(length=100), nullable=True))


def downgrade():
    op.drop_column('bc_customers', 'bc_price_group')
