"""Tests for strut cutting — struts are cuttable stock whose length + gauge
live in the description (Joey: 'struts, that's another item we can cut down')."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from app.services import sku_geometry
from app.services.cutting_stock_service import CuttingStockService


STRUTS = [
    {"number": "FH17-00018-00", "displayName": "STRUT, 16 GA, 24'"},      # 3" (>18')
    {"number": "FH17-00042-00", "displayName": "STRUT, 16 GA, 26'"},      # 3"
    {"number": "FH17-00036-00", "displayName": "STRUT, 16 GA, 20'"},      # 3"
    {"number": "FH17-00035-00", "displayName": "STRUT, 16 GA, 18'"},      # 2-1/4" (<=18')
    {"number": "FH17-00003-00", "displayName": "STRUT, 20 GA, 2-1/4 X 16'"},
    {"number": "FH17-00028-00", "displayName": "STRUT, 20 GA, 2-1/4 X 8'"},
    {"number": "FH17-00023-00", "displayName": "STRUT CLIP"},            # not stock
    {"number": "FH17-00019-00", "displayName": "Z-STRUT ANGLED STRAP"},  # not stock
]


@pytest.fixture(autouse=True)
def _register():
    sku_geometry._REGISTERED.clear()
    sku_geometry.register_struts(STRUTS)
    yield
    sku_geometry._REGISTERED.clear()


class TestStrutParsing:
    def test_length_and_gauge_from_description(self):
        g = sku_geometry.parse("FH17-00018-00")
        assert g is not None
        assert g.length_inches == 24 * 12
        assert g.kind == "strut"
        assert g.family == "STRUT-16GA-3.0"       # 24' -> 3" face
        assert g.cuttable is True

    def test_width_prefix_ignored(self):
        # "2-1/4 X 16'" -> 16', not 2 or 1
        assert sku_geometry.sku_to_inches("FH17-00003-00") == 16 * 12

    def test_gauge_is_part_of_family(self):
        a = sku_geometry.cut_family("FH17-00018-00")  # 16 GA
        b = sku_geometry.cut_family("FH17-00003-00")  # 20 GA
        assert a != b

    def test_clips_and_straps_are_not_cuttable(self):
        assert sku_geometry.parse("FH17-00023-00") is None
        assert sku_geometry.parse("FH17-00019-00") is None

    def test_16ga_cannot_cut_a_20ga(self):
        ok, why = sku_geometry.can_cut_from("FH17-00018-00", "FH17-00003-00")
        assert ok is False and "different cut family" in why

    def test_face_width_from_18ft_boundary(self):
        # <=18' derives to 2-1/4"; >18' derives to 3"
        assert sku_geometry.parse("FH17-00035-00").family == "STRUT-16GA-2.25"   # 18'
        assert sku_geometry.parse("FH17-00036-00").family == "STRUT-16GA-3.0"    # 20'
        assert sku_geometry.parse("FH17-00018-00").family == "STRUT-16GA-3.0"    # 24'

    def test_cannot_cut_3in_down_to_2_1_4in(self):
        """Joey's rule: a 24' (3") CANNOT be cut to an 18' (2-1/4"), the face
        height differs. This was the earlier wrong assumption."""
        ok, why = sku_geometry.can_cut_from("FH17-00018-00", "FH17-00035-00")
        assert ok is False and "different cut family" in why

    def test_can_cut_within_the_3in_class(self):
        # 26' (3") -> 20' (3"), same gauge + face width
        ok, _ = sku_geometry.can_cut_from("FH17-00042-00", "FH17-00036-00")
        assert ok is True


def _row(item_no, demand=0, on_hand=0, net_need=0, jobs=None):
    return {"item_no": item_no, "demand": demand, "on_hand": on_hand, "on_order": 0,
            "net_need": net_need, "unit_cost": 50.0, "unit_of_measure": "EA",
            "jobs": jobs or []}


class TestStrutInCuttingEngine:
    def test_short_strut_cut_from_longer_same_class(self):
        rows = [
            _row("FH17-00036-00", demand=3, net_need=3, jobs=["SO-1"]),  # 20' 3" short
            _row("FH17-00042-00", on_hand=5),                            # 26' 3" in stock
        ]
        recs = CuttingStockService().analyze(rows)
        assert len(recs) == 1
        assert recs[0].donor_sku == "FH17-00042-00"
        assert recs[0].target_sku == "FH17-00036-00"

    def test_no_cross_gauge_cut(self):
        rows = [
            _row("FH17-00003-00", demand=2, net_need=2),  # 16' 20GA short
            _row("FH17-00018-00", on_hand=5),             # 24' 16GA stock — wrong gauge
        ]
        assert CuttingStockService().analyze(rows) == []

    def test_no_cross_face_width_cut(self):
        """The 24' (3") in stock must NOT be offered to cut an 18' (2-1/4")."""
        rows = [
            _row("FH17-00035-00", demand=2, net_need=2),  # 18' 2-1/4" short
            _row("FH17-00018-00", on_hand=5),             # 24' 3" stock — wrong face width
        ]
        assert CuttingStockService().analyze(rows) == []
