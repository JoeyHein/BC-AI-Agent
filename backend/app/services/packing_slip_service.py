"""Packing slips for posted sales shipments.

A posted shipment gets a one-page PDF (sales order, customer PO, lines
shipped, backorders, Open Distribution's Redcliff address) so it can be
printed into the box. The PDF is also queued as an email to the customer
contact. Auto-send stays off until PACKING_SLIP_AUTO_SEND is turned on.
Approving one slip in the portal is the send.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import List, Optional, Sequence

from fpdf import FPDF
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import PackingSlip
from app.integrations.bc.client import bc_client
from app.integrations.email.client import graph_client
from app.services.late_orders import parse_date

logger = logging.getLogger(__name__)

COMPANY = "Open Distribution Company Inc."
ADDRESS_LINES = (
    "Bay 2, 125 Lockwood St NE",
    "Redcliff AB",
)


def auto_send_enabled(explicit: Optional[bool] = None) -> bool:
    if explicit is not None:
        return bool(explicit)
    return bool(settings.PACKING_SLIP_AUTO_SEND)


def _qty(value) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def shipment_lines(shipment: dict) -> List[dict]:
    rows = []
    for line in shipment.get("salesShipmentLines") or shipment.get("lines") or []:
        if (line.get("lineType") or "Item") not in ("Item", ""):
            continue
        item = (line.get("lineObjectNumber") or line.get("item_no") or "").strip()
        description = (line.get("description") or "").strip()
        qty = _qty(line.get("quantity"))
        if qty <= 0 or (not item and not description):
            continue
        rows.append({
            "item": item,
            "description": description,
            "quantity": qty,
        })
    return rows


def backorder_lines(order: Optional[dict]) -> List[dict]:
    if not order:
        return []
    rows = []
    for line in order.get("salesOrderLines") or []:
        if (line.get("lineType") or "Item") != "Item":
            continue
        item = (line.get("lineObjectNumber") or "").strip()
        if not item:
            continue
        try:
            qty = float(line.get("quantity") or 0)
            shipped = float(line.get("shippedQuantity") or 0)
            invoiced = float(line.get("invoicedQuantity") or 0)
        except (TypeError, ValueError):
            continue
        left = max(0.0, qty - max(shipped, invoiced))
        if left <= 0:
            continue
        rows.append({
            "item": item,
            "description": (line.get("description") or "").strip(),
            "quantity": round(left, 2),
        })
    return rows


def customer_po(shipment: dict, order: Optional[dict]) -> str:
    for source in (shipment, order or {}):
        value = (source.get("externalDocumentNumber") or source.get("customer_po") or "").strip()
        if value:
            return value
    return ""


def customer_email(shipment: dict, order: Optional[dict]) -> str:
    for source in (shipment, order or {}):
        value = (source.get("email") or source.get("customerEmail") or "").strip()
        if value and "@" in value:
            return value
    return ""


def _fmt_qty(value: float) -> str:
    if abs(value - round(value)) < 0.001:
        return str(int(round(value)))
    return f"{value:.2f}"


class _SlipPDF(FPDF):
    def footer(self):
        self.set_y(-18)
        self.set_font("Helvetica", size=8)
        self.set_text_color(90, 90, 90)
        self.cell(0, 5, f"{COMPANY}  |  {ADDRESS_LINES[0]}, {ADDRESS_LINES[1]}", align="C")


def build_packing_slip_pdf(slip: dict) -> bytes:
    """One printable page. ``slip`` carries the header and line lists."""
    pdf = _SlipPDF(format="Letter")
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.add_page()
    pdf.set_fill_color(20, 48, 84)
    pdf.rect(0, 0, 216, 28, "F")
    pdf.set_xy(12, 6)
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 8, COMPANY, ln=1)
    pdf.set_x(12)
    pdf.set_font("Helvetica", size=10)
    pdf.cell(0, 5, f"{ADDRESS_LINES[0]}, {ADDRESS_LINES[1]}", ln=1)
    pdf.ln(10)
    pdf.set_text_color(20, 48, 84)
    pdf.set_font("Helvetica", "B", 14)
    pdf.cell(0, 8, "PACKING SLIP", ln=1)
    pdf.set_text_color(0, 0, 0)
    pdf.set_font("Helvetica", size=11)
    pairs = [
        ("Shipment", slip.get("shipment_number") or ""),
        ("Sales order", slip.get("so_number") or ""),
        ("Customer", slip.get("customer_name") or ""),
        ("Customer PO", slip.get("customer_po") or ""),
        ("Ship date", slip.get("posting_date") or ""),
    ]
    for label, value in pairs:
        pdf.set_font("Helvetica", "B", 11)
        pdf.cell(40, 6, label)
        pdf.set_font("Helvetica", size=11)
        pdf.cell(0, 6, str(value), ln=1)
    pdf.ln(3)
    _table(pdf, "Shipped", slip.get("lines") or [], empty="No item lines on this shipment.")
    pdf.ln(4)
    _table(pdf, "Backorders", slip.get("backorders") or [], empty="No backorders.")
    raw = pdf.output()
    return bytes(raw)


def _table(pdf: FPDF, title: str, rows: Sequence[dict], empty: str) -> None:
    pdf.set_font("Helvetica", "B", 12)
    pdf.set_text_color(20, 48, 84)
    pdf.cell(0, 7, title, ln=1)
    pdf.set_text_color(0, 0, 0)
    if not rows:
        pdf.set_font("Helvetica", "I", 10)
        pdf.cell(0, 6, empty, ln=1)
        return
    pdf.set_font("Helvetica", "B", 9)
    pdf.set_fill_color(230, 236, 244)
    pdf.cell(40, 6, "Item", border=1, fill=True)
    pdf.cell(110, 6, "Description", border=1, fill=True)
    pdf.cell(30, 6, "Qty", border=1, fill=True, align="R", ln=1)
    pdf.set_font("Helvetica", size=9)
    for row in rows:
        description = (row.get("description") or "")[:70]
        pdf.cell(40, 6, (row.get("item") or "")[:22], border=1)
        pdf.cell(110, 6, description, border=1)
        pdf.cell(30, 6, _fmt_qty(row.get("quantity") or 0), border=1, align="R", ln=1)


def slip_payload(shipment: dict, order: Optional[dict]) -> dict:
    posted = parse_date(
        shipment.get("postingDate") or shipment.get("shipmentDate") or shipment.get("posting_date")
    )
    return {
        "shipment_id": shipment.get("id"),
        "shipment_number": shipment.get("number") or shipment.get("shipment_number") or "",
        "so_number": shipment.get("orderNumber") or (order or {}).get("number") or "",
        "customer_name": shipment.get("customerName") or (order or {}).get("customerName") or "",
        "customer_po": customer_po(shipment, order),
        "customer_email": customer_email(shipment, order),
        "posting_date": posted.isoformat() if posted else "",
        "lines": shipment_lines(shipment),
        "backorders": backorder_lines(order),
    }


def _send(slip: PackingSlip) -> None:
    if not slip.customer_email or "@" not in slip.customer_email:
        raise ValueError("Add a customer email before sending the packing slip.")
    subject = f"Packing slip {slip.shipment_number} for {slip.so_number or 'your order'}"
    html = (
        f"<p>Packing slip for sales order {slip.so_number or ''} "
        f"is attached. Customer PO: {slip.customer_po or '—'}.</p>"
        f"<p>{COMPANY}<br>{ADDRESS_LINES[0]}<br>{ADDRESS_LINES[1]}</p>"
    )
    graph_client.send_mail(
        settings.NOTIFICATION_SENDER_EMAIL,
        slip.customer_email,
        subject,
        html,
        attachments=[{
            "name": f"{slip.shipment_number}.pdf",
            "content_bytes": bytes(slip.pdf_bytes or b""),
            "content_type": "application/pdf",
        }],
    )


def queue_shipment(
    db: Session,
    shipment: dict,
    order: Optional[dict] = None,
    *,
    auto_send: Optional[bool] = None,
) -> PackingSlip:
    """Create the draft once per shipment number. Send only when auto-send is on."""
    payload = slip_payload(shipment, order)
    number = payload["shipment_number"]
    if not number:
        raise ValueError("Shipment has no number")
    existing = db.query(PackingSlip).filter_by(shipment_number=number).one_or_none()
    if existing is not None:
        return existing
    pdf = build_packing_slip_pdf(payload)
    posted = parse_date(payload["posting_date"]) if payload["posting_date"] else None
    row = PackingSlip(
        shipment_id=payload["shipment_id"],
        shipment_number=number,
        so_number=payload["so_number"] or None,
        customer_name=payload["customer_name"] or None,
        customer_po=payload["customer_po"] or None,
        customer_email=payload["customer_email"] or None,
        posting_date=posted,
        status="draft",
        pdf_bytes=pdf,
        line_count=len(payload["lines"]),
        backorder_count=len(payload["backorders"]),
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db.add(row)
    db.flush()
    if auto_send_enabled(auto_send):
        try:
            _send(row)
        except Exception as exc:
            row.send_error = str(exc)[:2000]
            row.updated_at = datetime.utcnow()
            logger.warning("[PackingSlip] auto-send failed for %s: %s", number, exc)
        else:
            row.status = "sent"
            row.sent_at = datetime.utcnow()
            row.updated_at = row.sent_at
            logger.info("[PackingSlip] auto-sent %s to %s", number, row.customer_email)
    else:
        logger.info("[PackingSlip] queued draft %s for %s (not sent)", number, row.so_number)
    return row


def approve_slip(db: Session, slip_id: int, to_email: Optional[str] = None) -> PackingSlip:
    row = db.query(PackingSlip).filter_by(id=slip_id).one_or_none()
    if row is None:
        raise LookupError("Packing slip not found")
    if row.status == "sent":
        return row
    if row.status == "rejected":
        raise ValueError("A rejected packing slip is not sent.")
    if to_email:
        row.customer_email = to_email.strip()
    _send(row)
    row.status = "sent"
    row.sent_at = datetime.utcnow()
    row.updated_at = row.sent_at
    row.send_error = None
    db.flush()
    return row


def reject_slip(db: Session, slip_id: int) -> PackingSlip:
    row = db.query(PackingSlip).filter_by(id=slip_id).one_or_none()
    if row is None:
        raise LookupError("Packing slip not found")
    if row.status == "sent":
        raise ValueError("A sent packing slip cannot be rejected.")
    row.status = "rejected"
    row.updated_at = datetime.utcnow()
    db.flush()
    return row


def update_recipient(db: Session, slip_id: int, to_email: str) -> PackingSlip:
    row = db.query(PackingSlip).filter_by(id=slip_id).one_or_none()
    if row is None:
        raise LookupError("Packing slip not found")
    row.customer_email = (to_email or "").strip() or None
    row.updated_at = datetime.utcnow()
    db.flush()
    return row


def list_slips(db: Session, limit: int = 100) -> List[dict]:
    rows = db.query(PackingSlip).order_by(PackingSlip.id.desc()).limit(limit).all()
    return [slip_dict(row) for row in rows]


def slip_dict(row: PackingSlip) -> dict:
    return {
        "id": row.id,
        "shipment_number": row.shipment_number,
        "so_number": row.so_number,
        "customer_name": row.customer_name,
        "customer_po": row.customer_po,
        "customer_email": row.customer_email,
        "posting_date": row.posting_date.isoformat() if row.posting_date else None,
        "status": row.status,
        "line_count": row.line_count,
        "backorder_count": row.backorder_count,
        "send_error": row.send_error,
        "sent_at": row.sent_at.isoformat() if row.sent_at else None,
    }


def process_shipments(
    db: Session,
    shipments: Sequence[dict],
    orders_by_number: Optional[dict] = None,
    *,
    auto_send: Optional[bool] = None,
) -> dict:
    orders_by_number = orders_by_number or {}
    created = 0
    existing = 0
    sent = 0
    for shipment in shipments or []:
        number = shipment.get("number") or ""
        before = db.query(PackingSlip).filter_by(shipment_number=number).one_or_none() if number else None
        so = shipment.get("orderNumber") or ""
        order = orders_by_number.get(so)
        row = queue_shipment(db, shipment, order, auto_send=auto_send)
        if before is None:
            created += 1
            if row.status == "sent":
                sent += 1
        else:
            existing += 1
    db.commit()
    return {"created": created, "existing": existing, "sent": sent, "auto_send": auto_send_enabled(auto_send)}


def process_recent(db: Session, *, auto_send: Optional[bool] = None, lookback_days: Optional[int] = None) -> dict:
    """Pull posted sales shipments and queue a draft for each new one."""
    days = lookback_days if lookback_days is not None else int(settings.PACKING_SLIP_LOOKBACK_DAYS or 14)
    since = (date.today() - timedelta(days=max(1, days))).isoformat()
    try:
        shipments = bc_client.get_sales_shipments(top=100)
    except Exception as exc:
        logger.error("[PackingSlip] shipment list failed: %s", exc)
        return {"created": 0, "error": str(exc)[:500], "auto_send": auto_send_enabled(auto_send)}
    recent = []
    for shipment in shipments or []:
        posted = parse_date(shipment.get("postingDate") or shipment.get("shipmentDate"))
        if posted and posted.isoformat() < since:
            continue
        number = shipment.get("number")
        if not number:
            continue
        if shipment.get("salesShipmentLines"):
            recent.append(shipment)
            continue
        try:
            full = bc_client.get_sales_shipment(shipment["id"]) if shipment.get("id") else shipment
        except Exception as exc:
            logger.warning("[PackingSlip] shipment %s detail failed: %s", number, exc)
            full = shipment
        recent.append(full)
    orders = {}
    for shipment in recent:
        so = shipment.get("orderNumber")
        if not so or so in orders:
            continue
        try:
            orders[so] = bc_client.get_sales_order_by_number(so)
        except Exception as exc:
            logger.warning("[PackingSlip] sales order %s failed: %s", so, exc)
            orders[so] = None
    return process_shipments(db, recent, orders, auto_send=auto_send)


