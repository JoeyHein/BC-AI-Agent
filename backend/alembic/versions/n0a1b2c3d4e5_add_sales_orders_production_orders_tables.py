"""Add sales_orders, production_orders, shipments, invoices tables

Revision ID: n0a1b2c3d4e5
Revises: a1b2c3d4e5f6
Create Date: 2026-03-03 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ENUM as PgENUM


# revision identifiers, used by Alembic.
revision: str = 'n0a1b2c3d4e5'
down_revision: Union[str, Sequence[str], None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create sales_orders, production_orders, shipments, and invoices tables."""

    # Create enum types (idempotent)
    op.execute("DO $$ BEGIN CREATE TYPE orderstatus AS ENUM ('pending', 'confirmed', 'in_production', 'ready_to_ship', 'shipped', 'invoiced', 'completed', 'cancelled'); EXCEPTION WHEN duplicate_object THEN null; END $$;")
    op.execute("DO $$ BEGIN CREATE TYPE productionstatus AS ENUM ('planned', 'released', 'in_progress', 'finished', 'cancelled'); EXCEPTION WHEN duplicate_object THEN null; END $$;")
    op.execute("DO $$ BEGIN CREATE TYPE invoicestatus AS ENUM ('draft', 'posted', 'paid', 'partially_paid', 'overdue', 'cancelled'); EXCEPTION WHEN duplicate_object THEN null; END $$;")

    order_status_enum = PgENUM('pending', 'confirmed', 'in_production', 'ready_to_ship', 'shipped', 'invoiced', 'completed', 'cancelled', name='orderstatus', create_type=False)
    production_status_enum = PgENUM('planned', 'released', 'in_progress', 'finished', 'cancelled', name='productionstatus', create_type=False)
    invoice_status_enum = PgENUM('draft', 'posted', 'paid', 'partially_paid', 'overdue', 'cancelled', name='invoicestatus', create_type=False)

    # Create sales_orders table
    op.create_table(
        'sales_orders',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('quote_request_id', sa.Integer(), nullable=True),
        sa.Column('bc_id', sa.String(length=100), nullable=True),
        sa.Column('bc_order_id', sa.String(length=100), nullable=True),
        sa.Column('bc_order_number', sa.String(length=50), nullable=True),
        sa.Column('bc_quote_number', sa.String(length=50), nullable=True),
        sa.Column('customer_id', sa.String(length=100), nullable=True),
        sa.Column('bc_customer_id', sa.String(length=100), nullable=True),
        sa.Column('customer_number', sa.String(length=50), nullable=True),
        sa.Column('customer_name', sa.String(length=255), nullable=True),
        sa.Column('customer_email', sa.String(length=255), nullable=True),
        sa.Column('status', order_status_enum, nullable=True),
        sa.Column('total_amount', sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column('currency', sa.String(length=10), nullable=True),
        sa.Column('order_date', sa.DateTime(), nullable=True),
        sa.Column('requested_delivery_date', sa.DateTime(), nullable=True),
        sa.Column('scheduled_date', sa.DateTime(), nullable=True),
        sa.Column('shipping_address', sa.Text(), nullable=True),
        sa.Column('billing_address', sa.Text(), nullable=True),
        sa.Column('external_document_number', sa.String(length=100), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('confirmed_at', sa.DateTime(), nullable=True),
        sa.Column('production_started_at', sa.DateTime(), nullable=True),
        sa.Column('production_completed_at', sa.DateTime(), nullable=True),
        sa.Column('shipped_at', sa.DateTime(), nullable=True),
        sa.Column('invoiced_at', sa.DateTime(), nullable=True),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.Column('last_synced_at', sa.DateTime(), nullable=True),
        sa.Column('bc_last_modified', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['quote_request_id'], ['quote_requests.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('bc_order_id')
    )
    op.create_index(op.f('ix_sales_orders_id'), 'sales_orders', ['id'], unique=False)
    op.create_index(op.f('ix_sales_orders_bc_id'), 'sales_orders', ['bc_id'], unique=False)
    op.create_index(op.f('ix_sales_orders_bc_order_id'), 'sales_orders', ['bc_order_id'], unique=True)
    op.create_index(op.f('ix_sales_orders_bc_order_number'), 'sales_orders', ['bc_order_number'], unique=False)
    op.create_index(op.f('ix_sales_orders_bc_customer_id'), 'sales_orders', ['bc_customer_id'], unique=False)
    op.create_index(op.f('ix_sales_orders_customer_number'), 'sales_orders', ['customer_number'], unique=False)
    op.create_index(op.f('ix_sales_orders_status'), 'sales_orders', ['status'], unique=False)
    op.create_index(op.f('ix_sales_orders_scheduled_date'), 'sales_orders', ['scheduled_date'], unique=False)

    # Create production_orders table
    op.create_table(
        'production_orders',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('sales_order_id', sa.Integer(), nullable=True),
        sa.Column('line_item_id', sa.Integer(), nullable=True),
        sa.Column('bc_prod_order_id', sa.String(length=100), nullable=True),
        sa.Column('bc_prod_order_number', sa.String(length=50), nullable=True),
        sa.Column('status', production_status_enum, nullable=True),
        sa.Column('item_type', sa.String(length=50), nullable=True),
        sa.Column('item_code', sa.String(length=100), nullable=True),
        sa.Column('item_description', sa.Text(), nullable=True),
        sa.Column('quantity', sa.Integer(), nullable=False),
        sa.Column('quantity_completed', sa.Integer(), nullable=True),
        sa.Column('specifications', sa.JSON(), nullable=True),
        sa.Column('inventory_allocated', sa.Boolean(), nullable=True, server_default='false'),
        sa.Column('inventory_allocation_id', sa.String(length=100), nullable=True),
        sa.Column('stock_available', sa.Integer(), nullable=True),
        sa.Column('stock_reserved', sa.Integer(), nullable=True),
        sa.Column('due_date', sa.DateTime(), nullable=True),
        sa.Column('start_date', sa.DateTime(), nullable=True),
        sa.Column('end_date', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('started_at', sa.DateTime(), nullable=True),
        sa.Column('finished_at', sa.DateTime(), nullable=True),
        sa.Column('last_synced_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['sales_order_id'], ['sales_orders.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('bc_prod_order_id')
    )
    op.create_index(op.f('ix_production_orders_id'), 'production_orders', ['id'], unique=False)
    op.create_index(op.f('ix_production_orders_bc_prod_order_id'), 'production_orders', ['bc_prod_order_id'], unique=True)
    op.create_index(op.f('ix_production_orders_bc_prod_order_number'), 'production_orders', ['bc_prod_order_number'], unique=False)
    op.create_index(op.f('ix_production_orders_status'), 'production_orders', ['status'], unique=False)
    op.create_index(op.f('ix_production_orders_item_type'), 'production_orders', ['item_type'], unique=False)
    op.create_index(op.f('ix_production_orders_sales_order_id'), 'production_orders', ['sales_order_id'], unique=False)

    # Create shipments table
    op.create_table(
        'shipments',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('sales_order_id', sa.Integer(), nullable=False),
        sa.Column('bc_shipment_id', sa.String(length=100), nullable=True),
        sa.Column('shipment_number', sa.String(length=50), nullable=True),
        sa.Column('shipped_date', sa.DateTime(), nullable=True),
        sa.Column('tracking_number', sa.String(length=100), nullable=True),
        sa.Column('carrier', sa.String(length=100), nullable=True),
        sa.Column('shipping_method', sa.String(length=100), nullable=True),
        sa.Column('ship_to_name', sa.String(length=255), nullable=True),
        sa.Column('ship_to_address', sa.JSON(), nullable=True),
        sa.Column('total_packages', sa.Integer(), nullable=True),
        sa.Column('total_weight', sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column('weight_unit', sa.String(length=10), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('delivered_at', sa.DateTime(), nullable=True),
        sa.Column('last_synced_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['sales_order_id'], ['sales_orders.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('bc_shipment_id')
    )
    op.create_index(op.f('ix_shipments_id'), 'shipments', ['id'], unique=False)
    op.create_index(op.f('ix_shipments_bc_shipment_id'), 'shipments', ['bc_shipment_id'], unique=True)
    op.create_index(op.f('ix_shipments_shipment_number'), 'shipments', ['shipment_number'], unique=False)
    op.create_index(op.f('ix_shipments_sales_order_id'), 'shipments', ['sales_order_id'], unique=False)

    # Create invoices table
    op.create_table(
        'invoices',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('sales_order_id', sa.Integer(), nullable=False),
        sa.Column('bc_invoice_id', sa.String(length=100), nullable=True),
        sa.Column('invoice_number', sa.String(length=50), nullable=True),
        sa.Column('status', invoice_status_enum, nullable=True),
        sa.Column('total_amount', sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column('tax_amount', sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column('currency', sa.String(length=10), nullable=True),
        sa.Column('due_date', sa.DateTime(), nullable=True),
        sa.Column('payment_terms', sa.String(length=50), nullable=True),
        sa.Column('amount_paid', sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column('amount_remaining', sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('posted_at', sa.DateTime(), nullable=True),
        sa.Column('paid_at', sa.DateTime(), nullable=True),
        sa.Column('last_synced_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['sales_order_id'], ['sales_orders.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('bc_invoice_id')
    )
    op.create_index(op.f('ix_invoices_id'), 'invoices', ['id'], unique=False)
    op.create_index(op.f('ix_invoices_bc_invoice_id'), 'invoices', ['bc_invoice_id'], unique=True)
    op.create_index(op.f('ix_invoices_invoice_number'), 'invoices', ['invoice_number'], unique=False)
    op.create_index(op.f('ix_invoices_status'), 'invoices', ['status'], unique=False)
    op.create_index(op.f('ix_invoices_sales_order_id'), 'invoices', ['sales_order_id'], unique=False)


def downgrade() -> None:
    """Drop sales_orders, production_orders, shipments, and invoices tables."""
    op.drop_index(op.f('ix_invoices_sales_order_id'), table_name='invoices')
    op.drop_index(op.f('ix_invoices_status'), table_name='invoices')
    op.drop_index(op.f('ix_invoices_invoice_number'), table_name='invoices')
    op.drop_index(op.f('ix_invoices_bc_invoice_id'), table_name='invoices')
    op.drop_index(op.f('ix_invoices_id'), table_name='invoices')
    op.drop_table('invoices')

    op.drop_index(op.f('ix_shipments_sales_order_id'), table_name='shipments')
    op.drop_index(op.f('ix_shipments_shipment_number'), table_name='shipments')
    op.drop_index(op.f('ix_shipments_bc_shipment_id'), table_name='shipments')
    op.drop_index(op.f('ix_shipments_id'), table_name='shipments')
    op.drop_table('shipments')

    op.drop_index(op.f('ix_production_orders_sales_order_id'), table_name='production_orders')
    op.drop_index(op.f('ix_production_orders_item_type'), table_name='production_orders')
    op.drop_index(op.f('ix_production_orders_status'), table_name='production_orders')
    op.drop_index(op.f('ix_production_orders_bc_prod_order_number'), table_name='production_orders')
    op.drop_index(op.f('ix_production_orders_bc_prod_order_id'), table_name='production_orders')
    op.drop_index(op.f('ix_production_orders_id'), table_name='production_orders')
    op.drop_table('production_orders')

    op.drop_index(op.f('ix_sales_orders_scheduled_date'), table_name='sales_orders')
    op.drop_index(op.f('ix_sales_orders_status'), table_name='sales_orders')
    op.drop_index(op.f('ix_sales_orders_customer_number'), table_name='sales_orders')
    op.drop_index(op.f('ix_sales_orders_bc_customer_id'), table_name='sales_orders')
    op.drop_index(op.f('ix_sales_orders_bc_order_number'), table_name='sales_orders')
    op.drop_index(op.f('ix_sales_orders_bc_order_id'), table_name='sales_orders')
    op.drop_index(op.f('ix_sales_orders_bc_id'), table_name='sales_orders')
    op.drop_index(op.f('ix_sales_orders_id'), table_name='sales_orders')
    op.drop_table('sales_orders')

    sa.Enum(name='invoicestatus').drop(op.get_bind(), checkfirst=True)
    sa.Enum(name='productionstatus').drop(op.get_bind(), checkfirst=True)
    sa.Enum(name='orderstatus').drop(op.get_bind(), checkfirst=True)
