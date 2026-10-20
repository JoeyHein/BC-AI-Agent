"""Purchase-order line prices belong to Business Central.

Creating a line without ``directUnitCost`` lets BC apply the vendor's
date-valid purchase price for the PO order date. A number is sent only
when a person typed an override. Item-card ``unitCost`` is an estimate
and is never written as the PO price. A missing override is not zero.
"""

from __future__ import annotations

from typing import Any, Optional


def explicit_override(*candidates: Any) -> Optional[float]:
    """First non-blank candidate, or None when BC should price the line.

    ``None`` and ``""`` are not overrides. ``0`` is an override: someone
    typed zero. Callers must not pass an item-card cost here.
    """
    for value in candidates:
        if value is None or value == "":
            continue
        return float(value)
    return None


def apply_direct_unit_cost(payload: dict, override: Any) -> dict:
    """Put ``directUnitCost`` on ``payload`` only for an explicit override."""
    if override is None or override == "":
        payload.pop("directUnitCost", None)
        return payload
    payload["directUnitCost"] = float(override)
    return payload
