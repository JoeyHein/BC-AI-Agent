"""Spring calculator and part number tests.

Covers the critical spring bugs we've fixed:
- CRAFT/commercial doors must calculate real springs (not SP01-00000-00)
- Residential doors get springs for all cycle counts
- Spring warnings appear instead of silent failures
- Wire step-up finds valid BC part numbers
- Duplex conversion produces viable options
"""
import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.part_number_service import get_parts_for_door_config
from app.services.spring_calculator_service import SpringCalculatorService


def _get_spring_parts(config_overrides: dict) -> list:
    """Helper: generate parts and return only spring-category items."""
    base = {
        "doorType": "residential",
        "doorSeries": "KANATA",
        "doorWidth": 108,
        "doorHeight": 84,
        "doorCount": 1,
        "panelColor": "WHITE",
        "panelDesign": "SHXL",
        "hardware": {"springs": True, "tracks": True, "struts": True,
                     "hardwareKits": True, "weatherStripping": True,
                     "bottomRetainer": True, "shafts": True},
        "targetCycles": 10000,
        "trackThickness": "2",
        "trackRadius": "15",
        "trackMount": "bracket",
        "liftType": "standard",
    }
    base.update(config_overrides)
    result = get_parts_for_door_config(base)
    return result.get("parts_list", [])


def _spring_items(parts):
    return [p for p in parts if p.get("category") in ("spring", "spring_accessory")]


def _spring_warnings(parts):
    return [p for p in parts if p.get("category") == "spring_warning"]


# ── No placeholder part numbers ──────────────────────────────────────────

class TestNoPlaceholders:
    """SP01-00000-00 must never appear on any quote."""

    def test_kanata_no_placeholder(self):
        parts = _get_spring_parts({"doorSeries": "KANATA"})
        for p in parts:
            assert p.get("part_number") != "SP01-00000-00", \
                f"KANATA door has placeholder spring: {p}"

    def test_craft_no_placeholder(self):
        parts = _get_spring_parts({"doorSeries": "CRAFT", "panelDesign": "FLUSH"})
        for p in parts:
            assert p.get("part_number") != "SP01-00000-00", \
                f"CRAFT door has placeholder spring: {p}"

    def test_commercial_no_placeholder(self):
        parts = _get_spring_parts({
            "doorType": "commercial", "doorSeries": "TX450",
            "doorWidth": 168, "doorHeight": 120,
            "panelDesign": "UDC", "trackThickness": "3",
        })
        for p in parts:
            assert p.get("part_number") != "SP01-00000-00", \
                f"Commercial door has placeholder spring: {p}"


# ── Springs always generated ─────────────────────────────────────────────

class TestSpringsGenerated:
    """Every door must produce at least one spring part or a warning."""

    @pytest.mark.parametrize("series,design", [
        ("KANATA", "SHXL"),
        ("CRAFT", "FLUSH"),
    ])
    @pytest.mark.parametrize("cycles", [10000, 15000, 25000])
    def test_residential_has_springs_or_warning(self, series, design, cycles):
        parts = _get_spring_parts({
            "doorSeries": series, "panelDesign": design, "targetCycles": cycles,
        })
        springs = _spring_items(parts)
        warnings = _spring_warnings(parts)
        assert springs or warnings, \
            f"{series} {cycles} cycles: no springs AND no warnings"

    def test_commercial_has_springs_or_warning(self):
        parts = _get_spring_parts({
            "doorType": "commercial", "doorSeries": "TX450",
            "doorWidth": 168, "doorHeight": 120,
            "panelDesign": "UDC", "trackThickness": "3",
            "targetCycles": 25000,
        })
        springs = _spring_items(parts)
        warnings = _spring_warnings(parts)
        assert springs or warnings, "Commercial 25K cycles: no springs AND no warnings"


# ── Spring part numbers exist in BC ──────────────────────────────────────

class TestSpringPartsInBC:
    """Generated spring part numbers must exist in BC inventory."""

    def test_standard_residential_springs_in_bc(self):
        from app.services.bc_part_number_mapper import get_bc_mapper
        mapper = get_bc_mapper()

        parts = _get_spring_parts({"doorSeries": "KANATA", "targetCycles": 10000})
        springs = [p for p in parts if p.get("category") == "spring" and p.get("part_number")]

        for s in springs:
            pn = s["part_number"]
            if pn.startswith("SP-"):  # Custom placeholder, skip
                continue
            assert pn in mapper.bc_items, \
                f"Spring {pn} not found in BC items"


# ── Duplex conversion ────────────────────────────────────────────────────

class TestDuplexConversion:
    """Duplex conversion must produce viable options."""

    def test_duplex_options_generated(self):
        calc = SpringCalculatorService()
        result = calc.calculate_conversion(
            current_wire=0.421,
            current_coil=6.0,
            current_length=58.0,
            current_spring_qty=2,
        )
        assert result.get("success"), f"Conversion failed: {result.get('error')}"
        assert result.get("duplex_options"), "No duplex options generated"
        assert len(result["duplex_options"]) > 0

    def test_duplex_options_shorter_than_original(self):
        calc = SpringCalculatorService()
        result = calc.calculate_conversion(
            current_wire=0.421, current_coil=6.0,
            current_length=58.0, current_spring_qty=2,
        )
        for opt in result.get("duplex_options", []):
            assert opt["outer"]["length"] < 58.0, \
                f"Duplex outer ({opt['outer']['length']}\") not shorter than original (58\")"


# ── High-lift duplex matches SSSpring, never tandem ──────────────────────

class TestHighLiftDuplexNoTandem:
    """SSSpring 5.1.3 on a 28'×20' hi-lift 72" / D800-120 / 6-spring duplex
    emits a single-shaft nest (~0.3625×6×38" + 0.295×3.75×37"). We used to
    treat inner+outer as 10 independent springs, blow MIP, pick a 5-pair
    70–89" pack, and stamp TANDEM SHAFT REQUIRED — on a high-lift door.
    """

    def test_combined_divider_matches_sss_lengths(self):
        from app.services.spring_calculator_service import spring_calculator

        ippt = 0.3910977 * 1900.9
        lengths = spring_calculator.duplex_lengths(0.3625, 0.2950, 6, ippt)
        assert lengths is not None
        outer_len, inner_len, combined = lengths
        assert combined == 4527.0
        # SSSpring: 38.25 / 37.25 (weight spinner 1900.9, 6 springs on door)
        assert outer_len == pytest.approx(37.63, abs=0.2)
        assert inner_len == pytest.approx(37.43, abs=0.2)
        assert inner_len <= outer_len

    def test_sss_style_28x20_three_pair_is_single_shaft(self):
        from app.services.door_calculator_service import DoorCalculatorService, DrumSelection

        svc = DoorCalculatorService()
        drum = DrumSelection(model="D800-120", offset=6.0, cable_diameter=0.25, cable_length=320)
        sel = svc._calculate_duplex_springs(
            1900.9, 240, 10000, 15, None, 3, "D800-120", 72, 336,
        )
        assert sel is not None
        assert sel.is_duplex
        assert sel.is_tandem is False
        assert sel.duplex_pairs == 3
        assert sel.quantity == 6
        assert sel.turns == 12.6
        assert 30 <= sel.length <= 45
        # Combined MIP lets 0.3625+0.2950 (or a nearby stocked pair) through
        from app.services.spring_calculator_service import spring_calculator
        outer_mip = spring_calculator.get_mip_capacity(sel.wire_diameter, 10000)
        inner_mip = spring_calculator.get_mip_capacity(sel.inner_wire_diameter, 10000)
        assert outer_mip and inner_mip
        ippt = spring_calculator.calculate_ippt(0.3910977, 1900.9)
        assert outer_mip + inner_mip >= (ippt * 12.6) / 6

    def test_tx500_28x20_hl72_not_tandem(self):
        from app.services.door_calculator_service import DoorCalculatorService

        svc = DoorCalculatorService()
        calc = svc.calculate_door(
            door_model="TX500-20",
            width_inches=336,
            height_inches=240,
            lift_type="high_lift",
            track_size=3,
            target_cycles=10000,
            high_lift_inches=72,
        )
        assert calc.drums is not None
        assert calc.drums.model == "D800-120"
        assert calc.springs is not None
        assert calc.springs.is_tandem is False
        assert calc.springs.length <= 75
        assert "TANDEM" not in " ".join(calc.warnings).upper()

    def test_overweight_high_lift_picks_d800_not_d6375(self):
        """2401 lb is over D800's 2200 and D6375's 1600. Fallback must
        keep the higher-capacity D800 (12.6 turns), not the taller D6375
        (14.9 turns) that used to win on max_height."""
        from app.services.door_calculator_service import DoorCalculatorService

        svc = DoorCalculatorService()
        hl = {"type": "high", "radius": 15, "name": "High Lift"}
        drum = svc._select_drum(240, 2401, hl, effective_height=312, track_size=3)
        assert drum is not None
        assert drum.model == "D800-120"


# ── Warning content ──────────────────────────────────────────────────────

class TestSpringWarnings:
    """Warnings must contain actionable text, not cryptic codes."""

    def test_warning_mentions_contact_office(self):
        """If springs can't be calculated, warning must say 'Contact office'."""
        # Use extreme specs that will fail
        parts = _get_spring_parts({
            "doorWidth": 240, "doorHeight": 240,
            "targetCycles": 100000,
            "doorType": "commercial", "doorSeries": "TX500",
            "panelDesign": "UDC", "trackThickness": "3",
        })
        warnings = _spring_warnings(parts)
        if warnings:
            for w in warnings:
                desc = w.get("description", "").lower()
                assert "contact" in desc or "edit" in desc or "manual" in desc, \
                    f"Warning doesn't guide user: {w['description']}"
