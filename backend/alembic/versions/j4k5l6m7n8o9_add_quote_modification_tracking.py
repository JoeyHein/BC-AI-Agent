"""Add quote modification tracking fields

Revision ID: j4k5l6m7n8o9
Revises: i3j4k5l6m7n8
Create Date: 2026-02-09

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'j4k5l6m7n8o9'
down_revision = 'i3j4k5l6m7n8'
branch_labels = None
depends_on = None


def upgrade():
    # Add quote modification detection fields to email_logs
    op.add_column('email_logs',
        sa.Column('is_modification', sa.Boolean(), nullable=True, server_default='false')
    )
    op.add_column('email_logs',
        sa.Column('referenced_quote_number', sa.String(100), nullable=True)
    )
    op.add_column('email_logs',
        sa.Column('modification_type', sa.String(50), nullable=True)
    )

    # Add quote modification tracking fields to quote_requests
    # Note: Using batch mode for SQLite compatibility
    with op.batch_alter_table('quote_requests') as batch_op:
        batch_op.add_column(sa.Column('is_modification', sa.Boolean(), nullable=True, server_default='false'))
        batch_op.add_column(sa.Column('parent_quote_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('revision_number', sa.Integer(), nullable=True, server_default='1'))
        batch_op.add_column(sa.Column('modification_type', sa.String(50), nullable=True))
        batch_op.add_column(sa.Column('modification_notes', sa.Text(), nullable=True))


def downgrade():
    # Remove quote modification fields from quote_requests
    with op.batch_alter_table('quote_requests') as batch_op:
        batch_op.drop_column('modification_notes')
        batch_op.drop_column('modification_type')
        batch_op.drop_column('revision_number')
        batch_op.drop_column('parent_quote_id')
        batch_op.drop_column('is_modification')

    # Remove quote modification fields from email_logs
    op.drop_column('email_logs', 'modification_type')
    op.drop_column('email_logs', 'referenced_quote_number')
    op.drop_column('email_logs', 'is_modification')
