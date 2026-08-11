"""Low-headroom front/rear torsion mount.

BC stocks only front-mount LHR kits (every HK32/HK33 reads "LHR ... FRONT"),
so the selection must NOT change the hardware SKU — it rides on the door
comment line and the shop drawing instead.
"""

import pytest

from app.services.part_number_service import (
    lhr_mount_label,
    get_parts_for_door_config,
)
from app.api.door_configurator import _format_lift_label
from app.services.shop_drawing_service import calculate_shop_drawing_geometry


def _cfg(**over):
    base = {
        "doorType": "residential",
        "doorSeries": "KANATA",
        "doorWidth": 108,
        "doorHeight": 84,
        "doorCount": 1,
        "panelColor": "WHITE",
        "panelDesign": "SHXL",
        "hasWindows": False,
        "trackRadius": "12",
        "trackThickness": "2",
        "trackMount": "bracket",
        "liftType": "low_headroom",
        "hardware": {"panels": True, "tracks": True, "springs": True, "struts": True,
                     "hardwareKits": True, "weatherStripping": True,
                     "bottomRetainer": True, "shafts": True},
    }
    base.update(over)
    return base


class TestLabel:
    def test_front_is_the_default(self):
        assert lhr_mount_label(None) == "(FRONT MOUNT)"
        assert lhr_mount_label("") == "(FRONT MOUNT)"
        assert lhr_mount_label("front") == "(FRONT MOUNT)"

    def test_rear_is_explicit_and_case_insensitive(self):
        assert lhr_mount_label("rear") == "(REAR MOUNT)"
        assert lhr_mount_label("REAR") == "(REAR MOUNT)"

    def test_unknown_value_never_reads_as_rear(self):
        # A typo must not silently quote the mount we don't stock hardware for.
        assert lhr_mount_label("raer") == "(FRONT MOUNT)"


class TestDoorHeaderComment:
    def test_lift_label_front_and_rear(self):
        assert _format_lift_label("low_headroom", None, "front") == "LHR FRONT"
        assert _format_lift_label("low_headroom", None, "rear") == "LHR REAR"

    def test_lift_label_defaults_to_front(self):
        assert _format_lift_label("low_headroom") == "LHR FRONT"

    def test_legacy_lift_values_still_carry_the_mount(self):
        assert _format_lift_label("lhr_rear") == "LHR REAR"
        assert _format_lift_label("lhr_front") == "LHR FRONT"

    def test_non_lhr_lift_types_unaffected(self):
        assert _format_lift_label("standard", None, "rear") == "STD LIFT"
        assert _format_lift_label("vertical", None, "rear") == "VERTICAL"
        assert _format_lift_label("high_lift", 24, "rear") == 'HIGH LIFT 24"'


class TestQuoteComment:
    def _comment(self, cfg):
        parts = get_parts_for_door_config(cfg)["parts_list"]
        comments = [p for p in parts if p.get("category") == "comment"]
        assert comments, "expected a door comment line"
        return comments[0]["description"]

    def test_front_mount_note_on_quote(self):
        assert "LOW HEADROOM (FRONT MOUNT)" in self._comment(_cfg(lhrMount="front"))

    def test_rear_mount_note_on_quote(self):
        assert "LOW HEADROOM (REAR MOUNT)" in self._comment(_cfg(lhrMount="rear"))

    def test_missing_field_falls_back_to_front(self):
        # Quotes saved before this field existed must not read as rear.
        assert "LOW HEADROOM (FRONT MOUNT)" in self._comment(_cfg())

    def test_note_absent_on_non_lhr_doors(self):
        assert "LOW HEADROOM" not in self._comment(_cfg(liftType="standard", trackRadius="15"))


class TestPartsUnchanged:
    """The mount choice is a note, not a different bill of materials."""

    def _skus(self, cfg):
        parts = get_parts_for_door_config(cfg)["parts_list"]
        return sorted(p["part_number"] for p in parts if p.get("part_number"))

    def test_rear_quotes_the_same_skus_as_front(self):
        assert self._skus(_cfg(lhrMount="rear")) == self._skus(_cfg(lhrMount="front"))

    def test_still_gets_the_front_hardware_kit(self):
        skus = self._skus(_cfg(lhrMount="rear"))
        assert any(s.startswith(("HK32", "HK33")) for s in skus), skus


class TestShopDrawingGeometry:
    """Front and rear need genuinely different headroom — this used to be
    hardcoded to rear for every low-headroom door."""

    def _geo(self, **kw):
        return calculate_shop_drawing_geometry(
            door_height=84, door_width=108, track_size=2, track_radius=12,
            lift_type="low_headroom", **kw
        )

    def test_front_and_rear_differ(self):
        front = self._geo(lhr_mount="front")
        rear = self._geo(lhr_mount="rear")
        assert front["headroom_min"] != rear["headroom_min"]

    def test_default_is_front_not_rear(self):
        assert self._geo()["headroom_min"] == self._geo(lhr_mount="front")["headroom_min"]

    def test_rear_needs_less_headroom_than_front(self):
        assert self._geo(lhr_mount="rear")["headroom_min"] < self._geo(lhr_mount="front")["headroom_min"]
