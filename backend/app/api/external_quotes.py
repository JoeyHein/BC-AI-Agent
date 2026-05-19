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
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.auth import get_db
from app.api.external_auth import assert_account_code, require_external_key
from app.db.models import ExternalApiKey
from app.services.external_quote_service import (
    CommitError,
    CommitLine,
    commit_external_quote,
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
    "UPSTREAM_ERROR": 502,
}


def _error_response(err: CommitError) -> JSONResponse:
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
