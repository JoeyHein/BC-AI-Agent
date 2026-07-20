"""SKU geometry — the single source of truth for "how long is this part, and
what else could it be cut from?"

Length arithmetic was previously duplicated across four call sites in
``part_number_service._get_shaft_parts`` (all hardcoding ``ff * 12 + 6``, i.e.
silently assuming SH11) plus two inline copies in ``bc_part_number_mapper``.
This module replaces all of it.

Two families carry a linear, cuttable dimension:

**Panels** ``PN{ss}-{hh}{d}{cc}-{FFII}``
    The trailing FFII is the section WIDTH — which is also the physical length
    of the stick of steel. Everything before it (series, section height, stamp,
    colour) is the *cut family*: two SKUs in the same family differ only in how
    long they are, so one can be cut from the other. Section height is a
    discrete forming dimension and is NOT cuttable.

**Shafts** ``SH{ss}-1{FF}{ext}-00``
    Length is ``FF * 12 + ext`` where ext is a per-type constant (SH11 = 6",
    SH12 = 10"). The stocked ladder is sparse (no 12'6", no 14'6" in SH11),
    which is exactly why buying up and cutting down is routine here.

Colour and design can never be substituted. That falls out of the encoding for
free: both live upstream of the length segment, so a cut family is by
construction single-colour and single-design.
"""

import logging
import re
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


# ── Panel series classification ───────────────────────────────────────────────
# Residential panels may only be cut in Trafalgar and Flush; every other
# residential design carries a stamped pattern that will not line up once the
# section is shortened. Commercial may be cut in any design.
RESIDENTIAL_PANEL_PREFIXES = {"PN65", "PN95"}

COMMERCIAL_PANEL_PREFIXES = {
    "PN35", "PN36", "PN40", "PN45", "PN46", "PN47", "PN48",
    "PN50", "PN55", "PN56", "PN57", "PN58", "PN74", "PN75", "PN76",
}

# Aluminium / full-view. Glass pockets are cut to a layout the section is built
# around, so these are never length-substitutable.
ALUMINUM_PANEL_PREFIXES = {"PN10", "PN12", "PN97"}

# Stamp digits are SERIES-DEPENDENT — '3' is Trafalgar on PN65 but micro-groove
# on PN75. Never interpret a stamp digit without its prefix.
KANATA_CUTTABLE_STAMPS = {"0", "3"}   # 0 = FLUSH, 3 = TRAF/Trafalgar/RIB
CRAFT_CUTTABLE_STAMPS = {"0"}         # 0 = FLUSH only; Denison/Granville/Muskoka are stamped

# Shaft trailing-inch constant by series.
SHAFT_EXT_INCHES = {"SH11": 6, "SH12": 10}

PANEL_RE = re.compile(r"^(PN\d{2})-(\d{2})(\d)(\d{2})-(\d{4})$")
SHAFT_RE = re.compile(r"^(SH\d{2})-1(\d{2})(\d{2})-00$")


@dataclass(frozen=True)
class SkuGeometry:
    """Parsed physical geometry of a length-bearing SKU."""

    sku: str
    family: str          # cut-family key: same family => interchangeable by length
    length_inches: int
    kind: str            # "panel" | "shaft"
    cuttable: bool       # may this SKU be cut down to satisfy a shorter one?
    reason: str          # why not, when cuttable is False


def _panel_cuttable(prefix: str, stamp: str) -> tuple[bool, str]:
    """Apply the residential/commercial cutting rules to a panel."""
    if prefix in ALUMINUM_PANEL_PREFIXES:
        return False, "aluminium/full-view — built around a fixed glass layout"
    if prefix in COMMERCIAL_PANEL_PREFIXES:
        return True, ""
    if prefix in RESIDENTIAL_PANEL_PREFIXES:
        allowed = KANATA_CUTTABLE_STAMPS if prefix == "PN65" else CRAFT_CUTTABLE_STAMPS
        if stamp in allowed:
            return True, ""
        return False, f"residential {prefix} stamp {stamp} is a stamped design (only Traf/Flush may be cut)"
    return False, f"unknown panel series {prefix} — not cuttable until classified"


def parse(sku: str) -> Optional[SkuGeometry]:
    """Parse a SKU into its physical geometry, or None if it carries no
    cuttable linear dimension (hardware, springs, kits, unknown formats)."""
    if not sku:
        return None
    sku = sku.strip().upper()

    m = PANEL_RE.match(sku)
    if m:
        prefix, height, stamp, color, width = m.groups()
        try:
            length = int(width[:2]) * 12 + int(width[2:4])
        except ValueError:
            return None
        if length <= 0:
            return None
        cuttable, reason = _panel_cuttable(prefix, stamp)
        return SkuGeometry(
            sku=sku,
            # Family deliberately includes colour and stamp — they can never change.
            family=f"{prefix}-{height}{stamp}{color}",
            length_inches=length,
            kind="panel",
            cuttable=cuttable,
            reason=reason,
        )

    m = SHAFT_RE.match(sku)
    if m:
        prefix, feet, ext = m.groups()
        expected_ext = SHAFT_EXT_INCHES.get(prefix)
        if expected_ext is None:
            return None
        # The ext digits ARE the trailing inches; trust the SKU over the table
        # so an unexpected ladder entry parses correctly rather than silently
        # coming out short (the ff*12+6 bug this module replaces).
        try:
            ext_in = int(ext)
        except ValueError:
            return None
        if ext_in != expected_ext:
            logger.warning(
                "Shaft %s has ext %02d but %s is expected to use %02d — "
                "trusting the SKU", sku, ext_in, prefix, expected_ext
            )
        length = int(feet) * 12 + ext_in
        return SkuGeometry(
            sku=sku,
            family=prefix,
            length_inches=length,
            kind="shaft",
            cuttable=True,  # shafts are plain bar stock in every design
            reason="",
        )

    return None


def sku_to_inches(sku: str) -> Optional[int]:
    """Physical length of a SKU in inches, or None if it has no linear dimension."""
    geo = parse(sku)
    return geo.length_inches if geo else None


def cut_family(sku: str) -> Optional[str]:
    """Cut-family key. Two SKUs sharing a family differ ONLY in length, so the
    longer may be cut to yield the shorter."""
    geo = parse(sku)
    return geo.family if geo else None


def can_cut_from(donor_sku: str, target_sku: str) -> tuple[bool, str]:
    """May ``donor_sku`` be cut down to produce ``target_sku``?

    Returns (allowed, reason_if_not). Requires same cut family, a cuttable
    donor, and a donor at least as long as the target.
    """
    d, t = parse(donor_sku), parse(target_sku)
    if d is None or t is None:
        return False, "one or both SKUs carry no cuttable length dimension"
    if d.family != t.family:
        return False, f"different cut family ({d.family} vs {t.family}) — colour/design/height differ"
    if not d.cuttable:
        return False, d.reason
    if d.length_inches < t.length_inches:
        return False, f"donor {d.length_inches}\" is shorter than target {t.length_inches}\""
    return True, ""


def format_inches(total_inches: int) -> str:
    """Render inches as FF'II" for human-facing reports."""
    sign = "-" if total_inches < 0 else ""
    total = abs(int(total_inches))
    return f"{sign}{total // 12}'{total % 12}\""
