"""Add customer portal tables

Revision ID: a1b2c3d4e5f6
Revises: 6fa0461410ad
Create Date: 2026-01-23 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = '6fa0461410ad'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Add customer portal fields to users table
    # Note: SQLite doesn't support ENUM, so we use String and validate in app code
    # user_type will be 'INTERNAL' or 'CUSTOMER'
    op.add_column('users', sa.Column('user_type', sa.String(length=20), nullable=True, server_default='INTERNAL'))
    op.add_column('users', sa.Column('bc_customer_id', sa.String(length=100), nullable=True))
    op.add_column('users', sa.Column('email_verified', sa.Boolean(), nullable=True, server_default='0'))
    op.add_column('users', sa.Column('email_verification_token', sa.String(length=255), nullable=True))
    op.add_column('users', sa.Column('email_verification_expires', sa.DateTime(), nullable=True))
    op.add_column('users', sa.Column('password_reset_token', sa.String(length=255), nullable=True))
    op.add_column('users', sa.Column('password_reset_expires', sa.DateTime(), nullable=True))

    # Set default value for existing users
    op.execute("UPDATE users SET user_type = 'INTERNAL' WHERE user_type IS NULL")
    op.execute("UPDATE users SET email_verified = 0 WHERE email_verified IS NULL")

    # Create saved_quote_configs table
    op.create_table(
        'saved_quote_configs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('config_data', sa.JSON(), nullable=False),
        sa.Column('is_submitted', sa.Boolean(), nullable=False, server_default='0'),
        sa.Column('bc_quote_number', sa.String(length=50), nullable=True),
        sa.Column('bc_quote_id', sa.String(length=100), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.Column('submitted_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_saved_quote_configs_id'), 'saved_quote_configs', ['id'], unique=False)
    op.create_index(op.f('ix_saved_quote_configs_user_id'), 'saved_quote_configs', ['user_id'], unique=False)
    op.create_index(op.f('ix_saved_quote_configs_is_submitted'), 'saved_quote_configs', ['is_submitted'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    # Drop saved_quote_configs table
    op.drop_index(op.f('ix_saved_quote_configs_is_submitted'), table_name='saved_quote_configs')
    op.drop_index(op.f('ix_saved_quote_configs_user_id'), table_name='saved_quote_configs')
    op.drop_index(op.f('ix_saved_quote_configs_id'), table_name='saved_quote_configs')
    op.drop_table('saved_quote_configs')

    # Remove customer portal fields from users table
    op.drop_column('users', 'password_reset_expires')
    op.drop_column('users', 'password_reset_token')
    op.drop_column('users', 'email_verification_expires')
    op.drop_column('users', 'email_verification_token')
    op.drop_column('users', 'email_verified')
    op.drop_column('users', 'bc_customer_id')
    op.drop_column('users', 'user_type')
