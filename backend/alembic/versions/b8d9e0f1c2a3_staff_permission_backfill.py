"""Give existing staff the access they already had.

Revision ID: b8d9e0f1c2a3
Revises: a7c8e9f0b1d2
Create Date: 2026-10-27

Joey's admin login becomes Owner. Other admins stay Admin. Reviewers
become Managers and keep the extra screens that only checked "is staff".
Viewers keep those screens too, except purchasing. Customers and the
automation identity are left alone.

Runs in its own revision so PostgreSQL has already committed the new
userrole labels.
"""
import json

from alembic import op
import sqlalchemy as sa

from app.services.staff_permissions import plan_backfill


revision = "b8d9e0f1c2a3"
down_revision = "a7c8e9f0b1d2"
branch_labels = None
depends_on = None


def _apply(bind, user_id, role_name, permissions):
    payload = None if permissions is None else json.dumps(permissions)
    if bind.dialect.name == "postgresql":
        bind.execute(
            sa.text(
                "UPDATE users SET role = CAST(:role AS userrole), "
                "permissions = CAST(:permissions AS json) WHERE id = :id"
            ),
            {"id": user_id, "role": role_name, "permissions": payload},
        )
        return
    bind.execute(
        sa.text("UPDATE users SET role = :role, permissions = :permissions WHERE id = :id"),
        {"id": user_id, "role": role_name, "permissions": payload},
    )


def upgrade():
    bind = op.get_bind()
    rows = bind.execute(sa.text("SELECT id, email, role, user_type, permissions FROM users")).mappings()
    for row in rows:
        planned = plan_backfill(row["email"], str(row["role"]) if row["role"] is not None else None, row["user_type"], row["permissions"])
        if planned is None:
            continue
        _apply(bind, row["id"], planned[0], planned[1])


def downgrade():
    """Map the new presets back onto the three old roles. Custom flags are dropped with the column."""
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        bind.execute(sa.text("UPDATE users SET role = 'VIEWER' WHERE role::text = 'CONFIGURATOR'"))
        bind.execute(sa.text("UPDATE users SET role = 'ADMIN' WHERE role::text = 'OWNER'"))
        bind.execute(
            sa.text(
                "UPDATE users SET role = 'REVIEWER' "
                "WHERE role::text IN ('MANAGER', 'SALES', 'PURCHASING', 'WAREHOUSE')"
            )
        )
        return
    bind.execute(sa.text("UPDATE users SET role = 'VIEWER' WHERE role = 'CONFIGURATOR'"))
    bind.execute(sa.text("UPDATE users SET role = 'ADMIN' WHERE role = 'OWNER'"))
    bind.execute(
        sa.text(
            "UPDATE users SET role = 'REVIEWER' "
            "WHERE role IN ('MANAGER', 'SALES', 'PURCHASING', 'WAREHOUSE')"
        )
    )
