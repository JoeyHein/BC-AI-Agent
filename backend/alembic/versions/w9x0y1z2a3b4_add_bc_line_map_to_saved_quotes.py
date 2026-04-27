"""Add bc_line_map to saved_quote_configs for surgical quote edits

Revision ID: w9x0y1z2a3b4
Revises: v8w9x0y1z2a3
Create Date: 2026-04-24 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'w9x0y1z2a3b4'
down_revision: Union[str, None] = 'v8w9x0y1z2a3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'saved_quote_configs',
        sa.Column('bc_line_map', sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('saved_quote_configs', 'bc_line_map')
