"""Which open sales orders are actually late.

The morning planning email used to call every material-short order "behind".
That counted orders that still have time. A sales order is late only when it
still has quantity to ship and either:

* the customer's requested or promised date is already past, or
* a linked supplier purchase order's expected receipt date, plus the internal
  lead (shop time after the supplier date), lands after the date the customer
  asked for.

Fully shipped lines (outstanding quantity 0) and orders already invoiced or
shipped are left out. A date shared by many open purchase orders, with no
supplier confirmation behind it, is a placeholder and is not a supplier date.
"""

from __future__ import annotations

import re
from collections import Counter
from datetime import date
from typing import Dict, List, Optional, Sequence

from app.services.alberta_business_days import add_business_days

# Charges typed as items. A leftover freight line is not an open order.
_NON_STOCK = {"FREIGHT", "INSTALLATION", "DISCOUNT", "SHIPPING", "MISC", "LABOUR", "LABOR"}

_SO_RE = re.compile(r"\bSO-(\d+)\b", re.IGNORECASE)
_CLOSED_STATUS = ("invoic", "shipped", "cancel", "closed", "complete")

# How many open POs must share one expected date before it is treated as a
# placeholder (the Nov 3 date stamped across the open book).
PLACEHOLDER_SHARE_COUNT = 3

# Shop time after the supplier's expected receipt before the order can go
# out to the customer. Overridable with PLANNING_INTERNAL_LEAD_DAYS.
DEFAULT_INTERNAL_LEAD_DAYS = 3


def internal_lead_days(explicit: Optional[int] = None) -> int:
    if explicit is not None:
        return max(0, int(explicit))
    try:
        from app.config import settings
        return max(0, int(settings.PLANNING_INTERNAL_LEAD_DAYS))
    except (TypeError, ValueError):
        return DEFAULT_INTERNAL_LEAD_DAYS


def parse_date(value) -> Optional[date]:
    """BC date or datetime string. Empty and 0001-01-01 are no date."""
    if value is None or value is False or value == "":
        return None
    if hasattr(value, "year") and hasattr(value, "month"):
        parsed = value.date() if hasattr(value, "hour") else value
        return None if parsed.year <= 1 else parsed
    text = str(value).strip()
    if not text or text[:10] <= "0001-01-01":
        return None
    try:
        parsed = date.fromisoformat(text[:10])
    except ValueError:
        return None
    return None if parsed.year <= 1 else parsed


def normalize_so(digits_or_token: str) -> str:
    match = _SO_RE.search(digits_or_token or "")
    digits = match.group(1) if match else re.sub(r"\D", "", digits_or_token or "")
    if not digits:
        return ""
    return f"SO-{int(digits):06d}"


def _line_outstanding(line: dict, received_field: str) -> float:
    if (line.get("lineType") or "Item") != "Item":
        return 0.0
    item = (line.get("lineObjectNumber") or "").strip().upper()
    if not item or item in _NON_STOCK:
        return 0.0
    try:
        qty = float(line.get("quantity") or 0)
        done = float(line.get(received_field) or 0)
        invoiced = float(line.get("invoicedQuantity") or 0) if received_field == "shippedQuantity" else 0.0
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, qty - max(done, invoiced))


def outstanding_qty(order: dict) -> float:
    """Quantity still to ship. Invoiced quantity counts as shipped."""
    total = 0.0
    for line in order.get("salesOrderLines") or []:
        total += _line_outstanding(line, "shippedQuantity")
    return round(total, 4)


def po_outstanding_qty(po: dict) -> float:
    total = 0.0
    for line in po.get("purchaseOrderLines") or []:
        total += _line_outstanding(line, "receivedQuantity")
    return round(total, 4)


def is_open_unshipped(order: dict) -> bool:
    """Still a sales order we can be late on: qty left, and not invoiced or shipped."""
    status = (order.get("status") or "").strip().lower()
    if any(token in status for token in _CLOSED_STATUS):
        return False
    return outstanding_qty(order) > 0


def customer_dates(order: dict) -> tuple:
    """(requested, promised). Either may be None."""
    requested = parse_date(order.get("requestedDeliveryDate") or order.get("requested_date"))
    promised = parse_date(order.get("promisedDeliveryDate") or order.get("promised_date"))
    return requested, promised


def commitment_date(order: dict) -> Optional[date]:
    """The date the customer is waiting on. Requested wins when both are set."""
    requested, promised = customer_dates(order)
    return requested or promised


def sales_orders_on_po(po: dict) -> List[str]:
    """SO numbers written on the PO header or any line description."""
    found: List[str] = []
    seen = set()

    def add(text: str) -> None:
        for match in _SO_RE.finditer(text or ""):
            so = f"SO-{int(match.group(1)):06d}"
            if so not in seen:
                seen.add(so)
                found.append(so)

    add(po.get("externalDocumentNumber") or "")
    add(po.get("number") or "")
    for line in po.get("purchaseOrderLines") or []:
        add(line.get("description") or "")
    return found


def po_expected_dates(po: dict) -> List[date]:
    """Expected receipt dates on outstanding item lines, else the header field."""
    dates: List[date] = []
    saw_outstanding = False
    for line in po.get("purchaseOrderLines") or []:
        if _line_outstanding(line, "receivedQuantity") <= 0:
            continue
        saw_outstanding = True
        parsed = parse_date(line.get("expectedReceiptDate") or line.get("expected_receipt_date"))
        if parsed:
            dates.append(parsed)
    if dates:
        return dates
    if not saw_outstanding:
        return []
    header = parse_date(po.get("expectedReceiptDate") or po.get("expected_receipt_date"))
    return [header] if header else []


def placeholder_dates(purchase_orders: Sequence[dict], share: int = PLACEHOLDER_SHARE_COUNT) -> set:
    """Dates stamped on many open POs at once. Those are not supplier dates."""
    counts: Counter = Counter()
    for po in purchase_orders or []:
        if po_outstanding_qty(po) <= 0:
            continue
        distinct = set(po_expected_dates(po))
        if len(distinct) == 1:
            counts[next(iter(distinct))] += 1
    return {day for day, n in counts.items() if n >= share}


def po_was_sent(po: dict) -> bool:
    status = (po.get("status") or "").strip().lower()
    if "cancel" in status:
        return False
    if status == "draft":
        return False
    if not status and not parse_date(po.get("orderDate") or po.get("order_date")):
        return False
    return True


def _real_expected(po: dict, placeholders: set) -> Optional[date]:
    real = [day for day in po_expected_dates(po) if day not in placeholders]
    return max(real) if real else None


def classify_late_sales_orders(
    sales_orders: Sequence[dict],
    purchase_orders: Sequence[dict],
    *,
    today: Optional[date] = None,
    internal_lead: Optional[int] = None,
    extra_links: Optional[Dict[str, Sequence[str]]] = None,
    confirmed_po_dates: Optional[Dict[str, date]] = None,
) -> dict:
    """Return ``{open_count, late: [...]}``.

    ``extra_links`` maps a PO number to sales orders named on a confirmation
    when the PO text itself does not. ``confirmed_po_dates`` is a supplier
    date we stored that should win over a placeholder on the PO.
    """
    today = today or date.today()
    lead = internal_lead_days(internal_lead)
    placeholders = placeholder_dates(purchase_orders or [])
    by_so: Dict[str, List[dict]] = {}
    for po in purchase_orders or []:
        if po_outstanding_qty(po) <= 0:
            continue
        number = (po.get("number") or "").strip()
        links = list(sales_orders_on_po(po))
        for so in (extra_links or {}).get(number, []):
            normalized = normalize_so(so)
            if normalized and normalized not in links:
                links.append(normalized)
        for so in links:
            by_so.setdefault(so, []).append(po)

    late: List[dict] = []
    open_count = 0
    for order in sales_orders or []:
        if not is_open_unshipped(order):
            continue
        open_count += 1
        so_number = normalize_so(order.get("number") or "") or (order.get("number") or "")
        requested, promised = customer_dates(order)
        commitment = requested or promised
        reasons: List[str] = []
        if requested and requested < today:
            reasons.append(f"requested date {requested.isoformat()} has passed")
        if promised and promised < today and promised != requested:
            reasons.append(f"promised date {promised.isoformat()} has passed")

        supplier_bits: List[str] = []
        for po in by_so.get(so_number, []):
            po_number = (po.get("number") or "").strip()
            expected = None
            if confirmed_po_dates and po_number in confirmed_po_dates:
                expected = confirmed_po_dates[po_number]
            if expected is None:
                expected = _real_expected(po, placeholders)
            if expected is None or commitment is None:
                continue
            arrival = add_business_days(expected, lead) if lead else expected
            if arrival > commitment:
                supplier_bits.append(
                    f"supplier date {expected.isoformat()} on {po_number}"
                    + (
                        f" plus {lead} business days internal lead lands {arrival.isoformat()}"
                        if lead
                        else ""
                    )
                    + f", after requested {commitment.isoformat()}"
                )
        if supplier_bits:
            reasons.append("; ".join(supplier_bits))
        if not reasons:
            continue
        late.append({
            "so_number": so_number,
            "customer": order.get("customerName") or order.get("customer_name") or "",
            "requested_date": commitment.isoformat() if commitment else None,
            "requested_raw": requested.isoformat() if requested else None,
            "promised_date": promised.isoformat() if promised else None,
            "reason": "; ".join(reasons),
            "outstanding_qty": outstanding_qty(order),
        })

    late.sort(key=lambda row: (row["requested_date"] or "9999", row["so_number"]))
    return {
        "open_count": open_count,
        "late_count": len(late),
        "internal_lead_days": lead,
        "placeholder_dates": sorted(day.isoformat() for day in placeholders),
        "late": late,
    }


def email_subject(report: dict) -> str:
    return (
        f"OPENDC Planning — {report.get('late_count', 0)} late sales order(s) "
        f"of {report.get('open_count', 0)} not fully shipped"
    )


def email_late_section(report: dict) -> str:
    """HTML table of the late list. Empty when nothing is late."""
    import html as html_lib

    rows = report.get("late") or []
    if not rows:
        return (
            "<p>No open sales order is late. "
            "Late means quantity still to ship, and either the customer's "
            "requested or promised date has passed, or a supplier expected "
            "date plus internal lead lands after that date.</p>"
        )
    body = [
        "<table cellpadding='6' cellspacing='0' border='1' "
        "style='border-collapse:collapse;font-size:14px'>",
        "<tr><th align='left'>SO</th><th align='left'>Customer</th>"
        "<th align='left'>Requested</th><th align='left'>Reason</th></tr>",
    ]
    for row in rows:
        body.append(
            "<tr>"
            f"<td>{html_lib.escape(row['so_number'])}</td>"
            f"<td>{html_lib.escape(row.get('customer') or '')}</td>"
            f"<td>{html_lib.escape(row.get('requested_date') or '')}</td>"
            f"<td>{html_lib.escape(row.get('reason') or '')}</td>"
            "</tr>"
        )
    body.append("</table>")
    return "\n".join(body)
