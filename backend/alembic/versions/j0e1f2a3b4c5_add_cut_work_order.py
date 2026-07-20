"""Add cut_work_order (per-SO cut plan, approve + post)

Revision ID: j0e1f2a3b4c5
Revises: i9d0e1f2a3b4
Create Date: 2026-07-20 00:00:00.000000

A decided per-sales-order cut plan: the cuts + inventory moves that make one SO
shippable. Only approved/rejected/posted work orders persist here (proposed
ones are computed live). journal_json holds the tagged item-journal adjustment
spec that makes each cut an auditable, mineable ledger event.
"""
from alembic import op
import sqlalchemy as sa


revision = 'j0e1f2a3b4c5'
down_revision = 'i9d0e1f2a3b4'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'cut_work_order',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('so_number', sa.String(50), nullable=False),
        sa.Column('status', sa.String(20), nullable=False, server_default='approved'),
        sa.Column('makes_invoiceable', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('purchase_avoided', sa.Numeric(12, 2), nullable=True),
        sa.Column('plan_json', sa.JSON(), nullable=True),
        sa.Column('journal_json', sa.JSON(), nullable=True),
        sa.Column('approved_by', sa.Integer(), nullable=True),
        sa.Column('approved_at', sa.DateTime(), nullable=True),
        sa.Column('rejected_by', sa.Integer(), nullable=True),
        sa.Column('rejected_at', sa.DateTime(), nullable=True),
        sa.Column('reason', sa.Text(), nullable=True),
        sa.Column('posted_at', sa.DateTime(), nullable=True),
        sa.Column('posted_document_no', sa.String(50), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['approved_by'], ['users.id']),
        sa.ForeignKeyConstraint(['rejected_by'], ['users.id']),
    )
    op.create_index('ix_cut_work_order_so_number', 'cut_work_order', ['so_number'])
    op.create_index('ix_cut_work_order_status', 'cut_work_order', ['status'])


def downgrade():
    op.drop_index('ix_cut_work_order_status', table_name='cut_work_order')
    op.drop_index('ix_cut_work_order_so_number', table_name='cut_work_order')
    op.drop_table('cut_work_order')
