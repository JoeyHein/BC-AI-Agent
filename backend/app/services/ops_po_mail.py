"""Match Joey's sent mail and supplier replies to purchase orders.

Business Central still owns the purchase order. This module only updates
the portal lifecycle and the activity log. It never sends mail.

Graph Mail.Read on joey@opendc.ca (Inbox and Sent Items) is required for a
live scan. Tests pass the same message shape the Graph client already returns.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Callable, Dict, List, Optional, Sequence

from sqlalchemy.orm import Session

from app.db.models import OpsTrackedLine, OpsTrackedPo
from app.services.ops_tracker_service import (
    HEARD_FROM_SUPPLIER,
    Actor,
    parse_date,
    record_activity,
    refresh_lifecycle,
)

_PO_RE = re.compile(r"\bPO-\d+\b", re.IGNORECASE)
_ORDER_NO_RES = (
    re.compile(r"\bS-ORD\d+\b", re.IGNORECASE),
    re.compile(r"\bUL-\d+\b", re.IGNORECASE),
    re.compile(r"(?:our\s+)?(?:order|confirmation|acknowledgement|ack)\s*(?:no\.?|number|#)\s*[:#]?\s*([A-Z0-9][A-Z0-9\-]{2,})", re.IGNORECASE),
)
_DATE_RES = (
    re.compile(r"(?:ship(?:ping)?|eta|expected|ready)\s*(?:date)?\s*[:\-]?\s*(\d{4}-\d{2}-\d{2})", re.IGNORECASE),
    re.compile(r"(?:ship(?:ping)?|eta|expected|ready)\s*(?:date)?\s*[:\-]?\s*([A-Z][a-z]+ \d{1,2},? \d{4})", re.IGNORECASE),
    re.compile(r"(?:ship(?:ping)?|eta|expected|ready)\s*(?:date)?\s*[:\-]?\s*(\d{1,2}/\d{1,2}/\d{2,4})", re.IGNORECASE),
)
_MISSING_RE = re.compile(
    r"(back\s*ordered|backorder\w*|short(?:\s+ship\w*)?|missing|out of stock|not available|will not ship)",
    re.IGNORECASE,
)
_ITEM_RE = re.compile(r"\b([A-Z]{1,5}\d{0,3}-[A-Z0-9][A-Z0-9\-]{1,24})\b")
_PRICE_RE = re.compile(r"(price|cost).{0,50}(\$\s?\d[\d,]*\.?\d*)", re.IGNORECASE)

# Domains Joey buys from. Used when a reply names the vendor but the PO
# number is only in an attachment name or a short subject.
VENDOR_DOMAINS = {
    "ultralitedoors.ca": "Ultra-Lite",
    "lynx-nsw.com": "Lynx",
    "hormann.ca": "Northwest Door",
    "icontrols.ca": "iControls",
    "upwardor.com": "Upwardor",
    "dekcanada.com": "DEK Canada",
}


def message_text(message: dict) -> str:
    body = message.get("body")
    if isinstance(body, dict):
        content = body.get("content") or ""
    else:
        content = message.get("body_text") or ""
    attachments = message.get("attachments") or []
    names = []
    for attachment in attachments:
        if isinstance(attachment, dict):
            names.append(attachment.get("name") or "")
        else:
            names.append(str(attachment))
    parts = [
        message.get("subject") or "",
        message.get("preview") or message.get("bodyPreview") or "",
        content,
        " ".join(names),
    ]
    return "\n".join(part for part in parts if part)


def po_numbers_in(text: str) -> List[str]:
    found = []
    for match in _PO_RE.finditer(text or ""):
        number = match.group(0).upper()
        if number not in found:
            found.append(number)
    return found


def _address(value) -> str:
    if isinstance(value, dict):
        email = (value.get("emailAddress") or {}).get("address") or ""
        return email.strip().lower()
    return (value or "").strip().lower()


def sender_of(message: dict) -> str:
    if message.get("from_email"):
        return str(message["from_email"]).strip().lower()
    return _address(message.get("from"))


def recipients_of(message: dict) -> List[str]:
    raw = message.get("to_emails") or message.get("toRecipients") or []
    if isinstance(raw, str):
        raw = [raw]
    out = []
    for item in raw:
        address = _address(item) if not isinstance(item, str) else item.strip().lower()
        if address:
            out.append(address)
    return out


def domain_of(address: str) -> str:
    if "@" not in (address or ""):
        return ""
    return address.split("@", 1)[1].lower()


def vendor_from_domain(address: str) -> Optional[str]:
    host = domain_of(address)
    for domain, name in VENDOR_DOMAINS.items():
        if host == domain or host.endswith("." + domain):
            return name
    return None


def _parse_loose_date(value: str):
    parsed = parse_date(value)
    if parsed:
        return parsed
    for fmt in ("%B %d, %Y", "%B %d %Y", "%b %d, %Y", "%b %d %Y", "%m/%d/%Y", "%m/%d/%y"):
        try:
            return datetime.strptime(value.strip(), fmt).date()
        except ValueError:
            continue
    return None


def extract_acknowledgement(text: str) -> dict:
    """Rules extraction. Needs review unless an order number and a ship date are both present."""
    vendor_order = None
    for pattern in _ORDER_NO_RES:
        match = pattern.search(text or "")
        if not match:
            continue
        vendor_order = match.group(0) if match.lastindex is None else match.group(1)
        vendor_order = vendor_order.strip().rstrip(".,;")
        break
    ship_date = None
    for pattern in _DATE_RES:
        match = pattern.search(text or "")
        if match:
            ship_date = _parse_loose_date(match.group(1))
            if ship_date:
                break
    missing_hits = list({match.group(0).lower() for match in _MISSING_RE.finditer(text or "")})
    items = []
    for match in _ITEM_RE.finditer(text or ""):
        token = match.group(1).upper()
        if token.startswith("PO-") or token in items:
            continue
        if vendor_order and token == vendor_order.upper():
            continue
        items.append(token)
    prices = [match.group(0).strip() for match in _PRICE_RE.finditer(text or "")]
    if vendor_order and ship_date and not missing_hits and not prices:
        confidence = "high"
    elif vendor_order or ship_date:
        confidence = "medium"
    else:
        confidence = "low"
    needs_review = confidence != "high" or bool(missing_hits) or bool(prices)
    return {
        "vendor_order_no": vendor_order,
        "ship_date": ship_date.isoformat() if ship_date else None,
        "missing_phrases": missing_hits,
        "item_numbers": items,
        "price_notes": prices,
        "confidence": confidence,
        "needs_review": needs_review,
    }


def lookup_stock_unavailable(item_no: str) -> dict:
    return {
        "qty": None,
        "location": "Redcliff",
        "source": "unavailable",
        "item_no": item_no,
        "note": "Item-card inventory was not checked. Pass a Business Central client to read on-hand quantity.",
    }


def lookup_stock_from_bc(bc, item_no: str) -> dict:
    """Company on-hand from the item card.

    The standard item API does not split quantity by warehouse. When a
    location named Redcliff exists it is named on the result; the quantity
    is still the item-card total unless a future location ledger is added.
    """
    try:
        items = bc.get_items_by_numbers([item_no]) if hasattr(bc, "get_items_by_numbers") else {}
        item = items.get(item_no) or {}
        qty = item.get("inventory")
        location = "company"
        if hasattr(bc, "_make_request") and getattr(bc, "company_id", None):
            try:
                payload = bc._make_request("GET", f"companies({bc.company_id})/locations")
                for loc in payload.get("value") or []:
                    blob = f"{loc.get('code') or ''} {loc.get('displayName') or ''}".upper()
                    if "REDCLIFF" in blob or "RED CLIFF" in blob:
                        location = loc.get("displayName") or loc.get("code") or "Redcliff"
                        break
            except Exception:
                location = "company"
        return {"qty": qty, "location": location, "source": "item_card", "item_no": item_no}
    except Exception as exc:
        result = lookup_stock_unavailable(item_no)
        result["note"] = str(exc)
        return result


def apply_mailbox(
    db: Session,
    emails: dict,
    stock_lookup: Optional[Callable[[str], dict]] = None,
    mailbox: str = "joey@opendc.ca",
) -> dict:
    """Update PO lifecycle from sent mail and supplier replies. Does not send."""
    if not emails or not emails.get("available"):
        return {"sent": 0, "replies": 0}
    stock_lookup = stock_lookup or lookup_stock_unavailable
    mailbox = (emails.get("mailbox") or mailbox).strip().lower()
    pos = {row.po_number.upper(): row for row in db.query(OpsTrackedPo).all()}
    sent_count = 0
    reply_count = 0
    known_threads: Dict[str, str] = {}

    for raw in emails.get("sent") or []:
        match = _match_sent(raw, pos, mailbox)
        if not match:
            continue
        sent_count += _record_sent(db, match)
        if match.get("conversation_id"):
            known_threads[match["conversation_id"]] = match["po_number"]

    for raw in emails.get("inbox") or []:
        match = _match_reply(raw, pos, mailbox, known_threads)
        if not match:
            continue
        reply_count += _record_reply(db, match, stock_lookup)

    for po in pos.values():
        refresh_lifecycle(po)
    db.flush()
    return {"sent": sent_count, "replies": reply_count}


def _match_sent(raw: dict, pos: Dict[str, OpsTrackedPo], mailbox: str) -> Optional[dict]:
    text = message_text(raw)
    numbers = [number for number in po_numbers_in(text) if number in pos]
    if not numbers:
        return None
    sender = sender_of(raw)
    if sender and sender != mailbox and mailbox not in sender:
        return None
    when = raw.get("sent_at") or raw.get("sentDateTime")
    return {
        "po_number": numbers[0],
        "when": when,
        "subject": raw.get("subject") or "",
        "web_link": raw.get("web_link") or raw.get("webLink") or "",
        "message_id": raw.get("id") or "",
        "conversation_id": raw.get("conversation_id") or raw.get("conversationId") or "",
        "to": recipients_of(raw),
        "attachment": _first_attachment(raw),
    }


def _match_reply(raw: dict, pos: Dict[str, OpsTrackedPo], mailbox: str, threads: Dict[str, str]) -> Optional[dict]:
    sender = sender_of(raw)
    if sender and (sender == mailbox or sender.endswith("opendc.ca")):
        return None
    text = message_text(raw)
    numbers = [number for number in po_numbers_in(text) if number in pos]
    conversation = raw.get("conversation_id") or raw.get("conversationId") or ""
    if not numbers and conversation and threads.get(conversation) in pos:
        numbers = [threads[conversation]]
    if not numbers:
        vendor = vendor_from_domain(sender)
        if vendor:
            named = [
                po for po in pos.values()
                if vendor.lower() in (po.vendor_name or "").lower()
                or vendor_from_domain(po.vendor_email or "") == vendor
            ]
            if len(named) == 1:
                numbers = [named[0].po_number.upper()]
    if not numbers:
        return None
    return {
        "po_number": numbers[0],
        "subject": raw.get("subject") or "",
        "web_link": raw.get("web_link") or raw.get("webLink") or "",
        "message_id": raw.get("id") or "",
        "from_email": sender,
        "text": text,
        "attachment": _first_attachment(raw),
        "received_at": raw.get("received_at") or raw.get("receivedDateTime"),
    }


def _first_attachment(raw: dict) -> Optional[str]:
    for attachment in raw.get("attachments") or []:
        if isinstance(attachment, dict) and attachment.get("name"):
            return attachment["name"]
    return None


def _record_sent(db: Session, match: dict) -> int:
    po = db.query(OpsTrackedPo).filter(OpsTrackedPo.po_number == match["po_number"]).one_or_none()
    if po is None:
        return 0
    when = _as_datetime(match.get("when")) or datetime.utcnow()
    if po.sent_at is None or when < po.sent_at:
        po.sent_at = when
    po.sent_source = "graph_sent"
    if not po.lifecycle_locked and po.lifecycle in {None, "", "drafted"}:
        po.lifecycle = "waiting_ack"
    who = ", ".join(match.get("to") or []) or (po.vendor_email or po.vendor_name or "the supplier")
    record_activity(
        db,
        event_type="po_emailed",
        direction="outbound",
        body=f"{po.po_number} emailed to {who}. Subject: {match.get('subject') or '(no subject)'}.",
        so_number=(po.so_numbers_json or [None])[0],
        po_number=po.po_number,
        vendor_number=po.vendor_number,
        vendor_name=po.vendor_name,
        actor=Actor(email="joey@opendc.ca", source="graph"),
        dedupe_key=f"mail-sent:{po.po_number}:{match.get('message_id') or when.isoformat()}",
        web_link=match.get("web_link") or None,
        message_id=match.get("message_id") or None,
        attachment_name=match.get("attachment"),
    )
    return 1


def _record_reply(db: Session, match: dict, stock_lookup: Callable[[str], dict]) -> int:
    po = db.query(OpsTrackedPo).filter(OpsTrackedPo.po_number == match["po_number"]).one_or_none()
    if po is None:
        return 0
    extracted = extract_acknowledgement(match.get("text") or "")
    po.ack_extracted_json = extracted
    po.ack_confidence = extracted["confidence"]
    po.ack_needs_review = bool(extracted["needs_review"])
    if extracted.get("vendor_order_no") and not po.vendor_order_no:
        po.vendor_order_no = extracted["vendor_order_no"]
    ship = parse_date(extracted.get("ship_date"))
    if ship and po.expected_date != ship:
        po.expected_date = ship
    if extracted.get("vendor_order_no") or ship:
        po.ack_status = "acknowledged"
        po.ack_received_at = _as_datetime(match.get("received_at")) or datetime.utcnow()
    missing_bits = []
    if extracted["missing_phrases"]:
        missing_bits.append(", ".join(extracted["missing_phrases"]))
    if extracted["item_numbers"]:
        missing_bits.append("items " + ", ".join(extracted["item_numbers"]))
    if extracted["missing_phrases"]:
        po.missing_summary = "; ".join(missing_bits)
        _flag_missing_lines(db, po, extracted, stock_lookup)
    elif not po.lifecycle_locked:
        po.missing_summary = None
    summary = f"Reply from {match.get('from_email') or 'supplier'} on {po.po_number}."
    if extracted.get("vendor_order_no"):
        summary += f" Vendor order {extracted['vendor_order_no']}."
    if extracted.get("ship_date"):
        summary += f" Ship date {extracted['ship_date']}."
    if po.missing_summary:
        summary += f" Missing: {po.missing_summary}."
    if extracted["price_notes"]:
        summary += " Price noted: " + "; ".join(extracted["price_notes"]) + "."
    if extracted["needs_review"]:
        summary += f" Needs review ({extracted['confidence']} confidence)."
    record_activity(
        db,
        event_type="supplier_reply",
        direction="inbound",
        body=summary,
        so_number=(po.so_numbers_json or [None])[0],
        po_number=po.po_number,
        vendor_number=po.vendor_number,
        vendor_name=po.vendor_name,
        actor=Actor(email=match.get("from_email") or po.vendor_name, source="graph"),
        dedupe_key=f"mail-reply:{po.po_number}:{match.get('message_id') or summary[:80]}",
        web_link=match.get("web_link") or None,
        message_id=match.get("message_id") or None,
        needs_review=bool(extracted["needs_review"]),
        confidence=extracted["confidence"],
        extracted_json=extracted,
        attachment_name=match.get("attachment"),
    )
    return 1


def _flag_missing_lines(db: Session, po: OpsTrackedPo, extracted: dict, stock_lookup: Callable[[str], dict]) -> None:
    lines = db.query(OpsTrackedLine).filter(OpsTrackedLine.linked_po_number == po.po_number, OpsTrackedLine.active.is_(True)).all()
    wanted = {item.upper() for item in extracted.get("item_numbers") or []}
    targets = [line for line in lines if (line.item_no or "").upper() in wanted] or lines
    details = []
    for line in targets:
        stock = stock_lookup(line.item_no or "") or {}
        line.missing_flag = True
        line.missing_detail = po.missing_summary
        line.stock_qty = stock.get("qty")
        line.stock_location = stock.get("location") or "Redcliff"
        line.stock_source = stock.get("source") or "unavailable"
        qty = "unknown" if stock.get("qty") is None else stock.get("qty")
        details.append(f"{line.item_no}: on hand {qty} ({line.stock_location}, {line.stock_source})")
    if details:
        po.missing_summary = (po.missing_summary or "Missing") + ". Stock: " + "; ".join(details)


def _as_datetime(value) -> Optional[datetime]:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    text = str(value).strip().replace("Z", "")
    try:
        return datetime.fromisoformat(text[:19])
    except ValueError:
        parsed = parse_date(text)
        return datetime.combine(parsed, datetime.min.time()) if parsed else None


def note_po_review_draft(db: Session, po_number: str, vendor_name: Optional[str], web_link: Optional[str]) -> None:
    """The purchasing screen saves an Outlook draft. That is not a send.

    Waiting on acknowledgement starts when Sent Items contains the message.
    """
    record_activity(
        db,
        event_type="po_draft_saved",
        direction="draft",
        body=f"Outlook draft saved for {po_number} to {vendor_name or 'the supplier'}. It has not been sent.",
        po_number=po_number,
        vendor_name=vendor_name,
        actor=Actor(email="portal", source="portal"),
        dedupe_key=f"po-draft:{po_number}:{web_link or 'saved'}",
        web_link=web_link,
    )
