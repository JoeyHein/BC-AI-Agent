"""Parse supplier confirmations into a purchase order, a supplier order
number, and an expected receipt date.

Covers three shapes that land in joey@ and Finance@:

* Upwardor acknowledgements from upwardor.com (S-ORD, often ``PO#000956``
  or ``PO 1107``).
* Elton Manufacturing order confirmations.
* Upwardor / Michael open-order lists (a spreadsheet or a pasted table).

Matching is by our PO number or by the supplier's own order number.
Nothing here calls Business Central or sends mail.
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from datetime import date
from typing import List, Optional, Sequence

from app.services.vendor_ack_parser import (
    PO_DASH_RE,
    PO_HASH_RE,
    PO_LABELED_RE,
    SORD_RE,
    _coerce_date,
    email_body_text,
    html_to_text,
    normalize_po_number,
    parse_acknowledgement,
    po_base,
)

PO_SPACE_RE = re.compile(r"(?i)\bPO\s+(\d{3,})\s*(?:\(\s*(\d+)\s*\))?")

_DATE_TOKEN = (
    r"\d{4}-\d{2}-\d{2}"
    r"|\d{1,2}[\-/][A-Za-z]{3,}[\-/]\d{2,4}"
    r"|[A-Za-z]{3,9}\s+\d{1,2},?\s+\d{4}"
    r"|\d{1,2}[/-]\d{1,2}[/-]\d{2,4}"
)
DATE_LABEL_RE = re.compile(
    r"(?i)(?:completion|expected(?:\s+\w+){0,2}|ship(?:ment)?|ready|eta|delivery)"
    r"\s*date\s*[:\-]?\s*(" + _DATE_TOKEN + r")"
)
SUPPLIER_NO_RE = re.compile(
    r"(?i)(?:sales\s*order|our\s*order|order\s*(?:no\.?|number|#)|"
    r"confirmation\s*(?:no\.?|number|#)|acknowledgement\s*(?:no\.?|number|#))"
    r"\s*[:#\-]?\s*([A-Z]{0,5}-?\d{4,})"
)
_OUR_SO_RE = re.compile(r"\bSO-(\d{3,})\b", re.IGNORECASE)

_PO_HEADERS = ("purchase order", "your po", "customer po", "od po", "p.o", "po number", "po #", "po no")
_SORD_HEADERS = ("sales order", "s-ord", "supplier order", "supplier so", "our order", "order number", "order no")
_DATE_HEADERS = ("expected", "ship date", "completion", "eta", "receipt date", "ready date")


@dataclass
class ParsedSupplierConfirmation:
    vendor_key: str
    supplier_order_no: Optional[str]
    po_numbers: List[str] = field(default_factory=list)
    our_so_numbers: List[str] = field(default_factory=list)
    expected_date: Optional[date] = None
    source: str = "acknowledgement"  # acknowledgement | open_orders


def find_po_numbers(*chunks: str) -> List[str]:
    """Every PO mentioned, normalized to PO-001107. ``PO 1107`` counts."""
    found: List[str] = []
    seen = set()
    for chunk in chunks:
        if not chunk:
            continue
        for pattern in (PO_LABELED_RE, PO_HASH_RE, PO_DASH_RE, PO_SPACE_RE):
            for match in pattern.finditer(chunk):
                suffix = match.group(2) if match.lastindex and match.lastindex >= 2 else None
                number = normalize_po_number(match.group(1), suffix)
                base = po_base(number) or number
                if base in seen:
                    continue
                seen.add(base)
                found.append(number if suffix else base)
    return found


def _sord_numbers(*chunks: str) -> List[str]:
    found: List[str] = []
    for chunk in chunks:
        if not chunk:
            continue
        for match in SORD_RE.finditer(chunk):
            number = f"S-ORD{match.group(1)}"
            if number not in found:
                found.append(number)
    return found


def _supplier_numbers(*chunks: str) -> List[str]:
    found = _sord_numbers(*chunks)
    sord_digits = {re.sub(r"\D", "", number) for number in found}
    for chunk in chunks:
        if not chunk:
            continue
        for match in SUPPLIER_NO_RE.finditer(chunk):
            token = re.sub(r"\s+", "", match.group(1)).upper()
            if token.startswith("PO"):
                continue
            if re.fullmatch(r"SO-?\d+", token):
                continue
            digits = re.sub(r"\D", "", token)
            if digits and digits in sord_digits:
                continue
            if token.isdigit():
                token = f"S-ORD{token}" if "s-ord" in chunk.lower() or "upwardor" in chunk.lower() else token
            if token not in found:
                found.append(token)
    return found


def _our_sales_orders(*chunks: str) -> List[str]:
    found: List[str] = []
    for chunk in chunks:
        if not chunk:
            continue
        for match in _OUR_SO_RE.finditer(chunk):
            number = f"SO-{int(match.group(1)):06d}"
            if number not in found:
                found.append(number)
    return found


def _labeled_date(*chunks: str) -> Optional[date]:
    for chunk in chunks:
        if not chunk:
            continue
        match = DATE_LABEL_RE.search(chunk)
        if not match:
            continue
        parsed = _coerce_date(match.group(1).strip())
        if parsed:
            return parsed
    return None


def vendor_key_for(sender: str, subject: str, body: str) -> str:
    blob = f"{sender or ''}\n{subject or ''}\n{body or ''}".lower()
    if "upwardor" in blob or "s-ord" in blob:
        return "upwardor"
    if "elton" in blob:
        return "elton"
    return "supplier"


def is_open_orders_message(subject: str, body: str, filename: str = "") -> bool:
    blob = f"{subject or ''}\n{body or ''}\n{filename or ''}".lower()
    if "open order" in blob or "open-order" in blob or "sales order master" in blob:
        return True
    if "michael" in blob and ("upwardor" in blob or "s-ord" in blob):
        return True
    return False


def is_supplier_confirmation_email(subject: str, body: str, sender: str = "", filename: str = "") -> bool:
    """True when the message is worth opening for a confirmation or open-order list."""
    blob = f"{subject or ''}\n{body or ''}\n{sender or ''}\n{filename or ''}".lower()
    if is_open_orders_message(subject, body, filename):
        return True
    sender_l = (sender or "").lower()
    from_supplier = (
        "upwardor.com" in sender_l
        or "elton" in sender_l
        or "upwardor" in blob
        or "elton" in blob
    )
    if not from_supplier and "s-ord" not in blob:
        return False
    if any(token in blob for token in (
        "confirm", "acknowledg", "s-ord", "order#", "order #", "purchase order", " po-", " po ", "po#",
    )):
        return True
    return False


def _one(
    vendor: str,
    supplier_no: Optional[str],
    po_numbers: Sequence[str],
    our_sos: Sequence[str],
    expected: Optional[date],
    source: str,
) -> List[ParsedSupplierConfirmation]:
    pos = list(po_numbers) or [None]
    rows = []
    for po in pos:
        if not supplier_no and not po and not expected:
            continue
        rows.append(ParsedSupplierConfirmation(
            vendor_key=vendor,
            supplier_order_no=supplier_no,
            po_numbers=[po] if po else [],
            our_so_numbers=list(our_sos),
            expected_date=expected,
            source=source,
        ))
    return rows


def parse_confirmation_text(
    *,
    subject: str = "",
    body: str = "",
    sender: str = "",
    filename: str = "",
    pdf_text: str = "",
) -> List[ParsedSupplierConfirmation]:
    """Parse one acknowledgement body or PDF. Open-order tables use the other parser."""
    subject = subject or ""
    body = body or ""
    pdf_text = pdf_text or ""
    filename = filename or ""
    vendor = vendor_key_for(sender, subject, f"{body}\n{pdf_text}")
    ack = parse_acknowledgement(subject=subject, body=body, filename=filename, pdf_text=pdf_text)
    pos = find_po_numbers(pdf_text, subject, body, filename)
    supplier_nos = _supplier_numbers(pdf_text, subject, body, filename)
    our_sos = _our_sales_orders(pdf_text, body, subject)
    expected = _labeled_date(pdf_text, body, subject)
    if ack is not None:
        if ack.vendor_order_no and ack.vendor_order_no not in supplier_nos:
            supplier_nos.insert(0, ack.vendor_order_no)
        if ack.our_po_number:
            base = po_base(ack.our_po_number)
            if base and base not in {po_base(p) for p in pos}:
                pos.insert(0, ack.our_po_number)
        if ack.completion_date and expected is None:
            expected = ack.completion_date
        for so in ack.our_so_numbers or []:
            if so not in our_sos:
                our_sos.append(so)
        if vendor == "supplier":
            vendor = "upwardor"
    supplier_no = supplier_nos[0] if supplier_nos else None
    if not supplier_no and not pos and not expected:
        return []
    return _one(vendor, supplier_no, pos, our_sos, expected, "acknowledgement")


def _header_index(cells: Sequence, needles: Sequence[str]) -> Optional[int]:
    for index, cell in enumerate(cells):
        label = re.sub(r"\s+", " ", str(cell or "").strip().lower())
        if not label:
            continue
        for needle in needles:
            if needle in label:
                # "Sales Order No." is the supplier order, not our PO.
                if needle in ("po",) and "sales" in label:
                    continue
                return index
    return None


def _po_header_index(cells: Sequence) -> Optional[int]:
    for index, cell in enumerate(cells):
        label = re.sub(r"\s+", " ", str(cell or "").strip().lower())
        if not label or "sales order" in label:
            continue
        if label in {"po", "p.o.", "p.o"} or any(needle in label for needle in _PO_HEADERS):
            return index
    return None


def parse_open_order_rows(rows: Sequence[Sequence]) -> List[ParsedSupplierConfirmation]:
    """Rows of an open-order list. The first matching header row names the columns.

    Raises ValueError when no header identifies a PO column or a supplier
    order column. An empty list after a real header means the supplier sent
    no open orders.
    """
    header_at = None
    po_idx = sord_idx = date_idx = None
    scanned = list(rows or [])
    for offset, raw in enumerate(scanned[:20]):
        cells = list(raw or [])
        po_idx = _po_header_index(cells)
        sord_idx = _header_index(cells, _SORD_HEADERS)
        date_idx = _header_index(cells, _DATE_HEADERS)
        if po_idx is not None or sord_idx is not None:
            header_at = offset
            break
    if header_at is None:
        raise ValueError("Open-order list has no PO or supplier-order column")
    parsed: List[ParsedSupplierConfirmation] = []
    for raw in scanned[header_at + 1:]:
        cells = list(raw or [])
        if not any(str(c or "").strip() for c in cells):
            continue
        po_text = str(cells[po_idx]).strip() if po_idx is not None and po_idx < len(cells) else ""
        sord_text = str(cells[sord_idx]).strip() if sord_idx is not None and sord_idx < len(cells) else ""
        date_text = str(cells[date_idx]).strip() if date_idx is not None and date_idx < len(cells) else ""
        pos = find_po_numbers(po_text) or find_po_numbers(" ".join(str(c or "") for c in cells))
        supplier_nos = _supplier_numbers(sord_text, po_text)
        if not supplier_nos and sord_text:
            token = re.sub(r"\s+", "", sord_text).upper()
            if token and not token.startswith("PO") and not re.fullmatch(r"SO-?\d+", token):
                supplier_nos = [token if token.startswith("S-ORD") or not token.isdigit() else f"S-ORD{token}"]
                if token.isdigit():
                    supplier_nos = [f"S-ORD{token}"]
        expected = _coerce_date(date_text) if date_text else None
        if not expected:
            expected = _labeled_date(date_text)
        supplier_no = supplier_nos[0] if supplier_nos else None
        if not supplier_no and not pos:
            continue
        parsed.extend(_one("upwardor", supplier_no, pos, [], expected, "open_orders"))
    return parsed


_LINE_RE = re.compile(
    r"(?i)\b(PO[-\s]?\d{3,}(?:\(\s*\d+\s*\))?)\b"
    r".{0,60}?"
    r"\b(S-ORD\s*\d{4,}|[A-Z]{1,5}-?\d{4,})\b"
    r"(?:.{0,40}?(" + _DATE_TOKEN + r"))?"
)


def parse_open_order_text(text: str) -> List[ParsedSupplierConfirmation]:
    """Pasted lines such as ``PO-001107  S-ORD116307  2026-12-04``."""
    rows = []
    for line in (text or "").splitlines():
        match = _LINE_RE.search(line)
        if not match:
            continue
        po = match.group(1)
        supplier = re.sub(r"\s+", "", match.group(2)).upper()
        if supplier.startswith("PO"):
            continue
        when = _coerce_date(match.group(3)) if match.group(3) else None
        rows.extend(_one(
            "upwardor",
            supplier if supplier.startswith("S-ORD") or not supplier.startswith("SO-") else supplier,
            find_po_numbers(po),
            [],
            when,
            "open_orders",
        ))
    return rows


def parse_open_order_csv(content: bytes) -> List[ParsedSupplierConfirmation]:
    text = content.decode("utf-8-sig", errors="replace")
    reader = csv.reader(io.StringIO(text))
    return parse_open_order_rows(list(reader))


def parse_open_order_xlsx(content: bytes) -> List[ParsedSupplierConfirmation]:
    from openpyxl import load_workbook

    if not content:
        raise ValueError("Open-order workbook is empty")
    wb = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    try:
        ws = wb.active
        rows = [list(row) for row in ws.iter_rows(values_only=True)]
    finally:
        wb.close()
    return parse_open_order_rows(rows)


def parse_supplier_message(
    *,
    subject: str = "",
    body: str = "",
    sender: str = "",
    filename: str = "",
    pdf_text: str = "",
    attachment_bytes: Optional[bytes] = None,
) -> List[ParsedSupplierConfirmation]:
    """One email. Spreadsheet attachments are open-order lists; the rest are acknowledgements."""
    name = (filename or "").lower()
    if attachment_bytes and (name.endswith(".xlsx") or name.endswith(".xlsm")):
        return parse_open_order_xlsx(attachment_bytes)
    if attachment_bytes and name.endswith(".csv"):
        return parse_open_order_csv(attachment_bytes)
    text = "\n".join(part for part in (pdf_text, body, subject) if part)
    if is_open_orders_message(subject, body, filename) and not pdf_text:
        listed = parse_open_order_text(text)
        if listed:
            return listed
    if is_open_orders_message(subject, body, filename) and pdf_text:
        listed = parse_open_order_text(pdf_text) or parse_open_order_text(body)
        if listed:
            return listed
    return parse_confirmation_text(
        subject=subject, body=body, sender=sender, filename=filename, pdf_text=pdf_text,
    )


def message_body(email: dict) -> str:
    return email_body_text(email) or html_to_text(email.get("bodyPreview") or "")
