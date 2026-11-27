"""Customer-facing quote lines.

Dealers see one row per door package (description, door quantity, package
total), plus any line that is not part of a package (a separately ordered
part, an operator, freight). Component rows, unit prices, part numbers,
and internal notes stay on the staff quote. They are removed before a
customer response or a customer PDF is built.
"""

from __future__ import annotations

import re
from typing import Optional

from fpdf import FPDF
from fpdf.enums import XPos, YPos

from app.services.quote_adjustments import FREIGHT_ESTIMATE_LABEL, FREIGHT_ESTIMATE_NOTE, is_freight_note_text
from app.services.quote_line_layout import is_operator_rail

_DOOR_QTY = re.compile(r"^\(\s*(\d+)\s*\)")
_HOIST_PARTS = frozenset({"SP12-00084-00", "FH12-00190-00"})
_HIDDEN_KEYS = frozenset({
    "part_number",
    "item_number",
    "lineObjectNumber",
    "unit_price",
    "unitPrice",
    "line_amount",
    "lineAmount",
    "pricing_flag",
    "customer_group",
    "unpriced",
    "held_for_review",
    "id",
    "item_id",
    "line_number",
    "sequence",
    "_output",
})


def _text(value) -> str:
    return str(value or "").strip()


def _part_number(row: dict, source: Optional[dict] = None) -> str:
    source = source or {}
    return _text(
        row.get("part_number")
        or row.get("lineObjectNumber")
        or row.get("item_number")
        or source.get("part_number")
        or source.get("lineObjectNumber")
        or source.get("item_number")
    ).upper()


def _line_type(row: dict, source: Optional[dict] = None) -> str:
    source = source or {}
    return _text(row.get("line_type") or row.get("lineType") or source.get("lineType") or source.get("line_type"))


def _description(row: dict, source: Optional[dict] = None) -> str:
    source = source or {}
    return _text(row.get("description") or source.get("description"))


def _money(value) -> float:
    if value is None or isinstance(value, bool):
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _quantity(row: dict):
    quantity = row.get("quantity")
    if quantity is None:
        return 1
    return quantity


def line_amount(row: dict) -> float:
    """Extended price already on the row. Unit price is only a fallback."""
    if row.get("line_total") is not None:
        return round(_money(row.get("line_total")), 2)
    for key in ("line_amount", "lineAmount", "netAmount"):
        if row.get(key) is not None:
            return round(_money(row.get(key)), 2)
    unit = row.get("unit_price")
    if unit is None:
        unit = row.get("unitPrice")
    if unit is None:
        return 0.0
    quantity = _money(_quantity(row) or 1)
    return round(_money(unit) * quantity, 2)


def door_quantity(description: str) -> int:
    match = _DOOR_QTY.match(_text(description))
    if not match:
        return 1
    return int(match.group(1))


def _is_door_header(description: str, source: Optional[dict] = None) -> bool:
    source = source or {}
    if source.get("is_door_desc"):
        return True
    return bool(_DOOR_QTY.match(_text(description)))


def _is_operator_line(row: dict, source: Optional[dict] = None) -> bool:
    source = source or {}
    if _text(source.get("category") or row.get("category")).lower() == "operator":
        return True
    part = _part_number(row, source)
    if part.startswith("OP") or part in _HOIST_PARTS:
        return True
    return is_operator_rail({
        "part_number": part,
        "description": _description(row, source),
    })


def customer_group_for(row: dict, source: Optional[dict], state: dict) -> str:
    """Classify one pricing row. ``state['in_package']`` tracks the open door."""
    source = source or {}
    description = _description(row, source)
    kind = _line_type(row, source)
    part = _part_number(row, source)
    if row.get("is_freight_note") or source.get("is_freight_note") or is_freight_note_text(description):
        return "freight_note"
    if source.get("is_door_freight") or part == "FREIGHT" or _text(source.get("category")).lower() == "freight":
        state["in_package"] = False
        return "freight"
    if part == "INSTALLATION":
        state["in_package"] = False
        return "standalone"
    if _is_door_header(description, source):
        state["in_package"] = True
        return "package_header"
    if (
        row.get("held_for_review")
        or row.get("unpriced")
        or source.get("is_note")
        or kind.lower() == "note"
        or kind.lower() == "comment"
    ):
        return "note"
    if _is_operator_line(row, source) or (row.get("_output") and kind.lower() == "item"):
        return "standalone"
    if state.get("in_package"):
        return "package_component"
    return "standalone"


def annotate_customer_groups(line_pricing, sources) -> None:
    """Tag pricing rows in place. Staff snapshots keep every component row."""
    state = {"in_package": False}
    sources = list(sources or [])
    for index, row in enumerate(line_pricing or []):
        if not isinstance(row, dict):
            continue
        source = sources[index] if index < len(sources) else row
        row["customer_group"] = customer_group_for(row, source, state)


def _package_row(description: str, total: float) -> dict:
    return {
        "line_type": "Package",
        "description": description,
        "quantity": door_quantity(description),
        "line_total": round(total, 2),
    }


def _standalone_row(row: dict) -> dict:
    description = _description(row) or _part_number(row)
    return {
        "line_type": "Item",
        "description": description,
        "quantity": _quantity(row),
        "line_total": line_amount(row),
    }


def _freight_row(row: dict) -> dict:
    return {
        "line_type": "Freight",
        "description": FREIGHT_ESTIMATE_LABEL,
        "quantity": 1,
        "line_total": line_amount(row),
    }


def collapse_customer_line_pricing(lines, output_by_sequence=None) -> list:
    """One package row per door. Component lines and internal notes are dropped."""
    prepared = []
    for line in lines or []:
        if not isinstance(line, dict):
            continue
        row = dict(line)
        sequence = row.get("sequence")
        if output_by_sequence and sequence is not None and output_by_sequence.get(sequence):
            row["_output"] = True
        prepared.append(row)
    if any(not row.get("customer_group") for row in prepared):
        annotate_customer_groups(prepared, prepared)

    visible = []
    package = None
    buffered = []

    def flush_package():
        nonlocal package, buffered
        if package is not None:
            visible.append(_package_row(package["description"], package["total"]))
            package = None
        visible.extend(buffered)
        buffered = []

    for row in prepared:
        group = row.get("customer_group")
        if group == "package_header":
            flush_package()
            package = {"description": _description(row), "total": 0.0}
        elif group == "package_component":
            if package is None:
                visible.append(_standalone_row(row))
            else:
                package["total"] += line_amount(row)
        elif group in ("note", "freight_note"):
            continue
        elif group == "freight":
            flush_package()
            visible.append(_freight_row(row))
        else:
            item = _standalone_row(row)
            if package is None:
                visible.append(item)
            else:
                buffered.append(item)
    flush_package()
    return visible


def present_door_results(rows):
    """Door success and the description the customer already sees. No part counts."""
    if not isinstance(rows, list):
        return rows
    cleaned = []
    for row in rows:
        if not isinstance(row, dict):
            cleaned.append(row)
            continue
        cleaned.append({
            "door_index": row.get("door_index"),
            "door_description": row.get("door_description"),
            "success": row.get("success"),
            "error": row.get("error"),
        })
    return cleaned


def present_customer_pricing(result: dict) -> dict:
    """Copy a pricing payload and remove component-line data."""
    if not isinstance(result, dict):
        return result
    out = dict(result)
    out["line_pricing"] = collapse_customer_line_pricing(result.get("line_pricing"))
    if "door_results" in out:
        out["door_results"] = present_door_results(out.get("door_results"))
    out.pop("lines_failed", None)
    out.pop("price_override_warnings", None)
    out.pop("escalating_margin", None)
    return out


def _pdf_text(value) -> str:
    text = _text(value)
    return text.encode("latin-1", "replace").decode("latin-1")


def _money_label(amount) -> str:
    return f"${_money(amount):,.2f}"


def build_customer_quote_pdf(quote: dict, lines, output_by_sequence=None) -> bytes:
    """Quote PDF a customer can download or receive. Packages and totals only."""
    quote = quote or {}
    visible = collapse_customer_line_pricing(lines, output_by_sequence=output_by_sequence)
    number = _text(quote.get("number") or quote.get("bc_quote_number")) or "Quote"
    customer = _text(quote.get("customerName") or quote.get("customer_name"))
    document_date = _text(quote.get("documentDate") or quote.get("document_date"))
    subtotal = quote.get("totalAmountExcludingTax")
    if subtotal is None:
        subtotal = (quote.get("pricing") or {}).get("subtotal")
    total = quote.get("totalAmountIncludingTax")
    if total is None:
        total = (quote.get("pricing") or {}).get("total")
    tax = quote.get("tax")
    if tax is None and isinstance(quote.get("pricing"), dict):
        tax = quote["pricing"].get("tax")
    if tax is None and subtotal is not None and total is not None:
        tax = round(_money(total) - _money(subtotal), 2)
    if subtotal is None:
        subtotal = round(sum(line_amount(row) for row in visible), 2)
    if tax is None:
        tax = 0.0
    if total is None:
        total = round(_money(subtotal) + _money(tax), 2)

    pdf = FPDF(format="Letter")
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.add_page()
    pdf.set_fill_color(12, 35, 64)
    pdf.rect(0, 0, 216, 28, "F")
    pdf.set_xy(12, 6)
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 8, "Open Distribution Company Inc.", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_x(12)
    pdf.set_font("Helvetica", size=10)
    pdf.cell(0, 5, "Quote", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(12)
    pdf.set_text_color(12, 35, 64)
    pdf.set_font("Helvetica", "B", 14)
    pdf.cell(0, 8, _pdf_text(f"Quote {number}"), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_text_color(0, 0, 0)
    pdf.set_font("Helvetica", size=11)
    if customer:
        pdf.cell(0, 6, _pdf_text(customer), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    if document_date:
        pdf.cell(0, 6, _pdf_text(document_date), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(4)

    pdf.set_font("Helvetica", "B", 10)
    pdf.set_fill_color(240, 244, 248)
    pdf.cell(120, 7, "Description", fill=True, new_x=XPos.RIGHT, new_y=YPos.TOP)
    pdf.cell(25, 7, "Qty", align="R", fill=True, new_x=XPos.RIGHT, new_y=YPos.TOP)
    pdf.cell(35, 7, "Total", align="R", fill=True, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_font("Helvetica", size=10)
    for row in visible:
        description = _pdf_text(row.get("description")) or "-"
        wrapped = pdf.multi_cell(120, 5, description, dry_run=True, output="LINES") or [description]
        row_height = 5 * len(wrapped)
        y = pdf.get_y()
        if y + row_height > pdf.page_break_trigger:
            pdf.add_page()
            y = pdf.get_y()
        pdf.set_xy(12, y)
        pdf.multi_cell(120, 5, description, new_x=XPos.RIGHT, new_y=YPos.TOP)
        pdf.set_xy(132, y)
        pdf.cell(25, 5, _pdf_text(row.get("quantity")), align="R", new_x=XPos.RIGHT, new_y=YPos.TOP)
        pdf.cell(35, 5, _money_label(row.get("line_total")), align="R", new_x=XPos.RIGHT, new_y=YPos.TOP)
        pdf.set_y(y + row_height + 1)
    pdf.ln(3)
    pdf.set_font("Helvetica", size=11)
    for label, amount in (("Subtotal", subtotal), ("Tax", tax)):
        pdf.cell(145, 6, label, align="R", new_x=XPos.RIGHT, new_y=YPos.TOP)
        pdf.cell(35, 6, _money_label(amount), align="R", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(145, 8, "Total", align="R", new_x=XPos.RIGHT, new_y=YPos.TOP)
    pdf.cell(35, 8, _money_label(total), align="R", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(4)
    pdf.set_font("Helvetica", "I", 9)
    pdf.set_text_color(80, 80, 80)
    pdf.multi_cell(0, 5, FREIGHT_ESTIMATE_NOTE)
    raw = pdf.output()
    return bytes(raw)


def customer_visible_keys_only(rows) -> bool:
    """True when a collapsed payload has no component price fields."""
    for row in rows or []:
        if not isinstance(row, dict):
            return False
        if row.get("line_type") not in {"Package", "Item", "Freight"}:
            return False
        if any(key in row for key in _HIDDEN_KEYS):
            return False
    return True
