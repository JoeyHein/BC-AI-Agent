"""Per-customer freight override, with Marquis Overhead Doors set to waive.

Revision ID: h3i4j5k6l7m8
Revises: g2h3i4j5k6l7
Create Date: 2026-11-26

Null freight_override means "use the province rate" and is still eligible
for this seed. Marquis Overhead Doors (BC customer number MRQ, or a company
name containing both "marquis" and "overhead") is set to waive when the
column is still empty. An admin choice of default, waive, or percent is
stored as that word and is not overwritten here or by a later BC sync.
"""
from alembic import op
import sqlalchemy as sa


revision = "h3i4j5k6l7m8"
down_revision = "g2h3i4j5k6l7"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("bc_customers", sa.Column("freight_override", sa.String(length=20), nullable=True))
    op.add_column("bc_customers", sa.Column("freight_percent", sa.Float(), nullable=True))

    # Imported here so alembic can load this file before the app is fully up.
    from app.services.freight_service import seed_freight_overrides

    seed_freight_overrides(op.get_bind())


def downgrade():
    op.drop_column("bc_customers", "freight_percent")
    op.drop_column("bc_customers", "freight_override")
