"""External purchase-order endpoint (BCB-02 / TD-PO-01).

POST /api/external/purchase-orders
    Headers: X-Service-AI-Key, [Idempotency-Key]
    Body:
      { "supplierAccountCode": "ED-001",
        "externalPoId": "<service.ai PO uuid>",
        "poNumber": "PO-000123",
        "lines": [{ "sku": "PN10", "quantity": 5, "unitCostCents": 700,
                    "description": "..." }] }

Response (200/201):
    { "ok": true, "data": { "supplierPoRef": "104821", "supplierPoId": "...",
                             "createdAt": "..." } }

Idempotent on `externalPoId` (external_purchase_orders table + per-key lock,
mirrors commit). A replay returns the cached BC PO number with no BC traffic.
"""
from __future__ import annotations

import logging
from typing import List, Optional

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.api.auth import get_db
from app.api.external_auth import assert_account_code, require_external_key
from app.db.models import ExternalApiKey
from app.services.external_purchase_order_service import (
    PoError,
    PoLine,
    create_external_purchase_order,
)
from sqlalchemy.orm import Session

router = APIRouter(prefix="/api/external", tags=["external"])
logger = logging.getLogger(__name__)


class _LineIn(BaseModel):
    sku: str = Field(min_length=1, max_length=80)
    quantity: float = Field(gt=0, le=1_000_000)
    unitCostCents: int = Field(ge=0)
    description: Optional[str] = Field(default=None, max_length=300)


class PurchaseOrderIn(BaseModel):
    supplierAccountCode: str = Field(min_length=1, max_length=80)
    externalPoId: str = Field(min_length=1, max_length=80)
    poNumber: Optional[str] = Field(default=None, max_length=40)
    lines: List[_LineIn] = Field(min_length=1, max_length=500)


class PurchaseOrderData(BaseModel):
    supplierPoRef: str
    supplierPoId: str
    createdAt: str


class PurchaseOrderOut(BaseModel):
    ok: bool = True
    data: PurchaseOrderData


_ERROR_STATUS = {
    "INVALID_REQUEST": 400,
    "IDEMPOTENCY_CONFLICT": 409,
    "IN_PROGRESS": 409,
    "UPSTREAM_ERROR": 502,
}


@router.post("/purchase-orders")
def create_purchase_order(
    payload: PurchaseOrderIn,
    db: Session = Depends(get_db),
    api_key: ExternalApiKey = Depends(require_external_key),
):
    assert_account_code(api_key, payload.supplierAccountCode)

    result = create_external_purchase_order(
        db,
        api_key_id=api_key.id,
        account_code=payload.supplierAccountCode,
        external_po_id=payload.externalPoId,
        po_number=payload.poNumber,
        lines=[
            PoLine(
                sku=l.sku,
                quantity=l.quantity,
                unit_cost_cents=l.unitCostCents,
                description=l.description,
            )
            for l in payload.lines
        ],
    )

    if isinstance(result, PoError):
        http = _ERROR_STATUS.get(result.code, 502)
        return JSONResponse(
            status_code=http,
            content={"ok": False, "error": {"code": result.code, "message": result.message}},
        )

    status_code = 200 if result.cached else 201
    return JSONResponse(
        status_code=status_code,
        content={
            "ok": True,
            "data": {
                "supplierPoRef": result.supplier_po_ref,
                "supplierPoId": result.supplier_po_id,
                "createdAt": result.created_at.isoformat(),
            },
        },
    )
