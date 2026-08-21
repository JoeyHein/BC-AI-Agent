"""Add incoming_invoices table (AI invoice intake)

Revision ID: m3h4i5j6k7l8
Revises: k1f2a3b4c5d6
Create Date: 2026-08-21 09:00:00.000000

Tracks the AI invoice-intake pipeline: one row per vendor invoice attachment
pulled from the monitored mailbox, through Claude extraction, vendor/PO/GL
matching, and the resulting BC Draft purchase invoice. Never posts anything —
BC's own Draft status is the "hold off on posting" gate; this table is the
audit trail plus the review queue for anything the matcher wasn't confident
about (usually an unmatched vendor, since the BC invoice header needs a
vendorId to be created at all).
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'm3h4i5j6k7l8'
down_revision = 'k1f2a3b4c5d6'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'incoming_invoices',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('source_email_id', sa.String(300), nullable=False),
        sa.Column('source_email_received_at', sa.DateTime(), nullable=True),
        sa.Column('sender_email', sa.String(255), nullable=True),
        sa.Column('attachment_filename', sa.String(255), nullable=False),
        sa.Column('vendor_id', sa.String(100), nullable=True),
        sa.Column('vendor_number', sa.String(40), nullable=True),
        sa.Column('vendor_name_extracted', sa.String(255), nullable=True),
        sa.Column('vendor_invoice_number', sa.String(100), nullable=True),
        sa.Column('invoice_date', sa.Date(), nullable=True),
        sa.Column('due_date', sa.Date(), nullable=True),
        sa.Column('total_amount', sa.Numeric(14, 2), nullable=True),
        sa.Column('currency_code', sa.String(10), nullable=True),
        sa.Column('extracted_json', sa.JSON(), nullable=True),
        sa.Column('match_type', sa.String(20), nullable=True),
        sa.Column('matched_po_number', sa.String(40), nullable=True),
        sa.Column('gl_account_suggested', sa.String(40), nullable=True),
        sa.Column('gl_confidence', sa.String(20), nullable=True),
        sa.Column('review_flags', sa.JSON(), nullable=True),
        sa.Column('status', sa.String(20), nullable=False, server_default='pending'),
        sa.Column('bc_invoice_id', sa.String(100), nullable=True),
        sa.Column('bc_invoice_number', sa.String(40), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('reviewed_by_user_id', sa.Integer(), nullable=True),
        sa.Column('reviewed_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['reviewed_by_user_id'], ['users.id'], ondelete='SET NULL'),
        sa.UniqueConstraint('source_email_id', 'attachment_filename', name='uq_incoming_invoice_source'),
        sa.CheckConstraint(
            "status IN ('pending', 'created', 'duplicate_skipped', 'error')",
            name='incoming_invoices_status_chk',
        ),
        sa.CheckConstraint(
            "match_type IS NULL OR match_type IN ('po', 'gl', 'unmatched')",
            name='incoming_invoices_match_type_chk',
        ),
    )

    op.create_index('ix_incoming_invoices_source_email_id', 'incoming_invoices', ['source_email_id'])
    op.create_index('ix_incoming_invoices_vendor_number', 'incoming_invoices', ['vendor_number'])
    op.create_index('ix_incoming_invoices_vendor_invoice_number', 'incoming_invoices', ['vendor_invoice_number'])
    op.create_index('ix_incoming_invoices_status', 'incoming_invoices', ['status'])


def downgrade():
    op.drop_index('ix_incoming_invoices_status', table_name='incoming_invoices')
    op.drop_index('ix_incoming_invoices_vendor_invoice_number', table_name='incoming_invoices')
    op.drop_index('ix_incoming_invoices_vendor_number', table_name='incoming_invoices')
    op.drop_index('ix_incoming_invoices_source_email_id', table_name='incoming_invoices')
    op.drop_table('incoming_invoices')
