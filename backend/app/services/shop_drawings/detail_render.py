"""True-proportion section details.

Coordinates are real inches. Exterior is x = 0, interior is x = thickness, +y
is up. Each draw function returns callout anchors ``(x, y, lines)`` in that
same space so the sheet can put a leader and arrow on the part.
"""

from __future__ import annotations

from app.services.shop_drawings.profiles import (
    groove_profile,
    shiplap_breaks,
    shiplap_lower,
    shiplap_upper,
    thermal_break_lower,
    thermal_break_upper,
    tongue_profile,
)
from app.services.shop_drawings.sheet_geom import Pen

OUTLINE = 0.015
SKIN = 0.008


def _parts(T: float) -> list[tuple[str, float]]:
    return [
        ("astragal", 0.55 * T),
        ("retainer", 0.28 * T),
        ("body", 1.25),
        ("joint", 0.36 * T),
        ("break", 0.22),
        ("body", 0.70),
        ("joint", 0.36 * T),
        ("break", 0.20),
        ("body", 0.98),
        ("cap", 0.34 * T),
        ("flap", 0.42 * T),
    ]


def steel_size(T: float) -> tuple[float, float]:
    height = sum(h for _, h in _parts(T))
    width = T + 0.62 * T
    return width, height


def render_steel(msp, spec, origin, scale: float) -> list[tuple]:
    pen = Pen(msp, origin[0], origin[1], scale, "FRAMING")
    T = spec.thickness_in
    shiplap = spec.joint == "shiplap"
    anchors: list[tuple] = []
    y = 0.0
    body_i = 0
    joint_i = 0
    for name, height in _parts(T):
        if name == "astragal":
            _astragal(pen, T, y + height * 0.92)
            anchors.append((T * 0.55, y + 0.22 * T, ("LOW TEMP. VINYL", "BOTTOM ASTRAGAL")))
        elif name == "retainer":
            _retainer(pen, T, y, height)
            anchors.append((T * 0.82, y + height * 0.45, ("P.V.C.", "RETAINER")))
        elif name == "body":
            _body(pen, T, y, height)
            if body_i == 2:
                anchors.append((0.0, y + height * 0.55, _exterior_lines(spec)))
                anchors.append((T, y + height * 0.35, _interior_lines(spec)))
                anchors.append((0.48 * T, y + height * 0.62, ("FOAMED-IN-PLACE", "POLYURETHANE", "2.5 PCF DENSITY")))
            body_i += 1
        elif name == "joint":
            _joint(pen, T, y, shiplap, full_hinge=(joint_i == 1))
            if joint_i == 0:
                anchors.append((0.50 * T, y + 0.18 * T, ("WEATHER SEAL",)))
                anchors.append((0.32 * T, y - 0.10 * T, ("THERMALLY BROKEN", "CHEMICALLY BONDED", "AND SEALED")))
                anchors.append((T, y + 0.20 * T, ("HINGE REINFORCING", "2 STEEL STRIPS,", '1-1/4" W')))
            else:
                anchors.append((T + 0.36 * T, y + 0.06 * T, ("FULL HINGE", "APPLICATION")))
            joint_i += 1
        elif name == "break":
            _break(pen, T, y + height * 0.45)
        elif name == "cap":
            _cap(pen, T, y, height)
        elif name == "flap":
            _flap(pen, T, y, height, spec.top_seal)
            lines = ("LOW TEMP. VINYL", "TOP SEAL", "(OPTIONAL)") if not spec.top_seal else ("LOW TEMP. VINYL", "TOP SEAL")
            anchors.append((0.02 * T, y + height * 0.72, lines))
        y += height
    return anchors


def _exterior_lines(spec) -> tuple[str, ...]:
    label = spec.exterior_skin_label
    if "FINISH" in label:
        gauge, rest = label.split(" ", 1)
        return (f"{gauge} STUCCO", "EMBOSSED FINISH:", rest.split(":")[-1].strip() or "WHITE")
    if "FLUSH" in label:
        return tuple(label.replace(" FINISH:", "\nFINISH:").split("\n"))[:3] or (label,)
    return (label,)


def _interior_lines(spec) -> tuple[str, ...]:
    return ("26GA STUCCO", "EMBOSSED WHITE") if spec.joint != "panorama" else ("GLAZING", "MOULDING")


def _body(pen: Pen, T: float, y0: float, h: float) -> None:
    y1 = y0 + h
    pen.line(0, y0, 0, y1)
    pen.line(0.03 * T, y0 + 0.05, 0.03 * T, y1 - 0.04)
    pen.line(T, y0, T, y1)
    pen.line(T - 0.03 * T, y0 + 0.05, T - 0.03 * T, y1 - 0.04)
    pen.dots(0.12 * T, y0 + 0.08, 0.88 * T, y1 - 0.08, 0.10, layer="HATCH")
    yy = y0 + 0.16
    while yy < y1 - 0.10:
        pen.poly([(0.0, yy), (0.08 * T, yy - 0.04), (0.15 * T, yy)], width=SKIN)
        yy += 0.24
    mid = (y0 + y1) / 2
    pen.poly([(T, mid - 0.05), (T - 0.08 * T, mid), (T, mid + 0.05)], width=SKIN)


def _joint(pen: Pen, T: float, y: float, shiplap: bool, full_hinge: bool) -> None:
    if shiplap:
        pen.poly([(x, y + yy) for x, yy in shiplap_lower(T)], width=OUTLINE)
        pen.poly([(x, y + yy) for x, yy in shiplap_upper(T)], width=OUTLINE)
        for box in shiplap_breaks(T):
            pen.filled_rect(box[0], y + box[1], box[2], y + box[3])
        pen.circle(0.28 * T, y + 0.10 * T, 0.04 * T, layer="HARDWARE")
        pen.filled_rect(0.22 * T, y + 0.07 * T, 0.34 * T, y + 0.14 * T, layer="SOLID_FILL")
    else:
        pen.poly([(x, y + yy) for x, yy in tongue_profile(T)], width=OUTLINE)
        pen.poly([(x, y + yy) for x, yy in groove_profile(T)], width=OUTLINE)
        x0, y0, x1, y1 = thermal_break_lower(T)
        pen.filled_rect(x0, y + y0, x1, y + y1)
        x0, y0, x1, y1 = thermal_break_upper(T)
        pen.filled_rect(x0, y + y0, x1, y + y1)
        _seal(pen, T, y)
    _screws(pen, T, y)
    if full_hinge:
        _hinge(pen, T, y)


def _seal(pen: Pen, T: float, y: float) -> None:
    """Barbed seal standing on the tongue, up into the groove."""
    cx = 0.50 * T
    foot = y + 0.11 * T
    pen.filled_rect(cx - 0.07 * T, foot, cx + 0.07 * T, foot + 0.045 * T)
    pen.filled_rect(cx - 0.015 * T, foot, cx + 0.015 * T, foot + 0.14 * T)
    for step in (0.04, 0.075, 0.11):
        by = foot + step * T
        pen.triangle([
            (cx, by),
            (cx - 0.055 * T, by + 0.03 * T),
            (cx - 0.01 * T, by + 0.012 * T),
        ])
        pen.triangle([
            (cx, by),
            (cx + 0.055 * T, by + 0.03 * T),
            (cx + 0.01 * T, by + 0.012 * T),
        ])


def _screws(pen: Pen, T: float, y: float) -> None:
    for sy in (y + 0.18 * T, y - 0.14 * T):
        _screw(pen, T, sy)
        pen.filled_rect(T - 0.055 * T, sy - 0.055 * T, T + 0.012 * T, sy + 0.055 * T)


def _screw(pen: Pen, T: float, y: float) -> None:
    head = T + 0.18 * T
    tip = T - 0.02 * T
    pen.line(head, y, tip, y, layer="HARDWARE")
    x = tip + 0.04 * T
    while x < head - 0.03 * T:
        pen.line(x, y - 0.028 * T, x + 0.028 * T, y + 0.028 * T, layer="HARDWARE")
        x += 0.032 * T
    pen.poly([
        (tip, y),
        (tip + 0.045 * T, y + 0.022 * T),
        (tip + 0.045 * T, y - 0.022 * T),
    ], close=True, layer="HARDWARE")
    r = 0.038 * T
    pen.poly([
        (head + r, y),
        (head + r * 0.5, y + r * 0.86),
        (head - r * 0.5, y + r * 0.86),
        (head - r, y),
        (head - r * 0.5, y - r * 0.86),
        (head + r * 0.5, y - r * 0.86),
    ], close=True, layer="HARDWARE")


def _hinge(pen: Pen, T: float, y: float) -> None:
    ky = y + 0.05 * T
    kx = T + 0.11 * T
    pen.line(T, ky + 0.12 * T, kx, ky, layer="HARDWARE")
    pen.line(T, ky - 0.14 * T, kx, ky, layer="HARDWARE")
    pen.circle(kx, ky, 0.09 * T, layer="HARDWARE")
    pen.circle(kx, ky, 0.03 * T, layer="HARDWARE")
    rx = T + 0.36 * T
    pen.line(kx + 0.06 * T, ky, rx - 0.12 * T, ky, layer="HARDWARE")
    pen.circle(rx, ky, 0.16 * T, layer="HARDWARE")
    pen.circle(rx, ky, 0.05 * T, layer="HARDWARE")


def _retainer(pen: Pen, T: float, y: float, h: float) -> None:
    pen.poly([
        (-0.05 * T, y + h),
        (-0.05 * T, y + 0.04 * T),
        (T + 0.05 * T, y + 0.04 * T),
        (T + 0.05 * T, y + h),
    ], width=OUTLINE, layer="HARDWARE")
    # T-slots the astragal legs lock into
    pen.rect(0.22 * T, y, 0.36 * T, y + 0.16 * T, layer="HARDWARE")
    pen.rect(0.64 * T, y, 0.78 * T, y + 0.16 * T, layer="HARDWARE")


def _astragal(pen: Pen, T: float, top: float) -> None:
    r = 0.34 * T
    cx = T / 2
    pen.arc(cx, top - r * 0.15, r, 200, 340, layer="HARDWARE")
    pen.line(cx - r * 0.72, top, cx - 0.12 * T, top + 0.12 * T, layer="HARDWARE")
    pen.line(cx + r * 0.72, top, cx + 0.12 * T, top + 0.12 * T, layer="HARDWARE")
    # second stroke so the bulb reads as a heavy seal
    pen.arc(cx, top - r * 0.15, r * 0.82, 205, 335, layer="HARDWARE")


def _cap(pen: Pen, T: float, y: float, h: float) -> None:
    pen.poly([
        (-0.05 * T, y),
        (-0.05 * T, y + h),
        (T + 0.05 * T, y + h),
        (T + 0.05 * T, y),
    ], width=OUTLINE, layer="HARDWARE")
    pen.line(-0.02 * T, y + 0.06 * T, T + 0.02 * T, y + h - 0.05 * T, layer="HATCH")
    pen.line(-0.02 * T, y + h * 0.55, T * 0.55, y + 0.05 * T, layer="HATCH")
    pen.circle(0.10 * T, y + h - 0.10 * T, 0.06 * T, layer="HARDWARE")


def _flap(pen: Pen, T: float, y: float, h: float, fitted: bool) -> None:
    pen.poly([
        (0.08 * T, y + 0.05 * T),
        (-0.28 * T, y + h * 0.85),
        (-0.12 * T, y + h),
        (0.14 * T, y + 0.08 * T),
    ], close=True, width=SKIN, layer="HARDWARE")


def _break(pen: Pen, T: float, y: float) -> None:
    pen.poly([
        (-0.06 * T, y),
        (0.18 * T, y + 0.07),
        (0.40 * T, y - 0.07),
        (0.62 * T, y + 0.07),
        (0.84 * T, y - 0.07),
        (T + 0.06 * T, y),
    ], width=SKIN, layer="HIDDEN")


# ─── Panorama ───────────────────────────────────────────────────────────────

def _pano_parts(T: float) -> list[tuple[str, float]]:
    return [
        ("astragal", 0.48 * T),
        ("bottom", 0.95),
        ("glass", 1.15),
        ("meet", 0.72),
        ("break", 0.22),
        ("glass", 1.05),
        ("top", 0.95),
        ("seal", 0.48 * T),
    ]


def panorama_size(T: float) -> tuple[float, float]:
    height = sum(h for _, h in _pano_parts(T))
    return T + 0.70 * T, height


def render_panorama(msp, spec, origin, scale: float) -> list[tuple]:
    pen = Pen(msp, origin[0], origin[1], scale, "FRAMING")
    T = spec.thickness_in
    anchors: list[tuple] = []
    y = 0.0
    glass_i = 0
    for name, height in _pano_parts(T):
        if name == "astragal":
            _astragal(pen, T, y + height * 0.9)
            anchors.append((0.15 * T, y + 0.2 * T, ("LOW TEMP VINYL", "BOTTOM ASTRAGAL")))
        elif name == "bottom":
            _pano_rail(pen, T, y, height, kind="bottom")
            _bracket(pen, T, y + height * 0.35, bottom=True)
            anchors.append((T + 0.45 * T, y + height * 0.4, ("BOTTOM BRACKET", "12GA GAL STEEL")))
        elif name == "glass":
            _pano_glass(pen, T, y, height)
            if glass_i == 0:
                anchors.append((T + 0.02 * T, y + height * 0.7, ("GLAZING", "MOULDING")))
            glass_i += 1
        elif name == "meet":
            _meeting(pen, T, y, height)
            anchors.append((0.55 * T, y + height * 0.45, ("WEATHER SEAL",)))
        elif name == "break":
            _break(pen, T, y + height * 0.5)
        elif name == "top":
            _pano_rail(pen, T, y, height, kind="top")
            _bracket(pen, T, y + height * 0.45, bottom=False)
            anchors.append((T + 0.48 * T, y + height * 0.75, ("ADJUSTABLE TOP ROLLER", "12GA GAL STEEL")))
        elif name == "seal":
            _pano_top_seal(pen, T, y, height)
            anchors.append((-0.02 * T, y + height * 0.65, ("LOW TEMP. VINYL", "TOP SEAL")))
        y += height
    return anchors


def _pano_rail(pen: Pen, T: float, y: float, h: float, kind: str) -> None:
    pen.rect(0, y, T, y + h, layer="FRAMING")
    pen.line(0.34 * T, y + 0.06, 0.34 * T, y + h - 0.06)
    pen.line(0.66 * T, y + 0.06, 0.66 * T, y + h - 0.06)
    if kind == "top":
        pen.circle(0.12 * T, y + h - 0.14 * T, 0.07 * T, layer="FRAMING")
    if kind == "bottom":
        pen.rect(0.20 * T, y - 0.06 * T, 0.34 * T, y + 0.14 * T, layer="FRAMING")
        pen.rect(0.66 * T, y - 0.06 * T, 0.80 * T, y + 0.14 * T, layer="FRAMING")
    # interior glazing clip
    pen.poly([
        (T, y + h * 0.25),
        (T + 0.10 * T, y + h * 0.25),
        (T + 0.10 * T, y + h * 0.62),
        (T, y + h * 0.62),
    ], close=True, layer="HARDWARE")


def _pano_glass(pen: Pen, T: float, y: float, h: float) -> None:
    inset = 0.07 * T
    pen.rect(inset, y, T - inset, y + h, layer="GLAZING")
    pen.line(inset, y, T - inset, y + h, layer="HATCH")
    pen.line(inset, y + h, T - inset, y, layer="HATCH")
    pen.line(inset, y + h * 0.5, T - inset, y + h, layer="HATCH")
    pen.line(inset, y, T - inset, y + h * 0.5, layer="HATCH")


def _meeting(pen: Pen, T: float, y: float, h: float) -> None:
    peak = h * 0.42
    pen.poly([
        (0, y),
        (T / 2, y + peak),
        (T, y),
        (T, y + h * 0.55),
        (0, y + h * 0.55),
    ], close=True, width=OUTLINE)
    pen.line(0.34 * T, y + 0.04, 0.34 * T, y + h * 0.5)
    pen.line(0.66 * T, y + 0.04, 0.66 * T, y + h * 0.5)
    y2 = y + h * 0.58
    pen.poly([
        (0, y + h),
        (0, y2 + peak * 0.35),
        (T / 2, y2),
        (T, y2 + peak * 0.35),
        (T, y + h),
    ], close=True, width=OUTLINE)
    pen.circle(T / 2, y + peak * 0.15, 0.07 * T, layer="HARDWARE")
    pen.circle(T / 2, y + peak * 0.55, 0.05 * T, layer="HARDWARE")


def _bracket(pen: Pen, T: float, y: float, bottom: bool) -> None:
    hx = T + 0.08 * T
    pen.line(T, y, hx + 0.12 * T, y, layer="HARDWARE")
    _screw(pen, T, y + 0.08 * T)
    _screw(pen, T, y - 0.08 * T)
    rx = T + 0.40 * T
    pen.circle(rx, y, 0.15 * T, layer="HARDWARE")
    pen.circle(rx, y, 0.045 * T, layer="HARDWARE")
    pen.line(hx + 0.10 * T, y, rx - 0.12 * T, y, layer="HARDWARE")
    if bottom:
        pen.poly([
            (T, y - 0.18 * T),
            (T + 0.22 * T, y - 0.02 * T),
            (T, y + 0.18 * T),
        ], close=True, layer="HARDWARE")


def _pano_top_seal(pen: Pen, T: float, y: float, h: float) -> None:
    pen.circle(0.12 * T, y + 0.10 * T, 0.08 * T, layer="HARDWARE")
    pen.poly([
        (0.10 * T, y + 0.16 * T),
        (-0.22 * T, y + h * 0.85),
        (-0.06 * T, y + h),
        (0.16 * T, y + 0.18 * T),
    ], close=True, layer="HARDWARE")
