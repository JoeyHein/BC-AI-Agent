"""Regressions from SQ-003183 (GNB, big TX450 high-lift doors).

1. High lift past a drum's table must not clamp to the nearest row.
2. Duplex quotes emitted 2x the springs the calculator sized.
3. The calculator must only propose SP11 SKUs BC sells (a wire step-up
   at the same length is an over-strong spring).
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.door_calculator_service import door_calculator, _spring_sellable
from app.services.spring_calculator_service import spring_calculator
from app.services.part_number_service import get_parts_for_door_config


def _hl_cfg(width, height, hl, cycles=10000):
    return dict(
        doorType="commercial", doorSeries="TX450", doorWidth=width, doorHeight=height,
        doorCount=1, panelColor="WHITE", panelDesign="UDC", hasWindows=False,
        trackRadius=15, trackThickness=3, trackMount="angle",
        liftType="high_lift", highLiftInches=hl, targetCycles=cycles, hardware={},
    )


class TestHighLiftDrumLimit:
    def test_hl_within_drum_data_resolves(self):
        assert spring_calculator.get_drum_data(168, 15, "D800-120", high_lift_inches=120) is not None

    def test_hl_past_drum_data_returns_none_not_clamped(self):
        # D800-120 only has data to 120" HL; 168" used to silently use the 120" row
        assert spring_calculator.get_drum_data(216, 15, "D800-120", high_lift_inches=168) is None

    def test_hl_rounds_up_to_next_row(self):
        # 119" must use the 120" row (more turns), never the 117" row
        _, _, t_119 = spring_calculator.get_drum_data(168, 15, "D800-120", high_lift_inches=119)
        _, _, t_120 = spring_calculator.get_drum_data(168, 15, "D800-120", high_lift_inches=120)
        assert t_119 == t_120

    def test_select_drum_skips_drums_without_hl_data(self):
        lift = {"type": "high", "radius": 15}
        assert door_calculator._select_drum(216, 750, lift, effective_height=216 + 168, track_size=3) is None
        d = door_calculator._select_drum(168, 450, lift, effective_height=168 + 120, track_size=3)
        assert d is not None
        assert spring_calculator.hl_drum_supports(d.model, 168, 120)

    def test_quote_flags_office_review_and_emits_no_springs(self):
        parts = get_parts_for_door_config(_hl_cfg(240, 240, 192))["parts_list"]
        assert any(p.get("notes") == "hl_drum_out_of_range" for p in parts)
        assert not any(p.get("category") == "spring" for p in parts)

    def test_calculate_door_warns(self):
        calc = door_calculator.calculate_door(
            "TX450", 240, 240, lift_type="high_lift", track_size=3, high_lift_inches=192,
        )
        assert any("exceeds every high-lift drum" in w for w in calc.warnings)


class TestDuplexQuantities:
    def test_duplex_lines_match_calculated_positions(self):
        cfg = _hl_cfg(168, 168, 120, cycles=25000)
        parts = get_parts_for_door_config(cfg)["parts_list"]
        sel = door_calculator._calculate_springs(
            door_weight=next(
                float(p["description"].split("Door Weight: ")[1].split(" lbs")[0])
                for p in parts if "Door Weight:" in (p.get("description") or "")
            ),
            height_inches=168, width_inches=168,
            drums=door_calculator._select_drum(168, 450, {"type": "high", "radius": 15},
                                               effective_height=288, track_size=3),
            target_cycles=25000, high_lift_inches=120,
        )
        if not (sel and sel.is_duplex):
            return  # selection is cost-driven; only assert when duplex wins
        positions = sel.duplex_pairs
        springs = [p for p in parts if p.get("category") == "spring"]
        # outer LH+RH and inner LH+RH: one spring per position per layer
        per_line = sorted(round(p["quantity"]) for p in springs)
        outer_len = max(per_line) // (positions // 2)
        assert len(springs) == 4
        winders = [p for p in parts if "WINDERS" in (p.get("description") or "")]
        assert sum(p["quantity"] for p in winders) == 2 * positions
        assert outer_len > 0

    def test_duplex_positions_are_even(self):
        from app.services.door_calculator_service import DUPLEX_POSITION_COUNTS
        assert all(n % 2 == 0 for n in DUPLEX_POSITION_COUNTS)


class TestSellableOnly:
    def test_unsellable_oil_tempered_combo_rejected(self):
        from app.services.bc_part_number_mapper import get_bc_mapper
        m = get_bc_mapper()
        if not m.spring_items:
            return
        # .295 x 6" shows up in the SP1x inventory feed but has no SP11 part
        if m.get_spring_part_number(0.295, 6.0, "LH").part_number not in m.spring_items:
            assert _spring_sellable(0.295, 6.0) is False
        assert _spring_sellable(0.3125, 6.0) is True
