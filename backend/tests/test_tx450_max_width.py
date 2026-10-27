"""TX450 max width is 36'2" (434"), not 36'0" (432").

The catalog's other wide series stop on a nominal foot plus 2" (weatherstrip
covers the stated length +2"; AL976 max is 24'2"; Panorama max is 30'2").
A 36'2" x 16' TX450 must pass validation and still produce a BOM. Lookups
with no stick at that width warn instead of failing or silently using a
shorter part.
"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from fastapi import HTTPException

from app.api.door_configurator import (
    DoorCalculationRequest,
    calculate_door_specifications,
    collect_dimension_validation,
    find_door_series,
    get_dimension_constraints,
)
from app.services.bc_part_number_mapper import (
    DoorModel,
    EndCapType,
    get_bc_mapper,
)
from app.services.part_number_service import (
    PartNumberService,
    get_parts_for_door_config,
    z_strut_run,
)
from app.services import sku_geometry


WIDTH_36_2 = 36 * 12 + 2  # 434
HEIGHT_16 = 16 * 12       # 192


def _tx450_parts(**overrides):
    base = {
        "doorType": "commercial",
        "doorSeries": "TX450",
        "doorWidth": WIDTH_36_2,
        "doorHeight": HEIGHT_16,
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
    base.update(overrides)
    return get_parts_for_door_config(base).get("parts_list", [])


def _by_category(parts, category):
    return [p for p in parts if p.get("category") == category]


class TestTx450WidthCap:
    def test_series_max_is_36_feet_2(self):
        specs = find_door_series("TX450")["specs"]
        assert specs["maxWidth"] == WIDTH_36_2

    def test_other_commercial_series_stay_at_36_feet(self):
        for series_id in ("TX500", "TX450-20", "TX500-20"):
            assert find_door_series(series_id)["specs"]["maxWidth"] == 432

    def test_434_is_allowed(self):
        errors, _warnings = collect_dimension_validation(
            "commercial", "TX450", WIDTH_36_2, HEIGHT_16
        )
        assert errors == []

    def test_432_is_still_allowed(self):
        errors, _warnings = collect_dimension_validation(
            "commercial", "TX450", 432, HEIGHT_16
        )
        assert errors == []

    def test_435_is_rejected(self):
        errors, _warnings = collect_dimension_validation(
            "commercial", "TX450", WIDTH_36_2 + 1, HEIGHT_16
        )
        assert any("exceeds maximum 434" in e for e in errors)
        assert any("Thermalex TX450" in e for e in errors)

    def test_tx500_still_rejects_36_feet_2(self):
        errors, _warnings = collect_dimension_validation(
            "commercial", "TX500", WIDTH_36_2, HEIGHT_16
        )
        assert any("exceeds maximum 432" in e for e in errors)

    def test_dimension_constraints_endpoint_matches_catalog(self):
        data = asyncio.run(get_dimension_constraints("TX450"))
        assert data["data"]["maxWidth"] == WIDTH_36_2

    def test_calculate_door_rejects_past_series_max_without_calling_bc(self):
        over = DoorCalculationRequest(
            doorModel="TX450", widthFeet=36, widthInches=3,
            heightFeet=16, heightInches=0,
        )
        with pytest.raises(HTTPException) as exc:
            asyncio.run(calculate_door_specifications(over, db=None))
        assert exc.value.status_code == 400
        assert "434" in exc.value.detail

        other = DoorCalculationRequest(
            doorModel="TX500", widthFeet=36, widthInches=2,
            heightFeet=16, heightInches=0,
        )
        with pytest.raises(HTTPException) as exc:
            asyncio.run(calculate_door_specifications(other, db=None))
        assert exc.value.status_code == 400
        assert "432" in exc.value.detail


class TestTx450PanelWidth:
    def test_36_2_keeps_exact_width_code(self):
        mapper = get_bc_mapper()
        panel = mapper.get_panel_part_number(
            model=DoorModel.TX450,
            width_feet=WIDTH_36_2 / 12,
            height_inches=24,
            color="WHITE",
            end_cap_type=EndCapType.DOUBLE,
            stamp="UDC",
        )
        assert panel.part_number == "PN46-24400-3602"
        assert panel.notes
        assert "3200" in panel.notes
        assert "not a substitute" in panel.notes

    def test_width_inside_the_table_still_steps_up(self):
        # 31'0" is not stocked; the next stocked DEC white UDC 24" is 32'0".
        mapper = get_bc_mapper()
        panel = mapper.get_panel_part_number(
            model=DoorModel.TX450,
            width_feet=31,
            height_inches=24,
            color="WHITE",
            end_cap_type=EndCapType.DOUBLE,
            stamp="UDC",
        )
        assert panel.part_number.endswith("-3200")
        assert not panel.notes


class TestZStrutRun:
    def test_36_2_is_covered_by_stocked_8_and_10_sticks(self):
        run = z_strut_run(WIDTH_36_2)
        assert run
        assert set(run) <= {96, 120}
        assert sum(run) >= WIDTH_36_2
        # 3×10' + 1×8' = 38'0" is the tightest cover. A 12' stick is not stocked.
        assert run.count(120) == 3
        assert run.count(96) == 1

    def test_hat_strut_past_the_table_warns_instead_of_claiming_36_feet(self):
        strut = get_bc_mapper().get_strut(36, gauge=20)
        assert strut.notes
        assert "36'" in strut.notes
        assert "36'" not in strut.description


class TestTx450BomAt36Feet2:
    @pytest.fixture(scope="class")
    def parts(self):
        return _tx450_parts()

    def test_generation_does_not_fail(self, parts):
        assert parts
        assert any(p.get("part_number") for p in parts)

    def test_sections_are_36_feet_2_not_the_32_foot_stick(self, parts):
        panels = _by_category(parts, "panel")
        assert panels
        assert all(p["part_number"].endswith("-3602") for p in panels)
        assert all("36' 02\"" in p["description"] for p in panels)
        assert all("3200" not in p["part_number"] for p in panels)
        warnings = _by_category(parts, "sizing_warning")
        assert any(w.get("notes") == "unstocked_panel_width" for w in warnings)

    def test_struts_span_the_opening(self, parts):
        info = PartNumberService._get_strut_requirements(WIDTH_36_2, HEIGHT_16)
        assert info["type"] == "z"
        assert info["count"] > 0
        struts = [
            p for p in _by_category(parts, "strut")
            if p["part_number"].startswith("FH17-98012")
        ]
        assert struts
        assert not any(p["part_number"] == "FH17-00003-00" for p in parts)
        run = z_strut_run(WIDTH_36_2)
        covered = sum(run)
        assert covered >= WIDTH_36_2
        length_for = {"FH17-98012-1000": 120, "FH17-98012-0800": 96}
        total_inches = sum(
            length_for[p["part_number"]] * p["quantity"] for p in struts
        )
        assert total_inches >= WIDTH_36_2 * info["count"]
        warnings = _by_category(parts, "sizing_warning")
        assert any(w.get("notes") == "z_strut_built_from_sticks" for w in warnings)

    def test_shafts_cover_width_plus_overhang(self, parts):
        needed = WIDTH_36_2 + 18
        shafts = [
            p for p in _by_category(parts, "shaft")
            if p.get("part_number") and not p["part_number"].startswith("SP12")
        ]
        assert shafts
        warnings = _by_category(parts, "sizing_warning")
        if any(p["part_number"] == "SH10-00002-00" for p in shafts):
            qty = sum(
                p["quantity"] for p in shafts if p["part_number"] == "SH10-00002-00"
            )
            assert qty >= needed
            assert any(w.get("notes") == "shaft_bulk_bar" for w in warnings)
            # Cones have to match the 1-1/4" bar. 1" plugs will not go on it.
            winders = [
                p for p in _by_category(parts, "spring_accessory")
                if "WINDER" in (p.get("description") or "").upper()
                or (p.get("part_number") or "").startswith("SP12-002")
            ]
            assert winders
            assert all("1-1/4" in p["description"] for p in winders), winders
        else:
            total = 0
            for p in shafts:
                inches = sku_geometry.sku_to_inches(p["part_number"]) or 0
                total += inches * p["quantity"]
            assert total >= needed, shafts

    def test_track_weatherstrip_and_hardware_are_present(self, parts):
        tracks = _by_category(parts, "track")
        assert tracks and all(t.get("part_number") for t in tracks)
        seals = _by_category(parts, "weather_stripping")
        assert seals and all(s.get("part_number") for s in seals)
        hardware = _by_category(parts, "hardware")
        assert hardware and hardware[0].get("part_number")
        warnings = _by_category(parts, "sizing_warning")
        assert any(w.get("notes") == "hardware_kit_past_width_table" for w in warnings)
        assert "434" in next(
            w["description"] for w in warnings
            if w.get("notes") == "hardware_kit_past_width_table"
        )
