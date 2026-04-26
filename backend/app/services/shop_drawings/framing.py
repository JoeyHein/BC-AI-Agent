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
    spring_count: int = 2         # 2 for residential, 4 for wide commercial; renders N coils
    # Operator
    operator: str = "NONE"        # NONE, CHAIN_HOIST, electric models, ...
    operator_side: str = "right"  # "left" or "right" — which jamb the operator mounts on
                                   # (looking at the door from inside)
    # Hardware bundle (mirrors frontend door.hardware)
    has_struts: bool = True
    has_weather_stripping: bool = True
    has_bottom_retainer: bool = True
    # Glass / window selections
    has_windows: bool = False
    window_positions: Optional[list] = None  # [{"section": int, "col": int}, ...]
    window_insert: str = ""              # "12X24_THERMOPANE" / "34X16_THERMOPANE" / "NONE"
    window_size: str = "long"            # "short" (12x24) or "long" (34x16)
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

    # ── Row 7: OPENDC branding + series banner ────────────────────────
    # Left third: OPENDC logo + warranty line. Right two-thirds: big
    # series name banner. Mirrors the reference Craft drawing's
    # "upwardOR / CRAFT" layout.
    brand_w = 1.6
    brand_x1 = x0 + brand_w
    msp.add_line((brand_x1, row_ys[6]), (brand_x1, row_ys[7]),
                 dxfattribs={"layer": "TITLE_BLOCK"})
    # OPENDC mark
    brand_lbl = msp.add_text(
        "OPENDC",
        dxfattribs={"layer": "TITLE_BLOCK", "height": 0.20, "style": "Standard"},
    )
    brand_lbl.set_placement(
        ((x0 + brand_x1) / 2, row_ys[6] - 0.15),
        align=TextEntityAlignment.MIDDLE_CENTER,
    )
    brand_sub = msp.add_text(
        "Garage Doors Designed for Life",
        dxfattribs={"layer": "TITLE_BLOCK", "height": 0.07, "style": "Standard"},
    )
    brand_sub.set_placement(
        ((x0 + brand_x1) / 2, row_ys[6] - 0.32),
        align=TextEntityAlignment.MIDDLE_CENTER,
    )
    # Warranty line at the bottom of the brand cell
    warranty_text = ("WARRANTED FOR COMMERCIAL USE"
                     if ctx.door_type == "commercial"
                     else "WARRANTED FOR RESIDENTIAL USE")
    warranty = msp.add_text(
        warranty_text,
        dxfattribs={"layer": "TITLE_BLOCK", "height": 0.06, "style": "Standard"},
    )
    warranty.set_placement(
        ((x0 + brand_x1) / 2, row_ys[7] + 0.08),
        align=TextEntityAlignment.MIDDLE_CENTER,
    )

    # Series banner (right cell)
    banner = msp.add_text(
        ctx.door_series.upper() if ctx.door_series else "FRAMING DRAWING",
        dxfattribs={"layer": "TITLE_BLOCK", "height": 0.32, "style": "Standard"},
    )
    banner.set_placement(
        ((brand_x1 + x1) / 2, (row_ys[6] + row_ys[7]) / 2),
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

    # ── Header (no labeled box — reference shop drawings just use the
    # space above the door for shaft + tracks geometry, the framing wall
    # itself isn't called out as "HEADER"). The hdr_y0/hdr_y1 anchors
    # below are still used to position the shaft and track extension. ──

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
    # Track structure detail per the reference Craft drawing:
    #   - Vertical track from floor up past the header
    #   - At header height, the track curves on its radius and runs
    #     horizontally back into the building (shown as a small arc on
    #     the elevation; the full horizontal run lives in the side view)
    #   - Mounting attachment along the side: either discrete bracket
    #     rectangles at regular intervals (track_mount=bracket) or a
    #     continuous angle-iron strip (track_mount=angle).
    radius_in = ctx.track_radius_in or 15.0
    angle_mount = (ctx.track_mount or "bracket").lower() == "angle"

    for tx in (left_track_x, right_track_x):
        is_left_side = (tx == left_track_x)
        side = -1 if is_left_side else 1
        # Vertical track running floor → past the door top. The radius
        # curve / horizontal run is shown on the SIDE VIEW; on the front
        # elevation we just show the vertical track itself, no arcs.
        arc_start_y = track_top_y
        msp.add_line((tx, d_y0), (tx, arc_start_y),
                     dxfattribs={"layer": "TRACKS"})

        # ── Mounting hardware ──
        if angle_mount:
            # Continuous angle iron — drawn as a parallel strip between
            # the jamb and the track. The angle attaches the track to
            # the jamb along its full length.
            angle_x_inner = tx - side * DX(0.6)  # slightly inside the track
            msp.add_line((angle_x_inner, d_y0), (angle_x_inner, arc_start_y),
                         dxfattribs={"layer": "TRACKS", "lineweight": 18})
            # Connector dashes between angle and track every 12"
            conn_spacing = 12.0
            n_conn = int(door_h / conn_spacing)
            for k in range(n_conn + 1):
                cy = d_y0 + DX(conn_spacing * k)
                if cy < arc_start_y - DX(2):
                    msp.add_line((angle_x_inner, cy), (tx, cy),
                                 dxfattribs={"layer": "HIDDEN", "lineweight": 5})
        else:
            # Discrete mounting brackets — small rectangles along the
            # track at standard intervals. Real-world spacing is one
            # bracket per panel section, plus one near the floor.
            brk_w_in = 4.0   # bracket horizontal width (real-world)
            brk_h_in = 3.0   # bracket vertical height (real-world)
            section_h_in = ctx.section_height_in
            n_brackets = max(2, int(door_h / section_h_in) + 1)
            for k in range(n_brackets):
                # Position brackets near each section joint, with one
                # near the floor and one near the top
                t_pos = k / max(n_brackets - 1, 1)
                by_center = d_y0 + DX(door_h * 0.05) + (DX(door_h * 0.90)) * t_pos
                if by_center > arc_start_y - DX(brk_h_in):
                    continue
                # Bracket rectangle, anchored to the inside face of the
                # track and protruding inward toward the jamb.
                bx_outer = tx
                bx_inner = tx - side * DX(brk_w_in)
                bxs = sorted([bx_outer, bx_inner])
                msp.add_lwpolyline(
                    [(bxs[0], by_center - DX(brk_h_in / 2)),
                     (bxs[1], by_center - DX(brk_h_in / 2)),
                     (bxs[1], by_center + DX(brk_h_in / 2)),
                     (bxs[0], by_center + DX(brk_h_in / 2)),
                     (bxs[0], by_center - DX(brk_h_in / 2))],
                    close=True,
                    dxfattribs={"layer": "HARDWARE", "lineweight": 25},
                )

        # Rail marker ticks along the vertical track (above brackets) —
        # gives a sense of the track's slotted profile
        rail_spacing = 24.0
        rail_marks = int((door_h + HEADER_VIS_H + TRACK_EXTENSION) / rail_spacing)
        for m in range(1, rail_marks + 1):
            y = fy0 + DX(rail_spacing * m)
            if y < arc_start_y - DX(1):
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

    # ── View title — "{SERIES} VIEW INSIDE LOOKING OUT" matches the
    # reference TX-450 / Craft drawings' title convention. ────────────
    series_for_title = (ctx.door_series or "DOOR").upper()
    view_title_main = msp.add_text(
        f"{series_for_title} VIEW INSIDE LOOKING OUT" if is_interior
        else f"{series_for_title} VIEW OUTSIDE LOOKING IN",
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
    """Render the residential door face on the shop drawing.

    All Kanata and Craft variants render as a FLUSH panel — section
    joints only, no surface-stamp rectangles. The panel design (SHXL /
    BCXL / BC / SH / Trafalgar / Sheridan / Carriage) is recorded in
    the view title and the BC parts list, but the shop drawing doesn't
    try to depict the exterior stamp pattern. This keeps residential
    panels visually distinct from aluminum (which has a real glass-
    pocket grid) — previous behaviour of drawing a stamp-cell grid was
    making Trafalgar (multi-col, multi-row stamps) look identical to an
    AL976 glass-pocket grid.

    Windows ARE still rendered when positioned — they're real cutouts
    in the panel face, not a stamp pattern. We use the column grid
    only as a positioning reference for windowPositions.
    """
    if not (ctx.has_windows and ctx.window_positions):
        return

    d_x0, d_y0, d_x1, d_y1 = door_bbox
    design = ctx.panel_design or "SHXL"
    is_craft = ctx.door_series == "CRAFT"
    # Use the same column count we'd use for stamp positioning, so
    # window x-coordinates match the configurator's windowPositions
    # (which are stored as {section, col} where col is into the same
    # column grid). FLUSH design defaults to 2 columns (matches the
    # configurator's default windowPositions layout).
    if design in {"FLUSH", "SMOOTH"}:
        cols = 2
    else:
        stamp_type = "long" if design in {"SHXL", "BCXL"} else "short"
        cols = _stamp_columns(ctx.door_width_in, stamp_type, is_craft, design)

    section_inset_x = (d_x1 - d_x0) * 0.015
    section_inset_y = 0.04
    col_w = (d_x1 - d_x0 - 2 * section_inset_x) / cols
    col_gap = min(col_w * 0.08, 0.04)

    window_cells: set[tuple[int, int]] = set()
    for w in ctx.window_positions:
        try:
            window_cells.add((int(w.get("section", 0)), int(w.get("col", 0))))
        except (TypeError, ValueError):
            continue

    for i in range(len(section_ys) - 1):
        sec_y0 = section_ys[i] + section_inset_y
        sec_y1 = section_ys[i + 1] - section_inset_y
        if sec_y1 - sec_y0 < 0.05:
            continue
        for c in range(cols):
            if (i, c) not in window_cells:
                continue
            sx0 = d_x0 + section_inset_x + c * col_w + col_gap / 2
            sx1 = sx0 + col_w - col_gap
            _draw_window_pane(msp, sx0, sec_y0, sx1, sec_y1,
                              size=ctx.window_size or "long")


def _draw_window_pane(msp: Modelspace, x0: float, y0: float,
                      x1: float, y1: float, size: str = "long") -> None:
    """Draw a window pane inside a stamp cell. Frame is a thicker outline
    plus an inner pane outline. For "long" windows (Kanata Long, 34x16)
    we add a single horizontal mullion across the middle; "short" windows
    (Kanata Short, 12x24) get a vertical mullion in the middle. Matches
    the visual idiom used in the reference Craft drawing's top-section
    window cutouts.
    """
    # Outer frame (heavier weight than stamp lines so it reads as a window)
    msp.add_lwpolyline(
        [(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)],
        close=True,
        dxfattribs={"layer": "FRAMING", "lineweight": 30},
    )
    # Inner pane (slight inset) — represents the glass within the frame
    inset = max(min(x1 - x0, y1 - y0) * 0.08, 0.015)
    msp.add_lwpolyline(
        [(x0 + inset, y0 + inset), (x1 - inset, y0 + inset),
         (x1 - inset, y1 - inset), (x0 + inset, y1 - inset),
         (x0 + inset, y0 + inset)],
        close=True,
        dxfattribs={"layer": "ANNOTATIONS", "lineweight": 13},
    )
    # Mullion: horizontal for "long" landscape windows, vertical for "short"
    is_landscape = (x1 - x0) >= (y1 - y0)
    if size == "long" or is_landscape:
        my = (y0 + y1) / 2
        msp.add_line((x0 + inset, my), (x1 - inset, my),
                     dxfattribs={"layer": "ANNOTATIONS", "lineweight": 13})
    else:
        mx = (x0 + x1) / 2
        msp.add_line((mx, y0 + inset), (mx, y1 - inset),
                     dxfattribs={"layer": "ANNOTATIONS", "lineweight": 13})


# ─── Series classification + per-series body rendering ─────────────────────

ALUMINUM_SERIES = {"AL976", "SWD", "PANORAMA", "SOLALITE"}
COMMERCIAL_SERIES = {"TX380", "TX450", "TX500", "TX450-20", "TX500-20"}


def _is_aluminum_series(series: str) -> bool:
    return (series or "").upper() in ALUMINUM_SERIES


def _is_commercial_series(series: str) -> bool:
    return (series or "").upper() in COMMERCIAL_SERIES


def _spring_count_from_calculator(door: dict) -> int:
    """Run the spring calculator (same one that picks BC spring SKUs for
    the quote) and return its physical spring count.

    The calculator emits one PartSelection per spring SKU (typically
    1 LH + 1 RH for a single-pair setup, or 2 LH + 2 RH for two-pair).
    The PartSelection's `quantity` field is wire length in inches —
    NOT physical count. Per-side count lives in the notes string,
    formatted "...× N" at the end. We parse that to get pair count
    and double for total physical springs.

    Falls back to 2 if the calculator can't produce a result.
    """
    import re
    try:
        from app.services.part_number_service import get_parts_for_door_config
        result = get_parts_for_door_config(door)
        spring_lines = [p for p in result.get("parts_list", [])
                        if (p.get("category") or "").lower() == "spring"
                        and p.get("part_number")]
        if not spring_lines:
            return 2
        # Count distinct sides — at least 1 LH and 1 RH = 2 springs.
        # If notes carry "× N" then each side has N springs (so total = N * 2).
        per_side = 1
        for p in spring_lines:
            m = re.search(r'(?:×|x|X)\s*(\d+)\s*$', (p.get("notes") or ""))
            if m:
                per_side = max(per_side, int(m.group(1)))
        # Double for LH + RH
        total = per_side * 2
        # Pair count = ceil(spring_lines / 2) per side gives a fallback
        # if some calculators emit multiple SKUs per side
        n_lh = sum(1 for p in spring_lines if "LH" in (p.get("description") or "").upper())
        n_rh = sum(1 for p in spring_lines if "RH" in (p.get("description") or "").upper())
        side_max = max(n_lh, n_rh, 1)
        total = max(total, side_max * 2)
        return max(2, total)
    except Exception as e:
        logger.debug(f"Spring count calculator fallback: {e}")
    return 2


def _is_woodgrain_finish(color: str) -> bool:
    """True if the colour is one of the embossed woodgrain finishes (French
    Oak / Walnut / English Chestnut). Hazelwood is a solid colour despite
    the name. Used to label the back-sheet correctly on the side profile.
    """
    if not color:
        return False
    s = color.upper().replace(" ", "_").replace("-", "_")
    return any(w in s for w in ("FRENCH_OAK", "WALNUT", "ENGLISH_CHESTNUT"))


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
    """Side view of the track installation, modeled on the reference
    Craft drawing's "20"R STANDARD LIFT TRACKS" section.

    Layout (matches reference convention):
      - Door face on the LEFT
      - Vertical track runs from floor up the door face
      - Radius arc curves the track from vertical (running up) to
        horizontal (running RIGHT, into the building)
      - Hatched ceiling at the top of the view, with the horizontal
        track running just under it
      - Backroom extends to the RIGHT
      - Track drawn as a TWO-LINE cross-section (showing the U-channel
        depth), with mounting bolt circles dotted along the horizontal
    """
    bx0, by0, bx1, by1 = box
    box_w = bx1 - bx0
    box_h = by1 - by0

    door_h = ctx.door_height_in or 84.0
    door_thick = DOOR_THICKNESS_VIS_IN
    radius = ctx.track_radius_in or 15.0

    # Geometry note:
    #   - Top of vertical track sits at door_top + (high-lift extension if any)
    #   - Track curves on its full radius from vertical to horizontal
    #   - Top of horizontal track is exactly radius above top-of-vertical
    #     (tangent geometry — the arc is a quarter-circle whose center
    #     sits at the elbow of the rails, so the horizontal rail is
    #     offset upward by the radius from the vertical rail's top).
    #   - The CEILING sits a real-world clearance above the horizontal
    #     track (6-8" on residential, more on commercial). This is the
    #     "REQ. HEADROOM" the installer needs above the door top.
    CEILING_CLEARANCE_IN = 6.0   # space between top of horizontal track and ceiling

    lift = ctx.lift_type
    if lift == "high_lift" and ctx.high_lift_inches:
        vert_ext_in = ctx.high_lift_inches
    else:
        vert_ext_in = 0.0
    # Geometric headroom = how far the top of the horizontal track sits
    # above the door top. Equals vertical extension + radius for standard
    # / high-lift, big number for full vertical, special small value for
    # low-headroom (which uses a different mechanism).
    if lift == "full_vertical":
        geom_headroom = door_h + 6.0
    elif lift == "low_headroom":
        geom_headroom = 6.0   # double-track low-HR mechanism, not a standard arc
    else:
        geom_headroom = vert_ext_in + radius
    # REQ. HEADROOM (the dim the customer sees) = geometric headroom +
    # ceiling clearance — i.e., the actual clear space they need above
    # the door for the track + ceiling.
    headroom = geom_headroom + CEILING_CLEARANCE_IN
    # Reference Craft 8' door shows backroom 9'-6" (= door_h + ~18")
    backroom = door_h + BACKROOM_MARGIN

    # View extents in real-world inches (with margins for labels/dims)
    view_w = backroom + door_thick + 24
    view_h = door_h + headroom + 24

    # Border/label space reservation
    usable_w = box_w * 0.82
    usable_h = box_h * 0.72
    scale = min(usable_w / view_w, usable_h / view_h)

    cx = (bx0 + bx1) / 2
    cy = (by0 + by1) / 2
    view_x0 = cx - (view_w * scale) / 2
    view_y0 = cy - (view_h * scale) / 2 + 0.10

    def SX(inches: float) -> float:
        return inches * scale

    # Anchors — door face on the LEFT, backroom extends RIGHT
    x_face = view_x0 + SX(8)              # door face is 8" inside the left margin
    x_back = x_face + SX(backroom)        # back end of horizontal track
    y_floor = view_y0 + 0.16              # floor line
    y_door_top = y_floor + SX(door_h)
    # Top of vertical track (above door top by any high-lift extension)
    y_vert_top = y_door_top + SX(vert_ext_in)
    # Top of horizontal track = vert_top + radius (tangent quarter-circle)
    y_track_horiz = y_vert_top + SX(radius)
    # Ceiling sits 6" above the top of the horizontal track
    y_ceiling = y_track_horiz + SX(CEILING_CLEARANCE_IN)

    # Track cross-section depth (visible on paper — the actual track
    # u-channel is ~3" deep)
    track_depth_in = 2.0
    track_depth = SX(track_depth_in)

    # ── Title — "20"R STANDARD LIFT TRACKS" (from reference Craft) ──
    radius_int = int(round(radius))
    lift_name = LIFT_TYPE_LABELS.get(lift, "STANDARD LIFT TRACKS")
    lift_label = lift_name.replace(" TRACKS", "")
    t = msp.add_text(
        f'{radius_int}"R {lift_label} TRACKS',
        dxfattribs={"layer": "ANNOTATIONS", "height": TEXT_MED, "style": "Standard"},
    )
    t.set_placement((cx, by1 - 0.12),
                    align=TextEntityAlignment.MIDDLE_CENTER)

    # ── Hatched ceiling ─────────────────────────────────────────────────
    # Reference shows diagonal hatching above the horizontal track,
    # representing the building's ceiling/roof framing.
    ceiling_top = y_ceiling + SX(6)
    msp.add_lwpolyline(
        [(x_face - SX(2), y_ceiling), (x_back + SX(2), y_ceiling),
         (x_back + SX(2), ceiling_top), (x_face - SX(2), ceiling_top),
         (x_face - SX(2), y_ceiling)],
        close=True,
        dxfattribs={"layer": "FRAMING", "lineweight": 18},
    )
    # 45° hatch lines clipped to ceiling rectangle
    hatch_step = 0.10
    cw = (x_back + SX(2)) - (x_face - SX(2))
    ch = ceiling_top - y_ceiling
    for i in range(int((cw + ch) / hatch_step) + 1):
        x_start = (x_face - SX(2)) - ch + i * hatch_step
        y_start = y_ceiling
        x_end = x_start + ch
        y_end = ceiling_top
        if x_end < (x_face - SX(2)) or x_start > (x_back + SX(2)):
            continue
        if x_start < (x_face - SX(2)):
            trim = (x_face - SX(2)) - x_start
            x_start += trim; y_start += trim
        if x_end > (x_back + SX(2)):
            trim = x_end - (x_back + SX(2))
            x_end -= trim; y_end -= trim
        if x_end > x_start and y_end > y_start:
            msp.add_line((x_start, y_start), (x_end, y_end),
                         dxfattribs={"layer": "HIDDEN", "lineweight": 5})

    # ── Floor line ──────────────────────────────────────────────────────
    msp.add_line(
        (view_x0, y_floor), (view_x0 + SX(view_w), y_floor),
        dxfattribs={"layer": "FRAMING", "lineweight": 30},
    )

    # ── Door (thin vertical bar at face, behind the vertical track) ─────
    door_x_back = x_face - SX(door_thick)
    msp.add_lwpolyline(
        [(door_x_back, y_floor), (x_face, y_floor),
         (x_face, y_door_top), (door_x_back, y_door_top),
         (door_x_back, y_floor)],
        close=True,
        dxfattribs={"layer": "FRAMING", "lineweight": 30},
    )

    # ── Track path: vertical → 90° arc → horizontal, drawn as a
    # DOUBLE-LINE cross-section (outer rail + inner rail spaced by
    # track_depth). Tangent quarter-circle geometry: the arc center
    # sits at the ELBOW of the rails — same height as top of vertical
    # track, offset right by the radius. So both arcs and rails meet
    # without gaps. ───────────────────────────────────────────────
    arc_cx = x_face + SX(radius)
    arc_cy = y_vert_top
    radius_outer_in = radius
    radius_inner_in = max(radius - track_depth_in, 0.5)

    if lift == "full_vertical":
        # No arc — track continues straight up to ceiling
        for offset in (0.0, track_depth):
            msp.add_line(
                (x_face + offset, y_floor),
                (x_face + offset, y_track_horiz),
                dxfattribs={"layer": "TRACKS", "lineweight": 18},
            )
    else:
        # Vertical rails (outer rail flush against door face = x_face;
        # inner rail offset INTO the building by track_depth).
        msp.add_line(
            (x_face, y_floor), (x_face, y_vert_top),
            dxfattribs={"layer": "TRACKS", "lineweight": 18},
        )
        msp.add_line(
            (x_face + track_depth, y_floor),
            (x_face + track_depth, y_vert_top),
            dxfattribs={"layer": "TRACKS", "lineweight": 18},
        )
        # Outer arc — sweeps the upper-LEFT quadrant of the arc center.
        # ezdxf arcs are counter-clockwise: 90° → 180° = upper-left.
        # 180° point: (arc_cx - R, arc_cy) = (x_face, y_vert_top)
        #             — connects to top of OUTER vertical rail
        # 90°  point: (arc_cx, arc_cy + R) = (arc_cx, y_track_horiz)
        #             — connects to start of OUTER horizontal rail
        msp.add_arc(
            center=(arc_cx, arc_cy),
            radius=SX(radius_outer_in),
            start_angle=90, end_angle=180,
            dxfattribs={"layer": "TRACKS", "lineweight": 18},
        )
        # Inner arc — same center, smaller radius. Connects to top of
        # INNER vertical rail at (x_face + track_depth, y_vert_top) and
        # to start of INNER horizontal rail at (arc_cx, y_track_horiz - track_depth).
        msp.add_arc(
            center=(arc_cx, arc_cy),
            radius=SX(radius_inner_in),
            start_angle=90, end_angle=180,
            dxfattribs={"layer": "TRACKS", "lineweight": 18},
        )
        # Horizontal rails — outer rail at top (y_track_horiz), inner
        # rail track_depth below. Both start at arc_cx (= elbow x).
        msp.add_line(
            (arc_cx, y_track_horiz),
            (x_back, y_track_horiz),
            dxfattribs={"layer": "TRACKS", "lineweight": 18},
        )
        msp.add_line(
            (arc_cx, y_track_horiz - track_depth),
            (x_back, y_track_horiz - track_depth),
            dxfattribs={"layer": "TRACKS", "lineweight": 18},
        )
        # Mounting bolts dotted along the horizontal track (~24" spacing)
        bolt_spacing_in = 24.0
        n_bolts = max(2, int((x_back - arc_cx) / SX(bolt_spacing_in)))
        for k in range(1, n_bolts + 1):
            bx = arc_cx + SX(bolt_spacing_in) * k - SX(bolt_spacing_in / 2)
            if bx >= x_back - SX(2):
                break
            msp.add_circle(
                center=(bx, y_track_horiz),
                radius=0.025,
                dxfattribs={"layer": "HARDWARE", "lineweight": 13},
            )
        # End cap at the back end of the horizontal track
        msp.add_line(
            (x_back, y_track_horiz - track_depth),
            (x_back, y_track_horiz),
            dxfattribs={"layer": "TRACKS", "lineweight": 25},
        )

        # ── TORSION SHAFT — small filled circle at the elbow of the
        # rails (= arc_cx, arc_cy). The shaft runs perpendicular to
        # the side view (across the door width); we see its
        # cross-section. Drawn with a centered dot so it reads as a
        # solid round shaft. ──────────────────────────────────────
        shaft_diameter_in = 1.0
        shaft_r = max(SX(shaft_diameter_in / 2), 0.04)
        msp.add_circle(
            center=(arc_cx, arc_cy),
            radius=shaft_r,
            dxfattribs={"layer": "HARDWARE", "lineweight": 30},
        )
        # Inner solid dot for clarity
        msp.add_circle(
            center=(arc_cx, arc_cy),
            radius=shaft_r * 0.35,
            dxfattribs={"layer": "HARDWARE", "lineweight": 25},
        )

    # ── High-lift extension dimension (between door top and radius start) ──
    if vert_ext_in > 0:
        _draw_linear_dim_vertical(
            msp, (x_face - 0.10, y_door_top), (x_face - 0.10, y_vert_top),
            dim_x=x_face - 0.32,
            label=f"HI-LIFT {fmt_length_imperial(vert_ext_in)}",
        )

    # ── Dimensions — stacked-horizontal labels per reference Craft ─────
    underside_y = y_track_horiz - track_depth
    underside_in = door_h + radius - track_depth_in

    # REQ. HEADROOM — closest column on the LEFT, between door top and
    # underside of horizontal track.
    _draw_linear_dim_vertical_stacked(
        msp, (x_face, y_door_top), (x_face, underside_y),
        dim_x=x_face - 0.20,
        label_lines=["REQ.", "HEADROOM",
                     fmt_length_imperial(headroom)],
        side="left",
    )

    # DOOR HEIGHT — outboard column on the LEFT, floor to door top.
    _draw_linear_dim_vertical_stacked(
        msp, (x_face, y_floor), (x_face, y_door_top),
        dim_x=x_face - 0.42,
        label_lines=["DOOR", "HEIGHT",
                     fmt_length_imperial(door_h)],
        side="left",
    )

    # UNDERSIDE OF TRACK — vertical dim on the right side of the arc,
    # placed in the open space between the door slab and the back end
    # of the horizontal track.
    underside_dim_x = arc_cx + 0.32
    _draw_linear_dim_vertical_stacked(
        msp, (arc_cx, y_floor), (arc_cx, underside_y),
        dim_x=underside_dim_x,
        label_lines=["UNDERSIDE", "OF", "TRACK",
                     fmt_length_imperial(underside_in)],
        side="right",
    )

    # BACKROOM — horizontal dim above the horizontal track, with a
    # 2-line stacked label at the right end.
    backroom_dim_y = y_track_horiz + 0.24
    sx_b, ex_b = x_face, x_back
    msp.add_line((sx_b, y_track_horiz), (sx_b, backroom_dim_y + 0.05),
                 dxfattribs={"layer": "DIMENSIONS"})
    msp.add_line((ex_b, y_track_horiz), (ex_b, backroom_dim_y + 0.05),
                 dxfattribs={"layer": "DIMENSIONS"})
    msp.add_line((sx_b, backroom_dim_y), (ex_b, backroom_dim_y),
                 dxfattribs={"layer": "DIMENSIONS"})
    for x in (sx_b, ex_b):
        msp.add_line((x - 0.04, backroom_dim_y - 0.04),
                     (x + 0.04, backroom_dim_y + 0.04),
                     dxfattribs={"layer": "DIMENSIONS"})
    # Stacked "BACKROOM / 9'-6"" label centered horizontally over the dim
    backroom_lines = ["BACKROOM", fmt_length_imperial(backroom)]
    block_h = len(backroom_lines) * 0.10
    label_cx = (sx_b + ex_b) / 2
    label_y_top = backroom_dim_y + 0.20 + block_h
    for i, ln in enumerate(backroom_lines):
        t = msp.add_text(
            ln,
            dxfattribs={"layer": "DIMENSIONS",
                        "height": TEXT_SMALL * 0.8,
                        "style": "Standard"},
        )
        t.set_placement((label_cx, label_y_top - (i + 0.5) * 0.10),
                        align=TextEntityAlignment.MIDDLE_CENTER)

    # ── Floor label below the floor line ────────────────────────────────
    floor_lbl = msp.add_text(
        "FLOOR",
        dxfattribs={"layer": "ANNOTATIONS", "height": TEXT_SMALL,
                    "style": "Standard"},
    )
    floor_lbl.set_placement(
        ((x_face + x_back) / 2, y_floor - 0.18),
        align=TextEntityAlignment.MIDDLE_CENTER,
    )

    # ── Interior / exterior labels — LEFT of door = exterior, RIGHT of
    # backroom track = interior. Placed at the same height as the
    # FLOOR label so they read along the floor line. ─────────────
    ext_label = msp.add_text(
        "EXTERIOR",
        dxfattribs={"layer": "ANNOTATIONS", "height": TEXT_SMALL * 0.85,
                    "style": "Standard"},
    )
    ext_label.set_placement(
        (door_x_back - SX(2), y_floor - 0.18),
        align=TextEntityAlignment.MIDDLE_RIGHT,
    )
    int_label = msp.add_text(
        "INTERIOR",
        dxfattribs={"layer": "ANNOTATIONS", "height": TEXT_SMALL * 0.85,
                    "style": "Standard"},
    )
    int_label.set_placement(
        (x_back + SX(2), y_floor - 0.18),
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
    # Spring count from ctx (residential/aluminum 2, wide commercial 4).
    # For 4-spring setup the springs are arranged in TWO PAIRS, one pair
    # on each side of center, with a small gap between the inner spring
    # of each pair and the center coupler.
    num_springs = max(2, int(ctx.spring_count or 2))
    spring_od_in = 3.5                          # visual OD (real ~2.0-2.75")
    spring_len_in = max(28.0, ctx.door_width_in * 0.12)
    spring_od = max(scale * spring_od_in, 0.15)
    spring_len = scale * spring_len_in

    center_x = (left_x + right_x) / 2
    gap_between_springs = scale * 6.0  # center gap

    # Compute spring x-ranges. For 2 springs: one each side of center.
    # For 4 springs: pairs of two on each side, tightly stacked end-to-end.
    spring_ranges: list[tuple[float, float]] = []
    if num_springs == 2:
        # Left side
        end_l = center_x - gap_between_springs / 2
        spring_ranges.append((end_l - spring_len, end_l))
        # Right side
        end_r = center_x + gap_between_springs / 2
        spring_ranges.append((end_r, end_r + spring_len))
    else:
        # 4 (or more) springs — split into pairs each side. Each pair has
        # the springs end-to-end with a tiny coupler-stub between them.
        per_side = num_springs // 2
        side_total = spring_len * per_side + scale * 2 * (per_side - 1)
        for s in range(per_side):
            end_l = center_x - gap_between_springs / 2 - (s * (spring_len + scale * 2))
            spring_ranges.append((end_l - spring_len, end_l))
            end_r = center_x + gap_between_springs / 2 + (s * (spring_len + scale * 2))
            spring_ranges.append((end_r, end_r + spring_len))

    for sx0, sx1 in spring_ranges:
        a, b = sorted([sx0, sx1])
        _draw_coil_spring(msp, a, b, shaft_cy, spring_od,
                          coils=16, layer="HARDWARE")

    # Center coupler (small block between innermost springs on the shaft)
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

    # ── End brackets (anchor brackets at each end of the shaft) ────────
    bracket_w = scale * 4.0
    bracket_h = shaft_thick * 4.0
    for bx in (left_x, right_x):
        msp.add_lwpolyline(
            [(bx - bracket_w / 2, shaft_cy - bracket_h / 2),
             (bx + bracket_w / 2, shaft_cy - bracket_h / 2),
             (bx + bracket_w / 2, shaft_cy + bracket_h / 2),
             (bx - bracket_w / 2, shaft_cy + bracket_h / 2),
             (bx - bracket_w / 2, shaft_cy - bracket_h / 2)],
            close=True,
            dxfattribs={"layer": "HARDWARE", "lineweight": 30},
        )

    # ── Cable drums at each shaft end (between the bracket and the
    # outermost spring). On the FRONT ELEVATION we view the shaft from
    # the side — its long axis runs left-right across the door — so a
    # drum (which is a cylinder mounted on the shaft) appears as a
    # short cylindrical body with the shaft passing horizontally
    # through it. Drawn as a rectangle taller than the shaft, with
    # vertical end faces and the shaft visible passing through. ─────
    drum_d_in = 8.0   # typical 8" residential drum diameter
    drum_w_in = 4.0   # axial length along the shaft
    drum_h = max(scale * drum_d_in, shaft_thick * 3.0)
    drum_w = max(scale * drum_w_in, shaft_thick * 1.5)
    for bx, side in ((left_x, +1), (right_x, -1)):
        # Drum sits just inboard of the end bracket
        drum_cx = bx + side * (bracket_w / 2 + drum_w / 2 + scale * 1.0)
        # Cylinder body
        msp.add_lwpolyline(
            [(drum_cx - drum_w / 2, shaft_cy - drum_h / 2),
             (drum_cx + drum_w / 2, shaft_cy - drum_h / 2),
             (drum_cx + drum_w / 2, shaft_cy + drum_h / 2),
             (drum_cx - drum_w / 2, shaft_cy + drum_h / 2),
             (drum_cx - drum_w / 2, shaft_cy - drum_h / 2)],
            close=True,
            dxfattribs={"layer": "HARDWARE", "lineweight": 25},
        )
        # Cable groove hint — a few horizontal lines on the drum body
        # representing the cable wrap channels
        for k in range(1, 4):
            gy = shaft_cy - drum_h / 2 + drum_h * (k / 4)
            msp.add_line(
                (drum_cx - drum_w / 2 + 0.01, gy),
                (drum_cx + drum_w / 2 - 0.01, gy),
                dxfattribs={"layer": "HARDWARE", "lineweight": 5},
            )

    # ── Operator marker on the chosen side of the shaft ────────────────
    # Reference TX-450 shows the operator on one specific side (a small
    # bracketed motor housing attached to the end of the shaft). We
    # render a labelled rectangle on the configured operator side so
    # the installer can see where the drive lands.
    is_powered = (ctx.operator or "NONE").upper() not in ("NONE", "MANUAL")
    if is_powered:
        op_side = (ctx.operator_side or "right").lower()
        op_anchor_x = left_x if op_side == "left" else right_x
        op_dir = -1 if op_side == "left" else +1
        op_w = scale * 6.0
        op_h = shaft_thick * 5.0
        # Position the operator OUTBOARD of the end bracket
        op_cx = op_anchor_x + op_dir * (bracket_w / 2 + op_w / 2 + scale * 2)
        msp.add_lwpolyline(
            [(op_cx - op_w / 2, shaft_cy - op_h / 2),
             (op_cx + op_w / 2, shaft_cy - op_h / 2),
             (op_cx + op_w / 2, shaft_cy + op_h / 2),
             (op_cx - op_w / 2, shaft_cy + op_h / 2),
             (op_cx - op_w / 2, shaft_cy - op_h / 2)],
            close=True,
            dxfattribs={"layer": "HARDWARE", "lineweight": 35},
        )
        op_lbl = msp.add_text(
            "OP",
            dxfattribs={"layer": "ANNOTATIONS",
                        "height": TEXT_SMALL * 0.7,
                        "style": "Standard"},
        )
        op_lbl.set_placement(
            (op_cx, shaft_cy),
            align=TextEntityAlignment.MIDDLE_CENTER,
        )

    # ── Shaft-length dimension above the brackets (full span) ──────────
    dim_y = shaft_top + 0.32
    shaft_length_in = (right_x - left_x) / scale
    _draw_linear_dim(msp, (left_x, shaft_top), (right_x, shaft_top), dim_y,
                     label=fmt_length_imperial(shaft_length_in))

    # ── Bracket-to-bracket span (matches reference "4'-6\"" callout) ──
    # The end brackets of a torsion shaft sit at the inside face of each
    # track jamb, so this is roughly the door-width clear opening.
    bracket_span_in = ctx.door_width_in or 96.0
    _draw_linear_dim(msp, (left_x, shaft_cy - bracket_h * 0.6),
                     (right_x, shaft_cy - bracket_h * 0.6),
                     shaft_cy - bracket_h - 0.18,
                     label=fmt_length_imperial(bracket_span_in))

    # ── Center-gap dimension between the two springs ("6\"" reference) ──
    # The springs meet at a center coupler — the gap between their inside
    # ends is small (typically ~6").
    spring_left_inner = center_x - gap_between_springs / 2
    spring_right_inner = center_x + gap_between_springs / 2
    gap_dim_y = shaft_cy + spring_od / 2 + 0.18
    _draw_linear_dim(msp, (spring_left_inner, shaft_cy + spring_od / 2),
                     (spring_right_inner, shaft_cy + spring_od / 2),
                     gap_dim_y,
                     label=fmt_length_imperial(6.0))

    # ── Centerline-of-shaft callout ─────────────────────────────────────
    cl_label = msp.add_text(
        "CENTERLINE OF SHAFT",
        dxfattribs={"layer": "ANNOTATIONS", "height": TEXT_SMALL, "style": "Standard"},
    )
    cl_label.set_placement(
        (center_x, shaft_cy - bracket_h - 0.42),
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
    # Exterior / Interior orientation labels above the profile (left/right
    # of the section centerline) — matches the reference Craft drawing.
    # Note: the LEFT face of the section is the exterior; RIGHT is interior.

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

    # Pre-compute heights used by both the layered composition and the
    # top-cap / astragal / bottom-bracket draws below.
    cap_h = SX(1.5)
    astr_h = SX(1.0)

    # ── Layered panel composition ──────────────────────────────────────
    # The reference Craft drawing shows the panel as a real cross-section
    # with visible exterior skin, foam core, and back sheet. We mirror
    # that here so the customer/installer can SEE the construction
    # rather than reading words from leader callouts alone.
    is_glass_series = ctx.door_series in {"AL976", "SWD", "PANORAMA", "SOLALITE"}
    skin_thickness_visual = max(SX(thickness_in * 0.06), 0.025)  # exaggerated 26ga
    thermal_break_thickness = max(SX(thickness_in * 0.04), 0.018)

    # Outer body outline (full section)
    msp.add_lwpolyline(
        [(prof_x0, prof_y0), (prof_x1, prof_y0),
         (prof_x1, prof_y1), (prof_x0, prof_y1),
         (prof_x0, prof_y0)],
        close=True,
        dxfattribs={"layer": "FRAMING", "lineweight": 35},
    )

    # Note: Exterior/Interior orientation is implicit — the asymmetric
    # composition (cap on top, astragal on bottom, exterior skin on the
    # left edge facing the foam core, woodgrain back-sheet on the right)
    # together with the labeled callouts makes the orientation obvious
    # without needing extra "EXT/INT" text crowding the title row.

    if not is_glass_series:
        # Exterior steel skin (on the LEFT face — exterior of door)
        ext_skin_x1 = prof_x0 + skin_thickness_visual
        msp.add_lwpolyline(
            [(prof_x0, prof_y0), (ext_skin_x1, prof_y0),
             (ext_skin_x1, prof_y1), (prof_x0, prof_y1),
             (prof_x0, prof_y0)],
            close=True,
            dxfattribs={"layer": "FRAMING", "lineweight": 25},
        )
        # Thermal break foam tape — thin strip just inside the exterior
        # skin, separating the skin from the foam core. Drawn as a
        # dashed-fill rectangle.
        tb_x0 = ext_skin_x1
        tb_x1 = tb_x0 + thermal_break_thickness
        msp.add_lwpolyline(
            [(tb_x0, prof_y0), (tb_x1, prof_y0),
             (tb_x1, prof_y1), (tb_x0, prof_y1),
             (tb_x0, prof_y0)],
            close=True,
            dxfattribs={"layer": "HIDDEN", "linetype": "HIDDEN", "lineweight": 13},
        )
        # Interior back sheet (RIGHT face)
        int_skin_x0 = prof_x1 - skin_thickness_visual
        msp.add_lwpolyline(
            [(int_skin_x0, prof_y0), (prof_x1, prof_y0),
             (prof_x1, prof_y1), (int_skin_x0, prof_y1),
             (int_skin_x0, prof_y0)],
            close=True,
            dxfattribs={"layer": "FRAMING", "lineweight": 25},
        )
        # Polyurethane foam core fill — stippled dots between thermal
        # break and back sheet so the insulation is visually obvious.
        core_x0 = tb_x1
        core_x1 = int_skin_x0
        if core_x1 > core_x0:
            stipple_step_x = max((core_x1 - core_x0) / 6, 0.04)
            stipple_step_y = stipple_step_x
            x = core_x0 + stipple_step_x / 2
            row = 0
            while x < core_x1:
                # Stagger every other row for organic look
                y_off = (stipple_step_y / 2) if row % 2 else 0
                y = prof_y0 + 0.05 + y_off
                while y < prof_y1 - 0.05:
                    msp.add_circle(
                        center=(x, y),
                        radius=0.008,
                        dxfattribs={"layer": "ANNOTATIONS", "lineweight": 5},
                    )
                    y += stipple_step_y
                x += stipple_step_x
                row += 1

        # Hinge / strut reinforcement steel strips — small horizontal
        # rectangles embedded in the foam at typical hinge positions.
        # Two strips in the upper half of the section, where the hinge
        # bolts through. Drawn as solid filled rectangles for emphasis.
        strip_w = (core_x1 - core_x0) * 0.55
        strip_h = SX(0.35)
        strip_x0 = core_x0 + (core_x1 - core_x0 - strip_w) / 2
        strip_x1 = strip_x0 + strip_w
        for y_pct in (0.18, 0.36):  # upper-third positions
            sy = prof_y0 + (prof_y1 - prof_y0) * (1 - y_pct)
            msp.add_lwpolyline(
                [(strip_x0, sy - strip_h / 2), (strip_x1, sy - strip_h / 2),
                 (strip_x1, sy + strip_h / 2), (strip_x0, sy + strip_h / 2),
                 (strip_x0, sy - strip_h / 2)],
                close=True,
                dxfattribs={"layer": "FRAMING", "lineweight": 30},
            )
            # Crosshatch the strip so it reads as steel
            for k in range(1, 4):
                px = strip_x0 + (strip_x1 - strip_x0) * (k / 4)
                msp.add_line((px, sy - strip_h / 2 + 0.01),
                             (px, sy + strip_h / 2 - 0.01),
                             dxfattribs={"layer": "ANNOTATIONS", "lineweight": 5})

    # ── Top end cap (steel with vinyl weather strip) ─────────────────────
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

    # ── Construction callouts (reference Craft drawing parity).
    # Each entry: (anchor_y on geometry, leader_from_x, label_text)
    # The label TEXT sits on the right side of the box with leaders
    # bending to point at the relevant feature. Label y-positions are
    # distributed evenly across the box so they don't collide; leaders
    # are kinked (horizontal segment from feature → vertical jog →
    # horizontal to label) so the leader doesn't overlap the label
    # of another callout above/below.
    sec_top = prof_y1 + cap_h
    sec_bot = prof_y0 - astr_h

    if is_glass_series:
        callouts = [
            (sec_top - cap_h * 0.5,    prof_x1 + 0.02, "STEEL END CAP\\PC/W VINYL WEATHER STRIP"),
            (prof_y1 - SX(2.0),        prof_x1 + 0.02, "GLAZING MOULDING"),
            (prof_cy,                  prof_x0 - SX(0.05), "ALUMINUM EXTRUDED FRAME"),
            (prof_y0 + SX(1.5),        prof_x1 + brk_w + 0.05, "BOTTOM BRACKET\\P12GA GAL STEEL"),
            (prof_y0 - astr_h * 0.55,  prof_x1 + 0.02, "LOW TEMP VINYL\\PBOTTOM ASTRAGAL"),
        ]
    else:
        back_label = ("BACK SHEET\\PWOODGRAIN EMBOSSED"
                      if _is_woodgrain_finish(ctx.panel_color)
                      else "BACK SHEET\\P26GA STEEL")
        callouts = [
            (sec_top - cap_h * 0.25,   prof_x1 + 0.02,        "RUBBER WEATHER SEAL"),
            (sec_top - cap_h * 0.85,   prof_x1 + 0.02,        "STEEL END CAP\\PC/W VINYL WEATHER STRIP"),
            (prof_y1 - SX(2.5),        prof_x1 + 0.02,        "HINGE / STRUT REINFORCEMENT\\PSTEEL STRIPS"),
            (prof_cy + SX(1.5),        prof_x1 + 0.02,        "FOAMED-IN-PLACE POLYURETHANE\\P2.5 PCF — ZERO ODP"),
            (prof_cy - SX(0.5),        prof_x0 - SX(0.05),    "26GA EXTERIOR PREFINISHED STEEL SKIN"),
            (prof_cy - SX(2.5),        prof_x1 + 0.02,        back_label),
            (prof_y0 + SX(1.5),        prof_x1 + brk_w + 0.05, "BOTTOM BRACKET\\P12GA GAL STEEL"),
            (prof_y0 - astr_h * 0.55,  prof_x1 + 0.02,        "LOW TEMP VINYL\\PBOTTOM ASTRAGAL"),
            (prof_y0 - astr_h * 0.05,  prof_x0 - SX(0.05),    "PLASTIC BOTTOM RETAINER"),
        ]

    # Distribute label y-positions evenly across the available label
    # column so multi-line callouts don't overlap each other. Leaders
    # bend to connect feature anchor → label position with a small jog.
    label_x = bx0 + box_w * 0.55
    label_top = sec_top - 0.02
    label_bot = sec_bot - 0.02
    n = len(callouts)
    label_h = max((label_top - label_bot) / max(n, 1), 0.12)
    for i, (anchor_y, leader_from_x, text_lines) in enumerate(callouts):
        # Label slot y, top → bottom, evenly spaced
        y_label = label_top - (i + 0.5) * label_h
        # Leader: feature → small horizontal stub → diagonal jog → label
        stub_x = max(leader_from_x + 0.06,
                     prof_x1 + brk_w + 0.10 if leader_from_x > prof_x1 else prof_x0 - SX(0.20))
        msp.add_line(
            (leader_from_x, anchor_y), (stub_x, anchor_y),
            dxfattribs={"layer": "ANNOTATIONS", "lineweight": 13},
        )
        msp.add_line(
            (stub_x, anchor_y), (label_x - 0.03, y_label),
            dxfattribs={"layer": "ANNOTATIONS", "lineweight": 13},
        )
        mtext = msp.add_mtext(
            text_lines,
            dxfattribs={
                "layer": "ANNOTATIONS",
                "char_height": TEXT_SMALL * 0.65,
                "style": "Standard",
                "attachment_point": 4,  # middle-left
                "width": bx1 - label_x - 0.02,
            },
        )
        mtext.dxf.insert = (label_x, y_label)

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
    sideroom_in = 3.5  # minimum required sideroom each side (wall thickness)
    jamb_2x_thickness_in = 1.5  # visible 2x6 lumber thickness
    door_thickness_in = _panel_thickness_in(ctx.door_series, ctx.door_type)
    # Plan-view geometry. The "sideroom" callout matches the reference and
    # represents the wall + jamb combined depth on each side of the RO.
    # Inside this sideroom, the inside-most 1.5" is the actual 2x6 jamb.
    total_w = ro_w + 2 * sideroom_in
    depth_in = door_thickness_in + 6.0  # section + ext/int buffer + jamb depth

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

    # ── Left + right jambs as cross-sections of the framing wall.
    # Each jamb is drawn as a 2x6 (1.5" x 5.5") sitting in a hatched
    # framing wall block, with the door slab tucking against its
    # interior face. The wall hatching makes it visually obvious that
    # the jamb is part of the structural opening, not free-floating.
    jamb_2x_thickness = 1.5    # 2x lumber actual thickness
    jamb_2x_depth = 5.5        # 2x6 actual depth
    wall_extension = 4.0       # how far the framing wall extends past the jamb
    is_steel_jamb = ctx.jamb_type == "steel"

    jl_x0 = plan_x0
    jl_x1 = plan_x0 + sideroom_in * scale
    jr_x0 = plan_x1 - sideroom_in * scale
    jr_x1 = plan_x1

    def _draw_jamb_block(wall_x0: float, wall_x1: float,
                          jamb_inside_x: float) -> None:
        """Draw the wall framing block + the 2x6 jamb sitting at the RO
        edge. The wall block spans wall_x0..wall_x1 (= sideroom_in wide),
        with hatching for visual texture. The jamb 2x6 is the inside-most
        ~1.5" of the wall block, drawn with a heavier outline."""
        wall_y_bot = sec_y_bot - SX(0.6)
        wall_y_top = sec_y_top + SX(jamb_2x_depth)
        wall_xs = sorted([wall_x0, wall_x1])
        # Outer wall block
        msp.add_lwpolyline(
            [(wall_xs[0], wall_y_bot), (wall_xs[1], wall_y_bot),
             (wall_xs[1], wall_y_top), (wall_xs[0], wall_y_top),
             (wall_xs[0], wall_y_bot)],
            close=True,
            dxfattribs={"layer": "FRAMING", "lineweight": 18},
        )
        # 45° hatch — clipped to the wall rectangle
        wall_w = wall_xs[1] - wall_xs[0]
        wall_h = wall_y_top - wall_y_bot
        hatch_step = 0.10
        n_hatches = int((wall_w + wall_h) / hatch_step) + 1
        for i in range(n_hatches):
            x_start = wall_xs[0] - wall_h + i * hatch_step
            y_start = wall_y_bot
            x_end = x_start + wall_h
            y_end = wall_y_top
            # Clip to wall x-bounds
            if x_end < wall_xs[0] or x_start > wall_xs[1]:
                continue
            if x_start < wall_xs[0]:
                trim = wall_xs[0] - x_start
                x_start += trim
                y_start += trim
            if x_end > wall_xs[1]:
                trim = x_end - wall_xs[1]
                x_end -= trim
                y_end -= trim
            if x_end > x_start and y_end > y_start:
                msp.add_line((x_start, y_start), (x_end, y_end),
                             dxfattribs={"layer": "HIDDEN", "lineweight": 5})
        # Jamb 2x6 inset (inside-most 1.5" of the wall block)
        jx_outer = (jamb_inside_x - SX(jamb_2x_thickness_in)
                    if jamb_inside_x > (wall_xs[0] + wall_xs[1]) / 2
                    else jamb_inside_x + SX(jamb_2x_thickness_in))
        jxs = sorted([jamb_inside_x, jx_outer])
        msp.add_lwpolyline(
            [(jxs[0], wall_y_bot), (jxs[1], wall_y_bot),
             (jxs[1], wall_y_top), (jxs[0], wall_y_top),
             (jxs[0], wall_y_bot)],
            close=True,
            dxfattribs={"layer": "FRAMING", "lineweight": 35},
        )
        if is_steel_jamb:
            # Add vertical pinstripes inside the jamb to read as steel
            step = max(SX(jamb_2x_thickness_in) / 4, 0.03)
            x = jxs[0] + step
            while x < jxs[1]:
                msp.add_line((x, wall_y_bot + 0.02), (x, wall_y_top - 0.02),
                             dxfattribs={"layer": "ANNOTATIONS", "lineweight": 5})
                x += step

    _draw_jamb_block(jl_x0, jl_x1, jl_x1)   # left wall: outer→inner; jamb at inner
    _draw_jamb_block(jr_x0, jr_x1, jr_x0)   # right wall: outer→inner; jamb at inner

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
    radius = int(round(float(ctx.track_radius_in or 15)))
    lift = (ctx.lift_type or "standard").lower()
    # Strut count — one strut per internal section joint when struts are on
    # (matches the reference Craft drawing's "20GA STRUTS ___1___" line for
    # an 8' door = 4 sections = 3 joints, but typically only 1 strut on
    # residential, more on wide commercial).
    n_sections = max(3, int((ctx.door_height_in or 84) / ctx.section_height_in))
    if not ctx.has_struts:
        strut_count = 0
    elif is_commercial:
        strut_count = max(1, n_sections - 1)
    else:
        strut_count = 1

    selected = {
        # Track size
        "2\" TRACK APPLICATION":       track_size in ("2", "2_in", ""),
        "3\" TRACK APPLICATION":       track_size in ("3", "3_in"),
        # Frame / jamb material
        "STEEL FRAME":                 ctx.jamb_type == "steel",
        "WOOD FRAME":                  ctx.jamb_type == "wood",
        # Track mount style
        "BRACKET MOUNT":               ctx.track_mount == "bracket",
        "CONTINUOUS ANGLE MOUNT":      ctx.track_mount == "angle",
        # End stile / hinge style
        "SINGLE END STILES/HINGES":    not (is_aluminum or
                                            (is_commercial and ctx.door_width_in >= 192)),
        "DOUBLE END STILES/HINGES":    is_aluminum or
                                        (is_commercial and ctx.door_width_in >= 192),
        # Track radius — call out the actual configured radius
        "12\" RADIUS":                 radius == 12,
        "15\" RADIUS":                 radius == 15,
        "20\" RADIUS":                 radius == 20,
        # Strut gauge with explicit count
        f"16GA STRUTS    [{strut_count}]" if (is_commercial and ctx.has_struts) else "16GA STRUTS":
                                       ctx.has_struts and is_commercial,
        f"20GA STRUTS    [{strut_count}]" if (not is_commercial and ctx.has_struts) else "20GA STRUTS":
                                       ctx.has_struts and not is_commercial,
        "MAN DOOR (see man door spec)": ctx.man_door,
        "INTERIOR SIDE LOCK":          ctx.interior_lock,
        # Operator
        "MANUAL OPERATION":            operator in ("NONE", "MANUAL"),
        "GEARED CHAIN HOIST":          operator in ("CHAIN_HOIST", "CHAIN", "HOIST"),
        "ELECTRIC OPERATOR (BY OTHERS)": (operator not in
                                          ("NONE", "MANUAL", "CHAIN_HOIST",
                                           "CHAIN", "HOIST")),
        # Shaft type
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
        # Weather seals
        "TOP SEAL VINYL":              ctx.has_weather_stripping,
        "STEEL VINYL WEATHER STRIP":   ctx.has_weather_stripping,
        # Hardware sub-items (residential extras the reference Craft drawing
        # carries — wired off the existing has_weather_stripping/struts
        # bundle for now, can be split into discrete configurator fields
        # later if needed).
        "HD 10 BALL ROLLERS":          True,  # standard-issue on every door
        "OPERATOR BRACKET":            operator not in ("NONE", "MANUAL"),
        "LHR FRONT":                   lift == "low_headroom" and ctx.track_mount == "bracket",
        "LHR REAR":                    lift == "low_headroom" and ctx.track_mount == "angle",
        "DECORATIVE FACE HARDWARE":    False,  # TODO: wire to a configurator field
        "EXHAUST PORT":                ctx.exhaust_port,
        # Final line: door colour choice spelled out (matches reference layout)
        f"DOOR COLOR CHOICE ({ctx.panel_color or 'WHITE'})": True,
    }

    # Layout: single column of check-items. Line height includes the
    # SPRINGS INFO + TURNS tail lines so they fit inside the box.
    avail_h = (by1 - 0.35) - (by0 + 0.05)
    n_extras_tail = 3   # gap + SPRINGS INFO + TURNS
    n = len(selected) + n_extras_tail
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

    # ── SPRINGS INFO + TURNS lines below the checklist (matches the
    # reference TX-450 drawing's tail). The tech fills in TURNS at
    # install time; we render the SPRINGS INFO from spring_count. ──
    y -= line_h * 0.4
    springs_info = msp.add_text(
        f"SPRINGS INFO: {ctx.spring_count}-SPRING SETUP",
        dxfattribs={"layer": "ANNOTATIONS", "height": TEXT_SMALL * 0.85,
                    "style": "Standard"},
    )
    springs_info.set_placement((bx0 + 0.08, y),
                                align=TextEntityAlignment.MIDDLE_LEFT)
    y -= line_h
    turns = msp.add_text(
        "TURNS:",
        dxfattribs={"layer": "ANNOTATIONS", "height": TEXT_SMALL * 0.85,
                    "style": "Standard"},
    )
    turns.set_placement((bx0 + 0.08, y),
                        align=TextEntityAlignment.MIDDLE_LEFT)
    # Underline placeholder for the tech to fill in turns count
    msp.add_line(
        (bx0 + 0.65, y - 0.02), (bx1 - 0.10, y - 0.02),
        dxfattribs={"layer": "ANNOTATIONS", "lineweight": 13},
    )


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


def _draw_linear_dim_vertical_stacked(
    msp: Modelspace, start: Tuple[float, float], end: Tuple[float, float],
    dim_x: float, label_lines: list[str], side: str = "left",
    line_h: float = 0.10,
) -> None:
    """Vertical dim with the label drawn as STACKED HORIZONTAL text
    centered between the dim line and the geometry. Matches the
    reference Craft drawing's "REQ. / HEADROOM / 1'-9"" style — each
    line is its own horizontal text, stacked vertically. Much more
    readable than rotated single-line text at small scales.

    side: "left"  → label is to the LEFT of dim_x
          "right" → label is to the RIGHT of dim_x
    """
    sx, sy = start
    _, ey = end
    # Extension + dim line + tick marks
    msp.add_line((sx, sy), (dim_x + 0.05, sy),
                 dxfattribs={"layer": "DIMENSIONS"})
    msp.add_line((sx, ey), (dim_x + 0.05, ey),
                 dxfattribs={"layer": "DIMENSIONS"})
    msp.add_line((dim_x, sy), (dim_x, ey),
                 dxfattribs={"layer": "DIMENSIONS"})
    for y in (sy, ey):
        msp.add_line((dim_x - 0.04, y - 0.04), (dim_x + 0.04, y + 0.04),
                     dxfattribs={"layer": "DIMENSIONS"})
    # Stacked label
    n = len(label_lines)
    if n == 0:
        return
    block_h = n * line_h
    y_top = (sy + ey) / 2 + block_h / 2
    label_x = dim_x - 0.10 if side == "left" else dim_x + 0.10
    align = (TextEntityAlignment.MIDDLE_RIGHT if side == "left"
             else TextEntityAlignment.MIDDLE_LEFT)
    for i, ln in enumerate(label_lines):
        t = msp.add_text(
            ln,
            dxfattribs={"layer": "DIMENSIONS",
                        "height": TEXT_SMALL * 0.8,
                        "style": "Standard"},
        )
        t.set_placement((label_x, y_top - (i + 0.5) * line_h),
                        align=align)


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

    # Bottom row: plan view (left) + side elevation (center+). The side
    # view carries the most installer-actionable dim chain on the
    # drawing (req headroom, door height, underside of track, backroom)
    # so we give it a larger horizontal allocation than the plan view.
    plan_x1 = DRAW_X0 + TOP_W * 0.30
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
        # Spring count comes from the door spring calculator (the same
        # engine that picks BC spring SKUs for the quote). This way the
        # drawing matches the actual hardware ordered. Falls back to 2
        # if the calculator can't produce a result.
        spring_count=_spring_count_from_calculator(door),
        operator=str(door.get("operator") or "NONE"),
        operator_side=str(door.get("operatorSide") or "right").lower(),
        has_struts=bool(hardware.get("struts", True)),
        has_weather_stripping=bool(hardware.get("weatherStripping", True)),
        has_bottom_retainer=bool(hardware.get("bottomRetainer", True)),
        has_windows=bool(door.get("hasWindows", False)),
        window_positions=door.get("windowPositions") or [],
        window_insert=str(door.get("windowInsert") or "NONE"),
        window_size=str(door.get("windowSize") or "long"),
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
