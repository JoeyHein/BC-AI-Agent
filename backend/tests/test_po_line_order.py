"""Panels-first PO line order. Pure functions — no Business Central calls."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services import po_line_order as order
from app.services.so_po_generation_service import _DOOR_HEADER_RE


def _item(item, seq, desc=""):
    return {
        "id": item,
        "sequence": seq,
        "lineType": "Item",
        "lineObjectNumber": item,
        "description": desc or item,
        "quantity": 1,
    }


def _comment(text, seq, line_id=None):
    return {
        "id": line_id or text,
        "sequence": seq,
        "lineType": "Comment",
        "lineObjectNumber": None,
        "description": text,
        "quantity": 0,
    }


class TestClassification:
    def test_insulated_section_prefixes(self):
        for item in (
            "PN55-24400-0900",
            "PN56-24405-1800",
            "PN45-24400-0900",
            "PN46-24405-2000",
            "PN65-21000-1000",
            "PN95-21000-0900",
            "PN35-21400-0800",
        ):
            assert order.classify_item(item) == "insulated", item

    def test_bulk_cores_are_not_insulated_sections(self):
        assert order.classify_item("PN40-24400-1800") == "rest"
        assert order.classify_item("PN50-24400-1800") == "rest"

    def test_glass_sections_and_glazing(self):
        for item in (
            "PN12-24300820-1602",
            "PN10-24300010-0802",
            "PN80-21100-1002",
            "PN97-24300810-1002",
            "PN20-21001020-0802",
            "PN70-24100810-0802",
            "GK17-10000-00",
            "GK15-11000-00",
            "GL12-CLEAR",
        ):
            assert order.classify_item(item) == "glass", item

    def test_hardware_struts_retainer_track_spring_are_rest(self):
        for item in ("HK02-14120-RC", "FH17-00100-00", "PL10-00141-00", "TR02-STDBM-0800", "SP10-25020-01"):
            assert order.classify_item(item) == "rest", item

    def test_prefix_boundary(self):
        assert order.classify_item("PN4500") == "rest"
        assert order.classify_item("PN45") == "insulated"

    def test_description_does_not_reclassify(self):
        assert order.classify_item("HK02-14120-RC", "INSULATED PANEL SECTION") == "rest"

    def test_door_header_regex_matches_so_writer(self):
        assert order.DOOR_HEADER_RE.pattern == _DOOR_HEADER_RE.pattern


class TestOrdering:
    def test_within_one_door_panels_then_glass_then_rest(self):
        header = '(1) 18\'0" x 8\'0" TX450, BLACK, UDC'
        lines = [
            _comment("Acme Doors", 10000, "pre-1"),
            _comment("Built from SO-001299 - 2026-10-06 - opendc purchasing (complete order)", 20000, "pre-2"),
            _comment(header, 30000, "door"),
            _item("HK02-14120-RC", 40000),
            _item("PN12-24300820-1602", 50000),
            _item("PN45-24400-0900", 60000),
            _comment("Five wall required", 70000, "note"),
            _item("FH17-00100-00", 80000),
            _comment('(2) 9\'0" x 7\'0" TX450, WHITE', 90000, "door2"),
            _item("SP10-25020-01", 100000),
            _item("PN55-24400-0900", 110000),
        ]
        got = [ln["id"] for ln in order.order_po_lines(lines)]
        assert got == [
            "pre-1",
            "pre-2",
            "door",
            "PN45-24400-0900",
            "PN12-24300820-1602",
            "HK02-14120-RC",
            "note",
            "FH17-00100-00",
            "door2",
            "PN55-24400-0900",
            "SP10-25020-01",
        ]

    def test_stable_within_a_band(self):
        lines = [
            _item("PN46-24405-1000", 10000),
            _item("PN45-24400-0900", 20000),
            _item("PN65-21000-0800", 30000),
        ]
        got = [ln["lineObjectNumber"] for ln in order.order_po_lines(lines)]
        assert got == ["PN46-24405-1000", "PN45-24400-0900", "PN65-21000-0800"]

    def test_shared_banner_starts_a_new_group(self):
        lines = [
            _comment('(1) 8\'0" x 7\'0" TX450, WHITE', 10000, "d1"),
            _item("HK02-14120-RC", 20000),
            _comment("ITEMS SHARED ACROSS MULTIPLE DOORS ON THIS ORDER", 30000, "shared"),
            _item("HK10-00804-0809", 40000),
            _item("PN45-24400-0900", 50000),
        ]
        got = [ln["id"] for ln in order.order_po_lines(lines)]
        assert got == [
            "d1",
            "HK02-14120-RC",
            "shared",
            "PN45-24400-0900",
            "HK10-00804-0809",
        ]

    def test_leading_comment_on_a_flat_po_stays_above_panels(self):
        rows = [
            {"line_type": "Comment", "description": "Five wall required"},
            {"item_no": "HK02-14120-RC", "description": "kit", "quantity": 1},
            {"item_no": "PN45-24400-0900", "description": "section", "quantity": 4},
            {"item_no": "GK17-10000-00", "description": "glazing", "quantity": 2},
        ]
        ordered = order.order_request_lines(rows)
        assert [row.get("item_no") or row["description"] for row in ordered] == [
            "Five wall required",
            "PN45-24400-0900",
            "GK17-10000-00",
            "HK02-14120-RC",
        ]

    def test_item_rows_sort_without_mixing_callers_dicts(self):
        rows = [
            {"item_no": "SP10-25020-01", "quantity": 2},
            {"item_no": "PN12-24300820-1602", "quantity": 1},
            {"item_no": "PN55-24400-0900", "quantity": 3},
        ]
        ordered = order.order_item_rows(rows)
        assert [row["item_no"] for row in ordered] == [
            "PN55-24400-0900",
            "PN12-24300820-1602",
            "SP10-25020-01",
        ]
        assert rows[0]["item_no"] == "SP10-25020-01"
