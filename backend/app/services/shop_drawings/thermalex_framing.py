"""Pads, jamb and extension for a TX-series framing detail.

The Thermalex weight workbook (``backend/thermalex_weight_calc.xlsx``) is the
source for track clearances, spring assembly length, and the geometric pad
spans printed on its framing sheets. Joey's rule decides how many pads a
door gets and where they sit: that comes from the quote's springs, not from
splitting the door width into equal parts.

Where those two disagree, the drawing follows Joey. The workbook spans stay
here so tests can show the difference. ``DIFFERENCES_FOR_JOEY`` is the list
the PR summary is written from.

TODO(Ola): the head-jamb extrusion is not redrawn. Sideroom uses the values
already in ``real_profiles`` (3.75 in. wood, 3.5 in. steel, matching the
11 Nov 2026 jamb sheet). The workbook's 75 mm × 6 mm note is the minimum
steel face, not a new profile.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional, Sequence

from app.services.shop_drawings.real_profiles import parse_tx_series, real_sideroom_in
from app.services.track_defaults import quoted_track_radius, resolve_track_thickness

# Spring Ass.Length: stationary cone + winding cone, inches.
CONE_ALLOWANCE_IN = 3.0
# Spring Ass.Length B9 / Spring Ass.Length 2 B8.
SPACE_BETWEEN_SPRINGS_IN = 6.0
# B15: length available on the shaft is door width minus 6 in.
END_CLEARANCE_IN = 6.0
# B16 warns when the free length per spring is under 3 in.
MIN_FREE_PER_SPRING_IN = 3.0
# Framing sheets: "min 8\"" between pads, "min 10\" (Typ.)" ,
# tandem sheets use "min 22\" (Typ.)".
MIN_PAD_GAP_IN = 8.0
MIN_JAMB_CLEAR_IN = 10.0
MIN_JAMB_CLEAR_TANDEM_IN = 22.0
# Track B.O.M. V8. Tandem sheets add this to shaft CL and headroom.
TANDEM_SHAFT_OFFSET_IN = 12.0
# Every framing sheet: electric operator plate, if required.
OPERATOR_PLATE_W_IN = 20.0
OPERATOR_PLATE_H_IN = 30.0
# Sheet note: steel frame face, not the sideroom.
JAMB_FACE_MIN_MM = 75.0
JAMB_FACE_MIN_IN = 6.0 / 25.4  # 6 mm is 1/4 in. on the sheet
# Input Data E18: extra center drums once the door is over 2,200 lb.
CENTER_PICKUP_WEIGHT_LB = 2200.0
CENTER_PICKUP_EACH_LB = 1100.0

# 'Spring Ass.Length' column F, the width the assembly formula multiplies.
# These are not the axial widths in door_calculator_service.DRUM_TABLE.
# See DIFFERENCES_FOR_JOEY.
WORKBOOK_DRUM_WIDTH_IN = {
    "D400-96": 1.64,
    "D400-144": 2.63,
    "D525-216": 3.62,
    "D800-384": 5.26,
    "D400-54": 3.03,
    "D525-54": 3.66,
    "D575-120": 3.71,
    "D6375-164": 6.09,
    "D800-120": 5.22,
    "D850-132": 3.33,
    "850-132": 3.33,
    "D1100-216": 4.29,
    "1100-216": 4.29,
    "D1350-336": 6.75,
    "1350-336": 6.75,
}

# Job-specific overrides on the sheets. Not used to place pads.
WORKBOOK_2PAD_1_COUPLER_SIDE_IN = 73.0
WORKBOOK_4PAD_CENTER_GAP_IN = 8.0

TX_THICKNESS_MM = (38.0, 45.0, 50.0)

DIFFERENCES_FOR_JOEY = (
    "Pad count and position follow the quote's springs, not the sheet's equal splits of door width.",
    "2 springs (1 LH + 1 RH meeting at the center coupler) → 1 center pad. "
    "The workbook's 2-pad sheets are a two-bearing shaft layout and are not used for that setup.",
    "4 springs (2 LH + 2 RH) → 3 pads: the center coupler, plus a pad at the outer end of each inner spring. "
    "The 3-pad sheet instead spaces those pads at W/4.",
    "3 springs → 3 pads and 5 springs → 5 pads. The side with fewer springs does not share the center bracket, "
    "so each of its springs has its own pad. This is the odd-count rule and needs Joey's confirmation.",
    "6 springs (3 LH + 3 RH) → 5 pads: the two inner springs share the center pad, and each extra spring adds a pad.",
    "A nested duplex spring shares the outer spring's anchor and does not add a pad. "
    "A 4-spring duplex (2 pairs) is therefore 1 pad, which is not the same as 4 springs in series.",
    "A door with only one wind gets one centered pad. Needs Joey's confirmation.",
    "Tandem shafts add 12 in. to the headroom and draw a second shaft centerline. "
    "The pads stay on one plan. Needs Joey's confirmation if the upper shaft wants its own pads.",
    "Center-pickup drums (door weight over 2,200 lb) are counted in the assembly length and noted on the sheet. "
    "They do not add a pad. The 5-pad workbook sheet draws a center drum between two couplers.",
    "The 2-pad, 1-coupler sheet hardcodes a 73 in. side span for one job. That number is not a general rule.",
    "The 4-pad sheet hardcodes an 8 in. center gap, so its spans do not add up to the door width unless the "
    "center shaft is also 8 in. That gap is not used to place pads.",
    "Workbook drum Width cells disagree with the axial drum widths the quote engine already uses "
    "(D525-216 is 3.62 in. on the sheet and 5.5 in. in the shaft-fit table). "
    "Assembly length uses the workbook width. Joey should confirm which number is the axial drum.",
    "TODO(Ola): the head-jamb extrusion is not drawn. Sideroom is the existing profile value "
    "(3.75 in. wood, 3.5 in. steel). The sheet's 75 mm × 1/4 in. note is the minimum steel face.",
    "The workbook never gives a pad plate width or height, only minimum clearances "
    "(8 in. between pads, 10 in. typical, 22 in. on tandem). "
    "Pads are marks at the anchor. Plate size is waiting on Ola.",
)


def is_workbook_tx_series(series: Optional[str]) -> bool:
    """TX380 / TX450 / TX500, including the -20 faces. Other series fall back."""
    parsed = parse_tx_series(series or "")
    if parsed is None:
        return False
    thickness_mm, _suffix = parsed
    return thickness_mm in TX_THICKNESS_MM


def excel_ceiling(number: float, significance: float) -> float:
    """Excel CEILING for a positive number and significance."""
    if significance == 0:
        return 0.0
    return math.ceil((number / significance) - 1e-9) * significance


def center_shaft_length(door_width_in: float, coupler_qty: int) -> float:
    """Input Data I15.

    Coupler qty 2 → CEILING(W/3, 1). Coupler qty 3 → CEILING(W/4, 0.5).
    One coupler or none → 0. The 2-pad / 4-pad / 5-pad sheets use this as
    the center shaft between the outer spans.
    """
    if coupler_qty == 2:
        return excel_ceiling(door_width_in / 3.0, 1.0)
    if coupler_qty >= 3:
        return excel_ceiling(door_width_in / 4.0, 0.5)
    return 0.0


def center_pickup_count(door_weight_lb: float) -> int:
    """Input Data E18. Extra center drums when the door weighs more than 2,200 lb."""
    if door_weight_lb is None or door_weight_lb <= CENTER_PICKUP_WEIGHT_LB:
        return 0
    return int(math.ceil(door_weight_lb / CENTER_PICKUP_EACH_LB - 1e-9)) - 2


def installed_length(wire: float, turns: float, cut_length: float) -> float:
    """Spring Ass.Length B33: wire × turns + cut length + 3 in. cones."""
    return float(wire) * float(turns) + float(cut_length) + CONE_ALLOWANCE_IN


def assembly_length(
    wire: float,
    turns: float,
    cut_length: float,
    spring_count: int,
    drum_width: float,
    *,
    space_between: float = SPACE_BETWEEN_SPRINGS_IN,
    center_pickups: int = 0,
) -> float:
    """Spring Ass.Length B13.

    (wire × turns + 3 + cut length) × springs
    + (springs − 1) × space between springs
    + drum width × (2 + center pickups)
    """
    count = int(spring_count)
    if count <= 0:
        return 0.0
    one = installed_length(wire, turns, cut_length)
    return one * count + (count - 1) * space_between + float(drum_width) * (2 + int(center_pickups))


def workbook_drum_width(drum_model: Optional[str]) -> Optional[float]:
    if not drum_model:
        return None
    return WORKBOOK_DRUM_WIDTH_IN.get(str(drum_model).strip())


@dataclass(frozen=True)
class SpringSpec:
    """One torsion spring from the quote.

    ``nested`` is a duplex inner spring. It occupies the outer spring's
    station and does not get its own pad. Springs of one wind are ordered
    inner (closest to the coupler) first.
    """

    wind: str
    wire: float
    turns: float
    cut_length: float
    nested: bool = False
    coil: float = 0.0

    @property
    def hand(self) -> str:
        token = (self.wind or "").upper().replace(" ", "")
        if token.startswith("L"):
            return "LH"
        if token.startswith("R"):
            return "RH"
        return token

    @property
    def length_in(self) -> float:
        return installed_length(self.wire, self.turns, self.cut_length)


@dataclass(frozen=True)
class SpringPad:
    """A spring anchor. x is inches from the door centerline, left negative."""

    role: str  # "center" or "anchor"
    x_from_center_in: float
    wind: str
    label: str

    def x_from_left_jamb(self, door_width_in: float) -> float:
        return door_width_in / 2.0 + self.x_from_center_in

    def x_from_right_jamb(self, door_width_in: float) -> float:
        return door_width_in - self.x_from_left_jamb(door_width_in)


@dataclass
class TrackClearance:
    """The numbers the framing sheets read off Track B.O.M."""

    lift: str
    track_size_in: int
    radius_in: float
    high_lift_in: Optional[float]
    # Sub-routine C18. None means the vertical-lift "N/A".
    ust_above_opening_in: Optional[float]
    # What the framing sheet prints. Low headroom prints the door height
    # (Track B.O.M. F8 = door height when the track type is LHR).
    ust_sheet_in: Optional[float]
    ust_label: str
    cl_from_header_in: float
    headroom_in: float
    shaft_from_floor_in: float
    backroom_in: float
    vertical_track_in: float
    extension_in: float
    tandem: bool = False
    tandem_shaft_from_floor_in: Optional[float] = None
    tandem_headroom_in: Optional[float] = None
    notes: list[str] = field(default_factory=list)


def _lift_key(lift_type: Optional[str], radius_in: float, lhr_mount: Optional[str]) -> str:
    lift = (lift_type or "standard").strip().lower().replace("-", "_").replace(" ", "_")
    if lift in ("high_lift", "high", "hl"):
        return "high_lift"
    if lift in ("vertical", "full_vertical", "vertical_lift", "vl"):
        return "vertical"
    if lift in ("low_headroom", "low_head_room", "lhr"):
        if str(lhr_mount or "front").strip().lower() == "rear":
            return "lhr_rear"
        return "lhr_front"
    if int(round(radius_in)) == 12:
        return "standard_12"
    return "standard_15"


def vertical_track_length(door_height_in: float, lift: str) -> float:
    """Track B.O.M. E19, the vertical track cut."""
    height = float(door_height_in)
    if lift == "lhr_front" or lift == "lhr_rear":
        return height - 15.0
    if lift == "vertical":
        if height <= 11 * 12:
            deduct = 8.0
        elif height <= 18 * 12:
            deduct = 11.0
        else:
            deduct = 13.5
        return height - deduct
    # Standard and high lift.
    return height - 8.0


def extension_length(
    door_height_in: float,
    lift: str,
    high_lift_in: float,
    radius_in: float,
    vertical_track_in: float,
) -> float:
    """Track B.O.M. E20. 0 unless the lift is high or vertical."""
    if lift == "high_lift":
        return float(high_lift_in) - float(radius_in) + 8.0
    if lift == "vertical":
        return float(door_height_in) * 2.0 + 12.0 + 8.0 - float(vertical_track_in)
    return 0.0


def track_clearance(
    *,
    door_width_in: float,
    door_height_in: float,
    lift_type: str,
    track_size_in: int,
    radius_in: float,
    high_lift_in: float = 0.0,
    lhr_mount: str = "front",
    tandem: bool = False,
    modified_shaft_from_floor_in: Optional[float] = None,
) -> TrackClearance:
    """Headroom, shaft centerline, U.S.T., high lift and the extension.

    The offsets are the Sub-Routine for U.S.T. rows (2 in. track at rows
    30–36, 3 in. track at rows 40–46). Track B.O.M. then publishes them as
    F8 (U.S.T.), V6 (shaft elevation), N5 (high lift) and N7 (headroom).
    Tandem sheets add 12 in. to the shaft and the headroom.
    """
    del door_width_in  # width does not enter the clearance table
    size = 3 if int(track_size_in) >= 3 else 2
    radius = 15.0 if size == 3 else float(radius_in or 15)
    lift = _lift_key(lift_type, radius, lhr_mount)
    height = float(door_height_in)
    hl = float(high_lift_in or 0.0) if lift == "high_lift" else 0.0
    notes: list[str] = []

    ust: Optional[float]
    cl: float
    hr: float
    back: float

    if lift == "standard_12":
        ust, cl, hr, back = height + 3.5, 9.5, 12.75, height + 18.0
    elif lift == "standard_15" and size == 2:
        ust, cl, hr, back = height + 6.5, 12.5, 15.75, height + 18.0
    elif lift == "standard_15" and height <= 216:
        ust, cl, hr, back = height + 7.5, 14.5, 17.75, height + 18.0
    elif lift == "standard_15":
        ust, cl, hr, back = height + 7.5, 15.5, 20.5, height + 18.0
    elif lift == "high_lift":
        ust = height + hl
        back = height - hl + 30.0
        if size == 2 and 11 < hl < 55:
            cl, hr = hl + 6.0, hl + 10.0
        elif size == 2 and 54 < hl < 121:
            cl, hr = hl + 6.5, hl + 11.5
        elif size == 3 and 11 < hl < 55:
            cl, hr = hl + 7.0, hl + 11.0
        elif size == 3 and 54 < hl < 165:
            cl, hr = hl + 7.5, hl + 14.0
        else:
            # The sheet's inequalities skip 54 in. exactly, and they stop
            # at 120 in. (2 in. track) or 164 in. (3 in. track).
            if abs(hl - 54.0) < 1e-6:
                cl = hl + (6.0 if size == 2 else 7.0)
                hr = hl + (10.0 if size == 2 else 11.0)
                notes.append(
                    "High lift of exactly 54 in. matches neither workbook band. Using the lower band."
                )
                notes.append("FLAG JOEY: high lift of 54 in. falls in a gap in the workbook inequalities.")
            else:
                cl = hl + (6.5 if size == 2 else 7.5)
                hr = hl + (11.5 if size == 2 else 14.0)
                notes.append(
                    f"High lift {hl:.1f} in. is outside the workbook table "
                    f"({'120' if size == 2 else '164'} in. max). Using the highest band."
                )
                notes.append("FLAG JOEY: high lift is above the workbook table.")
    elif lift == "vertical":
        ust = None
        cl, hr, back = height + 12.0, height + 18.0, 18.0
    elif lift == "lhr_front":
        ust = 0.0
        if size == 2:
            cl, hr = 6.5, 10.0
        else:
            cl, hr = 7.5, 11.0
        back = height + 18.0
    else:  # lhr_rear
        ust = 0.0
        if size == 2:
            cl, hr = 2.0, 5.5
        else:
            cl, hr = 3.0, 7.0
        back = height + 18.0

    if modified_shaft_from_floor_in:
        # Track B.O.M. N6 / N7 when a modified shaft elevation is entered.
        modified = float(modified_shaft_from_floor_in)
        cl = modified - height
        hr = modified - height + 4.0

    shaft = height + cl
    vertical = vertical_track_length(height, lift)
    extension = extension_length(height, lift, hl, radius, vertical)

    if lift == "vertical":
        ust_sheet = None
        ust_label = "U.S.T. N/A"
    elif lift.startswith("lhr"):
        # F8 returns the door height for low headroom, not the 0 in. clearance.
        ust_sheet = height
        ust_label = f"U.S.T.: {height:.2f} in."
        notes.append(
            "Low headroom: the framing sheet prints the door height as U.S.T. "
            "The clearance above the opening is 0."
        )
    elif ust == 0:
        ust_sheet = None
        ust_label = "U.S.T. N/A"
    else:
        ust_sheet = ust
        ust_label = f"U.S.T.: {ust:.2f} in."

    tandem_shaft = None
    tandem_hr = None
    shown_hr = hr
    if tandem:
        tandem_shaft = shaft + TANDEM_SHAFT_OFFSET_IN
        tandem_hr = hr + TANDEM_SHAFT_OFFSET_IN
        shown_hr = tandem_hr

    hl_out: Optional[float] = hl if lift == "high_lift" else None
    return TrackClearance(
        lift=lift,
        track_size_in=size,
        radius_in=radius,
        high_lift_in=hl_out,
        ust_above_opening_in=ust,
        ust_sheet_in=ust_sheet,
        ust_label=ust_label,
        cl_from_header_in=cl,
        headroom_in=shown_hr,
        shaft_from_floor_in=shaft,
        backroom_in=back,
        vertical_track_in=vertical,
        extension_in=extension,
        tandem=tandem,
        tandem_shaft_from_floor_in=tandem_shaft,
        tandem_headroom_in=tandem_hr,
        notes=notes,
    )


def workbook_gaps(sheet: str, door_width_in: float, coupler_qty: int) -> list[float]:
    """Gap chain printed on a framing sheet, left jamb to right jamb.

    ``sheet`` is center, 2pad_2coupler, 2pad_1coupler, 3pad, 4pad or 5pad.
    """
    width = float(door_width_in)
    shaft = center_shaft_length(width, coupler_qty)
    if sheet == "center":
        return [width / 2.0, width / 2.0]
    if sheet == "2pad_2coupler":
        side = (width - shaft) / 2.0
        return [side, shaft, side]
    if sheet == "2pad_1coupler":
        side = WORKBOOK_2PAD_1_COUPLER_SIDE_IN
        return [side, width - 2.0 * side, side]
    if sheet == "3pad":
        if coupler_qty <= 1:
            quarter = width / 4.0
            return [quarter, quarter, quarter, quarter]
        outer = (width - shaft) / 2.0
        # Outer callout is (W − center shaft) / 2 each side. The W/2 callout
        # is the center pad measured from the jamb, so the two middle gaps
        # split the center shaft.
        middle = width / 2.0 - outer
        return [outer, middle, middle, outer]
    if sheet == "4pad":
        span = (width - shaft) / 4.0
        return [span, span, WORKBOOK_4PAD_CENTER_GAP_IN, span, span]
    if sheet == "5pad":
        span = (width - shaft) / 4.0
        half = shaft / 2.0
        return [span, span, half, half, span, span]
    raise ValueError(f"Unknown workbook sheet '{sheet}'")


def workbook_pad_positions(sheet: str, door_width_in: float, coupler_qty: int) -> list[float]:
    """Pad stations measured from the left jamb, from the sheet's gap chain."""
    gaps = workbook_gaps(sheet, door_width_in, coupler_qty)
    positions: list[float] = []
    acc = 0.0
    for gap in gaps[:-1]:
        acc += gap
        positions.append(acc)
    return positions


def closest_workbook_sheet(pad_count: int, tandem: bool, coupler_qty: int) -> str:
    """Which framing tab this pad count would have been drawn on."""
    if pad_count <= 1:
        return "Cen Pad,  Jamb and Exten Tandem" if tandem else "Center Pad,  Jamb and Extension"
    if pad_count == 2:
        if tandem:
            return "2 Pads,  Jamb and Exten Tandem"
        if coupler_qty >= 2:
            return "2 Pads,  Jamb and Ext 2 Coupler"
        return "2 Pads,  Jamb and Ext 1 Coupler"
    if pad_count == 3:
        return "3 Pads,  Jamb and Extens Tandem" if tandem else "3 Pads,  Jamb and Extension Dwg"
    if pad_count == 4:
        return "4 Pads,  Jamb and Extension"
    return "5 Pads,  Jamb and Extension"


def _axial(springs: Sequence[SpringSpec], hand: str) -> list[SpringSpec]:
    return [s for s in springs if not s.nested and s.hand == hand]


def place_pads(
    springs: Sequence[SpringSpec],
    door_width_in: float,
) -> tuple[list[SpringPad], list[str]]:
    """Joey's pad rule.

    A center pad wherever the two winds meet at the coupler. Each additional
    spring on a side adds a pad at the outer end of the springs inboard of
    it. The installed length is wire × turns + cut length + 3 in. cones.
    The 6 in. space between springs is added at each junction after the first.

    Odd counts (3, 5, …): the shorter side does not share the center pad.
    Its first pad sits one space plus that spring's installed length off
    center, so the odd spring still has an anchor. See DIFFERENCES_FOR_JOEY.
    """
    del door_width_in  # positions are from center; the caller dimensions to the jambs
    notes: list[str] = []
    lh = _axial(springs, "LH")
    rh = _axial(springs, "RH")
    if any(s.nested for s in springs):
        notes.append(
            "Nested duplex springs share the outer spring's pad and are not given their own anchor."
        )
    if not lh and not rh:
        notes.append("This quote has no springs, so no spring pads are shown.")
        return [], notes

    pads: list[SpringPad] = [
        SpringPad(role="center", x_from_center_in=0.0, wind="CENTER", label="CENTER PAD")
    ]

    if not lh or not rh:
        only = lh or rh
        notes.append(
            "FLAG JOEY: springs are all one wind. One centered pad is shown. "
            "Confirm whether a single-wind door should use a different anchor."
        )
        _stack_sharing(pads, only, -1.0 if lh else 1.0)
        return _unique_pads(pads), notes

    if len(lh) != len(rh):
        notes.append(
            "FLAG JOEY: odd spring count. The side with fewer springs does not share the "
            "center bracket; each of those springs has its own pad. "
            f"{len(lh) + len(rh)} springs → {len(lh) + len(rh)} pads."
        )

    _stack_side(pads, lh, -1.0, len(rh))
    _stack_side(pads, rh, 1.0, len(lh))
    return _unique_pads(pads), notes


def _stack_side(pads: list[SpringPad], side: list[SpringSpec], sign: float, other_count: int) -> None:
    shares = len(side) >= other_count
    if shares:
        _stack_sharing(pads, side, sign)
        return
    acc = 0.0
    for index, spring in enumerate(side):
        acc += SPACE_BETWEEN_SPRINGS_IN + spring.length_in
        pads.append(SpringPad(
            role="anchor",
            x_from_center_in=sign * acc,
            wind=spring.hand,
            label=f"{spring.hand} PAD {index + 1}",
        ))


def _stack_sharing(pads: list[SpringPad], side: list[SpringSpec], sign: float) -> None:
    """Innermost spring uses the center pad. Later springs add a pad."""
    acc = 0.0
    for index in range(1, len(side)):
        acc += side[index - 1].length_in
        if index > 1:
            acc += SPACE_BETWEEN_SPRINGS_IN
        pads.append(SpringPad(
            role="anchor",
            x_from_center_in=sign * acc,
            wind=side[index].hand,
            label=f"{side[index].hand} PAD {index}",
        ))


def _unique_pads(pads: list[SpringPad]) -> list[SpringPad]:
    kept: list[SpringPad] = []
    for pad in pads:
        if any(abs(pad.x_from_center_in - other.x_from_center_in) < 0.05 for other in kept):
            continue
        kept.append(pad)
    kept.sort(key=lambda pad: pad.x_from_center_in)
    return kept


def clearance_notes(
    pads: Sequence[SpringPad],
    door_width_in: float,
    *,
    tandem: bool,
) -> list[str]:
    """Warn when a spring-length pad breaks the sheet's minimum clearances."""
    notes: list[str] = []
    jamb_min = MIN_JAMB_CLEAR_TANDEM_IN if tandem else MIN_JAMB_CLEAR_IN
    stations = [0.0] + [pad.x_from_left_jamb(door_width_in) for pad in pads] + [door_width_in]
    for left, right in zip(stations, stations[1:]):
        gap = right - left
        if gap < -0.05:
            notes.append("A pad falls outside the opening. The spring run is longer than the door.")
        elif left == 0.0 or right == door_width_in:
            if gap + 1e-6 < jamb_min:
                notes.append(
                    f"Clearance from a pad to the jamb is {gap:.1f} in. "
                    f"The sheet asks for {jamb_min:.0f} in."
                )
        elif gap + 1e-6 < MIN_PAD_GAP_IN:
            notes.append(
                f"Clearance between pads is {gap:.1f} in. The sheet asks for {MIN_PAD_GAP_IN:.0f} in."
            )
    return notes


def assembly_length_of(
    springs: Sequence[SpringSpec],
    drum_width: float,
    center_pickups: int = 0,
) -> float:
    """B13 for a real spring list. Identical springs match the sheet exactly."""
    axial = [s for s in springs if not s.nested]
    count = len(axial)
    if count == 0:
        return 0.0
    body = sum(s.length_in for s in axial)
    return body + (count - 1) * SPACE_BETWEEN_SPRINGS_IN + float(drum_width) * (2 + int(center_pickups))


def fit_notes(
    springs: Sequence[SpringSpec],
    door_width_in: float,
    drum_width: float,
    center_pickups: int,
) -> list[str]:
    axial = [s for s in springs if not s.nested]
    if not axial:
        return []
    length = assembly_length_of(springs, drum_width, center_pickups)
    available = door_width_in - END_CLEARANCE_IN
    notes = []
    if length > available + 1e-6:
        notes.append(
            f"Spring assembly is {length:.1f} in. and the workbook allows {available:.1f} in. "
            "(door width minus 6 in.). The sheet says try again."
        )
    free = (door_width_in - length) / len(axial)
    if free < MIN_FREE_PER_SPRING_IN:
        notes.append(
            f"Free length per spring is {free:.1f} in. The workbook flags anything under 3 in."
        )
    return notes


@dataclass
class FramingDetail:
    """Everything the customer framing sheet draws. No prices."""

    applies: bool
    series: str
    door_width_in: float
    door_height_in: float
    customer_name: str
    job_number: str
    drawing_date: str
    track: TrackClearance
    pads: list[SpringPad]
    springs: list[SpringSpec]
    drum_model: str
    drum_width_in: float
    coupler_qty: int
    center_pickups: int
    center_shaft_in: float
    jamb_type: str
    sideroom_in: float
    operator: str
    operator_side: str
    operator_plate: bool
    workbook_sheet: str
    assembly_length_in: float
    door_number: str = "1"
    notes: list[str] = field(default_factory=list)
    differences: tuple[str, ...] = DIFFERENCES_FOR_JOEY

    @property
    def spring_count(self) -> int:
        return len(self.springs)

    @property
    def axial_count(self) -> int:
        return sum(1 for spring in self.springs if not spring.nested)

    @property
    def pad_count(self) -> int:
        return len(self.pads)


def _door_number(door: dict, *keys: str, default: float = 0.0) -> float:
    for key in keys:
        if door.get(key) not in (None, ""):
            return float(door[key])
    return default


def _jamb_type(door: dict, series: str) -> str:
    explicit = door.get("jambType") or door.get("jamb_type")
    if explicit:
        return "steel" if "steel" in str(explicit).lower() else "wood"
    if str(door.get("doorType") or "").lower() == "residential" and not is_workbook_tx_series(series):
        return "wood"
    if str(door.get("doorType") or "").lower() == "residential":
        return "wood"
    return "steel"


def _operator(door: dict) -> str:
    operator = str(door.get("operator") or "NONE").strip()
    if operator.upper() in ("", "NONE"):
        hoist = str(door.get("chainHoist") or "none").strip().lower()
        if hoist in ("shaft", "wall"):
            return "CHAIN_HOIST"
    return operator or "NONE"


def operator_plate_required(operator: str) -> bool:
    token = (operator or "NONE").strip().upper()
    if token in ("", "NONE", "CHAIN_HOIST"):
        return False
    if "PAD" in token:
        return False
    return True


def springs_from_selection(selection) -> list[SpringSpec]:
    """Turn a door-calculator SpringSelection into axial springs.

    Duplex inners are nested. An odd non-duplex count keeps the extra
    spring on the left hand; the parts list currently drops that extra
    when it pairs winds, and the drawing does not.
    """
    if selection is None or not getattr(selection, "quantity", None):
        return []
    turns = float(selection.turns or 0.0)
    wire = float(selection.wire_diameter or 0.0)
    cut = float(selection.length or 0.0)
    coil = float(selection.coil_diameter or 0.0)
    if getattr(selection, "is_duplex", False) and getattr(selection, "duplex_pairs", 0):
        positions = int(selection.duplex_pairs)
        lh_n = positions // 2
        rh_n = positions - lh_n
        springs: list[SpringSpec] = []
        for hand, count in (("LH", lh_n), ("RH", rh_n)):
            for _ in range(count):
                springs.append(SpringSpec(hand, wire, turns, cut, coil=coil))
                if selection.inner_length:
                    springs.append(SpringSpec(
                        hand,
                        float(selection.inner_wire_diameter or 0.0),
                        turns,
                        float(selection.inner_length),
                        nested=True,
                        coil=float(selection.inner_coil_diameter or 0.0),
                    ))
        return springs
    qty = int(selection.quantity)
    if qty <= 1:
        return [SpringSpec("LH", wire, turns, cut, coil=coil)]
    lh_n = (qty + 1) // 2
    rh_n = qty // 2
    springs = []
    for hand, count in (("LH", lh_n), ("RH", rh_n)):
        springs.extend(SpringSpec(hand, wire, turns, cut, coil=coil) for _ in range(count))
    return springs


def _calculator_inputs(door: dict) -> dict:
    series = str(door.get("doorSeries") or door.get("door_model") or "TX450")
    width = _door_number(door, "doorWidth", "width")
    height = _door_number(door, "doorHeight", "height")
    radius = quoted_track_radius(
        door.get("trackThickness") if "trackThickness" in door else door.get("track_size"),
        door.get("trackRadius") or door.get("track_radius") or 15,
        series,
    )
    track = resolve_track_thickness(
        door.get("trackThickness") if "trackThickness" in door else door.get("track_size"),
        series,
        door.get("doorType"),
    )
    lift = str(door.get("liftType") or door.get("lift_type") or "standard")
    lhr = str(door.get("lhrMount") or door.get("lhr_mount") or "front")
    calc_lift = {
        "high_lift": "high_lift",
        "vertical": "vertical",
        "full_vertical": "vertical",
        "low_headroom": "lhr_rear" if lhr == "rear" else "lhr_front",
    }.get(lift, "standard_12" if radius == "12" else "standard_15")
    hl = door.get("highLiftInches", door.get("high_lift_inches"))
    return {
        "door_model": series,
        "width_inches": int(round(width)),
        "height_inches": int(round(height)),
        "lift_type": calc_lift,
        "track_size": int(track),
        "target_cycles": int(door.get("targetCycles") or door.get("target_cycles") or 10000),
        "shaft_type": str(door.get("shaftType") or door.get("shaft_type") or "auto"),
        "high_lift_inches": int(hl) if hl else 0,
        "door_type": str(door.get("doorType") or door.get("door_type") or "commercial"),
    }


def load_quote_springs(door: dict):
    """Run the same door calculator the quote uses.

    Returns (springs, drum model, coupler qty, tandem, weight) or None when
    the calculator cannot produce a spring. Prices are not read.
    """
    try:
        from app.services.door_calculator_service import door_calculator
        calc = door_calculator.calculate_door(**_calculator_inputs(door))
    except Exception:
        return None
    springs = springs_from_selection(calc.springs)
    if not springs:
        return None
    drum = calc.drums.model if calc.drums else ""
    couplers = int(calc.shaft.coupler_qty) if calc.shaft else 0
    tandem = bool(getattr(calc.springs, "is_tandem", False))
    weight = float(calc.weight.total_weight or 0.0)
    return springs, drum, couplers, tandem, weight


def build_framing_detail(
    door: dict,
    *,
    customer_name: str = "",
    job_number: str = "",
    drawing_date: str = "",
    springs: Optional[Sequence[SpringSpec]] = None,
    drum_model: Optional[str] = None,
    coupler_qty: Optional[int] = None,
    is_tandem: Optional[bool] = None,
    door_weight_lb: Optional[float] = None,
) -> FramingDetail:
    """Build the framing detail for one door dict from a saved quote."""
    series = str(door.get("doorSeries") or door.get("door_model") or "")
    width = _door_number(door, "doorWidth", "width")
    height = _door_number(door, "doorHeight", "height")
    if width <= 0 or height <= 0:
        raise ValueError("Door width and height are required for a framing detail")

    notes: list[str] = []
    quote = None
    if springs is None:
        quote = load_quote_springs(door)
        if quote is None:
            notes.append(
                "The spring calculator did not return a setup. "
                "One center pad is shown until the spring quote is confirmed."
            )
            springs = []
        else:
            springs = quote[0]
            drum_model = drum_model or quote[1]
            if coupler_qty is None:
                coupler_qty = quote[2]
            if is_tandem is None:
                is_tandem = quote[3]
            if door_weight_lb is None:
                door_weight_lb = quote[4]
    springs = list(springs)
    if (
        quote is None
        and springs
        and any(not s.nested for s in springs)
        and (sum(1 for s in springs if not s.nested) % 2 == 1)
        and sum(1 for s in springs if not s.nested) > 1
    ):
        notes.append(
            "FLAG JOEY: an odd spring count is kept on the drawing. "
            "The parts list pairs winds and can omit the extra spring."
        )

    tandem = bool(is_tandem)
    couplers = int(coupler_qty or 0)
    weight = float(door_weight_lb or 0.0)
    pickups = center_pickup_count(weight)
    drum_name = drum_model or ""
    drum_width = workbook_drum_width(drum_name)
    if drum_width is None:
        drum_width = 0.0
        if drum_name:
            notes.append(
                f"Drum {drum_name} is not on the workbook Width column. "
                "Assembly length omits the drum width."
            )
            notes.append("FLAG JOEY: unknown drum width; workbook Width column has no match.")

    radius = float(quoted_track_radius(
        door.get("trackThickness") if "trackThickness" in door else door.get("track_size"),
        door.get("trackRadius") or door.get("track_radius") or 15,
        series,
    ) or 15)
    track_size = int(resolve_track_thickness(
        door.get("trackThickness") if "trackThickness" in door else door.get("track_size"),
        series,
        door.get("doorType"),
    ))
    hl = _door_number(door, "highLiftInches", "high_lift_inches")
    track = track_clearance(
        door_width_in=width,
        door_height_in=height,
        lift_type=str(door.get("liftType") or door.get("lift_type") or "standard"),
        track_size_in=track_size,
        radius_in=radius,
        high_lift_in=hl,
        lhr_mount=str(door.get("lhrMount") or door.get("lhr_mount") or "front"),
        tandem=tandem,
    )
    notes.extend(track.notes)

    pads, pad_notes = place_pads(springs, width)
    if not springs:
        pads = [SpringPad(role="center", x_from_center_in=0.0, wind="CENTER", label="CENTER PAD")]
        pad_notes = [
            note for note in pad_notes
            if "no spring pads" not in note
        ]
    notes.extend(pad_notes)
    axial = [s for s in springs if not s.nested]
    if len(axial) > 1 and len(axial) % 2 == 1:
        notes.append(
            "FLAG JOEY: the parts list pairs springs by wind and can drop an odd spring. "
            "This drawing keeps every spring."
        )
    notes.extend(clearance_notes(pads, width, tandem=tandem))
    if drum_width:
        notes.extend(fit_notes(springs, width, drum_width, pickups))
    if pickups:
        notes.append(
            f"Center pickup: {pickups} extra drum(s) because the door is over 2,200 lb. "
            "Counted in the assembly length. No extra pad."
        )
        notes.append(
            "FLAG JOEY: center-pickup drums do not add a pad. The 5-pad sheet draws a center drum."
        )
    if tandem:
        notes.append("Tandem shaft is 12 in. above the main shaft. Pads are drawn once.")
        notes.append("FLAG JOEY: confirm whether the upper shaft needs its own pads.")

    jamb = _jamb_type(door, series)
    operator = _operator(door)
    sheet = closest_workbook_sheet(len(pads), tandem, couplers)
    return FramingDetail(
        applies=is_workbook_tx_series(series),
        series=series,
        door_width_in=width,
        door_height_in=height,
        customer_name=customer_name or "",
        job_number=job_number or "",
        drawing_date=drawing_date or "",
        track=track,
        pads=pads,
        springs=springs,
        drum_model=drum_name,
        drum_width_in=drum_width,
        coupler_qty=couplers,
        center_pickups=pickups,
        center_shaft_in=center_shaft_length(width, couplers),
        jamb_type=jamb,
        sideroom_in=real_sideroom_in(jamb),
        operator=operator,
        operator_side=str(door.get("operatorSide") or door.get("operator_side") or "right").lower(),
        operator_plate=operator_plate_required(operator),
        workbook_sheet=sheet,
        assembly_length_in=assembly_length_of(springs, drum_width, pickups),
        door_number=str(door.get("doorNumber") or door.get("doorNo") or "1"),
        notes=notes,
    )
