"""Crate dimensions for sectional doors shipping from Redcliff.

Length is the shaft rule: door width plus the overhang (18 in, so a 16 ft
door is 210 in). Height is the stacked panel thickness plus one dunnage
allowance. Width is the taller section face plus the packing allowance.
Doors of the same width, and the same shaft rule, share a crate until the
panel stack reaches the maximum.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Dict, List

from app.services.freight_numbers import D, as_number, pounds


def pack_crates(units: List[dict], crate: dict) -> List[dict]:
    groups: Dict[tuple, List[dict]] = {}
    for unit in units:
        key = (int(round(float(unit["width_in"]))), bool(unit.get("include_shaft", True)))
        groups.setdefault(key, []).append(unit)

    crates = []
    max_stack = D(crate["max_stack_height_in"])
    for width_in, include_shaft in sorted(groups):
        members = sorted(groups[(width_in, include_shaft)], key=lambda row: D(row["stack_in"]), reverse=True)
        bins: List[dict] = []
        for member in members:
            stack = D(member["stack_in"])
            placed = False
            if stack <= max_stack:
                for bin_ in bins:
                    if bin_["stack"] + stack <= max_stack:
                        bin_["units"].append(member)
                        bin_["stack"] += stack
                        placed = True
                        break
            if not placed:
                bins.append({
                    "units": [member],
                    "stack": stack,
                    "oversized": stack > max_stack,
                })
        overhang = crate["shaft_overhang_in"] if include_shaft else crate["no_shaft_end_allowance_in"]
        for bin_ in bins:
            length = D(width_in) + D(overhang)
            face = max(D(unit["section_face_in"]) for unit in bin_["units"])
            width = face + D(crate["packing_allowance_in"])
            height = bin_["stack"] + D(crate["dunnage_in"])
            product = sum((D(unit["product_weight_lb"]) for unit in bin_["units"]), D(0))
            tare = D(crate["tare_base_lb"]) + D(crate["tare_lb_per_ft"]) * length / D(12)
            ship = product + tare
            warning = None
            if bin_["oversized"]:
                warning = (
                    "One door is already taller than the max stack, so it crates alone."
                )
            crates.append({
                "kind": "crate",
                "length_in": as_number(pounds(length)),
                "width_in": as_number(pounds(width)),
                "height_in": as_number(pounds(height)),
                "product_weight_lb": as_number(pounds(product)),
                "tare_lb": as_number(pounds(tare)),
                "weight_lb": as_number(pounds(ship)),
                "stack_in": as_number(pounds(bin_["stack"])),
                "door_count": len(bin_["units"]),
                "include_shaft": include_shaft,
                "contents": [unit["label"] for unit in bin_["units"]],
                "warning": warning,
            })
    for index, crate_row in enumerate(crates, start=1):
        names = ", ".join(crate_row["contents"])
        crate_row["label"] = f"Crate {index}: {names}" if names else f"Crate {index}"
    return crates


def skid_pieces(skids: List[dict]) -> List[dict]:
    pieces = []
    for index, skid in enumerate(skids or [], start=1):
        length = skid.get("length_in", skid.get("lengthIn"))
        width = skid.get("width_in", skid.get("widthIn"))
        height = skid.get("height_in", skid.get("heightIn"))
        weight = skid.get("weight_lb", skid.get("weightLb"))
        if None in (length, width, height, weight):
            raise ValueError(f"Skid {index} needs length, width, height, and weight.")
        pieces.append({
            "kind": "skid",
            "label": skid.get("label") or f"Skid {index}",
            "length_in": float(length),
            "width_in": float(width),
            "height_in": float(height),
            "weight_lb": float(weight),
            "product_weight_lb": float(weight),
            "tare_lb": 0,
            "contents": [],
            "warning": None,
        })
    return pieces
