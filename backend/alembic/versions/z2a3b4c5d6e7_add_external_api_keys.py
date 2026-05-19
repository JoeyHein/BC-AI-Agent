"""Add external_api_keys table (SQB-03)

Revision ID: z2a3b4c5d6e7
Revises: y1z2a3b4c5d6
Create Date: 2026-05-17 08:00:00.000000

External API keys gate the `/api/external/*` surface that Service.AI
calls into for the supplier quote bridge. Each key:
  * Is bcrypt-hashed (the plaintext is shown ONCE on create).
  * Is bound to a single `supplier_account_code` (e.g., the BC customer
    number for Elevated Doors). A request whose body references a
    different account code is rejected with 404.
  * Carries a per-key rate limit in requests per minute (default 600).
  * Has a `status` of 'active' or 'revoked'; revocation is the only way
    to deactivate a key — they are never hard-deleted so the call log
    keeps an FK target.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'z2a3b4c5d6e7'
down_revision = 'y1z2a3b4c5d6'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'external_api_keys',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(200), nullable=False),
        # First 12 characters of the plaintext so the admin UI can show
        # something stable ("sai_live_AbCd...") without ever holding
        # the secret. Indexed for fast list-screen rendering.
        sa.Column('key_prefix', sa.String(12), nullable=False),
        sa.Column('key_hash', sa.String(255), nullable=False),
        # BC customer number (or whichever upstream identifier the
        # supplier uses) this key is bound to. Cross-key probes that
        # reference a different account_code return 404.
        sa.Column('supplier_account_code', sa.String(80), nullable=False),
        sa.Column(
            'status',
            sa.String(20),
            nullable=False,
            server_default='active',
        ),
        sa.Column('rate_limit_rpm', sa.Integer(), nullable=False, server_default='600'),
        sa.Column('created_by_user_id', sa.Integer(), nullable=True),
        sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('revoked_by_user_id', sa.Integer(), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
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
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['created_by_user_id'], ['users.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['revoked_by_user_id'], ['users.id'], ondelete='SET NULL'),
        sa.CheckConstraint(
            "status IN ('active', 'revoked')",
            name='external_api_keys_status_chk',
        ),
        sa.CheckConstraint(
            'rate_limit_rpm > 0',
            name='external_api_keys_rate_limit_positive_chk',
        ),
    )

    op.create_index(
        'ix_external_api_keys_status',
        'external_api_keys',
        ['status'],
    )
    op.create_index(
        'ix_external_api_keys_account_code',
        'external_api_keys',
        ['supplier_account_code'],
    )
    # key_prefix is non-unique (collisions are vanishingly rare but
    # harmless — verification still checks the hash); the index just
    # speeds the admin list view.
    op.create_index(
        'ix_external_api_keys_key_prefix',
        'external_api_keys',
        ['key_prefix'],
    )


def downgrade():
    op.drop_index('ix_external_api_keys_key_prefix', table_name='external_api_keys')
    op.drop_index('ix_external_api_keys_account_code', table_name='external_api_keys')
    op.drop_index('ix_external_api_keys_status', table_name='external_api_keys')
    op.drop_table('external_api_keys')
