"""Open Distribution does not carry 1-3/4\" ID torsion springs."""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.door_calculator_service import door_calculator
from app.services.spring_calculator_service import (
    COIL_CONVERSION_NOTE,
    SOLD_COIL_IDS,
    is_unsold_coil,
    sold_coil,
    spring_calculator,
)


def test_sold_coils_are_the_four_stocked_ids():
    assert SOLD_COIL_IDS == (2.0, 2.625, 3.75, 6.0)
    assert sold_coil(1.75) == 2.0
    assert is_unsold_coil(1.75)
    assert not is_unsold_coil(2.0)


def test_light_door_candidates_and_quote_skip_175():
    drum = door_calculator._select_drum(84, 150, {"type": "standard"}, track_size=2)
    cands = door_calculator._enumerate_spring_candidates(
        150, 84, 15, 2, 10000, drum.model, 0, door_weight_for_wires=150,
    )
    assert cands
    assert all(abs(c.coil_diameter - 1.75) > 0.02 for c in cands)
    sel = door_calculator._calculate_springs(
        150, 84, 96, drum, 10000, 15, 2, is_residential=True,
    )
    assert sel.coil_diameter == pytest.approx(2.0)
    assert all(abs(opt["coil_diameter"] - 1.75) > 0.02 for opt in sel.alternatives)


def test_pinned_175_is_calculated_as_2_inch():
    asked = spring_calculator.calculate_spring(
        150, 84, 15, 2, wire_diameter=0.192, coil_diameter=1.75,
        target_cycles=10000, drum_model="D400-96",
    )
    native = spring_calculator.calculate_spring(
        150, 84, 15, 2, wire_diameter=0.192, coil_diameter=2.0,
        target_cycles=10000, drum_model="D400-96",
    )
    assert asked is not None and native is not None
    assert asked.coil_diameter == pytest.approx(2.0)
    assert asked.length == pytest.approx(native.length, abs=0.05)


def test_existing_175_converts_to_the_same_wire_on_2_inch():
    result = spring_calculator.calculate_conversion(
        current_wire=0.250,
        current_coil=1.75,
        current_length=30,
        current_spring_qty=2,
        replacement_spring_qty=2,
        target_cycles=10000,
    )
    assert result["success"] is True
    assert result["current"]["coil_diameter"] == pytest.approx(1.75)
    repl = result["replacement"]
    assert repl["coil_diameter"] == pytest.approx(2.0)
    assert repl["wire_diameter"] == pytest.approx(0.250, abs=1e-3)
    assert result["coil_conversion_note"] == COIL_CONVERSION_NOTE
    assert all(
        abs(opt["coil_diameter"] - 1.75) > 0.02
        for opt in (result.get("all_candidates") or [])
    )


def test_spring_options_do_not_list_175():
    options = spring_calculator.calculate_spring_options(
        door_weight=200, door_height=84, track_radius=15, spring_qty=2,
        target_cycles=10000, drum_model="D400-96",
    )
    coils = [opt.coil_diameter for opt in options.options]
    assert coils
    assert all(abs(coil - 1.75) > 0.02 for coil in coils)
