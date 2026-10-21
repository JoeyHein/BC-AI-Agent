"""Catalog identification for weatherstrip, and the 18-foot top-seal gate.

Weatherstrip item numbers and descriptions are taken from
backend/data/bc_analysis/bc_items.json. Rigid retainers, glazing plastics,
and in-house wrapping are not weatherstrip.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.production_schedule_service import production_schedule_service
from app.services.top_seal_policy import auto_top_seal, include_top_seal
from app.services.weatherstrip_policy import (
    KNOWN_WEATHERSTRIP_ITEMS,
    is_upwardor_vendor,
    is_weatherstrip_item,
)

_CATALOG = Path(__file__).resolve().parent.parent / "data" / "bc_analysis" / "bc_items.json"

# Rigid retainers that must stay eligible for an Upwardor PO.
_RETAINERS = {
    "PL10-00134-00",
    "PL10-00135-00",
    "PL10-00141-00",
    "PL10-00145-01",
    "PL10-00146-00",
    "PL10-00150-00",
    "PL10-00194-00",
    "PL15-00310-00",
    "PL15-00516-00",
    "AL97-35509-01",
}

# Door-package astragal. Complete rolls bought alone are a manual Elton PO.
_ASTRAGAL = {
    "PL10-00004-00",
    "PL10-00005-01",
    "PL10-00005-02",
    "PL10-00005-03",
}

# Plastics that are not seals.
_NOT_WEATHERSTRIP = {
    "PL10-00000-00",  # sealed glass polystyrene
    "PL10-00068-01",  # glazing bead
    "PL10-00071-00",  # polycarbonate moulding
    "PL10-00072-00",  # half round
    "PL10-00126-01",  # thermo pane moulding
    "WRAP",
    "WRAPALU",
    "PK11-00036-01",
}


def test_known_patterns_and_retainers():
    assert is_weatherstrip_item("PL10-08203-00", "anything")
    assert is_weatherstrip_item("pl11-22082-00", "")
    assert is_weatherstrip_item("PL10-00127-00", "")
    assert is_weatherstrip_item("MI20-00001-00", "")
    assert not is_weatherstrip_item("PL10-00004-00", 'ASTRAGAL, 3" ALUMINIUM DOOR BOTTOM RUBBER')
    assert not is_weatherstrip_item("PL10-00005-01", 'ASTRAGAL, 3" RESI/COMM/ALUM BOTTOM RUBBER')
    assert not is_weatherstrip_item("PL10-00005-02", 'ASTRAGAL, 4" RESI/COMM BOTTOM RUBBER')
    assert not is_weatherstrip_item("PL10-00005-03", 'ASTRAGAL, 6.5" COMM BOTTOM RUBBER')
    assert not is_weatherstrip_item("NEW-SKU", 'ASTRAGAL, 4" BOTTOM RUBBER')
    assert is_weatherstrip_item("NEW-SKU", "TOP SEAL RUBBER")
    assert is_weatherstrip_item("NEW-SKU", "WHITE VINYL FOR V7001 W/S")
    for item in _RETAINERS:
        assert not is_weatherstrip_item(item, ""), item
    assert not is_weatherstrip_item("PL10-00141-00", 'TOP/BOTTOM RETAINER, 1 3/4" (BOTTOM)')
    assert not is_weatherstrip_item("WRAPALU", "WRAPPING - ALUMINUM PANELS")
    assert not is_weatherstrip_item("PN45-24405-1200", "SECTION TX450")
    assert is_upwardor_vendor("UPW", "somebody else")
    assert is_upwardor_vendor("", "Upwardor Doors")
    assert not is_upwardor_vendor("ELT", "Elton Manufacturing")


def test_catalog_classification_matches_bc_items():
    items = json.loads(_CATALOG.read_text())
    weather = []
    retainers_seen = []
    for item in items:
        number = item.get("number") or ""
        desc = item.get("displayName") or ""
        if is_weatherstrip_item(number, desc):
            weather.append((number, desc))
        if number in _RETAINERS:
            retainers_seen.append(number)
            assert not is_weatherstrip_item(number, desc), (number, desc)
    numbers = {number for number, _desc in weather}
    assert KNOWN_WEATHERSTRIP_ITEMS <= numbers
    assert any(number.startswith("PL11-") for number in numbers)
    assert any(number.startswith("PL10-") and "203-" in number for number in numbers)
    assert set(retainers_seen) == _RETAINERS
    assert _ASTRAGAL.isdisjoint(numbers)
    for number in _ASTRAGAL:
        match = next(item for item in items if item.get("number") == number)
        assert not is_weatherstrip_item(number, match.get("displayName") or ""), number
    # Every catalog weatherstrip we classified is a seal, not a retainer or wrap.
    for number, desc in weather:
        upper = desc.upper()
        assert not number.upper().startswith("WRAP")
        assert "RETAINER" not in upper or "WEATHER" in upper or "SEAL" in upper
        assert "GLAZING BEAD" not in upper
        assert "MOULDING" not in upper
    for number in _NOT_WEATHERSTRIP:
        match = next((item for item in items if item.get("number") == number), None)
        if match is None:
            continue
        assert not is_weatherstrip_item(number, match.get("displayName") or ""), number


@pytest.mark.parametrize(
    "door_type,width,height,explicit,expected",
    [
        ("commercial", 216, 144, None, False),   # exactly 18' x 12'
        ("commercial", 216, 144, True, True),
        ("commercial", 217, 120, None, True),    # wider than 18' and 10' tall
        ("commercial", 240, 119, None, False),   # wide, under 10' tall
        ("commercial", 168, 120, None, False),
        ("residential", 240, 144, None, False),
        ("residential", 96, 84, True, True),
        ("aluminium", 216, 96, None, False),
        ("aluminium", 240, 96, None, True),
        ("aluminum", 240, 84, False, True),      # False does not cancel auto
        ("aluminium", 192, 96, True, True),
    ],
)
def test_top_seal_width_gate(door_type, width, height, explicit, expected):
    assert include_top_seal(door_type, width, height, explicit) is expected
    if explicit is not True:
        assert auto_top_seal(door_type, width, height) is expected


def test_weatherstrip_only_sales_order_does_not_need_an_upwardor_po():
    orders = [{
        "number": "SO-9",
        "salesOrderLines": [
            {"lineType": "Item", "lineObjectNumber": "PL10-08203-00", "quantity": 2,
             "description": "PLASTICS, WEATHER STRIP, WHITE, 8'"},
            {"lineType": "Item", "lineObjectNumber": "PL10-00127-00", "quantity": 144,
             "description": "TOP SEAL RUBBER"},
        ],
    }]
    facts = production_schedule_service.compute_so_facts(orders, {})
    assert facts["SO-9"]["order_status"] is None

    with_panel = [{
        "number": "SO-10",
        "salesOrderLines": [
            {"lineType": "Item", "lineObjectNumber": "PN45-24405-1200", "quantity": 4,
             "description": "SECTION"},
            {"lineType": "Item", "lineObjectNumber": "PL10-08203-00", "quantity": 2,
             "description": "WEATHER STRIP"},
        ],
    }]
    facts = production_schedule_service.compute_so_facts(with_panel, {})
    assert facts["SO-10"]["order_status"] == "Waiting to Order"
