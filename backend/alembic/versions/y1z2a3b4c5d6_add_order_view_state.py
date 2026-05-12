"""add order_view_state table for portal-side new-order tracking

Revision ID: y1z2a3b4c5d6
Revises: x0y1z2a3b4c5
Create Date: 2026-05-11

Adds the `order_view_state` table so the Order Management page can show
a NEW badge on orders that no sales agent has opened yet. Source of
truth is local — BC is never written to.

Backfill of existing BC orders is handled by a separate one-shot script
(scripts/backfill_order_view_state.py) that hits the BC API at deploy
time — keeping this migration deterministic and offline-safe.
"""
from typing import Sequence, Union
from datetime import datetime

from alembic import op
import sqlalchemy as sa


revision: str = 'y1z2a3b4c5d6'
down_revision: Union[str, None] = 'x0y1z2a3b4c5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'order_view_state',
        sa.Column('bc_order_number', sa.String(length=50), primary_key=True),
        sa.Column('viewed_at', sa.DateTime(), nullable=False),
        sa.Column('viewed_by_user_id', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['viewed_by_user_id'], ['users.id'], ondelete='SET NULL'),
    )
    op.create_index(
        'ix_order_view_state_viewed_by_user_id',
        'order_view_state',
        ['viewed_by_user_id'],
    )


def downgrade() -> None:
    op.drop_index('ix_order_view_state_viewed_by_user_id', table_name='order_view_state')
    op.drop_table('order_view_state')
