"""Deterministic parser for Upwardor (UPW) order acknowledgements.

Andrew Couture (Inside Sales) sends a structured subject:

    Confirmation Order#116307 / PO#000956
    Revised Confirmation Order#116307 / PO#000956

The acknowledgement number is S-ORD plus those digits (PDF header or
filename). Our PO is in the subject, body, or PDF ("P.O. No."). Our sales
order is in the PDF as ``TAG:SO-######``. Completion Date is in the PDF.
A split confirmation keeps its suffix (``PO#000960(2)``) so it does not
replace the primary PO's acknowledgement.

Manveer forwards freeform mail ("attached order confirmation") with one PDF
per acknowledgement. Each PDF is parsed on its own. No model call — if a
PDF does not yield an S-ORD number it is skipped.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import List, Optional, Sequence


ORDER_DIGITS_RE = re.compile(r"(?i)\border\s*#\s*(\d{4,})")
SORD_RE = re.compile(r"(?i)\bS-ORD\s*(\d{4,})")
PO_LABELED_RE = re.compile(
    r"(?i)\bP\.?\s*O\.?\s*(?:No\.?|Number|#)\s*[:#\-\s]*"
    r"(\d{3,})\s*(?:\(\s*(\d+)\s*\))?"
)
PO_HASH_RE = re.compile(r"(?i)\bPO\s*#\s*(\d{3,})\s*(?:\(\s*(\d+)\s*\))?")
PO_DASH_RE = re.compile(r"(?i)\bPO-(\d{3,})\s*(?:\(\s*(\d+)\s*\))?")
TAG_SO_RE = re.compile(r"(?i)\bTAG\s*:\s*SO\s*-?\s*(\d{3,})")
COMPLETION_RE = re.compile(
    r"(?i)completion\s*date\s*[:\-]?\s*"
    r"(\d{4}-\d{2}-\d{2}"
    r"|\d{1,2}[\-/][A-Za-z]{3,}[\-/]\d{2,4}"
    r"|[A-Za-z]{3,9}\s+\d{1,2},?\s+\d{4}"
    r"|\d{1,2}[/-]\d{1,2}[/-]\d{2,4})"
)
CANCELLED_RE = re.compile(r"(?i)\b(cancelled|canceled|cancellation)\b")
REVISED_RE = re.compile(r"(?i)\brevised\b")

_MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
}

STATUS_LABELS = {
    "confirmed": "Confirmed",
    "revised": "Revised",
    "cancelled": "Cancelled",
    "pending": "Pending",
    "error": "Error",
}


@dataclass
class ParsedVendorAck:
    vendor_order_no: str
    our_po_number: Optional[str]
    our_so_numbers: List[str] = field(default_factory=list)
    status: str = "confirmed"          # confirmed | revised | cancelled | pending
    document_status: str = "confirmed"  # status before the unmatched→pending fold
    completion_date: Optional[date] = None
    po_source: Optional[str] = None
    subject_order_digits: Optional[str] = None
    pdf_excerpt: str = ""


def html_to_text(raw: Optional[str]) -> str:
    if not raw:
        return ""
    text = re.sub(r"(?i)<\s*br\s*/?\s*>", "\n", raw)
    text = re.sub(r"(?i)</\s*p\s*>", "\n", text)
    text = re.sub(r"<[^>]+>", " ", text)
    return html.unescape(text)


def email_body_text(email: dict) -> str:
    body = email.get("body") or {}
    if isinstance(body, dict):
        content = body.get("content") or ""
    else:
        content = str(body or "")
    text = html_to_text(content)
    if text.strip():
        return text
    return email.get("bodyPreview") or ""


def is_candidate_email(subject: str, body: str) -> bool:
    """Andrew's subject, or a Manveer-style freeform confirmation note.

    Filename-only mail is not opened here — Graph attachment listing pulls
    file bytes, and these mailboxes are personal inboxes. The known Manveer
    path says "attached order confirmation" (or names S-ORD) in the body.
    """
    blob = f"{subject or ''}\n{body or ''}"
    if ORDER_DIGITS_RE.search(subject or ""):
        return True
    if SORD_RE.search(blob):
        return True
    low = blob.lower()
    if "order confirmation" in low or "order acknowledgement" in low or "order acknowledgment" in low:
        return True
    if "upwardor" in low and "acknowledg" in low:
        return True
    return False


def filename_looks_like_ack(filename: str) -> bool:
    name = filename or ""
    low = name.lower()
    return "s-ord" in low or "acknowledg" in low or bool(re.search(r"(?i)so-\d", name))


def normalize_po_number(digits: str, suffix: Optional[str] = None) -> str:
    base = f"PO-{int(digits):06d}"
    if suffix:
        return f"{base}({int(suffix)})"
    return base


def po_base(po_number: Optional[str]) -> Optional[str]:
    """PO-000960(2) and PO-000960 both collapse to PO-000960."""
    if not po_number:
        return None
    match = re.search(r"PO-(\d+)", po_number.upper())
    if match:
        return f"PO-{int(match.group(1)):06d}"
    bare = re.search(r"(\d{3,})", po_number)
    if not bare:
        return None
    return f"PO-{int(bare.group(1)):06d}"


def po_suffix(po_number: Optional[str]) -> Optional[str]:
    if not po_number:
        return None
    match = re.search(r"\((\d+)\)\s*$", po_number.strip())
    return match.group(1) if match else None


def normalize_so(digits: str) -> str:
    return f"SO-{int(digits):06d}"


def _find_po(text: str) -> Optional[tuple]:
    if not text:
        return None
    for pattern in (PO_LABELED_RE, PO_HASH_RE, PO_DASH_RE):
        match = pattern.search(text)
        if match:
            return match.group(1), match.group(2)
    return None


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


def _parse_completion_date(text: str) -> Optional[date]:
    if not text:
        return None
    match = COMPLETION_RE.search(text)
    if not match:
        return None
    return _coerce_date(match.group(1).strip())


def _coerce_date(value: str) -> Optional[date]:
    iso = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", value)
    if iso:
        return _safe_date(int(iso.group(1)), int(iso.group(2)), int(iso.group(3)))

    named = re.fullmatch(
        r"(\d{1,2})[\-/]([A-Za-z]{3,9})[\-/](\d{2,4})", value
    )
    if named:
        month = _MONTHS.get(named.group(2).lower())
        year = _expand_year(named.group(3))
        if month and year:
            return _safe_date(year, month, int(named.group(1)))

    month_first = re.fullmatch(
        r"([A-Za-z]{3,9})\s+(\d{1,2}),?\s+(\d{4})", value
    )
    if month_first:
        month = _MONTHS.get(month_first.group(1).lower())
        if month:
            return _safe_date(int(month_first.group(3)), month, int(month_first.group(2)))

    numeric = re.fullmatch(r"(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})", value)
    if numeric:
        a, b, year = int(numeric.group(1)), int(numeric.group(2)), _expand_year(numeric.group(3))
        if not year:
            return None
        # Ambiguous numeric dates are month/day (the form on the sample
        # acknowledgements). If the first number cannot be a month, treat
        # it as day/month.
        if a > 12 and b <= 12:
            return _safe_date(year, b, a)
        return _safe_date(year, a, b)
    return None


def _expand_year(raw: str) -> Optional[int]:
    year = int(raw)
    if year < 100:
        year += 2000
    if year < 2000 or year > 2100:
        return None
    return year


def _safe_date(year: int, month: int, day: int) -> Optional[date]:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _document_status(subject: str, pdf_text: str) -> str:
    head = f"{subject or ''}\n{(pdf_text or '')[:1200]}"
    if CANCELLED_RE.search(head):
        return "cancelled"
    if REVISED_RE.search(head):
        return "revised"
    return "confirmed"


def _so_numbers(*chunks: str) -> List[str]:
    found: List[str] = []
    for chunk in chunks:
        if not chunk:
            continue
        for match in TAG_SO_RE.finditer(chunk):
            so = normalize_so(match.group(1))
            if so not in found:
                found.append(so)
    return found


def parse_acknowledgement(
    *,
    subject: str = "",
    body: str = "",
    filename: str = "",
    pdf_text: str = "",
) -> Optional[ParsedVendorAck]:
    """Parse one acknowledgement. Returns None when no S-ORD number is present."""
    subject = subject or ""
    body = body or ""
    filename = filename or ""
    pdf_text = pdf_text or ""

    subject_match = ORDER_DIGITS_RE.search(subject)
    subject_digits = subject_match.group(1) if subject_match else None

    pdf_ords = _sord_numbers(pdf_text)
    file_ords = _sord_numbers(filename)
    subject_ords = _sord_numbers(subject, body)

    vendor_order_no: Optional[str] = None
    if subject_digits:
        wanted = f"S-ORD{subject_digits}"
        for candidate in pdf_ords + file_ords + subject_ords:
            if candidate == wanted:
                vendor_order_no = candidate
                break
    if vendor_order_no is None:
        vendor_order_no = (pdf_ords or file_ords or subject_ords or [None])[0]
    if vendor_order_no is None and subject_digits:
        vendor_order_no = f"S-ORD{subject_digits}"
    if not vendor_order_no:
        return None

    po_source = None
    po_hit = _find_po(pdf_text)
    if po_hit:
        po_source = "pdf"
    else:
        po_hit = _find_po(subject)
        if po_hit:
            po_source = "subject"
        else:
            po_hit = _find_po(body)
            if po_hit:
                po_source = "body"

    our_po = normalize_po_number(po_hit[0], po_hit[1]) if po_hit else None
    document_status = _document_status(subject, pdf_text)
    status = document_status if our_po else "pending"

    return ParsedVendorAck(
        vendor_order_no=vendor_order_no,
        our_po_number=our_po,
        our_so_numbers=_so_numbers(pdf_text, body),
        status=status,
        document_status=document_status,
        completion_date=_parse_completion_date(pdf_text) or _parse_completion_date(body),
        po_source=po_source,
        subject_order_digits=subject_digits,
        pdf_excerpt=(pdf_text or "")[:1500],
    )


def ack_cells_for_po(po_number: str, acks: Sequence[dict]) -> dict:
    """Cells for one Purchase Orders sheet row.

    Suffixed acknowledgements (PO-000960(2)) join the base PO but stay
    labeled so they do not replace the primary ack number. Completion Date
    and Ack Received come from the unsuffixed acknowledgement when there
    is one.
    """
    base = po_base(po_number)
    matched = []
    for ack in acks or []:
        if not ack.get("vendor_order_no"):
            continue
        if po_base(ack.get("our_po_number")) != base:
            continue
        if (ack.get("status") or "") in ("pending", "error"):
            continue
        matched.append(ack)
    empty = {
        "vendor_ack": None,
        "ack_status": None,
        "ack_received": None,
        "completion_date": None,
    }
    if not matched:
        return empty

    def _sort_key(ack: dict):
        suffix = po_suffix(ack.get("our_po_number")) or ""
        received = ack.get("received_at") or datetime.min
        return (0 if not suffix else 1, int(suffix) if suffix.isdigit() else 0, received)

    matched.sort(key=_sort_key)
    labels = []
    statuses = []
    for ack in matched:
        suffix = po_suffix(ack.get("our_po_number"))
        number = ack["vendor_order_no"]
        label = STATUS_LABELS.get(ack.get("status") or "", ack.get("status") or "")
        if suffix:
            labels.append(f"{number} ({suffix})")
            statuses.append(f"{label} ({suffix})")
        else:
            labels.append(number)
            statuses.append(label)

    primary = next((a for a in matched if not po_suffix(a.get("our_po_number"))), matched[0])
    return {
        "vendor_ack": "; ".join(labels),
        "ack_status": "; ".join(statuses),
        "ack_received": _received_shop_date(primary.get("received_at")),
        "completion_date": primary.get("completion_date"),
    }


def _received_shop_date(value):
    """Email timestamp → America/Edmonton calendar date for the sheet."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        from zoneinfo import ZoneInfo
        dt = value
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=ZoneInfo("UTC"))
        return dt.astimezone(ZoneInfo("America/Edmonton")).date()
    if isinstance(value, date):
        return value
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return _received_shop_date(parsed)
