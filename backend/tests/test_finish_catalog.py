"""Finish colours come from the shared manifest, not a second hex table."""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.api.door_configurator import COLORS
from app.services.finish_catalog import finishes_path, load_finishes


def test_manifest_is_the_hex_source():
    finishes = load_finishes()
    raw = json.loads(finishes_path().read_text())
    assert [row["id"] for row in raw["finishes"] if row["id"] == "WALNUT"]
    for series_colors in COLORS.values():
        for entry in series_colors:
            source = finishes[entry["id"]]
            assert entry["hex"] == source.get("hex")
            assert entry["name"] == source["name"]
            if source.get("type") == "woodgrain":
                assert entry["grain"][0] == source["hex"]
                assert entry["grain"][1] == source["light"]
                assert entry["grain"][2] == source["dark"]


def test_colour_ids_stay_stable():
    kanata = {row["id"] for row in COLORS["KANATA"]}
    assert {"WALNUT", "ENGLISH_CHESTNUT", "FRENCH_OAK", "WHITE", "BLACK"} <= kanata
    craft = {row["id"] for row in COLORS["CRAFT"]}
    assert {"WALNUT", "ENGLISH_CHESTNUT", "FRENCH_OAK"} <= craft
    walnut = next(row for row in COLORS["CRAFT"] if row["id"] == "WALNUT")
    assert walnut["note"] == "7' door only"


def test_english_chestnut_is_a_real_texture():
    finish = load_finishes()["ENGLISH_CHESTNUT"]
    assert finish["textureStatus"] == "catalogue"
    assert finish["grainAxis"] == "horizontal"
    assert finish["textureRotate"] == 90
    assert finish["hex"] == "#825B3F"
    assert finish["warmth"] > 0
    assert finish["grainContrast"] > 1
    assert (finishes_path().parent / "textures" / finish["texture"]).is_file()


def test_french_oak_uses_daylight_colour_and_closeup_grain():
    finish = load_finishes()["FRENCH_OAK"]
    assert finish["textureStatus"] == "catalogue"
    assert finish["recolorToHex"] is True
    assert finish["hex"] == "#BFA87B"
    assert finish["textureSource"].endswith("sources/french-oak.jpg")
    assert "colorStatus" not in finish
    assert (finishes_path().parent / "sources" / "french-oak.jpg").is_file()
