"""Small drawing helpers shared by the sheet and the parametric profiles."""

from __future__ import annotations

import math

from ezdxf.enums import TextEntityAlignment
from ezdxf.layouts import Modelspace

_ALIGN = {
    "mc": TextEntityAlignment.MIDDLE_CENTER,
    "ml": TextEntityAlignment.MIDDLE_LEFT,
    "mr": TextEntityAlignment.MIDDLE_RIGHT,
    "bl": TextEntityAlignment.BOTTOM_LEFT,
    "bc": TextEntityAlignment.BOTTOM_CENTER,
    "br": TextEntityAlignment.BOTTOM_RIGHT,
    "tl": TextEntityAlignment.TOP_LEFT,
    "tc": TextEntityAlignment.TOP_CENTER,
    "tr": TextEntityAlignment.TOP_RIGHT,
}


class Pen:
    """Draw in real inches, placed at an origin and scaled into the sheet."""

    def __init__(self, msp: Modelspace, ox: float, oy: float, scale: float, layer: str = "FRAMING"):
        self.msp = msp
        self.ox = ox
        self.oy = oy
        self.s = scale
        self.layer = layer

    def p(self, x: float, y: float) -> tuple[float, float]:
        return (self.ox + x * self.s, self.oy + y * self.s)

    def line(self, x0, y0, x1, y1, layer=None):
        self.msp.add_line(
            self.p(x0, y0), self.p(x1, y1),
            dxfattribs={"layer": layer or self.layer},
        )

    def poly(self, pts, close=False, layer=None, width=0.0):
        if len(pts) < 2:
            return
        attribs = {"layer": layer or self.layer}
        if width:
            attribs["const_width"] = width
        self.msp.add_lwpolyline(
            [self.p(x, y) for x, y in pts],
            close=close,
            dxfattribs=attribs,
        )

    def triangle(self, pts, layer=None):
        if len(pts) < 3:
            return
        a, b, c = (self.p(*pts[0]), self.p(*pts[1]), self.p(*pts[2]))
        self.msp.add_solid([a, b, c, c], dxfattribs={"layer": layer or "SOLID_FILL"})

    def rect(self, x0, y0, x1, y1, layer=None):
        self.poly([(x0, y0), (x1, y0), (x1, y1), (x0, y1)], close=True, layer=layer)

    def circle(self, x, y, r, layer=None):
        if r <= 0:
            return
        self.msp.add_circle(self.p(x, y), r * self.s, dxfattribs={"layer": layer or self.layer})

    def arc(self, x, y, r, start, end, layer=None):
        if r <= 0:
            return
        self.msp.add_arc(
            self.p(x, y), r * self.s, start, end,
            dxfattribs={"layer": layer or self.layer},
        )

    def filled_rect(self, x0, y0, x1, y1, layer=None, rgb=None):
        if x1 < x0:
            x0, x1 = x1, x0
        if y1 < y0:
            y0, y1 = y1, y0
        if abs(x1 - x0) < 1e-6 or abs(y1 - y0) < 1e-6:
            return
        # DXF SOLID corner order is (p1, p2, p3, p4) = (ll, lr, ul, ur).
        p1, p2 = self.p(x0, y0), self.p(x1, y0)
        p3, p4 = self.p(x0, y1), self.p(x1, y1)
        solid = self.msp.add_solid(
            [p1, p2, p3, p4],
            dxfattribs={"layer": layer or "SOLID_FILL"},
        )
        if rgb:
            solid.rgb = rgb

    def dots(self, x0, y0, x1, y1, step, layer=None):
        if x1 < x0:
            x0, x1 = x1, x0
        if y1 < y0:
            y0, y1 = y1, y0
        y = y0
        row = 0
        r = step * 0.07
        while y < y1:
            x = x0 + (step * 0.5 if row % 2 else 0.0)
            while x < x1:
                self.circle(x, y, r, layer=layer or "HATCH")
                x += step
            y += step
            row += 1


def text(msp, value, x, y, height=0.07, align="mc", layer="ANNOTATIONS",
         rotation=0.0, style="Standard"):
    if value is None:
        return
    value = str(value)
    if value == "":
        return
    ent = msp.add_text(
        value,
        dxfattribs={
            "layer": layer,
            "height": height,
            "style": style,
            "rotation": rotation,
        },
    )
    ent.set_placement((x, y), align=_ALIGN.get(align, TextEntityAlignment.MIDDLE_CENTER))
    return ent


def arrow(msp, tip, angle_deg, size=0.085, layer="DIMENSIONS"):
    ang = math.radians(angle_deg)
    x, y = tip
    back = size
    spread = size * 0.42
    bx = x - math.cos(ang) * back
    by = y - math.sin(ang) * back
    px = math.cos(ang + math.pi / 2) * spread
    py = math.sin(ang + math.pi / 2) * spread
    msp.add_solid(
        [(x, y), (bx + px, by + py), (bx - px, by - py), (bx - px, by - py)],
        dxfattribs={"layer": layer},
    )


def _ext(msp, x0, y0, x1, y1):
    msp.add_line((x0, y0), (x1, y1), dxfattribs={"layer": "DIMENSIONS"})


def dim_h(msp, x0, x1, y, label, text_h=0.088, ext=None):
    """Horizontal dimension. ``ext`` is the object y the extension lines start from."""
    if abs(x1 - x0) < 0.05:
        return
    if x1 < x0:
        x0, x1 = x1, x0
    if ext is not None:
        gap = 0.04 if y >= ext else -0.04
        over = 0.06 if y >= ext else -0.06
        for x in (x0, x1):
            _ext(msp, x, ext + gap, x, y + over)
    mid = (x0 + x1) / 2
    gap_w = min((x1 - x0) * 0.62, max(0.28, len(str(label)) * text_h * 0.55))
    _ext(msp, x0, y, mid - gap_w / 2, y)
    _ext(msp, mid + gap_w / 2, y, x1, y)
    arrow(msp, (x0, y), 180, size=0.075)
    arrow(msp, (x1, y), 0, size=0.075)
    text(msp, label, mid, y + text_h * 0.15, text_h, "mc", "DIMENSIONS")


def dim_v(msp, y0, y1, x, lines, text_h=0.078, side="left", ext=None):
    """Vertical dimension. ``ext`` is the object x the extension lines start from."""
    if abs(y1 - y0) < 0.05:
        return
    if y1 < y0:
        y0, y1 = y1, y0
    if ext is not None:
        gap = 0.04 if x <= ext else -0.04
        over = -0.06 if side == "left" else 0.06
        for y in (y0, y1):
            _ext(msp, ext - gap, y, x + over, y)
    msp.add_line((x, y0), (x, y1), dxfattribs={"layer": "DIMENSIONS"})
    arrow(msp, (x, y0), -90, size=0.075)
    arrow(msp, (x, y1), 90, size=0.075)
    mid = (y0 + y1) / 2
    step = text_h + 0.02
    n = len(lines)
    anchor_x = x - 0.08 if side == "left" else x + 0.08
    align = "mr" if side == "left" else "ml"
    for i, line in enumerate(lines):
        yy = mid + ((n - 1) / 2 - i) * step
        text(msp, line, anchor_x, yy, text_h, align, "DIMENSIONS")


def leader(msp, target, text_x, text_y, lines, text_h=0.062):
    """Arrow at ``target``, callout stacked at ``text_x`` (left edge), centred on ``text_y``."""
    if not lines:
        return
    step = text_h + 0.008
    top = text_y + (len(lines) - 1) * step / 2
    for i, line in enumerate(lines):
        text(msp, line, text_x, top - i * step, text_h, "ml", "ANNOTATIONS")
    start = (text_x - 0.05, text_y)
    end = target
    if abs(start[1] - end[1]) < 0.03:
        msp.add_line(start, end, dxfattribs={"layer": "DIMENSIONS"})
        angle = 180 if end[0] <= start[0] else 0
    else:
        knee = (end[0] + 0.16, start[1])
        msp.add_line(start, knee, dxfattribs={"layer": "DIMENSIONS"})
        msp.add_line(knee, end, dxfattribs={"layer": "DIMENSIONS"})
        angle = math.degrees(math.atan2(end[1] - knee[1], end[0] - knee[0]))
    arrow(msp, end, angle, size=0.07, layer="ANNOTATIONS")


def checkbox(msp, x, y, checked, size=0.075):
    msp.add_lwpolyline(
        [(x, y), (x + size, y), (x + size, y + size), (x, y + size)],
        close=True,
        dxfattribs={"layer": "ANNOTATIONS"},
    )
    if checked:
        msp.add_line((x + 0.01, y + 0.01), (x + size - 0.01, y + size - 0.01),
                     dxfattribs={"layer": "ANNOTATIONS"})
        msp.add_line((x + 0.01, y + size - 0.01), (x + size - 0.01, y + 0.01),
                     dxfattribs={"layer": "ANNOTATIONS"})


def view_frame(msp, box, title=None):
    x0, y0, x1, y1 = box
    msp.add_lwpolyline(
        [(x0, y0), (x1, y0), (x1, y1), (x0, y1)],
        close=True,
        dxfattribs={"layer": "BORDER"},
    )
    if title:
        text(msp, title, (x0 + x1) / 2, y1 - 0.14, 0.125, "tc", "ANNOTATIONS", style="BOLD")
        msp.add_line((x0 + 0.08, y1 - 0.26), (x1 - 0.08, y1 - 0.26),
                     dxfattribs={"layer": "ANNOTATIONS", "lineweight": 50})
