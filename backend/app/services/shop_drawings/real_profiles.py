"""Upwardor side-profile and jamb details, drawn when the flag is on.

The supplier DWG files are not in the repo. These views are a parametric
reading of the assembly callouts received 2026-11-11:

* The TX series number is the thickness in millimetres (TX-380 is 38 mm,
  TX-450 is 45 mm, TX-500 is 50 mm). A trailing -20 is the exterior face
  gauge, not a thickness.
* TX-450 is the tongue-and-groove joint: full hinge, two 1-1/4" steel
  hinge-reinforcing strips, 26 ga stucco-embossed white skins,
  foamed-in-place polyurethane 2.5 PCF, thermally broken, PVC retainer,
  weather seal, low-temp vinyl bottom astragal, optional low-temp vinyl
  top seal.
* TX-500 is that same joint scaled to 50 mm. The 1-1/4" strips stay
  1-1/4" because that is the part size, not a scaled cartoon.
* TX-380 is the same construction in 1-1/2", with a half hinge and one
  reinforcing strip.
* A -20 door keeps that joint and uses a 20 ga exterior face. The
  standard skin callout stays 26 ga, which is what the supplier sheet
  shows.
* Panorama is a 1-3/4" aluminum full-view section.
* Wood jambs need 3.75" sideroom. Steel jamb welds stay at 3.5".

Skin thickness on the sheet is exaggerated. 26 ga steel is about 0.018"
and would disappear at this scale. The callout still says the real gauge.
"""
from __future__ import annotations

import re
from typing import Optional, Tuple

from ezdxf.enums import TextEntityAlignment
from ezdxf.layouts import Modelspace

from app.services.shop_drawings.framing import (
    TEXT_MED,
    TEXT_SMALL,
    DrawingContext,
    _draw_linear_dim,
)

_TX = re.compile(r"^TX-?(?P<num>\d{3})(?:-?(?P<suffix>\d+))?[A-Z]*$", re.I)

# Reference joint is the TX-450 section. Other TX thicknesses scale this
# joint in the thickness direction. 1.75" is 45 mm rounded to the nearest
# eighth, which is how the shop states the size.
_TX450_IN = 1.75

_EIGHTHS = {
    0: "",
    1: "1/8",
    2: "1/4",
    3: "3/8",
    4: "1/2",
    5: "5/8",
    6: "3/4",
    7: "7/8",
}


def _series_token(series: str) -> str:
    return (series or "").upper().replace(" ", "")


def parse_tx_series(series: str) -> Optional[Tuple[float, str]]:
    """Return (thickness mm, gauge suffix) for a TX series code.

    TX-450, TX450, and TX450-20 all read as 45 mm. The suffix is "" or
    "20". Anything that is not a TX code returns None.
    """
    match = _TX.match(_series_token(series))
    if not match:
        return None
    mm = int(match.group("num")) / 10.0
    return mm, (match.group("suffix") or "")


def nominal_inches(mm: float) -> float:
    """Shop size: millimetres to the nearest eighth of an inch."""
    return round(mm / 25.4 * 8.0) / 8.0


def inches_fraction(inches: float) -> str:
    eighths = int(round(float(inches) * 8.0))
    whole, rem = divmod(eighths, 8)
    frac = _EIGHTHS[rem]
    if not frac:
        return f'{whole}"'
    if whole:
        return f'{whole}-{frac}"'
    return f'{frac}"'


def series_thickness_mm(series: str) -> Optional[float]:
    parsed = parse_tx_series(series)
    return None if parsed is None else parsed[0]


def exterior_is_20ga(series: str) -> bool:
    parsed = parse_tx_series(series)
    return parsed is not None and parsed[1] == "20"


def hinge_style(series: str) -> str:
    """TX-380 is the half-hinge section. Every other TX joint is full."""
    mm = series_thickness_mm(series)
    return "half" if mm == 38 else "full"


def real_panel_thickness_in(series: str, door_type: str = "") -> Optional[float]:
    """Thickness for a series we know how to draw, or None to keep the schematic.

    TX thickness comes from the series number. Panorama is 1-3/4".
    ``door_type`` is accepted so callers can pass the drawing context
    without deciding which field matters.
    """
    del door_type
    parsed = parse_tx_series(series)
    if parsed is not None:
        return nominal_inches(parsed[0])
    if is_panorama(series):
        return 1.75
    return None


def is_panorama(series: str) -> bool:
    return _series_token(series) == "PANORAMA"


def real_sideroom_in(jamb_type: str) -> float:
    """Minimum sideroom each side. Wood is 3.75". Steel weld is 3.5"."""
    if (jamb_type or "").lower() == "steel":
        return 3.5
    return 3.75


def thickness_callout(series: str, door_type: str = "") -> Optional[str]:
    del door_type
    parsed = parse_tx_series(series)
    if parsed is not None:
        mm, _suffix = parsed
        inches = nominal_inches(mm)
        mm_txt = str(int(mm)) if mm == int(mm) else f"{mm:g}"
        return f"{inches_fraction(inches)} ({mm_txt} mm)"
    if is_panorama(series):
        return inches_fraction(1.75)
    return None


def draw_real_panel_profile(msp: Modelspace, ctx: DrawingContext,
                            box: Tuple[float, float, float, float]) -> bool:
    """Draw the supplier profile. Return False when this series stays schematic."""
    if parse_tx_series(ctx.door_series) is not None:
        _draw_tx_profile(msp, ctx, box)
        return True
    if is_panorama(ctx.door_series):
        _draw_panorama_profile(msp, ctx, box)
        return True
    return False


def _poly(msp: Modelspace, pts, layer: str, lw: int = 25, closed: bool = True,
          linetype: str = "CONTINUOUS") -> None:
    if len(pts) < 2:
        return
    attribs = {"layer": layer, "lineweight": lw, "linetype": linetype}
    msp.add_lwpolyline(list(pts), close=closed, dxfattribs=attribs)


def _text(msp, value, xy, height, align=TextEntityAlignment.MIDDLE_CENTER):
    entity = msp.add_text(
        value,
        dxfattribs={"layer": "ANNOTATIONS", "height": height, "style": "Standard"},
    )
    entity.set_placement(xy, align=align)
    return entity


def _callouts(msp, box, anchors) -> None:
    """Stack callouts down the right side of the profile box.

    anchors: (sheet_x, sheet_y, mtext) in top-to-bottom reading order.
    """
    bx0, by0, bx1, by1 = box
    label_x = bx0 + (bx1 - bx0) * 0.50
    label_top = by1 - 0.42
    label_bot = by0 + 0.36
    # Highest feature gets the highest label so leaders stay short.
    anchors = sorted(anchors, key=lambda item: -item[1])
    n = max(len(anchors), 1)
    slot = max((label_top - label_bot) / n, 0.10)
    for i, (ax, ay, text) in enumerate(anchors):
        y_label = label_top - (i + 0.5) * slot
        stub_x = max(ax + 0.04, min(label_x - 0.08, ax + 0.12))
        msp.add_line((ax, ay), (stub_x, ay),
                     dxfattribs={"layer": "ANNOTATIONS", "lineweight": 13})
        msp.add_line((stub_x, ay), (label_x - 0.03, y_label),
                     dxfattribs={"layer": "ANNOTATIONS", "lineweight": 13})
        mtext = msp.add_mtext(
            text,
            dxfattribs={
                "layer": "ANNOTATIONS",
                "char_height": TEXT_SMALL * 0.58,
                "style": "Standard",
                "attachment_point": 4,
                "width": max(bx1 - label_x - 0.02, 0.4),
            },
        )
        mtext.dxf.insert = (label_x, y_label)


def _fit(box, local_w, local_h):
    bx0, by0, bx1, by1 = box
    box_w = bx1 - bx0
    box_h = by1 - by0
    draw_right = bx0 + box_w * 0.48
    avail_w = max(draw_right - bx0 - 0.16, 0.4)
    avail_h = max(box_h - 0.72, 0.4)
    scale = min(avail_w / local_w, avail_h / local_h)
    content_h = local_h * scale
    origin_x = bx0 + 0.10
    origin_y = by0 + 0.38 + max(avail_h - content_h, 0) / 2
    return scale, origin_x, origin_y


def _draw_tx_profile(msp, ctx: DrawingContext, box) -> None:
    parsed = parse_tx_series(ctx.door_series)
    mm, _suffix = parsed
    thickness = nominal_inches(mm)
    sx = thickness / _TX450_IN
    full = hinge_style(ctx.door_series) == "full"
    heavy_exterior = exterior_is_20ga(ctx.door_series)

    tongue_w = 0.62 * sx
    tongue_h = 0.48 * sx
    tongue_x0 = 0.30 * sx
    tongue_x1 = tongue_x0 + tongue_w
    groove_h = tongue_h
    # 26 ga is drawn thin. A 20 ga exterior face is visibly heavier.
    # The tongue still has to clear the skin so the thermal break has a gap.
    skin_ext = 0.20 if heavy_exterior else 0.07
    skin_int = 0.07
    skin_ext = min(skin_ext, max(tongue_x0 - 0.06, 0.05))
    strip_h = 1.25
    strip_depth = 0.22
    foam_window = 1.15
    astragal_h = 0.78
    retainer_h = 0.36
    top_seal_h = 0.34
    overhang = 0.14

    if full:
        body_h = groove_h + 0.10 + strip_h + foam_window + strip_h + 0.12
    else:
        body_h = groove_h + 0.12 + foam_window + strip_h + 0.12

    y_section0 = astragal_h + retainer_h
    y_section1 = y_section0 + body_h
    y_tongue1 = y_section1 + tongue_h
    y_top = y_tongue1 + top_seal_h

    # Local bounds include the astragal overhang and the hinge knuckle.
    local_x0 = -overhang
    local_x1 = thickness + 0.36
    local_w = local_x1 - local_x0
    local_h = y_top

    scale, origin_x, origin_y = _fit(box, local_w, local_h)

    def X(x):
        return origin_x + (x - local_x0) * scale

    def Y(y):
        return origin_y + y * scale

    def P(*pairs):
        return [(X(x), Y(y)) for x, y in pairs]

    bx0, by0, bx1, by1 = box
    _text(
        msp,
        f"{ctx.door_series} SIDE PROFILE",
        ((bx0 + bx1) / 2, by1 - 0.12),
        TEXT_MED,
    )

    # Tongue-and-groove silhouette.
    _poly(msp, P(
        (0, y_section0),
        (0, y_section1),
        (tongue_x0, y_section1),
        (tongue_x0, y_tongue1),
        (tongue_x1, y_tongue1),
        (tongue_x1, y_section1),
        (thickness, y_section1),
        (thickness, y_section0),
        (tongue_x1, y_section0),
        (tongue_x1, y_section0 + groove_h),
        (tongue_x0, y_section0 + groove_h),
        (tongue_x0, y_section0),
    ), "FRAMING", 35)

    # Skins. The exterior face is heavier on a -20 door.
    _poly(msp, P(
        (0, y_section0),
        (skin_ext, y_section0),
        (skin_ext, y_section1),
        (0, y_section1),
    ), "FRAMING", 25)
    _poly(msp, P(
        (thickness - skin_int, y_section0),
        (thickness, y_section0),
        (thickness, y_section1),
        (thickness - skin_int, y_section1),
    ), "FRAMING", 25)

    # Thermal break: PVC blocks where the two skins would otherwise meet.
    tb_top = (
        (skin_ext, y_section1 - 0.20),
        (tongue_x0, y_section1 - 0.20),
        (tongue_x0, y_section1),
        (skin_ext, y_section1),
    )
    tb_bot = (
        (skin_ext, y_section0),
        (tongue_x0, y_section0),
        (tongue_x0, y_section0 + 0.18),
        (skin_ext, y_section0 + 0.18),
    )
    for block in (tb_top, tb_bot):
        _poly(msp, P(*block), "HARDWARE", 18)
        xs = [p[0] for p in block]
        ys = [p[1] for p in block]
        _hatch(msp, min(xs), max(xs), min(ys), max(ys), X, Y)

    # Foam between the strips (or between the groove and the one strip).
    strip_x1 = thickness - skin_int - 0.03
    strip_x0 = strip_x1 - strip_depth
    if full:
        bot_y0 = y_section0 + groove_h + 0.08
        bot_y1 = bot_y0 + strip_h
        top_y1 = y_section1 - 0.10
        top_y0 = top_y1 - strip_h
        strips = ((strip_x0, strip_x1, bot_y0, bot_y1),
                  (strip_x0, strip_x1, top_y0, top_y1))
        foam_y0, foam_y1 = bot_y1, top_y0
    else:
        top_y1 = y_section1 - 0.10
        top_y0 = top_y1 - strip_h
        strips = ((strip_x0, strip_x1, top_y0, top_y1),)
        foam_y0 = y_section0 + groove_h + 0.10
        foam_y1 = top_y0

    _stipple(msp, skin_ext + 0.04, strip_x0 - 0.02, foam_y0, foam_y1, X, Y)
    # Break lines so the shortened foam reads as a continuing section.
    mid = (foam_y0 + foam_y1) / 2
    for dy in (-0.10, 0.10):
        _break(msp, skin_ext + 0.05, thickness - skin_int - 0.05, mid + dy, X, Y)

    for x0, x1, y0, y1 in strips:
        _poly(msp, P((x0, y0), (x1, y0), (x1, y1), (x0, y1)), "FRAMING", 30)
        _hatch(msp, x0, x1, y0, y1, X, Y, step=0.05)

    # Hinge leaves and knuckles on the interior face.
    leaf_t = 0.08
    knuckle_r = 0.18
    _hinge(msp, thickness, y_section1, leaf_t, knuckle_r, X, Y, downward=True,
           centered_on_joint=full)
    if full:
        _hinge(msp, thickness, y_section0, leaf_t, knuckle_r, X, Y, downward=False,
               centered_on_joint=True)

    # Weather seal sitting in the groove, clear of the retainer below it.
    seal_c = ((tongue_x0 + tongue_x1) / 2, y_section0 + groove_h * 0.62)
    msp.add_circle(
        center=(X(seal_c[0]), Y(seal_c[1])),
        radius=max(groove_h * 0.22 * scale, 0.012),
        dxfattribs={"layer": "HARDWARE", "lineweight": 18},
    )

    # PVC retainer, then the low-temp vinyl astragal under it.
    ret_x0 = 0.10 * sx
    ret_x1 = thickness - 0.10 * sx
    _poly(msp, P(
        (ret_x0, y_section0),
        (ret_x1, y_section0),
        (ret_x1, y_section0 - retainer_h),
        (ret_x0, y_section0 - retainer_h),
    ), "HARDWARE", 25)
    _poly(msp, P(
        (-overhang, y_section0 - retainer_h),
        (thickness + overhang, y_section0 - retainer_h),
        (thickness + overhang * 0.4, astragal_h * 0.15),
        (-overhang * 0.4, astragal_h * 0.15),
    ), "HARDWARE", 25)

    # Optional top seal, dashed so it reads as optional.
    _poly(msp, P(
        (tongue_x0, y_tongue1),
        (tongue_x1, y_tongue1),
        (tongue_x1 - 0.06 * sx, y_top),
        (tongue_x0 + 0.06 * sx, y_top),
    ), "HIDDEN", 18, linetype="HIDDEN")

    if heavy_exterior:
        skin_label = "20 GA STUCCO-EMBOSSED\\PFLUSH WHITE EXTERIOR\\P26 GA STUCCO-EMBOSSED WHITE INTERIOR"
    else:
        skin_label = "26 GA STUCCO-EMBOSSED\\PWHITE SKINS"
    hinge_label = (
        "TONGUE-AND-GROOVE\\PFULL HINGE"
        if full else
        "TONGUE-AND-GROOVE\\PHALF-HINGE APPLICATION"
    )
    strip_label = (
        'TWO 1-1/4" STEEL\\PHINGE-REINFORCING STRIPS'
        if full else
        'ONE 1-1/4" STEEL\\PHINGE-REINFORCING STRIP'
    )
    # Point at the top strip. A full hinge has a second strip at the bottom.
    strip_anchor_y = (strips[-1][2] + strips[-1][3]) / 2

    anchors = [
        (X((tongue_x0 + tongue_x1) / 2), Y(y_top - 0.04),
         "OPTIONAL LOW-TEMP\\PVINYL TOP SEAL"),
        (X(tongue_x1), Y(y_section1 + tongue_h * 0.4), hinge_label),
        (X(strip_x1), Y(strip_anchor_y), strip_label),
        (X(skin_ext), Y((foam_y0 + foam_y1) / 2), skin_label),
        (X((skin_ext + strip_x0) / 2), Y((foam_y0 + foam_y1) / 2),
         "FOAMED-IN-PLACE\\PPOLYURETHANE\\P2.5 PCF"),
        (X(tongue_x0), Y(y_section1 - 0.08), "THERMALLY BROKEN"),
        (X(seal_c[0]), Y(seal_c[1]), "WEATHER SEAL"),
        (X((ret_x0 + ret_x1) / 2), Y(y_section0 - retainer_h * 0.5), "PVC RETAINER"),
        (X(thickness * 0.5), Y(astragal_h * 0.45),
         "LOW-TEMP VINYL\\PBOTTOM ASTRAGAL"),
    ]
    _callouts(msp, box, anchors)

    dim_y = Y(0) - 0.30
    _draw_linear_dim(
        msp,
        (X(0), Y(0)),
        (X(thickness), Y(0)),
        dim_y,
        label=thickness_callout(ctx.door_series),
    )


def _hinge(msp, thickness, joint_y, leaf_t, knuckle_r, X, Y, *,
           downward: bool, centered_on_joint: bool) -> None:
    direction = -1 if downward else 1
    leaf_y1 = joint_y
    leaf_y0 = joint_y + direction * 1.25
    y0, y1 = sorted((leaf_y0, leaf_y1))
    _poly(msp, [
        (X(thickness), Y(y0)),
        (X(thickness + leaf_t), Y(y0)),
        (X(thickness + leaf_t), Y(y1)),
        (X(thickness), Y(y1)),
    ], "HARDWARE", 25)
    if centered_on_joint:
        cy = joint_y
    else:
        # Half hinge sits on this section, not astride the joint.
        cy = joint_y - knuckle_r
    msp.add_circle(
        center=(X(thickness + knuckle_r * 0.9), Y(cy)),
        radius=max(knuckle_r * (Y(1) - Y(0)), 0.012),
        dxfattribs={"layer": "HARDWARE", "lineweight": 25},
    )


def _hatch(msp, x0, x1, y0, y1, X, Y, step: float = 0.06) -> None:
    span = max(x1 - x0, 0.01)
    n = max(int(span / step), 2)
    for i in range(1, n):
        x = x0 + span * i / n
        msp.add_line(
            (X(x), Y(y0)), (X(x), Y(y1)),
            dxfattribs={"layer": "ANNOTATIONS", "lineweight": 5},
        )


def _stipple(msp, x0, x1, y0, y1, X, Y) -> None:
    if x1 <= x0 or y1 <= y0:
        return
    cols = 4
    rows = 5
    for c in range(cols):
        for r in range(rows):
            x = x0 + (x1 - x0) * (c + 0.5) / cols
            y = y0 + (y1 - y0) * ((r + (0.25 if c % 2 else 0.0)) / rows)
            if y >= y1:
                continue
            msp.add_circle(
                center=(X(x), Y(y)),
                radius=0.008,
                dxfattribs={"layer": "ANNOTATIONS", "lineweight": 5},
            )


def _break(msp, x0, x1, y, X, Y) -> None:
    mid = (x0 + x1) / 2
    pts = [
        (x0, y),
        (mid - 0.16, y),
        (mid - 0.06, y + 0.12),
        (mid + 0.06, y - 0.12),
        (mid + 0.16, y),
        (x1, y),
    ]
    msp.add_lwpolyline(
        [(X(x), Y(yy)) for x, yy in pts],
        dxfattribs={"layer": "FRAMING", "lineweight": 18},
    )


def _draw_panorama_profile(msp, ctx: DrawingContext, box) -> None:
    thickness = 1.75
    rail_h = 1.85
    glass_h = 2.15
    astragal_h = 0.72
    seal_h = 0.30
    wall = 0.12
    glass_t = 0.50
    mould_w = 0.16
    mould_h = 0.28
    overhang = 0.12

    y_rail0 = astragal_h
    y_glass0 = y_rail0 + rail_h
    y_glass1 = y_glass0 + glass_h
    y_rail1 = y_glass1 + rail_h
    y_top = y_rail1 + seal_h
    local_x0 = -overhang
    local_x1 = thickness + 0.85
    scale, origin_x, origin_y = _fit(box, local_x1 - local_x0, y_top + 0.15)

    def X(x):
        return origin_x + (x - local_x0) * scale

    def Y(y):
        return origin_y + y * scale

    def P(*pairs):
        return [(X(x), Y(y)) for x, y in pairs]

    bx0, by0, bx1, by1 = box
    _text(
        msp,
        f"{ctx.door_series} SIDE PROFILE",
        ((bx0 + bx1) / 2, by1 - 0.12),
        TEXT_MED,
    )

    def rail(y0, y1, rebate_from_top: bool) -> None:
        _poly(msp, P((0, y0), (thickness, y0), (thickness, y1), (0, y1)), "FRAMING", 35)
        inset_y0 = y0 + wall
        inset_y1 = y1 - wall
        _poly(msp, P(
            (wall, inset_y0),
            (thickness - wall, inset_y0),
            (thickness - wall, inset_y1),
            (wall, inset_y1),
        ), "FRAMING", 18)
        # Glazing rebate: the glass pockets into the rail.
        if rebate_from_top:
            pocket_y0, pocket_y1 = y1 - wall, y1
            glass_end = y1 - 0.32
        else:
            pocket_y0, pocket_y1 = y0, y0 + wall
            glass_end = y0 + 0.32
        gx0 = (thickness - glass_t) / 2
        gx1 = gx0 + glass_t
        _poly(msp, P(
            (gx0, pocket_y0), (gx1, pocket_y0), (gx1, pocket_y1), (gx0, pocket_y1),
        ), "HIDDEN", 13, linetype="HIDDEN")
        return glass_end

    _ = rail(y_rail0, y_glass0, rebate_from_top=True)
    rail(y_glass1, y_rail1, rebate_from_top=False)

    gx0 = (thickness - glass_t) / 2
    gx1 = gx0 + glass_t
    # Double pane between the rails, running into each rebate.
    for x in (gx0, (gx0 + gx1) / 2, gx1):
        msp.add_line(
            (X(x), Y(y_rail0 + 0.32)),
            (X(x), Y(y_rail1 - 0.32)),
            dxfattribs={"layer": "ANNOTATIONS", "lineweight": 18},
        )

    # Glazing moulding on the exterior, at each rail where the glass starts.
    for y0 in (y_glass0, y_glass1 - mould_h):
        _poly(msp, P(
            (-0.02, y0),
            (mould_w, y0),
            (mould_w, y0 + mould_h),
            (-0.02, y0 + mould_h),
        ), "HARDWARE", 25)

    # Weather seal on top of the top rail.
    _poly(msp, P(
        (0.20, y_rail1),
        (thickness * 0.55, y_rail1),
        (thickness * 0.50, y_top),
        (0.28, y_top),
    ), "HARDWARE", 18)

    # 12 ga adjustable top roller: slotted bracket on the interior, wheel above.
    br_x0 = thickness
    br_x1 = thickness + 0.48
    br_y0 = y_rail1 - 0.55
    br_y1 = y_rail1 + 0.70
    _poly(msp, P(
        (br_x0, br_y0), (br_x1, br_y0), (br_x1, br_y1), (br_x0, br_y1),
    ), "HARDWARE", 30)
    slot_x = (br_x0 + br_x1) / 2
    msp.add_line((X(slot_x - 0.04), Y(br_y0 + 0.12)),
                 (X(slot_x - 0.04), Y(br_y1 - 0.18)),
                 dxfattribs={"layer": "HARDWARE", "lineweight": 13})
    msp.add_line((X(slot_x + 0.04), Y(br_y0 + 0.12)),
                 (X(slot_x + 0.04), Y(br_y1 - 0.18)),
                 dxfattribs={"layer": "HARDWARE", "lineweight": 13})
    msp.add_circle(
        center=(X(slot_x), Y(br_y1 + 0.02)),
        radius=max(0.16 * scale, 0.015),
        dxfattribs={"layer": "HARDWARE", "lineweight": 30},
    )

    # 12 ga bottom bracket.
    bb_y0 = y_rail0 + 0.28
    bb_y1 = bb_y0 + 0.95
    _poly(msp, P(
        (thickness, bb_y0),
        (thickness + 0.62, bb_y0),
        (thickness + 0.62, bb_y1),
        (thickness, bb_y1),
    ), "HARDWARE", 30)

    # Low-temp vinyl bottom astragal.
    _poly(msp, P(
        (-overhang, y_rail0),
        (thickness + overhang, y_rail0),
        (thickness + overhang * 0.35, astragal_h * 0.12),
        (-overhang * 0.35, astragal_h * 0.12),
    ), "HARDWARE", 25)

    anchors = [
        (X(0.35), Y(y_top - 0.04), "WEATHER SEAL"),
        (X(br_x1), Y((br_y0 + br_y1) / 2),
         "12 GA GALV.\\PADJUSTABLE TOP ROLLER"),
        (X(mould_w), Y(y_glass0 + mould_h * 0.5), "GLAZING MOULDING"),
        (X(thickness * 0.5), Y((y_glass0 + y_glass1) / 2),
         '1-3/4" ALUMINUM\\PFULL-VIEW'),
        (X(thickness + 0.62), Y((bb_y0 + bb_y1) / 2),
         "12 GA GALV.\\PBOTTOM BRACKET"),
        (X(thickness * 0.5), Y(astragal_h * 0.4),
         "LOW-TEMP VINYL\\PBOTTOM ASTRAGAL"),
    ]
    _callouts(msp, box, anchors)
    _draw_linear_dim(
        msp,
        (X(0), Y(0)),
        (X(thickness), Y(0)),
        Y(0) - 0.30,
        label=inches_fraction(thickness),
    )


def draw_welded_jamb(msp: Modelspace, *, d_x0, d_x1, sec_y_bot, sec_y_top,
                     bx0, bx1, opening_dim_y) -> None:
    """Steel jamb weld: an angle welded to each steel jamb, 3.5" sideroom.

    The angle is drawn large enough to read. The sideroom dimension, not
    this symbol, carries the 3.5" minimum.
    """
    band = max(sec_y_top - sec_y_bot, 0.08)
    leg = max(band * 1.35, 0.16)
    th = max(band * 0.28, 0.035)

    def angle(sign: int, jamb_x: float) -> None:
        # sign +1 grows into the opening toward the right.
        x_leg = jamb_x + sign * leg
        x_th = jamb_x + sign * th
        pts = [
            (jamb_x, sec_y_bot),
            (jamb_x, sec_y_bot - leg),
            (x_th, sec_y_bot - leg),
            (x_th, sec_y_bot - th),
            (x_leg, sec_y_bot - th),
            (x_leg, sec_y_bot),
            (jamb_x, sec_y_bot),
        ]
        _poly(msp, pts, "HARDWARE", 35)
        # Weld ticks on the jamb side of the vertical leg.
        for i in range(3):
            y = sec_y_bot - leg * (0.25 + 0.22 * i)
            msp.add_line(
                (jamb_x - sign * th * 0.2, y),
                (jamb_x - sign * th * 1.6, y - th),
                dxfattribs={"layer": "HARDWARE", "lineweight": 18},
            )

    angle(+1, d_x0)
    angle(-1, d_x1)

    label_x = bx1 - 1.35
    label_y = opening_dim_y - 0.55
    leader_x = d_x0 + (d_x1 - d_x0) * 0.72
    msp.add_line(
        (leader_x, sec_y_bot - th),
        (label_x, label_y + 0.06),
        dxfattribs={"layer": "ANNOTATIONS"},
    )
    mtext = msp.add_mtext(
        "WELDED ANGLE\\PTO THE STEEL JAMB",
        dxfattribs={
            "layer": "ANNOTATIONS",
            "char_height": TEXT_SMALL * 0.75,
            "style": "Standard",
            "attachment_point": 4,
            "width": 1.30,
        },
    )
    mtext.dxf.insert = (label_x, label_y)


def draw_wood_jamb_hardware(msp: Modelspace, *, d_x0, d_x1, sec_y_bot, sec_y_top,
                            jl_x0, jl_x1, jr_x0, jr_x1) -> None:
    """Steel end cap on the door edge, and ramset-fastened weatherstripping.

    The existing plan callouts name both of these. This adds the shapes
    next to those leaders. Sideroom for this application is 3.75".
    """
    band = max(sec_y_top - sec_y_bot, 0.05)
    cap = max(band * 0.22, 0.025)
    # End cap wraps each vertical edge of the slab.
    for edge, sign in ((d_x0, 1), (d_x1, -1)):
        _poly(msp, [
            (edge, sec_y_bot),
            (edge + sign * cap, sec_y_bot),
            (edge + sign * cap, sec_y_top),
            (edge, sec_y_top),
        ], "HARDWARE", 30)

    strip_h = max(band * 0.35, 0.04)
    reach = max((d_x1 - d_x0) * 0.08, cap * 3)

    def weatherstrip(x_outer, x_inner) -> None:
        xs = sorted((x_outer, x_inner))
        y0 = sec_y_top
        y1 = sec_y_top + strip_h
        _poly(msp, [
            (xs[0], y0), (xs[1], y0), (xs[1], y1), (xs[0], y1),
        ], "HARDWARE", 18)
        # Two ramset marks.
        span = xs[1] - xs[0]
        for frac in (0.35, 0.70):
            cx = xs[0] + span * frac
            cy = (y0 + y1) / 2
            arm = strip_h * 0.28
            msp.add_line((cx - arm, cy - arm), (cx + arm, cy + arm),
                         dxfattribs={"layer": "ANNOTATIONS", "lineweight": 18})
            msp.add_line((cx - arm, cy + arm), (cx + arm, cy - arm),
                         dxfattribs={"layer": "ANNOTATIONS", "lineweight": 18})

    weatherstrip(jl_x1 - reach, jl_x1)
    weatherstrip(jr_x0, jr_x0 + reach)
