"""
Database Models for BC AI Agent
SQLAlchemy models for PostgreSQL database
"""

from datetime import datetime
from typing import Optional
from sqlalchemy import (
    Column, Integer, String, Text, DateTime, Boolean, Float,
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

    # Relationships
    email_connections = relationship("EmailConnection", back_populates="user", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<User(id={self.id}, email={self.email}, role={self.role.value})>"


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
    ai_category = Column(String(50))  # quote_request, invoice, inquiry, other, etc.
    ai_category_confidence = Column(Float)  # 0.0-1.0
    ai_category_reasoning = Column(Text)  # Why AI chose this category
    user_verified_category = Column(String(50))  # User's correction (if different from AI)
    categorization_correct = Column(Boolean)  # Was AI categorization correct?

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
    pricing_tier = Column(String(50))  # 'standard', 'preferred', 'wholesale', 'contractor'
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
    bc_order_id = Column(String(100), unique=True, index=True)  # BC sales order GUID
    bc_order_number = Column(String(50), index=True)  # e.g., "SO-001234"
    bc_quote_number = Column(String(50))  # Source quote reference

    # Customer
    customer_id = Column(String(100))  # BC customer ID
    customer_name = Column(String(255))
    customer_email = Column(String(255))

    # Order details
    status = Column(SQLEnum(OrderStatus), default=OrderStatus.PENDING, index=True)
    total_amount = Column(Numeric(12, 2))
    currency = Column(String(10), default="CAD")

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
    production_orders = relationship("ProductionOrder", back_populates="sales_order", cascade="all, delete-orphan")
    shipments = relationship("Shipment", back_populates="sales_order", cascade="all, delete-orphan")
    invoices = relationship("Invoice", back_populates="sales_order", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<SalesOrder(id={self.id}, bc_number={self.bc_order_number}, status={self.status.value})>"


class ProductionOrder(Base):
    """Production orders - created from sales order line items"""
    __tablename__ = "production_orders"

    id = Column(Integer, primary_key=True, index=True)
    sales_order_id = Column(Integer, ForeignKey("sales_orders.id"), nullable=False, index=True)

    # BC Integration
    bc_prod_order_id = Column(String(100), unique=True, index=True)
    bc_prod_order_number = Column(String(50), index=True)  # e.g., "PO-001234"

    # Production details
    status = Column(SQLEnum(ProductionStatus), default=ProductionStatus.PLANNED, index=True)
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
    status = Column(SQLEnum(InvoiceStatus), default=InvoiceStatus.DRAFT, index=True)
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
