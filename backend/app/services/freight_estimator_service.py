"""Ship-weight, crate, and Manitoulin freight estimate.

This module does not call Business Central. It prices a hypothetical
shipment from door lines and manual skids.
"""
from __future__ import annotations

from typing import Optional

from app.services.crate_estimator import pack_crates, skid_pieces
from app.services.freight_estimator_settings import DEFAULT_CONFIG, freight_estimator_config
from app.services.freight_numbers import as_number, money
from app.services.manitoulin_rate_engine import rate_pieces
from app.services.manitoulin_rate_table import AGREEMENT, load_rate_table, normalize_place
from app.services.ship_weight_service import (
    apply_constant_overrides,
    build_door_line,
    door_units,
    load_constants,
)

SIGNED_NOTE = (
    "Manitoulin Preferential Service Agreement #19067426 must be signed "
    "before these rates are applied."
)


def _config(config: Optional[dict], db=None) -> dict:
    base = dict(DEFAULT_CONFIG)
    if db is not None and config is None:
        base.update(freight_estimator_config(db))
    elif config:
        base.update(config)
    return base


def estimate_freight(payload: dict, db=None, config: Optional[dict] = None, rate_table=None, constants=None) -> dict:
    cfg = _config(config, db if config is None else None)
    constants = apply_constant_overrides(constants or load_constants(), cfg)
    table = rate_table or load_rate_table()

    lines = []
    units = []
    for index, door in enumerate(payload.get("doors") or [], start=1):
        line = build_door_line(door, constants, index)
        lines.append(line)
        units.extend(door_units(line))

    crates = pack_crates(units, constants["crate"])
    pieces = list(crates) + skid_pieces(payload.get("skids") or [])
    origin = payload.get("origin") or "redcliff"
    destination = payload.get("destination")
    rated = rate_pieces(pieces, origin, destination, table, cfg)
    for piece, source in zip(rated["pieces"], pieces):
        if source.get("warning"):
            piece["warning"] = source["warning"]
        if source.get("door_count") is not None:
            piece["door_count"] = source["door_count"]
        if source.get("stack_in") is not None:
            piece["stack_in"] = source["stack_in"]

    return {
        "agreement": AGREEMENT,
        "signed_note": SIGNED_NOTE,
        "origin": rated["origin"],
        "destination": rated["destination"],
        "destination_recognized": normalize_place(destination) is not None,
        "lines": lines,
        "pieces": rated["pieces"],
        "shipment": rated["shipment"],
        "lane_on_sheet": rated["lane_on_sheet"],
        "rate_table": {
            "placeholder": bool(table.get("placeholder")),
            "status": table.get("status"),
            "notice": table.get("notice"),
        },
        "assumptions": {
            "fuel_percent": float(cfg.get("fuel_percent")),
            "long_charge": float(cfg.get("long_charge")),
            "long_min_length_in": float(cfg.get("long_min_length_in")),
            "density_lb_per_cuft": float(cfg.get("density_lb_per_cuft")),
            "gst_percent": float(cfg.get("gst_percent")),
            "crate": {
                "shaft_overhang_in": constants["crate"]["shaft_overhang_in"],
                "dunnage_in": constants["crate"]["dunnage_in"],
                "packing_allowance_in": constants["crate"]["packing_allowance_in"],
                "max_stack_height_in": constants["crate"]["max_stack_height_in"],
                "tare_base_lb": constants["crate"]["tare_base_lb"],
                "tare_lb_per_ft": constants["crate"]["tare_lb_per_ft"],
            },
        },
    }


def assumptions_money(config: dict) -> dict:
    """Quantized echo of the rating knobs, used by the settings screen."""
    return {
        "fuel_percent": as_number(money(config["fuel_percent"])),
        "long_charge": as_number(money(config["long_charge"])),
        "long_min_length_in": float(config["long_min_length_in"]),
        "density_lb_per_cuft": float(config["density_lb_per_cuft"]),
        "gst_percent": float(config["gst_percent"]),
    }
