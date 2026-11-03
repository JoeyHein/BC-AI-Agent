"""Internal production tracker, to-do list, and approval-gated mail.

Business Central remains the source for sales orders, lines, purchase orders,
receipts, and vendor acknowledgements. This module stores the columns the
schedule spreadsheet kept by hand (sourcing, operators, window kits, emergency
build, shipping, notes) and writes an audit row whenever one of them changes.

Opening a record never sends email. ``approve_message`` is the only function
that calls a sender, and the API calls it only after an approval click.
"""

from __future__ import annotations

import html
import logging
import re
from datetime import date, datetime, time, timedelta
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence

from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import (
    OpsActionItem,
    OpsFieldAudit,
    OpsOutboundMessage,
    OpsTrackedLine,
    OpsTrackedOrder,
    OpsTrackedPo,
    OpsTrackerMeta,
    VendorOrderAck,
)

logger = logging.getLogger(__name__)

SOURCE_UPW = "UPW"
SOURCE_STOCK = "STOCK"
UPW_LABEL = "Upwardor"
STOCK_LABEL = "Stock / on hand"

FULFILLMENT_CHOICES = ["Buy Complete", "Emergency Build"]
ORDER_STATES = [
    "Waiting to Order",
    "PO Drafted",
    "Ordered",
    "Shipped by Vendor",
    "Partially Received",
    "Received",
]
WINDOW_KIT_STATES = ["", "Not Started", "In Progress", "Complete"]
BUILD_STATES = ["", "Not Started", "In Production", "Complete"]
SHIPPING_STATES = ["Not Ready", "Ready to Ship", "Shipped"]
OPERATOR_STATES = [""] + ORDER_STATES
ACK_STATES = ["none", "pending", "acknowledged", "revised", "cancelled", "not_required"]

_ORDER_RANK = {name: index for index, name in enumerate(ORDER_STATES)}
_SHIP_RANK = {name: index for index, name in enumerate(SHIPPING_STATES)}

ACK_GRACE_DAYS = 3
REMINDER_INTERVAL_DAYS = 3
REPLY_LOOKBACK_DAYS = 21
ACK_TURNAROUND_DAYS = 90

# Shown even before a Business Central vendor pull, so the dropdown is usable
# on day one. Real vendor numbers are added beside these when BC returns them.
DEFAULT_VENDORS = [
    (SOURCE_UPW, UPW_LABEL),
    (SOURCE_STOCK, STOCK_LABEL),
    ("NWD", "Northwest Door"),
    ("LYNX", "Lynx"),
    ("ULTRA", "Ultra-Lite"),
    ("DEK", "DEK Canada"),
    ("JANUS", "Janus"),
]

_SO_RE = re.compile(r"\bSO-\d+\b", re.IGNORECASE)
_SKIP_SUBJECTS = ("automatic reply", "out of office", "undeliverable", "delivery status")

STRUCTURAL_KINDS = ("missing_po", "missing_po_line", "missing_ack", "missing_expected")
HEARD_FROM_SUPPLIER = {"acknowledged", "revised", "cancelled"}


class OpsTrackerError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


class Actor:
    def __init__(self, user_id: Optional[int] = None, email: Optional[str] = None, source: str = "portal"):
        self.user_id = user_id
        self.email = email
        self.source = source


def tracker_mailbox() -> str:
    return (
        getattr(settings, "OPS_TRACKER_MAILBOX", None)
        or getattr(settings, "EMAIL_INBOX_1", None)
        or "joey@opendc.ca"
    )


def text_to_html(body: str) -> str:
    blocks = []
    for para in (body or "").split("\n\n"):
        lines = "<br>".join(html.escape(line) for line in para.split("\n"))
        blocks.append(f"<p>{lines}</p>")
    return "".join(blocks) or "<p></p>"


def parse_date(value: Any) -> Optional[date]:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00")[:19])
    except ValueError:
        try:
            parsed = datetime.fromisoformat(text[:10])
        except ValueError:
            return None
    if parsed.year <= 1:
        return None
    return parsed.date()


def parse_datetime(value: Any) -> Optional[datetime]:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    text = str(value).strip().replace("Z", "")
    if not text:
        return None
    try:
        return datetime.fromisoformat(text[:19])
    except ValueError:
        parsed = parse_date(text)
        return datetime.combine(parsed, time.min) if parsed else None


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.isoformat(timespec="seconds")
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def _iso(value: Optional[date]) -> Optional[str]:
    return value.isoformat() if value else None


def _at(day: Optional[date]) -> Optional[datetime]:
    return datetime.combine(day, time(hour=8)) if day else None


def _po_key(number: Optional[str]) -> str:
    return (number or "").strip().upper()


def _is_upwardor(number: Optional[str], name: Optional[str]) -> bool:
    token = (number or "").strip().upper()
    if token in {"UPW", "UPWARDOR", "UPWARD"}:
        return True
    return "upward" in (name or "").lower()


def _rank_advance(current: str, computed: Optional[str], ranks: Dict[str, int]) -> str:
    if not computed:
        return current or ""
    if not current:
        return computed
    if ranks.get(computed, -1) > ranks.get(current, -1):
        return computed
    return current


def _choice(value: Optional[str], choices: Sequence[str], label: str) -> str:
    text = "" if value is None else str(value).strip()
    if text not in choices:
        raise OpsTrackerError(f"{label} must be one of: {', '.join(c or 'blank' for c in choices)}")
    return text


def _meta(db: Session) -> OpsTrackerMeta:
    row = db.query(OpsTrackerMeta).filter(OpsTrackerMeta.id == 1).one_or_none()
    if row is None:
        row = OpsTrackerMeta(id=1, mail_available=False, updated_at=datetime.utcnow())
        db.add(row)
        db.flush()
    return row


def _audit(
    db: Session,
    entity_type: str,
    entity_key: str,
    field: str,
    old: Any,
    new: Any,
    actor: Optional[Actor],
) -> None:
    if _text(old) == _text(new):
        return
    db.add(
        OpsFieldAudit(
            entity_type=entity_type,
            entity_key=entity_key,
            field_name=field,
            old_value=_text(old) or None,
            new_value=_text(new) or None,
            actor_user_id=actor.user_id if actor else None,
            actor_email=actor.email if actor else None,
            source=actor.source if actor else "system",
            created_at=datetime.utcnow(),
        )
    )


def _assign(db: Session, obj: Any, entity_type: str, entity_key: str, field: str, new: Any, actor: Optional[Actor], audit: bool) -> bool:
    old = getattr(obj, field)
    if _text(old) == _text(new):
        return False
    if audit:
        _audit(db, entity_type, entity_key, field, old, new, actor)
    setattr(obj, field, new)
    return True


def _so_numbers_from_po(po: dict) -> List[str]:
    found: List[str] = []

    def add(text: Optional[str]) -> None:
        for match in _SO_RE.finditer(text or ""):
            number = match.group(0).upper()
            if number not in found:
                found.append(number)

    add(po.get("external_document_number"))
    for number in po.get("so_numbers") or []:
        add(str(number))
    for line in po.get("lines") or []:
        add(line.get("description"))
    return found


def _vendor_options(extra: Optional[Iterable[dict]] = None) -> List[dict]:
    options = [{"code": code, "label": label, "email": None} for code, label in DEFAULT_VENDORS]
    seen = {row["code"].upper() for row in options}
    for vendor in extra or []:
        code = (vendor.get("number") or vendor.get("code") or "").strip()
        label = (vendor.get("name") or vendor.get("displayName") or code).strip()
        if not code or code.upper() in seen:
            continue
        seen.add(code.upper())
        options.append({"code": code, "label": label or code, "email": vendor.get("email") or None})
    return options


def _label_for(code: str, options: Sequence[dict]) -> str:
    token = (code or "").upper()
    for row in options:
        if row["code"].upper() == token:
            return row["label"]
    if token == SOURCE_STOCK:
        return STOCK_LABEL
    if token == SOURCE_UPW:
        return UPW_LABEL
    return code


def _source_for_vendor(po: dict, options: Sequence[dict]) -> tuple:
    number = (po.get("vendor_number") or "").strip()
    name = po.get("vendor_name") or ""
    if _is_upwardor(number, name):
        return SOURCE_UPW, UPW_LABEL
    if number:
        return number, _label_for(number, options) if _label_for(number, options) != number else (name or number)
    return SOURCE_UPW, UPW_LABEL


def _ack_for(po_number: str, acks: Sequence[dict]) -> Optional[dict]:
    key = _po_key(po_number)
    matches = [ack for ack in acks if _po_key(ack.get("po_number") or ack.get("our_po_number")) == key]
    if not matches:
        return None
    matches.sort(key=lambda ack: _text(ack.get("received_at")))
    return matches[-1]


def _ack_fields(po: dict, ack: Optional[dict]) -> tuple:
    vendor_order = (po.get("vendor_order_no") or "").strip() or None
    received_at = None
    completion = parse_date(po.get("expected_date"))
    status = "none"
    if ack:
        received_at = parse_datetime(ack.get("received_at"))
        vendor_order = (ack.get("vendor_order_no") or vendor_order or "").strip() or None
        if parse_date(ack.get("completion_date")):
            completion = parse_date(ack.get("completion_date"))
        raw = (ack.get("status") or "").lower()
        if raw in {"confirmed", "acknowledged", "revised"}:
            status = "acknowledged" if raw != "revised" else "revised"
        elif raw == "cancelled":
            status = "cancelled"
        elif vendor_order:
            status = "acknowledged"
        else:
            status = "pending"
    elif vendor_order:
        status = "acknowledged"
    elif (po.get("status") or "").lower() == "draft":
        status = "none"
    return status, vendor_order, received_at, completion


def _fully_received(po: dict) -> bool:
    lines = [
        line for line in po.get("lines") or []
        if (line.get("line_type") or "Item") == "Item" and (line.get("item_no") or "").strip()
    ]
    if not lines:
        return False
    qty = sum(float(line.get("quantity") or 0) for line in lines)
    got = sum(float(line.get("received_quantity") or 0) for line in lines)
    return qty > 0 and got + 1e-6 >= qty


def _order_status_from_pos(pos: Sequence[dict]) -> str:
    if not pos:
        return "Waiting to Order"
    if all((po.get("status") or "").lower() == "draft" for po in pos):
        return "PO Drafted"
    if all(_fully_received(po) for po in pos):
        return "Received"
    if any(
        sum(float(line.get("received_quantity") or 0) for line in (po.get("lines") or [])) > 0
        for po in pos
    ):
        return "Partially Received"
    return "Ordered"


def _pick_po(item_no: str, related: Sequence[dict]) -> Optional[dict]:
    item = (item_no or "").upper()
    hits = []
    for po in related:
        for line in po.get("lines") or []:
            if item and (line.get("item_no") or "").upper() == item:
                hits.append(po)
                break
    if not hits and len(related) == 1 and not item.startswith("OP"):
        hits = list(related)
    if not hits:
        return None

    def rank(po: dict) -> tuple:
        draft = 1 if (po.get("status") or "").lower() == "draft" else 0
        upw = 0 if _is_upwardor(po.get("vendor_number"), po.get("vendor_name")) else 1
        return (draft, upw, po.get("number") or "")

    return sorted(hits, key=rank)[0]


def _normalize_message(raw: dict) -> dict:
    sender = raw.get("from_email")
    sender_name = raw.get("from_name") or ""
    if not sender and isinstance(raw.get("from"), dict):
        email = (raw["from"].get("emailAddress") or {})
        sender = email.get("address")
        sender_name = email.get("name") or sender_name
    return {
        "id": raw.get("id") or "",
        "conversation_id": raw.get("conversation_id") or raw.get("conversationId") or raw.get("id") or "",
        "received_at": parse_datetime(raw.get("received_at") or raw.get("receivedDateTime")),
        "sent_at": parse_datetime(raw.get("sent_at") or raw.get("sentDateTime")),
        "from_email": (sender or "").strip().lower(),
        "from_name": sender_name or sender or "",
        "subject": raw.get("subject") or "(no subject)",
        "preview": raw.get("preview") or raw.get("bodyPreview") or "",
        "web_link": raw.get("web_link") or raw.get("webLink") or "",
    }


def messages_needing_reply(inbox: Sequence[dict], sent: Sequence[dict], mailbox: str, today: date) -> List[dict]:
    """Inbox messages with no later send in the same conversation."""
    mailbox = (mailbox or "").strip().lower()
    sent_norm = [_normalize_message(row) for row in sent or []]
    latest_sent: Dict[str, datetime] = {}
    for row in sent_norm:
        if not row["sent_at"]:
            continue
        current = latest_sent.get(row["conversation_id"])
        if current is None or row["sent_at"] > current:
            latest_sent[row["conversation_id"]] = row["sent_at"]
    cutoff = today - timedelta(days=REPLY_LOOKBACK_DAYS)
    needed = []
    for raw in inbox or []:
        message = _normalize_message(raw)
        if not message["id"] or not message["received_at"]:
            continue
        if message["received_at"].date() < cutoff:
            continue
        if message["from_email"] and message["from_email"] == mailbox:
            continue
        subject = message["subject"].strip().lower()
        if subject.startswith(_SKIP_SUBJECTS):
            continue
        replied_at = latest_sent.get(message["conversation_id"])
        if replied_at and replied_at > message["received_at"]:
            continue
        needed.append(message)
    return needed


def _customer_body(order: OpsTrackedOrder, new_date: date, old_date: Optional[date]) -> str:
    tag = f" ({order.external_document_number})" if order.external_document_number else ""
    previous = old_date.isoformat() if old_date else "not set yet"
    who = order.customer_name or "there"
    return (
        f"Hello {who},\n\n"
        f"An update on order {order.so_number}{tag}: the expected date is now {new_date.isoformat()}. "
        f"The previous date we had was {previous}.\n\n"
        "We will write again if that date moves.\n\n"
        "Open Distribution\n"
    )


def _supplier_body(po: OpsTrackedPo, customers: str) -> str:
    sos = ", ".join(po.so_numbers_json or []) or "the related sales order"
    extra = f" for {customers}" if customers else ""
    return (
        f"Hello,\n\n"
        f"Please send the acknowledgement and expected ship date for {po.po_number}{extra}.\n\n"
        f"This purchase order covers {sos}.\n\n"
        "Thank you,\n"
        "Open Distribution\n"
    )


def _upsert_auto(db: Session, key: str, fields: dict) -> None:
    row = db.query(OpsActionItem).filter(OpsActionItem.auto_key == key).one_or_none()
    if row is not None and not row.auto_managed and row.status == "done":
        return
    if row is None:
        row = OpsActionItem(auto_key=key, auto_managed=True, status="open", created_at=datetime.utcnow())
        db.add(row)
    for name, value in fields.items():
        setattr(row, name, value)
    if row.status != "open":
        row.status = "open"
        row.closed_at = None
        row.closed_by_user_id = None
    row.auto_managed = True


def _close_missing(db: Session, kinds: Sequence[str], keep: set) -> None:
    rows = (
        db.query(OpsActionItem)
        .filter(
            OpsActionItem.auto_managed.is_(True),
            OpsActionItem.status == "open",
            OpsActionItem.kind.in_(list(kinds)),
        )
        .all()
    )
    now = datetime.utcnow()
    for row in rows:
        if row.auto_key not in keep:
            row.status = "done"
            row.closed_at = now


def _refresh_structural(db: Session, today: date) -> None:
    orders = db.query(OpsTrackedOrder).filter(OpsTrackedOrder.bc_open.is_(True)).all()
    pos = {po.po_number: po for po in db.query(OpsTrackedPo).filter(OpsTrackedPo.bc_open.is_(True)).all()}
    keep: set = set()
    for order in orders:
        lines = [line for line in order.lines if line.active]
        purchasable = [line for line in lines if (line.source_code or "") != SOURCE_STOCK]
        linked = {line.linked_po_number for line in lines if line.linked_po_number}
        if purchasable and not linked:
            key = f"missing_po:{order.so_number}"
            keep.add(key)
            _upsert_auto(db, key, {
                "kind": "missing_po",
                "title": f"{order.so_number} has no purchase order",
                "detail": f"{order.customer_name or 'Customer'} · tag {order.external_document_number or '—'}",
                "so_number": order.so_number,
                "po_number": None,
                "due_at": _at(order.order_date or today),
            })
        for line in purchasable:
            if line.source_code in {SOURCE_UPW, SOURCE_STOCK}:
                continue
            if line.linked_po_number:
                continue
            key = f"missing_po_line:{order.so_number}:{line.bc_line_no}"
            keep.add(key)
            _upsert_auto(db, key, {
                "kind": "missing_po_line",
                "title": f"{line.item_no or 'Line'} on {order.so_number} needs a {line.source_label} PO",
                "detail": line.description or "",
                "so_number": order.so_number,
                "po_number": None,
                "line_id": line.id,
                "due_at": _at(order.order_date or today),
            })
        if (
            purchasable
            and not order.fully_shipped
            and order.shipping_status != "Shipped"
            and not order.expected_receipt
        ):
            key = f"missing_expected:{order.so_number}"
            keep.add(key)
            _upsert_auto(db, key, {
                "kind": "missing_expected",
                "title": f"{order.so_number} has no expected date",
                "detail": order.customer_name or "",
                "so_number": order.so_number,
                "due_at": _at((order.order_date or today) + timedelta(days=2)),
            })
    for po in pos.values():
        status = (po.status or "").lower()
        if status == "draft" or po.fully_received:
            continue
        if po.ack_status in HEARD_FROM_SUPPLIER or po.ack_status == "not_required":
            continue
        if po.vendor_order_no and po.ack_status == "acknowledged":
            continue
        key = f"missing_ack:{po.po_number}"
        keep.add(key)
        anchor = po.order_date or (po.created_at.date() if po.created_at else today)
        _upsert_auto(db, key, {
            "kind": "missing_ack",
            "title": f"{po.po_number} has no supplier acknowledgement",
            "detail": f"{po.vendor_name or 'Supplier'} · sales orders {', '.join(po.so_numbers_json or []) or '—'}",
            "so_number": (po.so_numbers_json or [None])[0],
            "po_number": po.po_number,
            "due_at": _at(anchor + timedelta(days=ACK_GRACE_DAYS)),
        })
    _close_missing(db, STRUCTURAL_KINDS, keep)


def _queue_customer_update(db: Session, order: OpsTrackedOrder, from_edit: bool = False) -> None:
    """Draft a customer email when the expected date moves.

    The first date recorded from Business Central is the baseline and does
    not email the whole open book. A later move does. A date typed in the
    portal (`from_edit`) drafts as soon as it differs from that baseline.
    """
    if not order.updates_baselined:
        order.customer_update_baseline = order.expected_receipt
        order.updates_baselined = True
        if not from_edit:
            return
    new_date = order.expected_receipt
    if not from_edit and order.customer_update_baseline is None and new_date is not None:
        order.customer_update_baseline = new_date
        return
    if new_date is None or new_date == order.customer_update_baseline:
        pending = (
            db.query(OpsOutboundMessage)
            .filter(
                OpsOutboundMessage.kind == "customer_update",
                OpsOutboundMessage.so_number == order.so_number,
                OpsOutboundMessage.status == "pending",
            )
            .all()
        )
        for row in pending:
            row.status = "withdrawn"
            row.updated_at = datetime.utcnow()
        return
    dedupe = f"customer:{order.so_number}:{new_date.isoformat()}"
    already = (
        db.query(OpsOutboundMessage)
        .filter(
            OpsOutboundMessage.dedupe_key == dedupe,
            OpsOutboundMessage.status.in_(["sent", "rejected"]),
        )
        .first()
    )
    if already:
        return
    body = _customer_body(order, new_date, order.customer_update_baseline)
    subject = f"Production update for {order.so_number}"
    context = {
        "old_date": _iso(order.customer_update_baseline),
        "new_date": new_date.isoformat(),
        "customer_name": order.customer_name,
    }
    pending = (
        db.query(OpsOutboundMessage)
        .filter(
            OpsOutboundMessage.kind == "customer_update",
            OpsOutboundMessage.so_number == order.so_number,
            OpsOutboundMessage.status == "pending",
        )
        .one_or_none()
    )
    now = datetime.utcnow()
    if pending is None:
        db.add(
            OpsOutboundMessage(
                kind="customer_update",
                status="pending",
                dedupe_key=dedupe,
                to_email=order.customer_email or None,
                subject=subject,
                body_text=body,
                so_number=order.so_number,
                context_json=context,
                created_at=now,
                updated_at=now,
            )
        )
        return
    pending.dedupe_key = dedupe
    pending.subject = subject
    pending.body_text = body
    pending.context_json = context
    pending.updated_at = now
    if not pending.to_email and order.customer_email:
        pending.to_email = order.customer_email


def _queue_supplier_reminders(db: Session, today: date) -> None:
    pos = db.query(OpsTrackedPo).filter(OpsTrackedPo.bc_open.is_(True)).all()
    names = {
        order.so_number: order.customer_name
        for order in db.query(OpsTrackedOrder).all()
    }
    for po in pos:
        status = (po.status or "").lower()
        if status == "draft" or po.fully_received:
            _withdraw_supplier(db, po.po_number)
            continue
        if po.ack_status in HEARD_FROM_SUPPLIER:
            _withdraw_supplier(db, po.po_number)
            continue
        anchor = po.order_date or (po.created_at.date() if po.created_at else today)
        if (today - anchor).days < ACK_GRACE_DAYS:
            continue
        pending = (
            db.query(OpsOutboundMessage)
            .filter(
                OpsOutboundMessage.kind == "supplier_reminder",
                OpsOutboundMessage.po_number == po.po_number,
                OpsOutboundMessage.status == "pending",
            )
            .one_or_none()
        )
        last = (
            db.query(OpsOutboundMessage)
            .filter(
                OpsOutboundMessage.kind == "supplier_reminder",
                OpsOutboundMessage.po_number == po.po_number,
                OpsOutboundMessage.status == "sent",
            )
            .order_by(OpsOutboundMessage.sent_at.desc())
            .first()
        )
        if last and last.sent_at and (today - last.sent_at.date()).days < REMINDER_INTERVAL_DAYS:
            continue
        customers = ", ".join(name for name in (names.get(so) for so in (po.so_numbers_json or [])) if name)
        body = _supplier_body(po, customers)
        subject = f"Acknowledgement needed for {po.po_number}"
        cycle = (
            db.query(OpsOutboundMessage)
            .filter(
                OpsOutboundMessage.kind == "supplier_reminder",
                OpsOutboundMessage.po_number == po.po_number,
                OpsOutboundMessage.status == "sent",
            )
            .count()
        ) + 1
        dedupe = f"supplier:{po.po_number}:{cycle}"
        now = datetime.utcnow()
        if pending is None:
            db.add(
                OpsOutboundMessage(
                    kind="supplier_reminder",
                    status="pending",
                    dedupe_key=dedupe,
                    to_email=po.vendor_email or None,
                    subject=subject,
                    body_text=body,
                    so_number=(po.so_numbers_json or [None])[0],
                    po_number=po.po_number,
                    context_json={"cycle": cycle, "vendor": po.vendor_name},
                    created_at=now,
                    updated_at=now,
                )
            )
        elif not pending.to_email and po.vendor_email:
            pending.to_email = po.vendor_email
            pending.updated_at = now


def _withdraw_supplier(db: Session, po_number: str) -> None:
    rows = (
        db.query(OpsOutboundMessage)
        .filter(
            OpsOutboundMessage.kind == "supplier_reminder",
            OpsOutboundMessage.po_number == po_number,
            OpsOutboundMessage.status == "pending",
        )
        .all()
    )
    now = datetime.utcnow()
    for row in rows:
        row.status = "withdrawn"
        row.updated_at = now


def _reconcile_mail(db: Session, emails: dict, today: date) -> None:
    meta = _meta(db)
    meta.mail_available = bool(emails.get("available"))
    meta.mail_reason = emails.get("reason")
    meta.last_mail_check_at = datetime.utcnow()
    meta.updated_at = datetime.utcnow()
    if not emails.get("available"):
        return
    mailbox = (emails.get("mailbox") or tracker_mailbox()).lower()
    needed = messages_needing_reply(emails.get("inbox") or [], emails.get("sent") or [], mailbox, today)
    keep = set()
    for message in needed:
        key = f"reply:{message['id']}"
        keep.add(key)
        due = message["received_at"].date() + timedelta(days=1) if message["received_at"] else today
        _upsert_auto(db, key, {
            "kind": "needs_reply",
            "title": f"Reply to {message['from_name'] or message['from_email'] or 'someone'}: {message['subject']}",
            "detail": (message["preview"] or "")[:500],
            "source_ref": message["id"],
            "due_at": _at(due),
            "payload_json": {
                "from_email": message["from_email"],
                "subject": message["subject"],
                "web_link": message["web_link"],
                "conversation_id": message["conversation_id"],
            },
        })
    _close_missing(db, ("needs_reply",), keep)


def apply_snapshot(
    db: Session,
    snapshot: dict,
    actor: Optional[Actor] = None,
    today: Optional[date] = None,
    allow_empty: bool = False,
) -> dict:
    """Merge a normalized snapshot into the tracker. Does not send mail."""
    today = today or date.today()
    actor = actor or Actor(email="Business Central", source="sync")
    orders_in = snapshot.get("orders") or []
    if not orders_in and not allow_empty:
        existing = db.query(OpsTrackedOrder).filter(OpsTrackedOrder.bc_open.is_(True)).count()
        if existing:
            raise OpsTrackerError(
                "Refusing to close every open sales order because Business Central returned none.",
                status=409,
            )
    if "purchase_orders" in snapshot and not (snapshot.get("purchase_orders") or []) and not allow_empty:
        existing_pos = db.query(OpsTrackedPo).filter(OpsTrackedPo.bc_open.is_(True)).count()
        if existing_pos:
            raise OpsTrackerError(
                "Refusing to drop every open purchase order because Business Central returned none.",
                status=409,
            )

    options = _vendor_options(snapshot.get("vendors"))
    email_by_vendor = {
        (row.get("number") or row.get("code") or "").upper(): row.get("email")
        for row in (snapshot.get("vendors") or [])
        if row.get("email")
    }
    acks = list(snapshot.get("acks") or [])
    receipt_on: Dict[str, date] = {}
    for receipt in snapshot.get("receipts") or []:
        number = _po_key(receipt.get("po_number") or receipt.get("orderNumber"))
        posted = parse_date(receipt.get("posting_date") or receipt.get("postingDate"))
        if number and posted and (number not in receipt_on or posted > receipt_on[number]):
            receipt_on[number] = posted

    seen_pos = set()
    po_dicts: Dict[str, dict] = {}
    if "purchase_orders" in snapshot:
        for raw in snapshot.get("purchase_orders") or []:
            number = (raw.get("number") or "").strip()
            if not number:
                continue
            seen_pos.add(number)
            po_dicts[number] = raw
            row = db.query(OpsTrackedPo).filter(OpsTrackedPo.po_number == number).one_or_none()
            created = row is None
            if created:
                row = OpsTrackedPo(po_number=number, created_at=datetime.utcnow())
                db.add(row)
            ack_status, vendor_order, received_at, expected = _ack_fields(raw, _ack_for(number, acks))
            vendor_email = raw.get("vendor_email") or email_by_vendor.get((raw.get("vendor_number") or "").upper())
            row.vendor_number = raw.get("vendor_number") or row.vendor_number
            row.vendor_name = raw.get("vendor_name") or row.vendor_name
            if vendor_email and not row.vendor_email_locked:
                row.vendor_email = vendor_email
            row.status = raw.get("status") or row.status
            row.order_date = parse_date(raw.get("order_date")) or row.order_date
            row.expected_date = expected
            if number.upper() in receipt_on:
                row.receipt_date = receipt_on[number.upper()]
            row.vendor_order_no = vendor_order
            row.ack_status = ack_status
            if received_at:
                row.ack_received_at = received_at
            row.so_numbers_json = _so_numbers_from_po(raw)
            row.fully_received = _fully_received(raw)
            row.bc_open = True
            row.updated_at = datetime.utcnow()
            if created:
                db.flush()
        if seen_pos or allow_empty or orders_in:
            for row in db.query(OpsTrackedPo).all():
                if row.po_number not in seen_pos:
                    row.bc_open = False
                    row.updated_at = datetime.utcnow()

    seen_orders = set()
    for raw in orders_in:
        number = (raw.get("number") or "").strip().upper()
        if not number:
            continue
        seen_orders.add(number)
        order = db.query(OpsTrackedOrder).filter(OpsTrackedOrder.so_number == number).one_or_none()
        is_new = order is None
        if is_new:
            order = OpsTrackedOrder(so_number=number, created_at=datetime.utcnow(), updated_at=datetime.utcnow())
            db.add(order)
            db.flush()
        key = f"order:{number}"
        audit = not is_new
        _assign(db, order, "order", key, "customer_name", raw.get("customer_name") or order.customer_name, actor, audit)
        _assign(db, order, "order", key, "customer_number", raw.get("customer_number") or order.customer_number, actor, audit)
        if raw.get("customer_email"):
            _assign(db, order, "order", key, "customer_email", raw.get("customer_email"), actor, audit)
        _assign(
            db, order, "order", key, "external_document_number",
            raw.get("external_document_number") or "", actor, audit,
        )
        order.bc_order_id = raw.get("id") or order.bc_order_id
        order.order_date = parse_date(raw.get("order_date")) or order.order_date
        order.bc_status = raw.get("status") or order.bc_status
        order.fully_shipped = bool(raw.get("fully_shipped"))
        order.bc_open = True
        if is_new and not order.fulfillment:
            order.fulfillment = "Buy Complete"

        related = [
            po_dicts[po.po_number]
            for po in db.query(OpsTrackedPo).filter(OpsTrackedPo.bc_open.is_(True)).all()
            if number in (po.so_numbers_json or []) and po.po_number in po_dicts
        ]
        # POs linked by number even when this snapshot didn't include the PO dict.
        related_rows = [
            po for po in db.query(OpsTrackedPo).filter(OpsTrackedPo.bc_open.is_(True)).all()
            if number in (po.so_numbers_json or [])
        ]
        seen_lines = set()
        for raw_line in raw.get("lines") or []:
            if (raw_line.get("line_type") or "Item") not in {"Item", "Resource"}:
                continue
            item_no = (raw_line.get("item_no") or "").strip()
            if not item_no:
                continue
            line_no = int(raw_line.get("line_no") or 0)
            seen_lines.add(line_no)
            line = (
                db.query(OpsTrackedLine)
                .filter(OpsTrackedLine.so_number == number, OpsTrackedLine.bc_line_no == line_no)
                .one_or_none()
            )
            line_new = line is None
            if line_new:
                line = OpsTrackedLine(
                    order_id=order.id,
                    so_number=number,
                    bc_line_no=line_no,
                    source_code=SOURCE_UPW,
                    source_label=UPW_LABEL,
                    created_at=datetime.utcnow(),
                )
                db.add(line)
                db.flush()
            line_key = f"line:{number}:{line_no}"
            line_audit = not line_new
            _assign(db, line, "line", line_key, "item_no", item_no, actor, line_audit)
            _assign(db, line, "line", line_key, "description", raw_line.get("description") or "", actor, line_audit)
            line.quantity = float(raw_line.get("quantity") or 0)
            line.quantity_shipped = float(raw_line.get("shipped_quantity") or 0)
            line.line_type = raw_line.get("line_type") or "Item"
            line.active = True
            line.updated_at = datetime.utcnow()
            if not line.po_locked:
                chosen = _pick_po(item_no, related)
                new_po = chosen.get("number") if chosen else None
                _assign(db, line, "line", line_key, "linked_po_number", new_po, actor, line_audit and bool(line.linked_po_number or new_po))
            if not line.source_locked:
                if line.linked_po_number and line.linked_po_number in po_dicts:
                    code, label = _source_for_vendor(po_dicts[line.linked_po_number], options)
                    if not (item_no.upper().startswith("OP") and code == SOURCE_UPW and line_new):
                        _assign(db, line, "line", line_key, "source_code", code, actor, line_audit)
                        line.source_label = label
                elif line_new:
                    line.source_code = SOURCE_UPW
                    line.source_label = UPW_LABEL
            linked = next((po for po in related_rows if po.po_number == line.linked_po_number), None)
            supplier_expected = linked.expected_date if linked else None
            line.supplier_expected = supplier_expected
            if not line.expected_date_locked:
                _assign(db, line, "line", line_key, "expected_date", supplier_expected, actor, line_audit)
            if not line.ack_locked:
                if line.source_code == SOURCE_STOCK:
                    line.ack_status = "not_required"
                elif linked:
                    line.ack_status = linked.ack_status
                else:
                    line.ack_status = "none"
        for line in list(order.lines):
            if line.bc_line_no not in seen_lines:
                line.active = False

        upwardor = []
        po_dates = []
        link_rows = []
        for po in related_rows:
            if po.order_date:
                po_dates.append(po.order_date)
            if _is_upwardor(po.vendor_number, po.vendor_name):
                upwardor.append(po.po_number)
            link_rows.append({
                "po_number": po.po_number,
                "vendor_number": po.vendor_number,
                "vendor_name": po.vendor_name,
                "status": po.status,
                "order_date": _iso(po.order_date),
                "expected_date": _iso(po.expected_date),
                "ack_status": po.ack_status,
                "vendor_order_no": po.vendor_order_no,
            })
        order.po_links_json = link_rows
        order.po_date = min(po_dates) if po_dates else None
        order.upwardor_po_number = ", ".join(upwardor) or None
        computed_status = _order_status_from_pos([po_dicts[po.po_number] for po in related_rows if po.po_number in po_dicts] or [
            {"status": po.status, "lines": []} for po in related_rows
        ])
        # A PO we already stored but didn't get lines for still counts as ordered
        # when its status is not Draft. _order_status_from_pos handles status.
        if not related_rows:
            computed_status = "Waiting to Order"
        order.order_status = _rank_advance(order.order_status if not is_new else "", computed_status, _ORDER_RANK) or computed_status
        if order.fully_shipped:
            order.shipping_status = _rank_advance(order.shipping_status, "Shipped", _SHIP_RANK)
        supplier_dates = [line.supplier_expected for line in order.lines if line.active and line.supplier_expected]
        if not supplier_dates:
            supplier_dates = [po.expected_date for po in related_rows if po.expected_date]
        order.supplier_expected = min(supplier_dates) if supplier_dates else None
        if not order.expected_receipt_locked:
            previous = order.expected_receipt
            order.expected_receipt = order.supplier_expected
            if audit and _text(previous) != _text(order.expected_receipt):
                _audit(db, "order", key, "expected_receipt", previous, order.expected_receipt, actor)
        active_items = [line.item_no or "" for line in order.lines if line.active]
        if any(item.upper().startswith("GK") for item in active_items) and not order.window_kits:
            order.window_kits = "Not Started"
        if any(item.upper().startswith("OP") for item in active_items) and not order.operators:
            order.operators = "Waiting to Order"
        order.updated_at = datetime.utcnow()
        _queue_customer_update(db, order)

    for order in db.query(OpsTrackedOrder).all():
        if order.so_number not in seen_orders:
            order.bc_open = False
            order.updated_at = datetime.utcnow()

    meta = _meta(db)
    meta.vendors_json = options
    meta.last_sync_at = datetime.utcnow()
    meta.last_sync_error = None
    meta.updated_at = datetime.utcnow()
    db.flush()
    _refresh_structural(db, today)
    _queue_supplier_reminders(db, today)
    if "emails" in snapshot and snapshot.get("emails") is not None:
        _reconcile_mail(db, snapshot.get("emails") or {}, today)
    db.flush()
    return {"orders": len(seen_orders), "purchase_orders": len(seen_pos)}


def snapshot_from_bc(bc: Any, db: Session) -> dict:
    """Read open sales orders, purchase orders, receipts, vendors, and stored acks."""
    sales = bc.get_open_sales_orders_with_lines() or []
    purchase_orders = bc.get_open_purchase_orders_with_lines() or []
    try:
        vendors = bc.get_vendors(top=500) or []
    except Exception as exc:
        logger.warning("Vendor list unavailable: %s", exc)
        vendors = []
    try:
        receipts = bc.get_purchase_receipts_with_lines() or []
    except Exception as exc:
        logger.warning("Purchase receipts unavailable: %s", exc)
        receipts = []
    acks = []
    for row in db.query(VendorOrderAck).all():
        acks.append({
            "po_number": row.our_po_number,
            "status": row.status,
            "completion_date": _iso(row.completion_date),
            "received_at": row.received_at.isoformat() if row.received_at else None,
            "vendor_order_no": row.vendor_order_no,
            "vendor_no": row.vendor_no,
        })
    return {
        "orders": [_normalize_sales_order(row) for row in sales],
        "purchase_orders": [_normalize_purchase_order(row) for row in purchase_orders],
        "vendors": [_normalize_vendor(row) for row in vendors],
        "receipts": [
            {
                "po_number": row.get("orderNumber"),
                "posting_date": row.get("postingDate"),
            }
            for row in receipts
        ],
        "acks": [ack for ack in acks if ack.get("po_number")],
    }


def _normalize_sales_order(row: dict) -> dict:
    lines = []
    for line in row.get("salesOrderLines") or row.get("lines") or []:
        lines.append({
            "line_no": line.get("sequence") or line.get("lineNo") or line.get("line_no") or 0,
            "item_no": line.get("lineObjectNumber") or line.get("item_no") or "",
            "description": line.get("description") or "",
            "quantity": line.get("quantity") or 0,
            "shipped_quantity": line.get("shippedQuantity") or line.get("shipped_quantity") or 0,
            "line_type": line.get("lineType") or line.get("line_type") or "Item",
        })
    return {
        "number": row.get("number") or "",
        "id": row.get("id"),
        "customer_number": row.get("customerNumber") or row.get("customer_number"),
        "customer_name": row.get("customerName") or row.get("customer_name"),
        "customer_email": row.get("email") or row.get("customer_email"),
        "external_document_number": row.get("externalDocumentNumber") or row.get("external_document_number") or "",
        "order_date": row.get("orderDate") or row.get("order_date"),
        "status": row.get("status"),
        "fully_shipped": bool(row.get("fullyShipped") or row.get("fully_shipped")),
        "lines": lines,
    }


def _normalize_purchase_order(row: dict) -> dict:
    lines = []
    for line in row.get("purchaseOrderLines") or row.get("lines") or []:
        lines.append({
            "item_no": line.get("lineObjectNumber") or line.get("item_no") or "",
            "description": line.get("description") or "",
            "quantity": line.get("quantity") or 0,
            "received_quantity": line.get("receivedQuantity") or line.get("received_quantity") or 0,
            "line_type": line.get("lineType") or line.get("line_type") or "Item",
        })
    return {
        "number": row.get("number") or "",
        "vendor_number": row.get("vendorNumber") or row.get("vendor_number"),
        "vendor_name": row.get("vendorName") or row.get("vendor_name"),
        "vendor_email": row.get("vendor_email"),
        "status": row.get("status"),
        "order_date": row.get("orderDate") or row.get("order_date"),
        "expected_date": row.get("requestedReceiptDate") or row.get("expectedReceiptDate") or row.get("expected_date"),
        "vendor_order_no": row.get("vendorOrderNumber") or row.get("vendor_order_no") or "",
        "external_document_number": row.get("externalDocumentNumber") or row.get("external_document_number") or "",
        "lines": lines,
    }


def _normalize_vendor(row: dict) -> dict:
    return {
        "number": row.get("number") or "",
        "name": row.get("displayName") or row.get("name") or "",
        "email": row.get("email") or None,
    }


def read_mailbox(graph: Any, mailbox: Optional[str] = None) -> dict:
    """Read Joey's inbox. A missing Graph app is reported, not raised."""
    mailbox = mailbox or tracker_mailbox()
    if graph is None or getattr(graph, "app", None) is None:
        return {
            "available": False,
            "mailbox": mailbox,
            "reason": (
                "Outlook is not connected for this server. Set GRAPH_TENANT_ID, GRAPH_CLIENT_ID, "
                "and GRAPH_CLIENT_SECRET with Mail.Read and Mail.Send. Until then, POST /api/ops/inbox "
                "can feed the messages that still need a reply."
            ),
            "inbox": [],
            "sent": [],
        }
    try:
        inbox = graph.get_inbox_emails(mailbox, max_count=40)
        sent = graph.get_sent_emails(mailbox, days_back=REPLY_LOOKBACK_DAYS, max_count=80)
    except Exception as exc:
        logger.warning("Mailbox read failed: %s", exc)
        return {
            "available": False,
            "mailbox": mailbox,
            "reason": (
                f"Outlook could not be read ({exc}). POST /api/ops/inbox can feed messages "
                "until Mail.Read is available."
            ),
            "inbox": [],
            "sent": [],
        }
    return {"available": True, "reason": None, "mailbox": mailbox, "inbox": inbox, "sent": sent}


def run_sync(db: Session, bc: Any, graph: Any, actor: Optional[Actor] = None, today: Optional[date] = None, allow_empty: bool = False) -> dict:
    snapshot = snapshot_from_bc(bc, db)
    snapshot["emails"] = read_mailbox(graph)
    return apply_snapshot(db, snapshot, actor=actor, today=today, allow_empty=allow_empty)


def feed_mail(db: Session, emails: dict, today: Optional[date] = None) -> dict:
    today = today or date.today()
    payload = dict(emails or {})
    payload.setdefault("available", True)
    payload.setdefault("mailbox", tracker_mailbox())
    _reconcile_mail(db, payload, today)
    db.flush()
    return {"open_replies": _count_open(db, "needs_reply")}


def _count_open(db: Session, kind: Optional[str] = None) -> int:
    query = db.query(OpsActionItem).filter(OpsActionItem.status == "open")
    if kind:
        query = query.filter(OpsActionItem.kind == kind)
    return query.count()


def _order_or_404(db: Session, so_number: str) -> OpsTrackedOrder:
    order = db.query(OpsTrackedOrder).filter(OpsTrackedOrder.so_number == so_number.strip().upper()).one_or_none()
    if order is None:
        raise OpsTrackerError(f"No tracker row for {so_number}.", status=404)
    return order


def patch_order(db: Session, so_number: str, fields: dict, actor: Actor, today: Optional[date] = None) -> dict:
    today = today or date.today()
    order = _order_or_404(db, so_number)
    key = f"order:{order.so_number}"
    if fields.get("use_supplier_date"):
        _assign(db, order, "order", key, "expected_receipt", order.supplier_expected, actor, True)
        order.expected_receipt_locked = False
    if "expected_receipt" in fields and not fields.get("use_supplier_date"):
        _assign(db, order, "order", key, "expected_receipt", parse_date(fields.get("expected_receipt")), actor, True)
        order.expected_receipt_locked = True
    if "fulfillment" in fields:
        _assign(db, order, "order", key, "fulfillment", _choice(fields.get("fulfillment"), FULFILLMENT_CHOICES, "Fulfillment"), actor, True)
    if "order_status" in fields:
        _assign(db, order, "order", key, "order_status", _choice(fields.get("order_status"), ORDER_STATES, "Order status"), actor, True)
    if "operators" in fields:
        _assign(db, order, "order", key, "operators", _choice(fields.get("operators"), OPERATOR_STATES, "Operators"), actor, True)
    if "window_kits" in fields:
        _assign(db, order, "order", key, "window_kits", _choice(fields.get("window_kits"), WINDOW_KIT_STATES, "Window kits"), actor, True)
    if "emergency_build" in fields:
        _assign(db, order, "order", key, "emergency_build", _choice(fields.get("emergency_build"), BUILD_STATES, "Emergency build"), actor, True)
    if "shipping_status" in fields:
        _assign(db, order, "order", key, "shipping_status", _choice(fields.get("shipping_status"), SHIPPING_STATES, "Shipping status"), actor, True)
    if "notes" in fields:
        _assign(db, order, "order", key, "notes", fields.get("notes") or "", actor, True)
    if "customer_email" in fields:
        _assign(db, order, "order", key, "customer_email", (fields.get("customer_email") or "").strip() or None, actor, True)
    order.updated_at = datetime.utcnow()
    order.updated_by_user_id = actor.user_id
    _queue_customer_update(db, order, from_edit=True)
    _refresh_structural(db, today)
    db.flush()
    return _order_dict(order, today, [])


def patch_line(db: Session, line_id: int, fields: dict, actor: Actor, today: Optional[date] = None) -> dict:
    today = today or date.today()
    line = db.query(OpsTrackedLine).filter(OpsTrackedLine.id == line_id).one_or_none()
    if line is None:
        raise OpsTrackerError("Line not found.", status=404)
    order = line.order
    key = f"line:{line.so_number}:{line.bc_line_no}"
    options = (_meta(db).vendors_json or _vendor_options())
    if fields.get("use_supplier_date"):
        _assign(db, line, "line", key, "expected_date", line.supplier_expected, actor, True)
        line.expected_date_locked = False
    if "source_code" in fields:
        code = (fields.get("source_code") or "").strip()
        if not code:
            raise OpsTrackerError("Choose a supplier.")
        label = (fields.get("source_label") or "").strip() or _label_for(code, options)
        _assign(db, line, "line", key, "source_code", code, actor, True)
        line.source_label = label
        line.source_locked = True
        if code == SOURCE_STOCK and not line.ack_locked:
            line.ack_status = "not_required"
    if "linked_po_number" in fields:
        number = (fields.get("linked_po_number") or "").strip() or None
        _assign(db, line, "line", key, "linked_po_number", number, actor, True)
        line.po_locked = True
    if "ack_status" in fields:
        _assign(db, line, "line", key, "ack_status", _choice(fields.get("ack_status"), ACK_STATES, "Acknowledgement"), actor, True)
        line.ack_locked = True
    if "expected_date" in fields and not fields.get("use_supplier_date"):
        _assign(db, line, "line", key, "expected_date", parse_date(fields.get("expected_date")), actor, True)
        line.expected_date_locked = True
    if "notes" in fields:
        _assign(db, line, "line", key, "notes", fields.get("notes") or "", actor, True)
    line.updated_at = datetime.utcnow()
    if line.expected_date_locked and not order.expected_receipt_locked:
        dates = [item.expected_date for item in order.lines if item.active and item.expected_date]
        previous = order.expected_receipt
        order.expected_receipt = min(dates) if dates else order.expected_receipt
        if _text(previous) != _text(order.expected_receipt):
            _audit(db, "order", f"order:{order.so_number}", "expected_receipt", previous, order.expected_receipt, actor)
    order.updated_at = datetime.utcnow()
    order.updated_by_user_id = actor.user_id
    _queue_customer_update(db, order, from_edit=True)
    _refresh_structural(db, today)
    db.flush()
    return _line_dict(line)


def patch_po(db: Session, po_number: str, fields: dict, actor: Actor) -> dict:
    po = db.query(OpsTrackedPo).filter(OpsTrackedPo.po_number == po_number.strip()).one_or_none()
    if po is None:
        raise OpsTrackerError(f"No purchase order {po_number}.", status=404)
    key = f"po:{po.po_number}"
    if "notes" in fields:
        _assign(db, po, "po", key, "notes", fields.get("notes") or "", actor, True)
    if "vendor_email" in fields:
        _assign(db, po, "po", key, "vendor_email", (fields.get("vendor_email") or "").strip() or None, actor, True)
        po.vendor_email_locked = True
        pending = (
            db.query(OpsOutboundMessage)
            .filter(
                OpsOutboundMessage.po_number == po.po_number,
                OpsOutboundMessage.kind == "supplier_reminder",
                OpsOutboundMessage.status == "pending",
            )
            .all()
        )
        for message in pending:
            if not message.to_email:
                message.to_email = po.vendor_email
    po.updated_at = datetime.utcnow()
    db.flush()
    return _po_dict(po, date.today())


def create_follow_up(db: Session, fields: dict, actor: Actor) -> dict:
    title = (fields.get("title") or "").strip()
    if not title:
        raise OpsTrackerError("A follow-up needs a title.")
    due = parse_date(fields.get("due_on") or fields.get("due_at"))
    row = OpsActionItem(
        kind="follow_up",
        auto_key=None,
        auto_managed=False,
        title=title,
        detail=(fields.get("detail") or "").strip() or None,
        so_number=(fields.get("so_number") or "").strip().upper() or None,
        po_number=(fields.get("po_number") or "").strip() or None,
        due_at=_at(due) if due else None,
        status="open",
        created_at=datetime.utcnow(),
    )
    db.add(row)
    db.flush()
    _audit(db, "action", f"action:{row.id}", "status", None, "open", actor)
    return _action_dict(row, date.today())


def complete_action(db: Session, action_id: int, actor: Actor) -> dict:
    row = db.query(OpsActionItem).filter(OpsActionItem.id == action_id).one_or_none()
    if row is None:
        raise OpsTrackerError("To-do not found.", status=404)
    if row.status == "done":
        return _action_dict(row, date.today())
    if row.kind in STRUCTURAL_KINDS:
        raise OpsTrackerError("This closes when the purchase order, acknowledgement, or date is on the order.")
    row.status = "done"
    row.auto_managed = False
    row.closed_at = datetime.utcnow()
    row.closed_by_user_id = actor.user_id
    _audit(db, "action", f"action:{row.id}", "status", "open", "done", actor)
    db.flush()
    return _action_dict(row, date.today())


def update_message(db: Session, message_id: int, fields: dict, actor: Actor) -> dict:
    message = _message_or_404(db, message_id)
    if message.status != "pending":
        raise OpsTrackerError("Only a pending email can be edited.")
    if "to_email" in fields:
        _assign(db, message, "message", f"message:{message.id}", "to_email", (fields.get("to_email") or "").strip() or None, actor, True)
    if "subject" in fields:
        subject = (fields.get("subject") or "").strip()
        if not subject:
            raise OpsTrackerError("Subject is required.")
        _assign(db, message, "message", f"message:{message.id}", "subject", subject, actor, True)
    if "body_text" in fields:
        body = fields.get("body_text") or ""
        if not body.strip():
            raise OpsTrackerError("Body is required.")
        _assign(db, message, "message", f"message:{message.id}", "body_text", body, actor, True)
    message.updated_at = datetime.utcnow()
    db.flush()
    return _message_dict(message)


def approve_message(
    db: Session,
    message_id: int,
    actor: Actor,
    sender: Callable[[dict], None],
    now: Optional[datetime] = None,
) -> dict:
    message = _message_or_404(db, message_id)
    if message.status != "pending":
        raise OpsTrackerError("Only a pending email can be sent.", status=409)
    if not message.to_email or "@" not in message.to_email:
        raise OpsTrackerError("Add a recipient address before sending.")
    now = now or datetime.utcnow()
    payload = {
        "to_email": message.to_email,
        "subject": message.subject,
        "body_text": message.body_text,
        "kind": message.kind,
        "so_number": message.so_number,
        "po_number": message.po_number,
    }
    try:
        sender(payload)
    except Exception as exc:
        message.send_error = str(exc)[:2000]
        message.updated_at = now
        db.commit()
        raise OpsTrackerError(f"The email was not sent: {exc}", status=502)
    message.status = "sent"
    message.sent_at = now
    message.approved_at = now
    message.approved_by_user_id = actor.user_id
    message.send_error = None
    message.updated_at = now
    _audit(db, "message", f"message:{message.id}", "status", "pending", "sent", actor)
    if message.kind == "customer_update" and message.so_number:
        order = db.query(OpsTrackedOrder).filter(OpsTrackedOrder.so_number == message.so_number).one_or_none()
        new_date = parse_date((message.context_json or {}).get("new_date"))
        if order and new_date:
            previous = order.customer_update_baseline
            order.customer_update_baseline = new_date
            _audit(db, "order", f"order:{order.so_number}", "customer_update_sent", previous, new_date, actor)
    db.flush()
    return _message_dict(message)


def reject_message(db: Session, message_id: int, actor: Actor) -> dict:
    message = _message_or_404(db, message_id)
    if message.status != "pending":
        raise OpsTrackerError("Only a pending email can be rejected.", status=409)
    message.status = "rejected"
    message.rejected_at = datetime.utcnow()
    message.updated_at = datetime.utcnow()
    _audit(db, "message", f"message:{message.id}", "status", "pending", "rejected", actor)
    db.flush()
    return _message_dict(message)


def _message_or_404(db: Session, message_id: int) -> OpsOutboundMessage:
    message = db.query(OpsOutboundMessage).filter(OpsOutboundMessage.id == message_id).one_or_none()
    if message is None:
        raise OpsTrackerError("Email not found.", status=404)
    return message


def _line_dict(line: OpsTrackedLine) -> dict:
    return {
        "id": line.id,
        "so_number": line.so_number,
        "line_no": line.bc_line_no,
        "item_no": line.item_no,
        "description": line.description,
        "quantity": line.quantity,
        "quantity_shipped": line.quantity_shipped,
        "source_code": line.source_code,
        "source_label": line.source_label,
        "source_locked": line.source_locked,
        "linked_po_number": line.linked_po_number,
        "ack_status": line.ack_status,
        "expected_date": _iso(line.expected_date),
        "supplier_expected": _iso(line.supplier_expected),
        "expected_date_locked": line.expected_date_locked,
        "notes": line.notes or "",
        "active": line.active,
    }


def _order_dict(order: OpsTrackedOrder, today: date, communications: List[dict]) -> dict:
    late_days = 0
    at_risk = False
    if (
        order.expected_receipt
        and order.expected_receipt < today
        and order.shipping_status != "Shipped"
        and order.order_status != "Received"
        and order.bc_open
    ):
        at_risk = True
        late_days = (today - order.expected_receipt).days
    lines = [_line_dict(line) for line in order.lines if line.active]
    return {
        "so_number": order.so_number,
        "customer_number": order.customer_number,
        "customer_name": order.customer_name,
        "customer_email": order.customer_email,
        "external_document_number": order.external_document_number or "",
        "order_date": _iso(order.order_date),
        "po_date": _iso(order.po_date),
        "fulfillment": order.fulfillment,
        "upwardor_po_number": order.upwardor_po_number or "",
        "order_status": order.order_status,
        "expected_receipt": _iso(order.expected_receipt),
        "supplier_expected": _iso(order.supplier_expected),
        "expected_receipt_locked": order.expected_receipt_locked,
        "operators": order.operators or "",
        "window_kits": order.window_kits or "",
        "emergency_build": order.emergency_build or "",
        "shipping_status": order.shipping_status,
        "notes": order.notes or "",
        "bc_open": order.bc_open,
        "fully_shipped": order.fully_shipped,
        "at_risk": at_risk,
        "days_late": late_days,
        "lines": lines,
        "purchase_orders": order.po_links_json or [],
        "communications": communications,
        "updated_at": order.updated_at.isoformat() if order.updated_at else None,
    }


def _po_dict(po: OpsTrackedPo, today: date) -> dict:
    anchor = po.order_date
    age = (today - anchor).days if anchor else None
    return {
        "po_number": po.po_number,
        "vendor_number": po.vendor_number,
        "vendor_name": po.vendor_name,
        "vendor_email": po.vendor_email,
        "status": po.status,
        "order_date": _iso(po.order_date),
        "expected_date": _iso(po.expected_date),
        "receipt_date": _iso(po.receipt_date),
        "vendor_order_no": po.vendor_order_no,
        "ack_status": po.ack_status,
        "ack_received_at": po.ack_received_at.isoformat() if po.ack_received_at else None,
        "so_numbers": po.so_numbers_json or [],
        "fully_received": po.fully_received,
        "bc_open": po.bc_open,
        "notes": po.notes or "",
        "age_days": age,
        "needs_ack": po.bc_open and not po.fully_received and (po.status or "").lower() != "draft" and po.ack_status not in HEARD_FROM_SUPPLIER,
    }


def _action_dict(row: OpsActionItem, today: date) -> dict:
    overdue = bool(row.status == "open" and row.due_at and row.due_at.date() < today)
    return {
        "id": row.id,
        "kind": row.kind,
        "title": row.title,
        "detail": row.detail or "",
        "so_number": row.so_number,
        "po_number": row.po_number,
        "line_id": row.line_id,
        "due_at": row.due_at.isoformat() if row.due_at else None,
        "status": row.status,
        "auto_managed": row.auto_managed,
        "overdue": overdue,
        "source_ref": row.source_ref,
        "payload": row.payload_json or {},
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "closed_at": row.closed_at.isoformat() if row.closed_at else None,
    }


def _message_dict(row: OpsOutboundMessage) -> dict:
    return {
        "id": row.id,
        "kind": row.kind,
        "status": row.status,
        "to_email": row.to_email,
        "subject": row.subject,
        "body_text": row.body_text,
        "so_number": row.so_number,
        "po_number": row.po_number,
        "context": row.context_json or {},
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "sent_at": row.sent_at.isoformat() if row.sent_at else None,
        "rejected_at": row.rejected_at.isoformat() if row.rejected_at else None,
        "send_error": row.send_error,
        "approved_by_user_id": row.approved_by_user_id,
    }


def list_tracker(db: Session, today: Optional[date] = None, **filters) -> dict:
    today = today or date.today()
    _refresh_structural(db, today)
    _queue_supplier_reminders(db, today)
    db.flush()
    query = db.query(OpsTrackedOrder)
    if not filters.get("include_closed"):
        query = query.filter(OpsTrackedOrder.bc_open.is_(True))
    orders = query.all()
    sent = (
        db.query(OpsOutboundMessage)
        .filter(OpsOutboundMessage.status == "sent")
        .order_by(OpsOutboundMessage.sent_at.desc())
        .all()
    )
    by_so: Dict[str, List[dict]] = {}
    for message in sent:
        if message.so_number:
            by_so.setdefault(message.so_number, []).append(_message_dict(message))
    rows = []
    customer = (filters.get("customer") or "").strip().lower()
    status = (filters.get("status") or "").strip()
    supplier = (filters.get("supplier") or "").strip().lower()
    query_text = (filters.get("q") or "").strip().lower()
    at_risk_only = bool(filters.get("at_risk"))
    for order in orders:
        payload = _order_dict(order, today, (by_so.get(order.so_number) or [])[:5])
        if customer and customer not in (order.customer_name or "").lower() and customer not in (order.customer_number or "").lower():
            continue
        if status and order.order_status != status:
            continue
        if supplier:
            labels = " ".join(
                f"{line.source_code} {line.source_label}".lower() for line in order.lines if line.active
            )
            if supplier not in labels:
                continue
        if at_risk_only and not payload["at_risk"]:
            continue
        if query_text:
            blob = " ".join([
                order.so_number,
                order.customer_name or "",
                order.external_document_number or "",
                order.upwardor_po_number or "",
                order.notes or "",
                " ".join((line.item_no or "") + " " + (line.description or "") + " " + (line.linked_po_number or "") for line in order.lines),
            ]).lower()
            if query_text not in blob:
                continue
        rows.append(payload)
    rows.sort(key=lambda row: (row["order_date"] or "", row["so_number"]), reverse=True)
    meta = _meta(db)
    open_actions = db.query(OpsActionItem).filter(OpsActionItem.status == "open").count()
    pending = db.query(OpsOutboundMessage).filter(OpsOutboundMessage.status == "pending").count()
    return {
        "orders": rows,
        "purchase_orders": [
            _po_dict(po, today)
            for po in db.query(OpsTrackedPo).filter(OpsTrackedPo.bc_open.is_(True)).order_by(OpsTrackedPo.po_number).all()
        ],
        "vendors": meta.vendors_json or _vendor_options(),
        "choices": {
            "fulfillment": FULFILLMENT_CHOICES,
            "order_status": ORDER_STATES,
            "operators": OPERATOR_STATES,
            "window_kits": [item for item in WINDOW_KIT_STATES],
            "emergency_build": list(BUILD_STATES),
            "shipping_status": SHIPPING_STATES,
            "ack_status": ACK_STATES,
        },
        "mail": {"available": bool(meta.mail_available), "reason": meta.mail_reason},
        "synced_at": meta.last_sync_at.isoformat() if meta.last_sync_at else None,
        "counts": {
            "orders": len(rows),
            "at_risk": sum(1 for row in rows if row["at_risk"]),
            "open_actions": open_actions,
            "pending_approvals": pending,
        },
    }


def list_actions(db: Session, today: Optional[date] = None, status: str = "open") -> dict:
    today = today or date.today()
    _refresh_structural(db, today)
    db.flush()
    query = db.query(OpsActionItem)
    if status != "all":
        query = query.filter(OpsActionItem.status == status)
    rows = [_action_dict(row, today) for row in query.order_by(OpsActionItem.due_at.asc(), OpsActionItem.id.asc()).all()]
    meta = _meta(db)
    return {
        "actions": rows,
        "mail": {"available": bool(meta.mail_available), "reason": meta.mail_reason},
        "overdue": sum(1 for row in rows if row["overdue"]),
    }


def list_messages(db: Session, status: Optional[str] = None) -> dict:
    query = db.query(OpsOutboundMessage)
    if status:
        query = query.filter(OpsOutboundMessage.status == status)
    rows = [_message_dict(row) for row in query.order_by(OpsOutboundMessage.created_at.desc()).all()]
    return {"messages": rows}


def list_audit(db: Session, so_number: str) -> dict:
    prefix_line = f"line:{so_number.strip().upper()}:"
    order_key = f"order:{so_number.strip().upper()}"
    rows = (
        db.query(OpsFieldAudit)
        .filter((OpsFieldAudit.entity_key == order_key) | (OpsFieldAudit.entity_key.like(prefix_line + "%")))
        .order_by(OpsFieldAudit.created_at.desc(), OpsFieldAudit.id.desc())
        .limit(200)
        .all()
    )
    return {
        "audit": [
            {
                "id": row.id,
                "entity_type": row.entity_type,
                "entity_key": row.entity_key,
                "field": row.field_name,
                "old_value": row.old_value,
                "new_value": row.new_value,
                "actor_email": row.actor_email,
                "actor_user_id": row.actor_user_id,
                "source": row.source,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
            for row in rows
        ]
    }


def weekly_summary(db: Session, as_of: Optional[date] = None) -> dict:
    """Lead time, acknowledgement turnaround, late orders, and customer-update counts.

    Lead time is the purchase-order date to the expected receipt, or to the
    receipt posting date when the goods have arrived. Acknowledgement
    turnaround is the purchase-order date to the acknowledgement time, for
    acks in the last 90 days. Customer-update counts are the week that
    contains ``as_of`` (Monday through Sunday).
    """
    as_of = as_of or date.today()
    week_start = as_of - timedelta(days=as_of.weekday())
    week_end = week_start + timedelta(days=6)
    pos = {po.po_number: po for po in db.query(OpsTrackedPo).all()}
    buckets: Dict[str, dict] = {}
    for line in db.query(OpsTrackedLine).filter(OpsTrackedLine.active.is_(True)).all():
        po = pos.get(line.linked_po_number or "")
        if po is None or not po.order_date:
            continue
        end = po.receipt_date or line.expected_date or po.expected_date
        if not end:
            continue
        days = (end - po.order_date).days
        if days < 0:
            continue
        slot = buckets.setdefault(line.source_code or SOURCE_UPW, {
            "supplier": line.source_label or line.source_code,
            "source_code": line.source_code,
            "samples": 0,
            "total_days": 0,
        })
        slot["samples"] += 1
        slot["total_days"] += days
    lead = []
    for slot in buckets.values():
        lead.append({
            "supplier": slot["supplier"],
            "source_code": slot["source_code"],
            "samples": slot["samples"],
            "avg_lead_days": round(slot["total_days"] / slot["samples"], 1),
        })
    lead.sort(key=lambda row: row["supplier"] or "")

    ack_buckets: Dict[str, dict] = {}
    window = as_of - timedelta(days=ACK_TURNAROUND_DAYS)
    for po in pos.values():
        if not po.order_date or not po.ack_received_at:
            continue
        if po.ack_received_at.date() < window:
            continue
        days = (po.ack_received_at.date() - po.order_date).days
        if days < 0:
            continue
        key = po.vendor_number or po.vendor_name or "unknown"
        slot = ack_buckets.setdefault(key, {"supplier": po.vendor_name or key, "acks": 0, "total_days": 0})
        slot["acks"] += 1
        slot["total_days"] += days
    acks = [
        {"supplier": slot["supplier"], "acks": slot["acks"], "avg_days": round(slot["total_days"] / slot["acks"], 1)}
        for slot in ack_buckets.values()
    ]

    late = []
    for order in db.query(OpsTrackedOrder).filter(OpsTrackedOrder.bc_open.is_(True)).all():
        if not order.expected_receipt or order.expected_receipt >= as_of:
            continue
        if order.shipping_status == "Shipped" or order.order_status == "Received":
            continue
        late.append({
            "so_number": order.so_number,
            "customer": order.customer_name,
            "expected_receipt": order.expected_receipt.isoformat(),
            "days_late": (as_of - order.expected_receipt).days,
            "order_status": order.order_status,
        })
    late.sort(key=lambda row: row["days_late"], reverse=True)

    def _in_week(value: Optional[datetime]) -> bool:
        return bool(value) and week_start <= value.date() <= week_end

    messages = db.query(OpsOutboundMessage).all()
    customer_rows = [row for row in messages if row.kind == "customer_update"]
    reminder_rows = [row for row in messages if row.kind == "supplier_reminder"]
    open_actions = {}
    for row in db.query(OpsActionItem).filter(OpsActionItem.status == "open").all():
        open_actions[row.kind] = open_actions.get(row.kind, 0) + 1
    return {
        "as_of": as_of.isoformat(),
        "week_start": week_start.isoformat(),
        "week_ending": week_end.isoformat(),
        "lead_time_days_by_supplier": lead,
        "ack_turnaround_days_by_supplier": acks,
        "late_orders": late,
        "customer_updates": {
            "drafted": sum(1 for row in customer_rows if _in_week(row.created_at)),
            "sent": sum(1 for row in customer_rows if _in_week(row.sent_at)),
            "rejected": sum(1 for row in customer_rows if _in_week(row.rejected_at)),
            "pending_now": sum(1 for row in customer_rows if row.status == "pending"),
        },
        "supplier_reminders": {
            "drafted": sum(1 for row in reminder_rows if _in_week(row.created_at)),
            "sent": sum(1 for row in reminder_rows if _in_week(row.sent_at)),
            "pending_now": sum(1 for row in reminder_rows if row.status == "pending"),
        },
        "open_actions": open_actions,
        "definitions": {
            "lead_time_days": "Purchase order date to expected receipt, or to the receipt posting date when goods have arrived. Grouped by the line's sourcing supplier.",
            "ack_turnaround_days": f"Purchase order date to the acknowledgement time, last {ACK_TURNAROUND_DAYS} days.",
            "late_orders": "Open orders whose expected receipt is before as_of and that are not shipped or received.",
            "customer_updates": "Drafted, sent, and rejected counts for the Monday–Sunday week that contains as_of. pending_now is the queue waiting for an approval click.",
            "nothing_sends_automatically": "Supplier reminders and customer updates stay pending until POST /api/ops/messages/{id}/approve.",
        },
    }


def default_sender(message: dict) -> None:
    from app.integrations.email.client import graph_client

    if getattr(graph_client, "app", None) is None:
        raise RuntimeError("Graph mail is not configured, so this email was not sent.")
    graph_client.send_mail(
        from_email=tracker_mailbox(),
        to=message["to_email"],
        subject=message["subject"],
        html_body=text_to_html(message["body_text"]),
    )
