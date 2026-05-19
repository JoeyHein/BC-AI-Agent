"""
External price-items endpoint (SQB-04).

POST /api/external/price-items
    Headers: X-Service-AI-Key: <plaintext from SQB-03>
    Body:
      {
        "supplierAccountCode": "ED-001",
        "items": [{ "sku": "PN10-...", "quantity": 4, "options": {...} }],
        "currency": "CAD"      # optional, defaults to CAD
      }

Response (200):
    {
      "ok": true,
      "data": {
        "items": [{
            "sku": "...", "quantity": 4,
            "unitPriceCents": 12345, "unitCostCents": 6700,
            "lineTotalCents": 49380,
            "itemCategory": "ALUMINIUM",
            "description": "...",
            "currency": "CAD",
            "priceSource": "customer" | "group" | "all_customers" | "item_default"
        }],
        "subtotalCents": 49380,
        "taxCents": 0,
        "totalCents": 49380,
        "currency": "CAD",
        "validUntil": "2026-06-16T..."
      }
    }

Pricing path:
    Customer (source_type=1) → Customer Price Group (source_type=2) →
    All Customers (source_type=0) → item.unitPrice fallback.

Caching: in-memory, 60 s TTL keyed by (account_code, sku, qty). See
`external_pricing_service._price_cache`. The same call within the
window returns the cached envelope, avoiding repeated BC OData hits
during a live quote build.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.auth import get_db
from app.api.external_auth import assert_account_code, require_external_key
from app.db.models import ExternalApiKey
from app.services.external_pricing_service import resolve_price

router = APIRouter(prefix="/api/external", tags=["external"])
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Schemas — camelCase wire shape (Service.AI consumes), snake_case in code.
# ---------------------------------------------------------------------------


class _ItemIn(BaseModel):
    sku: str = Field(min_length=1, max_length=80)
    quantity: int = Field(ge=1, le=100_000)
    # Provider-opaque extras. Accepted but unused in v1 — passed through
    # so future configurator-aware pricing has the data when SQB-04.1
    # extends the resolver.
    options: Optional[dict] = None


class PriceItemsIn(BaseModel):
    supplierAccountCode: str = Field(min_length=1, max_length=80)
    items: List[_ItemIn] = Field(min_length=1, max_length=200)
    currency: str = Field(default="CAD", pattern=r"^(CAD|USD)$")


class _LineOut(BaseModel):
    sku: str
    quantity: int
    unitPriceCents: int
    unitCostCents: int
    lineTotalCents: int
    itemCategory: Optional[str] = None
    description: str
    currency: str
    priceSource: str


class PriceItemsData(BaseModel):
    items: List[_LineOut]
    subtotalCents: int
    taxCents: int
    totalCents: int
    currency: str
    validUntil: str


class PriceItemsOut(BaseModel):
    ok: bool = True
    data: PriceItemsData


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _validity_window_iso(days: int = 30) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()


def _envelope_error(code: str, message: str, http_status: int) -> JSONResponse:
    return JSONResponse(
        status_code=http_status,
        content={"ok": False, "error": {"code": code, "message": message}},
    )


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


@router.post("/price-items")
def price_items(
    payload: PriceItemsIn,
    db: Session = Depends(get_db),
    api_key: ExternalApiKey = Depends(require_external_key),
):
    # Cross-tenant probe: 404 (not 403) per the cross-tenant rule —
    # never confirm the existence of another supplier_account_code.
    assert_account_code(api_key, payload.supplierAccountCode)

    lines: List[_LineOut] = []
    subtotal_cents = 0
    for item in payload.items:
        resolved = resolve_price(
            db,
            account_code=payload.supplierAccountCode,
            sku=item.sku,
            quantity=item.quantity,
        )
        if resolved is None:
            # Per-line zero entry so the UI can flag the missing SKU
            # without dropping the whole batch.
            lines.append(
                _LineOut(
                    sku=item.sku,
                    quantity=item.quantity,
                    unitPriceCents=0,
                    unitCostCents=0,
                    lineTotalCents=0,
                    itemCategory=None,
                    description="(price not available)",
                    currency=payload.currency,
                    priceSource="missing",
                )
            )
            continue
        # External callers always see CAD for v1 — we don't FX-convert.
        # Per-line currency mismatches between request + resolved BC
        # data are accepted; the response currency is the request's.
        lines.append(
            _LineOut(
                sku=resolved.sku,
                quantity=resolved.quantity,
                unitPriceCents=resolved.unit_price_cents,
                unitCostCents=resolved.unit_cost_cents,
                lineTotalCents=resolved.line_total_cents,
                itemCategory=resolved.item_category,
                description=resolved.description,
                currency=payload.currency,
                priceSource=resolved.price_source,
            )
        )
        subtotal_cents += resolved.line_total_cents

    # v1: no tax computation. The Service.AI side applies tax based on
    # the branch's locale; mirroring it here would double-tax.
    tax_cents = 0
    total_cents = subtotal_cents + tax_cents

    return PriceItemsOut(
        data=PriceItemsData(
            items=lines,
            subtotalCents=subtotal_cents,
            taxCents=tax_cents,
            totalCents=total_cents,
            currency=payload.currency,
            validUntil=_validity_window_iso(),
        ),
    )
