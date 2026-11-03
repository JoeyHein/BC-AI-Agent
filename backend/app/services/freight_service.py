"""
Freight Service
Calculates freight charges based on province and delivery type.
Rates are percentage-based and configurable via AppSettings.
"""

import logging
from typing import Dict, Any, Optional
from sqlalchemy.orm import Session

from app.db.models import AppSettings

logger = logging.getLogger(__name__)

FREIGHT_CONFIG_KEY = "freight_config"

# BC sends full province names — map to codes for freight lookup
PROVINCE_NAME_TO_CODE = {
    "ALBERTA": "AB",
    "BRITISH COLUMBIA": "BC",
    "MANITOBA": "MB",
    "NEW BRUNSWICK": "NB",
    "NEWFOUNDLAND AND LABRADOR": "NL",
    "NORTHWEST TERRITORIES": "NT",
    "NOVA SCOTIA": "NS",
    "NUNAVUT": "NU",
    "ONTARIO": "ON",
    "PRINCE EDWARD ISLAND": "PE",
    "QUEBEC": "QC",
    "SASKATCHEWAN": "SK",
    "YUKON": "YT",
}


def get_default_freight_config() -> Dict[str, Any]:
    """Hardcoded default freight configuration."""
    return {
        "default_rate": 9.0,
        "province_overrides": {
            "AB": 7.0,
        },
        "freight_item_number": "FREIGHT",
        "fallback_to_comment": True,
    }


def get_freight_config(db: Session) -> Dict[str, Any]:
    """Load freight config from AppSettings, falling back to defaults."""
    setting = db.query(AppSettings).filter(
        AppSettings.setting_key == FREIGHT_CONFIG_KEY
    ).first()

    if setting and setting.setting_value:
        return setting.setting_value

    return get_default_freight_config()


def calculate_freight(
    product_subtotal: float,
    province: Optional[str],
    delivery_type: str,
    db: Session,
) -> Dict[str, Any]:
    """
    Calculate freight charge for a quote.

    Args:
        product_subtotal: Total of product lines (excl. tax)
        province: Customer province code (e.g. "AB", "SK", "BC")
        delivery_type: "delivery" or "pickup"
        db: Database session

    Returns:
        dict with: amount, rate, description, skip (True if pickup or zero)
    """
    if delivery_type == "pickup":
        return {
            "amount": 0,
            "rate": 0,
            "description": "Pickup - No Freight",
            "skip": True,
        }

    config = get_freight_config(db)
    default_rate = config.get("default_rate", 5.0)
    province_overrides = config.get("province_overrides", {})

    # Normalize province — BC sends full names like "Manitoba", we need codes like "MB"
    province_upper = (province or "").upper().strip()
    province_code = PROVINCE_NAME_TO_CODE.get(province_upper, province_upper)
    rate = province_overrides.get(province_code, default_rate)

    amount = round(product_subtotal * rate / 100, 2)

    # Build description
    if province_code and province_code in province_overrides:
        description = f"Freight ({rate}% - {province_code})"
    else:
        description = f"Freight ({rate}%)"

    return {
        "amount": amount,
        "rate": rate,
        "description": description,
        "skip": amount <= 0,
    }


def interleave_door_freight(lines: list, freight_item: str = "FREIGHT") -> list:
    """Place a freight placeholder immediately after each door's last line.

    Callers price the placeholder afterwards. Posted order per door is
    ``[door lines..., WRAP, FREIGHT]``. A door with no freight line (pickup,
    or a later zero amount that gets deleted) keeps WRAP as its last line.
    ``fixed_unit_price`` 0 holds the card price off the product subtotal
    until the real per-door amount is patched.
    """
    if not lines:
        return lines
    out = []
    for i, line in enumerate(lines):
        out.append(line)
        door = line.get("door_index")
        if not door:
            continue
        nxt = lines[i + 1] if i + 1 < len(lines) else None
        if nxt and nxt.get("door_index") == door:
            continue
        out.append({
            "lineType": "Item",
            "part_number": freight_item,
            "description": "Freight",
            "quantity": 1,
            "category": "freight",
            "door_index": door,
            "is_door_freight": True,
            "fixed_unit_price": 0,
        })
    return out


def allocate_freight_across_doors(door_subtotals: list, freight_total: float) -> list:
    """Split one quote freight amount across doors by product subtotal.

    Each share is rounded to the cent. The last door with product absorbs
    the rounding remainder so the shares sum to ``freight_total``.
    """
    subs = [max(0.0, float(s or 0)) for s in door_subtotals]
    target = round(float(freight_total or 0), 2)
    if not subs:
        return []
    if target <= 0 or sum(subs) <= 0:
        return [0.0] * len(subs)
    base = sum(subs)
    amounts = [round(s / base * target, 2) for s in subs]
    drift = round(target - sum(amounts), 2)
    for i in range(len(amounts) - 1, -1, -1):
        if subs[i] > 0 or i == 0:
            amounts[i] = round(amounts[i] + drift, 2)
            break
    return amounts


def sum_line_amounts(quote_lines: list, line_ids: list) -> float:
    """Sum BC quote-line amounts for the given line ids.

    Prefers netAmount. Falls back to unitPrice × quantity when netAmount
    is still zero (freight placeholders, or a line patched after the fetch
    the net amount was computed from).
    """
    by_id = {ln.get("id"): ln for ln in quote_lines or []}
    total = 0.0
    for lid in line_ids:
        ln = by_id.get(lid) or {}
        if (ln.get("lineType") or "") == "Comment":
            continue
        if (ln.get("lineObjectNumber") or "").upper() == "FREIGHT":
            continue
        price = ln.get("unitPrice")
        qty = ln.get("quantity") or 0
        if price not in (None, ""):
            total += float(price) * float(qty)
        elif ln.get("netAmount") not in (None, "", 0, 0.0):
            total += float(ln.get("netAmount"))
    return round(total, 2)


def door_freight_amounts(quote_lines: list, slots: list, door_product_ids: dict, freight_total: float) -> list:
    """Per-door freight shares for placeholders already posted under each door."""
    subs = [
        sum_line_amounts(quote_lines, door_product_ids.get(slot.get("door_index"), []))
        for slot in slots
    ]
    if sum(subs) <= 0 and freight_total and slots:
        subs = [1.0] * len(slots)
    return allocate_freight_across_doors(subs, freight_total)


def remember_added_door_line(line, added_line, door_order, door_product_ids, door_freight_slots):
    """Track product lines and per-door freight placeholders as they are posted."""
    if not isinstance(line, dict) or not added_line or not added_line.get("id"):
        return
    if line.get("is_door_freight"):
        door_freight_slots.append({
            "id": added_line["id"],
            "door_index": line.get("door_index"),
            "sequence": added_line.get("sequence"),
        })
        return
    door = line.get("door_index")
    if not door or line.get("lineType") == "Comment":
        return
    if door not in door_product_ids:
        door_order.append(door)
        door_product_ids[door] = []
    door_product_ids[door].append(added_line["id"])


def apply_freight_to_line_pricing(line_pricing: list, amounts: list, description: str) -> list:
    """Write per-door freight amounts onto FREIGHT rows, in door order.

    A zero share is dropped so that door's WRAP stays the last visible line.
    """
    fi = 0
    kept = []
    for row in line_pricing or []:
        if row.get("part_number") == "FREIGHT" and fi < len(amounts):
            amount = round(float(amounts[fi] or 0), 2)
            fi += 1
            if amount <= 0:
                continue
            row = dict(row)
            row["description"] = description or row.get("description") or "Freight"
            row["quantity"] = 1
            row["unit_price"] = amount
            row["line_total"] = amount
        kept.append(row)
    return kept
