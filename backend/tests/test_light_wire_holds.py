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


def _kanata_8x7():
    return {
        "doorType": "residential",
        "doorSeries": "KANATA",
        "doorWidth": 96,
        "doorHeight": 84,
        "doorCount": 1,
        "panelColor": "WHITE",
        "panelDesign": "SHXL",
        "hardware": {
            "panels": True,
            "tracks": True,
            "springs": True,
            "struts": True,
            "hardwareKits": True,
            "weatherStripping": True,
            "bottomRetainer": True,
            "shafts": True,
        },
        "targetCycles": 10000,
        "trackThickness": "2",
        "trackRadius": "15",
        "trackMount": "bracket",
        "liftType": "standard",
    }


_LIGHT = ("SP11-20720-01", "SP11-20720-02")


class _RejectingBC:
    """Accepts every line except a missing light-wire item, which BC rejects."""

    def __init__(self):
        self.added = []
        self._n = 0

    def update_sales_quote(self, quote_id, quote_data, etag="*", company_id=None):
        return {"id": quote_id}

    def add_quote_line(self, quote_id, line_data):
        number = line_data.get("lineObjectNumber") or ""
        if line_data.get("lineType") != "Comment" and number.startswith("SP11-207"):
            raise RuntimeError(f"BC item {number} does not exist")
        self._n += 1
        row = {"id": f"line-{self._n}", "sequence": self._n * 10000, **line_data}
        self.added.append(row)
        return {**row, "description": line_data.get("description", ""), "unitPrice": 0, "@odata.etag": "*"}

    def update_quote_line(self, quote_id, line_id, etag, data):
        return {"id": line_id}

    def set_quote_line_output(self, number, sequence, output=True):
        return None

    def delete_quote_line(self, quote_id, line_id):
        return None

    def get_sales_quote(self, quote_id):
        return {
            "id": quote_id,
            "number": "SQ-HOLD",
            "totalAmountExcludingTax": 100.0,
            "totalAmountIncludingTax": 105.0,
        }

    def get_quote_lines(self, quote_id):
        return [
            row for row in self.added
            if row.get("lineType") == "Item"
        ]


def _no_substitute(*args, **kwargs):
    raise AssertionError("a missing light-wire spring must not be substituted")


def test_local_estimate_holds_kanata_207_unpriced(monkeypatch):
    import app.api.customer_portal as portal

    monkeypatch.setattr(portal, "get_bc_spring_inventory", lambda: {})
    monkeypatch.setattr(portal, "warm_bc_cost_cache", lambda *args, **kwargs: None)
    monkeypatch.setattr(portal, "calculate_selling_price", lambda **kwargs: 0.0)
    monkeypatch.setattr(portal, "_find_ai_substitute", _no_substitute)
    monkeypatch.setattr(
        portal, "calculate_freight",
        lambda **kwargs: {"skip": True, "amount": 0, "rate": 0, "description": "Pickup"},
    )
    result = portal._estimate_pricing_locally(
        doors=[_kanata_8x7()],
        pricing_tier="retail",
        config_id=1,
        db=None,
        delivery_type="pickup",
    )
    rows = result["line_pricing"]
    items = [row for row in rows if row.get("line_type") == "Item"]
    assert not any(row.get("part_number") in _LIGHT for row in items)
    held = [
        row for row in rows
        if row.get("held_for_review") and any(pn in (row.get("description") or "") for pn in _LIGHT)
    ]
    assert {pn for pn in _LIGHT if any(pn in row["description"] for row in held)} == set(_LIGHT)
    for row in held:
        assert row["unpriced"] is True
        assert row["unit_price"] is None
        assert row["line_total"] is None
        assert row["line_type"] == "Note"
        assert "Do not substitute .218" in row["description"]
    assert all(row.get("unit_price") != 0 or row.get("part_number") not in _LIGHT for row in rows)


def test_edit_reprice_holds_kanata_207_as_a_comment(monkeypatch):
    import app.api.customer_portal as portal
    from types import SimpleNamespace

    monkeypatch.setattr(portal, "get_bc_spring_inventory", lambda: {})
    monkeypatch.setattr(portal, "warm_bc_cost_cache", lambda *args, **kwargs: None)
    monkeypatch.setattr(portal, "_find_ai_substitute", _no_substitute)
    bc = _RejectingBC()
    monkeypatch.setattr(portal, "bc_client", bc)
    config = SimpleNamespace(
        id=None,
        bc_quote_id="quote-hold",
        bc_quote_number="SQ-HOLD",
        config_data={"doors": []},
        bc_line_map=None,
    )
    result = portal._edit_bc_quote_lines(
        config,
        {"doors": [_kanata_8x7()]},
        bc_customer_id="C-HOLD",
        pricing_tier="retail",
        db=None,
        customer_user_id=None,
        delivery_type="pickup",
    )
    posted_items = [
        row.get("lineObjectNumber") for row in bc.added if row.get("lineType") == "Item"
    ]
    assert not any(pn in posted_items for pn in _LIGHT)
    comments = [row.get("description") or "" for row in bc.added if row.get("lineType") == "Comment"]
    for pn in _LIGHT:
        match = [text for text in comments if pn in text]
        assert match, pn
        assert any("Held for review, unpriced" in text and "Do not substitute .218" in text for text in match)
        assert not any(text.startswith(f"{pn} - ") for text in match)
    failed = result.get("lines_failed") or []
    assert not any((row.get("part_number") or "") in _LIGHT for row in failed)
