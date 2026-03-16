"""
Database Models for BC AI Agent
SQLAlchemy models for PostgreSQL database
"""

from datetime import datetime
from typing import Optional
from sqlalchemy import (
    Column, Integer, String, Text, DateTime, Date, Boolean, Float,
    ForeignKey, JSON, Enum as SQLEnum, ARRAY, Numeric
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
import enum

Base = declarative_base()


# Enums for memory system
class FeedbackType(enum.Enum):
    """Types of user feedback"""
    APPROVE = "approve"
    CORRECT = "correct"
    REJECT = "reject"


class KnowledgeType(enum.Enum):
    """Types of domain knowledge"""
    DOOR_MODEL = "door_model"
    CUSTOMER_PREFERENCE = "customer_preference"
    COMMON_PATTERN = "common_pattern"
    SPECIFICATION = "specification"


class UserRole(enum.Enum):
    """User roles for permission system"""
    ADMIN = "admin"          # Full access: manage users, connect emails, review quotes
    REVIEWER = "reviewer"    # Can review and approve/reject quotes
    VIEWER = "viewer"        # Read-only access


class UserType(enum.Enum):
    """User types - internal staff vs external customers"""
    INTERNAL = "internal"    # Internal staff users (admin app)
    CUSTOMER = "customer"    # External customer users (customer portal)


class AccountType(enum.Enum):
    """Account types for customer users"""
    DEALER = "dealer"              # Dealer / installer
    HOME_BUILDER = "home_builder"  # Home builder


class AccountStatus(enum.Enum):
    """Account approval status"""
    PENDING = "pending"
    ACTIVE = "active"
    DECLINED = "declined"


class User(Base):
    """Users - for authentication and permissions"""
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    name = Column(String(255))
    role = Column(SQLEnum(UserRole), default=UserRole.VIEWER, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    last_login_at = Column(DateTime)

    # Customer portal fields
    # Using String instead of SQLEnum for SQLite compatibility
    # Valid values: 'INTERNAL', 'CUSTOMER' (matches UserType enum)
    user_type = Column(String(20), default='INTERNAL', nullable=True)
    bc_customer_id = Column(String(100), ForeignKey("bc_customers.bc_customer_id"), nullable=True)
    email_verified = Column(Boolean, default=False)  # For customer self-registration
    email_verification_token = Column(String(255), nullable=True)
    email_verification_expires = Column(DateTime, nullable=True)
    password_reset_token = Column(String(255), nullable=True)
    password_reset_expires = Column(DateTime, nullable=True)

    # Home builder / dealer account fields
    account_type = Column(String(20), default='dealer', nullable=True)  # 'dealer' or 'home_builder'
    account_status = Column(String(20), default='active', nullable=True)  # 'pending', 'active', 'declined'
    approved_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    approved_at = Column(DateTime, nullable=True)
    company_name = Column(String(255), nullable=True)
    phone = Column(String(50), nullable=True)

    # Relationships
    email_connections = relationship("EmailConnection", back_populates="user", cascade="all, delete-orphan")
    bc_customer = relationship("BCCustomer", foreign_keys=[bc_customer_id], primaryjoin="User.bc_customer_id == BCCustomer.bc_customer_id")
    saved_quote_configs = relationship("SavedQuoteConfig", back_populates="user", cascade="all, delete-orphan")
    projects = relationship("Project", back_populates="customer", cascade="all, delete-orphan")
    install_referrals = relationship("InstallReferral", back_populates="customer", cascade="all, delete-orphan")
    approver = relationship("User", remote_side=[id], foreign_keys=[approved_by])

    def __repr__(self):
        return f"<User(id={self.id}, email={self.email}, role={self.role.value}, type={self.user_type})>"


class EmailConnection(Base):
    """Email connections - stores OAuth tokens for connected email accounts"""
    __tablename__ = "email_connections"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    email_address = Column(String(255), unique=True, nullable=False, index=True)

    # OAuth tokens
    access_token = Column(Text, nullable=False)
    refresh_token = Column(Text)
    token_expires_at = Column(DateTime)

    # Status
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    last_checked_at = Column(DateTime)
    last_sync_status = Column(String(50))  # success, error, auth_failed

    # Relationships
    user = relationship("User", back_populates="email_connections")

    def __repr__(self):
        return f"<EmailConnection(id={self.id}, email={self.email_address}, active={self.is_active})>"


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

    # AI Categorization Learning System
    ai_category = Column(String(50))  # quote_request, quote_modification, invoice, inquiry, other, etc.
    ai_category_confidence = Column(Float)  # 0.0-1.0
    ai_category_reasoning = Column(Text)  # Why AI chose this category
    user_verified_category = Column(String(50))  # User's correction (if different from AI)
    categorization_correct = Column(Boolean)  # Was AI categorization correct?

    # Quote Modification Detection
    is_modification = Column(Boolean, default=False)  # Detected as modifying existing quote
    referenced_quote_number = Column(String(100))  # Quote number mentioned in email
    modification_type = Column(String(50))  # dimension_change, color_change, etc.

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

    # Quote Modification Tracking
    is_modification = Column(Boolean, default=False)  # True if this modifies an existing quote
    parent_quote_id = Column(Integer, ForeignKey("quote_requests.id"), nullable=True)  # Original quote being modified
    revision_number = Column(Integer, default=1)  # 1 = original, 2+ = revisions
    modification_type = Column(String(50))  # dimension_change, color_change, quantity_change, spec_change, cancellation
    modification_notes = Column(Text)  # AI-detected changes summary

    # Relationships
    email = relationship("EmailLog", back_populates="quote_requests")
    parent_quote = relationship("QuoteRequest", remote_side=[id], backref="revisions")
    ai_decisions = relationship("AIDecision", back_populates="quote_request")
    user_feedback = relationship("UserFeedback", back_populates="quote_request")
    quote_items = relationship("QuoteItem", back_populates="quote_request", cascade="all, delete-orphan")

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
    """User feedback - for AI training and improvement (legacy field-level)"""
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


# ============================================================================
# MEMORY & LEARNING SYSTEM MODELS
# ============================================================================

class ParseFeedback(Base):
    """Comprehensive feedback on AI parses - enables learning from corrections"""
    __tablename__ = "parse_feedback"

    id = Column(Integer, primary_key=True, index=True)
    quote_request_id = Column(Integer, ForeignKey("quote_requests.id"), nullable=False, index=True)
    user_id = Column(String(50), nullable=False)  # Azure AD user ID
    feedback_type = Column(SQLEnum(FeedbackType), nullable=False, index=True)

    # Store both versions for comparison
    original_parse = Column(JSON)  # What AI originally extracted
    corrected_parse = Column(JSON)  # User's corrections (null if approved/rejected)

    feedback_notes = Column(Text)  # User's explanation
    review_time_seconds = Column(Integer)  # How long user spent reviewing
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)

    # Relationship
    quote_request = relationship("QuoteRequest", foreign_keys=[quote_request_id])

    def __repr__(self):
        return f"<ParseFeedback(id={self.id}, type={self.feedback_type.value}, quote={self.quote_request_id})>"


class DomainKnowledge(Base):
    """Learned patterns and domain-specific knowledge"""
    __tablename__ = "domain_knowledge"

    id = Column(Integer, primary_key=True, index=True)
    knowledge_type = Column(SQLEnum(KnowledgeType), nullable=False, index=True)
    entity = Column(String(255), nullable=False, index=True)  # e.g., "TX450", "ABC Company"

    # Flexible JSON storage for different knowledge types
    pattern_data = Column(JSON, nullable=False)
    # Examples:
    # door_model: {"common_widths": [8,9,10], "default_track": "2\"", ...}
    # customer_preference: {"typical_quantity": 5, "preferred_colors": ["Brown"], ...}
    # common_pattern: {"when": "subject contains 'urgent'", "then": "set priority high"}

    confidence = Column(Float, default=0.5)  # How confident we are in this knowledge (0-1)
    usage_count = Column(Integer, default=0)  # How many times successfully used
    success_rate = Column(Float, default=0.0)  # % of times this knowledge helped

    source = Column(String(100))  # "user_feedback", "auto_extracted", "manual_entry"
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow, index=True)

    def __repr__(self):
        return f"<DomainKnowledge(type={self.knowledge_type.value}, entity={self.entity}, conf={self.confidence:.2f})>"


class ParseExample(Base):
    """High-quality parse examples for RAG (Retrieval-Augmented Generation)"""
    __tablename__ = "parse_examples"

    id = Column(Integer, primary_key=True, index=True)
    quote_request_id = Column(Integer, ForeignKey("quote_requests.id"), nullable=False, unique=True)

    # The example data
    email_subject = Column(Text)
    email_body = Column(Text)
    parsed_result = Column(JSON, nullable=False)

    # Quality indicators
    is_verified = Column(Boolean, default=False, index=True)  # User approved this parse
    quality_score = Column(Float, default=0.5, index=True)  # Overall quality (0-1)
    completeness_score = Column(Float)  # % of fields filled

    # For retrieval/matching
    tags = Column(ARRAY(String), default=list)  # ["TX450", "multi-door", "complete-specs", "urgent"]
    door_models = Column(ARRAY(String), default=list)  # Extracted door models for quick filtering
    customer_name = Column(String(255), index=True)

    # Usage tracking
    times_retrieved = Column(Integer, default=0)  # How often used as an example
    times_helpful = Column(Integer, default=0)  # How often it led to good parse

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    last_used_at = Column(DateTime)

    # Relationship
    quote_request = relationship("QuoteRequest", foreign_keys=[quote_request_id])

    def __repr__(self):
        return f"<ParseExample(id={self.id}, quality={self.quality_score:.2f}, verified={self.is_verified})>"


class LearningMetrics(Base):
    """Track learning progress and system improvement over time"""
    __tablename__ = "learning_metrics"

    id = Column(Integer, primary_key=True, index=True)
    metric_date = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)

    # Parse accuracy metrics
    total_parses = Column(Integer, default=0)
    approved_parses = Column(Integer, default=0)
    corrected_parses = Column(Integer, default=0)
    rejected_parses = Column(Integer, default=0)
    approval_rate = Column(Float)  # approved / total

    # Confidence metrics
    avg_confidence = Column(Float)
    avg_confidence_approved = Column(Float)  # Confidence of approved parses
    avg_confidence_rejected = Column(Float)  # Confidence of rejected parses

    # Knowledge base growth
    total_examples = Column(Integer, default=0)
    verified_examples = Column(Integer, default=0)
    total_knowledge_items = Column(Integer, default=0)

    # Performance
    avg_parse_time_ms = Column(Float)
    avg_retrieval_time_ms = Column(Float)

    # Model info
    model_used = Column(String(100))

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    def __repr__(self):
        return f"<LearningMetrics(date={self.metric_date.date()}, approval_rate={self.approval_rate:.2%})>"


# ============================================================================
# QUOTE GENERATION MODELS (Week 3)
# ============================================================================

class QuoteItem(Base):
    """Individual line items for quote generation"""
    __tablename__ = "quote_items"

    id = Column(Integer, primary_key=True, index=True)
    quote_request_id = Column(Integer, ForeignKey("quote_requests.id", ondelete="CASCADE"), nullable=False, index=True)

    # Item details
    item_type = Column(String(50), nullable=False, index=True)  # 'door', 'hardware', 'glazing', 'installation'
    product_code = Column(String(100))  # BC product code
    description = Column(Text)

    # Pricing
    quantity = Column(Integer, nullable=False)
    unit_price = Column(Numeric(10, 2))
    total_price = Column(Numeric(10, 2))

    # Additional data
    item_metadata = Column(JSON)  # Additional item details (specs, options, etc.)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    # Relationships
    quote_request = relationship("QuoteRequest", back_populates="quote_items")

    def __repr__(self):
        return f"<QuoteItem(id={self.id}, type={self.item_type}, qty={self.quantity}, price={self.total_price})>"


class PricingRule(Base):
    """Business rules for quote pricing calculations"""
    __tablename__ = "pricing_rules"

    id = Column(Integer, primary_key=True, index=True)

    # Rule identification
    rule_type = Column(String(50), nullable=False, index=True)  # 'base_price', 'volume_discount', 'shipping', etc.
    entity = Column(String(100), index=True)  # 'TX450', 'AL976', 'customer:ABC', 'glazing:thermopane', etc.

    # Rule logic
    condition = Column(JSON)  # { "min_qty": 5, "max_qty": 10, "customer_tier": "preferred" }
    action = Column(JSON, nullable=False)  # { "discount_percent": 10 } or { "price": 1200 }

    # Rule metadata
    priority = Column(Integer, nullable=False, default=0, index=True)  # Higher priority rules apply first
    is_active = Column(Boolean, nullable=False, default=True, index=True)
    description = Column(Text)

    # Timestamps
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, onupdate=datetime.utcnow)

    def __repr__(self):
        return f"<PricingRule(id={self.id}, type={self.rule_type}, entity={self.entity}, active={self.is_active})>"

    def matches(self, context: dict) -> bool:
        """Check if this rule's conditions match the given context"""
        if not self.is_active:
            return False

        if not self.condition:
            return True  # No conditions means always match

        # Check each condition
        for key, value in self.condition.items():
            context_value = context.get(key)

            # Range conditions (min_qty, max_qty, etc.)
            if key.startswith("min_"):
                if context_value is None or context_value < value:
                    return False
            elif key.startswith("max_"):
                if context_value is None or context_value > value:
                    return False
            # Exact match conditions
            elif context_value != value:
                return False

        return True

    def apply(self, base_value: float) -> float:
        """Apply this rule's action to a base value"""
        if "discount_percent" in self.action:
            return base_value * (1 - self.action["discount_percent"] / 100)
        elif "discount_amount" in self.action:
            return base_value - self.action["discount_amount"]
        elif "price" in self.action:
            return self.action["price"]
        elif "multiplier" in self.action:
            return base_value * self.action["multiplier"]

        return base_value


class BCCustomer(Base):
    """Cached Business Central customer data"""
    __tablename__ = "bc_customers"

    id = Column(Integer, primary_key=True, index=True)

    # BC identification
    bc_customer_id = Column(String(100), unique=True, nullable=False, index=True)

    # Customer details
    company_name = Column(String(255), index=True)
    contact_name = Column(String(255))
    email = Column(String(255), index=True)
    phone = Column(String(50))
    address = Column(JSON)  # { "street": "...", "city": "...", "province": "...", "postal": "..." }

    # Pricing and classification
    pricing_tier = Column(String(50))  # portal tier: gold, silver, bronze, retail
    price_multiplier = Column(Float, nullable=True)  # BC price multiplier % (e.g. +10 = 10% markup, -5 = 5% discount)
    bc_price_group = Column(String(100), nullable=True)  # BC customerPriceGroup code (e.g. RETAIL, CONTRACTOR)
    customer_metadata = Column(JSON)  # Additional BC customer data

    # Sync tracking
    last_synced = Column(DateTime)

    # Timestamps
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, onupdate=datetime.utcnow)

    def __repr__(self):
        return f"<BCCustomer(id={self.bc_customer_id}, name={self.company_name})>"


# ============================================================================
# ORDER LIFECYCLE MODELS (Order-to-Cash Automation)
# ============================================================================

class OrderStatus(enum.Enum):
    """Sales order status states"""
    PENDING = "pending"           # Awaiting conversion from quote
    CONFIRMED = "confirmed"       # Order confirmed, awaiting production
    IN_PRODUCTION = "in_production"  # Production orders created
    READY_TO_SHIP = "ready_to_ship"  # Production complete
    SHIPPED = "shipped"           # Shipped to customer
    INVOICED = "invoiced"         # Invoice generated
    COMPLETED = "completed"       # Fully paid and closed
    CANCELLED = "cancelled"


class ProductionStatus(enum.Enum):
    """Production order status states"""
    PLANNED = "planned"           # Production order planned
    RELEASED = "released"         # Released for production
    IN_PROGRESS = "in_progress"   # Currently being manufactured
    FINISHED = "finished"         # Production complete
    CANCELLED = "cancelled"


class InvoiceStatus(enum.Enum):
    """Invoice status states"""
    DRAFT = "draft"               # Draft invoice not yet posted
    POSTED = "posted"             # Posted to general ledger
    PAID = "paid"                 # Payment received
    PARTIALLY_PAID = "partially_paid"
    OVERDUE = "overdue"
    CANCELLED = "cancelled"


class SalesOrder(Base):
    """Sales orders - converted from quotes, tracked through fulfillment"""
    __tablename__ = "sales_orders"

    id = Column(Integer, primary_key=True, index=True)
    quote_request_id = Column(Integer, ForeignKey("quote_requests.id"), index=True)

    # BC Integration
    bc_id = Column(String(100), index=True)  # BC order GUID (id field from API)
    bc_order_id = Column(String(100), unique=True, index=True)  # Legacy - BC sales order GUID
    bc_order_number = Column(String(50), index=True)  # e.g., "SO-001234"
    bc_quote_number = Column(String(50))  # Source quote reference

    # Customer
    customer_id = Column(String(100))  # BC customer ID (legacy)
    bc_customer_id = Column(String(100), index=True)  # BC customer GUID
    customer_number = Column(String(50))  # BC customer number (e.g., "C00123")
    customer_name = Column(String(255))
    customer_email = Column(String(255))

    # Order details
    status = Column(
        SQLEnum(OrderStatus, values_callable=lambda x: [e.value for e in x]),
        default=OrderStatus.PENDING,
        index=True,
    )
    total_amount = Column(Numeric(12, 2))
    currency = Column(String(10), default="CAD")

    # Dates
    order_date = Column(DateTime)  # BC order date
    requested_delivery_date = Column(DateTime)  # Requested delivery
    scheduled_date = Column(DateTime, index=True)  # Production/picking scheduled date

    # Addresses
    shipping_address = Column(Text)  # Full shipping address
    billing_address = Column(Text)  # Full billing address

    # External reference for tracking
    external_document_number = Column(String(100))  # AI-QR-xxx for AI-generated orders

    # Timestamps
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    confirmed_at = Column(DateTime)
    production_started_at = Column(DateTime)
    production_completed_at = Column(DateTime)
    shipped_at = Column(DateTime)
    invoiced_at = Column(DateTime)
    completed_at = Column(DateTime)

    # Sync tracking
    last_synced_at = Column(DateTime)
    bc_last_modified = Column(DateTime)

    # Relationships
    quote_request = relationship("QuoteRequest", foreign_keys=[quote_request_id])
    line_items = relationship("SalesOrderLineItem", back_populates="sales_order", cascade="all, delete-orphan")
    production_orders = relationship("ProductionOrder", back_populates="sales_order", cascade="all, delete-orphan")
    shipments = relationship("Shipment", back_populates="sales_order", cascade="all, delete-orphan")
    invoices = relationship("Invoice", back_populates="sales_order", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<SalesOrder(id={self.id}, bc_number={self.bc_order_number}, status={self.status.value})>"


class SalesOrderLineItem(Base):
    """Line items within a sales order - synced from BC"""
    __tablename__ = "sales_order_line_items"

    id = Column(Integer, primary_key=True, index=True)
    sales_order_id = Column(Integer, ForeignKey("sales_orders.id"), nullable=False, index=True)

    # BC Integration
    bc_line_no = Column(Integer, nullable=False)  # BC line number (10000, 20000, etc.)
    bc_document_no = Column(String(50), index=True)  # BC sales order number

    # Line item details
    item_no = Column(String(100), index=True)  # BC item number
    description = Column(Text)
    quantity = Column(Float, default=1)
    unit_of_measure = Column(String(20))
    unit_price = Column(Numeric(12, 2))
    line_amount = Column(Numeric(12, 2))

    # Type indicator
    line_type = Column(String(20))  # 'Item', 'Resource', 'G/L Account', etc.

    # Pick/Pack tracking (for orders without production orders)
    quantity_picked = Column(Float, default=0)  # How many have been picked
    picked_at = Column(DateTime)  # When the pick was confirmed
    picked_by = Column(String(100))  # User who confirmed the pick

    # Timestamps
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    last_synced_at = Column(DateTime)

    # Relationships
    sales_order = relationship("SalesOrder", back_populates="line_items")
    production_orders = relationship("ProductionOrder", back_populates="line_item")

    def __repr__(self):
        return f"<SalesOrderLineItem(id={self.id}, item_no={self.item_no}, qty={self.quantity})>"

    def to_dict(self):
        return {
            "id": self.id,
            "salesOrderId": self.sales_order_id,
            "bcLineNo": self.bc_line_no,
            "bcDocumentNo": self.bc_document_no,
            "itemNo": self.item_no,
            "description": self.description,
            "quantity": self.quantity,
            "unitOfMeasure": self.unit_of_measure,
            "unitPrice": float(self.unit_price) if self.unit_price else None,
            "lineAmount": float(self.line_amount) if self.line_amount else None,
            "lineType": self.line_type,
            "quantityPicked": self.quantity_picked or 0,
            "pickedAt": self.picked_at.isoformat() if self.picked_at else None,
            "pickedBy": self.picked_by,
            "isPicked": self.quantity_picked is not None and self.quantity_picked >= (self.quantity or 0),
        }


class ProductionOrder(Base):
    """Production orders - created from sales order line items"""
    __tablename__ = "production_orders"

    id = Column(Integer, primary_key=True, index=True)
    sales_order_id = Column(Integer, ForeignKey("sales_orders.id"), nullable=True, index=True)  # Nullable for orphan BC orders
    line_item_id = Column(Integer, ForeignKey("sales_order_line_items.id"), nullable=True, index=True)  # Link to source line item

    # BC Integration
    bc_prod_order_id = Column(String(100), unique=True, index=True)
    bc_prod_order_number = Column(String(50), index=True)  # e.g., "PO-001234"

    # Production details
    status = Column(
        SQLEnum(ProductionStatus, values_callable=lambda x: [e.value for e in x]),
        default=ProductionStatus.PLANNED,
        index=True,
    )
    item_type = Column(String(50), index=True)  # 'door', 'spring', 'hardware', etc.
    item_code = Column(String(100))  # BC item/product code
    item_description = Column(Text)
    quantity = Column(Integer, nullable=False)
    quantity_completed = Column(Integer, default=0)

    # Specifications (JSON for flexible storage of item-specific details)
    # For springs: {wire_diameter, coil_diameter, length, ippt, mip_per_spring, turns, cycle_life, drum_model, door_weight}
    # For doors: {model, size, color, panel_config}
    specifications = Column(JSON)

    # Inventory allocation
    inventory_allocated = Column(Boolean, default=False)
    inventory_allocation_id = Column(String(100))  # BC inventory allocation reference
    stock_available = Column(Integer)  # Available stock at time of creation
    stock_reserved = Column(Integer, default=0)  # Reserved for this production order

    # Scheduling
    due_date = Column(DateTime)
    start_date = Column(DateTime)
    end_date = Column(DateTime)

    # Timestamps
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    started_at = Column(DateTime)
    finished_at = Column(DateTime)

    # Sync tracking
    last_synced_at = Column(DateTime)

    # Relationships
    sales_order = relationship("SalesOrder", back_populates="production_orders")
    line_item = relationship("SalesOrderLineItem", back_populates="production_orders")

    def __repr__(self):
        return f"<ProductionOrder(id={self.id}, bc_number={self.bc_prod_order_number}, status={self.status.value})>"


class Shipment(Base):
    """Shipments - tracks shipping of sales orders"""
    __tablename__ = "shipments"

    id = Column(Integer, primary_key=True, index=True)
    sales_order_id = Column(Integer, ForeignKey("sales_orders.id"), nullable=False, index=True)

    # BC Integration
    bc_shipment_id = Column(String(100), unique=True, index=True)
    shipment_number = Column(String(50), index=True)  # e.g., "SS-001234"

    # Shipment details
    shipped_date = Column(DateTime)
    tracking_number = Column(String(100))
    carrier = Column(String(100))  # e.g., "FedEx", "UPS", "Local Delivery"
    shipping_method = Column(String(100))

    # Destination
    ship_to_name = Column(String(255))
    ship_to_address = Column(JSON)  # Full address details

    # Quantities
    total_packages = Column(Integer)
    total_weight = Column(Numeric(10, 2))
    weight_unit = Column(String(10), default="kg")

    # Timestamps
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    delivered_at = Column(DateTime)

    # Sync tracking
    last_synced_at = Column(DateTime)

    # Relationships
    sales_order = relationship("SalesOrder", back_populates="shipments")

    def __repr__(self):
        return f"<Shipment(id={self.id}, number={self.shipment_number}, tracking={self.tracking_number})>"


class Invoice(Base):
    """Invoices - generated from shipped orders"""
    __tablename__ = "invoices"

    id = Column(Integer, primary_key=True, index=True)
    sales_order_id = Column(Integer, ForeignKey("sales_orders.id"), nullable=False, index=True)

    # BC Integration
    bc_invoice_id = Column(String(100), unique=True, index=True)
    invoice_number = Column(String(50), index=True)  # e.g., "SI-001234"

    # Invoice details
    status = Column(
        SQLEnum(InvoiceStatus, values_callable=lambda x: [e.value for e in x]),
        default=InvoiceStatus.DRAFT,
        index=True,
    )
    total_amount = Column(Numeric(12, 2))
    tax_amount = Column(Numeric(10, 2))
    currency = Column(String(10), default="CAD")

    # Payment terms
    due_date = Column(DateTime)
    payment_terms = Column(String(50))  # e.g., "Net 30"

    # Payment tracking
    amount_paid = Column(Numeric(12, 2), default=0)
    amount_remaining = Column(Numeric(12, 2))

    # Timestamps
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    posted_at = Column(DateTime)
    paid_at = Column(DateTime)

    # Sync tracking
    last_synced_at = Column(DateTime)

    # Relationships
    sales_order = relationship("SalesOrder", back_populates="invoices")

    def __repr__(self):
        return f"<Invoice(id={self.id}, number={self.invoice_number}, status={self.status.value}, amount={self.total_amount})>"


# ============================================================================
# CUSTOMER PORTAL MODELS
# ============================================================================

class SavedQuoteConfig(Base):
    """Saved door configurations - customer drafts for quote building"""
    __tablename__ = "saved_quote_configs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)

    # Configuration details
    name = Column(String(255))  # Customer-assigned name for this config
    description = Column(Text)  # Optional notes/description
    config_data = Column(JSON, nullable=False)  # Full door configuration data

    # Status tracking
    is_submitted = Column(Boolean, default=False, index=True)
    bc_quote_number = Column(String(50), nullable=True)  # BC quote number if submitted
    bc_quote_id = Column(String(100), nullable=True)  # BC quote GUID if submitted

    # Timestamps
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, onupdate=datetime.utcnow)
    submitted_at = Column(DateTime, nullable=True)

    # Relationships
    user = relationship("User", back_populates="saved_quote_configs")

    def __repr__(self):
        return f"<SavedQuoteConfig(id={self.id}, name={self.name}, submitted={self.is_submitted})>"


# ============================================================================
# HOME BUILDER / PROJECT MODELS
# ============================================================================

class Project(Base):
    """Projects - home builder multi-lot project management"""
    __tablename__ = "projects"

    id = Column(String(36), primary_key=True)  # UUID
    customer_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    status = Column(String(20), nullable=False, default='active')  # active, complete, cancelled
    billing_mode = Column(String(20), nullable=False, default='full')  # full, staged
    bc_quote_id = Column(String(100), nullable=True)
    bc_quote_number = Column(String(100), nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, onupdate=datetime.utcnow)

    # Relationships
    customer = relationship("User", back_populates="projects")
    lots = relationship("ProjectLot", back_populates="project", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Project(id={self.id}, name={self.name}, status={self.status})>"


class ProjectLot(Base):
    """Project lots - individual lots within a home builder project"""
    __tablename__ = "project_lots"

    id = Column(String(36), primary_key=True)  # UUID
    project_id = Column(String(36), ForeignKey("projects.id"), nullable=False, index=True)
    lot_number = Column(String(100), nullable=False)
    address = Column(Text, nullable=True)
    door_config_id = Column(Integer, nullable=True)  # Optional link to SavedQuoteConfig
    door_spec = Column(JSON, nullable=True)
    stage = Column(Integer, nullable=True, index=True)  # null = full release
    lot_status = Column(String(20), nullable=False, default='quoted')  # quoted, released, ordered, shipped, complete
    bc_order_id = Column(String(100), nullable=True)
    bc_order_number = Column(String(100), nullable=True)
    bc_invoice_id = Column(String(100), nullable=True)
    bc_invoice_number = Column(String(100), nullable=True)
    install_referral_id = Column(String(36), ForeignKey("install_referrals.id"), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, onupdate=datetime.utcnow)

    # Relationships
    project = relationship("Project", back_populates="lots")
    install_referral = relationship("InstallReferral", back_populates="project_lot", foreign_keys=[install_referral_id])

    def __repr__(self):
        return f"<ProjectLot(id={self.id}, lot={self.lot_number}, status={self.lot_status})>"


class InstallReferral(Base):
    """Install referrals - home builder install requests routed to subcontractors"""
    __tablename__ = "install_referrals"

    id = Column(String(36), primary_key=True)  # UUID
    customer_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    order_reference = Column(String(100), nullable=True)
    project_lot_id = Column(String(36), ForeignKey("project_lots.id"), nullable=True, index=True)
    site_address = Column(Text, nullable=False)
    site_contact_name = Column(String(255), nullable=False)
    site_contact_phone = Column(String(50), nullable=False)
    requested_date = Column(Date, nullable=True)
    access_notes = Column(Text, nullable=True)
    status = Column(String(20), nullable=False, default='new')  # new, scheduled, complete
    assigned_sub = Column(String(255), nullable=True)
    scheduled_date = Column(Date, nullable=True)
    internal_notes = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, onupdate=datetime.utcnow)

    # Relationships
    customer = relationship("User", back_populates="install_referrals")
    project_lot = relationship("ProjectLot", back_populates="install_referral", foreign_keys=[project_lot_id])

    def __repr__(self):
        return f"<InstallReferral(id={self.id}, status={self.status})>"


# ============================================================================
# PRODUCTION TASK COMPLETION MODELS
# ============================================================================

class TaskCompletionStatus(enum.Enum):
    """Task completion status states"""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    BLOCKED = "blocked"


class ProductionTask(Base):
    """Production tasks - line items within production orders for shop floor tracking"""
    __tablename__ = "production_tasks"

    id = Column(Integer, primary_key=True, index=True)
    production_order_id = Column(Integer, ForeignKey("production_orders.id"), nullable=True, index=True)

    # BC Reference
    bc_prod_order_no = Column(String(50), index=True)
    bc_line_no = Column(Integer)

    # Item details
    item_no = Column(String(100), index=True)
    description = Column(Text)
    quantity_required = Column(Float, default=1)
    quantity_completed = Column(Float, default=0)
    unit_of_measure = Column(String(20))

    # Material availability (display only - no BC reservation)
    material_available = Column(Float, default=0)
    material_needed = Column(Float, default=0)

    # Status tracking
    status = Column(
        SQLEnum(TaskCompletionStatus, values_callable=lambda x: [e.value for e in x]),
        default=TaskCompletionStatus.PENDING,
        index=True,
    )
    scheduled_date = Column(DateTime, index=True)
    completed_at = Column(DateTime)
    completed_by = Column(String(50))  # User ID who completed the task

    # BC sync tracking
    bc_synced = Column(Boolean, default=False)
    bc_sync_error = Column(Text)

    # Timestamps
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, onupdate=datetime.utcnow)

    # Relationships
    production_order = relationship("ProductionOrder", foreign_keys=[production_order_id])

    def __repr__(self):
        return f"<ProductionTask(id={self.id}, item={self.item_no}, status={self.status.value})>"

    def to_dict(self):
        return {
            "id": self.id,
            "productionOrderId": self.production_order_id,
            "bcProdOrderNo": self.bc_prod_order_no,
            "bcLineNo": self.bc_line_no,
            "itemNo": self.item_no,
            "description": self.description,
            "quantityRequired": self.quantity_required,
            "quantityCompleted": self.quantity_completed,
            "unitOfMeasure": self.unit_of_measure,
            "materialAvailable": self.material_available,
            "materialNeeded": self.material_needed,
            "status": self.status.value,
            "scheduledDate": self.scheduled_date.isoformat() if self.scheduled_date else None,
            "completedAt": self.completed_at.isoformat() if self.completed_at else None,
            "completedBy": self.completed_by,
            "bcSynced": self.bc_synced,
        }


# ============================================================================
# AI CHAT MODELS
# ============================================================================

class Conversation(Base):
    """AI Chat conversations - groups messages into sessions"""
    __tablename__ = "conversations"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)

    # Conversation metadata
    title = Column(String(255))  # Auto-generated from first message
    is_active = Column(Boolean, default=True, index=True)

    # Timestamps
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    user = relationship("User", foreign_keys=[user_id])
    messages = relationship("ChatMessage", back_populates="conversation", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Conversation(id={self.id}, title={self.title}, active={self.is_active})>"


class ChatMessage(Base):
    """Individual chat messages within a conversation"""
    __tablename__ = "chat_messages"

    id = Column(Integer, primary_key=True, index=True)
    conversation_id = Column(Integer, ForeignKey("conversations.id"), nullable=False, index=True)

    # Message content
    role = Column(String(20), nullable=False)  # 'user', 'assistant', 'tool_result'
    content = Column(Text, nullable=False)

    # Context when message was sent
    context = Column(JSON)  # { page: 'production_calendar', selectedDate: '2026-02-10', ... }

    # Actions taken (for assistant messages)
    actions_taken = Column(JSON)  # [{ tool: 'schedule_order', params: {...}, result: {...} }, ...]

    # Token usage tracking
    tokens_used = Column(Integer)

    # Timestamps
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    # Relationships
    conversation = relationship("Conversation", back_populates="messages")

    def __repr__(self):
        return f"<ChatMessage(id={self.id}, role={self.role}, conv={self.conversation_id})>"

    def to_dict(self):
        return {
            "id": self.id,
            "conversationId": self.conversation_id,
            "role": self.role,
            "content": self.content,
            "context": self.context,
            "actionsTaken": self.actions_taken,
            "tokensUsed": self.tokens_used,
            "createdAt": self.created_at.isoformat() if self.created_at else None,
        }


# ============================================================================
# APPLICATION SETTINGS MODELS
# ============================================================================

class QuoteSnapshot(Base):
    """Stores the original configurator output when a BC quote is created"""
    __tablename__ = "quote_snapshots"

    id = Column(Integer, primary_key=True, index=True)
    bc_quote_id = Column(String(100), unique=True, nullable=False, index=True)
    bc_quote_number = Column(String(50), index=True)
    source = Column(String(20), nullable=False)  # "admin" or "customer"

    # Original configurator output
    original_lines = Column(JSON)  # The all_lines list at generation time
    original_line_pricing = Column(JSON)  # The line_pricing with prices from BC
    original_pricing_totals = Column(JSON)  # {subtotal, tax, total}
    door_configs = Column(JSON)  # Simplified door configs for AI context

    # Context
    bc_customer_id = Column(String(100), nullable=True)
    pricing_tier = Column(String(50), nullable=True)
    saved_config_id = Column(Integer, ForeignKey("saved_quote_configs.id"), nullable=True)

    # Timestamps
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, onupdate=datetime.utcnow)

    # Relationships
    reviews = relationship("QuoteReview", back_populates="snapshot", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<QuoteSnapshot(id={self.id}, bc_quote={self.bc_quote_number}, source={self.source})>"


class QuoteReview(Base):
    """Stores each comparison result between original snapshot and current BC quote"""
    __tablename__ = "quote_reviews"

    id = Column(Integer, primary_key=True, index=True)
    snapshot_id = Column(Integer, ForeignKey("quote_snapshots.id"), nullable=False, index=True)

    # Current BC state at review time
    bc_lines_at_review = Column(JSON)  # BC quote lines fetched at review time

    # Diff result
    diff_result = Column(JSON)  # {added, removed, modified, unchanged_count, summary}

    # AI analysis
    ai_analysis = Column(JSON, nullable=True)  # patterns, code suggestions, confidence

    # Review metadata
    reviewed_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    review_notes = Column(Text, nullable=True)

    # Timestamps
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    # Relationships
    snapshot = relationship("QuoteSnapshot", back_populates="reviews")
    reviewer = relationship("User", foreign_keys=[reviewed_by])

    def __repr__(self):
        return f"<QuoteReview(id={self.id}, snapshot={self.snapshot_id})>"


class AppSettings(Base):
    """Application-wide settings storage"""
    __tablename__ = "app_settings"

    id = Column(Integer, primary_key=True, index=True)
    setting_key = Column(String(100), unique=True, nullable=False, index=True)
    setting_value = Column(JSON, nullable=False)
    description = Column(String(500), nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    updated_by = Column(Integer, ForeignKey("users.id"), nullable=True)

    # Relationships
    updated_by_user = relationship("User", foreign_keys=[updated_by])

    def __repr__(self):
        return f"<AppSettings(key={self.setting_key}, updated_at={self.updated_at})>"

    def to_dict(self):
        return {
            "id": self.id,
            "settingKey": self.setting_key,
            "settingValue": self.setting_value,
            "description": self.description,
            "updatedAt": self.updated_at.isoformat() if self.updated_at else None,
            "updatedBy": self.updated_by,
        }


# ============================================================================
# OPENDC PLATFORM MODELS (Catalog, Agents, Inventory, PO)
# ============================================================================

class CatalogStatus(enum.Enum):
    """Status of a part in the catalog"""
    PENDING_REVIEW = "pending_review"
    ACTIVE = "active"
    INACTIVE = "inactive"
    DISCONTINUED = "discontinued"


class SpecialOrderStatus(enum.Enum):
    """Status of a special order request"""
    PENDING = "pending"
    QUOTED = "quoted"
    ORDERED = "ordered"
    RECEIVED = "received"
    CANCELLED = "cancelled"


class DemandSignalType(enum.Enum):
    """Types of inventory demand signals"""
    CRITICAL_STOCKOUT = "critical_stockout"
    REORDER_NEEDED = "reorder_needed"
    DEMAND_SIGNAL = "demand_signal"


class POAgentMode(enum.Enum):
    """PO Agent operation modes"""
    DRAFT_ONLY = "draft_only"
    PENDING_APPROVAL = "pending_approval"
    AUTO_APPROVE = "auto_approve"


class POStatus(enum.Enum):
    """PO draft status"""
    DRAFT = "draft"
    APPROVED = "approved"
    REJECTED = "rejected"
    SUBMITTED = "submitted"
    FAILED = "failed"


class Part(Base):
    """Core parts catalog — items extracted from BC, classified and enriched"""
    __tablename__ = "parts"

    id = Column(Integer, primary_key=True, index=True)

    # BC reference
    bc_item_id = Column(String(100), nullable=True, index=True)
    bc_item_number = Column(String(100), nullable=False, index=True)
    bc_description = Column(String(500), nullable=True)

    # Classification
    category = Column(String(50), nullable=False, index=True)  # spring, panel, track, hardware, etc.
    subcategory = Column(String(50), nullable=True)

    # Enriched attributes (JSONB-style)
    attributes = Column(JSON, nullable=True)  # wire_size, coil_diameter, wind_direction, color, etc.

    # Pricing
    unit_cost = Column(Numeric(10, 2), nullable=True)
    retail_price = Column(Numeric(10, 2), nullable=True)

    # Supplier
    vendor_id = Column(String(100), nullable=True)
    vendor_name = Column(String(255), nullable=True)
    lead_time_days = Column(Integer, nullable=True)

    # Compatibility
    compatibility = Column(JSON, nullable=True)  # door models, lift types, etc.

    # Status
    catalog_status = Column(
        String(30), nullable=False, default="pending_review", index=True
    )

    # Timestamps
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, onupdate=datetime.utcnow)

    def __repr__(self):
        return f"<Part(id={self.id}, item={self.bc_item_number}, cat={self.category})>"


class DrumType(Base):
    """Drum radius reference for torque calculations"""
    __tablename__ = "drum_types"

    id = Column(Integer, primary_key=True, index=True)
    drum_model = Column(String(50), nullable=False, unique=True)
    radius_inches = Column(Float, nullable=False)
    lift_type = Column(String(30), nullable=False)  # standard, high_lift, vertical
    max_door_height_inches = Column(Integer, nullable=True)
    description = Column(String(255), nullable=True)

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    def __repr__(self):
        return f"<DrumType(model={self.drum_model}, radius={self.radius_inches})>"


class DoorWeightDefault(Base):
    """Weight lookup by door dimensions and material"""
    __tablename__ = "door_weight_defaults"

    id = Column(Integer, primary_key=True, index=True)
    door_model = Column(String(50), nullable=False, index=True)
    width_inches = Column(Integer, nullable=False)
    height_inches = Column(Integer, nullable=False)
    weight_lbs = Column(Float, nullable=False)
    material = Column(String(50), nullable=True)  # insulated, non-insulated, etc.

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    def __repr__(self):
        return f"<DoorWeightDefault(model={self.door_model}, {self.width_inches}x{self.height_inches}, {self.weight_lbs}lbs)>"


class WireSizeConstraint(Base):
    """IPPT ranges per wire size / inside diameter / cycle rating"""
    __tablename__ = "wire_size_constraints"

    id = Column(Integer, primary_key=True, index=True)
    wire_diameter = Column(Float, nullable=False)
    inside_diameter = Column(Float, nullable=False)
    cycle_rating = Column(Integer, nullable=False)  # 10000, 15000, 20000, 25000, 50000, 100000
    min_ippt = Column(Float, nullable=True)
    max_ippt = Column(Float, nullable=True)

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    def __repr__(self):
        return f"<WireSizeConstraint(wire={self.wire_diameter}, ID={self.inside_diameter}, cycles={self.cycle_rating})>"


class StockedInsideDiameter(Base):
    """Stocked coil inside diameters — 4 fixed rows"""
    __tablename__ = "stocked_inside_diameters"

    id = Column(Integer, primary_key=True, index=True)
    inside_diameter = Column(Float, nullable=False, unique=True)
    description = Column(String(100), nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    def __repr__(self):
        return f"<StockedInsideDiameter(ID={self.inside_diameter})>"


class BCStagingItem(Base):
    """Catalog builder extraction staging — raw BC items before classification"""
    __tablename__ = "bc_staging"

    id = Column(Integer, primary_key=True, index=True)

    # BC raw data
    bc_item_id = Column(String(100), nullable=False, index=True)
    bc_item_number = Column(String(100), nullable=False, index=True)
    bc_description = Column(String(500), nullable=True)
    bc_unit_cost = Column(Numeric(10, 2), nullable=True)
    bc_unit_price = Column(Numeric(10, 2), nullable=True)
    bc_inventory = Column(Float, nullable=True)
    bc_raw_data = Column(JSON, nullable=True)

    # Processing state
    is_processed = Column(Boolean, nullable=False, default=False, index=True)
    classified_category = Column(String(50), nullable=True)
    enriched_attributes = Column(JSON, nullable=True)
    processing_notes = Column(Text, nullable=True)

    # Pipeline tracking
    pipeline_run_id = Column(String(50), nullable=True, index=True)

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    processed_at = Column(DateTime, nullable=True)

    def __repr__(self):
        return f"<BCStagingItem(item={self.bc_item_number}, processed={self.is_processed})>"


class CatalogReviewItem(Base):
    """Items needing human review/classification"""
    __tablename__ = "catalog_review_queue"

    id = Column(Integer, primary_key=True, index=True)

    # Reference to staging
    staging_id = Column(Integer, ForeignKey("bc_staging.id"), nullable=True)
    bc_item_number = Column(String(100), nullable=False, index=True)
    bc_description = Column(String(500), nullable=True)

    # Review context
    reason = Column(String(100), nullable=False)  # unknown_prefix, ambiguous_classification, etc.
    suggested_category = Column(String(50), nullable=True)
    suggested_attributes = Column(JSON, nullable=True)

    # Resolution
    is_resolved = Column(Boolean, nullable=False, default=False, index=True)
    resolved_category = Column(String(50), nullable=True)
    resolved_attributes = Column(JSON, nullable=True)
    resolved_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    resolved_at = Column(DateTime, nullable=True)

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    # Relationships
    staging_item = relationship("BCStagingItem", foreign_keys=[staging_id])
    resolver = relationship("User", foreign_keys=[resolved_by])

    def __repr__(self):
        return f"<CatalogReviewItem(item={self.bc_item_number}, resolved={self.is_resolved})>"


class DuplicateCandidate(Base):
    """Deduplication flagging — potential duplicate parts"""
    __tablename__ = "duplicate_candidates"

    id = Column(Integer, primary_key=True, index=True)

    # The two items being compared
    item_a_number = Column(String(100), nullable=False, index=True)
    item_b_number = Column(String(100), nullable=False, index=True)
    item_a_id = Column(Integer, ForeignKey("parts.id"), nullable=True)
    item_b_id = Column(Integer, ForeignKey("parts.id"), nullable=True)

    # Similarity scoring
    similarity_score = Column(Float, nullable=False)  # 0.0 to 1.0
    match_reasons = Column(JSON, nullable=True)  # ["same_attributes", "similar_description", etc.]

    # Resolution
    is_resolved = Column(Boolean, nullable=False, default=False, index=True)
    resolution = Column(String(50), nullable=True)  # keep_both, merge, discard_b
    resolved_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    resolved_at = Column(DateTime, nullable=True)

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    # Relationships
    part_a = relationship("Part", foreign_keys=[item_a_id])
    part_b = relationship("Part", foreign_keys=[item_b_id])
    resolver = relationship("User", foreign_keys=[resolved_by])

    def __repr__(self):
        return f"<DuplicateCandidate(A={self.item_a_number}, B={self.item_b_number}, score={self.similarity_score})>"


class SpecialOrderRequest(Base):
    """Spring specs that can't be fulfilled from catalog"""
    __tablename__ = "special_order_queue"

    id = Column(Integer, primary_key=True, index=True)

    # Customer reference
    customer_user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    bc_customer_id = Column(String(100), nullable=True)

    # Spring specification
    wire_diameter = Column(Float, nullable=False)
    coil_diameter = Column(Float, nullable=False)
    spring_length = Column(Float, nullable=False)
    wind_direction = Column(String(5), nullable=False)  # LH or RH
    quantity = Column(Integer, nullable=False, default=1)
    spring_type = Column(String(10), nullable=True)  # SP10, SP11

    # Door context
    door_width = Column(Float, nullable=True)
    door_height = Column(Float, nullable=True)
    door_weight = Column(Float, nullable=True)

    # Calculation context
    calculation_data = Column(JSON, nullable=True)  # full spring calc output

    # Status tracking
    status = Column(
        String(20), nullable=False, default="pending", index=True
    )
    admin_notes = Column(Text, nullable=True)
    quoted_price = Column(Numeric(10, 2), nullable=True)
    quoted_lead_time_days = Column(Integer, nullable=True)

    # Timestamps
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, onupdate=datetime.utcnow)

    # Relationships
    customer = relationship("User", foreign_keys=[customer_user_id])

    def __repr__(self):
        return f"<SpecialOrderRequest(id={self.id}, wire={self.wire_diameter}, status={self.status})>"


class DemandSignal(Base):
    """Inventory review agent output — demand signals for restocking"""
    __tablename__ = "demand_signals"

    id = Column(Integer, primary_key=True, index=True)

    # Part reference
    part_id = Column(Integer, ForeignKey("parts.id"), nullable=True)
    bc_item_number = Column(String(100), nullable=False, index=True)

    # Signal details
    signal_type = Column(
        String(30), nullable=False, index=True
    )  # critical_stockout, reorder_needed, demand_signal
    severity = Column(Integer, nullable=False, default=5)  # 1-10, 10 = most urgent

    # Inventory snapshot at signal time
    current_stock = Column(Float, nullable=True)
    reorder_point = Column(Float, nullable=True)
    avg_daily_demand = Column(Float, nullable=True)
    days_of_stock = Column(Float, nullable=True)

    # Recommended action
    recommended_qty = Column(Float, nullable=True)
    recommended_vendor = Column(String(255), nullable=True)
    estimated_lead_time_days = Column(Integer, nullable=True)

    # Status
    is_acknowledged = Column(Boolean, nullable=False, default=False, index=True)
    acknowledged_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    acknowledged_at = Column(DateTime, nullable=True)
    linked_po_id = Column(Integer, nullable=True)  # linked to po_agent_log if PO was generated

    # Pipeline tracking
    review_run_id = Column(String(50), nullable=True, index=True)

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    # Relationships
    part = relationship("Part", foreign_keys=[part_id])
    acknowledger = relationship("User", foreign_keys=[acknowledged_by])

    def __repr__(self):
        return f"<DemandSignal(item={self.bc_item_number}, type={self.signal_type}, severity={self.severity})>"


class POAgentLog(Base):
    """PO tracking — drafts, approvals, rejections for learning"""
    __tablename__ = "po_agent_log"

    id = Column(Integer, primary_key=True, index=True)

    # Vendor
    vendor_id = Column(String(100), nullable=True)
    vendor_name = Column(String(255), nullable=False)

    # PO details
    status = Column(
        String(20), nullable=False, default="draft", index=True
    )  # draft, approved, rejected, submitted, failed
    total_amount = Column(Numeric(10, 2), nullable=True)
    currency = Column(String(10), nullable=False, default="CAD")

    # Line items
    line_items = Column(JSON, nullable=False)  # [{bc_item_number, qty, unit_cost, description}, ...]

    # Source signals
    demand_signal_ids = Column(JSON, nullable=True)  # [signal_id, ...]

    # BC reference (after submission)
    bc_po_id = Column(String(100), nullable=True)
    bc_po_number = Column(String(50), nullable=True)

    # Approval workflow
    approved_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    approved_at = Column(DateTime, nullable=True)
    rejected_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    rejected_at = Column(DateTime, nullable=True)
    rejection_reason = Column(Text, nullable=True)

    # Pipeline tracking
    po_run_id = Column(String(50), nullable=True, index=True)

    # Timestamps
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, onupdate=datetime.utcnow)
    submitted_at = Column(DateTime, nullable=True)

    # Relationships
    approver = relationship("User", foreign_keys=[approved_by])
    rejector = relationship("User", foreign_keys=[rejected_by])

    def __repr__(self):
        return f"<POAgentLog(id={self.id}, vendor={self.vendor_name}, status={self.status})>"
