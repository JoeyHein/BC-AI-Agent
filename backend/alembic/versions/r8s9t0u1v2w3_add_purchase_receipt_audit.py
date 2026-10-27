"""Audit log for purchase-order receipts (Receive only)

Revision ID: r8s9t0u1v2w3
Revises: q7r8s9t0u1v2
Create Date: 2026-10-19

Each preview and each posted receipt records who, the PO, the lines and
quantities, and the vendor packing slip. Existing service keys that can
already read purchasing also gain purchasing:receive so the assistant key
can call the new route without being recreated.
"""
import json

from alembic import op
import sqlalchemy as sa

from app.services.staff_service_keys_service import grant_receive_scope


revision = "r8s9t0u1v2w3"
down_revision = "q7r8s9t0u1v2"
branch_labels = None
depends_on = None


def _write_scopes(conn, key_id: int, scopes: list) -> None:
    payload = json.dumps(scopes)
    if conn.dialect.name == "postgresql":
        conn.execute(
            sa.text(
                "UPDATE staff_service_keys SET scopes = CAST(:scopes AS json) WHERE id = :id"
            ),
            {"scopes": payload, "id": key_id},
        )
    else:
        conn.execute(
            sa.text("UPDATE staff_service_keys SET scopes = :scopes WHERE id = :id"),
            {"scopes": payload, "id": key_id},
        )


def upgrade():
    op.create_table(
        "purchase_receipt_audits",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("actor_email", sa.String(length=255), nullable=True),
        sa.Column("actor_name", sa.String(length=255), nullable=True),
        sa.Column("service_key_id", sa.Integer(), nullable=True),
        sa.Column("service_key_name", sa.String(length=200), nullable=True),
        sa.Column("po_number", sa.String(length=40), nullable=False),
        sa.Column("po_id", sa.String(length=64), nullable=True),
        sa.Column("vendor_number", sa.String(length=40), nullable=True),
        sa.Column("vendor_name", sa.String(length=200), nullable=True),
        sa.Column("vendor_shipment_no", sa.String(length=35), nullable=True),
        sa.Column("lines", sa.JSON(), nullable=False),
        sa.Column("dry_run", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("posted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("posting", sa.String(length=20), nullable=False, server_default="Receive"),
        sa.Column("invoice", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("bc_receipt_no", sa.String(length=40), nullable=True),
        sa.Column("outcome", sa.String(length=20), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["service_key_id"], ["staff_service_keys.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_purchase_receipt_audits_created_at",
        "purchase_receipt_audits",
        ["created_at"],
    )
    op.create_index(
        "ix_purchase_receipt_audits_po_number",
        "purchase_receipt_audits",
        ["po_number"],
    )

    conn = op.get_bind()
    rows = conn.execute(sa.text("SELECT id, scopes FROM staff_service_keys")).mappings().all()
    for row in rows:
        updated = grant_receive_scope(row["scopes"])
        if updated is not None:
            _write_scopes(conn, row["id"], updated)


def downgrade():
    conn = op.get_bind()
    rows = conn.execute(sa.text("SELECT id, scopes FROM staff_service_keys")).mappings().all()
    for row in rows:
        raw = row["scopes"]
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except json.JSONDecodeError:
                continue
        if not isinstance(raw, list) or "purchasing:receive" not in raw:
            continue
        _write_scopes(conn, row["id"], [item for item in raw if item != "purchasing:receive"])

    op.drop_index("ix_purchase_receipt_audits_po_number", table_name="purchase_receipt_audits")
    op.drop_index("ix_purchase_receipt_audits_created_at", table_name="purchase_receipt_audits")
    op.drop_table("purchase_receipt_audits")
