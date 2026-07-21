"""Add cut_rule (ratified cutting rules from verdicts)

Revision ID: k1f2a3b4c5d6
Revises: j0e1f2a3b4c5
Create Date: 2026-07-20 00:00:00.000000

Human-approved suppression rules derived from accumulated cut verdicts. A rule
only takes effect once approved — verdicts are the signal, rules are the policy.
"""
from alembic import op
import sqlalchemy as sa


revision = 'k1f2a3b4c5d6'
down_revision = 'j0e1f2a3b4c5'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'cut_rule',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('scope', sa.String(10), nullable=False, server_default='pair'),
        sa.Column('action', sa.String(20), nullable=False, server_default='suppress'),
        sa.Column('donor_sku', sa.String(50), nullable=True),
        sa.Column('target_sku', sa.String(50), nullable=True),
        sa.Column('cut_family', sa.String(60), nullable=True),
        sa.Column('reason', sa.Text(), nullable=True),
        sa.Column('active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('created_by', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['created_by'], ['users.id']),
    )
    op.create_index('ix_cut_rule_donor_sku', 'cut_rule', ['donor_sku'])
    op.create_index('ix_cut_rule_target_sku', 'cut_rule', ['target_sku'])
    op.create_index('ix_cut_rule_cut_family', 'cut_rule', ['cut_family'])
    op.create_index('ix_cut_rule_active', 'cut_rule', ['active'])


def downgrade():
    op.drop_index('ix_cut_rule_active', table_name='cut_rule')
    op.drop_index('ix_cut_rule_cut_family', table_name='cut_rule')
    op.drop_index('ix_cut_rule_target_sku', table_name='cut_rule')
    op.drop_index('ix_cut_rule_donor_sku', table_name='cut_rule')
    op.drop_table('cut_rule')
