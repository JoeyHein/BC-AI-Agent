"""Framing drawing generator (Stage 1).

Creates a US Letter (8.5" × 11") portrait sheet in DXF with a proper title
block, border, and empty viewport. Exports to PDF via ezdxf's matplotlib
backend.

Stage 2 will render the actual door + framing geometry inside the viewport.
"""

from __future__ import annotations

import io
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Tuple

import ezdxf
from ezdxf.enums import TextEntityAlignment
from ezdxf.layouts import Modelspace

logger = logging.getLogger(__name__)

# ─── Sheet geometry ────────────────────────────────────────────────────────
# ANSI B landscape: 17" wide × 11" tall. All drawing units are inches.
# Matches the reference Panorama shop drawing layout — there's too much
# content (exterior elevation + interior + panel profile + plan + side view
# + extras checklist + window spec + title block) to fit on Letter.
SHEET_W = 17.0
SHEET_H = 11.0
MARGIN_L = 0.5
MARGIN_R = 0.5
MARGIN_T = 0.5
MARGIN_B = 0.5

# Title block: lower-right corner, 5.5" wide × 3.2" tall. Tall enough for
# the structured cells (DOOR SIZE/OPENING/SECTIONS, operator row, springs
# info, project/architect/drawn-by rows).
TITLE_BLOCK_W = 5.5
TITLE_BLOCK_H = 3.2

# ─── Layer definitions (name, ACI color, lineweight in 1/100 mm) ────────────
# ezdxf lineweight: -3=default, 0..211 = 1/100mm (e.g. 50 = 0.5mm)
# Colors: avoid ACI 7 (chameleon — white on white/black on black). Use 250
# (near-black dark gray) so entities always show on white paper. DIMENSIONS
# gets ACI 8 (gray) so they read as clearly secondary to the geometry.
LAYERS = [
    # name,          color, lineweight, linetype
    ("BORDER",         250,  50, "CONTINUOUS"),  # near-black, 0.5mm
    ("TITLE_BLOCK",    250,  35, "CONTINUOUS"),  # near-black, 0.35mm
    ("FRAMING",          1,  50, "CONTINUOUS"),  # red, 0.5mm
    ("HORIZONTALS",    250,  25, "CONTINUOUS"),  # near-black, 0.25mm — section joints
    ("TRACKS",           5,  35, "CONTINUOUS"),  # blue, 0.35mm
    ("STRUTS",           3,  35, "CONTINUOUS"),  # green, 0.35mm
    ("HARDWARE",         6,  35, "CONTINUOUS"),  # magenta, 0.35mm
    ("DIMENSIONS",       8,  18, "CONTINUOUS"),  # mid-gray, 0.18mm
    ("ANNOTATIONS",    250,  25, "CONTINUOUS"),  # near-black, 0.25mm
    ("HIDDEN",           8,  25, "HIDDEN"),      # gray, 0.25mm, hidden linetype
    ("CENTERLINE",       4,  18, "CENTER"),      # cyan, 0.18mm
]

# Text heights in inches (printed at 1:1 scale from the sheet)
TEXT_LARGE = 0.20     # title block headings
TEXT_MED   = 0.12     # title block values
TEXT_SMALL = 0.08     # annotations, dimension text


@dataclass
class DrawingContext:
    """Inputs for a framing drawing, pulled from SavedQuoteConfig + door entry."""
    job_number: str
    customer_name: str
    door_series: str
    door_type: str
    door_width_in: float
    door_height_in: float
    door_count: int
    drawing_date: str             # ISO date string
    designer: str = ""
    sheet_label: str = "1 OF 1"
    scale_label: str = "NTS"
    config_id: Optional[int] = None
    # Door construction/hardware inputs
    panel_design: str = "SHXL"    # SHXL, SH, BCXL, BC, FLUSH, TRAFALGAR, UDC
    panel_color: str = "WHITE"
    lift_type: str = "standard"   # standard, high_lift, full_vertical, low_headroom
    high_lift_inches: Optional[float] = None
    track_radius_in: float = 15.0 # "15" (15") or "12" (low-headroom)
    track_thickness_ga: str = "14"  # nominal track size: "2" (2") / "3" (3")
    track_mount: str = "bracket"  # "bracket" or "angle" (continuous angle)
    jamb_type: str = "wood"       # wood, steel
    insulated: bool = True
    section_height_in: float = 21.0  # aluminum 21", commercial 24", residential 21"
    # Spring + shaft selections
    target_cycles: int = 10000    # 10k = standard, 25k/50k/100k = upgraded
    shaft_type: str = "auto"      # auto, single, split, 1_solid, 1_25_solid, 1_tubular
    # Operator
    operator: str = "NONE"        # NONE, CHAIN_HOIST, electric models, ...
    # Hardware bundle (mirrors frontend door.hardware)
    has_struts: bool = True
    has_weather_stripping: bool = True
    has_bottom_retainer: bool = True
    # Glass / window selections
    has_windows: bool = False
    glass_pockets_per_section: Optional[dict] = None  # {section_idx: count} for AL/SWD
    # Aluminum-specific: pocket count (used when glass_pockets_per_section is None)
    al_pocket_count: Optional[int] = None
    # Additional optional extras (mirror the title-block extras checklist)
    man_door: bool = False
    man_door_spec: str = ""
    interior_lock: bool = False
    pusher_spring: bool = False
    bumper_spring: bool = False
    track_guards: bool = False
    exhaust_port: bool = False


# ─── DXF setup ──────────────────────────────────────────────────────────────

def _new_drawing() -> ezdxf.document.Drawing:
    """Create a new DXF document with our standard layer/linetype/text setup.

    R2013 chosen for broad compatibility with older AutoCAD / BricsCAD /
    LibreCAD. INSUNITS=1 marks the drawing as inches so downstream CAD tools
    know the measurement system.
    """
    doc = ezdxf.new(dxfversion="R2013", setup=True)
    doc.header["$INSUNITS"] = 1  # 1 = inches
    doc.header["$MEASUREMENT"] = 0  # 0 = imperial

    # Override the default "Standard" text style — ezdxf ships with it
    # pointing to txt.shx (an AutoCAD shape font matplotlib can't render),
    # which causes TEXT entities to silently drop when exporting to PDF.
    # LiberationSans is open-source Arial-compatible and bundled with ezdxf.
    std = doc.styles.get("Standard")
    std.dxf.font = "LiberationSans-Regular.ttf"

    # Register layers (setup=True already loaded standard linetypes
    # incl. HIDDEN, CENTER, DASHED)
    for name, color, lw, linetype in LAYERS:
        layer = doc.layers.add(name) if name not in doc.layers else doc.layers.get(name)
        layer.color = color
        layer.dxf.lineweight = lw
        layer.dxf.linetype = linetype

    # Ensure the "0" layer has safe defaults (0 is the default layer)
    zero = doc.layers.get("0")
    zero.color = 7
    zero.dxf.lineweight = 25

    return doc


# ─── Title block ────────────────────────────────────────────────────────────

def _draw_title_block(msp: Modelspace, ctx: DrawingContext) -> None:
    """Title block in the lower-right corner, modeled on the reference Panorama
    shop drawing. 5.5"w × 3.2"h divided into several regions.

    Layout (top → bottom):
      Row 1 (0.50"): Door opening (W/H) | Door size (W/H) | Sections | High H   (4 cells w/ sub-headers)
      Row 2 (0.50"): Electric operator — Model | HP | Volt | Ph                  (spec grid)
      Row 3 (0.55"): Springs info (turns) | Operator accessories (Name | Qty)
      Row 4 (0.35"): Distributor / Project name
      Row 5 (0.35"): Architect / Drawn by
      Row 6 (0.35"): Series  +  Date + Sheet
      Row 7 (0.60"): PANORAMA / SHXL large series banner
    """
    x0 = SHEET_W - MARGIN_R - TITLE_BLOCK_W
    y0 = MARGIN_B
    x1 = x0 + TITLE_BLOCK_W
    y1 = y0 + TITLE_BLOCK_H

    # Outer frame
    msp.add_lwpolyline(
        [(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)],
        close=True,
        dxfattribs={"layer": "TITLE_BLOCK", "lineweight": 50},
    )

    # Row heights top → bottom
    row_heights = [0.50, 0.50, 0.55, 0.35, 0.35, 0.35, 0.60]
    row_ys = [y1]
    for h in row_heights:
        row_ys.append(row_ys[-1] - h)
    for ry in row_ys[1:-1]:
        msp.add_line((x0, ry), (x1, ry), dxfattribs={"layer": "TITLE_BLOCK"})

    # ── Row 1: DOOR OPENING | DOOR SIZE | SECTIONS | HIGH H ─────────────
    r1_top = row_ys[0]
    r1_bot = row_ys[1]
    r1_widths = [1.6, 1.6, 1.1, 1.2]
    r1_xs = _col_xs(x0, r1_widths)
    for xc in r1_xs[1:]:
        msp.add_line((xc, r1_top), (xc, r1_bot), dxfattribs={"layer": "TITLE_BLOCK"})
    door_w_str = fmt_length_imperial(ctx.door_width_in)
    door_h_str = fmt_length_imperial(ctx.door_height_in)
    # Rough opening: width follows the +2" rule (RO = door − 2" for
    # X′-2″ variants, otherwise = door); height = door height.
    ro_w_str = fmt_length_imperial(_ro_width(ctx.door_width_in))
    num_sections_tb = max(3, int(ctx.door_height_in / ctx.section_height_in))
    high_h_str = (fmt_length_imperial(ctx.high_lift_inches)
                  if ctx.high_lift_inches else "—")
    r1_cells = [
        ("DOOR OPENING (W x H)", f"{ro_w_str} x {door_h_str}"),
        ("DOOR SIZE (W x H)",    f"{door_w_str} x {door_h_str}"),
        ("SECTIONS",             str(num_sections_tb)),
        ("HIGH H",               high_h_str),
    ]
    for (lbl, val), cx, cw in zip(r1_cells, r1_xs, r1_widths):
        _field(msp, cx + 0.06, r1_bot, lbl, val,
               cell_w=cw - 0.10, cell_h=row_heights[0])

    # ── Row 2: ELECTRIC OPERATOR (Model | HP | Volt | Ph) ───────────────
    r2_top = row_ys[1]
    r2_bot = row_ys[2]
    # Banner on left, 4 spec cells on right
    banner_w = 1.4
    spec_w = (TITLE_BLOCK_W - banner_w) / 4
    r2_xs = [x0, x0 + banner_w, x0 + banner_w + spec_w,
             x0 + banner_w + 2 * spec_w, x0 + banner_w + 3 * spec_w]
    for xc in r2_xs[1:]:
        msp.add_line((xc, r2_top), (xc, r2_bot), dxfattribs={"layer": "TITLE_BLOCK"})
    # Banner
    elec_banner = msp.add_text(
        "ELECTRIC\nOPERATOR",
        dxfattribs={"layer": "TITLE_BLOCK", "height": TEXT_SMALL, "style": "Standard"},
    )
    elec_banner.set_placement(
        (x0 + banner_w / 2, (r2_top + r2_bot) / 2),
        align=TextEntityAlignment.MIDDLE_CENTER,
    )
    # Spec headers only (values filled in from portal later)
    for (lbl,), cx in zip([("MODEL",), ("HP",), ("VOLT",), ("PH",)], r2_xs[1:]):
        _field(msp, cx + 0.04, r2_bot, lbl, "—",
               cell_w=spec_w - 0.08, cell_h=row_heights[1])

    # ── Row 3: SPRINGS INFO | OPERATOR ACCESSORIES ──────────────────────
    r3_top = row_ys[2]
    r3_bot = row_ys[3]
    mid_x = x0 + TITLE_BLOCK_W / 2
    msp.add_line((mid_x, r3_top), (mid_x, r3_bot),
                 dxfattribs={"layer": "TITLE_BLOCK"})
    springs_lbl = msp.add_text(
        "SPRINGS INFO  (TURNS)",
        dxfattribs={"layer": "TITLE_BLOCK", "height": TEXT_SMALL, "style": "Standard"},
    )
    springs_lbl.set_placement((x0 + 0.08, r3_top - 0.10),
                              align=TextEntityAlignment.MIDDLE_LEFT)
    accessories_lbl = msp.add_text(
        "OPERATOR ACCESSORIES",
        dxfattribs={"layer": "TITLE_BLOCK", "height": TEXT_SMALL, "style": "Standard"},
    )
    accessories_lbl.set_placement((mid_x + 0.08, r3_top - 0.10),
                                  align=TextEntityAlignment.MIDDLE_LEFT)
    # Empty rows for field staff to fill in
    for y_off in (0.22, 0.35, 0.48):
        msp.add_line((x0 + 0.10, r3_top - y_off), (mid_x - 0.10, r3_top - y_off),
                     dxfattribs={"layer": "TITLE_BLOCK", "lineweight": 9})
        msp.add_line((mid_x + 0.10, r3_top - y_off), (x1 - 0.10, r3_top - y_off),
                     dxfattribs={"layer": "TITLE_BLOCK", "lineweight": 9})

    # ── Row 4: DISTRIBUTOR | PROJECT NAME ────────────────────────────────
    # PROJECT NAME carries the job number — reference uses one field for both.
    _kv_row(msp, row_ys[3], row_ys[4], x0, x1,
            [("DISTRIBUTOR", "OPEN DISTRIBUTION COMPANY", 3.0),
             ("PROJECT NAME / JOB #", ctx.job_number or "—", TITLE_BLOCK_W - 3.0)])

    # ── Row 5: ARCHITECT | DRAWN BY ──────────────────────────────────────
    _kv_row(msp, row_ys[4], row_ys[5], x0, x1,
            [("ARCHITECT", "—", 3.0),
             ("DRAWN BY", ctx.designer or ctx.customer_name or "—",
              TITLE_BLOCK_W - 3.0)])

    # ── Row 6: SERIES | DATE | SHEET ─────────────────────────────────────
    _kv_row(msp, row_ys[5], row_ys[6], x0, x1,
            [("SERIES", ctx.door_series, 2.0),
             ("DATE", ctx.drawing_date, 2.0),
             ("SHEET", ctx.sheet_label, TITLE_BLOCK_W - 4.0)])

    # ── Row 7: Big series banner ─────────────────────────────────────────
    banner = msp.add_text(
        ctx.door_series.upper() if ctx.door_series else "FRAMING DRAWING",
        dxfattribs={"layer": "TITLE_BLOCK", "height": 0.32, "style": "Standard"},
    )
    banner.set_placement(
        ((x0 + x1) / 2, (row_ys[6] + row_ys[7]) / 2),
        align=TextEntityAlignment.MIDDLE_CENTER,
    )


def _col_xs(x0: float, widths: list[float]) -> list[float]:
    """Return starting x for each column given a list of widths."""
    xs = [x0]
    for w in widths[:-1]:
        xs.append(xs[-1] + w)
    return xs


def _kv_row(msp: Modelspace, row_top: float, row_bot: float,
            row_x0: float, row_x1: float,
            cells: list[tuple[str, str, float]]) -> None:
    """Draw a single row of labeled cells. cells = [(label, value, width), ...]."""
    xs = _col_xs(row_x0, [w for _, _, w in cells])
    for xc in xs[1:]:
        msp.add_line((xc, row_top), (xc, row_bot),
                     dxfattribs={"layer": "TITLE_BLOCK"})
    for (lbl, val, w), cx in zip(cells, xs):
        _field(msp, cx + 0.06, row_bot, lbl, val,
               cell_w=w - 0.10, cell_h=row_top - row_bot)


def _field(msp: Modelspace, x: float, y_base: float, label: str, value: str,
           cell_w: float, cell_h: float) -> None:
    """Draw a labeled field inside a title-block cell.

    Label is small text in the top-left of the cell; value is medium text
    centered in the lower portion.
    """
    # Label (top-left, small)
    lbl = msp.add_text(
        label,
        dxfattribs={"layer": "TITLE_BLOCK", "height": TEXT_SMALL, "style": "Standard"},
    )
    lbl.set_placement((x, y_base + cell_h - 0.10), align=TextEntityAlignment.MIDDLE_LEFT)

    # Value (centered in lower portion)
    val = msp.add_text(
        value or "—",
        dxfattribs={"layer": "TITLE_BLOCK", "height": TEXT_MED, "style": "Standard"},
    )
    val.set_placement(
        (x + cell_w / 2 - 0.05, y_base + cell_h * 0.35),
        align=TextEntityAlignment.MIDDLE_CENTER,
    )


def _fmt_size(w_in: float, h_in: float, count: int) -> str:
    """Format "(2) 16'-0\" x 8'-0\"" style size label."""
    qty = f"({count}) " if count and count > 1 else ""
    return f"{qty}{fmt_length_imperial(w_in)} x {fmt_length_imperial(h_in)}"


# ─── Length formatters ─────────────────────────────────────────────────────
# Portal data is in inches; these helpers format for display and optionally
# add mm alongside for customers/installers who work in metric.

MM_PER_INCH = 25.4


def fmt_length_imperial(inches: float) -> str:
    """Format inches as feet-inches: e.g. 192 → "16'-0\"" or 110 → "9'-2\"".

    Partial inches (fractions of an inch) are shown as decimals when needed.
    """
    feet = int(inches // 12)
    rem = round(inches - feet * 12, 2)
    if rem == int(rem):
        rem_str = str(int(rem))
    else:
        rem_str = f"{rem:g}"
    return f"{feet}'-{rem_str}\""


def fmt_length_dual(inches: float, mm_precision: int = 0) -> str:
    """Format a length in both imperial and metric: `16'-0" [4877mm]`.

    Used for dimension text so customers/fabricators who work in mm don't
    have to convert mentally. mm_precision=0 rounds to the nearest mm.
    """
    mm = inches * MM_PER_INCH
    mm_str = f"{mm:.{mm_precision}f}".rstrip("0").rstrip(".")
    if not mm_str:
        mm_str = "0"
    return f"{fmt_length_imperial(inches)} [{mm_str}mm]"


# ─── Sheet border + viewport placeholder ───────────────────────────────────

def _draw_sheet_border(msp: Modelspace) -> None:
    """Outer sheet border (full sheet size) and inner drawing border (inside margins)."""
    # Outer sheet edge — thin line showing paper extent
    msp.add_lwpolyline(
        [(0, 0), (SHEET_W, 0), (SHEET_W, SHEET_H), (0, SHEET_H), (0, 0)],
        close=True,
        dxfattribs={"layer": "BORDER", "lineweight": 18},
    )

    # Inner drawing border — thick line
    msp.add_lwpolyline(
        [
            (MARGIN_L, MARGIN_B),
            (SHEET_W - MARGIN_R, MARGIN_B),
            (SHEET_W - MARGIN_R, SHEET_H - MARGIN_T),
            (MARGIN_L, SHEET_H - MARGIN_T),
            (MARGIN_L, MARGIN_B),
        ],
        close=True,
        dxfattribs={"layer": "BORDER", "lineweight": 50},
    )


# ── Track type → label mapping ──────────────────────────────────────────────
LIFT_TYPE_LABELS = {
    "standard": "STANDARD LIFT TRACKS",
    "high_lift": "HIGH LIFT TRACKS",
    "full_vertical": "FULL VERTICAL LIFT TRACKS",
    "low_headroom": "LOW HEADROOM FRONT MOUNT",
}


def _stamp_columns(width_inches: float, stamp_type: str, is_craft: bool,
                   panel_design: str) -> int:
    """Mirror of getStampColumns() in DoorPreview.jsx — number of panel
    stamps horizontally for the given width and panel design."""
    width_feet = width_inches / 12
    # Long stamps (SHXL, BCXL): ~42" wide
    if width_feet < 12:
        long_cols = 2
    elif width_feet <= 14:
        long_cols = 3
    elif width_feet <= 16:
        long_cols = 4
    elif width_feet <= 19:
        long_cols = 5
    else:
        long_cols = 6

    if is_craft or stamp_type == "long":
        return long_cols

    is_bronte = panel_design == "BC"
    if is_bronte:
        if width_feet <= 10:
            return 4
        if width_feet <= 14:
            return 6
        if width_feet <= 16:
            return 8
        if width_feet <= 18:
            return 8
        return 10
    # SH (Sheridan standard)
    if width_feet <= 9:
        return 4
    if width_feet <= 10:
        return 5
    if width_feet <= 12:
        return 6
    if width_feet <= 14:
        return 7
    if width_feet <= 16:
        return 8
    if width_feet <= 18:
        return 9
    return 10


def _middle_hinge_count(width_inches: float) -> int:
    """Legacy helper kept for backward compatibility — prefer _hinge_columns().
    Number of intermediate (middle) hinges per horizontal section joint,
    in addition to the two end hinges at the jambs.
    """
    return max(0, _hinge_columns(width_inches) - 2)


def _hinge_columns(width_inches: float) -> int:
    """Total hinge columns across the door (including end columns at each
    jamb). Rule: max(3, ceil(W″/60) + 1).

    Spaces hinges no further than ~60″ apart, ensuring minimum 3 columns
    even on narrow doors (jamb + center + jamb). Validated against the
    OPENDC reference DXF for both TX commercial and Kanata/Craft
    residential — same rule applies.
    """
    import math
    return max(3, math.ceil(width_inches / 60.0) + 1)


def _al_pocket_count(width_inches: float) -> int:
    """Mirrors frontend glassPockets.js defaultPocketsForWidth(): glass
    pocket count per row for AL976/SWD/PANORAMA. Pockets = bays between
    stiles, so internal stile count = pockets - 1.
    """
    f = width_inches / 12
    if f <= 10: return 3
    if f <= 14: return 4
    if f <= 18: return 5
    if f <= 22: return 6
    return 7


def _is_plus_two_variant(width_inches: float) -> bool:
    """True for the X′-2″ door variants (8′-2″, 9′-2″, ...). These ship
    with a rough opening 2″ smaller than the door (the extra 2″ of door
    overlaps onto the jamb face, giving 1″ of overlap per side)."""
    rem = round(width_inches - int(width_inches // 12) * 12, 2)
    return abs(rem - 2.0) < 0.01


def _ro_width(door_width_in: float) -> float:
    """Rough-opening width per OPENDC convention:
      - Standard door (e.g., 8′-0″): RO = door width
      - +2″ variant (e.g., 8′-2″):   RO = door width − 2″
    Height is unaffected (RO height = door height).
    """
    return door_width_in - 2.0 if _is_plus_two_variant(door_width_in) else door_width_in


def _draw_front_elevation(msp: Modelspace, ctx: DrawingContext,
                          box: Tuple[float, float, float, float],
                          view: str = "interior") -> None:
    """Front elevation with jambs, header, section joints, panel stamps /
    glass pockets, hinges, tracks, and dimension chain.

    Sectional doors install AGAINST the jambs (not inside them like a
    swinging door's leaf), so the door slab here is drawn spanning
    OUTSIDE the jamb edges — i.e., the slab covers the full door width
    and overlaps onto the jamb face on each side.

    Two modes:
      view="interior":  DOOR FACE: INSIDE LOOKING OUT — shows shaft + springs
                        above the door, dim chain, hinges on section joints.
      view="exterior":  DOOR FACE: OUTSIDE LOOKING IN — same door but with
                        surrounding wall context (simple hatch), no shaft.
    """
    draw_x0, draw_y0, draw_x1, draw_y1 = box
    draw_w = draw_x1 - draw_x0
    draw_h = draw_y1 - draw_y0
    is_interior = view == "interior"

    # Door + jambs + header + tracks footprint
    JAMB_VIS_W = 3.5        # visible jamb width on drawing (2x6)
    HEADER_VIS_H = 12.0     # visible header height
    TRACK_OFFSET = 2.75     # horizontal distance from jamb to track centerline
    # Extra vertical space above header for shaft + springs on interior view.
    # Exterior view omits the shaft so less height is needed.
    TRACK_EXTENSION = 18.0 if is_interior else 10.0
    door_w = ctx.door_width_in or 96.0
    door_h = ctx.door_height_in or 84.0
    ro_w = _ro_width(door_w)
    # Interior view extends the footprint width to include shaft past jambs
    SHAFT_OVERHANG = 6.0 if is_interior else 0.0  # shaft extends past each jamb
    footprint_w = door_w + 2 * JAMB_VIS_W + 2 * TRACK_OFFSET + 2 * SHAFT_OVERHANG
    footprint_h = door_h + HEADER_VIS_H + TRACK_EXTENSION

    # Fit-to-viewport scale. Reserve ~0.5" at top for two title lines +
    # track-type label, and ~0.6" at bottom for two dim chains + jamb labels.
    title_reserve = 0.55
    bottom_reserve = 0.55
    usable_w = draw_w * 0.80
    usable_h = draw_h - title_reserve - bottom_reserve
    scale = min(usable_w / footprint_w, usable_h / footprint_h)

    draw_cx = (draw_x0 + draw_x1) / 2
    # Anchor the footprint's bottom at draw_y0 + bottom_reserve so nothing
    # collides with the sub-box below. The header-and-tracks fit above.
    fx0 = draw_cx - (footprint_w * scale) / 2
    fy0 = draw_y0 + bottom_reserve

    def DX(inches: float) -> float:
        """Convert real-world inches → sheet-space inches."""
        return inches * scale

    # Key geometry anchors (origin at footprint lower-left = fx0, fy0).
    # x-layout: [track][jamb][RO opening][jamb][track], with the door
    # slab overlaying — extending OUTSIDE the jambs (sectional install
    # convention). For +2" variants, the door is 2" wider than the RO,
    # so it overlaps 1" onto each jamb face.
    left_track_x = fx0 + DX(0)
    jl_x0 = fx0 + DX(TRACK_OFFSET)
    jl_x1 = jl_x0 + DX(JAMB_VIS_W)
    # Rough opening edges = inside faces of the jambs
    ro_x0 = jl_x1
    ro_x1 = ro_x0 + DX(ro_w)
    jr_x0 = ro_x1
    jr_x1 = jr_x0 + DX(JAMB_VIS_W)
    right_track_x = jr_x1 + DX(TRACK_OFFSET)
    # Door slab: centered on the RO, extends to the door width.
    # For standard door: door_w == ro_w, so door edges align with RO edges
    # (+ jamb inside). For +2" variant: door extends 1" onto each jamb.
    door_overlap = (door_w - ro_w) / 2  # 0 for standard, 1.0 for +2" variant
    d_x0 = ro_x0 - DX(door_overlap)
    d_x1 = ro_x1 + DX(door_overlap)
    # y-layout: [ground at fy0][door to fy0+door_h][header][track extension]
    d_y0 = fy0
    d_y1 = fy0 + DX(door_h)
    hdr_y0 = d_y1
    hdr_y1 = hdr_y0 + DX(HEADER_VIS_H)
    track_top_y = hdr_y1 + DX(TRACK_EXTENSION)

    # ── Header ───────────────────────────────────────────────────────────
    msp.add_lwpolyline(
        [(jl_x0, hdr_y0), (jr_x1, hdr_y0), (jr_x1, hdr_y1),
         (jl_x0, hdr_y1), (jl_x0, hdr_y0)],
        close=True,
        dxfattribs={"layer": "FRAMING"},
    )
    hdr_label = msp.add_text(
        "HEADER",
        dxfattribs={"layer": "ANNOTATIONS", "height": TEXT_SMALL, "style": "Standard"},
    )
    hdr_label.set_placement(((jl_x0 + jr_x1) / 2, (hdr_y0 + hdr_y1) / 2),
                            align=TextEntityAlignment.MIDDLE_CENTER)

    # ── Jambs (left + right) — drawn BEHIND the door slab so the slab
    # visibly overlaps onto the jamb faces ─────────────────────────────
    for jx0, jx1 in [(jl_x0, jl_x1), (jr_x0, jr_x1)]:
        msp.add_lwpolyline(
            [(jx0, d_y0), (jx1, d_y0), (jx1, d_y1), (jx0, d_y1), (jx0, d_y0)],
            close=True,
            dxfattribs={"layer": "FRAMING"},
        )

    # Jamb labels (below door)
    for x_label in ((jl_x0 + jl_x1) / 2, (jr_x0 + jr_x1) / 2):
        lbl = msp.add_text(
            "JAMB",
            dxfattribs={"layer": "ANNOTATIONS", "height": TEXT_SMALL, "style": "Standard"},
        )
        lbl.set_placement((x_label, d_y0 - 0.14),
                          align=TextEntityAlignment.MIDDLE_CENTER)

    # ── Door panel ───────────────────────────────────────────────────────
    msp.add_lwpolyline(
        [(d_x0, d_y0), (d_x1, d_y0), (d_x1, d_y1), (d_x0, d_y1), (d_x0, d_y0)],
        close=True,
        dxfattribs={"layer": "FRAMING", "lineweight": 40},
    )

    # ── Section divisions (use ctx.section_height_in) ────────────────────
    # int() floors — 8' door (96")/21" = 4.57 → 4 sections (residential standard),
    # 9' (108")/21" → 5, 10' (120")/21" → 5, matches typical residential builds.
    section_h_in = ctx.section_height_in
    num_sections = max(3, int(door_h / section_h_in))
    real_section_h = door_h / num_sections
    section_ys = [d_y0 + DX(real_section_h * i) for i in range(num_sections + 1)]
    for y in section_ys[1:-1]:
        msp.add_line((d_x0, y), (d_x1, y), dxfattribs={"layer": "HORIZONTALS"})

    # ── Per-series body fill (panel stamps / glass pockets / ribs) ─────
    if _is_aluminum_series(ctx.door_series):
        _draw_aluminum_pockets(
            msp, ctx,
            door_bbox=(d_x0, d_y0, d_x1, d_y1),
            section_ys=section_ys,
        )
    elif _is_commercial_series(ctx.door_series):
        # TX-series: solid steel face with horizontal rib stamps, no stiles
        _draw_tx_ribs(
            msp, ctx,
            door_bbox=(d_x0, d_y0, d_x1, d_y1),
            section_ys=section_ys,
        )
    else:
        # Residential (Kanata SHXL/BCXL/BC/SH, Craft, Trafalgar): solid
        # face with stamped panel pattern. No internal stiles — only
        # horizontal section joints already drawn above.
        _draw_panel_stamps(
            msp, ctx,
            door_bbox=(d_x0, d_y0, d_x1, d_y1),
            section_ys=section_ys,
        )

    # ── Hinges at each internal section joint ────────────────────────────
    _draw_hinges(
        msp, ctx,
        door_bbox=(d_x0, d_y0, d_x1, d_y1),
        section_ys=section_ys,
        scale=scale,
    )

    # ── Tracks (vertical lines outside jambs, extending above header) ────
    for tx in (left_track_x, right_track_x):
        msp.add_line((tx, d_y0), (tx, track_top_y),
                     dxfattribs={"layer": "TRACKS"})
        # Rail marker ticks every ~24" along track
        rail_spacing = 24.0
        rail_marks = int((door_h + HEADER_VIS_H + TRACK_EXTENSION) / rail_spacing)
        for m in range(1, rail_marks + 1):
            y = fy0 + DX(rail_spacing * m)
            if y < track_top_y - DX(1):
                side = -1 if tx == left_track_x else 1
                msp.add_line(
                    (tx + side * 0.04, y), (tx + side * 0.12, y),
                    dxfattribs={"layer": "TRACKS"},
                )

    # ── Shaft + springs above header (interior view only) ──────────────
    if is_interior:
        _draw_shaft_and_springs(
            msp, ctx,
            left_x=left_track_x - DX(SHAFT_OVERHANG),
            right_x=right_track_x + DX(SHAFT_OVERHANG),
            door_top_y=d_y1,
            header_top_y=hdr_y1,
            track_top_y=track_top_y,
            scale=scale,
        )

    # Track type label above the tracks
    track_lbl = msp.add_text(
        LIFT_TYPE_LABELS.get(ctx.lift_type, "STANDARD LIFT TRACKS"),
        dxfattribs={"layer": "ANNOTATIONS", "height": TEXT_SMALL, "style": "Standard"},
    )
    track_lbl.set_placement(
        (draw_cx, track_top_y + 0.10),
        align=TextEntityAlignment.MIDDLE_CENTER,
    )

    # ── Width dimension (door slab width) ────────────────────────────────
    dim_y_inner = d_y0 - 0.30
    if dim_y_inner < draw_y0 + 0.15:
        dim_y_inner = draw_y0 + 0.15
    _draw_linear_dim(msp, (d_x0, d_y0), (d_x1, d_y0), dim_y_inner,
                     label=fmt_length_dual(door_w))

    # ── Rough-opening dimension — between jamb inside faces ────────────
    # OPENDC convention: RO = door width for standard sizes; RO = door − 2"
    # for the +2" variants (which overlap 1" onto each jamb face).
    dim_y_ro = dim_y_inner - 0.30
    if dim_y_ro < draw_y0 + 0.08:
        dim_y_ro = draw_y0 + 0.08
    _draw_linear_dim(msp, (ro_x0, d_y0), (ro_x1, d_y0), dim_y_ro,
                     label=f"R.O. {fmt_length_dual(ro_w)}")

    # ── Height dimension (right side of door) ────────────────────────────
    dim_x = right_track_x + 0.20
    if dim_x > draw_x1 - 0.25:
        dim_x = draw_x1 - 0.25
    _draw_linear_dim_vertical(msp, (d_x1, d_y0), (d_x1, d_y1), dim_x,
                              label=fmt_length_dual(door_h))

    # ── Header dimension ─────────────────────────────────────────────────
    _draw_linear_dim_vertical(msp, (d_x1, d_y1), (d_x1, hdr_y1), dim_x,
                              label=fmt_length_dual(HEADER_VIS_H),
                              extra_offset=0.22)

    # ── View title (includes panel design + section count) ──────────────
    view_title_main = msp.add_text(
        "DOOR FACE: INSIDE LOOKING OUT" if is_interior
        else "DOOR FACE: OUTSIDE LOOKING IN",
        dxfattribs={"layer": "ANNOTATIONS", "height": TEXT_MED, "style": "Standard"},
    )
    view_title_main.set_placement(
        (draw_cx, draw_y1 - 0.10),
        align=TextEntityAlignment.MIDDLE_CENTER,
    )
    if is_interior:
        view_title_sub = msp.add_text(
            f"{num_sections} SECTIONS @ {fmt_length_imperial(real_section_h)}    "
            f"DESIGN: {ctx.panel_design}    FINISH: {ctx.panel_color}",
            dxfattribs={"layer": "ANNOTATIONS", "height": TEXT_SMALL, "style": "Standard"},
        )
        view_title_sub.set_placement(
            (draw_cx, draw_y1 - 0.28),
            align=TextEntityAlignment.MIDDLE_CENTER,
        )


# ─── Panel stamps ───────────────────────────────────────────────────────────

def _draw_panel_stamps(msp: Modelspace, ctx: DrawingContext,
                       door_bbox: Tuple[float, float, float, float],
                       section_ys: list[float]) -> None:
    """Draw the panel design stamp pattern on the door face. Mirrors the logic
    in DoorPreview.jsx so the shop drawing matches the configurator preview.
    """
    d_x0, d_y0, d_x1, d_y1 = door_bbox
    design = ctx.panel_design or "SHXL"

    # Flush / smooth finish: no stamp pattern, skip
    if design in {"FLUSH", "SMOOTH"}:
        return

    is_craft = ctx.door_series == "CRAFT"
    # Long-stamp designs (SHXL, BCXL) get one stamp per column per section
    # Short-stamp designs (SH, BC) get stamp-count based on a different formula
    stamp_type = "long" if design in {"SHXL", "BCXL"} else "short"
    cols = _stamp_columns(ctx.door_width_in, stamp_type, is_craft, design)

    # Draw stamp rectangles inside each section, inset from the section edges
    section_inset_x = (d_x1 - d_x0) * 0.015
    section_inset_y = 0.04
    col_w = (d_x1 - d_x0 - 2 * section_inset_x) / cols
    col_gap = min(col_w * 0.08, 0.04)

    for i in range(len(section_ys) - 1):
        sec_y0 = section_ys[i] + section_inset_y
        sec_y1 = section_ys[i + 1] - section_inset_y
        if sec_y1 - sec_y0 < 0.05:
            continue
        for c in range(cols):
            sx0 = d_x0 + section_inset_x + c * col_w + col_gap / 2
            sx1 = sx0 + col_w - col_gap
            msp.add_lwpolyline(
                [(sx0, sec_y0), (sx1, sec_y0), (sx1, sec_y1),
                 (sx0, sec_y1), (sx0, sec_y0)],
                close=True,
                dxfattribs={"layer": "ANNOTATIONS", "lineweight": 13},
            )

    # Panel design is noted in the view title — no separate label needed here


# ─── Series classification + per-series body rendering ─────────────────────

ALUMINUM_SERIES = {"AL976", "SWD", "PANORAMA", "SOLALITE"}
COMMERCIAL_SERIES = {"TX380", "TX450", "TX500", "TX450-20", "TX500-20"}


def _is_aluminum_series(series: str) -> bool:
    return (series or "").upper() in ALUMINUM_SERIES


def _is_commercial_series(series: str) -> bool:
    return (series or "").upper() in COMMERCIAL_SERIES


def _panel_thickness_in(series: str, door_type: str) -> float:
    """Door panel thickness in inches. TX-series subseries differ only in
    panel thickness (no visible difference in elevation):
      TX380   → 38mm = 1-1/2″
      TX450   → 45mm = 1-3/4″
      TX500   → 50mm = 2″
      TX450-20, TX500-20 inherit their base thickness.

    Aluminum series use 1-3/4″ regardless of pocket count.
    Residential default is 1-3/4″.
    """
    s = (series or "").upper()
    MM_TO_IN = 1.0 / 25.4
    tx_thickness_mm = {
        "TX380": 38, "TX450": 45, "TX500": 50,
        "TX450-20": 45, "TX500-20": 50,
    }
    if s in tx_thickness_mm:
        return round(tx_thickness_mm[s] * MM_TO_IN * 8) / 8.0  # nearest 1/8"
    if s in ALUMINUM_SERIES:
        return 1.75
    # Residential
    return 1.75


def _draw_aluminum_pockets(msp: Modelspace, ctx: DrawingContext,
                           door_bbox: Tuple[float, float, float, float],
                           section_ys: list[float]) -> None:
    """Aluminum-series glass pocket grid: vertical stiles divide each
    section into N glass pockets per row. Stile count comes from the
    width-based rule in glassPockets.js, mirrored by _al_pocket_count().

    Per-section pocket-count overrides (AL976/SWD center-stile customizations)
    are read from ctx.glass_pockets_per_section when present.
    """
    d_x0, d_y0, d_x1, d_y1 = door_bbox
    door_w = d_x1 - d_x0
    default_pockets = _al_pocket_count(ctx.door_width_in)
    overrides = ctx.glass_pockets_per_section or {}

    for i in range(len(section_ys) - 1):
        sec_y0 = section_ys[i]
        sec_y1 = section_ys[i + 1]
        # Per-section override or default
        n_pockets = overrides.get(i) or overrides.get(str(i)) or default_pockets
        n_pockets = max(1, int(n_pockets))
        # Vertical stile lines (interior bay dividers)
        for k in range(1, n_pockets):
            sx = d_x0 + door_w * (k / n_pockets)
            msp.add_line((sx, sec_y0), (sx, sec_y1),
                         dxfattribs={"layer": "FRAMING", "lineweight": 25})
        # Glass pocket rectangles (slight inset from stiles + section edges)
        bay_w = door_w / n_pockets
        inset_x = min(bay_w * 0.06, 0.04)
        inset_y = min((sec_y1 - sec_y0) * 0.08, 0.05)
        for k in range(n_pockets):
            px0 = d_x0 + bay_w * k + inset_x
            px1 = d_x0 + bay_w * (k + 1) - inset_x
            py0 = sec_y0 + inset_y
            py1 = sec_y1 - inset_y
            if px1 - px0 < 0.02 or py1 - py0 < 0.02:
                continue
            msp.add_lwpolyline(
                [(px0, py0), (px1, py0), (px1, py1),
                 (px0, py1), (px0, py0)],
                close=True,
                dxfattribs={"layer": "ANNOTATIONS", "lineweight": 13},
            )


def _draw_tx_ribs(msp: Modelspace, ctx: DrawingContext,
                  door_bbox: Tuple[float, float, float, float],
                  section_ys: list[float]) -> None:
    """TX-series commercial sectional: solid steel face with fine
    horizontal rib stamps in each section. NO internal stiles — only
    the horizontal section joints already drawn above.
    Reference: OPENDC catalog DXF TX-SERIES region. Each section shows
    ~10 horizontal embossed grooves per panel.
    """
    d_x0, _, d_x1, _ = door_bbox
    RIBS_PER_SECTION = 10
    rib_inset_x = min((d_x1 - d_x0) * 0.015, 0.04)
    for i in range(len(section_ys) - 1):
        sec_y0 = section_ys[i]
        sec_y1 = section_ys[i + 1]
        sec_h = sec_y1 - sec_y0
        if sec_h < 0.05:
            continue
        # Distribute ribs evenly within the section, with a small margin
        # from the section joints so rib lines don't merge with joints.
        margin = sec_h * 0.10
        usable = sec_h - 2 * margin
        for r in range(RIBS_PER_SECTION):
            ry = sec_y0 + margin + usable * (r / max(RIBS_PER_SECTION - 1, 1))
            msp.add_line(
                (d_x0 + rib_inset_x, ry), (d_x1 - rib_inset_x, ry),
                dxfattribs={"layer": "ANNOTATIONS", "lineweight": 9},
            )


# ─── Side elevation ─────────────────────────────────────────────────────────

# Real-world dimensions for side view. Door thickness is exaggerated for
# visibility (actual ~1.75" but that's a hairline at our scale).
DOOR_THICKNESS_VIS_IN = 4.0      # visible door thickness on side view
HEADROOM_REQ = {                  # minimum headroom by lift type
    "standard":     12.0,
    "high_lift":    None,         # filled from ctx.high_lift_inches
    "full_vertical": None,        # filled from ctx.door_height_in (roughly)
    "low_headroom":  6.0,
}
BACKROOM_MARGIN = 18.0            # door height + ~18" typical backroom


def _draw_side_elevation(msp: Modelspace, ctx: DrawingContext,
                         box: Tuple[float, float, float, float]) -> None:
    """Side view showing track path, headroom, backroom, and door thickness.

    Geometry (in real-world inches, drawn with fit-to-box scale):
      x-axis: backroom (horizontal track run, into the building)
      y-axis: height (floor at bottom, ceiling above header)

    Track path:
      - Door face is at x = 0 (right edge of frame).
      - Vertical track runs straight up from floor (y=0) to somewhere near
        the top of the door height.
      - Radius curves back horizontally over ~R (15" typical).
      - Horizontal track extends backward to ~door_h + headroom.
    """
    bx0, by0, bx1, by1 = box
    box_w = bx1 - bx0
    box_h = by1 - by0

    door_h = ctx.door_height_in or 84.0
    door_thick = DOOR_THICKNESS_VIS_IN
    radius = ctx.track_radius_in or 15.0

    # Determine headroom + backroom based on lift type
    lift = ctx.lift_type
    if lift == "high_lift" and ctx.high_lift_inches:
        headroom = ctx.high_lift_inches + 6.0
    elif lift == "full_vertical":
        headroom = door_h + 6.0
    elif lift == "low_headroom":
        headroom = 6.0
    else:
        headroom = 12.0
    # Backroom = door height + some margin for horizontal track return
    backroom = door_h + BACKROOM_MARGIN

    view_w = backroom + door_thick + 10  # +10" padding front of door
    view_h = door_h + headroom + 24

    # Border/label space reservation
    usable_w = box_w * 0.78
    usable_h = box_h * 0.74
    scale = min(usable_w / view_w, usable_h / view_h)

    # Position view within the box
    cx = (bx0 + bx1) / 2
    cy = (by0 + by1) / 2
    # Place origin (floor-right / door-face) so that the full view fits
    view_x0 = cx - (view_w * scale) / 2     # left edge of side view in sheet space
    view_y0 = cy - (view_h * scale) / 2 + 0.15  # leave room at bottom for labels

    def SX(inches: float) -> float:
        return inches * scale

    # Sheet-space helper coordinates. The door face is at the RIGHT of the
    # side view (x_face), backroom extends LEFT (decreasing x).
    x_face = view_x0 + SX(view_w - 5)     # door face near right edge (5" margin)
    x_back = x_face - SX(backroom)        # backroom extends left
    y_floor = view_y0 + 0.10              # floor line
    y_door_top = y_floor + SX(door_h)
    y_track_horiz = y_door_top + SX(headroom)  # horizontal track elevation
    y_ceiling = y_floor + SX(view_h - 2)

    # ── Title ────────────────────────────────────────────────────────────
    t = msp.add_text(
        f"SIDE VIEW — {LIFT_TYPE_LABELS.get(lift, 'STANDARD LIFT')}",
        dxfattribs={"layer": "ANNOTATIONS", "height": TEXT_MED, "style": "Standard"},
    )
    t.set_placement((cx, by1 - 0.12),
                    align=TextEntityAlignment.MIDDLE_CENTER)
    # Subtitle row: jamb material + track size + R= radius
    sub_lines = [
        f"{ctx.jamb_type.upper()} JAMB",
        f"{ctx.track_thickness_ga}\" TRACK",
        f"R = {fmt_length_imperial(ctx.track_radius_in)}",
    ]
    sub = msp.add_text(
        "    ".join(sub_lines),
        dxfattribs={"layer": "ANNOTATIONS", "height": TEXT_SMALL, "style": "Standard"},
    )
    sub.set_placement((cx, by1 - 0.28),
                      align=TextEntityAlignment.MIDDLE_CENTER)

    # ── Floor line ──────────────────────────────────────────────────────
    msp.add_line(
        (view_x0, y_floor), (view_x0 + SX(view_w), y_floor),
        dxfattribs={"layer": "FRAMING", "lineweight": 30},
    )
    floor_lbl = msp.add_text(
        "FLOOR",
        dxfattribs={"layer": "ANNOTATIONS", "height": TEXT_SMALL, "style": "Standard"},
    )
    floor_lbl.set_placement(
        (view_x0 + 0.10, y_floor - 0.12),
        align=TextEntityAlignment.MIDDLE_LEFT,
    )

    # ── Door thickness (vertical rectangle at face position) ─────────────
    x_door_back = x_face - SX(door_thick)
    msp.add_lwpolyline(
        [(x_door_back, y_floor), (x_face, y_floor),
         (x_face, y_door_top), (x_door_back, y_door_top),
         (x_door_back, y_floor)],
        close=True,
        dxfattribs={"layer": "FRAMING", "lineweight": 40},
    )
    # "DOOR" label on the door
    door_lbl = msp.add_text(
        "DOOR",
        dxfattribs={
            "layer": "ANNOTATIONS", "height": TEXT_SMALL,
            "style": "Standard", "rotation": 90,
        },
    )
    door_lbl.set_placement(
        ((x_door_back + x_face) / 2, (y_floor + y_door_top) / 2),
        align=TextEntityAlignment.MIDDLE_CENTER,
    )

    # ── Track path ───────────────────────────────────────────────────────
    # Standard:    floor → [up door_h] → radius arc → horizontal to backroom
    # High-lift:   floor → [up door_h + extra vertical] → radius arc → horiz
    # Full-vert:   floor → [up door_h + headroom] (no arc, no horizontal)
    # Low-headrm:  floor → [up door_h] → small radius (6") → short horiz
    vert_ext_in = 0.0
    if lift == "high_lift" and ctx.high_lift_inches:
        vert_ext_in = ctx.high_lift_inches
    y_vert_top = y_door_top + SX(vert_ext_in)
    arc_cy = y_vert_top + SX(radius)

    # Vertical section (includes high-lift extension)
    msp.add_line(
        (x_face + 0.05, y_floor), (x_face + 0.05, y_vert_top),
        dxfattribs={"layer": "TRACKS"},
    )

    if lift == "full_vertical":
        # No arc — track keeps going up to ceiling
        # Already drawn via the vertical line above; extend up to y_track_horiz
        msp.add_line(
            (x_face + 0.05, y_vert_top), (x_face + 0.05, y_track_horiz),
            dxfattribs={"layer": "TRACKS"},
        )
    else:
        # Radius arc from vertical → horizontal
        msp.add_arc(
            center=(x_face - SX(radius), arc_cy),
            radius=SX(radius),
            start_angle=270,
            end_angle=0,
            dxfattribs={"layer": "TRACKS"},
        )
        # Horizontal section from arc end back to backroom
        msp.add_line(
            (x_face - SX(radius), arc_cy),
            (x_back, arc_cy),
            dxfattribs={"layer": "TRACKS"},
        )

    # ── High-lift extension dimension (between door top and radius start) ──
    if vert_ext_in > 0:
        _draw_linear_dim_vertical(
            msp, (x_face + 0.15, y_door_top), (x_face + 0.15, y_vert_top),
            dim_x=x_face + 0.35,
            label=f"HI-LIFT {fmt_length_imperial(vert_ext_in)}",
        )

    # Annotation: track radius
    rad_label = msp.add_text(
        f"R = {fmt_length_imperial(radius)}",
        dxfattribs={"layer": "ANNOTATIONS", "height": TEXT_SMALL, "style": "Standard"},
    )
    rad_label.set_placement(
        (x_face - SX(radius), arc_cy + 0.06),
        align=TextEntityAlignment.MIDDLE_LEFT,
    )

    # ── Headroom dimension (floor-to-track horizontal, at left) ─────────
    dim_x_left = x_back - 0.15
    _draw_linear_dim_vertical(
        msp, (dim_x_left + SX(1), y_door_top), (dim_x_left + SX(1), y_track_horiz),
        dim_x=dim_x_left,
        label=f"HDRM {fmt_length_imperial(headroom)}",
    )

    # ── Door height dimension ───────────────────────────────────────────
    _draw_linear_dim_vertical(
        msp, (dim_x_left + SX(1), y_floor), (dim_x_left + SX(1), y_door_top),
        dim_x=dim_x_left - 0.30,
        label=fmt_length_imperial(door_h),
    )

    # ── Backroom dimension (horizontal at top) ───────────────────────────
    dim_y_top = y_track_horiz + 0.18
    _draw_linear_dim(
        msp, (x_back, y_track_horiz), (x_face, y_track_horiz), dim_y_top,
        label=f"BACKROOM {fmt_length_imperial(backroom)}",
    )

    # ── Centerline of shaft (interior view only — when there's a shaft) ──
    if lift != "full_vertical":
        # Shaft sits at the radius arc center elevation
        msp.add_line(
            (x_face - SX(radius) - 0.20, arc_cy),
            (x_face + 0.20, arc_cy),
            dxfattribs={"layer": "CENTERLINE", "linetype": "CENTER"},
        )
        cl_lbl = msp.add_text(
            "CL SHAFT",
            dxfattribs={
                "layer": "ANNOTATIONS", "height": TEXT_SMALL * 0.85,
                "style": "Standard",
            },
        )
        cl_lbl.set_placement(
            (x_face + 0.22, arc_cy),
            align=TextEntityAlignment.MIDDLE_LEFT,
        )

    # ── Jamb stub at door face (visualises wood/steel jamb depth) ──────
    jamb_depth_in = 5.5  # 2x6 visual depth
    jamb_x0 = x_face
    jamb_x1 = x_face + SX(jamb_depth_in)
    msp.add_lwpolyline(
        [(jamb_x0, y_floor), (jamb_x1, y_floor),
         (jamb_x1, y_door_top + SX(2)), (jamb_x0, y_door_top + SX(2)),
         (jamb_x0, y_floor)],
        close=True,
        dxfattribs={"layer": "FRAMING", "lineweight": 18},
    )

    # ── Interior / exterior labels ──────────────────────────────────────
    int_label = msp.add_text(
        "INTERIOR",
        dxfattribs={"layer": "ANNOTATIONS", "height": TEXT_SMALL, "style": "Standard"},
    )
    int_label.set_placement(
        (x_back + 0.08, y_floor + 0.10),
        align=TextEntityAlignment.MIDDLE_LEFT,
    )
    ext_label = msp.add_text(
        "EXTERIOR",
        dxfattribs={"layer": "ANNOTATIONS", "height": TEXT_SMALL, "style": "Standard"},
    )
    ext_label.set_placement(
        (jamb_x1 + 0.05, y_floor + 0.10),
        align=TextEntityAlignment.MIDDLE_LEFT,
    )


# ─── Callout panel (construction, weather, hardware notes) ──────────────────

def _draw_callout_panel(msp: Modelspace, ctx: DrawingContext,
                        box: Tuple[float, float, float, float]) -> None:
    """Right-side panel listing construction stack-up, hardware, and notes.

    Line format:   "LABEL:  value"
    Sections are separated by a thin horizontal rule.
    """
    bx0, by0, bx1, by1 = box

    # Panel title
    t = msp.add_text(
        "CONSTRUCTION & HARDWARE",
        dxfattribs={"layer": "ANNOTATIONS", "height": TEXT_MED, "style": "Standard"},
    )
    t.set_placement(((bx0 + bx1) / 2, by1 - 0.12),
                    align=TextEntityAlignment.MIDDLE_CENTER)

    # Build the notes rows
    construction_lines = [
        "26GA STUCCO EMBOSSED",
        "FINISH: " + (ctx.panel_color or "WHITE"),
    ]
    if ctx.insulated:
        construction_lines.append("FOAMED-IN-PLACE")
        construction_lines.append("POLYURETHANE 2.5 PCF")
    construction_lines.append("P.V.C. RETAINER")
    construction_lines.append("STEEL END CAP W/ VINYL")
    construction_lines.append("WEATHER STRIP")

    weather_lines = [
        "TOP SEAL: LOW TEMP VINYL",
        "BOTTOM: LOW TEMP VINYL",
        "ASTRAGAL",
    ]

    hardware_lines = [
        "HINGE REINFORCING:",
        "2 STEEL STRIPS, 1-1/4\" W",
        "FULL HINGE APPLICATION",
    ]

    track_jamb_lines = [
        f"TRACK: {LIFT_TYPE_LABELS.get(ctx.lift_type, 'STANDARD LIFT')}",
        f"RADIUS: {fmt_length_imperial(ctx.track_radius_in)}",
        f"JAMB: {ctx.jamb_type.upper()} APPLICATION",
        "DOOR FACE: INSIDE LOOKING OUT",
    ]

    groups = [
        ("SECTION CONSTRUCTION",  construction_lines),
        ("WEATHER SEAL",          weather_lines),
        ("HARDWARE",              hardware_lines),
        ("TRACK / JAMB",          track_jamb_lines),
    ]

    # Vertical layout — compute total lines and line height
    total_lines = sum(1 + len(lines) for _, lines in groups) + len(groups)
    avail_h = (by1 - 0.25) - (by0 + 0.10)
    line_h = min(avail_h / max(total_lines, 1), 0.14)

    y = by1 - 0.35
    for group_title, lines in groups:
        # Group header
        gh = msp.add_text(
            group_title,
            dxfattribs={"layer": "ANNOTATIONS", "height": TEXT_SMALL, "style": "Standard"},
        )
        gh.set_placement((bx0 + 0.08, y),
                         align=TextEntityAlignment.MIDDLE_LEFT)
        # Underline for group header
        y_underline = y - line_h * 0.35
        msp.add_line(
            (bx0 + 0.08, y_underline), (bx1 - 0.08, y_underline),
            dxfattribs={"layer": "ANNOTATIONS", "lineweight": 13},
        )
        y -= line_h * 1.1
        for text_line in lines:
            txt = msp.add_text(
                text_line,
                dxfattribs={"layer": "ANNOTATIONS", "height": TEXT_SMALL * 0.85, "style": "Standard"},
            )
            txt.set_placement((bx0 + 0.15, y),
                              align=TextEntityAlignment.MIDDLE_LEFT)
            y -= line_h
        y -= line_h * 0.4  # gap between groups


# ─── Hinges ─────────────────────────────────────────────────────────────────

def _draw_hinges(msp: Modelspace, ctx: DrawingContext,
                 door_bbox: Tuple[float, float, float, float],
                 section_ys: list[float], scale: float) -> None:
    """Draw hinge symbols at each internal section joint.

    Hinge column rule (TX commercial + Kanata/Craft residential, validated
    against OPENDC reference catalog): max(3, ceil(W″/60) + 1) total
    columns spaced evenly across the door — end columns at each jamb
    plus intermediates spaced ≤ 60″ apart. Aluminum (AL976/SWD/PANORAMA)
    uses one hinge per stile column instead.

    Each hinge is a small filled square, ~2" wide per real-world.
    """
    d_x0, _, d_x1, _ = door_bbox
    HINGE_SIZE_IN = 2.0   # real-world size of each hinge symbol
    HINGE_OFFSET_IN = 3.5 # distance from door edge to end hinge column
    hinge_w = HINGE_SIZE_IN * scale
    end_offset = HINGE_OFFSET_IN * scale
    door_pw = d_x1 - d_x0

    if _is_aluminum_series(ctx.door_series):
        # One hinge per stile column. Stile count = pockets - 1 internal
        # + 2 at the jambs.
        n_pockets = _al_pocket_count(ctx.door_width_in)
        positions = [d_x0 + end_offset, d_x1 - end_offset]
        for k in range(1, n_pockets):
            positions.append(d_x0 + door_pw * (k / n_pockets))
    else:
        # TX commercial + Kanata/Craft residential: hinge columns from
        # the spacing rule.
        n_cols = _hinge_columns(ctx.door_width_in)
        positions = []
        for k in range(n_cols):
            t = k / (n_cols - 1) if n_cols > 1 else 0.5
            x = d_x0 + end_offset + (door_pw - 2 * end_offset) * t
            positions.append(x)

    # Draw at each internal section joint (skip top/bottom)
    for y in section_ys[1:-1]:
        for px in positions:
            msp.add_solid(
                [
                    (px - hinge_w / 2, y - hinge_w / 4),
                    (px + hinge_w / 2, y - hinge_w / 4),
                    (px - hinge_w / 2, y + hinge_w / 4),
                    (px + hinge_w / 2, y + hinge_w / 4),
                ],
                dxfattribs={"layer": "HARDWARE"},
            )


# ─── Shaft + springs (interior elevation overhead) ──────────────────────────

def _draw_shaft_and_springs(msp: Modelspace, ctx: DrawingContext,
                            left_x: float, right_x: float,
                            door_top_y: float, header_top_y: float,
                            track_top_y: float, scale: float) -> None:
    """Draw the torsion-spring shaft above the header with springs + bearings.

    Reference Panorama shop drawing layout:
      - Shaft centerline ~6" above header (distance varies by liftType)
      - Shaft is a horizontal line spanning just past the tracks
      - Springs are visible on the shaft (coiled cylinders)
      - Dimension "CENTERLINE OF SHAFT" shown with door-height callout
      - Shaft length ("9'-1\"" on reference) shown as horizontal dim
    """
    # Shaft centerline is roughly halfway between header and track top
    shaft_cy = (header_top_y + track_top_y) / 2
    shaft_diameter_in = 1.0   # 1" solid shaft typical
    # Exaggerate shaft thickness on paper so it's visible at small scales
    shaft_thick = max(scale * shaft_diameter_in, 0.06)
    shaft_top = shaft_cy + shaft_thick / 2
    shaft_bot = shaft_cy - shaft_thick / 2

    # Horizontal shaft bar
    msp.add_lwpolyline(
        [(left_x, shaft_bot), (right_x, shaft_bot),
         (right_x, shaft_top), (left_x, shaft_top),
         (left_x, shaft_bot)],
        close=True,
        dxfattribs={"layer": "HARDWARE", "lineweight": 25},
    )
    # Centerline
    msp.add_line(
        (left_x - scale * 2, shaft_cy),
        (right_x + scale * 2, shaft_cy),
        dxfattribs={"layer": "CENTERLINE", "linetype": "CENTER"},
    )

    # ── Springs ─────────────────────────────────────────────────────────
    # Residential/aluminum: 2 springs, one on each side of center.
    # Commercial > 18': often 4 springs.
    # Spring outer diameter typical 2-3", length varies with door weight.
    # Both are exaggerated on paper so they're legible at small scales.
    num_springs = 2  # sensible default; real quantity comes from part schedule
    spring_od_in = 3.5                          # visual OD (real ~2.0-2.75")
    spring_len_in = max(28.0, ctx.door_width_in * 0.15)  # scales with door width
    spring_od = max(scale * spring_od_in, 0.15)
    spring_len = scale * spring_len_in

    center_x = (left_x + right_x) / 2
    gap_between_springs = scale * 6.0  # center gap
    for i in range(num_springs):
        side = -1 if i == 0 else 1
        end_x = center_x + side * gap_between_springs / 2
        start_x = end_x + side * spring_len
        sx0, sx1 = sorted([start_x, end_x])
        _draw_coil_spring(msp, sx0, sx1, shaft_cy, spring_od,
                          coils=16, layer="HARDWARE")

    # Center coupler (small block between springs on the shaft)
    coupler_w = scale * 3.0
    coupler_h = shaft_thick * 2.2
    msp.add_lwpolyline(
        [(center_x - coupler_w / 2, shaft_cy - coupler_h / 2),
         (center_x + coupler_w / 2, shaft_cy - coupler_h / 2),
         (center_x + coupler_w / 2, shaft_cy + coupler_h / 2),
         (center_x - coupler_w / 2, shaft_cy + coupler_h / 2),
         (center_x - coupler_w / 2, shaft_cy - coupler_h / 2)],
        close=True,
        dxfattribs={"layer": "HARDWARE", "lineweight": 30},
    )

    # ── Shaft-length dimension above springs (matches reference "9'-1\"") ──
    dim_y = shaft_top + 0.25
    shaft_length_in = (right_x - left_x) / scale
    _draw_linear_dim(msp, (left_x, shaft_top), (right_x, shaft_top), dim_y,
                     label=fmt_length_imperial(shaft_length_in))

    # ── Centerline-of-shaft callout ─────────────────────────────────────
    cl_label = msp.add_text(
        "CENTERLINE OF SHAFT",
        dxfattribs={"layer": "ANNOTATIONS", "height": TEXT_SMALL, "style": "Standard"},
    )
    cl_label.set_placement(
        (center_x, shaft_cy - 0.15),
        align=TextEntityAlignment.MIDDLE_CENTER,
    )
    # Distance from floor (= door_h + centerline offset)
    cl_height_in = (shaft_cy - (door_top_y - scale * (ctx.door_height_in or 84))) / scale
    # simpler: cl_height_in = door_height + offset-from-door-top
    # The visual position encodes it; add a dim on the right
    cl_dim = msp.add_text(
        fmt_length_imperial(cl_height_in),
        dxfattribs={"layer": "DIMENSIONS", "height": TEXT_SMALL, "style": "Standard"},
    )
    cl_dim.set_placement(
        (center_x, shaft_cy - 0.30),
        align=TextEntityAlignment.MIDDLE_CENTER,
    )


def _draw_coil_spring(msp: Modelspace, x0: float, x1: float, cy: float,
                      od: float, coils: int = 14, layer: str = "HARDWARE") -> None:
    """Draw a helical torsion spring as a series of arcs (zig-zag silhouette)
    between x0 and x1 with given outer diameter and coil count.
    """
    if x1 <= x0:
        return
    length = x1 - x0
    step = length / coils
    # Upper and lower envelope lines of the spring cylinder
    msp.add_line((x0, cy + od / 2), (x1, cy + od / 2),
                 dxfattribs={"layer": layer})
    msp.add_line((x0, cy - od / 2), (x1, cy - od / 2),
                 dxfattribs={"layer": layer})
    # End caps
    msp.add_line((x0, cy + od / 2), (x0, cy - od / 2),
                 dxfattribs={"layer": layer, "lineweight": 40})
    msp.add_line((x1, cy + od / 2), (x1, cy - od / 2),
                 dxfattribs={"layer": layer, "lineweight": 40})
    # Diagonal lines simulating the coil spiral
    for i in range(coils):
        xa = x0 + i * step
        xb = xa + step
        msp.add_line((xa, cy - od / 2), (xb, cy + od / 2),
                     dxfattribs={"layer": layer})


# ─── View stubs — filled in by later tasks ──────────────────────────────────

def _draw_panel_profile(msp: Modelspace, ctx: DrawingContext,
                        box: Tuple[float, float, float, float]) -> None:
    """Side profile (cross-section) of ONE door section.

    Shows:
      - Door thickness (1-3/4" residential, 2" commercial) — vertical rect
      - Steel end cap with vinyl weather strip (top cap detail)
      - Glazing moulding (only on glass series — AL976/SWD/PANORAMA)
      - Bottom bracket (12GA galv steel) protruding from bottom
      - Low temp vinyl bottom astragal (seal under door)
      - Dimension callout: 1-3/4" thickness
    """
    bx0, by0, bx1, by1 = box
    box_w = bx1 - bx0
    box_h = by1 - by0

    # Title at top of box
    t = msp.add_text(
        f"{ctx.door_series} SIDE PROFILE",
        dxfattribs={"layer": "ANNOTATIONS", "height": TEXT_MED, "style": "Standard"},
    )
    t.set_placement(((bx0 + bx1) / 2, by1 - 0.12),
                    align=TextEntityAlignment.MIDDLE_CENTER)

    # Door section dimensions (real-world inches). TX panel thickness
    # depends on the subseries (TX380=38mm, TX450=45mm, TX500=50mm).
    thickness_in = _panel_thickness_in(ctx.door_series, ctx.door_type)
    section_h_in = ctx.section_height_in

    # Fit: the section is tall and skinny. Scale to fit available height.
    reserved_top = 0.45   # leave space for title + first leader label
    reserved_bot = 0.40   # leave space for thickness dim + astragal
    reserved_right_labels = box_w * 0.55  # right side holds labels/leaders
    avail_w = (box_w - reserved_right_labels) * 0.9
    avail_h = box_h - reserved_top - reserved_bot
    scale = min(avail_w / thickness_in, avail_h / section_h_in)

    # Place the profile on the LEFT side of the box
    prof_x0 = bx0 + 0.20
    prof_x1 = prof_x0 + thickness_in * scale
    prof_cy = by0 + reserved_bot + (avail_h / 2)
    prof_y0 = prof_cy - (section_h_in * scale) / 2
    prof_y1 = prof_cy + (section_h_in * scale) / 2

    def SX(inches: float) -> float:
        return inches * scale

    # ── Main section body (door thickness × section height) ──────────────
    msp.add_lwpolyline(
        [(prof_x0, prof_y0), (prof_x1, prof_y0),
         (prof_x1, prof_y1), (prof_x0, prof_y1),
         (prof_x0, prof_y0)],
        close=True,
        dxfattribs={"layer": "FRAMING", "lineweight": 35},
    )

    # ── Top end cap (steel with vinyl weather strip) ─────────────────────
    cap_h = SX(1.5)
    msp.add_lwpolyline(
        [(prof_x0 - SX(0.25), prof_y1),
         (prof_x1 + SX(0.25), prof_y1),
         (prof_x1 + SX(0.25), prof_y1 + cap_h),
         (prof_x0 - SX(0.25), prof_y1 + cap_h),
         (prof_x0 - SX(0.25), prof_y1)],
        close=True,
        dxfattribs={"layer": "HARDWARE"},
    )
    # Vinyl tab protrusion on exterior side (left)
    msp.add_lwpolyline(
        [(prof_x0 - SX(0.35), prof_y1 + cap_h * 0.2),
         (prof_x0 - SX(0.25), prof_y1 + cap_h * 0.2),
         (prof_x0 - SX(0.25), prof_y1 + cap_h * 0.8),
         (prof_x0 - SX(0.35), prof_y1 + cap_h * 0.8)],
        dxfattribs={"layer": "HARDWARE"},
    )

    # ── Glazing moulding (shown as dashed inner rectangle for glass series) ──
    is_glass_series = ctx.door_series in {"AL976", "SWD", "PANORAMA", "SOLALITE"}
    if is_glass_series:
        glaze_inset = SX(0.25)
        glaze_y0 = prof_y0 + SX(2.0)
        glaze_y1 = prof_y1 - SX(2.0)
        msp.add_lwpolyline(
            [(prof_x0 + glaze_inset, glaze_y0),
             (prof_x1 - glaze_inset, glaze_y0),
             (prof_x1 - glaze_inset, glaze_y1),
             (prof_x0 + glaze_inset, glaze_y1),
             (prof_x0 + glaze_inset, glaze_y0)],
            close=True,
            dxfattribs={"layer": "HIDDEN", "linetype": "HIDDEN"},
        )

    # ── Bottom astragal (vinyl weather seal, wider than section) ─────────
    astr_h = SX(1.0)
    msp.add_lwpolyline(
        [(prof_x0 - SX(0.15), prof_y0),
         (prof_x1 + SX(0.15), prof_y0),
         (prof_x1 + SX(0.05), prof_y0 - astr_h),
         (prof_x0 - SX(0.05), prof_y0 - astr_h),
         (prof_x0 - SX(0.15), prof_y0)],
        close=True,
        dxfattribs={"layer": "HARDWARE"},
    )

    # ── Bottom bracket (small rectangle protruding from bottom-right) ────
    brk_w = SX(2.5)
    brk_h = SX(2.0)
    msp.add_lwpolyline(
        [(prof_x1, prof_y0 + SX(0.5)),
         (prof_x1 + brk_w, prof_y0 + SX(0.5)),
         (prof_x1 + brk_w, prof_y0 + SX(0.5) + brk_h),
         (prof_x1, prof_y0 + SX(0.5) + brk_h),
         (prof_x1, prof_y0 + SX(0.5))],
        close=True,
        dxfattribs={"layer": "HARDWARE"},
    )

    # ── Leader lines + labels on the right side of the box ──────────────
    # Use MTEXT for multi-line labels (TEXT entity doesn't honor newlines).
    label_x = bx0 + box_w * 0.55
    labels = [
        (prof_y1 + cap_h * 0.5, "STEEL END CAP\\PC/W VINYL WEATHER STRIP"),
    ]
    if is_glass_series:
        labels.append(((prof_y0 + prof_y1) / 2, "GLAZING MOULDING"))
    labels.append((prof_y0 + SX(1.5), "BOTTOM BRACKET\\P12GA GAL STEEL"))
    labels.append((prof_y0 - astr_h / 2, "LOW TEMP VINYL\\PBOTTOM ASTRAGAL"))

    for y_pt, text_lines in labels:
        # Leader from label to the profile geometry
        leader_from_x = prof_x1 + brk_w + 0.05 if "BRACKET" in text_lines else prof_x1 + 0.02
        msp.add_line(
            (leader_from_x, y_pt),
            (label_x - 0.03, y_pt),
            dxfattribs={"layer": "ANNOTATIONS", "lineweight": 13},
        )
        # MTEXT supports the \P paragraph break
        mtext = msp.add_mtext(
            text_lines,
            dxfattribs={
                "layer": "ANNOTATIONS",
                "char_height": TEXT_SMALL * 0.75,
                "style": "Standard",
                "attachment_point": 4,  # middle-left
                "width": bx1 - label_x - 0.02,
            },
        )
        mtext.dxf.insert = (label_x, y_pt)

    # ── Thickness dimension at bottom ─────────────────────────────────────
    dim_y = prof_y0 - astr_h - 0.15
    _draw_linear_dim(msp, (prof_x0, prof_y0 - astr_h), (prof_x1, prof_y0 - astr_h),
                     dim_y, label=fmt_length_imperial(thickness_in))


def _draw_plan_view(msp: Modelspace, ctx: DrawingContext,
                    box: Tuple[float, float, float, float]) -> None:
    """Horizontal cross-section through the door opening.

    Shows (mirrors the reference Panorama PLAN VIEW):
      - Door opening width with clear-opening dimension
      - Min req. sideroom 3.5" on each side (jamb pocket)
      - Exterior/Interior labels
      - Weather strip ramset-fastened callout (outside of section)
      - Steel end cap w/ vinyl weather strip callout (inside)
      - Jamb application label below ("STEEL/WOOD JAMB WELD APPLICATION")
    """
    bx0, by0, bx1, by1 = box
    box_w = bx1 - bx0
    box_h = by1 - by0

    # Title at top
    t = msp.add_text(
        "PLAN VIEW",
        dxfattribs={"layer": "ANNOTATIONS", "height": TEXT_MED, "style": "Standard"},
    )
    t.set_placement(((bx0 + bx1) / 2, by1 - 0.12),
                    align=TextEntityAlignment.MIDDLE_CENTER)

    # Real-world dims (inches)
    door_w = ctx.door_width_in or 96.0
    ro_w = _ro_width(door_w)
    sideroom_in = 3.5  # minimum required sideroom each side
    door_thickness_in = _panel_thickness_in(ctx.door_series, ctx.door_type)
    # Plan-view geometry: jambs flank the rough opening, not the door slab.
    # Door slab (drawn as the section band between jambs) overlaps inward
    # for +2" variants, so the interior face line is the door slab width.
    total_w = ro_w + 2 * sideroom_in
    depth_in = door_thickness_in + 4.0  # section + exterior/interior buffer

    usable_w = box_w * 0.88
    usable_h = box_h * 0.65
    scale = min(usable_w / total_w, usable_h / depth_in)

    cx = (bx0 + bx1) / 2
    # Center the geometry in the upper portion of the box so top callouts
    # and title have room without empty white space below.
    cy = by0 + box_h * 0.65
    plan_x0 = cx - (total_w * scale) / 2
    plan_x1 = plan_x0 + total_w * scale
    sec_y_bot = cy - (depth_in * scale) / 2
    sec_y_top = sec_y_bot + door_thickness_in * scale

    def SX(inches: float) -> float:
        return inches * scale

    # ── Left jamb (sideroom pocket) ─────────────────────────────────────
    jl_x0 = plan_x0
    jl_x1 = plan_x0 + sideroom_in * scale
    msp.add_lwpolyline(
        [(jl_x0, sec_y_bot), (jl_x1, sec_y_bot),
         (jl_x1, sec_y_top + SX(1.5)),
         (jl_x0, sec_y_top + SX(1.5)),
         (jl_x0, sec_y_bot)],
        close=True,
        dxfattribs={"layer": "FRAMING"},
    )
    # ── Right jamb ──────────────────────────────────────────────────────
    jr_x0 = plan_x1 - sideroom_in * scale
    jr_x1 = plan_x1
    msp.add_lwpolyline(
        [(jr_x0, sec_y_bot), (jr_x1, sec_y_bot),
         (jr_x1, sec_y_top + SX(1.5)),
         (jr_x0, sec_y_top + SX(1.5)),
         (jr_x0, sec_y_bot)],
        close=True,
        dxfattribs={"layer": "FRAMING"},
    )

    # ── Door section (thin horizontal band between jambs) ───────────────
    d_x0 = jl_x1
    d_x1 = jr_x0
    msp.add_lwpolyline(
        [(d_x0, sec_y_bot), (d_x1, sec_y_bot),
         (d_x1, sec_y_top), (d_x0, sec_y_top),
         (d_x0, sec_y_bot)],
        close=True,
        dxfattribs={"layer": "FRAMING", "lineweight": 40},
    )

    # ── Sideroom dimensions (left + right) ──────────────────────────────
    dim_y = sec_y_bot - 0.25
    _draw_linear_dim(msp, (jl_x0, sec_y_bot), (jl_x1, sec_y_bot), dim_y,
                     label=f"SIDEROOM {fmt_length_imperial(sideroom_in)}")
    _draw_linear_dim(msp, (jr_x0, sec_y_bot), (jr_x1, sec_y_bot), dim_y,
                     label=f"SIDEROOM {fmt_length_imperial(sideroom_in)}")

    # ── Rough-opening dimension (between jamb inside faces) ────────────
    opening_dim_y = dim_y - 0.30
    _draw_linear_dim(msp, (d_x0, sec_y_bot), (d_x1, sec_y_bot), opening_dim_y,
                     label=f"R.O. {fmt_length_dual(ro_w)}")

    # ── Exterior / Interior labels (inside the view, close to geometry) ──
    ext_lbl = msp.add_text(
        "EXTERIOR",
        dxfattribs={"layer": "ANNOTATIONS", "height": TEXT_SMALL, "style": "Standard"},
    )
    ext_lbl.set_placement(
        (cx, sec_y_top + SX(1.5) + 0.10),
        align=TextEntityAlignment.MIDDLE_CENTER,
    )
    int_lbl = msp.add_text(
        "INTERIOR",
        dxfattribs={"layer": "ANNOTATIONS", "height": TEXT_SMALL, "style": "Standard"},
    )
    # Place INTERIOR just below the opening-dim line
    int_lbl.set_placement(
        (cx, opening_dim_y - 0.30),
        align=TextEntityAlignment.MIDDLE_CENTER,
    )

    # ── Callouts (MTEXT so newlines work) with short leaders ────────────
    # Weather strip (exterior face) — label above-left of section
    ws_leader_x = d_x0 + (d_x1 - d_x0) * 0.25
    ws_label_x = bx0 + 0.15
    ws_label_y = sec_y_top + SX(1.5) + 0.30
    msp.add_line((ws_leader_x, sec_y_top), (ws_label_x + 0.80, ws_label_y),
                 dxfattribs={"layer": "ANNOTATIONS"})
    mt = msp.add_mtext(
        "WEATHER STRIPPING\\PRAMSET FASTENED",
        dxfattribs={
            "layer": "ANNOTATIONS", "char_height": TEXT_SMALL * 0.75,
            "style": "Standard", "attachment_point": 7,  # bottom-left
            "width": 1.1,
        },
    )
    mt.dxf.insert = (ws_label_x, ws_label_y)

    # Steel end cap (interior face) — label below-right of section
    ec_leader_x = d_x0 + (d_x1 - d_x0) * 0.75
    ec_label_x = bx1 - 1.3
    ec_label_y = sec_y_bot - 0.10
    # Push label below INTERIOR label if needed
    if ec_label_y > opening_dim_y - 0.60:
        ec_label_y = opening_dim_y - 0.60
    msp.add_line((ec_leader_x, sec_y_bot), (ec_label_x + 0.05, ec_label_y + 0.08),
                 dxfattribs={"layer": "ANNOTATIONS"})
    mt2 = msp.add_mtext(
        "STEEL END CAP\\PC/W VINYL WEATHER STRIP",
        dxfattribs={
            "layer": "ANNOTATIONS", "char_height": TEXT_SMALL * 0.75,
            "style": "Standard", "attachment_point": 4,  # middle-left
            "width": 1.25,
        },
    )
    mt2.dxf.insert = (ec_label_x, ec_label_y)

    # ── Jamb application label at the bottom ─────────────────────────────
    jamb_label = msp.add_text(
        f"{ctx.jamb_type.upper()} JAMB "
        f"{'WELD ' if ctx.jamb_type == 'steel' else ''}APPLICATION",
        dxfattribs={"layer": "ANNOTATIONS", "height": TEXT_SMALL, "style": "Standard"},
    )
    jamb_label.set_placement(
        (cx, by0 + 0.18),
        align=TextEntityAlignment.MIDDLE_CENTER,
    )


def _draw_optional_extras(msp: Modelspace, ctx: DrawingContext,
                          box: Tuple[float, float, float, float]) -> None:
    """Checklist of optional extras on the right side of the sheet.

    Items mirror the reference list. Each item renders with a small check
    box; the box is filled if the config specifies the option.
    """
    bx0, by0, bx1, by1 = box
    # Panel title
    t = msp.add_text(
        "OPTIONAL EXTRAS",
        dxfattribs={"layer": "ANNOTATIONS", "height": TEXT_MED, "style": "Standard"},
    )
    t.set_placement(((bx0 + bx1) / 2, by1 - 0.15),
                    align=TextEntityAlignment.MIDDLE_CENTER)

    # Bind every checkbox to a field on DrawingContext. Items that don't
    # have a corresponding configurator field today render unchecked —
    # add the field upstream (configurator → SavedQuoteConfig →
    # build_context_from_config) before changing them here.
    track_size = (ctx.track_thickness_ga or "").strip()
    operator = (ctx.operator or "NONE").upper()
    shaft = (ctx.shaft_type or "auto").lower()
    cycles = ctx.target_cycles or 10000
    is_aluminum = _is_aluminum_series(ctx.door_series)
    is_commercial = _is_commercial_series(ctx.door_series)

    selected = {
        # Track size: 2" for residential standard, 3" for commercial
        "2\" TRACK APPLICATION":       track_size in ("2", "2_in", ""),
        "3\" TRACK APPLICATION":       track_size in ("3", "3_in"),
        # Frame / jamb material
        "STEEL FRAME":                 ctx.jamb_type == "steel",
        "WOOD FRAME":                  ctx.jamb_type == "wood",
        # Track mount style
        "BRACKET MOUNT":               ctx.track_mount == "bracket",
        "CONTINUOUS ANGLE MOUNT":      ctx.track_mount == "angle",
        # End stile / hinge style — aluminum + wide commercial use double
        "SINGLE END STILES/HINGES":    not (is_aluminum or
                                            (is_commercial and ctx.door_width_in >= 192)),
        "DOUBLE END STILES/HINGES":    is_aluminum or
                                        (is_commercial and ctx.door_width_in >= 192),
        # Strut gauge — commercial defaults to 16GA, residential to 20GA
        "16GA STRUTS":                 ctx.has_struts and is_commercial,
        "20GA STRUTS":                 ctx.has_struts and not is_commercial,
        "MAN DOOR (see man door spec)": ctx.man_door,
        "INTERIOR SIDE LOCK":          ctx.interior_lock,
        # Operator
        "MANUAL OPERATION":            operator in ("NONE", "MANUAL"),
        "GEARED CHAIN HOIST":          operator in ("CHAIN_HOIST", "CHAIN", "HOIST"),
        "ELECTRIC OPERATOR (BY OTHERS)": (operator not in
                                          ("NONE", "MANUAL", "CHAIN_HOIST",
                                           "CHAIN", "HOIST")),
        # Shaft type — "auto" defaults to 1" solid for residential, 1-1/4"
        # for wide/commercial. Explicit shaft_type values override.
        "1\" SOLID SHAFT":             (shaft in ("1_solid", "single") or
                                        (shaft == "auto" and not (is_commercial
                                            or ctx.door_width_in >= 192))),
        "1-1/4\" SOLID SHAFT":         (shaft == "1_25_solid" or
                                        (shaft == "auto" and (is_commercial
                                            or ctx.door_width_in >= 192))),
        "1\" TUBULAR SHAFT":           shaft == "1_tubular",
        "COUPLER":                     shaft == "split",
        # Spring cycle rating
        "STANDARD CYCLE SPRING":       cycles <= 10000,
        "25,000 CYCLE SPRINGS":        cycles == 25000,
        "50,000 CYCLE SPRINGS":        cycles == 50000,
        "100,000 CYCLE SPRINGS":       cycles >= 100000,
        "PUSHER SPRING":               ctx.pusher_spring,
        "BUMPER SPRING":               ctx.bumper_spring,
        "TRACK GUARDS":                ctx.track_guards,
        # Weather seals — driven by hardware bundle flag
        "TOP SEAL VINYL":              ctx.has_weather_stripping,
        "STEEL VINYL WEATHER STRIP":   ctx.has_weather_stripping,
        "EXHAUST PORT":                ctx.exhaust_port,
    }

    # Layout: single column of check-items. Line height calculated from list.
    avail_h = (by1 - 0.35) - (by0 + 0.05)
    n = len(selected)
    line_h = min(avail_h / max(n, 1), 0.18)
    y = by1 - 0.35
    for label, is_on in selected.items():
        # Check-box square (sheet coords)
        box_size = line_h * 0.55
        bx = bx0 + 0.08
        by = y - box_size / 2
        msp.add_lwpolyline(
            [(bx, by), (bx + box_size, by), (bx + box_size, by + box_size),
             (bx, by + box_size), (bx, by)],
            close=True,
            dxfattribs={"layer": "ANNOTATIONS", "lineweight": 13},
        )
        if is_on:
            # check mark (two diagonal lines forming ✔)
            msp.add_line((bx + 0.015, by + box_size * 0.5),
                         (bx + box_size * 0.4, by + 0.02),
                         dxfattribs={"layer": "ANNOTATIONS", "lineweight": 25})
            msp.add_line((bx + box_size * 0.4, by + 0.02),
                         (bx + box_size - 0.01, by + box_size - 0.01),
                         dxfattribs={"layer": "ANNOTATIONS", "lineweight": 25})
        # Label
        lbl = msp.add_text(
            label,
            dxfattribs={"layer": "ANNOTATIONS", "height": TEXT_SMALL * 0.85,
                        "style": "Standard"},
        )
        lbl.set_placement((bx + box_size + 0.05, y),
                          align=TextEntityAlignment.MIDDLE_LEFT)
        y -= line_h


def _draw_box_with_title(msp: Modelspace, box: Tuple[float, float, float, float],
                         title: str) -> None:
    """Dashed outline + centered title — placeholder for not-yet-implemented views."""
    bx0, by0, bx1, by1 = box
    msp.add_lwpolyline(
        [(bx0, by0), (bx1, by0), (bx1, by1), (bx0, by1), (bx0, by0)],
        close=True,
        dxfattribs={"layer": "HIDDEN", "linetype": "HIDDEN"},
    )
    t = msp.add_text(
        title,
        dxfattribs={"layer": "ANNOTATIONS", "height": TEXT_SMALL, "style": "Standard"},
    )
    t.set_placement(((bx0 + bx1) / 2, by1 - 0.15),
                    align=TextEntityAlignment.MIDDLE_CENTER)
    todo = msp.add_text(
        "(rendered in next iteration)",
        dxfattribs={"layer": "ANNOTATIONS", "height": TEXT_SMALL * 0.8,
                    "style": "Standard"},
    )
    todo.set_placement(((bx0 + bx1) / 2, (by0 + by1) / 2),
                       align=TextEntityAlignment.MIDDLE_CENTER)


def _infer_section_count(door_height_in: float, door_series: str) -> int:
    """Heuristic for number of door sections based on height and series.

    Stage 2 will pull this from the actual panel schedule. For now:
      - Commercial series use 24" sections
      - Aluminum AL976/SWD use 21" sections
      - Residential default 21" sections
    """
    commercial_series = {"TX380", "TX450", "TX500", "TX450-20", "TX500-20"}
    section_h = 24.0 if door_series in commercial_series else 21.0
    return max(2, round(door_height_in / section_h))


def _draw_linear_dim(msp: Modelspace, start: Tuple[float, float],
                     end: Tuple[float, float], dim_y: float,
                     label: str) -> None:
    """Simple linear dimension with extension + dimension lines and centered
    text. Not a full AutoCAD DIMENSION entity (those need dimstyle setup);
    this is a lightweight equivalent that renders reliably in matplotlib."""
    sx, sy = start
    ex, _ = end
    # Extension lines
    msp.add_line((sx, sy), (sx, dim_y - 0.05),
                 dxfattribs={"layer": "DIMENSIONS"})
    msp.add_line((ex, sy), (ex, dim_y - 0.05),
                 dxfattribs={"layer": "DIMENSIONS"})
    # Dimension line
    msp.add_line((sx, dim_y), (ex, dim_y),
                 dxfattribs={"layer": "DIMENSIONS"})
    # Tick marks at each end (45° slashes, 0.08" long)
    for x in (sx, ex):
        msp.add_line((x - 0.04, dim_y - 0.04), (x + 0.04, dim_y + 0.04),
                     dxfattribs={"layer": "DIMENSIONS"})
    # Text above the line
    t = msp.add_text(
        label,
        dxfattribs={"layer": "DIMENSIONS", "height": TEXT_SMALL, "style": "Standard"},
    )
    t.set_placement(((sx + ex) / 2, dim_y + 0.08),
                    align=TextEntityAlignment.MIDDLE_CENTER)


def _draw_linear_dim_vertical(msp: Modelspace, start: Tuple[float, float],
                              end: Tuple[float, float], dim_x: float,
                              label: str, extra_offset: float = 0.0) -> None:
    """Vertical dimension (extension lines to the right of the geometry)."""
    sx, sy = start
    _, ey = end
    x_offset = dim_x + extra_offset
    msp.add_line((sx, sy), (x_offset + 0.05, sy),
                 dxfattribs={"layer": "DIMENSIONS"})
    msp.add_line((sx, ey), (x_offset + 0.05, ey),
                 dxfattribs={"layer": "DIMENSIONS"})
    msp.add_line((x_offset, sy), (x_offset, ey),
                 dxfattribs={"layer": "DIMENSIONS"})
    for y in (sy, ey):
        msp.add_line((x_offset - 0.04, y - 0.04), (x_offset + 0.04, y + 0.04),
                     dxfattribs={"layer": "DIMENSIONS"})
    t = msp.add_text(
        label,
        dxfattribs={
            "layer": "DIMENSIONS", "height": TEXT_SMALL,
            "style": "Standard", "rotation": 90,
        },
    )
    t.set_placement((x_offset + 0.08, (sy + ey) / 2),
                    align=TextEntityAlignment.MIDDLE_CENTER)


# ─── Public entry point ────────────────────────────────────────────────────

def build_dxf(ctx: DrawingContext) -> ezdxf.document.Drawing:
    """Build and return the DXF document.

    Sheet layout (ANSI B landscape 17×11, modeled on the reference
    Panorama shop drawing):

      +--------------------+---------------------+------+---------+
      |  FRONT ELEVATION   |  FRONT ELEVATION    | SIDE | OPTIONAL|
      |  EXTERIOR VIEW     |  INTERIOR VIEW      | PANEL| EXTRAS  |
      |  (wall context)    |  (shaft + springs)  | PROF |CHECKLIST|
      |                    |                     |      |         |
      +---------+----------+----------+----------+------+         |
      |  PLAN   | (jamb    |   SIDE   | WINDOW   |      |         |
      |  VIEW   |  detail) | ELEVATION|  SPEC    |      |         |
      |                    |          +----------+------+---------+
      |                    |          |       TITLE BLOCK         |
      |                    |          |                           |
      +--------------------+----------+---------------------------+
    """
    doc = _new_drawing()
    msp = doc.modelspace()
    _draw_sheet_border(msp)
    _draw_title_block(msp, ctx)

    # Overall drawing area (inside sheet margins)
    DRAW_X0 = MARGIN_L + 0.10
    DRAW_X1 = SHEET_W - MARGIN_R - 0.10
    DRAW_Y_BOT = MARGIN_B + 0.10
    DRAW_Y_TOP = SHEET_H - MARGIN_T - 0.10

    # Title block is in lower-right; compute its footprint
    tb_x0 = SHEET_W - MARGIN_R - TITLE_BLOCK_W
    tb_y1 = MARGIN_B + TITLE_BLOCK_H

    # Vertical split between top and bottom halves
    DIVIDE_Y = DRAW_Y_BOT + (DRAW_Y_TOP - DRAW_Y_BOT) * 0.55  # top half a bit taller

    # Top row columns: exterior (18%) | interior (40%) | panel profile (10%) | extras (22%)
    TOP_W = DRAW_X1 - DRAW_X0
    ext_x1 = DRAW_X0 + TOP_W * 0.20
    int_x1 = DRAW_X0 + TOP_W * 0.58
    prof_x1 = DRAW_X0 + TOP_W * 0.72
    extras_x1 = DRAW_X1

    exterior_box = (DRAW_X0, DIVIDE_Y, ext_x1 - 0.10, DRAW_Y_TOP)
    interior_box = (ext_x1 + 0.05, DIVIDE_Y, int_x1 - 0.10, DRAW_Y_TOP)
    profile_box = (int_x1 + 0.05, DIVIDE_Y, prof_x1 - 0.10, DRAW_Y_TOP)
    extras_box = (prof_x1 + 0.05, tb_y1 + 0.10, extras_x1, DRAW_Y_TOP)

    # Bottom row: plan view (left) + side elevation (center). Window/
    # callout area sits above the title block which starts at tb_x0.
    plan_x1 = DRAW_X0 + TOP_W * 0.38
    plan_box = (DRAW_X0, DRAW_Y_BOT, plan_x1 - 0.10, DIVIDE_Y - 0.10)

    side_x0 = plan_x1 + 0.05
    side_x1 = tb_x0 - 0.15   # side view runs up to title block
    side_box = (side_x0, tb_y1 + 0.10, side_x1, DIVIDE_Y - 0.10)

    # ── Draw views ───────────────────────────────────────────────────────
    _draw_front_elevation(msp, ctx, interior_box, view="interior")
    _draw_front_elevation(msp, ctx, exterior_box, view="exterior")
    _draw_panel_profile(msp, ctx, profile_box)
    _draw_optional_extras(msp, ctx, extras_box)
    _draw_plan_view(msp, ctx, plan_box)
    _draw_side_elevation(msp, ctx, side_box)

    return doc


def dxf_to_pdf_bytes(doc: ezdxf.document.Drawing) -> bytes:
    """Render the DXF to a PDF using ezdxf's matplotlib backend.

    We set `finalize=False` because the backend's default finalize step
    re-fits the axes to the entity extents — which would crop our sheet
    to the drawn content and lose the full-page margin. Instead we pin
    the axes to the full sheet bounds ourselves.
    """
    # Lazy import to keep module load cheap if only DXF is requested
    import matplotlib
    matplotlib.use("Agg")  # headless — no Tk/GTK required
    from matplotlib import pyplot as plt
    from matplotlib.backends.backend_pdf import PdfPages
    from ezdxf.addons.drawing import RenderContext, Frontend
    from ezdxf.addons.drawing.matplotlib import MatplotlibBackend

    fig = plt.figure(figsize=(SHEET_W, SHEET_H), dpi=300)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_aspect("equal")
    ax.axis("off")

    ctx_render = RenderContext(doc)
    backend = MatplotlibBackend(ax)
    # finalize=False so the backend doesn't auto-fit the axes to entity
    # extents (which would crop out the paper margin).
    Frontend(ctx_render, backend).draw_layout(doc.modelspace(), finalize=False)

    # Pin axes to full sheet so the paper bounds are honored.
    ax.set_xlim(0, SHEET_W)
    ax.set_ylim(0, SHEET_H)

    buf = io.BytesIO()
    with PdfPages(buf) as pdf:
        pdf.savefig(fig, bbox_inches=None, pad_inches=0)
    plt.close(fig)
    return buf.getvalue()


def dxf_to_string(doc: ezdxf.document.Drawing) -> bytes:
    """Serialize the DXF to bytes for download."""
    buf = io.StringIO()
    doc.write(buf)
    return buf.getvalue().encode("utf-8")


# ─── Context builder from SavedQuoteConfig ─────────────────────────────────

def build_context_from_config(
    config_data: dict,
    customer_name: str,
    job_number: str,
    drawing_date: Optional[datetime] = None,
    config_id: Optional[int] = None,
    door_index: int = 0,
) -> DrawingContext:
    """Extract drawing inputs from a SavedQuoteConfig row.

    For multi-door configs, pick which door to draw via `door_index` (0-based).
    Stage 2 will support multi-door layouts or multi-sheet sets.
    """
    doors = (config_data or {}).get("doors", [])
    if not doors:
        raise ValueError("Config has no doors to draw")
    if door_index >= len(doors):
        raise ValueError(f"door_index {door_index} out of range (have {len(doors)})")
    door = doors[door_index]

    date_str = (drawing_date or datetime.utcnow()).strftime("%Y-%m-%d")

    door_type = door.get("doorType", "residential")
    series = door.get("doorSeries", "—")
    # Section height: aluminum and residential use 21", commercial uses 24"
    commercial_series = {"TX380", "TX450", "TX500", "TX450-20", "TX500-20"}
    section_h = 24.0 if series in commercial_series else 21.0

    hardware = door.get("hardware") or {}
    return DrawingContext(
        job_number=job_number or (f"Q-{config_id}" if config_id else "UNASSIGNED"),
        customer_name=customer_name or "—",
        door_series=series,
        door_type=door_type,
        door_width_in=float(door.get("doorWidth") or 0),
        door_height_in=float(door.get("doorHeight") or 0),
        door_count=int(door.get("doorCount") or 1),
        drawing_date=date_str,
        config_id=config_id,
        panel_design=door.get("panelDesign") or "SHXL",
        panel_color=door.get("panelColor") or "WHITE",
        lift_type=door.get("liftType") or "standard",
        high_lift_inches=(float(door["highLiftInches"]) if door.get("highLiftInches") else None),
        track_radius_in=float(door.get("trackRadius") or 15),
        track_thickness_ga=str(door.get("trackThickness") or "2"),
        track_mount=str(door.get("trackMount") or "bracket"),
        jamb_type="steel" if door_type == "commercial" else "wood",
        insulated=True,
        section_height_in=section_h,
        target_cycles=int(door.get("targetCycles") or 10000),
        shaft_type=str(door.get("shaftType") or "auto"),
        operator=str(door.get("operator") or "NONE"),
        has_struts=bool(hardware.get("struts", True)),
        has_weather_stripping=bool(hardware.get("weatherStripping", True)),
        has_bottom_retainer=bool(hardware.get("bottomRetainer", True)),
        has_windows=bool(door.get("hasWindows", False)),
        glass_pockets_per_section=door.get("glassPocketsPerSection"),
        man_door=bool(door.get("manDoor", False)),
        man_door_spec=str(door.get("manDoorSpec") or ""),
        interior_lock=bool(door.get("interiorLock", False)),
        pusher_spring=bool(door.get("pusherSpring", False)),
        bumper_spring=bool(door.get("bumperSpring", False)),
        track_guards=bool(door.get("trackGuards", False)),
        exhaust_port=bool(door.get("exhaustPort", False)),
    )


def generate_framing_drawing(
    config_data: dict,
    customer_name: str,
    job_number: str,
    fmt: str = "pdf",
    drawing_date: Optional[datetime] = None,
    config_id: Optional[int] = None,
    door_index: int = 0,
) -> bytes:
    """Top-level helper: config → bytes.

    fmt: "pdf" (default) or "dxf".
    """
    ctx = build_context_from_config(
        config_data=config_data,
        customer_name=customer_name,
        job_number=job_number,
        drawing_date=drawing_date,
        config_id=config_id,
        door_index=door_index,
    )
    doc = build_dxf(ctx)
    if fmt == "dxf":
        return dxf_to_string(doc)
    if fmt == "pdf":
        return dxf_to_pdf_bytes(doc)
    raise ValueError(f"Unsupported format: {fmt}")
