"""Incoming lane and supplier shipping-mail matching.

Open purchase orders are read with GET only. A shipping email can update
the portal overlay (ETA, carrier, tracking, Shipped) and a supplier-order
map. Nothing here calls a Business Central POST, PATCH, or DELETE.

The build date for a row is the purchase order requested receipt date.
A saved shipping notice can replace that ETA. A row with no date stays off
the board.

Upwardor purchase orders are listed separately, still from this same
read. Their ETA is the ship-notice date when one is saved, otherwise the
expected receipt date. A row with no date, or a date past the 7-day
window, stays on that list under Later. Other vendors keep the Incoming
window and still drop undated rows.

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
from app.services.po_line_order import (
    GLASS_SECTION_PREFIXES,
    INSULATED_SECTION_PREFIXES,
    _prefix_match,
)
from app.services.shop_tv_board import (
    SHOP_TZ,
    _group,
    _read_setting,
    _write_setting,
    parse_when,
    shop_today,
)
from app.services.sku_geometry import PANEL_RE
from app.services.vendor_ack_parser import (
    ORDER_DIGITS_RE,
    PO_DASH_RE,
    PO_HASH_RE,
    PO_LABELED_RE,
    SORD_RE,
    TAG_SO_RE,
    ack_cells_for_po,
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
_SECTION_PREFIXES = frozenset(INSULATED_SECTION_PREFIXES | GLASS_SECTION_PREFIXES)
_DOOR_FEET_RE = re.compile(
    r"""^\((\d+)\)\s+(\d+)'(\d+)"\s*[xX×]\s*(\d+)'(\d+)"\s+([A-Za-z0-9][A-Za-z0-9-]*)(?:\s*,\s*([^,]+))?""",
    re.IGNORECASE,
)
_DOOR_COMPACT_RE = re.compile(
    r"^\((\d+)\)\s+(\d+)\s*[xX×]\s*(\d+)\s+([A-Za-z0-9][A-Za-z0-9-]*)(?:\s*,\s*([^,]+))?",
    re.IGNORECASE,
)
_SERIES_BY_PREFIX = {
    "PN65": "Kanata",
    "PN95": "Craft",
    "PN45": "TX450",
    "PN46": "TX450",
    "PN47": "TX450",
    "PN48": "TX450",
    "PN55": "TX500",
    "PN56": "TX500",
    "PN57": "TX500",
    "PN58": "TX500",
    "PN35": "TX380",
    "PN36": "TX380",
    "PN75": "TX760",
    "PN76": "TX760",
    "PN10": "V130G",
    "PN12": "V230G",
    "PN80": "Panorama",
    "PN20": "Solalite",
    "PN70": "AL-SWD",
    "PN97": "AL976",
}
_COLOR_BY_CODE = {
    "00": "white",
    "01": "brown",
    "03": "almond",
    "04": "sandtone",
    "05": "black",
    "06": "bronze",
    "10": "new brown",
    "15": "onyx black",
    "20": "steel grey",
    "25": "iron ore",
    "30": "new almond",
    "35": "french oak",
    "40": "hazelwood",
    "45": "canyon",
    "51": "walnut",
    "55": "english chestnut",
}


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


def supplier_key_from_sender(sender: str) -> str:
    """Supplier identity comes from the sender domain, not a person's first name."""
    match = re.search(r"@([a-z0-9.-]+)", (sender or "").lower())
    domain = match.group(1) if match else ""
    if not domain:
        return ""
    if domain == "upwardor.com" or domain.endswith(".upwardor.com"):
        return "upwardor"
    if "elton" in domain:
        return "elton"
    if domain == "dek.com" or domain.endswith(".dek.com") or "dekcanada" in domain:
        return "dek"
    compact = domain.replace("-", "")
    if "globaloverhead" in compact:
        return "global"
    return ""


def carrier_key_from_sender(sender: str) -> str:
    """Carriers are not vendors. TEAMS and Manitoulin do not pick a supplier."""
    match = re.search(r"@([a-z0-9.-]+)", (sender or "").lower())
    domain = (match.group(1) if match else "").replace("-", "")
    if "teamstransport" in domain:
        return "teams"
    if "manitoulin" in domain:
        return "manitoulin"
    return ""


def carrier_key_from_text(carrier: str) -> str:
    text = (carrier or "").lower()
    if "teams transport" in text:
        return "teams"
    if "manitoulin" in text:
        return "manitoulin"
    return ""


def vendor_supplier_key(po: dict) -> str:
    blob = f"{po.get('vendorName') or ''} {po.get('vendorNumber') or ''}"
    if re.search(r"(?i)upwardor|\bUPW\b", blob):
        return "upwardor"
    if re.search(r"(?i)\belton\b", blob):
        return "elton"
    if re.search(r"(?i)\bdek\b", blob):
        return "dek"
    if re.search(r"(?i)global overhead", blob):
        return "global"
    return ""


def canonical_supplier_order(raw: str, supplier_key: str) -> str:
    """Exact token for one vendor. Upwardor uses S-ORD. Other vendors keep their own form."""
    compact = re.sub(r"[^A-Z0-9]", "", (raw or "").upper())
    if not compact:
        return ""
    if supplier_key == "upwardor":
        digits = re.search(r"(\d{4,})", compact)
        if digits and (compact.startswith("SORD") or compact.startswith("ORDER")):
            return f"S-ORD{digits.group(1)}"
    return compact


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
    supplier_key = supplier_key_from_sender(sender)
    sord = ""
    sord_match = SORD_RE.search(text)
    order_match = ORDER_DIGITS_RE.search(text)
    if sord_match:
        sord = canonical_supplier_order(f"S-ORD {sord_match.group(1)}", supplier_key)
    elif order_match:
        sord = canonical_supplier_order(f"ORDER {order_match.group(1)}", supplier_key)
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
        "supplier_key": supplier_key,
        "supplier_order_no": sord,
        "our_po_number": our_po,
        "sales_orders": sales_orders,
        "carrier": carrier_match.group(1).strip() if carrier_match else "",
        "carrier_key": carrier_key_from_sender(sender) or carrier_key_from_text(
            carrier_match.group(1) if carrier_match else ""
        ),
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


def sales_orders_for_po(po: dict, tracker_links=None, sales_by_number=None, maps=None) -> list:
    """SO links for one PO: the existing resolver, then a saved supplier map.

    ``linked_sales_orders`` already reads the external document, your
    reference, ``Built from SO-`` / ``TAG:SO-`` text, and tracker
    ``linked_po_number``. A saved map is the same supplier-order map the
    ship-notice matcher uses. It is applied only when it names this PO.
    """
    linked = linked_sales_orders(po, tracker_links, sales_by_number)
    known = {item["number"] for item in linked}
    po_key = po_digits(po.get("number"))
    supplier = vendor_supplier_key(po)
    sales_by_number = sales_by_number or {}
    for row in maps or []:
        if po_digits(row.get("our_po_number")) != po_key:
            continue
        row_key = row.get("supplier_key") or ""
        if row_key and supplier and row_key != supplier:
            continue
        for item in row.get("sales_orders") or []:
            if isinstance(item, str):
                number = item.upper()
                customer = ""
            else:
                number = str((item or {}).get("number") or "").upper()
                customer = str((item or {}).get("customer") or "").strip()
            if not number or number in known:
                continue
            if not customer:
                sales = sales_by_number.get(number) or {}
                customer = str(sales.get("customerName") or sales.get("customer_name") or "").strip()
            linked.append({"number": number, "customer": customer})
            known.add(number)
    return linked


def _qty_text(value) -> str:
    number = float(value)
    if abs(number - round(number)) < 1e-6:
        return str(int(round(number)))
    return f"{number:g}"


def _outstanding_qty(line: dict) -> float:
    try:
        qty = float(line.get("quantity") or 0)
        received = float(line.get("receivedQuantity") if line.get("receivedQuantity") is not None else line.get("received_quantity") or 0)
    except (TypeError, ValueError):
        return 0.0
    return max(qty - received, 0.0)


def _is_comment_line(line: dict) -> bool:
    return str(line.get("lineType") or line.get("line_type") or "").strip().lower() == "comment"


def _is_item_line(line: dict) -> bool:
    return str(line.get("lineType") or line.get("line_type") or "Item").strip().lower() == "item"


def _series_label(raw: str) -> str:
    text = (raw or "").strip()
    if not text:
        return ""
    if any(ch.isdigit() for ch in text):
        return text.upper()
    return text.capitalize()


def _color_label(raw: str) -> str:
    return " ".join((raw or "").split()).lower()


def _feet_size(width_feet, width_inches, height_feet, height_inches) -> str:
    def part(feet, inches):
        feet = int(feet)
        inches = int(inches or 0)
        if inches:
            return f"{feet}'{inches}"
        return str(feet)

    return f"{part(width_feet, width_inches)}x{part(height_feet, height_inches)}"


def _parse_door_header(text: str):
    raw = " ".join((text or "").split())
    feet = _DOOR_FEET_RE.match(raw)
    if feet:
        return {
            "qty": float(feet.group(1)),
            "size": _feet_size(feet.group(2), feet.group(3), feet.group(4), feet.group(5)),
            "series": _series_label(feet.group(6)),
            "color": _color_label(feet.group(7) or ""),
        }
    compact = _DOOR_COMPACT_RE.match(raw)
    if compact:
        return {
            "qty": float(compact.group(1)),
            "size": f"{int(compact.group(2))}x{int(compact.group(3))}",
            "series": _series_label(compact.group(4)),
            "color": _color_label(compact.group(5) or ""),
        }
    return None


def _is_section_line(line: dict) -> bool:
    item = str(line.get("lineObjectNumber") or line.get("item_no") or "").strip()
    if _prefix_match(item, _SECTION_PREFIXES):
        return True
    description = str(line.get("description") or "").lower()
    return "section" in description and "hardware" not in description


def _section_identity(line: dict) -> dict:
    item = str(line.get("lineObjectNumber") or line.get("item_no") or "").strip().upper()
    match = PANEL_RE.match(item)
    if match:
        prefix, _height, _stamp, color_code, width = match.groups()
        feet, inches = int(width[:2]), int(width[2:])
        size = f"{feet}'" if inches == 0 else f"{feet}'{inches}\""
        series = _SERIES_BY_PREFIX.get(prefix, "")
        color = _COLOR_BY_CODE.get(color_code, "")
        return {"key": ("sku", size, series, color), "size": size, "series": series, "color": color}
    description = " ".join(str(line.get("description") or "").split())
    short = (description[:48].rstrip() or "sections")
    return {"key": ("desc", short.lower()), "raw": short}


def _section_phrase(qty, size: str, series: str, color: str) -> str:
    words = [f"{_qty_text(qty)}× {size}"]
    if series:
        words.append(series)
    if color:
        words.append(color)
    words.append("sections")
    return " ".join(words)


def summarize_po_lines(lines) -> str:
    """Plain one-line summary of what is still coming on a purchase order.

    A door comment such as ``(2) 10'0" x 7'0" KANATA, WHITE`` becomes
    ``2× 10x7 Kanata white sections``. Outstanding lines that are not
    sections collapse to ``+ hardware``. Section SKUs are used when the
    PO has no door comment. Fully received lines are skipped.
    """
    doors = []
    loose = {}
    loose_order = []
    hardware = False
    current = None
    for line in lines or []:
        if not isinstance(line, dict):
            continue
        if _is_comment_line(line):
            parsed = _parse_door_header(line.get("description") or "")
            if parsed:
                doors.append({**parsed, "outstanding": 0.0})
                current = len(doors) - 1
            continue
        if not _is_item_line(line):
            continue
        outstanding = _outstanding_qty(line)
        if outstanding <= 0:
            continue
        if _is_section_line(line):
            if current is not None:
                doors[current]["outstanding"] += outstanding
            else:
                ident = _section_identity(line)
                bucket = loose.get(ident["key"])
                if bucket is None:
                    bucket = {**ident, "qty": 0.0}
                    loose[ident["key"]] = bucket
                    loose_order.append(ident["key"])
                bucket["qty"] += outstanding
        else:
            hardware = True

    merged = {}
    merged_order = []
    for door in doors:
        if door["outstanding"] <= 0:
            continue
        key = (door["size"], door["series"], door["color"])
        if key not in merged:
            merged[key] = {"qty": 0.0, "size": door["size"], "series": door["series"], "color": door["color"]}
            merged_order.append(key)
        merged[key]["qty"] += door["qty"]
    phrases = [
        _section_phrase(merged[key]["qty"], merged[key]["size"], merged[key]["series"], merged[key]["color"])
        for key in merged_order
    ]
    for key in loose_order:
        bucket = loose[key]
        if bucket.get("raw"):
            phrases.append(f"{_qty_text(bucket['qty'])}× {bucket['raw']}")
        else:
            phrases.append(_section_phrase(bucket["qty"], bucket["size"], bucket["series"], bucket["color"]))
    if not phrases:
        return "Hardware" if hardware else ""
    text = ", ".join(phrases)
    if hardware:
        text += " + hardware"
    if len(text) > 140:
        text = text[:137].rstrip() + "…"
    return text


def so_completion_text(so_number: str, other_po_numbers, *, needs_stock: bool = False) -> str:
    """``Completes SO-xxxx`` or ``SO-xxxx also waiting on PO-yyyy``.

    ``other_po_numbers`` are open purchase orders already linked to this
    sales order, excluding the one being received. ``needs_stock`` means
    a tracker line for that sales order is still sourced from stock.
    """
    so = str(so_number or "").upper()
    others = []
    seen = set()
    for raw in other_po_numbers or []:
        label = format_po(raw) or str(raw or "").strip().upper()
        if not label or label in seen:
            continue
        seen.add(label)
        others.append(label)
    others.sort()
    if not others and not needs_stock:
        return f"Completes {so}"
    if others and needs_stock:
        return f"{so} also waiting on {', '.join(others)} and stock"
    if needs_stock:
        return f"{so} also waiting on stock"
    return f"{so} also waiting on {', '.join(others)}"


def _other_open_pos(this_po: str, numbers) -> list:
    this = po_digits(this_po)
    found = []
    seen = set()
    for number in numbers or []:
        key = po_digits(number)
        if not key or key == this or key in seen:
            continue
        seen.add(key)
        found.append(format_po(number) or f"PO-{key.zfill(6)}")
    found.sort()
    return found


def completion_for_po(po_number: str, linked, open_pos_by_so, stock_waiting=None) -> str:
    stock = {str(number).upper() for number in (stock_waiting or set())}
    parts = []
    for item in linked or []:
        so = str(item.get("number") or "").upper()
        if not so:
            continue
        others = _other_open_pos(po_number, (open_pos_by_so or {}).get(so) or [])
        parts.append(so_completion_text(so, others, needs_stock=so in stock))
    return " · ".join(parts)


def _sales_label(linked) -> str:
    if not linked:
        return "STOCK"
    parts = []
    for item in linked:
        number = str(item.get("number") or "").upper()
        customer = str(item.get("customer") or "").strip()
        text = f"{number} {customer}".strip()
        if text:
            parts.append(text)
    return " · ".join(parts) or "STOCK"


def _customer_field(linked) -> str:
    if not linked:
        return "STOCK"
    names = [str(item.get("customer") or "").strip() for item in linked if str(item.get("customer") or "").strip()]
    if len(names) == 1:
        return names[0]
    if len(names) > 1:
        return " · ".join(names)
    return ""


def supplier_order_label(raw: str, supplier_key: str = "upwardor") -> str:
    token = canonical_supplier_order(raw or "", supplier_key)
    if not token:
        return " ".join(str(raw or "").split())
    match = re.fullmatch(r"S-ORD(\d+)", token)
    if match:
        return f"S-ORD {match.group(1)}"
    return token


def _ack_supplier_order(ack_cells: dict) -> str:
    raw = str((ack_cells or {}).get("vendor_ack") or "")
    first = raw.split(";")[0]
    return re.sub(r"\s*\(\d+\)\s*$", "", first).strip()


def upwardor_status(notice: dict, ack_cells: dict) -> str:
    """Ship notice wins. Otherwise the vendor acknowledgement, or No ack."""
    if str((notice or {}).get("status") or "").lower() == "shipped":
        return "Shipped"
    primary = str((ack_cells or {}).get("ack_status") or "").split(";")[0].strip().lower()
    primary = re.sub(r"\s*\(\d+\)\s*$", "", primary).strip()
    if primary.startswith("revised"):
        return "Revised"
    if primary.startswith("confirmed"):
        return "Acknowledged"
    if primary.startswith("cancel"):
        return "Ack cancelled"
    return "No ack"


def upwardor_eta(po: dict, notice: dict):
    """Ship-notice ETA, else expected receipt, else the header requested date.

    Returns ``(day, clock, source)``. ``source`` is ``notice``,
    ``expected``, ``requested``, or ``""`` when nothing is a real date.
    """
    parsed = parse_when((notice or {}).get("eta"))
    if parsed:
        return parsed[0], parsed[1], "notice"
    expected = []
    for line in po.get("purchaseOrderLines") or po.get("lines") or []:
        if not isinstance(line, dict) or not _is_item_line(line):
            continue
        if _outstanding_qty(line) <= 0 and float(line.get("quantity") or 0) > 0:
            continue
        found = parse_when(line.get("expectedReceiptDate") or line.get("expected_receipt_date"))
        if found:
            expected.append(found[0])
    if expected:
        return min(expected), None, "expected"
    for key in ("expectedReceiptDate", "expected_receipt_date"):
        found = parse_when(po.get(key))
        if found:
            return found[0], found[1], "expected"
    for key in ("requestedReceiptDate", "requested_receipt_date"):
        found = parse_when(po.get(key))
        if found:
            return found[0], found[1], "requested"
    return None, None, ""


def _open_pos_by_so(purchase_orders, tracker_links, sales_by_number, maps) -> dict:
    found = {}
    for po in purchase_orders or []:
        if not isinstance(po, dict) or not _open_po(po):
            continue
        number = po.get("number") or ""
        if not number:
            continue
        for link in sales_orders_for_po(po, tracker_links, sales_by_number, maps):
            found.setdefault(link["number"], [])
            if number not in found[link["number"]]:
                found[link["number"]].append(number)
    return found


def _review(extracted: dict, reason: str) -> dict:
    return {
        "action": "review",
        "confidence": "low",
        "reason": reason,
        "po_number": "",
        "sales_orders": [],
        "supplier_order_no": extracted.get("supplier_order_no") or "",
        "supplier_key": extracted.get("supplier_key") or "",
        "carrier": extracted.get("carrier") or "",
        "tracking": extracted.get("tracking") or "",
        "eta": extracted.get("eta") or "",
    }


def _pos_for_vendor(purchase_orders, supplier_key: str) -> list:
    return [po for po in purchase_orders or [] if vendor_supplier_key(po) == supplier_key]


def _exact_pos(purchase_orders, po_number: str) -> list:
    key = po_digits(po_number)
    if not key:
        return []
    return [po for po in purchase_orders or [] if po_digits(po.get("number")) == key]


def decide_match(extracted: dict, purchase_orders, maps=None, tracker_links=None, sales_orders=None, staff_po: str = "") -> dict:
    """Apply only an exact match. Anything else is a review.

    A PO number typed by staff is looked up across every open purchase
    order. The vendor then comes from that PO. A carrier is not a vendor:
    the email may name our PO number, and it applies only when that number
    is one open purchase order.
    """
    sales_by_number = {}
    for order in sales_orders or []:
        number = str(order.get("number") or "").upper()
        if number:
            sales_by_number[number] = order
    maps = maps or []
    supplier_key = extracted.get("supplier_key") or ""
    supplier_order = canonical_supplier_order(extracted.get("supplier_order_no") or "", supplier_key)
    carrier_key = extracted.get("carrier_key") or ""
    po = None
    reason = ""
    saved = None

    if staff_po:
        matches = _exact_pos(purchase_orders, staff_po)
        if len(matches) != 1:
            return _review(extracted, "That PO number is missing or matches more than one open purchase order.")
        po = matches[0]
        supplier_key = vendor_supplier_key(po) or supplier_key
        supplier_order = canonical_supplier_order(extracted.get("supplier_order_no") or "", supplier_key)
        reason = "staff selected the purchase order"
    elif not supplier_key and carrier_key:
        if not extracted.get("our_po_number"):
            return _review(extracted, "A carrier email needs our PO number.")
        matches = _exact_pos(purchase_orders, extracted["our_po_number"])
        if len(matches) != 1:
            return _review(extracted, "The PO number on the carrier email is not one open purchase order.")
        po = matches[0]
        supplier_key = vendor_supplier_key(po) or ""
        supplier_order = canonical_supplier_order(extracted.get("supplier_order_no") or "", supplier_key)
        reason = "PO number on the carrier email"
    elif not supplier_key:
        return _review(extracted, "Unknown sender. A staff person has to match this email.")

    if po is None and supplier_order:
        for row in maps:
            row_key = row.get("supplier_key") or ""
            row_order = canonical_supplier_order(row.get("supplier_order_no") or "", row_key)
            if row_key and row_key == supplier_key and row_order == supplier_order:
                saved = row
                break
    if po is None and saved:
        candidates = [
            item for item in _pos_for_vendor(purchase_orders, supplier_key)
            if po_digits(item.get("number")) == po_digits(saved.get("our_po_number"))
        ]
        if len(candidates) != 1:
            return _review(extracted, "Saved map does not point at one open purchase order for this supplier.")
        po = candidates[0]
        reason = "saved supplier map"
    elif po is None and extracted.get("our_po_number"):
        candidates = [
            item for item in _pos_for_vendor(purchase_orders, supplier_key)
            if po_digits(item.get("number")) == po_digits(extracted["our_po_number"])
        ]
        if len(candidates) != 1:
            return _review(extracted, "The PO number on the email is not one open purchase order for this supplier.")
        po = candidates[0]
        reason = "PO number on the email"
    elif po is None and supplier_order:
        candidates = []
        for candidate in _pos_for_vendor(purchase_orders, supplier_key):
            vendor_order = canonical_supplier_order(
                candidate.get("vendorOrderNumber") or candidate.get("vendor_order_no") or "",
                supplier_key,
            )
            if vendor_order and vendor_order == supplier_order:
                candidates.append(candidate)
        if len(candidates) != 1:
            return _review(
                extracted,
                "Supplier order number did not match exactly one open purchase order for this supplier.",
            )
        po = candidates[0]
        reason = "supplier order number on the purchase order"
    if po is None:
        return _review(extracted, "No purchase order number, saved map, or vendor order number matched.")
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
        "supplier_key": supplier_key,
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


def _incoming_detail(linked, supplier_order, carrier, tracking) -> Optional[str]:
    bits = []
    if linked:
        bits.append(", ".join(f"{item['number']} {item['customer']}".strip() for item in linked))
    if supplier_order:
        bits.append(str(supplier_order))
    if carrier or tracking:
        bits.append(" ".join(part for part in (carrier, tracking) if part))
    return " · ".join(bits) or None


def lookup_sales_order_customers(numbers, bc=None) -> dict:
    """GET each sales order that is not already on the board. No writes."""
    if bc is None:
        from app.integrations.bc.client import bc_client
        bc = bc_client
    found = {}
    for number in numbers or []:
        try:
            row = bc.get_sales_order_by_number(number)
        except Exception:
            logger.warning("Shop TV could not read sales order %s", number, exc_info=True)
            continue
        name = str((row or {}).get("customerName") or "").strip()
        if name:
            found[number] = name
    return found


def build_incoming_days(purchase_orders, sales_orders=None, notices=None, tracker_links=None, maps=None, *, today: date, now=None, horizon_days: int = 7, customer_lookup=None) -> dict:
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
        linked = sales_orders_for_po(po, tracker_links, sales_by_number, maps)
        supplier_order = notice.get("supplier_order_no") or po.get("vendorOrderNumber") or ""
        carrier = notice.get("carrier") or ""
        tracking = notice.get("tracking") or ""
        status = notice.get("status") or "expected"
        late = False
        if clock is not None and day == today and now is not None:
            current = now.astimezone(SHOP_TZ) if getattr(now, "tzinfo", None) else now
            late = clock < current.time().replace(microsecond=0, second=0)
        items.append({
            "id": f"incoming:{number}",
            "lane": "incoming",
            "order_number": number,
            "customer": po.get("vendorName") or po.get("vendor_name") or "",
            "detail": _incoming_detail(linked, supplier_order, carrier, tracking),
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
    missing = sorted({
        so["number"]
        for item in items
        for so in item["sales_orders"]
        if so.get("number") and not so.get("customer")
    })
    if missing and customer_lookup:
        try:
            names = customer_lookup(missing) or {}
        except Exception:
            logger.warning("Shop TV customer lookup failed", exc_info=True)
            names = {}
        for item in items:
            changed = False
            for so in item["sales_orders"]:
                if not so.get("customer") and names.get(so["number"]):
                    so["customer"] = names[so["number"]]
                    changed = True
            if changed:
                item["detail"] = _incoming_detail(
                    item["sales_orders"],
                    item.get("supplier_order_no") or "",
                    item.get("carrier") or "",
                    item.get("tracking") or "",
                )
    return {"days": _group(items, today, horizon_days), "omitted_no_date": omitted}


def _later_heading(items: list) -> dict:
    dated = [row for row in items if row.get("date")]
    undated = [row for row in items if not row.get("date")]
    if dated and undated:
        sublabel = "No date or after this week"
    elif dated:
        sublabel = "After this week"
    else:
        sublabel = "No date"
    return {
        "date": None,
        "label": "Later",
        "sublabel": sublabel,
        "is_today": False,
        "overdue": False,
        "later": True,
        "items": items,
    }


def build_upwardor_days(
    purchase_orders,
    sales_orders=None,
    notices=None,
    tracker_links=None,
    maps=None,
    acks=None,
    stock_waiting=None,
    *,
    today: date,
    now=None,
    horizon_days: int = 7,
    customer_lookup=None,
) -> dict:
    """Open Upwardor POs, including undated and past-the-window rows.

    Other vendors are ignored. A date inside today + ``horizon_days`` is
    grouped like Incoming. Anything later, or with no date, is one Later
    group. Overdue dates stay red.
    """
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
    open_by_so = _open_pos_by_so(purchase_orders, tracker_links, sales_by_number, maps)
    window_end = today.toordinal() + horizon_days
    in_window = []
    later = []
    for po in purchase_orders or []:
        if not isinstance(po, dict) or vendor_supplier_key(po) != "upwardor" or not _open_po(po):
            continue
        number = po.get("number") or ""
        if not number:
            continue
        notice = notice_by_po.get(po_digits(number)) or {}
        ack = ack_cells_for_po(number, acks or [])
        day, clock, eta_source = upwardor_eta(po, notice)
        linked = sales_orders_for_po(po, tracker_links, sales_by_number, maps)
        raw_order = (
            str(notice.get("supplier_order_no") or "").strip()
            or str(po.get("vendorOrderNumber") or po.get("vendor_order_no") or "").strip()
            or _ack_supplier_order(ack)
        )
        status = upwardor_status(notice, ack)
        late = False
        overdue = False
        if day is not None:
            overdue = day < today
            if clock is not None and day == today and now is not None:
                current = now.astimezone(SHOP_TZ) if getattr(now, "tzinfo", None) else now
                late = clock < current.time().replace(microsecond=0, second=0)
        summary = summarize_po_lines(po.get("purchaseOrderLines") or po.get("lines") or [])
        item = {
            "id": f"upwardor:{number}",
            "lane": "upwardor",
            "order_number": number,
            "supplier_order_no": canonical_supplier_order(raw_order, "upwardor") or None,
            "supplier_order_label": supplier_order_label(raw_order, "upwardor") if raw_order else "",
            "customer": _customer_field(linked),
            "sales_label": _sales_label(linked),
            "summary": summary,
            "completion": completion_for_po(number, linked, open_by_so, stock_waiting),
            "status_label": status,
            "detail": summary or None,
            "destination": None,
            "date": day.isoformat() if day else None,
            "time": clock.strftime("%H:%M") if clock else None,
            "kind": "eta",
            "when_label": status,
            "eta_source": eta_source or None,
            "overdue": overdue,
            "late": late,
            "sales_orders": linked,
        }
        if day is not None and day.toordinal() <= window_end:
            in_window.append(item)
        else:
            later.append(item)
    missing = sorted({
        so["number"]
        for item in in_window + later
        for so in item["sales_orders"]
        if so.get("number") and not so.get("customer")
    })
    if missing and customer_lookup:
        try:
            names = customer_lookup(missing) or {}
        except Exception:
            logger.warning("Shop TV customer lookup failed", exc_info=True)
            names = {}
        for item in in_window + later:
            changed = False
            for so in item["sales_orders"]:
                if not so.get("customer") and names.get(so["number"]):
                    so["customer"] = names[so["number"]]
                    changed = True
            if changed:
                item["customer"] = _customer_field(item["sales_orders"])
                item["sales_label"] = _sales_label(item["sales_orders"])
    days = [day for day in _group(in_window, today, horizon_days) if day.get("items")]
    if later:
        later.sort(key=lambda row: (row.get("date") is None, row.get("date") or "", row.get("order_number") or ""))
        days.append(_later_heading(later))
    return {"days": days}


def load_purchase_orders(bc=None):
    """Read open purchase orders. Calls get_open_purchase_orders_with_lines only."""
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


def _acks(db: Optional[Session]) -> list:
    if db is None:
        return []
    nested = None
    try:
        from app.db.models import VendorOrderAck
        nested = db.begin_nested()
        rows = db.query(VendorOrderAck).all()
        nested.commit()
    except Exception:
        logger.warning("Shop TV incoming could not read vendor acknowledgements", exc_info=True)
        if nested is not None:
            try:
                nested.rollback()
            except Exception:
                pass
        return []
    return [
        {
            "vendor_order_no": row.vendor_order_no,
            "our_po_number": row.our_po_number,
            "status": row.status,
            "received_at": row.received_at,
            "completion_date": row.completion_date,
        }
        for row in rows
    ]


def _stock_waiting(db: Optional[Session]) -> set:
    """Sales orders with a tracker line still sourced from stock."""
    if db is None:
        return set()
    nested = None
    try:
        from app.db.models import OpsTrackedLine
        nested = db.begin_nested()
        rows = (
            db.query(OpsTrackedLine)
            .filter(OpsTrackedLine.active.is_(True))
            .filter(OpsTrackedLine.source_code == "STOCK")
            .all()
        )
        nested.commit()
    except Exception:
        logger.warning("Shop TV incoming could not read stock lines", exc_info=True)
        if nested is not None:
            try:
                nested.rollback()
            except Exception:
                pass
        return set()
    found = set()
    for line in rows:
        try:
            remaining = float(line.quantity or 0) - float(line.quantity_shipped or 0)
        except (TypeError, ValueError):
            remaining = 0
        number = str(line.so_number or "").upper()
        if number and remaining > 0:
            found.add(number)
    return found


def attach_incoming(db: Optional[Session], board: dict, *, purchase_orders=None, now=None) -> dict:
    """Add Incoming and Arriving from Upwardor when the flag is on.

    Off leaves both lanes empty and does not read purchase orders.
    Upwardor rows are removed from Incoming so a PO is not listed twice.
    """
    board = dict(board)
    lanes = dict(board.get("lanes") or {})
    if not incoming_enabled(db):
        board["incoming_enabled"] = False
        lanes["incoming"] = {"days": []}
        lanes["upwardor"] = {"days": []}
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
    try:
        maps = _maps(db) if db is not None else []
    except Exception:
        logger.warning("Shop TV incoming supplier maps are unavailable", exc_info=True)
        maps = []
    tracker = _tracker_links(db)
    acks = _acks(db)
    stock = _stock_waiting(db)
    sales = []
    for lane in ("production", "pickups", "deliveries"):
        for day in (lanes.get(lane) or {}).get("days") or []:
            for item in day.get("items") or []:
                if item.get("order_number"):
                    sales.append({"number": item["order_number"], "customerName": item.get("customer")})
    horizon = int(board.get("horizon_days") or 7)
    others = [
        po for po in (purchase_orders or [])
        if not isinstance(po, dict) or vendor_supplier_key(po) != "upwardor"
    ]
    built = build_incoming_days(
        others,
        sales_orders=sales,
        notices=notices,
        tracker_links=tracker,
        maps=maps,
        today=today,
        now=current,
        horizon_days=horizon,
        customer_lookup=lookup_sales_order_customers,
    )
    upwardor = build_upwardor_days(
        purchase_orders,
        sales_orders=sales,
        notices=notices,
        tracker_links=tracker,
        maps=maps,
        acks=acks,
        stock_waiting=stock,
        today=today,
        now=current,
        horizon_days=horizon,
        customer_lookup=lookup_sales_order_customers,
    )
    board["incoming_enabled"] = True
    lanes["incoming"] = {"days": built["days"]}
    lanes["upwardor"] = {"days": upwardor["days"]}
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
    supplier_key = decision.get("supplier_key") or ""
    if supplier_order and supplier_key:
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
    message_id = (extracted.get("message_id") or "").strip()
    if message_id:
        existing = (
            db.query(IncomingEmailReview)
            .filter(IncomingEmailReview.message_id == message_id)
            .first()
        )
        if existing is not None:
            return existing.id
    row = IncomingEmailReview(
        status="pending",
        sender=extracted.get("sender"),
        subject=extracted.get("subject"),
        extracted_json=extracted,
        reason=decision.get("reason"),
        confidence="low",
        proposed_po=extracted.get("our_po_number") or None,
        message_id=message_id or None,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row.id


def _already_seen(db: Session, message_id: str) -> bool:
    from app.db.models import IncomingMailSeen
    if not message_id:
        return False
    return (
        db.query(IncomingMailSeen)
        .filter(IncomingMailSeen.message_id == message_id)
        .first()
        is not None
    )


def _mark_seen(db: Session, message_id: str) -> None:
    from app.db.models import IncomingMailSeen
    if not message_id or _already_seen(db, message_id):
        return
    db.add(IncomingMailSeen(message_id=message_id))
    db.commit()


def message_identity(message: dict, extracted: dict) -> str:
    mid = str(message.get("internetMessageId") or message.get("id") or "").strip()
    if mid:
        return mid[:400]
    return ("fp:" + "|".join([
        extracted.get("sender") or "",
        extracted.get("subject") or "",
        extracted.get("supplier_order_no") or "",
        extracted.get("our_po_number") or "",
    ]))[:400]


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
            extracted = extract_shipping_notice(subject, body, sender)
            identity = message_identity(message, extracted)
            if _already_seen(db, identity):
                continue
            extracted["message_id"] = identity
            processed += 1
            decision = route_notice(db, extracted, purchase_orders, sales_orders, tracker)
            _mark_seen(db, identity)
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
    if row.status != "pending":
        return {"ok": False, "reason": "already handled", "status": row.status}
    extracted = dict(row.extracted_json or {})
    chosen = po_number or row.proposed_po or extracted.get("our_po_number")
    if purchase_orders is None:
        purchase_orders = []
    decision = decide_match(
        extracted,
        purchase_orders,
        _maps(db),
        _tracker_links(db),
        sales_orders,
        staff_po=chosen or "",
    )
    if decision["action"] != "apply":
        return {"ok": False, "reason": decision["reason"]}
    _save_apply(db, decision)
    row.status = "accepted"
    row.proposed_po = decision["po_number"]
    db.commit()
    return {"ok": True, "po_number": decision["po_number"]}


def reject_review(db: Session, review_id: int) -> dict:
    from app.db.models import IncomingEmailReview
    row = db.query(IncomingEmailReview).filter(IncomingEmailReview.id == review_id).first()
    if row is None:
        return {"ok": False}
    if row.status != "pending":
        return {"ok": False, "reason": "already handled", "status": row.status}
    row.status = "rejected"
    db.commit()
    return {"ok": True, "status": "rejected"}
