"""Add revocable shop TV kiosk tokens

Revision ID: d1e2f3a4b5c7
Revises: c0d1e2f3a4b6
Create Date: 2026-11-12 16:10:00.000000

The shop TV board flag lives in app_settings (shop_tv_board) and needs
no new table. These tokens are the cast-URL secret: hashed, read-only,
and scoped to the board. Revoking a row stops the TV on its next refresh.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d1e2f3a4b5c7"
down_revision: Union[str, None] = "c0d1e2f3a4b6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "shop_tv_kiosk_tokens",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("key_prefix", sa.String(length=12), nullable=False),
        sa.Column("key_hash", sa.String(length=64), nullable=False),
        sa.Column("scope", sa.String(length=40), nullable=False, server_default="shop_tv:read"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="active"),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column("revoked_by_user_id", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["revoked_by_user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.CheckConstraint(
            "status IN ('active', 'revoked')",
            name="shop_tv_kiosk_tokens_status_chk",
        ),
    )
    op.create_index("ix_shop_tv_kiosk_tokens_id", "shop_tv_kiosk_tokens", ["id"])
    op.create_index(
        "ix_shop_tv_kiosk_tokens_key_prefix", "shop_tv_kiosk_tokens", ["key_prefix"]
    )
    op.create_index("ix_shop_tv_kiosk_tokens_status", "shop_tv_kiosk_tokens", ["status"])


def downgrade() -> None:
    op.drop_index("ix_shop_tv_kiosk_tokens_status", table_name="shop_tv_kiosk_tokens")
    op.drop_index("ix_shop_tv_kiosk_tokens_key_prefix", table_name="shop_tv_kiosk_tokens")
    op.drop_index("ix_shop_tv_kiosk_tokens_id", table_name="shop_tv_kiosk_tokens")
    op.drop_table("shop_tv_kiosk_tokens")
