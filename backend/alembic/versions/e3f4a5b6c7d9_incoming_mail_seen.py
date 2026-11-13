"""Remember shipping emails already handled

Revision ID: e3f4a5b6c7d9
Revises: e2f3a4b5c6d8
Create Date: 2026-11-13 16:10:00.000000

The poll stores Graph internetMessageId (or the Graph id) so the same
message does not open a second review. Reviews keep that id too.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e3f4a5b6c7d9"
down_revision: Union[str, None] = "e2f3a4b5c6d8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("incoming_email_reviews", sa.Column("message_id", sa.String(length=400), nullable=True))
    op.create_index("ix_incoming_email_reviews_message_id", "incoming_email_reviews", ["message_id"], unique=True)
    op.create_table(
        "incoming_mail_seen",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("message_id", sa.String(length=400), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("message_id"),
    )
    op.create_index("ix_incoming_mail_seen_id", "incoming_mail_seen", ["id"])
    op.create_index("ix_incoming_mail_seen_message_id", "incoming_mail_seen", ["message_id"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_incoming_mail_seen_message_id", table_name="incoming_mail_seen")
    op.drop_index("ix_incoming_mail_seen_id", table_name="incoming_mail_seen")
    op.drop_table("incoming_mail_seen")
    op.drop_index("ix_incoming_email_reviews_message_id", table_name="incoming_email_reviews")
    op.drop_column("incoming_email_reviews", "message_id")
