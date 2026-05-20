"""
External quote void service (TD-SQB-A8).

Wraps `bc_client.delete_sales_quote` behind an idempotency layer keyed
by `external_quote_id` (the SAME id used at commit + convert). Operates
on the existing `external_quote_commits` row: if the row already has
`voided_at` populated, return the cached result without any BC traffic.

Failure modes that are intentionally NOT marked as 'failed' on the
status column:
  - The commit succeeded (status='committed'). Only the void failed.
    A retry must be able to attempt again — leave `voided_at` null.

Already-converted quotes are rejected with UNPROCESSABLE: once a BC
quote has been converted into a sales order, the quote is consumed and
cannot be voided through this surface. The caller should cancel the
order instead (a separate operation not exposed via the external API).

Concurrency strategy mirrors `external_order_conversion_service`:
  - Per-key in-process `threading.Lock`, reusing the same `_locks` map.
  - DB-level: a single UPDATE on the row, which is atomic. Two
    concurrent calls that bypass the in-process lock (e.g. across
    worker processes) will both call BC; the second one will get a
    BC 404 (quote already deleted), which we treat as success and
    persist `voided_at`. No second BC document; harmless second call.
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
class VoidResult:
    supplier_quote_ref: str
    voided_at: datetime
    cached: bool  # True when this call returned a previously-voided row.


@dataclass
class VoidError:
    code: str
    message: str
    retryable: bool


def void_external_quote(
    db: Session,
    api_key_id: int,
    account_code: str,
    external_quote_id: str,
    reason: Optional[str] = None,
) -> VoidResult | VoidError:
    """Void a previously-committed BC quote.

    Returns VoidResult on success (including idempotent replay) and
    VoidError on every failure mode. The caller (the FastAPI route)
    maps VoidError.code → HTTP status via the shared `_ERROR_STATUS`
    table in `external_quotes.py`.
    """
    lock = _lock_for(external_quote_id)
    acquired = lock.acquire(timeout=10.0)
    if not acquired:
        return VoidError(
            code="IN_PROGRESS",
            message="Another void is in progress for this quote",
            retryable=True,
        )

    try:
        row: Optional[ExternalQuoteCommit] = (
            db.query(ExternalQuoteCommit)
            .filter(ExternalQuoteCommit.external_quote_id == external_quote_id)
            .first()
        )

        if row is None:
            return VoidError(
                code="NOT_FOUND",
                message="No external quote commit found for that id",
                retryable=False,
            )

        # Cross-key probe: same 404 semantic as commit + convert.
        if row.supplier_account_code != account_code:
            logger.warning(
                "External API key id=%s tried to void quote external_id=%s "
                "bound to account_code=%s (key bound to %s)",
                api_key_id, external_quote_id, row.supplier_account_code, account_code,
            )
            return VoidError(
                code="NOT_FOUND",
                message="No external quote commit found for that id",
                retryable=False,
            )

        # Idempotency replay: already voided -> return the cached result.
        if row.voided_at is not None:
            return VoidResult(
                supplier_quote_ref=row.supplier_quote_ref or "",
                voided_at=row.voided_at,
                cached=True,
            )

        # Voiding only makes sense for a committed quote. A row that
        # never reached the committed state cannot be voided; the caller
        # has no BC document to delete.
        if row.status != "committed" or not row.bc_quote_id:
            return VoidError(
                code="UNPROCESSABLE",
                message=(
                    f"Cannot void quote in status={row.status}; "
                    "a successful commit must run first."
                ),
                retryable=False,
            )

        # Reject voids on quotes already converted to orders — the BC
        # quote no longer exists in BC after conversion (delete is part
        # of the manual conversion path), and the order is a separate
        # document with its own lifecycle.
        if row.converted_at is not None:
            return VoidError(
                code="UNPROCESSABLE",
                message=(
                    "Cannot void a quote that has been converted to an order. "
                    "Cancel the order instead."
                ),
                retryable=False,
            )

        try:
            bc_client.delete_sales_quote(row.bc_quote_id)
        except Exception as exc:  # noqa: BLE001 — BC client raises bare Exception subclasses
            # 404 from BC means the quote is already gone — treat as success
            # so a retry after partial failure converges. Any other error
            # is retryable.
            message = str(exc)
            if "404" in message or "not found" in message.lower():
                logger.info(
                    "BC sales quote %s already absent; treating as already-voided",
                    row.bc_quote_id,
                )
            else:
                logger.exception(
                    "delete_sales_quote failed: external_id=%s bc_quote_id=%s",
                    external_quote_id, row.bc_quote_id,
                )
                return VoidError(
                    code="UPSTREAM_ERROR",
                    message=f"BC delete_sales_quote failed: {exc}",
                    retryable=True,
                )

        now = datetime.now(timezone.utc)
        row.voided_at = now
        if reason:
            row.void_reason = reason[:1000]
        db.commit()

        return VoidResult(
            supplier_quote_ref=row.supplier_quote_ref or "",
            voided_at=now,
            cached=False,
        )
    finally:
        lock.release()
        _release_lock(external_quote_id)
