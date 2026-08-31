"""'Generate anyway' force path — unresolved section/panel becomes a MANUAL
ENTRY comment line instead of aborting the whole BC quote.

Covers the pure helper `_flag_unresolved_line_as_comment`. The force flag only
changes the `is_panel_like` "no larger size" abort; it must NOT bypass
`validate_panel_combo` (unstocked color/stamp/series stays a hard block — that
case is covered by test_series_constraints.py).
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from app.api.door_configurator import (
    _flag_unresolved_line_as_comment,
    QuoteGenerationRequest,
    validate_panel_combo,
)


def test_flag_unresolved_line_mutates_to_comment():
    line = {
        "lineType": "Item",
        "part_number": "PN10-24600345-2402",
        "description": "V130G FULL VIEW SECTION",
        "quantity": 1,
        "door_index": 2,
        "category": "v130g_section",
    }
    warning = _flag_unresolved_line_as_comment(
        line, "PN10-24600345-2402",
        "not stocked in BC and no larger size available",
    )

    assert line["lineType"] == "Comment"
    assert line["_unresolved"] is True
    assert line["description"].startswith("** MANUAL ENTRY REQUIRED - Door 2:")
    assert "PN10-24600345-2402" in line["description"]
    assert "Qty 1" in line["description"]

    assert warning["manual_entry_required"] is True
    assert warning["substituted"] is None
    assert warning["original"] == "PN10-24600345-2402"


def test_flag_unresolved_line_handles_missing_fields():
    line = {"lineType": "Item", "part_number": "PN97-16000352-1602"}
    warning = _flag_unresolved_line_as_comment(line, "PN97-16000352-1602", "no SKU")
    assert line["lineType"] == "Comment"
    assert "Door ?" in line["description"]
    assert warning["manual_entry_required"] is True


def test_force_generate_defaults_off():
    req = QuoteGenerationRequest(doors=[])
    assert req.forceGenerate is False


def test_force_does_not_bypass_panel_combo_guard():
    # Force is about catalog gaps, not "we don't build that" — the combo
    # validator is unchanged and still raises.
    with pytest.raises(ValueError):
        validate_panel_combo("TX500", "STEEL_GREY", "UDC")
