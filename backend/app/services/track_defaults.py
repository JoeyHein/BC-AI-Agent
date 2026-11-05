"""Default track size for a door when the configurator does not send one.

Aluminum / full-view models standard is 3" track. 2" remains a choice the
user makes in the door builder; an explicit "2" is never rewritten here.
Steel doors keep the historical 2" fallback. Commercial steel is set to 3"
by the portal when that series is chosen, not by this fallback.
"""
from __future__ import annotations

from typing import Optional

# Catalog series under door type "aluminium" in the portal configurator.
ALUMINUM_DOOR_SERIES = frozenset({
    "AL976",
    "SWD",
    "PANORAMA",
    "SOLALITE",
})
ALUMINUM_DOOR_TYPES = frozenset({"aluminium", "aluminum"})


def is_aluminum_door(door_series: Optional[str] = None, door_type: Optional[str] = None) -> bool:
    series = (door_series or "").strip().upper()
    dtype = (door_type or "").strip().lower()
    return series in ALUMINUM_DOOR_SERIES or dtype in ALUMINUM_DOOR_TYPES


def default_track_thickness(
    door_series: Optional[str] = None,
    door_type: Optional[str] = None,
) -> str:
    """Track size ('2' or '3') used when the caller did not choose one."""
    return "3" if is_aluminum_door(door_series, door_type) else "2"


def resolve_track_thickness(
    explicit: Optional[object],
    door_series: Optional[str] = None,
    door_type: Optional[str] = None,
) -> str:
    """Keep an explicit 2" or 3". Blank / missing uses the series default.

    Accepts "2", "3", "2 inch", "3\"". Anything else is treated as unspecified
    so a junk value cannot silently bill the wrong track.
    """
    if explicit is None:
        return default_track_thickness(door_series, door_type)
    text = str(explicit).strip().lower().strip('"').strip("'")
    if not text:
        return default_track_thickness(door_series, door_type)
    if text.startswith("3"):
        return "3"
    if text.startswith("2"):
        return "2"
    return default_track_thickness(door_series, door_type)
