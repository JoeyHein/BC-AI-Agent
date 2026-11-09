"""Weekly match of Upwardor's open-order list against our purchase orders.

Staff upload the list Upwardor sends (CSV or Excel) or paste the rows. The
column names vary. Matching uses their S-ORD number and our PO reference when
they filled one in. The purchase orders themselves come from the order
tracker, which is the Business Central snapshot already on the portal.

This is separate from the production-schedule workbook recon. That sheet has
no PO column and only paints RED / MISSED on the schedule. This one is the
exceptions list a purchaser works from, and each run is stored.
"""

from __future__ import annotations

import csv
import io
import re
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Sequence

from openpyxl import load_workbook
from sqlalchemy.orm import Session

from app.db.models import OpsTrackedPo, UpwardorReconRun
from app.services.ops_tracker_service import HEARD_FROM_SUPPLIER, Actor, OpsTrackerError, _is_upwardor

_SORD_RE = re.compile(r"S[\s\-]*ORD[\s\-]*(\d+)", re.IGNORECASE)
_PO_RE = re.compile(r"PO[\s\-]*(\d+)", re.IGNORECASE)
_DIGITS_RE = re.compile(r"^\d{3,8}$")

# Header words, lowercase, after punctuation is stripped to spaces.
# First match wins. Order is most specific first.
HEADER_ALIASES = {
    "sord": (
        "s-ord", "sord", "sales order no", "sales order number", "sales order",
        "upwardor order", "vendor order", "vendor order no", "ack no", "ack number",
        "acknowledgement", "acknowledgment", "their order",
    ),
    "po": (
        "customer po", "customer order", "your po", "our po", "opendc po",
        "po reference", "po number", "po no", "purchase order", "external document",
        "po",
    ),
    "part": ("part no", "part number", "item no", "item number", "sku", "part", "item"),
    "description": ("description", "desc"),
    "qty": (
        "qty ordered", "qty. ordered", "remaining qty", "qty to manufacture",
        "qty. to manufacture", "quantity", "qty",
    ),
    "date": (
        "ship date", "required date", "promise date", "completion date",
        "due date", "order date", "date",
    ),
}

COLUMN_GUIDE = [
    {
        "field": "sord",
        "uses": "Their S-ORD number. This is the acknowledgement.",
        "accepted_headers": list(HEADER_ALIASES["sord"]),
    },
    {
        "field": "po",
        "uses": "Our purchase order, when Upwardor recorded it. Digits are enough (1066 and PO-001066 are the same).",
        "accepted_headers": list(HEADER_ALIASES["po"]),
    },
    {
        "field": "part",
        "uses": "Line item. Kept on the exception so staff can see what the row is.",
        "accepted_headers": list(HEADER_ALIASES["part"]),
    },
    {
        "field": "description",
        "uses": "Line description.",
        "accepted_headers": list(HEADER_ALIASES["description"]),
    },
    {
        "field": "qty",
        "uses": "Quantity ordered or remaining.",
        "accepted_headers": list(HEADER_ALIASES["qty"]),
    },
    {
        "field": "date",
        "uses": "Ship, required, or order date on their row.",
        "accepted_headers": list(HEADER_ALIASES["date"]),
    },
]


def _clean_header(value: Any) -> str:
    text = str(value or "").strip().lower()
    text = text.replace(".", " ").replace("_", " ").replace("#", " ")
    text = re.sub(r"[^a-z0-9\s\-]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def normalize_sord(value: Any) -> Optional[str]:
    match = _SORD_RE.search(str(value or ""))
    if not match:
        return None
    return f"S-ORD{match.group(1)}"


def po_key(value: Any) -> Optional[str]:
    """Digits of a PO number, without leading zeros. None when it is not a PO."""
    text = str(value or "").strip()
    if not text:
        return None
    match = _PO_RE.search(text)
    if match:
        return match.group(1).lstrip("0") or "0"
    if _DIGITS_RE.match(text):
        return text.lstrip("0") or "0"
    return None


def display_po(value: Any) -> Optional[str]:
    key = po_key(value)
    if not key:
        return None
    if len(key) <= 6:
        return f"PO-{int(key):06d}"
    return f"PO-{key}"


def _alias_field(header: str) -> Optional[str]:
    for field, names in HEADER_ALIASES.items():
        for name in names:
            if header == name or header.startswith(name + " "):
                return field
    return None


def _column_values(rows: Sequence[Sequence[Any]], index: int) -> List[str]:
    values = []
    for row in rows:
        if index < len(row) and row[index] not in (None, ""):
            values.append(str(row[index]).strip())
    return values


def map_columns(headers: Sequence[Any], rows: Sequence[Sequence[Any]]) -> Dict[str, int]:
    """Pick a column index per field. Headers win. Cell contents fill the gaps."""
    mapping: Dict[str, int] = {}
    for index, header in enumerate(headers):
        field = _alias_field(_clean_header(header))
        if field and field not in mapping:
            mapping[field] = index
    scores = {"sord": [], "po": []}
    for index in range(len(headers)):
        if index in mapping.values():
            continue
        values = _column_values(rows, index)
        if not values:
            continue
        sord_hits = sum(1 for value in values if normalize_sord(value))
        po_hits = sum(1 for value in values if po_key(value))
        if sord_hits:
            scores["sord"].append((sord_hits / len(values), sord_hits, index))
        if po_hits:
            scores["po"].append((po_hits / len(values), po_hits, index))
    for field in ("sord", "po"):
        if field in mapping or not scores[field]:
            continue
        ratio, hits, index = sorted(scores[field], reverse=True)[0]
        if ratio >= 0.4 or hits >= 2:
            mapping[field] = index
    return mapping


def _cell(row: Sequence[Any], index: Optional[int]) -> str:
    if index is None or index >= len(row) or row[index] is None:
        return ""
    return str(row[index]).strip()


def rows_from_table(headers: Sequence[Any], data_rows: Sequence[Sequence[Any]]) -> dict:
    mapping = map_columns(headers, data_rows)
    if "sord" not in mapping and "po" not in mapping:
        raise OpsTrackerError(
            "Could not find an S-ORD column or a PO column. "
            "Use a header such as 'Sales Order No.' or 'Customer PO', or keep the S-ORD and PO values in their own columns."
        )
    parsed = []
    for offset, row in enumerate(data_rows, start=2):
        if not any(str(cell or "").strip() for cell in row):
            continue
        sord = normalize_sord(_cell(row, mapping.get("sord")))
        raw_po = _cell(row, mapping.get("po"))
        key = po_key(raw_po)
        part = _cell(row, mapping.get("part"))
        description = _cell(row, mapping.get("description"))
        qty = _cell(row, mapping.get("qty"))
        their_date = _cell(row, mapping.get("date"))
        if not sord and not key and not part and not description:
            continue
        parsed.append({
            "sord": sord,
            "po_number": display_po(raw_po) if key else None,
            "po_key": key,
            "their_po_text": raw_po or None,
            "part": part or None,
            "description": description or None,
            "qty": qty or None,
            "date": their_date or None,
            "source_row": offset,
        })
    if not parsed:
        raise OpsTrackerError("The file has headers but no order rows.")
    named = {}
    for field, index in mapping.items():
        header = headers[index] if index < len(headers) else ""
        named[field] = str(header or "").strip() or f"column {index + 1}"
    return {"column_map": named, "rows": parsed}


def _split_header_line(text: str) -> List[List[str]]:
    sample = text.strip()
    if not sample:
        raise OpsTrackerError("Paste the open-order rows, or upload a CSV or Excel file.")
    first = sample.splitlines()[0]
    delimiter = "\t" if first.count("\t") >= first.count(",") and "\t" in first else ","
    reader = csv.reader(io.StringIO(sample), delimiter=delimiter)
    table = [row for row in reader if any(cell.strip() for cell in row)]
    if len(table) < 2:
        raise OpsTrackerError("Need a header row and at least one order row.")
    return table


def _alias_score(column_map: dict) -> tuple:
    hits = 0
    for field, header in column_map.items():
        if _alias_field(_clean_header(header)) == field:
            hits += 1
    return (hits, len(column_map))


def choose_table(table: Sequence[Sequence[Any]]) -> dict:
    """Pick the header row. A title row above the real headers loses to a row whose names match."""
    if len(table) < 2:
        raise OpsTrackerError("Need a header row and at least one order row.")
    best = None
    best_score = (-1, -1)
    last_error = None
    for start in range(min(15, len(table) - 1)):
        try:
            parsed = rows_from_table(table[start], table[start + 1:])
        except OpsTrackerError as exc:
            last_error = exc
            continue
        score = _alias_score(parsed["column_map"])
        if score > best_score:
            best = parsed
            best_score = score
    if best is None:
        raise last_error or OpsTrackerError("Could not find an S-ORD column or a PO column.")
    return best


def parse_open_order_text(text: str) -> dict:
    return choose_table(_split_header_line(text or ""))


def parse_open_order_xlsx(payload: bytes) -> dict:
    try:
        workbook = load_workbook(io.BytesIO(payload), read_only=True, data_only=True)
    except Exception as exc:
        raise OpsTrackerError("That Excel file could not be read. Save it as .xlsx or CSV.") from exc
    sheet = workbook.active
    table = []
    for row in sheet.iter_rows(values_only=True):
        values = ["" if cell is None else str(cell) for cell in row]
        if any(value.strip() for value in values):
            table.append(values)
    workbook.close()
    if len(table) < 2:
        raise OpsTrackerError("The workbook needs a header row and at least one order row.")
    return choose_table(table)


def parse_open_order_payload(payload: bytes, filename: Optional[str] = None) -> dict:
    name = (filename or "").lower()
    if name.endswith(".xls") and not name.endswith(".xlsx"):
        raise OpsTrackerError("Save the old .xls file as .xlsx or CSV and upload that.")
    if name.endswith(".xlsx") or payload[:2] == b"PK":
        return parse_open_order_xlsx(payload)
    try:
        text = payload.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = payload.decode("latin-1")
    return parse_open_order_text(text)


def _received(po: dict) -> bool:
    if po.get("fully_received"):
        return True
    if (po.get("lifecycle") or "") == "received":
        return True
    return bool(po.get("receipt_date"))


def _open_on_ours(po: dict) -> bool:
    if not po.get("bc_open", True):
        return False
    if _received(po):
        return False
    status = (po.get("status") or "").lower()
    if status in {"", "draft"}:
        return False
    if (po.get("lifecycle") or "") == "drafted":
        return False
    return True


def _we_have_ack(po: dict) -> bool:
    if (po.get("ack_status") or "") in HEARD_FROM_SUPPLIER:
        return True
    return bool(normalize_sord(po.get("vendor_order_no")) or (po.get("vendor_order_no") or "").strip())


def _line_summary(rows: Sequence[dict]) -> List[dict]:
    lines = []
    for row in rows:
        if row.get("part") or row.get("description") or row.get("qty"):
            lines.append({
                "part": row.get("part"),
                "description": row.get("description"),
                "qty": row.get("qty"),
                "date": row.get("date"),
            })
    return lines[:12]


def reconcile_open_orders(their_rows: Sequence[dict], our_pos: Sequence[dict]) -> dict:
    """Match Upwardor's rows to Upwardor purchase orders and list the exceptions.

    `our_pos` is every Upwardor PO the tracker knows, open and received.
    Other vendors are ignored.
    """
    ours = [po for po in our_pos if _is_upwardor(po.get("vendor_number"), po.get("vendor_name"))]
    by_key: Dict[str, dict] = {}
    by_sord: Dict[str, dict] = {}
    for po in ours:
        key = po_key(po.get("po_number"))
        if key:
            by_key[key] = po
        sord = normalize_sord(po.get("vendor_order_no"))
        if sord:
            by_sord[sord] = po

    groups: Dict[str, List[dict]] = {}
    order: List[str] = []
    for row in their_rows:
        token = row.get("sord") or (f"po:{row.get('po_key')}" if row.get("po_key") else None)
        if not token:
            token = f"row:{row.get('source_row')}"
        if token not in groups:
            groups[token] = []
            order.append(token)
        groups[token].append(row)

    exceptions: List[dict] = []
    matched: set = set()

    def add(exc_type: str, summary: str, action: str, po: Optional[dict], rows: Sequence[dict], sord: Optional[str]) -> None:
        po_number = (po or {}).get("po_number") or (rows[0].get("po_number") if rows else None)
        exceptions.append({
            "type": exc_type,
            "po_number": po_number,
            "sord": sord,
            "so_numbers": (po or {}).get("so_numbers") or [],
            "our_ack": (po or {}).get("vendor_order_no"),
            "our_status": (po or {}).get("status"),
            "summary": summary,
            "suggested_action": action,
            "lines": _line_summary(rows),
            "dates": [row.get("date") for row in rows if row.get("date")][:6],
        })

    for token in order:
        rows = groups[token]
        sord = next((row.get("sord") for row in rows if row.get("sord")), None)
        key = next((row.get("po_key") for row in rows if row.get("po_key")), None)
        po = by_key.get(key) if key else None
        if po is None and sord:
            po = by_sord.get(sord)
        if po is None:
            if not sord and not key:
                continue
            label = sord or (rows[0].get("po_number") or "a row")
            add(
                "their_sord_no_po",
                f"Upwardor lists {label} and it does not match an Upwardor purchase order of ours.",
                "Ask Upwardor which OpenDC PO this belongs to, or whether it is still an unconverted quote.",
                None,
                rows,
                sord,
            )
            continue
        matched.add(po.get("po_number"))
        if _received(po):
            add(
                "received_still_open",
                f"{po.get('po_number')} is received in Business Central and Upwardor still has it open"
                + (f" as {sord}" if sord else "")
                + ".",
                "Tell Upwardor this purchase order is received so they can close it on their open-order list.",
                po,
                rows,
                sord,
            )
        we_have = _we_have_ack(po)
        they_have = bool(sord)
        if we_have and not they_have:
            add(
                "ack_we_have_they_dont",
                f"{po.get('po_number')} has acknowledgement {po.get('vendor_order_no') or po.get('ack_status')} on our side, and Upwardor's row has no S-ORD.",
                "Ask Upwardor to put the acknowledgement number on this order, or confirm the S-ORD was cancelled.",
                po,
                rows,
                sord,
            )
        elif they_have and not we_have:
            add(
                "ack_they_have_we_dont",
                f"Upwardor shows {sord} for {po.get('po_number')}, and we have no acknowledgement recorded.",
                "Record the acknowledgement on the purchase order, or confirm the S-ORD is the one we are waiting on.",
                po,
                rows,
                sord,
            )

    for po in ours:
        if not _open_on_ours(po):
            continue
        if po.get("po_number") in matched:
            continue
        sord = normalize_sord(po.get("vendor_order_no"))
        add(
            "our_open_po_missing",
            f"{po.get('po_number')} is open in Business Central"
            + (f" ({sord})" if sord else "")
            + " and it is not on Upwardor's open-order list.",
            "Ask Upwardor to confirm the order is on their book. A 'please order' email can sit as a quote and never become an S-ORD.",
            po,
            [],
            sord,
        )

    counts: Dict[str, int] = {}
    for row in exceptions:
        counts[row["type"]] = counts.get(row["type"], 0) + 1
    return {
        "exceptions": exceptions,
        "counts": counts,
        "their_row_count": len(their_rows),
        "their_group_count": len(groups),
        "our_upwardor_pos": len(ours),
        "our_open_pos": sum(1 for po in ours if _open_on_ours(po)),
        "matched_pos": len(matched),
    }


def _exception_key(row: dict) -> str:
    return f"{row.get('type')}|{row.get('po_number') or ''}|{row.get('sord') or ''}"


def compare_runs(previous: Optional[dict], current: dict) -> dict:
    if not previous:
        return {
            "previous_run_id": None,
            "previous_created_at": None,
            "new_keys": [_exception_key(row) for row in current.get("exceptions") or []],
            "cleared_keys": [],
            "new_count": len(current.get("exceptions") or []),
            "cleared_count": 0,
        }
    old_rows = previous.get("exceptions") or []
    new_rows = current.get("exceptions") or []
    old_keys = {_exception_key(row) for row in old_rows}
    new_keys = {_exception_key(row) for row in new_rows}
    fresh = sorted(new_keys - old_keys)
    cleared = sorted(old_keys - new_keys)
    return {
        "previous_run_id": previous.get("id"),
        "previous_created_at": previous.get("created_at"),
        "new_keys": fresh,
        "cleared_keys": cleared,
        "new_count": len(fresh),
        "cleared_count": len(cleared),
    }


def our_pos_from_tracker(db: Session) -> List[dict]:
    rows = []
    for po in db.query(OpsTrackedPo).all():
        if not _is_upwardor(po.vendor_number, po.vendor_name):
            continue
        rows.append({
            "po_number": po.po_number,
            "vendor_number": po.vendor_number,
            "vendor_name": po.vendor_name,
            "status": po.status,
            "lifecycle": po.lifecycle,
            "bc_open": po.bc_open,
            "fully_received": po.fully_received,
            "receipt_date": po.receipt_date.isoformat() if po.receipt_date else None,
            "ack_status": po.ack_status,
            "vendor_order_no": po.vendor_order_no,
            "expected_date": po.expected_date.isoformat() if po.expected_date else None,
            "so_numbers": po.so_numbers_json or [],
        })
    return rows


def _run_dict(row: UpwardorReconRun, include_rows: bool) -> dict:
    payload = {
        "id": row.id,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "created_by_email": row.created_by_email,
        "source": row.source,
        "filename": row.filename,
        "column_map": row.column_map_json or {},
        "row_count": row.row_count,
        "summary": row.summary_json or {},
        "comparison": row.comparison_json or {},
        "previous_run_id": row.previous_run_id,
    }
    if include_rows:
        payload["exceptions"] = row.exceptions_json or []
    return payload


def import_upwardor_recon(
    db: Session,
    payload: bytes,
    *,
    filename: Optional[str],
    source: str,
    actor: Optional[Actor],
) -> dict:
    parsed = parse_open_order_payload(payload, filename)
    report = reconcile_open_orders(parsed["rows"], our_pos_from_tracker(db))
    previous_row = (
        db.query(UpwardorReconRun)
        .order_by(UpwardorReconRun.created_at.desc(), UpwardorReconRun.id.desc())
        .first()
    )
    previous = None
    if previous_row is not None:
        previous = {
            "id": previous_row.id,
            "created_at": previous_row.created_at.isoformat() if previous_row.created_at else None,
            "exceptions": previous_row.exceptions_json or [],
        }
    comparison = compare_runs(previous, report)
    now = datetime.utcnow()
    row = UpwardorReconRun(
        created_at=now,
        created_by_user_id=actor.user_id if actor else None,
        created_by_email=actor.email if actor else None,
        source=source,
        filename=(filename or "").strip() or None,
        column_map_json=parsed["column_map"],
        row_count=len(parsed["rows"]),
        exceptions_json=report["exceptions"],
        summary_json={key: value for key, value in report.items() if key != "exceptions"},
        comparison_json=comparison,
        previous_run_id=previous["id"] if previous else None,
    )
    db.add(row)
    db.flush()
    body = _run_dict(row, include_rows=True)
    body["guide"] = COLUMN_GUIDE
    body["runs"] = list_runs(db)["runs"]
    return body


def list_runs(db: Session) -> dict:
    rows = (
        db.query(UpwardorReconRun)
        .order_by(UpwardorReconRun.created_at.desc(), UpwardorReconRun.id.desc())
        .limit(30)
        .all()
    )
    return {"guide": COLUMN_GUIDE, "runs": [_run_dict(row, include_rows=False) for row in rows]}


def get_run(db: Session, run_id: int) -> dict:
    row = db.query(UpwardorReconRun).filter(UpwardorReconRun.id == run_id).one_or_none()
    if row is None:
        raise OpsTrackerError("Reconciliation run not found.", status=404)
    body = _run_dict(row, include_rows=True)
    body["guide"] = COLUMN_GUIDE
    return body
