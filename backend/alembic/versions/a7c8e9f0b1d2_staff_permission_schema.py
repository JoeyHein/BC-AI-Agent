"""Staff permission columns and the access-change log.

Revision ID: a7c8e9f0b1d2
Revises: q7r8s9t0u1v2
Create Date: 2026-10-27

PostgreSQL cannot use a new enum value in the same transaction that adds
it. This revision only adds the labels and columns. The next revision
fills existing rows.
"""
from alembic import op
import sqlalchemy as sa


revision = "a7c8e9f0b1d2"
down_revision = "q7r8s9t0u1v2"
branch_labels = None
depends_on = None

NEW_ROLES = ("OWNER", "MANAGER", "SALES", "PURCHASING", "WAREHOUSE", "CONFIGURATOR")


def upgrade():
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        with op.get_context().autocommit_block():
            for name in NEW_ROLES:
                op.execute(f"ALTER TYPE userrole ADD VALUE IF NOT EXISTS '{name}'")

    op.add_column("users", sa.Column("permissions", sa.JSON(), nullable=True))
    op.add_column(
        "users",
        sa.Column(
            "invite_pending",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.create_table(
        "staff_access_audit",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("actor_user_id", sa.Integer(), nullable=True),
        sa.Column("actor_email", sa.String(length=255), nullable=True),
        sa.Column("target_user_id", sa.Integer(), nullable=True),
        sa.Column("target_email", sa.String(length=255), nullable=True),
        sa.Column("action", sa.String(length=40), nullable=False),
        sa.Column("detail", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["target_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_staff_access_audit_id", "staff_access_audit", ["id"], unique=False)


def downgrade():
    op.drop_index("ix_staff_access_audit_id", table_name="staff_access_audit")
    op.drop_table("staff_access_audit")
    op.drop_column("users", "invite_pending")
    op.drop_column("users", "permissions")
    # PostgreSQL cannot drop a value from userrole while the type is in use.
    # The data revision maps new roles back onto ADMIN / REVIEWER first.
