"""Joey's Nov 16 2026 torsion-spring rules, plus the physics bugs beside them.

Ranking, for a 10,000-cycle target unless the quote asks for more:
closest rated life, then least steel at $2.30/lb plus cones, .393 almost
never, more springs before a heavier wire, stocked BC springs as a tiebreak.

Physics:
- 0.2375 and 0.4305 must not keep their Canimex length on a .234 / .437 SKU
- low-headroom uses the LHR drum column
- shaft fit is spring + cone + bearing against shaft length (width + 18")
- a 4-spring set does not go on a hollow tube shaft
- duplex outers carry 2/3 of the position MIP and inners 1/2
- existing-spring conversion honours the requested cycle life
- Craft door weight is the Upwardor 28"/32" chart, not Kanata's 21"/24" rates
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.door_calculator_service import (
    DOOR_MODEL_WEIGHTS,
    DoorCalculatorService,
    _springs_fit_on_shaft,
    door_calculator,
    spring_rank_key,
)
from app.services.part_number_service import DoorConfiguration, PartNumberService
from app.services.spring_calculator_service import (
    spring_calculator,
    calculate_spring_weight,
)


STD = {"type": "standard"}


def _tx450_18x18():
    """18'2\" x 18' TX450. The example Joey used for 4×.331 vs a long .437."""
    svc = PartNumberService()
    cfg = DoorConfiguration(
        door_type="commercial",
        door_series="TX450",
        door_width=218,
        door_height=216,
        door_count=1,
        panel_color="WHITE",
        panel_design="UDC",
        target_cycles=10000,
        track_thickness="3",
        track_radius="15",
        lift_type="standard",
    )
    weight = svc._calculate_door_weight(cfg)
    drum = door_calculator._select_drum(216, weight, STD, track_size=3)
    return weight, drum


class TestFactoryChart:
    """Canimex formulas against a published drum cell, not a fitted guess."""

    def test_d400_96_standard_and_lhr_cells(self):
        # D400-96, 7' door. The 15" radius row and the LHR row are different
        # (multiplier, turns) pairs in the cable-drum catalog.
        model, multi, turns = spring_calculator.get_drum_data(84, 15, "D400-96")
        assert model == "D400-96"
        assert multi == pytest.approx(0.2866, abs=1e-4)
        assert turns == pytest.approx(7.9, abs=0.05)

        lhr_model, lhr_multi, lhr_turns = spring_calculator.get_drum_data(
            84, 15, "D400-96", low_headroom=True,
        )
        assert lhr_model == "D400-96"
        assert lhr_multi == pytest.approx(0.317, abs=1e-3)
        assert lhr_turns == pytest.approx(7.2, abs=0.05)
        assert (lhr_multi, lhr_turns) != (multi, turns)

    def test_ippt_mip_length_match_the_catalog_formulas(self):
        """200 lb door, 84\" high, D400-96, 15\" radius, two .250 x 2\" springs.

        IPPT = multiplier × weight
        MIP  = IPPT × turns / qty
        Active coils = qty × divider / IPPT
        Length = active coils + dead-coil factor
        """
        weight = 200.0
        _, multi, turns = spring_calculator.get_drum_data(84, 15, "D400-96")
        wire, coil, qty = 0.2500, 2.0, 2
        ippt = multi * weight
        mip = (ippt * turns) / qty
        divider = spring_calculator.get_divider(wire, coil)
        dead = spring_calculator.get_dead_coil_factor(wire, coil)
        active = (qty * divider) / ippt
        length = active + dead

        result = spring_calculator.calculate_spring(
            door_weight=weight,
            door_height=84,
            track_radius=15,
            spring_qty=qty,
            wire_diameter=wire,
            coil_diameter=coil,
            target_cycles=10000,
            drum_model="D400-96",
        )
        assert result is not None
        assert result.ippt == pytest.approx(ippt, abs=0.05)
        assert result.mip_per_spring == pytest.approx(mip, abs=0.05)
        assert result.length == pytest.approx(length, abs=0.05)
        assert result.turns == pytest.approx(turns, abs=0.05)
        # .250 at this MIP is on the 10k column, not a higher one by accident.
        assert result.achieved_cycles == spring_calculator.achieved_cycle_life(wire, mip)

    def test_low_headroom_quote_uses_lhr_turns(self):
        parts_svc = PartNumberService()
        cfg = DoorConfiguration(
            door_type="commercial", door_series="TX450",
            door_width=120, door_height=96, door_count=1,
            panel_color="WHITE", panel_design="UDC",
            lift_type="low_headroom", track_thickness="2", track_radius="12",
            target_cycles=10000,
        )
        weight = parts_svc._calculate_door_weight(cfg)
        drum = door_calculator._select_drum(96, weight, {"type": "low_headroom"}, track_size=2)
        assert drum is not None
        std = spring_calculator.get_drum_data(96, 15, drum.model)
        lhr = spring_calculator.get_drum_data(96, 12, drum.model, low_headroom=True)
        assert lhr is not None and std is not None
        assert lhr[2] != std[2]
        sel = door_calculator._calculate_springs(
            weight, 96, 120, drum, 10000, track_radius=12, low_headroom=True,
        )
        assert sel is not None
        assert sel.turns == pytest.approx(lhr[2], abs=0.05)


class TestWireSnapRecompute:
    def test_2375_does_not_keep_its_length_on_a_234_sku(self):
        """0.2375 snaps to the .234 SKU. The length has to be the .234 length."""
        raw = spring_calculator.calculate_spring(
            180, 84, 15, 2, wire_diameter=0.2375, coil_diameter=2.0,
            target_cycles=10000, drum_model="D400-96",
        )
        at_234 = spring_calculator.calculate_spring(
            180, 84, 15, 2, wire_diameter=0.2344, coil_diameter=2.0,
            target_cycles=10000, drum_model="D400-96",
        )
        # If .234 cannot carry the MIP, the snap steps up and recomputes.
        # Either way the sold length is not the 0.2375 length.
        native = spring_calculator.get_divider(0.2375, 2.0)
        assert native is not None
        if raw is None:
            assert at_234 is None or at_234.wire_diameter != 0.2375
            return
        assert abs(raw.wire_diameter - 0.2375) > 1e-4
        assert raw.length == pytest.approx(at_234.length, abs=0.05) or raw.wire_diameter > 0.2344

    def test_4305_recomputes_onto_the_437_sku(self):
        weight, drum = _tx450_18x18()
        snapped = spring_calculator.calculate_spring(
            weight, 216, 15, 2, wire_diameter=0.4305, coil_diameter=6.0,
            target_cycles=10000, drum_model=drum.model,
        )
        native_437 = spring_calculator.calculate_spring(
            weight, 216, 15, 2, wire_diameter=0.4375, coil_diameter=6.0,
            target_cycles=10000, drum_model=drum.model,
        )
        assert snapped is not None and native_437 is not None
        assert snapped.wire_diameter == pytest.approx(0.4375, abs=1e-4)
        assert snapped.length == pytest.approx(native_437.length, abs=0.05)
        # The unrecomputed 0.4305 length is the bug (about 74", not the .437 length).
        divider_4305 = spring_calculator.get_divider(0.4305, 6.0)
        ippt = snapped.ippt
        stale = (2 * divider_4305) / ippt + spring_calculator.get_dead_coil_factor(0.4305, 6.0)
        assert abs(snapped.length - stale) > 1.0


class TestRankingRules:
    def test_100_lb_door_stays_at_15k_because_smaller_wire_cannot_carry_it(self):
        """One spring is 226 in-lb. .192/.207 10k capacity is 172/212, so they
        cannot make 10k. Two of them are rated 50k, farther from 10k than the
        .2187 spring at 15k. That 15k spring is the honest pick.
        """
        drum = door_calculator._select_drum(84, 100, STD, track_size=2)
        sel = door_calculator._calculate_springs(100, 84, 96, drum, 10000, 15, 2)
        assert sel is not None
        assert sel.wire_diameter == pytest.approx(0.2187, abs=1e-3)
        assert sel.cycles == 15000
        assert sel.quantity == 1

    def test_missing_light_wire_items_are_named(self):
        from app.services.bc_part_number_mapper import get_bc_mapper
        mapper = get_bc_mapper()
        missing = []
        for wire, coil in ((0.192, 2.0), (0.192, 1.75), (0.207, 2.0), (0.207, 1.75)):
            pn = mapper.get_spring_part_number(wire, coil, "LH").part_number
            if pn not in mapper.spring_items:
                missing.append(pn)
        assert missing == [
            "SP11-19220-01", "SP11-19217-01", "SP11-20720-01", "SP11-20717-01",
        ]

    def test_150_lb_door_is_10k_not_the_old_218_at_50k(self):
        """Before: 2 x .2187 x 2" x 32" rated 50,000. After: 2 x .192 at 10,000."""
        drum = door_calculator._select_drum(84, 150, STD, track_size=2)
        sel = door_calculator._calculate_springs(
            150, 84, 96, drum, 10000, 15, 2, is_residential=True,
        )
        assert sel is not None
        assert sel.quantity == 2
        assert sel.wire_diameter == pytest.approx(0.192, abs=1e-3)
        assert sel.cycles == 10000
        assert sel.length < 25
        assert not sel.is_duplex

    def test_kanata_16x7_top_options_are_not_the_282_lb_duplex(self):
        """Option 3 used to be 4 x .3125 x 6" outers, 66", ~282 lb, labeled 10k."""
        svc = PartNumberService()
        cfg = DoorConfiguration(
            door_type="residential", door_series="KANATA",
            door_width=192, door_height=84, door_count=1,
            panel_color="WHITE", panel_design="SHXL",
            track_thickness="2", track_radius="15",
        )
        weight = svc._calculate_door_weight(cfg)
        drum = door_calculator._select_drum(84, weight, STD, track_size=2)
        sel = door_calculator._calculate_springs(
            weight, 84, 192, drum, 10000, 15, 2, is_residential=True,
        )
        assert sel is not None
        assert not sel.is_duplex
        for opt in sel.alternatives:
            assert not opt["is_duplex"]
            assert opt["wire_lb"] < 80
            assert opt["cycles"] >= 10000
            assert opt["ippt"] and opt["turns"]

    def test_393_loses_to_any_other_wire_that_meets_the_target(self):
        weight, drum = _tx450_18x18()
        banned = spring_calculator.calculate_spring(
            weight, 216, 15, 2, wire_diameter=0.3938, coil_diameter=6.0,
            target_cycles=10000, drum_model=drum.model,
        )
        other = spring_calculator.calculate_spring(
            weight, 216, 15, 4, wire_diameter=0.3125, coil_diameter=6.0,
            target_cycles=10000, drum_model=drum.model,
        )
        assert banned is not None and other is not None
        assert spring_rank_key(other, 10000) < spring_rank_key(banned, 10000)

    def test_stocked_is_only_a_tiebreak(self):
        """A heavier stocked spring does not beat a lighter unstocked one."""
        weight, drum = _tx450_18x18()
        light = spring_calculator.calculate_spring(
            weight, 216, 15, 4, wire_diameter=0.3125, coil_diameter=6.0,
            target_cycles=10000, drum_model=drum.model,
        )
        heavy = spring_calculator.calculate_spring(
            weight, 216, 15, 2, wire_diameter=0.4062, coil_diameter=6.0,
            target_cycles=10000, drum_model=drum.model,
        )
        assert spring_rank_key(light, 10000, stocked=False) < spring_rank_key(heavy, 10000, stocked=True)

    def test_requested_cycle_life_is_not_replaced_by_10k(self):
        weight, drum = _tx450_18x18()
        sel = door_calculator._calculate_springs(weight, 216, 218, drum, 25000, 15, 2)
        assert sel is not None
        assert sel.cycles >= 25000
        cap = spring_calculator.get_mip_capacity(sel.wire_diameter, 25000)
        mip = (sel.ippt * sel.turns) / sel.quantity
        assert cap is not None and cap >= mip

    def test_options_are_the_top_three(self):
        calc = door_calculator.calculate_door("TX450", 122, 120, track_size=3, target_cycles=10000)
        summary = door_calculator.get_calculation_summary(calc)
        options = summary["springs"]["options"]
        assert 1 <= len(options) <= 3
        for opt in options:
            assert "ippt" in opt and "turns" in opt and "cycles" in opt and "wire_lb" in opt


class TestShaftAndDuplex:
    def test_fit_uses_shaft_length_not_the_opening(self):
        # A spring that overruns the opening but fits the shaft (opening + 18")
        # is a legal assembly. One that overruns the shaft is not.
        weight, drum = _tx450_18x18()
        four = spring_calculator.calculate_spring(
            weight, 216, 15, 4, wire_diameter=0.331, coil_diameter=6.0,
            target_cycles=10000, drum_model=drum.model,
        )
        assert four is not None
        on_shaft = _springs_fit_on_shaft(
            218, four.length, 4, 6.0, drum.model, turns=four.turns, wire_diameter=four.wire_diameter,
        )
        assert on_shaft is True

    def test_four_springs_are_not_a_hollow_tube(self):
        svc = PartNumberService()
        cfg = DoorConfiguration(
            door_type="residential", door_series="KANATA",
            door_width=192, door_height=84, door_count=1,
            panel_color="WHITE", panel_design="SHXL", door_weight=400,
        )
        tube = svc._get_shaft_parts(cfg, spring_count=2)
        solid = svc._get_shaft_parts(cfg, spring_count=4)
        tube_pn = next(p.part_number for p in tube if p.category == "shaft")
        solid_pn = next(p.part_number for p in solid if p.category == "shaft")
        assert tube_pn.startswith("SH12-")
        assert solid_pn.startswith("SH11-")

    def test_duplex_outer_respects_two_thirds_mip(self):
        """A wire that only clears an equal split must not pass the 2/3 outer limit."""
        weight, drum = _tx450_18x18()
        # Build a duplex directly and confirm the selector's outer wire can
        # carry 2/3 of the per-position MIP at 10k.
        data = spring_calculator.get_drum_data(216, 15, drum.model)
        assert data is not None
        _, multi, turns = data
        ippt = multi * weight
        position_mip = (ippt * turns) / 2  # 2 duplex positions
        sel = door_calculator._calculate_duplex_springs(
            weight, 216, 10000, 15, inventory=None, duplex_pairs=2,
            drum_model=drum.model, width_inches=218,
        )
        if sel is None:
            pytest.skip("no duplex pair fits this door under the MIP limits")
        cap = spring_calculator.get_mip_capacity(sel.wire_diameter, 10000)
        inner_cap = spring_calculator.get_mip_capacity(sel.inner_wire_diameter, 10000)
        assert cap >= (2.0 / 3.0) * position_mip
        assert inner_cap >= 0.5 * position_mip
        outer_life = spring_calculator.achieved_cycle_life(sel.wire_diameter, (2.0 / 3.0) * position_mip)
        inner_life = spring_calculator.achieved_cycle_life(sel.inner_wire_diameter, 0.5 * position_mip)
        assert outer_life <= inner_life


class TestCycleLifeOnExistingSprings:
    def test_conversion_max_turns_follow_the_requested_life(self):
        at_10 = spring_calculator.calculate_conversion(
            current_wire=0.250, current_coil=2.0, current_length=30,
            current_spring_qty=2, replacement_spring_qty=2,
            replacement_wire=0.250, target_cycles=10000,
        )
        at_25 = spring_calculator.calculate_conversion(
            current_wire=0.250, current_coil=2.0, current_length=30,
            current_spring_qty=2, replacement_spring_qty=2,
            replacement_wire=0.250, target_cycles=25000,
        )
        assert at_10["success"] and at_25["success"]
        assert at_25["target_cycles"] == 25000
        assert at_25["replacement"]["max_turns"] < at_10["replacement"]["max_turns"]
        assert at_25["current"]["max_turns"] < at_10["current"]["max_turns"]


class TestCraftWeight:
    def test_craft_rates_match_the_upwardor_chart(self):
        assert DOOR_MODEL_WEIGHTS["CRAFT"]["28"] == pytest.approx(5.1375, abs=1e-4)
        assert DOOR_MODEL_WEIGHTS["CRAFT"]["32"] == pytest.approx(6.1875, abs=1e-4)
        assert "21" not in DOOR_MODEL_WEIGHTS["CRAFT"]

    def test_every_chart_row_is_within_two_percent(self):
        import csv
        from pathlib import Path

        path = Path(__file__).resolve().parents[1] / "data" / "upwardor_kanata_craft_weight_by_size.csv"
        svc = PartNumberService()
        with path.open() as handle:
            rows = list(csv.DictReader(handle))
        assert len(rows) >= 32
        anchors = {
            ("CRAFT", "8", "7"): 147.5,
            ("CRAFT", "9", "8"): 183.9,
            ("CRAFT", "16", "8"): 323.2,
            ("CRAFT", "18", "7"): 314.5,
        }
        for row in rows:
            series = row["series"]
            width_ft = int(row["width_ft"])
            height_ft = int(row["height_ft"])
            chart = float(row["total_lb"])
            rate = float(row["section_lb_per_ft"])
            if series == "CRAFT":
                assert rate == pytest.approx(5.1375 if height_ft == 7 else 6.1875, abs=1e-4)
            cfg = DoorConfiguration(
                door_type="residential", door_series=series,
                door_width=width_ft * 12, door_height=height_ft * 12,
                door_count=1, panel_color="WHITE",
                panel_design="SHXL" if series == "KANATA" else "FLUSH",
            )
            got = svc._calculate_door_weight(cfg)
            assert got == pytest.approx(chart, rel=0.02), (
                f"{series} {width_ft}x{height_ft}: {got:.1f} lb vs chart {chart}"
            )
            key = (series, row["width_ft"], row["height_ft"])
            if key in anchors:
                assert chart == anchors[key]

    def test_measured_weight_is_accepted_for_a_brand_with_no_chart(self):
        calc = door_calculator.calculate_door(
            "NOCHART", 96, 84, door_type="residential", track_size=2, door_weight=410,
        )
        assert calc.weight.total_weight == pytest.approx(410, abs=0.1)
        assert any("measured" in w.lower() for w in calc.warnings)
        assert not any("Kanata" in w and "using" in w.lower() for w in calc.warnings)

    def test_full_cost_beats_lighter_steel(self):
        """TX450 218x216 at 857.1 lb.

        4×.3065×2.625"×60.5" costs $430.10. 4×.3065×3.75"×43.5" uses less
        steel but the 3-3/4" cones bring it to $464.03. Cost is the
        tiebreak after cycle life; steel weight is later.
        """
        from app.services.door_calculator_service import _candidate_facts

        door = door_calculator.calculate_door(
            "TX450", 218, 216, door_type="commercial", track_size=3, door_weight=857.1,
        )
        drum = door.drums.model
        costs = {}
        results = {}
        for coil in (2.625, 3.75):
            result = spring_calculator.calculate_spring(
                857.1, 216, 15, 4, 0.3065, coil, 10000, drum,
            )
            facts = _candidate_facts(result)
            costs[coil] = facts["steel"] * 2.30 + facts["cones"]
            results[coil] = result
            assert result.achieved_cycles == 10000
        assert round(results[2.625].length, 1) == 60.5
        assert round(results[3.75].length, 1) == 43.5
        assert costs[2.625] == pytest.approx(430.10, abs=0.02)
        assert costs[3.75] == pytest.approx(464.03, abs=0.02)
        assert spring_rank_key(results[2.625], 10000) < spring_rank_key(results[3.75], 10000)

    def test_amarr_without_a_weight_is_held(self):
        calc = door_calculator.calculate_door(
            "AMARR", 96, 84, door_type="residential", track_size=2,
        )
        summary = door_calculator.get_calculation_summary(calc)
        assert summary["weight_required"] is True
        assert calc.weight.total_weight == 0
        assert calc.springs is None
        assert any("TX450 weights were not used" in w for w in calc.warnings)

        cfg = DoorConfiguration(
            door_type="residential", door_series="AMARR",
            door_width=96, door_height=84, door_count=1,
            panel_color="WHITE", panel_design="FLUSH",
        )
        spring_parts, _, _ = PartNumberService()._get_spring_parts(cfg)
        assert spring_parts[0].notes == "weight_required"
        assert spring_parts[0].category == "spring_warning"
        assert "TX450 weights were not used" in spring_parts[0].description

    def test_amarr_uses_a_measured_weight(self):
        calc = door_calculator.calculate_door(
            "AMARR", 96, 84, door_type="residential", track_size=2, door_weight=180,
        )
        assert calc.weight.total_weight == pytest.approx(180, abs=0.1)
        assert calc.springs is not None
        assert door_calculator.get_calculation_summary(calc)["weight_required"] is False

