"""Weatherstrip is bought from Elton Manufacturing or used from stock.

It does not go on an Upwardor door purchase order. Sales quotes and sales
orders still carry the lines — this module only decides what an Upwardor PO
must leave off.

How an item is recognized (checked against the BC item catalog in
``backend/data/bc_analysis/bc_items.json``):

Item numbers
  * ``PL11-*`` — dual-fin and tri-seal weatherstrip (resi and commercial).
  * ``PL10-{length}203-{color}`` — galvanized steel / flexible vinyl weatherstrip
    (for example ``PL10-08203-00``).
  * Known bottom-seal, top-seal, bubble-seal, and vinyl-for-weatherstrip
    SKUs listed in ``KNOWN_WEATHERSTRIP_ITEMS``.

Descriptions (so a hand-keyed line with a matching name is caught even when
the item number is new)
  * WEATHER STRIP / WEATHERSTRIP, DUAL FIN / DUAL-FIN, TRI-SEAL,
    TOP SEAL, BOTTOM SEAL, BUBBLE SEAL, U-rubber, or ``W/S``.

Not weatherstrip (these stay eligible for an Upwardor PO)
  * Astragal / bottom rubber that ships with the door package
    (``PL10-00004-00``, ``PL10-00005-01`` / ``02`` / ``03``). Joey, 2026-10:
    that astragal stays on the Upwardor door PO. A complete roll bought on
    its own is a manual Elton purchase, not this exclusion.
  * Rigid aluminum retainers (``TOP/BOTTOM RETAINER``, ``BOTTOM RETAINER``,
    ``PL15-*`` aluminium retainer, Panorama bottom retainer). The 2026-09-16
    companion rule still puts the retainer on the door PO.
  * Glazing bead, moulding, and polycarbonate plastics.
  * In-house wrapping (``WRAP``, ``WRAPALU``). That is a separate exclusion
    ("handled internally"), not an Elton weatherstrip buy. No catalog item
    is a weatherstrip "wrap".
"""

from __future__ import annotations

import re

WEATHERSTRIP_EXCLUSION_REASON = (
    "weatherstrip — sourced from stock or Elton Manufacturing, not Upwardor"
)

# PL10-{feet}203-{color}. Length is two digits; color is the BC color code.
_PL10_VINYL_RE = re.compile(r"^PL10-\d{2}203-", re.IGNORECASE)

# SKUs that are weatherstrip but do not match the PL11 or PL10-xx203 patterns.
# Descriptions are the BC display names from bc_items.json.
KNOWN_WEATHERSTRIP_ITEMS = frozenset({
    "PL10-00006-00",  # WHITE VINYL FOR V7001 W/S
    "PL10-00127-00",  # TOP SEAL RUBBER (FS-1864 Die # 206)
    "PL10-00127-01",  # TOP SEAL, 3 1/4", CO-EXTRUDED RIGID/FLEXIBLE VINYL, TS-320
    "PL10-00144-00",  # RESI BUBBLE SEAL
    "PL10-00159-30",  # PLASTICS, WEATHER STRIP, DUAL FIN, NEW ALMOND
    "PL12-01400-05",  # BOTTOM 'U' RUBBER PVC
    "MI20-00001-00",  # BOTTOM SEAL FOAM FOR V130G
})

_DESC_MARKERS = (
    "WEATHER STRIP",
    "WEATHERSTRIP",
    "DUAL FIN",
    "DUAL-FIN",
    "TRI-SEAL",
    "TRI SEAL",
    "TOP SEAL",
    "BOTTOM SEAL",
    "BUBBLE SEAL",
    "U RUBBER",
    "U' RUBBER",
)


def is_weatherstrip_item(item_no: str, description: str = "") -> bool:
    """True when this line is weatherstrip Open Distribution does not buy from Upwardor."""
    item = (item_no or "").strip().upper()
    # In-house panel wrapping is not Elton weatherstrip. Checked before the
    # description markers so a wrap description cannot be reclassified.
    if item.startswith("WRAP"):
        return False
    if item.startswith("PL11-") or item in KNOWN_WEATHERSTRIP_ITEMS or _PL10_VINYL_RE.match(item):
        return True
    desc = (description or "").upper()
    if any(marker in desc for marker in _DESC_MARKERS):
        return True
    return bool(re.search(r"\bW/S\b", desc))


def is_upwardor_vendor(vendor_no: str = "", vendor_name: str = "") -> bool:
    """True for BC vendor UPW or a vendor name that matches the Upwardor lead-time rule."""
    from app.services.vendor_receipt_lead_time import match_vendor_lead_time

    return match_vendor_lead_time(vendor_no, vendor_name).key == "upwardor"
