"""Panels-first purchase-order line order (Joey's rule).

Within each door group on a PO, insulated sections come first, glass
sections and glazing next, then the rest of that door (hardware kits,
struts, retainer/astragal, tracks, springs, and so on). A comment that
introduces the group — the configurator door header, or a section banner
such as "ITEMS SHARED…" — stays at the top of that group. Comments that
sit between items stay with the following item, so a note like
"Five wall required" does not jump into the panel block on its own.

Classification is by item-number prefix, using the same families
``part_number_service`` / ``sku_geometry`` already use:

* Insulated sections — residential ``PN65`` / ``PN95`` and the commercial
  section prefixes in ``sku_geometry.COMMERCIAL_PANEL_PREFIXES``
  (``PN45`` / ``PN46`` TX450, ``PN55`` / ``PN56`` TX500, ``PN35`` TX380,
  ``PN65`` is residential, and the other finished-section prefixes in
  that set). ``PN40`` and ``PN50`` are bulk cores left behind when a
  section BOM is exploded, not the section line, so they stay with the
  rest of the door.
* Glass — full-view / aluminum sections ``PN10`` / ``PN12`` (V130G /
  V230G), ``PN97`` (AL976), ``PN80`` (Panorama), ``PN20`` (Solalite),
  ``PN70`` (AL-SWD), plus glazing ``GK15`` / ``GK16`` / ``GK17`` and
  glass sheet ``GL12`` / ``GL17`` / ``GL18``.
* Everything else — ``HK`` hardware, ``FH`` struts, ``PL`` retainer and
  astragal, ``TR`` track, ``SP`` springs, comments that are not group
  headers, and so on.

Door groups start at the same ``(1) 18'0" x 8'0" …`` comment the sales
order writer detects (``so_po_generation_service._DOOR_HEADER_RE``), or
at the shared / raw-material banners ``_write_plan_lines`` inserts.
Lines before the first banner are their own group, so the customer name
and "Built from SO-…" comments stay above door 1.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional, Sequence

from app.services.sku_geometry import (
    ALUMINUM_PANEL_PREFIXES,
    COMMERCIAL_PANEL_PREFIXES,
    RESIDENTIAL_PANEL_PREFIXES,
)

# Same shape as so_po_generation_service._DOOR_HEADER_RE. Kept in sync by
# test_po_line_order.test_door_header_regex_matches_so_writer.
DOOR_HEADER_RE = re.compile(r'^\(\d+\)\s+\d+\'\d+"\s*x\s*\d+\'\d+"')

# Bulk cores, not the finished insulated section. See purchasing demand
# leftovers: PN45/PN46 explode to a PN40 core.
_BULK_CORE_PREFIXES = frozenset({"PN40", "PN50"})

INSULATED_SECTION_PREFIXES = frozenset(
    (RESIDENTIAL_PANEL_PREFIXES | COMMERCIAL_PANEL_PREFIXES) - _BULK_CORE_PREFIXES
)

# Aluminum / full-view sections from sku_geometry plus the other aluminum
# section families part_number_service._get_aluminum_section_parts builds.
GLASS_SECTION_PREFIXES = frozenset(ALUMINUM_PANEL_PREFIXES | {"PN80", "PN20", "PN70"})

GLAZING_PREFIXES = frozenset({"GK15", "GK16", "GK17", "GL12", "GL17", "GL18"})

PANEL_INSULATED = "insulated"
PANEL_GLASS = "glass"
PANEL_REST = "rest"
PANEL_COMMENT = "comment"

_BAND_ORDER = (PANEL_INSULATED, PANEL_GLASS, PANEL_REST)

BC_DESCRIPTION_MAX = 100


def _item_number(line: Dict[str, Any]) -> str:
    raw = line.get("lineObjectNumber")
    if raw is None:
        raw = line.get("item_no") or line.get("item_number") or ""
    return str(raw or "").strip()


def _description(line: Dict[str, Any]) -> str:
    return str(line.get("description") or "").strip()


def _line_type(line: Dict[str, Any]) -> str:
    raw = line.get("lineType")
    if raw is None:
        raw = line.get("line_type")
    return str(raw or "").strip()


def is_comment_line(line: Dict[str, Any]) -> bool:
    """True for a BC Comment line or a generate-po request line typed blank/comment."""
    raw = line.get("lineType")
    if raw is None:
        raw = line.get("line_type")
    if raw is None:
        return False
    return str(raw).strip().lower() in ("", "comment", "blank")


def _prefix_match(item: str, prefixes: Iterable[str]) -> bool:
    """True when ``item`` is exactly ``prefix`` or ``prefix`` plus a non-alphanumeric boundary.

    ``PN45-24400-0900`` matches ``PN45``. ``PN4500`` does not.
    """
    item = (item or "").upper().strip()
    if not item:
        return False
    for prefix in prefixes:
        p = prefix.upper()
        if not item.startswith(p):
            continue
        rest = item[len(p):]
        if rest == "" or not rest[0].isalnum():
            return True
    return False


def classify_item(item_no: Optional[str], description: str = "") -> str:
    """``insulated``, ``glass``, or ``rest`` for one item number.

    ``description`` is accepted so callers can pass the BC line through
    unchanged. The class comes from the item prefix, not the description
    text — a hardware line whose description mentions "panel" stays rest.
    """
    del description  # prefix-only; kept so call sites can pass the line text
    item = (item_no or "").strip()
    if _prefix_match(item, INSULATED_SECTION_PREFIXES):
        return PANEL_INSULATED
    if _prefix_match(item, GLASS_SECTION_PREFIXES) or _prefix_match(item, GLAZING_PREFIXES):
        return PANEL_GLASS
    return PANEL_REST


def classify_line(line: Dict[str, Any]) -> str:
    if is_comment_line(line) or _line_type(line).lower() == "comment":
        return PANEL_COMMENT
    return classify_item(_item_number(line), _description(line))


def _is_group_start(line: Dict[str, Any]) -> bool:
    if not (is_comment_line(line) or _line_type(line).lower() == "comment"):
        return False
    desc = _description(line)
    if DOOR_HEADER_RE.match(desc):
        return True
    upper = desc.upper()
    if upper.startswith("ITEMS SHARED ACROSS"):
        return True
    if upper.startswith("RAW MATERIALS"):
        return True
    return False


def _sorted_by_sequence(lines: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return sorted(lines, key=lambda ln: (ln.get("sequence") is None, ln.get("sequence") or 0))


def _split_groups(lines: Sequence[Dict[str, Any]]) -> List[List[Dict[str, Any]]]:
    groups: List[List[Dict[str, Any]]] = []
    current: List[Dict[str, Any]] = []
    for line in lines:
        if _is_group_start(line) and current:
            groups.append(current)
            current = [line]
        else:
            current.append(line)
    if current:
        groups.append(current)
    return groups


def _order_group(lines: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Introducer comments, then insulated, glass, rest. Stable inside each band."""
    intro: List[Dict[str, Any]] = []
    idx = 0
    while idx < len(lines) and (is_comment_line(lines[idx]) or _line_type(lines[idx]).lower() == "comment"):
        intro.append(lines[idx])
        idx += 1

    bands: Dict[str, List[Dict[str, Any]]] = {name: [] for name in _BAND_ORDER}
    pending: List[Dict[str, Any]] = []
    for line in lines[idx:]:
        if is_comment_line(line) or _line_type(line).lower() == "comment":
            pending.append(line)
            continue
        band = classify_line(line)
        if band not in bands:
            band = PANEL_REST
        bands[band].extend(pending)
        bands[band].append(line)
        pending = []
    bands[PANEL_REST].extend(pending)

    ordered = list(intro)
    for name in _BAND_ORDER:
        ordered.extend(bands[name])
    return ordered


def order_po_lines(lines: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Return ``lines`` in panels-first order. Does not mutate the input.

    Accepts BC purchase-order lines (``lineType``, ``lineObjectNumber``,
    ``sequence``) or generate-po request rows (``line_type``, ``item_no``).
    Sequence is used only to establish the starting order. Lines with no
    sequence keep their relative input order (sorted as 0, stable).
    """
    indexed = []
    for i, line in enumerate(lines):
        copied = dict(line)
        if copied.get("sequence") is None:
            copied["sequence"] = i
        indexed.append(copied)
    sequenced = _sorted_by_sequence(indexed)
    ordered: List[Dict[str, Any]] = []
    for group in _split_groups(sequenced):
        ordered.extend(_order_group(group))
    return ordered


def order_item_rows(rows: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Panels-first order for SO→PO item dicts (``item_no``, ``description``)."""
    wrapped = [{
        "lineType": "Item",
        "lineObjectNumber": row.get("item_no") or "",
        "description": row.get("description") or "",
        "sequence": i,
        "_src": row,
    } for i, row in enumerate(rows)]
    return [line["_src"] for line in order_po_lines(wrapped)]


def order_request_lines(lines: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Panels-first order for generate-po request rows, including comment lines."""
    wrapped = []
    for i, row in enumerate(lines):
        comment = is_comment_line(row)
        wrapped.append({
            "lineType": "Comment" if comment else "Item",
            "line_type": "Comment" if comment else "Item",
            "lineObjectNumber": "" if comment else (row.get("item_no") or ""),
            "description": row.get("description") or "",
            "sequence": i,
            "_src": row,
        })
    return [line["_src"] for line in order_po_lines(wrapped)]


def same_line_order(left: Sequence[Dict[str, Any]], right: Sequence[Dict[str, Any]]) -> bool:
    """True when both sequences carry the same BC line ids in the same order."""
    return [ln.get("id") for ln in left] == [ln.get("id") for ln in right]
