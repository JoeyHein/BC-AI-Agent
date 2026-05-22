"""Merge the three alembic heads (TD-BCB-03)

Revision ID: d4e5f6a7b8c9
Revises: b1c2d3e4f5a6, c7d8e9f0a1b2, m7n8o9p0q1r2
Create Date: 2026-05-21 00:00:00.000000

The history had branched into three independent heads:
  - b1c2d3e4f5a6  (external_purchase_orders — BCB-02, external-tables lineage)
  - c7d8e9f0a1b2  (production_tasks)
  - m7n8o9p0q1r2  (bc_price_group on bc_customers)

This is a no-op merge revision so `alembic upgrade head` resolves to a single
head again. No schema changes.
"""
from alembic import op  # noqa: F401  (kept for parity with other revisions)
import sqlalchemy as sa  # noqa: F401


revision = 'd4e5f6a7b8c9'
down_revision = ('b1c2d3e4f5a6', 'c7d8e9f0a1b2', 'm7n8o9p0q1r2')
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
