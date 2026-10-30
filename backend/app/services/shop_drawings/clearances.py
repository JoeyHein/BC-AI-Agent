"""Thermalex clearance lookup for shop drawings.

Headroom is the only value we adjust: add 1/4 inch as a safety buffer, then
round UP to the next 1/2 inch. 17.75 becomes 18, 35 becomes 35.5, 85 becomes
85.5. Shaft centreline, underside of track, backroom, and sideroom stay on
the table.

The Thermalex tables live in ``shop_drawing_service``. For full vertical the
table stores shaft centreline as ``H + 12`` in the offset field, and the
floor dimension is ``H + that field`` (2H + 12), which is what the sample
sheets print. Headroom for vertical is stored as the printed figure ``H + 18``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

from app.services.shop_drawing_service import (
    _get_2inch_track_dims,
    _get_3inch_track_dims,
)


def round_up_half_inch(value: float) -> float:
    """Smallest multiple of 1/2 inch that is >= value."""
    return math.ceil(float(value) * 2 - 1e-9) / 2.0


def printed_headroom(table_value: float) -> float:
    """Table headroom plus a 1/4 inch buffer, rounded up to the next 1/2 inch.

    17.75 → 18, 35 → 35.5, 85 → 85.5, 186 → 186.5.
    """
    return round_up_half_inch(float(table_value) + 0.25)


@dataclass(frozen=True)
class Clearances:
    lift: str
    track_size: int
    radius: int
    high_lift_in: float
    headroom_table_in: float
    headroom_in: float
    ust_offset_in: float
    ust_from_floor_in: Optional[float]
    backroom_in: float
    cl_shaft_from_floor_in: float
    sideroom_in: float
    mount: str


def lookup_clearances(
    door_height_in: float,
    *,
    track_size: int,
    radius: int,
    lift: str,
    high_lift_in: float = 0,
    mount: str = "bracket",
) -> Clearances:
    """Return printed clearances for one door.

    ``lift`` is one of standard, high_lift, vertical, lhr_front, lhr_rear.
    ``mount`` is "bracket" or "angle".
    """
    height = int(round(door_height_in))
    hl = int(round(high_lift_in or 0))
    track = 3 if int(track_size) == 3 else 2
    rad = 12 if int(radius) == 12 else 15
    if track == 2:
        dims = _get_2inch_track_dims(height, rad, lift, hl)
    else:
        dims = _get_3inch_track_dims(height, rad, lift, hl)

    table_hr = float(dims["headroom_min"])
    # Both standard (offset above the opening) and vertical (H+18, already
    # the printed figure) are stored in this field. Do not add H again.
    headroom = printed_headroom(table_hr)

    ust_offset = float(dims["ust"])
    show_ust = lift in ("standard", "high_lift") and ust_offset > 0
    ust_floor = (height + ust_offset) if show_ust else None

    sideroom_key = "sideroom_angle" if mount == "angle" else "sideroom_bracket"
    return Clearances(
        lift=lift,
        track_size=track,
        radius=rad,
        high_lift_in=float(hl if lift == "high_lift" else 0),
        headroom_table_in=table_hr,
        headroom_in=headroom,
        ust_offset_in=ust_offset,
        ust_from_floor_in=ust_floor,
        backroom_in=float(dims["backroom"]),
        cl_shaft_from_floor_in=height + float(dims["cl_shaft"]),
        sideroom_in=float(dims[sideroom_key]),
        mount=mount,
    )
