"""Cost model for a complete spring assembly.

Spring selection used to optimize *length* (shortest spring wins), which is
inversely correlated with price: a shorter spring means a bigger coil, and a
bigger coil costs more per inch, needs a pricier winder set, and — at 6" — drags
in a PVC tube. This module prices the whole assembly so the selector can pick the
cheapest option that still meets the cycle target and fits the shaft.

Costs mirror exactly what part_number_service._get_spring_parts() emits, so the
number here matches what actually lands on the quote:

    springs   price/in x ceil(length) x count, per winding (LH/RH)
    winders   one set per spring, priced by coil diameter
    PVC tube  6" non-duplex only (the inner spring fills a duplex outer)
    couplers  qty > 2 needs a second shaft, so qty//2 - 1 couplers

Prices come from spring_price_book.json (regenerate with
`python -m scripts.refresh_spring_prices`). Blocked and $0 items are excluded
from the book on purpose — a $0 item looks free and would win every comparison.
If a part has no trustworthy price, cost is None and the caller must not treat
the candidate as cheap; it should fall back to the legacy ordering instead.
"""

import json
import logging
import math
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_PRICE_BOOK_PATH = Path(__file__).with_name("spring_price_book.json")

PVC_TUBE_PN = "PK14-00003-00"
COUPLER_PN = "SP12-00160-00"
SHAFT_BORE = 1.0


def _load_price_book() -> dict:
    try:
        with open(_PRICE_BOOK_PATH) as f:
            book = json.load(f)
        prices = book.get("prices", {})
        logger.info(
            f"Loaded spring price book: {len(prices)} parts "
            f"(generated {book.get('generated_utc', 'unknown')})"
        )
        return prices
    except FileNotFoundError:
        logger.warning(
            f"Spring price book not found at {_PRICE_BOOK_PATH} — cost-aware spring "
            f"selection disabled, falling back to legacy length ordering. "
            f"Run: python -m scripts.refresh_spring_prices"
        )
        return {}
    except (json.JSONDecodeError, OSError) as e:
        logger.warning(f"Spring price book unreadable ({e}) — cost-aware selection disabled")
        return {}


PRICES: dict = _load_price_book()


def has_price_book() -> bool:
    """False when the book is missing/unreadable — callers keep legacy behaviour."""
    return bool(PRICES)


def price_of(part_number: str) -> Optional[float]:
    """Unit price, or None if the part isn't in the book (blocked, $0, or absent)."""
    if not part_number:
        return None
    return PRICES.get(part_number)


def _winding_counts(spring_qty: int) -> tuple[int, int]:
    """(lh_count, rh_count) — matches part_number_service._get_spring_parts.

    An odd qty (in practice 1, small residential) is a single LH spring with no
    RH counterpart.
    """
    if spring_qty <= 1:
        return 1, 0
    pairs = spring_qty // 2
    return pairs, pairs


def assembly_cost(
    wire_diameter: float,
    coil_diameter: float,
    length: float,
    spring_qty: int,
    *,
    is_duplex: bool = False,
    inner_wire_diameter: Optional[float] = None,
    inner_coil_diameter: Optional[float] = None,
    inner_length: Optional[float] = None,
    duplex_pairs: int = 0,
) -> Optional[float]:
    """Total cost of the spring assembly, or None if any part lacks a real price.

    Returning None (rather than 0 or a guess) is deliberate: an unpriced part must
    never make a candidate look cheap.
    """
    if not PRICES:
        return None

    # Imported lazily: get_bc_mapper() reads a ~15MB item cache, and this module
    # is imported by the door calculator on paths that may never price anything.
    from app.services.bc_part_number_mapper import get_bc_mapper

    mapper = get_bc_mapper()
    length_in = math.ceil(length)
    lh_count, rh_count = _winding_counts(spring_qty)

    total = 0.0

    # Outer springs, priced per winding
    for wind, count in (("LH", lh_count), ("RH", rh_count)):
        if count <= 0:
            continue
        pn = mapper.get_spring_part_number(wire_diameter, coil_diameter, wind).part_number
        unit = price_of(pn)
        if unit is None:
            return None
        total += unit * length_in * count

    # Winder/stationary sets — one per spring
    winder_pn = mapper.get_winder_stationary_set(coil_diameter, SHAFT_BORE).part_number
    winder_price = price_of(winder_pn)
    if winder_price is None:
        return None
    total += winder_price * spring_qty

    if is_duplex:
        if not (inner_wire_diameter and inner_coil_diameter and inner_length and duplex_pairs):
            return None
        inner_len_in = math.ceil(inner_length)
        for wind in ("LH", "RH"):
            pn = mapper.get_spring_part_number(inner_wire_diameter, inner_coil_diameter, wind).part_number
            unit = price_of(pn)
            if unit is None:
                return None
            total += unit * inner_len_in * duplex_pairs

        inner_winder_pn = mapper.get_winder_stationary_set(inner_coil_diameter, SHAFT_BORE).part_number
        inner_winder_price = price_of(inner_winder_pn)
        if inner_winder_price is None:
            return None
        total += inner_winder_price * spring_qty
    elif coil_diameter == 6.0:
        # 6" springs need a PVC tube inside each spring; duplex skips it because
        # the inner spring already fills the outer.
        pvc = price_of(PVC_TUBE_PN)
        if pvc is None:
            return None
        total += pvc * length_in * spring_qty

    # More than 2 springs forces a second shaft, hence couplers.
    couplers = max(0, spring_qty // 2 - 1)
    if couplers:
        coupler_price = price_of(COUPLER_PN)
        if coupler_price is None:
            return None
        total += coupler_price * couplers

    return round(total, 2)
