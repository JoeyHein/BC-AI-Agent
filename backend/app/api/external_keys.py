"""
External API key management (SQB-03).

Admin-only endpoints for creating, listing, revoking, and rotating
the keys that gate the `/api/external/*` surface that Service.AI
calls into.

Plaintext is shown ONCE on create + rotate. Subsequent GETs return
the prefix only — there is no path to recover a plaintext from the
database.

Routes:
    POST   /api/external-keys            create
    GET    /api/external-keys            list
    GET    /api/external-keys/{id}       read
    POST   /api/external-keys/{id}/revoke
    POST   /api/external-keys/{id}/rotate
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.auth import get_db, require_admin
from app.db.models import ExternalApiKey, User
from app.services.external_api_keys_service import (
    create_key,
    revoke_key,
    rotate_key,
)

router = APIRouter(prefix="/api/external-keys", tags=["external-keys"])
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class ExternalApiKeyOut(BaseModel):
    """Public read shape — no plaintext, no hash."""

    id: int
    name: str
    key_prefix: str
    supplier_account_code: str
    status: str
    rate_limit_rpm: int
    notes: Optional[str] = None
    created_by_user_id: Optional[int] = None
    last_used_at: Optional[datetime] = None
    revoked_at: Optional[datetime] = None
    revoked_by_user_id: Optional[int] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ExternalApiKeyCreatedOut(ExternalApiKeyOut):
    """Returned ONCE on POST / rotate. `plaintext` is unrecoverable
    after the response leaves this handler."""

    plaintext: str = Field(
        ...,
        description=(
            "The full API key plaintext. Shown ONCE — store it now; "
            "the server cannot show it again."
        ),
    )


class CreateExternalApiKeyIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    supplier_account_code: str = Field(min_length=1, max_length=80)
    rate_limit_rpm: int = Field(default=600, ge=1, le=60_000)
    notes: Optional[str] = Field(default=None, max_length=2000)
    environment: str = Field(default="live", pattern=r"^(live|test)$")


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post(
    "",
    response_model=ExternalApiKeyCreatedOut,
    status_code=status.HTTP_201_CREATED,
)
def create_external_api_key(
    payload: CreateExternalApiKeyIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> ExternalApiKeyCreatedOut:
    """Create a new external API key. Returns the plaintext ONCE."""
    row, plaintext = create_key(
        db,
        name=payload.name,
        supplier_account_code=payload.supplier_account_code,
        rate_limit_rpm=payload.rate_limit_rpm,
        notes=payload.notes,
        created_by_user_id=current_user.id,
        environment=payload.environment,
    )
    logger.info(
        "External API key created: id=%s name=%s account=%s by user=%s",
        row.id, row.name, row.supplier_account_code, current_user.id,
    )
    out = ExternalApiKeyOut.model_validate(row).model_dump()
    return ExternalApiKeyCreatedOut(**out, plaintext=plaintext)


@router.get("", response_model=List[ExternalApiKeyOut])
def list_external_api_keys(
    status_filter: Optional[str] = Query(default=None, alias="status"),
    supplier_account_code: Optional[str] = None,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> List[ExternalApiKeyOut]:
    """List keys. Filter by status ('active' / 'revoked') and/or
    supplier_account_code."""
    q = db.query(ExternalApiKey)
    if status_filter:
        if status_filter not in ("active", "revoked"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="status filter must be 'active' or 'revoked'",
            )
        q = q.filter(ExternalApiKey.status == status_filter)
    if supplier_account_code:
        q = q.filter(ExternalApiKey.supplier_account_code == supplier_account_code)
    rows = q.order_by(ExternalApiKey.created_at.desc()).all()
    return [ExternalApiKeyOut.model_validate(r) for r in rows]


@router.get("/{key_id}", response_model=ExternalApiKeyOut)
def get_external_api_key(
    key_id: int,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> ExternalApiKeyOut:
    row = db.query(ExternalApiKey).filter(ExternalApiKey.id == key_id).first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Key not found")
    return ExternalApiKeyOut.model_validate(row)


@router.post("/{key_id}/revoke", response_model=ExternalApiKeyOut)
def revoke_external_api_key(
    key_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> ExternalApiKeyOut:
    """Mark a key revoked. Idempotent — re-revoking returns the same row."""
    row = revoke_key(db, key_id=key_id, revoked_by_user_id=current_user.id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Key not found")
    logger.info(
        "External API key revoked: id=%s by user=%s",
        row.id, current_user.id,
    )
    return ExternalApiKeyOut.model_validate(row)


@router.post("/{key_id}/rotate", response_model=ExternalApiKeyCreatedOut)
def rotate_external_api_key(
    key_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> ExternalApiKeyCreatedOut:
    """Rotate a key: revokes the old row and returns a new plaintext
    on a freshly-active row inheriting the same name / account /
    rate limit."""
    result = rotate_key(db, key_id=key_id, rotated_by_user_id=current_user.id)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Key not found")
    _old, new_row, plaintext = result
    logger.info(
        "External API key rotated: old_id=%s new_id=%s by user=%s",
        _old.id, new_row.id, current_user.id,
    )
    out = ExternalApiKeyOut.model_validate(new_row).model_dump()
    return ExternalApiKeyCreatedOut(**out, plaintext=plaintext)
