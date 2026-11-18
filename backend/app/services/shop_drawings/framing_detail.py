"""Customer framing-detail sheet: pads, jamb and extension.

TX-series doors get this sheet. Every other series falls back to the
existing framing drawing so that path stays intact. The sheet has no
prices and no costs.

TODO(Ola): pad plate size and the head-jamb extrusion. This sheet marks
the anchor and calls out the sideroom already in the profile library.
"""

from __future__ import annotations

import io
from datetime import datetime
from typing import Optional

import ezdxf
from ezdxf.enums import TextEntityAlignment

from app.services.shop_drawings.thermalex_framing import (
    JAMB_FACE_MIN_MM,
    MIN_JAMB_CLEAR_IN,
    MIN_JAMB_CLEAR_TANDEM_IN,
    MIN_PAD_GAP_IN,
    OPERATOR_PLATE_H_IN,
    OPERATOR_PLATE_W_IN,
    FramingDetail,
    build_framing_detail,
    is_workbook_tx_series,
)

SHEET_W = 17.0
SHEET_H = 11.0


def framing_detail_kind(series: Optional[str]) -> str:
    """``thermalex`` for a TX door the workbook covers, otherwise ``shop``."""
    return "thermalex" if is_workbook_tx_series(series) else "shop"


def _door(config_data: dict, door_index: int) -> dict:
    doors = (config_data or {}).get("doors") or []
    if not doors:
        raise ValueError("Config has no doors to draw")
    if door_index < 0 or door_index >= len(doors):
        raise ValueError(f"door_index {door_index} out of range (have {len(doors)})")
    return doors[door_index]


def _ft_in(inches: Optional[float]) -> str:
    if inches is None:
        return "N/A"
    sign = "-" if inches < 0 else ""
    value = abs(float(inches))
    feet = int(value // 12)
    rest = value - feet * 12
    rest = round(rest, 2)
    if abs(rest - round(rest)) < 0.05:
        rest_s = str(int(round(rest)))
    else:
        rest_s = f"{rest:.2f}".rstrip("0").rstrip(".")
    if feet and float(rest_s or 0):
        return f"{sign}{feet}'-{rest_s}\""
    if feet:
        return f"{sign}{feet}'"
    return f"{sign}{rest_s}\""


def _inches(value: Optional[float]) -> str:
    if value is None:
        return "N/A"
    rounded = round(float(value), 2)
    if abs(rounded - round(rounded)) < 0.001:
        return f"{int(round(rounded))}\""
    text = f"{rounded:.2f}".rstrip("0").rstrip(".")
    return f"{text}\""


def sheet_lines(detail: FramingDetail) -> list[str]:
    """Customer-facing lines. No price, cost, or margin."""
    track = detail.track
    lines = [
        "FRAMING DETAIL  —  PADS, JAMB AND EXTENSION",
        f"{detail.series or 'TX'}    {_ft_in(detail.door_width_in)} wide  ×  {_ft_in(detail.door_height_in)} high",
        f"Job {detail.job_number or '—'}    {detail.customer_name or ''}".strip(),
        f"Closest Thermalex sheet: {detail.workbook_sheet}",
        f"Track {track.track_size_in}\"    {track.lift.replace('_', ' ')}    radius {_inches(track.radius_in)}",
        f"Opening width (W): {_inches(detail.door_width_in)} ({_ft_in(detail.door_width_in)})",
        f"Opening height (H): {_inches(detail.door_height_in)} ({_ft_in(detail.door_height_in)})",
        f"High lift (H.L.): {_inches(track.high_lift_in) if track.high_lift_in is not None else 'N/A'}",
        track.ust_label,
        f"Shaft centerline from floor: {_inches(track.shaft_from_floor_in)} ({_ft_in(track.shaft_from_floor_in)})",
        f"Shaft centerline above opening: {_inches(track.cl_from_header_in)}",
        f"Headroom (H.R.): {_inches(track.headroom_in)} ({_ft_in(track.headroom_in)})",
    ]
    if track.tandem_shaft_from_floor_in is not None:
        lines.append(
            f"Tandem shaft centerline: {_inches(track.tandem_shaft_from_floor_in)} "
            f"({_ft_in(track.tandem_shaft_from_floor_in)})"
        )
    lines.append(f"Vertical track: {_inches(track.vertical_track_in)}")
    if track.extension_in > 0.05:
        lines.append(f"Track extension: {_inches(track.extension_in)} ({_ft_in(track.extension_in)})")
    else:
        lines.append("Track extension: none")
    lines.append(
        f"Jamb: {detail.jamb_type} sideroom {_inches(detail.sideroom_in)}. "
        f"Steel face at least {JAMB_FACE_MIN_MM:.0f} mm (3 in.) wide by 6 mm (1/4 in.) thick."
    )
    lines.append(
        f"Pads: {detail.pad_count}    "
        f"min {MIN_PAD_GAP_IN:.0f}\" between pads, "
        f"min {MIN_JAMB_CLEAR_TANDEM_IN if track.tandem else MIN_JAMB_CLEAR_IN:.0f}\" to the jamb"
    )
    for pad in detail.pads:
        left = pad.x_from_left_jamb(detail.door_width_in)
        lines.append(
            f"{pad.label}: {_inches(left)} from left jamb, "
            f"{_inches(pad.x_from_right_jamb(detail.door_width_in))} from right jamb, "
            f"{_inches(pad.x_from_center_in)} from centerline"
        )
    if detail.springs:
        lh = sum(1 for s in detail.springs if s.hand == "LH")
        rh = sum(1 for s in detail.springs if s.hand == "RH")
        lines.append(
            f"Springs: {detail.spring_count} total ({lh} LH + {rh} RH), "
            f"{detail.axial_count} on the shaft"
        )
        seen = set()
        for spring in detail.springs:
            key = (spring.hand, spring.nested, round(spring.wire, 4), round(spring.cut_length, 2), round(spring.turns, 2))
            if key in seen:
                continue
            seen.add(key)
            kind = "inner duplex" if spring.nested else spring.hand
            lines.append(
                f"  {kind}: {_fmt_wire(spring.wire)} wire × {spring.coil:g}\" ID × "
                f"{_inches(spring.cut_length)} cut, {spring.turns:.1f} turns, "
                f"installed {_inches(spring.length_in)}"
            )
    if detail.drum_model:
        lines.append(f"Drum {detail.drum_model} width {_inches(detail.drum_width_in)} (workbook)")
    lines.append(f"Couplers: {detail.coupler_qty}")
    if detail.center_shaft_in:
        lines.append(f"Workbook center shaft: {_inches(detail.center_shaft_in)}")
    if detail.assembly_length_in:
        lines.append(f"Spring assembly length: {_inches(detail.assembly_length_in)}")
    if detail.operator_plate:
        lines.append(
            f"Electric operator plate {OPERATOR_PLATE_W_IN:.0f}\" × {OPERATOR_PLATE_H_IN:.0f}\" "
            f"(W × H), {detail.operator_side} side, if required. "
            "See the operator manual for the plate elevation. Not used for a pad operator."
        )
    else:
        lines.append("Operator plate: not required")
    lines.append("Pad locations follow this quote's spring assembly.")
    lines.append("TODO(Ola): head-jamb extrusion and pad plate size are not drawn.")
    for note in detail.notes:
        # Engineer flags stay on the detail object for tests and the PR.
        # The customer sheet only keeps clearance and fit warnings.
        if note.startswith("FLAG JOEY") or "Confirm with Joey" in note:
            continue
        if note not in lines:
            lines.append(note)
    return lines


def _fmt_wire(wire: float) -> str:
    return f"{wire:.3f}\""


def detail_to_pdf(detail: FramingDetail) -> bytes:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.backends.backend_pdf import PdfPages

    fig = plt.figure(figsize=(SHEET_W, SHEET_H), dpi=120)
    fig.patch.set_facecolor("white")
    ax = fig.add_axes((0, 0, 1, 1))
    ax.set_xlim(0, SHEET_W)
    ax.set_ylim(0, SHEET_H)
    ax.axis("off")
    ax.add_patch(plt.Rectangle((0.35, 0.3), SHEET_W - 0.7, SHEET_H - 0.6,
                               fill=False, lw=1.4, ec="#1a1a1a"))
    _draw_plan(ax, detail)
    _draw_schedule(ax, detail)
    buf = io.BytesIO()
    with PdfPages(buf) as pdf:
        pdf.savefig(fig)
        pdf.infodict().update({
            "Title": "OpenDC framing detail",
            "Subject": "Pads, jamb and extension",
        })
    plt.close(fig)
    return buf.getvalue()


def detail_to_png(detail: FramingDetail, path: str) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig = plt.figure(figsize=(SHEET_W, SHEET_H), dpi=110)
    fig.patch.set_facecolor("white")
    ax = fig.add_axes((0, 0, 1, 1))
    ax.set_xlim(0, SHEET_W)
    ax.set_ylim(0, SHEET_H)
    ax.axis("off")
    ax.add_patch(plt.Rectangle((0.35, 0.3), SHEET_W - 0.7, SHEET_H - 0.6,
                               fill=False, lw=1.4, ec="#1a1a1a"))
    _draw_plan(ax, detail)
    _draw_schedule(ax, detail)
    fig.savefig(path, dpi=110)
    plt.close(fig)


def _draw_plan(ax, detail: FramingDetail) -> None:
    """Head plan: jambs at the ends, pads at the spring anchors."""
    x0, x1 = 0.7, 16.3
    y = 8.15
    span = x1 - x0
    width = max(detail.door_width_in, 1.0)

    def sx(inches: float) -> float:
        return x0 + span * (inches / width)

    ax.plot([x0, x1], [y, y], color="#1a1a1a", lw=2.0, solid_capstyle="butt")
    for jamb in (0.0, width):
        ax.plot([sx(jamb), sx(jamb)], [y - 0.45, y + 0.55], color="#1a1a1a", lw=3.0)
    # Sideroom tick outside each jamb. Not a fabricated extrusion.
    side = detail.sideroom_in
    ax.plot([sx(0) - span * side / width, sx(0)], [y - 0.15, y - 0.15], color="#555555", lw=1.0)
    ax.plot([sx(width), sx(width) + span * side / width], [y - 0.15, y - 0.15], color="#555555", lw=1.0)
    ax.text(sx(0), y - 0.72, "JAMB", ha="center", va="top", fontsize=7, color="#1a1a1a")
    ax.text(sx(width), y - 0.72, "JAMB", ha="center", va="top", fontsize=7, color="#1a1a1a")

    center = sx(width / 2.0)
    ax.plot([center, center], [y - 0.35, y + 1.15], color="#1d4e89", lw=0.8, ls=(0, (4, 2, 1, 2)))
    ax.text(center, y + 1.28, "CENTERLINE", ha="center", va="bottom", fontsize=7, color="#1d4e89")

    if detail.drum_width_in > 0:
        for station in (detail.drum_width_in, width - detail.drum_width_in):
            ax.plot([sx(station), sx(station)], [y - 0.28, y + 0.28], color="#888888", lw=0.8, ls="--")
        ax.text(sx(detail.drum_width_in), y + 0.38, "DRUM", ha="center", fontsize=6, color="#666666")

    for pad in detail.pads:
        left = pad.x_from_left_jamb(detail.door_width_in)
        px = sx(left)
        ax.add_patch(plt_rect(px - 0.09, y - 0.22, 0.18, 0.44))
        ax.plot([px, px], [y + 0.22, y + 0.85], color="#9a3412", lw=0.6)
        ax.text(px, y + 0.9, pad.label, ha="center", va="bottom", fontsize=6.5, color="#9a3412")
        ax.text(
            px, y - 0.95,
            f"{_inches(left)} from jamb\n{_inches(pad.x_from_center_in)} from CL",
            ha="center", va="top", fontsize=6, color="#1a1a1a",
        )

    ax.annotate(
        "", xy=(x1, y + 1.7), xytext=(x0, y + 1.7),
        arrowprops=dict(arrowstyle="<->", color="#1a1a1a", lw=0.8),
    )
    ax.text(
        (x0 + x1) / 2, y + 1.82,
        f"Opening width (W)  {_inches(detail.door_width_in)}  ({_ft_in(detail.door_width_in)})",
        ha="center", va="bottom", fontsize=8,
    )
    ax.text(
        0.55, 9.85,
        "FRAMING DETAIL  —  PADS, JAMB AND EXTENSION",
        fontsize=12, fontweight="bold", color="#1a1a1a",
    )
    ax.text(
        0.55, 9.55,
        f"{detail.series or 'TX'}     {_ft_in(detail.door_width_in)}  ×  {_ft_in(detail.door_height_in)}"
        f"     Job {detail.job_number or '—'}     {detail.customer_name or ''}",
        fontsize=8, color="#333333",
    )


def plt_rect(x, y, w, h):
    import matplotlib.pyplot as plt
    return plt.Rectangle((x, y), w, h, facecolor="#fff7ed", edgecolor="#9a3412", lw=1.2)


def _draw_schedule(ax, detail: FramingDetail) -> None:
    lines = sheet_lines(detail)
    # The title and the two header lines are already on the plan.
    body = [line for line in lines if not line.startswith("FRAMING DETAIL") and not line.startswith(detail.series or "TX")]
    # Drop the job line if it was the third header.
    if body and body[0].startswith("Job "):
        body = body[1:]
    text = "\n".join(body[:28])
    ax.text(
        0.55, 6.35, text,
        fontsize=7.2, family="DejaVu Sans", color="#1a1a1a", va="top",
        linespacing=1.35,
    )
    ax.text(
        0.55, 0.42,
        "No prices on this sheet. Frames and anchor plates are by the general contractor. "
        "Keep the marked clearances free of obstruction.",
        fontsize=6.5, color="#444444",
    )


def detail_to_dxf(detail: FramingDetail) -> bytes:
    doc = ezdxf.new(dxfversion="R2013", setup=True)
    doc.header["$INSUNITS"] = 1
    std = doc.styles.get("Standard")
    std.dxf.font = "LiberationSans-Regular.ttf"
    if "FRAMING" not in doc.layers:
        layer = doc.layers.add("FRAMING")
        layer.color = 1
    if "ANNOTATIONS" not in doc.layers:
        layer = doc.layers.add("ANNOTATIONS")
        layer.color = 7
    msp = doc.modelspace()
    msp.add_lwpolyline(
        [(0.35, 0.3), (SHEET_W - 0.35, 0.3), (SHEET_W - 0.35, SHEET_H - 0.3), (0.35, SHEET_H - 0.3)],
        close=True,
        dxfattribs={"layer": "FRAMING"},
    )
    y = 10.2
    for line in sheet_lines(detail):
        msp.add_text(
            line[:180],
            height=0.12,
            dxfattribs={"layer": "ANNOTATIONS"},
        ).set_placement((0.5, y), align=TextEntityAlignment.LEFT)
        y -= 0.2
        if y < 0.4:
            break
    _dxf_plan(msp, detail)
    buf = io.StringIO()
    doc.write(buf)
    return buf.getvalue().encode("utf-8")


def _dxf_plan(msp, detail: FramingDetail) -> None:
    width = max(detail.door_width_in, 1.0)
    x0, x1, y = 0.7, 16.3, 2.4
    span = x1 - x0

    def sx(inches: float) -> float:
        return x0 + span * (inches / width)

    msp.add_line((x0, y), (x1, y), dxfattribs={"layer": "FRAMING"})
    msp.add_line((sx(0), y - 0.3), (sx(0), y + 0.3), dxfattribs={"layer": "FRAMING"})
    msp.add_line((sx(width), y - 0.3), (sx(width), y + 0.3), dxfattribs={"layer": "FRAMING"})
    for pad in detail.pads:
        px = sx(pad.x_from_left_jamb(detail.door_width_in))
        msp.add_lwpolyline(
            [(px - 0.08, y - 0.15), (px + 0.08, y - 0.15), (px + 0.08, y + 0.15), (px - 0.08, y + 0.15)],
            close=True,
            dxfattribs={"layer": "FRAMING"},
        )


def generate_framing_detail(
    config_data: dict,
    customer_name: str,
    job_number: str,
    fmt: str = "pdf",
    drawing_date: Optional[datetime] = None,
    config_id: Optional[int] = None,
    door_index: int = 0,
    db=None,
) -> bytes:
    """PDF or DXF for one door on a quote.

    TX-series doors get the pad, jamb and extension sheet. Other series
    get the existing framing drawing, unchanged.
    """
    fmt = (fmt or "pdf").lower()
    if fmt not in ("pdf", "dxf"):
        raise ValueError("fmt must be 'pdf' or 'dxf'")
    door = _door(config_data, door_index)
    series = str(door.get("doorSeries") or "")
    if framing_detail_kind(series) != "thermalex":
        from app.services.shop_drawings.framing import generate_framing_drawing
        return generate_framing_drawing(
            config_data=config_data,
            customer_name=customer_name,
            job_number=job_number,
            fmt=fmt,
            drawing_date=drawing_date,
            config_id=config_id,
            door_index=door_index,
            db=db,
        )
    date_str = (drawing_date or datetime.utcnow()).strftime("%Y-%m-%d")
    detail = build_framing_detail(
        door,
        customer_name=customer_name or "",
        job_number=job_number or "",
        drawing_date=date_str,
    )
    if fmt == "dxf":
        return detail_to_dxf(detail)
    return detail_to_pdf(detail)
