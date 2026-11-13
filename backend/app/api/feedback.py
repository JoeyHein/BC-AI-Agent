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
    FeedbackType, EmailLog, User
)
from app.services.memory_service import get_memory_service
from app.services.upwardor_service import generate_upwardor_quote_from_request, UpwardorAPIError
from app.services.bc_quote_service import bc_quote_service
from app.api.auth import get_current_user
from app.api.staff_principal import require_staff

router = APIRouter(
    prefix="/api/quotes",
    tags=["feedback"],
    dependencies=[Depends(require_staff)],
)
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
    email_id: Optional[int]  # Email ID for feedback/learning system
    customer_name: Optional[str]
    contact_email: Optional[str]
    contact_phone: Optional[str]
    parsed_data: dict
    confidence_scores: dict
    status: str
    created_at: datetime
    email_subject: Optional[str]
    email_from: Optional[str]
    bc_quote_id: Optional[str]  # BC quote ID if created
    field_sources: Optional[dict] = None
    deviations: Optional[list] = None
    matched_bc_customer_id: Optional[str] = None
    customer_match: Optional[dict] = None
    customer_approval: Optional[dict] = None

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
    elif status == "pending":
        # "Pending" is anything still waiting for a person, including a
        # quote held because the email differs from the customer standard.
        query = db.query(QuoteRequest).filter(
            QuoteRequest.status.in_([
                "pending",
                "low_confidence",
                "needs_manual_review",
                "held_for_customer_match",
                "held_for_standard_deviation",
            ])
        )
    elif status:
        query = db.query(QuoteRequest).filter(QuoteRequest.status == status)
    else:
        query = db.query(QuoteRequest).filter(
            QuoteRequest.status.in_([
                "pending",
                "low_confidence",
                "needs_manual_review",
                "held_for_customer_match",
                "held_for_standard_deviation",
            ])
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
            email_id=quote.email_id,
            customer_name=quote.customer_name,
            contact_email=quote.contact_email,
            contact_phone=quote.contact_phone,
            parsed_data=quote.parsed_data,
            confidence_scores=quote.confidence_scores,
            status=quote.status,
            created_at=quote.created_at,
            email_subject=email_log.subject if email_log else None,
            email_from=email_log.from_address if email_log else None,
            bc_quote_id=quote.bc_quote_id,
            field_sources=quote.field_sources,
            deviations=quote.deviations,
            matched_bc_customer_id=quote.matched_bc_customer_id,
            customer_match=quote.customer_match,
        )
        results.append(result)

    return results


class ConvertApprovalBody(BaseModel):
    bc_quote_number: Optional[str] = None


def _approval_for_quote(db: Session, quote: QuoteRequest):
    from app.db.models import CustomerOrderApproval
    from app.services.quote_followup import approval_to_dict
    row = (
        db.query(CustomerOrderApproval)
        .filter(CustomerOrderApproval.email_log_id == quote.email_id)
        .order_by(CustomerOrderApproval.id.desc())
        .first()
    )
    if row is None:
        rows = (
            db.query(CustomerOrderApproval)
            .filter(CustomerOrderApproval.status.in_(["ready", "needs_choice", "converted"]))
            .order_by(CustomerOrderApproval.id.desc())
            .limit(50)
            .all()
        )
        for candidate in rows:
            if candidate.quote_request_id == quote.id:
                row = candidate
                break
            for item in candidate.candidates or []:
                if isinstance(item, dict) and item.get("quote_request_id") == quote.id:
                    row = candidate
                    break
            if row is not None:
                break
    return approval_to_dict(row) if row else None


@router.get("/customer-approvals")
def list_customer_approvals(
    status: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """Go-ahead emails waiting for staff to convert a quote. Nothing is converted here."""
    from app.db.models import CustomerOrderApproval
    from app.services.quote_followup import approval_to_dict
    query = db.query(CustomerOrderApproval).order_by(CustomerOrderApproval.created_at.desc())
    if status:
        query = query.filter(CustomerOrderApproval.status == status)
    return [approval_to_dict(row) for row in query.limit(100).all()]


@router.post("/customer-approvals/{approval_id}/convert")
def convert_customer_approval_route(
    approval_id: int,
    body: Optional[ConvertApprovalBody] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Convert the matched SQ. Ambiguous rows need bc_quote_number. Never automatic."""
    from app.services.quote_followup import convert_customer_approval
    return convert_customer_approval(
        db,
        approval_id,
        bc_quote_number=body.bc_quote_number if body else None,
        user_email=current_user.email,
    )


@router.post("/customer-approvals/{approval_id}/dismiss")
def dismiss_customer_approval(
    approval_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.db.models import CustomerOrderApproval
    row = db.query(CustomerOrderApproval).filter(CustomerOrderApproval.id == approval_id).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Approval not found")
    if row.status == "converted":
        raise HTTPException(status_code=400, detail="This approval is already converted")
    row.status = "dismissed"
    row.decided_at = datetime.utcnow()
    row.decided_by = current_user.email
    db.commit()
    from app.services.quote_followup import approval_to_dict
    return approval_to_dict(row)


class QuotePoAcceptBody(BaseModel):
    bc_quote_number: Optional[str] = None


@router.get("/quote-po-intakes")
def list_quote_po_intakes_route(db: Session = Depends(get_db)):
    """Purchase-order emails waiting on staff. Missed ones are first."""
    from app.services.quote_po_auto_convert import list_quote_po_intakes
    return list_quote_po_intakes(db)


@router.post("/quote-po-intakes/{intake_id}/accept")
def accept_quote_po_route(
    intake_id: int,
    body: Optional[QuotePoAcceptBody] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Convert the matched quote, or the quote number staff typed in."""
    from app.services.quote_po_auto_convert import accept_quote_po
    return accept_quote_po(
        db,
        intake_id,
        bc_quote_number=body.bc_quote_number if body else None,
        user_email=current_user.email,
    )


@router.post("/quote-po-intakes/{intake_id}/dismiss")
def dismiss_quote_po_route(
    intake_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.services.quote_po_auto_convert import dismiss_quote_po
    return dismiss_quote_po(db, intake_id, user_email=current_user.email)


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
        email_id=quote.email_id,
        customer_name=quote.customer_name,
        contact_email=quote.contact_email,
        contact_phone=quote.contact_phone,
        parsed_data=quote.parsed_data,
        confidence_scores=quote.confidence_scores,
        status=quote.status,
        created_at=quote.created_at,
        email_subject=email_log.subject if email_log else None,
        email_from=email_log.from_address if email_log else None,
        bc_quote_id=quote.bc_quote_id,
        field_sources=quote.field_sources,
        deviations=quote.deviations,
        matched_bc_customer_id=quote.matched_bc_customer_id,
        customer_match=quote.customer_match,
        customer_approval=_approval_for_quote(db, quote),
    )


def _mapped_doors(quote: QuoteRequest) -> list:
    mapping = (quote.parsed_data or {}).get("configurator_mapping") or {}
    doors = mapping.get("doors") or []
    return [door for door in doors if isinstance(door, dict)]


def _restore_quote_status(db: Session, quote_id: int, previous: str) -> None:
    try:
        db.rollback()
    except Exception:
        pass
    row = db.query(QuoteRequest).filter(QuoteRequest.id == quote_id).first()
    if row is not None and row.status == "pricing" and not row.bc_quote_id:
        row.status = previous
        db.commit()


def _price_mapped_quote(quote: QuoteRequest, db: Session, profile_applied: bool = True) -> dict:
    """Send the doors already resolved from the email to Business Central.

    A second call returns the quote that was already created. The status
    flip to ``pricing`` is committed before Business Central is called, so
    two requests cannot both create a quote.
    """
    from app.api.door_configurator import (
        DoorConfigRequest,
        QuoteGenerationRequest,
        build_bc_quote_from_doors,
    )
    from app.services.email_monitor import EmailMonitorService
    from app.services.quote_followup import queue_quote_send_for

    if quote.bc_quote_id or quote.status in {"bc_created", "quote_generated"}:
        return {
            "priced": bool(quote.bc_quote_id) or quote.status == "quote_generated",
            "status": quote.status,
            "bc_quote_number": quote.bc_quote_id,
            "already": True,
        }
    if quote.status == "pricing":
        raise HTTPException(status_code=409, detail="This quote is already being priced")
    doors = _mapped_doors(quote)
    if not doors:
        return {"priced": False, "status": quote.status, "reason": "No mapped doors to price"}
    previous = quote.status
    claimed = (
        db.query(QuoteRequest)
        .filter(
            QuoteRequest.id == quote.id,
            QuoteRequest.status == previous,
            QuoteRequest.bc_quote_id.is_(None),
        )
        .update({"status": "pricing"}, synchronize_session=False)
    )
    db.commit()
    if claimed != 1:
        db.refresh(quote)
        if quote.bc_quote_id or quote.status in {"bc_created", "quote_generated"}:
            return {
                "priced": True,
                "status": quote.status,
                "bc_quote_number": quote.bc_quote_id,
                "already": True,
            }
        raise HTTPException(status_code=409, detail="This quote is already being priced")
    db.refresh(quote)
    delivery = ((quote.field_sources or {}).get("deliveryType") or {}).get("used")
    if not delivery:
        delivery = ((quote.field_sources or {}).get("deliveryType") or {}).get("value") or "delivery"
    request = QuoteGenerationRequest(
        doors=[
            DoorConfigRequest(**{key: value for key, value in door.items() if key != "_touched"})
            for door in doors
        ],
        customerId=quote.matched_bc_customer_id,
        tagName=quote.customer_name or "Email Quote",
        poNumber=f"EMAIL-QR-{quote.id}",
        deliveryType=delivery,
        deliveryExplicit=True,
        profileApplied=profile_applied,
    )
    try:
        result = build_bc_quote_from_doors(request, db, source="email")
    except HTTPException:
        _restore_quote_status(db, quote.id, previous)
        raise
    except Exception:
        _restore_quote_status(db, quote.id, previous)
        raise
    data = result.get("data", {}) if isinstance(result, dict) else {}
    number = data.get("bc_quote_number")
    if number:
        quote.bc_quote_id = number
        quote.status = "bc_created"
    else:
        quote.status = "quote_generated"

    def _after_bc(action):
        nested = db.begin_nested()
        try:
            action()
            nested.commit()
        except Exception:
            logger.exception("Business Central quote %s was kept. A later step failed.", number)
            try:
                nested.rollback()
            except Exception:
                pass

    _after_bc(lambda: EmailMonitorService()._persist_quote_items_from_pricing(
        db, quote.id, data.get("line_pricing") or [],
    ))
    if quote.status == "bc_created":
        _after_bc(lambda: queue_quote_send_for(db, quote))
    db.commit()
    return {"priced": True, "status": quote.status, "bc_quote_number": number}


@router.post("/{quote_id}/confirm-customer")
def confirm_suggested_customer(
    quote_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Accept a suggestion, remember the sender, and price the quote.

    Pricing uses the email values. If those values differ from a locked or
    usual profile value, the quote is held for that deviation instead of
    being priced. With no mapped doors the quote returns to pending.
    """
    from app.services.customer_profile_service import (
        apply_profile_for_customer,
        get_or_create_profile,
        quote_email_text,
        quoting_mode,
    )
    quote = db.query(QuoteRequest).filter(QuoteRequest.id == quote_id).first()
    if not quote:
        raise HTTPException(status_code=404, detail="Quote request not found")
    if quote.bc_quote_id or quote.status in {"bc_created", "quote_generated"}:
        return {
            "bc_customer_id": quote.matched_bc_customer_id,
            "priced": bool(quote.bc_quote_id),
            "status": quote.status,
            "bc_quote_number": quote.bc_quote_id,
            "already": True,
        }
    if quote.status == "pricing":
        raise HTTPException(status_code=409, detail="This quote is already being priced")
    match = quote.customer_match or {}
    customer_id = match.get("bc_customer_id")
    if not customer_id or not match.get("suggested"):
        raise HTTPException(status_code=400, detail="No suggested customer to confirm")
    # Read this before writing the profile. A table check on SQLite commits
    # the connection and would drop the contact we just added.
    mode = quoting_mode(db)
    profile = get_or_create_profile(db, customer_id)
    email = (quote.contact_email or "").strip().lower()
    contacts = [dict(item) for item in (profile.contacts or []) if isinstance(item, dict)]
    if email and email not in {item.get("email") for item in contacts}:
        contacts.append({"email": email, "name": quote.customer_name, "role": "quote"})
    profile.contacts = contacts
    quote.customer_match = {
        **match,
        "suggested": False,
        "confident": True,
        "method": "confirmed_contact",
        "reason": f"Staff confirmed {email or 'the sender'} for {customer_id}",
    }
    quote.matched_bc_customer_id = customer_id
    doors = _mapped_doors(quote)
    if not doors:
        quote.status = "pending"
        quote.field_sources = {**(quote.field_sources or {}), "mode": mode}
        db.commit()
        return {"bc_customer_id": customer_id, "status": quote.status, "priced": False}

    email_log = db.query(EmailLog).filter(EmailLog.id == quote.email_id).first()
    text = quote_email_text(
        getattr(email_log, "subject", "") or "",
        getattr(email_log, "body", "") or "",
        getattr(email_log, "attachments", None),
    )
    parsed = (quote.parsed_data or {}).get("doors")
    profile_applied = mode == "on"
    if mode == "off":
        quote.field_sources = {**(quote.field_sources or {}), "mode": "off"}
    else:
        applied = apply_profile_for_customer(
            db,
            customer_id,
            [dict(door) for door in doors],
            email_text=text,
            parsed_doors=parsed if isinstance(parsed, list) else None,
            customer_name=quote.customer_name,
        )
        quote.field_sources = {**applied["field_sources"], "mode": mode}
        quote.deviations = applied["deviations"]
        if mode == "shadow":
            quote.deviations = [
                {**item, "shadow": True} if isinstance(item, dict) else item
                for item in (quote.deviations or [])
            ]
            if applied.get("hold_for_review"):
                quote.field_sources = {**(quote.field_sources or {}), "would_hold": True}
        else:
            parsed_data = dict(quote.parsed_data or {})
            mapping = dict((parsed_data.get("configurator_mapping") or {}))
            mapping["doors"] = applied["doors"]
            parsed_data["configurator_mapping"] = mapping
            quote.parsed_data = parsed_data
            if applied.get("hold_for_review"):
                quote.status = "held_for_standard_deviation"
                db.commit()
                return {
                    "bc_customer_id": customer_id,
                    "status": quote.status,
                    "priced": False,
                    "reason": "Email differs from the customer standard",
                }
    db.commit()
    try:
        outcome = _price_mapped_quote(quote, db, profile_applied=profile_applied)
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        logger.exception("Confirm-and-price failed for quote %s", quote_id)
        db.rollback()
        quote.status = "pending"
        db.commit()
        return {
            "bc_customer_id": customer_id,
            "status": quote.status,
            "priced": False,
            "reason": str(exc),
        }
    return {"bc_customer_id": customer_id, **outcome}


@router.post("/{quote_id}/release")
def release_held_quote(
    quote_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Price a held quote with the email values staff already reviewed.

    A quote still waiting on a customer match is refused. Pricing it here
    would use the suggested customer, or cash if that suggestion is empty.
    """
    quote = db.query(QuoteRequest).filter(QuoteRequest.id == quote_id).first()
    if not quote:
        raise HTTPException(status_code=404, detail="Quote request not found")
    if quote.bc_quote_id or quote.status in {"bc_created", "quote_generated"}:
        return {
            "priced": bool(quote.bc_quote_id),
            "status": quote.status,
            "bc_quote_number": quote.bc_quote_id,
            "already": True,
        }
    if quote.status == "pricing":
        raise HTTPException(status_code=409, detail="This quote is already being priced")
    if quote.status == "held_for_customer_match":
        raise HTTPException(
            status_code=400,
            detail="Confirm the customer before pricing. Release cannot price a suggested customer.",
        )
    if quote.status != "held_for_standard_deviation":
        raise HTTPException(status_code=400, detail="This quote is not held for a standard deviation")
    if not _mapped_doors(quote):
        raise HTTPException(status_code=400, detail="No mapped doors to price")
    try:
        outcome = _price_mapped_quote(quote, db)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Release failed for quote %s", quote_id)
        raise HTTPException(status_code=400, detail=f"Could not price the quote: {exc}")
    db.commit()
    return outcome


@router.post("/{quote_id}/feedback", response_model=FeedbackResponse)
def submit_feedback(
    quote_id: int,
    feedback: FeedbackRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
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
    user_id = current_user.email
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

    # Trigger Upwardor quote generation on approval
    upwardor_result = None
    bc_result = None
    if feedback_type == FeedbackType.APPROVE:
        # Generate Upwardor quote
        try:
            upwardor_result = generate_upwardor_quote_from_request(quote)
            logger.info(f"Upwardor quote generated for quote {quote_id}")
        except UpwardorAPIError as e:
            logger.warning(f"Upwardor quote generation failed: {e}")
        except Exception as e:
            logger.warning(f"Upwardor integration error: {e}")
        
        # Create BC quote with line items
        try:
            bc_result = bc_quote_service.create_quote_in_bc(
                db=db,
                quote_request=quote,
                user_id=user_id
            )
            if bc_result.get("success"):
                logger.info(f"BC quote created for quote {quote_id}: {bc_result.get('bc_quote_number')}")
            else:
                logger.warning(f"BC quote creation failed: {bc_result.get('error')}")
        except Exception as e:
            logger.warning(f"BC integration error: {e}")

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
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Quick approve a quote parse

    Shortcut endpoint for approving without full feedback object.

    Args:
        quote_id: Quote request ID
        notes: Optional approval notes

    Returns:
        Feedback confirmation
    """
    feedback = FeedbackRequest(
        feedback_type="approve",
        notes=notes
    )
    return submit_feedback(quote_id, feedback, db, current_user)


@router.post("/{quote_id}/correct", response_model=FeedbackResponse)
def correct_quote(
    quote_id: int,
    correction: CorrectionRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Correct a quote parse

    Provide corrected data for the quote request.
    The learning system will update with the correction.

    Args:
        quote_id: Quote request ID
        correction: Corrected parse data

    Returns:
        Feedback confirmation
    """
    feedback = FeedbackRequest(
        feedback_type="correct",
        corrected_data=correction.corrected_data,
        notes=correction.notes
    )
    return submit_feedback(quote_id, feedback, db, current_user)


@router.post("/{quote_id}/reject", response_model=FeedbackResponse)
def reject_quote(
    quote_id: int,
    notes: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Reject a quote parse

    Mark the parse as incorrect/unusable.

    Args:
        quote_id: Quote request ID
        notes: Optional rejection reason

    Returns:
        Feedback confirmation
    """
    feedback = FeedbackRequest(
        feedback_type="reject",
        notes=notes
    )
    return submit_feedback(quote_id, feedback, db, current_user)


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
