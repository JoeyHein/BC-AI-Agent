"""Round 5: replacement sections sell at the item-card list price, and the
section finder resolves one stocked part or sends the request to staff.

Off mode does not set a fixed price, so a complete door and a sections-only
door both stay on the customer's price list.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.bc_part_number_mapper import get_bc_mapper
from app.services.quote_price_overrides import (
    PriceOverrideSettings,
    apply_price_overrides,
)
from app.services.section_finder import finder_options, resolve_section


DOOR_FACE = {
    "panels": True, "tracks": False, "springs": False, "struts": False,
    "hardwareKits": False, "weatherStripping": False, "bottomRetainer": True,
    "shafts": False,
}
COMPLETE = {key: True for key in DOOR_FACE}

KANATA_16_BLACK = {
    "application": "residential",
    "series": "KANATA",
    "thickness": "1-3/4",
    "gauge": "standard",
    "section_height": 21,
    "width_feet": 16,
    "width_inches": 0,
    "color": "BLACK",
    "design": "FLUSH",
    "position": "bottom",
    "windows": False,
    "quantity": 2,
}


def _list_price(part_number):
    item = get_bc_mapper().bc_items.get(part_number) or {}
    price = item.get("unitPrice")
    return float(price) if price else None


def test_doortech_panels_only_is_the_card_not_silv_or_margin():
    card = get_bc_mapper().bc_items["PN65-21005-1600"]["unitPrice"]
    assert card == 454.34
    line = {
        "part_number": "PN65-21005-1600",
        "description": "SECTION",
        "quantity": 2,
        "category": "panel",
    }
    apply_price_overrides(
        [line],
        hardware=DOOR_FACE,
        door_type="residential",
        door_series="KANATA",
        settings=PriceOverrideSettings(panel_mode="on"),
        list_lookup=lambda pn: card,
    )
    assert line["fixed_unit_price"] == 454.34
    assert line["fixed_unit_price"] != 380.96
    assert line["fixed_unit_price"] != 408.90


def test_complete_door_keeps_the_customer_price_list():
    line = {
        "part_number": "PN65-21005-1600",
        "description": "SECTION",
        "quantity": 4,
        "category": "panel",
    }
    apply_price_overrides(
        [line],
        hardware=COMPLETE,
        door_type="residential",
        door_series="KANATA",
        settings=PriceOverrideSettings(panel_mode="on"),
        list_lookup=lambda pn: 454.34,
    )
    assert "fixed_unit_price" not in line


def test_off_mode_does_not_set_a_list_price():
    line = {
        "part_number": "PN65-21005-1600",
        "quantity": 1,
        "category": "panel",
    }
    apply_price_overrides(
        [line],
        hardware=DOOR_FACE,
        door_type="residential",
        door_series="KANATA",
        settings=PriceOverrideSettings(),
        list_lookup=lambda pn: (_ for _ in ()).throw(AssertionError("lookup")),
    )
    assert "fixed_unit_price" not in line


def test_finder_resolves_the_doortech_kanata_section():
    result = resolve_section(KANATA_16_BLACK, list_price_lookup=_list_price)
    assert result["status"] == "resolved"
    assert result["part_number"] == "PN65-21005-1600"
    assert result["list_price"] == 454.34
    assert result["quantity"] == 2
    assert "FLUSH" in result["description"]


def test_finder_resolves_a_tx450_section_and_not_a_guessed_width():
    result = resolve_section({
        "application": "commercial",
        "series": "TX450",
        "thickness": "1-3/4",
        "gauge": "standard",
        "section_height": 24,
        "width_feet": 9,
        "width_inches": 0,
        "color": "WHITE",
        "design": "UDC",
        "position": "top",
        "windows": False,
        "quantity": 1,
    }, list_price_lookup=_list_price)
    assert result["status"] == "resolved"
    assert result["part_number"] == "PN45-24400-0900"
    assert result["list_price"] == 288.00

    missing = resolve_section({
        "application": "commercial",
        "series": "TX450",
        "thickness": "1-3/4",
        "gauge": "standard",
        "section_height": 24,
        "width_feet": 12,
        "width_inches": 0,
        "color": "WHITE",
        "design": "FLUSH",
        "position": "top",
        "windows": False,
        "quantity": 1,
    }, list_price_lookup=_list_price)
    assert missing["status"] == "review"
    assert missing["part_number"] is None
    assert "PN45-24000-1200" in missing["reasons"][0]


def test_finder_does_not_guess():
    unsure = resolve_section({**KANATA_16_BLACK, "series": "not sure"})
    assert unsure["status"] == "review"
    assert any("not guessed" in reason for reason in unsure["reasons"])

    windows = resolve_section({**KANATA_16_BLACK, "windows": True})
    assert windows["status"] == "review"
    assert any("glass kit" in reason for reason in windows["reasons"])

    wrong_thickness = resolve_section({**KANATA_16_BLACK, "thickness": "2"})
    assert wrong_thickness["status"] == "review"

    options = finder_options()
    series_ids = {row["id"] for row in options["series"]}
    assert "KANATA" in series_ids
    assert "TX760" in series_ids
    assert "AL976" not in series_ids
    assert not any("Executive" in row["id"] for row in options["series"])
    assert any("full-view" in gap for gap in options["gaps"])
