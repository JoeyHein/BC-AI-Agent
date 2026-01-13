"""add_quote_generation_tables

Revision ID: 5d02affe1651
Revises: 8926eb042f88
Create Date: 2025-12-24 13:18:43.178525

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5d02affe1651'
down_revision: Union[str, Sequence[str], None] = '8926eb042f88'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema - Add quote generation tables."""

    # Create quote_items table for individual line items
    op.create_table(
        'quote_items',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('quote_request_id', sa.Integer(), nullable=False),
        sa.Column('item_type', sa.String(length=50), nullable=False),  # 'door', 'hardware', 'glazing', 'installation'
        sa.Column('product_code', sa.String(length=100), nullable=True),  # BC product code
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('quantity', sa.Integer(), nullable=False),
        sa.Column('unit_price', sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column('total_price', sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column('item_metadata', sa.JSON(), nullable=True),  # Additional item details
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.ForeignKeyConstraint(['quote_request_id'], ['quote_requests.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_quote_items_quote_request_id', 'quote_items', ['quote_request_id'])
    op.create_index('ix_quote_items_item_type', 'quote_items', ['item_type'])

    # Create pricing_rules table for business rules
    op.create_table(
        'pricing_rules',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('rule_type', sa.String(length=50), nullable=False),  # 'base_price', 'volume_discount', 'shipping'
        sa.Column('entity', sa.String(length=100), nullable=True),  # 'TX450', 'AL976', 'customer:ABC', etc.
        sa.Column('condition', sa.JSON(), nullable=True),  # { "min_qty": 5, "max_qty": 10 }
        sa.Column('action', sa.JSON(), nullable=False),  # { "discount_percent": 10 } or { "price": 1200 }
        sa.Column('priority', sa.Integer(), nullable=False, server_default='0'),  # Higher priority rules apply first
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_pricing_rules_rule_type', 'pricing_rules', ['rule_type'])
    op.create_index('ix_pricing_rules_entity', 'pricing_rules', ['entity'])
    op.create_index('ix_pricing_rules_is_active', 'pricing_rules', ['is_active'])

    # Create bc_customers table for cached BC customer data
    op.create_table(
        'bc_customers',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('bc_customer_id', sa.String(length=100), nullable=False, unique=True),  # BC customer ID
        sa.Column('company_name', sa.String(length=255), nullable=True),
        sa.Column('contact_name', sa.String(length=255), nullable=True),
        sa.Column('email', sa.String(length=255), nullable=True),
        sa.Column('phone', sa.String(length=50), nullable=True),
        sa.Column('address', sa.JSON(), nullable=True),  # Full address object
        sa.Column('pricing_tier', sa.String(length=50), nullable=True),  # 'standard', 'preferred', 'wholesale'
        sa.Column('customer_metadata', sa.JSON(), nullable=True),  # Additional BC customer data
        sa.Column('last_synced', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_bc_customers_bc_customer_id', 'bc_customers', ['bc_customer_id'], unique=True)
    op.create_index('ix_bc_customers_company_name', 'bc_customers', ['company_name'])
    op.create_index('ix_bc_customers_email', 'bc_customers', ['email'])


def downgrade() -> None:
    """Downgrade schema - Remove quote generation tables."""

    # Drop tables in reverse order (child tables first)
    op.drop_index('ix_bc_customers_email', table_name='bc_customers')
    op.drop_index('ix_bc_customers_company_name', table_name='bc_customers')
    op.drop_index('ix_bc_customers_bc_customer_id', table_name='bc_customers')
    op.drop_table('bc_customers')

    op.drop_index('ix_pricing_rules_is_active', table_name='pricing_rules')
    op.drop_index('ix_pricing_rules_entity', table_name='pricing_rules')
    op.drop_index('ix_pricing_rules_rule_type', table_name='pricing_rules')
    op.drop_table('pricing_rules')

    op.drop_index('ix_quote_items_item_type', table_name='quote_items')
    op.drop_index('ix_quote_items_quote_request_id', table_name='quote_items')
    op.drop_table('quote_items')
