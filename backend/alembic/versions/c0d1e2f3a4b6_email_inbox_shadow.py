"""Shadow notes live on the email, not in its attachments

Revision ID: c0d1e2f3a4b6
Revises: b9c0d1e2f4a5
Create Date: 2026-11-10 18:40:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c0d1e2f3a4b6"
down_revision: Union[str, None] = "b9c0d1e2f4a5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_column(table: str, column: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if table not in inspector.get_table_names():
        return False
    return column in {item["name"] for item in inspector.get_columns(table)}


def upgrade() -> None:
    # The profile migration test upgrades a database that never had email_logs.
    # Production does. Skip quietly when the table is not there yet.
    if not _has_column("email_logs", "id") and "email_logs" not in sa.inspect(op.get_bind()).get_table_names():
        return
    if _has_column("email_logs", "inbox_shadow"):
        return
    op.add_column("email_logs", sa.Column("inbox_shadow", sa.JSON(), nullable=True))


def downgrade() -> None:
    if not _has_column("email_logs", "inbox_shadow"):
        return
    op.drop_column("email_logs", "inbox_shadow")
