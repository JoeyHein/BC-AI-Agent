"""Add so_timeline_snapshot table (daily planning workbook)

Revision ID: h8c9d0e1f2a3
Revises: g7b8c9d0e1f2
Create Date: 2026-07-17 00:00:00.000000

Weekly on-target snapshot per open sales order, written by the daily planning
workbook job. Unique on (so_number, week_ending) so a re-run within a week
overwrites rather than duplicating, and the Timeline tab can show week-over-week
movement.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'h8c9d0e1f2a3'
down_revision = 'g7b8c9d0e1f2'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'so_timeline_snapshot',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('so_number', sa.String(50), nullable=False),
        sa.Column('week_ending', sa.Date(), nullable=False),
        sa.Column('rag', sa.String(10), nullable=False),
        sa.Column('requested_delivery_date', sa.Date(), nullable=True),
        sa.Column('short_item_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('status', sa.String(50), nullable=True),
        sa.Column('snapshot_json', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('so_number', 'week_ending', name='uq_so_timeline_week'),
    )
    op.create_index('ix_so_timeline_snapshot_so_number', 'so_timeline_snapshot', ['so_number'])
    op.create_index('ix_so_timeline_snapshot_week_ending', 'so_timeline_snapshot', ['week_ending'])


def downgrade():
    op.drop_index('ix_so_timeline_snapshot_week_ending', table_name='so_timeline_snapshot')
    op.drop_index('ix_so_timeline_snapshot_so_number', table_name='so_timeline_snapshot')
    op.drop_table('so_timeline_snapshot')
