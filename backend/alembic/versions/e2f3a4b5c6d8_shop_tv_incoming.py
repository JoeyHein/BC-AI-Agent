"""Shop TV incoming notices, supplier maps, and email review

Revision ID: e2f3a4b5c6d8
Revises: d1e2f3a4b5c7
Create Date: 2026-11-13 15:40:00.000000

Portal-only tables. Shipping mail updates these rows. Business Central
purchase orders stay read-only.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e2f3a4b5c6d8"
down_revision: Union[str, None] = "d1e2f3a4b5c7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "incoming_shipment_notices",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("our_po_number", sa.String(length=40), nullable=False),
        sa.Column("supplier_order_no", sa.String(length=40), nullable=True),
        sa.Column("carrier", sa.String(length=80), nullable=True),
        sa.Column("tracking", sa.String(length=80), nullable=True),
        sa.Column("eta", sa.Date(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="expected"),
        sa.Column("confidence", sa.String(length=20), nullable=False, server_default="high"),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("our_po_number"),
    )
    op.create_index("ix_incoming_shipment_notices_id", "incoming_shipment_notices", ["id"])
    op.create_index("ix_incoming_shipment_notices_our_po_number", "incoming_shipment_notices", ["our_po_number"])

    op.create_table(
        "supplier_order_maps",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("supplier_key", sa.String(length=40), nullable=False),
        sa.Column("supplier_order_no", sa.String(length=40), nullable=False),
        sa.Column("our_po_number", sa.String(length=40), nullable=False),
        sa.Column("sales_orders_json", sa.JSON(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("supplier_key", "supplier_order_no", name="uq_supplier_order_map"),
    )
    op.create_index("ix_supplier_order_maps_id", "supplier_order_maps", ["id"])
    op.create_index("ix_supplier_order_maps_supplier_key", "supplier_order_maps", ["supplier_key"])
    op.create_index("ix_supplier_order_maps_supplier_order_no", "supplier_order_maps", ["supplier_order_no"])
    op.create_index("ix_supplier_order_maps_our_po_number", "supplier_order_maps", ["our_po_number"])

    op.create_table(
        "incoming_email_reviews",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("sender", sa.String(length=255), nullable=True),
        sa.Column("subject", sa.String(length=300), nullable=True),
        sa.Column("extracted_json", sa.JSON(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("confidence", sa.String(length=20), nullable=False, server_default="low"),
        sa.Column("proposed_po", sa.String(length=40), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_incoming_email_reviews_id", "incoming_email_reviews", ["id"])
    op.create_index("ix_incoming_email_reviews_status", "incoming_email_reviews", ["status"])
    op.create_index("ix_incoming_email_reviews_created_at", "incoming_email_reviews", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_incoming_email_reviews_created_at", table_name="incoming_email_reviews")
    op.drop_index("ix_incoming_email_reviews_status", table_name="incoming_email_reviews")
    op.drop_index("ix_incoming_email_reviews_id", table_name="incoming_email_reviews")
    op.drop_table("incoming_email_reviews")
    op.drop_index("ix_supplier_order_maps_our_po_number", table_name="supplier_order_maps")
    op.drop_index("ix_supplier_order_maps_supplier_order_no", table_name="supplier_order_maps")
    op.drop_index("ix_supplier_order_maps_supplier_key", table_name="supplier_order_maps")
    op.drop_index("ix_supplier_order_maps_id", table_name="supplier_order_maps")
    op.drop_table("supplier_order_maps")
    op.drop_index("ix_incoming_shipment_notices_our_po_number", table_name="incoming_shipment_notices")
    op.drop_index("ix_incoming_shipment_notices_id", table_name="incoming_shipment_notices")
    op.drop_table("incoming_shipment_notices")
