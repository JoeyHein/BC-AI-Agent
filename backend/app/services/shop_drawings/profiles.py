"""Panel, joint, and jamb geometry.

The shapes below are parametric stand-ins measured off Joey's sample sheets
(see the spec, §4). A DXF dropped into ``profiles/`` replaces that geometry
entirely — see ``DROP_IN.txt`` for the insertion contract. Leaders and the
sheet layout stay in ``sheet.py`` either way.

Coordinates are real inches. Exterior is x = 0, interior is x = thickness,
+y is up.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional, Sequence

import ezdxf
from ezdxf.document import Drawing
from ezdxf.layouts import Modelspace

logger = logging.getLogger(__name__)

PROFILES_DIR = Path(__file__).resolve().parent / "profiles"

# kind → filename. Present file wins over the parametric builder.
PROFILE_FILES = {
    "shiplap": "tx380_shiplap.dxf",
    "tongue_groove": "tx_tongue_and_groove.dxf",
    "panorama": "panorama_section.dxf",
    "jamb_steel": "jamb_steel.dxf",
    "jamb_wood": "jamb_wood.dxf",
}


def profile_dxf_path(kind: str) -> Optional[Path]:
    name = PROFILE_FILES.get(kind)
    if not name:
        return None
    path = PROFILES_DIR / name
    return path if path.is_file() else None


def import_profile_block(doc: Drawing, kind: str) -> Optional[str]:
    """Import a drop-in DXF as a block. Returns the block name, or None."""
    path = profile_dxf_path(kind)
    if path is None:
        return None
    block_name = f"PROFILE_{kind.upper()}"
    if block_name in doc.blocks:
        return block_name
    try:
        source = ezdxf.readfile(str(path))
    except Exception as exc:
        logger.warning("Could not read profile DXF %s: %s", path, exc)
        return None
    try:
        from ezdxf.addons import Importer
        block = doc.blocks.new(block_name)
        importer = Importer(source, doc)
        # Modelspace entities land in the block. Sheet code scales the insert.
        importer.import_modelspace(block)
        importer.finalize()
    except Exception as exc:
        logger.warning("Could not import profile %s: %s", path.name, exc)
        return None
    return block_name


# ─── tongue and groove (TX-450 / TX-500) ────────────────────────────────────
# Fractions of T measured on the TX-450 joint crop. The tongue is centred,
# not a lap. Thermal-break bars sit just behind each exterior skin return
# so the inside and outside skins never touch.

def tongue_profile(T: float) -> list[tuple[float, float]]:
    """Top edge of the lower section, exterior → interior. y = 0 is the land."""
    r = 0.06 * T
    rise = 0.13 * T
    return [
        (0.0, -0.02 * T),
        (r, 0.0),
        (0.32 * T, 0.0),
        (0.32 * T, rise),
        (0.67 * T, rise),
        (0.75 * T, 0.0),
        (T - r, 0.0),
        (T, -0.02 * T),
    ]


def groove_profile(T: float) -> list[tuple[float, float]]:
    """Bottom edge of the upper section. Mirror of the tongue, opening down,
    with a hairline clearance so the noses do not fuse.
    """
    gap = 0.015 * T
    return [(x, -(y + gap)) for x, y in tongue_profile(T)]


def thermal_break_lower(T: float) -> tuple[float, float, float, float]:
    """Black bar in the lower section, x0,y0,x1,y1. y0 is the land."""
    return (0.30 * T, -0.20 * T, 0.34 * T, 0.0)


def thermal_break_upper(T: float) -> tuple[float, float, float, float]:
    """Black bar in the upper section, above the groove, into that section's foam."""
    return (0.30 * T, 0.04 * T, 0.34 * T, 0.24 * T)


def seal_pocket(T: float) -> tuple[float, float, float, float]:
    """Keyhole pocket in the groove, above the tongue. x0,y0,x1,y1."""
    return (0.42 * T, -0.20 * T, 0.58 * T, -0.05 * T)


def hinge_reinforcing(T: float, *, upper: bool) -> tuple[float, float, float, float]:
    """Short bar on the inside face of the interior skin."""
    x0 = T - 0.045 * T
    x1 = T + 0.01 * T
    if upper:
        return (x0, -0.28 * T, x1, -0.08 * T)
    return (x0, 0.04 * T, x1, 0.24 * T)


# ─── shiplap (TX-380) ───────────────────────────────────────────────────────
# An offset lap, not a centred tongue. The exterior skin of the lower
# section ships up over the upper section. Thermal breaks sit at both the
# exterior return and the step, so the two skins still never meet.

def shiplap_lower(T: float) -> list[tuple[float, float]]:
    """Top edge of the lower section. The high lap is on the exterior."""
    lap = 0.20 * T
    return [
        (0.0, lap),
        (0.46 * T, lap),
        (0.46 * T, 0.0),
        (T, 0.0),
    ]


def shiplap_upper(T: float) -> list[tuple[float, float]]:
    """Bottom edge of the upper section, the receiving rabbet."""
    gap = 0.02 * T
    lap = 0.20 * T
    return [
        (0.0, lap + gap),
        (0.46 * T - gap, lap + gap),
        (0.46 * T - gap, gap),
        (T, gap),
    ]


def shiplap_breaks(T: float) -> list[tuple[float, float, float, float]]:
    """Two bars per section edge: exterior return and the lap step."""
    lap = 0.20 * T
    depth = 0.18 * T
    w = 0.04 * T
    return [
        # lower, exterior return, down into the foam
        (0.08 * T, -depth, 0.08 * T + w, 0.0),
        # lower, at the step, down into the foam
        (0.46 * T, -depth, 0.46 * T + w, 0.0),
        # upper, exterior return, up into the foam
        (0.08 * T, lap, 0.08 * T + w, lap + depth),
        # upper, at the step, up into the foam
        (0.42 * T, lap, 0.42 * T + w, lap + depth),
    ]


def joint_high_point(points: Sequence[tuple[float, float]]) -> tuple[float, float]:
    """The (x, y) where the lower-section profile is highest. Tests use this
    to tell a centred tongue from an exterior shiplap.
    """
    return max(points, key=lambda p: (p[1], -p[0]))


# ─── shared stack heights (real inches, before the view scales them) ───────

def steel_stack_height(T: float) -> float:
    """Nominal real height of the abbreviated section stack."""
    return 0.55 * T + 1.15 + 0.85 + 1.05 + 0.70 * T


def draw_parametric_steel(msp: Modelspace, spec, origin, scale: float) -> None:
    """Draw the TX section stack at ``origin`` (exterior, bottom), +y up."""
    from app.services.shop_drawings.sheet_geom import Pen

    pen = Pen(msp, origin[0], origin[1], scale, "FRAMING")
    T = spec.thickness_in
    shiplap = spec.joint == "shiplap"
    # Bottom of the astragal is y = 0. Build upward.
    y = 0.55 * T  # astragal hangs below the retainer
    _draw_astragal(pen, T, y)
    y = _draw_retainer(pen, T, y, shiplap)
    body_b = 1.05
    _draw_section_body(pen, T, y, body_b, spec, bottom=True, shiplap=shiplap)
    y += body_b
    _draw_joint(pen, T, y, shiplap, hinge=True)
    y += 0.22 * T
    _draw_break(pen, T, y + 0.15)
    mid = 0.85
    y += 0.30
    _draw_section_body(pen, T, y, mid, spec, bottom=False, shiplap=shiplap)
    y += mid
    _draw_joint(pen, T, y, shiplap, hinge=True)
    y += 0.22 * T
    _draw_break(pen, T, y + 0.12)
    top_body = 0.70
    y += 0.24
    _draw_section_body(pen, T, y, top_body, spec, bottom=False, shiplap=shiplap, top_tongue=True)
    y += top_body
    _draw_top_cap(pen, T, y, spec.top_seal)


def draw_parametric_panorama(msp: Modelspace, spec, origin, scale: float) -> None:
    from app.services.shop_drawings.sheet_geom import Pen

    pen = Pen(msp, origin[0], origin[1], scale, "FRAMING")
    T = spec.thickness_in
    rail_h = 0.85
    glass_h = 1.15
    y = 0.0
    _draw_pano_astragal(pen, T, y + 0.15)
    y = 0.45
    _draw_pano_rail(pen, T, y, rail_h, kind="bottom")
    y += rail_h
    _draw_pano_glass(pen, T, y, glass_h)
    y += glass_h
    _draw_pano_meeting(pen, T, y)
    y += 0.55
    _draw_break(pen, T, y)
    y += 0.25
    _draw_pano_rail(pen, T, y, 0.45, kind="mid")
    y += 0.45
    _draw_pano_glass(pen, T, y, 0.9)
    y += 0.9
    _draw_pano_rail(pen, T, y, rail_h, kind="top")
    _draw_pano_top_seal(pen, T, y + rail_h)


# ─── steel pieces ───────────────────────────────────────────────────────────

def _section_outline(T, y0, y1, shiplap, *, top_tongue=False, bottom=False):
    """Closed outline of one abbreviated section between y0 and y1.

    The joint profiles replace the plain top/bottom when the caller draws
    the joint separately, so this outline is the skin box only. Joints are
    overlaid at the ends.
    """
    return [
        (0, y0), (T, y0), (T, y1), (0, y1),
    ]


def _draw_section_body(pen, T, y0, h, spec, *, bottom, shiplap, top_tongue=False):
    y1 = y0 + h
    # Foam
    pen.dots(0.08 * T, y0 + 0.08, T - 0.08 * T, y1 - 0.08, 0.12, layer="HATCH")
    # Skins — double line
    pen.line(0, y0, 0, y1, layer="FRAMING")
    pen.line(0.025 * T, y0, 0.025 * T, y1, layer="FRAMING")
    pen.line(T, y0, T, y1, layer="FRAMING")
    pen.line(T - 0.025 * T, y0, T - 0.025 * T, y1, layer="FRAMING")
    # Exterior V ribs
    rib_y = y0 + 0.22
    while rib_y < y1 - 0.15:
        pen.line(0, rib_y, 0.07 * T, rib_y - 0.04, layer="HORIZONTALS")
        pen.line(0.07 * T, rib_y - 0.04, 0.14 * T, rib_y, layer="HORIZONTALS")
        rib_y += 0.28
    # Interior shallow notch
    mid = (y0 + y1) / 2
    pen.line(T, mid - 0.04, T - 0.06 * T, mid, layer="HORIZONTALS")
    pen.line(T - 0.06 * T, mid, T, mid + 0.04, layer="HORIZONTALS")
    # Top / bottom closure if this is a free end (joint draws the other)
    if bottom:
        pen.poly(_end_profile(T, y0, shiplap, top=False), layer="FRAMING")
    if top_tongue:
        pen.poly(_end_profile(T, y1, shiplap, top=True), layer="FRAMING")


def _end_profile(T, y, shiplap, *, top: bool):
    if shiplap:
        pts = shiplap_lower(T) if top else [(x, -yy) for x, yy in shiplap_upper(T)]
    else:
        pts = tongue_profile(T) if top else [(x, -yy) for x, yy in groove_profile(T)]
    if top:
        return [(x, y + yy) for x, yy in pts]
    # bottom edge: the profile y is already negative-ish relative to the edge
    return [(x, y + yy) for x, yy in pts]


def _draw_joint(pen, T, y, shiplap, *, hinge: bool):
    """Joint centred so the mating line is about ``y``. ``y`` is the lower land."""
    if shiplap:
        lower = [(x, y + yy) for x, yy in shiplap_lower(T)]
        upper = [(x, y + yy) for x, yy in shiplap_upper(T)]
        pen.poly(lower, layer="FRAMING")
        pen.poly(upper, layer="FRAMING")
        for box in shiplap_breaks(T):
            pen.filled_rect(box[0], y + box[1], box[2], y + box[3], layer="SOLID_FILL")
        # Seal bulb in the lap pocket
        pen.circle(0.30 * T, y + 0.10 * T, 0.035 * T, layer="HARDWARE")
    else:
        lower = [(x, y + yy) for x, yy in tongue_profile(T)]
        upper = [(x, y + yy) for x, yy in groove_profile(T)]
        pen.poly(lower, layer="FRAMING")
        pen.poly(upper, layer="FRAMING")
        x0, y0, x1, y1 = thermal_break_lower(T)
        pen.filled_rect(x0, y + y0, x1, y + y1, layer="SOLID_FILL")
        x0, y0, x1, y1 = thermal_break_upper(T)
        pen.filled_rect(x0, y + y0, x1, y + y1, layer="SOLID_FILL")
        # Christmas-tree seal in the groove pocket
        sx0, sy0, sx1, sy1 = seal_pocket(T)
        pen.poly(
            [
                (sx0, y + sy1),
                ((sx0 + sx1) / 2, y + sy0),
                (sx1, y + sy1),
                ((sx0 + sx1) / 2, y + (sy0 + sy1) / 2),
            ],
            close=True,
            layer="HARDWARE",
        )
        pen.filled_rect(sx0 + 0.02 * T, y + sy0, sx1 - 0.02 * T, y - 0.02 * T, layer="SOLID_FILL")
    # Hinge reinforcing on the interior skin
    for upper in (False, True):
        x0, y0, x1, y1 = hinge_reinforcing(T, upper=upper)
        pen.filled_rect(x0, y + y0, x1, y + y1, layer="SOLID_FILL")
    if hinge:
        _draw_hinge(pen, T, y)


def _draw_hinge(pen, T, y):
    # Leaves on the interior face
    pen.line(T, y + 0.02 * T, T + 0.28 * T, y + 0.02 * T, layer="HARDWARE")
    pen.line(T, y - 0.16 * T, T + 0.28 * T, y - 0.16 * T, layer="HARDWARE")
    # Knuckle
    pen.circle(T + 0.10 * T, y - 0.06 * T, 0.09 * T, layer="HARDWARE")
    # Two screws into each skin, pointing at the reinforcing
    for sy in (y + 0.12 * T, y - 0.22 * T):
        pen.line(T + 0.22 * T, sy, T - 0.02 * T, sy, layer="HARDWARE")
        pen.circle(T + 0.24 * T, sy, 0.035 * T, layer="HARDWARE")


def _draw_top_cap(pen, T, y, with_seal: bool):
    """Inverted-U retainer wrapping the top tongue, plus the optional flap."""
    cap_h = 0.28 * T
    pen.poly(
        [
            (-0.04 * T, y),
            (-0.04 * T, y + cap_h),
            (T + 0.04 * T, y + cap_h),
            (T + 0.04 * T, y),
        ],
        layer="HARDWARE",
    )
    # Hatch the cap
    pen.line(-0.04 * T, y + 0.05 * T, T + 0.04 * T, y + cap_h - 0.02 * T, layer="HATCH")
    pen.line(-0.04 * T, y + cap_h - 0.02 * T, T + 0.04 * T, y + 0.05 * T, layer="HATCH")
    if with_seal:
        # Flap angled up and out toward the header (exterior / -x)
        pen.poly(
            [
                (0.02 * T, y + cap_h),
                (-0.22 * T, y + cap_h + 0.35 * T),
                (-0.10 * T, y + cap_h + 0.38 * T),
                (0.08 * T, y + cap_h),
            ],
            close=True,
            layer="HARDWARE",
        )


def _draw_retainer(pen, T, y, shiplap) -> float:
    """PVC U retainer. ``y`` is the top of the astragal zone. Returns the
    y of the section bottom sitting in the retainer.
    """
    h = 0.22 * T
    pen.poly(
        [
            (-0.05 * T, y + h),
            (-0.05 * T, y),
            (T + 0.05 * T, y),
            (T + 0.05 * T, y + h),
        ],
        layer="HARDWARE",
    )
    return y + h


def _draw_astragal(pen, T, top_y):
    """U-bulb hanging below the retainer. ``top_y`` is the retainer bottom."""
    r = 0.28 * T
    cx = T / 2
    pen.arc(cx, top_y - r * 0.15, r, 200, 340, layer="HARDWARE")
    pen.line(cx - r * 0.7, top_y, cx - r * 0.3, top_y - r * 0.2, layer="HARDWARE")
    pen.line(cx + r * 0.7, top_y, cx + r * 0.3, top_y - r * 0.2, layer="HARDWARE")


def _draw_break(pen, T, y):
    z = [
        (-0.08 * T, y),
        (0.15 * T, y + 0.08),
        (0.35 * T, y - 0.08),
        (0.55 * T, y + 0.08),
        (0.75 * T, y - 0.08),
        (T + 0.08 * T, y),
    ]
    pen.poly(z, layer="HIDDEN")


# ─── panorama pieces ────────────────────────────────────────────────────────

def _draw_pano_rail(pen, T, y, h, *, kind: str):
    pen.rect(0, y, T, y + h, layer="FRAMING")
    # Internal web
    pen.line(0.35 * T, y, 0.35 * T, y + h, layer="FRAMING")
    pen.line(0.65 * T, y, 0.65 * T, y + h, layer="FRAMING")
    if kind == "top":
        # Keyhole for the top seal, exterior top corner
        pen.circle(0.12 * T, y + h - 0.12 * T, 0.06 * T, layer="FRAMING")
    if kind == "bottom":
        # Two downward T-slots
        pen.rect(0.18 * T, y - 0.08 * T, 0.32 * T, y + 0.12 * T, layer="FRAMING")
        pen.rect(0.68 * T, y - 0.08 * T, 0.82 * T, y + 0.12 * T, layer="FRAMING")
    # Glazing moulding clip on the interior, upper rails
    if kind in ("top", "mid"):
        pen.poly(
            [
                (T, y + h * 0.35),
                (T + 0.12 * T, y + h * 0.35),
                (T + 0.12 * T, y + h * 0.7),
                (T, y + h * 0.7),
            ],
            close=True,
            layer="HARDWARE",
        )


def _draw_pano_glass(pen, T, y, h):
    inset = 0.08 * T
    pen.rect(inset, y, T - inset, y + h, layer="GLAZING")
    pen.line(inset, y, T - inset, y + h, layer="HATCH")
    pen.line(T - inset, y, inset, y + h, layer="HATCH")


def _draw_pano_meeting(pen, T, y):
    """Peaked meeting rails with a weather-seal bulb."""
    peak = 0.28 * T
    # Lower rail: V pointing up
    pen.poly(
        [(0, y), (T / 2, y + peak), (T, y), (T, y + 0.35 * T), (0, y + 0.35 * T)],
        close=True,
        layer="FRAMING",
    )
    pen.line(0.35 * T, y, 0.35 * T, y + 0.35 * T, layer="FRAMING")
    pen.line(0.65 * T, y, 0.65 * T, y + 0.35 * T, layer="FRAMING")
    # Upper rail starts above, inverted V
    y2 = y + 0.40 * T
    pen.poly(
        [
            (0, y2 + 0.32 * T),
            (0, y2 + peak),
            (T / 2, y2),
            (T, y2 + peak),
            (T, y2 + 0.32 * T),
        ],
        close=True,
        layer="FRAMING",
    )
    # Bulb in the keyhole at the peak
    pen.circle(T / 2, y + peak + 0.02 * T, 0.06 * T, layer="HARDWARE")
    pen.circle(T / 2, y + peak + 0.10 * T, 0.045 * T, layer="HARDWARE")


def _draw_pano_astragal(pen, T, y):
    r = 0.22 * T
    pen.arc(T / 2, y, r, 200, 340, layer="HARDWARE")
    pen.line(0.22 * T, y + r * 0.3, 0.22 * T, y + r, layer="HARDWARE")
    pen.line(0.78 * T, y + r * 0.3, 0.78 * T, y + r, layer="HARDWARE")


def _draw_pano_top_seal(pen, T, y):
    pen.circle(0.12 * T, y + 0.08 * T, 0.07 * T, layer="HARDWARE")
    pen.poly(
        [
            (0.12 * T, y + 0.14 * T),
            (-0.18 * T, y + 0.40 * T),
            (-0.06 * T, y + 0.44 * T),
            (0.16 * T, y + 0.14 * T),
        ],
        close=True,
        layer="HARDWARE",
    )


def panorama_stack_height(T: float) -> float:
    return 0.45 + 0.85 + 1.15 + 0.55 + 0.25 + 0.45 + 0.9 + 0.85 + 0.3
