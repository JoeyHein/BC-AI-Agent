"""Framing drawing generator (Stage 1).

Creates an ANSI B (17"x11" landscape) sheet in DXF with a proper title block,
border, and empty viewport. Exports to PDF via ezdxf's matplotlib backend.

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
SHEET_W = 17.0
SHEET_H = 11.0
MARGIN_L = 0.75     # binding edge
MARGIN_R = 0.5
MARGIN_T = 0.5
MARGIN_B = 0.5

# Title block: lower-right corner, 5.5" wide × 2.5" tall
TITLE_BLOCK_W = 5.5
TITLE_BLOCK_H = 2.5

# ─── Layer definitions (name, ACI color, lineweight in 1/100 mm) ────────────
# ezdxf lineweight: -3=default, 0..211 = 1/100mm (e.g. 50 = 0.5mm)
LAYERS = [
    # name,          color, lineweight, linetype
    ("BORDER",          7,  50, "CONTINUOUS"),  # black/white, 0.5mm
    ("TITLE_BLOCK",     7,  35, "CONTINUOUS"),  # 0.35mm
    ("FRAMING",         1,  50, "CONTINUOUS"),  # red, 0.5mm
    ("TRACKS",          5,  35, "CONTINUOUS"),  # blue, 0.35mm
    ("STRUTS",          3,  35, "CONTINUOUS"),  # green, 0.35mm
    ("HARDWARE",        6,  35, "CONTINUOUS"),  # magenta, 0.35mm
    ("DIMENSIONS",      2,  18, "CONTINUOUS"),  # yellow, 0.18mm
    ("ANNOTATIONS",     7,  25, "CONTINUOUS"),  # black/white, 0.25mm
    ("HIDDEN",          8,  25, "HIDDEN"),      # grey, 0.25mm, hidden linetype
    ("CENTERLINE",      4,  18, "CENTER"),      # cyan, 0.18mm
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
    scale_label: str = "NTS"      # Stage 1: no geometry yet, so "Not To Scale"
    config_id: Optional[int] = None


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
    """Title block in lower-right corner.

    Layout (5.5"w x 2.5"h), divided into rows:
      Row 1 (top, 0.5"):   Company banner "OPEN DISTRIBUTION COMPANY"
      Row 2 (0.6"):        Drawing title "FRAMING DRAWING"
      Row 3 (0.5"):        Customer | Date
      Row 4 (0.4"):        Job#     | Series
      Row 5 (0.5"):        Size     | Scale | Sheet
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

    # Row dividers (top → bottom: 0.5, 0.6, 0.5, 0.4, 0.5)
    row_heights = [0.5, 0.6, 0.5, 0.4, 0.5]
    row_ys = [y1]
    for h in row_heights:
        row_ys.append(row_ys[-1] - h)
    for ry in row_ys[1:-1]:
        msp.add_line(
            (x0, ry), (x1, ry),
            dxfattribs={"layer": "TITLE_BLOCK"},
        )

    # Column divider in rows 3, 4, 5 at midpoint
    x_mid = x0 + TITLE_BLOCK_W / 2
    for i in (2, 3, 4):  # rows 3, 4, 5 (0-indexed)
        msp.add_line(
            (x_mid, row_ys[i]), (x_mid, row_ys[i + 1]),
            dxfattribs={"layer": "TITLE_BLOCK"},
        )

    # Row 5 has an extra divider separating Scale and Sheet
    x_q3 = x_mid + (TITLE_BLOCK_W / 2) * 0.6
    msp.add_line(
        (x_q3, row_ys[4]), (x_q3, row_ys[5]),
        dxfattribs={"layer": "TITLE_BLOCK"},
    )

    def _text(s: str, xy: Tuple[float, float], h: float, *, bold: bool = False) -> None:
        t = msp.add_text(
            s,
            dxfattribs={
                "layer": "TITLE_BLOCK",
                "height": h,
                "style": "Standard",
            },
        )
        t.set_placement(xy, align=TextEntityAlignment.MIDDLE_LEFT)

    # Banner row 1 — company, centered
    banner = msp.add_text(
        "OPEN DISTRIBUTION COMPANY",
        dxfattribs={"layer": "TITLE_BLOCK", "height": TEXT_LARGE, "style": "Standard"},
    )
    banner.set_placement(
        ((x0 + x1) / 2, (row_ys[0] + row_ys[1]) / 2),
        align=TextEntityAlignment.MIDDLE_CENTER,
    )

    # Row 2 — drawing title
    title = msp.add_text(
        "FRAMING DRAWING",
        dxfattribs={"layer": "TITLE_BLOCK", "height": TEXT_LARGE, "style": "Standard"},
    )
    title.set_placement(
        ((x0 + x1) / 2, (row_ys[1] + row_ys[2]) / 2),
        align=TextEntityAlignment.MIDDLE_CENTER,
    )

    # Row 3 — Customer | Date
    _field(msp, x0 + 0.1, row_ys[2], "CUSTOMER", ctx.customer_name, cell_w=TITLE_BLOCK_W / 2 - 0.1, cell_h=row_heights[2])
    _field(msp, x_mid + 0.1, row_ys[2], "DATE", ctx.drawing_date, cell_w=TITLE_BLOCK_W / 2 - 0.1, cell_h=row_heights[2])

    # Row 4 — Job# | Series
    _field(msp, x0 + 0.1, row_ys[3], "JOB #", ctx.job_number, cell_w=TITLE_BLOCK_W / 2 - 0.1, cell_h=row_heights[3])
    _field(msp, x_mid + 0.1, row_ys[3], "SERIES", ctx.door_series, cell_w=TITLE_BLOCK_W / 2 - 0.1, cell_h=row_heights[3])

    # Row 5 — Size | Scale | Sheet
    size_txt = _fmt_size(ctx.door_width_in, ctx.door_height_in, ctx.door_count)
    _field(msp, x0 + 0.1, row_ys[4], "SIZE (W x H)", size_txt, cell_w=TITLE_BLOCK_W / 2 - 0.1, cell_h=row_heights[4])
    _field(msp, x_mid + 0.1, row_ys[4], "SCALE", ctx.scale_label, cell_w=(x_q3 - x_mid) - 0.1, cell_h=row_heights[4])
    _field(msp, x_q3 + 0.1, row_ys[4], "SHEET", ctx.sheet_label, cell_w=(x1 - x_q3) - 0.1, cell_h=row_heights[4])


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
    """Format "(2) 16'0\" x 8'0\"" style size label."""
    def _ft_in(x: float) -> str:
        feet = int(x // 12)
        inches = round(x - feet * 12, 2)
        if inches == int(inches):
            inches_str = str(int(inches))
        else:
            inches_str = str(inches)
        return f"{feet}'-{inches_str}\""
    qty = f"({count}) " if count and count > 1 else ""
    return f"{qty}{_ft_in(w_in)} x {_ft_in(h_in)}"


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


def _draw_stage1_placeholder(msp: Modelspace) -> None:
    """Placeholder rectangle where the door elevation will go in Stage 2.

    Dashed outline so it's obvious this is a TODO, not the actual drawing.
    """
    # Drawing area: everything inside inner border EXCEPT the title block
    x0 = MARGIN_L + 0.25
    y0 = MARGIN_B + TITLE_BLOCK_H + 0.25
    x1 = SHEET_W - MARGIN_R - 0.25
    y1 = SHEET_H - MARGIN_T - 0.25

    msp.add_lwpolyline(
        [(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)],
        close=True,
        dxfattribs={"layer": "HIDDEN", "linetype": "HIDDEN"},
    )

    note = msp.add_text(
        "DRAWING AREA — GEOMETRY RENDERED IN STAGE 2",
        dxfattribs={"layer": "ANNOTATIONS", "height": TEXT_MED, "style": "Standard"},
    )
    note.set_placement(((x0 + x1) / 2, (y0 + y1) / 2), align=TextEntityAlignment.MIDDLE_CENTER)


# ─── Public entry point ────────────────────────────────────────────────────

def build_dxf(ctx: DrawingContext) -> ezdxf.document.Drawing:
    """Build and return the DXF document. Caller can save it or export to PDF."""
    doc = _new_drawing()
    msp = doc.modelspace()
    _draw_sheet_border(msp)
    _draw_title_block(msp, ctx)
    _draw_stage1_placeholder(msp)
    return doc


def dxf_to_pdf_bytes(doc: ezdxf.document.Drawing) -> bytes:
    """Render the DXF to a PDF using ezdxf's matplotlib backend."""
    # Lazy import to keep module load cheap if only DXF is requested
    import matplotlib
    matplotlib.use("Agg")  # headless — no Tk/GTK required
    from matplotlib import pyplot as plt
    from matplotlib.backends.backend_pdf import PdfPages
    from ezdxf.addons.drawing import RenderContext, Frontend
    from ezdxf.addons.drawing.matplotlib import MatplotlibBackend

    fig = plt.figure(figsize=(SHEET_W, SHEET_H), dpi=300)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, SHEET_W)
    ax.set_ylim(0, SHEET_H)
    ax.set_aspect("equal")
    ax.axis("off")

    ctx_render = RenderContext(doc)
    backend = MatplotlibBackend(ax)
    Frontend(ctx_render, backend).draw_layout(doc.modelspace(), finalize=True)

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

    return DrawingContext(
        job_number=job_number or f"Q-{config_id}" if config_id else "UNASSIGNED",
        customer_name=customer_name or "—",
        door_series=door.get("doorSeries", "—"),
        door_type=door.get("doorType", "residential"),
        door_width_in=float(door.get("doorWidth") or 0),
        door_height_in=float(door.get("doorHeight") or 0),
        door_count=int(door.get("doorCount") or 1),
        drawing_date=date_str,
        config_id=config_id,
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
