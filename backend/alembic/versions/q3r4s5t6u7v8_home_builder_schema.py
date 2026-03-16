"""Add home builder account type, projects, lots, and install referrals

Revision ID: q3r4s5t6u7v8
Revises: p2q3r4s5t6u7
Create Date: 2026-03-16 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'q3r4s5t6u7v8'
down_revision: Union[str, None] = 'p2q3r4s5t6u7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _column_exists(table, column):
    """Check if column already exists (for idempotent migration after partial failure)."""
    from alembic import context
    bind = op.get_bind()
    if bind.dialect.name == 'sqlite':
        result = bind.execute(sa.text(f"PRAGMA table_info({table})"))
        return column in [row[1] for row in result]
    else:
        result = bind.execute(sa.text(
            f"SELECT column_name FROM information_schema.columns WHERE table_name='{table}' AND column_name='{column}'"
        ))
        return result.fetchone() is not None


def upgrade() -> None:
    # --- Add account_type and account_status to users table ---
    # Use idempotent checks for SQLite (non-transactional DDL can leave partial state)
    if not _column_exists('users', 'account_type'):
        op.add_column('users', sa.Column('account_type', sa.String(20), nullable=True, server_default='dealer'))
    if not _column_exists('users', 'account_status'):
        op.add_column('users', sa.Column('account_status', sa.String(20), nullable=True, server_default='active'))
    if not _column_exists('users', 'approved_by'):
        op.add_column('users', sa.Column('approved_by', sa.Integer(), nullable=True))
    if not _column_exists('users', 'approved_at'):
        op.add_column('users', sa.Column('approved_at', sa.DateTime(), nullable=True))
    if not _column_exists('users', 'company_name'):
        op.add_column('users', sa.Column('company_name', sa.String(255), nullable=True))
    if not _column_exists('users', 'phone'):
        op.add_column('users', sa.Column('phone', sa.String(50), nullable=True))

    # Set existing CUSTOMER users to active dealer status
    op.execute("UPDATE users SET account_type = 'dealer', account_status = 'active' WHERE user_type = 'CUSTOMER'")
    # Internal users don't need account_type/status but set them to avoid nulls
    op.execute("UPDATE users SET account_type = 'dealer', account_status = 'active' WHERE user_type = 'INTERNAL' OR user_type IS NULL")

    # --- projects table ---
    op.create_table(
        'projects',
        sa.Column('id', sa.String(36), nullable=False),  # UUID as string for SQLite compat
        sa.Column('customer_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('status', sa.String(20), nullable=False, server_default='active'),
        sa.Column('billing_mode', sa.String(20), nullable=False, server_default='full'),
        sa.Column('bc_quote_id', sa.String(100), nullable=True),
        sa.Column('bc_quote_number', sa.String(100), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_projects_customer_id', 'projects', ['customer_id'])
    op.create_index('ix_projects_status', 'projects', ['status'])

    # --- project_lots table ---
    op.create_table(
        'project_lots',
        sa.Column('id', sa.String(36), nullable=False),
        sa.Column('project_id', sa.String(36), sa.ForeignKey('projects.id'), nullable=False),
        sa.Column('lot_number', sa.String(100), nullable=False),
        sa.Column('address', sa.Text(), nullable=True),
        sa.Column('door_config_id', sa.Integer(), nullable=True),  # FK to saved_quote_configs if desired
        sa.Column('door_spec', sa.JSON(), nullable=True),
        sa.Column('stage', sa.Integer(), nullable=True),  # null = full release
        sa.Column('lot_status', sa.String(20), nullable=False, server_default='quoted'),
        sa.Column('bc_order_id', sa.String(100), nullable=True),
        sa.Column('bc_order_number', sa.String(100), nullable=True),
        sa.Column('bc_invoice_id', sa.String(100), nullable=True),
        sa.Column('bc_invoice_number', sa.String(100), nullable=True),
        sa.Column('install_referral_id', sa.String(36), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_project_lots_project_id', 'project_lots', ['project_id'])
    op.create_index('ix_project_lots_lot_status', 'project_lots', ['lot_status'])
    op.create_index('ix_project_lots_stage', 'project_lots', ['stage'])

    # --- install_referrals table ---
    op.create_table(
        'install_referrals',
        sa.Column('id', sa.String(36), nullable=False),
        sa.Column('customer_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('order_reference', sa.String(100), nullable=True),
        sa.Column('project_lot_id', sa.String(36), sa.ForeignKey('project_lots.id'), nullable=True),
        sa.Column('site_address', sa.Text(), nullable=False),
        sa.Column('site_contact_name', sa.String(255), nullable=False),
        sa.Column('site_contact_phone', sa.String(50), nullable=False),
        sa.Column('requested_date', sa.Date(), nullable=True),
        sa.Column('access_notes', sa.Text(), nullable=True),
        sa.Column('status', sa.String(20), nullable=False, server_default='new'),
        sa.Column('assigned_sub', sa.String(255), nullable=True),
        sa.Column('scheduled_date', sa.Date(), nullable=True),
        sa.Column('internal_notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_install_referrals_customer_id', 'install_referrals', ['customer_id'])
    op.create_index('ix_install_referrals_status', 'install_referrals', ['status'])
    op.create_index('ix_install_referrals_project_lot_id', 'install_referrals', ['project_lot_id'])

    # Add FK from project_lots.install_referral_id -> install_referrals.id
    # (Can't add during table creation due to circular dependency)
    # SQLite doesn't support ADD CONSTRAINT, so we skip FK enforcement there
    # PostgreSQL will enforce this
    try:
        op.create_foreign_key(
            'fk_project_lots_install_referral',
            'project_lots', 'install_referrals',
            ['install_referral_id'], ['id']
        )
    except Exception:
        pass  # SQLite doesn't support ALTER TABLE ADD CONSTRAINT


def downgrade() -> None:
    try:
        op.drop_constraint('fk_project_lots_install_referral', 'project_lots', type_='foreignkey')
    except Exception:
        pass
    op.drop_table('install_referrals')
    op.drop_table('project_lots')
    op.drop_table('projects')
    op.drop_column('users', 'phone')
    op.drop_column('users', 'company_name')
    op.drop_column('users', 'approved_at')
    op.drop_column('users', 'approved_by')
    op.drop_column('users', 'account_status')
    op.drop_column('users', 'account_type')
