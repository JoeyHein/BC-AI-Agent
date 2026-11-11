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


def _track_size_token(thickness: Optional[object]) -> str:
    text = str(thickness or "").strip().lower().strip('"').strip("'")
    if text.startswith("3"):
        return "3"
    if text.startswith("2"):
        return "2"
    return ""


def quoted_track_radius(
    thickness: Optional[object],
    requested: Optional[object] = None,
    series: Optional[str] = None,
) -> str:
    """Radius that is actually quoted.

    3 inch track is manufactured only at 15 inch radius. 2 inch track keeps
    an explicit 12 or 15. 20 inch radius is a Craft track; every other series
    maps 20, and anything else that is not 12 or 15, to 15. An omitted 2 inch
    radius stays 15, which is what the email normalizer already used.
    """
    if _track_size_token(thickness) == "3":
        return "15"
    raw = str(requested or "").strip()
    if raw in {"12", "15"}:
        return raw
    if raw == "20" and str(series or "").strip().upper() == "CRAFT":
        return "20"
    return "15"


def unavailable_3_inch_radius(mapped_doors, parsed_doors=None, email_text: str = "") -> list:
    """Deviations for an explicit non-15 radius on 3 inch track.

    The mapped thickness is what the door will be built with. The radius is
    the one the email or the parser asked for, including the value the
    normalizer saved on requestedTrackRadius before quoting 15.
    """
    email_radius = None
    if email_text:
        from app.services.customer_profile_service import analyse_email
        reading = (analyse_email(email_text, {}) or {}).get("trackRadius") or {}
        if reading.get("basis") == "explicit":
            email_radius = reading.get("value")
    parsed_doors = list(parsed_doors or [])
    deviations = []
    for index, mapped in enumerate(mapped_doors or []):
        if not isinstance(mapped, dict):
            continue
        parsed = parsed_doors[index] if index < len(parsed_doors) and isinstance(parsed_doors[index], dict) else {}
        thickness = mapped.get("trackThickness")
        asked = None
        # mapped trackRadius may already be the quoted 15. The ask is the
        # parser field, the value the normalizer saved, or the email text.
        for value in (
            parsed.get("track_radius"),
            parsed.get("trackRadius"),
            parsed.get("radius"),
            mapped.get("requestedTrackRadius"),
            email_radius,
        ):
            asked = explicit_non_15_on_3_inch(thickness, value)
            if asked:
                break
        if not asked:
            continue
        deviations.append({
            "kind": "track_radius_not_available",
            "field": "trackRadius",
            "door_index": index + 1,
            "from": asked,
            "to": "15",
            "applied_value": "15",
            "reason": (
                f'3" track comes only in a 15" radius. '
                f'The requested {asked}" radius was not quoted. Held for review.'
            ),
        })
    return deviations


def explicit_non_15_on_3_inch(thickness: Optional[object], requested: Optional[object]) -> Optional[str]:
    """The radius someone asked for, when 3 inch track cannot be built that way."""
    if _track_size_token(thickness) != "3":
        return None
    raw = str(requested or "").strip()
    if raw and raw != "15":
        return raw
    return None


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
