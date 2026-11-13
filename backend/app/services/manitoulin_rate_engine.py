"""Manitoulin agreement 19067426 rating rules.

Billed weight is the greater of the actual weight and the cube times the
density factor (10 lb per cubic foot). The break is the column whose floor
is still at or under that weight. L5C is only for weights under 500 lb.
Every higher break is also priced at its own minimum weight, and the
cheapest linehaul wins. The lane minimum then floors that linehaul. LONG
is $75 for each piece whose longest side meets the length rule. Manitoulin
has not confirmed whether FLT is once per shipment instead; until it does,
each long piece is charged. Fuel is a percent of the linehaul only. GST is
calculated on linehaul + LONG + fuel and kept separate.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, List, Optional

from app.services.freight_numbers import D, as_number, money, pounds
from app.services.manitoulin_rate_table import (
    AGREEMENT,
    BREAKS,
    BREAK_MINIMUMS,
    L5C_BELOW_LB,
    NO_CONTRACT_RATE,
    find_lane,
    label_for,
    lane_has_any_rate,
    normalize_place,
)

CUIN_PER_CUFT = D(1728)


def cube_cuft(length_in, width_in, height_in) -> Decimal:
    return D(length_in) * D(width_in) * D(height_in) / CUIN_PER_CUFT


def billed_weight(actual_lb, cube: Decimal, density_lb_per_cuft) -> Decimal:
    dimensional = cube * D(density_lb_per_cuft)
    return pounds(max(D(actual_lb), dimensional))


def _break_for(weight: Decimal) -> str:
    if weight < L5C_BELOW_LB:
        return "L5C"
    chosen = "500"
    for name in BREAKS:
        if name == "L5C":
            continue
        if weight >= BREAK_MINIMUMS[name]:
            chosen = name
    return chosen


def _rate(lane: dict, break_name: str) -> Optional[Decimal]:
    raw = (lane.get("rates") or {}).get(break_name)
    if raw is None:
        return None
    return D(raw)


def _charge(weight: Decimal, rate: Decimal) -> Decimal:
    return money(weight * rate / D(100))


def rate_billed_weight(billed: Decimal, lane: dict, *, minimum_override=None) -> dict:
    """Price one billed weight against a lane. Does not add LONG, fuel, or GST."""
    if not lane_has_any_rate(lane):
        return {"rated": False, "message": NO_CONTRACT_RATE}

    break_name = _break_for(billed)
    rate = _rate(lane, break_name)
    if rate is None:
        return {
            "rated": False,
            "message": NO_CONTRACT_RATE,
            "break": break_name,
            "billed_weight_lb": as_number(billed),
        }

    linehaul = _charge(billed, rate)
    rated_weight = billed
    chosen_rate = rate
    deficit_checked = False
    deficit_used = False
    # Price every higher break at that break's minimum weight and keep the
    # cheapest. A break further up can beat the one immediately above when
    # its minimum charge is lower. An equal charge stays on the lower break.
    start = BREAKS.index(break_name)
    for higher in BREAKS[start + 1:]:
        higher_rate = _rate(lane, higher)
        if higher_rate is None:
            continue
        deficit_checked = True
        alternative = _charge(BREAK_MINIMUMS[higher], higher_rate)
        if alternative < linehaul:
            break_name = higher
            chosen_rate = higher_rate
            rated_weight = BREAK_MINIMUMS[higher]
            linehaul = alternative
            deficit_used = True

    minimum = lane.get("min") if minimum_override is None else minimum_override
    minimum_applied = False
    if minimum is not None and linehaul < D(minimum):
        linehaul = money(minimum)
        minimum_applied = True

    return {
        "rated": True,
        "break": break_name,
        "rate_per_cwt": float(chosen_rate),
        "billed_weight_lb": as_number(billed),
        "rated_weight_lb": as_number(pounds(rated_weight)),
        "linehaul": as_number(linehaul),
        "linehaul_decimal": linehaul,
        "minimum": None if minimum is None else as_number(money(minimum)),
        "minimum_applied": minimum_applied,
        "deficit_checked": deficit_checked,
        "deficit_used": deficit_used,
    }


def _longest(piece: dict) -> Decimal:
    return max(D(piece["length_in"]), D(piece["width_in"]), D(piece["height_in"]))


def _finish_money(core: dict, *, long_amount: Decimal, fuel_percent: Decimal, gst_percent: Decimal) -> dict:
    if not core.get("rated"):
        core.pop("linehaul_decimal", None)
        return core
    linehaul = core.pop("linehaul_decimal")
    fuel = money(linehaul * fuel_percent / D(100))
    subtotal = linehaul + long_amount + fuel
    gst = money(subtotal * gst_percent / D(100))
    core.update({
        "long": as_number(long_amount),
        "fuel": as_number(fuel),
        "fuel_percent": float(fuel_percent),
        "subtotal": as_number(subtotal),
        "gst": as_number(gst),
        "gst_percent": float(gst_percent),
        "all_in": as_number(subtotal + gst),
    })
    return core


def rate_pieces(
    pieces: List[dict],
    origin: Any,
    destination: Any,
    table: dict,
    config: dict,
) -> dict:
    """Rate each piece on its own and rate the pieces together as one shipment.

    The shipment is the figure to use on a bill of lading. The per-piece
    numbers are what that one piece would cost if it moved alone.
    """
    density = config.get("density_lb_per_cuft", 10)
    fuel_percent = D(config.get("fuel_percent", "68.80"))
    gst_percent = D(config.get("gst_percent", 5))
    long_charge = D(config.get("long_charge", 75))
    long_min = D(config.get("long_min_length_in", 96))
    # LONG stays $75 (or the saved amount) for every piece at or over the
    # length. Pending confirmation from Manitoulin on whether FLT is charged
    # once per shipment instead of once per long piece.

    origin_id = normalize_place(origin)
    destination_id = normalize_place(destination)
    lane = find_lane(table, origin_id, destination_id)

    rated_pieces = []
    total_actual = D(0)
    total_cube = D(0)
    for index, piece in enumerate(pieces, start=1):
        cube = cube_cuft(piece["length_in"], piece["width_in"], piece["height_in"])
        actual = D(piece["weight_lb"])
        billed = billed_weight(actual, cube, density)
        longest = _longest(piece)
        long_pieces = 1 if longest >= long_min else 0
        long_amount = money(long_charge * long_pieces)
        alone = {"rated": False, "message": NO_CONTRACT_RATE}
        if lane is not None:
            alone = rate_billed_weight(billed, lane)
            alone = _finish_money(
                alone,
                long_amount=long_amount,
                fuel_percent=fuel_percent,
                gst_percent=gst_percent,
            )
        density_lb_per_cuft = None
        if cube > 0:
            density_lb_per_cuft = as_number(pounds(actual / cube))
        rated_pieces.append({
            "piece": index,
            "kind": piece.get("kind") or "piece",
            "label": piece.get("label") or f"Piece {index}",
            "length_in": as_number(pounds(piece["length_in"])),
            "width_in": as_number(pounds(piece["width_in"])),
            "height_in": as_number(pounds(piece["height_in"])),
            "ship_weight_lb": as_number(pounds(actual)),
            "tare_lb": as_number(pounds(piece.get("tare_lb") or 0)),
            "product_weight_lb": as_number(pounds(piece.get("product_weight_lb") or actual)),
            "cube_cuft": as_number(pounds(cube)),
            "cube_exact": cube,
            "density_lb_per_cuft": density_lb_per_cuft,
            "billed_weight_lb": as_number(billed),
            "overlength": bool(long_pieces),
            "rated_alone": {key: value for key, value in alone.items() if key != "cube_exact"},
            "contents": piece.get("contents") or [],
        })
        total_actual += actual
        total_cube += cube

    shipment_billed = billed_weight(total_actual, total_cube, density) if pieces else pounds(0)
    long_count = sum(1 for piece in rated_pieces if piece["overlength"])
    long_amount = money(long_charge * long_count)
    if not pieces:
        shipment = {"rated": False, "message": "Add a door line or a skid."}
    elif lane is None or not lane_has_any_rate(lane):
        shipment = {
            "rated": False,
            "message": NO_CONTRACT_RATE,
            "billed_weight_lb": as_number(shipment_billed),
        }
    else:
        shipment = rate_billed_weight(shipment_billed, lane)
        shipment = _finish_money(
            shipment,
            long_amount=long_amount,
            fuel_percent=fuel_percent,
            gst_percent=gst_percent,
        )
        shipment["long_pieces"] = long_count

    shipment["actual_weight_lb"] = as_number(pounds(total_actual))
    shipment["cube_cuft"] = as_number(pounds(total_cube))
    shipment["piece_count"] = len(rated_pieces)
    # Drop the exact cube from the public pieces. It is not JSON-safe as a Decimal
    # only if a caller reuses the list; the API returns the floats above.
    for piece in rated_pieces:
        piece.pop("cube_exact", None)

    return {
        "agreement": AGREEMENT,
        "origin": {"id": origin_id, "label": label_for("origin", origin_id)},
        "destination": {"id": destination_id, "label": label_for("destination", destination_id)},
        "lane_on_sheet": bool(lane is not None and lane_has_any_rate(lane)),
        "pieces": rated_pieces,
        "shipment": shipment,
    }
