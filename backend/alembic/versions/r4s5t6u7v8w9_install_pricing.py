"""Add customer_install_pricing table

Revision ID: r4s5t6u7v8w9
Revises: q3r4s5t6u7v8
Create Date: 2026-03-16 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'r4s5t6u7v8w9'
down_revision: Union[str, None] = 'q3r4s5t6u7v8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(table_name):
    """Check if a table exists."""
    bind = op.get_bind()
    if bind.dialect.name == 'sqlite':
        result = bind.execute(sa.text(
            f"SELECT name FROM sqlite_master WHERE type='table' AND name='{table_name}'"
        ))
    else:
        result = bind.execute(sa.text(
            f"SELECT table_name FROM information_schema.tables WHERE table_name='{table_name}' AND table_schema='public'"
        ))
    return result.fetchone() is not None


def upgrade() -> None:
    if not _table_exists('customer_install_pricing'):
        # Drop orphaned sequence from any previous failed migration attempt (PostgreSQL only)
        bind = op.get_bind()
        if bind.dialect.name != 'sqlite':
            bind.execute(sa.text("DROP SEQUENCE IF EXISTS customer_install_pricing_id_seq CASCADE"))
        op.create_table(
            'customer_install_pricing',
            sa.Column('id', sa.Integer(), nullable=False, autoincrement=True),
            sa.Column('customer_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
            sa.Column('residential_small', sa.Numeric(10, 2), nullable=True),
            sa.Column('residential_medium', sa.Numeric(10, 2), nullable=True),
            sa.Column('residential_large', sa.Numeric(10, 2), nullable=True),
            sa.Column('commercial_base_rate', sa.Numeric(10, 2), nullable=True),
            sa.Column('commercial_sqft_rate', sa.Numeric(10, 2), nullable=True),
            sa.Column('max_auto_height', sa.Integer(), nullable=False, server_default='168'),
            sa.Column('travel_rate_per_km', sa.Numeric(10, 2), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.Column('updated_at', sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint('id'),
        )

    # Create indexes idempotently
    bind = op.get_bind()
    if bind.dialect.name == 'sqlite':
        bind.execute(sa.text(
            "CREATE UNIQUE INDEX IF NOT EXISTS ix_customer_install_pricing_customer_id "
            "ON customer_install_pricing (customer_id)"
        ))
    else:
        bind.execute(sa.text(
            "CREATE UNIQUE INDEX IF NOT EXISTS ix_customer_install_pricing_customer_id "
            "ON customer_install_pricing (customer_id)"
        ))


def downgrade() -> None:
    op.drop_table('customer_install_pricing')
