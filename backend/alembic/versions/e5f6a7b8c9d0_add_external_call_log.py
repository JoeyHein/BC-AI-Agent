"""Add external_call_log table (TD-QOC-A8)

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-05-22 00:00:00.000000

Observability log of every /api/external/* call (method, path, status,
latency, key prefix). Written by the external-call middleware.
"""
from alembic import op
import sqlalchemy as sa


revision = 'e5f6a7b8c9d0'
down_revision = 'd4e5f6a7b8c9'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'external_call_log',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('method', sa.String(length=10), nullable=False),
        sa.Column('path', sa.String(length=300), nullable=False),
        sa.Column('status_code', sa.Integer(), nullable=False),
        sa.Column('latency_ms', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('key_prefix', sa.String(length=20), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index('ix_external_call_log_path', 'external_call_log', ['path'])
    op.create_index('ix_external_call_log_status', 'external_call_log', ['status_code'])
    op.create_index('ix_external_call_log_key_prefix', 'external_call_log', ['key_prefix'])
    op.create_index('ix_external_call_log_created_at', 'external_call_log', ['created_at'])


def downgrade():
    op.drop_index('ix_external_call_log_created_at', table_name='external_call_log')
    op.drop_index('ix_external_call_log_key_prefix', table_name='external_call_log')
    op.drop_index('ix_external_call_log_status', table_name='external_call_log')
    op.drop_index('ix_external_call_log_path', table_name='external_call_log')
    op.drop_table('external_call_log')
