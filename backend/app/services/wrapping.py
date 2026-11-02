"""In-house wrapping sold on every steel door package.

Upwardor bills wrapping as the door opening in square feet, rounded to the
nearest whole square foot per door (halves round up), then multiplied by
the door quantity. Open Distribution sells that same quantity as BC item
WRAP ("Wrapping", unit SF) at a fixed rate.

The WRAP item card in Business Central is $2.50. Quote lines must not
inherit that price. Callers that post a sales quote PATCH ``unitPrice``
from ``fixed_wrap_unit_price``. This module does not write item master data.
"""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Mapping, Optional

WRAP_ITEM_NUMBER = "WRAP"
WRAP_DESCRIPTION = "Wrapping"
WRAP_CATEGORY = "wrapping"
# Sell price per square foot. Our cost is about $0.63/SF; the BC item
# card (unit price $2.50, cached unit cost $0.66) is not the quote price.
WRAP_SELL_PRICE_PER_SF = 0.95


def wrapping_sqft(width_inches: int, height_inches: int) -> int:
    """Nearest whole square foot of one door opening. Half rounds up.

    Width and height are the opening in inches. ``width_ft × height_ft``
    is computed exactly from those inches (÷ 144) so 14'2" × 14' is
    198.333… → 198 and 24'2" × 16' is 386.666… → 387.

    Do not use the built-in ``round()``. It is half-to-even, so 100.5
    (9'0" × 11'2") becomes 100 instead of 101.
    """
    try:
        width = int(width_inches or 0)
        height = int(height_inches or 0)
    except (TypeError, ValueError):
        return 0
    if width <= 0 or height <= 0:
        return 0
    area = (Decimal(width) * Decimal(height)) / Decimal(144)
    return int(area.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def fixed_wrap_unit_price(line: Mapping[str, Any]) -> Optional[float]:
    """Unit price to write on a WRAP quote line, or None for every other line.

    A line that already carries ``unit_price`` keeps that value (the part
    builder sets it to ``WRAP_SELL_PRICE_PER_SF``). A WRAP line with no
    explicit price still sells at the configured rate, so a caller that
    drops the field cannot fall through to BC's $2.50 card price.
    """
    if (line.get("lineType") or "Item") == "Comment":
        return None
    part_number = str(line.get("part_number") or "").strip().upper()
    if part_number != WRAP_ITEM_NUMBER:
        return None
    explicit = line.get("unit_price")
    if explicit is None:
        return WRAP_SELL_PRICE_PER_SF
    return round(float(explicit), 2)
