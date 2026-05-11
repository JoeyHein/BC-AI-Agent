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

# =============================================================================
# QUOTING ANALYTICS — reviewer+ (admin or reviewer)
# =============================================================================

@router.get("/quoting")
async def get_quoting_analytics(
    days: int = 30,
    current_user: User = Depends(require_reviewer),
):
    """Quoting pipeline analytics: conversion, aging, volume, items."""
    try:
        from app.services.quoting_analytics_service import quoting_analytics_service
        data = quoting_analytics_service.get_quoting_analytics(days=days)
        return {"success": True, "data": data}
    except Exception as e:
        logger.error(f"Quoting analytics error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# ORDER AGE TRACKER — reviewer+
# =============================================================================

@router.get("/sales-analytics")
async def get_sales_analytics(
    period: str = "12m",
    compare: str = "prior",
    current_user: User = Depends(require_reviewer),
):
    """Sales analytics dashboard: KPIs, monthly trend, quarterly summary,
    top customers — sourced from BC PostedSalesInvoices.

    period: this_month | last_month | this_quarter | last_quarter |
            ytd | 12m | 24m
    compare: prior (immediately preceding window) | year_ago (same
             window shifted back one year)
    """
    try:
        from app.services.sales_analytics_service import get_sales_analytics as _get
        data = _get(period=period, compare=compare)
        return {"success": True, "data": data}
    except Exception as e:
        logger.error(f"Sales analytics error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/order-age")
async def get_order_age(
    lookback_days: int = 90,
    current_user: User = Depends(require_reviewer),
    db: Session = Depends(get_db),
):
    """Open-order aging + delivery success rate buckets for the team dashboard."""
    try:
        from app.services.order_age_service import get_order_age_metrics
        data = get_order_age_metrics(db, success_lookback_days=lookback_days)
        return {"success": True, "data": data}
    except Exception as e:
        logger.error(f"Order age metrics error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


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
