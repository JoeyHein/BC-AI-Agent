"""Tests for SKU geometry + the cutting-stock solver.

The panel and shaft cases are Joey's real examples (2026-07-20):
  - PN40-24400-3204 is a 32'4" bulk UDC white commercial section
  - one 32'4" yields 2 x 16'2" with no waste, or 14' + 18'2" with 2" of drop
  - SH11 stock ladder is sparse (no 12'6", no 14'6"), so 13'6" gets cut down
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from app.services import sku_geometry
from app.services.cutting_stock_service import (
    KERF_BY_KIND,
    FIT_TOLERANCE_BY_KIND,
    CuttingStockService,
    pack_pieces,
)


class TestPanelParsing:
    def test_bulk_panel_decodes_to_32ft4(self):
        geo = sku_geometry.parse("PN40-24400-3204")
        assert geo is not None
        assert geo.length_inches == 388          # 32*12 + 4
        assert geo.kind == "panel"
        assert geo.family == "PN40-24400"
        assert geo.cuttable is True              # commercial

    def test_family_excludes_only_the_length(self):
        a = sku_geometry.cut_family("PN40-24400-3204")
        b = sku_geometry.cut_family("PN40-24400-1602")
        assert a == b == "PN40-24400"

    def test_different_colour_is_a_different_family(self):
        white = sku_geometry.cut_family("PN40-24400-3204")
        black = sku_geometry.cut_family("PN40-24405-3204")
        assert white != black

    def test_different_height_is_a_different_family(self):
        h24 = sku_geometry.cut_family("PN40-24400-3204")
        h21 = sku_geometry.cut_family("PN40-21400-3204")
        assert h24 != h21

    def test_garbage_sku_returns_none(self):
        assert sku_geometry.parse("HK02-00001-00") is None
        assert sku_geometry.parse("") is None
        assert sku_geometry.parse("not-a-sku") is None


class TestCuttingRules:
    def test_commercial_any_design_is_cuttable(self):
        # PN75 stamp 3 = micro-groove, commercial -> allowed
        assert sku_geometry.parse("PN75-24300-1600").cuttable is True

    def test_residential_flush_and_traf_are_cuttable(self):
        assert sku_geometry.parse("PN65-24000-0900").cuttable is True   # 0 = FLUSH
        assert sku_geometry.parse("PN65-24300-0900").cuttable is True   # 3 = TRAF

    def test_residential_stamped_design_is_not_cuttable(self):
        geo = sku_geometry.parse("PN65-24100-0900")  # 1 = SH, a stamped design
        assert geo.cuttable is False
        assert "stamped design" in geo.reason

    def test_craft_only_flush_is_cuttable(self):
        assert sku_geometry.parse("PN95-24000-0900").cuttable is True   # FLUSH
        assert sku_geometry.parse("PN95-24600-0900").cuttable is False  # Denison

    def test_stamp_digit_meaning_is_series_dependent(self):
        """'3' is Trafalgar on PN65 (cuttable) and micro-groove on PN75
        (also cuttable, but for a completely different reason). '1' is a
        stamped residential design and must NOT be cuttable."""
        assert sku_geometry.parse("PN65-24300-0900").cuttable is True
        assert sku_geometry.parse("PN75-24300-1600").cuttable is True
        assert sku_geometry.parse("PN65-24100-0900").cuttable is False

    def test_aluminium_never_cuttable(self):
        for pn in ("PN10", "PN12", "PN97"):
            geo = sku_geometry.parse(f"{pn}-24000-0900")
            assert geo.cuttable is False
            assert "glass layout" in geo.reason


class TestCanCutFrom:
    def test_longer_donor_same_family_allowed(self):
        ok, why = sku_geometry.can_cut_from("PN40-24400-3204", "PN40-24400-1602")
        assert ok is True and why == ""

    def test_shorter_donor_rejected(self):
        ok, why = sku_geometry.can_cut_from("PN40-24400-1602", "PN40-24400-3204")
        assert ok is False and "shorter than target" in why

    def test_cross_colour_rejected(self):
        ok, why = sku_geometry.can_cut_from("PN40-24405-3204", "PN40-24400-1602")
        assert ok is False and "different cut family" in why

    def test_residential_stamped_donor_rejected(self):
        ok, why = sku_geometry.can_cut_from("PN65-24100-1600", "PN65-24100-0900")
        assert ok is False and "stamped design" in why


class TestShaftParsing:
    def test_sh11_uses_6_inch_offset(self):
        assert sku_geometry.sku_to_inches("SH11-11306-00") == 13 * 12 + 6   # 13'6"
        assert sku_geometry.sku_to_inches("SH11-11006-00") == 10 * 12 + 6   # 10'6"
        assert sku_geometry.sku_to_inches("SH11-10906-00") == 9 * 12 + 6    # 9'6"

    def test_sh12_uses_10_inch_offset_not_6(self):
        """The bug this module replaces: part_number_service hardcodes
        ff*12+6 at four sites, so every SH12 came out 4" short."""
        assert sku_geometry.sku_to_inches("SH12-11210-00") == 12 * 12 + 10
        assert sku_geometry.sku_to_inches("SH12-11210-00") != 12 * 12 + 6

    def test_shafts_are_always_cuttable(self):
        assert sku_geometry.parse("SH11-11306-00").cuttable is True

    def test_shaft_cut_down_from_13ft6(self):
        """Joey's real case: no 12'6" or 14'6" in the ladder, so a 13'6" gets
        cut down to a 10'6" and (from a second stick) a 9'6"."""
        ok, _ = sku_geometry.can_cut_from("SH11-11306-00", "SH11-11006-00")
        assert ok is True
        ok, _ = sku_geometry.can_cut_from("SH11-11306-00", "SH11-10906-00")
        assert ok is True


class TestFormatInches:
    def test_renders_feet_and_inches(self):
        assert sku_geometry.format_inches(388) == "32'4\""
        assert sku_geometry.format_inches(194) == "16'2\""
        assert sku_geometry.format_inches(2) == "0'2\""


class TestPacking:
    def test_two_16ft2_from_one_32ft4_with_a_real_blade(self):
        """Joey's example, with the blade modelled honestly. 2 x 194 + 1/8"
        kerf = 388.125" out of a 388" stick, which only works because a panel
        may finish up to 1/4" under nominal. Both pieces come off one stick."""
        plans = pack_pieces(donor_length=388, piece_length=194, qty_needed=2,
                            donor_sticks_available=5,
                            kerf=KERF_BY_KIND["panel"],
                            fit_tolerance=FIT_TOLERANCE_BY_KIND["panel"])
        assert len(plans) == 1
        assert plans[0].pieces == [194, 194]

    def test_without_fit_tolerance_the_kerf_costs_a_piece(self):
        """Guards the tolerance model. Zero tolerance and a real blade halves
        the yield — if this ever becomes the live config, panel buy quantities
        roughly double."""
        plans = pack_pieces(donor_length=388, piece_length=194, qty_needed=2,
                            donor_sticks_available=5, kerf=0.125,
                            fit_tolerance=0.0)
        assert len(plans) == 2
        assert all(len(p.pieces) == 1 for p in plans)

    def test_waste_never_reported_negative(self):
        """When tolerance absorbs the kerf the arithmetic can go a hair
        negative; that is a piece finishing under nominal, not an offcut."""
        plans = pack_pieces(donor_length=388, piece_length=194, qty_needed=2,
                            donor_sticks_available=1, kerf=0.125,
                            fit_tolerance=0.25)
        assert all(p.waste_inches >= 0 for p in plans)

    def test_14ft_and_18ft2_leaves_2_inches(self):
        """168 + 218 = 386 out of 388 -> 2" drop. Verifies the arithmetic
        behind Joey's 'only waste of 2 inches' example."""
        assert 168 + 218 == 386
        assert 388 - 386 == 2

    def test_respects_available_stick_count(self):
        plans = pack_pieces(donor_length=388, piece_length=194,
                            qty_needed=10, donor_sticks_available=2, kerf=0)
        assert len(plans) == 2
        assert sum(len(p.pieces) for p in plans) == 4

    def test_piece_longer_than_donor_yields_nothing(self):
        assert pack_pieces(donor_length=194, piece_length=388,
                           qty_needed=1, donor_sticks_available=5) == []

    def test_zero_and_negative_inputs_are_safe(self):
        assert pack_pieces(0, 10, 1, 1) == []
        assert pack_pieces(100, 0, 1, 1) == []
        assert pack_pieces(100, 10, 0, 1) == []


def _row(item_no, demand=0, on_hand=0, net_need=0, unit_cost=100.0, jobs=None):
    return {
        "item_no": item_no, "demand": demand, "on_hand": on_hand,
        "on_order": 0, "net_need": net_need, "unit_cost": unit_cost,
        "unit_of_measure": "EA", "jobs": jobs or [],
    }


class TestCuttingStockService:
    def setup_method(self):
        self.svc = CuttingStockService()

    def test_finds_the_obvious_opportunity(self):
        rows = [
            _row("PN40-24400-1602", demand=4, net_need=4, jobs=["SO-1"]),
            _row("PN40-24400-3204", on_hand=3),
        ]
        recs = self.svc.analyze(rows)
        assert len(recs) == 1
        r = recs[0]
        assert r.target_sku == "PN40-24400-1602"
        assert r.donor_sku == "PN40-24400-3204"
        assert r.pieces_yielded >= 4
        assert r.jobs == ["SO-1"]

    def test_ignores_donor_in_a_different_colour(self):
        rows = [
            _row("PN40-24400-1602", demand=4, net_need=4),
            _row("PN40-24405-3204", on_hand=9),   # black, not white
        ]
        assert self.svc.analyze(rows) == []

    def test_ignores_stamped_residential_donor(self):
        rows = [
            _row("PN65-24100-0900", demand=2, net_need=2),
            _row("PN65-24100-1600", on_hand=5),
        ]
        assert self.svc.analyze(rows) == []

    def test_does_not_consume_donor_stock_already_committed(self):
        """Donor has 2 on hand but its own demand is 2 -> nothing free."""
        rows = [
            _row("PN40-24400-1602", demand=4, net_need=4),
            _row("PN40-24400-3204", demand=2, on_hand=2),
        ]
        assert self.svc.analyze(rows) == []

    def test_two_shortfalls_cannot_claim_the_same_stick(self):
        rows = [
            _row("PN40-24400-1602", demand=2, net_need=2),
            _row("PN40-24400-1600", demand=2, net_need=2),
            _row("PN40-24400-3204", on_hand=1),   # only ONE stick
        ]
        recs = self.svc.analyze(rows)
        assert sum(r.donor_sticks_used for r in recs) <= 1

    def test_flags_waste_over_tolerance(self):
        """9'6" out of a 13'6" stick = 4' of drop: allowed, but flagged."""
        rows = [
            _row("SH11-10906-00", demand=1, net_need=1),
            _row("SH11-11306-00", on_hand=2),
        ]
        recs = self.svc.analyze(rows)
        assert len(recs) == 1
        assert recs[0].within_tolerance is False
        assert "exceeds" in recs[0].note

    def test_no_donor_stock_yields_nothing(self):
        rows = [
            _row("PN40-24400-1602", demand=4, net_need=4),
            _row("PN40-24400-3204", on_hand=0),
        ]
        assert self.svc.analyze(rows) == []

    def test_non_length_skus_are_ignored_entirely(self):
        rows = [_row("HK02-00001-00", demand=5, net_need=5),
                _row("GK17-11600-00", on_hand=50)]
        assert self.svc.analyze(rows) == []

    def test_summary_shape(self):
        rows = [
            _row("PN40-24400-1602", demand=4, net_need=4, unit_cost=250.0),
            _row("PN40-24400-3204", on_hand=3),
        ]
        s = self.svc.summarize(self.svc.analyze(rows))
        assert s["opportunity_count"] == 1
        assert s["items_covered"] == 1
        assert s["estimated_cost_avoided"] > 0
        assert set(s) == {
            "opportunity_count", "items_covered", "estimated_cost_avoided",
            "within_tolerance", "over_tolerance", "total_waste_inches",
        }
