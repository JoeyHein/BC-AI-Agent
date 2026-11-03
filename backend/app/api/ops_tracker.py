"""Internal order tracker, to-do list, and approval queue.

Nothing on these routes sends email except POST /messages/{id}/approve.
Supplier reminders and customer production updates stay pending until that
click. GET /weekly-summary is the feed for the weekly ops review: lead time
by supplier, acknowledgement turnaround, late orders, and how many customer
updates were drafted or sent.

If Outlook is not configured, `mail.available` is false and `mail.reason`
says what is missing. POST /inbox accepts the same message shape so the
to-do list can still be fed.
"""

import logging
from datetime import date, datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.staff_principal import service_user_if_key
from app.db.database import SessionLocal
from app.db.models import User
from app.integrations.bc.client import bc_client
from app.integrations.email.client import graph_client
from app.services.auth_service import auth_service
from app.services.ops_tracker_service import (
    Actor,
    OpsTrackerError,
    apply_snapshot,
    approve_message,
    complete_action,
    create_follow_up,
    default_sender,
    feed_mail,
    list_actions,
    list_audit,
    list_messages,
    list_tracker,
    patch_line,
    patch_order,
    patch_po,
    reject_message,
    run_sync,
    update_message,
    weekly_summary,
)
from app.services.staff_permissions import enforce_staff_permission

router = APIRouter(prefix="/api/ops", tags=["ops-tracker"])
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
    payload = auth_service.decode_token(credentials.credentials)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if payload.get("user_type") == "customer":
        raise HTTPException(status_code=403, detail="Admin access required")
    user = db.query(User).get(int(payload.get("sub")))
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="User not found or inactive")
    enforce_staff_permission(request, user)
    return user


def _actor(user: User) -> Actor:
    return Actor(user_id=user.id, email=user.email, source="portal")


def _run(db: Session, fn):
    try:
        result = fn()
        db.commit()
        return result
    except OpsTrackerError as exc:
        if exc.status != 502:
            db.rollback()
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc


class OrderPatch(BaseModel):
    fulfillment: Optional[str] = None
    order_status: Optional[str] = None
    expected_receipt: Optional[str] = None
    use_supplier_date: bool = False
    operators: Optional[str] = None
    window_kits: Optional[str] = None
    emergency_build: Optional[str] = None
    shipping_status: Optional[str] = None
    notes: Optional[str] = None
    customer_email: Optional[str] = None


class LinePatch(BaseModel):
    source_code: Optional[str] = None
    source_label: Optional[str] = None
    linked_po_number: Optional[str] = None
    ack_status: Optional[str] = None
    expected_date: Optional[str] = None
    use_supplier_date: bool = False
    notes: Optional[str] = None


class PoPatch(BaseModel):
    notes: Optional[str] = None
    vendor_email: Optional[str] = None


class FollowUpBody(BaseModel):
    title: str
    detail: Optional[str] = None
    so_number: Optional[str] = None
    po_number: Optional[str] = None
    due_on: Optional[str] = None


class MessagePatch(BaseModel):
    to_email: Optional[str] = None
    subject: Optional[str] = None
    body_text: Optional[str] = None


class IngestBody(BaseModel):
    orders: list = Field(default_factory=list)
    purchase_orders: Optional[list] = None
    vendors: list = Field(default_factory=list)
    acks: list = Field(default_factory=list)
    receipts: list = Field(default_factory=list)
    emails: Optional[dict] = None
    allow_empty: bool = False


class InboxBody(BaseModel):
    inbox: list = Field(default_factory=list)
    sent: list = Field(default_factory=list)
    available: bool = True
    reason: Optional[str] = None
    mailbox: Optional[str] = None


def _present(model: BaseModel) -> dict:
    return {key: value for key, value in model.model_dump().items() if key in model.model_fields_set}


@router.get("/tracker")
async def get_tracker(
    customer: Optional[str] = None,
    status: Optional[str] = None,
    supplier: Optional[str] = None,
    at_risk: bool = False,
    q: Optional[str] = None,
    include_closed: bool = False,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_admin),
):
    return _run(db, lambda: list_tracker(
        db,
        customer=customer,
        status=status,
        supplier=supplier,
        at_risk=at_risk,
        q=q,
        include_closed=include_closed,
    ))


@router.post("/sync")
async def sync_tracker(
    allow_empty: bool = Query(False),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_admin),
):
    """Pull open sales orders, purchase orders, receipts, acks, and mailbox.

    Refuses to mark every order closed if Business Central returns an empty
    list, unless allow_empty is set. Does not send email.
    """
    def _go():
        try:
            return run_sync(db, bc_client, graph_client, actor=_actor(user), allow_empty=allow_empty)
        except OpsTrackerError:
            raise
        except Exception as exc:
            logger.exception("Order tracker sync failed")
            raise OpsTrackerError(f"Business Central sync failed: {exc}", status=503) from exc

    return _run(db, _go)


@router.post("/ingest")
async def ingest_snapshot(
    body: IngestBody,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_admin),
):
    """Apply a snapshot without calling Business Central. Used to seed and to test."""
    snapshot: dict[str, Any] = {
        "orders": body.orders,
        "vendors": body.vendors,
        "acks": body.acks,
        "receipts": body.receipts,
    }
    if body.purchase_orders is not None:
        snapshot["purchase_orders"] = body.purchase_orders
    if body.emails is not None:
        snapshot["emails"] = body.emails
    return _run(db, lambda: apply_snapshot(db, snapshot, actor=_actor(user), allow_empty=body.allow_empty))


@router.patch("/tracker/orders/{so_number}")
async def update_order(
    so_number: str,
    body: OrderPatch,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_admin),
):
    return _run(db, lambda: patch_order(db, so_number, _present(body), _actor(user)))


@router.patch("/tracker/lines/{line_id}")
async def update_line(
    line_id: int,
    body: LinePatch,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_admin),
):
    return _run(db, lambda: patch_line(db, line_id, _present(body), _actor(user)))


@router.patch("/tracker/pos/{po_number}")
async def update_po(
    po_number: str,
    body: PoPatch,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_admin),
):
    return _run(db, lambda: patch_po(db, po_number, _present(body), _actor(user)))


@router.get("/tracker/orders/{so_number}/audit")
async def order_audit(
    so_number: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_admin),
):
    return list_audit(db, so_number)


@router.get("/actions")
async def get_actions(
    status: str = "open",
    db: Session = Depends(get_db),
    user: User = Depends(get_current_admin),
):
    return _run(db, lambda: list_actions(db, status=status))


@router.post("/actions")
async def post_follow_up(
    body: FollowUpBody,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_admin),
):
    return _run(db, lambda: create_follow_up(db, body.model_dump(), _actor(user)))


@router.post("/actions/{action_id}/done")
async def done_action(
    action_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_admin),
):
    return _run(db, lambda: complete_action(db, action_id, _actor(user)))


@router.post("/inbox")
async def post_inbox(
    body: InboxBody,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_admin),
):
    """Feed messages that need a reply when Graph Mail.Read is not available."""
    return _run(db, lambda: feed_mail(db, body.model_dump()))


@router.get("/messages")
async def get_messages(
    status: Optional[str] = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_admin),
):
    return list_messages(db, status=status)


@router.patch("/messages/{message_id}")
async def edit_message(
    message_id: int,
    body: MessagePatch,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_admin),
):
    return _run(db, lambda: update_message(db, message_id, _present(body), _actor(user)))


@router.post("/messages/{message_id}/approve")
async def approve(
    message_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_admin),
):
    """Send one queued email. This is the only route that sends mail."""
    return _run(db, lambda: approve_message(db, message_id, _actor(user), default_sender))


@router.post("/messages/{message_id}/reject")
async def reject(
    message_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_admin),
):
    return _run(db, lambda: reject_message(db, message_id, _actor(user)))


@router.get("/weekly-summary")
async def get_weekly_summary(
    as_of: Optional[str] = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_admin),
):
    """Ops review numbers. `as_of` is an ISO date; the week is Monday–Sunday."""
    day = date.today()
    if as_of:
        try:
            day = datetime.fromisoformat(as_of).date()
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="as_of must be an ISO date.") from exc
    return weekly_summary(db, day)
