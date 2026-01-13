"""
Feedback API Endpoints
Allows users to approve, correct, or reject AI parses
"""

import logging
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List, Optional
from pydantic import BaseModel, Field
from datetime import datetime

from app.db.database import SessionLocal
from app.db.models import (
    QuoteRequest, ParseFeedback, ParseExample,
    FeedbackType, EmailLog
)
from app.services.memory_service import get_memory_service

router = APIRouter(prefix="/api/quotes", tags=["feedback"])
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

class FeedbackRequest(BaseModel):
    """Request model for providing feedback"""
    feedback_type: str = Field(..., description="approve, correct, or reject")
    corrected_data: Optional[dict] = Field(None, description="Corrected parse data (required for 'correct')")
    notes: Optional[str] = Field(None, description="Optional feedback notes")
    review_time_seconds: Optional[int] = Field(None, description="Time spent reviewing")

    class Config:
        json_schema_extra = {
            "example": {
                "feedback_type": "approve",
                "notes": "Looks good!",
                "review_time_seconds": 30
            }
        }


class CorrectionRequest(BaseModel):
    """Request model for correcting a parse"""
    corrected_data: dict = Field(..., description="The corrected parse data")
    notes: Optional[str] = Field(None, description="Explanation of corrections")

    class Config:
        json_schema_extra = {
            "example": {
                "corrected_data": {
                    "customer": {
                        "company_name": "ABC Construction",
                        "contact_name": "John Smith",
                        "phone": "(403) 555-1234",
                        "email": "john@abc.com"
                    },
                    "doors": [
                        {
                            "model": "TX450",
                            "quantity": 2,
                            "width_ft": 10,
                            "height_ft": 10,
                            "color": "Brown"
                        }
                    ]
                },
                "notes": "Corrected door model from AL976 to TX450"
            }
        }


class QuoteResponse(BaseModel):
    """Response model for quote request"""
    id: int
    customer_name: Optional[str]
    contact_email: Optional[str]
    contact_phone: Optional[str]
    parsed_data: dict
    confidence_scores: dict
    status: str
    created_at: datetime
    email_subject: Optional[str]
    email_from: Optional[str]

    class Config:
        from_attributes = True


class FeedbackResponse(BaseModel):
    """Response model for feedback"""
    id: int
    quote_request_id: int
    feedback_type: str
    created_at: datetime
    message: str

    class Config:
        from_attributes = True


# ============================================================================
# ENDPOINTS
# ============================================================================

@router.get("/pending-review", response_model=List[QuoteResponse])
def get_pending_reviews(
    min_confidence: float = 0.0,
    max_results: int = 50,
    status: Optional[str] = None,  # NEW: Optional status filter
    db: Session = Depends(get_db)
):
    """Get quote requests pending review

    Returns all quote requests that haven't been reviewed yet.

    Args:
        min_confidence: Minimum confidence threshold (0.0-1.0)
        max_results: Maximum number of results to return
        status: Optional status filter (pending, approved, rejected, or 'all' for everything)

    Returns:
        List of pending quote requests
    """
    # Build query based on status parameter
    if status == "all":
        query = db.query(QuoteRequest)
    elif status:
        query = db.query(QuoteRequest).filter(QuoteRequest.status == status)
    else:
        query = db.query(QuoteRequest).filter(
            QuoteRequest.status.in_(["pending", "low_confidence"])
        )

    # Filter by confidence if specified
    if min_confidence > 0:
        quotes = [q for q in query.all()
                  if q.confidence_scores.get("overall", 0) >= min_confidence]
    else:
        quotes = query.all()

    # Limit results
    quotes = quotes[:max_results]

    # Enrich with email data
    results = []
    for quote in quotes:
        email_log = db.query(EmailLog).filter(EmailLog.id == quote.email_id).first()
        result = QuoteResponse(
            id=quote.id,
            customer_name=quote.customer_name,
            contact_email=quote.contact_email,
            contact_phone=quote.contact_phone,
            parsed_data=quote.parsed_data,
            confidence_scores=quote.confidence_scores,
            status=quote.status,
            created_at=quote.created_at,
            email_subject=email_log.subject if email_log else None,
            email_from=email_log.from_address if email_log else None
        )
        results.append(result)

    return results


@router.get("/{quote_id}", response_model=QuoteResponse)
def get_quote(quote_id: int, db: Session = Depends(get_db)):
    """Get a specific quote request by ID

    Args:
        quote_id: Quote request ID

    Returns:
        Quote request details
    """
    quote = db.query(QuoteRequest).filter(QuoteRequest.id == quote_id).first()

    if not quote:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Quote request #{quote_id} not found"
        )

    email_log = db.query(EmailLog).filter(EmailLog.id == quote.email_id).first()

    return QuoteResponse(
        id=quote.id,
        customer_name=quote.customer_name,
        contact_email=quote.contact_email,
        contact_phone=quote.contact_phone,
        parsed_data=quote.parsed_data,
        confidence_scores=quote.confidence_scores,
        status=quote.status,
        created_at=quote.created_at,
        email_subject=email_log.subject if email_log else None,
        email_from=email_log.from_address if email_log else None
    )


@router.post("/{quote_id}/feedback", response_model=FeedbackResponse)
def submit_feedback(
    quote_id: int,
    feedback: FeedbackRequest,
    user_id: str = "system",  # TODO: Get from auth
    db: Session = Depends(get_db)
):
    """Submit feedback on a quote parse

    Allows user to approve, correct, or reject an AI parse.
    Triggers the learning system to update examples and knowledge.

    Args:
        quote_id: Quote request ID
        feedback: Feedback data
        user_id: User providing feedback (from auth)

    Returns:
        Feedback confirmation
    """
    # Validate quote exists
    quote = db.query(QuoteRequest).filter(QuoteRequest.id == quote_id).first()
    if not quote:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Quote request #{quote_id} not found"
        )

    # Validate feedback type
    feedback_type_str = feedback.feedback_type.upper()
    if feedback_type_str not in ['APPROVE', 'CORRECT', 'REJECT']:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="feedback_type must be 'approve', 'correct', or 'reject'"
        )

    feedback_type = FeedbackType[feedback_type_str]

    # Validate corrected data for CORRECT type
    if feedback_type == FeedbackType.CORRECT and not feedback.corrected_data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="corrected_data is required when feedback_type is 'correct'"
        )

    # Record feedback using memory service
    memory_service = get_memory_service(db)
    parse_feedback = memory_service.record_feedback(
        quote_request_id=quote_id,
        user_id=user_id,
        feedback_type=feedback_type,
        original_parse=quote.parsed_data,
        corrected_parse=feedback.corrected_data,
        feedback_notes=feedback.notes,
        review_time_seconds=feedback.review_time_seconds
    )

    # Update quote status
    if feedback_type == FeedbackType.APPROVE:
        quote.status = "approved"
        message = "Quote approved and added to learning examples"
    elif feedback_type == FeedbackType.CORRECT:
        quote.status = "approved"  # Corrected and approved
        message = "Quote corrected and learning system updated"
    else:  # REJECT
        quote.status = "rejected"
        message = "Quote rejected"

    db.commit()

    return FeedbackResponse(
        id=parse_feedback.id,
        quote_request_id=quote_id,
        feedback_type=feedback_type.value,
        created_at=parse_feedback.created_at,
        message=message
    )


@router.post("/{quote_id}/approve", response_model=FeedbackResponse)
def approve_quote(
    quote_id: int,
    notes: Optional[str] = None,
    user_id: str = "system",  # TODO: Get from auth
    db: Session = Depends(get_db)
):
    """Quick approve a quote parse

    Shortcut endpoint for approving without full feedback object.

    Args:
        quote_id: Quote request ID
        notes: Optional approval notes
        user_id: User approving (from auth)

    Returns:
        Feedback confirmation
    """
    feedback = FeedbackRequest(
        feedback_type="approve",
        notes=notes
    )
    return submit_feedback(quote_id, feedback, user_id, db)


@router.post("/{quote_id}/correct", response_model=FeedbackResponse)
def correct_quote(
    quote_id: int,
    correction: CorrectionRequest,
    user_id: str = "system",  # TODO: Get from auth
    db: Session = Depends(get_db)
):
    """Correct a quote parse

    Provide corrected data for the quote request.
    The learning system will update with the correction.

    Args:
        quote_id: Quote request ID
        correction: Corrected parse data
        user_id: User correcting (from auth)

    Returns:
        Feedback confirmation
    """
    feedback = FeedbackRequest(
        feedback_type="correct",
        corrected_data=correction.corrected_data,
        notes=correction.notes
    )
    return submit_feedback(quote_id, feedback, user_id, db)


@router.post("/{quote_id}/reject", response_model=FeedbackResponse)
def reject_quote(
    quote_id: int,
    notes: Optional[str] = None,
    user_id: str = "system",  # TODO: Get from auth
    db: Session = Depends(get_db)
):
    """Reject a quote parse

    Mark the parse as incorrect/unusable.

    Args:
        quote_id: Quote request ID
        notes: Optional rejection reason
        user_id: User rejecting (from auth)

    Returns:
        Feedback confirmation
    """
    feedback = FeedbackRequest(
        feedback_type="reject",
        notes=notes
    )
    return submit_feedback(quote_id, feedback, user_id, db)


@router.get("/{quote_id}/examples-used", response_model=List[dict])
def get_examples_used(quote_id: int, db: Session = Depends(get_db)):
    """Get the examples that were used to parse this quote

    Shows which past examples the AI referenced when parsing this quote.
    Useful for understanding why the AI made certain decisions.

    Args:
        quote_id: Quote request ID

    Returns:
        List of example metadata
    """
    # This would require storing which examples were used during parsing
    # For now, return empty list as this is a future enhancement
    return []


# ============================================================================
# ANALYTICS ENDPOINTS
# ============================================================================

@router.get("/stats/learning-progress")
def get_learning_progress(db: Session = Depends(get_db)):
    """Get learning system statistics

    Returns:
        Current learning metrics
    """
    from app.db.models import LearningMetrics, DomainKnowledge

    # Get latest metrics
    latest_metrics = db.query(LearningMetrics).order_by(
        LearningMetrics.metric_date.desc()
    ).first()

    # Get current counts
    total_examples = db.query(ParseExample).count()
    verified_examples = db.query(ParseExample).filter(
        ParseExample.is_verified == True
    ).count()
    total_knowledge = db.query(DomainKnowledge).count()
    pending_reviews = db.query(QuoteRequest).filter(
        QuoteRequest.status.in_(["pending", "low_confidence"])
    ).count()

    return {
        "total_examples": total_examples,
        "verified_examples": verified_examples,
        "total_knowledge_items": total_knowledge,
        "pending_reviews": pending_reviews,
        "latest_metrics": {
            "date": latest_metrics.metric_date if latest_metrics else None,
            "approval_rate": latest_metrics.approval_rate if latest_metrics else None,
            "avg_confidence": latest_metrics.avg_confidence if latest_metrics else None
        } if latest_metrics else None
    }


# ============================================================================
# QUOTE GENERATION ENDPOINTS (Week 3)
# ============================================================================

@router.post("/{quote_id}/generate-quote")
def generate_quote(
    quote_id: int,
    db: Session = Depends(get_db)
):
    """Generate a quote with line items and pricing from parsed email data"""
    from app.services.quote_service import get_quote_service

    try:
        quote_service = get_quote_service(db)
        result = quote_service.generate_quote(quote_id)

        return {
            "success": True,
            "quote": result
        }

    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Error generating quote: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to generate quote: {str(e)}")


@router.get("/{quote_id}/quote-items")
def get_quote_items(
    quote_id: int,
    db: Session = Depends(get_db)
):
    """Get line items for a generated quote"""
    from app.db.models import QuoteItem

    items = db.query(QuoteItem).filter(
        QuoteItem.quote_request_id == quote_id
    ).all()

    if not items:
        raise HTTPException(status_code=404, detail="No quote items found. Generate quote first.")

    # Calculate totals
    subtotal = sum(float(item.total_price or 0) for item in items)
    tax = subtotal * 0.05  # 5% GST

    return {
        "quote_id": quote_id,
        "items": [
            {
                "id": item.id,
                "type": item.item_type,
                "product_code": item.product_code,
                "description": item.description,
                "quantity": item.quantity,
                "unit_price": float(item.unit_price or 0),
                "total_price": float(item.total_price or 0),
                "metadata": item.item_metadata
            }
            for item in items
        ],
        "subtotal": subtotal,
        "tax": tax,
        "total": subtotal + tax
    }
