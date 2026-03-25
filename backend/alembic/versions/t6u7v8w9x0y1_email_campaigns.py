"""Add email_campaigns table

Revision ID: t6u7v8w9x0y1
Revises: s5t6u7v8w9x0
Create Date: 2026-03-25 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 't6u7v8w9x0y1'
down_revision: Union[str, None] = 's5t6u7v8w9x0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'email_campaigns',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('subject', sa.String(500), nullable=False),
        sa.Column('mailchimp_campaign_id', sa.String(100), nullable=True),
        sa.Column('recipient_count', sa.Integer(), server_default='0'),
        sa.Column('brief_summary', sa.String(200), nullable=True),
        sa.Column('sent_by', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('sent_at', sa.DateTime(), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table('email_campaigns')
