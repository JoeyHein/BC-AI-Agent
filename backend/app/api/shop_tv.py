"""Shop TV board routes.

The flag defaults to off. While it is off, the board and the nav probe
are 404. A cast URL uses a kiosk token (query ``kiosk`` or header
``X-Shop-Tv-Token``). A staff login with production or sales-order access
can open the same read. Settings, including revoke, require users.manage
and never accept the kiosk token.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.staff_principal import require_staff
from app.db.database import get_db
from app.db.models import User
from app.services.auth_service import auth_service
from app.services.shop_tv_board import (
    MAPPING_NOTES,
    assemble_board,
    board_enabled,
    lane_config,
    save_lane_config,
    set_board_mode,
)
from app.services.shop_tv_incoming import (
    EMAIL_FLAG,
    INCOMING_FLAG,
    accept_review,
    email_matching_enabled,
    incoming_enabled,
    list_reviews,
    reject_review,
    set_flag,
)
from app.services.shop_tv_kiosk import (
    authenticate,
    create_token,
    list_tokens,
    public_row,
    revoke_token,
)
from app.services.staff_permissions import has_permission

router = APIRouter(prefix="/api/shop-tv", tags=["shop-tv"])


class ShopTvSettingsIn(BaseModel):
    mode: str = Field(..., description="off or on")
    pickup_shipment_methods: list[str] = Field(default_factory=list)
    delivery_shipment_methods: list[str] = Field(default_factory=list)
    pickup_shipping_agents: list[str] = Field(default_factory=list)
    delivery_shipping_agents: list[str] = Field(default_factory=list)
    shipping_agent_means_delivery: bool = False
    incoming_mode: Optional[str] = None
    email_matching_mode: Optional[str] = None


class KioskTokenIn(BaseModel):
    name: str


class IncomingFixIn(BaseModel):
    po_number: str


def _presented_kiosk_token(request: Request) -> str:
    header = (request.headers.get("x-shop-tv-token") or "").strip()
    query = (request.query_params.get("kiosk") or "").strip()
    if header or query:
        return header or query
    bearer = request.headers.get("authorization") or ""
    if bearer.lower().startswith("bearer "):
        token = bearer[7:].strip()
        if token.startswith("stv_"):
            return token
    return ""


def _staff_bearer(request: Request) -> str:
    bearer = request.headers.get("authorization") or ""
    if not bearer.lower().startswith("bearer "):
        return ""
    token = bearer[7:].strip()
    if token.startswith("stv_"):
        return ""
    return token


def _require_board_reader(request: Request, db: Session) -> None:
    """Kiosk token or a staff login that can see production or sales orders."""
    kiosk = _presented_kiosk_token(request)
    if kiosk:
        decision = authenticate(db, kiosk)
        if decision == "ok":
            return
        if decision == "revoked":
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Kiosk token revoked")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid kiosk token",
        )

    token = _staff_bearer(request)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    payload = auth_service.decode_token(token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
        )
    if payload.get("user_type") == "customer":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Staff access required")
    try:
        user_id = int(payload.get("sub"))
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
        )
    user = auth_service.get_user_by_id(db, user_id=user_id)
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
        )
    if (getattr(user, "user_type", None) or "").upper() == "CUSTOMER":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Staff access required")
    if not (
        has_permission(user, "production.view")
        or has_permission(user, "sales_orders.view")
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to do that",
        )


def _require_flag(db: Session) -> None:
    if not board_enabled(db):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")


@router.get("/enabled")
def shop_tv_enabled(request: Request, db: Session = Depends(get_db)):
    """Nav probe. 404 while the flag is off, so the link stays hidden."""
    _require_flag(db)
    _require_board_reader(request, db)
    return {"enabled": True}


@router.get("/board")
def shop_tv_board(request: Request, db: Session = Depends(get_db)):
    """The board. Read-only. 404 while the flag is off."""
    _require_flag(db)
    _require_board_reader(request, db)
    from app.services.shop_tv_incoming import attach_incoming
    return attach_incoming(db, assemble_board(db))


@router.get("/settings")
def shop_tv_settings(
    db: Session = Depends(get_db),
    _current_user: User = Depends(require_staff),
):
    config = lane_config(db)
    return {
        "mode": "on" if board_enabled(db) else "off",
        "pickup_shipment_methods": config["pickup_shipment_methods"],
        "delivery_shipment_methods": config["delivery_shipment_methods"],
        "pickup_shipping_agents": config["pickup_shipping_agents"],
        "delivery_shipping_agents": config["delivery_shipping_agents"],
        "shipping_agent_means_delivery": config["shipping_agent_means_delivery"],
        "outlook_calendar_enabled": config["outlook_calendar_enabled"],
        "incoming_mode": "on" if incoming_enabled(db) else "off",
        "email_matching_mode": "on" if email_matching_enabled(db) else "off",
        "incoming_reviews": list_reviews(db) if incoming_enabled(db) else [],
        "mapping": MAPPING_NOTES,
        "tokens": [public_row(row) for row in list_tokens(db)],
    }


@router.put("/settings")
def update_shop_tv_settings(
    body: ShopTvSettingsIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_staff),
):
    try:
        mode = set_board_mode(db, body.mode, user_id=current_user.id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    config = save_lane_config(db, body.model_dump(), user_id=current_user.id)
    if body.incoming_mode is not None:
        set_flag(db, INCOMING_FLAG, body.incoming_mode, user_id=current_user.id)
    if body.email_matching_mode is not None:
        set_flag(db, EMAIL_FLAG, body.email_matching_mode, user_id=current_user.id)
    return {"mode": mode, **{key: config[key] for key in (
        "pickup_shipment_methods",
        "delivery_shipment_methods",
        "pickup_shipping_agents",
        "delivery_shipping_agents",
        "shipping_agent_means_delivery",
        "outlook_calendar_enabled",
    )}}


@router.post("/kiosk-tokens", status_code=status.HTTP_201_CREATED)
def create_kiosk_token(
    body: KioskTokenIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_staff),
):
    try:
        row, plaintext = create_token(db, name=body.name, created_by_user_id=current_user.id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    payload = public_row(row)
    payload["token"] = plaintext
    payload["path"] = f"/shop-tv?kiosk={plaintext}"
    return payload


@router.post("/kiosk-tokens/{token_id}/revoke")
def revoke_kiosk_token(
    token_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_staff),
):
    row = revoke_token(db, token_id=token_id, revoked_by_user_id=current_user.id)
    if row is None:
        raise HTTPException(status_code=404, detail="Kiosk token not found")
    return public_row(row)


def _require_incoming(db: Session) -> None:
    if not incoming_enabled(db):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")


@router.get("/incoming")
def shop_tv_incoming(request: Request, db: Session = Depends(get_db)):
    """Incoming lane only. 404 while shop_tv_incoming is off, with no PO rows."""
    _require_incoming(db)
    _require_board_reader(request, db)
    from app.services.shop_tv_incoming import attach_incoming
    payload = attach_incoming(db, {"lanes": {}, "horizon_days": 7})
    return payload["lanes"]["incoming"]


@router.get("/incoming/reviews")
def shop_tv_incoming_reviews(
    db: Session = Depends(get_db),
    _current_user: User = Depends(require_staff),
):
    _require_incoming(db)
    return list_reviews(db)


@router.post("/incoming/reviews/{review_id}/accept")
def shop_tv_accept_review(
    review_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_staff),
):
    del current_user
    _require_incoming(db)
    from app.services.shop_tv_incoming import load_purchase_orders
    try:
        purchase_orders = load_purchase_orders()
    except Exception:
        purchase_orders = []
    result = accept_review(db, review_id, purchase_orders=purchase_orders)
    if not result.get("ok"):
        raise HTTPException(status_code=404, detail=result.get("reason") or "Review not found")
    return result


@router.post("/incoming/reviews/{review_id}/fix")
def shop_tv_fix_review(
    review_id: int,
    body: IncomingFixIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_staff),
):
    del current_user
    _require_incoming(db)
    from app.services.shop_tv_incoming import load_purchase_orders
    try:
        purchase_orders = load_purchase_orders()
    except Exception:
        purchase_orders = []
    result = accept_review(db, review_id, po_number=body.po_number, purchase_orders=purchase_orders)
    if not result.get("ok"):
        raise HTTPException(status_code=422, detail=result.get("reason") or "Could not match that PO")
    return result


@router.post("/incoming/reviews/{review_id}/reject")
def shop_tv_reject_review(
    review_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_staff),
):
    del current_user
    _require_incoming(db)
    result = reject_review(db, review_id)
    if not result.get("ok"):
        raise HTTPException(status_code=404, detail=result.get("reason") or "Review not found")
    return result
