"""Manual shop TV schedule entries

Revision ID: c8d9e0f1a2b3
Revises: b7c8d9e0f1a2
Create Date: 2026-11-16 21:20:00.000000

Staff type the shop schedule because Business Central sales orders stay
in Draft and fullyShipped is not a reliable off switch. These rows are
portal-only. The migration does not touch Business Central.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c8d9e0f1a2b3"
down_revision: Union[str, None] = "b7c8d9e0f1a2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "shop_schedule_entries",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("so_number", sa.String(length=40), nullable=True),
        sa.Column("customer_name", sa.String(length=200), nullable=True),
        sa.Column("lane", sa.String(length=20), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("time", sa.Time(), nullable=True),
        sa.Column("note", sa.String(length=200), nullable=True),
        sa.Column("done", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint(
            "lane IN ('pickup', 'delivery', 'receiving', 'production')",
            name="shop_schedule_entries_lane_chk",
        ),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_shop_schedule_entries_id", "shop_schedule_entries", ["id"])
    op.create_index("ix_shop_schedule_entries_so_number", "shop_schedule_entries", ["so_number"])
    op.create_index("ix_shop_schedule_entries_lane", "shop_schedule_entries", ["lane"])
    op.create_index("ix_shop_schedule_entries_date", "shop_schedule_entries", ["date"])
    op.create_index("ix_shop_schedule_entries_done", "shop_schedule_entries", ["done"])


def downgrade() -> None:
    op.drop_index("ix_shop_schedule_entries_done", table_name="shop_schedule_entries")
    op.drop_index("ix_shop_schedule_entries_date", table_name="shop_schedule_entries")
    op.drop_index("ix_shop_schedule_entries_lane", table_name="shop_schedule_entries")
    op.drop_index("ix_shop_schedule_entries_so_number", table_name="shop_schedule_entries")
    op.drop_index("ix_shop_schedule_entries_id", table_name="shop_schedule_entries")
    op.drop_table("shop_schedule_entries")
