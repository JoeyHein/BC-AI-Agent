"""
Vendor sourcing policy for OPENDC purchasing.

Preferred vendors are the normal source for everything. Expedite vendors are
last-resort — only used when the product is needed in < 1 week (faster but
typically pricier). The purchasing tool must never *default* an item to an
expedite vendor: auto-assignment prefers the most-recent preferred vendor from
history, and only falls back to an expedite vendor (flagged) when there is no
preferred-vendor history at all.
"""

# Vendor numbers (BC) — keep in sync with BC vendor cards.
PREFERRED_VENDORS = {"UPW", "LYNX", "ELT"}      # Upwardor, Lynx, Elton Manufacturing
EXPEDITE_VENDORS = {"DEK", "UPAM"}              # Dek Canada, Upwardor Amazon — <1wk only


def is_preferred(vendor_no: str) -> bool:
    return (vendor_no or "").upper() in PREFERRED_VENDORS


def is_expedite(vendor_no: str) -> bool:
    return (vendor_no or "").upper() in EXPEDITE_VENDORS
