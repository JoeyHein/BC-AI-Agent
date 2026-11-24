"""Missing .192/.207 springs stay manual-entry lines.

They must not be rewritten to .218, posted as an empty-number Item,
substituted by the customer-quote matcher, or priced at $0.
"""
import os
import re
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.api.door_configurator import resolve_unstocked_part_numbers
from app.services.part_number_service import (
    hold_missing_light_wire_line,
    is_missing_light_wire_spring,
    unpriced_light_wire_row,
)


API = os.path.join(os.path.dirname(__file__), "..", "app", "api")
FRONTEND = os.path.join(os.path.dirname(__file__), "..", "..", "frontend", "src")


def test_resolve_does_not_rewrite_192_to_218():
    stocked = {
        "SP11-21820-01": {"number": "SP11-21820-01", "displayName": "SPRING LH .218 x 2"},
        "SP11-21820-02": {"number": "SP11-21820-02", "displayName": "SPRING RH .218 x 2"},
    }
    lines = [
        {
            "part_number": "SP11-19220-01",
            "description": "SPRING, LH, .192 x 2.0 x 17",
            "quantity": 17,
            "category": "spring",
        },
        {
            "part_number": "SP11-19220-02",
            "description": "SPRING, RH, .192 x 2.0 x 17",
            "quantity": 17,
            "category": "spring",
        },
    ]
    warnings = resolve_unstocked_part_numbers(lines, stocked, allow_unresolved_parts=True)
    assert len(warnings) == 2
    for line in lines:
        assert line["lineType"] == "Comment"
        assert line["part_number"] == ""
        assert "SP11-218" not in line["description"]
        assert "Do not substitute .218" in line["description"]
        assert "SP11-19220" in line["description"]
        assert "MANUAL ENTRY" in line["description"]
        assert line.get("_held_for_review") or line.get("_unresolved")


def test_spring_warning_is_a_comment_category():
    pattern = re.compile(r'part\.get\("category"\) in \(([^)]+)\)')
    for name in ("door_configurator.py", "customer_portal.py"):
        text = open(os.path.join(API, name), encoding="utf-8").read()
        groups = [group for group in pattern.findall(text) if "spring_comment" in group]
        assert groups, name
        assert all("spring_warning" in group for group in groups), name


def test_customer_quote_holds_the_missing_sku_unpriced():
    line = {
        "lineType": "Item",
        "part_number": "SP11-20720-02",
        "description": "SPRING, RH, .207 x 2.0",
        "quantity": 24,
    }
    assert is_missing_light_wire_spring(line["part_number"])
    assert hold_missing_light_wire_line(dict(line)) is True
    held = dict(line)
    hold_missing_light_wire_line(held)
    assert held["lineType"] == "Comment"
    assert "Do not substitute .218" in held["description"]

    priced = unpriced_light_wire_row(line)
    assert priced["line_type"] == "Note"
    assert priced["unit_price"] is None
    assert priced["line_total"] is None
    assert priced["held_for_review"] is True
    assert unpriced_light_wire_row({"part_number": "SP11-21820-01", "quantity": 24}) is None


def test_quote_review_shows_spring_warning_and_door_weight():
    jsx = open(
        os.path.join(FRONTEND, "components", "DoorConfigurator.jsx"),
        encoding="utf-8",
    ).read()
    assert "category === 'spring_warning'" in jsx
    assert "Measured Door Weight" in jsx
    assert "doorWeight" in jsx
    builder = open(
        os.path.join(FRONTEND, "components", "customer", "SpringBuilder.jsx"),
        encoding="utf-8",
    ).read()
    assert "missing_bc_items" in builder


def test_spring_finder_does_not_step_192_up_to_218():
    from app.services.spring_builder_service import spring_builder_service

    class _Query:
        def filter(self, *args, **kwargs):
            return self

        def first(self):
            return None

    class _DB:
        def query(self, *args, **kwargs):
            return _Query()

    result = spring_builder_service.calculate_and_match(
        db=_DB(),
        door_weight=150,
        door_height=84,
        door_width=96,
        spring_qty=2,
        target_cycles=10000,
        drum_model="D400-96",
        track_radius=15,
    )
    assert result["success"] is True
    assert result["missing_bc_items"]
    assert all("192" in pn or "207" in pn for pn in result["missing_bc_items"])
    assert "218" not in result["springs"]["lh"]["part_number"]
    assert "218" not in result["springs"]["rh"]["part_number"]
    assert result["special_order_needed"] is True
