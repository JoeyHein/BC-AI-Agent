"""Resolve a replacement section from the answers a customer can give.

Exactly one stocked steel section part is a resolution. Anything else is
a staff review. The price on a resolution is the item-card list price.

What this can resolve
---------------------
Kanata (PN65), Craft (PN95), TX380 (PN35), TX450 (PN45/PN46), TX450-20
(PN47/PN48), TX500 (PN55/PN56), TX500-20 (PN57/PN58), and TX760 (PN75/PN76),
when the series, thickness, height, width, colour, and design all match a
single catalog part number. End caps follow the configurator: wider than
16 feet is a double end cap. Craft Muskoka top is the flush section,
intermediate and bottom are the two Muskoka stamps.

What this will not guess
-------------------------
- Series "not sure", or a thickness that does not belong to the series.
- A colour or design the part-number map does not encode.
- A section height the series does not use (Craft is 28 or 32 inches;
  the other series here are 21 or 24).
- A width that is not stocked. The closest wider section is not sold
  in its place.
- A section the customer says has a window. The steel section part
  number does not include the glass kit, and the kit needs a size this
  form does not ask for, so that request is one review, not two parts.
- Aluminum and full-view sections (AL976, PN10, PN12, PN97).
- Kanata Executive. It is not a separate model in the part-number map.
"""
from __future__ import annotations

from typing import Any, Callable, Optional

from app.services.bc_part_number_mapper import DoorModel, EndCapType, get_bc_mapper
from app.services.quote_price_overrides import card_list_price

SERIES = {
    "KANATA": {
        "application": "residential",
        "model": DoorModel.KANATA,
        "thickness": "1-3/4",
        "gauge": "standard",
        "heights": (21, 24),
        "stamps": ("FLUSH", "SH", "BC", "TRAFALGAR", "SHXL", "BCXL"),
    },
    "CRAFT": {
        "application": "residential",
        "model": DoorModel.CRAFT,
        "thickness": "1-3/4",
        "gauge": "standard",
        "heights": (28, 32),
        "stamps": ("FLUSH", "DENISON", "GRANVILLE", "MUSKOKA"),
    },
    "TX380": {
        "application": "commercial",
        "model": DoorModel.TX380,
        "thickness": "1-1/2",
        "gauge": "standard",
        "heights": (21, 24),
        "stamps": ("FLUSH", "UDC"),
    },
    "TX450": {
        "application": "commercial",
        "model": DoorModel.TX450,
        "thickness": "1-3/4",
        "gauge": "standard",
        "heights": (21, 24),
        "stamps": ("FLUSH", "UDC", "V GROOVE"),
    },
    "TX450-20": {
        "application": "commercial",
        "model": DoorModel.TX450_20,
        "thickness": "1-3/4",
        "gauge": "20",
        "heights": (21, 24),
        "stamps": ("FLUSH", "UDC", "V GROOVE"),
    },
    "TX500": {
        "application": "commercial",
        "model": DoorModel.TX500,
        "thickness": "2",
        "gauge": "standard",
        "heights": (21, 24),
        "stamps": ("FLUSH", "UDC"),
    },
    "TX500-20": {
        "application": "commercial",
        "model": DoorModel.TX500_20,
        "thickness": "2",
        "gauge": "20",
        "heights": (21, 24),
        "stamps": ("FLUSH", "UDC"),
    },
    "TX760": {
        "application": "commercial",
        "model": DoorModel.TX760,
        "thickness": "3",
        "gauge": "standard",
        "heights": (21, 24),
        "stamps": ("FLUSH", "MICRO GROOVE"),
    },
}

POSITIONS = ("bottom", "intermediate", "top")
NOT_SURE = {"", "not sure", "not_sure", "unsure", "unknown"}


def finder_options() -> dict:
    """Choices the form can offer. They come from the part-number map."""
    colors = sorted(get_bc_mapper().COLOR_CODES)
    return {
        "applications": ["residential", "commercial"],
        "series": [
            {
                "id": key,
                "application": spec["application"],
                "thickness": spec["thickness"],
                "gauge": spec["gauge"],
                "heights": list(spec["heights"]),
                "designs": list(spec["stamps"]),
            }
            for key, spec in SERIES.items()
        ],
        "thicknesses": ["1-1/2", "1-3/4", "2", "3"],
        "gauges": ["standard", "20"],
        "colors": colors,
        "positions": list(POSITIONS),
        "gaps": [
            "Aluminum and full-view sections are not built from these answers.",
            "Kanata Executive is not a separate series in the part-number map.",
            "A section with a window is not one part: the glass kit is separate and this form does not ask its size.",
            "An unstocked width is not replaced with a different width.",
        ],
    }


def _text(value: Any) -> str:
    return str(value or "").strip()


def _color_name(value: Any) -> str:
    return _text(value).replace("_", " ").upper()


def _stamp_for(series_id: str, design: str, position: str) -> Optional[str]:
    """Craft's top section is always flush, for every design.

    Muskoka then splits the other two sections into intermediate and bottom.
    """
    design_name = _text(design).upper()
    if series_id == "CRAFT" and position == "top":
        return "FLUSH"
    if series_id == "CRAFT" and design_name == "MUSKOKA":
        if position == "intermediate":
            return "MUSKOKA_INTERMEDIATE"
        if position == "bottom":
            return "MUSKOKA_BOTTOM"
        return None
    return design_name


def _end_cap_choice(value: Any) -> Optional[EndCapType]:
    text = _text(value).lower().replace("-", " ")
    if text in {"single", "sec", "single end cap", "single end caps"}:
        return EndCapType.SINGLE
    if text in {"double", "dec", "double end cap", "double end caps"}:
        return EndCapType.DOUBLE
    return None


def _shares_one_prefix(series_id: str) -> bool:
    return series_id in {"KANATA", "CRAFT"}


def _stocked(mapper, spec, width_feet, height, color, stamp, end_cap) -> bool:
    try:
        part = mapper.get_panel_part_number(
            model=spec["model"],
            width_feet=width_feet,
            height_inches=height,
            color=color,
            end_cap_type=end_cap,
            stamp=stamp,
            allow_width_substitute=False,
        )
    except ValueError:
        return False
    return not part.notes and part.part_number in mapper.bc_items


def _resolve_end_cap(series_id, spec, answers, mapper, width_feet, height, color, stamp):
    """Return (end cap, review reason).

    Kanata and Craft use one prefix for both end caps, so the question is
    skipped. Other series ask single, double, or not sure. Not sure goes to
    staff when both versions are stocked at that width.
    """
    if _shares_one_prefix(series_id):
        return EndCapType.SINGLE, None
    chosen = _end_cap_choice(answers.get("end_caps"))
    if chosen is not None:
        return chosen, None
    text = _text(answers.get("end_caps")).lower()
    if text not in NOT_SURE and text not in {"", "not sure"}:
        return None, "End caps must be single, double, or not sure."
    single = _stocked(mapper, spec, width_feet, height, color, stamp, EndCapType.SINGLE)
    double = _stocked(mapper, spec, width_feet, height, color, stamp, EndCapType.DOUBLE)
    if single and double:
        return None, (
            "Both single and double end caps are stocked at this width. "
            "Say which hinges the section uses, or leave it for staff."
        )
    if double and not single:
        return EndCapType.DOUBLE, None
    return EndCapType.SINGLE, None


def resolve_section(
    answers: dict,
    list_price_lookup: Optional[Callable[[str], Optional[float]]] = None,
) -> dict:
    """Return a resolved section or the reasons it has to be reviewed."""
    answers = answers or {}
    reasons: list[str] = []
    lookup = list_price_lookup or card_list_price

    application = _text(answers.get("application")).lower()
    series_raw = _text(answers.get("series"))
    series_id = series_raw.upper().replace(" ", "")
    if series_id == "TX45020":
        series_id = "TX450-20"
    if series_id == "TX50020":
        series_id = "TX500-20"
    thickness = _text(answers.get("thickness"))
    gauge_raw = _text(answers.get("gauge")).lower()
    position = _text(answers.get("position")).lower()
    windows = answers.get("windows")
    try:
        quantity = int(answers.get("quantity") or 0)
    except (TypeError, ValueError):
        quantity = 0
    try:
        height = int(answers.get("section_height") or 0)
    except (TypeError, ValueError):
        height = 0
    try:
        width_feet = int(answers.get("width_feet"))
        width_inches = int(answers.get("width_inches") or 0)
    except (TypeError, ValueError):
        width_feet = -1
        width_inches = -1

    if application not in ("residential", "commercial"):
        reasons.append("Application must be residential or commercial.")
    if series_raw.lower() in NOT_SURE or series_id not in SERIES:
        reasons.append("Door series is not one this finder can build. It was not guessed.")
        spec = None
    else:
        spec = SERIES[series_id]
        if spec["application"] != application and application in ("residential", "commercial"):
            reasons.append(f"{series_id} is a {spec['application']} series.")
        if thickness and thickness != spec["thickness"]:
            reasons.append(
                f"{series_id} is {spec['thickness']} inch, not {thickness} inch."
            )
        elif not thickness:
            reasons.append("Door thickness is required.")
        gauge = gauge_raw or spec["gauge"]
        if gauge not in ("standard", "20"):
            reasons.append("Gauge must be standard or 20.")
        elif gauge != spec["gauge"]:
            reasons.append(f"{series_id} is {spec['gauge']} gauge, not {gauge}.")
        if height not in spec["heights"]:
            reasons.append(
                f"{series_id} sections are {', '.join(str(h) for h in spec['heights'])} inches."
            )
        design = _text(answers.get("design")).upper()
        if design not in spec["stamps"]:
            reasons.append(f"{design or 'That design'} is not a {series_id} texture.")
    if position not in POSITIONS:
        reasons.append("Section position must be bottom, intermediate, or top.")
    if windows is True:
        reasons.append(
            "A section with a window is the section plus a glass kit. "
            "Window size is not on this form, so this is not one part."
        )
    elif windows is not False:
        reasons.append("Say whether the section has a window.")
    if quantity < 1 or quantity > 100:
        reasons.append("Quantity must be from 1 to 100.")
    if width_feet < 0 or not (0 <= width_inches <= 11) or width_feet * 12 + max(width_inches, 0) <= 0:
        reasons.append("Door width must be feet and inches.")

    if reasons or spec is None:
        return {
            "status": "review",
            "part_number": None,
            "description": None,
            "list_price": None,
            "quantity": quantity if quantity > 0 else None,
            "reasons": reasons,
        }

    stamp = _stamp_for(series_id, answers.get("design"), position)
    if not stamp:
        return {
            "status": "review",
            "part_number": None,
            "description": None,
            "list_price": None,
            "quantity": quantity,
            "reasons": ["Craft Muskoka needs a top, intermediate, or bottom position."],
        }

    total_inches = width_feet * 12 + width_inches
    color = _color_name(answers.get("color"))
    mapper = get_bc_mapper()
    if color not in mapper.COLOR_CODES:
        return {
            "status": "review",
            "part_number": None,
            "description": None,
            "list_price": None,
            "quantity": quantity,
            "reasons": [f"Colour {color or '(blank)'} is not on the section colour map."],
        }

    end_cap, end_cap_reason = _resolve_end_cap(
        series_id, spec, answers, mapper, total_inches / 12, height, color, stamp,
    )
    if end_cap_reason:
        return {
            "status": "review",
            "part_number": None,
            "description": None,
            "list_price": None,
            "quantity": quantity,
            "reasons": [end_cap_reason],
        }

    try:
        part = mapper.get_panel_part_number(
            model=spec["model"],
            width_feet=total_inches / 12,
            height_inches=height,
            color=color,
            end_cap_type=end_cap,
            stamp=stamp,
            allow_width_substitute=False,
        )
    except ValueError as exc:
        return {
            "status": "review",
            "part_number": None,
            "description": None,
            "list_price": None,
            "quantity": quantity,
            "reasons": [str(exc)],
        }

    if part.notes or part.part_number not in mapper.bc_items:
        return {
            "status": "review",
            "part_number": None,
            "description": part.description,
            "list_price": None,
            "quantity": quantity,
            "candidate_part_number": part.part_number,
            "reasons": [
                part.notes
                or f"{part.part_number} is not a stocked section. A different width was not substituted."
            ],
        }

    try:
        price = lookup(part.part_number)
    except Exception:
        price = None
    if price is None or price <= 0:
        return {
            "status": "review",
            "part_number": part.part_number,
            "description": part.description,
            "list_price": None,
            "quantity": quantity,
            "reasons": [f"{part.part_number} has no item-card list price."],
        }

    description = part.description
    design_name = _text(answers.get("design")).upper()
    if series_id == "CRAFT" and design_name == "MUSKOKA":
        if position == "top":
            description = f"{description}, top section"
        elif position == "intermediate":
            description = description.replace(
                "MUSKOKA_INTERMEDIATE", "MUSKOKA INTERMEDIATE, intermediate section",
            )
        elif position == "bottom":
            description = description.replace(
                "MUSKOKA_BOTTOM", "MUSKOKA BOTTOM, bottom section",
            )
    else:
        description = f"{description}, {position} section"
    return {
        "status": "resolved",
        "part_number": part.part_number,
        "description": description,
        "list_price": float(price),
        "quantity": quantity,
        "reasons": [],
    }
