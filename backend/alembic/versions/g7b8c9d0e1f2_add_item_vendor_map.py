"""Add item_vendor_map table + po_agent_log email cols (purchasing tool)

Revision ID: g7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-05-28 00:00:00.000000

Item -> preferred vendor mapping that lets the purchasing tool group
shortfalls by vendor. Rows carry a `source` (manual | bc | history) so a
purchaser's manual assignment is never clobbered by an automated refresh.

Also adds emailed_to / emailed_at to po_agent_log so the purchasing tool can
record that a generated PO's PDF was emailed to the vendor.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'g7b8c9d0e1f2'
down_revision = 'f6a7b8c9d0e1'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'item_vendor_map',
        sa.Column('bc_item_number', sa.String(100), nullable=False),
        sa.Column('vendor_no', sa.String(50), nullable=True),
        sa.Column('vendor_name', sa.String(255), nullable=True),
        sa.Column('source', sa.String(20), nullable=False, server_default='history'),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('bc_item_number'),
    )
    op.add_column('po_agent_log', sa.Column('emailed_to', sa.String(255), nullable=True))
    op.add_column('po_agent_log', sa.Column('emailed_at', sa.DateTime(), nullable=True))


def downgrade():
    op.drop_column('po_agent_log', 'emailed_at')
    op.drop_column('po_agent_log', 'emailed_to')
    op.drop_table('item_vendor_map')
