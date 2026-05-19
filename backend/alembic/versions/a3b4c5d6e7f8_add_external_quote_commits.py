"""Add external_quote_commits table (SQB-05)

Revision ID: a3b4c5d6e7f8
Revises: z2a3b4c5d6e7
Create Date: 2026-05-17 10:00:00.000000

Idempotency record for `POST /api/external/quotes`. One row per
Service.AI `external_quote_id` — UNIQUE constraint enforces "one BC
sales quote per external id, no matter how many times the caller
retries."

Status transitions:
    in_progress → committed   (happy path)
    in_progress → failed      (BC call raised; caller can retry)

Replay rules per status:
    committed: return cached response immediately, no BC traffic.
    in_progress: caller waits (in-process lock during the window the
        original caller holds it; second-process retries observe the
        committed state by the time their request lands).
    failed: a retry can attempt a fresh BC call. The original row's
        external_quote_id is reused — UPDATE in place, no second row.
"""
from alembic import op
import sqlalchemy as sa


revision = 'a3b4c5d6e7f8'
down_revision = 'z2a3b4c5d6e7'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'external_quote_commits',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('external_quote_id', sa.String(80), nullable=False),
        sa.Column('api_key_id', sa.Integer(), nullable=True),
        sa.Column('supplier_account_code', sa.String(80), nullable=False),
        sa.Column('bc_quote_id', sa.String(100), nullable=True),
        sa.Column('supplier_quote_ref', sa.String(100), nullable=True),
        sa.Column(
            'status',
            sa.String(20),
            nullable=False,
            server_default='in_progress',
        ),
        sa.Column('request_hash', sa.String(64), nullable=True),
        sa.Column('failure_reason', sa.Text(), nullable=True),
        sa.Column('item_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('subtotal_cents', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('currency', sa.String(3), nullable=False, server_default='CAD'),
        sa.Column('valid_until', sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text('CURRENT_TIMESTAMP'),
        ),
        sa.Column(
            'updated_at',
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text('CURRENT_TIMESTAMP'),
        ),
        sa.Column('committed_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(
            ['api_key_id'],
            ['external_api_keys.id'],
            ondelete='SET NULL',
        ),
        sa.UniqueConstraint(
            'external_quote_id',
            name='external_quote_commits_external_id_unique',
        ),
        sa.CheckConstraint(
            "status IN ('in_progress', 'committed', 'failed')",
            name='external_quote_commits_status_chk',
        ),
    )
    op.create_index(
        'ix_external_quote_commits_account_code',
        'external_quote_commits',
        ['supplier_account_code'],
    )
    op.create_index(
        'ix_external_quote_commits_status',
        'external_quote_commits',
        ['status'],
    )
    op.create_index(
        'ix_external_quote_commits_bc_quote_id',
        'external_quote_commits',
        ['bc_quote_id'],
    )


def downgrade():
    op.drop_index('ix_external_quote_commits_bc_quote_id', table_name='external_quote_commits')
    op.drop_index('ix_external_quote_commits_status', table_name='external_quote_commits')
    op.drop_index('ix_external_quote_commits_account_code', table_name='external_quote_commits')
    op.drop_table('external_quote_commits')
