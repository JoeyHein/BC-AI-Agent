"""
External quote commit endpoint (SQB-05).

POST /api/external/quotes
    Headers: X-Service-AI-Key: <plaintext from SQB-03>
    Body:
      {
        "supplierAccountCode": "ED-001",
        "externalQuoteId": "<service.ai uuid>",
        "items": [
            {
                "sku": "PN10-...",
                "quantity": 4,
                "unitPriceCents": 12345,
                "description": "..."   # optional
            }
        ],
        "currency": "CAD",
        "notes": "..."  # optional, attached to BC customerNote
      }

Idempotency: same `externalQuoteId` -> same `supplierQuoteRef`.
Concurrent attempts collapse via the UNIQUE constraint on
`external_quote_commits.external_quote_id`.
"""
from __future__ import annotations

import logging
from typing import List, Optional

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.api.auth import get_db
from app.api.external_auth import assert_account_code, require_external_key
from app.db.models import ExternalApiKey
from app.services.external_quote_service import (
    CommitError,
    CommitLine,
    commit_external_quote,
)
from app.services.external_order_conversion_service import (
    ConvertError,
    ConvertResult,
    convert_external_quote_to_order,
)
from app.services.external_quote_void_service import (
    VoidError,
    VoidResult,
    void_external_quote,
)

router = APIRouter(prefix="/api/external", tags=["external"])
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class _ItemIn(BaseModel):
    sku: str = Field(min_length=1, max_length=80)
    quantity: int = Field(ge=1, le=100_000)
    unitPriceCents: int = Field(ge=0)
    description: Optional[str] = Field(default=None, max_length=400)


class CommitQuoteIn(BaseModel):
    supplierAccountCode: str = Field(min_length=1, max_length=80)
    externalQuoteId: str = Field(min_length=1, max_length=80)
    items: List[_ItemIn] = Field(min_length=1, max_length=500)
    currency: str = Field(default="CAD", pattern=r"^(CAD|USD)$")
    notes: Optional[str] = Field(default=None, max_length=2000)


class CommitQuoteData(BaseModel):
    supplierQuoteRef: str
    supplierQuoteId: str
    validUntil: str
    currency: str
    cached: bool


class CommitQuoteOut(BaseModel):
    ok: bool = True
    data: CommitQuoteData


# ---------------------------------------------------------------------------
# Error → HTTP status mapping
# ---------------------------------------------------------------------------


_ERROR_STATUS = {
    "INVALID_REQUEST": 400,
    "IDEMPOTENCY_CONFLICT": 409,
    "IN_PROGRESS": 409,
    "NOT_FOUND": 404,
    "UNPROCESSABLE": 422,
    "UPSTREAM_ERROR": 502,
}


def _error_response(err: CommitError | ConvertError | VoidError) -> JSONResponse:
    status_code = _ERROR_STATUS.get(err.code, 500)
    return JSONResponse(
        status_code=status_code,
        content={
            "ok": False,
            "error": {
                "code": err.code,
                "message": err.message,
                "retryable": err.retryable,
            },
        },
    )


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


@router.post("/quotes")
def commit_quote(
    payload: CommitQuoteIn,
    db: Session = Depends(get_db),
    api_key: ExternalApiKey = Depends(require_external_key),
):
    assert_account_code(api_key, payload.supplierAccountCode)

    lines = [
        CommitLine(
            sku=item.sku,
            quantity=item.quantity,
            unit_price_cents=item.unitPriceCents,
            description=item.description,
        )
        for item in payload.items
    ]

    result = commit_external_quote(
        db,
        api_key_id=api_key.id,
        account_code=payload.supplierAccountCode,
        external_quote_id=payload.externalQuoteId,
        items=lines,
        currency=payload.currency,
        notes=payload.notes,
    )

    if isinstance(result, CommitError):
        return _error_response(result)

    return CommitQuoteOut(
        data=CommitQuoteData(
            supplierQuoteRef=result.supplier_quote_ref,
            supplierQuoteId=result.supplier_quote_id,
            validUntil=result.valid_until.isoformat(),
            currency=result.currency,
            cached=result.cached,
        ),
    )


# ---------------------------------------------------------------------------
# Convert-to-order endpoint (QOC-04)
# ---------------------------------------------------------------------------


class ConvertToOrderData(BaseModel):
    supplierOrderRef: str
    supplierOrderId: str
    orderedAt: str
    cached: bool


class ConvertToOrderOut(BaseModel):
    ok: bool = True
    data: ConvertToOrderData


# TD-QOC-A6: a strict, body-less input model. The convert is keyed entirely on
# the path param, so the body must be empty / {} — `extra='forbid'` rejects any
# smuggled fields (matches the /void endpoint's optional-model tightening).
class ConvertToOrderIn(BaseModel):
    model_config = ConfigDict(extra="forbid")


@router.post("/quotes/{external_quote_id}/convert-to-order")
def convert_to_order(
    external_quote_id: str,
    body: Optional[ConvertToOrderIn] = None,
    db: Session = Depends(get_db),
    api_key: ExternalApiKey = Depends(require_external_key),
):
    """Convert a previously-committed external quote into a BC sales order.

    Idempotent on `external_quote_id` — the same id used at commit.
    Repeat calls return the cached SO-XXXXXX without touching BC. The
    operation is keyed off the existing `external_quote_commits` row
    (no parallel table); see QOC-03 migration for the schema shape.

    Cross-key probes return 404 NOT_FOUND, never 403, per the
    Service.AI convention. A source quote that is not in status='committed'
    returns 422 UNPROCESSABLE.
    """
    # Path-level guard: keep external_quote_id reasonable.
    if not external_quote_id or len(external_quote_id) > 80:
        return JSONResponse(
            status_code=400,
            content={
                "ok": False,
                "error": {
                    "code": "INVALID_REQUEST",
                    "message": "external_quote_id is required and must be ≤80 chars",
                    "retryable": False,
                },
            },
        )

    result = convert_external_quote_to_order(
        db,
        api_key_id=api_key.id,
        account_code=api_key.supplier_account_code,
        external_quote_id=external_quote_id,
    )

    if isinstance(result, ConvertError):
        return _error_response(result)

    assert isinstance(result, ConvertResult)
    return ConvertToOrderOut(
        data=ConvertToOrderData(
            supplierOrderRef=result.supplier_order_ref,
            supplierOrderId=result.supplier_order_id,
            orderedAt=result.ordered_at.isoformat(),
            cached=result.cached,
        ),
    )


# ---------------------------------------------------------------------------
# Void endpoint (TD-SQB-A8)
# ---------------------------------------------------------------------------


class VoidQuoteIn(BaseModel):
    reason: Optional[str] = Field(default=None, max_length=1000)


class VoidQuoteData(BaseModel):
    supplierQuoteRef: str
    voidedAt: str
    cached: bool


class VoidQuoteOut(BaseModel):
    ok: bool = True
    data: VoidQuoteData


@router.post("/quotes/{external_quote_id}/void")
def void_quote(
    external_quote_id: str,
    payload: Optional[VoidQuoteIn] = None,
    db: Session = Depends(get_db),
    api_key: ExternalApiKey = Depends(require_external_key),
):
    """Void a previously-committed external quote.

    Idempotent on `external_quote_id` — the same id used at commit.
    Repeat calls return the cached `voidedAt` without touching BC. A
    quote that has been converted to a sales order cannot be voided
    via this endpoint (returns 422 UNPROCESSABLE).

    Cross-key probes return 404 NOT_FOUND, never 403, per the
    Service.AI convention.
    """
    if not external_quote_id or len(external_quote_id) > 80:
        return JSONResponse(
            status_code=400,
            content={
                "ok": False,
                "error": {
                    "code": "INVALID_REQUEST",
                    "message": "external_quote_id is required and must be ≤80 chars",
                    "retryable": False,
                },
            },
        )

    result = void_external_quote(
        db,
        api_key_id=api_key.id,
        account_code=api_key.supplier_account_code,
        external_quote_id=external_quote_id,
        reason=payload.reason if payload else None,
    )

    if isinstance(result, VoidError):
        return _error_response(result)

    assert isinstance(result, VoidResult)
    return VoidQuoteOut(
        data=VoidQuoteData(
            supplierQuoteRef=result.supplier_quote_ref,
            voidedAt=result.voided_at.isoformat(),
            cached=result.cached,
        ),
    )
