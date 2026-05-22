"""Add external_purchase_orders idempotency table (BCB-02)

Revision ID: b1c2d3e4f5a6
Revises: c5d6e7f8g9h0
Create Date: 2026-05-21 00:00:00.000000

Backs the new `POST /api/external/purchase-orders` endpoint. One row per
Service.AI `external_po_id`; the UNIQUE constraint collapses concurrent /
retried PO creates to a single BC purchase order (mirrors
external_quote_commits). Service.AI's PO id is the idempotency key.
"""
from alembic import op
import sqlalchemy as sa


revision = 'b1c2d3e4f5a6'
down_revision = 'c5d6e7f8g9h0'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'external_purchase_orders',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('external_po_id', sa.String(length=80), nullable=False),
        sa.Column('api_key_id', sa.Integer(), nullable=True),
        sa.Column('supplier_account_code', sa.String(length=80), nullable=False),
        sa.Column('bc_po_id', sa.String(length=100), nullable=True),
        sa.Column('bc_po_number', sa.String(length=100), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='in_progress'),
        sa.Column('request_hash', sa.String(length=64), nullable=True),
        sa.Column('failure_reason', sa.Text(), nullable=True),
        sa.Column('item_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('committed_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['api_key_id'], ['external_api_keys.id'], ondelete='SET NULL'),
        sa.UniqueConstraint('external_po_id', name='uq_external_purchase_orders_external_po_id'),
    )
    op.create_index('ix_external_purchase_orders_id', 'external_purchase_orders', ['id'])
    op.create_index('ix_external_purchase_orders_account', 'external_purchase_orders', ['supplier_account_code'])
    op.create_index('ix_external_purchase_orders_bc_po_id', 'external_purchase_orders', ['bc_po_id'])
    op.create_index('ix_external_purchase_orders_status', 'external_purchase_orders', ['status'])


def downgrade():
    op.drop_index('ix_external_purchase_orders_status', table_name='external_purchase_orders')
    op.drop_index('ix_external_purchase_orders_bc_po_id', table_name='external_purchase_orders')
    op.drop_index('ix_external_purchase_orders_account', table_name='external_purchase_orders')
    op.drop_index('ix_external_purchase_orders_id', table_name='external_purchase_orders')
    op.drop_table('external_purchase_orders')
