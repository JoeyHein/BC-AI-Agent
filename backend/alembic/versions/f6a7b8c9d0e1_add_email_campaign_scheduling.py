"""Add scheduling fields to email_campaigns

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-05-27 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f6a7b8c9d0e1'
down_revision: Union[str, None] = 'e5f6a7b8c9d0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # status: 'sent' (immediate send) | 'scheduled' (queued at Mailchimp) | 'canceled'
    op.add_column('email_campaigns', sa.Column('status', sa.String(20), server_default='sent', nullable=False))
    # scheduled_at: the UTC time Mailchimp will release the campaign (null for immediate sends)
    op.add_column('email_campaigns', sa.Column('scheduled_at', sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column('email_campaigns', 'scheduled_at')
    op.drop_column('email_campaigns', 'status')
