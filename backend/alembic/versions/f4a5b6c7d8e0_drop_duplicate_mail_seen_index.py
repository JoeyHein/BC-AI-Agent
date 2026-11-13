"""Drop the extra unique index on incoming mail

Revision ID: f4a5b6c7d8e0
Revises: e3f4a5b6c7d9
Create Date: 2026-11-13 16:20:00.000000

incoming_mail_seen.message_id already has one unique constraint.
A second unique index on the same column is removed when it exists.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f4a5b6c7d8e0"
down_revision: Union[str, None] = "e3f4a5b6c7d9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    indexes = sa.inspect(bind).get_indexes("incoming_mail_seen")
    if any(index.get("name") == "ix_incoming_mail_seen_message_id" for index in indexes):
        op.drop_index("ix_incoming_mail_seen_message_id", table_name="incoming_mail_seen")


def downgrade() -> None:
    # The unique constraint on message_id stays. Putting the extra index
    # back would restore the duplicate this revision removes.
    pass
