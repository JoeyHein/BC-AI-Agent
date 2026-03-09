"""Add OPENDC platform tables (parts catalog, agents, inventory, PO)

Revision ID: p2q3r4s5t6u7
Revises: o1p2q3r4s5t6
Create Date: 2026-03-09 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'p2q3r4s5t6u7'
down_revision: Union[str, None] = 'o1p2q3r4s5t6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Clean up any partially-created tables from a previous failed migration attempt
    # (PostgreSQL may leave sequences/tables behind if a prior run failed mid-transaction)
    op.execute("DROP TABLE IF EXISTS po_agent_log CASCADE")
    op.execute("DROP TABLE IF EXISTS demand_signals CASCADE")
    op.execute("DROP TABLE IF EXISTS special_order_queue CASCADE")
    op.execute("DROP TABLE IF EXISTS duplicate_candidates CASCADE")
    op.execute("DROP TABLE IF EXISTS catalog_review_queue CASCADE")
    op.execute("DROP TABLE IF EXISTS bc_staging CASCADE")
    op.execute("DROP TABLE IF EXISTS stocked_inside_diameters CASCADE")
    op.execute("DROP TABLE IF EXISTS wire_size_constraints CASCADE")
    op.execute("DROP TABLE IF EXISTS door_weight_defaults CASCADE")
    op.execute("DROP TABLE IF EXISTS drum_types CASCADE")
    op.execute("DROP TABLE IF EXISTS parts CASCADE")

    # --- parts ---
    op.create_table(
        'parts',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('bc_item_id', sa.String(100), nullable=True),
        sa.Column('bc_item_number', sa.String(100), nullable=False),
        sa.Column('bc_description', sa.String(500), nullable=True),
        sa.Column('category', sa.String(50), nullable=False),
        sa.Column('subcategory', sa.String(50), nullable=True),
        sa.Column('attributes', sa.JSON(), nullable=True),
        sa.Column('unit_cost', sa.Numeric(10, 2), nullable=True),
        sa.Column('retail_price', sa.Numeric(10, 2), nullable=True),
        sa.Column('vendor_id', sa.String(100), nullable=True),
        sa.Column('vendor_name', sa.String(255), nullable=True),
        sa.Column('lead_time_days', sa.Integer(), nullable=True),
        sa.Column('compatibility', sa.JSON(), nullable=True),
        sa.Column('catalog_status', sa.String(30), nullable=False, server_default='pending_review'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_parts_id'), 'parts', ['id'])
    op.create_index(op.f('ix_parts_bc_item_id'), 'parts', ['bc_item_id'])
    op.create_index(op.f('ix_parts_bc_item_number'), 'parts', ['bc_item_number'])
    op.create_index(op.f('ix_parts_category'), 'parts', ['category'])
    op.create_index(op.f('ix_parts_catalog_status'), 'parts', ['catalog_status'])

    # --- drum_types ---
    op.create_table(
        'drum_types',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('drum_model', sa.String(50), nullable=False),
        sa.Column('radius_inches', sa.Float(), nullable=False),
        sa.Column('lift_type', sa.String(30), nullable=False),
        sa.Column('max_door_height_inches', sa.Integer(), nullable=True),
        sa.Column('description', sa.String(255), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('drum_model'),
    )
    op.create_index(op.f('ix_drum_types_id'), 'drum_types', ['id'])

    # --- door_weight_defaults ---
    op.create_table(
        'door_weight_defaults',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('door_model', sa.String(50), nullable=False),
        sa.Column('width_inches', sa.Integer(), nullable=False),
        sa.Column('height_inches', sa.Integer(), nullable=False),
        sa.Column('weight_lbs', sa.Float(), nullable=False),
        sa.Column('material', sa.String(50), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_door_weight_defaults_id'), 'door_weight_defaults', ['id'])
    op.create_index(op.f('ix_door_weight_defaults_door_model'), 'door_weight_defaults', ['door_model'])

    # --- wire_size_constraints ---
    op.create_table(
        'wire_size_constraints',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('wire_diameter', sa.Float(), nullable=False),
        sa.Column('inside_diameter', sa.Float(), nullable=False),
        sa.Column('cycle_rating', sa.Integer(), nullable=False),
        sa.Column('min_ippt', sa.Float(), nullable=True),
        sa.Column('max_ippt', sa.Float(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_wire_size_constraints_id'), 'wire_size_constraints', ['id'])

    # --- stocked_inside_diameters ---
    op.create_table(
        'stocked_inside_diameters',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('inside_diameter', sa.Float(), nullable=False),
        sa.Column('description', sa.String(100), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('inside_diameter'),
    )
    op.create_index(op.f('ix_stocked_inside_diameters_id'), 'stocked_inside_diameters', ['id'])

    # --- bc_staging ---
    op.create_table(
        'bc_staging',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('bc_item_id', sa.String(100), nullable=False),
        sa.Column('bc_item_number', sa.String(100), nullable=False),
        sa.Column('bc_description', sa.String(500), nullable=True),
        sa.Column('bc_unit_cost', sa.Numeric(10, 2), nullable=True),
        sa.Column('bc_unit_price', sa.Numeric(10, 2), nullable=True),
        sa.Column('bc_inventory', sa.Float(), nullable=True),
        sa.Column('bc_raw_data', sa.JSON(), nullable=True),
        sa.Column('is_processed', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('classified_category', sa.String(50), nullable=True),
        sa.Column('enriched_attributes', sa.JSON(), nullable=True),
        sa.Column('processing_notes', sa.Text(), nullable=True),
        sa.Column('pipeline_run_id', sa.String(50), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('processed_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_bc_staging_id'), 'bc_staging', ['id'])
    op.create_index(op.f('ix_bc_staging_bc_item_id'), 'bc_staging', ['bc_item_id'])
    op.create_index(op.f('ix_bc_staging_bc_item_number'), 'bc_staging', ['bc_item_number'])
    op.create_index(op.f('ix_bc_staging_is_processed'), 'bc_staging', ['is_processed'])
    op.create_index(op.f('ix_bc_staging_pipeline_run_id'), 'bc_staging', ['pipeline_run_id'])

    # --- catalog_review_queue ---
    op.create_table(
        'catalog_review_queue',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('staging_id', sa.Integer(), nullable=True),
        sa.Column('bc_item_number', sa.String(100), nullable=False),
        sa.Column('bc_description', sa.String(500), nullable=True),
        sa.Column('reason', sa.String(100), nullable=False),
        sa.Column('suggested_category', sa.String(50), nullable=True),
        sa.Column('suggested_attributes', sa.JSON(), nullable=True),
        sa.Column('is_resolved', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('resolved_category', sa.String(50), nullable=True),
        sa.Column('resolved_attributes', sa.JSON(), nullable=True),
        sa.Column('resolved_by', sa.Integer(), nullable=True),
        sa.Column('resolved_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['staging_id'], ['bc_staging.id']),
        sa.ForeignKeyConstraint(['resolved_by'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_catalog_review_queue_id'), 'catalog_review_queue', ['id'])
    op.create_index(op.f('ix_catalog_review_queue_bc_item_number'), 'catalog_review_queue', ['bc_item_number'])
    op.create_index(op.f('ix_catalog_review_queue_is_resolved'), 'catalog_review_queue', ['is_resolved'])

    # --- duplicate_candidates ---
    op.create_table(
        'duplicate_candidates',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('item_a_number', sa.String(100), nullable=False),
        sa.Column('item_b_number', sa.String(100), nullable=False),
        sa.Column('item_a_id', sa.Integer(), nullable=True),
        sa.Column('item_b_id', sa.Integer(), nullable=True),
        sa.Column('similarity_score', sa.Float(), nullable=False),
        sa.Column('match_reasons', sa.JSON(), nullable=True),
        sa.Column('is_resolved', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('resolution', sa.String(50), nullable=True),
        sa.Column('resolved_by', sa.Integer(), nullable=True),
        sa.Column('resolved_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['item_a_id'], ['parts.id']),
        sa.ForeignKeyConstraint(['item_b_id'], ['parts.id']),
        sa.ForeignKeyConstraint(['resolved_by'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_duplicate_candidates_id'), 'duplicate_candidates', ['id'])
    op.create_index(op.f('ix_duplicate_candidates_item_a_number'), 'duplicate_candidates', ['item_a_number'])
    op.create_index(op.f('ix_duplicate_candidates_item_b_number'), 'duplicate_candidates', ['item_b_number'])
    op.create_index(op.f('ix_duplicate_candidates_is_resolved'), 'duplicate_candidates', ['is_resolved'])

    # --- special_order_queue ---
    op.create_table(
        'special_order_queue',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('customer_user_id', sa.Integer(), nullable=False),
        sa.Column('bc_customer_id', sa.String(100), nullable=True),
        sa.Column('wire_diameter', sa.Float(), nullable=False),
        sa.Column('coil_diameter', sa.Float(), nullable=False),
        sa.Column('spring_length', sa.Float(), nullable=False),
        sa.Column('wind_direction', sa.String(5), nullable=False),
        sa.Column('quantity', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('spring_type', sa.String(10), nullable=True),
        sa.Column('door_width', sa.Float(), nullable=True),
        sa.Column('door_height', sa.Float(), nullable=True),
        sa.Column('door_weight', sa.Float(), nullable=True),
        sa.Column('calculation_data', sa.JSON(), nullable=True),
        sa.Column('status', sa.String(20), nullable=False, server_default='pending'),
        sa.Column('admin_notes', sa.Text(), nullable=True),
        sa.Column('quoted_price', sa.Numeric(10, 2), nullable=True),
        sa.Column('quoted_lead_time_days', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['customer_user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_special_order_queue_id'), 'special_order_queue', ['id'])
    op.create_index(op.f('ix_special_order_queue_customer_user_id'), 'special_order_queue', ['customer_user_id'])
    op.create_index(op.f('ix_special_order_queue_status'), 'special_order_queue', ['status'])

    # --- demand_signals ---
    op.create_table(
        'demand_signals',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('part_id', sa.Integer(), nullable=True),
        sa.Column('bc_item_number', sa.String(100), nullable=False),
        sa.Column('signal_type', sa.String(30), nullable=False),
        sa.Column('severity', sa.Integer(), nullable=False, server_default='5'),
        sa.Column('current_stock', sa.Float(), nullable=True),
        sa.Column('reorder_point', sa.Float(), nullable=True),
        sa.Column('avg_daily_demand', sa.Float(), nullable=True),
        sa.Column('days_of_stock', sa.Float(), nullable=True),
        sa.Column('recommended_qty', sa.Float(), nullable=True),
        sa.Column('recommended_vendor', sa.String(255), nullable=True),
        sa.Column('estimated_lead_time_days', sa.Integer(), nullable=True),
        sa.Column('is_acknowledged', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('acknowledged_by', sa.Integer(), nullable=True),
        sa.Column('acknowledged_at', sa.DateTime(), nullable=True),
        sa.Column('linked_po_id', sa.Integer(), nullable=True),
        sa.Column('review_run_id', sa.String(50), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['part_id'], ['parts.id']),
        sa.ForeignKeyConstraint(['acknowledged_by'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_demand_signals_id'), 'demand_signals', ['id'])
    op.create_index(op.f('ix_demand_signals_bc_item_number'), 'demand_signals', ['bc_item_number'])
    op.create_index(op.f('ix_demand_signals_signal_type'), 'demand_signals', ['signal_type'])
    op.create_index(op.f('ix_demand_signals_is_acknowledged'), 'demand_signals', ['is_acknowledged'])
    op.create_index(op.f('ix_demand_signals_review_run_id'), 'demand_signals', ['review_run_id'])

    # --- po_agent_log ---
    op.create_table(
        'po_agent_log',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('vendor_id', sa.String(100), nullable=True),
        sa.Column('vendor_name', sa.String(255), nullable=False),
        sa.Column('status', sa.String(20), nullable=False, server_default='draft'),
        sa.Column('total_amount', sa.Numeric(10, 2), nullable=True),
        sa.Column('currency', sa.String(10), nullable=False, server_default='CAD'),
        sa.Column('line_items', sa.JSON(), nullable=False),
        sa.Column('demand_signal_ids', sa.JSON(), nullable=True),
        sa.Column('bc_po_id', sa.String(100), nullable=True),
        sa.Column('bc_po_number', sa.String(50), nullable=True),
        sa.Column('approved_by', sa.Integer(), nullable=True),
        sa.Column('approved_at', sa.DateTime(), nullable=True),
        sa.Column('rejected_by', sa.Integer(), nullable=True),
        sa.Column('rejected_at', sa.DateTime(), nullable=True),
        sa.Column('rejection_reason', sa.Text(), nullable=True),
        sa.Column('po_run_id', sa.String(50), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.Column('submitted_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['approved_by'], ['users.id']),
        sa.ForeignKeyConstraint(['rejected_by'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_po_agent_log_id'), 'po_agent_log', ['id'])
    op.create_index(op.f('ix_po_agent_log_status'), 'po_agent_log', ['status'])
    op.create_index(op.f('ix_po_agent_log_po_run_id'), 'po_agent_log', ['po_run_id'])


def downgrade() -> None:
    op.drop_table('po_agent_log')
    op.drop_table('demand_signals')
    op.drop_table('special_order_queue')
    op.drop_table('duplicate_candidates')
    op.drop_table('catalog_review_queue')
    op.drop_table('bc_staging')
    op.drop_table('stocked_inside_diameters')
    op.drop_table('wire_size_constraints')
    op.drop_table('door_weight_defaults')
    op.drop_table('drum_types')
    op.drop_table('parts')
