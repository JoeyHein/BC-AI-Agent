"""add is_customer_admin to users for customer-managed team

Revision ID: x0y1z2a3b4c5
Revises: w9x0y1z2a3b4
Create Date: 2026-05-11

Adds the `is_customer_admin` boolean to the users table. A customer-admin
is a CUSTOMER-type user who can add/remove/disable other staff users on
their BC customer account.

Backfill rules:
- Every CUSTOMER user with NO bc_customer_id becomes an admin (they're
  a solo account; they're inherently the admin of their own login).
- For each bc_customer_id that has at least one CUSTOMER user, the
  OLDEST user (lowest id) gets is_customer_admin=True. They were
  effectively the "primary" / anchor before this field existed.
- Internal (non-CUSTOMER) users are unaffected and stay False.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'x0y1z2a3b4c5'
down_revision: Union[str, None] = 'w9x0y1z2a3b4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'users',
        sa.Column(
            'is_customer_admin',
            sa.Boolean(),
            nullable=False,
            server_default=sa.text('false'),
        ),
    )

    # Backfill: solo customer users get admin automatically.
    op.execute("""
        UPDATE users
        SET is_customer_admin = TRUE
        WHERE user_type = 'CUSTOMER'
          AND bc_customer_id IS NULL
    """)

    # Backfill: oldest user per bc_customer_id (the anchor) gets admin.
    # Works on both Postgres and SQLite (no DISTINCT ON required).
    op.execute("""
        UPDATE users
        SET is_customer_admin = TRUE
        WHERE id IN (
            SELECT MIN(id)
            FROM users
            WHERE user_type = 'CUSTOMER' AND bc_customer_id IS NOT NULL
            GROUP BY bc_customer_id
        )
    """)


def downgrade() -> None:
    op.drop_column('users', 'is_customer_admin')
