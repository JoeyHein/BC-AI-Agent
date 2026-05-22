"""External purchase-order create service (BCB-02 / TD-PO-01).

Wraps `bc_client.create_purchase_order` + `add_purchase_order_line` behind an
idempotency layer keyed by `external_po_id` (Service.AI's PO UUID). Concurrent
/ retried creates with the same external id collapse to a single BC purchase
order. Mirrors `external_quote_service.commit_external_quote`:

    1. In-process lock keyed by external_po_id (shared lock map).
    2. DB UNIQUE on external_purchase_orders.external_po_id — cross-process
       races fall back to the constraint; the loser re-reads the cached row.
"""
from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import ExternalPurchaseOrder
from app.integrations.bc.client import bc_client
from app.services.external_quote_service import _lock_for

logger = logging.getLogger(__name__)


@dataclass
class PoLine:
    sku: str
    quantity: float
    unit_cost_cents: int
    description: Optional[str] = None


@dataclass
class PoResult:
    supplier_po_ref: str
    supplier_po_id: str
    created_at: datetime
    cached: bool


@dataclass
class PoError:
    code: str
    message: str
    retryable: bool


def _request_hash(account_code: str, lines: List[PoLine]) -> str:
    payload = {
        "account_code": account_code,
        "lines": [
            {
                "sku": l.sku,
                "quantity": l.quantity,
                "unit_cost_cents": l.unit_cost_cents,
                "description": l.description or "",
            }
            for l in lines
        ],
    }
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def _build_po_data(account_code: str, po_number: Optional[str]) -> Dict[str, Any]:
    data: Dict[str, Any] = {"vendorNumber": account_code, "vendorName": account_code}
    if po_number:
        data["yourReference"] = po_number[:35]
    return data


def _build_line_data(line: PoLine) -> Dict[str, Any]:
    description = (line.description or line.sku)[:100]
    return {
        "lineType": "Item",
        "lineObjectNumber": line.sku,
        "quantity": line.quantity,
        "directUnitCost": line.unit_cost_cents / 100.0,
        "description": description,
    }


def _to_cached_result(row: ExternalPurchaseOrder) -> PoResult:
    assert row.bc_po_number is not None
    assert row.bc_po_id is not None
    return PoResult(
        supplier_po_ref=row.bc_po_number,
        supplier_po_id=row.bc_po_id,
        created_at=row.committed_at or row.created_at,
        cached=True,
    )


def create_external_purchase_order(
    db: Session,
    *,
    api_key_id: Optional[int],
    account_code: str,
    external_po_id: str,
    po_number: Optional[str],
    lines: List[PoLine],
) -> PoResult | PoError:
    """Create a BC purchase order idempotently against external_po_id."""
    if not lines:
        return PoError(code="INVALID_REQUEST", message="lines must not be empty", retryable=False)

    request_hash = _request_hash(account_code, lines)
    lock = _lock_for(external_po_id)

    with lock:
        row: Optional[ExternalPurchaseOrder] = None
        for _ in range(2):
            db.expire_all()
            existing = (
                db.query(ExternalPurchaseOrder)
                .filter(ExternalPurchaseOrder.external_po_id == external_po_id)
                .first()
            )
            if existing is not None:
                if existing.supplier_account_code != account_code:
                    return PoError(
                        code="IDEMPOTENCY_CONFLICT",
                        message="external_po_id is bound to a different account",
                        retryable=False,
                    )
                if existing.status == "committed":
                    return _to_cached_result(existing)
                if existing.status == "in_progress":
                    return PoError(
                        code="IN_PROGRESS",
                        message="A create for this external_po_id is in progress",
                        retryable=True,
                    )
                # status == 'failed' — re-arm in place.
                row = existing
                row.status = "in_progress"
                row.failure_reason = None
                row.request_hash = request_hash
                row.item_count = len(lines)
                db.commit()
                break

            candidate = ExternalPurchaseOrder(
                external_po_id=external_po_id,
                api_key_id=api_key_id,
                supplier_account_code=account_code,
                status="in_progress",
                request_hash=request_hash,
                item_count=len(lines),
            )
            db.add(candidate)
            try:
                db.commit()
                row = candidate
                break
            except IntegrityError:
                db.rollback()
                continue

        if row is None:
            return PoError(code="UPSTREAM_ERROR", message="Failed to acquire idempotency row", retryable=True)

        # Make the real BC calls.
        try:
            bc_po = bc_client.create_purchase_order(_build_po_data(account_code, po_number))
        except Exception as exc:  # noqa: BLE001
            row.status = "failed"
            row.failure_reason = f"create_purchase_order raised: {exc}"
            db.commit()
            logger.exception("BC create_purchase_order failed for %s", external_po_id)
            return PoError(code="UPSTREAM_ERROR", message="BC create_purchase_order failed", retryable=True)

        bc_po_id = bc_po.get("id") if isinstance(bc_po, dict) else None
        bc_po_number = bc_po.get("number") if isinstance(bc_po, dict) else None
        if not bc_po_id or not bc_po_number:
            row.status = "failed"
            row.failure_reason = f"BC response missing id/number: {bc_po!r}"
            db.commit()
            return PoError(code="UPSTREAM_ERROR", message="BC did not return a PO id", retryable=True)

        line_failures: List[str] = []
        for line in lines:
            try:
                bc_client.add_purchase_order_line(bc_po_id, _build_line_data(line))
            except Exception as exc:  # noqa: BLE001
                line_failures.append(f"{line.sku}: {exc}")
                logger.exception("BC add_purchase_order_line failed for sku=%s po=%s", line.sku, bc_po_id)

        if line_failures:
            row.status = "failed"
            row.failure_reason = "; ".join(line_failures)[:1900]
            row.bc_po_id = bc_po_id
            row.bc_po_number = bc_po_number
            db.commit()
            return PoError(
                code="UPSTREAM_ERROR",
                message="Some BC line additions failed; PO left partially built",
                retryable=True,
            )

        row.status = "committed"
        row.bc_po_id = bc_po_id
        row.bc_po_number = bc_po_number
        row.committed_at = datetime.utcnow()
        db.commit()

        return PoResult(
            supplier_po_ref=bc_po_number,
            supplier_po_id=bc_po_id,
            created_at=row.committed_at,
            cached=False,
        )
