"""Incoming lane and supplier shipping-mail matching.

Open purchase orders are read with GET only. A shipping email can update
the portal overlay (ETA, carrier, tracking, Shipped) and a supplier-order
map. Nothing here calls a Business Central POST, PATCH, or DELETE.

The build date for a row is the purchase order requested receipt date.
A saved shipping notice can replace that ETA. A row with no date stays off
the board.

PO to sales order, in this order:

1. A saved supplier-order map.
2. Our PO number on the email, found on an open purchase order.
3. The supplier order number equals the PO vendor order number.
4. Sales order numbers already written on the PO: external document,
   your reference, and line text such as ``Built from SO-``.
5. The order tracker line ``linked_po_number``. ``source_label`` only
   names the supplier. It does not choose a purchase order.

Customer names come from the open sales order with that number, or from
the tracker link. If neither has a name, the sales order number is shown
and the customer is left blank.

A shipping email with no PO number, no vendor-order match, and no saved
map is low confidence. It is queued for review and does not change a row.
"""
from __future__ import annotations

import logging
import re
from datetime import date, datetime
from typing import Optional

from sqlalchemy.orm import Session

from app.services.draft_po_review_service import _sales_orders_from_po
from app.services.shop_tv_board import (
    SHOP_TZ,
    _group,
    _read_setting,
    _write_setting,
    parse_when,
    shop_today,
)
from app.services.vendor_ack_parser import (
    ORDER_DIGITS_RE,
    PO_DASH_RE,
    PO_HASH_RE,
    PO_LABELED_RE,
    SORD_RE,
    TAG_SO_RE,
)

logger = logging.getLogger(__name__)

INCOMING_FLAG = "shop_tv_incoming"
EMAIL_FLAG = "incoming_email_matching"

_SHIP_HINT = re.compile(
    r"(?i)\b(?:shipped|on the truck|packing\s*slip|pack(?:ing)?\s*list|waybill|bill of lading|tracking)\b"
)
_SUPPLIER_HINT = re.compile(
    r"(?i)\b(?:upwardor|justin|elton|dek|global overhead(?:\s+doors)?|teams transport|teams)\b"
)
_CARRIER_RE = re.compile(r"(?i)\bcarrier\s*[:\-]\s*([A-Za-z][A-Za-z0-9 &]{1,40})")
_WAYBILL_RE = re.compile(
    r"(?i)\b(?:waybill|tracking(?:\s+number)?|pro)\s*(?:no\.?|number|#)?\s*[:\-]\s*([A-Z0-9][A-Z0-9\-]{3,})"
)
_ETA_RE = re.compile(
    r"(?i)\b(?:eta|estimated arrival|ship date|shipped)\s*[:\-]?\s*(\d{4}-\d{2}-\d{2})"
)
_LINE_RE = re.compile(
    r"(?i)\b([A-Z]{1,4}\d{2,}[A-Z0-9\-]*)\s+(.{0,48}?)\s+qty\s+(\d+(?:\.\d+)?)"
)
_YOUR_REF_KEYS = ("yourReference", "your_reference", "Your_Reference")
_BC_READ = "get_open_purchase_orders_with_lines"


def _flag_on(db: Optional[Session], key: str) -> bool:
    raw = _read_setting(db, key)
    if isinstance(raw, dict):
        raw = raw.get("mode") or raw.get("value") or ""
    return str(raw or "").strip().lower() == "on"


def incoming_enabled(db: Optional[Session]) -> bool:
    return _flag_on(db, INCOMING_FLAG)


def email_matching_enabled(db: Optional[Session]) -> bool:
    return _flag_on(db, EMAIL_FLAG)


def set_flag(db: Session, key: str, mode: str, user_id: Optional[int] = None) -> str:
    if key not in {INCOMING_FLAG, EMAIL_FLAG}:
        raise ValueError("Unknown incoming flag")
    cleaned = str(mode or "").strip().lower()
    if cleaned not in {"off", "on"}:
        raise ValueError("mode must be off or on")
    _write_setting(db, key, {"mode": cleaned}, f"Shop TV {key}. Off does no work.", user_id)
    return cleaned


def po_digits(value) -> str:
    match = re.search(r"(\d+)", str(value or ""))
    if not match:
        return ""
    try:
        return str(int(match.group(1)))
    except ValueError:
        return ""


def format_po(value) -> str:
    digits = po_digits(value)
    if not digits:
        return ""
    raw = str(value or "")
    if re.search(r"(?i)\bPO-\d+", raw):
        match = re.search(r"(?i)\b(PO-\d+)", raw)
        return match.group(1).upper() if match else f"PO-{digits.zfill(6)}"
    return f"PO-{digits.zfill(6)}"


def _supplier_key(text: str) -> str:
    blob = text or ""
    if re.search(r"(?i)upwardor|\bjustin\b", blob):
        return "upwardor"
    if re.search(r"(?i)\belton\b", blob):
        return "elton"
    if re.search(r"(?i)\bdek\b", blob):
        return "dek"
    if re.search(r"(?i)global overhead", blob):
        return "global"
    if re.search(r"(?i)teams", blob):
        return "teams"
    return ""


def is_shipping_message(subject: str = "", body: str = "", sender: str = "") -> bool:
    blob = "\n".join([subject or "", body or "", sender or ""])
    if not _SHIP_HINT.search(blob):
        return False
    if _SUPPLIER_HINT.search(blob):
        return True
    return bool(PO_DASH_RE.search(blob) or PO_HASH_RE.search(blob) or SORD_RE.search(blob))


def extract_shipping_notice(subject: str = "", body: str = "", sender: str = "") -> dict:
    """Pull the fields a packing slip or ship notice actually prints."""
    text = "\n".join(part for part in (subject, body, sender) if part)
    our_po = ""
    for pattern in (PO_DASH_RE, PO_HASH_RE, PO_LABELED_RE):
        match = pattern.search(text)
        if match:
            our_po = format_po(match.group(1))
            break
    sord = ""
    sord_match = SORD_RE.search(text) or ORDER_DIGITS_RE.search(text)
    if sord_match:
        sord = f"S-ORD{sord_match.group(1)}"
    sales_orders = []
    for match in TAG_SO_RE.finditer(text):
        number = f"SO-{match.group(1)}"
        if number not in sales_orders:
            sales_orders.append(number)
    carrier_match = _CARRIER_RE.search(text)
    waybill_match = _WAYBILL_RE.search(text)
    eta_match = _ETA_RE.search(text)
    lines = []
    for match in _LINE_RE.finditer(text):
        lines.append({
            "item": match.group(1),
            "description": " ".join(match.group(2).split()),
            "quantity": match.group(3),
        })
    return {
        "supplier_key": _supplier_key(text),
        "supplier_order_no": sord,
        "our_po_number": our_po,
        "sales_orders": sales_orders,
        "carrier": carrier_match.group(1).strip() if carrier_match else "",
        "tracking": waybill_match.group(1).strip() if waybill_match else "",
        "eta": eta_match.group(1) if eta_match else "",
        "lines": lines,
        "sender": sender or "",
        "subject": subject or "",
    }


def _find_po(purchase_orders, po_number: str):
    key = po_digits(po_number)
    if not key:
        return None
    for po in purchase_orders or []:
        if po_digits(po.get("number")) == key:
            return po
    return None


def linked_sales_orders(po: dict, tracker_links=None, sales_by_number=None) -> list:
    """SO numbers and customer names already tied to this purchase order."""
    lines = po.get("purchaseOrderLines") or po.get("lines") or []
    numbers = _sales_orders_from_po(po, lines)
    seen = {item.upper() for item in numbers}
    for key in _YOUR_REF_KEYS:
        for match in re.finditer(r"\bSO-\d+\b", str(po.get(key) or ""), re.IGNORECASE):
            so = match.group(0).upper()
            if so not in seen:
                seen.add(so)
                numbers.append(so)
    po_key = po_digits(po.get("number"))
    for link in tracker_links or []:
        if po_digits(link.get("po_number")) != po_key:
            continue
        so = str(link.get("so_number") or "").upper()
        if so and so not in seen:
            seen.add(so)
            numbers.append(so)
    found = []
    sales_by_number = sales_by_number or {}
    for so in numbers:
        sales = sales_by_number.get(so) or {}
        customer = str(sales.get("customerName") or sales.get("customer_name") or "").strip()
        if not customer:
            for link in tracker_links or []:
                if str(link.get("so_number") or "").upper() == so and link.get("customer_name"):
                    customer = str(link["customer_name"]).strip()
                    break
        found.append({"number": so, "customer": customer})
    return found


def decide_match(extracted: dict, purchase_orders, maps=None, tracker_links=None, sales_orders=None) -> dict:
    """High confidence applies. Low confidence is a review, not a guess."""
    sales_by_number = {}
    for order in sales_orders or []:
        number = str(order.get("number") or "").upper()
        if number:
            sales_by_number[number] = order
    maps = maps or []
    supplier_order = extracted.get("supplier_order_no") or ""
    supplier_key = extracted.get("supplier_key") or ""

    saved = None
    if supplier_order:
        for row in maps:
            if row.get("supplier_order_no") == supplier_order and (
                not supplier_key or row.get("supplier_key") in {supplier_key, ""}
            ):
                saved = row
                break
    po = None
    reason = ""
    if saved:
        po = _find_po(purchase_orders, saved.get("our_po_number"))
        reason = "saved supplier map"
    if po is None and extracted.get("our_po_number"):
        po = _find_po(purchase_orders, extracted["our_po_number"])
        if po is not None:
            reason = "PO number on the email"
    if po is None and supplier_order:
        for candidate in purchase_orders or []:
            vendor_order = str(candidate.get("vendorOrderNumber") or candidate.get("vendor_order_no") or "")
            if supplier_order and supplier_order.replace("-", "") in vendor_order.replace("-", "").replace(" ", ""):
                po = candidate
                reason = "supplier order number on the purchase order"
                break
    if po is None:
        return {
            "action": "review",
            "confidence": "low",
            "reason": "No purchase order number, saved map, or vendor order number matched.",
            "po_number": "",
            "sales_orders": [],
            "supplier_order_no": supplier_order,
            "carrier": extracted.get("carrier") or "",
            "tracking": extracted.get("tracking") or "",
            "eta": extracted.get("eta") or "",
        }
    linked = linked_sales_orders(po, tracker_links, sales_by_number)
    if saved and saved.get("sales_orders"):
        known = {item["number"] for item in linked}
        for item in saved["sales_orders"]:
            number = str(item.get("number") or "").upper()
            if number and number not in known:
                linked.append({"number": number, "customer": item.get("customer") or ""})
    for number in extracted.get("sales_orders") or []:
        upper = number.upper()
        if upper not in {item["number"] for item in linked}:
            sales = sales_by_number.get(upper) or {}
            linked.append({
                "number": upper,
                "customer": str(sales.get("customerName") or sales.get("customer_name") or "").strip(),
            })
    return {
        "action": "apply",
        "confidence": "high",
        "reason": reason,
        "po_number": po.get("number") or format_po(extracted.get("our_po_number")),
        "sales_orders": linked,
        "supplier_order_no": supplier_order,
        "supplier_key": supplier_key or _supplier_key(po.get("vendorName") or ""),
        "carrier": extracted.get("carrier") or "",
        "tracking": extracted.get("tracking") or "",
        "eta": extracted.get("eta") or "",
    }


def _open_po(po: dict) -> bool:
    status = str(po.get("status") or "").strip().lower()
    if status in {"draft", "cancelled", "canceled"}:
        return False
    lines = [ln for ln in (po.get("purchaseOrderLines") or []) if (ln.get("lineType") or "") == "Item"]
    if lines and all(float(ln.get("receivedQuantity") or 0) >= float(ln.get("quantity") or 0) > 0 for ln in lines):
        return False
    return True


def build_incoming_days(purchase_orders, sales_orders=None, notices=None, tracker_links=None, *, today: date, now=None, horizon_days: int = 7) -> dict:
    """Group open POs. No date means the row stays off. Email ETA wins when saved."""
    sales_by_number = {}
    for order in sales_orders or []:
        number = str(order.get("number") or "").upper()
        if number:
            sales_by_number[number] = order
    notice_by_po = {}
    for notice in notices or []:
        key = po_digits(notice.get("our_po_number"))
        if key:
            notice_by_po[key] = notice
    items = []
    omitted = 0
    for po in purchase_orders or []:
        if not isinstance(po, dict) or not _open_po(po):
            continue
        number = po.get("number") or ""
        notice = notice_by_po.get(po_digits(number)) or {}
        eta_raw = notice.get("eta") or po.get("requestedReceiptDate") or po.get("requested_receipt_date")
        parsed = parse_when(eta_raw)
        if parsed is None:
            omitted += 1
            continue
        day, clock = parsed
        window_end = today.toordinal() + horizon_days
        if day.toordinal() > window_end:
            continue
        linked = linked_sales_orders(po, tracker_links, sales_by_number)
        supplier_order = notice.get("supplier_order_no") or po.get("vendorOrderNumber") or ""
        carrier = notice.get("carrier") or ""
        tracking = notice.get("tracking") or ""
        status = notice.get("status") or "expected"
        bits = []
        if linked:
            bits.append(", ".join(
                f"{item['number']} {item['customer']}".strip() for item in linked
            ))
        if supplier_order:
            bits.append(str(supplier_order))
        if carrier or tracking:
            bits.append(" ".join(part for part in (carrier, tracking) if part))
        late = False
        if clock is not None and day == today and now is not None:
            current = now.astimezone(SHOP_TZ) if getattr(now, "tzinfo", None) else now
            late = clock < current.time().replace(microsecond=0, second=0)
        items.append({
            "id": f"incoming:{number}",
            "lane": "incoming",
            "order_number": number,
            "customer": po.get("vendorName") or po.get("vendor_name") or "",
            "detail": " · ".join(bits) or None,
            "destination": None,
            "date": day.isoformat(),
            "time": clock.strftime("%H:%M") if clock else None,
            "kind": "eta",
            "when_label": "Shipped" if str(status).lower() == "shipped" else "Expected",
            "overdue": day < today,
            "late": late,
            "sales_orders": linked,
            "supplier_order_no": supplier_order or None,
            "carrier": carrier or None,
            "tracking": tracking or None,
        })
    return {"days": _group(items, today, horizon_days), "omitted_no_date": omitted}


def load_purchase_orders(bc=None):
    """GET open purchase orders. This is the only Business Central call."""
    if bc is None:
        from app.integrations.bc.client import bc_client
        bc = bc_client
    reader = getattr(bc, _BC_READ)
    return reader() or []


def _notices(db: Session) -> list:
    from app.db.models import IncomingShipmentNotice
    rows = db.query(IncomingShipmentNotice).all()
    return [
        {
            "our_po_number": row.our_po_number,
            "supplier_order_no": row.supplier_order_no,
            "carrier": row.carrier,
            "tracking": row.tracking,
            "eta": row.eta.isoformat() if row.eta else None,
            "status": row.status,
        }
        for row in rows
    ]


def _maps(db: Session) -> list:
    from app.db.models import SupplierOrderMap
    rows = db.query(SupplierOrderMap).all()
    return [
        {
            "supplier_key": row.supplier_key,
            "supplier_order_no": row.supplier_order_no,
            "our_po_number": row.our_po_number,
            "sales_orders": row.sales_orders_json or [],
        }
        for row in rows
    ]


def _tracker_links(db: Optional[Session]) -> list:
    if db is None:
        return []
    nested = None
    try:
        from app.db.models import OpsTrackedLine, OpsTrackedOrder
        nested = db.begin_nested()
        rows = (
            db.query(OpsTrackedLine, OpsTrackedOrder)
            .join(OpsTrackedOrder, OpsTrackedLine.order_id == OpsTrackedOrder.id)
            .filter(OpsTrackedLine.linked_po_number.isnot(None))
            .all()
        )
        nested.commit()
    except Exception:
        logger.warning("Shop TV incoming could not read tracker links", exc_info=True)
        if nested is not None:
            try:
                nested.rollback()
            except Exception:
                pass
        return []
    found = []
    for line, order in rows:
        if not line.linked_po_number:
            continue
        found.append({
            "po_number": line.linked_po_number,
            "so_number": line.so_number,
            "source_label": line.source_label,
            "customer_name": order.customer_name,
        })
    return found


def attach_incoming(db: Optional[Session], board: dict, *, purchase_orders=None, now=None) -> dict:
    """Add the lane only when the flag is on. Off leaves the lane empty."""
    board = dict(board)
    lanes = dict(board.get("lanes") or {})
    if not incoming_enabled(db):
        board["incoming_enabled"] = False
        lanes["incoming"] = {"days": []}
        board["lanes"] = lanes
        return board
    current = now or datetime.now(SHOP_TZ)
    today = shop_today(current)
    if purchase_orders is None:
        try:
            purchase_orders = load_purchase_orders()
        except Exception:
            logger.warning("Shop TV could not read purchase orders", exc_info=True)
            purchase_orders = []
    try:
        notices = _notices(db) if db is not None else []
    except Exception:
        logger.warning("Shop TV incoming notices are unavailable", exc_info=True)
        notices = []
    tracker = _tracker_links(db)
    built = build_incoming_days(
        purchase_orders,
        sales_orders=None,
        notices=notices,
        tracker_links=tracker,
        today=today,
        now=current,
        horizon_days=int(board.get("horizon_days") or 7),
    )
    # Customer names from the sales orders already on the board when the PO names an SO.
    sales = []
    for lane in ("production", "pickups", "deliveries"):
        for day in (lanes.get(lane) or {}).get("days") or []:
            for item in day.get("items") or []:
                if item.get("order_number"):
                    sales.append({"number": item["order_number"], "customerName": item.get("customer")})
    if sales:
        built = build_incoming_days(
            purchase_orders,
            sales_orders=sales,
            notices=notices,
            tracker_links=tracker,
            today=today,
            now=current,
            horizon_days=int(board.get("horizon_days") or 7),
        )
    board["incoming_enabled"] = True
    lanes["incoming"] = {"days": built["days"]}
    board["lanes"] = lanes
    return board


def _save_apply(db: Session, decision: dict) -> None:
    from app.db.models import IncomingShipmentNotice, SupplierOrderMap
    po_number = decision["po_number"]
    eta = None
    parsed = parse_when(decision.get("eta"))
    if parsed:
        eta = parsed[0]
    row = db.query(IncomingShipmentNotice).filter(IncomingShipmentNotice.our_po_number == po_number).first()
    if row is None:
        row = IncomingShipmentNotice(our_po_number=po_number)
        db.add(row)
    if decision.get("supplier_order_no"):
        row.supplier_order_no = decision["supplier_order_no"]
    if decision.get("carrier"):
        row.carrier = decision["carrier"]
    if decision.get("tracking"):
        row.tracking = decision["tracking"]
    if eta is not None:
        row.eta = eta
    row.status = "shipped"
    row.confidence = "high"
    row.updated_at = datetime.utcnow()
    supplier_order = decision.get("supplier_order_no") or ""
    supplier_key = decision.get("supplier_key") or "supplier"
    if supplier_order:
        existing = (
            db.query(SupplierOrderMap)
            .filter(SupplierOrderMap.supplier_key == supplier_key)
            .filter(SupplierOrderMap.supplier_order_no == supplier_order)
            .first()
        )
        if existing is None:
            existing = SupplierOrderMap(
                supplier_key=supplier_key,
                supplier_order_no=supplier_order,
                our_po_number=po_number,
            )
            db.add(existing)
        existing.our_po_number = po_number
        existing.sales_orders_json = decision.get("sales_orders") or []
        existing.updated_at = datetime.utcnow()
    db.commit()


def _queue_review(db: Session, extracted: dict, decision: dict) -> int:
    from app.db.models import IncomingEmailReview
    row = IncomingEmailReview(
        status="pending",
        sender=extracted.get("sender"),
        subject=extracted.get("subject"),
        extracted_json=extracted,
        reason=decision.get("reason"),
        confidence="low",
        proposed_po=extracted.get("our_po_number") or None,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row.id


def route_notice(db: Optional[Session], extracted: dict, purchase_orders, sales_orders=None, tracker_links=None) -> dict:
    maps = _maps(db) if db is not None else []
    decision = decide_match(extracted, purchase_orders, maps, tracker_links, sales_orders)
    if decision["action"] == "apply" and db is not None:
        _save_apply(db, decision)
    elif decision["action"] == "review" and db is not None:
        decision["review_id"] = _queue_review(db, extracted, decision)
    return decision


def poll_shipping_mail(db: Session, *, graph=None, purchase_orders=None, sales_orders=None, mailboxes=None) -> dict:
    """Read shipping mail. Off returns nothing and does not call Graph or BC."""
    if not email_matching_enabled(db):
        return {"enabled": False, "processed": 0, "applied": [], "reviews": []}
    if purchase_orders is None:
        purchase_orders = load_purchase_orders()
    if graph is None:
        from app.integrations.email.client import graph_client
        graph = graph_client
    if mailboxes is None:
        from app.services.vendor_ack_intake_service import configured_mailboxes
        mailboxes = configured_mailboxes()
    applied = []
    reviews = []
    processed = 0
    tracker = _tracker_links(db)
    for mailbox in mailboxes:
        messages = graph.get_inbox_emails(mailbox, max_count=40) or []
        for message in messages:
            subject = message.get("subject") or ""
            body = ((message.get("body") or {}).get("content")) or message.get("bodyPreview") or ""
            sender = (((message.get("from") or {}).get("emailAddress") or {}).get("address")) or ""
            if not is_shipping_message(subject, body, sender):
                continue
            processed += 1
            extracted = extract_shipping_notice(subject, body, sender)
            decision = route_notice(db, extracted, purchase_orders, sales_orders, tracker)
            if decision["action"] == "apply":
                applied.append(decision["po_number"])
            else:
                reviews.append(decision.get("review_id"))
    return {"enabled": True, "processed": processed, "applied": applied, "reviews": reviews}


def list_reviews(db: Session) -> list:
    from app.db.models import IncomingEmailReview
    rows = (
        db.query(IncomingEmailReview)
        .filter(IncomingEmailReview.status == "pending")
        .order_by(IncomingEmailReview.id.desc())
        .all()
    )
    return [
        {
            "id": row.id,
            "subject": row.subject,
            "sender": row.sender,
            "reason": row.reason,
            "proposed_po": row.proposed_po,
            "extracted": row.extracted_json,
        }
        for row in rows
    ]


def accept_review(db: Session, review_id: int, po_number: Optional[str] = None, purchase_orders=None, sales_orders=None) -> dict:
    from app.db.models import IncomingEmailReview
    row = db.query(IncomingEmailReview).filter(IncomingEmailReview.id == review_id).first()
    if row is None:
        return {"ok": False}
    extracted = dict(row.extracted_json or {})
    chosen = po_number or row.proposed_po or extracted.get("our_po_number")
    if chosen:
        extracted["our_po_number"] = format_po(chosen) or chosen
    if purchase_orders is None:
        purchase_orders = []
    decision = decide_match(extracted, purchase_orders, _maps(db), _tracker_links(db), sales_orders)
    if decision["action"] != "apply":
        return {"ok": False, "reason": decision["reason"]}
    _save_apply(db, decision)
    row.status = "accepted"
    row.proposed_po = decision["po_number"]
    db.commit()
    return {"ok": True, "po_number": decision["po_number"]}
