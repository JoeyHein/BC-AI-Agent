"""Craft Series stocked-size validation (fail fast, not at Get Pricing).

Source of truth: DOOR_SERIES["residential"] CRAFT specs in
backend/app/api/door_configurator.py, matching
docs/UPWARDOR_PORTAL_CONFIGURATION.md:

  Widths:  8', 9', 12', 16'  (96", 108", 144", 192")
  Heights: 7', 8'            (84", 96")  — 3×28" or 3×32" sections

Kanata / TX450 stay range-limited (max width/height), not discrete lists.
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from fastapi import HTTPException

from app.api.door_configurator import (
    collect_dimension_validation,
    validate_door_dimensions,
    find_door_series,
    DOOR_SERIES,
)
from app.api.customer_portal import _validate_doors_config


CRAFT_WIDTHS = [96, 108, 144, 192]
CRAFT_HEIGHTS = [84, 96]


def _craft_door(width, height):
    return {
        "doorType": "residential",
        "doorSeries": "CRAFT",
        "doorWidth": width,
        "doorHeight": height,
    }


# ── catalog ─────────────────────────────────────────────────────────────────

def test_craft_stocked_sizes_match_brochure():
    craft = find_door_series("CRAFT", "residential")
    assert craft is not None
    assert craft["specs"]["availableWidths"] == CRAFT_WIDTHS
    assert craft["specs"]["availableHeights"] == CRAFT_HEIGHTS


def test_kanata_and_tx450_do_not_use_discrete_width_lists():
    # Don't tighten other series to Craft's fixed sizes.
    kanata = find_door_series("KANATA")
    tx450 = find_door_series("TX450")
    assert "availableWidths" not in kanata["specs"]
    assert "availableHeights" not in kanata["specs"]
    assert "availableWidths" not in tx450["specs"]
    assert "availableHeights" not in tx450["specs"]


# ── valid Craft sizes still proceed ─────────────────────────────────────────

@pytest.mark.parametrize("width,height", [
    (96, 84), (108, 84), (144, 84), (192, 84),
    (96, 96), (108, 96), (144, 96), (192, 96),
])
def test_valid_craft_size_has_no_errors(width, height):
    errors, warnings = collect_dimension_validation(
        "residential", "CRAFT", width, height
    )
    assert errors == []
    assert warnings == []
    validate_door_dimensions("residential", "CRAFT", width, height)  # must not raise
    doors = _validate_doors_config({"doors": [_craft_door(width, height)]})
    assert doors[0]["doorWidth"] == width


# ── invalid Craft size fails immediately ────────────────────────────────────

def test_invalid_craft_width_errors_before_pricing():
    errors, warnings = collect_dimension_validation(
        "residential", "CRAFT", 120, 84  # 10' × 7' — Kanata-legal, not Craft
    )
    assert warnings == []
    assert len(errors) == 1
    assert "not available in width 10'0\"" in errors[0]
    assert "8'0\"" in errors[0]
    assert "9'0\"" in errors[0]
    assert "12'0\"" in errors[0]
    assert "16'0\"" in errors[0]


def test_invalid_craft_height_errors_before_pricing():
    errors, _ = collect_dimension_validation(
        "residential", "CRAFT", 96, 72  # 8' × 6' — under maxHeight, not stocked
    )
    assert any("not available in height 6'0\"" in e for e in errors)
    assert "7'0\"" in errors[0]
    assert "8'0\"" in errors[0]


def test_craft_height_above_max_uses_stocked_list_message():
    errors, _ = collect_dimension_validation("residential", "CRAFT", 96, 108)
    assert any("not available in height 9'0\"" in e for e in errors)
    # Discrete list is the user-facing message, not the generic maxHeight line.
    assert not any("exceeds maximum" in e for e in errors)


def test_validate_door_dimensions_raises_on_invalid_craft():
    with pytest.raises(ValueError, match="not available in width 10'0"):
        validate_door_dimensions("residential", "CRAFT", 120, 84)


def test_customer_portal_rejects_invalid_craft_and_accepts_valid():
    with pytest.raises(HTTPException) as ei:
        _validate_doors_config({"doors": [_craft_door(120, 84)]})
    assert ei.value.status_code == 400
    assert "Door 1:" in ei.value.detail
    assert "not available in width 10'0\"" in ei.value.detail

    doors = _validate_doors_config({"doors": [_craft_door(144, 96)]})
    assert doors[0]["doorSeries"] == "CRAFT"


def test_unstocked_craft_width_is_error_not_warning():
    # Regression: /validate used to warn "Non-standard width" and still
    # let Get Pricing hit BC SKU lookup.
    errors, warnings = collect_dimension_validation(
        "residential", "CRAFT", 168, 84  # 14'
    )
    assert errors
    assert not any("Non-standard width" in w for w in warnings)


# ── other series unchanged ──────────────────────────────────────────────────

def test_kanata_custom_width_still_allowed():
    errors, _ = collect_dimension_validation(
        "residential", "KANATA", 120, 84  # 10' — not a Craft size
    )
    assert errors == []


def test_tx450_custom_size_still_allowed():
    errors, _ = collect_dimension_validation(
        "commercial", "TX450", 120, 108
    )
    assert errors == []


def test_kanata_over_max_width_still_errors():
    errors, _ = collect_dimension_validation(
        "residential", "KANATA", 240, 84  # 20' > 18' max
    )
    assert any("exceeds maximum" in e for e in errors)


def test_full_config_exposes_craft_available_sizes():
    residential = DOOR_SERIES["residential"]
    craft = next(s for s in residential if s["id"] == "CRAFT")
    assert craft["specs"]["availableWidths"] == CRAFT_WIDTHS
    assert craft["specs"]["availableHeights"] == CRAFT_HEIGHTS
