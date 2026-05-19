"""
External quote commit service (SQB-05).

Wraps `bc_client.create_sales_quote` + `add_quote_line` behind an
idempotency layer keyed by `external_quote_id`. Concurrent commits
with the same external id collapse to a single BC document — the
load-bearing test is the 10× concurrent stress in
`test_external_quote_commit.py`.

Concurrency strategy:
    Two mechanisms, layered:

    1. **In-process lock** keyed by `external_quote_id`. Inside the
       Gunicorn worker process that holds the lock, every retry
       observes the same DB state without racing.

    2. **DB UNIQUE constraint** on `external_quote_commits.external_quote_id`.
       Cross-process / cross-worker races fall back to this — only one
       INSERT wins, the others catch IntegrityError, re-read the row,
       and return the cached response.

The Postgres UNIQUE constraint is the source of truth. The in-process
lock just makes the test (and single-process dev) deterministic.
"""
from __future__ import annotations

import hashlib
import json
import logging
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import ExternalQuoteCommit
from app.integrations.bc.client import bc_client

logger = logging.getLogger(__name__)

DEFAULT_VALIDITY_DAYS = 30


@dataclass
class CommitLine:
    sku: str
    quantity: int
    unit_price_cents: int
    description: Optional[str] = None


@dataclass
class CommitResult:
    supplier_quote_ref: str
    supplier_quote_id: str
    valid_until: datetime
    currency: str
    cached: bool  # True when this call returned a previously-committed row.


@dataclass
class CommitError:
    code: str
    message: str
    retryable: bool


# ---------------------------------------------------------------------------
# Per-key in-process lock map
# ---------------------------------------------------------------------------

_locks: Dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def _lock_for(external_quote_id: str) -> threading.Lock:
    with _locks_guard:
        lock = _locks.get(external_quote_id)
        if lock is None:
            lock = threading.Lock()
            _locks[external_quote_id] = lock
        return lock


def _release_lock(external_quote_id: str) -> None:
    with _locks_guard:
        _locks.pop(external_quote_id, None)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _request_hash(account_code: str, items: List[CommitLine], currency: str) -> str:
    payload = {
        "account_code": account_code,
        "currency": currency,
        "items": [
            {
                "sku": i.sku,
                "quantity": i.quantity,
                "unit_price_cents": i.unit_price_cents,
                "description": i.description or "",
            }
            for i in items
        ],
    }
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def _validity_window() -> datetime:
    return datetime.now(timezone.utc) + timedelta(days=DEFAULT_VALIDITY_DAYS)


def _build_quote_data(account_code: str, currency: str, notes: Optional[str]) -> Dict[str, Any]:
    quote: Dict[str, Any] = {
        "customerNumber": account_code,
        "currencyCode": currency,
    }
    if notes:
        # BC truncates long descriptions on line items; the quote-level
        # note isn't subject to that same 100-char rule.
        quote["customerNote"] = notes[:2000]
    return quote


def _build_line_data(item: CommitLine) -> Dict[str, Any]:
    description = item.description or item.sku
    # BC enforces a 100-character limit on line description.
    description = description[:100]
    return {
        "itemNumber": item.sku,
        "quantity": item.quantity,
        "unitPrice": item.unit_price_cents / 100.0,
        "description": description,
    }


def _to_committed_result(row: ExternalQuoteCommit) -> CommitResult:
    assert row.supplier_quote_ref is not None
    assert row.bc_quote_id is not None
    assert row.valid_until is not None
    return CommitResult(
        supplier_quote_ref=row.supplier_quote_ref,
        supplier_quote_id=row.bc_quote_id,
        valid_until=row.valid_until,
        currency=row.currency,
        cached=True,
    )


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def commit_external_quote(
    db: Session,
    *,
    api_key_id: Optional[int],
    account_code: str,
    external_quote_id: str,
    items: List[CommitLine],
    currency: str = "CAD",
    notes: Optional[str] = None,
) -> CommitResult | CommitError:
    """Create a BC sales quote idempotently against external_quote_id.

    Returns CommitResult on success (`cached=True` when the call was a
    replay of a previously-committed external id). Returns CommitError
    on a structured failure path.
    """
    if not items:
        return CommitError(code="INVALID_REQUEST", message="items must not be empty", retryable=False)

    request_hash = _request_hash(account_code, items, currency)
    lock = _lock_for(external_quote_id)

    with lock:
        # Resolve the row to operate on. Loops at most twice: the
        # first pass either finds an existing row or inserts a new
        # one; the second pass handles "I lost the UNIQUE race against
        # another process — re-read what they wrote." Recursion would
        # deadlock because `lock` is non-reentrant.
        row: Optional[ExternalQuoteCommit] = None
        for _ in range(2):
            db.expire_all()  # force a fresh read past any session cache
            existing = (
                db.query(ExternalQuoteCommit)
                .filter(ExternalQuoteCommit.external_quote_id == external_quote_id)
                .first()
            )
            if existing is not None:
                if existing.supplier_account_code != account_code:
                    logger.warning(
                        "external_quote_id=%s reused with mismatching "
                        "account_code (stored=%s, requested=%s)",
                        external_quote_id,
                        existing.supplier_account_code,
                        account_code,
                    )
                    return CommitError(
                        code="IDEMPOTENCY_CONFLICT",
                        message="external_quote_id is bound to a different account",
                        retryable=False,
                    )
                if existing.status == "committed":
                    if existing.request_hash and existing.request_hash != request_hash:
                        # Same external_quote_id, different body. Warn
                        # but still return the original committed ref
                        # — the supplier-side document is the truth.
                        logger.warning(
                            "external_quote_id=%s replay with different body "
                            "(original ref=%s); returning cached response",
                            external_quote_id, existing.supplier_quote_ref,
                        )
                    return _to_committed_result(existing)
                if existing.status == "in_progress":
                    # Another process / thread is mid-commit. The
                    # in-process lock serialized us against same-
                    # process races; this branch handles a cross-
                    # process or cross-worker race.
                    return CommitError(
                        code="IN_PROGRESS",
                        message="A commit for this external_quote_id is in progress",
                        retryable=True,
                    )
                # status == 'failed' — re-arm in place.
                row = existing
                row.status = "in_progress"
                row.failure_reason = None
                row.request_hash = request_hash
                row.item_count = len(items)
                row.subtotal_cents = sum(i.unit_price_cents * i.quantity for i in items)
                db.commit()
                break

            # No existing row — try to INSERT the placeholder. The
            # UNIQUE constraint on external_quote_id collapses
            # cross-process races.
            candidate = ExternalQuoteCommit(
                external_quote_id=external_quote_id,
                api_key_id=api_key_id,
                supplier_account_code=account_code,
                status="in_progress",
                request_hash=request_hash,
                item_count=len(items),
                subtotal_cents=sum(i.unit_price_cents * i.quantity for i in items),
                currency=currency,
            )
            db.add(candidate)
            try:
                db.commit()
                row = candidate
                break
            except IntegrityError:
                db.rollback()
                # Another worker won the race. Loop once to re-read
                # whatever they wrote.
                continue

        if row is None:
            # Should be unreachable — the loop either inserted, found
            # the existing row, or returned. Defensive only.
            return CommitError(
                code="UPSTREAM_ERROR",
                message="Failed to acquire idempotency row",
                retryable=True,
            )

        # 3. Make the real BC calls.
        try:
            bc_quote = bc_client.create_sales_quote(
                _build_quote_data(account_code, currency, notes)
            )
        except Exception as exc:
            row.status = "failed"
            row.failure_reason = f"create_sales_quote raised: {exc}"
            db.commit()
            logger.exception("BC create_sales_quote failed for %s", external_quote_id)
            return CommitError(
                code="UPSTREAM_ERROR",
                message="BC create_sales_quote failed",
                retryable=True,
            )

        bc_quote_id = bc_quote.get("id") if isinstance(bc_quote, dict) else None
        supplier_quote_ref = bc_quote.get("number") if isinstance(bc_quote, dict) else None
        if not bc_quote_id or not supplier_quote_ref:
            row.status = "failed"
            row.failure_reason = f"BC response missing id/number: {bc_quote!r}"
            db.commit()
            return CommitError(
                code="UPSTREAM_ERROR",
                message="BC did not return a quote id",
                retryable=True,
            )

        # 4. Add lines. Failure here leaves the BC quote without lines
        # — we don't roll it back from BC's side (BC API is fire-and-
        # forget); the row is marked failed so the caller retries.
        line_failures: List[str] = []
        for item in items:
            try:
                bc_client.add_quote_line(bc_quote_id, _build_line_data(item))
            except Exception as exc:
                line_failures.append(f"{item.sku}: {exc}")
                logger.exception(
                    "BC add_quote_line failed for sku=%s quote=%s",
                    item.sku, bc_quote_id,
                )

        if line_failures:
            row.status = "failed"
            row.failure_reason = "; ".join(line_failures)[:1900]
            row.bc_quote_id = bc_quote_id
            row.supplier_quote_ref = supplier_quote_ref
            db.commit()
            return CommitError(
                code="UPSTREAM_ERROR",
                message="Some BC line additions failed; quote left partially built",
                retryable=True,
            )

        # 5. Mark committed.
        valid_until = _validity_window()
        row.status = "committed"
        row.bc_quote_id = bc_quote_id
        row.supplier_quote_ref = supplier_quote_ref
        row.committed_at = datetime.utcnow()
        row.valid_until = valid_until
        db.commit()

        return CommitResult(
            supplier_quote_ref=supplier_quote_ref,
            supplier_quote_id=bc_quote_id,
            valid_until=valid_until,
            currency=currency,
            cached=False,
        )
