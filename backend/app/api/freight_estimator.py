"""Ship-weight and Manitoulin freight estimate.

Read routes 404 while ``freight_estimator`` is off. The settings route stays
available so the switch can be turned on. This router never writes to
Business Central.
"""
from __future__ import annotations

import logging
import math
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.api.staff_principal import service_user_if_key
from app.db.database import SessionLocal
from app.db.models import User
from app.services.auth_service import auth_service
from app.services.freight_estimator_service import SIGNED_NOTE, estimate_freight
from app.services.freight_estimator_settings import (
    freight_estimator_config,
    freight_estimator_enabled,
    freight_estimator_mode,
    set_freight_estimator_config,
    set_freight_estimator_mode,
)
from app.services.manitoulin_rate_table import DESTINATIONS, ORIGINS
from app.services.ship_weight_service import load_constants
from app.services.staff_permissions import enforce_staff_permission

router = APIRouter(prefix="/api/freight-estimator", tags=["freight-estimator"])
logger = logging.getLogger(__name__)
security = HTTPBearer()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db),
) -> User:
    service_user = service_user_if_key(request, credentials, db)
    if service_user is not None:
        return service_user
    payload = auth_service.decode_token(credentials.credentials)
    if not payload:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    user = auth_service.get_user_by_id(db, user_id=int(payload.get("sub", 0)))
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    enforce_staff_permission(request, user)
    return user


def _require_on(db: Session) -> None:
    if not freight_estimator_enabled(db):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")


class FreightSettingsUpdate(BaseModel):
    mode: Optional[str] = None
    fuel_percent: Optional[float] = None
    long_charge: Optional[float] = None
    long_min_length_in: Optional[float] = None
    density_lb_per_cuft: Optional[float] = None
    gst_percent: Optional[float] = None
    crate: Optional[Dict[str, Any]] = None
    operator_lb: Optional[Dict[str, float]] = None
    shaft_lb_per_ft: Optional[Dict[str, float]] = None
    drum_lb_each: Optional[Dict[str, float]] = None
    bearing_lb_each: Optional[float] = None
    winding_cone_lb_each: Optional[float] = None
    stationary_cone_lb_each: Optional[float] = None
    coupler_lb_each: Optional[float] = None


class EstimateRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    origin: str = "redcliff"
    destination: str
    fuel_percent: Optional[float] = None
    long_charge: Optional[float] = None
    long_min_length_in: Optional[float] = None
    density_lb_per_cuft: Optional[float] = None
    doors: List[Dict[str, Any]] = Field(default_factory=list)
    skids: List[Dict[str, Any]] = Field(default_factory=list)


MAX_DOOR_LINES = 100
MAX_DOOR_QTY = 50
MAX_SKIDS = 100


def _check_number(name: str, value: Optional[float], *, low: float, high: Optional[float] = None) -> None:
    if value is None:
        return
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = None
    if (
        isinstance(value, bool)
        or number is None
        or not math.isfinite(number)
        or number < low
        or (high is not None and number > high)
    ):
        limit = f"{low} to {high}" if high is not None else f"at least {low}"
        raise HTTPException(status_code=400, detail=f"{name} must be {limit}")


def _positive(name: str, raw: Any) -> float:
    """A finite number greater than zero. NaN and Infinity are a 400."""
    if isinstance(raw, bool):
        raise HTTPException(status_code=400, detail=f"{name} must be greater than 0")
    try:
        number = float(raw)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail=f"{name} must be greater than 0")
    if not math.isfinite(number) or number <= 0:
        raise HTTPException(status_code=400, detail=f"{name} must be greater than 0")
    return number


def _first_present(row: dict, *names: str):
    for name in names:
        if name in row and row[name] not in (None, ""):
            return row[name]
    return None


def _check_non_negative_map(name: str, values: Optional[dict]) -> None:
    if values is None:
        return
    if not isinstance(values, dict):
        raise HTTPException(status_code=400, detail=f"{name} must be an object")
    for key, value in values.items():
        label = f"{name}.{key}"
        if isinstance(value, dict):
            _check_non_negative_map(label, value)
            continue
        if isinstance(value, bool):
            raise HTTPException(status_code=400, detail=f"{label} must be zero or greater")
        try:
            number = float(value)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail=f"{label} must be zero or greater")
        if not math.isfinite(number) or number < 0:
            raise HTTPException(status_code=400, detail=f"{label} must be zero or greater")


def validate_estimate_request(body: "EstimateRequest") -> None:
    """Reject overrides and sizes that would otherwise become a 500."""
    _check_number("fuel_percent", body.fuel_percent, low=0, high=200)
    _check_number("long_charge", body.long_charge, low=0)
    _check_number("long_min_length_in", body.long_min_length_in, low=1)
    _check_number("density_lb_per_cuft", body.density_lb_per_cuft, low=0.1)
    if len(body.doors) > MAX_DOOR_LINES:
        raise HTTPException(status_code=400, detail=f"At most {MAX_DOOR_LINES} door lines")
    if len(body.skids) > MAX_SKIDS:
        raise HTTPException(status_code=400, detail=f"At most {MAX_SKIDS} skids")
    for index, door in enumerate(body.doors, start=1):
        if not isinstance(door, dict):
            raise HTTPException(status_code=400, detail=f"Door {index} must be an object")
        _positive(
            f"Door {index} width",
            _first_present(door, "doorWidth", "door_width", "width"),
        )
        _positive(
            f"Door {index} height",
            _first_present(door, "doorHeight", "door_height", "height"),
        )
        qty = _first_present(door, "doorCount", "door_count", "qty")
        if qty is None:
            continue
        if isinstance(qty, bool):
            raise HTTPException(status_code=400, detail=f"Door {index} quantity must be from 1 to {MAX_DOOR_QTY}")
        try:
            count = float(qty)
        except (TypeError, ValueError):
            count = None
        if count is None or not math.isfinite(count) or count < 1 or count > MAX_DOOR_QTY:
            raise HTTPException(
                status_code=400,
                detail=f"Door {index} quantity must be from 1 to {MAX_DOOR_QTY}",
            )
    for index, skid in enumerate(body.skids, start=1):
        if not isinstance(skid, dict):
            raise HTTPException(status_code=400, detail=f"Skid {index} must be an object")
        _positive(f"Skid {index} length", _first_present(skid, "length_in", "lengthIn"))
        _positive(f"Skid {index} width", _first_present(skid, "width_in", "widthIn"))
        _positive(f"Skid {index} height", _first_present(skid, "height_in", "heightIn"))
        _positive(f"Skid {index} weight", _first_present(skid, "weight_lb", "weightLb"))


def _settings_payload(db: Session) -> dict:
    constants = load_constants()
    config = freight_estimator_config(db)
    operators = {
        key: {"label": row["label"], "lb": config.get("operator_lb", {}).get(key, row["lb"])}
        for key, row in constants["operators"].items()
    }
    return {
        "mode": freight_estimator_mode(db),
        "signed_note": SIGNED_NOTE,
        "config": config,
        "origins": [dict(row) for row in ORIGINS],
        "destinations": [dict(row) for row in DESTINATIONS],
        "operators": operators,
        "shaft_lb_per_ft": constants["shaft"]["lb_per_ft"],
        "crate_defaults": {
            key: constants["crate"][key]
            for key in (
                "shaft_overhang_in",
                "dunnage_in",
                "packing_allowance_in",
                "max_stack_height_in",
                "tare_base_lb",
                "tare_lb_per_ft",
            )
        },
    }


@router.get("/settings")
def get_settings(
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    """Switch and editable numbers. Available while the estimator is off."""
    return _settings_payload(db)


@router.put("/settings")
def update_settings(
    body: FreightSettingsUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _check_number("fuel_percent", body.fuel_percent, low=0, high=200)
    _check_number("long_charge", body.long_charge, low=0)
    _check_number("long_min_length_in", body.long_min_length_in, low=1)
    _check_number("density_lb_per_cuft", body.density_lb_per_cuft, low=0.1)
    _check_number("gst_percent", body.gst_percent, low=0, high=20)
    _check_non_negative_map("crate", body.crate)
    _check_non_negative_map("operator_lb", body.operator_lb)
    _check_non_negative_map("shaft_lb_per_ft", body.shaft_lb_per_ft)
    _check_non_negative_map("drum_lb_each", body.drum_lb_each)
    if body.mode is not None:
        try:
            set_freight_estimator_mode(db, body.mode, user_id=user.id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
    updates = body.model_dump(exclude_unset=True, exclude={"mode"})
    if updates:
        set_freight_estimator_config(db, updates, user_id=user.id)
    db.commit()
    return _settings_payload(db)


@router.get("/enabled")
def enabled(
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    """Nav probe. 404 while the flag is off, so the link and the panel stay hidden."""
    _require_on(db)
    config = freight_estimator_config(db)
    return {
        "enabled": True,
        "signed_note": SIGNED_NOTE,
        "origins": [dict(row) for row in ORIGINS],
        "destinations": [dict(row) for row in DESTINATIONS],
        "defaults": {
            "origin": "redcliff",
            "fuel_percent": config.get("fuel_percent"),
            "long_charge": config.get("long_charge"),
            "long_min_length_in": config.get("long_min_length_in"),
            "density_lb_per_cuft": config.get("density_lb_per_cuft"),
            "gst_percent": config.get("gst_percent"),
        },
    }


@router.post("/estimate")
def estimate(
    body: EstimateRequest,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    """Estimate ship weight and contract freight. 404 while the flag is off."""
    _require_on(db)
    if not body.doors and not body.skids:
        raise HTTPException(status_code=400, detail="Add a door line or a skid.")
    validate_estimate_request(body)
    saved = freight_estimator_config(db)
    for key in ("fuel_percent", "long_charge", "long_min_length_in", "density_lb_per_cuft"):
        override = getattr(body, key)
        if override is not None:
            saved[key] = override
    try:
        return estimate_freight(
            {
                "origin": body.origin,
                "destination": body.destination,
                "doors": body.doors,
                "skids": body.skids,
            },
            config=saved,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
