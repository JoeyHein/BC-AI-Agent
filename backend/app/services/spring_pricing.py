"""Cost model for a complete spring assembly.

Spring selection used to optimize *length* (shortest spring wins), which is
inversely correlated with price: a shorter spring means a bigger coil, and a
bigger coil costs more per inch, needs a pricier winder set, and — at 6" — drags
in a PVC tube. This module prices the whole assembly so the selector can pick the
cheapest option that still meets the cycle target and fits the shaft.

Costs track what part_number_service._get_spring_parts() emits so the ranking
reflects what actually lands on the quote:

    springs   price/in x ceil(length) x count, per winding (LH/RH)
    winders   one set per spring, priced by coil diameter
    PVC tube  6" non-duplex only (the inner spring fills a duplex outer)
    couplers  APPROXIMATED as qty//2 - 1 (see note below)

Crucially, we price the part the emitter would actually sell: a Canimex wire/coil
whose exact SP11 SKU isn't stocked is stepped up via mapper.resolve_spring_in_bc
(the same resolver _get_spring_parts uses) before pricing. Without that, valid
sellable springs score as unpriceable and get dropped from selection.

Coupler note: _get_spring_parts emits no couplers itself; couplers come from
_get_shaft_parts, whose count is max(ceil(spring_count/2), width_min_shafts) - 1.
The width floor is constant across a door's candidates, so the part that VARIES
between candidates is the spring-count term modeled here. The absolute figure can
therefore under-count couplers on very wide doors where width forces extra shafts;
that offset is the same for every candidate of that door and doesn't change the
ranking. It exists only to make "4 small springs" carry its extra-shaft cost
versus "2 big springs."

Prices come from spring_price_book.json (regenerate with
`python -m scripts.refresh_spring_prices`). Blocked and $0 items are excluded
from the book on purpose — a $0 item looks free and would win every comparison.
If a part has no trustworthy price, cost is None and the caller must not treat
the candidate as cheap; it falls back to the legacy ordering instead.
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

# Lazily populated on first access so importing this module (and, transitively,
# door_calculator_service) does no disk I/O at import time.
_PRICES: Optional[dict] = None


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


def prices() -> dict:
    """The price book, loaded on first use."""
    global _PRICES
    if _PRICES is None:
        _PRICES = _load_price_book()
    return _PRICES


def reload_price_book() -> dict:
    """Force a re-read (after refresh_spring_prices regenerates the file, or in tests)."""
    global _PRICES
    _PRICES = _load_price_book()
    return _PRICES


def has_price_book() -> bool:
    """False when the book is missing/unreadable — callers keep legacy behaviour."""
    return bool(prices())


def price_of(part_number: str) -> Optional[float]:
    """Unit price, or None if the part isn't in the book (blocked, $0, or absent)."""
    if not part_number:
        return None
    return prices().get(part_number)


def _resolved_spring_price_in(wire_diameter: float, coil_diameter: float, mapper) -> Optional[tuple]:
    """Price the sellable spring for this wire/coil, per inch, per winding.

    Mirrors _get_spring_parts: if the exact SP11 SKU isn't a real BC item, step
    up via resolve_spring_in_bc to the part that would actually be sold, then
    price THAT. Returns (lh_price_per_in, rh_price_per_in, resolved_coil) or None
    when nothing sellable is priced. resolved_coil flows out because a coil
    step-up (e.g. 2.0 → 2.625) changes the winder set and the PVC decision.
    """
    lh_pn = mapper.get_spring_part_number(wire_diameter, coil_diameter, "LH").part_number
    resolved_coil = coil_diameter
    if price_of(lh_pn) is None:
        found, rw, rc = mapper.resolve_spring_in_bc(wire_diameter, coil_diameter)
        if not found:
            return None
        wire_diameter, resolved_coil = rw, rc
        lh_pn = mapper.get_spring_part_number(wire_diameter, resolved_coil, "LH").part_number

    rh_pn = mapper.get_spring_part_number(wire_diameter, resolved_coil, "RH").part_number
    lh_price = price_of(lh_pn)
    rh_price = price_of(rh_pn)
    if lh_price is None or rh_price is None:
        return None
    return lh_price, rh_price, resolved_coil


def _winding_counts(spring_qty: int) -> tuple:
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
    if not prices():
        return None

    # Imported lazily: get_bc_mapper() reads a ~15MB item cache, and this module
    # is imported by the door calculator on paths that may never price anything.
    from app.services.bc_part_number_mapper import get_bc_mapper

    mapper = get_bc_mapper()
    length_in = math.ceil(length)
    lh_count, rh_count = _winding_counts(spring_qty)

    total = 0.0

    # Outer springs — priced on the part that would actually be sold (after any
    # step-up), which may also bump the coil we use for the winder/PVC below.
    resolved = _resolved_spring_price_in(wire_diameter, coil_diameter, mapper)
    if resolved is None:
        return None
    lh_price, rh_price, coil_diameter = resolved
    total += lh_price * length_in * lh_count
    total += rh_price * length_in * rh_count

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
        inner = _resolved_spring_price_in(inner_wire_diameter, inner_coil_diameter, mapper)
        if inner is None:
            return None
        inner_lh, inner_rh, inner_coil = inner
        total += (inner_lh + inner_rh) * inner_len_in * duplex_pairs

        inner_winder_pn = mapper.get_winder_stationary_set(inner_coil, SHAFT_BORE).part_number
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

    # More than 2 springs forces a second shaft, hence couplers (see module note).
    couplers = max(0, spring_qty // 2 - 1)
    if couplers:
        coupler_price = price_of(COUPLER_PN)
        if coupler_price is None:
            return None
        total += coupler_price * couplers

    return round(total, 2)
