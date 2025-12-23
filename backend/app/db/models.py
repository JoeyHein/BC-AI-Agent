"""
Database Models for BC AI Agent
SQLAlchemy models for PostgreSQL database
"""

from datetime import datetime
from typing import Optional
from sqlalchemy import (
    Column, Integer, String, Text, DateTime, Boolean, Float,
    ForeignKey, JSON
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship

Base = declarative_base()


class EmailLog(Base):
    """Email logs - stores all incoming emails"""
    __tablename__ = "email_logs"

    id = Column(Integer, primary_key=True, index=True)
    message_id = Column(String(255), unique=True, nullable=False, index=True)
    received_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    from_address = Column(String(255), nullable=False)
    subject = Column(Text)
    body = Column(Text)
    attachments = Column(JSON)  # JSONB in PostgreSQL
    parsed_at = Column(DateTime)
    status = Column(String(50), default="pending")  # pending, parsed, quote_created, error

    # Relationship
    quote_requests = relationship("QuoteRequest", back_populates="email")

    def __repr__(self):
        return f"<EmailLog(id={self.id}, from={self.from_address}, status={self.status})>"


class QuoteRequest(Base):
    """Quote requests - parsed from emails"""
    __tablename__ = "quote_requests"

    id = Column(Integer, primary_key=True, index=True)
    email_id = Column(Integer, ForeignKey("email_logs.id"), nullable=False)
    customer_name = Column(String(255))
    contact_email = Column(String(255))
    contact_phone = Column(String(50))
    door_specs = Column(JSON)  # {type, quantity, size, color, style, etc.}
    parsed_data = Column(JSON)  # raw AI extraction
    confidence_scores = Column(JSON)  # per-field confidence
    bc_quote_id = Column(String(50))  # BC quote number
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    status = Column(String(50), default="pending")  # pending, approved, rejected, created

    # Relationships
    email = relationship("EmailLog", back_populates="quote_requests")
    ai_decisions = relationship("AIDecision", back_populates="quote_request")
    user_feedback = relationship("UserFeedback", back_populates="quote_request")

    def __repr__(self):
        return f"<QuoteRequest(id={self.id}, customer={self.customer_name}, status={self.status})>"


class AIDecision(Base):
    """AI decisions - audit trail for all AI actions"""
    __tablename__ = "ai_decisions"

    id = Column(Integer, primary_key=True, index=True)
    quote_request_id = Column(Integer, ForeignKey("quote_requests.id"))
    decision_type = Column(String(100), nullable=False)  # email_parse, pricing_calc, etc.
    input_data = Column(JSON)
    output_data = Column(JSON)
    confidence_score = Column(Float)
    model_used = Column(String(100))  # claude-3-5-sonnet-20241022
    prompt_tokens = Column(Integer)
    completion_tokens = Column(Integer)
    human_override = Column(Boolean, default=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    # Relationship
    quote_request = relationship("QuoteRequest", back_populates="ai_decisions")

    def __repr__(self):
        return f"<AIDecision(id={self.id}, type={self.decision_type}, confidence={self.confidence_score})>"


class VendorPerformance(Base):
    """Vendor performance - intelligence engine for PO automation"""
    __tablename__ = "vendor_performance"

    id = Column(Integer, primary_key=True, index=True)
    vendor_id = Column(String(50), nullable=False, index=True)  # BC vendor ID
    vendor_name = Column(String(255), nullable=False)
    item_id = Column(String(50), index=True)  # BC item ID
    total_orders = Column(Integer, default=0)
    on_time_deliveries = Column(Integer, default=0)
    average_lead_time_days = Column(Float)
    reliability_score = Column(Float)  # 0-1
    last_order_date = Column(DateTime)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f"<VendorPerformance(vendor={self.vendor_name}, score={self.reliability_score})>"


class AuditTrail(Base):
    """Audit trail - track all user and system actions"""
    __tablename__ = "audit_trail"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String(50))  # Azure AD user ID
    action = Column(String(100), nullable=False)  # quote_created, quote_approved, etc.
    entity_type = Column(String(50))  # quote, sales_order, po
    entity_id = Column(String(50))  # BC entity ID
    details = Column(JSON)
    timestamp = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)

    def __repr__(self):
        return f"<AuditTrail(id={self.id}, action={self.action}, entity={self.entity_type})>"


class UserFeedback(Base):
    """User feedback - for AI training and improvement"""
    __tablename__ = "user_feedback"

    id = Column(Integer, primary_key=True, index=True)
    quote_request_id = Column(Integer, ForeignKey("quote_requests.id"), nullable=False)
    field_name = Column(String(100))  # which field was corrected
    ai_value = Column(Text)
    correct_value = Column(Text)
    feedback_by = Column(String(50))  # user ID
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    # Relationship
    quote_request = relationship("QuoteRequest", back_populates="user_feedback")

    def __repr__(self):
        return f"<UserFeedback(id={self.id}, field={self.field_name}, by={self.feedback_by})>"
