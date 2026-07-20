"""Add cut_feedback and item_lead_time (cutting-stock feedback layer)

Revision ID: i9d0e1f2a3b4
Revises: h8c9d0e1f2a3
Create Date: 2026-07-20 00:00:00.000000

The feedback layer for the cutting-stock engine:

  cut_feedback   — append-only log of human verdicts (approve/reject/modify)
                   on cut recommendations, with the reason and a snapshot. The
                   learning signal; rules are derived from it, never stored as
                   hard constraints here.
  item_lead_time — purchaser-entered per-item lead time, upserted on
                   (item_no, vendor_no), feeding timeline projections.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'i9d0e1f2a3b4'
down_revision = 'h8c9d0e1f2a3'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'cut_feedback',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('target_sku', sa.String(50), nullable=False),
        sa.Column('donor_sku', sa.String(50), nullable=False),
        sa.Column('cut_family', sa.String(60), nullable=True),
        sa.Column('so_number', sa.String(50), nullable=True),
        sa.Column('qty_pieces', sa.Integer(), nullable=True),
        sa.Column('scrap_inches', sa.Numeric(10, 2), nullable=True),
        sa.Column('verdict', sa.String(20), nullable=False),
        sa.Column('reason', sa.Text(), nullable=True),
        sa.Column('opportunity_json', sa.JSON(), nullable=True),
        sa.Column('source', sa.String(30), nullable=False, server_default='portal'),
        sa.Column('created_by', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['created_by'], ['users.id']),
    )
    op.create_index('ix_cut_feedback_target_sku', 'cut_feedback', ['target_sku'])
    op.create_index('ix_cut_feedback_donor_sku', 'cut_feedback', ['donor_sku'])
    op.create_index('ix_cut_feedback_cut_family', 'cut_feedback', ['cut_family'])
    op.create_index('ix_cut_feedback_so_number', 'cut_feedback', ['so_number'])
    op.create_index('ix_cut_feedback_verdict', 'cut_feedback', ['verdict'])
    op.create_index('ix_cut_feedback_created_at', 'cut_feedback', ['created_at'])

    op.create_table(
        'item_lead_time',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('item_no', sa.String(50), nullable=False),
        sa.Column('vendor_no', sa.String(50), nullable=True),
        sa.Column('lead_time_days', sa.Integer(), nullable=False),
        sa.Column('note', sa.Text(), nullable=True),
        sa.Column('source', sa.String(30), nullable=False, server_default='portal'),
        sa.Column('created_by', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['created_by'], ['users.id']),
        sa.UniqueConstraint('item_no', 'vendor_no', name='uq_item_lead_time'),
    )
    op.create_index('ix_item_lead_time_item_no', 'item_lead_time', ['item_no'])


def downgrade():
    op.drop_index('ix_item_lead_time_item_no', table_name='item_lead_time')
    op.drop_table('item_lead_time')
    op.drop_index('ix_cut_feedback_created_at', table_name='cut_feedback')
    op.drop_index('ix_cut_feedback_verdict', table_name='cut_feedback')
    op.drop_index('ix_cut_feedback_so_number', table_name='cut_feedback')
    op.drop_index('ix_cut_feedback_cut_family', table_name='cut_feedback')
    op.drop_index('ix_cut_feedback_donor_sku', table_name='cut_feedback')
    op.drop_index('ix_cut_feedback_target_sku', table_name='cut_feedback')
    op.drop_table('cut_feedback')
