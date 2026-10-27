"""Creator tag and per-user counter for configurator quotes.

Revision ID: c9e0f1a2b3c4
Revises: b8d9e0f1c2a3
Create Date: 2026-10-27

Stores who generated a door-configurator sales quote (staff user or the
email auto-quote counter) so the tag is queryable even when External
Document No. is a customer PO.
"""
from alembic import op
import sqlalchemy as sa


revision = "c9e0f1a2b3c4"
down_revision = "b8d9e0f1c2a3"
branch_labels = None
depends_on = None


def _add_creator_columns(table: str) -> None:
    op.add_column(table, sa.Column("creator_user_id", sa.Integer(), nullable=True))
    op.add_column(table, sa.Column("creator_email", sa.String(length=255), nullable=True))
    op.add_column(table, sa.Column("creator_tag", sa.String(length=35), nullable=True))
    op.create_index(f"ix_{table}_creator_user_id", table, ["creator_user_id"])
    op.create_index(f"ix_{table}_creator_tag", table, ["creator_tag"])
    op.create_foreign_key(
        f"fk_{table}_creator_user_id_users",
        table,
        "users",
        ["creator_user_id"],
        ["id"],
        ondelete="SET NULL",
    )


def _drop_creator_columns(table: str) -> None:
    op.drop_constraint(f"fk_{table}_creator_user_id_users", table, type_="foreignkey")
    op.drop_index(f"ix_{table}_creator_tag", table_name=table)
    op.drop_index(f"ix_{table}_creator_user_id", table_name=table)
    op.drop_column(table, "creator_tag")
    op.drop_column(table, "creator_email")
    op.drop_column(table, "creator_user_id")


def upgrade():
    op.create_table(
        "configurator_quote_counters",
        sa.Column("counter_key", sa.String(length=64), primary_key=True),
        sa.Column("last_issued", sa.Integer(), nullable=False, server_default="0"),
    )
    _add_creator_columns("quote_snapshots")
    _add_creator_columns("saved_quote_configs")


def downgrade():
    _drop_creator_columns("saved_quote_configs")
    _drop_creator_columns("quote_snapshots")
    op.drop_table("configurator_quote_counters")
