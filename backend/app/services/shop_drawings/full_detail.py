"""Flag-on elevations, shaft, and track. The section profile is not drawn here.

Every view on this sheet uses one scale. Spring length and outside diameter,
shaft diameter and length, drum diameter, door thickness, section joints,
and the track radius are the calculator and Thermalex figures. A part with
no source is labeled BY FACTORY and is not given a made-up size.
"""
from __future__ import annotations

import re

from ezdxf.enums import TextEntityAlignment

from app.services.shop_drawings.framing import (
    TEXT_MED,
    TEXT_SMALL,
    fmt_length_dual,
    fmt_length_imperial,
    _hinge_columns,
)
from app.services.shop_drawings.real_profiles import real_panel_thickness_in
from app.services.shop_drawings.shop_hardware import BY_FACTORY, ShopHardware, resolve_shop_hardware

_TOP_NOTE = re.compile(r"to\s+(\d+)", re.I)


def hardware(ctx) -> ShopHardware:
    cached = getattr(ctx, "_shop_hw", None)
    if cached is None:
        cached = resolve_shop_hardware(ctx)
        ctx._shop_hw = cached
    return cached


def section_heights(door_h: float) -> list[float]:
    """Bottom-to-top section heights from the section table.

    The table's note puts the cut section on top. Otherwise the 21 in.
    sections are the lower ones and the 24 in. sections are above them,
    which is how the parts list orders them.
    """
    from app.services.door_calculator_service import SECTION_HEIGHT_TABLE

    key = int(round(door_h or 0))
    entry = SECTION_HEIGHT_TABLE.get(key)
    if not entry:
        return []
    note = _TOP_NOTE.search(entry.get("note") or "")
    if note:
        top = float(note.group(1))
        full = max(int(entry["total"]) - 1, 0)
        return [21.0] * full + [top]
    n21 = int(entry.get("21") or 0)
    n24 = int(entry.get("24") or 0)
    return [21.0] * n21 + [24.0] * n24


def _section_label(heights: list[float]) -> str:
    if not heights:
        return "SECTIONS — BY FACTORY"
    if len(set(round(h, 3) for h in heights)) == 1:
        return f"{len(heights)} SECTIONS @ {fmt_length_imperial(heights[0])}"
    parts = []
    run = 1
    for prev, cur in zip(heights, heights[1:] + [None]):
        if cur is not None and abs(cur - prev) < 0.01:
            run += 1
            continue
        parts.append(f"{run} @ {fmt_length_imperial(prev)}")
        run = 1
    return "SECTIONS " + " + ".join(parts)


def _text(msp, value, xy, height=None, align=TextEntityAlignment.MIDDLE_CENTER):
    entity = msp.add_text(
        value,
        dxfattribs={
            "layer": "ANNOTATIONS",
            "height": height if height is not None else TEXT_SMALL,
            "style": "Standard",
        },
    )
    entity.set_placement(xy, align=align)
    return entity


def _thickness_label(inches: float) -> str:
    """Series thickness as a shop fraction: 1.75 → 1-3/4\"."""
    eighths = int(round(inches * 8))
    whole, frac = divmod(eighths, 8)
    names = {1: "1/8", 2: "1/4", 3: "3/8", 4: "1/2", 5: "5/8", 6: "3/4", 7: "7/8"}
    if frac == 0:
        return f'{whole}"'
    if whole:
        return f'{whole}-{names[frac]}"'
    return f'{names[frac]}"'


def _line(msp, a, b, layer="FRAMING", weight=18):
    color = 8 if layer == "DIMENSIONS" else 250
    msp.add_line(a, b, dxfattribs={"layer": layer, "lineweight": weight, "color": color})


def _rect(msp, x0, y0, x1, y1, layer="FRAMING", weight=25):
    msp.add_lwpolyline(
        [(x0, y0), (x1, y0), (x1, y1), (x0, y1)],
        close=True,
        dxfattribs={"layer": layer, "lineweight": weight, "color": 250},
    )


def _fill(msp, x0, y0, x1, y1):
    """Light gray fill so a framing member reads as material, not a void."""
    hatch = msp.add_hatch(dxfattribs={"layer": "FRAMING", "color": 9})
    hatch.paths.add_polyline_path(
        [(x0, y0), (x1, y0), (x1, y1), (x0, y1)],
        is_closed=True,
    )


def draw_front_detail(msp, ctx, box, view: str = "interior") -> None:
    hw = hardware(ctx)
    x0, y0, x1, y1 = box
    interior = view == "interior"
    door_w = ctx.door_width_in or 96.0
    door_h = ctx.door_height_in or 84.0
    wood = (ctx.jamb_type or "wood") != "steel"
    jamb_w = 5.5 if wood else 3.0
    header_h = jamb_w
    heights = section_heights(door_h)
    if not heights:
        heights = [door_h]
    thick = real_panel_thickness_in(ctx.door_series, ctx.door_type) or 1.75
    track = float(hw.track_size)
    headroom = hw.headroom or 0.0

    title = "INSIDE LOOKING OUT" if interior else "OUTSIDE LOOKING IN"
    member = "2x6" if wood else '3" ANGLE'
    _text(msp, f"{ctx.door_series}  {title}", ((x0 + x1) / 2, y1 - 0.12), TEXT_MED * 0.85)
    _text(
        msp,
        f"{_section_label(heights)}    {member} JAMB / HEADER    {ctx.panel_design}",
        ((x0 + x1) / 2, y1 - 0.28),
        TEXT_SMALL * 0.62,
    )
    if interior:
        _hardware_notes(msp, hw, x0, x1, y1)

    # One scale for the opening, the framing, and (inside) the shaft.
    shaft_len = hw.shaft_length or 0.0
    shaft_x0 = door_w / 2 - shaft_len / 2 if shaft_len else 0.0
    shaft_y = door_h + hw.shaft_cl if (interior and hw.shaft_cl is not None) else door_h
    drum_d = hw.drum_diameter or 0.0
    y_top = door_h + max(headroom, (hw.shaft_cl or 0) + drum_d)
    x_left = -jamb_w - track - 1.0
    x_right = door_w + jamb_w + track + 1.0
    if interior and shaft_len:
        x_left = min(x_left, shaft_x0 - 1.0)
        x_right = max(x_right, shaft_x0 + shaft_len + 1.0)

    title_band = 0.78 if interior else 0.46
    bot_band = 0.28
    avail_w = max((x1 - x0) - 0.20, 0.4)
    avail_h = max((y1 - y0) - title_band - bot_band, 0.4)
    scale = min(avail_w / (x_right - x_left), avail_h / max(y_top, 1.0))
    ox = x0 + 0.10 + (avail_w - (x_right - x_left) * scale) / 2 - x_left * scale
    oy = y0 + bot_band

    def X(inches):
        return ox + inches * scale

    def Y(inches):
        return oy + inches * scale

    # Framing members at their real width, filled gray, outlined black.
    _fill(msp, X(x_left + track + 1), Y(0), X(0), Y(door_h))
    _fill(msp, X(door_w), Y(0), X(door_w + jamb_w), Y(door_h))
    _fill(msp, X(x_left + track + 1), Y(door_h), X(door_w + jamb_w), Y(door_h + header_h))
    _rect(msp, X(0) - jamb_w * scale, Y(0), X(0), Y(door_h), weight=35)
    _rect(msp, X(door_w), Y(0), X(door_w) + jamb_w * scale, Y(door_h), weight=35)
    _rect(msp, X(0) - jamb_w * scale, Y(door_h), X(door_w) + jamb_w * scale,
          Y(door_h + header_h), weight=35)
    _rect(msp, X(0), Y(0), X(door_w), Y(door_h), weight=50)

    # Joints at the real section heights, not equal slices of the opening.
    acc = 0.0
    joints = []
    for height in heights[:-1]:
        acc += height
        joints.append(acc)
        _line(msp, (X(0), Y(acc)), (X(door_w), Y(acc)), layer="HORIZONTALS", weight=25)

    if ctx.has_windows and ctx.window_positions:
        for pos in ctx.window_positions:
            sec = int(pos.get("section", 0))
            col = int(pos.get("col", 0))
            base = sum(heights[:sec])
            sec_h = heights[sec] if sec < len(heights) else heights[-1]
            _rect(
                msp,
                X(door_w * (col + 0.28) / 4), Y(base + sec_h * 0.25),
                X(door_w * (col + 0.52) / 4), Y(base + sec_h * 0.72),
                layer="ANNOTATIONS", weight=18,
            )
    elif ctx.has_windows:
        _text(msp, f"WINDOWS — {BY_FACTORY}", (X(door_w / 2), Y(door_h * 0.5)), TEXT_SMALL * 0.6)

    if hw.strut_count > 0:
        gauge = (hw.strut_gauge or "20ga").upper()
        for i in range(min(hw.strut_count, len(heights))):
            base = sum(heights[:i])
            _line(
                msp, (X(2), Y(base + heights[i] * 0.5)),
                (X(door_w - 2), Y(base + heights[i] * 0.5)),
                layer="STRUTS", weight=30,
            )
        _text(msp, f"{hw.strut_count} {gauge} STRUTS",
              (X(door_w / 2), Y(heights[0] * 0.5)), TEXT_SMALL * 0.5)

    # Hinges at each joint. The number is the position along the joint.
    # The hinge model itself is not in the parts list.
    n_cols = _hinge_columns(door_w)
    hinge_xs = []
    for k in range(n_cols):
        t = k / (n_cols - 1) if n_cols > 1 else 0.5
        hinge_xs.append(3.5 + (door_w - 7) * t)
    for joint in joints:
        for n, hx in enumerate(hinge_xs, start=1):
            _rect(msp, X(hx - 1.0), Y(joint - 0.7), X(hx + 1.0), Y(joint + 0.7),
                  layer="HARDWARE", weight=18)
            if joint == joints[0]:
                _text(msp, str(n), (X(hx), Y(joint) + 0.08), 0.045)

    # Bottom bracket and top fixture. Drawn, not sized: no catalog model.
    for edge in (0.0, door_w - 4.0):
        _rect(msp, X(edge), Y(0.3), X(edge + 4.0), Y(3.0), layer="HARDWARE", weight=25)
    for edge in (0.0, door_w - 3.0):
        _rect(msp, X(edge), Y(door_h - 2.6), X(edge + 3.0), Y(door_h - 0.2),
              layer="HARDWARE", weight=25)

    # Vertical track just outside each jamb. High lift continues the
    # track above the opening by the high-lift amount.
    track_top = door_h + hw.high_lift
    for side in (-jamb_w - track - 0.4, door_w + jamb_w + 0.4):
        _rect(msp, X(side), Y(0), X(side + track), Y(track_top), layer="TRACKS", weight=35)
    yb = 24.0
    while yb < track_top - 6:
        _line(msp, (X(-jamb_w - track - 1.2), Y(yb)), (X(-jamb_w), Y(yb)),
              layer="HARDWARE", weight=13)
        _line(msp, (X(door_w + jamb_w), Y(yb)), (X(door_w + jamb_w + track + 0.8), Y(yb)),
              layer="HARDWARE", weight=13)
        yb += 24.0

    if headroom:
        ceil = door_h + headroom
        _line(msp, (X(-jamb_w), Y(ceil)), (X(door_w + jamb_w), Y(ceil)), weight=18)

    # Dimensions sit outside the opening.
    _dim_h(msp, X(0), X(door_w), oy - 0.08, fmt_length_dual(door_w))
    _dim_v(msp, Y(0), Y(door_h), X(door_w + jamb_w) + 0.10, fmt_length_imperial(door_h))

    if interior:
        _draw_shaft(msp, hw, X, Y, door_w, door_h, scale)


def _hardware_notes(msp, hw: ShopHardware, x0, x1, y1):
    kind = hw.shaft_kind or BY_FACTORY
    shown = fmt_length_imperial(hw.shaft_length) if hw.shaft_length else BY_FACTORY
    _text(msp, f"SHAFT {kind}  {shown}", ((x0 + x1) / 2, y1 - 0.44), TEXT_SMALL * 0.55)
    if hw.wire and hw.coil_id and hw.spring_length:
        turns = f"{hw.turns:.1f} TURNS" if hw.turns is not None else f"TURNS {BY_FACTORY}"
        spring = (
            f'LH/RH {hw.wire:g}" x {hw.coil_id:g}" ID x {hw.spring_length:g}"  {turns}'
        )
    else:
        spring = f"SPRINGS — {BY_FACTORY}"
    drum = hw.drum_model or BY_FACTORY
    dia = f'{hw.drum_diameter:g}"' if hw.drum_diameter else BY_FACTORY
    cable = f'{hw.cable_diameter:g}"' if hw.cable_diameter else BY_FACTORY
    _text(msp, f"DRUM {drum} {dia}    CABLE {cable}    {spring}",
          ((x0 + x1) / 2, y1 - 0.58), TEXT_SMALL * 0.5)
    strut = (
        f"STRUTS: NONE ({hw.strut_gauge or '20ga'} CHART)"
        if hw.strut_count <= 0 else ""
    )
    extra = f"{strut}    " if strut else ""
    _text(
        msp,
        f"{extra}END BRG / CTR BRKT / BOTTOM BRACKET / TOP FIXTURE / TRACK BRACKET — {BY_FACTORY}",
        ((x0 + x1) / 2, y1 - 0.72),
        TEXT_SMALL * 0.42,
    )


def _dim_h(msp, x0, x1, y, text):
    _line(msp, (x0, y + 0.06), (x0, y - 0.03), layer="DIMENSIONS", weight=9)
    _line(msp, (x1, y + 0.06), (x1, y - 0.03), layer="DIMENSIONS", weight=9)
    _line(msp, (x0, y), (x1, y), layer="DIMENSIONS", weight=9)
    _text(msp, text, ((x0 + x1) / 2, y - 0.07), TEXT_SMALL * 0.55)


def _dim_v(msp, y0, y1, x, text):
    _line(msp, (x - 0.04, y0), (x + 0.05, y0), layer="DIMENSIONS", weight=9)
    _line(msp, (x - 0.04, y1), (x + 0.05, y1), layer="DIMENSIONS", weight=9)
    _line(msp, (x, y0), (x, y1), layer="DIMENSIONS", weight=9)
    entity = msp.add_text(
        text,
        dxfattribs={"layer": "ANNOTATIONS", "height": TEXT_SMALL * 0.55,
                    "style": "Standard", "rotation": 90},
    )
    entity.set_placement(((x + 0.08), (y0 + y1) / 2), align=TextEntityAlignment.MIDDLE_LEFT)


def _draw_shaft(msp, hw: ShopHardware, X, Y, door_w, door_h, scale):
    """Shaft, springs, drums and cable in the same scale as the door.

    Drums sit on the cable line, which drops straight to the bottom
    bracket. The end bearing plate is immediately outboard of each drum.
    Springs are the calculated length and outside diameter, LH on the
    left of the center bracket and RH on the right.
    """
    length = hw.shaft_length
    if not length or hw.shaft_cl is None:
        _text(msp, f"SHAFT — {BY_FACTORY}", (X(door_w / 2), Y(door_h + 4)), TEXT_SMALL * 0.5)
        return
    dia = hw.shaft_diameter or 1.0
    shaft_x0 = door_w / 2 - length / 2
    shaft_y = door_h + hw.shaft_cl
    _rect(
        msp, X(shaft_x0), Y(shaft_y - dia / 2), X(shaft_x0 + length), Y(shaft_y + dia / 2),
        layer="HARDWARE", weight=50,
    )

    # Cable centers land inside the bottom brackets. The drum is centered
    # on that cable. Its drawn barrel length equals the known diameter
    # because the catalog does not publish an axial length.
    drum_d = hw.drum_diameter or 4.0
    drum_w = drum_d if hw.drum_diameter else 4.0
    cable_xs = (3.0, door_w - 3.0)
    for cx in cable_xs:
        _drum(msp, X(cx), Y(shaft_y), drum_d * scale, drum_w * scale)
        outboard = -1 if cx < door_w / 2 else 1
        plate = cx + outboard * (drum_w / 2 + 0.35)
        _rect(
            msp, X(plate), Y(shaft_y - drum_d * 0.7),
            X(plate + outboard * 0.4), Y(shaft_y + drum_d * 0.7),
            layer="HARDWARE", weight=35,
        )
        _line(
            msp, (X(cx), Y(shaft_y - drum_d / 2)), (X(cx), Y(3.0)),
            layer="HARDWARE", weight=25,
        )

    span = hw.spring_length or 0.0
    od = ((hw.coil_id or 0.0) + (hw.wire or 0.0)) or 0.0
    gap = 1.5
    mid = door_w / 2
    if span and od and hw.lh_count:
        _coil(msp, X(mid - gap - span), X(mid - gap), Y(shaft_y), od * scale)
    if span and od and hw.rh_count:
        _coil(msp, X(mid + gap), X(mid + gap + span), Y(shaft_y), od * scale)
    _rect(
        msp, X(mid - 1.0), Y(shaft_y - max(od, dia) * 0.9),
        X(mid + 1.0), Y(shaft_y + max(od, dia) * 0.9),
        layer="HARDWARE", weight=35,
    )


def _coil(msp, x0, x1, cy, od):
    if x1 <= x0 or od <= 0:
        return
    _line(msp, (x0, cy + od / 2), (x1, cy + od / 2), layer="HARDWARE", weight=18)
    _line(msp, (x0, cy - od / 2), (x1, cy - od / 2), layer="HARDWARE", weight=18)
    _line(msp, (x0, cy - od / 2), (x0, cy + od / 2), layer="HARDWARE", weight=25)
    _line(msp, (x1, cy - od / 2), (x1, cy + od / 2), layer="HARDWARE", weight=25)
    steps = 10
    span = x1 - x0
    for i in range(steps):
        xa = x0 + span * i / steps
        xb = x0 + span * (i + 1) / steps
        ya = cy - od / 2 if i % 2 == 0 else cy + od / 2
        yb = cy + od / 2 if i % 2 == 0 else cy - od / 2
        _line(msp, (xa, ya), (xb, yb), layer="HARDWARE", weight=13)


def _drum(msp, cx, cy, diameter, width):
    """Cable drum: flanges at the known diameter, barrel between them."""
    flange = diameter
    barrel = diameter * 0.62
    _rect(msp, cx - width / 2, cy - flange / 2, cx - width / 2 + width * 0.22,
          cy + flange / 2, layer="HARDWARE", weight=25)
    _rect(msp, cx + width / 2 - width * 0.22, cy - flange / 2, cx + width / 2,
          cy + flange / 2, layer="HARDWARE", weight=25)
    _rect(msp, cx - width * 0.28, cy - barrel / 2, cx + width * 0.28,
          cy + barrel / 2, layer="HARDWARE", weight=18)


def draw_side_detail(msp, ctx, box) -> None:
    hw = hardware(ctx)
    bx0, by0, bx1, by1 = box
    door_h = ctx.door_height_in or 84.0
    thick = real_panel_thickness_in(ctx.door_series, ctx.door_type) or 1.75
    radius = float(hw.track_radius)
    track = float(hw.track_size)
    hl = hw.high_lift
    lift = (ctx.lift_type or "standard").lower()
    vertical = lift in ("full_vertical", "vertical")
    headroom = hw.headroom if hw.headroom is not None else 0.0
    backroom = hw.backroom if hw.backroom is not None else 0.0
    ust = hw.ust if hw.ust is not None else 0.0
    heights = section_heights(door_h) or [door_h]

    if vertical:
        label = f'{int(track)}" FULL VERTICAL LIFT'
    elif hl:
        label = f'{int(radius)}"R {int(track)}" HIGH LIFT'
    else:
        label = f'{int(radius)}"R {int(track)}" STANDARD LIFT'
    _text(msp, label, ((bx0 + bx1) / 2, by1 - 0.12), TEXT_MED * 0.85)

    # The horizontal rail lands on the published underside. The radius is
    # the ordered 12" or 15", so the straight vertical stops one radius
    # below that rail. For high lift the underside is the high-lift amount,
    # and the track therefore rises by that amount.
    y_ust = door_h + ust
    arc_start = y_ust - radius
    if vertical:
        vert_top = door_h + headroom
        y_max = vert_top + 4
        x_max = 30.0
    else:
        vert_top = max(arc_start, 0.0)
        y_max = max(y_ust + track, door_h + headroom) + 4
        x_max = max(backroom, radius + track) + thick + 6

    geo_right = bx0 + (bx1 - bx0) * 0.56
    avail_w = max(geo_right - bx0 - 0.35, 0.4)
    avail_h = max((by1 - 0.32) - (by0 + 0.22), 0.4)
    scale = min(avail_w / x_max, avail_h / y_max)
    ox = bx0 + 0.28
    oy = by0 + 0.22

    def X(inches):
        return ox + inches * scale

    def Y(inches):
        return oy + inches * scale

    # Door at the series thickness, with the same section joints.
    _rect(msp, X(-thick), Y(0), X(0), Y(door_h), weight=50)
    acc = 0.0
    for height in heights[:-1]:
        acc += height
        _line(msp, (X(-thick), Y(acc)), (X(0), Y(acc)), layer="HORIZONTALS", weight=18)
    _line(msp, (X(-thick - 6), Y(0)), (X(x_max - 4), Y(0)), weight=25)

    _line(msp, (X(0), Y(0)), (X(0), Y(vert_top)), layer="TRACKS", weight=35)
    _line(msp, (X(track), Y(0)), (X(track), Y(vert_top)), layer="TRACKS", weight=35)
    if not vertical and backroom > radius:
        center = (X(track + radius), Y(arc_start))
        msp.add_arc(
            center, radius * scale, 90, 180,
            dxfattribs={"layer": "TRACKS", "lineweight": 35, "color": 250},
        )
        msp.add_arc(
            center, (radius + track) * scale, 90, 180,
            dxfattribs={"layer": "TRACKS", "lineweight": 35, "color": 250},
        )
        _line(msp, (X(track + radius), Y(y_ust)), (X(backroom), Y(y_ust)),
              layer="TRACKS", weight=35)
        _line(msp, (X(track + radius), Y(y_ust + track)), (X(backroom), Y(y_ust + track)),
              layer="TRACKS", weight=35)
        _line(msp, (X(backroom), Y(y_ust)), (X(backroom), Y(y_ust + track)),
              layer="TRACKS", weight=25)

    if headroom:
        _line(msp, (X(-thick - 2), Y(door_h + headroom)),
              (X(min(18, x_max / 3)), Y(door_h + headroom)), weight=18)

    # Door height and thickness are far from the track, so each gets its
    # own level leader. The clearance figures all live at the head of the
    # track; one leader feeds a stacked block so the lines do not cross.
    _stacked_leaders(msp, [
        (Y(door_h / 2), (X(-thick), Y(door_h / 2)), f"DOOR HEIGHT {fmt_length_imperial(door_h)}"),
        (Y(6.0), (X(-thick / 2), Y(6.0)), f"DOOR {_thickness_label(thick)}"),
    ], bx1 - 0.06)
    clearance = []
    if headroom:
        clearance.append(f"REQ. HEADROOM {fmt_length_imperial(headroom)}")
    if not vertical and hw.floor_to_ust:
        clearance.append(f"UNDERSIDE OF TRACK {fmt_length_imperial(hw.floor_to_ust)}")
    if hl and not vertical:
        clearance.append(f"HI-LIFT {fmt_length_imperial(hl)}")
    if backroom:
        clearance.append(f"BACKROOM {fmt_length_imperial(backroom)}")
    if clearance:
        anchor_y = Y(y_ust if not vertical else vert_top)
        anchor = (X(min(backroom, radius + 8) if not vertical else 12), anchor_y)
        _line(msp, anchor, (bx1 - 1.7, anchor_y), layer="DIMENSIONS", weight=9)
        ty = anchor_y
        for line in clearance:
            _text(msp, line, (bx1 - 0.06, ty), TEXT_SMALL * 0.52, TextEntityAlignment.MIDDLE_RIGHT)
            ty -= 0.15
    _text(msp, "EXTERIOR", (bx0 + 0.06, by0 + 0.08), TEXT_SMALL * 0.5, TextEntityAlignment.MIDDLE_LEFT)
    _text(msp, "INTERIOR", (geo_right, by0 + 0.08), TEXT_SMALL * 0.5, TextEntityAlignment.MIDDLE_RIGHT)


def _stacked_leaders(msp, items, text_x, gap=0.14):
    """Horizontal leaders. Text stacks when two features are closer than a line."""
    placed = []
    ordered = sorted(items, key=lambda item: item[0], reverse=True)
    for feature_y, anchor, text in ordered:
        ty = feature_y
        for prev in placed:
            if prev - gap < ty < prev + gap:
                ty = prev - gap
        placed.append(ty)
        _line(msp, anchor, (text_x - 0.04, ty), layer="DIMENSIONS", weight=9)
        _text(msp, text, (text_x, ty), TEXT_SMALL * 0.52, TextEntityAlignment.MIDDLE_RIGHT)


def annotate_springs(msp, ctx, box) -> None:
    """Fill the blank springs and turns lines. Flag off never calls this."""
    hw = hardware(ctx)
    bx0, by0, bx1, by1 = box
    if hw.wire is not None:
        line = (
            f"SPRINGS {hw.wire:g}\" x {hw.coil_id:g}\" ID x {hw.spring_length:g}\"  "
            f"{hw.lh_count} LH + {hw.rh_count} RH"
        )
    else:
        line = f"SPRINGS — {BY_FACTORY}"
    turns = f"{hw.turns:.1f}" if hw.turns is not None else BY_FACTORY
    drum = hw.drum_model or BY_FACTORY
    _text(msp, line, (bx0 + 0.08, by0 + 0.28), TEXT_SMALL * 0.42, TextEntityAlignment.MIDDLE_LEFT)
    _text(msp, f"TURNS {turns}    DRUM {drum}    {hw.cycles:,} CYCLES",
          (bx0 + 0.08, by0 + 0.12), TEXT_SMALL * 0.42, TextEntityAlignment.MIDDLE_LEFT)
