"""Ship weight for one door line.

Hanging weight comes from DoorCalculatorService (Thermalex panel rates, end
caps, retainers, seals, struts, and the hardware kit). Track, springs,
shaft, drums, bearings, cones, and the operator are added from the JSON
constants. Nothing in this module writes to Business Central. The part-number
mapper used by the door calculator is a local lookup.
"""
from __future__ import annotations

import copy
import json
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.services.door_calculator_service import DOOR_MODEL_WEIGHTS, LIFT_TYPES, door_calculator
from app.services.freight_numbers import D, as_number, pounds

CONSTANTS_PATH = Path(__file__).resolve().parents[2] / "data" / "freight" / "ship_weight_constants.json"


def load_constants(path: Optional[Path] = None) -> dict:
    target = Path(path) if path else CONSTANTS_PATH
    with open(target, encoding="utf-8") as handle:
        return json.load(handle)


def apply_constant_overrides(constants: dict, config: Optional[dict]) -> dict:
    """Settings replace crate, shaft, and operator numbers. The file stays the default."""
    merged = copy.deepcopy(constants)
    if not config:
        return merged
    crate = config.get("crate") or {}
    for key, value in crate.items():
        if key in merged["crate"] and value is not None and not isinstance(merged["crate"][key], dict):
            merged["crate"][key] = value
        elif key == "panel_thickness_in" and isinstance(value, dict):
            merged["crate"]["panel_thickness_in"].update(value)
    shaft = config.get("shaft_lb_per_ft") or {}
    merged["shaft"]["lb_per_ft"].update({key: value for key, value in shaft.items() if value is not None})
    for family, pounds_each in (config.get("operator_lb") or {}).items():
        if family in merged["operators"] and pounds_each is not None:
            merged["operators"][family]["lb"] = pounds_each
    drums = config.get("drum_lb_each") or {}
    merged["drums"]["lb_each"].update({key: value for key, value in drums.items() if value is not None})
    for key in ("bearing_lb_each", "winding_cone_lb_each", "stationary_cone_lb_each", "coupler_lb_each"):
        if config.get(key) is not None:
            merged[key] = config[key]
    return merged


def _lookup_spring_lb_per_in(table: dict, wire, coil) -> Optional[float]:
    if not table or wire is None or coil is None:
        return None
    wire_f = float(wire)
    coil_f = float(coil)
    wire_key = min(table.keys(), key=lambda item: abs(item - wire_f))
    if abs(wire_key - wire_f) > 0.004:
        return None
    coils = table[wire_key]
    coil_key = min(coils.keys(), key=lambda item: abs(item - coil_f))
    if abs(coil_key - coil_f) > 0.05:
        return None
    return float(coils[coil_key])


def _spring_weight(springs, warnings: List[str]) -> Tuple[Decimal, str, int]:
    if springs is None:
        warnings.append("No spring was selected, so spring weight is zero.")
        return D(0), "none", 0
    from app.services.spring_calculator_service import SPRING_WEIGHTS, calculate_spring_weight

    if getattr(springs, "is_duplex", False):
        pairs = int(springs.duplex_pairs or 0) or int(springs.quantity or 0)
        specs = [
            (springs.wire_diameter, springs.coil_diameter, springs.length, pairs),
        ]
        if springs.inner_wire_diameter and springs.inner_length:
            specs.append((
                springs.inner_wire_diameter,
                springs.inner_coil_diameter,
                springs.inner_length,
                pairs,
            ))
    else:
        specs = [(springs.wire_diameter, springs.coil_diameter, springs.length, int(springs.quantity or 0))]

    total = D(0)
    source = "spring-weights.json"
    count = 0
    for wire, coil, length, qty in specs:
        if not qty or not length:
            continue
        count += int(qty)
        per_inch = _lookup_spring_lb_per_in(SPRING_WEIGHTS, wire, coil)
        if per_inch is None:
            each = calculate_spring_weight(float(wire), float(coil), float(length))
            total += D(str(each)) * D(qty)
            source = "formula"
            warnings.append(
                f"Spring {wire} x {coil} is not in spring-weights.json. "
                "Weight uses the steel-density formula."
            )
        else:
            total += D(str(per_inch)) * D(str(length)) * D(qty)
    return total, source, count


def _series_key(series: str, thickness: dict) -> str:
    raw = str(series or "").upper().replace(" ", "").replace("_", "-")
    if raw in thickness:
        return raw
    if raw.endswith("S") and raw[:-1] in thickness:
        return raw[:-1]
    aliases = {"AL-SWD": "AL976-SWD", "ALSWD": "AL976-SWD"}
    mapped = aliases.get(raw)
    if mapped and mapped in thickness:
        return mapped
    return raw


def calculator_model(series: str) -> str:
    raw = str(series or "TX450").upper().replace(" ", "-")
    if raw.endswith("S") and raw[:-1] in DOOR_MODEL_WEIGHTS:
        return raw[:-1]
    return raw


def calculator_lift(door: dict) -> str:
    raw = str(door.get("liftType") or door.get("lift_type") or "standard").lower()
    raw = raw.replace("-", "_").replace(" ", "_")
    if raw in LIFT_TYPES:
        return raw
    if raw in {"lhr", "lhr_front", "lhr_rear", "low_headroom"}:
        return "low_headroom"
    if raw in {"high_lift", "highlift"}:
        return "high_lift"
    if raw == "vertical":
        return "vertical"
    radius = str(door.get("trackRadius") or door.get("track_radius") or "15")
    if radius.startswith("12"):
        return "standard_12"
    return "standard_15"


def _flag(hardware: Optional[dict], key: str, default: bool = True) -> bool:
    if not isinstance(hardware, dict) or key not in hardware:
        return default
    return bool(hardware.get(key))


def _family_from_catalog(token: str, item: Optional[dict]) -> str:
    name = token.lower()
    if item:
        name = f"{item.get('displayName', '')} {token}".lower()
        kind = item.get("type") or ""
        mount = (item.get("mount") or "").lower()
    else:
        kind = ""
        mount = ""
    jackshaft = any(word in name for word in ("jackshaft", "jhdc", "98022", "8500", "lj8900"))
    if jackshaft and (kind == "Commercial" or "jhdc" in name):
        return "commercial_jackshaft"
    if jackshaft:
        return "residential_jackshaft"
    if kind == "Commercial" and mount == "trolley":
        return "commercial_trolley"
    if kind == "Commercial" and (mount == "shaft" or "hoist" in name):
        return "commercial_hoist"
    if kind == "Residential":
        return "residential_trolley"
    if "trolley" in name:
        return "commercial_trolley"
    if "hoist" in name:
        return "commercial_hoist"
    return "unknown"


def operator_weight(operator: Any, chain_hoist: Any, constants: dict) -> Tuple[Optional[str], Decimal]:
    families = constants["operators"]
    token = str(operator or "").strip()
    chain = str(chain_hoist or "none").strip().lower()
    if token in families and token not in {"unknown"}:
        weight = D(families[token]["lb"])
        if chain in {"shaft", "wall"} and token != "chain_hoist":
            weight += D(families["chain_hoist"]["lb"])
            return token, weight
        return token, weight
    if token.upper() in {"", "NONE", "NULL"}:
        if chain in {"shaft", "wall"}:
            return "chain_hoist", D(families["chain_hoist"]["lb"])
        return None, D(0)

    item = None
    try:
        from app.services.operator_service import _load_catalog
        item = next((row for row in _load_catalog() if row["partNumber"] == token), None)
    except Exception:
        item = None
    family = _family_from_catalog(token, item)
    if family not in families:
        family = "unknown"
    weight = D(families[family]["lb"])
    if chain in {"shaft", "wall"}:
        weight += D(families["chain_hoist"]["lb"])
    return family, weight


def _track_weight(track, mount: str, constants: dict) -> Decimal:
    size = str(int(getattr(track, "size", 2) or 2))
    rails = constants["track"]["rail_lb_per_ft"]
    rate = D(rails.get(size) or rails.get("2") or 0)
    vertical = D(getattr(track, "vertical_length", 0) or 0)
    horizontal = D(getattr(track, "horizontal_length", 0) or 0)
    if "vertical" in str(getattr(track, "lift_type", "") or "").lower():
        horizontal = D(constants["track"]["vertical_lift_header_in"])
    rail_lb = rate * (D(2) * (vertical + horizontal)) / D(12)
    angle_lb = D(0)
    if str(mount or "bracket").lower() == "angle":
        extras = constants["track"]["angle_extra_lb_per_ft"]
        angle_lb = D(extras.get(size) or 0) * (D(2) * horizontal) / D(12)
    return rail_lb + angle_lb


def _shaft_weight(shaft, constants: dict) -> Tuple[Decimal, str]:
    if shaft is None:
        return D(0), ""
    rates = constants["shaft"]["lb_per_ft"]
    kind = shaft.shaft_type or "solid"
    rate = D(rates.get(kind) or rates["solid"])
    pieces = int(shaft.pieces or 1)
    if pieces <= 1:
        inches = D(shaft.length or 0)
    else:
        operator_length = shaft.operator_length if shaft.operator_length else shaft.length
        inches = D(shaft.length or 0) * D(pieces - 1) + D(operator_length or 0)
    metal = rate * inches / D(12)
    couplers = D(constants["coupler_lb_each"]) * D(int(shaft.coupler_qty or 0))
    return metal + couplers, kind


def _drum_weight(model: Optional[str], constants: dict) -> Decimal:
    table = constants["drums"]["lb_each"]
    name = (model or "").upper()
    each = D(table.get("default") or 0)
    for key in sorted((key for key in table if key != "default"), key=len, reverse=True):
        if key.upper() in name:
            each = D(table[key])
            break
    return each * D(constants["drums"].get("per_door") or 2)


def _window_request(door: dict, warnings: List[str]) -> Tuple[Optional[str], int]:
    qty = door.get("windowQty", door.get("window_qty")) or 0
    try:
        qty = int(qty or 0)
    except (TypeError, ValueError):
        qty = 0
    panels = door.get("windowPanels") or door.get("window_panels") or {}
    if qty <= 0 and isinstance(panels, dict):
        for entry in panels.values():
            try:
                qty += int((entry or {}).get("qty") or 1)
            except (TypeError, ValueError, AttributeError):
                qty += 1
    window_type = door.get("windowType") or door.get("window_type")
    if qty > 0 and not window_type:
        window_type = "24x12"
        warnings.append("Window weight uses the 24x12 rate because the opening size was not set.")
    return window_type, qty


def _inches(door: dict, *names) -> int:
    for name in names:
        if door.get(name) not in (None, ""):
            return int(round(float(door[name])))
    raise ValueError("door width and height are required")


def _component(value: Decimal) -> Decimal:
    return pounds(value)


def build_door_line(door: dict, constants: dict, line_index: int = 1) -> dict:
    warnings: List[str] = []
    series = door.get("doorSeries") or door.get("door_series") or door.get("doorModel") or "TX450"
    width = _inches(door, "doorWidth", "door_width", "width")
    height = _inches(door, "doorHeight", "door_height", "height")
    try:
        count = int(door.get("doorCount") or door.get("door_count") or door.get("qty") or 1)
    except (TypeError, ValueError):
        count = 1
    count = max(count, 1)

    thickness_map = constants["crate"]["panel_thickness_in"]
    series_id = _series_key(str(series), thickness_map)
    if series_id in thickness_map:
        thickness = D(thickness_map[series_id])
    else:
        thickness = D(constants["crate"]["default_panel_thickness_in"])
        warnings.append(f"Panel thickness for {series} is not in the constants. Using {thickness} in.")

    panel = door_calculator._calculate_panel_config(height, False, False)
    face = 24 if panel.sections_24 else 21 if panel.sections_21 else int(constants["crate"]["default_section_face_in"])
    if panel.sections_24 and panel.sections_21:
        face = 24
    stack = thickness * D(panel.total_sections)

    hardware = door.get("hardware") if isinstance(door.get("hardware"), dict) else {}
    include_tracks = _flag(hardware, "tracks")
    include_springs = _flag(hardware, "springs")
    include_shafts = _flag(hardware, "shafts")
    include_counterbalance = include_springs or include_shafts

    model = calculator_model(str(series))
    door_type = door.get("doorType") or door.get("door_type") or "commercial"
    track_size = int(float(door.get("trackThickness") or door.get("track_thickness") or door.get("trackSize") or 2))
    window_type, window_qty = _window_request(door, warnings)
    high_lift = door.get("highLiftInches", door.get("high_lift_inches"))
    try:
        high_lift = int(high_lift) if high_lift not in (None, "") else None
    except (TypeError, ValueError):
        high_lift = None

    hanging = D(0)
    track_lb = D(0)
    spring_lb = D(0)
    spring_source = "none"
    spring_count = 0
    shaft_lb = D(0)
    shaft_kind = ""
    drum_lb = D(0)
    bearing_lb = D(0)
    cone_lb = D(0)
    calc = None
    try:
        calc = door_calculator.calculate_door(
            door_model=model,
            width_inches=width,
            height_inches=height,
            lift_type=calculator_lift(door),
            track_size=track_size,
            window_type=window_type,
            window_qty=window_qty,
            target_cycles=int(door.get("targetCycles") or door.get("target_cycles") or 10000),
            shaft_type=door.get("shaftType") or door.get("shaft_type") or "auto",
            high_lift_inches=high_lift,
            door_type=door_type,
            glazing_type=door.get("glazingType") or door.get("glazing_type") or "glass",
            glass_pane_type=door.get("glassPaneType") or door.get("glass_pane_type") or "INSULATED",
            include_top_seal=door.get("includeTopSeal", door.get("include_top_seal")),
        )
    except Exception as exc:
        warnings.append(f"Door calculator failed ({exc}). Hanging weight is zero.")

    if calc is not None:
        hanging = D(str(calc.weight.total_weight))
        warnings.extend(list(calc.warnings or []))
        panel = calc.panel_config
        face = 24 if panel.sections_24 else 21 if panel.sections_21 else face
        stack = thickness * D(panel.total_sections)
        if include_tracks and calc.track is not None:
            track_lb = _track_weight(calc.track, door.get("trackMount") or door.get("track_mount") or "bracket", constants)
        if include_springs:
            spring_lb, spring_source, spring_count = _spring_weight(calc.springs, warnings)
        if include_shafts and calc.shaft is not None:
            shaft_lb, shaft_kind = _shaft_weight(calc.shaft, constants)
        if include_counterbalance:
            drum_lb = _drum_weight(calc.drums.model if calc.drums else None, constants)
            couplers = int(calc.shaft.coupler_qty or 0) if calc.shaft is not None else 0
            bearings = 2 + couplers
            bearing_lb = D(constants["bearing_lb_each"]) * D(bearings)
        if include_springs and spring_count:
            cone_lb = (D(constants["winding_cone_lb_each"]) + D(constants["stationary_cone_lb_each"])) * D(spring_count)

    family, operator_lb = operator_weight(
        door.get("operator"),
        door.get("chainHoist") or door.get("chain_hoist"),
        constants,
    )
    if family == "unknown":
        warnings.append("Operator family was not recognized. The unknown-operator weight was used.")

    parts = {
        "hanging_lb": _component(hanging),
        "track_lb": _component(track_lb),
        "springs_lb": _component(spring_lb),
        "shaft_lb": _component(shaft_lb),
        "drums_lb": _component(drum_lb),
        "bearings_lb": _component(bearing_lb),
        "cones_lb": _component(cone_lb),
        "operator_lb": _component(operator_lb),
    }
    product = pounds(sum(parts.values(), D(0)))
    feet = width // 12
    inches = width % 12
    height_feet = height // 12
    height_inches = height % 12
    label = door.get("label") or f"{series} {feet}'{inches}\" x {height_feet}'{height_inches}\""

    return {
        "line": line_index,
        "label": label,
        "series": str(series),
        "width_in": width,
        "height_in": height,
        "qty": count,
        "door_type": door_type,
        "sections": {
            "count": int(panel.total_sections),
            "sections_21": int(panel.sections_21),
            "sections_24": int(panel.sections_24),
            "thickness_in": as_number(pounds(thickness)),
            "face_in": int(face),
            "stack_in": as_number(pounds(stack)),
        },
        "include_shaft": bool(include_shafts),
        "components": {key: as_number(value) for key, value in parts.items()},
        "spring_weight_source": spring_source,
        "shaft_type": shaft_kind,
        "operator_family": family,
        "product_weight_lb": as_number(product),
        "line_product_weight_lb": as_number(pounds(product * D(count))),
        "warnings": warnings,
    }


def door_units(line: dict) -> List[dict]:
    units = []
    for copy_index in range(int(line["qty"])):
        units.append({
            "line": line["line"],
            "label": line["label"] if line["qty"] == 1 else f"{line['label']} ({copy_index + 1} of {line['qty']})",
            "width_in": line["width_in"],
            "section_face_in": line["sections"]["face_in"],
            "stack_in": line["sections"]["stack_in"],
            "product_weight_lb": line["product_weight_lb"],
            "include_shaft": line["include_shaft"],
        })
    return units
