"""Hardware the shop sheet can label from the parts and Thermalex calculators.

Used only when real profiles are on. A missing figure is the string
``BY FACTORY`` rather than a guessed number.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

BY_FACTORY = "BY FACTORY"

_WIRE = re.compile(
    r"Springs:\s*([0-9.]+)\"\s*wire\s*x\s*([0-9.]+)\"\s*ID\s*x\s*([0-9.]+)\"",
    re.I,
)
_HANDS = re.compile(r"(\d+)\s*LH(?:\s*\+\s*(\d+)\s*RH)?", re.I)
_TURNS = re.compile(r"Turns:\s*([0-9.]+)", re.I)
_DRUM = re.compile(r"Drum:\s*([^|]+)", re.I)
_WEIGHT = re.compile(r"Door Weight:\s*([0-9.]+)\s*lbs", re.I)
_SHAFT_LEN = re.compile(r"(\d+)'-(\d+(?:\.\d+)?)\"")


@dataclass
class ShopHardware:
    wire: Optional[float] = None
    coil_id: Optional[float] = None
    spring_length: Optional[float] = None
    turns: Optional[float] = None
    cycles: int = 10000
    lh_count: int = 0
    rh_count: int = 0
    spring_count: int = 0
    drum_model: Optional[str] = None
    drum_diameter: Optional[float] = None
    cable_diameter: Optional[float] = None
    cable_length: Optional[float] = None
    shaft_label: Optional[str] = None
    shaft_diameter: Optional[float] = None
    shaft_length: Optional[float] = None
    shaft_kind: Optional[str] = None
    strut_count: int = 0
    strut_gauge: Optional[str] = None
    headroom: Optional[float] = None
    backroom: Optional[float] = None
    floor_to_ust: Optional[float] = None
    ust: Optional[float] = None
    vertical_track: Optional[float] = None
    horizontal_track: Optional[float] = None
    track_size: int = 2
    track_radius: int = 15
    high_lift: float = 0.0
    door_weight: Optional[float] = None
    by_factory: list[str] = field(default_factory=list)

    def spring_label(self, wind: str) -> str:
        if self.wire is None or self.coil_id is None or self.spring_length is None:
            return f"SPRING {wind} — {BY_FACTORY}"
        turns = f"{self.turns:.1f} TURNS" if self.turns is not None else f"TURNS {BY_FACTORY}"
        return (
            f"{self.wire:g}\" x {self.coil_id:g}\" ID x {self.spring_length:g}\"  "
            f"{wind}  {turns}"
        )


def drum_diameter_in(model: Optional[str]) -> Optional[float]:
    """Series diameter encoded in the drum model name."""
    name = (model or "").upper()
    if "525" in name:
        return 5.25
    if "400" in name:
        return 4.0
    return None


def _shaft_kind(description: str, part: str) -> tuple[Optional[str], Optional[float], Optional[float]]:
    desc = description or ""
    match = _SHAFT_LEN.search(desc)
    length = None
    if match:
        length = int(match.group(1)) * 12 + float(match.group(2))
    part_u = (part or "").upper()
    low = desc.lower()
    if part_u.startswith("SH10") or "1-1/4" in low:
        return "1-1/4\" SOLID KEYED", 1.25, length
    if part_u.startswith("SH11") or "solid" in low:
        return "1\" SOLID KEYED", 1.0, length
    if part_u.startswith("SH12") or "tube" in low:
        return "1\" TUBULAR", 1.0, length
    return None, None, length


def resolve_shop_hardware(ctx) -> ShopHardware:
    """Pull spring, drum, shaft, strut, and track figures for one door."""
    hw = ShopHardware(cycles=int(ctx.target_cycles or 10000))
    door = {
        "doorSeries": ctx.door_series,
        "doorType": ctx.door_type,
        "doorWidth": int(ctx.door_width_in),
        "doorHeight": int(ctx.door_height_in),
        "liftType": ctx.lift_type,
        "highLiftInches": int(ctx.high_lift_inches or 0),
        "trackRadius": int(round(ctx.track_radius_in or 15)),
        "targetCycles": int(ctx.target_cycles or 10000),
        "trackThickness": ctx.track_thickness_ga,
        "panelDesign": ctx.panel_design,
        "panelColor": ctx.panel_color,
        "hasWindows": ctx.has_windows,
    }
    try:
        from app.services.part_number_service import (
            PartNumberService,
            get_parts_for_door_config,
        )
        result = get_parts_for_door_config(door)
        for part in result.get("parts_list", []):
            cat = (part.get("category") or "").lower()
            desc = part.get("description") or ""
            if cat == "spring_comment" and "wire" in desc.lower():
                found = _WIRE.search(desc)
                if found:
                    hw.wire = float(found.group(1))
                    hw.coil_id = float(found.group(2))
                    hw.spring_length = float(found.group(3))
                hands = _HANDS.search(desc)
                if hands:
                    hw.lh_count = int(hands.group(1))
                    hw.rh_count = int(hands.group(2) or 0)
            elif cat == "spring_comment" and "drum" in desc.lower():
                turns = _TURNS.search(desc)
                drum = _DRUM.search(desc)
                weight = _WEIGHT.search(desc)
                if turns:
                    hw.turns = float(turns.group(1))
                if drum:
                    hw.drum_model = drum.group(1).strip()
                if weight:
                    hw.door_weight = float(weight.group(1))
            elif cat == "shaft" and "coupler" not in desc.lower():
                kind, dia, length = _shaft_kind(desc, part.get("part_number") or "")
                if kind:
                    hw.shaft_kind = kind
                    hw.shaft_diameter = dia
                    hw.shaft_label = desc.strip()
                if length:
                    hw.shaft_length = length
        hw.spring_count = hw.lh_count + hw.rh_count
        info = PartNumberService._get_strut_requirements(
            int(ctx.door_width_in), int(ctx.door_height_in),
        )
        hw.strut_count = int(info.get("count") or 0)
        hw.strut_gauge = info.get("type")
    except Exception:
        logger.warning("Shop hardware lookup failed", exc_info=True)

    hw.drum_diameter = drum_diameter_in(hw.drum_model)
    if hw.wire is None:
        hw.by_factory.append("spring wire, ID, and length")
    if hw.turns is None:
        hw.by_factory.append("spring turns")
    if not hw.drum_model:
        hw.by_factory.append("drum model")
    if hw.drum_diameter is None and hw.drum_model:
        hw.by_factory.append("drum diameter")
    if not hw.shaft_kind:
        hw.by_factory.append("shaft type and diameter")
    if hw.shaft_length is None:
        hw.by_factory.append("shaft length")
    hw.by_factory.extend([
        "end bearing model",
        "center bracket model",
        "bottom bracket model",
        "top fixture model",
        "vertical track bracket model",
        "hinge model",
    ])

    lift = (ctx.lift_type or "standard").lower()
    if lift in ("full_vertical", "vertical"):
        lift_key = "vertical"
    elif lift == "high_lift":
        lift_key = "high_lift"
    else:
        lift_key = "standard"
    hw.high_lift = float(ctx.high_lift_inches or 0) if lift_key == "high_lift" else 0.0
    try:
        track_size = int(float(str(ctx.track_thickness_ga or "2").strip() or 2))
    except ValueError:
        track_size = 2
    if track_size not in (2, 3):
        track_size = 2
    radius = 15 if int(round(ctx.track_radius_in or 15)) != 12 else 12
    hw.track_size = track_size
    hw.track_radius = radius
    try:
        from app.services.shop_drawing_service import calculate_shop_drawing_geometry
        geo = calculate_shop_drawing_geometry(
            door_height=int(ctx.door_height_in),
            door_width=int(ctx.door_width_in),
            track_size=track_size,
            track_radius=radius,
            lift_type=lift_key,
            high_lift_inches=int(hw.high_lift),
            mount_type=ctx.track_mount or "bracket",
            frame_type=ctx.jamb_type or "wood",
            door_type=ctx.door_type or "residential",
            lhr_mount=ctx.lhr_mount or "front",
        )
        hw.headroom = float(geo["headroom_min"])
        hw.backroom = float(geo["backroom"])
        hw.ust = float(geo["ust"])
        hw.floor_to_ust = geo.get("floor_to_ust")
        if hw.floor_to_ust is not None:
            hw.floor_to_ust = float(hw.floor_to_ust)
        hw.vertical_track = float(geo["vertical_track_length"])
        hw.horizontal_track = float(geo["horizontal_track_length"])
    except Exception:
        logger.warning("Track geometry lookup failed", exc_info=True)
        hw.by_factory.append("headroom and backroom")

    if hw.cable_diameter is None and hw.door_weight and hw.drum_model:
        try:
            from app.services.door_calculator_service import door_calculator
            lift_map = {"standard": "standard", "high_lift": "high", "vertical": "vertical"}
            drums = door_calculator._select_drum(
                int(ctx.door_height_in),
                hw.door_weight,
                {"type": lift_map.get(lift_key, "standard"), "radius": radius},
                effective_height=int(ctx.door_height_in + hw.high_lift),
                track_size=track_size,
            )
            if drums is not None:
                hw.cable_diameter = drums.cable_diameter
                hw.cable_length = drums.cable_length
        except Exception:
            logger.debug("Cable lookup failed", exc_info=True)
    if hw.cable_diameter is None:
        hw.by_factory.append("cable diameter")
    return hw
