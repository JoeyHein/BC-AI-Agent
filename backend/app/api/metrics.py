"""
Business Metrics API
Serves dashboard KPIs and customer metrics from Business Central
"""

import logging
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from app.db.database import SessionLocal
from app.db.models import User, UserRole
from app.services.auth_service import auth_service

router = APIRouter(prefix="/api/metrics", tags=["metrics"])
logger = logging.getLogger(__name__)

security = HTTPBearer()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db)
) -> User:
    token = credentials.credentials
    payload = auth_service.decode_token(token)
    if not payload:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    user_id = int(payload.get("sub", 0))
    user = auth_service.get_user_by_id(db, user_id=user_id)
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    return user


def require_viewer(current_user: User = Depends(get_current_user)) -> User:
    """Any authenticated internal user can access metrics."""
    return current_user


def require_reviewer(current_user: User = Depends(get_current_user)) -> User:
    if not auth_service.check_permission(current_user, UserRole.REVIEWER):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Reviewer access required")
    return current_user


def require_admin(current_user: User = Depends(get_current_user)) -> User:
    if not auth_service.check_permission(current_user, UserRole.ADMIN):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    return current_user


# =============================================================================
# EXECUTIVE VIEW — admin only
# =============================================================================

@router.get("/executive")
async def get_executive_metrics(current_user: User = Depends(require_admin)):
    """Executive dashboard: revenue, margin, customers, OTD."""
    try:
        from app.services.bc_metrics_service import bc_metrics_service
        data = bc_metrics_service.get_executive_metrics()
        return {"success": True, "data": data}
    except Exception as e:
        logger.error(f"Executive metrics error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# OPERATIONS VIEW — reviewer+ (admin or reviewer)
# =============================================================================

@router.get("/operations")
async def get_operations_metrics(current_user: User = Depends(require_reviewer)):
    """Operations dashboard: open orders, pipeline, OTD, overdue."""
    try:
        from app.services.bc_metrics_service import bc_metrics_service
        data = bc_metrics_service.get_operations_metrics()
        return {"success": True, "data": data}
    except Exception as e:
        logger.error(f"Operations metrics error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# SHIPPING VIEW — any authenticated user
# =============================================================================

@router.get("/shipping")
async def get_shipping_metrics(current_user: User = Depends(require_viewer)):
    """Shipping dashboard: today's queue, overdue, avg days to ship."""
    try:
        from app.services.bc_metrics_service import bc_metrics_service
        data = bc_metrics_service.get_shipping_metrics()
        return {"success": True, "data": data}
    except Exception as e:
        logger.error(f"Shipping metrics error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# CUSTOMER METRICS — any authenticated user (admin sees all, customers see own)
# =============================================================================

@router.get("/customer/{customer_number}")
async def get_customer_metrics(
    customer_number: str,
    current_user: User = Depends(require_viewer),
):
    """Per-customer metrics: sales, OTD, orders, credit."""
    try:
        from app.services.bc_metrics_service import bc_metrics_service
        data = bc_metrics_service.get_customer_metrics(customer_number)
        return {"success": True, "data": data}
    except Exception as e:
        logger.error(f"Customer metrics error for {customer_number}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
