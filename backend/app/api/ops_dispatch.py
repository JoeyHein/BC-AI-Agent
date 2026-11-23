"""Planning flags, supplier-date changes, customer-update drafts, packing slips.

Scheduled mail and Business Central writes stay off until their flags are
set. POST approve on a packing slip is an explicit send. Customer updates
stay on the order-tracker approval queue and are not sent here.
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.staff_principal import service_user_if_key
from app.db.database import SessionLocal
from app.db.models import PackingSlip, User
from app.services.auth_service import auth_service
from app.services.packing_slip_service import (
    approve_slip,
    list_slips,
    process_recent,
    reject_slip,
    slip_dict,
    update_recipient,
)
from app.services.staff_permissions import enforce_staff_permission
from app.services.supplier_confirmation_service import (
    dispatch_summary,
    ingest_messages,
    process_inbox,
)

router = APIRouter(prefix="/api/admin/ops-dispatch", tags=["ops-dispatch"])
logger = logging.getLogger(__name__)
security = HTTPBearer()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_current_admin(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db),
) -> User:
    service_user = service_user_if_key(request, credentials, db)
    if service_user is not None:
        return service_user
    token = credentials.credentials
    payload = auth_service.decode_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if payload.get("user_type") == "customer":
        raise HTTPException(status_code=403, detail="Admin access required")
    user = db.query(User).get(int(payload.get("sub")))
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="User not found or inactive")
    enforce_staff_permission(request, user)
    return user


class IngestBody(BaseModel):
    messages: list
    write_bc: bool = False


class SlipEmail(BaseModel):
    to_email: Optional[str] = None


@router.get("")
async def summary(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_admin),
):
    payload = dispatch_summary(db)
    payload["packing_slips"] = list_slips(db)
    return payload


@router.post("/supplier-confirmations/run")
async def run_confirmations(
    write_bc: bool = Query(False),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_admin),
):
    """Poll supplier mail. write_bc defaults off and only patches expectedReceiptDate."""
    try:
        result = process_inbox(db, write_bc=write_bc)
    except Exception as exc:
        logger.exception("Supplier confirmation run failed")
        raise HTTPException(status_code=502, detail=str(exc)[:500]) from exc
    return result


@router.post("/supplier-confirmations/ingest")
async def ingest(
    body: IngestBody,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_admin),
):
    """Apply confirmations that were already fetched. Does not send mail."""
    return ingest_messages(db, body.messages, write_bc=body.write_bc)


@router.post("/packing-slips/run")
async def run_packing_slips(
    auto_send: bool = Query(False),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_admin),
):
    """Queue packing slips for recent posted shipments. auto_send defaults off."""
    return process_recent(db, auto_send=auto_send)


@router.get("/packing-slips/{slip_id}/pdf")
async def packing_slip_pdf(
    slip_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_admin),
):
    row = db.query(PackingSlip).filter_by(id=slip_id).one_or_none()
    if row is None or not row.pdf_bytes:
        raise HTTPException(status_code=404, detail="Packing slip not found")
    return Response(
        content=bytes(row.pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{row.shipment_number}.pdf"'},
    )


@router.post("/packing-slips/{slip_id}/approve")
async def approve_packing_slip(
    slip_id: int,
    body: Optional[SlipEmail] = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_admin),
):
    """Send one queued packing slip. This is an explicit send, not the auto-send flag."""
    try:
        row = approve_slip(db, slip_id, to_email=(body.to_email if body else None))
        db.commit()
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Packing slip send failed")
        raise HTTPException(status_code=502, detail=str(exc)[:500]) from exc
    return slip_dict(row)


@router.post("/packing-slips/{slip_id}/reject")
async def reject_packing_slip(
    slip_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_admin),
):
    try:
        row = reject_slip(db, slip_id)
        db.commit()
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return slip_dict(row)


@router.patch("/packing-slips/{slip_id}")
async def patch_packing_slip(
    slip_id: int,
    body: SlipEmail,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_admin),
):
    try:
        row = update_recipient(db, slip_id, body.to_email or "")
        db.commit()
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return slip_dict(row)
