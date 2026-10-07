"""Add staff service API keys and usage audit

Revision ID: p6q7r8s9t0u1
Revises: o5p6q7r8s9t0
Create Date: 2026-10-07

Long-lived keys for scheduled staff-portal jobs. The plaintext is shown
once; only a bcrypt hash and a 12-character prefix are stored. Revocation
is a column update, so the next request sees it. Optional expires_at.
staff_service_key_audit records key name, route, and time for each attempt.
"""
from alembic import op
import sqlalchemy as sa


revision = "p6q7r8s9t0u1"
down_revision = "o5p6q7r8s9t0"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "staff_service_keys",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("key_prefix", sa.String(length=12), nullable=False),
        sa.Column("key_hash", sa.String(length=255), nullable=False),
        sa.Column("scopes", sa.JSON(), nullable=False),
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
            name="staff_service_keys_status_chk",
        ),
    )
    op.create_index("ix_staff_service_keys_id", "staff_service_keys", ["id"])
    op.create_index(
        "ix_staff_service_keys_key_prefix", "staff_service_keys", ["key_prefix"]
    )
    op.create_index("ix_staff_service_keys_status", "staff_service_keys", ["status"])

    op.create_table(
        "staff_service_key_audit",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("key_id", sa.Integer(), nullable=True),
        sa.Column("key_name", sa.String(length=200), nullable=True),
        sa.Column("key_prefix", sa.String(length=12), nullable=True),
        sa.Column("method", sa.String(length=10), nullable=False),
        sa.Column("path", sa.String(length=300), nullable=False),
        sa.Column("decision", sa.String(length=20), nullable=False),
        sa.Column("status_code", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["key_id"], ["staff_service_keys.id"], ondelete="SET NULL"
        ),
    )
    op.create_index(
        "ix_staff_service_key_audit_id", "staff_service_key_audit", ["id"]
    )
    op.create_index(
        "ix_staff_service_key_audit_key_id", "staff_service_key_audit", ["key_id"]
    )
    op.create_index(
        "ix_staff_service_key_audit_created_at",
        "staff_service_key_audit",
        ["created_at"],
    )


def downgrade():
    op.drop_index(
        "ix_staff_service_key_audit_created_at", table_name="staff_service_key_audit"
    )
    op.drop_index(
        "ix_staff_service_key_audit_key_id", table_name="staff_service_key_audit"
    )
    op.drop_index("ix_staff_service_key_audit_id", table_name="staff_service_key_audit")
    op.drop_table("staff_service_key_audit")
    op.drop_index("ix_staff_service_keys_status", table_name="staff_service_keys")
    op.drop_index("ix_staff_service_keys_key_prefix", table_name="staff_service_keys")
    op.drop_index("ix_staff_service_keys_id", table_name="staff_service_keys")
    op.drop_table("staff_service_keys")
