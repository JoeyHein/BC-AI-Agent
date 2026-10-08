"""External door-config → parts resolution (TD-WI-01).

POST /api/external/door-config/resolve-parts
    Headers: X-Service-AI-Key
    Body: { "supplierAccountCode": "ED-001", "doorConfig": { ...widget config... } }

Lift fields on doorConfig (all optional; omitting them keeps today's
standard-lift, 15" radius, 2" bracket-mount resolution):

    liftType          standard | low_headroom | high_lift | vertical
                      Also accepted: standard_12, standard_15, lhr_front,
                      lhr_rear, and plain words such as "low headroom rear
                      mount" or "high lift".
    lhrMount          front | rear. Used when liftType is low_headroom.
                      lhr_front / lhr_rear (and the plain-word forms) set
                      this when lhrMount itself is omitted. An explicit
                      lhrMount wins over a mount encoded in liftType.
    highLiftInches    whole inches of high lift. Also accepted as highLiftIn.
    trackRadius       "12" or "15" (any positive whole number). standard_12 /
                      standard_15 set this when trackRadius is omitted.
    trackThickness    "2" or "3". Omitted → the resolver's 2" default.
    trackMount        bracket | angle. Omitted → bracket.

Response (200) is unchanged:
    { "ok": true, "data": { "parts": [
        { "sku", "quantity", "description", "category" } ] } }

Prices are not on this response. The SKUs and quantities are what
POST /api/external/price-items prices, so a low-headroom or high-lift
request now prices the matching track, hardware kit, extension, and
spring length instead of standard-lift hardware.

BC stocks one low-headroom kit (front mount). Front and rear therefore
return the same SKUs and the same price. Rear mount is recorded on the
internal door comment, which this endpoint does not return because that
line has no SKU. The caller keeps lhrMount on its own quote notes.

Wraps `part_number_service.get_parts_for_door_config`, mapping the door
designer widget's config shape (familyId / colorId / designId / widthInches…)
onto the resolver's expected keys. A read — no idempotency. Lets a Service.AI
widget lead arrive with concrete SKUs instead of a config blob.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.api.external_auth import assert_account_code, require_external_key
from app.db.models import ExternalApiKey
from app.services.part_number_service import get_parts_for_door_config

router = APIRouter(prefix="/api/external", tags=["external"])
logger = logging.getLogger(__name__)


class ResolvePartsIn(BaseModel):
    supplierAccountCode: str = Field(min_length=1, max_length=80)
    doorConfig: Dict[str, Any] = Field(default_factory=dict)


class _PartOut(BaseModel):
    sku: str
    quantity: float
    description: Optional[str] = None
    category: Optional[str] = None


class ResolvePartsData(BaseModel):
    parts: List[_PartOut]


class ResolvePartsOut(BaseModel):
    ok: bool = True
    data: ResolvePartsData


def _first(cfg: Dict[str, Any], *keys: str) -> Any:
    for k in keys:
        v = cfg.get(k)
        if v is not None and v != "":
            return v
    return None


def _norm_token(value: Any) -> str:
    """Lowercase words to a single underscore token: 'Low Headroom (Rear Mount)' → 'low_headroom_rear_mount'."""
    return re.sub(r"[^a-z0-9]+", "_", str(value).strip().lower()).strip("_")


def _whole_number(value: Any) -> Optional[int]:
    """Parse a non-negative whole number from an int, a whole float, or a numeric string.

    Bool is rejected (it is an int subclass). Strings may carry a trailing
    inch mark or the word "inches". Anything else returns None so a bad
    value is ignored instead of failing the request.
    """
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, float):
        if value < 0 or not value.is_integer():
            return None
        return int(value)
    text = str(value).strip().lower()
    text = text.replace("inches", "").replace("inch", "")
    text = text.strip().strip('"').strip("'").strip()
    if text.endswith("in") and text[:-2].strip().replace(".", "", 1).isdigit():
        text = text[:-2].strip()
    if not text:
        return None
    try:
        number = float(text) if "." in text else int(text)
    except ValueError:
        return None
    if isinstance(number, float):
        if number < 0 or not number.is_integer():
            return None
        return int(number)
    return number if number >= 0 else None


# token → (liftType, lhrMount or None, trackRadius or None)
# Resolver vocabulary is standard | low_headroom | high_lift | vertical.
# The other rows are spellings callers already use: the fit engine
# (standard_12, lhr_front, …) and plain words from a measure form.
_LIFT_SPECS: Dict[str, Tuple[str, Optional[str], Optional[str]]] = {
    "standard": ("standard", None, None),
    "standard_lift": ("standard", None, None),
    "std": ("standard", None, None),
    "std_lift": ("standard", None, None),
    "standard_12": ("standard", None, "12"),
    "standard_15": ("standard", None, "15"),
    "low_headroom": ("low_headroom", None, None),
    "low_head_room": ("low_headroom", None, None),
    "lhr": ("low_headroom", None, None),
    "low_headroom_front": ("low_headroom", "front", None),
    "low_headroom_front_mount": ("low_headroom", "front", None),
    "lhr_front": ("low_headroom", "front", None),
    "lhr_front_mount": ("low_headroom", "front", None),
    "low_headroom_rear": ("low_headroom", "rear", None),
    "low_headroom_rear_mount": ("low_headroom", "rear", None),
    "lhr_rear": ("low_headroom", "rear", None),
    "lhr_rear_mount": ("low_headroom", "rear", None),
    "high_lift": ("high_lift", None, None),
    "highlift": ("high_lift", None, None),
    "high_lift_track": ("high_lift", None, None),
    "vertical": ("vertical", None, None),
    "vertical_lift": ("vertical", None, None),
    "full_vertical": ("vertical", None, None),
}


def _mount_token(value: Any) -> Optional[str]:
    token = _norm_token(value)
    if token in ("front", "front_mount"):
        return "front"
    if token in ("rear", "rear_mount"):
        return "rear"
    return None


def _lift_fields(cfg: Dict[str, Any]) -> Dict[str, Any]:
    """Lift / track keys the part resolver already understands.

    Only keys the caller actually sent are returned. Missing keys stay
    missing so get_parts_for_door_config keeps its current defaults
    (standard lift, 15" radius, 2" track, bracket mount, front LHR).
    """
    extra: Dict[str, Any] = {}
    encoded_mount: Optional[str] = None
    encoded_radius: Optional[str] = None

    lift_raw = _first(cfg, "liftType", "lift_type", "lift")
    if lift_raw is not None:
        token = _norm_token(lift_raw)
        spec = _LIFT_SPECS.get(token)
        if spec is None:
            # An unrecognized value used to be dropped, which resolved as
            # standard lift. Keep that result instead of failing the request.
            logger.warning(
                "resolve-parts: unrecognized liftType %r; resolving standard lift",
                lift_raw,
            )
        else:
            lift_type, encoded_mount, encoded_radius = spec
            extra["liftType"] = lift_type

    mount_raw = _first(cfg, "lhrMount", "lhr_mount")
    mount = _mount_token(mount_raw) if mount_raw is not None else None
    if mount:
        extra["lhrMount"] = mount
    elif encoded_mount:
        extra["lhrMount"] = encoded_mount

    radius_raw = _first(cfg, "trackRadius", "track_radius")
    radius = _whole_number(radius_raw) if radius_raw is not None else None
    if radius:
        extra["trackRadius"] = str(radius)
    elif encoded_radius:
        extra["trackRadius"] = encoded_radius

    inches_raw = _first(
        cfg, "highLiftInches", "high_lift_inches", "highLiftIn", "high_lift_in"
    )
    inches = _whole_number(inches_raw) if inches_raw is not None else None
    if inches is not None:
        extra["highLiftInches"] = inches

    thickness_raw = _first(cfg, "trackThickness", "track_thickness")
    thickness = _whole_number(thickness_raw) if thickness_raw is not None else None
    if thickness:
        extra["trackThickness"] = str(thickness)

    track_mount_raw = _first(cfg, "trackMount", "track_mount")
    if track_mount_raw is not None:
        track_mount = _norm_token(track_mount_raw)
        if track_mount in ("angle", "angle_mount"):
            extra["trackMount"] = "angle"
        elif track_mount in ("bracket", "bracket_mount"):
            extra["trackMount"] = "bracket"

    return extra


def _map_widget_config(cfg: Dict[str, Any]) -> Dict[str, Any]:
    """Map the door-designer widget's config shape onto the part resolver's."""
    windows_val = cfg.get("windows")
    has_windows = bool(windows_val) and str(windows_val).lower() != "none"
    mapped: Dict[str, Any] = {
        "doorType": _first(cfg, "doorType") or "residential",
        "doorSeries": _first(cfg, "doorSeries", "familyId", "family") or "KANATA",
        "doorWidth": _first(cfg, "widthInches", "doorWidth") or 96,
        "doorHeight": _first(cfg, "heightInches", "doorHeight") or 84,
        "doorCount": _first(cfg, "doorCount") or 1,
        "panelColor": _first(cfg, "colorId", "panelColor", "color") or "WHITE",
        "panelDesign": _first(cfg, "designId", "panelDesign", "design") or "SHXL",
        "hasWindows": has_windows,
        "windowInsert": _first(cfg, "windowId", "windowInsert") if has_windows else None,
        "windowQty": _first(cfg, "windowQty") or 0,
        "windowFrameColor": _first(cfg, "windowFrameColor") or "BLACK",
        "glassType": _first(cfg, "glassType"),
        "glassColor": _first(cfg, "glassId", "glassColor"),
        "glassPaneType": _first(cfg, "glassPaneType"),
        "glazingType": _first(cfg, "glazingType"),
    }
    mapped.update(_lift_fields(cfg))
    return {k: v for k, v in mapped.items() if v is not None}


@router.post("/door-config/resolve-parts", response_model=ResolvePartsOut)
def resolve_parts(
    payload: ResolvePartsIn,
    api_key: ExternalApiKey = Depends(require_external_key),
):
    assert_account_code(api_key, payload.supplierAccountCode)
    summary = get_parts_for_door_config(_map_widget_config(payload.doorConfig))
    parts: List[_PartOut] = []
    for p in summary.get("parts_list", []):
        sku = p.get("part_number")
        if not sku:
            continue
        parts.append(
            _PartOut(
                sku=sku,
                quantity=float(p.get("quantity", 1) or 1),
                description=p.get("description"),
                category=p.get("category"),
            )
        )
    return ResolvePartsOut(data=ResolvePartsData(parts=parts))
