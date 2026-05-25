"""Series-specific color/design constraints (TX500 / 20-gauge).

BC stocks TX500 (PN55/56) in White/Black only, and 20-gauge (TX450-20/TX500-20,
PN47/48/57/58) in White + Flush only (no UDC). The configurator must offer only
those, and the quote path must reject unstocked combos with a clear message
instead of a cryptic "panel not found in BC".
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from app.api.door_configurator import (
    validate_panel_combo, COLORS, PANEL_DESIGNS,
    SERIES_COLOR_KEY, SERIES_DESIGN_KEY,
)


def _ids(lst):
    return {x["id"] for x in lst}


# ── offered option lists ────────────────────────────────────────────────────

def test_tx500_colors_white_black_only():
    assert _ids(COLORS["COMMERCIAL_TX500"]) == {"WHITE", "BLACK"}

def test_twenty_gauge_colors_white_only():
    assert _ids(COLORS["COMMERCIAL_20"]) == {"WHITE"}

def test_twenty_gauge_designs_flush_only_no_udc():
    assert _ids(PANEL_DESIGNS["COMMERCIAL_20"]) == {"FLUSH"}

def test_series_maps_point_at_constrained_lists():
    assert SERIES_COLOR_KEY["TX500"] == "COMMERCIAL_TX500"
    assert SERIES_COLOR_KEY["TX450-20"] == "COMMERCIAL_20"
    assert SERIES_COLOR_KEY["TX500-20"] == "COMMERCIAL_20"
    assert SERIES_DESIGN_KEY["TX500-20"] == "COMMERCIAL_20"


# ── validator: rejects the combos that failed the GNB test run ──────────────

def test_tx500_steel_grey_rejected():
    with pytest.raises(ValueError, match="not available in 'STEEL_GREY'"):
        validate_panel_combo("TX500", "STEEL_GREY", "UDC")

def test_tx500_20_udc_rejected():
    with pytest.raises(ValueError, match="design 'UDC'"):
        validate_panel_combo("TX500-20", "WHITE", "UDC")

def test_tx450_20_non_white_rejected():
    with pytest.raises(ValueError, match="not available in 'BLACK'"):
        validate_panel_combo("TX450-20", "BLACK", "FLUSH")


# ── validator: allows the valid combos ──────────────────────────────────────

@pytest.mark.parametrize("series,color,design", [
    ("TX500", "WHITE", "UDC"),
    ("TX500", "BLACK", "UDC"),
    ("TX500-20", "WHITE", "FLUSH"),
    ("TX450-20", "WHITE", "FLUSH"),
    ("TX450", "STEEL_GREY", "UDC"),   # TX450 genuinely stocks steel grey
    ("TX450", "WHITE", "UDC"),
])
def test_valid_combos_pass(series, color, design):
    validate_panel_combo(series, color, design)  # must not raise


def test_non_commercial_series_pass_through():
    # Residential / aluminum are not hard-validated here.
    validate_panel_combo("KANATA", "WALNUT", "SHXL")
    validate_panel_combo("AL976", "CLEAR_ANODIZED", None)
