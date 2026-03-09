"""
Catalog Builder & Parts Management API (Admin)
Also handles special order management.
"""

import logging
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, status, Query
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional, List

from app.db.database import SessionLocal
from app.db.models import User, UserRole, Part, SpecialOrderRequest
from app.services.auth_service import auth_service
from app.services.catalog_builder_service import catalog_builder_service

router = APIRouter(prefix="/api/admin/catalog", tags=["catalog-builder"])
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
    """Get current authenticated admin user."""
    token = credentials.credentials
    payload = auth_service.decode_token(token)
    if not payload:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    user_type = payload.get("user_type")
    if user_type == "customer":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    user_id = payload.get("sub")
    user = db.query(User).get(int(user_id))
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found or inactive")
    return user


# ============================================================================
# REQUEST / RESPONSE MODELS
# ============================================================================

class ReviewResolution(BaseModel):
    category: str
    attributes: Optional[dict] = None


class SpecialOrderUpdate(BaseModel):
    status: Optional[str] = None
    admin_notes: Optional[str] = None
    quoted_price: Optional[float] = None
    quoted_lead_time_days: Optional[int] = None


# ============================================================================
# PIPELINE ENDPOINTS
# ============================================================================

@router.post("/run-pipeline")
async def run_pipeline(
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    """Run the full catalog builder pipeline (Extract → Classify → Enrich → Deduplicate → Publish)."""
    stats = catalog_builder_service.run_pipeline(db)
    return {"success": True, "stats": stats}


# ============================================================================
# STAGING ENDPOINTS
# ============================================================================

@router.get("/staging")
async def list_staging(
    run_id: Optional[str] = None,
    processed: Optional[bool] = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    """List staged BC items."""
    items = catalog_builder_service.get_staging_items(db, run_id=run_id, processed=processed, skip=skip, limit=limit)
    return {
        "items": [
            {
                "id": i.id,
                "bc_item_number": i.bc_item_number,
                "bc_description": i.bc_description,
                "bc_unit_cost": float(i.bc_unit_cost) if i.bc_unit_cost else None,
                "is_processed": i.is_processed,
                "classified_category": i.classified_category,
                "enriched_attributes": i.enriched_attributes,
                "processing_notes": i.processing_notes,
                "pipeline_run_id": i.pipeline_run_id,
                "created_at": i.created_at.isoformat() if i.created_at else None,
            }
            for i in items
        ],
        "count": len(items),
    }


# ============================================================================
# REVIEW QUEUE ENDPOINTS
# ============================================================================

@router.get("/review-queue")
async def list_review_queue(
    resolved: Optional[bool] = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    """List items needing review."""
    items = catalog_builder_service.get_review_queue(db, resolved=resolved, skip=skip, limit=limit)
    return {
        "items": [
            {
                "id": i.id,
                "bc_item_number": i.bc_item_number,
                "bc_description": i.bc_description,
                "reason": i.reason,
                "suggested_category": i.suggested_category,
                "is_resolved": i.is_resolved,
                "resolved_category": i.resolved_category,
                "resolved_at": i.resolved_at.isoformat() if i.resolved_at else None,
                "created_at": i.created_at.isoformat() if i.created_at else None,
            }
            for i in items
        ],
        "count": len(items),
    }


@router.post("/review/{review_id}")
async def resolve_review(
    review_id: int,
    body: ReviewResolution,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    """Resolve a review queue item with a category and attributes."""
    try:
        item = catalog_builder_service.resolve_review_item(
            db, review_id, body.category, body.attributes, admin.id
        )
        db.commit()
        return {
            "success": True,
            "id": item.id,
            "resolved_category": item.resolved_category,
        }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ============================================================================
# DUPLICATES ENDPOINTS
# ============================================================================

@router.get("/duplicates")
async def list_duplicates(
    resolved: Optional[bool] = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    """List duplicate candidates."""
    items = catalog_builder_service.get_duplicates(db, resolved=resolved, skip=skip, limit=limit)
    return {
        "items": [
            {
                "id": i.id,
                "item_a_number": i.item_a_number,
                "item_b_number": i.item_b_number,
                "similarity_score": i.similarity_score,
                "match_reasons": i.match_reasons,
                "is_resolved": i.is_resolved,
                "resolution": i.resolution,
                "created_at": i.created_at.isoformat() if i.created_at else None,
            }
            for i in items
        ],
        "count": len(items),
    }


# ============================================================================
# PARTS CATALOG ENDPOINTS (Admin browse)
# ============================================================================

@router.get("/parts")
async def list_parts(
    category: Optional[str] = None,
    status: Optional[str] = None,
    search: Optional[str] = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    """Browse published catalog parts."""
    items = catalog_builder_service.get_parts(db, category=category, status=status, search=search, skip=skip, limit=limit)
    return {
        "items": [_part_to_dict(p) for p in items],
        "count": len(items),
    }


# ============================================================================
# STATS ENDPOINT
# ============================================================================

@router.get("/stats")
async def pipeline_stats(
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    """Pipeline statistics."""
    return catalog_builder_service.get_stats(db)


# ============================================================================
# SPECIAL ORDER MANAGEMENT (Admin)
# ============================================================================

@router.get("/special-orders")
async def list_special_orders(
    status_filter: Optional[str] = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    """List all special order requests."""
    q = db.query(SpecialOrderRequest)
    if status_filter:
        q = q.filter(SpecialOrderRequest.status == status_filter)
    orders = q.order_by(SpecialOrderRequest.created_at.desc()).offset(skip).limit(limit).all()
    return {
        "items": [_special_order_to_dict(o) for o in orders],
        "count": len(orders),
    }


@router.patch("/special-orders/{order_id}")
async def update_special_order(
    order_id: int,
    body: SpecialOrderUpdate,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    """Update a special order (status, notes, quote)."""
    order = db.query(SpecialOrderRequest).get(order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Special order not found")

    if body.status is not None:
        order.status = body.status
    if body.admin_notes is not None:
        order.admin_notes = body.admin_notes
    if body.quoted_price is not None:
        order.quoted_price = body.quoted_price
    if body.quoted_lead_time_days is not None:
        order.quoted_lead_time_days = body.quoted_lead_time_days

    db.commit()
    return {"success": True, "order": _special_order_to_dict(order)}


# ============================================================================
# HELPERS
# ============================================================================

def _part_to_dict(p: Part) -> dict:
    return {
        "id": p.id,
        "bc_item_number": p.bc_item_number,
        "bc_description": p.bc_description,
        "category": p.category,
        "subcategory": p.subcategory,
        "attributes": p.attributes,
        "unit_cost": float(p.unit_cost) if p.unit_cost else None,
        "retail_price": float(p.retail_price) if p.retail_price else None,
        "vendor_name": p.vendor_name,
        "lead_time_days": p.lead_time_days,
        "catalog_status": p.catalog_status,
        "created_at": p.created_at.isoformat() if p.created_at else None,
    }


def _special_order_to_dict(o: SpecialOrderRequest) -> dict:
    return {
        "id": o.id,
        "customer_user_id": o.customer_user_id,
        "bc_customer_id": o.bc_customer_id,
        "wire_diameter": o.wire_diameter,
        "coil_diameter": o.coil_diameter,
        "spring_length": o.spring_length,
        "wind_direction": o.wind_direction,
        "quantity": o.quantity,
        "spring_type": o.spring_type,
        "door_width": o.door_width,
        "door_height": o.door_height,
        "door_weight": o.door_weight,
        "status": o.status,
        "admin_notes": o.admin_notes,
        "quoted_price": float(o.quoted_price) if o.quoted_price else None,
        "quoted_lead_time_days": o.quoted_lead_time_days,
        "created_at": o.created_at.isoformat() if o.created_at else None,
        "updated_at": o.updated_at.isoformat() if o.updated_at else None,
    }
