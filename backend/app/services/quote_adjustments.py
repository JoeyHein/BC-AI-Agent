"""Staff adjustments applied when a quote is priced.

One freight charge for the whole order, optional manual freight amount,
and optional unit-price overrides. Business Central still prices every
other line from SalesPriceLists.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

FREIGHT_ESTIMATE_LABEL = "Freight (estimate)"
FREIGHT_ESTIMATE_NOTE = (
    "Freight is an estimate. If the actual shipping cost comes in higher, "
    "the difference will be added to the invoice."
)


def is_freight_note_text(description: Optional[str]) -> bool:
    return (description or "").strip().lower().startswith("freight is an estimate")


class StaffAdjustmentError(ValueError):
    """A staff price or freight override that cannot be applied."""


def _non_negative_money(value, field_name: str) -> float:
    """Zero is allowed. Negative, blank, and non-numeric values are not."""
    if isinstance(value, bool) or value is None:
        raise StaffAdjustmentError(f"{field_name} must be a number zero or greater")
    if isinstance(value, str):
        text = value.strip()
        if not text:
            raise StaffAdjustmentError(f"{field_name} must be a number zero or greater")
        value = text
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise StaffAdjustmentError(f"{field_name} must be a number zero or greater")
    if number != number or number in (float("inf"), float("-inf")) or number < 0:
        raise StaffAdjustmentError(f"{field_name} must be a number zero or greater")
    return round(number, 2)


def parse_staff_price_overrides(raw) -> list:
    """Strict parse for a staff request. None means no overrides."""
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise StaffAdjustmentError("linePriceOverrides must be a list")
    rows = []
    for item in raw:
        if hasattr(item, "model_dump"):
            item = item.model_dump()
        if not isinstance(item, dict):
            raise StaffAdjustmentError("each price override must be an object")
        part = item.get("part_number") or item.get("partNumber")
        if not str(part or "").strip():
            raise StaffAdjustmentError("each price override needs a part number")
        price = item.get("unit_price")
        if price is None:
            price = item.get("unitPrice")
        price = _non_negative_money(price, "unitPrice")
        door = item.get("door_index")
        if door is None:
            door = item.get("doorIndex")
        if door is not None:
            try:
                door = int(door)
            except (TypeError, ValueError):
                raise StaffAdjustmentError("doorIndex must be a whole number")
        rows.append({
            "part_number": str(part).strip(),
            "unit_price": price,
            "door_index": door,
        })
    return rows


def parse_freight_amount(value):
    """None means use the province rule. Zero waives freight. Negatives are rejected."""
    if value is None:
        return None
    return _non_negative_money(value, "freightAmount")


def normalize_line_price_overrides(raw) -> list:
    """Accept pydantic models or dicts. ``door_index`` None applies to every door."""
    if not raw:
        return []
    rows = []
    for item in raw:
        if hasattr(item, "model_dump"):
            item = item.model_dump()
        if not isinstance(item, dict):
            continue
        part = item.get("part_number") or item.get("partNumber")
        price = item.get("unit_price")
        if price is None:
            price = item.get("unitPrice")
        if not part or price is None:
            continue
        try:
            price = round(float(price), 2)
        except (TypeError, ValueError):
            continue
        door = item.get("door_index")
        if door is None:
            door = item.get("doorIndex")
        try:
            door = int(door) if door is not None else None
        except (TypeError, ValueError):
            door = None
        rows.append({
            "part_number": str(part).strip(),
            "unit_price": price,
            "door_index": door,
        })
    return rows


def override_unit_price(overrides, part_number, door_index) -> Optional[float]:
    """Door-specific override wins over a part-wide one."""
    if not overrides or not part_number:
        return None
    part = str(part_number).strip().upper()
    specific = None
    generic = None
    for row in overrides:
        if str(row.get("part_number") or "").strip().upper() != part:
            continue
        row_door = row.get("door_index")
        if row_door is None:
            generic = row.get("unit_price")
        elif door_index is not None and int(row_door) == int(door_index):
            specific = row.get("unit_price")
    if specific is not None:
        return float(specific)
    if generic is not None:
        return float(generic)
    return None


def line_price_override(overrides, line: dict) -> Optional[float]:
    """Unit price a staff member typed for this item line, if any."""
    if not isinstance(line, dict):
        return None
    if line.get("lineType") == "Comment" or line.get("is_door_freight") or line.get("is_freight_note"):
        return None
    part = line.get("part_number") or line.get("lineObjectNumber")
    return override_unit_price(overrides, part, line.get("door_index"))


def dropped_price_overrides(overrides, lines) -> list:
    """Overrides whose part is not on the quote that was just built."""
    if not overrides:
        return []
    posted = []
    for line in lines or []:
        if not isinstance(line, dict):
            continue
        if line.get("lineType") == "Comment" or line.get("is_door_freight") or line.get("is_freight_note"):
            continue
        if (line.get("category") or "").lower() == "freight":
            continue
        part = line.get("part_number") or line.get("lineObjectNumber")
        if not part or str(part).upper() == "FREIGHT":
            continue
        posted.append((str(part).strip().upper(), line.get("door_index")))
    dropped = []
    for row in overrides:
        part = str(row.get("part_number") or "").strip().upper()
        door = row.get("door_index")
        matched = False
        for posted_part, posted_door in posted:
            if posted_part != part:
                continue
            if door is None or posted_door is None or int(door) == int(posted_door):
                matched = True
                break
        if not matched:
            dropped.append({
                "part_number": row.get("part_number"),
                "unit_price": row.get("unit_price"),
                "door_index": door,
                "message": (
                    f"{row.get('part_number')} at ${float(row.get('unit_price') or 0):.2f} "
                    "is not on this quote, so that price override was not applied."
                ),
            })
    return dropped


def apply_freight_override(freight: dict, override_amount) -> dict:
    """Use a typed freight amount on a delivery quote. Pickup stays at no freight.

    The sales-quote line is always labeled ``Freight (estimate)``. The rate
    stays on the dict so settings screens can still show it.
    """
    freight = dict(freight or {})
    if freight.get("skip") and str(freight.get("description") or "").lower().startswith("pickup"):
        return freight
    if override_amount is None:
        if not freight.get("skip"):
            freight["description"] = FREIGHT_ESTIMATE_LABEL
        return freight
    try:
        amount = round(float(override_amount), 2)
    except (TypeError, ValueError):
        if not freight.get("skip"):
            freight["description"] = FREIGHT_ESTIMATE_LABEL
        return freight
    freight["amount"] = amount
    freight["overridden"] = True
    freight["skip"] = amount <= 0
    freight["description"] = FREIGHT_ESTIMATE_LABEL
    return freight


def add_freight_estimate_note(bc_client, quote_id) -> Optional[dict]:
    """Comment that follows the single freight line. Best-effort."""
    try:
        return bc_client.add_quote_line(quote_id, {
            "lineType": "Comment",
            "description": FREIGHT_ESTIMATE_NOTE,
        })
    except Exception as exc:
        logger.warning("Could not add freight estimate note: %s", exc)
        return None


def freight_note_pricing_row() -> dict:
    return {
        "line_type": "Comment",
        "part_number": "",
        "description": FREIGHT_ESTIMATE_NOTE,
        "quantity": 0,
        "unit_price": 0,
        "line_total": 0,
        "is_freight_note": True,
    }


def snapshot_priced_items(quote_lines) -> list:
    """Item unit prices already on a BC quote, in door order.

    Door headers are comment lines whose description starts with ``(``.
    Freight lines are left out; they are not a part-price override.
    """
    rows = []
    door_index = None
    for line in quote_lines or []:
        if not isinstance(line, dict):
            continue
        if (line.get("lineType") or "") == "Comment":
            description = line.get("description") or ""
            if description.startswith("("):
                door_index = (door_index or 0) + 1
            continue
        part = (line.get("lineObjectNumber") or line.get("part_number") or "").strip()
        if not part or part.upper() == "FREIGHT":
            continue
        try:
            price = round(float(line.get("unitPrice") if line.get("unitPrice") is not None else line.get("unit_price")), 2)
        except (TypeError, ValueError):
            continue
        rows.append({
            "part_number": part,
            "unit_price": price,
            "description": line.get("description") or "",
            "quantity": line.get("quantity"),
            "door_index": door_index,
        })
    return rows


def freight_total_from_lines(quote_lines) -> Optional[float]:
    total = 0.0
    found = False
    for line in quote_lines or []:
        if not isinstance(line, dict):
            continue
        part = (line.get("lineObjectNumber") or line.get("part_number") or "").upper()
        if part != "FREIGHT":
            continue
        found = True
        try:
            qty = float(line.get("quantity") or 1)
            price = float(line.get("unitPrice") if line.get("unitPrice") is not None else line.get("unit_price") or 0)
            total += price * qty
        except (TypeError, ValueError):
            continue
    if not found:
        return None
    return round(total, 2)


def price_change_warnings(previous, new_lines, overrides) -> list:
    """Warn when a regenerate would replace a previous unit price.

    An override that was applied (or that matches the new price) is not a warning.
    A part that disappeared is a warning so the old price is not silent.
    """
    warnings = []
    new_by_part = {}
    for line in new_lines or []:
        if not isinstance(line, dict):
            continue
        part = (line.get("part_number") or line.get("lineObjectNumber") or "").strip()
        if not part or part.upper() == "FREIGHT":
            continue
        raw = line.get("unit_price")
        if raw is None:
            raw = line.get("unitPrice")
        try:
            price = round(float(raw), 2)
        except (TypeError, ValueError):
            continue
        new_by_part.setdefault(part.upper(), []).append(price)
    seen = set()
    for prev in previous or []:
        part = str(prev.get("part_number") or "").strip()
        if not part:
            continue
        key = (part.upper(), prev.get("door_index"), prev.get("unit_price"))
        if key in seen:
            continue
        seen.add(key)
        if override_unit_price(overrides, part, prev.get("door_index")) is not None:
            continue
        try:
            old = round(float(prev.get("unit_price")), 2)
        except (TypeError, ValueError):
            continue
        new_prices = new_by_part.get(part.upper())
        if not new_prices:
            warnings.append({
                "part_number": part,
                "previous_unit_price": old,
                "door_index": prev.get("door_index"),
                "message": (
                    f"{part} was ${old:.2f} on the previous quote and is not on this one. "
                    "That price was not carried over."
                ),
            })
            continue
        if any(abs(price - old) <= 0.009 for price in new_prices):
            continue
        warnings.append({
            "part_number": part,
            "previous_unit_price": old,
            "new_unit_price": new_prices[0],
            "door_index": prev.get("door_index"),
            "message": (
                f"{part} was ${old:.2f} and regenerated at ${new_prices[0]:.2f}. "
                f"Set a price override to keep ${old:.2f}."
            ),
        })
    return warnings


def below_cost_warnings(lines) -> list:
    """Selling price under the BC item-card unit cost. Freight is not an item."""
    from app.services.pricing_service import _get_live_item

    warnings = []
    seen = set()
    for line in lines or []:
        if not isinstance(line, dict):
            continue
        if line.get("line_type") in ("Comment", "Note") or line.get("lineType") == "Comment":
            continue
        part = (line.get("part_number") or line.get("lineObjectNumber") or "").strip()
        if not part or part.upper() == "FREIGHT":
            continue
        raw = line.get("unit_price")
        if raw is None:
            raw = line.get("unitPrice")
        try:
            price = float(raw)
        except (TypeError, ValueError):
            continue
        try:
            item = _get_live_item(part) or {}
        except Exception:
            logger.warning("Unit cost lookup failed for %s", part, exc_info=True)
            continue
        try:
            cost = float(item.get("unitCost") or 0)
        except (TypeError, ValueError):
            continue
        if cost <= 0 or price + 0.001 >= cost:
            continue
        key = (part.upper(), line.get("door_index"), round(price, 2))
        if key in seen:
            continue
        seen.add(key)
        warnings.append({
            "part_number": part,
            "description": line.get("description") or "",
            "door_index": line.get("door_index"),
            "unit_price": round(price, 2),
            "unit_cost": round(cost, 2),
            "overridden": bool(line.get("price_overridden")),
            "message": f"{part} is priced at ${price:.2f}, below its BC unit cost.",
        })
    return warnings


def mark_overridden_prices(line_pricing, overrides) -> None:
    for row in line_pricing or []:
        if not isinstance(row, dict):
            continue
        if override_unit_price(overrides, row.get("part_number"), row.get("door_index")) is not None:
            row["price_overridden"] = True


def preview_part_prices(parts, customer_id, db) -> None:
    """Attach unit_price, unit_cost, and below_cost onto part dicts in place.

    A fixed portal price (wrapping, flat windows) wins over SalesPriceLists.
    A missing BC price leaves unit_price unset so the review step can still
    accept a typed override.
    """
    from app.services.external_pricing_service import resolve_price
    from app.services.pricing_service import _get_live_item, warm_bc_cost_cache

    numbers = []
    for part in parts or []:
        part_number = part.get("part_number") if isinstance(part, dict) else None
        if part_number and str(part_number).upper() != "FREIGHT":
            numbers.append(part_number)
    if numbers:
        try:
            warm_bc_cost_cache(numbers)
        except Exception:
            logger.warning("Could not warm costs for the price preview", exc_info=True)

    resolved_cache = {}
    for part in parts or []:
        if not isinstance(part, dict):
            continue
        part_number = part.get("part_number")
        if not part_number or str(part_number).upper() == "FREIGHT":
            continue
        if part.get("fixed_unit_price") is not None:
            try:
                part["unit_price"] = round(float(part["fixed_unit_price"]), 2)
                part["price_source"] = "fixed"
            except (TypeError, ValueError):
                pass
        elif customer_id and db is not None:
            cache_key = (str(part_number), int(part.get("quantity") or 1))
            if cache_key not in resolved_cache:
                try:
                    resolved_cache[cache_key] = resolve_price(
                        db, customer_id, part_number, cache_key[1],
                    )
                except Exception:
                    logger.warning("Price preview failed for %s", part_number, exc_info=True)
                    resolved_cache[cache_key] = None
            resolved = resolved_cache[cache_key]
            if resolved is not None:
                part["unit_price"] = round(resolved.unit_price_cents / 100, 2)
                part["price_source"] = resolved.price_source
        try:
            item = _get_live_item(part_number) or {}
            cost = float(item.get("unitCost") or 0)
        except Exception:
            cost = 0
        if cost > 0:
            part["unit_cost"] = round(cost, 2)
        price = part.get("unit_price")
        part["below_cost"] = bool(
            cost > 0 and price is not None and float(price) + 0.001 < cost
        )


def redact_preview_prices(parts, *, see_prices: bool, see_cost: bool) -> None:
    for part in parts or []:
        if not isinstance(part, dict):
            continue
        if not see_cost:
            part.pop("unit_cost", None)
        if not see_prices:
            part.pop("unit_price", None)
            part.pop("price_source", None)
            part.pop("below_cost", None)
            part.pop("line_total", None)
