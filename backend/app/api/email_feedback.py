"""
API endpoints for users to provide feedback on email categorizations
This feedback trains the AI to improve over time
"""

import logging
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional

from app.db.database import SessionLocal
from app.db.models import EmailLog, User
from app.services.email_categorization_service import get_categorization_service
from app.api.auth import get_current_user

router = APIRouter(prefix="/api/email-feedback", tags=["email-feedback"])
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

class EmailFeedbackRequest(BaseModel):
    """Request to provide feedback on email categorization"""
    correct_category: str  # What it should be
    comment: Optional[str] = None


class EmailFeedbackResponse(BaseModel):
    """Response after recording feedback"""
    message: str
    ai_was_correct: bool
    learning_examples_count: int
    new_category: str


class CategorizationStatsResponse(BaseModel):
    """Categorization accuracy statistics"""
    total_emails: int
    total_verified: int
    correct_categorizations: int
    incorrect_categorizations: int
    accuracy_rate: float
    false_positive_rate: float
    false_negative_rate: float
    learning_examples_available: int


# ============================================================================
# ENDPOINTS
# ============================================================================

@router.post("/{email_id}", response_model=EmailFeedbackResponse)
def provide_categorization_feedback(
    email_id: int,
    feedback: EmailFeedbackRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    User provides feedback on email categorization
    This trains the AI to improve accuracy

    Args:
        email_id: ID of the email to provide feedback for
        feedback: Feedback data (correct category, optional comment)

    Returns:
        Feedback response with updated statistics
    """
    # Get the email to check what AI said
    email = db.query(EmailLog).filter(EmailLog.id == email_id).first()
    if not email:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Email not found"
        )

    # Validate category
    valid_categories = [
        "quote_request", "order_confirmation", "invoice",
        "inquiry", "shipping", "general", "other"
    ]
    if feedback.correct_category not in valid_categories:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid category. Must be one of: {', '.join(valid_categories)}"
        )

    # Record if AI was correct
    was_correct = (email.ai_category == feedback.correct_category)

    # Get categorization service
    categorization_service = get_categorization_service(db)

    # Record user verification
    categorization_service.record_user_verification(
        email_id=email_id,
        user_verified_category=feedback.correct_category,
        was_ai_correct=was_correct
    )

    # Get updated learning examples count
    learning_examples = categorization_service._get_learning_examples()

    logger.info(
        f"User {current_user.email} provided feedback on email {email_id}: "
        f"AI said '{email.ai_category}', correct was '{feedback.correct_category}' "
        f"(AI was {'correct' if was_correct else 'incorrect'})"
    )

    # If comment provided, log it
    if feedback.comment:
        logger.info(f"  Comment: {feedback.comment}")

    return EmailFeedbackResponse(
        message="Feedback recorded - AI will learn from this" if not was_correct
                else "Thank you! AI categorization was correct",
        ai_was_correct=was_correct,
        learning_examples_count=len(learning_examples),
        new_category=feedback.correct_category
    )


@router.get("/stats", response_model=CategorizationStatsResponse)
def get_categorization_stats(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get AI categorization accuracy statistics

    Returns:
        Statistics about categorization accuracy, false positives, etc.
    """
    categorization_service = get_categorization_service(db)
    stats = categorization_service.get_categorization_stats()

    return CategorizationStatsResponse(**stats)


@router.post("/{email_id}/mark-not-quote", response_model=EmailFeedbackResponse)
def mark_as_not_quote_request(
    email_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Quick action: Mark an email as NOT a quote request

    This is a convenience endpoint for the most common correction:
    AI thought it was a quote request, but it wasn't

    Args:
        email_id: ID of the email

    Returns:
        Feedback response
    """
    # Get the email
    email = db.query(EmailLog).filter(EmailLog.id == email_id).first()
    if not email:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Email not found"
        )

    # Default to "inquiry" as the most common non-quote category
    correct_category = "inquiry"

    # Record feedback
    categorization_service = get_categorization_service(db)

    was_correct = (email.ai_category == correct_category)

    categorization_service.record_user_verification(
        email_id=email_id,
        user_verified_category=correct_category,
        was_ai_correct=was_correct
    )

    # Get updated learning examples count
    learning_examples = categorization_service._get_learning_examples()

    logger.info(
        f"User {current_user.email} marked email {email_id} as NOT a quote request "
        f"(AI said: '{email.ai_category}')"
    )

    return EmailFeedbackResponse(
        message="Marked as 'not a quote request' - AI will learn from this",
        ai_was_correct=was_correct,
        learning_examples_count=len(learning_examples),
        new_category=correct_category
    )
