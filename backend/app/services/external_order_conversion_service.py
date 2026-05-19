"""
External quote-to-order conversion service (QOC-04).

Wraps `bc_client.convert_quote_to_order` behind an idempotency layer
keyed by `external_quote_id` (the SAME id used at commit). Operates on
the existing `external_quote_commits` row: if the row already has
`bc_order_id` populated, return the cached order ref without any BC
traffic. Otherwise, look up the row's `bc_quote_id`, call BC's
makeOrder action, persist the order ref on the same row.

Two failure modes are intentionally NOT marked as 'failed' on the
status column:
  - The commit succeeded (status='committed' already). Only the
    conversion failed. A retry must be able to attempt again.
  - The status='failed' or status='in_progress' case is rejected
    UPSTREAM (the endpoint returns 422 UNPROCESSABLE before this
    service runs).

Concurrency strategy:
  - Per-key in-process `threading.Lock` (same mechanism as commit;
    re-uses the same `_locks` map by `external_quote_id`).
  - DB-level: the conversion is a single UPDATE on the row, which is
    atomic. Two concurrent calls that both pass the in-process lock
    in different worker processes will both call BC; the second one
    will get back the same BC order (BC's makeOrder is idempotent on
    the quote id) and the second UPDATE writes the same values. No
    second BC document; harmless second BC call.

Cross-worker idempotency is best-effort here: BC's makeOrder action
on the same quote id returns the same result, so even if two workers
race, the final state is consistent. A future hardening could add a
PostgreSQL advisory lock; for v1, the existing layered strategy is
acceptable per the QOC gate's "best-effort" framing.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.db.models import ExternalQuoteCommit
from app.integrations.bc.client import bc_client
from app.services.external_quote_service import _lock_for, _release_lock

logger = logging.getLogger(__name__)


@dataclass
class ConvertResult:
    supplier_order_ref: str
    supplier_order_id: str
    ordered_at: datetime
    cached: bool  # True when this call returned a previously-converted row.


@dataclass
class ConvertError:
    code: str
    message: str
    retryable: bool


def convert_external_quote_to_order(
    db: Session,
    api_key_id: int,
    account_code: str,
    external_quote_id: str,
) -> ConvertResult | ConvertError:
    """Convert a previously-committed BC quote to a BC sales order.

    Returns ConvertResult on success (including idempotent replay) and
    ConvertError on every failure mode. The caller (the FastAPI route)
    maps ConvertError.code → HTTP status.
    """
    lock = _lock_for(external_quote_id)
    acquired = lock.acquire(timeout=10.0)
    if not acquired:
        return ConvertError(
            code="IN_PROGRESS",
            message="Another conversion is in progress for this quote",
            retryable=True,
        )

    try:
        row: Optional[ExternalQuoteCommit] = (
            db.query(ExternalQuoteCommit)
            .filter(ExternalQuoteCommit.external_quote_id == external_quote_id)
            .first()
        )

        if row is None:
            return ConvertError(
                code="NOT_FOUND",
                message="No external quote commit found for that id",
                retryable=False,
            )

        # Cross-key probe: a key bound to one account_code must not
        # convert another key's quote. Same 404 semantic as the rest of
        # the external surface.
        if row.supplier_account_code != account_code:
            logger.warning(
                "External API key id=%s tried to convert quote external_id=%s "
                "bound to account_code=%s (key bound to %s)",
                api_key_id, external_quote_id, row.supplier_account_code, account_code,
            )
            return ConvertError(
                code="NOT_FOUND",
                message="No external quote commit found for that id",
                retryable=False,
            )

        # Idempotency replay: already converted -> return the cached ref.
        if row.converted_at is not None and row.bc_order_ref and row.bc_order_id:
            return ConvertResult(
                supplier_order_ref=row.bc_order_ref,
                supplier_order_id=row.bc_order_id,
                ordered_at=row.converted_at,
                cached=True,
            )

        # Conversion requires a successfully-committed source quote.
        # Reject in-progress, failed, or any quote whose BC id never landed.
        if row.status != "committed" or not row.bc_quote_id:
            return ConvertError(
                code="UNPROCESSABLE",
                message=(
                    f"Cannot convert quote in status={row.status}; "
                    "a successful commit must run first."
                ),
                retryable=False,
            )

        try:
            bc_order = bc_client.convert_quote_to_order(row.bc_quote_id)
        except Exception as exc:  # noqa: BLE001 — BC client raises bare Exception subclasses
            logger.exception(
                "convert_quote_to_order failed: external_id=%s bc_quote_id=%s",
                external_quote_id, row.bc_quote_id,
            )
            return ConvertError(
                code="UPSTREAM_ERROR",
                message=f"BC convert_quote_to_order failed: {exc}",
                retryable=True,
            )

        bc_order_id = bc_order.get("id")
        bc_order_ref = bc_order.get("number")
        if not bc_order_id or not bc_order_ref:
            return ConvertError(
                code="UPSTREAM_ERROR",
                message="BC convert_quote_to_order returned no order id/number",
                retryable=True,
            )

        now = datetime.now(timezone.utc)
        row.bc_order_id = bc_order_id
        row.bc_order_ref = bc_order_ref
        row.converted_at = now
        db.commit()

        return ConvertResult(
            supplier_order_ref=bc_order_ref,
            supplier_order_id=bc_order_id,
            ordered_at=now,
            cached=False,
        )
    finally:
        lock.release()
        # Don't immediately release the lock from the map — let it
        # linger for the duration of the request batch. The commit
        # service does the same; eventual cleanup happens when the
        # process restarts. For long-running deployments, the worry is
        # tiny because each key is a UUID and the conversion is a
        # once-per-quote operation.
        _release_lock(external_quote_id)
