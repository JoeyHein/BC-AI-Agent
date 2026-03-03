"""Add production tasks table

Revision ID: c7d8e9f0a1b2
Revises: a1b2c3d4e5f6
Create Date: 2026-01-30 08:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ENUM as PgENUM


# revision identifiers, used by Alembic.
revision = 'c7d8e9f0a1b2'
down_revision = 'n0a1b2c3d4e5'
branch_labels = None
depends_on = None


def upgrade():
    # Create task completion status enum (idempotent raw SQL)
    op.execute("DO $$ BEGIN CREATE TYPE taskcompletionstatus AS ENUM ('pending', 'in_progress', 'completed', 'blocked'); EXCEPTION WHEN duplicate_object THEN null; END $$;")
    task_status_enum = PgENUM('pending', 'in_progress', 'completed', 'blocked', name='taskcompletionstatus', create_type=False)

    # Create production_tasks table
    op.create_table(
        'production_tasks',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('production_order_id', sa.Integer(), nullable=True),
        sa.Column('bc_prod_order_no', sa.String(50), nullable=True),
        sa.Column('bc_line_no', sa.Integer(), nullable=True),
        sa.Column('item_no', sa.String(100), nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('quantity_required', sa.Float(), nullable=True, default=1),
        sa.Column('quantity_completed', sa.Float(), nullable=True, default=0),
        sa.Column('unit_of_measure', sa.String(20), nullable=True),
        sa.Column('material_available', sa.Float(), nullable=True, default=0),
        sa.Column('material_needed', sa.Float(), nullable=True, default=0),
        sa.Column('status', task_status_enum, nullable=True, default='pending'),
        sa.Column('scheduled_date', sa.DateTime(), nullable=True),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.Column('completed_by', sa.String(50), nullable=True),
        sa.Column('bc_synced', sa.Boolean(), nullable=True, default=False),
        sa.Column('bc_sync_error', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['production_order_id'], ['production_orders.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_production_tasks_id'), 'production_tasks', ['id'], unique=False)
    op.create_index(op.f('ix_production_tasks_bc_prod_order_no'), 'production_tasks', ['bc_prod_order_no'], unique=False)
    op.create_index(op.f('ix_production_tasks_item_no'), 'production_tasks', ['item_no'], unique=False)
    op.create_index(op.f('ix_production_tasks_status'), 'production_tasks', ['status'], unique=False)
    op.create_index(op.f('ix_production_tasks_scheduled_date'), 'production_tasks', ['scheduled_date'], unique=False)
    op.create_index(op.f('ix_production_tasks_production_order_id'), 'production_tasks', ['production_order_id'], unique=False)


def downgrade():
    op.drop_index(op.f('ix_production_tasks_production_order_id'), table_name='production_tasks')
    op.drop_index(op.f('ix_production_tasks_scheduled_date'), table_name='production_tasks')
    op.drop_index(op.f('ix_production_tasks_status'), table_name='production_tasks')
    op.drop_index(op.f('ix_production_tasks_item_no'), table_name='production_tasks')
    op.drop_index(op.f('ix_production_tasks_bc_prod_order_no'), table_name='production_tasks')
    op.drop_index(op.f('ix_production_tasks_id'), table_name='production_tasks')
    op.drop_table('production_tasks')

    # Drop enum type
    task_status_enum = sa.Enum('pending', 'in_progress', 'completed', 'blocked', name='taskcompletionstatus')
    task_status_enum.drop(op.get_bind(), checkfirst=True)
