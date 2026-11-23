"""Store supplier confirmations and, when enabled, write the expected
receipt date onto the matching purchase order.

Business Central writes are limited to ``expectedReceiptDate`` on
outstanding purchase-order lines. The supplier's own order number is
stored here and is not written to Business Central by this module.
Nothing in this module sends email. A date that pushes a sales order
past the customer's requested date becomes a customer-update draft on
the existing approval queue.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Dict, List, Optional, Sequence

from sqlalchemy import inspect
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import (
    OpsActionItem,
    OpsOutboundMessage,
    SupplierConfirmation,
    SupplierConfirmationSource,
    SupplierDateChange,
)
from app.integrations.bc.client import bc_client
from app.integrations.email.client import graph_client
from app.services.alberta_business_days import add_business_days, business_days_between
from app.services.late_orders import (
    commitment_date,
    is_open_unshipped,
    normalize_so,
    parse_date,
    placeholder_dates,
    po_expected_dates,
    po_outstanding_qty,
    po_was_sent,
)
from app.services.supplier_confirmation_parser import (
    ParsedSupplierConfirmation,
    is_supplier_confirmation_email,
    message_body,
    parse_supplier_message,
)
from app.services.vendor_ack_intake_service import configured_mailboxes, pdf_bytes_to_text
from app.services.vendor_ack_parser import po_base

logger = logging.getLogger(__name__)

CONFIRM_WAIT_BUSINESS_DAYS = 3
OREGAN_DEDUPE = "customer:SO-001295:2026-12-04:supplier-seed"
OREGAN_EXPECTED = date(2026, 12, 4)
_BODY_ATTACHMENT = "(body)"


def bc_write_enabled(explicit: Optional[bool] = None) -> bool:
    if explicit is not None:
        return bool(explicit)
    return bool(settings.SUPPLIER_CONFIRM_BC_WRITE)


def _tables(db: Session) -> set:
    """Tables visible on this session's connection.

    Inspecting the engine instead checks out a second connection. On SQLite
    that second checkout can end the session transaction and drop an
    uncommitted insert.
    """
    try:
        return set(inspect(db.connection()).get_table_names())
    except Exception:
        return set()


def _dedupe(vendor: str, supplier_no: Optional[str], po_number: Optional[str]) -> str:
    return "|".join([
        (vendor or "supplier").lower(),
        (supplier_no or "").upper(),
        po_base(po_number) or (po_number or "").upper(),
    ])


def _previous_date(db: Session, po_number: str, po: Optional[dict], placeholders: set) -> Optional[date]:
    if po is not None:
        real = [day for day in po_expected_dates(po) if day not in placeholders]
        if real:
            return max(real)
    last = (
        db.query(SupplierDateChange)
        .filter(SupplierDateChange.po_number == po_number)
        .filter(SupplierDateChange.bc_status.in_(["written", "held", "unchanged"]))
        .order_by(SupplierDateChange.id.desc())
        .first()
    )
    return last.new_date if last else None


def _log_change(
    db: Session,
    *,
    po_number: str,
    supplier_order_no: Optional[str],
    previous: Optional[date],
    new_date: Optional[date],
    bc_status: str,
    bc_error: Optional[str] = None,
    detail: Optional[str] = None,
) -> SupplierDateChange:
    row = SupplierDateChange(
        po_number=po_number,
        supplier_order_no=supplier_order_no,
        previous_date=previous,
        new_date=new_date,
        bc_status=bc_status,
        bc_error=(bc_error or None),
        detail=detail,
        created_at=datetime.utcnow(),
    )
    db.add(row)
    logger.info(
        "[SupplierConfirm] %s %s -> %s (%s)%s",
        po_number,
        previous.isoformat() if previous else "none",
        new_date.isoformat() if new_date else "none",
        bc_status,
        f" {bc_error}" if bc_error else "",
    )
    return row


def _write_expected_date(po_number: str, new_date: date) -> dict:
    """PATCH expectedReceiptDate on outstanding item lines. No other field."""
    po = bc_client.get_purchase_order_by_number(po_number)
    if not po:
        raise LookupError(f"BC has no purchase order {po_number}")
    updated = []
    unchanged = 0
    for line in po.get("purchaseOrderLines") or []:
        if (line.get("lineType") or "") != "Item":
            continue
        try:
            qty = float(line.get("quantity") or 0)
            received = float(line.get("receivedQuantity") or 0)
        except (TypeError, ValueError):
            continue
        if qty - received <= 0:
            continue
        current = parse_date(line.get("expectedReceiptDate"))
        if current == new_date:
            unchanged += 1
            continue
        line_id = line.get("id")
        if not line_id:
            continue
        bc_client.update_purchase_order_line(
            po["id"], line_id, {"expectedReceiptDate": new_date.isoformat()},
        )
        updated.append(line_id)
    return {
        "bc_po_id": po.get("id"),
        "updated": updated,
        "unchanged": unchanged,
    }


def _upsert_confirmation(
    db: Session,
    parsed: ParsedSupplierConfirmation,
    po_number: Optional[str],
    *,
    source_email_id: str,
    sender_email: str,
    subject: str,
) -> SupplierConfirmation:
    key = _dedupe(parsed.vendor_key, parsed.supplier_order_no, po_number)
    row = db.query(SupplierConfirmation).filter_by(dedupe_key=key).one_or_none()
    now = datetime.utcnow()
    if row is None:
        row = SupplierConfirmation(
            dedupe_key=key,
            vendor_key=parsed.vendor_key,
            created_at=now,
        )
        db.add(row)
    row.supplier_order_no = parsed.supplier_order_no or row.supplier_order_no
    row.our_po_number = po_base(po_number) if po_number else row.our_po_number
    row.our_so_numbers = parsed.our_so_numbers or row.our_so_numbers
    if parsed.expected_date:
        row.expected_receipt_date = parsed.expected_date
    row.source = parsed.source
    row.source_email_id = source_email_id or row.source_email_id
    row.sender_email = sender_email or row.sender_email
    row.subject = (subject or "")[:300] or row.subject
    row.status = "stored" if row.our_po_number else "pending"
    row.updated_at = now
    db.flush()
    return row


def _match_po_by_supplier(db: Session, supplier_no: Optional[str]) -> Optional[str]:
    if not supplier_no:
        return None
    row = (
        db.query(SupplierConfirmation)
        .filter(SupplierConfirmation.supplier_order_no == supplier_no)
        .filter(SupplierConfirmation.our_po_number.isnot(None))
        .order_by(SupplierConfirmation.id.desc())
        .first()
    )
    if row:
        return row.our_po_number
    try:
        from app.db.models import VendorOrderAck
        ack = (
            db.query(VendorOrderAck)
            .filter(VendorOrderAck.vendor_order_no == supplier_no)
            .filter(VendorOrderAck.our_po_number.isnot(None))
            .order_by(VendorOrderAck.id.desc())
            .first()
        )
    except Exception:
        return None
    if ack is None:
        return None
    return po_base(ack.our_po_number)


def _po_index(purchase_orders: Sequence[dict]) -> Dict[str, dict]:
    indexed = {}
    for po in purchase_orders or []:
        number = po_base(po.get("number") or "")
        if number:
            indexed[number] = po
    return indexed


def _queue_customer_draft(
    db: Session,
    *,
    so_number: str,
    customer_name: str,
    to_email: Optional[str],
    requested: date,
    supplier_date: date,
    arrival: date,
    po_numbers: Sequence[str],
) -> Optional[int]:
    if "ops_outbound_messages" not in _tables(db):
        return None
    told = arrival
    dedupe = f"customer:{so_number}:{told.isoformat()}:supplier:{','.join(po_numbers)}"
    existing = (
        db.query(OpsOutboundMessage)
        .filter(OpsOutboundMessage.dedupe_key == dedupe)
        .one_or_none()
    )
    if existing is not None:
        return existing.id
    handled = (
        db.query(OpsOutboundMessage)
        .filter(OpsOutboundMessage.so_number == so_number)
        .filter(OpsOutboundMessage.kind == "customer_update")
        .filter(OpsOutboundMessage.status.in_(["sent", "rejected"]))
        .all()
    )
    for row in handled:
        if (row.context_json or {}).get("new_date") == told.isoformat():
            return None
    who = customer_name or "there"
    po_text = " and ".join(po_numbers) if po_numbers else "the supplier order"
    body = (
        f"Hello {who},\n\n"
        f"Update on sales order {so_number}. We now expect {told.isoformat()}. "
        f"{po_text} is confirmed for {supplier_date.isoformat()}, which is past "
        f"the {requested.isoformat()} date you asked for. Sorry for the change.\n\n"
        f"Joey\nOpen Distribution\n"
    )
    now = datetime.utcnow()
    message = OpsOutboundMessage(
        kind="customer_update",
        status="pending",
        dedupe_key=dedupe,
        to_email=to_email or None,
        subject=f"Update on {so_number}",
        body_text=body,
        so_number=so_number,
        po_number=po_numbers[0] if po_numbers else None,
        context_json={
            "trigger": "supplier_date",
            "old_date": requested.isoformat(),
            "new_date": told.isoformat(),
            "supplier_date": supplier_date.isoformat(),
            "customer_name": customer_name,
            "po_numbers": list(po_numbers),
            "reason": (
                f"Supplier date {supplier_date.isoformat()} on {po_text} "
                f"lands {told.isoformat()}, after requested {requested.isoformat()}"
            ),
            "auto_send": False,
        },
        created_at=now,
        updated_at=now,
    )
    db.add(message)
    db.flush()
    if "ops_action_items" in _tables(db):
        key = f"customer_update:{dedupe}"
        action = db.query(OpsActionItem).filter_by(auto_key=key).one_or_none()
        if action is None:
            action = OpsActionItem(
                auto_key=key,
                auto_managed=True,
                status="open",
                created_at=now,
            )
            db.add(action)
        action.kind = "customer_update"
        action.title = f"Customer update needed: {so_number} now expected {told.isoformat()}"
        action.detail = message.context_json["reason"]
        action.so_number = so_number
        action.po_number = message.po_number
        action.status = "open"
    logger.info(
        "[SupplierConfirm] queued customer update draft for %s expected %s (not sent)",
        so_number, told.isoformat(),
    )
    return message.id


def ensure_oregan_seed(db: Session) -> Optional[int]:
    """O'Regan SO-001295, expected 4 Dec 2026, waiting for approval. Never sent."""
    if "ops_outbound_messages" not in _tables(db):
        return None
    existing = (
        db.query(OpsOutboundMessage)
        .filter(OpsOutboundMessage.dedupe_key == OREGAN_DEDUPE)
        .one_or_none()
    )
    if existing is not None:
        return existing.id
    now = datetime.utcnow()
    body = (
        "Hello O'Regan,\n\n"
        "Update on sales order SO-001295. We now expect 2026-12-04. "
        "PO-000959 and PO-001049 moved the date past the date you asked for. "
        "Sorry for the change.\n\n"
        "Joey\nOpen Distribution\n"
    )
    message = OpsOutboundMessage(
        kind="customer_update",
        status="pending",
        dedupe_key=OREGAN_DEDUPE,
        to_email=None,
        subject="Update on SO-001295",
        body_text=body,
        so_number="SO-001295",
        po_number="PO-000959",
        context_json={
            "trigger": "supplier_date",
            "new_date": OREGAN_EXPECTED.isoformat(),
            "customer_name": "O'Regan",
            "po_numbers": ["PO-000959", "PO-001049"],
            "reason": "Supplier date now 2026-12-04 on PO-000959 and PO-001049",
            "seed": True,
            "auto_send": False,
        },
        created_at=now,
        updated_at=now,
    )
    db.add(message)
    db.flush()
    if "ops_action_items" in _tables(db):
        key = f"customer_update:{OREGAN_DEDUPE}"
        if db.query(OpsActionItem).filter_by(auto_key=key).one_or_none() is None:
            db.add(OpsActionItem(
                auto_key=key,
                auto_managed=True,
                kind="customer_update",
                status="open",
                title="Customer update needed: SO-001295 now expected 2026-12-04",
                detail="O'Regan. PO-000959 and PO-001049. Waiting for approval. Not sent.",
                so_number="SO-001295",
                po_number="PO-000959",
                created_at=now,
            ))
    return message.id


def _maybe_customer_updates(
    db: Session,
    *,
    po_number: str,
    supplier_date: date,
    sales_orders: Sequence[dict],
    extra_sos: Sequence[str],
    lead_days: int,
    changed: bool,
) -> List[str]:
    if not changed:
        return []
    linked = []
    for order in sales_orders or []:
        if not is_open_unshipped(order):
            continue
        so_number = normalize_so(order.get("number") or "")
        if so_number not in extra_sos and so_number not in _sos_for_po_text(order, po_number):
            continue
        requested = commitment_date(order)
        if requested is None:
            continue
        arrival = add_business_days(supplier_date, lead_days) if lead_days else supplier_date
        if supplier_date > requested:
            told = supplier_date
        elif arrival > requested:
            told = arrival
        else:
            continue
        queued = _queue_customer_draft(
            db,
            so_number=so_number,
            customer_name=order.get("customerName") or order.get("customer_name") or "",
            to_email=order.get("email") or order.get("customerEmail"),
            requested=requested,
            supplier_date=supplier_date,
            arrival=told,
            po_numbers=[po_number],
        )
        if queued:
            linked.append(so_number)
    return linked


def _sos_for_po_text(order: dict, po_number: str) -> set:
    """Sales orders in the feed whose lines or external doc name this PO, plus the order number itself when the PO text names it."""
    blob = " ".join([
        order.get("externalDocumentNumber") or "",
        order.get("number") or "",
    ])
    for line in order.get("salesOrderLines") or []:
        blob += " " + (line.get("description") or "")
    if po_number and po_number in blob.upper():
        so = normalize_so(order.get("number") or "")
        return {so} if so else set()
    return set()


def apply_confirmations(
    db: Session,
    parsed_rows: Sequence[ParsedSupplierConfirmation],
    *,
    purchase_orders: Optional[Sequence[dict]] = None,
    sales_orders: Optional[Sequence[dict]] = None,
    write_bc: Optional[bool] = None,
    source_email_id: str = "",
    sender_email: str = "",
    subject: str = "",
    lead_days: Optional[int] = None,
) -> dict:
    """Store rows, log date decisions, and optionally PATCH Business Central.

    Customer drafts are queued and not sent. ``write_bc`` defaults to
    SUPPLIER_CONFIRM_BC_WRITE (off).
    """
    from app.services.late_orders import internal_lead_days, sales_orders_on_po

    do_write = bc_write_enabled(write_bc)
    lead = internal_lead_days(lead_days)
    placeholders = placeholder_dates(purchase_orders or [])
    indexed = _po_index(purchase_orders or [])
    summary = {
        "stored": 0,
        "pending": 0,
        "bc_written": 0,
        "bc_held": 0,
        "bc_failed": 0,
        "bc_unchanged": 0,
        "customer_drafts": 0,
        "write_bc": do_write,
    }
    so_by_po: Dict[str, List[str]] = {}
    for po in purchase_orders or []:
        number = po_base(po.get("number") or "")
        if number:
            so_by_po[number] = sales_orders_on_po(po)

    for parsed in parsed_rows:
        targets = [po_base(po) for po in (parsed.po_numbers or []) if po_base(po)]
        if not targets and parsed.supplier_order_no:
            matched = _match_po_by_supplier(db, parsed.supplier_order_no)
            if matched:
                targets = [matched]
        if not targets:
            _upsert_confirmation(
                db, parsed, None,
                source_email_id=source_email_id,
                sender_email=sender_email,
                subject=subject,
            )
            summary["pending"] += 1
            continue
        for po_number in targets:
            row = _upsert_confirmation(
                db, parsed, po_number,
                source_email_id=source_email_id,
                sender_email=sender_email,
                subject=subject,
            )
            summary["stored"] += 1
            if not parsed.expected_date:
                continue
            po = indexed.get(po_number)
            previous = _previous_date(db, po_number, po, placeholders)
            if previous == parsed.expected_date:
                _log_change(
                    db,
                    po_number=po_number,
                    supplier_order_no=parsed.supplier_order_no,
                    previous=previous,
                    new_date=parsed.expected_date,
                    bc_status="unchanged",
                    detail="Expected receipt date already matches the confirmation",
                )
                summary["bc_unchanged"] += 1
                continue
            if not do_write:
                _log_change(
                    db,
                    po_number=po_number,
                    supplier_order_no=parsed.supplier_order_no,
                    previous=previous,
                    new_date=parsed.expected_date,
                    bc_status="held",
                    detail="SUPPLIER_CONFIRM_BC_WRITE is off. Date stored, Business Central not patched.",
                )
                summary["bc_held"] += 1
                changed = True
            else:
                try:
                    result = _write_expected_date(po_number, parsed.expected_date)
                except Exception as exc:
                    _log_change(
                        db,
                        po_number=po_number,
                        supplier_order_no=parsed.supplier_order_no,
                        previous=previous,
                        new_date=parsed.expected_date,
                        bc_status="failed",
                        bc_error=str(exc)[:2000],
                    )
                    summary["bc_failed"] += 1
                    row.status = "failed"
                    continue
                if result["updated"]:
                    status = "written"
                    summary["bc_written"] += 1
                elif result["unchanged"]:
                    status = "unchanged"
                    summary["bc_unchanged"] += 1
                else:
                    status = "skipped"
                _log_change(
                    db,
                    po_number=po_number,
                    supplier_order_no=parsed.supplier_order_no,
                    previous=previous,
                    new_date=parsed.expected_date,
                    bc_status=status,
                    detail=(
                        f"Patched expectedReceiptDate on {len(result['updated'])} line(s)"
                        if result["updated"] else "No outstanding line needed a new date"
                    ),
                )
                changed = status == "written"
            sos = list(parsed.our_so_numbers or [])
            for so in so_by_po.get(po_number, []):
                if so not in sos:
                    sos.append(so)
            drafted = _maybe_customer_updates(
                db,
                po_number=po_number,
                supplier_date=parsed.expected_date,
                sales_orders=sales_orders or [],
                extra_sos=sos,
                lead_days=lead,
                changed=changed,
            )
            summary["customer_drafts"] += len(drafted)
    db.flush()
    return summary


def record_source(
    db: Session,
    *,
    source_email_id: str,
    filename: str,
    mailbox: str,
    outcome: str,
    detail: str = "",
) -> bool:
    """Return False when this email attachment was already processed."""
    filename = filename or _BODY_ATTACHMENT
    existing = (
        db.query(SupplierConfirmationSource)
        .filter_by(source_email_id=source_email_id, attachment_filename=filename)
        .one_or_none()
    )
    if existing is not None:
        return False
    db.add(SupplierConfirmationSource(
        source_email_id=source_email_id,
        attachment_filename=filename[:255],
        mailbox=mailbox,
        outcome=outcome,
        detail=(detail or "")[:2000] or None,
        created_at=datetime.utcnow(),
    ))
    db.flush()
    return True


def confirmation_links(db: Session) -> tuple:
    """(extra PO→SO links, confirmed PO→date) from stored rows."""
    if "supplier_confirmations" not in _tables(db):
        return {}, {}
    links: Dict[str, List[str]] = {}
    dates: Dict[str, date] = {}
    rows = (
        db.query(SupplierConfirmation)
        .filter(SupplierConfirmation.our_po_number.isnot(None))
        .all()
    )
    for row in rows:
        po = po_base(row.our_po_number)
        if not po:
            continue
        for so in row.our_so_numbers or []:
            normalized = normalize_so(so)
            if normalized and normalized not in links.setdefault(po, []):
                links[po].append(normalized)
        if row.expected_receipt_date:
            current = dates.get(po)
            if current is None or row.expected_receipt_date > current:
                dates[po] = row.expected_receipt_date
    return links, dates


def po_flags(
    purchase_orders: Sequence[dict],
    *,
    today: Optional[date] = None,
    confirmed_po_numbers: Optional[Sequence[str]] = None,
    confirmed_dates: Optional[Dict[str, date]] = None,
) -> List[dict]:
    """Open POs sent 3 Alberta business days ago with no confirmation or no real date."""
    today = today or date.today()
    confirmed = {po_base(n) for n in (confirmed_po_numbers or []) if po_base(n)}
    placeholders = placeholder_dates(purchase_orders or [])
    flags = []
    for po in purchase_orders or []:
        if not po_was_sent(po) or po_outstanding_qty(po) <= 0:
            continue
        number = po_base(po.get("number") or "") or (po.get("number") or "")
        sent = parse_date(po.get("orderDate") or po.get("order_date") or po.get("postingDate"))
        if sent is None or business_days_between(sent, today) < CONFIRM_WAIT_BUSINESS_DAYS:
            continue
        has_confirmation = number in confirmed
        real_dates = [day for day in po_expected_dates(po) if day not in placeholders]
        confirmed_date = (confirmed_dates or {}).get(number)
        if confirmed_date and confirmed_date not in placeholders:
            real_dates.append(confirmed_date)
        reasons = []
        if not has_confirmation:
            reasons.append("no supplier confirmation")
        if not real_dates:
            shared = [day for day in po_expected_dates(po) if day in placeholders]
            if shared:
                reasons.append(
                    f"expected date {shared[0].isoformat()} is a shared placeholder, counted as no date"
                )
            else:
                reasons.append("no real expected receipt date")
        if not reasons:
            continue
        flags.append({
            "po_number": number,
            "vendor": po.get("vendorName") or po.get("vendor_name") or "",
            "sent_on": sent.isoformat(),
            "business_days": business_days_between(sent, today),
            "reason": "; ".join(reasons),
        })
    flags.sort(key=lambda row: (row["sent_on"], row["po_number"]))
    return flags


def flags_for_purchase_orders(db: Optional[Session], purchase_orders: Sequence[dict], today: Optional[date] = None) -> List[dict]:
    confirmed: List[str] = []
    dates: Dict[str, date] = {}
    if db is not None and "supplier_confirmations" in _tables(db):
        for row in db.query(SupplierConfirmation).filter(SupplierConfirmation.our_po_number.isnot(None)).all():
            if row.supplier_order_no or row.expected_receipt_date:
                confirmed.append(row.our_po_number)
            if row.expected_receipt_date:
                dates[po_base(row.our_po_number) or row.our_po_number] = row.expected_receipt_date
    return po_flags(
        purchase_orders,
        today=today,
        confirmed_po_numbers=confirmed,
        confirmed_dates=dates,
    )


def email_flags_section(flags: Sequence[dict]) -> str:
    import html as html_lib

    if not flags:
        return "<p>No open purchase order is past 3 business days without a confirmation or a real expected date.</p>"
    body = [
        f"<p><b>{len(flags)}</b> open purchase order(s) were sent at least "
        f"{CONFIRM_WAIT_BUSINESS_DAYS} business days ago and have no supplier "
        "confirmation or no real expected receipt date.</p>",
        "<table cellpadding='6' cellspacing='0' border='1' style='border-collapse:collapse;font-size:14px'>",
        "<tr><th align='left'>PO</th><th align='left'>Vendor</th><th align='left'>Sent</th><th align='left'>Why</th></tr>",
    ]
    for row in flags:
        body.append(
            "<tr>"
            f"<td>{html_lib.escape(row['po_number'])}</td>"
            f"<td>{html_lib.escape(row.get('vendor') or '')}</td>"
            f"<td>{html_lib.escape(row.get('sent_on') or '')}</td>"
            f"<td>{html_lib.escape(row.get('reason') or '')}</td>"
            "</tr>"
        )
    body.append("</table>")
    return "\n".join(body)


def _attachment_bytes(att: dict) -> bytes:
    import base64
    raw = att.get("contentBytes") or ""
    if not raw:
        return b""
    try:
        return base64.b64decode(raw)
    except Exception:
        return b""


def ingest_messages(
    db: Session,
    messages: Sequence[dict],
    *,
    purchase_orders: Optional[Sequence[dict]] = None,
    sales_orders: Optional[Sequence[dict]] = None,
    write_bc: Optional[bool] = None,
    mailbox: str = "",
    lead_days: Optional[int] = None,
) -> dict:
    """Parse already-fetched messages. Attachments may include ``contentBytes``."""
    summary = {
        "seen": 0,
        "parsed": 0,
        "skipped": 0,
        "stored": 0,
        "pending": 0,
        "bc_written": 0,
        "bc_held": 0,
        "bc_failed": 0,
        "customer_drafts": 0,
        "write_bc": bc_write_enabled(write_bc),
    }
    for email in messages or []:
        message_id = email.get("id") or ""
        subject = email.get("subject") or ""
        sender = ((email.get("from") or {}).get("emailAddress") or {}).get("address") or email.get("sender") or ""
        body = message_body(email)
        attachments = email.get("attachments") or []
        interesting_files = []
        for att in attachments:
            filename = att.get("name") or ""
            if is_supplier_confirmation_email(subject, body, sender, filename):
                interesting_files.append(att)
        if not interesting_files and not is_supplier_confirmation_email(subject, body, sender):
            continue
        summary["seen"] += 1
        pieces = [
            att for att in interesting_files
            if (att.get("name") or "").lower().endswith((".pdf", ".xlsx", ".xlsm", ".csv"))
        ]
        if not pieces:
            pieces = [{"name": _BODY_ATTACHMENT, "contentBytes": ""}]
        for att in pieces:
            filename = att.get("name") or _BODY_ATTACHMENT
            if not record_source(
                db,
                source_email_id=message_id or f"inline:{subject[:80]}",
                filename=filename,
                mailbox=mailbox,
                outcome="parsed",
            ):
                summary["skipped"] += 1
                continue
            raw = _attachment_bytes(att)
            pdf_text = ""
            if filename.lower().endswith(".pdf") and raw:
                pdf_text = pdf_bytes_to_text(raw)
            try:
                parsed = parse_supplier_message(
                    subject=subject,
                    body=body,
                    sender=sender,
                    filename=filename,
                    pdf_text=pdf_text,
                    attachment_bytes=raw or None,
                )
            except ValueError as exc:
                summary["skipped"] += 1
                logger.warning("[SupplierConfirm] parse skipped for %s: %s", filename, exc)
                continue
            if not parsed:
                summary["skipped"] += 1
                continue
            summary["parsed"] += len(parsed)
            applied = apply_confirmations(
                db,
                parsed,
                purchase_orders=purchase_orders,
                sales_orders=sales_orders,
                write_bc=write_bc,
                source_email_id=message_id,
                sender_email=sender,
                subject=subject,
                lead_days=lead_days,
            )
            for key in ("stored", "pending", "bc_written", "bc_held", "bc_failed", "customer_drafts"):
                summary[key] += applied.get(key, 0)
    db.commit()
    return summary


def process_inbox(db: Session, *, write_bc: Optional[bool] = None) -> dict:
    """Poll the vendor-ack mailboxes and open purchase orders. Does not send mail."""
    try:
        purchase_orders = bc_client.get_open_purchase_orders_with_lines()
    except Exception as exc:
        logger.error("[SupplierConfirm] open purchase orders failed: %s", exc)
        purchase_orders = []
    try:
        sales_orders = bc_client.get_open_sales_orders_with_lines()
    except Exception as exc:
        logger.error("[SupplierConfirm] open sales orders failed: %s", exc)
        sales_orders = []
    lookback = int(getattr(settings, "SUPPLIER_CONFIRM_LOOKBACK_HOURS", 72) or 72)
    since = datetime.utcnow().replace(microsecond=0)
    from datetime import timedelta
    since = since - timedelta(hours=lookback)
    filt = f"receivedDateTime ge {since.strftime('%Y-%m-%dT%H:%M:%SZ')}"
    totals = {
        "mailboxes": [],
        "stored": 0,
        "parsed": 0,
        "bc_written": 0,
        "bc_held": 0,
        "customer_drafts": 0,
        "write_bc": bc_write_enabled(write_bc),
    }
    for mailbox in configured_mailboxes():
        try:
            messages = graph_client.get_inbox_emails(mailbox, max_count=50, filter_query=filt)
        except Exception as exc:
            logger.error("[SupplierConfirm] inbox %s failed: %s", mailbox, exc)
            continue
        hydrated = []
        for message in messages or []:
            message_id = message.get("id")
            subject = message.get("subject") or ""
            body = message_body(message)
            sender = ((message.get("from") or {}).get("emailAddress") or {}).get("address") or ""
            if not is_supplier_confirmation_email(subject, body, sender):
                continue
            try:
                atts = graph_client.get_message_attachments(mailbox, message_id) if message_id else []
            except Exception as exc:
                logger.warning("[SupplierConfirm] attachments failed: %s", exc)
                atts = []
            message = dict(message)
            message["attachments"] = atts or []
            hydrated.append(message)
        result = ingest_messages(
            db,
            hydrated,
            purchase_orders=purchase_orders,
            sales_orders=sales_orders,
            write_bc=write_bc,
            mailbox=mailbox,
        )
        totals["mailboxes"].append(mailbox)
        for key in ("stored", "parsed", "bc_written", "bc_held", "customer_drafts"):
            totals[key] += result.get(key, 0)
    return totals


def list_changes(db: Session, limit: int = 100) -> List[dict]:
    rows = (
        db.query(SupplierDateChange)
        .order_by(SupplierDateChange.id.desc())
        .limit(limit)
        .all()
    )
    return [_change_dict(row) for row in rows]


def _change_dict(row: SupplierDateChange) -> dict:
    return {
        "id": row.id,
        "po_number": row.po_number,
        "supplier_order_no": row.supplier_order_no,
        "previous_date": row.previous_date.isoformat() if row.previous_date else None,
        "new_date": row.new_date.isoformat() if row.new_date else None,
        "bc_status": row.bc_status,
        "bc_error": row.bc_error,
        "detail": row.detail,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def list_confirmations(db: Session, limit: int = 200) -> List[dict]:
    rows = (
        db.query(SupplierConfirmation)
        .order_by(SupplierConfirmation.id.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "id": row.id,
            "vendor_key": row.vendor_key,
            "supplier_order_no": row.supplier_order_no,
            "our_po_number": row.our_po_number,
            "our_so_numbers": row.our_so_numbers or [],
            "expected_receipt_date": row.expected_receipt_date.isoformat() if row.expected_receipt_date else None,
            "source": row.source,
            "sender_email": row.sender_email,
            "subject": row.subject,
            "status": row.status,
        }
        for row in rows
    ]


def pending_customer_updates(db: Session) -> List[dict]:
    if "ops_outbound_messages" not in _tables(db):
        return []
    rows = (
        db.query(OpsOutboundMessage)
        .filter(OpsOutboundMessage.kind == "customer_update")
        .filter(OpsOutboundMessage.status == "pending")
        .order_by(OpsOutboundMessage.id.desc())
        .all()
    )
    out = []
    for row in rows:
        ctx = row.context_json or {}
        out.append({
            "id": row.id,
            "so_number": row.so_number,
            "customer_name": ctx.get("customer_name"),
            "po_number": row.po_number,
            "po_numbers": ctx.get("po_numbers") or [],
            "new_date": ctx.get("new_date"),
            "subject": row.subject,
            "body_text": row.body_text,
            "to_email": row.to_email,
            "status": row.status,
            "reason": ctx.get("reason"),
        })
    return out


def dispatch_summary(
    db: Session,
    *,
    sales_orders: Optional[Sequence[dict]] = None,
    purchase_orders: Optional[Sequence[dict]] = None,
    today: Optional[date] = None,
) -> dict:
    """Portal payload. Business Central failures come back as an error string."""
    bc_error = None
    if purchase_orders is None:
        try:
            purchase_orders = bc_client.get_open_purchase_orders_with_lines()
        except Exception as exc:
            purchase_orders = []
            bc_error = str(exc)[:500]
    if sales_orders is None:
        try:
            sales_orders = bc_client.get_open_sales_orders_with_lines()
        except Exception as exc:
            sales_orders = []
            bc_error = bc_error or str(exc)[:500]
    ensure_oregan_seed(db)
    db.commit()
    links, dates = confirmation_links(db)
    from app.services.late_orders import classify_late_sales_orders
    late = classify_late_sales_orders(
        sales_orders or [],
        purchase_orders or [],
        today=today,
        extra_links=links,
        confirmed_po_dates=dates,
    )
    return {
        "late": late,
        "flags": flags_for_purchase_orders(db, purchase_orders or [], today=today),
        "confirmations": list_confirmations(db),
        "date_changes": list_changes(db),
        "customer_updates": pending_customer_updates(db),
        "bc_error": bc_error,
        "flags_enabled": {
            "supplier_confirm_intake": bool(settings.SUPPLIER_CONFIRM_INTAKE_ENABLED),
            "supplier_confirm_bc_write": bool(settings.SUPPLIER_CONFIRM_BC_WRITE),
            "packing_slip_enabled": bool(settings.PACKING_SLIP_ENABLED),
            "packing_slip_auto_send": bool(settings.PACKING_SLIP_AUTO_SEND),
        },
    }
