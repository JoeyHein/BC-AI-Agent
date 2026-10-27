"""Buy Panorama polycarbonate as whole sheets, sized from the door.

Joey, 2026-10-27: a Panorama sheet is 4' tall and as long as the door's
nominal width. A 14'2" door takes 14' sheets. A 16'2" door takes 16'
sheets. Extra inches do not bump the length to the next sheet. Sheets
per door = ceil(door height / 4'). Door count on the sales-order header
multiplies that.

Quote coverage stays width × height square feet (see
``PartNumberService._panorama_polycarbonate_sqft``). This module only
changes what the purchase order buys.

Sheet length maps to a BC item number. The map below is 3-wall clear.
A length with no item (14' today) is a warning. A longer sheet is not
substituted. Other colors have no sheet map, so their glazing-kit line
stays on the PO and a warning says clear sheet was not substituted.
"""

from __future__ import annotations

import logging
import re
from collections import defaultdict
from typing import Callable, Dict, List, Optional, Tuple

from app.services.part_number_service import GK17_POLYCARBONATE

logger = logging.getLogger(__name__)

# 4' sheet height. ceil(door height / 4') == ceil(height_in / 48).
SHEET_HEIGHT_IN = 48

# Nominal length in feet → BC item. Add a key only when that item exists.
# 14' is absent on purpose: there is no 14' clear sheet in BC yet.
PANORAMA_SHEET_ITEMS: Dict[str, Dict[int, dict]] = {
    "CLEAR": {
        10: {
            "item_no": "GL12-00025-00",
            "description": "POLYCARBONATE SHEET, 3-WALL CLEAR, 10' x 4'",
        },
        12: {
            "item_no": "GL12-00028-00",
            "description": "POLYCARBONATE SHEET, 3-WALL CLEAR, 12' x 4'",
        },
        16: {
            "item_no": "GL12-00026-00",
            "description": "POLYCARBONATE SHEET, 3-WALL CLEAR, 16' x 4'",
        },
        18: {
            "item_no": "GL12-00027-00",
            "description": "POLYCARBONATE SHEET, 3-WALL CLEAR, 18' x 4'",
        },
    },
}

_POLY_COLOR_BY_ITEM = {
    pn.upper(): color for color, (pn, _desc) in GK17_POLYCARBONATE.items()
}

# "(1) 14'2\" x 16'0\" PANORAMA, CLEAR ANODIZED, ..."
_DOOR_RE = re.compile(
    r'^\((\d+)\)\s+(\d+)\'(\d+)"\s*x\s*(\d+)\'(\d+)"\s+([^,\s]+)'
)

NetNeed = Callable[[str, float], Tuple[float, float]]


def panorama_sheet_item_numbers() -> set:
    """BC item numbers this policy purchases on purpose."""
    numbers = set()
    for lengths in PANORAMA_SHEET_ITEMS.values():
        for spec in lengths.values():
            numbers.add(spec["item_no"])
    return numbers


def is_panorama_polycarbonate_item(item_no: str) -> bool:
    """GK17 polycarbonate glazing kits (the quote/SO coverage line)."""
    item = (item_no or "").upper()
    return item in _POLY_COLOR_BY_ITEM or item.startswith("GK17-25")


def polycarbonate_color(item_no: str) -> Optional[str]:
    return _POLY_COLOR_BY_ITEM.get((item_no or "").upper())


def parse_door_header(label: str) -> Optional[dict]:
    """Door count, size in inches, and series from a configurator header."""
    match = _DOOR_RE.match((label or "").strip())
    if not match:
        return None
    count, w_ft, w_in, h_ft, h_in, series = match.groups()
    width_ft = int(w_ft)
    width_extra = int(w_in)
    height_ft = int(h_ft)
    height_extra = int(h_in)
    return {
        "door_count": int(count),
        "width_in": width_ft * 12 + width_extra,
        "height_in": height_ft * 12 + height_extra,
        "series": series.upper(),
    }


def nominal_sheet_length_ft(width_in: int) -> int:
    """Whole feet of the door width. Leftover inches do not size up."""
    if width_in <= 0:
        return 0
    return int(width_in) // 12


def sheets_per_door(height_in: int) -> int:
    """ceil(door height / 4')."""
    if height_in <= 0:
        return 0
    return (int(height_in) + SHEET_HEIGHT_IN - 1) // SHEET_HEIGHT_IN


def _size_label(width_in: int, height_in: int) -> str:
    w_ft, w_in = divmod(int(width_in), 12)
    h_ft, h_in = divmod(int(height_in), 12)
    return f"{w_ft}'{w_in}\" x {h_ft}'{h_in}\""


def _clip_comment(text: str) -> str:
    # BC comment lines reject anything over 100 characters.
    return text[:100]


def panorama_sheet_order(
    width_in: int,
    height_in: int,
    door_count: int = 1,
    color: str = "CLEAR",
) -> dict:
    """Sheet decision for one Panorama door size.

    ``item_no`` is None when nothing in ``PANORAMA_SHEET_ITEMS`` matches.
    ``warning`` is set in that case. ``convert`` is true when the glazing-kit
    line should come off the PO (clear sheets, whether or not the length
    has an item). Unmapped colors keep the kit line.
    """
    color_key = (color or "CLEAR").upper()
    count = max(int(door_count or 0), 0)
    length_ft = nominal_sheet_length_ft(width_in)
    per_door = sheets_per_door(height_in)
    sheet_count = per_door * count
    size = _size_label(width_in, height_in)
    base = {
        "length_ft": length_ft,
        "sheets_per_door": per_door,
        "sheet_count": sheet_count,
        "door_count": count,
        "width_in": int(width_in or 0),
        "height_in": int(height_in or 0),
        "color": color_key,
        "item_no": None,
        "description": None,
        "warning": None,
        "po_comment": None,
        "code": None,
        "convert": False,
    }
    if count <= 0 or length_ft <= 0 or per_door <= 0:
        return base

    color_map = PANORAMA_SHEET_ITEMS.get(color_key)
    if color_map is None:
        label = color_key.replace("_", " ").title()
        message = (
            f"Panorama door {size} needs {sheet_count} x {length_ft}' "
            f"polycarbonate sheets. No sheet items are configured for {label}. "
            f"The glazing kit line stays on the PO. Clear sheets were not substituted."
        )
        base.update({
            "warning": message,
            "po_comment": _clip_comment(
                f"PANORAMA SHEET: {sheet_count} x {length_ft}' {label} "
                f"- no sheet item, kit line kept"
            ),
            "code": "panorama_sheet_color_unmapped",
            "convert": False,
        })
        return base

    spec = color_map.get(length_ft)
    if spec is None:
        message = (
            f"Panorama door {size} needs {sheet_count} x {length_ft}' "
            f"polycarbonate sheets. No BC item is mapped for {length_ft}'. "
            f"Not substituted with a longer sheet."
        )
        base.update({
            "warning": message,
            "po_comment": _clip_comment(
                f"PANORAMA SHEET: {sheet_count} x {length_ft}' for {size} "
                f"- no BC item, not sized up"
            ),
            "code": "panorama_sheet_item_missing",
            "convert": True,
        })
        return base

    base.update({
        "item_no": spec["item_no"],
        "description": spec["description"],
        "convert": True,
    })
    return base


def _gk_items_for_door(door_item_qty: Dict[str, Dict[int, float]], door_idx: int) -> List[str]:
    found = []
    for item, by_door in door_item_qty.items():
        if is_panorama_polycarbonate_item(item) and float(by_door.get(door_idx) or 0) > 0:
            found.append(item)
    return found


def _positive_doors(door_qty: Dict[int, float]) -> List[int]:
    return [d for d, qty in door_qty.items() if float(qty or 0) > 0]


def _strip_purchase_rows(
    rows: List[dict],
    strip_doors_by_item: Dict[str, set],
    door_qty_snapshot: Dict[str, Dict[int, float]],
) -> List[dict]:
    """Drop Panorama glazing-kit quantity that is being replaced by sheets.

    Stock already netted into ``quantity`` stays with the doors that are
    not converted. Those doors keep max(0, their sales-order qty minus the
    stock this row already consumed).
    """
    kept: List[dict] = []
    for row in rows:
        item = row.get("item_no")
        strip_doors = strip_doors_by_item.get(item or "")
        if not strip_doors:
            kept.append(row)
            continue
        door_qty = door_qty_snapshot.get(item, {})
        if row.get("doors"):
            doors = list(row["doors"])
            total_so = sum(float(door_qty.get(door_idx) or 0) for door_idx in doors)
            remain_doors = [door_idx for door_idx in doors if door_idx not in strip_doors]
            remain_so = sum(float(door_qty.get(door_idx) or 0) for door_idx in remain_doors)
            purchased = float(row.get("quantity") or 0)
            stock_used = max(0.0, total_so - purchased)
            keep = round(max(0.0, remain_so - stock_used), 2)
            if keep <= 0 or not remain_doors:
                continue
            updated = dict(row)
            updated["doors"] = remain_doors
            updated["quantity"] = keep
            kept.append(updated)
            continue

        positive = _positive_doors(door_qty)
        if positive and all(door_idx in strip_doors for door_idx in positive):
            continue
        stripped_so = sum(float(door_qty.get(door_idx) or 0) for door_idx in strip_doors)
        total_so = sum(float(qty or 0) for qty in door_qty.values())
        updated = dict(row)
        if "ordered_qty" in updated:
            updated["ordered_qty"] = round(max(0.0, float(updated["ordered_qty"]) - stripped_so), 2)
        if total_so > 0 and "net_qty" in updated:
            remain_so = max(0.0, total_so - stripped_so)
            updated["net_qty"] = round(float(updated["net_qty"]) * (remain_so / total_so), 2)
        if updated.get("ordered_qty", 1) <= 0 and updated.get("net_qty", 1) <= 0:
            continue
        kept.append(updated)
    return kept


def _allocate_purchases(
    decisions: List[dict],
    net_need: Optional[NetNeed],
) -> Dict[int, float]:
    """Purchase qty per door index. Stock covers earlier doors first."""
    by_item: Dict[str, List[dict]] = defaultdict(list)
    for decision in decisions:
        if decision.get("item_no"):
            by_item[decision["item_no"]].append(decision)
    purchase: Dict[int, float] = {}
    for item_no, group in by_item.items():
        total = float(sum(d["sheet_count"] for d in group))
        if net_need is None:
            covered = 0.0
        else:
            _avail, net = net_need(item_no, total)
            covered = max(0.0, total - float(net))
        for decision in sorted(group, key=lambda d: d["door_index"]):
            take = min(covered, float(decision["sheet_count"]))
            covered = round(covered - take, 4)
            purchase[decision["door_index"]] = round(float(decision["sheet_count"]) - take, 2)
    return purchase


def replace_panorama_polycarbonate(
    door_labels: Dict[int, str],
    door_item_qty: Dict[str, Dict[int, float]],
    included: List[dict],
    excluded_in_stock: Optional[List[dict]] = None,
    trimmed: Optional[List[dict]] = None,
    net_need: Optional[NetNeed] = None,
) -> dict:
    """Swap Panorama GK17 polycarbonate buys for per-sheet lines.

    ``door_item_qty`` is updated so a removed kit is not grouped back onto
    the door. ``net_need(item_no, qty) -> (avail, net_qty)`` is the stock
    rule from the netted planner. Omit it to buy the full sheet count.
    """
    excluded_in_stock = list(excluded_in_stock or [])
    trimmed = list(trimmed or [])
    included = list(included)

    decisions: List[dict] = []
    for door_idx in sorted(door_labels):
        parsed = parse_door_header(door_labels[door_idx])
        if not parsed or parsed["series"] != "PANORAMA":
            continue
        gk_items = _gk_items_for_door(door_item_qty, door_idx)
        if not gk_items:
            continue
        colors = {polycarbonate_color(item) for item in gk_items}
        if colors == {"CLEAR"}:
            color = "CLEAR"
        elif len(colors) == 1:
            color = next(iter(colors)) or "UNKNOWN"
        else:
            color = "UNKNOWN"
        order = panorama_sheet_order(
            parsed["width_in"], parsed["height_in"], parsed["door_count"], color,
        )
        order["door_index"] = door_idx
        order["door_label"] = door_labels[door_idx]
        order["gk_items"] = gk_items
        decisions.append(order)

    strip_doors_by_item: Dict[str, set] = defaultdict(set)
    for decision in decisions:
        if not decision["convert"]:
            continue
        for item in decision["gk_items"]:
            strip_doors_by_item[item].add(decision["door_index"])

    door_qty_snapshot = {
        item: dict(by_door) for item, by_door in door_item_qty.items()
    }
    if strip_doors_by_item:
        included = _strip_purchase_rows(included, strip_doors_by_item, door_qty_snapshot)
        excluded_in_stock = _strip_purchase_rows(
            excluded_in_stock, strip_doors_by_item, door_qty_snapshot,
        )
        trimmed = _strip_purchase_rows(trimmed, strip_doors_by_item, door_qty_snapshot)
        for item, doors in strip_doors_by_item.items():
            by_door = door_item_qty.get(item)
            if not by_door:
                continue
            for door_idx in doors:
                if door_idx in by_door:
                    by_door[door_idx] = 0

    purchasable = [d for d in decisions if d.get("item_no")]
    purchase_qty = _allocate_purchases(purchasable, net_need)

    warnings: List[dict] = []
    panorama_sheets: List[dict] = []
    for decision in decisions:
        bought = purchase_qty.get(decision["door_index"], 0) if decision.get("item_no") else 0
        record = {
            "door_index": decision["door_index"],
            "door_label": decision.get("door_label"),
            "door_count": decision["door_count"],
            "width_in": decision["width_in"],
            "height_in": decision["height_in"],
            "length_ft": decision["length_ft"],
            "sheets_per_door": decision["sheets_per_door"],
            "sheet_count": decision["sheet_count"],
            "color": decision["color"],
            "item_no": decision.get("item_no"),
            "description": decision.get("description"),
            "purchase_qty": bought,
            "warning": decision.get("warning"),
        }
        panorama_sheets.append(record)
        if decision.get("warning"):
            warning = {
                "code": decision.get("code"),
                "door_index": decision["door_index"],
                "door_label": decision.get("door_label"),
                "length_ft": decision["length_ft"],
                "sheet_count": decision["sheet_count"],
                "item_no": decision.get("item_no"),
                "message": decision["warning"],
                "po_comment": decision.get("po_comment"),
            }
            warnings.append(warning)
            logger.warning("Panorama sheet purchase: %s", decision["warning"])
            continue
        if not decision.get("item_no"):
            continue
        description = decision["description"]
        door_idx = decision["door_index"]
        if bought <= 0:
            excluded_in_stock.append({
                "item_no": decision["item_no"],
                "description": description,
                "ordered_qty": decision["sheet_count"],
                "net_qty": 0,
                "avail": decision["sheet_count"],
                "doors": [door_idx],
            })
            continue
        included.append({
            "item_no": decision["item_no"],
            "description": description,
            "quantity": bought,
            "unit_cost": None,
            "uom": "EA",
            "doors": [door_idx],
            "length_ft": decision["length_ft"],
        })
        if bought < decision["sheet_count"]:
            trimmed.append({
                "item_no": decision["item_no"],
                "description": description,
                "ordered_qty": decision["sheet_count"],
                "net_qty": bought,
                "doors": [door_idx],
            })

    return {
        "included": included,
        "excluded_in_stock": excluded_in_stock,
        "trimmed": trimmed,
        "warnings": warnings,
        "panorama_sheets": panorama_sheets,
    }
