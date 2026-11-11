"""One door spec for a shop drawing.

Built from the saved-quote door dict plus the Thermalex weight, section, and
spring calculators. The sheet reads this object only — a partial browser
payload cannot omit sections, clearances, or springs, because those are
filled in here.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from app.services.door_calculator_service import (
    SECTION_HEIGHT_TABLE,
    calculate_door_from_config,
)
from app.services.shop_drawings.clearances import Clearances, lookup_clearances

logger = logging.getLogger(__name__)

DISTRIBUTOR = "OPEN DISTRIBUTION COMPANY"

# Series that draw an outside-face view (brick surround).
_FLUSH_SERIES = {"TX-500-20", "TX-450-20"}
_ALUMINUM_SERIES = {"PANORAMA", "SOLALITE", "AL976", "SWD", "AL-SWD", "ALSWD"}
_PANORAMA_PROFILE = {"PANORAMA", "SOLALITE"}

_GLAZING_SIZES = {
    "24X12": '24" X 12"',
    "24X8": '24" X 8"',
    "34X16": '34" X 16"',
    "18X8": '18" X 8"',
    "12X24": '12" X 24"',
    "32X16": '32" X 16"',
}


@dataclass
class SpringLine:
    hand: str          # LHW or RHW
    count: int
    wire: float
    coil: float
    length: float
    nested: bool = False

    def text(self) -> str:
        tag = " INNER" if self.nested else ""
        return (
            f"{self.count}{self.hand} {fmt_wire(self.wire)} X "
            f'{fmt_coil(self.coil)}" X {fmt_num(self.length)}"{tag}'
        )


@dataclass
class WindowSpec:
    qty: int
    size_text: str
    material: str
    sections_from_bottom: list[int]   # 1-based, bottom = 1
    per_section_qty: dict[int, int] = field(default_factory=dict)
    full_section: bool = False

    @property
    def location_text(self) -> str:
        if not self.sections_from_bottom:
            return "N/A"
        return " & ".join(ordinal(n) for n in self.sections_from_bottom)

    @property
    def glazed_text(self) -> str:
        if not self.sections_from_bottom:
            return "N/A"
        if self.full_section:
            return "FULL"
        return "INTERMEDIATE"


@dataclass
class DoorDrawingSpec:
    series: str
    series_key: str
    width_in: float
    height_in: float
    qty: int
    section_heights: list[float]          # bottom → top, inches
    thickness_in: float
    joint: str                             # tongue_groove, shiplap, panorama
    exterior_gauge: str
    interior_gauge: str
    finish: str                            # stucco or flush
    color: str
    show_outside_face: bool
    clearances: Clearances
    springs: list[SpringLine]
    turns: Optional[float]
    spring_cycles: int
    drum_model: str
    weight_lbs: Optional[float]
    shaft_kind: str                        # 1_solid, 1_25_solid, 1_tubular
    coupler: bool
    struts_16: int
    struts_20: int
    double_end_stiles: bool
    windows: WindowSpec
    lift: str
    frame: str                             # steel or wood
    mount: str                             # bracket or angle
    track_size: int
    operator_model: str
    operator_qty: int
    chain_hoist: bool
    manual: bool
    top_seal: bool
    weather_strip: bool
    weather_strip_material: str            # STEEL or ALUMINUM
    exhaust_port: bool
    man_door: bool
    bar_latch: bool
    keyed_outside_handle: bool
    interior_lock: bool
    pusher_spring: bool
    bumper_spring: bool
    track_guards: bool
    distributor: str
    project_name: str
    architect: str
    drawn_by: str
    drawing_date: str                      # DD/MM/YYYY
    drawing_number: str
    revision: Optional[int]
    job_number: str
    customer_name: str
    warnings: list[str] = field(default_factory=list)

    # ── labels the sheet prints (single source for tests) ──────────────

    @property
    def headroom_text(self) -> str:
        return fmt_headroom(self.clearances.headroom_in, self.clearances.lift)

    @property
    def ust_text(self) -> Optional[str]:
        if self.clearances.ust_from_floor_in is None:
            return None
        return fmt_arch(self.clearances.ust_from_floor_in)

    @property
    def backroom_text(self) -> str:
        return fmt_arch(self.clearances.backroom_in)

    @property
    def cl_shaft_text(self) -> str:
        return fmt_arch(self.clearances.cl_shaft_from_floor_in)

    @property
    def sideroom_text(self) -> str:
        return fmt_inches(self.clearances.sideroom_in)

    @property
    def high_lift_text(self) -> Optional[str]:
        if self.lift != "high_lift" or self.clearances.high_lift_in <= 0:
            return None
        return fmt_inches(self.clearances.high_lift_in)

    @property
    def door_width_text(self) -> str:
        return fmt_arch(self.width_in)

    @property
    def door_height_text(self) -> str:
        return fmt_arch(self.height_in)

    @property
    def half_shaft_text(self) -> str:
        return fmt_arch(self.width_in / 2.0)

    @property
    def sections_text(self) -> str:
        return format_section_stack(self.section_heights)

    @property
    def thickness_text(self) -> str:
        return fmt_arch_inches_only(self.thickness_in)

    @property
    def joint_title(self) -> str:
        if self.joint == "shiplap":
            return "SHIPLAP JOINT"
        if self.joint == "panorama":
            return "PANORAMA SIDE PROFILE"
        return "TONGUE AND GROOVE"

    @property
    def track_title(self) -> str:
        return {
            "standard": "STANDARD LIFT TRACKS",
            "high_lift": "HIGH LIFT TRACKS",
            "vertical": "FULL VERTICAL LIFT TRACKS",
            "lhr_front": "LOW HEADROOM FRONT MOUNT TRACKS",
            "lhr_rear": "LOW HEADROOM REAR MOUNT TRACKS",
        }.get(self.lift, "STANDARD LIFT TRACKS")

    @property
    def turns_text(self) -> str:
        if self.turns is None:
            return "—"
        return f"{self.turns:.1f}"

    @property
    def exterior_skin_label(self) -> str:
        if self.joint == "panorama":
            return "EXTRUDED ALUMINIUM RAIL"
        colour = (self.color or "").replace("_", " ").strip()
        if self.finish == "flush":
            base = f"{self.exterior_gauge} FLUSH"
        else:
            base = f"{self.exterior_gauge} STUCCO EMBOSSED"
        if colour and colour.upper() not in ("", "NONE"):
            return f"{base} FINISH: {colour.upper()}"
        return base

    @property
    def interior_skin_label(self) -> str:
        if self.joint == "panorama":
            return "GLAZING MOULDING"
        return f"{self.interior_gauge} STUCCO EMBOSSED WHITE"


def build_door_spec(
    door: dict,
    *,
    customer_name: str = "",
    job_number: str = "",
    drawn_by: str = "",
    drawing_number: str = "",
    revision: Optional[int] = None,
    drawing_date: Optional[datetime] = None,
    project_name: str = "",
    architect: str = "",
    distributor: str = DISTRIBUTOR,
    config_data: Optional[dict] = None,
) -> DoorDrawingSpec:
    """Build a complete drawing spec for one door dict."""
    door = door or {}
    config_data = config_data or {}
    series_key = _series_key(door.get("doorSeries") or door.get("door_series") or "")
    series = _series_label(series_key)
    width = float(door.get("doorWidth") or door.get("door_width") or 0)
    height = float(door.get("doorHeight") or door.get("door_height") or 0)
    if width <= 0 or height <= 0:
        raise ValueError("Door width and height must be positive")

    lift = normalize_lift(
        door.get("liftType") or door.get("lift_type"),
        door.get("lhrMount") or door.get("lhr_mount") or "front",
    )
    hl = float(door.get("highLiftInches") or door.get("high_lift_inches") or 0)
    if lift != "high_lift":
        hl = 0
    track = _track_size(door, series_key)
    radius = _track_radius(door)
    mount = _mount(door)
    frame = _frame(door)
    color = str(door.get("panelColor") or door.get("panel_color") or "WHITE")
    design = str(door.get("panelDesign") or door.get("panel_design") or "").upper()
    finish = "flush" if (series_key in _FLUSH_SERIES or design == "FLUSH") else "stucco"
    joint = _joint_for(series_key)
    thickness = _thickness_for(series_key)
    ext_gauge, int_gauge = _gauges_for(series_key)
    show_outside = series_key in _FLUSH_SERIES or series_key in _ALUMINUM_SERIES or design == "FLUSH"

    heights = section_stack(height)
    clearances = lookup_clearances(
        height,
        track_size=track,
        radius=radius,
        lift=lift,
        high_lift_in=hl,
        mount=mount,
    )

    calc = _run_calculator(
        series_key=series_key,
        width=width,
        height=height,
        lift=lift,
        track=track,
        radius=radius,
        high_lift=hl,
        door=door,
    )
    springs_raw = (calc or {}).get("springs") or None
    springs = spring_lines(springs_raw)
    turns = None
    cycles = int(door.get("targetCycles") or door.get("target_cycles") or 10000)
    if springs_raw:
        turns = float(springs_raw["turns"]) if springs_raw.get("turns") is not None else None
        if springs_raw.get("cycles"):
            cycles = int(springs_raw["cycles"])
    drum = ""
    weight = None
    shaft_kind = "1_solid"
    coupler = False
    struts_16 = 0
    struts_20 = 0
    warnings = list((calc or {}).get("warnings") or [])
    if calc:
        drum = str((calc.get("drum") or {}).get("model") or "")
        weight = (calc.get("weight") or {}).get("total_lbs")
        shaft_kind, coupler = _shaft_from_calc(calc.get("shaft") or {})
        struts_16, struts_20 = _struts_from_calc(calc.get("hardware") or {})
        calc_sections = (calc.get("panels") or {}).get("total_sections")
        if calc_sections and calc_sections != len(heights):
            warnings.append(
                f"Section count {len(heights)} from the height table "
                f"differs from calculator total {calc_sections}"
            )

    # A caller can force the shaft checkbox (tests / explicit hardware).
    forced = str(door.get("shaftType") or door.get("shaft_type") or "auto").lower()
    if forced in ("1_solid", "1_25_solid", "1_tubular"):
        shaft_kind = forced
    if door.get("coupler") is True:
        coupler = True

    end_cap = str(door.get("endCapType") or door.get("end_cap_type") or "").upper()
    double_stiles = end_cap == "DEC" or width > 16 * 12
    if end_cap == "SEC":
        double_stiles = False

    windows = _windows(door, len(heights), series_key)
    operator = str(door.get("operator") or "NONE").strip()
    hoist = str(door.get("chainHoist") or door.get("chain_hoist") or "none").lower()
    # An electric operator wins over a chain hoist, matching the quote.
    if operator.upper() in ("CHAIN_HOIST", "CHAIN HOIST"):
        chain = True
        operator = "NONE"
    elif operator.upper() in ("", "NONE") and hoist in ("shaft", "wall"):
        chain = True
    else:
        chain = False
    manual = operator.upper() in ("", "NONE") and not chain
    op_model = "" if operator.upper() in ("", "NONE") else operator
    op_qty = int(door.get("operatorQty") or door.get("operator_qty") or (1 if op_model else 0))

    hardware = door.get("hardware") or {}
    weather = bool(hardware.get("weatherStripping", door.get("weatherStripping", True)))
    weather_mat = "ALUMINUM" if joint == "panorama" or series_key in _ALUMINUM_SERIES else "STEEL"
    top_seal = bool(
        door.get("includeTopSeal")
        or door.get("topSeal")
        or hardware.get("topSeal")
        or width >= 18 * 12
    )

    project = (
        project_name
        or config_data.get("projectName")
        or config_data.get("project_name")
        or door.get("projectName")
        or customer_name
        or ""
    )
    architect_name = (
        architect
        or config_data.get("architect")
        or door.get("architect")
        or ""
    )
    when = drawing_date or datetime.utcnow()
    if isinstance(when, str):
        date_text = _format_date_string(when)
    else:
        date_text = when.strftime("%d/%m/%Y")

    return DoorDrawingSpec(
        series=series,
        series_key=series_key,
        width_in=width,
        height_in=height,
        qty=max(1, int(door.get("doorCount") or door.get("door_count") or 1)),
        section_heights=heights,
        thickness_in=thickness,
        joint=joint,
        exterior_gauge=ext_gauge,
        interior_gauge=int_gauge,
        finish=finish,
        color=color,
        show_outside_face=show_outside,
        clearances=clearances,
        springs=springs,
        turns=turns,
        spring_cycles=cycles,
        drum_model=drum,
        weight_lbs=float(weight) if weight is not None else None,
        shaft_kind=shaft_kind,
        coupler=coupler,
        struts_16=struts_16,
        struts_20=struts_20,
        double_end_stiles=double_stiles,
        windows=windows,
        lift=lift,
        frame=frame,
        mount=mount,
        track_size=track,
        operator_model=op_model,
        operator_qty=op_qty,
        chain_hoist=chain,
        manual=manual,
        top_seal=top_seal,
        weather_strip=weather,
        weather_strip_material=weather_mat,
        exhaust_port=bool(door.get("exhaustPort") or door.get("exhaust_port")),
        man_door=bool(door.get("manDoor") or door.get("man_door")),
        bar_latch=bool(door.get("barLatch") or door.get("bar_latch")),
        keyed_outside_handle=bool(door.get("keyedOutsideHandle") or door.get("keyed_outside_handle")),
        interior_lock=bool(door.get("interiorLock") or door.get("interior_lock")),
        pusher_spring=bool(door.get("pusherSpring") or door.get("pusher_spring")),
        bumper_spring=bool(door.get("bumperSpring") or door.get("bumper_spring")),
        track_guards=bool(door.get("trackGuards") or door.get("track_guards")),
        distributor=distributor or DISTRIBUTOR,
        project_name=project,
        architect=architect_name,
        drawn_by=(drawn_by or "").strip(),
        drawing_date=date_text,
        drawing_number=(drawing_number or job_number or "").strip(),
        revision=revision,
        job_number=job_number or "",
        customer_name=customer_name or "",
        warnings=warnings,
    )


def build_spec_from_config(
    config_data: dict,
    *,
    customer_name: str = "",
    job_number: str = "",
    drawn_by: str = "",
    drawing_number: str = "",
    revision: Optional[int] = None,
    drawing_date: Optional[datetime] = None,
    project_name: str = "",
    architect: str = "",
    door_index: int = 0,
) -> DoorDrawingSpec:
    doors = (config_data or {}).get("doors") or []
    if not doors:
        raise ValueError("Config has no doors to draw")
    if door_index >= len(doors):
        raise ValueError(f"door_index {door_index} out of range (have {len(doors)})")
    return build_door_spec(
        doors[door_index],
        customer_name=customer_name,
        job_number=job_number,
        drawn_by=drawn_by,
        drawing_number=drawing_number,
        revision=revision,
        drawing_date=drawing_date,
        project_name=project_name or (config_data or {}).get("projectName") or "",
        architect=architect or (config_data or {}).get("architect") or "",
        config_data=config_data,
    )


# ─── sections ───────────────────────────────────────────────────────────────

def section_stack(height_in: float) -> list[float]:
    """Section heights in inches, bottom to top.

    Uses ``SECTION_HEIGHT_TABLE`` (the same table the weight calculator
    uses). 24 inch sections sit on top of the 21 inch sections. When the
    table note cuts the top panel, the top height is shortened so the stack
    sums to the door height. A 10 foot door is 5 × 24, not 6.
    """
    height = int(round(height_in))
    if height in SECTION_HEIGHT_TABLE:
        entry = SECTION_HEIGHT_TABLE[height]
        n21, n24 = int(entry["21"]), int(entry["24"])
    else:
        panel_count = max(3, -(-height // 24))
        diff = panel_count * 24 - height
        n21 = max(0, min(panel_count, diff // 3))
        n24 = panel_count - n21
    heights = [21.0] * n21 + [24.0] * n24
    if not heights:
        heights = [24.0]
    extra = sum(heights) - height
    if extra > 0.5:
        heights[-1] = max(6.0, heights[-1] - extra)
    return heights


def format_section_stack(heights: list[float]) -> str:
    groups: list[list] = []
    for h in heights:
        if groups and abs(groups[-1][0] - h) < 0.05:
            groups[-1][1] += 1
        else:
            groups.append([h, 1])
    parts = []
    for h, n in groups:
        label = str(int(round(h))) if abs(h - round(h)) < 0.05 else f"{h:g}"
        parts.append(f'{n} X {label}"')
    return " + ".join(parts)


# ─── lift / series helpers ──────────────────────────────────────────────────

def normalize_lift(raw, lhr_mount: str = "front") -> str:
    """Map configurator lift names onto the Thermalex table keys.

    The configurator sends ``vertical``. Older drawing code looked for
    ``full_vertical`` and fell through to standard lift. Both names are
    full vertical.
    """
    s = str(raw or "").strip().lower().replace("-", " ").replace("_", " ")
    s = " ".join(s.split())
    if s in ("vertical", "full vertical", "fullvertical"):
        return "vertical"
    if s in ("high lift", "high", "hl"):
        return "high_lift"
    if s in ("lhr front", "low headroom front", "front low headroom"):
        return "lhr_front"
    if s in ("lhr rear", "low headroom rear", "rear low headroom"):
        return "lhr_rear"
    if s in ("low headroom", "lhr"):
        return "lhr_rear" if str(lhr_mount or "").lower() == "rear" else "lhr_front"
    return "standard"


def _series_key(raw: str) -> str:
    s = (raw or "").upper().replace(" ", "").replace("_", "")
    aliases = {
        "TX380": "TX-380",
        "TX-380": "TX-380",
        "TX450": "TX-450",
        "TX-450": "TX-450",
        "TX450-20": "TX-450-20",
        "TX-450-20": "TX-450-20",
        "TX500": "TX-500",
        "TX-500": "TX-500",
        "TX500-20": "TX-500-20",
        "TX-500-20": "TX-500-20",
        "PANORAMA": "PANORAMA",
        "SOLALITE": "SOLALITE",
        "AL976": "AL976",
        "SWD": "SWD",
        "ALSWD": "AL976",
        "AL-SWD": "AL976",
    }
    return aliases.get(s, (raw or "").upper() or "TX-450")


def _series_label(key: str) -> str:
    return key


def _calculator_model(key: str) -> str:
    return {
        "TX-380": "TX380",
        "TX-450": "TX450",
        "TX-450-20": "TX450-20",
        "TX-500": "TX500",
        "TX-500-20": "TX500-20",
        "PANORAMA": "PANORAMA",
        "SOLALITE": "SOLALITE",
        "AL976": "AL976",
        "SWD": "AL-SWD",
    }.get(key, key.replace("-", ""))


def _joint_for(key: str) -> str:
    if key in _PANORAMA_PROFILE or key in _ALUMINUM_SERIES:
        return "panorama"
    if key == "TX-380":
        return "shiplap"
    return "tongue_groove"


def _thickness_for(key: str) -> float:
    return {
        "TX-380": 1.5,
        "TX-450": 1.75,
        "TX-450-20": 1.75,
        "TX-500": 2.0,
        "TX-500-20": 2.0,
        "PANORAMA": 1.75,
        "SOLALITE": 1.75,
        "AL976": 1.75,
    }.get(key, 1.75)


def _gauges_for(key: str) -> tuple[str, str]:
    """Drawing labels. TX-380 matches TX-450 (26 ga). -20 series are 20 ga outside.

    The weight calculator still prices non-20 steel at its 24 ga table; the
    shop-drawing label follows the sample sheets (26 ga), per Joey.
    """
    if key in ("TX-500-20", "TX-450-20"):
        return "20GA", "26GA"
    if key in _ALUMINUM_SERIES:
        return "ALUM", "ALUM"
    return "26GA", "26GA"


def _track_size(door: dict, series_key: str) -> int:
    raw = door.get("trackThickness", door.get("trackSize", door.get("track_size")))
    try:
        n = int(float(raw))
    except (TypeError, ValueError):
        n = 0
    if n in (2, 3):
        return n
    if series_key.startswith("TX") or series_key in _ALUMINUM_SERIES:
        return 3
    return 2


def _track_radius(door: dict) -> int:
    raw = door.get("trackRadius", door.get("track_radius", 15))
    try:
        n = int(float(raw))
    except (TypeError, ValueError):
        n = 15
    return 12 if n == 12 else 15


def _mount(door: dict) -> str:
    raw = str(door.get("trackMount") or door.get("track_mount") or "bracket").lower()
    if raw in ("angle", "continuous", "continuous_angle", "continuous angle"):
        return "angle"
    return "bracket"


def _frame(door: dict) -> str:
    surface = str(
        door.get("mountSurface")
        or door.get("mount_surface")
        or door.get("jambType")
        or door.get("jamb_type")
        or ""
    ).lower()
    if surface in ("steel", "concrete", "masonry"):
        return "steel"
    if surface == "wood":
        return "wood"
    door_type = str(door.get("doorType") or door.get("door_type") or "").lower()
    if door_type == "commercial":
        return "steel"
    return "wood"


def _run_calculator(*, series_key, width, height, lift, track, radius, high_lift, door) -> Optional[dict]:
    model = _calculator_model(series_key)
    if lift == "high_lift":
        lift_key = "high_lift"
    elif lift == "vertical":
        lift_key = "vertical"
    elif lift in ("lhr_front", "lhr_rear"):
        lift_key = "low_headroom"
    elif radius == 12 and track == 2:
        lift_key = "standard_12"
    else:
        lift_key = "standard_15"
    door_type = str(door.get("doorType") or door.get("door_type") or "commercial")
    try:
        return calculate_door_from_config({
            "door_model": model,
            "width": int(round(width)),
            "height": int(round(height)),
            "lift_type": lift_key,
            "track_size": track,
            "high_lift_inches": int(round(high_lift or 0)),
            "target_cycles": int(door.get("targetCycles") or door.get("target_cycles") or 10000),
            "shaft_type": door.get("shaftType") or door.get("shaft_type") or "auto",
            "door_type": door_type if door_type in ("residential", "commercial") else "commercial",
            "window_type": _window_type_key(door),
            "window_qty": int(door.get("windowQty") or door.get("window_qty") or 0),
            "double_end_caps": str(door.get("endCapType") or "").upper() == "DEC" or width > 192,
            "glazing_type": door.get("glazingType") or door.get("glazing_type") or "glass",
            "glass_pane_type": door.get("glassPaneType") or door.get("glass_pane_type") or "INSULATED",
        })
    except Exception as exc:
        logger.warning("Door calculator failed for shop drawing: %s", exc)
        return None


def _window_type_key(door: dict) -> Optional[str]:
    raw = str(door.get("windowInsert") or door.get("windowSize") or "").upper().replace("-", "X").replace(" ", "")
    for key in ("34X16", "24X12", "18X8", "12X24"):
        if key in raw:
            return key.lower()
    return None


def _shaft_from_calc(shaft: dict) -> tuple[str, bool]:
    if not shaft:
        return "1_solid", False
    kind = str(shaft.get("shaft_type") or "solid").lower()
    diameter = str(shaft.get("diameter") or "1")
    coupler = int(shaft.get("couplers") or 0) > 0
    if "1-1/4" in diameter or "1-1/4" in kind or kind == "1-1/4":
        return "1_25_solid", coupler
    if "tube" in kind:
        return "1_tubular", coupler
    return "1_solid", coupler


def _struts_from_calc(hardware: dict) -> tuple[int, int]:
    struts = (hardware or {}).get("struts") or {}
    n16 = 0
    n20 = 0
    for name, qty in struts.items():
        label = str(name).lower()
        if "clip" in label:
            continue
        try:
            n = int(qty)
        except (TypeError, ValueError):
            continue
        if "16" in label:
            n16 += n
        elif "20" in label or "hat" in label:
            n20 += n
    return n16, n20


def spring_lines(springs: Optional[dict]) -> list[SpringLine]:
    if not springs or not springs.get("quantity"):
        return []
    qty = int(springs["quantity"])
    wire = float(springs["wire_diameter"])
    coil = float(springs["coil_diameter"])
    length = float(springs["length"])
    if springs.get("is_duplex") and springs.get("inner_wire_diameter"):
        pairs = int(springs.get("duplex_pairs") or 0) or max(1, qty // 2)
        inner = (
            float(springs["inner_wire_diameter"]),
            float(springs["inner_coil_diameter"]),
            float(springs["inner_length"]),
        )
        hands = _split_hands(pairs)
        lines: list[SpringLine] = []
        for hand, n in hands:
            lines.append(SpringLine(hand, n, wire, coil, length, nested=False))
            lines.append(SpringLine(hand, n, inner[0], inner[1], inner[2], nested=True))
        return lines
    lines = []
    for hand, n in _split_hands(qty):
        lines.append(SpringLine(hand, n, wire, coil, length))
    return lines


def _split_hands(count: int) -> list[tuple[str, int]]:
    if count <= 0:
        return []
    if count == 1:
        return [("LHW", 1)]
    left = count // 2
    right = count - left
    out = []
    if left:
        out.append(("LHW", left))
    if right:
        out.append(("RHW", right))
    return out


def _windows(door: dict, section_count: int, series_key: str) -> WindowSpec:
    """Windows counted from the bottom, the way the sample sheets label them.

    The configurator numbers panels from the top (1 = top). This converts.
    """
    insert = str(door.get("windowInsert") or door.get("window_insert") or "")
    full_view = insert.upper() in ("V130G", "V230G", "PANORAMA") or series_key in _PANORAMA_PROFILE
    panels = door.get("windowPanels") or door.get("window_panels") or {}
    from_bottom: list[int] = []
    per: dict[int, int] = {}
    qty = 0
    if isinstance(panels, dict) and panels:
        for key, info in panels.items():
            try:
                from_top = int(key)
            except (TypeError, ValueError):
                continue
            n = section_count - from_top + 1
            if n < 1 or n > section_count:
                continue
            count = info.get("qty", 1) if isinstance(info, dict) else int(info or 1)
            count = int(count or 0)
            if count <= 0:
                continue
            per[n] = per.get(n, 0) + count
            qty += count
        from_bottom = sorted(per)
    else:
        raw_qty = int(door.get("windowQty") or door.get("window_qty") or 0)
        has = bool(door.get("hasWindows") or door.get("has_windows") or raw_qty or (insert and insert.upper() not in ("", "NONE")))
        if has and raw_qty <= 0 and series_key not in _PANORAMA_PROFILE:
            raw_qty = 0
        section_from_top = int(door.get("windowSection") or door.get("window_section") or 1)
        if raw_qty > 0 and section_count:
            n = section_count - section_from_top + 1
            n = min(section_count, max(1, n))
            from_bottom = [n]
            per[n] = raw_qty
            qty = raw_qty
        elif series_key in _PANORAMA_PROFILE:
            # Full-view aluminium: every section is glazed.
            from_bottom = list(range(1, section_count + 1))
            per = {n: 1 for n in from_bottom}
            qty = section_count
            full_view = True

    if series_key in _PANORAMA_PROFILE and not from_bottom:
        from_bottom = list(range(1, section_count + 1))
        per = {n: 1 for n in from_bottom}
        qty = section_count

    material = _glazing_material(insert, series_key)
    size = _glazing_size(door, series_key)
    if qty <= 0:
        return WindowSpec(0, "N/A", "N/A", [], {}, False)
    return WindowSpec(
        qty=qty,
        size_text=size,
        material=material,
        sections_from_bottom=from_bottom,
        per_section_qty=per,
        full_section=full_view or series_key in _PANORAMA_PROFILE,
    )


def _glazing_material(insert: str, series_key: str) -> str:
    if series_key in ("PANORAMA", "SOLALITE"):
        return "POLYCARBONATE"
    ins = (insert or "").upper()
    if not ins or ins == "NONE":
        return "N/A"
    if "THERM" in ins or "LOW" in ins:
        return "THERM, TEMP/TEMP LOW E"
    if "POLY" in ins:
        return "POLYCARBONATE"
    if ins in ("V130G", "V230G"):
        return "INSULATED GLASS"
    return ins.replace("_", " ")


def _glazing_size(door: dict, series_key: str) -> str:
    if series_key in _PANORAMA_PROFILE:
        return "FULL SECTION"
    raw = str(door.get("windowInsert") or door.get("windowSize") or "").upper().replace("-", "X").replace(" ", "")
    for key, label in _GLAZING_SIZES.items():
        if key in raw:
            return label
    size = str(door.get("windowSize") or "").lower()
    if size == "long":
        return '34" X 16"'
    if size == "short":
        return '12" X 24"'
    return "N/A"


# ─── number formatting ──────────────────────────────────────────────────────

def fmt_inches(value: float) -> str:
    """Decimal inches: 18"  35.5"  4.25"  3.5"."""
    v = float(value)
    if abs(v - round(v)) < 1e-6:
        return f'{int(round(v))}"'
    s = f"{v:.2f}".rstrip("0").rstrip(".")
    return f'{s}"'


def fmt_headroom(value: float, lift: str = "standard") -> str:
    """Decimal inches, matching the sample sheets (18\", 35\", 85\").

    Full vertical is the exception: the sheet prints the floor-to-ceiling
    figure in feet and inches (15'-6\" for a 14' door).
    """
    if lift == "vertical":
        return fmt_arch(value)
    return fmt_inches(value)


def fmt_arch(inches: float) -> str:
    """Architectural feet and inches: 16'-7"  10'-7 1/2"  1'-6"."""
    sign = "-" if inches < 0 else ""
    inches = abs(float(inches))
    feet = int(math.floor(inches / 12.0 + 1e-9))
    rem = inches - feet * 12.0
    if abs(rem - round(rem)) < 0.02:
        rem_s = str(int(round(rem)))
    else:
        whole = int(math.floor(rem + 1e-9))
        frac = rem - whole
        frac_s = _frac(frac)
        if frac_s is None:
            return f'{sign}{feet}\'-{rem:.1f}"'
        if not frac_s:
            rem_s = str(whole)
        elif whole <= 0:
            rem_s = frac_s
        else:
            rem_s = f"{whole} {frac_s}"
    return f'{sign}{feet}\'-{rem_s}"'


def fmt_arch_inches_only(inches: float) -> str:
    """1-3/4"  1-1/2"  2"."""
    v = float(inches)
    whole = int(math.floor(v + 1e-9))
    frac = _frac(v - whole)
    if abs(v - round(v)) < 0.02:
        return f'{int(round(v))}"'
    if frac and whole:
        return f'{whole}-{frac}"'
    if frac:
        return f'{frac}"'
    return f'{v:g}"'


def _frac(frac: float) -> Optional[str]:
    if abs(frac - 0.5) < 0.02:
        return "1/2"
    if abs(frac - 0.25) < 0.02:
        return "1/4"
    if abs(frac - 0.75) < 0.02:
        return "3/4"
    if abs(frac) < 0.02 or abs(frac - 1) < 0.02:
        return ""
    return None


def fmt_wire(value: float) -> str:
    s = f"{float(value):.4f}".rstrip("0").rstrip(".")
    if "." not in s:
        s += ".0"
    return s


def fmt_coil(value: float) -> str:
    v = float(value)
    known = {
        6.0: "6",
        3.75: "3-3/4",
        2.625: "2-5/8",
        2.0: "2",
        3.375: "3-3/8",
    }
    for key, label in known.items():
        if abs(v - key) < 0.02:
            return label
    return f"{v:g}"


def fmt_num(value: float) -> str:
    v = float(value)
    if abs(v - round(v)) < 0.02:
        return str(int(round(v)))
    return f"{v:.2f}".rstrip("0").rstrip(".")


def ordinal(n: int) -> str:
    if 10 <= (n % 100) <= 20:
        suf = "TH"
    else:
        suf = {1: "ST", 2: "ND", 3: "RD"}.get(n % 10, "TH")
    return f"{n}{suf}"


def _format_date_string(value: str) -> str:
    value = value.strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(value[:10], fmt).strftime("%d/%m/%Y")
        except ValueError:
            continue
    return value
