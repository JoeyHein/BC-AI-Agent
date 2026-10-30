"""Shop drawing entry point.

The sheet itself is drawn by ``sheet.draw_sheet`` from a ``DoorDrawingSpec``.
This module keeps the public API the portal and the existing tests call:
context building, DXF/PDF bytes, and the imperial formatters.
"""

from __future__ import annotations

import io
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import ezdxf

from app.services.shop_drawings.sheet import draw_sheet
from app.services.shop_drawings.spec import DoorDrawingSpec, build_door_spec, build_spec_from_config

logger = logging.getLogger(__name__)

# ANSI B landscape. Constants stay in this module because tests pin them.
SHEET_W = 17.0
SHEET_H = 11.0
MARGIN_L = 0.5
MARGIN_R = 0.5
MARGIN_T = 0.5
MARGIN_B = 0.5
TITLE_BLOCK_W = 5.5
TITLE_BLOCK_H = 3.2

LAYERS = [
    ("BORDER", 250, 50, "CONTINUOUS"),
    ("TITLE_BLOCK", 250, 35, "CONTINUOUS"),
    ("FRAMING", 250, 35, "CONTINUOUS"),
    ("HORIZONTALS", 250, 18, "CONTINUOUS"),
    ("TRACKS", 250, 30, "CONTINUOUS"),
    ("STRUTS", 250, 25, "CONTINUOUS"),
    ("HARDWARE", 250, 25, "CONTINUOUS"),
    ("DIMENSIONS", 250, 18, "CONTINUOUS"),
    ("ANNOTATIONS", 250, 18, "CONTINUOUS"),
    ("HIDDEN", 8, 18, "HIDDEN"),
    ("CENTERLINE", 250, 18, "CENTER"),
    ("SOLID_FILL", 250, 25, "CONTINUOUS"),
    ("GLAZING", 4, 18, "CONTINUOUS"),
    ("HATCH", 8, 13, "CONTINUOUS"),
]

TEXT_LARGE = 0.20
TEXT_MED = 0.12
TEXT_SMALL = 0.08

MM_PER_INCH = 25.4

_NOTO = {
    "regular": "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
    "bold": "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
    "italic": "/usr/share/fonts/truetype/noto/NotoSans-Italic.ttf",
}


@dataclass
class DrawingContext:
    """Inputs for a framing drawing, pulled from a saved quote door."""
    job_number: str
    customer_name: str
    door_series: str
    door_type: str
    door_width_in: float
    door_height_in: float
    door_count: int
    drawing_date: str
    designer: str = ""
    sheet_label: str = "1 OF 1"
    scale_label: str = "NTS"
    config_id: Optional[int] = None
    panel_design: str = "SHXL"
    panel_color: str = "WHITE"
    lift_type: str = "standard"
    high_lift_inches: Optional[float] = None
    lhr_mount: str = "front"
    track_radius_in: float = 15.0
    track_thickness_ga: str = "14"
    track_mount: str = "bracket"
    jamb_type: str = "wood"
    insulated: bool = True
    section_height_in: float = 21.0
    target_cycles: int = 10000
    shaft_type: str = "auto"
    shaft_flags: frozenset = frozenset()
    spring_count: int = 2
    operator: str = "NONE"
    operator_side: str = "right"
    has_struts: bool = True
    has_weather_stripping: bool = True
    has_bottom_retainer: bool = True
    has_windows: bool = False
    window_positions: Optional[list] = None
    window_insert: str = ""
    window_size: str = "long"
    glass_pockets_per_section: Optional[dict] = None
    al_pocket_count: Optional[int] = None
    man_door: bool = False
    man_door_spec: str = ""
    interior_lock: bool = False
    pusher_spring: bool = False
    bumper_spring: bool = False
    track_guards: bool = False
    exhaust_port: bool = False
    # Title-block identity. DRAWN BY is the staff user, never the customer.
    drawn_by: str = ""
    drawing_number: str = ""
    revision: Optional[int] = None
    project_name: str = ""
    architect: str = ""


def _new_drawing() -> ezdxf.document.Drawing:
    doc = ezdxf.new(dxfversion="R2013", setup=True)
    doc.header["$INSUNITS"] = 1
    doc.header["$MEASUREMENT"] = 0

    std = doc.styles.get("Standard")
    std.dxf.font = "LiberationSans-Regular.ttf"
    for name, font in (("BOLD", "LiberationSans-Bold.ttf"), ("ITALIC", "LiberationSans-Italic.ttf")):
        if name in doc.styles:
            style = doc.styles.get(name)
        else:
            style = doc.styles.new(name)
        style.dxf.font = font

    for name, color, lw, linetype in LAYERS:
        layer = doc.layers.add(name) if name not in doc.layers else doc.layers.get(name)
        layer.color = color
        layer.dxf.lineweight = lw
        layer.dxf.linetype = linetype

    zero = doc.layers.get("0")
    zero.color = 7
    zero.dxf.lineweight = 25
    return doc


def fmt_length_imperial(inches: float) -> str:
    """Format inches as feet-inches: 192 → 16'-0\"."""
    feet = int(inches // 12)
    rem = round(inches - feet * 12, 2)
    if rem == int(rem):
        rem_str = str(int(rem))
    else:
        rem_str = f"{rem:g}"
    return f"{feet}'-{rem_str}\""


def fmt_length_dual(inches: float, mm_precision: int = 0) -> str:
    """Format a length in imperial and metric: 16'-0\" [4877mm]."""
    mm = inches * MM_PER_INCH
    mm_str = f"{mm:.{mm_precision}f}".rstrip("0").rstrip(".")
    if not mm_str:
        mm_str = "0"
    return f"{fmt_length_imperial(inches)} [{mm_str}mm]"


def _fmt_size(w_in: float, h_in: float, count: int) -> str:
    qty = f"({count}) " if count and count > 1 else ""
    return f"{qty}{fmt_length_imperial(w_in)} x {fmt_length_imperial(h_in)}"


def _drawing_operator(door: dict) -> str:
    operator = str(door.get("operator") or "NONE").strip()
    if operator.upper() in ("", "NONE"):
        hoist = str(door.get("chainHoist") or "none").strip().lower()
        if hoist in ("shaft", "wall"):
            return "CHAIN_HOIST"
    return operator or "NONE"


def _jamb_from_door(door: dict, door_type: str) -> str:
    surface = str(door.get("mountSurface") or door.get("jambType") or "").lower()
    if surface in ("steel", "concrete", "masonry"):
        return "steel"
    if surface == "wood":
        return "wood"
    return "steel" if door_type == "commercial" else "wood"


def build_context_from_config(
    config_data: dict,
    customer_name: str,
    job_number: str,
    drawing_date: Optional[datetime] = None,
    config_id: Optional[int] = None,
    door_index: int = 0,
) -> DrawingContext:
    """Extract drawing inputs from a saved-quote config.

    Kept so existing callers and tests can still build a context. The sheet
    is driven by :func:`build_spec_from_config`, which re-reads the door and
    fills sections, springs, and clearances from the calculators.
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
        lhr_mount=str(door.get("lhrMount") or "front"),
        track_radius_in=float(door.get("trackRadius") or 15),
        track_thickness_ga=str(door.get("trackThickness") or "2"),
        track_mount=str(door.get("trackMount") or "bracket"),
        jamb_type=_jamb_from_door(door, door_type),
        target_cycles=int(door.get("targetCycles") or 10000),
        shaft_type=str(door.get("shaftType") or "auto"),
        operator=_drawing_operator(door),
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
        project_name=str((config_data or {}).get("projectName") or ""),
        architect=str((config_data or {}).get("architect") or ""),
    )


def spec_from_context(ctx: DrawingContext) -> DoorDrawingSpec:
    """Rebuild a full spec from a DrawingContext (tests and older callers)."""
    door = {
        "doorSeries": ctx.door_series,
        "doorType": ctx.door_type,
        "doorWidth": ctx.door_width_in,
        "doorHeight": ctx.door_height_in,
        "doorCount": ctx.door_count,
        "panelDesign": ctx.panel_design,
        "panelColor": ctx.panel_color,
        "liftType": ctx.lift_type,
        "highLiftInches": ctx.high_lift_inches,
        "lhrMount": ctx.lhr_mount,
        "trackRadius": ctx.track_radius_in,
        "trackThickness": ctx.track_thickness_ga,
        "trackMount": ctx.track_mount,
        "mountSurface": ctx.jamb_type,
        "targetCycles": ctx.target_cycles,
        "shaftType": ctx.shaft_type,
        "operator": ctx.operator,
        "hasWindows": ctx.has_windows,
        "windowInsert": ctx.window_insert,
        "windowSize": ctx.window_size,
        "windowPositions": ctx.window_positions,
        "manDoor": ctx.man_door,
        "interiorLock": ctx.interior_lock,
        "pusherSpring": ctx.pusher_spring,
        "bumperSpring": ctx.bumper_spring,
        "trackGuards": ctx.track_guards,
        "exhaustPort": ctx.exhaust_port,
        "hardware": {"weatherStripping": ctx.has_weather_stripping},
    }
    return build_door_spec(
        door,
        customer_name=ctx.customer_name,
        job_number=ctx.job_number,
        drawn_by=ctx.drawn_by or ctx.designer,
        drawing_number=ctx.drawing_number,
        revision=ctx.revision,
        drawing_date=ctx.drawing_date,
        project_name=ctx.project_name,
        architect=ctx.architect,
    )


def build_dxf(ctx: DrawingContext) -> ezdxf.document.Drawing:
    doc = _new_drawing()
    draw_sheet(doc, spec_from_context(ctx))
    return doc


def _figure(doc: ezdxf.document.Drawing, dpi: int):
    """Render geometry as vectors and TEXT entities as real font text."""
    import matplotlib
    matplotlib.use("Agg")
    matplotlib.rcParams["pdf.fonttype"] = 42
    matplotlib.rcParams["ps.fonttype"] = 42
    from matplotlib import font_manager
    from matplotlib import pyplot as plt
    from ezdxf.addons.drawing import RenderContext, Frontend
    from ezdxf.addons.drawing.config import Configuration, TextPolicy
    from ezdxf.addons.drawing.matplotlib import MatplotlibBackend

    for path in _NOTO.values():
        try:
            font_manager.fontManager.addfont(path)
        except (OSError, ValueError):
            pass

    fig = plt.figure(figsize=(SHEET_W, SHEET_H), dpi=dpi)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_aspect("equal")
    ax.axis("off")
    backend = MatplotlibBackend(ax)
    config = Configuration(text_policy=TextPolicy.IGNORE)
    Frontend(RenderContext(doc), backend, config).draw_layout(doc.modelspace(), finalize=False)
    _overlay_text(ax, doc)
    ax.set_xlim(0, SHEET_W)
    ax.set_ylim(0, SHEET_H)
    ax.set_axis_off()
    return fig


def _overlay_text(ax, doc: ezdxf.document.Drawing) -> None:
    for entity in doc.modelspace().query("TEXT"):
        value = entity.dxf.text
        if not value:
            continue
        halign = int(entity.dxf.halign or 0)
        valign = int(entity.dxf.valign or 0)
        point = entity.dxf.align_point if (halign or valign) else entity.dxf.insert
        ha = {0: "left", 1: "center", 2: "right", 3: "center", 4: "center", 5: "center"}.get(halign, "left")
        va = {0: "baseline", 1: "bottom", 2: "center", 3: "top"}.get(valign, "baseline")
        style = (entity.dxf.style or "Standard").upper()
        ax.text(
            point.x,
            point.y,
            value,
            fontsize=float(entity.dxf.height) * 72.0,
            ha=ha,
            va=va,
            rotation=float(entity.dxf.rotation or 0),
            color="black",
            fontname="Noto Sans",
            fontweight="bold" if style == "BOLD" else "regular",
            fontstyle="italic" if style == "ITALIC" else "normal",
            clip_on=False,
        )


def dxf_to_pdf_bytes(doc: ezdxf.document.Drawing) -> bytes:
    import matplotlib
    matplotlib.use("Agg")
    from matplotlib import pyplot as plt
    from matplotlib.backends.backend_pdf import PdfPages

    fig = _figure(doc, dpi=120)
    buf = io.BytesIO()
    with PdfPages(buf) as pdf:
        pdf.savefig(fig, bbox_inches=None, pad_inches=0)
    plt.close(fig)
    return buf.getvalue()


def dxf_to_png_bytes(doc: ezdxf.document.Drawing, dpi: int = 110) -> bytes:
    import matplotlib
    matplotlib.use("Agg")
    from matplotlib import pyplot as plt

    fig = _figure(doc, dpi=dpi)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=dpi)
    plt.close(fig)
    return buf.getvalue()


def dxf_to_string(doc: ezdxf.document.Drawing) -> bytes:
    buf = io.StringIO()
    doc.write(buf)
    return buf.getvalue().encode("utf-8")


def generate_framing_drawing(
    config_data: dict,
    customer_name: str,
    job_number: str,
    fmt: str = "pdf",
    drawing_date: Optional[datetime] = None,
    config_id: Optional[int] = None,
    door_index: int = 0,
    drawn_by: str = "",
    drawing_number: str = "",
    revision: Optional[int] = None,
    project_name: str = "",
    architect: str = "",
) -> bytes:
    """Config → PDF or DXF bytes.

    Sections, springs, drum, shaft, and clearances come from the calculators
    inside :func:`build_spec_from_config`, not from whatever the browser
    happened to send.
    """
    spec = build_spec_from_config(
        config_data or {},
        customer_name=customer_name,
        job_number=job_number or (f"Q-{config_id}" if config_id else ""),
        drawn_by=drawn_by,
        drawing_number=drawing_number,
        revision=revision,
        drawing_date=drawing_date,
        project_name=project_name,
        architect=architect,
        door_index=door_index,
    )
    doc = _new_drawing()
    draw_sheet(doc, spec)
    if fmt == "dxf":
        return dxf_to_string(doc)
    if fmt == "pdf":
        return dxf_to_pdf_bytes(doc)
    if fmt == "png":
        return dxf_to_png_bytes(doc)
    raise ValueError(f"Unsupported format: {fmt}")
