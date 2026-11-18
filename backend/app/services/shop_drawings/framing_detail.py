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

# Letter landscape, the page the Thermalex framing sheets print on.
SHEET_W = 11.0
SHEET_H = 8.5
_PROFILE_DIR = __import__("pathlib").Path(__file__).resolve().parent / "profiles"


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


def layout_key(sheet_name: str) -> str:
    """Which of the nine Thermalex framing sheets this detail follows."""
    name = (sheet_name or "").lower()
    tandem = "tandem" in name
    if name.startswith("center") or name.startswith("cen pad"):
        return "center_tandem" if tandem else "center"
    if name.startswith("2 pads"):
        if tandem:
            return "2_tandem"
        if "1 coupler" in name:
            return "2_one"
        return "2_two"
    if name.startswith("3 pads"):
        return "3_tandem" if tandem else "3"
    if name.startswith("4"):
        return "4"
    return "5"


def _wind_words(detail: FramingDetail, key: str) -> list[str]:
    """Wind labels the matching sheet prints on the pads and the springs."""
    hands = {s.hand for s in detail.springs if not s.nested}
    words = []
    if "LH" in hands:
        words.append("LH spring")
    if "RH" in hands:
        words.append("RH spring")
    if key == "4":
        if "LH" in hands:
            words.append("L wind")
        if "RH" in hands:
            words.append("R wind")
    if key in ("2_one", "5"):
        if "LH" in hands:
            words.append("LHW")
        if "RH" in hands:
            words.append("RHW")
    return words


def layout_labels(detail: FramingDetail) -> list[str]:
    """Every piece of text the framing sheet draws. No prices."""
    track = detail.track
    key = layout_key(detail.workbook_sheet)
    typical = 'min 22"' if track.tandem else 'min 10"'
    hl = _inches(track.high_lift_in) if track.high_lift_in is not None else "N/A"
    ust = track.ust_label
    labels = [
        "Headroom (Min)",
        f"H.R.: {_inches(track.headroom_in)}",
        "Shaft Elev.",
        f"CL Shaft: {_inches(track.shaft_from_floor_in)}",
        "Electric operator plate",
        f'{OPERATOR_PLATE_W_IN:.0f}" X {OPERATOR_PLATE_H_IN:.0f}" (W X H)',
        "(if required)",
        "* Electric operator plate not required for PAD operator",
        f"Opening Height (H): {_inches(detail.door_height_in)}",
        f"Opening Width (W): {_inches(detail.door_width_in)}",
        "75 mm Steel Frame (Typ.)",
        "JAMB & EXTENSION DRAWING",
        "SPECIAL INSTRUCTIONS",
        "1- Frames, their extension and anchor plates to be supplied by the General Contractor.",
        "2- All indicated clearances must be free of obstruction.",
        "3- Jambs must show an interior facade of at least 75 mm (3 in.) by 6 mm (1/4 in.).",
        f"Work Order #: {detail.job_number or ''}",
        f"Door(s) No.: {detail.door_number}",
        f"Track: {track.track_size_in}\"",
        f"Door Width (W): {_inches(detail.door_width_in)} ({_ft_in(detail.door_width_in)})",
        f"Door Height (H): {_inches(detail.door_height_in)} ({_ft_in(detail.door_height_in)})",
        f"High Lift (H.L.): {hl}",
        ust,
        f"Headroom (H.R.): {_inches(track.headroom_in)} ({_ft_in(track.headroom_in)})",
        'min 8"',
        typical,
        "BEARING PLATE",
        "SHAFT",
        "DRUM",
        f"JAMB EXTENSION {_inches(track.extension_in)}",
        "HEAD JAMB",
        "SIDE JAMB",
        "PAD PLATE SIZE: Ola",
        "HEAD-JAMB EXTRUSION: Ola",
        "JAMB PROFILE — Ola",
        "TX SECTION — Ola",
        f"Sheet: {detail.workbook_sheet}",
    ]
    if track.tandem or key.endswith("tandem") or key == "center_tandem":
        elev = track.tandem_shaft_from_floor_in
        labels.append("Tandem Shaft Elev.")
        if elev is not None:
            labels.append(f"CL Tandem Shaft: {_inches(elev)}")
    if detail.coupler_qty or key in ("2_one", "2_two", "5"):
        labels.append("COUPLER")
    if key == "2_one":
        labels.append('1" COUPLER')
    if key == "5" or detail.center_pickups:
        labels.append("CENTER DRUM")
    for pad in detail.pads:
        labels.append(pad.label)
        labels.append(
            f"{_inches(pad.x_from_left_jamb(detail.door_width_in))} from jamb"
        )
    labels.extend(_wind_words(detail, key))
    if detail.drum_model:
        labels.append(f"Drum {detail.drum_model}")
    return labels


def required_components(detail: FramingDetail) -> list[str]:
    """Labels a layout must draw. Substrings of ``layout_labels``."""
    key = layout_key(detail.workbook_sheet)
    required = [
        "Headroom (Min)",
        "H.R.:",
        "Shaft Elev.",
        "CL Shaft:",
        "Electric operator plate",
        '20" X 30"',
        "Opening Height (H):",
        "Opening Width (W):",
        "75 mm Steel Frame",
        "JAMB & EXTENSION DRAWING",
        "SPECIAL INSTRUCTIONS",
        "Work Order #:",
        "Door(s) No.:",
        "Track:",
        "Door Width (W):",
        "Door Height (H):",
        "High Lift (H.L.):",
        "U.S.T.",
        "Headroom (H.R.):",
        'min 8"',
        "BEARING PLATE",
        "SHAFT",
        "DRUM",
        "JAMB EXTENSION",
        "HEAD JAMB",
        "SIDE JAMB",
        "PAD PLATE SIZE: Ola",
        "HEAD-JAMB EXTRUSION: Ola",
        "JAMB PROFILE — Ola",
        "TX SECTION — Ola",
    ]
    if detail.track.tandem or "tandem" in key:
        required.append("Tandem Shaft Elev.")
        required.append('min 22"')
    else:
        required.append('min 10"')
    if detail.coupler_qty or key in ("2_one", "2_two", "5"):
        required.append("COUPLER")
    if key == "2_one":
        required.append('1" COUPLER')
    if key == "5" or detail.center_pickups:
        required.append("CENTER DRUM")
    required.extend(_wind_words(detail, key))
    if any(pad.role == "center" for pad in detail.pads):
        required.append("CENTER PAD")
    return required


def _profile_crop(kind: str):
    """Wood or steel half of Ola's jamb sheet, or the TX section."""
    import matplotlib.image as mpimg
    if kind == "tx":
        path = _PROFILE_DIR / "ola_tx_section_profiles.png"
        if not path.exists():
            return None
        return mpimg.imread(path)
    path = _PROFILE_DIR / "ola_jamb_profiles.png"
    if not path.exists():
        return None
    image = mpimg.imread(path)
    mid = image.shape[1] // 2
    if kind == "wood":
        return image[:, :mid]
    return image[:, mid:]


def _render_figure(detail: FramingDetail):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import FancyBboxPatch, Rectangle

    fig = plt.figure(figsize=(SHEET_W, SHEET_H), dpi=110)
    fig.patch.set_facecolor("white")
    ax = fig.add_axes((0, 0, 1, 1))
    ax.set_xlim(0, SHEET_W)
    ax.set_ylim(0, SHEET_H)
    ax.axis("off")
    ax.add_patch(Rectangle((0.25, 0.22), SHEET_W - 0.5, SHEET_H - 0.44,
                           fill=False, lw=1.1, ec="#222"))

    width = max(detail.door_width_in, 1.0)
    ox0, oy0, ox1, oy1 = 1.85, 1.85, 6.45, 5.05
    span = ox1 - ox0

    def sx(inches: float) -> float:
        return ox0 + span * (max(0.0, min(width, inches)) / width)

    # Side jambs and head jamb. The thick frame is the sheet's symbol.
    # The extrusion itself is Ola's and is not given a made-up profile.
    frame = FancyBboxPatch(
        (ox0, oy0), ox1 - ox0, oy1 - oy0,
        boxstyle="square,pad=0", linewidth=8, edgecolor="#b5b5b5", facecolor="white",
    )
    ax.add_patch(frame)
    ax.text(ox0 + 0.2, oy1 - 0.18, "HEAD JAMB", ha="left", va="top", fontsize=6, color="#444")
    ax.text(ox0 - 0.06, (oy0 + oy1) / 2, "SIDE JAMB", ha="right", va="center", fontsize=6, color="#444", rotation=90)
    ax.text((ox0 + ox1) / 2, oy0 + 0.12, "75 mm Steel Frame (Typ.)", ha="center", fontsize=6.5)

    ext_top = oy1 + 0.85
    ax.plot([ox0, ox0], [oy1, ext_top], color="#666", lw=1.0, ls=(0, (3, 2)))
    ax.plot([ox1, ox1], [oy1, ext_top], color="#666", lw=1.0, ls=(0, (3, 2)))
    ax.text(ox0 - 0.08, (oy1 + ext_top) / 2, f"JAMB EXTENSION {_inches(detail.track.extension_in)}",
            ha="right", va="center", fontsize=5.5, rotation=90)

    # Shaft, tandem shaft, drums, pads, springs.
    pad_h = 0.58
    shaft_y = oy1 + pad_h * 0.45
    ax.plot([ox0 - 0.05, ox1 + 0.35], [shaft_y, shaft_y], color="#222", lw=1.3)
    ax.text(ox1 + 0.38, shaft_y, "SHAFT", fontsize=6, va="center", color="#222")
    ax.text(ox0 - 0.08, shaft_y + 0.22, "Shaft Elev.", fontsize=6, color="#333", ha="right")
    if detail.track.tandem:
        ty = shaft_y + 0.32
        ax.plot([ox0 - 0.05, ox1 + 0.35], [ty, ty], color="#222", lw=0.9, ls=(0, (4, 2)))
        ax.text(ox1 + 0.38, ty, "Tandem Shaft Elev.", fontsize=5.5, va="center")

    drum_w = 0.16
    for edge, anchor in ((ox0 + 0.18, "left"), (ox1 - 0.18, "right")):
        ax.add_patch(Rectangle((edge - drum_w / 2, shaft_y - 0.12), drum_w, 0.24,
                               facecolor="#d9d9d9", edgecolor="#333", lw=0.6))
        ax.text(edge, shaft_y - 0.2, "DRUM", ha="center", va="top", fontsize=5)
    if layout_key(detail.workbook_sheet) == "5" or detail.center_pickups:
        cx = sx(width / 2)
        ax.add_patch(Rectangle((cx - 0.1, shaft_y + 0.16), 0.2, 0.16,
                               facecolor="#c8c8c8", edgecolor="#333", lw=0.6))
        ax.text(cx, shaft_y + 0.34, "CENTER DRUM", ha="center", fontsize=5)

    pads = sorted(detail.pads, key=lambda pad: pad.x_from_left_jamb(width))
    pad_w = 0.26
    for pad in pads:
        left = pad.x_from_left_jamb(width)
        x = sx(left)
        ax.add_patch(Rectangle((x - pad_w / 2, oy1), pad_w, pad_h,
                               facecolor="#cfcfcf", edgecolor="#333", lw=0.7))
        ax.text(x, oy1 + pad_h + 0.02, pad.label, ha="center", va="bottom", fontsize=5, color="#7c2d12")
    if pads:
        anchor = sx(pads[0].x_from_left_jamb(width)) - 0.22
        ax.annotate(
            "", xy=(anchor, oy1 + pad_h), xytext=(anchor, oy1),
            arrowprops=dict(arrowstyle="<->", color="#222", lw=0.6),
        )
        ax.text(anchor - 0.06, oy1 + pad_h * 0.5, 'min 8"',
                ha="right", va="center", fontsize=5.5, color="#222")
    ax.text(ox0 + 0.35, oy1 - 0.36, "BEARING PLATE", fontsize=5.5, color="#333")

    # Springs sit on the shaft between the drums and the pads.
    stations = [0.0] + [pad.x_from_left_jamb(width) for pad in pads] + [width]
    for left_in, right_in in zip(stations, stations[1:]):
        mid = (left_in + right_in) / 2
        if right_in - left_in < width * 0.04:
            continue
        wind = "LH spring" if mid < width / 2 else "RH spring"
        if not any(s.hand == ("LH" if mid < width / 2 else "RH") and not s.nested for s in detail.springs):
            if not detail.springs:
                wind = "SPRING"
            elif mid < width / 2 and not any(s.hand == "LH" and not s.nested for s in detail.springs):
                continue
            elif mid >= width / 2 and not any(s.hand == "RH" and not s.nested for s in detail.springs):
                wind = "LH spring" if any(s.hand == "LH" for s in detail.springs) else wind
        x0, x1 = sx(left_in), sx(right_in)
        ax.plot([x0 + 0.08, x1 - 0.08], [shaft_y, shaft_y], color="#9a3412", lw=2.5, solid_capstyle="butt")
        ax.text((x0 + x1) / 2, shaft_y + 0.1, wind, ha="center", fontsize=4.5, color="#9a3412")

    key = layout_key(detail.workbook_sheet)
    if detail.coupler_qty or key in ("2_one", "2_two", "5"):
        label = '1" COUPLER' if key == "2_one" else "COUPLER"
        ax.annotate(
            label, xy=(sx(width / 2), oy1 - 0.05), xytext=(sx(width / 2), oy1 - 0.55),
            ha="center", fontsize=6,
            arrowprops=dict(arrowstyle="-", color="#333", lw=0.6),
        )

    # Dimension chain across the head, from the spring-based pad stations.
    chain_y = 6.55
    marks = [0.0] + [pad.x_from_left_jamb(width) for pad in pads] + [width]
    ax.annotate(
        "", xy=(sx(width), chain_y), xytext=(sx(0), chain_y),
        arrowprops=dict(arrowstyle="<->", color="#222", lw=0.7),
    )
    for a, b in zip(marks, marks[1:]):
        ax.text(sx((a + b) / 2), chain_y + 0.06, _inches(b - a), ha="center", va="bottom", fontsize=6)

    typical = 'min 22" (Typ.)' if detail.track.tandem else 'min 10" (Typ.)'
    ax.text(sx(width * 0.25), shaft_y + 0.42, typical, fontsize=6, color="#222")

    # Headroom and opening dimensions.
    ax.annotate(
        "", xy=(0.7, oy1 + pad_h), xytext=(0.7, oy0),
        arrowprops=dict(arrowstyle="<->", color="#222", lw=0.7),
    )
    ax.text(0.55, (oy0 + oy1) / 2, "Headroom (Min)", rotation=90, va="center", ha="center", fontsize=6)
    ax.text(0.95, oy1 + 0.15, f"H.R.: {_inches(detail.track.headroom_in)}", fontsize=6.5)
    ax.text(1.15, (oy0 + oy1) / 2, f"CL Shaft: {_inches(detail.track.shaft_from_floor_in)}",
            rotation=90, va="center", fontsize=6)
    ax.annotate(
        "", xy=(ox1 + 0.22, oy1), xytext=(ox1 + 0.22, oy0),
        arrowprops=dict(arrowstyle="<->", color="#222", lw=0.7),
    )
    ax.text(ox1 + 0.28, (oy0 + oy1) / 2, f"Opening Height (H): {_inches(detail.door_height_in)}",
            rotation=90, va="center", fontsize=6)
    ax.annotate(
        "", xy=(ox1, oy0 - 0.22), xytext=(ox0, oy0 - 0.22),
        arrowprops=dict(arrowstyle="<->", color="#222", lw=0.7),
    )
    ax.text((ox0 + ox1) / 2, oy0 - 0.38, f"Opening Width (W): {_inches(detail.door_width_in)}",
            ha="center", fontsize=6.5)
    hl = _inches(detail.track.high_lift_in) if detail.track.high_lift_in is not None else "N/A"
    ax.text(sx(width * 0.72), shaft_y - 0.35, f"H.L.: {hl}", fontsize=6)
    ax.text(sx(width * 0.72), shaft_y - 0.52, detail.track.ust_label, fontsize=6)

    # Operator plate, always on the sheet, marked when this quote needs it.
    plate_x = 6.55 if detail.operator_side != "left" else 1.15
    ax.add_patch(Rectangle((plate_x, oy1 + 0.05), 0.72, 0.95,
                           fill=False, lw=0.8, ec="#222"))
    ax.text(plate_x + 0.36, oy1 + 0.72, "Electric\noperator\nplate", ha="center", va="center", fontsize=5)
    ax.text(plate_x + 0.36, oy1 + 0.18, f'{OPERATOR_PLATE_W_IN:.0f}" X {OPERATOR_PLATE_H_IN:.0f}"',
            ha="center", fontsize=4.5)
    ax.text(plate_x + 0.36, oy1 - 0.02, "(if required)", ha="center", va="top", fontsize=4.5)
    if not detail.operator_plate:
        ax.text(plate_x, oy1 - 0.22, "not required", ha="left", fontsize=4.5, color="#555")

    _title_block(ax, detail)
    _profile_insets(fig, detail)
    return fig


def _title_block(ax, detail: FramingDetail) -> None:
    from matplotlib.patches import Rectangle
    x0, y0, x1, y1 = 7.55, 0.4, 10.7, 8.15
    ax.add_patch(Rectangle((x0, y0), x1 - x0, y1 - y0, fill=False, lw=0.8, ec="#222"))
    track = detail.track
    hl = _inches(track.high_lift_in) if track.high_lift_in is not None else "N/A"
    lines = [
        f"Work Order #: {detail.job_number or '—'}",
        f"Door(s) No.: {detail.door_number}",
        f"Track: {track.track_size_in}\"",
        f"Door Width (W): {_inches(detail.door_width_in)} ({_ft_in(detail.door_width_in)})",
        f"Door Height (H): {_inches(detail.door_height_in)} ({_ft_in(detail.door_height_in)})",
        f"High Lift (H.L.): {hl}",
        track.ust_label,
        f"CL Shaft: {_inches(track.shaft_from_floor_in)}",
        f"Headroom (H.R.): {_inches(track.headroom_in)}",
        f"Sheet: {detail.workbook_sheet}",
        "PAD PLATE SIZE: Ola",
        "HEAD-JAMB EXTRUSION: Ola",
        "* Electric operator plate not required for PAD operator",
    ]
    if track.tandem_shaft_from_floor_in is not None:
        lines.insert(8, f"CL Tandem Shaft: {_inches(track.tandem_shaft_from_floor_in)}")
    ax.text(x0 + 0.08, y1 - 0.12, "\n".join(lines), va="top", fontsize=5.4, family="DejaVu Sans", linespacing=1.25)
    ax.text(x0 + 0.08, 4.15, "SPECIAL INSTRUCTIONS", fontsize=6, fontweight="bold")
    ax.text(
        x0 + 0.08, 3.95,
        "1- Frames, their extension and anchor plates to be supplied\n"
        "by the General Contractor.\n"
        "2- All indicated clearances must be free of obstruction.\n"
        "3- Jambs must show an interior facade of at least\n"
        "75 mm (3 in.) by 6 mm (1/4 in.).",
        va="top", fontsize=4.6, family="DejaVu Sans", linespacing=1.2,
    )
    ax.plot([x0, x1], [1.55, 1.55], color="#222", lw=0.6)
    ax.text(x0 + 0.08, 1.38, "JAMB & EXTENSION DRAWING", fontsize=6, fontweight="bold")
    ax.text(
        x0 + 0.08, 1.18,
        f"PROJECT: {detail.customer_name or ''}\nDATE: {detail.drawing_date or ''}",
        va="top", fontsize=5.5,
    )


def _profile_insets(fig, detail: FramingDetail) -> None:
    import matplotlib.pyplot as plt
    kind = "wood" if detail.jamb_type == "wood" else "steel"
    jamb = _profile_crop(kind)
    tx = _profile_crop("tx")
    axj = fig.add_axes((0.035, 0.035, 0.13, 0.16))
    if jamb is not None:
        axj.imshow(jamb)
    axj.axis("off")
    axj.set_title("JAMB PROFILE — Ola", fontsize=5, color="#222")
    axt = fig.add_axes((0.17, 0.04, 0.08, 0.14))
    if tx is not None:
        axt.imshow(tx)
    axt.axis("off")
    axt.set_title("TX SECTION — Ola", fontsize=4.5, color="#222")


def detail_to_pdf(detail: FramingDetail) -> bytes:
    from matplotlib.backends.backend_pdf import PdfPages
    fig = _render_figure(detail)
    buf = io.BytesIO()
    with PdfPages(buf) as pdf:
        pdf.savefig(fig)
        pdf.infodict().update({
            "Title": "OpenDC framing detail",
            "Subject": detail.workbook_sheet,
        })
    import matplotlib.pyplot as plt
    plt.close(fig)
    return buf.getvalue()


def detail_to_png(detail: FramingDetail, path: str) -> None:
    import matplotlib.pyplot as plt
    fig = _render_figure(detail)
    fig.savefig(path, dpi=110)
    plt.close(fig)


def detail_to_dxf(detail: FramingDetail) -> bytes:
    """DXF of the same sheet. Text is the component list; geometry is the opening and pads."""
    doc = ezdxf.new(dxfversion="R2013", setup=True)
    doc.header["$INSUNITS"] = 1
    std = doc.styles.get("Standard")
    std.dxf.font = "LiberationSans-Regular.ttf"
    for name, color in (("FRAMING", 1), ("ANNOTATIONS", 7), ("PADS", 30)):
        if name not in doc.layers:
            layer = doc.layers.add(name)
            layer.color = color
    msp = doc.modelspace()
    msp.add_lwpolyline(
        [(0.25, 0.22), (SHEET_W - 0.25, 0.22), (SHEET_W - 0.25, SHEET_H - 0.22), (0.25, SHEET_H - 0.22)],
        close=True, dxfattribs={"layer": "FRAMING"},
    )
    ox0, oy0, ox1, oy1 = 1.85, 1.85, 6.45, 5.05
    msp.add_lwpolyline(
        [(ox0, oy0), (ox1, oy0), (ox1, oy1), (ox0, oy1)],
        close=True, dxfattribs={"layer": "FRAMING"},
    )
    width = max(detail.door_width_in, 1.0)
    span = ox1 - ox0
    for pad in detail.pads:
        x = ox0 + span * (pad.x_from_left_jamb(width) / width)
        msp.add_lwpolyline(
            [(x - 0.13, oy1), (x + 0.13, oy1), (x + 0.13, oy1 + 0.5), (x - 0.13, oy1 + 0.5)],
            close=True, dxfattribs={"layer": "PADS"},
        )
    labels = layout_labels(detail)
    half = (len(labels) + 1) // 2
    for column, chunk in enumerate((labels[:half], labels[half:])):
        y = SHEET_H - 0.45
        x = 0.4 + column * 5.2
        for line in chunk:
            msp.add_text(
                line[:120], height=0.08, dxfattribs={"layer": "ANNOTATIONS"},
            ).set_placement((x, y), align=TextEntityAlignment.LEFT)
            y -= 0.16
    buf = io.StringIO()
    doc.write(buf)
    return buf.getvalue().encode("utf-8")


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
