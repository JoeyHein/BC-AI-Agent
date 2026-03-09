"""
Inventory Review Agent API (Admin)
Manual triggers, signal viewing, dashboard.
"""

import logging
from fastapi import APIRouter, Depends, HTTPException, status, Query
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from typing import Optional

from app.db.database import SessionLocal
from app.db.models import User
from app.services.auth_service import auth_service
from app.services.inventory_review_service import inventory_review_service

router = APIRouter(prefix="/api/admin/inventory-agent", tags=["inventory-agent"])
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


@router.post("/run")
async def run_review(
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    """Manually trigger inventory review."""
    stats = inventory_review_service.run_review(db)
    db.commit()
    return {"success": True, "stats": stats}


@router.get("/signals")
async def list_signals(
    acknowledged: Optional[bool] = None,
    signal_type: Optional[str] = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    """List demand signals."""
    signals = inventory_review_service.get_signals(
        db, acknowledged=acknowledged, signal_type=signal_type, skip=skip, limit=limit
    )
    return {
        "items": [
            {
                "id": s.id,
                "bc_item_number": s.bc_item_number,
                "signal_type": s.signal_type,
                "severity": s.severity,
                "current_stock": s.current_stock,
                "reorder_point": s.reorder_point,
                "avg_daily_demand": s.avg_daily_demand,
                "days_of_stock": s.days_of_stock,
                "recommended_qty": s.recommended_qty,
                "recommended_vendor": s.recommended_vendor,
                "estimated_lead_time_days": s.estimated_lead_time_days,
                "is_acknowledged": s.is_acknowledged,
                "created_at": s.created_at.isoformat() if s.created_at else None,
            }
            for s in signals
        ],
        "count": len(signals),
    }


@router.get("/dashboard")
async def dashboard(
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    """Stock position overview."""
    return inventory_review_service.get_dashboard(db)


@router.post("/signals/{signal_id}/ack")
async def acknowledge_signal(
    signal_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    """Acknowledge a demand signal."""
    try:
        signal = inventory_review_service.acknowledge_signal(db, signal_id, admin.id)
        db.commit()
        return {"success": True, "signal_id": signal.id}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
