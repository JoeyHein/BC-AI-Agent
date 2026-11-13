"""Turn a customer purchase-order email into a Business Central sales order.

The conversion already exists. ``OrderLifecycleService.convert_quote_to_order``
looks the quote up by number and calls ``bc_client.convert_quote_to_order``,
which posts ``salesQuotes({id})/Microsoft.NAV.makeOrder``. Staff reach it
from the review queue (``convert_customer_approval``). Customer-approval
detection only queues that click. It never calls Business Central, and it
is off unless someone turns it on. A purchase-order email therefore sat in
the mailbox until a person saw it.

This module is the trigger. It reads the message with the existing
attachment reader, matches one open quote with deterministic rules, and
calls that same conversion. The AI category on the email is not an input.
Shadow records the decision and makes no Business Central call. Off does
nothing.

In on mode the only Business Central writes are a PATCH of the quote's
external document number and makeOrder. The manual line-copy fallback
inside makeOrder stays off, so a failed makeOrder comes back here for
review instead of building a second order.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, time, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import List, Optional
from zoneinfo import ZoneInfo

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import EmailLog, QuotePoIntake, QuoteRequest, SalesOrder
from app.services.email_text import fresh_message_text
from app.services.inbox_settings import QUOTE_PO_AUTO_CONVERT, inbox_mode
from app.services.quote_followup import (
    _rows_for_numbers,
    _same_customer,
    _sq_numbers,
    customer_po_number,
)

logger = logging.getLogger(__name__)

BUSINESS_TZ = ZoneInfo("America/Edmonton")
BUSINESS_OPEN = time(8, 0)
BUSINESS_CLOSE = time(17, 0)
MISSED_AFTER_HOURS = 4
AUTO_ACTOR = "quote-po-auto"

_CLOSED = {"expired", "cancelled", "canceled", "rejected", "void", "voided"}
_CONVERTED = {"converted_to_order"}
_BC_CLOSED = {"expired", "closed", "cancelled", "canceled"}

_TOTAL_RE = re.compile(
    r"(?:grand\s+total|order\s+total|po\s+total|invoice\s+total|total(?:\s+(?:amount|due))?)\s*[:\-]?\s*\$?\s*([\d,]+(?:\.\d{2})?)",
    re.I,
)
_LINE_RE = re.compile(
    r"\b(\d+(?:\.\d+)?)\s*[x×]\s*([A-Z][A-Z0-9][A-Z0-9\-]{1,})\b",
    re.I,
)
_ITEM_RE = re.compile(
    r"\b(?:item|part|sku)\s*[:#]?\s*([A-Z][A-Z0-9\-]{2,})\b",
    re.I,
)

REASON_TEXT = {
    "cross_customer": "The quote number belongs to a different customer.",
    "ambiguous": "More than one open quote matches. Nothing was chosen.",
    "mismatched_total": "The amount on the email does not match the quote.",
    "mismatched_lines": "The lines on the email do not match the quote.",
    "unknown_sender": "The sender is not a known contact for an open quote.",
    "already_converted": "This quote is already a sales order.",
    "expired": "This quote is expired or closed.",
    "quote_not_in_bc": "This quote is not an open Business Central sales quote.",
    "quote_not_in_portal": "That quote number is not in the portal.",
    "no_unique_quote": "No single open quote matches this purchase order.",
    "convert_failed": "Business Central did not convert the quote.",
    "lines_unverified": "The email lists lines and the quote has none on file to compare.",
    "unverified_quote": "This quote has no amount or lines on file to check against the purchase order.",
    "converting": "This quote is already being converted.",
}


def business_hours_between(start: Optional[datetime], end: Optional[datetime]) -> float:
    """Hours between two instants inside Monday–Friday 08:00–17:00 America/Edmonton.

    Open Distribution is in Redcliff, Alberta. Naive datetimes are UTC,
    which is how the mailbox clock is stored.
    """
    if start is None or end is None:
        return 0.0
    start_l = _as_utc(start).astimezone(BUSINESS_TZ)
    end_l = _as_utc(end).astimezone(BUSINESS_TZ)
    if end_l <= start_l:
        return 0.0
    hours = 0.0
    day = start_l.date()
    last = end_l.date()
    while day <= last:
        if day.weekday() < 5:
            open_at = datetime.combine(day, BUSINESS_OPEN, BUSINESS_TZ)
            close_at = datetime.combine(day, BUSINESS_CLOSE, BUSINESS_TZ)
            begin = max(start_l, open_at)
            finish = min(end_l, close_at)
            if finish > begin:
                hours += (finish - begin).total_seconds() / 3600.0
        day += timedelta(days=1)
    return hours


def handle_quote_po_email(
    db: Session,
    *,
    email_log: Optional[EmailLog],
    subject: str,
    body: str,
    from_address: str,
    graph_message_id: Optional[str],
    mailbox: Optional[str] = None,
    filenames: Optional[List[str]] = None,
    attachment_text: str = "",
    received_at: Optional[datetime] = None,
) -> Optional[QuotePoIntake]:
    """Detect one PO email and either record it or convert the matched quote.

    Returns None when the switch is off or the message is not a purchase
    order. A repeated Graph message id returns the first row and does not
    convert again. Email text is untrusted: the match uses the PO number,
    quote number, amount, and lines read from the message, not the AI
    category stored on the email log.
    """
    mode = inbox_mode(db, QUOTE_PO_AUTO_CONVERT)
    if mode == "off":
        return None
    visible = _visible_text(subject, body, attachment_text)
    po_number, po_source = _po_number(subject, body, attachment_text, filenames or [])
    if not po_number:
        return None
    existing = _by_graph_id(db, graph_message_id)
    if existing is not None:
        logger.info(
            "Purchase order %s already recorded for Graph message %s. Not converting again.",
            existing.customer_po, graph_message_id,
        )
        return existing
    facts = _read_facts(visible, po_number, po_source, filenames or [])
    match = _match_quote(db, from_address, facts, datetime.utcnow())
    row = _insert_row(
        db,
        email_log=email_log,
        subject=subject,
        from_address=from_address,
        graph_message_id=graph_message_id,
        mailbox=mailbox,
        received_at=received_at or (email_log.received_at if email_log is not None else None),
        facts=facts,
        match=match,
        excerpt=visible[:2000],
    )
    if row is None:
        return _by_graph_id(db, graph_message_id)
    if mode == "shadow" or match["confidence"] != "high":
        row.status = "shadow" if mode == "shadow" else "review"
        row.planned_action = _plan(match, facts, acted=False)
        logger.info(
            "Purchase order %s from %s mode=%s confidence=%s reason=%s. No Business Central write.",
            po_number, from_address, mode, match["confidence"], match.get("reason"),
        )
        db.commit()
        return row
    return _convert_row(db, row, match["quote"], AUTO_ACTOR)


def list_quote_po_intakes(db: Session, now: Optional[datetime] = None) -> List[dict]:
    """Review rows, missed purchase orders first."""
    try:
        refresh_missed_purchase_orders(db, now)
        rows = (
            db.query(QuotePoIntake)
            .filter(QuotePoIntake.status.in_(["review", "shadow", "converting"]))
            .all()
        )
    except Exception:
        logger.warning("Purchase-order review list is not available yet", exc_info=True)
        try:
            db.rollback()
        except Exception:
            pass
        return []
    overdue = sorted(
        (row for row in rows if row.overdue),
        key=lambda row: row.received_at or row.created_at or datetime.min,
    )
    waiting = sorted(
        (row for row in rows if not row.overdue),
        key=lambda row: row.created_at or datetime.min,
        reverse=True,
    )
    return [intake_to_dict(row) for row in overdue + waiting]


def missed_purchase_orders(db: Session, now: Optional[datetime] = None) -> List[dict]:
    """PO emails older than four business hours with no sales order."""
    try:
        refresh_missed_purchase_orders(db, now)
        rows = (
            db.query(QuotePoIntake)
            .filter(
                QuotePoIntake.overdue.is_(True),
                QuotePoIntake.status.in_(["review", "shadow", "converting"]),
            )
            .order_by(QuotePoIntake.received_at.asc())
            .all()
        )
    except Exception:
        logger.warning("Missed purchase-order check is not available yet", exc_info=True)
        try:
            db.rollback()
        except Exception:
            pass
        return []
    return [
        {
            "id": row.id,
            "from_address": row.from_address,
            "subject": row.subject,
            "customer_po": row.customer_po,
            "bc_quote_number": row.bc_quote_number,
            "received_at": row.received_at.isoformat() if row.received_at else None,
            "review_reason": row.review_reason,
            "review_reason_text": _reason_text(row.review_reason),
            "status": row.status,
        }
        for row in rows
    ]


def refresh_missed_purchase_orders(db: Session, now: Optional[datetime] = None) -> int:
    """Flag PO emails that still have no sales order after four business hours."""
    moment = now or datetime.utcnow()
    nested = db.begin_nested()
    try:
        rows = (
            db.query(QuotePoIntake)
            .filter(QuotePoIntake.status.in_(["review", "shadow", "converting", "converted", "dismissed"]))
            .all()
        )
    except Exception:
        logger.warning("Purchase-order table is not available yet", exc_info=True)
        nested.rollback()
        return 0
    changed = 0
    for row in rows:
        if row.status in {"converted", "dismissed"} or row.bc_order_number:
            late = False
        else:
            late = business_hours_between(row.received_at or row.created_at, moment) >= MISSED_AFTER_HOURS
        if bool(row.overdue) != late:
            row.overdue = late
            changed += 1
    nested.commit()
    if changed:
        db.commit()
    return changed


def accept_quote_po(
    db: Session,
    intake_id: int,
    *,
    bc_quote_number: Optional[str],
    user_email: str,
) -> dict:
    """Staff convert. Shadow and off do not call Business Central.

    A corrected quote number is the human match. It still has to be an open
    portal quote, and a quote that is already a sales order is not converted
    again. The email is linked to the existing order instead.
    """
    from fastapi import HTTPException

    row = db.query(QuotePoIntake).filter(QuotePoIntake.id == intake_id).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Purchase order email not found")
    if row.status == "converted" and row.bc_order_number:
        return {**intake_to_dict(row), "already": True, "converted": True}
    if row.status == "converting":
        raise HTTPException(status_code=409, detail="This quote is already being converted")
    if row.status not in {"review", "shadow"}:
        raise HTTPException(status_code=400, detail="This purchase order is not waiting for a convert")
    mode = inbox_mode(db, QUOTE_PO_AUTO_CONVERT)
    if mode != "on":
        return {
            **intake_to_dict(row),
            "converted": False,
            "already": False,
            "detail": "Shadow and off do not change Business Central.",
        }
    chosen = (bc_quote_number or "").strip() or row.bc_quote_number
    if not chosen:
        raise HTTPException(status_code=400, detail="Choose which quote to convert")
    quote = _one_quote(db, chosen)
    if quote is None:
        raise HTTPException(status_code=400, detail="That quote is not in the portal")
    closure = _closure(db, quote, datetime.utcnow())
    if closure == "expired":
        raise HTTPException(status_code=400, detail="That quote is expired or closed")
    row.bc_quote_number = quote.bc_quote_id
    row.quote_request_id = quote.id
    row.match_method = "staff"
    if closure == "already_converted":
        order = _sales_order_for(db, quote)
        row.status = "converted"
        row.review_reason = None
        row.bc_order_number = order.bc_order_number if order is not None else row.bc_order_number
        row.bc_order_id = (order.bc_order_id or order.bc_id) if order is not None else row.bc_order_id
        row.overdue = False
        row.decided_at = datetime.utcnow()
        row.decided_by = user_email
        row.planned_action = "Already a sales order. The email was linked. Business Central was not called."
        if row.bc_order_number:
            _notify(db, row, row.bc_order_number)
        db.commit()
        return {**intake_to_dict(row), "already": True, "converted": True}
    try:
        saved = _convert_row(db, row, quote, user_email)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Staff convert failed for purchase order %s", row.id)
        raise HTTPException(status_code=400, detail=f"Could not convert the quote: {exc}")
    return {**intake_to_dict(saved), "already": False, "converted": saved.status == "converted"}


def dismiss_quote_po(db: Session, intake_id: int, *, user_email: str) -> dict:
    from fastapi import HTTPException

    row = db.query(QuotePoIntake).filter(QuotePoIntake.id == intake_id).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Purchase order email not found")
    if row.status == "converted":
        raise HTTPException(status_code=400, detail="This purchase order is already a sales order")
    row.status = "dismissed"
    row.overdue = False
    row.decided_at = datetime.utcnow()
    row.decided_by = user_email
    db.commit()
    return intake_to_dict(row)


def intake_to_dict(row: QuotePoIntake) -> dict:
    return {
        "id": row.id,
        "email_log_id": row.email_log_id,
        "status": row.status,
        "confidence": row.confidence,
        "match_method": row.match_method,
        "review_reason": row.review_reason,
        "review_reason_text": _reason_text(row.review_reason),
        "bc_quote_number": row.bc_quote_number,
        "quote_request_id": row.quote_request_id,
        "candidates": row.candidates or [],
        "customer_po": row.customer_po,
        "po_source": row.po_source,
        "amount_cents": row.amount_cents,
        "line_hints": row.line_hints or [],
        "referenced_quotes": row.referenced_quotes or [],
        "excerpt": row.excerpt,
        "from_address": row.from_address,
        "subject": row.subject,
        "attachment_names": row.attachment_names or [],
        "bc_order_number": row.bc_order_number,
        "planned_action": row.planned_action,
        "overdue": bool(row.overdue),
        "received_at": row.received_at.isoformat() if row.received_at else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def _convert_row(db: Session, row: QuotePoIntake, quote: QuoteRequest, user_email: str) -> QuotePoIntake:
    """Claim the quote, then PATCH its external document number and makeOrder.

    The claim is committed before any Business Central call. A second email
    for the same quote loses the unique converting slot and does not call
    makeOrder.
    """
    intake_id = row.id
    quote_id = quote.id
    sq_number = quote.bc_quote_id
    blocked = _conversion_block(db, quote, row)
    if blocked:
        logger.info(
            "Purchase order %s did not convert %s (%s). Business Central was not called.",
            row.customer_po, sq_number, blocked,
        )
        held = _hold_for_review(db, row, quote, blocked)
        _staff_conflict(user_email, blocked)
        return held
    row.bc_quote_number = sq_number
    row.quote_request_id = quote_id
    row.status = "review"
    db.commit()
    if not _claim_converting(db, intake_id):
        fresh = db.query(QuotePoIntake).filter(QuotePoIntake.id == intake_id).one()
        quote = db.query(QuoteRequest).filter(QuoteRequest.id == quote_id).one()
        reason = "already_converted" if _sales_order_for(db, quote) or (quote.status or "").lower() in _CONVERTED else "converting"
        logger.info(
            "Purchase order %s did not convert %s (%s). Business Central was not called.",
            fresh.customer_po, sq_number, reason,
        )
        held = _hold_for_review(db, fresh, quote, reason)
        _staff_conflict(user_email, reason)
        return held
    quote = db.query(QuoteRequest).filter(QuoteRequest.id == quote_id).one()
    row = db.query(QuotePoIntake).filter(QuotePoIntake.id == intake_id).one()
    blocked = _conversion_block(db, quote, row)
    if blocked:
        logger.info(
            "Purchase order %s did not convert %s (%s). Business Central was not called.",
            row.customer_po, sq_number, blocked,
        )
        held = _hold_for_review(db, row, quote, blocked)
        _staff_conflict(user_email, blocked)
        return held
    try:
        result = _write_po_and_convert(db, quote, row.customer_po, user_email)
    except Exception as exc:
        logger.exception("Purchase order convert failed for %s", row.customer_po)
        db.rollback()
        failed = db.query(QuotePoIntake).filter(QuotePoIntake.id == intake_id).one()
        failed.status = "review"
        failed.confidence = "low"
        message = str(exc)
        if "not an open" in message:
            failed.review_reason = "quote_not_in_bc"
        elif "expired" in message.lower() or "closed" in message.lower():
            failed.review_reason = "expired"
        else:
            failed.review_reason = "convert_failed"
        failed.planned_action = message[:500]
        db.commit()
        if user_email != AUTO_ACTOR:
            raise
        return failed
    row = db.query(QuotePoIntake).filter(QuotePoIntake.id == intake_id).one()
    row.status = "converted"
    row.review_reason = None
    row.confidence = "high"
    row.bc_quote_number = sq_number
    row.quote_request_id = quote_id
    row.bc_order_number = result.get("bc_order_number")
    row.bc_order_id = result.get("bc_order_id")
    row.overdue = False
    row.decided_at = datetime.utcnow()
    row.decided_by = user_email
    row.planned_action = (
        f"Wrote PO {row.customer_po} on {sq_number} and converted it to {row.bc_order_number}."
    )
    if row.bc_order_number:
        _notify(db, row, row.bc_order_number)
    db.commit()
    logger.info(
        "Converted %s to %s from purchase order %s",
        sq_number, row.bc_order_number, row.customer_po,
    )
    return row


def _conversion_block(db: Session, quote: QuoteRequest, row: QuotePoIntake) -> Optional[str]:
    """A reason to stop before makeOrder, or None when this row may claim the quote."""
    prior = _sales_order_for(db, quote)
    if (prior is not None and prior.bc_order_number) or (quote.status or "").lower() in _CONVERTED:
        return "already_converted"
    number = (quote.bc_quote_id or "").strip()
    if not number:
        return "quote_not_in_portal"
    holder = (
        db.query(QuotePoIntake)
        .filter(
            QuotePoIntake.id != row.id,
            QuotePoIntake.bc_quote_number == number,
            QuotePoIntake.status.in_(["converting", "converted"]),
        )
        .first()
    )
    if holder is None:
        return None
    if holder.status == "converted" or holder.bc_order_number:
        return "already_converted"
    return "converting"


def _hold_for_review(db: Session, row: QuotePoIntake, quote: QuoteRequest, reason: str) -> QuotePoIntake:
    """Leave the email for staff. This does not call Business Central."""
    row.status = "review"
    row.confidence = "low"
    row.review_reason = reason
    row.bc_quote_number = quote.bc_quote_id
    row.quote_request_id = quote.id
    if reason == "already_converted":
        row.planned_action = "This quote is already a sales order. Business Central was not called."
    elif reason == "converting":
        row.planned_action = "Another email is already converting this quote. Business Central was not called."
    else:
        row.planned_action = _reason_text(reason)
    db.commit()
    return row


def _staff_conflict(user_email: str, reason: str) -> None:
    """Staff who lose the quote get 409. The inbox path only logs and reviews."""
    if user_email == AUTO_ACTOR:
        return
    from fastapi import HTTPException
    if reason == "already_converted":
        detail = "This quote is already a sales order."
    else:
        detail = "This quote is already being converted."
    raise HTTPException(status_code=409, detail=detail)


def _claim_converting(db: Session, intake_id: int) -> bool:
    """Commit status=converting for this row before makeOrder.

    The partial unique index on bc_quote_number lets one row per quote hold
    converting or converted. The losing update raises IntegrityError before
    commit on PostgreSQL. Either failure rolls back and makes no BC call.
    """
    try:
        claimed = (
            db.query(QuotePoIntake)
            .filter(
                QuotePoIntake.id == intake_id,
                QuotePoIntake.status.in_(["review", "shadow"]),
            )
            .update({"status": "converting"}, synchronize_session=False)
        )
    except IntegrityError:
        logger.info("Purchase order row %s lost the convert claim on update", intake_id)
        db.rollback()
        return False
    if claimed != 1:
        db.rollback()
        return False
    try:
        db.commit()
    except IntegrityError:
        logger.info("Purchase order row %s lost the convert claim on commit", intake_id)
        db.rollback()
        return False
    return True


def _write_po_and_convert(db: Session, quote: QuoteRequest, customer_po: Optional[str], user_email: str) -> dict:
    """The only Business Central writes on this path.

    1. PATCH salesQuotes({id}) externalDocumentNumber with the customer PO.
    2. OrderLifecycleService.convert_quote_to_order, which posts makeOrder.
    """
    from app.integrations.bc.client import bc_client
    from app.services.order_lifecycle_service import OrderLifecycleService

    number = quote.bc_quote_id
    found = bc_client.get_sales_quote_by_number(number)
    if not found or not found.get("id"):
        raise RuntimeError(f"Quote {number} is not an open Business Central sales quote")
    status = str(found.get("status") or "").strip().lower()
    if status in _BC_CLOSED:
        raise RuntimeError(f"Quote {number} is {status} in Business Central")
    if customer_po:
        bc_client.update_sales_quote(
            found["id"],
            {"externalDocumentNumber": customer_po},
            etag=found.get("@odata.etag") or "*",
        )
    result = OrderLifecycleService().convert_quote_to_order(
        db,
        quote.id,
        user_email,
        allow_manual_fallback=False,
    )
    if result.get("already") and result.get("bc_order_number"):
        return result
    if not result.get("success"):
        raise RuntimeError(result.get("error") or "Convert failed")
    return result


def _notify(db: Session, row: QuotePoIntake, so_number: str) -> None:
    """Link the email on the order timeline and leave an in-portal notice."""
    body = (
        f"Customer purchase order {row.customer_po} from {row.from_address} "
        f"on {row.bc_quote_number} is sales order {so_number}."
    )
    nested = db.begin_nested()
    try:
        from app.services.ops_tracker_service import Actor, record_activity
        record_activity(
            db,
            event_type="customer_po",
            body=body,
            so_number=so_number,
            dedupe_key=f"quote-po:{row.graph_message_id or row.id}",
            message_id=row.graph_message_id,
            direction="inbound",
            actor=Actor(email="quote-po", source="system"),
        )
        nested.commit()
    except Exception:
        logger.exception("Could not link purchase order %s on %s", row.customer_po, so_number)
        nested.rollback()
    nested = db.begin_nested()
    try:
        from app.db.models import OpsActionItem
        key = f"quote-po-converted:{row.graph_message_id or row.id}"
        existing = db.query(OpsActionItem).filter(OpsActionItem.auto_key == key).one_or_none()
        if existing is None:
            db.add(OpsActionItem(
                kind="quote_po_converted",
                auto_key=key,
                auto_managed=False,
                title=f"PO {row.customer_po} converted {row.bc_quote_number} to {so_number}",
                detail=row.subject or row.from_address,
                so_number=so_number,
                status="open",
                source_ref=row.graph_message_id,
                created_at=datetime.utcnow(),
            ))
            db.flush()
        nested.commit()
    except Exception:
        logger.exception("Could not notify staff about purchase order %s", row.customer_po)
        nested.rollback()


def _insert_row(db, *, email_log, subject, from_address, graph_message_id, mailbox, received_at, facts, match, excerpt):
    quote = match.get("quote")
    row = QuotePoIntake(
        graph_message_id=(graph_message_id or None),
        email_log_id=email_log.id if email_log is not None else None,
        mailbox=mailbox,
        from_address=from_address,
        subject=subject,
        received_at=_naive_utc(received_at) if received_at else datetime.utcnow(),
        customer_po=facts["po_number"],
        po_source=facts["po_source"],
        referenced_quotes=facts["sq_numbers"],
        amount_cents=facts["amount_cents"],
        line_hints=facts["line_hints"],
        excerpt=excerpt,
        attachment_names=facts["filenames"],
        status="review",
        review_reason=match.get("reason"),
        confidence=match["confidence"],
        match_method=match.get("method"),
        bc_quote_number=quote.bc_quote_id if quote is not None and match["confidence"] == "high" else None,
        quote_request_id=quote.id if quote is not None and match["confidence"] == "high" else None,
        candidates=match.get("candidates") or [],
        planned_action=_plan(match, facts, acted=False),
        overdue=False,
        created_at=datetime.utcnow(),
    )
    nested = db.begin_nested()
    try:
        db.add(row)
        db.flush()
        nested.commit()
    except IntegrityError:
        nested.rollback()
        logger.info("Purchase order email %s was already stored", graph_message_id)
        return None
    return row


def _match_quote(db: Session, from_address: str, facts: dict, now: datetime) -> dict:
    numbers = facts["sq_numbers"]
    if len(numbers) > 1:
        return _low("ambiguous", "ambiguous", _candidates_for_numbers(db, numbers))
    if len(numbers) == 1:
        return _match_exact_number(db, from_address, numbers[0], facts, now)
    return _match_by_customer(db, from_address, facts, now)


def _match_exact_number(db, from_address, number, facts, now) -> dict:
    rows = _rows_for_numbers(db, [number])
    if not rows:
        return _low("quote_not_in_portal", "number", [])
    owned = [row for row in rows if _same_customer(db, row, from_address)]
    others = [row for row in rows if row not in owned]
    if not owned and others:
        return _low("cross_customer", "number", [_candidate(row, "number") for row in others])
    if len(owned) != 1:
        return _low("ambiguous", "number", [_candidate(row, "number") for row in owned])
    quote = owned[0]
    closure = _closure(db, quote, now)
    if closure:
        return _low(closure, "number", [_candidate(quote, "number")])
    if _quote_amount_cents(quote) is None and not _quote_skus(quote):
        return _low("unverified_quote", "number", [_candidate(quote, "number")])
    problem = _amount_or_lines(quote, facts)
    if problem:
        return _low(problem, "number", [_candidate(quote, "number")])
    return _high(quote, "exact_quote")


def _match_by_customer(db, from_address, facts, now) -> dict:
    open_rows = _open_quotes_for_sender(db, from_address, now)
    if not open_rows:
        any_known = _rows_for_sender(db, from_address)
        if not any_known:
            return _low("unknown_sender", "customer", [])
        return _low("no_unique_quote", "customer", [])
    if facts["amount_conflict"]:
        return _low("mismatched_total", "customer", [_candidate(row, "customer") for row in open_rows])
    if facts["amount_cents"] is None and not facts["line_hints"]:
        reason = "ambiguous" if len(open_rows) > 1 else "no_unique_quote"
        return _low(reason, "customer", [_candidate(row, "customer") for row in open_rows])
    amount_hits = []
    for quote in open_rows:
        if facts["amount_cents"] is None:
            amount_hits.append(quote)
            continue
        quoted = _quote_amount_cents(quote)
        if quoted is not None and quoted == facts["amount_cents"]:
            amount_hits.append(quote)
    if facts["amount_cents"] is not None and not amount_hits:
        return _low("mismatched_total", "customer", [_candidate(row, "customer") for row in open_rows])
    matched = []
    unverified = False
    for quote in amount_hits:
        if not facts["line_hints"]:
            matched.append(quote)
            continue
        skus = _quote_skus(quote)
        if not skus:
            unverified = True
            continue
        if _lines_overlap(facts["line_hints"], skus):
            matched.append(quote)
    if len(matched) == 1:
        return _high(matched[0], "customer_amount")
    if len(matched) > 1:
        return _low("ambiguous", "customer", [_candidate(row, "customer") for row in matched])
    if unverified:
        return _low("lines_unverified", "customer", [_candidate(row, "customer") for row in amount_hits])
    return _low("mismatched_lines", "customer", [_candidate(row, "customer") for row in amount_hits])


def _amount_or_lines(quote: QuoteRequest, facts: dict) -> Optional[str]:
    if facts["amount_conflict"]:
        return "mismatched_total"
    if facts["amount_cents"] is not None:
        quoted = _quote_amount_cents(quote)
        if quoted is not None and quoted != facts["amount_cents"]:
            return "mismatched_total"
    if facts["line_hints"]:
        skus = _quote_skus(quote)
        if skus and not _lines_overlap(facts["line_hints"], skus):
            return "mismatched_lines"
    return None


def _open_quotes_for_sender(db, from_address, now) -> List[QuoteRequest]:
    found = []
    for row in _rows_for_sender(db, from_address):
        if _closure(db, row, now):
            continue
        if not _same_customer(db, row, from_address):
            continue
        found.append(row)
    return found


def _rows_for_sender(db, from_address) -> List[QuoteRequest]:
    from sqlalchemy import func, or_

    from app.services.quote_followup import _company_domain, _email_domain

    wanted = (from_address or "").strip().lower()
    if not wanted:
        return []
    domain = _email_domain(wanted)
    filters = [func.lower(QuoteRequest.contact_email) == wanted]
    if _company_domain(domain):
        filters.append(QuoteRequest.contact_email.ilike(f"%@{domain}"))
    return (
        db.query(QuoteRequest)
        .filter(QuoteRequest.bc_quote_id.isnot(None))
        .filter(or_(*filters))
        .order_by(QuoteRequest.created_at.desc())
        .limit(200)
        .all()
    )


def _closure(db, quote: QuoteRequest, now: datetime) -> Optional[str]:
    status = (quote.status or "").strip().lower()
    if status in _CONVERTED:
        return "already_converted"
    order = _sales_order_for(db, quote)
    if order is not None and (order.bc_order_number or order.bc_order_id or order.bc_id):
        return "already_converted"
    if status in _CLOSED:
        return "expired"
    data = quote.parsed_data if isinstance(quote.parsed_data, dict) else {}
    until = data.get("valid_until") or data.get("validUntil")
    if until:
        try:
            stamp = _naive_utc(datetime.fromisoformat(str(until).replace("Z", "+00:00")))
        except ValueError:
            stamp = None
        if stamp is not None and stamp < _naive_utc(now):
            return "expired"
    return None


def _sales_order_for(db, quote: QuoteRequest) -> Optional[SalesOrder]:
    nested = db.begin_nested()
    try:
        row = (
            db.query(SalesOrder)
            .filter(SalesOrder.quote_request_id == quote.id)
            .order_by(SalesOrder.id.desc())
            .first()
        )
        nested.commit()
        return row
    except Exception:
        logger.warning("Could not read sales orders for quote %s", quote.id, exc_info=True)
        nested.rollback()
        return None


def _quote_amount_cents(quote: QuoteRequest) -> Optional[int]:
    data = quote.parsed_data if isinstance(quote.parsed_data, dict) else {}
    for key in ("total", "total_amount", "quote_total", "totalAmountIncludingTax", "amount"):
        cents = _cents(data.get(key))
        if cents is not None:
            return cents
    try:
        items = list(quote.quote_items or [])
    except Exception:
        items = []
    total = 0
    found = False
    for item in items:
        cents = _cents(getattr(item, "total_price", None))
        if cents is None:
            continue
        total += cents
        found = True
    return total if found else None


def _quote_skus(quote: QuoteRequest) -> set:
    found = set()
    data = quote.parsed_data if isinstance(quote.parsed_data, dict) else {}
    for door in data.get("doors") or []:
        if isinstance(door, dict):
            for key in ("model", "part", "sku", "product_code"):
                sku = _norm_sku(door.get(key))
                if sku:
                    found.add(sku)
    for line in data.get("lines") or []:
        if isinstance(line, dict):
            sku = _norm_sku(line.get("sku") or line.get("product_code") or line.get("item"))
            if sku:
                found.add(sku)
    try:
        items = list(quote.quote_items or [])
    except Exception:
        items = []
    for item in items:
        sku = _norm_sku(getattr(item, "product_code", None))
        if sku:
            found.add(sku)
    return found


def _lines_overlap(hints: List[dict], skus: set) -> bool:
    """Every PO sku is on the quote. One shared sku is not enough to auto-select."""
    wanted = {_norm_sku(item.get("sku")) for item in hints}
    wanted.discard("")
    if not wanted or not skus:
        return False
    return all(hint in skus for hint in wanted)


def _read_facts(text: str, po_number: str, po_source: Optional[str], filenames: List[str]) -> dict:
    totals = []
    for raw in _TOTAL_RE.findall(text or ""):
        cents = _cents(raw)
        if cents is not None and cents not in totals:
            totals.append(cents)
    hints = []
    seen = set()
    for _qty, sku in _LINE_RE.findall(text or ""):
        key = _norm_sku(sku)
        if not key or key.startswith("SQ") or key in seen:
            continue
        seen.add(key)
        hints.append({"qty": _qty, "sku": key})
    for sku in _ITEM_RE.findall(text or ""):
        key = _norm_sku(sku)
        if not key or key.startswith("SQ") or key in seen:
            continue
        seen.add(key)
        hints.append({"qty": None, "sku": key})
    return {
        "po_number": po_number,
        "po_source": po_source,
        "sq_numbers": _sq_numbers(text),
        "amount_cents": totals[0] if len(totals) == 1 else None,
        "amount_conflict": len(totals) > 1,
        "line_hints": hints,
        "filenames": list(filenames),
    }


def _po_number(subject: str, body: str, attachment_text: str, filenames: List[str]):
    """Read the PO number from one field at a time.

    Joining the subject onto the body lets a subject of "Purchase order"
    swallow the first word of the body, so the number is never seen.
    """
    visible = fresh_message_text(body or "")
    number, source = customer_po_number(visible, filenames)
    if number:
        return number, source
    number, source = customer_po_number(subject or "", [])
    if number:
        return number, "subject" if source == "body" else source
    if attachment_text:
        number, source = customer_po_number(attachment_text, [])
        if number:
            return number, "attachment text" if source == "body" else source
    return None, None


def _visible_text(subject: str, body: str, attachment_text: str) -> str:
    visible = fresh_message_text(body or "")
    parts = [subject or "", visible, attachment_text or ""]
    return "\n".join(part for part in parts if part).strip()


def _candidates_for_numbers(db, numbers) -> List[dict]:
    return [_candidate(row, "number") for row in _rows_for_numbers(db, numbers)]


def _candidate(row: QuoteRequest, method: str) -> dict:
    return {
        "bc_quote_number": row.bc_quote_id,
        "quote_request_id": row.id,
        "customer_name": row.customer_name,
        "method": method,
    }


def _high(quote: QuoteRequest, method: str) -> dict:
    return {
        "confidence": "high",
        "method": method,
        "reason": None,
        "quote": quote,
        "candidates": [_candidate(quote, method)],
    }


def _low(reason: str, method: str, candidates: List[dict]) -> dict:
    return {
        "confidence": "low",
        "method": method,
        "reason": reason,
        "quote": None,
        "candidates": candidates,
    }


def _plan(match: dict, facts: dict, acted: bool) -> str:
    po = facts["po_number"]
    quote = match.get("quote")
    if match["confidence"] == "high" and quote is not None:
        verb = "Wrote" if acted else "Would write"
        convert = "converted" if acted else "convert"
        return (
            f"{verb} PO {po} on {quote.bc_quote_id} as the external document number "
            f"and {convert} that quote to a sales order."
        )
    return f"Leave this for staff. {_reason_text(match.get('reason'))}"


def _reason_text(reason: Optional[str]) -> Optional[str]:
    if not reason:
        return None
    return REASON_TEXT.get(reason, reason)


def _one_quote(db, number: str) -> Optional[QuoteRequest]:
    rows = _rows_for_numbers(db, [number])
    return rows[0] if rows else None


def _by_graph_id(db, graph_message_id: Optional[str]) -> Optional[QuotePoIntake]:
    if not graph_message_id:
        return None
    return (
        db.query(QuotePoIntake)
        .filter(QuotePoIntake.graph_message_id == graph_message_id)
        .first()
    )


def _cents(value) -> Optional[int]:
    if value is None or isinstance(value, bool):
        return None
    text = str(value).strip().replace("$", "").replace(",", "")
    if not text:
        return None
    try:
        return int((Decimal(text) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    except Exception:
        return None


def _norm_sku(value) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(value or "").upper())


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _naive_utc(value: datetime) -> datetime:
    return _as_utc(value).replace(tzinfo=None)
