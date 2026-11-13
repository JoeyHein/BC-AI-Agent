"""Upwardor side profiles and jamb details, used when the flag is on.

The geometry is the supplier DXF (received 2026-11-11), cropped per profile
and stored under ``profiles/``. TX-500 is that TX-450 drawing with the
thickness axis scaled from 45 mm to 50 mm. A -20 door is the supplier's
-20 drawing: the same section with a 20 ga exterior face. Two supplier
spellings are corrected when the file is drawn: POLYURETHENE becomes
POLYURETHANE, and the bottom-bracket note is BOTTOM BRACKET 12GA.
The 26 ga skin callout is left as the supplier wrote it.
"""
from __future__ import annotations

import json
import math
import re
from functools import lru_cache
from pathlib import Path
from typing import Optional, Tuple

from ezdxf.layouts import Modelspace

_TX = re.compile(r"^TX-?(?P<num>\d{3})(?:-?(?P<suffix>\d+))?[A-Z]*$", re.I)
_DIR = Path(__file__).resolve().parent / "profiles"
# TX-500 is the TX-450 joint at 50 mm. 50/45 is the thickness scale.
_TX500_SCALE = 50.0 / 45.0

_ALIGN = {
    1: ("top", "left"),
    2: ("top", "center"),
    3: ("top", "right"),
    4: ("center", "left"),
    5: ("center", "center"),
    6: ("center", "right"),
    7: ("bottom", "left"),
    8: ("bottom", "center"),
    9: ("bottom", "right"),
}


def _series_token(series: str) -> str:
    return (series or "").upper().replace(" ", "")


def parse_tx_series(series: str) -> Optional[Tuple[float, str]]:
    """Return (thickness mm, gauge suffix). TX-450 and TX450-20 are 45 mm."""
    match = _TX.match(_series_token(series))
    if not match:
        return None
    return int(match.group("num")) / 10.0, (match.group("suffix") or "")


def nominal_inches(mm: float) -> float:
    """Shop size: millimetres to the nearest eighth of an inch."""
    return round(mm / 25.4 * 8.0) / 8.0


def real_panel_thickness_in(series: str, door_type: str = "") -> Optional[float]:
    """Thickness we draw for this series, or None when the schematic stays."""
    del door_type
    parsed = parse_tx_series(series)
    if parsed is not None:
        return nominal_inches(parsed[0])
    if _series_token(series) == "PANORAMA":
        return 1.75
    return None


def real_sideroom_in(jamb_type: str) -> float:
    """Wood jambs need 3.75 inches. A steel jamb weld needs 3.5 inches."""
    if (jamb_type or "").lower() == "steel":
        return 3.5
    return 3.75


def _library_name(series: str) -> Optional[Tuple[str, float]]:
    parsed = parse_tx_series(series)
    if parsed is not None:
        mm, suffix = parsed
        if mm == 38:
            return "tx380", 1.0
        name = "tx450_20" if suffix == "20" else "tx450"
        return name, (_TX500_SCALE if mm == 50 else 1.0)
    if _series_token(series) == "PANORAMA":
        return "panorama", 1.0
    return None


def _jamb_name(jamb_type: str) -> str:
    return "steel_jamb" if (jamb_type or "").lower() == "steel" else "wood_jamb"


@lru_cache(maxsize=None)
def load_profile(name: str) -> dict:
    path = _DIR / f"{name}.json"
    return json.loads(path.read_text())


def _arc_points(cx, cy, r, a0, a1, x_scale, n=32):
    sweep = (a1 - a0) % 360.0
    if sweep == 0:
        sweep = 360.0
    pts = []
    for i in range(n + 1):
        ang = math.radians(a0 + sweep * i / n)
        pts += [(cx + r * math.cos(ang)) * x_scale, cy + r * math.sin(ang)]
    return pts


def _scaled_items(name: str, x_scale: float):
    """Yield items. An x scale other than 1 thickens the section about its left edge."""
    doc = load_profile(name)
    for item in doc["items"]:
        kind = item[0]
        if x_scale == 1.0:
            yield item
            continue
        if kind == "L":
            _, x1, y1, x2, y2 = item
            yield ["L", x1 * x_scale, y1, x2 * x_scale, y2]
        elif kind in ("P", "R"):
            flag, pts = item[1], item[2]
            scaled = []
            for i in range(0, len(pts), 2):
                scaled += [pts[i] * x_scale, pts[i + 1]]
            yield [kind, flag, scaled]
        elif kind == "A":
            _, x, y, r, a0, a1 = item
            if x_scale == 1.0:
                yield item
            else:
                # Thickness scale turns a circular arc into an elliptical one.
                yield ["P", 0, _arc_points(x, y, r, a0, a1, x_scale)]
        elif kind == "C":
            _, x, y, r = item
            if x_scale == 1.0:
                yield item
            else:
                yield ["E", x * x_scale, y, r * x_scale, 0.0, 1.0 / x_scale]
        elif kind == "E":
            _, x, y, mx, my, ratio = item
            yield ["E", x * x_scale, y, mx * x_scale, my, ratio]
        elif kind == "S":
            pts = item[1]
            scaled = []
            for i in range(0, len(pts), 2):
                scaled += [pts[i] * x_scale, pts[i + 1]]
            yield ["S", scaled]
        elif kind == "T":
            _, x, y, h, rot, attach, text = item
            if x_scale != 1.0 and text.strip() == '1-3/4"':
                text = '2" (50 mm)'
            yield ["T", x * x_scale, y, h, rot, attach, text]
        else:
            yield item


def _bounds(items) -> Tuple[float, float, float, float]:
    xs, ys = [], []
    for item in items:
        kind = item[0]
        if kind == "L":
            _, x1, y1, x2, y2 = item
            xs += [x1, x2]
            ys += [y1, y2]
        elif kind in ("P", "R", "S"):
            pts = item[-1]
            xs += pts[0::2]
            ys += pts[1::2]
        elif kind in ("A", "C"):
            xs.append(item[1])
            ys.append(item[2])
        elif kind == "E":
            xs.append(item[1])
            ys.append(item[2])
        elif kind == "T":
            xs.append(item[1])
            ys.append(item[2])
            # The anchor is one corner of the text. Keep the rest of the
            # note inside the frame so a top-aligned callout is not clipped.
            _, tx, ty, th, _rot, attach, text = item
            lines = text.split("\n") or [""]
            tw = max(len(line) for line in lines) * th * 0.55
            thgt = len(lines) * th * 1.2
            _va, ha = _ALIGN.get(int(attach), ("top", "left"))
            va = _va
            if ha == "right":
                xs.append(tx - tw)
            elif ha == "center":
                xs += [tx - tw / 2, tx + tw / 2]
            else:
                xs.append(tx + tw)
            if va == "top":
                ys.append(ty - thgt)
            elif va == "center":
                ys += [ty - thgt / 2, ty + thgt / 2]
            else:
                ys.append(ty + thgt)
    return min(xs), min(ys), max(xs), max(ys)


def _draw_items(msp: Modelspace, items, box) -> None:
    x0, y0, x1, y1 = _bounds(items)
    width = max(x1 - x0, 1.0)
    height = max(y1 - y0, 1.0)
    bx0, by0, bx1, by1 = box
    margin = 0.06
    avail_w = max((bx1 - bx0) - 2 * margin, 0.2)
    avail_h = max((by1 - by0) - 2 * margin, 0.2)
    scale = min(avail_w / width, avail_h / height)
    ox = bx0 + margin + (avail_w - width * scale) / 2
    oy = by0 + margin + (avail_h - height * scale) / 2

    def X(x):
        return ox + (x - x0) * scale

    def Y(y):
        return oy + (y - y0) * scale

    geom = {"layer": "ANNOTATIONS", "lineweight": 13}
    for item in items:
        kind = item[0]
        if kind == "L":
            _, x1_, y1_, x2, y2 = item
            msp.add_line((X(x1_), Y(y1_)), (X(x2), Y(y2)), dxfattribs=geom)
        elif kind in ("P", "R"):
            closed, pts = item[1], item[2]
            points = [(X(pts[i]), Y(pts[i + 1])) for i in range(0, len(pts), 2)]
            if len(points) >= 2:
                msp.add_lwpolyline(points, close=bool(closed), dxfattribs=geom)
        elif kind == "A":
            _, cx, cy, r, a0, a1 = item
            if r * scale > 0:
                msp.add_arc((X(cx), Y(cy)), r * scale, a0, a1, dxfattribs=geom)
        elif kind == "C":
            _, cx, cy, r = item
            if r * scale > 0:
                msp.add_circle((X(cx), Y(cy)), r * scale, dxfattribs=geom)
        elif kind == "E":
            _, cx, cy, mx, my, ratio = item
            msp.add_ellipse(
                (X(cx), Y(cy)),
                major_axis=(mx * scale, my * scale),
                ratio=ratio,
                dxfattribs=geom,
            )
        elif kind == "S":
            pts = item[1]
            points = [(X(pts[i]), Y(pts[i + 1])) for i in range(0, len(pts), 2)]
            if len(points) >= 3:
                msp.add_solid(points[:4], dxfattribs=geom)
        elif kind == "T":
            _, tx, ty, th, rot, attach, text = item
            mtext = msp.add_mtext(
                text.replace("\n", "\\P"),
                dxfattribs={
                    "layer": "ANNOTATIONS",
                    "char_height": max(th * scale, 0.02),
                    "style": "Standard",
                    "attachment_point": int(attach) if int(attach) in _ALIGN else 1,
                    "width": 0,
                    "rotation": rot,
                },
            )
            mtext.dxf.insert = (X(tx), Y(ty))


def draw_real_panel_profile(msp: Modelspace, ctx, box) -> bool:
    """Draw the supplier section. Return False to keep the schematic."""
    chosen = _library_name(ctx.door_series)
    if chosen is None:
        return False
    name, x_scale = chosen
    _draw_items(msp, list(_scaled_items(name, x_scale)), box)
    return True


def draw_real_plan_view(msp: Modelspace, ctx, box) -> None:
    """Wood or steel jamb detail from the supplier jamb sheet.

    The supplier sheet is drawn on a 16 ft opening. The geometry stays.
    The 16 ft callout is replaced with this door's width.
    """
    from app.services.shop_drawings.framing import fmt_length_imperial
    width = fmt_length_imperial(ctx.door_width_in or 0)
    items = []
    for item in _scaled_items(_jamb_name(ctx.jamb_type), 1.0):
        if item[0] == "T" and str(item[-1]).strip() in ('16\'-0"', '16\'-0\"'):
            item = list(item)
            item[-1] = width
        items.append(item)
    _draw_items(msp, items, box)


def render_items_png(items, path: str, title: str = "") -> None:
    """Black-on-white render at a constant scale, for side-by-side checks."""
    import matplotlib
    matplotlib.use("Agg")
    from matplotlib import pyplot as plt
    from matplotlib.patches import Polygon, Circle, Arc as MplArc, Ellipse as MplEllipse
    x0, y0, x1, y1 = _bounds(items)
    width = max(x1 - x0, 1.0)
    height = max(y1 - y0, 1.0)
    fig_h = 11.0
    fig_w = max(fig_h * width / height, 3.0)
    fig, ax = plt.subplots(figsize=(fig_w, fig_h), facecolor="white")
    ax.set_facecolor("white")
    ax.set_xlim(x0, x1)
    ax.set_ylim(y0, y1)
    ax.set_aspect("equal")
    ax.axis("off")
    # Figure height in points divided by the data height is the text scale
    # when the axes fill the figure. set_position makes that true.
    ax.set_position([0.01, 0.01, 0.98, 0.96])
    pt_per_unit = (fig_h * 0.96 * 72.0) / height

    for item in items:
        kind = item[0]
        if kind == "L":
            _, a, b, c, d = item
            ax.plot([a, c], [b, d], color="#111", linewidth=0.4, solid_capstyle="round")
        elif kind in ("P", "R"):
            pts = item[-1]
            xs, ys = pts[0::2], pts[1::2]
            if item[0] == "P" and item[1] and xs:
                xs = xs + [xs[0]]
                ys = ys + [ys[0]]
            ax.plot(xs, ys, color="#111", linewidth=0.4)
        elif kind == "A":
            _, cx, cy, r, a0, a1 = item
            sweep = a1 if a1 > a0 else a1 + 360
            ax.add_patch(MplArc((cx, cy), 2 * r, 2 * r, angle=0, theta1=a0, theta2=sweep,
                                linewidth=0.4, color="#111", fill=False))
        elif kind == "C":
            _, cx, cy, r = item
            ax.add_patch(Circle((cx, cy), r, fill=False, edgecolor="#111", linewidth=0.4))
        elif kind == "E":
            _, cx, cy, mx, my, ratio = item
            import math
            ang = math.degrees(math.atan2(my, mx))
            wmaj = 2 * math.hypot(mx, my)
            ax.add_patch(MplEllipse((cx, cy), wmaj, wmaj * ratio, angle=ang,
                                    fill=False, edgecolor="#111", linewidth=0.4))
        elif kind == "S":
            pts = item[1]
            poly = [(pts[i], pts[i + 1]) for i in range(0, len(pts), 2)]
            ax.add_patch(Polygon(poly, closed=True, facecolor="#111", edgecolor="#111", linewidth=0.2))
        elif kind == "T":
            _, tx, ty, th, rot, attach, text = item
            va, ha = _ALIGN.get(int(attach), ("top", "left"))
            ax.text(tx, ty, text, fontsize=max(th * pt_per_unit, 1), color="#111",
                    rotation=rot, va=va, ha=ha, linespacing=1.05)
    if title:
        fig.suptitle(title, fontsize=11, fontweight="bold")
    fig.savefig(path, dpi=110, facecolor="white")
    plt.close(fig)


def render_profile_png(name: str, path: str, x_scale: float = 1.0, title: str = "") -> None:
    render_items_png(list(_scaled_items(name, x_scale)), path, title=title)
