"""Door finishes, loaded from the shared door-renderer manifest.

Colour ids, names, and hex values are not duplicated here. Which finishes a
series is allowed to offer stays here, because that is a stocking rule rather
than a property of the finish.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

# (finish id, optional note shown by the configurator)
_SERIES_FINISHES = {
    "KANATA": [
        ("WHITE", None),
        ("NEW_ALMOND", None),
        ("BLACK", None),
        ("NEW_BROWN", None),
        ("HAZELWOOD", None),
        ("BRONZE", None),
        ("STEEL_GREY", None),
        ("SANDTONE", None),
        ("IRON_ORE", None),
        ("WALNUT", None),
        ("ENGLISH_CHESTNUT", None),
        ("FRENCH_OAK", None),
    ],
    "CRAFT": [
        ("WHITE", None),
        ("SANDTONE", None),
        ("WALNUT", "7' door only"),
        ("ENGLISH_CHESTNUT", None),
        ("IRON_ORE", None),
        ("FRENCH_OAK", None),
    ],
    "COMMERCIAL": [
        ("WHITE", None),
        ("BLACK", None),
        ("NEW_BROWN", None),
        ("STEEL_GREY", None),
    ],
    "COMMERCIAL_TX500": [
        ("WHITE", None),
        ("BLACK", None),
    ],
    "COMMERCIAL_20": [
        ("WHITE", None),
    ],
    "AL976": [
        ("CLEAR_ANODIZED", None),
        ("CUSTOM", None),
    ],
    "EXECUTIVE_STAINS": [
        ("MEDIUM_OAK", None),
        ("MAHOGANY", None),
        ("NATURAL", None),
        ("SLATE_DARK_GREY", None),
        ("DARK_WALNUT", None),
    ],
}


def finishes_path() -> Path:
    override = os.environ.get("DOOR_RENDERER_FINISHES")
    if override:
        return Path(override)
    here = Path(__file__).resolve()
    candidates = [
        here.parents[3] / "packages" / "door-renderer" / "finishes.json",
        Path("/app/door_renderer/finishes.json"),
    ]
    for path in candidates:
        if path.is_file():
            return path
    return candidates[0]


def load_finishes() -> dict:
    path = finishes_path()
    data = json.loads(path.read_text())
    return {finish["id"]: finish for finish in data["finishes"]}


def _entry(finish: dict, note: str | None) -> dict:
    entry = {
        "id": finish["id"],
        "name": finish["name"],
        "hex": finish.get("hex"),
        "type": finish.get("type", "solid"),
    }
    if finish.get("ral"):
        entry["ral"] = finish["ral"]
    if finish.get("type") == "woodgrain":
        base = finish.get("hex")
        entry["grain"] = [base, finish.get("light") or base, finish.get("dark") or base]
    note = note or finish.get("note")
    if note:
        entry["note"] = note
    return entry


def build_colors() -> dict:
    finishes = load_finishes()
    colors = {}
    for series, rows in _SERIES_FINISHES.items():
        built = []
        for finish_id, note in rows:
            finish = finishes.get(finish_id)
            if finish is None:
                raise KeyError(f"Finish {finish_id} is offered on {series} but missing from {finishes_path()}")
            built.append(_entry(finish, note))
        colors[series] = built
    return colors


COLORS = build_colors()
