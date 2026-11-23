"""Supplier confirmations, date-change log, packing slips, O'Regan draft.

Revision ID: g2h3i4j5k6l7
Revises: c1d2e3f4a5b6
Create Date: 2026-11-23

The O'Regan customer update is inserted as a pending draft. It is not sent.
"""

from datetime import datetime

import sqlalchemy as sa
from alembic import op


revision = "g2h3i4j5k6l7"
down_revision = "c1d2e3f4a5b6"
branch_labels = None
depends_on = None

OREGAN_DEDUPE = "customer:SO-001295:2026-12-04:supplier-seed"


def upgrade():
    op.create_table(
        "supplier_confirmations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("dedupe_key", sa.String(200), nullable=False),
        sa.Column("vendor_key", sa.String(40), nullable=False),
        sa.Column("supplier_order_no", sa.String(60), nullable=True),
        sa.Column("our_po_number", sa.String(40), nullable=True),
        sa.Column("our_so_numbers", sa.JSON(), nullable=True),
        sa.Column("expected_receipt_date", sa.Date(), nullable=True),
        sa.Column("source", sa.String(40), nullable=False, server_default="acknowledgement"),
        sa.Column("source_email_id", sa.String(300), nullable=True),
        sa.Column("sender_email", sa.String(255), nullable=True),
        sa.Column("subject", sa.String(300), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="stored"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("dedupe_key", name="uq_supplier_confirmation_dedupe"),
    )
    op.create_index("ix_supplier_confirmations_vendor_key", "supplier_confirmations", ["vendor_key"])
    op.create_index("ix_supplier_confirmations_supplier_order_no", "supplier_confirmations", ["supplier_order_no"])
    op.create_index("ix_supplier_confirmations_our_po_number", "supplier_confirmations", ["our_po_number"])
    op.create_index("ix_supplier_confirmations_status", "supplier_confirmations", ["status"])

    op.create_table(
        "supplier_confirmation_sources",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source_email_id", sa.String(300), nullable=False),
        sa.Column("attachment_filename", sa.String(255), nullable=False),
        sa.Column("mailbox", sa.String(255), nullable=True),
        sa.Column("outcome", sa.String(20), nullable=False, server_default="parsed"),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_email_id", "attachment_filename", name="uq_supplier_confirmation_source"
        ),
    )

    op.create_table(
        "supplier_date_changes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("po_number", sa.String(40), nullable=False),
        sa.Column("supplier_order_no", sa.String(60), nullable=True),
        sa.Column("previous_date", sa.Date(), nullable=True),
        sa.Column("new_date", sa.Date(), nullable=True),
        sa.Column("bc_status", sa.String(20), nullable=False),
        sa.Column("bc_error", sa.Text(), nullable=True),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_supplier_date_changes_po_number", "supplier_date_changes", ["po_number"])
    op.create_index("ix_supplier_date_changes_bc_status", "supplier_date_changes", ["bc_status"])
    op.create_index("ix_supplier_date_changes_created_at", "supplier_date_changes", ["created_at"])

    op.create_table(
        "packing_slips",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("shipment_id", sa.String(100), nullable=True),
        sa.Column("shipment_number", sa.String(40), nullable=False),
        sa.Column("so_number", sa.String(40), nullable=True),
        sa.Column("customer_name", sa.String(255), nullable=True),
        sa.Column("customer_po", sa.String(80), nullable=True),
        sa.Column("customer_email", sa.String(255), nullable=True),
        sa.Column("posting_date", sa.Date(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("pdf_bytes", sa.LargeBinary(), nullable=True),
        sa.Column("line_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("backorder_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("send_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("sent_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("shipment_number", name="uq_packing_slip_shipment"),
    )
    op.create_index("ix_packing_slips_so_number", "packing_slips", ["so_number"])
    op.create_index("ix_packing_slips_status", "packing_slips", ["status"])

    _seed_oregan()


def _seed_oregan():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "ops_outbound_messages" not in inspector.get_table_names():
        return
    meta = sa.MetaData()
    messages = sa.Table("ops_outbound_messages", meta, autoload_with=bind)
    existing = bind.execute(
        sa.select(messages.c.id).where(messages.c.dedupe_key == OREGAN_DEDUPE)
    ).first()
    if existing:
        return
    now = datetime.utcnow()
    body = (
        "Hello O'Regan,\n\n"
        "Update on sales order SO-001295. We now expect 2026-12-04. "
        "PO-000959 and PO-001049 moved the date past the date you asked for. "
        "Sorry for the change.\n\n"
        "Joey\nOpen Distribution\n"
    )
    bind.execute(messages.insert().values(
        kind="customer_update",
        status="pending",
        dedupe_key=OREGAN_DEDUPE,
        to_email=None,
        subject="Update on SO-001295",
        body_text=body,
        so_number="SO-001295",
        po_number="PO-000959",
        context_json={
            "trigger": "supplier_date",
            "new_date": "2026-12-04",
            "customer_name": "O'Regan",
            "po_numbers": ["PO-000959", "PO-001049"],
            "reason": "Supplier date now 2026-12-04 on PO-000959 and PO-001049",
            "seed": True,
            "auto_send": False,
        },
        created_at=now,
        updated_at=now,
    ))
    if "ops_action_items" not in inspector.get_table_names():
        return
    actions = sa.Table("ops_action_items", meta, autoload_with=bind)
    key = f"customer_update:{OREGAN_DEDUPE}"
    if bind.execute(sa.select(actions.c.id).where(actions.c.auto_key == key)).first():
        return
    bind.execute(actions.insert().values(
        kind="customer_update",
        auto_key=key,
        auto_managed=True,
        title="Customer update needed: SO-001295 now expected 2026-12-04",
        detail="O'Regan. PO-000959 and PO-001049. Waiting for approval. Not sent.",
        so_number="SO-001295",
        po_number="PO-000959",
        status="open",
        created_at=now,
    ))


def downgrade():
    op.drop_index("ix_packing_slips_status", table_name="packing_slips")
    op.drop_index("ix_packing_slips_so_number", table_name="packing_slips")
    op.drop_table("packing_slips")
    op.drop_index("ix_supplier_date_changes_created_at", table_name="supplier_date_changes")
    op.drop_index("ix_supplier_date_changes_bc_status", table_name="supplier_date_changes")
    op.drop_index("ix_supplier_date_changes_po_number", table_name="supplier_date_changes")
    op.drop_table("supplier_date_changes")
    op.drop_table("supplier_confirmation_sources")
    op.drop_index("ix_supplier_confirmations_status", table_name="supplier_confirmations")
    op.drop_index("ix_supplier_confirmations_our_po_number", table_name="supplier_confirmations")
    op.drop_index("ix_supplier_confirmations_supplier_order_no", table_name="supplier_confirmations")
    op.drop_index("ix_supplier_confirmations_vendor_key", table_name="supplier_confirmations")
    op.drop_table("supplier_confirmations")
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "ops_outbound_messages" in inspector.get_table_names():
        bind.execute(sa.text(
            "DELETE FROM ops_outbound_messages WHERE dedupe_key = :key"
        ), {"key": OREGAN_DEDUPE})
    if "ops_action_items" in inspector.get_table_names():
        bind.execute(sa.text(
            "DELETE FROM ops_action_items WHERE auto_key = :key"
        ), {"key": f"customer_update:{OREGAN_DEDUPE}"})
