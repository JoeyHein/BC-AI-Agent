"""Admin endpoints for staff service API keys.

    POST   /api/admin/service-keys          create (plaintext returned once)
    GET    /api/admin/service-keys          list (no secret, no hash)
    POST   /api/admin/service-keys/{id}/revoke
    GET    /api/admin/service-keys/audit    recent usage

These routes require a person's admin JWT. A service key cannot manage keys.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.auth import get_db, require_admin
from app.db.models import StaffServiceKey, StaffServiceKeyAudit, User
from app.services.staff_service_keys_service import (
    AUTOMATION_SCOPES,
    create_key,
    revoke_key,
)

router = APIRouter(prefix="/api/admin/service-keys", tags=["staff-service-keys"])
logger = logging.getLogger(__name__)


class StaffServiceKeyOut(BaseModel):
    id: int
    name: str
    key_prefix: str
    scopes: list
    status: str
    created_by_user_id: Optional[int] = None
    created_at: datetime
    last_used_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    revoked_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class StaffServiceKeyCreatedOut(StaffServiceKeyOut):
    plaintext: str = Field(
        ...,
        description="The full key. Shown once. The server cannot show it again.",
    )


class CreateStaffServiceKeyIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    # Omit to grant the automation preset (the hourly PO job's allow-list).
    scopes: Optional[List[str]] = None
    expires_at: Optional[datetime] = None


class StaffServiceKeyAuditOut(BaseModel):
    id: int
    key_id: Optional[int] = None
    key_name: Optional[str] = None
    key_prefix: Optional[str] = None
    method: str
    path: str
    decision: str
    status_code: int
    created_at: datetime

    class Config:
        from_attributes = True


@router.post("", response_model=StaffServiceKeyCreatedOut, status_code=status.HTTP_201_CREATED)
def create_staff_service_key(
    payload: CreateStaffServiceKeyIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> StaffServiceKeyCreatedOut:
    """Create a key. The plaintext is in this response only."""
    try:
        row, plaintext = create_key(
            db,
            name=payload.name,
            scopes=payload.scopes,
            expires_at=payload.expires_at,
            created_by_user_id=current_user.id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    logger.info(
        "Staff service key created: id=%s name=%s by user=%s scopes=%s",
        row.id,
        row.name,
        current_user.id,
        row.scopes,
    )
    out = StaffServiceKeyOut.model_validate(row).model_dump()
    return StaffServiceKeyCreatedOut(**out, plaintext=plaintext)


@router.get("", response_model=List[StaffServiceKeyOut])
def list_staff_service_keys(
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> List[StaffServiceKeyOut]:
    rows = db.query(StaffServiceKey).order_by(StaffServiceKey.created_at.desc()).all()
    return [StaffServiceKeyOut.model_validate(row) for row in rows]


@router.get("/audit", response_model=List[StaffServiceKeyAuditOut])
def list_staff_service_key_audit(
    key_id: Optional[int] = None,
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> List[StaffServiceKeyAuditOut]:
    """Recent service-key calls: key name, route, and time."""
    query = db.query(StaffServiceKeyAudit)
    if key_id is not None:
        query = query.filter(StaffServiceKeyAudit.key_id == key_id)
    rows = query.order_by(StaffServiceKeyAudit.created_at.desc()).limit(limit).all()
    return [StaffServiceKeyAuditOut.model_validate(row) for row in rows]


@router.post("/{key_id}/revoke", response_model=StaffServiceKeyOut)
def revoke_staff_service_key(
    key_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> StaffServiceKeyOut:
    """Revoke a key. The next request with that key is rejected."""
    row = revoke_key(db, key_id=key_id, revoked_by_user_id=current_user.id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Key not found")
    logger.info("Staff service key revoked: id=%s by user=%s", row.id, current_user.id)
    return StaffServiceKeyOut.model_validate(row)


@router.get("/scopes")
def list_staff_service_key_scopes(
    _admin: User = Depends(require_admin),
) -> dict:
    """Scope names an admin can assign. ``automation`` grants all of them."""
    return {"automation": AUTOMATION_SCOPES, "scopes": AUTOMATION_SCOPES}
