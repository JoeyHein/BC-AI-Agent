"""Round 3 quote gaps. Every switch defaults to off.

off leaves the door the mapper produced. shadow records what would change
and does not change the door. on applies that one gap.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from sqlalchemy.orm import Session

from app.services.inbox_settings import (
    ADJUSTABLE_PREP,
    CRATING_HISTORY,
    KANATA_SERIES_HISTORY,
    OPENER_MAPPING,
    SERIES_FALLBACK,
    STRUTS_PER_SECTION,
    WINDOW_PATTERNS,
    inbox_mode,
)

_STAGGER_RE = re.compile(r"\b(\d(?:\s*/\s*\d){1,7})\b")
_SECTION_WINDOW_RE = re.compile(
    r"(\d+)\s+(?:long\s+|short\s+)?windows?\s+in\s+(?:the\s+)?"
    r"(?:section\s+(\d+)|top(?:\s+section)?|bottom(?:\s+section)?|"
    r"(\d+)(?:st|nd|rd|th)?(?:\s+section)?)",
    re.IGNORECASE,
)
_EVERY_SECTION_RE = re.compile(
    r"\b(?:truss(?:es|ing)?|struts?)\b.{0,40}\bevery\s+section\b"
    r"|\bevery\s+section\b.{0,40}\b(?:truss(?:es|ing)?|struts?)\b",
    re.IGNORECASE,
)
_ADJUSTABLE_RE = re.compile(
    r"\b(?:adjustable\s+prep|opener\s+prep|operator\s+prep|adjustable\s+operator)\b",
    re.IGNORECASE,
)
_CRATING_RE = re.compile(r"\bcrat(?:e|ing|ed)\b", re.IGNORECASE)
_PICKUP_RE = re.compile(r"\b(?:pick\s*-?\s*up|will\s+collect|customer\s+pickup)\b", re.IGNORECASE)
_DELIVERY_RE = re.compile(r"\b(?:deliver(?:y|ed)?|ship(?:ped|ping)?|freight)\b", re.IGNORECASE)
_FLUSH_OR_CLOSEST_RE = re.compile(r"\b(?:flush|closest|similar)\b", re.IGNORECASE)

# Catalog rows a model name maps to with no guesswork. L979S is a real
# LiftMaster keypad and is not in the item export, so it is not given a
# part number here.
_EXACT_MODELS = {
    "2220L": "OP19-01118-00",
    "2420L": "OP19-01119-00",
    "84505R": "OP19-01073-00",
    "6580L": "OP19-01120-00",
    "878MAX": "OP19-02077-00",
    "98022": "OP19-01085-00",
    "98022MC": "OP19-01085-00",
    "LJ8900W": "OP19-01082-00",
    "8900W": "OP19-01082-00",
}
_UNRESOLVED_MODELS = {
    "L979S": "LiftMaster L979S is not in the operator catalog or the item export.",
    "8500W": (
        "8500W is not a current catalog row. 8500C and 8500CMC are discontinued, "
        "and LJ8900W and 98022MC are different jackshafts. None was chosen."
    ),
}
_KEYPAD_PHRASE_RE = re.compile(
    r"\b(?:878\s*max|keyless(?:\s+entry)?|wireless\s+keypad)\b",
    re.IGNORECASE,
)
_RAIL_RE = re.compile(r"\b(7|8|10)\s*(?:'|ft|foot|feet)\s+rail\b", re.IGNORECASE)
_CHAIN_RAILS = {"7": "OP19-02004-00", "8": "OP19-02005-00", "10": "OP19-02006-00"}
_BELT_RAILS = {"7": "OP19-02001-00", "8": "OP19-02002-00", "10": "OP19-02003-00"}


@dataclass
class Round3Result:
    doors: List[dict]
    applied: bool = False
    delivery_type: Optional[str] = None
    delivery_explicit: bool = False
    deviations: List[dict] = field(default_factory=list)
    shadow_notes: List[dict] = field(default_factory=list)
    unresolved: List[dict] = field(default_factory=list)


def round3_modes(db: Optional[Session]) -> Dict[str, str]:
    keys = (
        WINDOW_PATTERNS,
        OPENER_MAPPING,
        STRUTS_PER_SECTION,
        CRATING_HISTORY,
        KANATA_SERIES_HISTORY,
        ADJUSTABLE_PREP,
        SERIES_FALLBACK,
    )
    return {key: inbox_mode(db, key) for key in keys}


def apply_round3(
    db: Optional[Session],
    doors: Sequence[dict],
    *,
    email_text: str = "",
    parsed_doors: Optional[Sequence[dict]] = None,
    profile_fields: Optional[dict] = None,
    modes: Optional[Dict[str, str]] = None,
) -> Round3Result:
    """Apply the switches that are on. Shadow is recorded and not applied."""
    if modes is None:
        modes = round3_modes(db)
    planned = plan_round3(
        doors,
        email_text=email_text,
        parsed_doors=parsed_doors,
        profile_fields=profile_fields,
        modes=modes,
    )
    return planned


def plan_round3(
    doors: Sequence[dict],
    *,
    email_text: str = "",
    parsed_doors: Optional[Sequence[dict]] = None,
    profile_fields: Optional[dict] = None,
    modes: Optional[Dict[str, str]] = None,
) -> Round3Result:
    modes = {key: (value or "off") for key, value in (modes or {}).items()}
    text = email_text or ""
    updated = [dict(door or {}) for door in doors]
    result = Round3Result(doors=updated)
    fields = profile_fields or {}
    if modes.get(OPENER_MAPPING, "off") == "on":
        for door in updated:
            door["dedupeOperatorRails"] = True
            result.applied = True

    for index, door in enumerate(updated):
        parsed = {}
        if parsed_doors and index < len(parsed_doors) and isinstance(parsed_doors[index], dict):
            parsed = parsed_doors[index]
        blob = _blob(text, door, parsed)

        if modes.get(SERIES_FALLBACK, "off") != "off":
            swap = closest_series(door, blob)
            if swap:
                _keep(result, modes[SERIES_FALLBACK], index, "series", swap, door)

        if modes.get(WINDOW_PATTERNS, "off") != "off":
            windows = window_plan(door, blob, parsed)
            if windows:
                _keep(result, modes[WINDOW_PATTERNS], index, "windows", windows, door)

        if modes.get(OPENER_MAPPING, "off") != "off":
            opener = opener_plan(blob, door)
            if opener.get("changes") or opener.get("unresolved"):
                payload = dict(opener.get("changes") or {})
                payload["unresolved"] = opener.get("unresolved") or []
                _keep(result, modes[OPENER_MAPPING], index, "opener", payload, door)

        if modes.get(STRUTS_PER_SECTION, "off") != "off":
            if wants_strut_every_section(blob, fields):
                _keep(
                    result, modes[STRUTS_PER_SECTION], index, "struts",
                    {"strutsPerSection": True}, door,
                )

        if modes.get(ADJUSTABLE_PREP, "off") != "off":
            if _ADJUSTABLE_RE.search(blob):
                _keep(
                    result, modes[ADJUSTABLE_PREP], index, "adjustable_prep",
                    {"adjustablePrep": True}, door,
                )

        if modes.get(CRATING_HISTORY, "off") != "off" and index == 0:
            if _CRATING_RE.search(blob) or _usually_crates(fields):
                _keep(
                    result, modes[CRATING_HISTORY], index, "crating",
                    {"includeCrating": True}, door,
                )

    if modes.get(CRATING_HISTORY, "off") != "off":
        delivery = delivery_choice(text, fields)
        if delivery:
            note = {"field": "delivery", "door_index": 1, "changes": delivery}
            if modes[CRATING_HISTORY] == "on":
                result.applied = True
                result.delivery_type = delivery["deliveryType"]
                result.delivery_explicit = True
                result.deviations.append({
                    "kind": "pickup_or_freight",
                    "field": "deliveryType",
                    "applied_value": delivery["deliveryType"],
                    "reason": delivery["reason"],
                })
            else:
                result.shadow_notes.append({**note, "shadow": True})

    return result


def _keep(result: Round3Result, mode: str, index: int, kind: str, changes: dict, door: dict) -> None:
    unresolved = list(changes.get("unresolved") or [])
    payload = {key: value for key, value in changes.items() if key != "unresolved"}
    note = {"field": kind, "door_index": index + 1, "changes": payload, "unresolved": unresolved}
    if mode == "shadow":
        result.shadow_notes.append({**note, "shadow": True})
        return
    if mode != "on":
        return
    result.applied = True
    for key, value in payload.items():
        if key == "reason":
            continue
        door[key] = value
    if payload.get("reason") or unresolved:
        result.deviations.append({
            "kind": kind,
            "door_index": index + 1,
            "reason": payload.get("reason") or "; ".join(
                item.get("reason", "") for item in unresolved
            ),
            "unresolved": unresolved,
        })
    result.unresolved.extend(unresolved)


def _blob(email_text: str, door: dict, parsed: dict) -> str:
    bits = [email_text or "", str(door.get("notes") or ""), str(door.get("operator") or "")]
    for key in (
        "window_pattern", "windows", "operator", "keypad", "notes", "model",
        "struts", "hardware_notes",
    ):
        value = parsed.get(key)
        if value:
            bits.append(str(value))
    return "\n".join(bits)


def window_counts(text: str, parsed: Optional[dict] = None) -> List[int]:
    """Section counts from the top. Empty when the pattern is not stated."""
    parsed = parsed or {}
    raw = parsed.get("window_pattern") or parsed.get("windowPattern")
    if isinstance(raw, (list, tuple)) and raw:
        return [int(item) for item in raw]
    if isinstance(raw, str) and _STAGGER_RE.fullmatch(raw.strip()):
        return [int(part) for part in re.split(r"\s*/\s*", raw.strip())]
    match = _STAGGER_RE.search(str(parsed.get("windows") or ""))
    if match:
        return [int(part) for part in re.split(r"\s*/\s*", match.group(1))]
    match = _STAGGER_RE.search(text or "")
    if match and re.search(r"window|stagger", text or "", re.I):
        return [int(part) for part in re.split(r"\s*/\s*", match.group(1))]
    found: Dict[int, int] = {}
    for count, section, ordinal in _SECTION_WINDOW_RE.findall(text or ""):
        if section:
            index = int(section)
        elif ordinal:
            index = int(ordinal)
        else:
            # "top" is 1. "bottom" is left unset until the caller knows the
            # section count; a bare bottom without a number is section 4 on
            # a 7 foot door and is not guessed here.
            index = 1
        found[index] = int(count)
    if not found:
        return []
    last = max(found)
    return [found.get(i, 0) for i in range(1, last + 1)]


def columns_for_width(width_inches: int, window_size: str = "long") -> int:
    span = 48 if (window_size or "long") == "long" else 24
    width = int(width_inches or 0)
    if width <= 0 or span <= 0:
        return 1
    return max(1, width // span)


def positions_from_counts(counts: Sequence[int], columns: int) -> List[dict]:
    """Right-align each section's windows. Column 0 is the left side."""
    positions = []
    width = max(1, int(columns))
    for section, count in enumerate(counts, start=1):
        qty = max(0, int(count))
        if qty <= 0:
            continue
        qty = min(qty, width)
        start = width - qty
        for col in range(start, start + qty):
            positions.append({"section": section, "col": col})
    return positions


def window_plan(door: dict, text: str, parsed: dict) -> Optional[dict]:
    existing = door.get("windowPositions") or parsed.get("window_positions") or parsed.get("windowPositions")
    if isinstance(existing, list) and existing:
        positions = [
            {"section": int(item.get("section", 1)), "col": int(item.get("col", 0))}
            for item in existing if isinstance(item, dict)
        ]
    else:
        counts = window_counts(text, parsed)
        if not counts or sum(counts) <= 0:
            return None
        size = str(parsed.get("window_size") or parsed.get("windowSize") or door.get("windowSize") or "long")
        positions = positions_from_counts(counts, columns_for_width(door.get("doorWidth") or 0, size))
    if not positions:
        return None
    size = str(parsed.get("window_size") or door.get("windowSize") or "long").lower()
    if size not in {"short", "long"}:
        size = "long"
    return {
        "hasWindows": True,
        "windowSize": size,
        "windowPositions": positions,
        "windowQty": len(positions),
        "glassPaneType": "INSULATED",
        "glassColor": "CLEAR",
    }


def opener_plan(text: str, door: dict) -> dict:
    """Map wording to catalog part numbers. An unsure name is flagged."""
    from app.services.operator_service import catalog_part_role

    blob = f"{text}\n{door.get('operator') or ''}"
    changes: Dict[str, Any] = {"changes": {}, "unresolved": []}
    current = str(door.get("operator") or "").strip()
    if current and catalog_part_role(current) == "operator":
        part = current
    else:
        part, reason = _match_operator_model(blob)
        if part:
            changes["changes"]["operator"] = part
            changes["changes"]["doorType"] = door.get("doorType") or "residential"
        elif current and catalog_part_role(current) != "operator":
            changes["changes"]["operator"] = None
            changes["unresolved"].append({
                "field": "operator",
                "text": current,
                "reason": reason or f"No catalog operator matches {current!r}. It was not added as a free-text line.",
            })
        elif reason:
            changes["unresolved"].append({"field": "operator", "text": blob[:180], "reason": reason})

    accessories = list(door.get("operatorAccessories") or [])
    keypad, keypad_reason = _match_keypad(blob)
    if keypad and keypad not in accessories:
        accessories.append(keypad)
        changes["changes"]["operatorAccessories"] = accessories
    elif keypad_reason:
        changes["unresolved"].append({"field": "keypad", "text": keypad_reason, "reason": keypad_reason})

    rail = _match_rail(blob, part or current)
    if rail and rail not in accessories:
        accessories = list(changes["changes"].get("operatorAccessories") or accessories)
        accessories.append(rail)
        changes["changes"]["operatorAccessories"] = accessories

    if changes["unresolved"] and "reason" not in changes["changes"]:
        changes["changes"]["reason"] = changes["unresolved"][0]["reason"]
    return changes


def _match_operator_model(text: str):
    upper = (text or "").upper()
    compact = re.sub(r"\s+", "", upper)
    unresolved = [reason for token, reason in _UNRESOLVED_MODELS.items() if token in compact]
    if unresolved:
        return None, " ".join(unresolved)
    for token, part in _EXACT_MODELS.items():
        if token in compact and not token.endswith("MAX"):
            return part, None
    three_quarter = bool(re.search(r"3\s*/\s*4|¾", text or ""))
    chain = "CHAIN" in upper
    base = bool(re.search(r"\b(?:base|basic)\b", text or "", re.I))
    battery = bool(re.search(r"\b(?:bbu|battery)\b", text or "", re.I))
    if three_quarter and chain and base and not battery:
        return "OP19-01118-00", None
    if re.search(r"\bjackshaft\b", text or "", re.I) and "8900" not in compact and "98022" not in compact:
        return None, (
            "Jackshaft was requested without a model. "
            "LJ8900W, 98022MC, and the JHDC operators are different parts. None was chosen."
        )
    if current_words_look_like_operator(text) and "2220" not in compact:
        return None, "The opener wording does not match one catalog part. It was not invented."
    return None, None


def current_words_look_like_operator(text: str) -> bool:
    return bool(re.search(r"\b(?:liftmaster|operator|opener|horse\s*power|chain\s+drive)\b", text or "", re.I))


def _match_keypad(text: str):
    compact = re.sub(r"\s+", "", (text or "").upper())
    if "L979S" in compact:
        return None, _UNRESOLVED_MODELS["L979S"]
    if "878MAX" in compact or _KEYPAD_PHRASE_RE.search(text or ""):
        return "OP19-02077-00", None
    return None, None


def _match_rail(text: str, operator_part: str) -> Optional[str]:
    match = _RAIL_RE.search(text or "")
    if not match:
        return None
    length = match.group(1)
    upper = (text or "").upper()
    if "BELT" in upper and "CHAIN" not in upper:
        return _BELT_RAILS.get(length)
    return _CHAIN_RAILS.get(length)


def wants_strut_every_section(text: str, profile_fields: Optional[dict]) -> bool:
    if _EVERY_SECTION_RE.search(text or ""):
        return True
    spec = (profile_fields or {}).get("struts_per_section")
    if isinstance(spec, dict):
        return str(spec.get("value") or "").lower() in {"yes", "true", "every", "1"}
    return False


def _usually_crates(profile_fields: Optional[dict]) -> bool:
    spec = (profile_fields or {}).get("crating")
    if not isinstance(spec, dict):
        return False
    try:
        total = int(spec.get("total") or 0)
        confidence = float(spec.get("confidence") or 0)
    except (TypeError, ValueError):
        return False
    return bool(spec.get("locked")) or (total >= 2 and confidence >= 0.6 and str(spec.get("value")) == "yes")


def delivery_choice(text: str, profile_fields: Optional[dict]) -> Optional[dict]:
    pickup = bool(_PICKUP_RE.search(text or ""))
    delivery = bool(_DELIVERY_RE.search(text or ""))
    if pickup and not delivery:
        return {"deliveryType": "pickup", "reason": "The email asks for pickup, so freight is not added."}
    if delivery and not pickup:
        return {"deliveryType": "delivery", "reason": "The email asks for delivery, so freight is recorded."}
    spec = (profile_fields or {}).get("delivery_type")
    if isinstance(spec, dict) and str(spec.get("value") or "") in {"pickup", "delivery"}:
        try:
            total = int(spec.get("total") or 0)
            confidence = float(spec.get("confidence") or 0)
        except (TypeError, ValueError):
            total, confidence = 0, 0
        if spec.get("locked") or (total >= 2 and confidence >= 0.6):
            value = str(spec.get("value"))
            return {
                "deliveryType": value,
                "reason": f"The customer's history is {value}.",
            }
    return None


def closest_series(door: dict, text: str) -> Optional[dict]:
    """Kanata flush when the asked commercial series cannot be that colour and design."""
    if not _FLUSH_OR_CLOSEST_RE.search(text or ""):
        return None
    series = str(door.get("doorSeries") or "")
    color = str(door.get("panelColor") or "")
    design = str(door.get("panelDesign") or "")
    if not series or series.upper() == "KANATA":
        return None
    from app.api.door_configurator import validate_panel_combo
    try:
        validate_panel_combo(series, color or None, design or None)
        return None
    except ValueError as exc:
        reason = str(exc)
    return {
        "doorType": "residential",
        "doorSeries": "KANATA",
        "panelDesign": "FLUSH" if design.upper() == "FLUSH" or re.search(r"\bflush\b", text or "", re.I) else design or "FLUSH",
        "panelColor": color or "BLACK",
        "reason": f"{reason} Quoted Kanata flush, which is stocked in that colour.",
    }


def history_flags(db: Optional[Session]) -> dict:
    return {
        "count_kanata": inbox_mode(db, KANATA_SERIES_HISTORY) == "on",
        "count_crating": inbox_mode(db, CRATING_HISTORY) == "on",
    }
