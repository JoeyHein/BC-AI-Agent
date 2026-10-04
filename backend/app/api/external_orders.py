"""External order status, shipment, and pickup/delivery (ED-008).

Read-only. Auth is the existing X-Service-AI-Key. The key is bound to one
BC customer number (`supplier_account_code`). Every call names that customer
again; a mismatch is 404, the same as an unknown order.

GET /api/external/orders?supplierAccountCode=ED-001
    Open sales orders for that customer.

GET /api/external/orders/{orderNumber}?supplierAccountCode=ED-001
    F1 — status, lines, posted shipments, tracking when BC sends it,
    plus the F2 fulfillment object.

GET /api/external/orders/{orderNumber}/fulfillment?supplierAccountCode=ED-001
    F2 — pickup vs delivery, scheduled date, confirmation.

Nothing in this module writes to Business Central.
"""
from __future__ import annotations

import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.api.external_auth import require_external_key
from app.db.models import ExternalApiKey
from app.services.external_order_status_service import (
    OrderReadError,
    list_orders,
    read_order,
)

router = APIRouter(prefix="/api/external", tags=["external"])
logger = logging.getLogger(__name__)

_ERROR_STATUS = {
    "INVALID_REQUEST": 400,
    "NOT_FOUND": 404,
    "UPSTREAM_ERROR": 502,
}


class _ShipTo(BaseModel):
    name: Optional[str] = None
    contact: Optional[str] = None
    addressLine1: Optional[str] = None
    addressLine2: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    postCode: Optional[str] = None
    country: Optional[str] = None


class _Picking(BaseModel):
    available: bool
    queueStatus: Optional[str] = None
    pickingDate: Optional[str] = None
    shipmentDate: Optional[str] = None
    loadMethod: Optional[str] = None
    posted: bool
    shipmentNo: Optional[str] = None


class _Fulfillment(BaseModel):
    orderNumber: Optional[str] = None
    customerNumber: Optional[str] = None
    method: str
    methodSource: Optional[str] = None
    scheduledDate: Optional[str] = None
    shipmentDate: Optional[str] = None
    confirmed: bool
    confirmation: str
    fulfillmentStatus: str
    shipTo: Optional[_ShipTo] = None
    picking: _Picking


class _Line(BaseModel):
    sequence: Optional[int] = None
    lineType: Optional[str] = None
    itemNo: Optional[str] = None
    description: Optional[str] = None
    quantity: Optional[float] = None
    shippedQuantity: Optional[float] = None
    outstandingQuantity: Optional[float] = None
    unitOfMeasureCode: Optional[str] = None


class _Shipment(BaseModel):
    shipmentId: Optional[str] = None
    shipmentNumber: Optional[str] = None
    orderNumber: Optional[str] = None
    externalDocumentNumber: Optional[str] = None
    shipmentDate: Optional[str] = None
    postingDate: Optional[str] = None
    trackingNumber: Optional[str] = None
    carrier: Optional[str] = None
    shipToName: Optional[str] = None
    shipTo: Optional[_ShipTo] = None


class _Order(BaseModel):
    orderNumber: Optional[str] = None
    orderId: Optional[str] = None
    customerNumber: Optional[str] = None
    customerName: Optional[str] = None
    externalDocumentNumber: Optional[str] = None
    status: Optional[str] = None
    source: str
    orderDate: Optional[str] = None
    requestedDeliveryDate: Optional[str] = None
    currency: Optional[str] = None
    totalAmountExcludingTax: Optional[float] = None
    totalTaxAmount: Optional[float] = None
    totalAmountIncludingTax: Optional[float] = None
    fullyShipped: bool
    outstandingKnown: bool
    fulfillmentStatus: str
    shipmentMethodCode: Optional[str] = None
    shipTo: Optional[_ShipTo] = None
    lines: List[_Line]
    shipments: List[_Shipment]
    fulfillment: _Fulfillment


class _OrderOut(BaseModel):
    ok: bool = True
    data: _Order


class _FulfillmentOut(BaseModel):
    ok: bool = True
    data: _Fulfillment


class _OrderSummary(BaseModel):
    orderNumber: Optional[str] = None
    orderId: Optional[str] = None
    externalDocumentNumber: Optional[str] = None
    customerNumber: Optional[str] = None
    customerName: Optional[str] = None
    status: Optional[str] = None
    orderDate: Optional[str] = None
    requestedDeliveryDate: Optional[str] = None
    currency: Optional[str] = None
    totalAmountIncludingTax: Optional[float] = None
    fullyShipped: bool
    shipmentMethodCode: Optional[str] = None
    method: str


class _OrderList(BaseModel):
    customerNumber: str
    complete: bool
    orders: List[_OrderSummary]


class _OrderListOut(BaseModel):
    ok: bool = True
    data: _OrderList


def _error_response(err: OrderReadError) -> JSONResponse:
    return JSONResponse(
        status_code=_ERROR_STATUS.get(err.code, 500),
        content={
            "ok": False,
            "error": {
                "code": err.code,
                "message": err.message,
                "retryable": err.retryable,
            },
        },
    )


def _account_or_error(api_key: ExternalApiKey, supplier_account_code: Optional[str]):
    """Flat error envelope (not HTTPException's `detail` wrapper) so every
    ED-008 failure the bridge parses has the same `{ok, error}` shape.
    A code that does not match the key is 404, never 403.
    """
    if supplier_account_code is None or not str(supplier_account_code).strip():
        return _error_response(OrderReadError(
            "INVALID_REQUEST",
            "supplierAccountCode is required",
            False,
        ))
    if len(supplier_account_code) > 80:
        return _error_response(OrderReadError(
            "INVALID_REQUEST",
            "supplierAccountCode must be ≤80 characters",
            False,
        ))
    if api_key.supplier_account_code != supplier_account_code:
        logger.warning(
            "External API key id=%s tried to access account_code=%s (bound to %s)",
            api_key.id, supplier_account_code, api_key.supplier_account_code,
        )
        return _error_response(OrderReadError(
            "NOT_FOUND",
            "Supplier account not found",
            False,
        ))
    return None


@router.get("/orders", response_model=_OrderListOut)
def list_customer_orders(
    supplierAccountCode: Optional[str] = Query(default=None),
    api_key: ExternalApiKey = Depends(require_external_key),
):
    """Open sales orders for the customer bound to this API key."""
    rejected = _account_or_error(api_key, supplierAccountCode)
    if rejected is not None:
        return rejected
    result = list_orders(supplierAccountCode)
    if isinstance(result, OrderReadError):
        return _error_response(result)
    return _OrderListOut(data=_OrderList(**result))


@router.get("/orders/{order_number}/fulfillment", response_model=_FulfillmentOut)
def get_order_fulfillment(
    order_number: str,
    supplierAccountCode: Optional[str] = Query(default=None),
    api_key: ExternalApiKey = Depends(require_external_key),
):
    """F2 — pickup or delivery schedule and confirmation for one sales order."""
    rejected = _account_or_error(api_key, supplierAccountCode)
    if rejected is not None:
        return rejected
    result = read_order(supplierAccountCode, order_number)
    if isinstance(result, OrderReadError):
        return _error_response(result)
    return _FulfillmentOut(data=_Fulfillment(**result["fulfillment"]))


@router.get("/orders/{order_number}", response_model=_OrderOut)
def get_order_status(
    order_number: str,
    supplierAccountCode: Optional[str] = Query(default=None),
    api_key: ExternalApiKey = Depends(require_external_key),
):
    """F1 — status, shipment, and tracking for one sales order.

    The body also includes the F2 fulfillment object so a bridge can poll
    status and pickup/delivery in one call.
    """
    rejected = _account_or_error(api_key, supplierAccountCode)
    if rejected is not None:
        return rejected
    result = read_order(supplierAccountCode, order_number)
    if isinstance(result, OrderReadError):
        return _error_response(result)
    return _OrderOut(data=_Order(**result))
