"""
Quote Management API Endpoints
Manager approval workflow for quotes
"""

import logging
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime

from app.db.database import SessionLocal
from app.db.models import QuoteRequest, User, QuoteItem
from app.services.bc_quote_service import bc_quote_service
from app.api.auth import get_current_user

router = APIRouter(prefix="/api/quotes", tags=["quotes"])
logger = logging.getLogger(__name__)


# Dependency to get DB session
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ============================================================================
# REQUEST/RESPONSE MODELS
# ============================================================================

class QuoteItemResponse(BaseModel):
    """Quote item response"""
    id: int
    item_type: str
    product_code: Optional[str]
    description: Optional[str]
    quantity: int
    unit_price: Optional[float]
    total_price: Optional[float]

    class Config:
        from_attributes = True


class QuoteRequestResponse(BaseModel):
    """Quote request response"""
    id: int
    customer_name: Optional[str]
    contact_email: Optional[str]
    contact_phone: Optional[str]
    door_specs: Optional[dict]
    parsed_data: Optional[dict]
    confidence_scores: Optional[dict]
    bc_quote_id: Optional[str]
    status: str
    created_at: datetime
    quote_items: List[QuoteItemResponse] = []

    class Config:
        from_attributes = True


class ApproveQuoteRequest(BaseModel):
    """Request body for approving a quote"""
    notes: Optional[str] = None
    bc_customer_id: Optional[str] = None  # If manager selects a customer
    create_in_bc: bool = False  # Whether to immediately create in BC


class RejectQuoteRequest(BaseModel):
    """Request body for rejecting a quote"""
    reason: str


class CreateBCQuoteRequest(BaseModel):
    """Request body for creating BC quote"""
    quote_request_id: int


class BCQuoteResponse(BaseModel):
    """BC quote creation response"""
    success: bool
    bc_quote_number: Optional[str] = None
    bc_quote_id: Optional[str] = None
    total_amount: Optional[float] = None
    error: Optional[str] = None


# ============================================================================
# ENDPOINTS
# ============================================================================

@router.get("/pending-review", response_model=List[QuoteRequestResponse])
def get_pending_quotes(
    status: str = "all",  # all, pending, approved, low_confidence
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get quotes pending review

    Query params:
    - status: Filter by status (all, pending, approved, low_confidence)
    """
    query = db.query(QuoteRequest)

    if status == "pending":
        query = query.filter(QuoteRequest.status.in_(["pending", "low_confidence"]))
    elif status == "approved":
        query = query.filter(QuoteRequest.status == "approved")
    elif status == "low_confidence":
        query = query.filter(QuoteRequest.status == "low_confidence")
    elif status != "all":
        query = query.filter(QuoteRequest.status == status)

    quotes = query.order_by(QuoteRequest.created_at.desc()).limit(100).all()

    return quotes


@router.get("/{quote_id}", response_model=QuoteRequestResponse)
def get_quote_detail(
    quote_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get detailed quote information"""
    quote = db.query(QuoteRequest).filter(QuoteRequest.id == quote_id).first()

    if not quote:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Quote not found"
        )

    return quote


@router.post("/{quote_id}/approve")
def approve_quote(
    quote_id: int,
    request: ApproveQuoteRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Approve a quote request

    Optionally create BC quote immediately if create_in_bc=true
    """
    # Approve the quote
    result = bc_quote_service.approve_quote_request(
        db=db,
        quote_request_id=quote_id,
        user_id=current_user.email,
        notes=request.notes,
        customer_id=request.bc_customer_id
    )

    if not result.get("success"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result.get("error", "Failed to approve quote")
        )

    # If requested, create BC quote immediately
    bc_result = None
    if request.create_in_bc:
        quote_request = db.query(QuoteRequest).filter(
            QuoteRequest.id == quote_id
        ).first()

        bc_result = bc_quote_service.create_quote_in_bc(
            db=db,
            quote_request=quote_request,
            user_id=current_user.email,
            approved_by=current_user.email
        )

    return {
        "success": True,
        "message": "Quote approved successfully",
        "quote_id": quote_id,
        "status": "approved",
        "bc_quote_created": request.create_in_bc,
        "bc_quote_result": bc_result
    }


@router.post("/{quote_id}/reject")
def reject_quote(
    quote_id: int,
    request: RejectQuoteRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Reject a quote request"""
    result = bc_quote_service.reject_quote_request(
        db=db,
        quote_request_id=quote_id,
        user_id=current_user.email,
        reason=request.reason
    )

    if not result.get("success"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result.get("error", "Failed to reject quote")
        )

    return {
        "success": True,
        "message": "Quote rejected",
        "quote_id": quote_id,
        "status": "rejected"
    }


@router.post("/create-bc-quote", response_model=BCQuoteResponse)
def create_bc_quote(
    request: CreateBCQuoteRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Create a quote in Business Central

    The quote request must be approved first
    """
    quote_request = db.query(QuoteRequest).filter(
        QuoteRequest.id == request.quote_request_id
    ).first()

    if not quote_request:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Quote request not found"
        )

    # Check if already created
    if quote_request.bc_quote_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"BC quote already created: {quote_request.bc_quote_id}"
        )

    # Create in BC
    result = bc_quote_service.create_quote_in_bc(
        db=db,
        quote_request=quote_request,
        user_id=current_user.email
    )

    if not result.get("success"):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=result.get("error", "Failed to create BC quote")
        )

    return BCQuoteResponse(**result)


@router.get("/stats/summary")
def get_quote_stats(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get quote statistics for dashboard"""
    from sqlalchemy import func
    from datetime import timedelta

    # Total counts by status
    total_pending = db.query(QuoteRequest).filter(
        QuoteRequest.status.in_(["pending", "low_confidence"])
    ).count()

    total_approved = db.query(QuoteRequest).filter(
        QuoteRequest.status == "approved"
    ).count()

    total_rejected = db.query(QuoteRequest).filter(
        QuoteRequest.status == "rejected"
    ).count()

    total_bc_created = db.query(QuoteRequest).filter(
        QuoteRequest.bc_quote_id.isnot(None)
    ).count()

    # Recent activity (last 7 days)
    seven_days_ago = datetime.utcnow() - timedelta(days=7)
    recent_quotes = db.query(QuoteRequest).filter(
        QuoteRequest.created_at >= seven_days_ago
    ).count()

    return {
        "total_pending": total_pending,
        "total_approved": total_approved,
        "total_rejected": total_rejected,
        "total_bc_created": total_bc_created,
        "recent_quotes_7d": recent_quotes,
        "approval_rate": round(
            total_approved / (total_approved + total_rejected) * 100, 1
        ) if (total_approved + total_rejected) > 0 else 0
    }
