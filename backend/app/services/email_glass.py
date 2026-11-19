"""Glass and full-view fields for the email auto-quote path.

The configurator quotes a full-view section only when ``windowInsert`` is
V130G or V230G. The email mapper used to drop that field, so a request for
full-view tempered glass became a flush door. Normalization keeps the
fields, and the keyword pass fills them from the customer's words when the
model leaves them out.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

_FULL_VIEW_RE = re.compile(r"\bfull\s*view\b|\bv130g?\b|\bv230g?\b", re.I)
_NO_FULL_VIEW_RE = re.compile(r"\bno\s+full\s*view\b", re.I)
_V230_RE = re.compile(r"\bv230g?\b", re.I)
_V130_RE = re.compile(r"\bv130g?\b", re.I)
_OIL_TEMPERED_RE = re.compile(r"\boil[-\s]*tempered\b", re.I)
_TEMPERED_SPRING_RE = re.compile(r"\btempered\s+springs?\b", re.I)
_TEMPERED_RE = re.compile(r"\btempered\b", re.I)
_TEMP_TEMP_RE = re.compile(
    r"\btemp(?:ered)?\s*/\s*temp(?:ered)?\b|\bthermal\s+tempered\b",
    re.I,
)
_TEMP_CLEAR_RE = re.compile(r"\btemp(?:ered)?\s*/\s*clear\b", re.I)
_INSULATED_RE = re.compile(
    r"\binsulated\b|\bthermopane\b|\bthermo\s*pane\b|\bthermal\s+glass\b|\bthermal\s+tempered\b",
    re.I,
)
_SINGLE_RE = re.compile(r"\bsingle\s+pane\b|\bsingle\s+glass\b", re.I)
_SUPER_GREY_RE = re.compile(r"\bsuper\s*gr[ae]y\b", re.I)
_ETCHED_RE = re.compile(r"\betched\b|\bfrosted\b", re.I)
_TINTED_RE = re.compile(r"\btinted(?:\s*gr[ae]y)?\b", re.I)
_CLEAR_ANO_RE = re.compile(r"\bclear\s+anodiz\w*\b|\bclear\s+ano\b", re.I)
_CLEAR_RE = re.compile(r"\bclear\b", re.I)

_PUNCHED_INSERTS = frozenset({
    "24X12_THERMOPANE",
    "34X16_THERMOPANE",
    "18X8_THERMOPANE",
})

_INSERT_ALIASES = {
    "V130": "V130G",
    "V130G": "V130G",
    "V230": "V230G",
    "V230G": "V230G",
    "PANORAMA": "PANORAMA",
    "24X12": "24X12_THERMOPANE",
    "24X12_THERMOPANE": "24X12_THERMOPANE",
    "34X16": "34X16_THERMOPANE",
    "34X16_THERMOPANE": "34X16_THERMOPANE",
    "18X8": "18X8_THERMOPANE",
    "18X8_THERMOPANE": "18X8_THERMOPANE",
    "NONE": None,
    "FULLVIEW": "FULL_VIEW",
    "FULL_VIEW": "FULL_VIEW",
}

_PANE_ALIASES = {
    "INSULATED": "INSULATED",
    "THERMAL": "INSULATED",
    "THERM": "INSULATED",
    "THERMOPANE": "INSULATED",
    "DOUBLE": "INSULATED",
    "SINGLE": "SINGLE",
}

_TREATMENT_ALIASES = {
    "ANNEALED": "ANNEALED",
    "STANDARD": "ANNEALED",
    "TEMPERED": "TEMPERED",
    "TEMP_TEMP": "TEMP_TEMP",
    "THERMAL_TEMPERED": "TEMP_TEMP",
    "TEMPERED_BOTH": "TEMP_TEMP",
}

_COLOR_ALIASES = {
    "CLEAR": "CLEAR",
    "ETCHED": "ETCHED",
    "FROSTED": "ETCHED",
    "FROST": "ETCHED",
    "SUPER_GREY": "SUPER_GREY",
    "SUPER_GRAY": "SUPER_GREY",
    "SUPERGREY": "SUPER_GREY",
    "SUPERGRAY": "SUPER_GREY",
    "TINTED_GREY": "TINTED_GREY",
    "TINTED_GRAY": "TINTED_GREY",
    "TINTED": "TINTED_GREY",
    "TINT": "TINTED_GREY",
}


def _token(value: Any) -> str:
    return str(value or "").upper().strip().replace("-", "_").replace(" ", "_").replace("/", "_")


def coerce_window_insert(raw: Any, series: str) -> Optional[str]:
    """Map a model-written insert onto a configurator id.

    "full view" follows the series: V130G on TX450, V230G on TX500. Other
    identifier-shaped values are kept so a decorative insert is not dropped.
    """
    if raw is None or raw == "":
        return None
    token = _token(raw)
    compact = token.replace("_", "")
    if token in _INSERT_ALIASES:
        mapped = _INSERT_ALIASES[token]
    elif compact in _INSERT_ALIASES:
        mapped = _INSERT_ALIASES[compact]
    else:
        mapped = token if re.fullmatch(r"[A-Z0-9_]{1,40}", token) else None
    if mapped == "FULL_VIEW":
        series_name = (series or "").upper()
        if series_name.startswith("TX500"):
            return "V230G"
        if series_name.startswith("TX450"):
            return "V130G"
        return None
    return mapped


def coerce_window_panels(raw: Any) -> Optional[dict]:
    if not isinstance(raw, dict) or not raw:
        return None
    panels = {}
    for key, entry in raw.items():
        if not isinstance(entry, dict):
            continue
        panel: Dict[str, Any] = {}
        if entry.get("qty") is not None:
            try:
                panel["qty"] = max(1, int(entry.get("qty")))
            except (TypeError, ValueError):
                panel["qty"] = 1
        if entry.get("type"):
            panel["type"] = _token(entry.get("type"))
        if panel:
            panels[str(key)] = panel
    return panels or None


def coerce_pane(raw: Any) -> Optional[str]:
    if raw is None or raw == "":
        return None
    return _PANE_ALIASES.get(_token(raw))


def coerce_treatment(raw: Any) -> Optional[str]:
    if raw is None or raw == "":
        return None
    return _TREATMENT_ALIASES.get(_token(raw))


def coerce_glass_color(raw: Any) -> Optional[str]:
    if raw is None or raw == "":
        return None
    return _COLOR_ALIASES.get(_token(raw))


def normalize_glass_fields(raw: dict, series: str, window_qty: int) -> dict:
    """Fields the configurator needs in order to quote full-view glass.

    A real window insert turns windows on. The quote builder ignores
    ``windowInsert`` when ``hasWindows`` is false, which is how a full-view
    line was dropped.
    """
    insert = coerce_window_insert((raw or {}).get("windowInsert"), series)
    panels = coerce_window_panels((raw or {}).get("windowPanels"))
    has_windows = bool((raw or {}).get("hasWindows", False)) or bool(insert)
    qty = window_qty
    if insert in {"V130G", "V230G", "PANORAMA"} and qty < 1:
        qty = 1
    return {
        "hasWindows": has_windows,
        "windowInsert": insert,
        "windowQty": qty,
        "windowPanels": panels,
        "glassPaneType": coerce_pane((raw or {}).get("glassPaneType")),
        "glassType": coerce_treatment((raw or {}).get("glassType")),
        "glassColor": coerce_glass_color((raw or {}).get("glassColor")),
    }


def glass_keywords(text: str) -> Dict[str, str]:
    """Pane, treatment, and colour named in the email. Empty when silent.

    "insulated tempered" and "thermal tempered" are temp/temp (both lites).
    "temp/clear" stays the existing one-lite tempered kit. Oil-tempered
    springs are not glass.
    """
    cleaned = _OIL_TEMPERED_RE.sub(" ", text or "")
    cleaned = _TEMPERED_SPRING_RE.sub(" ", cleaned)
    cleaned = _CLEAR_ANO_RE.sub(" ", cleaned)
    found: Dict[str, str] = {}
    tempered = bool(_TEMPERED_RE.search(cleaned))
    insulated = bool(_INSULATED_RE.search(cleaned))
    if _TEMP_TEMP_RE.search(cleaned) or (tempered and insulated):
        found["glassPaneType"] = "INSULATED"
        found["glassType"] = "TEMP_TEMP"
    elif _TEMP_CLEAR_RE.search(cleaned):
        found["glassPaneType"] = "INSULATED"
        found["glassType"] = "TEMPERED"
    elif tempered:
        found["glassPaneType"] = "SINGLE"
        found["glassType"] = "TEMPERED"
    elif insulated:
        found["glassPaneType"] = "INSULATED"
        found["glassType"] = "ANNEALED"
    elif _SINGLE_RE.search(cleaned):
        found["glassPaneType"] = "SINGLE"
        found["glassType"] = "ANNEALED"

    if _SUPER_GREY_RE.search(cleaned):
        found["glassColor"] = "SUPER_GREY"
    elif _ETCHED_RE.search(cleaned):
        found["glassColor"] = "ETCHED"
    elif _TINTED_RE.search(cleaned):
        found["glassColor"] = "TINTED_GREY"
    elif _CLEAR_RE.search(cleaned):
        found["glassColor"] = "CLEAR"
    return found


def _full_view_insert(series: str, text: str) -> Optional[str]:
    series_name = (series or "").upper()
    asked_230 = bool(_V230_RE.search(text or ""))
    asked_130 = bool(_V130_RE.search(text or ""))
    if asked_230 and not asked_130:
        return "V230G"
    if asked_130 and not asked_230:
        return "V130G"
    if series_name.startswith("TX500"):
        return "V230G"
    if series_name.startswith("TX450"):
        return "V130G"
    return None


def apply_email_glass_request(doors: List[dict], text: str) -> List[dict]:
    """Fill full-view and glass fields from the email text.

    Runs after normalization. A punched window the model already chose
    (24x12 and the other thermopane inserts) is left alone. Full view on
    TX450 / TX450-20 is V130G. Full view on TX500 / TX500-20 is V230G.
    """
    choice = glass_keywords(text)
    wants_full_view = bool(_FULL_VIEW_RE.search(text or "")) and not bool(
        _NO_FULL_VIEW_RE.search(text or "")
    )
    updated = []
    for raw in doors or []:
        door = dict(raw or {})
        if wants_full_view and str(door.get("doorType") or "") == "commercial":
            insert = _full_view_insert(door.get("doorSeries") or "", text or "")
            current = door.get("windowInsert")
            if insert and current not in _PUNCHED_INSERTS:
                door["windowInsert"] = insert
                door["hasWindows"] = True
                if not door.get("windowQty"):
                    door["windowQty"] = 1
                if not door.get("windowPanels") and int(door.get("windowQty") or 1) <= 1:
                    door["windowPanels"] = {"1": {"qty": 1, "type": insert}}
                if not door.get("glazingType"):
                    door["glazingType"] = "glass"
        takes_glass = (
            str(door.get("doorType") or "") == "aluminium"
            or door.get("windowInsert") in {"V130G", "V230G", "PANORAMA"}
            or (
                door.get("hasWindows")
                and door.get("windowInsert") not in (None, "NONE")
            )
        )
        if takes_glass:
            door.update(choice)
        updated.append(door)
    return updated
