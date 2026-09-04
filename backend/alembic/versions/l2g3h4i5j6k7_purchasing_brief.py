"""Add purchasing_brief (daily AI narrative brief)

Revision ID: l2g3h4i5j6k7
Revises: m3h4i5j6k7l8
Create Date: 2026-07-28 00:00:00.000000

Stores the deterministic facts snapshot, the computed day-over-day diff, and
the narrative the model wrote. Keeping the facts makes a brief reproducible and
lets the next run diff against real numbers rather than asking the model to
remember yesterday.
"""
from alembic import op
import sqlalchemy as sa


revision = 'l2g3h4i5j6k7'
down_revision = 'm3h4i5j6k7l8'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'purchasing_brief',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('as_of', sa.Date(), nullable=False),
        sa.Column('generated_at', sa.DateTime(), nullable=False),
        sa.Column('facts_json', sa.JSON(), nullable=True),
        sa.Column('diff_json', sa.JSON(), nullable=True),
        sa.Column('brief_json', sa.JSON(), nullable=True),
        sa.Column('model', sa.String(60), nullable=True),
        sa.Column('input_tokens', sa.Integer(), nullable=True),
        sa.Column('output_tokens', sa.Integer(), nullable=True),
        sa.Column('error', sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_purchasing_brief_id', 'purchasing_brief', ['id'])
    op.create_index('ix_purchasing_brief_as_of', 'purchasing_brief', ['as_of'])
    op.create_index('ix_purchasing_brief_generated_at', 'purchasing_brief', ['generated_at'])


def downgrade():
    op.drop_index('ix_purchasing_brief_generated_at', table_name='purchasing_brief')
    op.drop_index('ix_purchasing_brief_as_of', table_name='purchasing_brief')
    op.drop_index('ix_purchasing_brief_id', table_name='purchasing_brief')
    op.drop_table('purchasing_brief')
