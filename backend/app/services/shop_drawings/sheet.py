"""11×17 shop-drawing sheet.

One function per view. Every dimension string comes from ``DoorDrawingSpec``
so the PDF text and the tests read the same clearance, stack, and spring
schedule. Geometry is NTS, matching the sample sheets. Drop-in DXF profiles
replace the hand-built joint and jamb when those files are present.
"""

from __future__ import annotations

from ezdxf.document import Drawing

from app.services.shop_drawings.profiles import (
    draw_parametric_panorama,
    draw_parametric_steel,
    import_profile_block,
    panorama_stack_size,
    steel_stack_size,
)
from app.services.shop_drawings.sheet_geom import (
    checkbox,
    dim_h,
    dim_v,
    leader,
    text,
    view_frame,
)
from app.services.shop_drawings.spec import DoorDrawingSpec

# Sheet inches. The border sits inside the 17×11 paper.
_LEFT = 0.28
_RIGHT = 16.72
_BOTTOM = 0.22
_TOP = 10.78


def draw_sheet(doc: Drawing, spec: DoorDrawingSpec) -> None:
    msp = doc.modelspace()
    msp.add_lwpolyline(
        [(_LEFT, _BOTTOM), (_RIGHT, _BOTTOM), (_RIGHT, _TOP), (_LEFT, _TOP)],
        close=True,
        dxfattribs={"layer": "BORDER"},
    )
    text(msp, "NTS", _RIGHT - 0.28, _TOP - 0.12, 0.06, "mr", "ANNOTATIONS")

    col_x0 = 12.58
    col_x1 = _RIGHT - 0.06
    checklist = (col_x0, 6.02, col_x1, _TOP - 0.06)
    schedules = (col_x0, 3.12, col_x1, 5.92)
    title = (col_x0, _BOTTOM + 0.06, col_x1, 3.02)

    area_x0 = _LEFT + 0.04
    area_x1 = col_x0 - 0.10
    top = (5.52, _TOP - 0.06)
    bot = (_BOTTOM + 0.06, 5.40)

    if spec.show_outside_face:
        inside = (area_x0, top[0], 4.55, top[1])
        outside = (4.65, top[0], 7.55, top[1])
        detail = (7.65, top[0], area_x1, top[1])
    else:
        inside = (area_x0, top[0], 7.72, top[1])
        outside = None
        detail = (7.82, top[0], area_x1, top[1])
    jamb = (area_x0, bot[0], 6.05, bot[1])
    track = (6.15, bot[0], area_x1, bot[1])

    _inside_face(msp, inside, spec)
    if outside:
        _outside_face(msp, outside, spec)
    _panel_detail(msp, detail, spec)
    _checklist(msp, checklist, spec)
    _jamb_plan(msp, jamb, spec)
    _track_elevation(msp, track, spec)
    _schedules(msp, schedules, spec)
    _title_block(msp, title, spec)


# ─── [A] inside face ────────────────────────────────────────────────────────

def _inside_face(msp, box, spec: DoorDrawingSpec):
    x0, y0, x1, y1 = box
    view_frame(msp, box, "DOOR FACE: INSIDE LOOKING OUT")
    # Title underline is near the top of the frame. The shaft dimensions sit
    # under it, then the door fills the rest of the view.
    cx0, cx1 = x0 + 1.05, x1 - 0.95
    # Leave the top of the frame for the title. Shaft dims sit under it.
    dy1_cap = y1 - 1.62
    dy0_min = y0 + 0.58
    avail_w = cx1 - cx0
    avail_h = dy1_cap - dy0_min
    if avail_w < 0.5 or avail_h < 0.5 or spec.height_in <= 0:
        return
    scale = min(avail_w / spec.width_in, avail_h / spec.height_in)
    door_w = spec.width_in * scale
    door_h = spec.height_in * scale
    dx0 = cx0 + (avail_w - door_w) / 2
    dy1 = dy0_min + door_h
    dy0 = dy0_min
    dx1 = dx0 + door_w
    shaft_y = dy1 + 0.16

    y = dy0
    for index, height in enumerate(spec.section_heights):
        sh = height / spec.height_in * door_h
        msp.add_lwpolyline(
            [(dx0, y), (dx1, y), (dx1, y + sh), (dx0, y + sh)],
            close=True,
            dxfattribs={"layer": "FRAMING"},
        )
        ribs = 7 if height >= 20 else 4
        for r in range(1, ribs + 1):
            ry = y + sh * r / (ribs + 1)
            msp.add_line((dx0 + 0.03, ry - 0.012), (dx1 - 0.03, ry - 0.012),
                         dxfattribs={"layer": "HORIZONTALS"})
            msp.add_line((dx0 + 0.03, ry + 0.012), (dx1 - 0.03, ry + 0.012),
                         dxfattribs={"layer": "HORIZONTALS"})
        sec = index + 1  # from the bottom
        if spec.joint == "panorama":
            _glazed_section(msp, dx0, y, door_w, sh)
        elif sec in spec.windows.per_section_qty:
            _window_row(msp, dx0, y, door_w, sh, spec.windows.per_section_qty[sec],
                        full=spec.windows.full_section)
        if index < len(spec.section_heights) - 1:
            _hinge_marks(msp, dx0, dx1, y + sh)
        y += sh

    # Vertical track lines and a roller at each end of the bottom and top.
    for edge in (dx0 - 0.05, dx1 + 0.05):
        msp.add_line((edge, dy0), (edge, dy1), dxfattribs={"layer": "TRACKS"})
    for yy in (dy0 + 0.06, dy1 - 0.06):
        msp.add_circle((dx0 - 0.05, yy), 0.035, dxfattribs={"layer": "HARDWARE"})
        msp.add_circle((dx1 + 0.05, yy), 0.035, dxfattribs={"layer": "HARDWARE"})

    shaft_y = dy1 + 0.62
    _shaft_line(msp, dx0, dx1, shaft_y, spec)

    dim_v(
        msp, dy0, shaft_y, x0 + 0.58,
        ["CENTERLINE", "OF SHAFT", spec.cl_shaft_text],
        side="left", ext=dx0,
    )
    dim_v(
        msp, dy0, dy1, dx1 + 0.42,
        ["DOOR", "HEIGHT", spec.door_height_text],
        side="right", ext=dx1,
    )
    dim_h(msp, dx0, dx1, dy0 - 0.28, spec.door_width_text, ext=dy0)
    text(msp, "DOOR WIDTH", (dx0 + dx1) / 2, dy0 - 0.48, 0.07, "mc", "DIMENSIONS")


def _window_row(msp, x, y, w, h, count, full=False):
    count = max(1, min(int(count), 8))
    margin = w * 0.08
    gap = w * 0.03
    ww = (w - 2 * margin - gap * (count - 1)) / count
    wh = h * (0.78 if full else 0.68)
    wy = y + (h - wh) / 2
    for i in range(count):
        wx = x + margin + i * (ww + gap)
        solid = msp.add_solid(
            [(wx, wy), (wx + ww, wy), (wx, wy + wh), (wx + ww, wy + wh)],
            dxfattribs={"layer": "GLAZING"},
        )
        solid.rgb = (170, 210, 230)
        msp.add_lwpolyline(
            [(wx, wy), (wx + ww, wy), (wx + ww, wy + wh), (wx, wy + wh)],
            close=True,
            dxfattribs={"layer": "FRAMING"},
        )


def _glazed_section(msp, x, y, w, h):
    rail = min(0.07, h * 0.16)
    # Top and bottom rails
    for ry in (y, y + h - rail):
        msp.add_lwpolyline(
            [(x, ry), (x + w, ry), (x + w, ry + rail), (x, ry + rail)],
            close=True,
            dxfattribs={"layer": "FRAMING"},
        )
    glass = msp.add_solid(
        [(x + 0.04, y + rail), (x + w - 0.04, y + rail),
         (x + 0.04, y + h - rail), (x + w - 0.04, y + h - rail)],
        dxfattribs={"layer": "GLAZING"},
    )
    glass.rgb = (186, 204, 214)
    n = max(2, int(w / 0.7))
    for i in range(n + 1):
        sx = x + w * i / n
        msp.add_line((sx, y + rail), (sx, y + h - rail), dxfattribs={"layer": "FRAMING"})


def _hinge_marks(msp, x0, x1, y):
    span = x1 - x0
    cols = 2 if span < 2.2 else 3 if span < 3.6 else 4
    for i in range(cols):
        hx = x0 + span * (i + 1) / (cols + 1)
        msp.add_circle((hx - 0.05, y), 0.028, dxfattribs={"layer": "HARDWARE"})
        msp.add_circle((hx + 0.05, y), 0.028, dxfattribs={"layer": "HARDWARE"})
        msp.add_line((hx - 0.05, y), (hx + 0.05, y), dxfattribs={"layer": "HARDWARE"})


def _shaft_line(msp, x0, x1, y, spec: DoorDrawingSpec):
    msp.add_line((x0 - 0.16, y), (x1 + 0.16, y), dxfattribs={"layer": "HARDWARE", "lineweight": 50})
    for edge in (x0, x1):
        msp.add_circle((edge, y), 0.13, dxfattribs={"layer": "HARDWARE"})
        msp.add_circle((edge, y), 0.04, dxfattribs={"layer": "HARDWARE"})
        msp.add_lwpolyline(
            [(edge - 0.05, y - 0.20), (edge + 0.05, y - 0.20),
             (edge + 0.05, y + 0.20), (edge - 0.05, y + 0.20)],
            close=True,
            dxfattribs={"layer": "HARDWARE"},
        )
    mid = (x0 + x1) / 2
    gap = 0.22
    left = [s for s in spec.springs if s.hand == "LHW"]
    right = [s for s in spec.springs if s.hand == "RHW"]
    _coil_group(msp, x0 + 0.22, mid - gap, y, _coil_count(left))
    _coil_group(msp, mid + gap, x1 - 0.22, y, _coil_count(right))
    if spec.coupler:
        msp.add_circle((mid, y), 0.055, dxfattribs={"layer": "HARDWARE"})
        msp.add_line((mid - 0.09, y - 0.09), (mid + 0.09, y + 0.09),
                     dxfattribs={"layer": "HARDWARE"})
    dim_h(msp, mid - gap, mid + gap, y + 0.20, '6"', ext=y + 0.08)
    text(msp, "SPRING PADS", mid - 0.72, y + 0.34, 0.058, "mc", "DIMENSIONS")
    dim_h(msp, mid, x1, y + 0.42, spec.half_shaft_text, ext=y + 0.12)
    text(msp, '3" FRAME', x0 - 0.15, y + 0.34, 0.060, "mc", "DIMENSIONS")
    if spec.drum_model:
        text(msp, f"DRUM {spec.drum_model}", x1, y - 0.28, 0.06, "mr", "ANNOTATIONS")


def _coil_count(lines) -> int:
    if not lines:
        return 1
    return max(1, min(4, sum(s.count for s in lines)))


def _coil_group(msp, x0, x1, y, count):
    if x1 - x0 < 0.15:
        return
    width = (x1 - x0) / count
    for i in range(count):
        a = x0 + i * width + 0.02
        b = x0 + (i + 1) * width - 0.03
        _zigzag(msp, a, b, y, amp=0.08)
        msp.add_circle((b, y), 0.045, dxfattribs={"layer": "HARDWARE"})


def _zigzag(msp, x0, x1, y, amp):
    n = max(10, int((x1 - x0) / 0.028))
    pts = []
    for i in range(n + 1):
        x = x0 + (x1 - x0) * i / n
        yy = y + (amp if i % 2 else -amp)
        pts.append((x, yy))
    msp.add_lwpolyline(pts, dxfattribs={"layer": "HARDWARE"})


# ─── [B] outside face ───────────────────────────────────────────────────────

def _outside_face(msp, box, spec: DoorDrawingSpec):
    x0, y0, x1, y1 = box
    colour = (spec.color or "WHITE").replace("_", " ").upper()
    title = "DOOR FACE: OUTSIDE LOOKING IN"
    if spec.finish == "flush":
        title = f"DOOR FACE: OUTSIDE LOOKING IN - FLUSH {colour}"
    view_frame(msp, box, None)
    text(msp, title, (x0 + x1) / 2, y1 - 0.10, 0.055, "tc", "ANNOTATIONS", style="BOLD")

    # Brick pier each side, slab below, door between.
    dx0, dy0 = x0 + 0.55, y0 + 0.55
    dx1, dy1 = x1 - 0.22, y1 - 0.42
    door_w = (dx1 - dx0) * 0.72
    door_h = (dy1 - dy0) * 0.82
    ox = dx0 + ((dx1 - dx0) - door_w) / 2
    oy = dy0 + 0.22
    _brick_field(msp, dx0, oy, ox, oy + door_h)
    _brick_field(msp, ox + door_w, oy, dx1, oy + door_h)
    _brick_field(msp, dx0, oy + door_h, dx1, dy1)
    # Slab
    for i in range(6):
        msp.add_line((dx0, oy - 0.04 - i * 0.03), (dx1, oy - 0.02 - i * 0.03),
                     dxfattribs={"layer": "HATCH"})
    text(msp, "SLAB", (dx0 + dx1) / 2, oy - 0.16, 0.05, "mc", "ANNOTATIONS")

    rgb = _color_rgb(spec.color)
    y = oy
    for index, height in enumerate(spec.section_heights):
        sh = height / spec.height_in * door_h
        if spec.joint == "panorama":
            _glazed_section(msp, ox, y, door_w, sh)
        else:
            if rgb and spec.finish == "flush":
                solid = msp.add_solid(
                    [(ox, y), (ox + door_w, y), (ox, y + sh), (ox + door_w, y + sh)],
                    dxfattribs={"layer": "FRAMING"},
                )
                solid.rgb = rgb
            msp.add_lwpolyline(
                [(ox, y), (ox + door_w, y), (ox + door_w, y + sh), (ox, y + sh)],
                close=True,
                dxfattribs={"layer": "FRAMING"},
            )
        y += sh


def _brick_field(msp, x0, y0, x1, y1):
    if x1 - x0 < 0.08 or y1 - y0 < 0.08:
        return
    brick_h = 0.09
    brick_w = 0.18
    row = 0
    y = y0
    while y < y1:
        x = x0 + (brick_w / 2 if row % 2 else 0)
        while x < x1:
            msp.add_lwpolyline(
                [(x, y), (min(x + brick_w, x1), y),
                 (min(x + brick_w, x1), min(y + brick_h, y1)), (x, min(y + brick_h, y1))],
                close=True,
                dxfattribs={"layer": "HATCH"},
            )
            x += brick_w
        y += brick_h
        row += 1


def _color_rgb(name: str):
    key = (name or "").upper().replace(" ", "_")
    return {
        "BLACK": (30, 30, 30),
        "BROWN": (92, 58, 36),
        "BRONZE": (120, 84, 48),
        "SANDTONE": (198, 170, 128),
        "CHOCOLATE": (70, 42, 28),
        "ESPRESSO": (48, 32, 24),
        "CLEAR_ANODIZED": (176, 184, 188),
        "DARK_BRONZE": (72, 56, 40),
    }.get(key)


# ─── [C] panel detail ───────────────────────────────────────────────────────

def _panel_detail(msp, box, spec: DoorDrawingSpec):
    x0, y0, x1, y1 = box
    title = spec.joint_title if spec.joint == "panorama" else "SIDE VIEW ILLUSTRATION"
    view_frame(msp, box, title)
    if spec.joint != "panorama":
        text(msp, spec.joint_title, (x0 + x1) / 2, y1 - 0.38, 0.08, "mc", "ANNOTATIONS", style="BOLD")
    text(msp, "Exterior", x0 + 0.72, y1 - 0.52, 0.09, "mc", "ANNOTATIONS", style="ITALIC")
    text(msp, "Interior", x0 + 1.90, y1 - 0.52, 0.09, "mc", "ANNOTATIONS", style="ITALIC")

    content_top = y1 - 0.68
    content_bot = y0 + 0.10
    T = spec.thickness_in
    real_w, real_h = panorama_stack_size(T) if spec.joint == "panorama" else steel_stack_size(T)
    # The section fills the height. Callouts sit immediately to its right.
    icon_w = 0.28
    callout_w = 1.85
    avail_w = (x1 - x0) - icon_w - callout_w - 0.20
    avail_h = content_top - content_bot
    scale = min(avail_w / real_w, avail_h / real_h)
    scale = max(0.35, scale)
    drawn_h = real_h * scale
    ox = x0 + icon_w
    oy = content_bot + max(0.0, (avail_h - drawn_h) / 2)

    block = import_profile_block(msp.doc, spec.joint)
    anchors = []
    if block:
        msp.add_blockref(
            block, (ox, oy),
            dxfattribs={"xscale": scale, "yscale": scale, "layer": "FRAMING"},
        )
    elif spec.joint == "panorama":
        anchors = draw_parametric_panorama(msp, spec, (ox, oy), scale) or []
    else:
        anchors = draw_parametric_steel(msp, spec, (ox, oy), scale) or []

    # Thickness sits across the foam, the way the sample sheets dimension it.
    dim_h(
        msp, ox + 0.02, ox + max(0.2, T * scale - 0.02),
        oy + drawn_h * 0.58, spec.thickness_text, text_h=0.08,
    )
    _place_leaders(msp, anchors, ox, oy, scale, x1 - callout_w, content_bot + 0.05, content_top - 0.05)
    _weather_icons(msp, x0 + 0.12, oy + drawn_h * 0.45)


def _place_leaders(msp, anchors, ox, oy, scale, text_x, y_bot, y_top):
    """Keep each callout next to its part, with an arrow on the part."""
    items = []
    for anchor in anchors:
        ax, ay, lines = anchor
        items.append({
            "x": ox + ax * scale,
            "y": oy + ay * scale,
            "lines": tuple(lines),
            "h": len(lines) * 0.070,
        })
    items.sort(key=lambda item: -item["y"])
    cursor = y_top
    for item in items:
        preferred = item["y"] + item["h"] / 2
        top = min(cursor, preferred)
        top = max(top, y_bot + item["h"])
        if top > cursor:
            top = cursor
        item["cy"] = top - item["h"] / 2
        cursor = top - item["h"] - 0.04
        leader(msp, (item["x"], item["y"]), text_x, item["cy"], item["lines"], text_h=0.060)


def _weather_icons(msp, x, y):
    import math
    # Sun
    msp.add_circle((x, y + 0.55), 0.05, dxfattribs={"layer": "ANNOTATIONS"})
    for i in range(8):
        a = math.radians(i * 45)
        msp.add_line(
            (x + math.cos(a) * 0.07, y + 0.55 + math.sin(a) * 0.07),
            (x + math.cos(a) * 0.11, y + 0.55 + math.sin(a) * 0.11),
            dxfattribs={"layer": "ANNOTATIONS"},
        )
    # Snowflake
    for ang in (90, 30, -30):
        a = math.radians(ang)
        msp.add_line(
            (x - math.cos(a) * 0.08, y - math.sin(a) * 0.08),
            (x + math.cos(a) * 0.08, y + math.sin(a) * 0.08),
            dxfattribs={"layer": "ANNOTATIONS"},
        )
    # Drop
    msp.add_circle((x, y - 0.55), 0.045, dxfattribs={"layer": "ANNOTATIONS"})
    msp.add_line((x, y - 0.50), (x, y - 0.38), dxfattribs={"layer": "ANNOTATIONS"})


# ─── [D] checklist ──────────────────────────────────────────────────────────

def _checklist(msp, box, spec: DoorDrawingSpec):
    x0, y0, x1, y1 = box
    view_frame(msp, box, None)
    rows = _checklist_rows(spec)
    top = y1 - 0.08
    bot = y0 + 0.06
    row_h = min(0.118, (top - bot) / max(1, len(rows)))
    y = top - row_h
    for kind, label, checked in rows:
        if kind == "header":
            text(msp, label, x0 + 0.08, y, 0.072, "ml", "ANNOTATIONS", style="BOLD")
        else:
            box = min(0.095, row_h * 0.72)
            checkbox(msp, x0 + 0.08, y - box * 0.35, bool(checked), size=box)
            text(msp, label, x0 + 0.08 + box + 0.06, y, 0.064, "ml", "ANNOTATIONS")
        y -= row_h
        if y < bot:
            break


def _checklist_rows(spec: DoorDrawingSpec):
    cycles = spec.spring_cycles or 10000
    rows = [
        ("check", '2" TRACK APPLICATION', spec.track_size == 2),
        ("check", '3" TRACK APPLICATION', spec.track_size == 3),
        ("check", "STEEL FRAME", spec.frame == "steel"),
        ("check", "WOOD FRAME", spec.frame == "wood"),
        ("check", "BRACKET MOUNT", spec.mount == "bracket"),
        ("check", "CONTINUOUS ANGLE MOUNT", spec.mount == "angle"),
        ("check", "SINGLE END STILES/HINGES", not spec.double_end_stiles),
        ("check", "DOUBLE END STILES/HINGES", spec.double_end_stiles),
        ("header", "OPTIONAL EXTRAS", None),
        ("check", f"16GA STRUTS  {spec.struts_16 or '________'}", spec.struts_16 > 0),
        ("check", f"20GA STRUTS  {spec.struts_20 or '________'}", spec.struts_20 > 0),
        ("check", "MAN DOOR (see man door spec)", spec.man_door),
        ("check", "BAR LATCH", spec.bar_latch),
        ("check", "KEYED OUTSIDE HANDLE", spec.keyed_outside_handle),
        ("check", "INTERIOR SIDE LOCK", spec.interior_lock),
        ("check", "MANUAL OPERATION", spec.manual),
        ("check", "GEARED CHAIN HOIST WALL MOUNT", spec.chain_hoist),
        ("check", "ELECTRIC OPERATOR (BY OTHERS)", bool(spec.operator_model)),
        ("check", '1" SOLID SHAFT', spec.shaft_kind == "1_solid"),
        ("check", '1-1/4" SOLID SHAFT', spec.shaft_kind == "1_25_solid"),
        ("check", '1" TUBULAR SHAFT', spec.shaft_kind == "1_tubular"),
        ("check", "COUPLER", spec.coupler),
        ("check", "STANDARD CYCLE SPRING", cycles <= 10000),
        ("check", "25,000 CYCLE SPRINGS", 10000 < cycles <= 25000),
        ("check", "50,000 CYCLE SPRINGS", 25000 < cycles <= 50000),
        ("check", "75,000 CYCLE SPRINGS", 50000 < cycles <= 75000),
        ("check", "100,000 CYCLE SPRINGS", cycles > 75000),
        ("check", "PUSHER SPRING", spec.pusher_spring),
        ("check", "BUMPER SPRING", spec.bumper_spring),
        ("check", "TRACK GUARDS", spec.track_guards),
        ("check", "TOP SEAL VINYL", spec.top_seal),
        ("check", f"{spec.weather_strip_material} FLEXIBLE VINYL WEATHER STRIP", spec.weather_strip),
        ("check", "EXHAUST PORT", spec.exhaust_port),
        ("header", "SPRINGS INFO:", None),
    ]
    if spec.springs:
        for line in spec.springs:
            rows.append(("header", line.text(), None))
    else:
        rows.append(("header", "SEE ENGINEERING", None))
    rows.append(("header", f"TURNS: {spec.turns_text}", None))
    if spec.drum_model:
        rows.append(("header", f"DRUM: {spec.drum_model}", None))
    if spec.weight_lbs is not None:
        rows.append(("header", f"DOOR WT: {spec.weight_lbs:.0f} LBS", None))
    return rows


# ─── [E] jamb plan ──────────────────────────────────────────────────────────

def _jamb_plan(msp, box, spec: DoorDrawingSpec):
    x0, y0, x1, y1 = box
    title = "STEEL JAMB WELD APPLICATION" if spec.frame == "steel" else "WOOD JAMB APPLICATION"
    view_frame(msp, box, title)
    # Drawing band
    left = x0 + 0.35
    right = x1 - 0.30
    mid_y = (y0 + y1) / 2 - 0.05
    door_x0 = left + 1.15
    door_x1 = right - 1.15
    # Door panel in plan, broken in the middle. Thickness is vertical on the sheet.
    thick = 0.16
    msp.add_lwpolyline(
        [(door_x0, mid_y - thick), (door_x0 + 0.85, mid_y - thick),
         (door_x0 + 0.95, mid_y - 0.04), (door_x0 + 0.85, mid_y + thick),
         (door_x0, mid_y + thick)],
        close=True,
        dxfattribs={"layer": "FRAMING"},
    )
    msp.add_lwpolyline(
        [(door_x1, mid_y - thick), (door_x1 - 0.85, mid_y - thick),
         (door_x1 - 0.95, mid_y + 0.04), (door_x1 - 0.85, mid_y + thick),
         (door_x1, mid_y + thick)],
        close=True,
        dxfattribs={"layer": "FRAMING"},
    )

    _one_jamb(msp, left, mid_y, spec, side="left")
    _one_jamb(msp, right, mid_y, spec, side="right")

    dim_h(msp, left, door_x0, mid_y + 0.85, spec.sideroom_text)
    text(msp, "MIN. REQ. SIDEROOM", (left + door_x0) / 2, mid_y + 1.02, 0.045, "mc", "DIMENSIONS")
    dim_h(msp, door_x1, right, mid_y + 0.85, spec.sideroom_text)
    text(msp, "MIN. REQ. SIDEROOM", (door_x1 + right) / 2, mid_y + 1.02, 0.045, "mc", "DIMENSIONS")
    dim_h(msp, door_x0, door_x1, mid_y - 0.55, "DOOR OPENING")
    dim_h(msp, left, right, y0 + 0.28, spec.door_width_text)
    text(msp, "WEATHER STRIPPING RAMSET FASTENED", (x0 + x1) / 2, y0 + 0.55, 0.042, "mc")
    text(msp, "STEEL END CAP C/W VINYL WEATHER STRIP", (x0 + x1) / 2, y0 + 0.42, 0.042, "mc")


def _one_jamb(msp, wall_x, y, spec: DoorDrawingSpec, side: str):
    sign = 1 if side == "left" else -1
    # Wall / buck
    x_out = wall_x
    x_in = wall_x + sign * 0.55
    if spec.frame == "steel":
        _stipple(msp, min(x_out, x_in), y - 0.55, max(x_out, x_in), y + 0.55)
        # Steel angle wrapping the jamb face
        msp.add_lwpolyline(
            [(x_in, y - 0.45), (x_in, y + 0.45),
             (x_in - sign * 0.12, y + 0.45), (x_in - sign * 0.12, y + 0.32),
             (x_out + sign * 0.08, y + 0.32), (x_out + sign * 0.08, y - 0.32),
             (x_in - sign * 0.12, y - 0.32), (x_in - sign * 0.12, y - 0.45)],
            close=True,
            dxfattribs={"layer": "FRAMING"},
        )
    else:
        _wood_hatch(msp, min(x_out, x_in), y - 0.55, max(x_out, x_in), y + 0.55)
    # Track channel beyond the jamb, door side
    track_x = x_in + sign * 0.28
    msp.add_lwpolyline(
        [(track_x, y - 0.16), (track_x + sign * 0.16, y - 0.16),
         (track_x + sign * 0.16, y + 0.16), (track_x, y + 0.16)],
        close=True,
        dxfattribs={"layer": "TRACKS"},
    )
    msp.add_circle((track_x + sign * 0.08, y), 0.045, dxfattribs={"layer": "HARDWARE"})
    # Weather-strip wedge on the exterior skin
    msp.add_solid(
        [
            (x_in + sign * 0.02, y + 0.22),
            (x_in + sign * 0.16, y + 0.10),
            (x_in + sign * 0.02, y - 0.02),
            (x_in + sign * 0.02, y - 0.02),
        ],
        dxfattribs={"layer": "SOLID_FILL"},
    )


def _stipple(msp, x0, y0, x1, y1):
    import random
    rng = random.Random(1)
    if x1 < x0:
        x0, x1 = x1, x0
    if y1 < y0:
        y0, y1 = y1, y0
    for _ in range(28):
        x = rng.uniform(x0, x1)
        y = rng.uniform(y0, y1)
        msp.add_circle((x, y), 0.012, dxfattribs={"layer": "HATCH"})


def _wood_hatch(msp, x0, y0, x1, y1):
    _diag_hatch(msp, x0, y0, x1, y1)


# ─── [F] track elevation ────────────────────────────────────────────────────

def _track_elevation(msp, box, spec: DoorDrawingSpec):
    x0, y0, x1, y1 = box
    view_frame(msp, box, spec.track_title)
    floor_y = y0 + 0.55
    wall_x = x0 + 1.55
    head_y = floor_y + 2.05
    ceil_y = y1 - 0.55
    # Header wall
    msp.add_line((wall_x, floor_y), (wall_x, ceil_y), dxfattribs={"layer": "FRAMING"})
    msp.add_line((wall_x, head_y), (x1 - 0.25, head_y), dxfattribs={"layer": "FRAMING"})
    _diag_hatch(msp, wall_x - 0.22, head_y, wall_x, ceil_y)
    if spec.lift != "vertical":
        msp.add_line((wall_x, ceil_y), (x1 - 0.25, ceil_y), dxfattribs={"layer": "FRAMING"})
        _diag_hatch(msp, wall_x, ceil_y - 0.16, x1 - 0.25, ceil_y)

    if spec.lift == "vertical":
        _track_vertical(msp, wall_x, floor_y, head_y, ceil_y, spec)
    elif spec.lift == "high_lift":
        _track_high_lift(msp, wall_x, floor_y, head_y, ceil_y, x1, spec)
    elif spec.lift in ("lhr_front", "lhr_rear"):
        _track_low_headroom(msp, wall_x, floor_y, head_y, x1, spec)
    else:
        _track_standard(msp, wall_x, floor_y, head_y, ceil_y, x1, spec)

    dim_v(
        msp, floor_y, head_y, x0 + 0.32,
        ["DOOR", "HEIGHT", spec.door_height_text],
        side="left",
    )


def _track_standard(msp, wall_x, floor_y, head_y, ceil_y, x1, spec):
    radius = 0.38
    msp.add_line((wall_x + 0.12, floor_y), (wall_x + 0.12, head_y - radius),
                 dxfattribs={"layer": "TRACKS"})
    msp.add_arc((wall_x + 0.12 + radius, head_y - radius), radius, 90, 180,
                dxfattribs={"layer": "TRACKS"})
    track_y = head_y
    msp.add_line((wall_x + 0.12 + radius, track_y), (x1 - 0.35, track_y),
                 dxfattribs={"layer": "TRACKS"})
    msp.add_circle((wall_x + 0.28, head_y + 0.28), 0.09, dxfattribs={"layer": "HARDWARE"})
    _hangers(msp, wall_x + 1.1, x1 - 0.55, track_y, ceil_y)
    dim_v(msp, head_y, ceil_y, wall_x - 0.45, ["MIN. REQ.", "HEADROOM", spec.headroom_text], side="left")
    if spec.ust_text:
        text(msp, "UNDERSIDE OF TRACK", (wall_x + x1) / 2, track_y - 0.28, 0.05, "mc", "DIMENSIONS")
        text(msp, spec.ust_text, (wall_x + x1) / 2, track_y - 0.40, 0.06, "mc", "DIMENSIONS", style="BOLD")
    dim_h(msp, wall_x, x1 - 0.30, floor_y + 0.85, spec.backroom_text)
    text(msp, "MIN. REQ. BACKROOM", (wall_x + x1) / 2, floor_y + 1.05, 0.048, "mc", "DIMENSIONS")


def _track_high_lift(msp, wall_x, floor_y, head_y, ceil_y, x1, spec):
    # The high-lift rise is drawn taller than a standard radius so the
    # extra track reads, but the printed dimension is the real value.
    rise = 0.55
    radius = 0.32
    msp.add_line((wall_x + 0.12, floor_y), (wall_x + 0.12, head_y + rise - radius),
                 dxfattribs={"layer": "TRACKS"})
    msp.add_arc((wall_x + 0.12 + radius, head_y + rise - radius), radius, 90, 180,
                dxfattribs={"layer": "TRACKS"})
    track_y = head_y + rise
    msp.add_line((wall_x + 0.12 + radius, track_y), (x1 - 0.35, track_y),
                 dxfattribs={"layer": "TRACKS"})
    msp.add_circle((wall_x + 0.30, track_y + 0.22), 0.08, dxfattribs={"layer": "HARDWARE"})
    _hangers(msp, wall_x + 1.15, x1 - 0.5, track_y, min(ceil_y, track_y + 0.45))
    dim_v(msp, head_y, head_y + rise, wall_x + 0.7, ["HIGH LIFT", spec.high_lift_text or ""], side="right")
    dim_v(msp, head_y, ceil_y, wall_x - 0.42, ["MIN. REQ.", "HEADROOM", spec.headroom_text], side="left")
    if spec.ust_text:
        text(msp, "UNDERSIDE OF", (wall_x + x1) / 2 - 0.2, track_y - 0.22, 0.045, "mc", "DIMENSIONS")
        text(msp, f"TRACK  {spec.ust_text}", (wall_x + x1) / 2 - 0.2, track_y - 0.34, 0.05, "mc", "DIMENSIONS")
    dim_h(msp, wall_x + 0.2, x1 - 0.35, floor_y + 0.7, spec.backroom_text)
    text(msp, "MIN. REQ. BACKROOM", (wall_x + x1) / 2, floor_y + 0.92, 0.045, "mc", "DIMENSIONS")


def _track_vertical(msp, wall_x, floor_y, head_y, ceil_y, spec):
    msp.add_line((wall_x + 0.16, floor_y), (wall_x + 0.16, ceil_y - 0.15),
                 dxfattribs={"layer": "TRACKS"})
    # Section break so the track reads as continuing
    msp.add_line((wall_x + 0.08, (floor_y + head_y) / 2), (wall_x + 0.28, (floor_y + head_y) / 2 + 0.08),
                 dxfattribs={"layer": "TRACKS"})
    msp.add_circle((wall_x + 0.16, ceil_y - 0.05), 0.09, dxfattribs={"layer": "HARDWARE"})
    dim_v(msp, head_y, ceil_y, wall_x - 0.45, ["MIN. REQ.", "HEADROOM", spec.headroom_text], side="left")
    dim_h(msp, wall_x + 0.16, wall_x + 1.15, ceil_y - 0.05, spec.backroom_text)
    text(msp, "BACKROOM", wall_x + 1.35, ceil_y - 0.05, 0.05, "ml", "DIMENSIONS")


def _track_low_headroom(msp, wall_x, floor_y, head_y, x1, spec):
    # No sample sheet. Schematic: horizontal track tucked against the header.
    msp.add_line((wall_x + 0.12, floor_y), (wall_x + 0.12, head_y - 0.08),
                 dxfattribs={"layer": "TRACKS"})
    track_y = head_y + 0.06
    msp.add_line((wall_x + 0.12, track_y), (x1 - 0.35, track_y), dxfattribs={"layer": "TRACKS"})
    msp.add_line((wall_x + 0.12, track_y + 0.10), (x1 - 0.35, track_y + 0.10),
                 dxfattribs={"layer": "TRACKS"})
    rear = spec.lift == "lhr_rear"
    drum_x = (x1 - 0.6) if rear else (wall_x + 0.4)
    msp.add_circle((drum_x, track_y + 0.28), 0.08, dxfattribs={"layer": "HARDWARE"})
    text(msp, "REAR TORSION" if rear else "FRONT TORSION", drum_x, track_y + 0.46, 0.045, "mc")
    dim_v(msp, head_y, head_y + 0.7, wall_x - 0.4, ["MIN. REQ.", "HEADROOM", spec.headroom_text], side="left")
    dim_h(msp, wall_x, x1 - 0.3, floor_y + 0.7, spec.backroom_text)
    text(msp, "MIN. REQ. BACKROOM", (wall_x + x1) / 2, floor_y + 0.9, 0.045, "mc", "DIMENSIONS")
    text(msp, "NO SAMPLE — LOW HEADROOM FORMAT", (wall_x + x1) / 2, floor_y + 0.35, 0.042, "mc", "ANNOTATIONS")


def _hangers(msp, x0, x1, track_y, ceil_y):
    if x1 - x0 < 0.4:
        return
    for i in range(3):
        x = x0 + (x1 - x0) * (i + 0.5) / 3
        msp.add_line((x, track_y), (x, ceil_y), dxfattribs={"layer": "TRACKS"})
        msp.add_line((x - 0.05, track_y + 0.08), (x + 0.05, track_y + 0.08),
                     dxfattribs={"layer": "TRACKS"})
        msp.add_line((x - 0.05, ceil_y - 0.06), (x + 0.05, ceil_y - 0.06),
                     dxfattribs={"layer": "TRACKS"})


def _diag_hatch(msp, x0, y0, x1, y1):
    """Diagonal hatch clipped to the rectangle. Lines must not leave the box."""
    if x1 < x0:
        x0, x1 = x1, x0
    if y1 < y0:
        y0, y1 = y1, y0
    if x1 - x0 < 0.04 or y1 - y0 < 0.04:
        return
    msp.add_lwpolyline(
        [(x0, y0), (x1, y0), (x1, y1), (x0, y1)],
        close=True,
        dxfattribs={"layer": "FRAMING"},
    )
    # y = x + b, clipped to the box.
    b = y0 - x1
    b_max = y1 - x0
    step = 0.07
    while b < b_max:
        hits = []
        if y0 <= x0 + b <= y1:
            hits.append((x0, x0 + b))
        if y0 <= x1 + b <= y1:
            hits.append((x1, x1 + b))
        if x0 <= y0 - b <= x1:
            hits.append((y0 - b, y0))
        if x0 <= y1 - b <= x1:
            hits.append((y1 - b, y1))
        uniq = []
        for hx, hy in hits:
            if not any(abs(hx - ux) < 1e-6 and abs(hy - uy) < 1e-6 for ux, uy in uniq):
                uniq.append((hx, hy))
        if len(uniq) >= 2:
            msp.add_line(uniq[0], uniq[1], dxfattribs={"layer": "HATCH"})
        b += step


# ─── [G] schedules ──────────────────────────────────────────────────────────

def _schedules(msp, box, spec: DoorDrawingSpec):
    x0, y0, x1, y1 = box
    view_frame(msp, box, None)
    # Door table
    text(msp, "QTY", x0 + 0.22, y1 - 0.16, 0.045, "mc", "TITLE_BLOCK", style="BOLD")
    text(msp, "DOOR OPENING", x0 + 1.15, y1 - 0.12, 0.04, "mc", "TITLE_BLOCK", style="BOLD")
    text(msp, "DOOR SIZE", x0 + 2.35, y1 - 0.12, 0.04, "mc", "TITLE_BLOCK", style="BOLD")
    text(msp, "SECTIONS", x1 - 0.45, y1 - 0.12, 0.04, "mc", "TITLE_BLOCK", style="BOLD")
    text(msp, "W", x0 + 0.85, y1 - 0.28, 0.04, "mc", "TITLE_BLOCK")
    text(msp, "H", x0 + 1.40, y1 - 0.28, 0.04, "mc", "TITLE_BLOCK")
    text(msp, "W", x0 + 2.05, y1 - 0.28, 0.04, "mc", "TITLE_BLOCK")
    text(msp, "H", x0 + 2.65, y1 - 0.28, 0.04, "mc", "TITLE_BLOCK")
    text(msp, "HIGH", x1 - 0.45, y1 - 0.28, 0.04, "mc", "TITLE_BLOCK")
    text(msp, str(spec.qty), x0 + 0.22, y1 - 0.46, 0.05, "mc", "TITLE_BLOCK")
    text(msp, "N/A", x0 + 0.85, y1 - 0.46, 0.045, "mc", "TITLE_BLOCK")
    text(msp, "N/A", x0 + 1.40, y1 - 0.46, 0.045, "mc", "TITLE_BLOCK")
    text(msp, spec.door_width_text, x0 + 2.05, y1 - 0.46, 0.045, "mc", "TITLE_BLOCK")
    text(msp, spec.door_height_text, x0 + 2.65, y1 - 0.46, 0.045, "mc", "TITLE_BLOCK")
    text(msp, spec.sections_text, x1 - 0.45, y1 - 0.46, 0.042, "mc", "TITLE_BLOCK")
    msp.add_line((x0 + 0.04, y1 - 0.58), (x1 - 0.04, y1 - 0.58), dxfattribs={"layer": "TITLE_BLOCK"})

    win = spec.windows
    text(msp, "WINDOWS", x0 + 0.08, y1 - 0.72, 0.05, "ml", "TITLE_BLOCK", style="BOLD")
    text(msp, f"QTY: {win.qty or 'N/A'}", x0 + 0.08, y1 - 0.88, 0.042, "ml", "TITLE_BLOCK")
    text(msp, f"GLAZING SIZE: {win.size_text}", x0 + 0.08, y1 - 1.02, 0.042, "ml", "TITLE_BLOCK")
    text(msp, f"GLAZING MATERIAL: {win.material}", x0 + 0.08, y1 - 1.16, 0.04, "ml", "TITLE_BLOCK")
    text(msp, f"SECTION GLAZED: {win.glazed_text}", x0 + 0.08, y1 - 1.30, 0.04, "ml", "TITLE_BLOCK")
    text(msp, f"LOCATION ON DOOR: {win.location_text}", x0 + 0.08, y1 - 1.44, 0.04, "ml", "TITLE_BLOCK")
    msp.add_line((x0 + 0.04, y1 - 1.56), (x1 - 0.04, y1 - 1.56), dxfattribs={"layer": "TITLE_BLOCK"})

    text(msp, "ELECTRIC OPERATOR", x0 + 0.08, y1 - 1.70, 0.05, "ml", "TITLE_BLOCK", style="BOLD")
    model = spec.operator_model or "N/A"
    qty = str(spec.operator_qty) if spec.operator_model else "N/A"
    text(msp, "MODEL", x0 + 0.7, y1 - 1.86, 0.04, "mc", "TITLE_BLOCK")
    text(msp, "QTY", x1 - 0.35, y1 - 1.86, 0.04, "mc", "TITLE_BLOCK")
    text(msp, model[:28], x0 + 0.08, y1 - 2.02, 0.042, "ml", "TITLE_BLOCK")
    text(msp, qty, x1 - 0.35, y1 - 2.02, 0.045, "mc", "TITLE_BLOCK")
    text(msp, "OPERATOR ACCESSORIES", x0 + 0.08, y1 - 2.20, 0.045, "ml", "TITLE_BLOCK", style="BOLD")
    text(msp, "NAME", x0 + 0.7, y1 - 2.36, 0.04, "mc", "TITLE_BLOCK")
    text(msp, "QTY", x1 - 0.35, y1 - 2.36, 0.04, "mc", "TITLE_BLOCK")
    text(msp, "—", x0 + 0.7, y1 - 2.52, 0.045, "mc", "TITLE_BLOCK")


# ─── [H] title block ────────────────────────────────────────────────────────

def _title_block(msp, box, spec: DoorDrawingSpec):
    x0, y0, x1, y1 = box
    msp.add_lwpolyline(
        [(x0, y0), (x1, y0), (x1, y1), (x0, y1)],
        close=True,
        dxfattribs={"layer": "TITLE_BLOCK"},
    )
    mid = (x0 + x1) / 2
    text(msp, "Upwardor", x0 + 0.55, y1 - 0.22, 0.11, "mc", "TITLE_BLOCK", style="BOLD")
    text(msp, spec.series, mid + 0.7, y1 - 0.22, 0.14, "mc", "TITLE_BLOCK", style="BOLD")
    msp.add_line((x0, y1 - 0.40), (x1, y1 - 0.40), dxfattribs={"layer": "TITLE_BLOCK"})

    rev = "—" if spec.revision is None else str(spec.revision)
    dwg = spec.drawing_number or "—"
    rows = [
        ("DWG NO.", dwg),
        ("REVISION", rev),
        ("JOB NO.", spec.job_number or "—"),
        ("DISTRIBUTOR", spec.distributor),
        ("PROJECT NAME", spec.project_name or "—"),
        ("ARCHITECT", spec.architect or "—"),
        ("DRAWN BY", spec.drawn_by or "—"),
        ("DATE", spec.drawing_date or "—"),
    ]
    row_h = (y1 - 0.46 - y0 - 0.04) / len(rows)
    y = y1 - 0.40
    for label, value in rows:
        y_next = y - row_h
        msp.add_line((x0, y_next), (x1, y_next), dxfattribs={"layer": "TITLE_BLOCK"})
        text(msp, label, x0 + 0.06, (y + y_next) / 2, 0.058, "ml", "TITLE_BLOCK")
        text(msp, value, x1 - 0.06, (y + y_next) / 2, 0.068, "mr", "TITLE_BLOCK", style="BOLD")
        y = y_next
