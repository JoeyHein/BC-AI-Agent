"""Admin list for Upwardor order acknowledgements.

Rows with status 'pending' parsed an S-ORD number but no PO number — they
are not on the Production Schedule until a PO is known. This API does not
send mail. POST /run polls the configured mailboxes; pass dry_run=true to
store rows without writing Vendor Order No. in Business Central.
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from app.db.database import SessionLocal
from app.db.models import User, VendorOrderAck
from app.services.auth_service import auth_service

router = APIRouter(prefix="/api/admin/vendor-acks", tags=["vendor-acks"])
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


def _row_to_dict(row: VendorOrderAck) -> dict:
    return {
        "id": row.id,
        "vendor_no": row.vendor_no,
        "vendor_order_no": row.vendor_order_no,
        "our_po_number": row.our_po_number,
        "our_so_numbers": row.our_so_numbers or [],
        "status": row.status,
        "completion_date": row.completion_date.isoformat() if row.completion_date else None,
        "received_at": row.received_at.isoformat() if row.received_at else None,
        "mailbox": row.mailbox,
        "sender_email": row.sender_email,
        "attachment_filename": row.attachment_filename,
        "bc_po_id": row.bc_po_id,
        "bc_write_status": row.bc_write_status,
        "bc_write_error": row.bc_write_error,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


@router.get("")
async def list_acks(
    status: Optional[str] = Query(
        None, description="confirmed | revised | cancelled | pending | error"
    ),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    """Latest acknowledgement per Upwardor order number. Filter status=pending
    for the unmatched queue (no PO on the PDF or subject)."""
    q = db.query(VendorOrderAck)
    if status:
        q = q.filter(VendorOrderAck.status == status)
    rows = q.order_by(VendorOrderAck.received_at.desc(), VendorOrderAck.id.desc()).limit(limit).all()
    counts = {
        s: db.query(VendorOrderAck).filter(VendorOrderAck.status == s).count()
        for s in ("confirmed", "revised", "cancelled", "pending", "error")
    }
    return {"acknowledgements": [_row_to_dict(r) for r in rows], "counts": counts}


@router.post("/run")
async def run_intake_now(
    dry_run: Optional[bool] = Query(
        None,
        description="true stores rows and skips the BC Vendor Order No. write. "
                    "Omit to follow VENDOR_ACK_DRY_RUN.",
    ),
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    """Poll joey@ and Finance@ now, instead of waiting for the scheduler."""
    from app.services.vendor_ack_intake_service import vendor_ack_intake_service
    return vendor_ack_intake_service.process_new_acks(db, dry_run=dry_run)
