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


def _pg_add_column(table, col_name, col_type, default=None):
    """Idempotent add column for PostgreSQL using DO $$ EXCEPTION block."""
    default_clause = f" DEFAULT '{default}'" if default else ""
    op.execute(sa.text(f"""
        DO $$ BEGIN
            ALTER TABLE {table} ADD COLUMN {col_name} {col_type}{default_clause};
        EXCEPTION WHEN duplicate_column THEN
            NULL;
        END $$;
    """))


def _sqlite_add_column(table, col_name, col_type, default=None):
    """Idempotent add column for SQLite using PRAGMA check."""
    bind = op.get_bind()
    result = bind.execute(sa.text(f"PRAGMA table_info({table})"))
    existing = [row[1] for row in result]
    if col_name not in existing:
        default_clause = f" DEFAULT '{default}'" if default else ""
        bind.execute(sa.text(f"ALTER TABLE {table} ADD COLUMN {col_name} {col_type}{default_clause}"))


def _add_column_if_not_exists(table, col_name, col_type, default=None):
    """Add column idempotently on both PostgreSQL and SQLite."""
    bind = op.get_bind()
    if bind.dialect.name == 'sqlite':
        _sqlite_add_column(table, col_name, col_type, default)
    else:
        _pg_add_column(table, col_name, col_type, default)


def _table_exists(table_name):
    """Check if a table exists."""
    bind = op.get_bind()
    if bind.dialect.name == 'sqlite':
        result = bind.execute(sa.text(
            f"SELECT name FROM sqlite_master WHERE type='table' AND name='{table_name}'"
        ))
    else:
        result = bind.execute(sa.text(
            f"SELECT table_name FROM information_schema.tables WHERE table_name='{table_name}' AND table_schema='public'"
        ))
    return result.fetchone() is not None


def _create_index_if_not_exists(index_name, table, columns):
    """Create index idempotently."""
    bind = op.get_bind()
    cols = ', '.join(columns)
    if bind.dialect.name == 'sqlite':
        bind.execute(sa.text(f"CREATE INDEX IF NOT EXISTS {index_name} ON {table} ({cols})"))
    else:
        bind.execute(sa.text(f"CREATE INDEX IF NOT EXISTS {index_name} ON {table} ({cols})"))


def upgrade() -> None:
    # --- Add account_type and account_status to users table ---
    _add_column_if_not_exists('users', 'account_type', 'VARCHAR(20)', 'dealer')
    _add_column_if_not_exists('users', 'account_status', 'VARCHAR(20)', 'active')
    _add_column_if_not_exists('users', 'approved_by', 'INTEGER')
    _add_column_if_not_exists('users', 'approved_at', 'TIMESTAMP')
    _add_column_if_not_exists('users', 'company_name', 'VARCHAR(255)')
    _add_column_if_not_exists('users', 'phone', 'VARCHAR(50)')

    # Set existing users to active dealer status (idempotent UPDATE)
    op.execute(sa.text(
        "UPDATE users SET account_type = 'dealer' WHERE account_type IS NULL"
    ))
    op.execute(sa.text(
        "UPDATE users SET account_status = 'active' WHERE account_status IS NULL"
    ))

    # --- projects table ---
    if not _table_exists('projects'):
        op.create_table(
            'projects',
            sa.Column('id', sa.String(36), nullable=False),
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
    _create_index_if_not_exists('ix_projects_customer_id', 'projects', ['customer_id'])
    _create_index_if_not_exists('ix_projects_status', 'projects', ['status'])

    # --- project_lots table ---
    if not _table_exists('project_lots'):
        op.create_table(
            'project_lots',
            sa.Column('id', sa.String(36), nullable=False),
            sa.Column('project_id', sa.String(36), sa.ForeignKey('projects.id'), nullable=False),
            sa.Column('lot_number', sa.String(100), nullable=False),
            sa.Column('address', sa.Text(), nullable=True),
            sa.Column('door_config_id', sa.Integer(), nullable=True),
            sa.Column('door_spec', sa.JSON(), nullable=True),
            sa.Column('stage', sa.Integer(), nullable=True),
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
    _create_index_if_not_exists('ix_project_lots_project_id', 'project_lots', ['project_id'])
    _create_index_if_not_exists('ix_project_lots_lot_status', 'project_lots', ['lot_status'])
    _create_index_if_not_exists('ix_project_lots_stage', 'project_lots', ['stage'])

    # --- install_referrals table ---
    if not _table_exists('install_referrals'):
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
    _create_index_if_not_exists('ix_install_referrals_customer_id', 'install_referrals', ['customer_id'])
    _create_index_if_not_exists('ix_install_referrals_status', 'install_referrals', ['status'])
    _create_index_if_not_exists('ix_install_referrals_project_lot_id', 'install_referrals', ['project_lot_id'])

    # Add FK from project_lots.install_referral_id -> install_referrals.id
    # Skip on SQLite (doesn't support ADD CONSTRAINT)
    bind = op.get_bind()
    if bind.dialect.name != 'sqlite':
        # Check if FK already exists
        result = bind.execute(sa.text("""
            SELECT constraint_name FROM information_schema.table_constraints
            WHERE table_name='project_lots' AND constraint_name='fk_project_lots_install_referral'
        """))
        if result.fetchone() is None:
            op.create_foreign_key(
                'fk_project_lots_install_referral',
                'project_lots', 'install_referrals',
                ['install_referral_id'], ['id']
            )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != 'sqlite':
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
