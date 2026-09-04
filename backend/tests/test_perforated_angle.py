"""Perforated back-hang angle tests.

Builder accounts get perforated back-hang angle on every door — we install
those doors, so the material rides on the quote. Dealers supply their own.

Size flips to 2x2 x 12GA at 500 lb; stick count steps
2 -> 4 (500) -> 6 (900) -> 8 (1200) -> 10 (1500 lb).
"""
import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.part_number_service import (
    DoorConfiguration,
    get_parts_for_door_config,
    part_number_service,
)

LIGHT = "TR13-00053-00"   # 1-1/4 x 13GA x 10' perforated
HEAVY = "TR13-00054-00"   # 2 x 2 x 12GA x 10' perforated


def _angle_lines(**overrides) -> list:
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
    parts = get_parts_for_door_config(base).get("parts_list", [])
    return [p for p in parts if p.get("category") == "perforated_angle"]


def _angle_at_weight(weight, **overrides):
    """Exercise the selector directly.

    doorWeight is not a mapped config_dict input (the engine always computes
    it), so hitting each weight boundary through door geometry alone isn't
    practical.
    """
    config = DoorConfiguration(
        door_type="commercial", door_series="KANATA",
        door_width=192, door_height=120, door_count=1,
        panel_color="WHITE", panel_design="FLUSH",
        door_weight=weight, include_perforated_angle=True,
        **overrides,
    )
    return part_number_service._get_perforated_angle_parts(config)


class TestBuilderGate:
    def test_dealer_gets_no_angle(self):
        # Default (flag absent) and explicit False both suppress it.
        assert _angle_lines(doorWidth=288, doorHeight=216) == []
        assert _angle_lines(doorWidth=288, doorHeight=216,
                            includePerforatedAngle=False) == []

    def test_selector_respects_builder_gate(self):
        config = DoorConfiguration(
            door_type="commercial", door_series="KANATA",
            door_width=192, door_height=120, door_count=1,
            panel_color="WHITE", panel_design="FLUSH", door_weight=1600,
        )
        assert part_number_service._get_perforated_angle_parts(config) == []

    def test_builder_light_door_gets_small_angle(self):
        parts = _angle_lines(includePerforatedAngle=True)
        assert len(parts) == 1
        assert parts[0]["part_number"] == LIGHT
        assert parts[0]["quantity"] == 2


class TestWeightThresholds:
    def test_size_flips_at_500_lb(self):
        assert _angle_at_weight(499)[0].part_number == LIGHT
        assert _angle_at_weight(500)[0].part_number == HEAVY

    @pytest.mark.parametrize("weight,expected_qty", [
        (150, 2), (499, 2),
        (500, 4), (899, 4),
        (900, 6), (1199, 6),
        (1200, 8), (1499, 8),
        (1500, 10), (2400, 10),
    ])
    def test_quantity_breakpoints(self, weight, expected_qty):
        assert _angle_at_weight(weight)[0].quantity == expected_qty, f"{weight} lb"

    def test_light_angle_only_ever_appears_at_two_sticks(self):
        # The 500 lb line is both the size step and the first quantity step, so
        # the 1-1/4 angle can never be quoted at more than 2 sticks.
        for weight in (50, 200, 350, 499):
            part = _angle_at_weight(weight)[0]
            assert part.part_number == LIGHT and part.quantity == 2


class TestQuoteIntegration:
    def test_quantity_multiplies_by_door_count(self):
        # 2 sticks per door (108x84 is under 500 lb) x 3 identical doors.
        parts = _angle_lines(includePerforatedAngle=True, doorCount=3)
        assert parts[0]["quantity"] == 6

    def test_note_records_the_driving_weight(self):
        parts = _angle_lines(doorWidth=288, doorHeight=216, doorType="commercial",
                             panelDesign="FLUSH", includePerforatedAngle=True)
        assert "10' stick(s)" in parts[0]["notes"]
        assert "lbs" in parts[0]["notes"]

    def test_sorts_between_track_and_hardware(self):
        from app.api.door_configurator import _sort_parts_by_category
        base = {
            "doorType": "commercial", "doorSeries": "KANATA",
            "doorWidth": 192, "doorHeight": 120, "doorCount": 1,
            "panelColor": "WHITE", "panelDesign": "FLUSH",
            "hardware": {}, "trackThickness": "2", "trackRadius": "15",
            "trackMount": "bracket", "liftType": "standard",
            "includePerforatedAngle": True,
        }
        parts = get_parts_for_door_config(base).get("parts_list", [])
        cats = [p.get("category") for p in _sort_parts_by_category(parts)]
        assert cats.index("track") < cats.index("perforated_angle") < cats.index("hardware")
