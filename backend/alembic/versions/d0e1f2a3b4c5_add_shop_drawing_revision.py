"""Store the issued shop drawing on a saved quote.

Revision ID: d0e1f2a3b4c5
Revises: c9e0f1a2b3c4
Create Date: 2026-10-30

Drawing number and revision live on the quote. The PDF and DXF are the
drawing as issued at that revision. Editing the door config bumps the
revision and replaces the bytes.
"""
from alembic import op
import sqlalchemy as sa


revision = "d0e1f2a3b4c5"
down_revision = "c9e0f1a2b3c4"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("saved_quote_configs", sa.Column("shop_drawing_number", sa.String(length=40), nullable=True))
    op.add_column("saved_quote_configs", sa.Column("shop_drawing_revision", sa.Integer(), nullable=True))
    op.add_column("saved_quote_configs", sa.Column("shop_drawing_pdf", sa.LargeBinary(), nullable=True))
    op.add_column("saved_quote_configs", sa.Column("shop_drawing_dxf", sa.LargeBinary(), nullable=True))
    op.add_column("saved_quote_configs", sa.Column("shop_drawn_by", sa.String(length=255), nullable=True))
    op.add_column("saved_quote_configs", sa.Column("shop_drawing_generated_at", sa.DateTime(), nullable=True))


def downgrade():
    op.drop_column("saved_quote_configs", "shop_drawing_generated_at")
    op.drop_column("saved_quote_configs", "shop_drawn_by")
    op.drop_column("saved_quote_configs", "shop_drawing_dxf")
    op.drop_column("saved_quote_configs", "shop_drawing_pdf")
    op.drop_column("saved_quote_configs", "shop_drawing_revision")
    op.drop_column("saved_quote_configs", "shop_drawing_number")
