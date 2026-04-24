"""Tests for the surgical quote-edit helpers in customer_portal.py."""

import pytest
from app.api.customer_portal import _diff_doors


class TestDiffDoors:
    def test_no_changes(self):
        doors = [{"doorSeries": "SHXL", "doorWidth": 96, "doorHeight": 84}]
        assert _diff_doors(doors, doors) == {"changed": [], "added": [], "removed": []}

    def test_single_field_change(self):
        old = [{"doorSeries": "SHXL", "doorWidth": 96}]
        new = [{"doorSeries": "SHXL", "doorWidth": 108}]
        assert _diff_doors(old, new) == {"changed": [1], "added": [], "removed": []}

    def test_second_door_changed(self):
        old = [{"doorWidth": 96}, {"doorWidth": 108}]
        new = [{"doorWidth": 96}, {"doorWidth": 120}]
        assert _diff_doors(old, new) == {"changed": [2], "added": [], "removed": []}

    def test_door_added_at_end(self):
        old = [{"doorWidth": 96}]
        new = [{"doorWidth": 96}, {"doorWidth": 108}]
        assert _diff_doors(old, new) == {"changed": [], "added": [2], "removed": []}

    def test_door_removed_at_end(self):
        old = [{"doorWidth": 96}, {"doorWidth": 108}]
        new = [{"doorWidth": 96}]
        assert _diff_doors(old, new) == {"changed": [], "added": [], "removed": [2]}

    def test_door_removed_at_start_shifts_indices(self):
        # When door 1 is removed, what was door 2 is now at position 1 —
        # position-based diff treats this as "position 1 changed, position 2 removed"
        old = [{"doorWidth": 96}, {"doorWidth": 108}]
        new = [{"doorWidth": 108}]
        assert _diff_doors(old, new) == {"changed": [1], "added": [], "removed": [2]}

    def test_hardware_nested_change(self):
        old = [{"doorWidth": 96, "hardware": {"kit": "HK02"}}]
        new = [{"doorWidth": 96, "hardware": {"kit": "HK03"}}]
        assert _diff_doors(old, new) == {"changed": [1], "added": [], "removed": []}

    def test_empty_to_single(self):
        assert _diff_doors([], [{"doorWidth": 96}]) == {
            "changed": [], "added": [1], "removed": [],
        }

    def test_single_to_empty(self):
        assert _diff_doors([{"doorWidth": 96}], []) == {
            "changed": [], "added": [], "removed": [1],
        }
