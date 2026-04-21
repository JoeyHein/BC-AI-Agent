"""Add customer_notes table for CRM interaction history

Revision ID: v8w9x0y1z2a3
Revises: u7v8w9x0y1z2
Create Date: 2026-04-20 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'v8w9x0y1z2a3'
down_revision: Union[str, None] = 'u7v8w9x0y1z2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'customer_notes',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        sa.Column('bc_customer_id', sa.String(length=100), sa.ForeignKey('bc_customers.bc_customer_id'), nullable=True, index=True),
        sa.Column('match_key', sa.String(length=255), nullable=True, index=True),
        sa.Column('match_key_type', sa.String(length=20), nullable=False, server_default='phone'),
        sa.Column('note_type', sa.String(length=20), nullable=False, index=True),
        sa.Column('subject', sa.String(length=255), nullable=True),
        sa.Column('body', sa.Text(), nullable=False),
        sa.Column('source', sa.String(length=50), nullable=False, server_default='donna_pa'),
        sa.Column('source_ref', sa.String(length=255), nullable=True),
        sa.Column('note_metadata', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now(), index=True),
    )


def downgrade() -> None:
    op.drop_table('customer_notes')
