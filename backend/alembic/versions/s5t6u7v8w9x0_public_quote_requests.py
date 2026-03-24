"""Add public_quote_requests table

Revision ID: s5t6u7v8w9x0
Revises: r4s5t6u7v8w9
Create Date: 2026-03-24 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 's5t6u7v8w9x0'
down_revision: Union[str, None] = 'r4s5t6u7v8w9'
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
    if not _table_exists('public_quote_requests'):
        # Drop orphaned sequence from any previous failed migration attempt (PostgreSQL only)
        bind = op.get_bind()
        if bind.dialect.name != 'sqlite':
            bind.execute(sa.text("DROP SEQUENCE IF EXISTS public_quote_requests_id_seq CASCADE"))
        op.create_table(
            'public_quote_requests',
            sa.Column('id', sa.Integer(), nullable=False, autoincrement=True),
            sa.Column('name', sa.String(255), nullable=False),
            sa.Column('email', sa.String(255), nullable=False),
            sa.Column('phone', sa.String(50), nullable=True),
            sa.Column('postal_code', sa.String(20), nullable=True),
            sa.Column('notes', sa.Text(), nullable=True),
            sa.Column('door_config', sa.JSON(), nullable=False),
            sa.Column('source', sa.String(50), nullable=True, server_default='widget'),
            sa.Column('status', sa.String(20), nullable=True, server_default='new'),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint('id'),
        )
        op.create_index(op.f('ix_public_quote_requests_id'), 'public_quote_requests', ['id'])
        op.create_index(op.f('ix_public_quote_requests_email'), 'public_quote_requests', ['email'])


def downgrade() -> None:
    op.drop_index(op.f('ix_public_quote_requests_email'), table_name='public_quote_requests')
    op.drop_index(op.f('ix_public_quote_requests_id'), table_name='public_quote_requests')
    op.drop_table('public_quote_requests')
