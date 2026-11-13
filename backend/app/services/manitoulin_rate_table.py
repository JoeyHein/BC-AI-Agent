"""Manitoulin agreement 19067426 rate table.

The workbook is not in the repo. The JSON file ships the cells that were
verified with the rating examples and leaves every other cell null. The
import script fills nulls from the xlsx. A null cell is not a rate of zero.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from app.services.freight_numbers import D

BREAKS = ("L5C", "500", "1000", "2000", "5000", "10000", "20000")
BREAK_MINIMUMS = {
    "L5C": D(0),
    "500": D(500),
    "1000": D(1000),
    "2000": D(2000),
    "5000": D(5000),
    "10000": D(10000),
    "20000": D(20000),
}
# L5C is the under-500 column. A billed weight of exactly 500 uses the 500 break.
L5C_BELOW_LB = D(500)

NO_CONTRACT_RATE = "no contract rate - get a spot quote"
AGREEMENT = "19067426"

DATA_PATH = Path(__file__).resolve().parents[2] / "data" / "freight" / "manitoulin_rates.json"
SCHEMA_PATH = Path(__file__).resolve().parents[2] / "data" / "freight" / "manitoulin_rates.schema.json"

ORIGINS = (
    {"id": "redcliff", "label": "Redcliff AB"},
    {"id": "milton", "label": "Milton ON"},
    {"id": "mississauga", "label": "Mississauga ON"},
)
DESTINATIONS = (
    {"id": "calgary", "label": "Calgary"},
    {"id": "edmonton", "label": "Edmonton"},
    {"id": "grande_prairie", "label": "Grande Prairie"},
    {"id": "red_deer", "label": "Red Deer"},
    {"id": "vancouver", "label": "Vancouver"},
    {"id": "winnipeg", "label": "Winnipeg"},
    {"id": "regina", "label": "Regina"},
)

# Rating examples supplied with the feature. Every other cell stays null
# until the workbook is imported.
VERIFIED_LANES = {
    ("redcliff", "calgary"): {
        "min": 66,
        "rates": {"1000": 14.41, "2000": 11.42},
        "source": "verified_example",
    },
    ("redcliff", "edmonton"): {
        "min": 80,
        "rates": {"1000": 20.50, "2000": 16.97},
        "source": "verified_example",
    },
    ("redcliff", "regina"): {
        "min": 76,
        "rates": {"L5C": 32.63, "500": 25.59, "1000": 20.00, "2000": 16.65},
        "source": "verified_example",
    },
}

PLACEHOLDER_NOTICE = (
    "PLACEHOLDER. Preferential Service Agreement #19067426 was not in the repo. "
    "Cells with source verified_example are the Redcliff to Calgary, Edmonton, and "
    "Regina figures from the rating examples. Every other cell is null and returns "
    "'no contract rate - get a spot quote'. Run scripts/import_manitoulin_rates.py "
    "against the workbook (the copy named on the box is "
    "/workspace/freight/190674sa26 (1).xlsx) to fill the table. A null cell is not $0. "
    "The agreement must be signed before these rates are used."
)

_PLACE_ALIASES = {
    "redcliff": "redcliff",
    "redcliffab": "redcliff",
    "milton": "milton",
    "miltonon": "milton",
    "mississauga": "mississauga",
    "mississaugaon": "mississauga",
    "calgary": "calgary",
    "calgaryab": "calgary",
    "edmonton": "edmonton",
    "edmontonab": "edmonton",
    "grandeprairie": "grande_prairie",
    "grandeprairieab": "grande_prairie",
    "grandprairie": "grande_prairie",
    "reddeer": "red_deer",
    "reddeerab": "red_deer",
    "vancouver": "vancouver",
    "vancouverbc": "vancouver",
    "winnipeg": "winnipeg",
    "winnipegmb": "winnipeg",
    "regina": "regina",
    "reginask": "regina",
}

_HEADER_ALIASES = {
    "min": "min",
    "minimum": "min",
    "mincharge": "min",
    "l5c": "L5C",
    "5c": "L5C",
    "<500": "L5C",
    "under500": "L5C",
    "lt500": "L5C",
    "500": "500",
    "1000": "1000",
    "2000": "2000",
    "5000": "5000",
    "10000": "10000",
    "10m": "10000",
    "20000": "20000",
    "20m": "20000",
}


def _squash(value: Any) -> str:
    text = str(value or "").lower()
    text = text.replace("−", "-")
    return re.sub(r"[^a-z0-9<]", "", text)


def normalize_place(value: Any) -> Optional[str]:
    key = _squash(value)
    if not key:
        return None
    if key in _PLACE_ALIASES:
        return _PLACE_ALIASES[key]
    for alias, place_id in _PLACE_ALIASES.items():
        if alias and alias in key and len(alias) >= 6:
            return place_id
    return None


def empty_rates() -> Dict[str, Optional[float]]:
    return {break_name: None for break_name in BREAKS}


def placeholder_document() -> dict:
    lanes = []
    for origin in ORIGINS:
        for destination in DESTINATIONS:
            verified = VERIFIED_LANES.get((origin["id"], destination["id"]))
            rates = empty_rates()
            minimum = None
            source = "placeholder"
            if verified:
                minimum = verified["min"]
                rates.update(verified["rates"])
                source = verified["source"]
            lanes.append({
                "origin": origin["id"],
                "destination": destination["id"],
                "min": minimum,
                "rates": rates,
                "source": source,
            })
    return {
        "agreement": AGREEMENT,
        "carrier": "Manitoulin Transport",
        "service": "Preferential Service Agreement",
        "currency": "CAD",
        "rate_unit": "CAD per CWT",
        "breaks": list(BREAKS),
        "l5c_applies_below_lb": 500,
        "placeholder": True,
        "status": "partial",
        "notice": PLACEHOLDER_NOTICE,
        "workbook": "190674sa26 (1).xlsx",
        "origins": [dict(row) for row in ORIGINS],
        "destinations": [dict(row) for row in DESTINATIONS],
        "lanes": lanes,
    }


def _validate(document: dict) -> dict:
    if document.get("agreement") != AGREEMENT:
        raise ValueError(f"Rate table agreement must be {AGREEMENT}")
    if list(document.get("breaks") or []) != list(BREAKS):
        raise ValueError(f"Rate table breaks must be {list(BREAKS)}")
    lanes = document.get("lanes") or []
    seen = set()
    for lane in lanes:
        origin = lane.get("origin")
        destination = lane.get("destination")
        key = (origin, destination)
        if origin not in {row["id"] for row in ORIGINS}:
            raise ValueError(f"Unknown origin {origin}")
        if destination not in {row["id"] for row in DESTINATIONS}:
            raise ValueError(f"Unknown destination {destination}")
        if key in seen:
            raise ValueError(f"Duplicate lane {origin} -> {destination}")
        seen.add(key)
        rates = lane.get("rates") or {}
        missing = [name for name in BREAKS if name not in rates]
        if missing:
            raise ValueError(f"Lane {origin} -> {destination} is missing {missing[0]}")
        if lane.get("min") is not None and D(lane["min"]) < 0:
            raise ValueError(f"Lane {origin} -> {destination} has a negative minimum")
    document["_lane_index"] = {key: lane for key, lane in (( (lane["origin"], lane["destination"]), lane) for lane in lanes)}
    return document


def load_rate_table(path: Optional[Path] = None) -> dict:
    target = Path(path) if path else DATA_PATH
    with open(target, encoding="utf-8") as handle:
        document = json.load(handle)
    return _validate(document)


def find_lane(table: dict, origin: Any, destination: Any) -> Optional[dict]:
    origin_id = normalize_place(origin)
    destination_id = normalize_place(destination)
    if not origin_id or not destination_id:
        return None
    index = table.get("_lane_index")
    if index is None:
        index = {(lane["origin"], lane["destination"]): lane for lane in table.get("lanes") or []}
    return index.get((origin_id, destination_id))


def lane_has_any_rate(lane: Optional[dict]) -> bool:
    if not lane:
        return False
    if lane.get("min") is not None:
        return True
    return any(value is not None for value in (lane.get("rates") or {}).values())


def label_for(kind: str, place_id: Optional[str]) -> str:
    rows = ORIGINS if kind == "origin" else DESTINATIONS
    for row in rows:
        if row["id"] == place_id:
            return row["label"]
    return place_id or ""


def _header_key(value: Any) -> Optional[str]:
    squashed = _squash(value)
    if not squashed:
        return None
    if squashed in _HEADER_ALIASES:
        return _HEADER_ALIASES[squashed]
    if squashed.endswith("cwt"):
        return _header_key(squashed[:-3])
    return None


def _number(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace("$", "").replace(",", "")
    if not text or text.lower() in {"n/a", "na", "-", "—"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _row_origin(values: Iterable[Any]) -> Optional[str]:
    for value in values:
        place = normalize_place(value)
        if place in {row["id"] for row in ORIGINS}:
            return place
        text = str(value or "").lower()
        if "origin" in text or text.strip().startswith("from"):
            place = normalize_place(value)
            if place in {row["id"] for row in ORIGINS}:
                return place
    return None


def _row_destination(values: Iterable[Any]) -> Optional[str]:
    destination_ids = {row["id"] for row in DESTINATIONS}
    for value in values:
        place = normalize_place(value)
        if place in destination_ids:
            return place
    return None


def _groups_from_header(values: List[Any]) -> List[dict]:
    """One group per run of break columns. A flat sheet is a single group."""
    groups = []
    current = None
    for index, value in enumerate(values):
        key = _header_key(value)
        if key is None:
            if current and len(current["columns"]) >= 3:
                groups.append(current)
            current = None
            continue
        if current is None:
            current = {"columns": {}, "start": index}
        current["columns"][index] = key
    if current and len(current["columns"]) >= 3:
        groups.append(current)
    return groups


def _extract_sheet(rows: List[List[Any]]) -> List[dict]:
    found: List[dict] = []
    current_origin = None
    groups: List[dict] = []
    flat = False
    for row_index, values in enumerate(rows):
        if not any(value not in (None, "") for value in values):
            continue
        header_groups = _groups_from_header(values)
        origin_here = _row_origin(values)
        if origin_here:
            current_origin = origin_here
        if header_groups:
            groups = header_groups
            labels = {_squash(value) for value in values}
            flat = "origin" in labels and "destination" in labels
            continue
        if not groups:
            continue
        if flat:
            origin = _row_origin(values) or current_origin
            destination = _row_destination(values)
        else:
            origin = current_origin
            destination = _row_destination(values)
        if not destination or not origin:
            continue
        # A header-like repeat should not become a lane.
        if _header_key(values[groups[0]["start"]]) and _row_destination(values) is None:
            continue
        for group_index, group in enumerate(groups):
            group_origin = origin
            if len(groups) > 1:
                # Origin for this column group is the nearest origin token
                # above the header, looking at the group's columns.
                group_origin = _origin_for_group(rows, row_index, group) or origin
            rates = empty_rates()
            minimum = None
            for col, key in group["columns"].items():
                if col >= len(values):
                    continue
                number = _number(values[col])
                if key == "min":
                    minimum = number
                elif key in rates:
                    rates[key] = number
            if minimum is None and all(value is None for value in rates.values()):
                continue
            found.append({
                "origin": group_origin,
                "destination": destination,
                "min": minimum,
                "rates": rates,
            })
    return found


def _origin_for_group(rows: List[List[Any]], row_index: int, group: dict) -> Optional[str]:
    columns = list(group["columns"])
    start = min(columns)
    end = max(columns)
    for previous in range(row_index - 1, -1, -1):
        values = rows[previous]
        window = values[start:end + 1]
        place = _row_origin(window)
        if place:
            return place
        # Merged origin cells put the name on the first column of the group
        # or on the cell just to the left of it.
        left = values[max(0, start - 1):start]
        place = _row_origin(left)
        if place:
            return place
        if any(value not in (None, "") for value in values):
            # Stop at the first content row that is not an origin banner,
            # so a previous destination is not read as the origin.
            if _groups_from_header(values):
                continue
            return None
    return None


def extract_lanes_from_workbook(path: str) -> List[dict]:
    """Read a Manitoulin preferential workbook into lane dicts.

    Accepts either a stacked layout (an origin banner, then a header row of
    MIN / L5C / 500 / ... and one destination per row) or a flat sheet with
    Origin and Destination columns. Column groups repeated across the sheet
    are read as separate origins when the row above the header names them.
    """
    import openpyxl

    workbook = openpyxl.load_workbook(path, data_only=True)
    found: List[dict] = []
    try:
        for sheet in workbook.worksheets:
            rows = []
            for row in sheet.iter_rows(values_only=True):
                rows.append(list(row))
            found.extend(_extract_sheet(rows))
    finally:
        workbook.close()
    return _merge_extracted(found)


def _merge_extracted(rows: List[dict]) -> List[dict]:
    merged: Dict[tuple, dict] = {}
    for row in rows:
        key = (row["origin"], row["destination"])
        slot = merged.get(key)
        if slot is None:
            slot = {
                "origin": row["origin"],
                "destination": row["destination"],
                "min": None,
                "rates": empty_rates(),
                "conflicts": [],
            }
            merged[key] = slot
        if row.get("min") is not None:
            if slot["min"] is None:
                slot["min"] = row["min"]
            elif float(slot["min"]) != float(row["min"]):
                slot["conflicts"].append("min")
        for name, value in (row.get("rates") or {}).items():
            if value is None or name not in slot["rates"]:
                continue
            if slot["rates"][name] is None:
                slot["rates"][name] = value
            elif float(slot["rates"][name]) != float(value):
                slot["conflicts"].append(name)
    return list(merged.values())


def apply_extracted(document: dict, extracted: List[dict], source_name: str) -> dict:
    """Copy extracted cells onto a full 21-lane document. Missing cells stay null."""
    index = {(lane["origin"], lane["destination"]): lane for lane in document["lanes"]}
    for row in extracted:
        lane = index.get((row["origin"], row["destination"]))
        if lane is None:
            continue
        if row.get("min") is not None:
            lane["min"] = row["min"]
        for name, value in (row.get("rates") or {}).items():
            if value is not None and name in lane["rates"]:
                lane["rates"][name] = value
        if row.get("conflicts"):
            lane["conflicts"] = row["conflicts"]
        lane["source"] = source_name
    filled = 0
    total = 0
    for lane in document["lanes"]:
        total += 1 + len(BREAKS)
        if lane.get("min") is not None:
            filled += 1
        filled += sum(1 for value in lane["rates"].values() if value is not None)
    document["placeholder"] = filled < total
    document["status"] = "imported" if filled == total else "partial"
    document["notice"] = (
        f"Loaded {filled} of {total} rate cells from {source_name}. "
        "A null cell still returns 'no contract rate - get a spot quote'. "
        "Agreement #19067426 must be signed before these rates are used."
    )
    document.pop("_lane_index", None)
    return document


def inspect_workbook(path: str) -> str:
    import openpyxl

    workbook = openpyxl.load_workbook(path, data_only=True, read_only=True)
    lines = []
    try:
        for sheet in workbook.worksheets:
            lines.append(f"# {sheet.title}")
            shown = 0
            for row in sheet.iter_rows(values_only=True):
                if shown >= 25:
                    lines.append("... truncated")
                    break
                if any(value not in (None, "") for value in row):
                    lines.append(" | ".join("" if value is None else str(value) for value in row[:16]))
                    shown += 1
    finally:
        workbook.close()
    return "\n".join(lines)
