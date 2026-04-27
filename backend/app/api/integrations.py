"""
Integrations API — service-to-service endpoints for external AI agents
(Donna PA, email agent, etc.) to write notes into the CRM.

Auth: X-API-Key header matching INTEGRATIONS_API_KEY env var. Does NOT use
JWT because these calls come from services, not users.
"""

import logging
import re
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Header, status
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field
from typing import Optional, Literal

from app.db.database import SessionLocal
from app.db.models import BCCustomer, CustomerNote
from app.config import settings

router = APIRouter(prefix="/api/integrations", tags=["integrations"])
logger = logging.getLogger(__name__)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def require_api_key(x_api_key: Optional[str] = Header(None)) -> None:
    """Service-to-service auth. Rejects missing/wrong keys; never logs the value."""
    expected = settings.INTEGRATIONS_API_KEY
    if not expected:
        logger.error("INTEGRATIONS_API_KEY not configured — all integration calls rejected")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Integrations not configured",
        )
    if not x_api_key or x_api_key != expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing X-API-Key",
        )


# ============================================================================
# REQUEST / RESPONSE MODELS
# ============================================================================

class CreateNoteRequest(BaseModel):
    phone: Optional[str] = Field(None, description="Caller phone in any format — normalized before matching")
    email: Optional[str] = Field(None, description="Contact email — used if phone is absent")
    note_type: Literal["call", "email", "meeting", "sms"]
    subject: Optional[str] = Field(None, max_length=255)
    body: str = Field(..., min_length=1)
    source: str = Field("donna_pa", max_length=50)
    source_ref: Optional[str] = Field(None, max_length=255)
    note_metadata: Optional[dict] = None


class CreateNoteResponse(BaseModel):
    id: int
    matched_customer_id: Optional[str]
    matched_company_name: Optional[str]
    match_key: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


# ============================================================================
# ROUTES
# ============================================================================

@router.post(
    "/notes",
    response_model=CreateNoteResponse,
    dependencies=[Depends(require_api_key)],
    status_code=status.HTTP_201_CREATED,
)
def create_note(payload: CreateNoteRequest, db: Session = Depends(get_db)) -> CreateNoteResponse:
    """
    Log a CRM note (call transcript / email summary / meeting notes) against a
    customer. Caller passes phone OR email; we match and link, otherwise store
    in the 'unmatched' bucket for later triage.
    """
    if not payload.phone and not payload.email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Either phone or email is required",
        )

    match_key, match_key_type = (payload.phone, "phone") if payload.phone else (payload.email, "email")

    customer = None
    if payload.phone:
        customer = _find_customer_by_phone(db, payload.phone)
    if not customer and payload.email:
        customer = db.query(BCCustomer).filter(BCCustomer.email.ilike(payload.email)).first()

    note = CustomerNote(
        bc_customer_id=customer.bc_customer_id if customer else None,
        match_key=match_key,
        match_key_type=match_key_type,
        note_type=payload.note_type,
        subject=payload.subject,
        body=payload.body,
        source=payload.source,
        source_ref=payload.source_ref,
        note_metadata=payload.note_metadata,
    )
    db.add(note)
    db.commit()
    db.refresh(note)

    logger.info(
        "CRM note created: id=%s type=%s customer=%s source=%s",
        note.id, note.note_type, note.bc_customer_id or 'unmatched', note.source,
    )

    return CreateNoteResponse(
        id=note.id,
        matched_customer_id=customer.bc_customer_id if customer else None,
        matched_company_name=customer.company_name if customer else None,
        match_key=match_key,
        created_at=note.created_at,
    )


# ============================================================================
# HELPERS
# ============================================================================

def _normalize_phone(raw: str) -> str:
    """Strip everything except digits. Drop leading '1' (NANP country code) so
    +1 403 555 1234 / 403-555-1234 / (403) 555-1234 all match 4035551234."""
    digits = re.sub(r"\D", "", raw or "")
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    return digits


def _find_customer_by_phone(db: Session, raw_phone: str) -> Optional[BCCustomer]:
    """Match a BCCustomer by normalized phone. Scans BC customers in-memory
    because BC phones are stored in various formats; normalization beats SQL
    LIKE tricks. Fine for a few thousand customers."""
    target = _normalize_phone(raw_phone)
    if len(target) < 7:
        return None

    customers_with_phone = db.query(BCCustomer).filter(BCCustomer.phone.isnot(None)).all()
    for c in customers_with_phone:
        if _normalize_phone(c.phone) == target:
            return c
    return None
