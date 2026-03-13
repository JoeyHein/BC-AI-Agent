"""
Shop Drawing Geometry Service
Encodes the Thermalex Door Weight Calculator spreadsheet formulas
for generating accurate framing drawings and side elevations.

All measurements in inches unless noted.
All offsets are measured from top of door opening unless noted.
"""

import math
import logging

logger = logging.getLogger(__name__)


def calculate_shop_drawing_geometry(
    door_height: int,
    door_width: int,
    track_size: int = 2,          # 2 or 3
    track_radius: int = 15,       # 12 or 15
    lift_type: str = "standard",  # standard, high_lift, vertical, lhr_front, lhr_rear, low_headroom
    high_lift_inches: int = 0,
    mount_type: str = "bracket",  # bracket or angle
    frame_type: str = "steel",    # steel or wood
    door_type: str = "residential",
) -> dict:
    """
    Calculate all shop drawing geometry from the Thermalex dimension tables.

    Returns a dict with all dimensions needed for framing and side elevation drawings.
    """
    H = door_height
    W = door_width
    HL = high_lift_inches or 0

    # Normalize lift_type aliases
    if lift_type == "low_headroom":
        lift_type = "lhr_rear"  # default LHR is rear mount

    # ---- Look up dimensions from Thermalex tables ----
    if track_size == 2:
        dims = _get_2inch_track_dims(H, track_radius, lift_type, HL)
    else:
        dims = _get_3inch_track_dims(H, track_radius, lift_type, HL)

    ust = dims["ust"]                     # Underside of Track above door opening
    cl_shaft_offset = dims["cl_shaft"]    # CL shaft above door opening
    headroom_min = dims["headroom_min"]   # Minimum headroom above door opening
    backroom = dims["backroom"]           # Total backroom depth
    sideroom_angle = dims["sideroom_angle"]
    sideroom_bracket = dims["sideroom_bracket"]

    # Pick sideroom based on mount type
    sideroom = sideroom_angle if mount_type == "angle" else sideroom_bracket

    # Center post width (both sides combined)
    center_post = 2 * sideroom

    # Absolute floor-referenced dimensions
    floor_to_ust = H + ust if lift_type not in ("vertical",) else None
    floor_to_cl_shaft = H + cl_shaft_offset
    floor_to_ceiling_min = H + headroom_min

    # Track lengths
    if lift_type == "vertical":
        vertical_track_length = H + cl_shaft_offset  # track goes full height
        horizontal_track_length = 0
        curve_type = "none"
    elif lift_type in ("high_lift",):
        vertical_track_length = H + HL
        horizontal_track_length = _calc_horizontal_track(H, HL, track_radius, lift_type)
        curve_type = "quarter"
    elif lift_type in ("lhr_front", "lhr_rear"):
        vertical_track_length = H
        horizontal_track_length = H + 18 - track_radius
        curve_type = "low_headroom"
    else:
        # Standard
        vertical_track_length = H
        horizontal_track_length = _calc_horizontal_track(H, 0, track_radius, "standard")
        curve_type = "quarter"

    # Frame width
    frame_width_inches = 3 if frame_type == "steel" else 3.5

    # Labels
    track_type_label = _get_track_type_label(lift_type)
    radius_label = f'{track_radius}" RADIUS' if lift_type not in ("vertical", "lhr_front", "lhr_rear") else ""
    lift_label = lift_type.replace("_", " ").upper()

    return {
        # Raw offsets (from top of door opening)
        "ust": ust,
        "cl_shaft": cl_shaft_offset,
        "headroom_min": headroom_min,
        "backroom": backroom,
        "sideroom": sideroom,
        "sideroom_angle": sideroom_angle,
        "sideroom_bracket": sideroom_bracket,
        "center_post": center_post,

        # Floor-referenced absolute dimensions
        "floor_to_ust": floor_to_ust,
        "floor_to_cl_shaft": floor_to_cl_shaft,
        "floor_to_ceiling_min": floor_to_ceiling_min,

        # Track geometry
        "vertical_track_length": vertical_track_length,
        "horizontal_track_length": horizontal_track_length,
        "track_radius": track_radius,
        "track_size": track_size,
        "curve_type": curve_type,

        # Frame
        "frame_width_inches": frame_width_inches,
        "frame_type": frame_type,

        # Door dimensions (echo back for convenience)
        "door_height": H,
        "door_width": W,
        "high_lift_inches": HL,
        "lift_type": lift_type,
        "mount_type": mount_type,

        # Labels
        "track_type_label": track_type_label,
        "radius_label": radius_label,
        "lift_label": lift_label,
    }


def _get_2inch_track_dims(H: int, radius: int, lift_type: str, HL: int) -> dict:
    """2" track dimension lookup from Thermalex tables."""

    if lift_type == "vertical":
        return {
            "ust": 0,  # N/A for vertical
            "cl_shaft": H + 12,  # relative to floor, but we store as offset from door top
            "headroom_min": H + 18,  # same
            "backroom": 18,
            "sideroom_angle": 3.25,
            "sideroom_bracket": 3.75,
        }
        # Note: for VL, cl_shaft and headroom_min are H+12 and H+18 from floor,
        # which means offsets from top of door = 12 and 18

    if lift_type == "lhr_front":
        return {
            "ust": 0,
            "cl_shaft": 6.5,
            "headroom_min": 10,
            "backroom": H + 18,
            "sideroom_angle": 6.5,
            "sideroom_bracket": 5.5,
        }

    if lift_type == "lhr_rear":
        return {
            "ust": 0,
            "cl_shaft": 2,
            "headroom_min": 5.5,
            "backroom": H + 18,
            "sideroom_angle": 6.5,
            "sideroom_bracket": 5.5,
        }

    if lift_type == "high_lift":
        if HL <= 54:
            return {
                "ust": HL,
                "cl_shaft": HL + 6,
                "headroom_min": HL + 10,
                "backroom": H - HL + 30,
                "sideroom_angle": 3.25,
                "sideroom_bracket": 3.75,
            }
        else:  # HL <= 120
            return {
                "ust": HL,
                "cl_shaft": HL + 6.5,
                "headroom_min": HL + 11.5,
                "backroom": H - HL + 30,
                "sideroom_angle": 3.25,
                "sideroom_bracket": 3.75,
            }

    # Standard lift
    if radius == 12 and H <= 216:
        return {
            "ust": 3.5,
            "cl_shaft": 9.5,
            "headroom_min": 12.75,
            "backroom": H + 18,
            "sideroom_angle": 3.25,
            "sideroom_bracket": 3.75,
        }
    elif radius == 15 and H <= 216:
        return {
            "ust": 6.5,
            "cl_shaft": 12.5,
            "headroom_min": 15.75,
            "backroom": H + 18,
            "sideroom_angle": 3.25,
            "sideroom_bracket": 3.75,
        }
    else:
        # Default to R15 for H > 216 (shouldn't happen for 2" track typically)
        return {
            "ust": 6.5,
            "cl_shaft": 12.5,
            "headroom_min": 15.75,
            "backroom": H + 18,
            "sideroom_angle": 3.25,
            "sideroom_bracket": 3.75,
        }


def _get_3inch_track_dims(H: int, radius: int, lift_type: str, HL: int) -> dict:
    """3" track dimension lookup from Thermalex tables."""

    if lift_type == "vertical":
        return {
            "ust": 0,
            "cl_shaft": H + 12,
            "headroom_min": H + 18,
            "backroom": 18,
            "sideroom_angle": 3.5,
            "sideroom_bracket": 4.25,
        }

    if lift_type == "lhr_front":
        return {
            "ust": 0,
            "cl_shaft": 7.5,
            "headroom_min": 11,
            "backroom": H + 18,
            "sideroom_angle": 6.75,
            "sideroom_bracket": 6.25,
        }

    if lift_type == "lhr_rear":
        return {
            "ust": 0,
            "cl_shaft": 3,
            "headroom_min": 7,
            "backroom": H + 18,
            "sideroom_angle": 6.75,
            "sideroom_bracket": 6.25,
        }

    if lift_type == "high_lift":
        if HL <= 54:
            return {
                "ust": HL,
                "cl_shaft": HL + 7,
                "headroom_min": HL + 11,
                "backroom": H - HL + 30,
                "sideroom_angle": 3.5,
                "sideroom_bracket": 4.25,
            }
        else:  # HL > 54
            return {
                "ust": HL,
                "cl_shaft": HL + 7.5,
                "headroom_min": HL + 14,
                "backroom": H - HL + 30,
                "sideroom_angle": 3.5,
                "sideroom_bracket": 4.25,
            }

    # Standard lift
    if H <= 216:
        return {
            "ust": 7.5,
            "cl_shaft": 14.5,
            "headroom_min": 17.75,
            "backroom": H + 18,
            "sideroom_angle": 3.5,
            "sideroom_bracket": 4.25,
        }
    else:  # H > 216
        return {
            "ust": 7.5,
            "cl_shaft": 15.5,
            "headroom_min": 20.5,
            "backroom": H + 18,
            "sideroom_angle": 3.5,
            "sideroom_bracket": 4.25,
        }


def _calc_horizontal_track(H: int, HL: int, radius: int, lift_type: str) -> float:
    """Calculate horizontal track length."""
    if lift_type == "vertical":
        return 0
    elif lift_type == "high_lift":
        return H - HL + 18 - radius
    else:
        # Standard: backroom minus the radius curve
        return H + 18 - radius


def _get_track_type_label(lift_type: str) -> str:
    labels = {
        "standard": "STANDARD LIFT TRACKS",
        "high_lift": "HIGH LIFT TRACKS",
        "vertical": "FULL VERTICAL LIFT TRACKS",
        "lhr_front": "LOW HEADROOM FRONT MOUNT TRACKS",
        "lhr_rear": "LOW HEADROOM REAR MOUNT TRACKS",
    }
    return labels.get(lift_type, "STANDARD LIFT TRACKS")
