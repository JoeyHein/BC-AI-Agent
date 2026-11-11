"""TX760 commercial doors quote the 3\" top/bottom retainer as a BC item.

PL10-00136-00 is TOP/BOTTOM RETAINER - 3\" (UOM IN), confirmed on the live
production item card. It was missing from the committed item export, so
generate-quote treated the number as unknown and rewrote it to another PL10
SKU or left it to post as a "not in BC" comment. Other series keep their
existing retainer numbers and the same per-inch quantity.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.api.door_configurator import catalog_keeps_part_number
from app.services.bc_part_number_mapper import BCPartNumberMapper, get_bc_mapper
from app.services.part_number_service import get_parts_for_door_config


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


class TestTx760RetainerLine:
    def test_two_priced_item_lines_at_door_width(self):
        parts = _parts(doorSeries="TX760", panelDesign="MICROGROOVE")
        retainers = _retainers(parts)
        assert [(p["part_number"], p["quantity"], p["description"]) for p in retainers] == [
            (TX760_RETAINER, 144, 'TOP/BOTTOM RETAINER - 3" (TOP)'),
            (TX760_RETAINER, 144, 'TOP/BOTTOM RETAINER - 3" (BOTTOM)'),
        ]
        assert all(p.get("lineType") != "Comment" for p in retainers)
        assert not any(
            "not in BC" in (p.get("description") or "") or "not available" in (p.get("description") or "").lower()
            for p in parts
            if "RETAINER" in (p.get("description") or "").upper()
        )

    def test_door_count_scales_both_runs(self):
        # SQ-003405 door 1: 7'10" (94") x 4. 94 * 4 = 376 inches per run.
        parts = _parts(
            doorSeries="TX760", panelDesign="MICROGROOVE",
            doorWidth=94, doorHeight=94, doorCount=4,
        )
        retainers = _retainers(parts)
        assert len(retainers) == 2
        assert {p["part_number"] for p in retainers} == {TX760_RETAINER}
        assert [p["quantity"] for p in retainers] == [376, 376]

    def test_catalog_item_is_the_live_3_inch_retainer(self):
        item = get_bc_mapper().bc_items[TX760_RETAINER]
        assert item["displayName"] == 'TOP/BOTTOM RETAINER - 3"'
        assert item["baseUnitOfMeasureCode"] == "IN"
        assert item["blocked"] is False
        assert item["type"] == "Inventory"
        assert item["unitCost"] == 0.62

    def test_stale_export_does_not_rewrite_or_comment_the_retainer(self):
        # The old check was `if pn in bc_items`. An empty export failed that
        # and the closest PL10 sibling (or a comment) replaced the line.
        assert catalog_keeps_part_number(TX760_RETAINER, {}, "retainer") is True
        assert catalog_keeps_part_number(TX760_RETAINER, {}) is True
        line = {
            "part_number": TX760_RETAINER,
            "description": 'TOP/BOTTOM RETAINER - 3" (TOP)',
            "quantity": 144,
            "category": "retainer",
        }
        assert catalog_keeps_part_number(
            line["part_number"], {}, line["category"]
        )
        assert line["part_number"] == TX760_RETAINER
        assert line.get("lineType") != "Comment"

    def test_unknown_pl10_is_still_not_trusted(self):
        assert catalog_keeps_part_number("PL10-00999-00", {}, "accessory") is False

    def test_wrap_and_hardware_kit_skips_unchanged(self):
        assert catalog_keeps_part_number("WRAP", {}, "wrapping") is True
        assert catalog_keeps_part_number("HK03-12345-00", {}, "hardware") is True
        # The -00000-RC placeholder is still not treated as a real kit.
        assert catalog_keeps_part_number("HK03-00000-RC", {}, "hardware") is False


@pytest.mark.parametrize("series,part_number,description", [
    ("TX380", "PL10-00134-00", 'TOP/BOTTOM RETAINER - 1 1/2"'),
    ("TX450", "PL10-00141-00", 'TOP/BOTTOM RETAINER, 1 3/4"'),
    ("TX450-20", "PL10-00141-00", 'TOP/BOTTOM RETAINER, 1 3/4"'),
    ("TX500", "PL10-00135-00", 'TOP/BOTTOM RETAINER 2"'),
    ("TX500-20", "PL10-00135-00", 'TOP/BOTTOM RETAINER 2"'),
])
def test_other_commercial_retainers_unchanged(series, part_number, description):
    retainers = _retainers(_parts(doorSeries=series))
    assert [(p["part_number"], p["quantity"], p["description"]) for p in retainers] == [
        (part_number, 144, f"{description} (TOP)"),
        (part_number, 144, f"{description} (BOTTOM)"),
    ]
    assert part_number in BCPartNumberMapper.COMMERCIAL_RETAINER_NUMBERS
    assert part_number in get_bc_mapper().bc_items
