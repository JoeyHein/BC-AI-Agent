"""Tests for multi-size cut nesting (plan_family_cuts).

Joey's rules:
  - an 18' AND a 14' should come off ONE 32'4" when a job needs both
  - the offcut is kept WHOLE (longest usable size), never pre-cut
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from app.services.cutting_stock_service import (
    plan_family_cuts, KERF_BY_KIND, FIT_TOLERANCE_BY_KIND,
)

# 32'4" = 388", 18' = 216", 14' = 168", 16'2" = 194"
PANEL_KERF = KERF_BY_KIND["panel"]
PANEL_FIT = FIT_TOLERANCE_BY_KIND["panel"]


class TestNesting:
    def test_18_and_14_share_one_stick(self):
        """The headline win: 216 + 168 = 384 fits one 388 stick (with the
        panel fit tolerance absorbing the kerf) -> ONE donor, not two."""
        plans, unmet = plan_family_cuts(
            pieces=[(216, "PN40-x-1800"), (168, "PN40-x-1400")],
            donor_sticks=[(388, "PN40-x-3204"), (388, "PN40-x-3204")],
            kerf=PANEL_KERF, fit_tolerance=PANEL_FIT,
        )
        assert unmet == []
        assert len(plans) == 1                       # one stick, not two
        got = sorted(p[0] for p in plans[0]["pieces"])
        assert got == [168, 216]
        assert plans[0]["leftover"] <= 5             # ~4" scrap

    def test_single_18_leaves_a_whole_14ft4_offcut(self):
        """No second piece needed -> the leftover stays whole (172" = 14'4"),
        the flexible remnant, not pre-cut."""
        plans, unmet = plan_family_cuts(
            pieces=[(216, "PN40-x-1800")],
            donor_sticks=[(388, "PN40-x-3204")],
            kerf=PANEL_KERF, fit_tolerance=PANEL_FIT,
        )
        assert len(plans) == 1
        assert plans[0]["pieces"] == [(216, "PN40-x-1800")]
        assert plans[0]["leftover"] == 172           # 14'4", kept whole

    def test_two_16ft2_nest_on_one_stick(self):
        plans, _ = plan_family_cuts(
            pieces=[(194, "T"), (194, "T")],
            donor_sticks=[(388, "D"), (388, "D")],
            kerf=PANEL_KERF, fit_tolerance=PANEL_FIT,
        )
        assert len(plans) == 1
        assert len(plans[0]["pieces"]) == 2

    def test_uses_second_stick_only_when_needed(self):
        """Three 18' need two sticks (two fit... no: 216*2=432 > 388, so one 18
        per stick) -> three sticks."""
        plans, unmet = plan_family_cuts(
            pieces=[(216, "T")] * 3,
            donor_sticks=[(388, "D")] * 3,
            kerf=PANEL_KERF, fit_tolerance=PANEL_FIT,
        )
        assert unmet == []
        assert len(plans) == 3

    def test_prefers_nesting_over_opening_new_sticks(self):
        """An 18 + 14 with three sticks available should still use just one."""
        plans, _ = plan_family_cuts(
            pieces=[(216, "A"), (168, "B")],
            donor_sticks=[(388, "D")] * 3,
            kerf=PANEL_KERF, fit_tolerance=PANEL_FIT,
        )
        assert len(plans) == 1

    def test_piece_with_no_fitting_stick_is_unmet(self):
        plans, unmet = plan_family_cuts(
            pieces=[(400, "TooBig")],
            donor_sticks=[(388, "D")],
            kerf=PANEL_KERF, fit_tolerance=PANEL_FIT,
        )
        assert plans == []
        assert unmet == [(400, "TooBig")]

    def test_smallest_adequate_stick_opened_first(self):
        """A 10' piece should open the 20' stick, not waste the 32'4"."""
        plans, _ = plan_family_cuts(
            pieces=[(120, "T")],
            donor_sticks=[(388, "big"), (240, "small")],
            kerf=PANEL_KERF, fit_tolerance=PANEL_FIT,
        )
        assert len(plans) == 1
        assert plans[0]["donor_sku"] == "small"

    def test_mixed_sizes_pack_densely(self):
        """18 + 14 on one stick, a lone 16'2" on another."""
        plans, unmet = plan_family_cuts(
            pieces=[(216, "A"), (168, "B"), (194, "C")],
            donor_sticks=[(388, "D")] * 3,
            kerf=PANEL_KERF, fit_tolerance=PANEL_FIT,
        )
        assert unmet == []
        assert len(plans) == 2                       # not 3 — nesting saved one
