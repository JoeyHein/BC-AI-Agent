"""External availability endpoint (BCB-02 / TD-INV-01).

POST /api/external/check-availability
    Headers: X-Service-AI-Key
    Body: { "supplierAccountCode": "ED-001",
            "items": [{ "sku": "PN10-...", "quantity": 4 }] }

Response (200):
    { "ok": true, "data": {
        "allAvailable": false,
        "items": [{ "sku", "onHand", "available", "shortfall",
                    "status": "available|partial|unavailable", "leadTimeDays" }] } }

A read — wraps `bc_inventory_service.check_availability`. No idempotency
needed. Cross-tenant probe → 404 per the account-code rule.
"""
from __future__ import annotations

import logging
from typing import List

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.api.external_auth import assert_account_code, require_external_key
from app.db.models import ExternalApiKey
from app.services.bc_inventory_service import bc_inventory_service

router = APIRouter(prefix="/api/external", tags=["external"])
logger = logging.getLogger(__name__)


class _ItemIn(BaseModel):
    sku: str = Field(min_length=1, max_length=80)
    quantity: float = Field(gt=0, le=1_000_000)


class CheckAvailabilityIn(BaseModel):
    supplierAccountCode: str = Field(min_length=1, max_length=80)
    items: List[_ItemIn] = Field(min_length=1, max_length=200)


class _LineOut(BaseModel):
    sku: str
    onHand: float
    available: float
    shortfall: float
    status: str
    leadTimeDays: int


class AvailabilityData(BaseModel):
    allAvailable: bool
    items: List[_LineOut]


class AvailabilityOut(BaseModel):
    ok: bool = True
    data: AvailabilityData


@router.post("/check-availability", response_model=AvailabilityOut)
def check_availability(
    payload: CheckAvailabilityIn,
    api_key: ExternalApiKey = Depends(require_external_key),
):
    assert_account_code(api_key, payload.supplierAccountCode)

    result = bc_inventory_service.check_availability(
        [{"itemNumber": i.sku, "quantity": i.quantity} for i in payload.items]
    )
    as_dict = result.to_dict()
    lines = [
        _LineOut(
            sku=item.get("itemNumber", ""),
            onHand=item.get("onHand", 0) or 0,
            available=item.get("available", 0) or 0,
            shortfall=item.get("shortfall", 0) or 0,
            status=item.get("status", "unavailable"),
            leadTimeDays=int(item.get("leadTimeDays", 0) or 0),
        )
        for item in as_dict.get("items", [])
    ]
    return AvailabilityOut(
        data=AvailabilityData(allAvailable=bool(as_dict.get("allAvailable", False)), items=lines)
    )
