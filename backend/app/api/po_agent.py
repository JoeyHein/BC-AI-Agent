"""
PO Generation Agent API (Admin)
Draft management, approval, rejection, stats.
"""

import logging
from fastapi import APIRouter, Depends, HTTPException, status, Query
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional

from app.db.database import SessionLocal
from app.db.models import User
from app.services.auth_service import auth_service
from app.services.po_agent_service import po_agent_service

router = APIRouter(prefix="/api/admin/po-agent", tags=["po-agent"])
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
    db: Session = Depends(get_db)
) -> User:
    token = credentials.credentials
    payload = auth_service.decode_token(token)
    if not payload:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    if payload.get("user_type") == "customer":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    user = db.query(User).get(int(payload.get("sub")))
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found or inactive")
    return user


class RejectRequest(BaseModel):
    reason: Optional[str] = None


@router.post("/run")
async def run_generation(
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    """Trigger PO generation from demand signals."""
    stats = po_agent_service.run_po_generation(db)
    db.commit()
    return {"success": True, "stats": stats}


@router.get("/drafts")
async def list_drafts(
    status_filter: Optional[str] = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    """List PO drafts."""
    drafts = po_agent_service.get_drafts(db, status_filter=status_filter, skip=skip, limit=limit)
    return {
        "items": [
            {
                "id": d.id,
                "vendor_name": d.vendor_name,
                "vendor_id": d.vendor_id,
                "status": d.status,
                "total_amount": float(d.total_amount) if d.total_amount else None,
                "currency": d.currency,
                "line_items": d.line_items,
                "line_count": len(d.line_items) if d.line_items else 0,
                "bc_po_number": d.bc_po_number,
                "created_at": d.created_at.isoformat() if d.created_at else None,
                "approved_at": d.approved_at.isoformat() if d.approved_at else None,
                "rejected_at": d.rejected_at.isoformat() if d.rejected_at else None,
                "rejection_reason": d.rejection_reason,
            }
            for d in drafts
        ],
        "count": len(drafts),
    }


@router.post("/drafts/{draft_id}/approve")
async def approve_draft(
    draft_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    """Approve a PO draft and submit to BC."""
    try:
        po = po_agent_service.approve_po(db, draft_id, admin.id)
        db.commit()
        return {
            "success": True,
            "po_id": po.id,
            "status": po.status,
            "bc_po_number": po.bc_po_number,
        }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/drafts/{draft_id}/reject")
async def reject_draft(
    draft_id: int,
    body: RejectRequest = None,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    """Reject a PO draft."""
    try:
        reason = body.reason if body else None
        po = po_agent_service.reject_po(db, draft_id, admin.id, reason)
        db.commit()
        return {
            "success": True,
            "po_id": po.id,
            "status": po.status,
        }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/stats")
async def stats(
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    """Approval rate history and stats."""
    return po_agent_service.get_stats(db)
