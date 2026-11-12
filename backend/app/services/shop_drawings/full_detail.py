"""Flag-on elevations, shaft, and track. The section profile is not drawn here.

Track headroom, backroom, and underside of track come from the Thermalex
tables in shop_drawing_service. Spring, drum, and shaft text come from the
parts calculator. A figure with no source is labeled BY FACTORY.
"""
from __future__ import annotations

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


def hardware(ctx) -> ShopHardware:
    cached = getattr(ctx, "_shop_hw", None)
    if cached is None:
        cached = resolve_shop_hardware(ctx)
        ctx._shop_hw = cached
    return cached


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
    msp.add_line(a, b, dxfattribs={"layer": layer, "lineweight": weight})


def _rect(msp, x0, y0, x1, y1, layer="FRAMING", weight=25):
    msp.add_lwpolyline(
        [(x0, y0), (x1, y0), (x1, y1), (x0, y1)],
        close=True,
        dxfattribs={"layer": layer, "lineweight": weight},
    )


def draw_front_detail(msp, ctx, box, view: str = "interior") -> None:
    hw = hardware(ctx)
    x0, y0, x1, y1 = box
    interior = view == "interior"
    door_w = ctx.door_width_in or 96.0
    door_h = ctx.door_height_in or 84.0
    wood = (ctx.jamb_type or "wood") != "steel"
    jamb_w = 5.5 if wood else 3.0
    header_h = 5.5 if wood else 3.0
    section_h = ctx.section_height_in or 21.0
    n_sec = max(3, int(door_h / section_h))
    sec_h = door_h / n_sec
    thick = real_panel_thickness_in(ctx.door_series, ctx.door_type) or 1.75

    title = "INSIDE LOOKING OUT" if interior else "OUTSIDE LOOKING IN"
    _text(msp, f"{ctx.door_series}  {title}", ((x0 + x1) / 2, y1 - 0.14), TEXT_MED)
    _text(
        msp,
        f"{n_sec} SECTIONS @ {fmt_length_imperial(sec_h)}    {ctx.panel_design}    {ctx.panel_color or 'WHITE'}",
        ((x0 + x1) / 2, y1 - 0.32),
        TEXT_SMALL * 0.8,
    )

    # The shaft is a separate strip above the door so its labels are not
    # scaled down with a 16 ft opening.
    top_reserve = 1.85 if interior else 0.55
    bot_reserve = 0.55
    overhead = max((hw.headroom or 0) - header_h, 4.0) + 2.0
    span_w = door_w + 2 * jamb_w + (24 if interior else 8)
    span_h = door_h + header_h + overhead
    scale = min((x1 - x0 - 0.3) / span_w, (y1 - y0 - top_reserve - bot_reserve) / span_h)
    ox = x0 + 0.2 + max(((x1 - x0 - 0.3) - span_w * scale) / 2, 0)
    oy = y0 + bot_reserve

    def X(inches):
        return ox + inches * scale

    def Y(inches):
        return oy + inches * scale

    # Opening, then the framing member outside it.
    open_x0 = jamb_w
    open_x1 = jamb_w + door_w
    _rect(msp, X(0), Y(0), X(jamb_w), Y(door_h), weight=35)
    _rect(msp, X(open_x1), Y(0), X(open_x1 + jamb_w), Y(door_h), weight=35)
    _rect(msp, X(0), Y(door_h), X(open_x1 + jamb_w), Y(door_h + header_h), weight=35)
    _rect(msp, X(open_x0), Y(0), X(open_x1), Y(door_h), weight=40)
    member = '2x6' if wood else '3" ANGLE'
    _text(msp, member, (X(jamb_w / 2), Y(door_h * 0.22)), TEXT_SMALL * 0.55)
    _text(msp, f"HEADER {member}", (X(open_x0 + door_w / 2), Y(door_h + header_h / 2)), TEXT_SMALL * 0.6)

    for i in range(1, n_sec):
        _line(msp, (X(open_x0), Y(sec_h * i)), (X(open_x1), Y(sec_h * i)), weight=18)
    if ctx.has_windows and ctx.window_positions:
        for pos in ctx.window_positions:
            sec = int(pos.get("section", 0))
            col = int(pos.get("col", 0))
            wy0 = sec_h * sec + sec_h * 0.25
            wy1 = wy0 + sec_h * 0.45
            wx0 = open_x0 + door_w * (col + 0.25) / 4
            wx1 = wx0 + door_w * 0.18
            _rect(msp, X(wx0), Y(wy0), X(wx1), Y(wy1), layer="ANNOTATIONS", weight=13)
    elif ctx.has_windows:
        _text(msp, f"WINDOWS — {BY_FACTORY}", (X(open_x0 + door_w / 2), Y(door_h * 0.5)), TEXT_SMALL * 0.7)

    # Struts from the Thermalex chart. Zero is a real answer, not a placeholder.
    if hw.strut_count <= 0:
        _text(msp, f"STRUTS: NONE ({hw.strut_gauge or '20ga'} CHART)",
              (X(open_x0 + door_w / 2), Y(door_h * 0.5)), TEXT_SMALL * 0.55)
    else:
        gauge = (hw.strut_gauge or "20ga").upper()
        for i in range(min(hw.strut_count, n_sec)):
            yy = sec_h * i + sec_h * 0.55
            _line(msp, (X(open_x0 + 2), Y(yy)), (X(open_x1 - 2), Y(yy)), layer="STRUTS", weight=30)
        _text(msp, f"{hw.strut_count} {gauge} STRUTS",
              (X(open_x0 + 4), Y(sec_h * 0.2)), TEXT_SMALL * 0.55,
              TextEntityAlignment.MIDDLE_LEFT)

    n_cols = _hinge_columns(door_w)
    hinge_xs = []
    for k in range(n_cols):
        t = k / (n_cols - 1) if n_cols > 1 else 0.5
        hinge_xs.append(open_x0 + 3.5 + (door_w - 7) * t)
    for joint in range(1, n_sec):
        for n, hx in enumerate(hinge_xs, start=1):
            s = 1.1
            _rect(msp, X(hx - s), Y(sec_h * joint - 0.6), X(hx + s), Y(sec_h * joint + 0.6),
                  layer="HARDWARE", weight=18)
            if joint == 1:
                _text(msp, str(n), (X(hx), Y(sec_h + 2.2)), TEXT_SMALL * 0.5)

    # Bottom bracket and top fixture. Models are not in the parts list.
    for edge in (open_x0, open_x1 - 4):
        _rect(msp, X(edge), Y(0.4), X(edge + 4), Y(3.2), layer="HARDWARE", weight=25)
    _text(msp, f"BOTTOM BRACKET — {BY_FACTORY}",
          (X(open_x0 + 5), Y(sec_h * 0.55)), TEXT_SMALL * 0.5, TextEntityAlignment.MIDDLE_LEFT)
    for edge in (open_x0, open_x1 - 3):
        _rect(msp, X(edge), Y(door_h - 3), X(edge + 3), Y(door_h - 0.3), layer="HARDWARE", weight=25)
    _text(msp, f"TOP FIXTURE — {BY_FACTORY}",
          (X(open_x0 + 4), Y(door_h - sec_h * 0.45)), TEXT_SMALL * 0.5,
          TextEntityAlignment.MIDDLE_LEFT)

    # Vertical tracks and brackets just outside the jambs.
    track = float(hw.track_size)
    for side in (-track - 0.5, open_x1 + jamb_w + 0.5):
        _rect(msp, X(side), Y(0), X(side + track), Y(door_h), layer="TRACKS", weight=18)
    bracket_note = f"TRACK BRACKET — {BY_FACTORY}"
    yb = 24.0
    while yb < door_h - 6:
        _line(msp, (X(-track - 1.6), Y(yb)), (X(0), Y(yb)), layer="HARDWARE", weight=13)
        _line(msp, (X(open_x1 + jamb_w), Y(yb)), (X(open_x1 + jamb_w + track + 1.1), Y(yb)),
              layer="HARDWARE", weight=13)
        yb += 24.0
    _text(msp, bracket_note, (X(open_x1 - 2), Y(door_h * 0.72)),
          TEXT_SMALL * 0.45, TextEntityAlignment.MIDDLE_RIGHT)

    _text(msp, "JAMB", (X(jamb_w / 2), Y(-3)), TEXT_SMALL * 0.7)
    _text(msp, "JAMB", (X(open_x1 + jamb_w / 2), Y(-3)), TEXT_SMALL * 0.7)
    _text(msp, fmt_length_dual(door_w), (X(open_x0 + door_w / 2), Y(-6)), TEXT_SMALL * 0.75)
    _text(msp, fmt_length_dual(door_h), (X(open_x1 + jamb_w + 8), Y(door_h / 2)), TEXT_SMALL * 0.7)

    # Headroom above the header, from the Thermalex table.
    if hw.headroom:
        ceil = door_h + header_h + max(hw.headroom - header_h, 1)
        _line(msp, (X(0), Y(ceil)), (X(open_x1 + jamb_w), Y(ceil)), weight=18)
        _text(
            msp,
            f"REQ. HEADROOM {fmt_length_imperial(hw.headroom)}",
            (X(open_x0 + door_w / 2), Y(door_h + header_h + (ceil - door_h - header_h) / 2)),
            TEXT_SMALL * 0.65,
        )

    if not interior:
        return

    cable = f'{hw.cable_diameter:g}"' if hw.cable_diameter else BY_FACTORY
    for edge in (open_x0 + 1.5, open_x1 - 1.5):
        _line(msp, (X(edge), Y(door_h - 1)), (X(edge), Y(2.5)), layer="HARDWARE", weight=13)
    _text(msp, f"CABLE {cable}", (X(open_x0 + 3), Y(door_h * 0.62)),
          TEXT_SMALL * 0.5, TextEntityAlignment.MIDDLE_LEFT)
    _draw_shaft_strip(msp, hw, x0 + 0.12, y1 - 1.72, x1 - 0.12, y1 - 0.48)


def _draw_shaft_strip(msp, hw: ShopHardware, x0, y0, x1, y1):
    """Shaft, springs and drums at true relative length, in a sheet-space strip.

    Spring length and OD are scaled with the shaft, not with the door, so a
    30 in. spring stays readable on a 16 ft opening.
    """
    length = hw.shaft_length or 0
    if length <= 0:
        _text(msp, f"SHAFT — {BY_FACTORY}", ((x0 + x1) / 2, (y0 + y1) / 2), TEXT_SMALL * 0.6)
        return
    pad = 0.15
    scale = (x1 - x0 - 2 * pad) / length
    cy = (y0 + y1) / 2 - 0.02

    def X(inches):
        return x0 + pad + inches * scale

    dia = hw.shaft_diameter or 1.0
    bar = max(dia * scale * 2.2, 0.035)
    _rect(msp, X(0), cy - bar / 2, X(length), cy + bar / 2, layer="HARDWARE", weight=25)
    kind = hw.shaft_kind or BY_FACTORY
    shown = fmt_length_imperial(length) if hw.shaft_length else BY_FACTORY
    _text(msp, f"SHAFT {kind}  {shown}", ((x0 + x1) / 2, y1 - 0.06), TEXT_SMALL * 0.48)

    od_in = (hw.coil_id or 2.0) + (hw.wire or 0.25)
    span = hw.spring_length or 0
    od = max(od_in * scale * 3.5, 0.09)
    gap = 3.0
    cx = length / 2
    if hw.lh_count and span:
        _coil_sheet(msp, X(cx - gap - span), X(cx - gap), cy, od)
        _text(msp, "LH", (X(cx - gap - span / 2), cy + od + 0.07), TEXT_SMALL * 0.42)
    if hw.rh_count and span:
        _coil_sheet(msp, X(cx + gap), X(cx + gap + span), cy, od)
        _text(msp, "RH", (X(cx + gap + span / 2), cy + od + 0.07), TEXT_SMALL * 0.42)
    _rect(msp, X(cx) - 0.05, cy - od, X(cx) + 0.05, cy + od, layer="HARDWARE", weight=30)

    drum_d = hw.drum_diameter or 4.0
    drum_w = max(drum_d * 0.85, 3.0)
    for end in (drum_w, length - drum_w):
        _drum_sheet(msp, X(end), cy, max(drum_d * scale * 3.2, 0.16), max(drum_w * scale, 0.10))
        # End bearing plate just outboard of the drum.
        _rect(msp, X(end) - 0.035, cy - od * 1.35, X(end) + 0.035, cy + od * 1.35,
              layer="HARDWARE", weight=30)
    model = hw.drum_model or BY_FACTORY
    dia_note = f'{drum_d:g}"' if hw.drum_diameter else BY_FACTORY
    if span and hw.wire and hw.coil_id:
        turns = f"{hw.turns:.1f} TURNS" if hw.turns is not None else BY_FACTORY
        spring = f'LH/RH {hw.wire:g}" x {hw.coil_id:g}" ID x {span:g}"  {turns}'
    else:
        spring = f"SPRINGS — {BY_FACTORY}"
    _text(msp, f"DRUM {model} {dia_note}", ((x0 + x1) / 2, y0 + 0.20), TEXT_SMALL * 0.42)
    _text(msp, spring, ((x0 + x1) / 2, y0 + 0.06), TEXT_SMALL * 0.42)
    _text(msp, f"END BRG / CTR BRKT — {BY_FACTORY}", (x1 - 0.02, y1 - 0.20),
          TEXT_SMALL * 0.38, TextEntityAlignment.MIDDLE_RIGHT)


def _coil_sheet(msp, x0, x1, cy, od):
    _line(msp, (x0, cy + od / 2), (x1, cy + od / 2), layer="HARDWARE", weight=18)
    _line(msp, (x0, cy - od / 2), (x1, cy - od / 2), layer="HARDWARE", weight=18)
    _line(msp, (x0, cy - od / 2), (x0, cy + od / 2), layer="HARDWARE", weight=25)
    _line(msp, (x1, cy - od / 2), (x1, cy + od / 2), layer="HARDWARE", weight=25)
    steps = 8
    span = x1 - x0
    for i in range(steps):
        xa = x0 + span * i / steps
        xb = x0 + span * (i + 1) / steps
        ya = cy - od / 2 if i % 2 == 0 else cy + od / 2
        yb = cy + od / 2 if i % 2 == 0 else cy - od / 2
        _line(msp, (xa, ya), (xb, yb), layer="HARDWARE", weight=13)


def _drum_sheet(msp, cx, cy, diameter, width):
    """Stepped cable drum: narrow barrel, wider flanges."""
    flange = diameter
    barrel = diameter * 0.62
    _rect(msp, cx - width / 2, cy - flange / 2, cx - width / 2 + width * 0.18,
          cy + flange / 2, layer="HARDWARE", weight=25)
    _rect(msp, cx + width / 2 - width * 0.18, cy - flange / 2, cx + width / 2,
          cy + flange / 2, layer="HARDWARE", weight=25)
    _rect(msp, cx - width * 0.32, cy - barrel / 2, cx + width * 0.32,
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
    headroom = hw.headroom if hw.headroom is not None else (door_h + 18 if vertical else radius + 6)
    backroom = hw.backroom if hw.backroom is not None else (18 if vertical else door_h + 18)
    ust = hw.ust if hw.ust is not None else (0 if vertical else (hl if hl else 6.5))
    # Vertical track rises by the high-lift amount. The horizontal
    # underside then sits `ust` above the opening, which already includes
    # that high lift in the Thermalex table.
    y_ust = door_h + ust
    # The ordered radius turns the vertical track into the horizontal rail,
    # and the rail lands on the published underside (the high-lift amount
    # when this is a high-lift door). The straight vertical therefore
    # stops one radius below that underside.
    arc_start = y_ust - radius
    vert_top = door_h + headroom if vertical else max(arc_start, 0)
    view_w = max(backroom, 24) + thick + 30
    view_h = max(y_ust + track, door_h + headroom, vert_top) + 18
    scale = min((bx1 - bx0) * 0.78 / view_w, (by1 - by0) * 0.72 / view_h)
    ox = bx0 + (bx1 - bx0) * 0.16
    oy = by0 + 0.35

    def X(inches):
        return ox + inches * scale

    def Y(inches):
        return oy + inches * scale

    if vertical:
        label = f'{int(track)}" FULL VERTICAL LIFT'
    elif hl:
        label = f'{int(radius)}"R {int(track)}" HIGH LIFT'
    else:
        label = f'{int(radius)}"R {int(track)}" STANDARD LIFT'
    _text(msp, label, ((bx0 + bx1) / 2, by1 - 0.12), TEXT_MED)

    # Door at the series thickness.
    _rect(msp, X(-thick), Y(0), X(0), Y(door_h), weight=35)
    _line(msp, (X(-thick - 4), Y(0)), (X(backroom), Y(0)), weight=25)
    # Two-line track. The inner rail is the ordered radius; the outer rail
    # is one track size larger, so the pair reads as a 2" or 3" section.
    _line(msp, (X(0), Y(0)), (X(0), Y(vert_top)), layer="TRACKS", weight=18)
    _line(msp, (X(track), Y(0)), (X(track), Y(vert_top)), layer="TRACKS", weight=18)
    if not vertical and backroom > radius:
        center = (X(track + radius), Y(arc_start))
        r_in = radius * scale
        r_out = (radius + track) * scale
        msp.add_arc(center, r_in, 90, 180, dxfattribs={"layer": "TRACKS", "lineweight": 18})
        msp.add_arc(center, r_out, 90, 180, dxfattribs={"layer": "TRACKS", "lineweight": 18})
        _line(msp, (X(track + radius), Y(y_ust)), (X(backroom), Y(y_ust)), layer="TRACKS", weight=18)
        _line(msp, (X(track + radius), Y(y_ust + track)), (X(backroom), Y(y_ust + track)), layer="TRACKS", weight=18)
        _line(msp, (X(backroom), Y(y_ust)), (X(backroom), Y(y_ust + track)), layer="TRACKS", weight=25)
    elif vertical:
        _line(msp, (X(0), Y(vert_top)), (X(18), Y(vert_top)), layer="TRACKS", weight=18)
        _text(msp, f"BACKROOM {fmt_length_imperial(backroom)}",
              (X(10), Y(vert_top + 4)), TEXT_SMALL * 0.65)

    ceil = door_h + headroom
    _line(msp, (X(-thick - 2), Y(ceil)), (X(min(backroom, 36) if not vertical else 20), Y(ceil)), weight=18)
    # Notes sit in the right margin. At door scale a 12 ft opening makes
    # an inch of text taller than a foot of track, so leaders on the
    # radius collide.
    notes = [
        f"REQ. HEADROOM {fmt_length_imperial(headroom)}",
        f"DOOR HEIGHT {fmt_length_imperial(door_h)}",
        f"DOOR {_thickness_label(thick)}",
    ]
    if not vertical and hw.floor_to_ust:
        notes.append(f"UNDERSIDE OF TRACK {fmt_length_imperial(hw.floor_to_ust)}")
    if backroom:
        notes.append(f"BACKROOM {fmt_length_imperial(backroom)}")
    if hl and not vertical:
        notes.append(f"HI-LIFT {fmt_length_imperial(hl)}")
    ny = by1 - 0.36
    for line in notes:
        _text(msp, line, (bx1 - 0.08, ny), TEXT_SMALL * 0.62, TextEntityAlignment.MIDDLE_RIGHT)
        ny -= 0.16
    _text(msp, "EXTERIOR", (bx0 + 0.08, by0 + 0.10), TEXT_SMALL * 0.55, TextEntityAlignment.MIDDLE_LEFT)
    _text(msp, "INTERIOR", (bx1 - 0.08, by0 + 0.10), TEXT_SMALL * 0.55, TextEntityAlignment.MIDDLE_RIGHT)


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
