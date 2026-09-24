"""
AI invoice intake — admin review API.

Every row here is a mailbox attachment the AI pipeline already ran through
extraction + matching (see invoice_intake_service). Rows with status
'pending' need a human decision — almost always resolving an unmatched
vendor — before a BC Draft invoice can be created. Rows with status
'created' already have a BC Draft invoice sitting there for normal review/
posting in BC itself; this API's "mark reviewed" is just a local
bookkeeping note, it does not touch BC.
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from sqlalchemy.orm import Session
from datetime import datetime

from sqlalchemy import or_

from app.config import settings
from app.db.database import SessionLocal
from app.db.models import IncomingInvoice, User
from app.services.auth_service import auth_service

router = APIRouter(prefix="/api/admin/invoices", tags=["invoice-intake"])
logger = logging.getLogger(__name__)

security = HTTPBearer()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_current_admin(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db),
) -> User:
    token = credentials.credentials
    payload = auth_service.decode_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if payload.get("user_type") == "customer":
        raise HTTPException(status_code=403, detail="Admin access required")
    user = db.query(User).get(int(payload.get("sub")))
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="User not found or inactive")
    return user


def describe_ai_action(row: IncomingInvoice) -> str:
    """One-line summary of what the AI did for this attachment — used by the
    bookkeeper dashboard activity log."""
    vendor = row.vendor_name_extracted or row.vendor_number or "unknown vendor"
    inv = row.vendor_invoice_number or "no invoice #"
    if row.status == "created":
        draft = row.bc_invoice_number or "Draft"
        if row.match_type == "po":
            return (
                f"Extracted {inv} from {vendor}, matched PO {row.matched_po_number}, "
                f"created BC Draft {draft}"
            )
        if row.match_type == "gl":
            return (
                f"Extracted {inv} from {vendor}, coded GL {row.gl_account_suggested}, "
                f"created BC Draft {draft}"
            )
        return f"Extracted {inv} from {vendor}, created BC Draft {draft}"
    if row.status == "pending":
        flags = ", ".join(row.review_flags or []) or "needs review"
        return f"Extracted {inv} from {vendor}; waiting on bookkeeper ({flags})"
    if row.status == "duplicate_skipped":
        return f"Skipped duplicate {inv} from {vendor} (already in BC or previously created)"
    if row.status == "error":
        return (
            f"Failed processing {row.attachment_filename or 'attachment'}: "
            f"{row.error_message or 'unknown error'}"
        )
    return f"Processed {inv} from {vendor} (status={row.status})"


def pipeline_status() -> dict:
    mailbox = settings.INVOICE_INTAKE_MAILBOX or settings.EMAIL_INBOX_1
    return {
        "enabled": bool(settings.INVOICE_INTAKE_ENABLED),
        "mailbox": mailbox,
        "lookback_hours": int(settings.INVOICE_INTAKE_LOOKBACK_HOURS),
        "poll_interval_minutes": 30,
        "creates_drafts_only": True,
        "posts_to_bc": False,
    }


def _row_to_dict(row: IncomingInvoice, reviewer_name: Optional[str] = None) -> dict:
    received = row.source_email_received_at
    return {
        "id": row.id,
        "source_email_id": row.source_email_id,
        "source_email_received_at": received.isoformat() if received else None,
        "sender_email": row.sender_email,
        "attachment_filename": row.attachment_filename,
        "vendor_number": row.vendor_number,
        "vendor_name_extracted": row.vendor_name_extracted,
        "vendor_invoice_number": row.vendor_invoice_number,
        "invoice_date": row.invoice_date.isoformat() if row.invoice_date else None,
        "due_date": row.due_date.isoformat() if row.due_date else None,
        "total_amount": float(row.total_amount) if row.total_amount is not None else None,
        "currency_code": row.currency_code,
        "match_type": row.match_type,
        "matched_po_number": row.matched_po_number,
        "gl_account_suggested": row.gl_account_suggested,
        "gl_confidence": row.gl_confidence,
        "review_flags": row.review_flags or [],
        "status": row.status,
        "bc_invoice_id": row.bc_invoice_id,
        "bc_invoice_number": row.bc_invoice_number,
        "error_message": row.error_message,
        "reviewed_by_user_id": row.reviewed_by_user_id,
        "reviewed_by_name": reviewer_name,
        "reviewed_at": row.reviewed_at.isoformat() if row.reviewed_at else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "ai_action": describe_ai_action(row),
    }


def _reviewer_names(db: Session, rows) -> dict:
    ids = {r.reviewed_by_user_id for r in rows if r.reviewed_by_user_id}
    if not ids:
        return {}
    users = db.query(User).filter(User.id.in_(ids)).all()
    return {u.id: (u.name or u.email or f"user {u.id}") for u in users}


@router.get("/pipeline")
async def get_pipeline(
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    """Mailbox watch status for the bookkeeper dashboard — not a processed invoice."""
    last = (
        db.query(IncomingInvoice)
        .order_by(IncomingInvoice.created_at.desc())
        .first()
    )
    info = pipeline_status()
    info["last_activity_at"] = last.created_at.isoformat() if last and last.created_at else None
    info["total_processed"] = db.query(IncomingInvoice).count()
    return info


@router.get("")
async def list_invoices(
    status: Optional[str] = Query(None, description="pending | created | duplicate_skipped | error"),
    q: Optional[str] = Query(None, description="Search vendor, invoice #, sender, filename"),
    unreviewed_only: bool = Query(False),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    """List tracked invoices, most recent first. Filter by status — 'pending'
    is the working queue (needs a human decision); everything else is audit
    trail."""
    query = db.query(IncomingInvoice)
    if status:
        query = query.filter(IncomingInvoice.status == status)
    if unreviewed_only:
        query = query.filter(IncomingInvoice.reviewed_at.is_(None))
    if q:
        like = f"%{q.strip()}%"
        query = query.filter(or_(
            IncomingInvoice.vendor_name_extracted.ilike(like),
            IncomingInvoice.vendor_number.ilike(like),
            IncomingInvoice.vendor_invoice_number.ilike(like),
            IncomingInvoice.sender_email.ilike(like),
            IncomingInvoice.attachment_filename.ilike(like),
            IncomingInvoice.bc_invoice_number.ilike(like),
        ))
    rows = query.order_by(IncomingInvoice.created_at.desc()).limit(limit).all()
    names = _reviewer_names(db, rows)
    counts = {
        s: db.query(IncomingInvoice).filter(IncomingInvoice.status == s).count()
        for s in ("pending", "created", "duplicate_skipped", "error")
    }
    counts["unreviewed"] = (
        db.query(IncomingInvoice)
        .filter(IncomingInvoice.reviewed_at.is_(None))
        .filter(IncomingInvoice.status.in_(("pending", "created", "error")))
        .count()
    )
    last = (
        db.query(IncomingInvoice)
        .order_by(IncomingInvoice.created_at.desc())
        .first()
    )
    pipe = pipeline_status()
    pipe["last_activity_at"] = last.created_at.isoformat() if last and last.created_at else None
    pipe["total_processed"] = sum(counts[s] for s in ("pending", "created", "duplicate_skipped", "error"))
    return {
        "invoices": [_row_to_dict(r, names.get(r.reviewed_by_user_id)) for r in rows],
        "counts": counts,
        "pipeline": pipe,
    }


@router.get("/{invoice_id}")
async def get_invoice(
    invoice_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    """Full detail for one row, including the raw Claude extraction (line
    items, confidence per field, parsing notes) — not included in the list
    view since it's the heaviest field."""
    row = db.query(IncomingInvoice).get(invoice_id)
    if not row:
        raise HTTPException(status_code=404, detail="Invoice not found")
    names = _reviewer_names(db, [row])
    detail = _row_to_dict(row, names.get(row.reviewed_by_user_id))
    detail["extracted_json"] = row.extracted_json
    return detail


class RunRequest(BaseModel):
    pass


@router.post("/run")
async def run_intake_now(
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    """Manually trigger a mailbox check now, instead of waiting for the
    30-minute scheduled job."""
    from app.services.invoice_intake_service import invoice_intake_service
    result = invoice_intake_service.process_new_invoices(db)
    return result


class ResolveVendorRequest(BaseModel):
    vendor_number: str


@router.post("/{invoice_id}/resolve-vendor")
async def resolve_vendor(
    invoice_id: int,
    body: ResolveVendorRequest,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    """Manually assign the correct BC vendor to a 'pending' row (the most
    common reason a row is stuck — sender email/name didn't match any BC
    vendor) and re-run matching + BC draft creation from the already-
    extracted data. No re-download, no re-extraction."""
    from app.services.invoice_intake_service import invoice_intake_service
    result = invoice_intake_service.resolve_pending(db, invoice_id, body.vendor_number)
    if not result.get("success") and "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.post("/{invoice_id}/mark-reviewed")
async def mark_reviewed(
    invoice_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    """Local acknowledgement that a human looked at this row — does not
    touch BC. Use this to track which Drafts (or flagged/errored rows)
    someone has already checked, separate from BC's own posting workflow."""
    row = db.query(IncomingInvoice).get(invoice_id)
    if not row:
        raise HTTPException(status_code=404, detail="Invoice not found")
    row.reviewed_by_user_id = admin.id
    row.reviewed_at = datetime.utcnow()
    db.add(row)
    db.commit()
    return {"success": True}
