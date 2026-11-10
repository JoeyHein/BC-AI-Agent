"""Customer ordering profiles and quote field sources

Revision ID: a8b9c0d1e2f3
Revises: f3a4b5c6d7e8
Create Date: 2026-11-10 12:00:00.000000

Profiles are keyed by BC customer id. Quote requests record which
fields came from the email, the profile, or a system default, plus
any deviation (locked-rule conflict, silent track substitution,
unstocked colour swap).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a8b9c0d1e2f3"
down_revision: Union[str, None] = "f3a4b5c6d7e8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "customer_profiles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("bc_customer_id", sa.String(length=100), nullable=False),
        sa.Column("customer_number", sa.String(length=50), nullable=True),
        sa.Column("fields", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("contacts", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("email_domains", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("ship_to", sa.JSON(), nullable=True),
        sa.Column("contacts_locked", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("domains_locked", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("ship_to_locked", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("documents_seen", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_seeded_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_customer_profiles_bc_customer_id", "customer_profiles", ["bc_customer_id"], unique=True)
    op.create_index("ix_customer_profiles_customer_number", "customer_profiles", ["customer_number"])

    op.add_column("quote_requests", sa.Column("field_sources", sa.JSON(), nullable=True))
    op.add_column("quote_requests", sa.Column("deviations", sa.JSON(), nullable=True))
    op.add_column("quote_requests", sa.Column("matched_bc_customer_id", sa.String(length=100), nullable=True))
    op.add_column("quote_requests", sa.Column("customer_match", sa.JSON(), nullable=True))
    op.create_index("ix_quote_requests_matched_bc_customer_id", "quote_requests", ["matched_bc_customer_id"])


def downgrade() -> None:
    op.drop_index("ix_quote_requests_matched_bc_customer_id", table_name="quote_requests")
    op.drop_column("quote_requests", "customer_match")
    op.drop_column("quote_requests", "matched_bc_customer_id")
    op.drop_column("quote_requests", "deviations")
    op.drop_column("quote_requests", "field_sources")
    op.drop_index("ix_customer_profiles_customer_number", table_name="customer_profiles")
    op.drop_index("ix_customer_profiles_bc_customer_id", table_name="customer_profiles")
    op.drop_table("customer_profiles")
