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


def steel_stack_height(T: float) -> float:
    from app.services.shop_drawings.detail_render import steel_size
    return steel_size(T)[1]


def steel_stack_size(T: float) -> tuple[float, float]:
    from app.services.shop_drawings.detail_render import steel_size
    return steel_size(T)


def panorama_stack_height(T: float) -> float:
    from app.services.shop_drawings.detail_render import panorama_size
    return panorama_size(T)[1]


def panorama_stack_size(T: float) -> tuple[float, float]:
    from app.services.shop_drawings.detail_render import panorama_size
    return panorama_size(T)


def draw_parametric_steel(msp: Modelspace, spec, origin, scale: float):
    from app.services.shop_drawings.detail_render import render_steel
    return render_steel(msp, spec, origin, scale)


def draw_parametric_panorama(msp: Modelspace, spec, origin, scale: float):
    from app.services.shop_drawings.detail_render import render_panorama
    return render_panorama(msp, spec, origin, scale)
