"""Staff-only price and freight overrides on saved quotes.

Revision ID: c1d2e3f4a5b6
Revises: b7c8d9e0f1a2
Create Date: 2026-11-18

Customers can store arbitrary JSON on a saved quote. Line-price and freight
overrides live in this column instead, and only a staff request may write it.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c1d2e3f4a5b6"
down_revision: Union[str, None] = "b7c8d9e0f1a2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_column(table: str, column: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if table not in inspector.get_table_names():
        return False
    return column in {col["name"] for col in inspector.get_columns(table)}


def upgrade() -> None:
    # Some upgrade paths reach this revision without the customer-portal
    # tables. Production has saved_quote_configs already.
    if not _has_column("saved_quote_configs", "staff_price_adjustments") and (
        "saved_quote_configs" in sa.inspect(op.get_bind()).get_table_names()
    ):
        op.add_column(
            "saved_quote_configs",
            sa.Column("staff_price_adjustments", sa.JSON(), nullable=True),
        )


def downgrade() -> None:
    if _has_column("saved_quote_configs", "staff_price_adjustments"):
        op.drop_column("saved_quote_configs", "staff_price_adjustments")
