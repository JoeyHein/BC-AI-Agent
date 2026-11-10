"""Missing-info replies, quote-send drafts, and customer approval detection.

Drafts land in the order-tracker approval queue. Nothing in this module
sends mail or converts a quote. Shadow writes a note on the quote and
stops there.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta
from typing import Any, List, Optional

from sqlalchemy.orm import Session

from app.db.models import CustomerOrderApproval, EmailLog, OpsOutboundMessage, QuoteRequest
from app.services.email_text import fresh_message_text, reply_recipient
from app.services.inbox_settings import (
    CUSTOMER_APPROVAL,
    MISSING_INFO_REPLY,
    QUOTE_SEND_DRAFT,
    inbox_mode,
)

logger = logging.getLogger(__name__)

_SQ_RE = re.compile(r"\bSQ-?\d{3,}\b", re.I)
_STRONG_RE = re.compile(
    r"\b(?:go ahead|po attached|purchase order attached|please proceed|we accept(?: the quote)?)\b",
    re.I,
)
_GO_AHEAD_CHANGE = re.compile(
    r"\bgo ahead\b(?:\s+and)?\s+(?:change|revise|update|modify|adjust)\b",
    re.I,
)
_NEGATED_APPROVAL = re.compile(
    r"\b(?:not|never|no|n't)\b(?:\s+\w+){0,3}\s+approved\b|\bapproved\b(?:\s+\w+){0,2}\s+yet\b",
    re.I,
)
_PREVIOUS_SQ = re.compile(
    r"\b(?:previous|last|old|earlier|prior)\b.{0,60}\bSQ-?\d+\b|\bSQ-?\d+\b.{0,40}\bwas approved\b",
    re.I,
)
_APPROVED_RE = re.compile(r"\bapproved\b", re.I)
_NEW_QUOTE_RE = re.compile(r"\b(?:please quote|need a quote|quote request|rfq|request for quote)\b", re.I)
_PO_FILE_RE = re.compile(r"\bPO[-_\s]?([A-Z0-9]*\d[A-Z0-9\-]*)", re.I)
_PO_BODY_RE = re.compile(
    r"\b(?:P\.?O\.?|purchase order)(?:\s+(?:number|no\.?|#|is))?\s*[:#]?\s*([A-Z0-9][A-Z0-9\-]{2,})",
    re.I,
)
_SIZE_HINT_RE = re.compile(r"\d\s*(?:'|ft|feet|x|×)", re.I)

_ASSUMPTION_FIELDS = (
    ("doorSeries", "Series"),
    ("panelColor", "Colour"),
    ("panelDesign", "Panel design"),
    ("trackMount", "Track mount"),
    ("trackThickness", "Track size"),
    ("trackRadius", "Track radius"),
    ("liftType", "Lift"),
    ("deliveryType", "Delivery"),
)


def is_customer_approval(category: str, subject: str, body: str) -> bool:
    """True when the new writing is a go-ahead, not a change or a new request.

    Quoted older mail is ignored. "Not approved yet" and "go ahead and
    change the colour" are not approvals. A new request that mentions an
    older SQ having been approved is not an approval either.
    """
    text = fresh_message_text(f"{subject or ''}\n{body or ''}")
    if _NEGATED_APPROVAL.search(text) or _GO_AHEAD_CHANGE.search(text):
        return False
    new_request = bool(_NEW_QUOTE_RE.search(text) or _SIZE_HINT_RE.search(text))
    if new_request and _PREVIOUS_SQ.search(text):
        return False
    if new_request and category in {"quote_request", "quote_modification", ""}:
        return False
    has_sq = _SQ_RE.search(text) is not None
    strong = _STRONG_RE.search(text) is not None
    approved = _APPROVED_RE.search(text) is not None
    if category == "order_confirmation" and (strong or approved or has_sq):
        return True
    if category == "order_confirmation":
        return False
    if strong:
        return True
    return bool(approved and has_sq)


def handle_customer_approval(
    db: Session,
    email_log: EmailLog,
    *,
    subject: str,
    body: str,
    from_address: str,
    graph_message_id: Optional[str] = None,
    mailbox: Optional[str] = None,
    filenames: Optional[List[str]] = None,
) -> Optional[CustomerOrderApproval]:
    """Queue a convert-to-SO, or log the match when the switch is shadow.

    Off does nothing. This never calls Business Central.
    """
    mode = inbox_mode(db, CUSTOMER_APPROVAL)
    if mode == "off":
        return None
    text = fresh_message_text(f"{subject or ''}\n{body or ''}")
    candidates = match_sales_quotes(db, text, from_address, subject, email_log.id)
    po_number, po_source = customer_po_number(text, filenames or [])
    payload = {
        "match_method": _match_method(candidates),
        "bc_quote_number": candidates[0]["bc_quote_number"] if len(candidates) == 1 else None,
        "candidates": candidates,
        "customer_po": po_number,
        "po_source": po_source,
        "from_address": from_address,
        "subject": subject,
    }
    if mode == "shadow":
        logger.info(
            "Customer approval shadow for %s: %s candidate(s), po=%s. No convert row created.",
            from_address, len(candidates), po_number,
        )
        _shadow_note(email_log, "customer_approval", payload)
        return None
    existing = (
        db.query(CustomerOrderApproval)
        .filter(CustomerOrderApproval.email_log_id == email_log.id)
        .first()
    )
    if existing is not None:
        return existing
    duplicate = _duplicate_approval(db, candidates)
    if duplicate is not None:
        return duplicate
    status, chosen_sq = _decision(candidates)
    row = CustomerOrderApproval(
        email_log_id=email_log.id,
        status=status,
        match_method=payload["match_method"],
        bc_quote_number=chosen_sq,
        quote_request_id=candidates[0].get("quote_request_id") if status == "ready" else None,
        candidates=candidates,
        customer_po=po_number,
        po_source=po_source,
        excerpt=text[:500],
        from_address=from_address,
        subject=subject,
        graph_message_id=graph_message_id,
        mailbox=mailbox,
        created_at=datetime.utcnow(),
    )
    db.add(row)
    db.flush()
    logger.info(
        "Queued convert-to-SO %s status=%s sq=%s",
        row.id, status, row.bc_quote_number,
    )
    return row


def match_sales_quotes(
    db: Session,
    text: str,
    from_address: str,
    subject: str,
    email_log_id: Optional[int],
) -> List[dict]:
    numbered = _quotes_for_numbers(db, _sq_numbers(text), from_address)
    if numbered:
        return numbered
    threaded = _quotes_on_thread(db, from_address, subject, email_log_id)
    if threaded:
        return threaded
    # A recent quote is a suggestion. It is never a ready match on its own.
    return _recent_customer_quotes(db, from_address)


def customer_po_number(text: str, filenames: List[str]):
    text = fresh_message_text(text or "")
    for name in filenames:
        match = _PO_FILE_RE.search(name or "")
        if match and re.search(r"\d", match.group(1)):
            return match.group(1), f"attachment {name}"
    for match in _PO_BODY_RE.finditer(text or ""):
        token = match.group(1)
        if re.search(r"\d", token) and not token.upper().startswith("SQ"):
            return token, "body"
    return None, None


def settle_quote_followups(
    db: Session,
    quote: QuoteRequest,
    email_log: Optional[EmailLog],
    *,
    mailbox: Optional[str] = None,
    graph_message_id: Optional[str] = None,
) -> None:
    """Draft the follow-up that matches the quote's final status. Never sends."""
    if quote.status in {"needs_manual_review", "low_confidence"}:
        queue_missing_info(db, quote, email_log, mailbox=mailbox, graph_message_id=graph_message_id)
    if quote.status == "bc_created" and quote.bc_quote_id:
        queue_quote_send(db, quote, email_log, mailbox=mailbox, graph_message_id=graph_message_id)


def queue_quote_send_for(db: Session, quote: QuoteRequest) -> Optional[OpsOutboundMessage]:
    email_log = None
    if quote.email_id:
        email_log = db.query(EmailLog).filter(EmailLog.id == quote.email_id).first()
    mail = (quote.parsed_data or {}).get("mail") or {}
    return queue_quote_send(
        db,
        quote,
        email_log,
        mailbox=mail.get("mailbox"),
        graph_message_id=mail.get("graph_message_id"),
    )


def queue_missing_info(
    db: Session,
    quote: QuoteRequest,
    email_log: Optional[EmailLog],
    *,
    mailbox: Optional[str] = None,
    graph_message_id: Optional[str] = None,
) -> Optional[OpsOutboundMessage]:
    mode = inbox_mode(db, MISSING_INFO_REPLY)
    if mode == "off":
        return None
    unknowns, assumptions = describe_gaps(db, quote, email_log)
    if not unknowns and not assumptions:
        logger.info("Quote %s needs review but nothing is unknown or assumed", quote.id)
        return None
    subject = email_log.subject if email_log and email_log.subject else "your quote"
    body = missing_info_body(quote.customer_name, unknowns, assumptions)
    to_email, forwarded = _draft_recipient(email_log, quote.contact_email)
    reply_subject = f"Re: {subject}"
    payload = {
        "unknowns": unknowns,
        "assumptions": assumptions,
        "subject": f"Re: {subject}",
        "body": body,
    }
    if mode == "shadow":
        logger.info(
            "Missing-info shadow for quote %s: %s unknown, %s assumed. No draft created.",
            quote.id, len(unknowns), len(assumptions),
        )
        _shadow_on_quote(quote, "missing_info_reply", payload)
        return None
    return _queue_message(
        db,
        kind="missing_info_reply",
        dedupe=f"missing-info:{quote.id}",
        to_email=to_email,
        subject=reply_subject,
        body=body,
        context={
            "trigger": "missing_info",
            "quote_request_id": quote.id,
            "reply_to_message_id": None if forwarded else graph_message_id,
            "reply_to_address": to_email,
            "reply_subject": reply_subject,
            "forwarded": forwarded,
            "mailbox": mailbox,
            "unknowns": unknowns,
            "assumptions": assumptions,
            "reason": "Waiting on the customer for the details we could not fill in.",
        },
    )


def queue_quote_send(
    db: Session,
    quote: QuoteRequest,
    email_log: Optional[EmailLog],
    *,
    mailbox: Optional[str] = None,
    graph_message_id: Optional[str] = None,
) -> Optional[OpsOutboundMessage]:
    mode = inbox_mode(db, QUOTE_SEND_DRAFT)
    if mode == "off" or not quote.bc_quote_id:
        return None
    assumptions, deviations = _quote_notes(quote)
    subject_src = email_log.subject if email_log and email_log.subject else "your quote"
    body = quote_send_body(quote.bc_quote_id, assumptions)
    to_email, forwarded = _draft_recipient(email_log, quote.contact_email)
    reply_subject = f"Re: {subject_src}"
    payload = {"subject": f"Quote {quote.bc_quote_id}", "body": body, "bc_quote_number": quote.bc_quote_id}
    if mode == "shadow":
        logger.info(
            "Quote-send shadow for %s on quote %s. No draft created.",
            quote.bc_quote_id, quote.id,
        )
        _shadow_on_quote(quote, "quote_send", payload)
        return None
    return _queue_message(
        db,
        kind="quote_send",
        dedupe=f"quote-send:{quote.id}:{quote.bc_quote_id}",
        to_email=to_email,
        subject=reply_subject,
        body=body,
        context={
            "trigger": "quote_send",
            "quote_request_id": quote.id,
            "bc_quote_number": quote.bc_quote_id,
            "attach_quote_pdf": True,
            "reply_to_message_id": None if forwarded else graph_message_id,
            "reply_to_address": to_email,
            "reply_subject": reply_subject,
            "forwarded": forwarded,
            "mailbox": mailbox,
            "assumptions": assumptions,
            "deviations": [item.get("reason") for item in deviations if isinstance(item, dict) and item.get("reason")],
            "reason": f"{quote.bc_quote_id} is ready. The PDF is attached when this is approved.",
        },
    )


def missing_info_body(customer_name: Optional[str], unknowns: List[str], assumptions: List[str]) -> str:
    who = customer_name or "there"
    lines = [f"Hi {who},", "", "Thanks for the request."]
    if unknowns:
        lines.append("We still need:")
        lines.extend(f"- {item}" for item in unknowns)
        lines.append("")
    if assumptions:
        lines.append("If we don't hear back, we will assume:")
        lines.extend(f"- {item}" for item in assumptions)
        lines.append("")
    lines.append("Reply on this thread and we will update the quote before it is sent.")
    lines.append("")
    lines.append("Open Distribution")
    return "\n".join(lines)


def quote_send_body(sq_number: str, assumptions: List[str], deviations: Optional[List[dict]] = None) -> str:
    """Customer-facing note. Deviation reasons stay off this draft.

    ``deviations`` is accepted so older callers still work. The reasons are
    an internal note on the approval card, not something the customer sees.
    """
    del deviations
    lines = [
        "Hi,",
        "",
        f"Attached is quote {sq_number}.",
    ]
    public = [item for item in assumptions if item and "locked" not in item.lower() and "standard is" not in item.lower()]
    if public:
        lines.append("")
        lines.append("We assumed:")
        lines.extend(f"- {item}" for item in public)
    lines.extend(["", "Reply on this thread if anything should change.", "", "Open Distribution"])
    return "\n".join(lines)


def describe_gaps(db: Session, quote: QuoteRequest, email_log: Optional[EmailLog]):
    """What the email did not say, after the profile fills what it knows."""
    from app.services.customer_profile_service import (
        _label,
        _system_default,
        analyse_email,
        apply_customer_profile,
        get_profile,
        quote_email_text,
    )
    subject = email_log.subject if email_log else ""
    body = email_log.body if email_log else ""
    attachments = email_log.attachments if email_log else None
    text = quote_email_text(subject or "", body or "", attachments)
    parsed = (quote.parsed_data or {}).get("doors") or []
    if not isinstance(parsed, list):
        parsed = []
    mapped = []
    mapping = (quote.parsed_data or {}).get("configurator_mapping") or {}
    if isinstance(mapping, dict):
        mapped = [door for door in (mapping.get("doors") or []) if isinstance(door, dict)]
    doors = mapped or [door for door in parsed if isinstance(door, dict)]
    customer_id = quote.matched_bc_customer_id
    profile = get_profile(db, customer_id) if customer_id else None
    readings = analyse_email(text, parsed[0] if parsed and isinstance(parsed[0], dict) else None)
    applied = None
    if doors:
        applied = apply_customer_profile(
            [dict(door) for door in doors],
            profile=profile,
            email_text=text,
            parsed_doors=parsed if parsed else None,
            customer_name=quote.customer_name,
        )
    unknowns = []
    assumptions = []
    if not _has_size(doors, parsed):
        unknowns.append("the width and height of each opening")
    door = (applied or {}).get("doors", [{}])[0] if applied else (doors[0] if doors else {})
    sources = ((applied or {}).get("field_sources") or {}).get("doors") or [{}]
    door_sources = sources[0] if sources else {}
    delivery = ((applied or {}).get("field_sources") or {}).get("deliveryType") or {}
    for key, label in _ASSUMPTION_FIELDS:
        if key == "deliveryType":
            reading = readings.get("deliveryType") or {}
            entry = delivery
            value = (applied or {}).get("delivery_type") or entry.get("used") or entry.get("value")
        else:
            reading = readings.get(key) or {}
            entry = door_sources.get(key) or {}
            value = door.get(key)
            if value in (None, "", []):
                value = entry.get("used") if entry else None
            if value in (None, "", []):
                value = _system_default(key, door or {})
        if reading.get("basis") == "explicit":
            continue
        if key in {"panelColor", "panelDesign", "trackMount", "trackThickness", "trackRadius", "liftType", "doorSeries"} and reading.get("basis") == "explicit":
            continue
        if value in (None, "", [], False):
            if key == "doorSeries":
                unknowns.append("which door series")
            continue
        source = entry.get("source")
        if source == "profile":
            assumptions.append(f"{label}: {_label(value)} (from this customer's usual order)")
        else:
            assumptions.append(f"{label}: {_label(value)} (our standard if you don't say otherwise)")
    return unknowns, assumptions


def convert_customer_approval(
    db: Session,
    approval_id: int,
    *,
    bc_quote_number: Optional[str],
    user_email: str,
) -> dict:
    """Turn one approved SQ into a sales order. A second call returns the first order."""
    from fastapi import HTTPException

    row = db.query(CustomerOrderApproval).filter(CustomerOrderApproval.id == approval_id).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Approval not found")
    if row.status == "converted" and row.bc_order_number:
        return _approval_result(row, already=True)
    if row.status == "converting":
        raise HTTPException(status_code=409, detail="This approval is already being converted")
    if row.status not in {"ready", "needs_choice"}:
        raise HTTPException(status_code=400, detail="This approval is not waiting for a convert")
    chosen = (bc_quote_number or "").strip() or row.bc_quote_number
    candidates = row.candidates or []
    if row.status == "needs_choice" and not chosen:
        raise HTTPException(status_code=400, detail="Choose which quote to convert")
    if candidates and chosen and not _candidate_has(candidates, chosen):
        raise HTTPException(status_code=400, detail="That quote is not one of the matches")
    if not chosen:
        raise HTTPException(status_code=400, detail="No quote number to convert")
    portal_quote = _quote_by_number(db, chosen)
    if portal_quote is None:
        raise HTTPException(status_code=400, detail="That quote is not in the portal")
    if row.from_address and not _belongs_to_sender(portal_quote, row.from_address):
        raise HTTPException(status_code=400, detail="That quote is not this customer's")
    previous = row.status
    claimed = (
        db.query(CustomerOrderApproval)
        .filter(
            CustomerOrderApproval.id == row.id,
            CustomerOrderApproval.status == previous,
        )
        .update({"status": "converting"}, synchronize_session=False)
    )
    db.commit()
    if claimed != 1:
        db.refresh(row)
        if row.status == "converted" and row.bc_order_number:
            return _approval_result(row, already=True)
        raise HTTPException(status_code=409, detail="This approval is already being converted")
    db.refresh(row)
    try:
        order = _convert_sq(db, row, chosen, user_email)
    except HTTPException:
        _restore_approval(db, row.id, previous)
        raise
    except Exception as exc:
        logger.exception("Convert failed for approval %s", approval_id)
        _restore_approval(db, row.id, previous)
        raise HTTPException(status_code=400, detail=f"Could not convert the quote: {exc}")
    row.status = "converted"
    row.bc_quote_number = chosen
    row.bc_order_number = order.get("bc_order_number")
    row.decided_at = datetime.utcnow()
    row.decided_by = user_email
    db.commit()
    return _approval_result(row, already=bool(order.get("already")))


def approval_to_dict(row: CustomerOrderApproval) -> dict:
    return {
        "id": row.id,
        "email_log_id": row.email_log_id,
        "status": row.status,
        "match_method": row.match_method,
        "bc_quote_number": row.bc_quote_number,
        "quote_request_id": row.quote_request_id,
        "candidates": row.candidates or [],
        "customer_po": row.customer_po,
        "po_source": row.po_source,
        "excerpt": row.excerpt,
        "from_address": row.from_address,
        "subject": row.subject,
        "bc_order_number": row.bc_order_number,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def _approval_result(row: CustomerOrderApproval, already: bool) -> dict:
    payload = approval_to_dict(row)
    payload["already"] = already
    payload["priced"] = False
    return payload


def _convert_sq(db: Session, row: CustomerOrderApproval, sq_number: str, user_email: str) -> dict:
    from app.integrations.bc.client import bc_client
    from app.services.order_lifecycle_service import OrderLifecycleService

    quote = _quote_by_number(db, sq_number)
    if quote is not None:
        if not quote.bc_quote_id:
            quote.bc_quote_id = sq_number
            db.flush()
        result = OrderLifecycleService().convert_quote_to_order(db, quote.id, user_email)
        if result.get("already") and result.get("bc_order_number"):
            return {
                "bc_order_number": result.get("bc_order_number"),
                "bc_order_id": result.get("bc_order_id"),
                "already": True,
            }
        if not result.get("success"):
            raise RuntimeError(result.get("error") or "Convert failed")
        order_id = result.get("bc_order_id")
        order_number = result.get("bc_order_number")
    else:
        found = bc_client.get_sales_quote_by_number(sq_number)
        if not found or not found.get("id"):
            raise RuntimeError(f"Quote {sq_number} was not found")
        created = bc_client.convert_quote_to_order(found["id"])
        order_id = created.get("id")
        order_number = created.get("number")
    if row.customer_po and order_id:
        try:
            bc_client.update_sales_order(order_id, {"externalDocumentNumber": row.customer_po})
        except Exception:
            logger.exception("Converted %s but could not write PO %s", sq_number, row.customer_po)
    return {"bc_order_number": order_number, "bc_order_id": order_id}


def _restore_approval(db: Session, approval_id: int, previous: str) -> None:
    try:
        db.rollback()
    except Exception:
        pass
    row = db.query(CustomerOrderApproval).filter(CustomerOrderApproval.id == approval_id).first()
    if row is not None and row.status == "converting" and not row.bc_order_number:
        row.status = previous
        db.commit()


def _queue_message(db, *, kind, dedupe, to_email, subject, body, context) -> Optional[OpsOutboundMessage]:
    existing = (
        db.query(OpsOutboundMessage)
        .filter(OpsOutboundMessage.dedupe_key == dedupe)
        .first()
    )
    if existing is not None:
        return existing if existing.status == "pending" else None
    now = datetime.utcnow()
    row = OpsOutboundMessage(
        kind=kind,
        status="pending",
        dedupe_key=dedupe,
        to_email=to_email,
        subject=subject[:300],
        body_text=body,
        context_json=context,
        created_at=now,
        updated_at=now,
    )
    db.add(row)
    db.flush()
    return row


def _shadow_on_quote(quote: QuoteRequest, kind: str, payload: dict) -> None:
    data = dict(quote.parsed_data or {})
    notes = list(data.get("inbox_shadow") or [])
    notes.append({"kind": kind, **payload})
    data["inbox_shadow"] = notes
    quote.parsed_data = data


def _shadow_note(email_log: EmailLog, kind: str, payload: dict) -> None:
    """Shadow for a message that never became a quote.

    Stored on email_logs.inbox_shadow, not on the attachment list. Attachment
    text is what the customer sent. A shadow note is ours.
    """
    note = {"kind": kind, "shadow": True, **_jsonable(payload)}
    current = list(email_log.inbox_shadow or [])
    current.append(note)
    email_log.inbox_shadow = current


def _jsonable(value):
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    return value


def _has_size(doors: list, parsed: list) -> bool:
    for door in list(doors) + list(parsed):
        if not isinstance(door, dict):
            continue
        width = door.get("doorWidth") or door.get("width_in") or door.get("width_ft")
        height = door.get("doorHeight") or door.get("height_in") or door.get("height_ft")
        try:
            if float(width or 0) > 0 and float(height or 0) > 0:
                return True
        except (TypeError, ValueError):
            continue
    return False


def _quote_notes(quote: QuoteRequest):
    assumptions = []
    sources = quote.field_sources or {}
    for door in sources.get("doors") or []:
        if not isinstance(door, dict):
            continue
        for key, label in _ASSUMPTION_FIELDS:
            if key == "deliveryType":
                continue
            entry = door.get(key) or {}
            if entry.get("source") in {"profile", "default"} and entry.get("email_basis") in {None, "silent"}:
                value = entry.get("used", entry.get("value"))
                if value not in (None, "", [], False):
                    assumptions.append(f"{label}: {value}")
    delivery = sources.get("deliveryType") or {}
    if delivery.get("source") in {"profile", "default"}:
        assumptions.append(f"Delivery: {delivery.get('used') or delivery.get('value')}")
    deviations = [item for item in (quote.deviations or []) if isinstance(item, dict)]
    return assumptions, deviations


def _sq_numbers(text: str) -> List[str]:
    found = []
    for match in _SQ_RE.findall(text or ""):
        number = _canonical_sq(match)
        if number not in found:
            found.append(number)
    return found


def _canonical_sq(token: str) -> str:
    digits = re.sub(r"\D", "", token or "")
    return f"SQ-{digits}" if digits else token


def _sq_key(token: Optional[str]) -> str:
    digits = re.sub(r"\D", "", token or "")
    if not digits:
        return ""
    return str(int(digits))


def _rows_for_numbers(db: Session, numbers: List[str]) -> List[QuoteRequest]:
    """Quotes whose number matches, without loading the whole table."""
    from sqlalchemy import or_
    likes = []
    keys = set()
    for number in numbers:
        digits = re.sub(r"\D", "", number or "")
        if not digits:
            continue
        keys.add(str(int(digits)))
        likes.append(QuoteRequest.bc_quote_id.like(f"%{digits}"))
    if not likes:
        return []
    rows = db.query(QuoteRequest).filter(or_(*likes)).all()
    return [row for row in rows if _sq_key(row.bc_quote_id) in keys]


def _quotes_for_numbers(db: Session, numbers: List[str], from_address: str) -> List[dict]:
    if not numbers:
        return []
    by_key = {}
    for row in _rows_for_numbers(db, numbers):
        if not _belongs_to_sender(row, from_address):
            continue
        by_key.setdefault(_sq_key(row.bc_quote_id), row)
    found = []
    seen = set()
    for number in numbers:
        key = _sq_key(number)
        if key in seen:
            continue
        row = by_key.get(key)
        if row is None:
            continue
        seen.add(key)
        found.append(_quote_candidate(row, "number"))
    return found


def _norm_subject(subject: Optional[str]) -> str:
    text = (subject or "").strip()
    while True:
        cleaned = re.sub(r"^(re|fw|fwd)\s*:\s*", "", text, flags=re.I)
        if cleaned == text:
            return cleaned.strip().lower()
        text = cleaned.strip()


def _quotes_on_thread(db: Session, from_address: str, subject: str, email_log_id: Optional[int]) -> List[dict]:
    wanted = _norm_subject(subject)
    if not wanted or not from_address:
        return []
    logs = (
        db.query(EmailLog)
        .filter(EmailLog.from_address == from_address)
        .all()
    )
    ids = [
        log.id for log in logs
        if log.id != email_log_id and _norm_subject(log.subject) == wanted
    ]
    if not ids:
        return []
    rows = (
        db.query(QuoteRequest)
        .filter(QuoteRequest.email_id.in_(ids), QuoteRequest.bc_quote_id.isnot(None))
        .all()
    )
    return [_quote_candidate(row, "thread") for row in rows]


def _recent_customer_quotes(db: Session, from_address: str) -> List[dict]:
    if not from_address:
        return []
    cutoff = datetime.utcnow() - timedelta(days=90)
    rows = (
        db.query(QuoteRequest)
        .filter(
            QuoteRequest.contact_email == from_address,
            QuoteRequest.bc_quote_id.isnot(None),
            QuoteRequest.created_at >= cutoff,
        )
        .order_by(QuoteRequest.created_at.desc())
        .all()
    )
    return [_quote_candidate(row, "customer_recent") for row in rows]


def _quote_candidate(row: QuoteRequest, method: str) -> dict:
    return {
        "bc_quote_number": row.bc_quote_id,
        "quote_request_id": row.id,
        "customer_name": row.customer_name,
        "method": method,
    }


def _match_method(candidates: List[dict]) -> str:
    if len(candidates) == 1:
        return candidates[0].get("method") or "number"
    if len(candidates) > 1:
        return "ambiguous"
    return "none"


def _candidate_has(candidates: List[dict], sq_number: str) -> bool:
    wanted = _sq_key(sq_number)
    return any(_sq_key(item.get("bc_quote_number")) == wanted for item in candidates)


def _quote_by_number(db: Session, sq_number: str) -> Optional[QuoteRequest]:
    rows = _rows_for_numbers(db, [sq_number])
    return rows[0] if rows else None


def _belongs_to_sender(row: QuoteRequest, from_address: str) -> bool:
    sender = (from_address or "").strip().lower()
    contact = (row.contact_email or "").strip().lower()
    return bool(sender and contact and sender == contact)


def _decision(candidates: List[dict]):
    """A single numbered or threaded quote is ready. Recent history is not."""
    if len(candidates) == 1 and candidates[0].get("method") in {"number", "thread"}:
        return "ready", candidates[0].get("bc_quote_number")
    return "needs_choice", None


def _duplicate_approval(db: Session, candidates: List[dict]):
    keys = {_sq_key(item.get("bc_quote_number")) for item in candidates if item.get("bc_quote_number")}
    keys.discard("")
    if not keys:
        return None
    rows = (
        db.query(CustomerOrderApproval)
        .filter(CustomerOrderApproval.status.in_(["ready", "needs_choice", "converting", "converted"]))
        .all()
    )
    for row in rows:
        row_keys = set()
        if row.bc_quote_number:
            row_keys.add(_sq_key(row.bc_quote_number))
        for item in row.candidates or []:
            if isinstance(item, dict) and item.get("bc_quote_number"):
                row_keys.add(_sq_key(item.get("bc_quote_number")))
        if keys & row_keys:
            return row
    return None


def _draft_recipient(email_log: Optional[EmailLog], fallback: Optional[str]):
    subject = email_log.subject if email_log else ""
    body = email_log.body if email_log else ""
    return reply_recipient(subject or "", body or "", fallback)
