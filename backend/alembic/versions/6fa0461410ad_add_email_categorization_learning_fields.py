"""add_email_categorization_learning_fields

Revision ID: 6fa0461410ad
Revises: b6354dc31842
Create Date: 2026-01-05 11:30:51.223324

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '6fa0461410ad'
down_revision: Union[str, Sequence[str], None] = 'b6354dc31842'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Add email categorization learning fields to email_logs table
    op.add_column('email_logs', sa.Column('ai_category', sa.String(length=50), nullable=True))
    op.add_column('email_logs', sa.Column('ai_category_confidence', sa.Float(), nullable=True))
    op.add_column('email_logs', sa.Column('ai_category_reasoning', sa.Text(), nullable=True))
    op.add_column('email_logs', sa.Column('user_verified_category', sa.String(length=50), nullable=True))
    op.add_column('email_logs', sa.Column('categorization_correct', sa.Boolean(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    # Remove email categorization learning fields
    op.drop_column('email_logs', 'categorization_correct')
    op.drop_column('email_logs', 'user_verified_category')
    op.drop_column('email_logs', 'ai_category_reasoning')
    op.drop_column('email_logs', 'ai_category_confidence')
    op.drop_column('email_logs', 'ai_category')
