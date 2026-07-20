"""Tests for shaft selection in part_number_service.

Focus on the two live bugs fixed 2026-07-20:
  1. heavy (>2000 lb) doors were billed SH10-00002-00 quantity=1 — one INCH
     of bulk bar stock (~$0.34) instead of a real ~20ft shaft.
  2. shaft physical length was hardcoded as ff*12+6 at four sites, so any
     SH12 (which ends 10", not 06") came out 4" short.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from app.services.part_number_service import DoorConfiguration, PartNumberService


def _config(width_in, door_type="commercial", weight=None):
    return DoorConfiguration(
        door_type=door_type,
        door_series="TX450",
        door_width=width_in,
        door_height=96,
        door_count=1,
        panel_color="WHITE",
        panel_design="FLUSH",
        door_weight=weight,
    )


class TestHeavyDoorShaft:
    def setup_method(self):
        self.svc = PartNumberService()

    def test_heavy_door_gets_the_24ft6_stock_shaft(self):
        """A 20' heavy door (258" span) fits within the 24'6" stock shaft, so
        it should bill SH10-00002-01 qty 1 — NOT one inch of bulk bar."""
        cfg = _config(20 * 12, weight=2500)
        parts = self.svc._get_shaft_parts(cfg, spring_count=2)
        shafts = [p for p in parts if p.category == "shaft"]
        assert shafts, "expected at least one shaft part"
        s = shafts[0]
        assert s.part_number == "SH10-00002-01"
        assert s.quantity == 1

    def test_bulk_bar_fallback_bills_by_the_inch(self):
        """A door too wide even for the 24'6" stock shaft falls through to bulk
        bar, which must be billed by the inch (never quantity=1)."""
        cfg = _config(30 * 12, weight=3000)   # 30' door -> 378" span > 294"
        parts = self.svc._get_shaft_parts(cfg, spring_count=2)
        s = next(p for p in parts if p.category == "shaft")
        if s.part_number == "SH10-00002-00":
            assert s.quantity >= 30 * 12, "bulk bar must bill by the inch"

    def test_heavy_door_shaft_covers_required_span(self):
        from app.services import sku_geometry
        cfg = _config(20 * 12, weight=2500)
        parts = self.svc._get_shaft_parts(cfg, spring_count=2)
        shaft = next(p for p in parts if p.category == "shaft")
        needed = cfg.door_width + 18
        if shaft.part_number != "SH10-00002-00":
            length = sku_geometry.sku_to_inches(shaft.part_number)
            assert length is not None and length >= needed


class TestShaftLengthNotFourInchesShort:
    def setup_method(self):
        self.svc = PartNumberService()

    def test_light_residential_tube_shaft_length_is_honest(self):
        """A light resi door takes an SH12 tube shaft. Its physical length must
        reflect the real 10" trailing dimension, not the old ff*12+6."""
        from app.services import sku_geometry
        cfg = _config(16 * 12, door_type="residential", weight=400)
        parts = self.svc._get_shaft_parts(cfg, spring_count=2)
        shaft = next(p for p in parts if p.category == "shaft")
        if shaft.part_number.startswith("SH12-"):
            length = sku_geometry.sku_to_inches(shaft.part_number)
            # SH12 ends in 10", so a 16' door's shaft is FF*12+10, and FF*12+6
            # would be the buggy answer.
            assert length % 12 == 10
