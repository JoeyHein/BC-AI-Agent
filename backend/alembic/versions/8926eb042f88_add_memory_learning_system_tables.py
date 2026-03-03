"""add_memory_learning_system_tables

Revision ID: 8926eb042f88
Revises: 9d3e076aaf3c
Create Date: 2025-12-24 12:30:48.921256

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY, ENUM


# revision identifiers, used by Alembic.
revision: str = '8926eb042f88'
down_revision: Union[str, Sequence[str], None] = '9d3e076aaf3c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema - Add memory and learning system tables."""

    # Create ENUM types using raw SQL with exception handling (idempotent)
    op.execute("DO $$ BEGIN CREATE TYPE feedbacktype AS ENUM ('APPROVE', 'CORRECT', 'REJECT'); EXCEPTION WHEN duplicate_object THEN null; END $$;")
    op.execute("DO $$ BEGIN CREATE TYPE knowledgetype AS ENUM ('DOOR_MODEL', 'CUSTOMER_PREFERENCE', 'COMMON_PATTERN', 'SPECIFICATION'); EXCEPTION WHEN duplicate_object THEN null; END $$;")

    # Use postgresql.ENUM with create_type=False — sa.Enum ignores this flag in some SA versions
    feedback_type_enum = ENUM('APPROVE', 'CORRECT', 'REJECT', name='feedbacktype', create_type=False)
    knowledge_type_enum = ENUM('DOOR_MODEL', 'CUSTOMER_PREFERENCE', 'COMMON_PATTERN', 'SPECIFICATION', name='knowledgetype', create_type=False)

    # Create parse_feedback table
    op.create_table(
        'parse_feedback',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('quote_request_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.String(length=50), nullable=False),
        sa.Column('feedback_type', feedback_type_enum, nullable=False),
        sa.Column('original_parse', sa.JSON(), nullable=True),
        sa.Column('corrected_parse', sa.JSON(), nullable=True),
        sa.Column('feedback_notes', sa.Text(), nullable=True),
        sa.Column('review_time_seconds', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['quote_request_id'], ['quote_requests.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_parse_feedback_id'), 'parse_feedback', ['id'], unique=False)
    op.create_index(op.f('ix_parse_feedback_quote_request_id'), 'parse_feedback', ['quote_request_id'], unique=False)
    op.create_index(op.f('ix_parse_feedback_feedback_type'), 'parse_feedback', ['feedback_type'], unique=False)
    op.create_index(op.f('ix_parse_feedback_created_at'), 'parse_feedback', ['created_at'], unique=False)

    # Create domain_knowledge table
    op.create_table(
        'domain_knowledge',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('knowledge_type', knowledge_type_enum, nullable=False),
        sa.Column('entity', sa.String(length=255), nullable=False),
        sa.Column('pattern_data', sa.JSON(), nullable=False),
        sa.Column('confidence', sa.Float(), nullable=True, server_default='0.5'),
        sa.Column('usage_count', sa.Integer(), nullable=True, server_default='0'),
        sa.Column('success_rate', sa.Float(), nullable=True, server_default='0.0'),
        sa.Column('source', sa.String(length=100), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_domain_knowledge_id'), 'domain_knowledge', ['id'], unique=False)
    op.create_index(op.f('ix_domain_knowledge_knowledge_type'), 'domain_knowledge', ['knowledge_type'], unique=False)
    op.create_index(op.f('ix_domain_knowledge_entity'), 'domain_knowledge', ['entity'], unique=False)
    op.create_index(op.f('ix_domain_knowledge_updated_at'), 'domain_knowledge', ['updated_at'], unique=False)

    # Create parse_examples table
    # Note: ARRAY type is PostgreSQL-specific, for SQLite we'll use JSON
    op.create_table(
        'parse_examples',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('quote_request_id', sa.Integer(), nullable=False),
        sa.Column('email_subject', sa.Text(), nullable=True),
        sa.Column('email_body', sa.Text(), nullable=True),
        sa.Column('parsed_result', sa.JSON(), nullable=False),
        sa.Column('is_verified', sa.Boolean(), nullable=True, server_default='0'),
        sa.Column('quality_score', sa.Float(), nullable=True, server_default='0.5'),
        sa.Column('completeness_score', sa.Float(), nullable=True),
        sa.Column('tags', sa.JSON(), nullable=True),  # ARRAY for PostgreSQL, JSON for SQLite
        sa.Column('door_models', sa.JSON(), nullable=True),  # ARRAY for PostgreSQL, JSON for SQLite
        sa.Column('customer_name', sa.String(length=255), nullable=True),
        sa.Column('times_retrieved', sa.Integer(), nullable=True, server_default='0'),
        sa.Column('times_helpful', sa.Integer(), nullable=True, server_default='0'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('last_used_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['quote_request_id'], ['quote_requests.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('quote_request_id')
    )
    op.create_index(op.f('ix_parse_examples_id'), 'parse_examples', ['id'], unique=False)
    op.create_index(op.f('ix_parse_examples_is_verified'), 'parse_examples', ['is_verified'], unique=False)
    op.create_index(op.f('ix_parse_examples_quality_score'), 'parse_examples', ['quality_score'], unique=False)
    op.create_index(op.f('ix_parse_examples_customer_name'), 'parse_examples', ['customer_name'], unique=False)
    op.create_index(op.f('ix_parse_examples_created_at'), 'parse_examples', ['created_at'], unique=False)

    # Create learning_metrics table
    op.create_table(
        'learning_metrics',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('metric_date', sa.DateTime(), nullable=False),
        sa.Column('total_parses', sa.Integer(), nullable=True, server_default='0'),
        sa.Column('approved_parses', sa.Integer(), nullable=True, server_default='0'),
        sa.Column('corrected_parses', sa.Integer(), nullable=True, server_default='0'),
        sa.Column('rejected_parses', sa.Integer(), nullable=True, server_default='0'),
        sa.Column('approval_rate', sa.Float(), nullable=True),
        sa.Column('avg_confidence', sa.Float(), nullable=True),
        sa.Column('avg_confidence_approved', sa.Float(), nullable=True),
        sa.Column('avg_confidence_rejected', sa.Float(), nullable=True),
        sa.Column('total_examples', sa.Integer(), nullable=True, server_default='0'),
        sa.Column('verified_examples', sa.Integer(), nullable=True, server_default='0'),
        sa.Column('total_knowledge_items', sa.Integer(), nullable=True, server_default='0'),
        sa.Column('avg_parse_time_ms', sa.Float(), nullable=True),
        sa.Column('avg_retrieval_time_ms', sa.Float(), nullable=True),
        sa.Column('model_used', sa.String(length=100), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_learning_metrics_id'), 'learning_metrics', ['id'], unique=False)
    op.create_index(op.f('ix_learning_metrics_metric_date'), 'learning_metrics', ['metric_date'], unique=False)


def downgrade() -> None:
    """Downgrade schema - Remove memory and learning system tables."""
    op.drop_index(op.f('ix_learning_metrics_metric_date'), table_name='learning_metrics')
    op.drop_index(op.f('ix_learning_metrics_id'), table_name='learning_metrics')
    op.drop_table('learning_metrics')

    op.drop_index(op.f('ix_parse_examples_created_at'), table_name='parse_examples')
    op.drop_index(op.f('ix_parse_examples_customer_name'), table_name='parse_examples')
    op.drop_index(op.f('ix_parse_examples_quality_score'), table_name='parse_examples')
    op.drop_index(op.f('ix_parse_examples_is_verified'), table_name='parse_examples')
    op.drop_index(op.f('ix_parse_examples_id'), table_name='parse_examples')
    op.drop_table('parse_examples')

    op.drop_index(op.f('ix_domain_knowledge_updated_at'), table_name='domain_knowledge')
    op.drop_index(op.f('ix_domain_knowledge_entity'), table_name='domain_knowledge')
    op.drop_index(op.f('ix_domain_knowledge_knowledge_type'), table_name='domain_knowledge')
    op.drop_index(op.f('ix_domain_knowledge_id'), table_name='domain_knowledge')
    op.drop_table('domain_knowledge')

    op.drop_index(op.f('ix_parse_feedback_created_at'), table_name='parse_feedback')
    op.drop_index(op.f('ix_parse_feedback_feedback_type'), table_name='parse_feedback')
    op.drop_index(op.f('ix_parse_feedback_quote_request_id'), table_name='parse_feedback')
    op.drop_index(op.f('ix_parse_feedback_id'), table_name='parse_feedback')
    op.drop_table('parse_feedback')

    # Drop ENUM types
    sa.Enum(name='feedbacktype').drop(op.get_bind(), checkfirst=True)
    sa.Enum(name='knowledgetype').drop(op.get_bind(), checkfirst=True)
