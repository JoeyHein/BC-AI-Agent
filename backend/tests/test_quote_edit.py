"""Tests for the surgical quote-edit helpers in customer_portal.py."""

import pytest
from app.api.customer_portal import _diff_doors


class TestDiffDoors:
    """Legacy positional-diff path — exercised when doors lack `door_uid`."""

    def test_no_changes(self):
        doors = [{"doorSeries": "SHXL", "doorWidth": 96, "doorHeight": 84}]
        assert _diff_doors(doors, doors) == {
            "changed": [], "added": [], "removed": [], "moved": [],
        }

    def test_single_field_change(self):
        old = [{"doorSeries": "SHXL", "doorWidth": 96}]
        new = [{"doorSeries": "SHXL", "doorWidth": 108}]
        assert _diff_doors(old, new) == {
            "changed": [1], "added": [], "removed": [], "moved": [],
        }

    def test_second_door_changed(self):
        old = [{"doorWidth": 96}, {"doorWidth": 108}]
        new = [{"doorWidth": 96}, {"doorWidth": 120}]
        assert _diff_doors(old, new) == {
            "changed": [2], "added": [], "removed": [], "moved": [],
        }

    def test_door_added_at_end(self):
        old = [{"doorWidth": 96}]
        new = [{"doorWidth": 96}, {"doorWidth": 108}]
        assert _diff_doors(old, new) == {
            "changed": [], "added": [2], "removed": [], "moved": [],
        }

    def test_door_removed_at_end(self):
        old = [{"doorWidth": 96}, {"doorWidth": 108}]
        new = [{"doorWidth": 96}]
        assert _diff_doors(old, new) == {
            "changed": [], "added": [], "removed": [2], "moved": [],
        }

    def test_door_removed_at_start_shifts_indices(self):
        # Without uids, falls back to positional diff — what was door 2 is now
        # at position 1, so positional comparison treats this as "position 1
        # changed, position 2 removed" (suboptimal but correct given no
        # identity info). The identity-based path tested below avoids this.
        old = [{"doorWidth": 96}, {"doorWidth": 108}]
        new = [{"doorWidth": 108}]
        assert _diff_doors(old, new) == {
            "changed": [1], "added": [], "removed": [2], "moved": [],
        }

    def test_hardware_nested_change(self):
        old = [{"doorWidth": 96, "hardware": {"kit": "HK02"}}]
        new = [{"doorWidth": 96, "hardware": {"kit": "HK03"}}]
        assert _diff_doors(old, new) == {
            "changed": [1], "added": [], "removed": [], "moved": [],
        }

    def test_empty_to_single(self):
        assert _diff_doors([], [{"doorWidth": 96}]) == {
            "changed": [], "added": [1], "removed": [], "moved": [],
        }

    def test_single_to_empty(self):
        assert _diff_doors([{"doorWidth": 96}], []) == {
            "changed": [], "added": [], "removed": [1], "moved": [],
        }


class TestDiffDoorsIdentity:
    """Identity-based diff — kicks in when every door carries a `door_uid`."""

    def test_unchanged_with_uids(self):
        doors = [
            {"door_uid": "A", "doorWidth": 96},
            {"door_uid": "B", "doorWidth": 108},
        ]
        assert _diff_doors(doors, doors) == {
            "changed": [], "added": [], "removed": [], "moved": [],
        }

    def test_uid_ignored_in_content_compare(self):
        # Adding a uid to an otherwise-identical door doesn't count as a change
        old = [{"door_uid": "A", "doorWidth": 96}]
        new = [{"door_uid": "A", "doorWidth": 96}]
        assert _diff_doors(old, new) == {
            "changed": [], "added": [], "removed": [], "moved": [],
        }

    def test_remove_first_door_shifts_others_via_moves(self):
        # The key bug fix: removing door 1 of 3 should mark only door 1 as
        # removed, with the remaining doors recorded as "moved" (no BC writes).
        old = [
            {"door_uid": "A", "doorWidth": 96},
            {"door_uid": "B", "doorWidth": 108},
            {"door_uid": "C", "doorWidth": 120},
        ]
        new = [
            {"door_uid": "B", "doorWidth": 108},
            {"door_uid": "C", "doorWidth": 120},
        ]
        d = _diff_doors(old, new)
        assert d["removed"] == [1]
        assert d["changed"] == []
        assert d["added"] == []
        assert sorted(d["moved"]) == [(2, 1), (3, 2)]

    def test_content_change_at_stable_position(self):
        old = [
            {"door_uid": "A", "doorWidth": 96},
            {"door_uid": "B", "doorWidth": 108},
        ]
        new = [
            {"door_uid": "A", "doorWidth": 96},
            {"door_uid": "B", "doorWidth": 144},
        ]
        d = _diff_doors(old, new)
        assert d["changed"] == [2]
        assert d["added"] == []
        assert d["removed"] == []
        assert d["moved"] == []

    def test_insert_at_front_shifts_others(self):
        old = [
            {"door_uid": "A", "doorWidth": 96},
            {"door_uid": "B", "doorWidth": 108},
        ]
        new = [
            {"door_uid": "X", "doorWidth": 72},
            {"door_uid": "A", "doorWidth": 96},
            {"door_uid": "B", "doorWidth": 108},
        ]
        d = _diff_doors(old, new)
        assert d["added"] == [1]
        assert d["changed"] == []
        assert d["removed"] == []
        assert sorted(d["moved"]) == [(1, 2), (2, 3)]

    def test_uid_swap_at_same_position(self):
        # Replacing a door's uid (not just its content) treats it as an
        # add+remove rather than a change.
        old = [{"door_uid": "A", "doorWidth": 96}]
        new = [{"door_uid": "X", "doorWidth": 96}]
        d = _diff_doors(old, new)
        assert d["removed"] == [1]
        assert d["added"] == [1]
        assert d["changed"] == []
        assert d["moved"] == []

    def test_swap_doors(self):
        # Two doors swap positions — pure move, no content changes.
        old = [
            {"door_uid": "A", "doorWidth": 96},
            {"door_uid": "B", "doorWidth": 108},
        ]
        new = [
            {"door_uid": "B", "doorWidth": 108},
            {"door_uid": "A", "doorWidth": 96},
        ]
        d = _diff_doors(old, new)
        assert d["changed"] == []
        assert d["added"] == []
        assert d["removed"] == []
        assert sorted(d["moved"]) == [(1, 2), (2, 1)]

    def test_partial_uids_falls_back_to_positional(self):
        # If any door lacks a uid, treat the whole thing as legacy data and
        # use positional diff. Mixed states shouldn't half-apply identity.
        old = [{"door_uid": "A", "doorWidth": 96}, {"doorWidth": 108}]
        new = [{"door_uid": "A", "doorWidth": 96}, {"doorWidth": 120}]
        d = _diff_doors(old, new)
        # Positional path — door 2 changed
        assert d["changed"] == [2]
        assert d["moved"] == []

    def test_remove_first_then_add_at_end(self):
        # [A, B, C] -> [B, C, X]
        # A is removed (was pos 1); B and C shift up; X is new at pos 3.
        # Verifies adds, removes, and moves can all coexist on one diff.
        old = [
            {"door_uid": "A", "doorWidth": 96},
            {"door_uid": "B", "doorWidth": 108},
            {"door_uid": "C", "doorWidth": 120},
        ]
        new = [
            {"door_uid": "B", "doorWidth": 108},
            {"door_uid": "C", "doorWidth": 120},
            {"door_uid": "X", "doorWidth": 132},
        ]
        d = _diff_doors(old, new)
        assert d["removed"] == [1]
        assert d["added"] == [3]
        assert d["changed"] == []
        assert sorted(d["moved"]) == [(2, 1), (3, 2)]

    def test_full_reverse(self):
        # [A, B, C] -> [C, B, A]: every door moves, none change content,
        # nothing added or removed. B stays at the same position so should
        # NOT appear in moves; A and C swap ends.
        old = [
            {"door_uid": "A", "doorWidth": 96},
            {"door_uid": "B", "doorWidth": 108},
            {"door_uid": "C", "doorWidth": 120},
        ]
        new = [
            {"door_uid": "C", "doorWidth": 120},
            {"door_uid": "B", "doorWidth": 108},
            {"door_uid": "A", "doorWidth": 96},
        ]
        d = _diff_doors(old, new)
        assert d["added"] == []
        assert d["removed"] == []
        assert d["changed"] == []
        assert sorted(d["moved"]) == [(1, 3), (3, 1)]

    def test_move_and_change_are_mutually_exclusive(self):
        # When a door moves AND its content changed, it goes into 'changed'
        # only — not also in 'moved'. The caller treats 'changed' as a full
        # re-price (which already implies updating the BC line at the new
        # position), so listing it again under 'moved' would double-count.
        # Only doors that moved WITHOUT content changes appear in 'moved'.
        old = [
            {"door_uid": "A", "doorWidth": 96},
            {"door_uid": "B", "doorWidth": 108},
        ]
        new = [
            {"door_uid": "B", "doorWidth": 144},   # moved 2 -> 1, content changed
            {"door_uid": "A", "doorWidth": 96},    # moved 1 -> 2, unchanged
        ]
        d = _diff_doors(old, new)
        assert d["added"] == []
        assert d["removed"] == []
        assert d["changed"] == [1]                  # B at new pos 1
        assert d["moved"] == [(1, 2)]               # only A — B is in 'changed'
