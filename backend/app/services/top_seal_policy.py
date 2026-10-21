"""When a door quote automatically includes top seal rubber.

Joey, 2026-10: doors 18 feet wide or narrower do not get a top seal unless
someone explicitly adds it. Wider than 18' keeps the previous automatic rule:

  * commercial — also at least 10 feet tall
  * aluminium — always
  * residential — never automatic

``explicit`` True forces the part on any door type. False does not cancel
the automatic rule on a door that is wider than 18'.

Width and height are inches. 18'0" is 216. 10'0" is 120.
"""

from __future__ import annotations

from typing import Optional

# Automatic only when the door is strictly wider than this.
TOP_SEAL_AUTO_WIDTH_IN = 216  # 18 feet
TOP_SEAL_AUTO_HEIGHT_IN = 120  # 10 feet, commercial only


def _norm_type(door_type: str) -> str:
    kind = (door_type or "").strip().lower()
    if kind == "aluminum":
        return "aluminium"
    return kind


def auto_top_seal(door_type: str, width_inches: float, height_inches: float = 0) -> bool:
    """True when the builder should add top seal without the user asking."""
    if (width_inches or 0) <= TOP_SEAL_AUTO_WIDTH_IN:
        return False
    kind = _norm_type(door_type)
    if kind == "aluminium":
        return True
    if kind == "commercial":
        return (height_inches or 0) >= TOP_SEAL_AUTO_HEIGHT_IN
    return False


def include_top_seal(
    door_type: str,
    width_inches: float,
    height_inches: float = 0,
    explicit: Optional[bool] = None,
) -> bool:
    """True when the quote (and its weight) should contain a top seal line.

    An explicit True always wins, including on a narrow door. An explicit
    False does not remove the seal from a door the automatic rule still covers.
    """
    if explicit is True:
        return True
    return auto_top_seal(door_type, width_inches, height_inches)
