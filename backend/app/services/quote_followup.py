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
from app.services.email_text import fresh_message_text, html_to_text, reply_recipient
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
    r"\bgo ahead\b.{0,40}\b(?:change|revise|update|modify|adjust|colour|color)\b"
    r"|\b(?:change|revise|update|modify|adjust)\b.{0,40}\bgo ahead\b",
    re.I,
)
# "update me" is a status request. "update the colour" is a change.
_CHANGE = re.compile(
    r"\b(?:change|revise|modify|adjust|make it|but make)\b|\bupdate\b(?!\s+me\b)",
    re.I,
)
_CONDITIONAL = re.compile(r"\b(?:once|when|if|after|before)\b", re.I)
# "no changes" agrees with the approval. "not" and "can't" reject it.
_NEGATION = re.compile(
    r"\b(?:not|never|nor|cannot)\b|\b(?:can|do|won|is|are|was|were|has|have|had|did|should|would|could)n['’]t\b|\w+n['’]t\b",
    re.I,
)
_QUOTE_SEND_MARK = re.compile(r"attached is quote\s+SQ-?\d+", re.I)
_PREVIOUS_SQ = re.compile(
    r"\b(?:previous|last|old|earlier|prior)\b.{0,60}\bSQ-?\d+\b|\bSQ-?\d+\b.{0,40}\bwas approved\b",
    re.I,
)
_APPROVED_RE = re.compile(r"\bapproved\b", re.I)
_NEW_QUOTE_RE = re.compile(
    r"\b(?:please quote|please price|can you (?:quote|price)|need a quote|"
    r"quote request|request for quote|rfq|re-?quote|revised quote|new quote)\b",
    re.I,
)
_SIZE_PAIR_RE = re.compile(
    r"(\d{1,2})(?:\s*(?:'|ft|feet))?\s*[x×]\s*(\d{1,2})",
    re.I,
)
_PARTIAL_RE = re.compile(
    r"\b(?:no|not|without|except|hold(?:\s+the)?|skip|exclude|minus|"
    r"don'?t include|do not include|don'?t need|do not need|"
    r"leave\s+off|leave\s+out|remove|drop)\b"
    r".{0,40}\b(?:opener|operator|motor|windows?|glass|keypad|rail|springs?|track)\b"
    r"|\b(?:opener|operator|motor|keypad)\b.{0,30}\b(?:no|not|without|except|hold)\b",
    re.I,
)
_FEET_INCHES_SIZE_RE = re.compile(
    r"\d{1,2}\s*(?:'|ft|feet)\s*\d{1,2}\s*(?:\"|in(?:ch(?:es)?)?)?\s*[x×]\s*"
    r"\d{1,2}(?:\s*(?:'|ft|feet)\s*\d{1,2}\s*(?:\"|in(?:ch(?:es)?)?)?)?",
    re.I,
)
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


def _sentences(text: str) -> List[str]:
    parts = re.split(r"\n+|(?<=[.!?])\s+", text or "")
    return [part.strip() for part in parts if part.strip()]


def _mentions_approval(sentence: str) -> bool:
    return bool(_STRONG_RE.search(sentence) or _APPROVED_RE.search(sentence))


def _blocked(sentence: str) -> bool:
    """A question, a conditional, a negation, or a change is not a go-ahead."""
    if "?" in sentence:
        return True
    if _CONDITIONAL.search(sentence) or _NEGATION.search(sentence):
        return True
    if _GO_AHEAD_CHANGE.search(sentence) or _CHANGE.search(sentence):
        return True
    return False


def _reply_on_quote_send(subject: str, body: str) -> bool:
    """A reply on the thread of a quote we already sent, not a new request.

    The new writing may not repeat the SQ. The quoted send still has it.
    """
    if not _looks_like_reply_subject(subject or ""):
        return False
    plain = html_to_text(body or "")
    fresh = fresh_message_text(body or "")
    if _QUOTE_SEND_MARK.search(plain) and not _QUOTE_SEND_MARK.search(fresh):
        return True
    return bool(_SQ_RE.search(plain) and not _SQ_RE.search(fresh))


def _is_new_quote_writing(category: str, text: str) -> bool:
    return (
        category == "quote_request"
        or _NEW_QUOTE_RE.search(text) is not None
        or _SIZE_HINT_RE.search(text) is not None
    )


def approval_exception(text: str) -> Optional[str]:
    """The sentence that makes an approval partial, such as 'but no opener'."""
    for sentence in _sentences(text or ""):
        if _PARTIAL_RE.search(sentence):
            return sentence.strip()
    return None


def approval_level(category: str, subject: str, body: str) -> str:
    """high, partial, low, or none.

    high is a clear go-ahead. partial is a go-ahead with an exception
    ('approved, but no opener') and is never high. low is a go-ahead tied
    to a change. none is everything else, including questions and 'not yet'.

    A new shop request that says "approved" or "go ahead" and then asks for
    a quote is not a go-ahead. A reply on the thread of a quote we sent can
    still be one.
    """
    text = fresh_message_text(body or "")
    if subject and not _looks_like_reply_subject(subject):
        text = f"{subject}\n{text}"
    if (
        _is_new_quote_writing(category, text)
        and not _SQ_RE.search(text)
        and not _reply_on_quote_send(subject, body)
    ):
        return "none"
    if _PREVIOUS_SQ.search(text) and (_NEW_QUOTE_RE.search(text) or _SIZE_HINT_RE.search(text)):
        return "none"
    high = False
    low = False
    for sentence in _sentences(text):
        if not _mentions_approval(sentence):
            continue
        if _blocked(sentence):
            if _SQ_RE.search(sentence) and (_CHANGE.search(sentence) or _GO_AHEAD_CHANGE.search(sentence)):
                if not _NEGATION.search(sentence) and "?" not in sentence and not _CONDITIONAL.search(sentence):
                    low = True
            continue
        if _STRONG_RE.search(sentence) or _APPROVED_RE.search(sentence):
            high = True
    if high and approval_exception(text):
        return "partial"
    if high and (_CHANGE.search(text) or _GO_AHEAD_CHANGE.search(text)):
        return "low"
    if high and not low:
        return "high"
    if low:
        return "low"
    return "none"


def _looks_like_reply_subject(subject: str) -> bool:
    return bool(re.match(r"^\s*(re|fw|fwd)\s*:", subject or "", re.I))


def size_pairs(text: str):
    """Door sizes written as 10x10 or 10' x 10'.

    Feet-and-inches forms such as 8'4 x 7 are not sizes. Matching the 4 and
    the 7 would invent a door that was not asked for.
    """
    cleaned = _FEET_INCHES_SIZE_RE.sub(" ", text or "")
    return {(int(a), int(b)) for a, b in _SIZE_PAIR_RE.findall(cleaned)}


def contains_new_quote_ask(subject: str, body: str, referenced_sizes=None) -> bool:
    """True when the new writing asks for another quote.

    A repeated size ('ship the 10x10 as quoted') is not a new quote.
    A size is new only when it is not already on the referenced quote.
    """
    del subject
    text = fresh_message_text(body or "")
    if _NEW_QUOTE_RE.search(text):
        return True
    found = size_pairs(text)
    if not found:
        return False
    # No referenced quote was found. A size next to the approval is a new
    # request, not a repeat of a quote we could not see.
    if referenced_sizes is None:
        return True
    if not referenced_sizes:
        return False
    known = set()
    for item in referenced_sizes:
        if isinstance(item, (tuple, list)) and len(item) == 2:
            known.add((int(item[0]), int(item[1])))
    return any(pair not in known for pair in found)


def note_also_new_request(row: CustomerOrderApproval) -> None:
    """The go-ahead also asks for a new door. The card says so."""
    note = "also contains a new request"
    text = row.excerpt or ""
    if note not in text.lower():
        row.excerpt = f"{text}\n{note}".strip()


def is_customer_approval(category: str, subject: str, body: str) -> bool:
    """True only for a clear go-ahead. A change, a question, or a maybe is not."""
    return approval_level(category, subject, body) == "high"


def note_low_approval(email_log: EmailLog, text: str) -> None:
    """A go-ahead mixed with a change. Noted, not queued, and not a divert."""
    _shadow_note(email_log, "customer_approval_low", {
        "confidence": "low",
        "excerpt": (text or "")[:500],
    })


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
    confidence: str = "high",
    exception_text: Optional[str] = None,
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
    if confidence == "partial" and status == "ready":
        status = "partial"
    superseded = _supersede_vague(
        db,
        from_address=from_address,
        candidates=candidates,
        status=status,
        chosen_sq=chosen_sq,
        po_number=po_number,
        po_source=po_source,
        excerpt=_approval_excerpt(text, exception_text),
        email_log_id=email_log.id,
    )
    if superseded is not None:
        return superseded
    row = CustomerOrderApproval(
        email_log_id=email_log.id,
        status=status,
        match_method=payload["match_method"],
        bc_quote_number=chosen_sq,
        quote_request_id=candidates[0].get("quote_request_id") if status in {"ready", "partial"} else None,
        candidates=candidates,
        customer_po=po_number,
        po_source=po_source,
        excerpt=_approval_excerpt(text, exception_text),
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


def _size_pairs_on_quote(row: QuoteRequest):
    pairs = set()
    data = row.parsed_data if isinstance(row.parsed_data, dict) else {}
    doors = []
    mapping = data.get("configurator_mapping") or {}
    if isinstance(mapping, dict):
        doors.extend(mapping.get("doors") or [])
    if isinstance(data.get("doors"), list):
        doors.extend(data.get("doors") or [])
    specs = row.door_specs
    if isinstance(specs, dict):
        doors.append(specs)
    elif isinstance(specs, list):
        doors.extend(specs)
    for door in doors:
        if not isinstance(door, dict):
            continue
        width_ft = door.get("width_ft")
        height_ft = door.get("height_ft")
        if width_ft and height_ft:
            pairs.add((int(width_ft), int(height_ft)))
            continue
        width = door.get("doorWidth") or door.get("width")
        height = door.get("doorHeight") or door.get("height")
        if width and height:
            pairs.add((int(width) // 12, int(height) // 12))
    return pairs


def sizes_on_matched_quotes(db: Session, text: str, from_address: str, subject: str, email_log_id: Optional[int]):
    """Sizes on the quote this approval names. None when no quote was matched."""
    candidates = match_sales_quotes(db, text, from_address, subject, email_log_id)
    numbers = [
        item.get("bc_quote_number")
        for item in candidates
        if item.get("bc_quote_number") and item.get("method") in {"number", "thread"}
    ]
    if not numbers:
        return None
    pairs = set()
    found = False
    for number in numbers:
        row = _quote_by_number(db, number)
        if row is None:
            continue
        found = True
        pairs |= _size_pairs_on_quote(row)
    return pairs if found else None


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
    if row.status not in {"ready", "partial", "needs_choice"}:
        raise HTTPException(status_code=400, detail="This approval is not waiting for a convert")
    chosen = (bc_quote_number or "").strip() or row.bc_quote_number
    candidates = row.candidates or []
    if row.status == "needs_choice" and not chosen:
        raise HTTPException(status_code=400, detail="Choose which quote to convert")
    if not chosen:
        raise HTTPException(status_code=400, detail="No quote number to convert")
    portal_quote = _quote_by_number(db, chosen)
    if portal_quote is None:
        raise HTTPException(status_code=400, detail="That quote is not in the portal")
    same_customer = bool(row.from_address) and _same_customer(db, portal_quote, row.from_address)
    if candidates and chosen and not _candidate_has(candidates, chosen) and not same_customer:
        raise HTTPException(status_code=400, detail="That quote is not one of the matches")
    if row.from_address and not same_customer:
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


def _approval_excerpt(text: str, exception_text: Optional[str]) -> str:
    body = (text or "")[:500]
    if not exception_text:
        return body
    prefix = f"Exception: {exception_text.strip()}"
    return f"{prefix}\n{body}"[:500]


def _exception_from_excerpt(excerpt: Optional[str]):
    text = excerpt or ""
    if not text.startswith("Exception:"):
        return None
    first = text.split("\n", 1)[0]
    return first[len("Exception:"):].strip() or None


def approval_to_dict(row: CustomerOrderApproval) -> dict:
    exception_text = _exception_from_excerpt(row.excerpt)
    return {
        "id": row.id,
        "email_log_id": row.email_log_id,
        "status": row.status,
        "confidence": "partial" if row.status == "partial" or exception_text else "high",
        "exception_text": exception_text,
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
        if not _same_customer(db, row, from_address):
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
    """Recent quotes for this person, their company domain, or that BC customer."""
    if not from_address:
        return []
    cutoff = datetime.utcnow() - timedelta(days=90)
    rows = (
        db.query(QuoteRequest)
        .filter(
            QuoteRequest.bc_quote_id.isnot(None),
            QuoteRequest.created_at >= cutoff,
        )
        .order_by(QuoteRequest.created_at.desc())
        .all()
    )
    found = []
    for row in rows:
        if _same_customer(db, row, from_address):
            found.append(_quote_candidate(row, "customer_recent"))
        if len(found) >= 8:
            break
    return found


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


def _email_domain(address: str) -> str:
    text = (address or "").strip().lower()
    if "@" not in text:
        return ""
    return text.rsplit("@", 1)[-1]


def _company_domain(domain: str) -> bool:
    from app.services.customer_profile_service import FREE_MAIL_DOMAINS, INTERNAL_DOMAINS
    return bool(domain) and domain not in FREE_MAIL_DOMAINS and domain not in INTERNAL_DOMAINS


def _belongs_to_sender(row: QuoteRequest, from_address: str) -> bool:
    """Same person, or the same company's own domain. Free mail does not count."""
    sender = (from_address or "").strip().lower()
    contact = (row.contact_email or "").strip().lower()
    if sender and contact and sender == contact:
        return True
    sender_domain = _email_domain(sender)
    contact_domain = _email_domain(contact)
    return bool(_company_domain(sender_domain) and sender_domain == contact_domain)


def _same_customer(db: Session, row: QuoteRequest, from_address: str) -> bool:
    """The sender, their company domain, or another contact on the same BC customer."""
    if _belongs_to_sender(row, from_address):
        return True
    customer_id = (row.matched_bc_customer_id or "").strip()
    domain = _email_domain(from_address)
    if not customer_id or not _company_domain(domain):
        return False
    sibling = (
        db.query(QuoteRequest.id)
        .filter(
            QuoteRequest.matched_bc_customer_id == customer_id,
            QuoteRequest.contact_email.ilike(f"%@{domain}"),
        )
        .first()
    )
    return sibling is not None


def _decision(candidates: List[dict]):
    """A single numbered or threaded quote is ready. Recent history is not."""
    if len(candidates) == 1 and candidates[0].get("method") in {"number", "thread"}:
        return "ready", candidates[0].get("bc_quote_number")
    return "needs_choice", None


def _is_vague(row: CustomerOrderApproval) -> bool:
    """A suggestion list with no chosen SQ. It must not block a later explicit one."""
    if row.bc_quote_number:
        return False
    methods = {
        item.get("method")
        for item in (row.candidates or [])
        if isinstance(item, dict)
    }
    return not methods or methods <= {"customer_recent"}


def _duplicate_approval(db: Session, candidates: List[dict]):
    """An open approval for the same SQ.

    A vague 'which quote?' row does not block a later email that names an SQ.
    Two vague rows for the same suggestion still collapse into one.
    """
    explicit = {
        _sq_key(item.get("bc_quote_number"))
        for item in candidates
        if item.get("bc_quote_number") and item.get("method") in {"number", "thread"}
    }
    explicit.discard("")
    suggested = {_sq_key(item.get("bc_quote_number")) for item in candidates if item.get("bc_quote_number")}
    suggested.discard("")
    if not explicit and not suggested:
        return None
    rows = (
        db.query(CustomerOrderApproval)
        .filter(CustomerOrderApproval.status.in_(["ready", "partial", "needs_choice", "converting", "converted"]))
        .all()
    )
    for row in rows:
        row_keys = set()
        if row.bc_quote_number:
            row_keys.add(_sq_key(row.bc_quote_number))
        for item in row.candidates or []:
            if isinstance(item, dict) and item.get("bc_quote_number"):
                if explicit and item.get("method") not in {"number", "thread"} and not row.bc_quote_number:
                    continue
                row_keys.add(_sq_key(item.get("bc_quote_number")))
        if explicit:
            if _is_vague(row):
                continue
            if explicit & row_keys:
                return row
        elif suggested & row_keys and _is_vague(row):
            return row
    return None


def _bc_customer_ids(db: Session, address: str) -> set:
    """Business Central customers this address, or its company domain, has quoted.

    The query is limited to that address and, for a company domain, addresses
    on that domain. It does not load every quote.
    """
    from sqlalchemy import func, or_

    domain = _email_domain(address)
    wanted = (address or "").strip().lower()
    if not wanted:
        return set()
    filters = [func.lower(QuoteRequest.contact_email) == wanted]
    if _company_domain(domain):
        filters.append(QuoteRequest.contact_email.ilike(f"%@{domain}"))
    rows = (
        db.query(QuoteRequest.matched_bc_customer_id, QuoteRequest.contact_email)
        .filter(QuoteRequest.matched_bc_customer_id.isnot(None))
        .filter(or_(*filters))
        .all()
    )
    found = set()
    for customer_id, contact in rows:
        cid = (customer_id or "").strip()
        if not cid or cid.upper() in {"CASH", "RETAIL", "CASH SALES"}:
            continue
        who = (contact or "").strip().lower()
        if who == wanted or (_company_domain(domain) and _email_domain(who) == domain):
            found.add(cid)
    return found


def _same_party(db: Session, left: Optional[str], right: Optional[str]) -> bool:
    """Same person, same company domain, or the same Business Central customer."""
    a = (left or "").strip().lower()
    b = (right or "").strip().lower()
    if not a or not b:
        return False
    if a == b:
        return True
    domain_a = _email_domain(a)
    domain_b = _email_domain(b)
    if _company_domain(domain_a) and domain_a == domain_b:
        return True
    return bool(_bc_customer_ids(db, a) & _bc_customer_ids(db, b))


def _open_vague_for_customer(db: Session, from_address: str):
    rows = (
        db.query(CustomerOrderApproval)
        .filter(
            CustomerOrderApproval.status == "needs_choice",
            CustomerOrderApproval.bc_quote_number.is_(None),
        )
        .order_by(CustomerOrderApproval.id.desc())
        .all()
    )
    for row in rows:
        if _is_vague(row) and _same_party(db, row.from_address, from_address):
            return row
    return None


def _supersede_vague(
    db: Session,
    *,
    from_address: str,
    candidates: List[dict],
    status: str,
    chosen_sq: Optional[str],
    po_number: Optional[str],
    po_source: Optional[str],
    excerpt: str,
    email_log_id: int,
):
    """A later 'approved SQ-x, PO y' replaces an open 'which quote?' row."""
    if not chosen_sq:
        return None
    vague = _open_vague_for_customer(db, from_address)
    if vague is None:
        return None
    kept_po = po_number or vague.customer_po
    kept_source = po_source if po_number else vague.po_source
    vague.status = status
    vague.bc_quote_number = chosen_sq
    vague.quote_request_id = next(
        (item.get("quote_request_id") for item in candidates if item.get("bc_quote_number") == chosen_sq),
        None,
    )
    vague.candidates = candidates
    vague.match_method = "number"
    vague.customer_po = kept_po
    vague.po_source = kept_source
    vague.excerpt = excerpt
    vague.email_log_id = email_log_id
    vague.from_address = from_address
    db.flush()
    return vague


def _draft_recipient(email_log: Optional[EmailLog], fallback: Optional[str]):
    subject = email_log.subject if email_log else ""
    body = email_log.body if email_log else ""
    return reply_recipient(subject or "", body or "", fallback)
