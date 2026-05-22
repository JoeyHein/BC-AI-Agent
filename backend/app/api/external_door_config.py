"""External door-config → parts resolution (TD-WI-01).

POST /api/external/door-config/resolve-parts
    Headers: X-Service-AI-Key
    Body: { "supplierAccountCode": "ED-001", "doorConfig": { ...widget config... } }

Response (200):
    { "ok": true, "data": { "parts": [
        { "sku", "quantity", "description", "category" } ] } }

Wraps `part_number_service.get_parts_for_door_config`, mapping the door
designer widget's config shape (familyId / colorId / designId / widthInches…)
onto the resolver's expected keys. A read — no idempotency. Lets a Service.AI
widget lead arrive with concrete SKUs instead of a config blob.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

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
