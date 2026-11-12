"""TX760 commercial doors quote the 3\" top/bottom retainer as a BC item.

PL10-00136-00 is TOP/BOTTOM RETAINER - 3\" (UOM IN), the only commercial
3\" retainer on the live production item card. It was missing from the
committed item export, so generate-quote treated the number as unknown and
rewrote it to another PL10 SKU or left it to post as a "not in BC" comment.
Other series keep their existing retainer numbers and the same per-inch
quantity.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.api.door_configurator import (
    catalog_keeps_part_number,
    resolve_unstocked_part_numbers,
)
from app.integrations.ai.client import ClaudeAIClient
from app.services.bc_part_number_mapper import get_bc_mapper
from app.services.part_number_service import get_parts_for_door_config
from app.services.quote_service import QuoteGenerationService


TX760_RETAINER = "PL10-00136-00"

# 12' x 10' commercial door. Quantity is the width in inches, once for the
# top run and once for the bottom run. Door count multiplies both.
_BASE = {
    "doorType": "commercial",
    "doorWidth": 144,
    "doorHeight": 120,
    "doorCount": 1,
    "panelColor": "WHITE",
    "panelDesign": "UDC",
    "hardware": {
        "struts": True, "tracks": True, "springs": True,
        "hardwareKits": True, "weatherStripping": True,
        "bottomRetainer": True, "shafts": True,
    },
    "targetCycles": 10000,
    "trackThickness": "3",
    "trackRadius": "15",
    "trackMount": "bracket",
    "liftType": "standard",
}


def _parts(**overrides):
    cfg = dict(_BASE)
    cfg.update(overrides)
    return get_parts_for_door_config(cfg).get("parts_list", [])


def _retainers(parts):
    return [p for p in parts if p.get("category") == "retainer"]


def _retainer_comments(parts):
    return [
        p for p in parts
        if "RETAINER" in (p.get("description") or "").upper()
        and (
            p.get("lineType") == "Comment"
            or p.get("category") == "comment"
            or "not available" in (p.get("description") or "").lower()
            or "not in bc" in (p.get("description") or "").lower()
        )
    ]


class TestTx760RetainerLine:
    def test_two_item_lines_at_door_width(self):
        parts = _parts(doorSeries="TX760", panelDesign="MICROGROOVE")
        retainers = _retainers(parts)
        assert [(p["part_number"], p["quantity"], p["description"]) for p in retainers] == [
            (TX760_RETAINER, 144, 'TOP/BOTTOM RETAINER - 3" (TOP)'),
            (TX760_RETAINER, 144, 'TOP/BOTTOM RETAINER - 3" (BOTTOM)'),
        ]
        assert all(p.get("lineType") != "Comment" for p in retainers)
        assert _retainer_comments(parts) == []

    def test_door_count_scales_both_runs(self):
        # 7'10" (94") quoted four times. 94 * 4 = 376 inches per run.
        parts = _parts(
            doorSeries="TX760", panelDesign="MICROGROOVE",
            doorWidth=94, doorHeight=94, doorCount=4,
        )
        retainers = _retainers(parts)
        assert len(retainers) == 2
        assert {p["part_number"] for p in retainers} == {TX760_RETAINER}
        assert [p["quantity"] for p in retainers] == [376, 376]
        assert _retainer_comments(parts) == []

    def test_catalog_item_is_the_3_inch_retainer(self):
        item = get_bc_mapper().bc_items[TX760_RETAINER]
        assert item["displayName"] == 'TOP/BOTTOM RETAINER - 3"'
        assert item["baseUnitOfMeasureCode"] == "IN"
        assert item["blocked"] is False
        assert item["type"] == "Inventory"
        assert item["unitCost"] == 0.62
        assert item["unitPrice"] == 1.24

    def test_stale_export_does_not_rewrite_or_comment_the_retainer(self):
        """The old export had every other PL10 and not this one, so the
        closest-length sibling (often PL10-00000-00) replaced the retainer
        or the post fell through to a not-available comment."""
        stale = {
            "PL10-00000-00": {"number": "PL10-00000-00", "displayName": "POLYSTYRENE"},
            "PL10-00141-00": {"number": "PL10-00141-00", "displayName": 'TOP/BOTTOM RETAINER, 1 3/4"'},
        }
        lines = [{
            "part_number": TX760_RETAINER,
            "description": 'TOP/BOTTOM RETAINER - 3" (BOTTOM)',
            "quantity": 144,
            "category": "retainer",
        }]
        warnings = resolve_unstocked_part_numbers(lines, stale)
        assert warnings == []
        assert lines[0]["part_number"] == TX760_RETAINER
        assert lines[0].get("lineType") != "Comment"
        assert catalog_keeps_part_number(TX760_RETAINER, {}, "retainer") is True

    def test_unknown_pl10_is_still_rewritten(self):
        stale = {
            "PL10-00000-00": {"number": "PL10-00000-00", "displayName": "POLYSTYRENE"},
        }
        lines = [{
            "part_number": "PL10-00999-00",
            "description": "UNKNOWN PLASTIC",
            "quantity": 1,
            "category": "accessory",
        }]
        warnings = resolve_unstocked_part_numbers(lines, stale)
        assert warnings and warnings[0]["substituted"] == "PL10-00000-00"
        assert lines[0]["part_number"] == "PL10-00000-00"
        assert catalog_keeps_part_number("PL10-00999-00", {}, "accessory") is False

    def test_wrap_and_hardware_kit_skips_unchanged(self):
        assert catalog_keeps_part_number("WRAP", {}, "wrapping") is True
        assert catalog_keeps_part_number("HK03-08080-RC", {}, "hardware") is True
        assert catalog_keeps_part_number("HK03-00000-RC", {}, "hardware") is False


@pytest.mark.parametrize("series,part_number,description", [
    ("TX380", "PL10-00134-00", 'TOP/BOTTOM RETAINER - 1 1/2"'),
    ("TX450", "PL10-00141-00", 'TOP/BOTTOM RETAINER, 1 3/4"'),
    ("TX450-20", "PL10-00141-00", 'TOP/BOTTOM RETAINER, 1 3/4"'),
    ("TX500", "PL10-00135-00", 'TOP/BOTTOM RETAINER 2"'),
    ("TX500-20", "PL10-00135-00", 'TOP/BOTTOM RETAINER 2"'),
])
def test_other_commercial_retainers_unchanged(series, part_number, description):
    design = "FLUSH" if series.endswith("-20") else "UDC"
    retainers = _retainers(_parts(doorSeries=series, panelDesign=design))
    assert [(p["part_number"], p["quantity"], p["description"]) for p in retainers] == [
        (part_number, 144, f"{description} (TOP)"),
        (part_number, 144, f"{description} (BOTTOM)"),
    ]
    assert _retainer_comments(_parts(doorSeries=series, panelDesign=design)) == []


def test_email_normalizer_keeps_tx760():
    out = ClaudeAIClient._normalize_configurator_doors([{
        "doorType": "commercial",
        "doorSeries": "TX760",
        "doorWidth": 144,
        "doorHeight": 120,
        "panelDesign": "FLUSH",
    }])
    assert out[0]["doorSeries"] == "TX760"
    assert out[0]["panelDesign"] == "MICROGROOVE"
    # A series the mapper does not know still falls back to TX450.
    other = ClaudeAIClient._normalize_configurator_doors([{
        "doorType": "commercial",
        "doorSeries": "TX999",
        "doorWidth": 144,
        "doorHeight": 120,
    }])
    assert other[0]["doorSeries"] == "TX450"


def test_legacy_quote_service_maps_tx760_to_the_retainer_item():
    assert QuoteGenerationService._map_model_to_series(None, "TX760") == "TX760"
    assert QuoteGenerationService._determine_door_type(None, "TX760", 96, 84) == "commercial"
    assert QuoteGenerationService._map_model_to_series(None, "TX450") == "TX450"
    assert QuoteGenerationService._determine_door_type(None, "TX450", 96, 84) == "commercial"
