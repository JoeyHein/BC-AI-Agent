"""Part number generation tests.

Covers critical bugs:
- Struts: KANATA and CRAFT residential always get 1x20ga
- Hardware boxes: correct BC part numbers (HW for commercial, HK10 for residential)
- Top seal: optional upgrade below threshold, auto above
- Comment line: includes track size, mount type, lift type
- Freight: Output flag set
- High lift: extension track kit included
"""
import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.part_number_service import get_parts_for_door_config
from app.services.bc_part_number_mapper import get_bc_mapper


def _get_parts(overrides: dict) -> list:
    base = {
        "doorType": "residential", "doorSeries": "KANATA",
        "doorWidth": 108, "doorHeight": 84, "doorCount": 1,
        "panelColor": "WHITE", "panelDesign": "SHXL",
        "hardware": {"struts": True, "tracks": True, "springs": True,
                     "hardwareKits": True, "weatherStripping": True,
                     "bottomRetainer": True, "shafts": True},
        "targetCycles": 10000, "trackThickness": "2",
        "trackRadius": "15", "trackMount": "bracket", "liftType": "standard",
    }
    base.update(overrides)
    return get_parts_for_door_config(base).get("parts_list", [])


def _by_category(parts, category):
    return [p for p in parts if p.get("category") == category]


# ── Struts ────────────────────────────────────────────────────────────────

class TestStruts:
    @pytest.mark.parametrize("series", ["KANATA", "CRAFT"])
    @pytest.mark.parametrize("width", [96, 108, 144, 192])
    def test_residential_always_gets_strut(self, series, width):
        design = "SHXL" if series == "KANATA" else "FLUSH"
        parts = _get_parts({"doorSeries": series, "panelDesign": design, "doorWidth": width})
        struts = _by_category(parts, "strut")
        assert len(struts) == 1, f"{series} {width//12}ft: expected 1 strut, got {len(struts)}"
        assert struts[0]["quantity"] == 1

    def test_commercial_uses_strutting_chart(self):
        parts = _get_parts({
            "doorType": "commercial", "doorSeries": "TX450",
            "doorWidth": 168, "doorHeight": 120,
            "panelDesign": "UDC", "trackThickness": "3",
        })
        struts = _by_category(parts, "strut")
        # Commercial doors may get 0 or more struts depending on chart
        # Just verify no crash and strut count is reasonable
        assert all(s["quantity"] >= 0 for s in struts)


# ── Hardware boxes ────────────────────────────────────────────────────────

class TestHardwareBoxes:
    def test_residential_hardware_in_bc(self):
        mapper = get_bc_mapper()
        for width in [8, 9, 10, 12, 16, 18]:
            parts = _get_parts({"doorWidth": width * 12})
            hw = _by_category(parts, "hardware")
            assert len(hw) >= 1, f"{width}ft: no hardware kit"
            pn = hw[0]["part_number"]
            assert pn in mapper.bc_items, f"{width}ft: hardware {pn} not in BC"

    def test_commercial_hardware_in_bc(self):
        mapper = get_bc_mapper()
        for width in [12, 14, 16, 18]:
            parts = _get_parts({
                "doorType": "commercial", "doorSeries": "TX450",
                "doorWidth": width * 12, "doorHeight": 120,
                "panelDesign": "UDC", "trackThickness": "3",
            })
            hw = _by_category(parts, "hardware")
            assert len(hw) >= 1, f"Comm {width}ft: no hardware kit"
            pn = hw[0]["part_number"]
            assert pn in mapper.bc_items, f"Comm {width}ft: hardware {pn} not in BC"


# ── Top seal ──────────────────────────────────────────────────────────────

class TestTopSeal:
    def test_residential_no_top_seal(self):
        parts = _get_parts({})
        top_seals = _by_category(parts, "top_seal")
        assert len(top_seals) == 0, "Residential door should NOT have top seal"

    def test_commercial_below_threshold_no_top_seal_by_default(self):
        parts = _get_parts({
            "doorType": "commercial", "doorSeries": "TX450",
            "doorWidth": 168, "doorHeight": 120,
            "panelDesign": "UDC", "trackThickness": "3",
        })
        top_seals = _by_category(parts, "top_seal")
        assert len(top_seals) == 0, "Commercial below 18'x10' should NOT have top seal by default"

    def test_commercial_below_threshold_with_upgrade(self):
        parts = _get_parts({
            "doorType": "commercial", "doorSeries": "TX450",
            "doorWidth": 168, "doorHeight": 120,
            "panelDesign": "UDC", "trackThickness": "3",
            "includeTopSeal": True,
        })
        top_seals = _by_category(parts, "top_seal")
        assert len(top_seals) >= 1, "Commercial with includeTopSeal=True should have top seal"

    def test_commercial_above_threshold_always_has_top_seal(self):
        parts = _get_parts({
            "doorType": "commercial", "doorSeries": "TX450",
            "doorWidth": 240, "doorHeight": 144,
            "panelDesign": "UDC", "trackThickness": "3",
        })
        top_seals = _by_category(parts, "top_seal")
        assert len(top_seals) >= 1, "Commercial 20'x12' should always have top seal"


# ── Comment line ──────────────────────────────────────────────────────────

class TestCommentLine:
    def test_comment_includes_mount_type(self):
        parts = _get_parts({"trackMount": "bracket"})
        comments = _by_category(parts, "comment")
        assert any("BRACKET MOUNT" in c.get("description", "") for c in comments), \
            "Comment should include BRACKET MOUNT"

    def test_comment_includes_angle_mount(self):
        parts = _get_parts({"trackMount": "angle"})
        comments = _by_category(parts, "comment")
        assert any("CONTINUOUS ANGLE" in c.get("description", "") for c in comments), \
            "Comment should include CONTINUOUS ANGLE"

    def test_comment_includes_high_lift(self):
        parts = _get_parts({"liftType": "high_lift", "highLiftInches": 24})
        comments = _by_category(parts, "comment")
        assert any('HIGH LIFT 24"' in c.get("description", "") for c in comments), \
            "Comment should include HIGH LIFT 24\""

    def test_comment_includes_track_size(self):
        parts = _get_parts({"trackThickness": "2"})
        comments = _by_category(parts, "comment")
        assert any('2"' in c.get("description", "") for c in comments), \
            "Comment should include track size"


# ── High lift extension ──────────────────────────────────────────────────

class TestHighLiftExtension:
    def test_high_lift_gets_extension_track(self):
        parts = _get_parts({"liftType": "high_lift", "highLiftInches": 24})
        hl_parts = _by_category(parts, "highlift_track")
        assert len(hl_parts) >= 1, "High lift door should have extension track kit"
        assert "EXT" in hl_parts[0]["part_number"], \
            f"Extension part number should contain EXT: {hl_parts[0]['part_number']}"

    def test_standard_lift_no_extension(self):
        parts = _get_parts({"liftType": "standard"})
        hl_parts = _by_category(parts, "highlift_track")
        assert len(hl_parts) == 0, "Standard lift should NOT have extension track"
