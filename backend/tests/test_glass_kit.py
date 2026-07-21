"""Tests for glass-kit workarounds — paint-the-frame + commercial flexibility."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from app.services.glass_kit_service import glass_kit_service as gk, parse_gk


# A slice of the real GK16 catalog.
CATALOG = {
    "GK16-23200-00": "GLASS KIT, 1-3/4\" TX 450, 24 X 12, THERM - CLEAR, WHITE",
    "GK16-23200-01": "GLASS KIT, 1-3/4\" TX 450, 24 X 8, THERM - CLEAR, WHITE",
    "GK16-23205-00": "GLASS KIT, 1-3/4\" TX 450, 24 X 12, THERM - CLEAR, BLACK",
    "GK16-23205-20": "GLASS KIT, 1-3/4\" TX 450, 24 X 12, THERM - TEMPERED, BLACK",
    "GK15-10110-00": "GLASS KIT, 1-3/4\" KANATA, SHORT, SINGLE - CLEAR, NEW BROWN",
    "GK15-10130-00": "GLASS KIT, 1-3/4\" KANATA, SHORT, SINGLE - CLEAR, NEW ALMOND",
    "GK15-10200-00": "GLASS KIT, 1-3/4\" KANATA, SHORT, THERM - CLEAR, WHITE",
}


class TestParse:
    def test_frame_colour_and_paint_key(self):
        g = parse_gk("GK16-23200-00", CATALOG["GK16-23200-00"])
        assert g["frame_color"] == "WHITE"
        assert g["is_commercial"] is True
        assert g["paint_key"].endswith("THERM - CLEAR")

    def test_same_kit_different_colour_shares_paint_key(self):
        a = parse_gk("GK16-23200-00", CATALOG["GK16-23200-00"])  # WHITE
        b = parse_gk("GK16-23205-00", CATALOG["GK16-23205-00"])  # BLACK
        assert a["paint_key"] == b["paint_key"]

    def test_different_glass_is_a_different_paint_key(self):
        clear = parse_gk("GK16-23205-00", CATALOG["GK16-23205-00"])   # CLEAR
        temp = parse_gk("GK16-23205-20", CATALOG["GK16-23205-20"])    # TEMPERED
        assert clear["paint_key"] != temp["paint_key"]

    def test_residential_detected(self):
        g = parse_gk("GK15-10110-00", CATALOG["GK15-10110-00"])
        assert g["is_residential"] is True
        assert g["paintable"] is True
        assert g["frame_color"] == "NEW BROWN"

    def test_commercial_is_not_paintable(self):
        g = parse_gk("GK16-23200-00", CATALOG["GK16-23200-00"])
        assert g["is_commercial"] is True
        assert g["paintable"] is False


class TestWorkaround:
    def test_commercial_is_never_painted(self):
        """GK16 is commercial (black/white only) — even with a same-kit
        different-colour in stock, the workaround is flex, NOT paint."""
        wa = gk.workaround("GK16-23200-00", CATALOG["GK16-23200-00"],
                           CATALOG, in_stock={"GK16-23205-00": 5})
        assert wa["type"] == "commercial_flex"
        assert gk.paint_substitutes("GK16-23200-00", CATALOG["GK16-23200-00"],
                                    CATALOG, in_stock={"GK16-23205-00": 5}) == []

    def test_residential_paint_when_only_colour_differs(self):
        # Need NEW BROWN, only NEW ALMOND in stock -> paint it (residential).
        wa = gk.workaround("GK15-10110-00", CATALOG["GK15-10110-00"],
                           CATALOG, in_stock={"GK15-10130-00": 3})
        assert wa["type"] == "paint_frame"
        assert "GK15-10130-00" in wa["detail"]
        assert "NEW BROWN" in wa["detail"]

    def test_residential_no_paint_when_size_or_glass_differs(self):
        # Only a different-size residential kit in stock -> no paint substitute.
        subs = gk.paint_substitutes(
            "GK15-10110-00", CATALOG["GK15-10110-00"], CATALOG,
            in_stock={"GK15-10200-00": 5},  # SHORT THERM (glass differs)
        )
        assert subs == []

    def test_commercial_flex_when_nothing_in_stock(self):
        wa = gk.workaround("GK16-23200-00", CATALOG["GK16-23200-00"],
                           CATALOG, in_stock={})
        assert wa["type"] == "commercial_flex"

    def test_residential_note_when_no_paint_stock(self):
        wa = gk.workaround("GK15-10110-00", CATALOG["GK15-10110-00"],
                           CATALOG, in_stock={})
        assert wa["type"] == "residential"

    def test_non_gk_returns_none(self):
        assert gk.workaround("PN40-21400-1800", "SECTION", CATALOG, {}) is None
