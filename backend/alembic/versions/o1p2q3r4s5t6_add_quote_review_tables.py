"""Add quote_snapshots and quote_reviews tables

Revision ID: o1p2q3r4s5t6
Revises: n0a1b2c3d4e5
Create Date: 2026-03-04 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'o1p2q3r4s5t6'
down_revision: Union[str, None] = 'm7n8o9p0q1r2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'quote_snapshots',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('bc_quote_id', sa.String(100), nullable=False),
        sa.Column('bc_quote_number', sa.String(50), nullable=True),
        sa.Column('source', sa.String(20), nullable=False),
        sa.Column('original_lines', sa.JSON(), nullable=True),
        sa.Column('original_line_pricing', sa.JSON(), nullable=True),
        sa.Column('original_pricing_totals', sa.JSON(), nullable=True),
        sa.Column('door_configs', sa.JSON(), nullable=True),
        sa.Column('bc_customer_id', sa.String(100), nullable=True),
        sa.Column('pricing_tier', sa.String(50), nullable=True),
        sa.Column('saved_config_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['saved_config_id'], ['saved_quote_configs.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_quote_snapshots_id'), 'quote_snapshots', ['id'])
    op.create_index(op.f('ix_quote_snapshots_bc_quote_id'), 'quote_snapshots', ['bc_quote_id'], unique=True)
    op.create_index(op.f('ix_quote_snapshots_bc_quote_number'), 'quote_snapshots', ['bc_quote_number'])

    op.create_table(
        'quote_reviews',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('snapshot_id', sa.Integer(), nullable=False),
        sa.Column('bc_lines_at_review', sa.JSON(), nullable=True),
        sa.Column('diff_result', sa.JSON(), nullable=True),
        sa.Column('ai_analysis', sa.JSON(), nullable=True),
        sa.Column('reviewed_by', sa.Integer(), nullable=True),
        sa.Column('review_notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['snapshot_id'], ['quote_snapshots.id']),
        sa.ForeignKeyConstraint(['reviewed_by'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_quote_reviews_id'), 'quote_reviews', ['id'])
    op.create_index(op.f('ix_quote_reviews_snapshot_id'), 'quote_reviews', ['snapshot_id'])


def downgrade() -> None:
    op.drop_table('quote_reviews')
    op.drop_table('quote_snapshots')
