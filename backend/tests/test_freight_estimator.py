"""Ship weight, crate size, and the Manitoulin agreement #19067426 rate engine."""
from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from app.services.crate_estimator import pack_crates
from app.services.door_calculator_service import DOOR_MODEL_WEIGHTS
from app.services.freight_estimator_service import SIGNED_NOTE, estimate_freight
from app.services.freight_estimator_settings import freight_estimator_enabled
from app.services.freight_numbers import D
from app.services.manitoulin_rate_engine import billed_weight, cube_cuft, rate_billed_weight, rate_pieces
from app.services.manitoulin_rate_table import (
    AGREEMENT,
    BREAKS,
    DATA_PATH,
    NO_CONTRACT_RATE,
    apply_extracted,
    extract_lanes_from_workbook,
    load_rate_table,
    placeholder_document,
)
from app.services.ship_weight_service import _spring_weight, build_door_line, load_constants
from app.services.staff_permissions import permission_for

ROOT = Path(__file__).resolve().parents[2]
FREIGHT_SOURCES = (
    "backend/app/services/ship_weight_service.py",
    "backend/app/services/crate_estimator.py",
    "backend/app/services/manitoulin_rate_engine.py",
    "backend/app/services/manitoulin_rate_table.py",
    "backend/app/services/freight_estimator_service.py",
    "backend/app/services/freight_estimator_settings.py",
    "backend/app/api/freight_estimator.py",
)


def _money(value) -> str:
    return f"{Decimal(str(value)).quantize(Decimal('0.01'))}"


def _piece(length, width, height, weight, label="piece"):
    return {
        "kind": "skid",
        "label": label,
        "length_in": length,
        "width_in": width,
        "height_in": height,
        "weight_lb": weight,
        "product_weight_lb": weight,
        "tare_lb": 0,
    }


def _rate(pieces, destination="regina", origin="redcliff", **config):
    table = load_rate_table()
    setup = {
        "fuel_percent": "68.80",
        "long_charge": 75,
        "long_min_length_in": 96,
        "density_lb_per_cuft": 10,
        "gst_percent": 5,
    }
    setup.update(config)
    return rate_pieces(pieces, origin, destination, table, setup)


def test_tx450_20_panel_rates_match_the_march_2026_workbook():
    rates = DOOR_MODEL_WEIGHTS["TX450-20"]
    assert rates["21"] == 4.5175
    assert rates["24"] == 4.7145
    # 18 in was a copy of the 21 in figure. It moves with the corrected 21 in rate.
    assert rates["18"] == 4.5175
    assert rates["28"] == 6.2
    source = (ROOT / "backend/app/services/part_number_service.py").read_text()
    assert "DOOR_MODEL_WEIGHTS" in source
    assert "5.6813" not in source
    assert '"TX450-20": {"18": 5.18' not in source


def test_spring_weight_uses_the_steel_formula():
    springs = type("Spring", (), {})()
    springs.is_duplex = False
    springs.quantity = 2
    springs.wire_diameter = 0.250
    springs.coil_diameter = 2.0
    springs.length = 30
    weight, source, count = _spring_weight(springs, [])
    assert source == "formula"
    assert count == 2
    # 0.250 x 2.0 x 30 in is about 11.8 lb of steel per spring.
    assert weight == D("11.81") * D(2)


def test_flag_defaults_off_without_a_row():
    assert freight_estimator_enabled(None) is False


def test_crate_length_is_the_shaft_rule_and_same_widths_share():
    constants = load_constants()
    crate = constants["crate"]
    wide = {
        "label": "16 ft door",
        "width_in": 192,
        "section_face_in": 24,
        "stack_in": 7,
        "product_weight_lb": 400,
        "include_shaft": True,
    }
    narrow = dict(wide, label="10 ft door", width_in=120, product_weight_lb=250)
    one = pack_crates([wide], crate)
    assert one[0]["length_in"] == 210
    assert one[0]["width_in"] == 28  # 24 in section face + 4 in packing
    assert one[0]["height_in"] == 11  # 7 in of panels + 4 in dunnage
    assert one[0]["door_count"] == 1

    shared = pack_crates([wide, dict(wide, label="16 ft door 2")], crate)
    assert len(shared) == 1
    assert shared[0]["door_count"] == 2
    assert shared[0]["height_in"] == 18  # 14 in of panels + 4 in dunnage
    assert shared[0]["length_in"] == 210

    separate = pack_crates([wide, narrow], crate)
    assert len(separate) == 2
    assert {row["length_in"] for row in separate} == {210, 138}

    split = pack_crates([wide, dict(wide, label="16 ft door 2")], dict(crate, max_stack_height_in=10))
    assert len(split) == 2


def test_one_door_past_the_stack_limit_still_crates():
    constants = load_constants()
    crate = dict(constants["crate"], max_stack_height_in=10)
    packed = pack_crates([{
        "label": "tall",
        "width_in": 96,
        "section_face_in": 21,
        "stack_in": 18,
        "product_weight_lb": 100,
        "include_shaft": True,
    }], crate)
    assert len(packed) == 1
    assert packed[0]["warning"]
    assert packed[0]["height_in"] == 22


def test_redcliff_calgary_known_crate():
    result = _rate([_piece(210, 28, 36, 1000)], destination="calgary")
    shipment = result["shipment"]
    assert shipment["rated"] is True
    assert shipment["billed_weight_lb"] == 1225
    assert shipment["break"] == "1000"
    assert _money(shipment["rate_per_cwt"]) == "14.41"
    assert _money(shipment["linehaul"]) == "176.52"
    assert _money(shipment["long"]) == "75.00"
    assert _money(shipment["fuel"]) == "121.45"
    assert _money(shipment["subtotal"]) == "372.97"
    assert _money(shipment["gst"]) == "18.65"
    assert _money(shipment["all_in"]) == "391.62"
    assert shipment["deficit_used"] is False
    alone = result["pieces"][0]["rated_alone"]
    assert _money(alone["linehaul"]) == "176.52"
    assert result["pieces"][0]["cube_cuft"] == 122.5


def test_redcliff_regina_known_breaks():
    light = _rate([_piece(48, 40, 24, 250)])
    assert light["shipment"]["billed_weight_lb"] == 266.67
    assert light["shipment"]["break"] == "L5C"
    assert _money(light["shipment"]["rate_per_cwt"]) == "32.63"
    assert _money(light["shipment"]["linehaul"]) == "87.01"

    cube = _rate([_piece(48, 40, 48, 400)])
    assert cube["shipment"]["billed_weight_lb"] == 533.33
    assert cube["shipment"]["break"] == "500"
    assert _money(cube["shipment"]["rate_per_cwt"]) == "25.59"
    assert _money(cube["shipment"]["linehaul"]) == "136.48"

    # 1800 lb actual. The 1000 break would be $360. Rating 2000 lb at the
    # 2000 break ($16.65) is $333, so the deficit weight wins.
    deficit = _rate([_piece(48, 40, 48, 1800)])
    assert deficit["shipment"]["billed_weight_lb"] == 1800
    assert deficit["shipment"]["break"] == "2000"
    assert deficit["shipment"]["rated_weight_lb"] == 2000
    assert _money(deficit["shipment"]["linehaul"]) == "333.00"
    assert deficit["shipment"]["deficit_used"] is True


def test_minimums_and_published_break_rates():
    table = load_rate_table()
    by_dest = {(lane["origin"], lane["destination"]): lane for lane in table["lanes"]}
    regina = by_dest[("redcliff", "regina")]
    edmonton = by_dest[("redcliff", "edmonton")]
    calgary = by_dest[("redcliff", "calgary")]
    assert regina["min"] == 76
    assert edmonton["min"] == 80
    assert calgary["min"] == 66
    assert regina["rates"]["1000"] == 20.00
    assert regina["rates"]["2000"] == 16.65
    assert edmonton["rates"]["1000"] == 20.50
    assert edmonton["rates"]["2000"] == 16.97
    assert calgary["rates"]["1000"] == 14.41
    assert calgary["rates"]["2000"] == 11.42
    assert regina["rates"]["L5C"] == 32.63
    assert regina["rates"]["500"] == 25.59
    assert edmonton["rates"]["L5C"] == 33.80
    assert edmonton["rates"]["500"] == 26.40
    assert edmonton["rates"]["10000"] == 9.99
    assert edmonton["rates"]["20000"] == 8.32

    bumped = _rate([_piece(12, 12, 12, 100)])
    assert bumped["shipment"]["minimum_applied"] is True
    assert _money(bumped["shipment"]["linehaul"]) == "76.00"
    assert _money(bumped["shipment"]["long"]) == "0.00"
    assert _money(bumped["shipment"]["fuel"]) == "52.29"


def test_break_floors_and_missing_lanes():
    # A 12 in cube does not change the billed weight. 300 lb stays on L5C
    # because 300 lb at $32.63 is cheaper than 500 lb at $25.59. 499 lb is
    # not: the next-break check rates it as 500 lb and that linehaul wins.
    assert _rate([_piece(12, 12, 12, 300)])["shipment"]["break"] == "L5C"
    at_five_hundred = _rate([_piece(12, 12, 12, 500)])["shipment"]
    assert at_five_hundred["break"] == "500"
    assert at_five_hundred["deficit_used"] is False
    jumped = _rate([_piece(12, 12, 12, 499)])["shipment"]
    assert jumped["break"] == "500"
    assert jumped["deficit_used"] is True

    # A lane with no cells, and a lane with one null cell, return the
    # spot-quote message instead of $0.
    table = load_rate_table()
    setup = {"fuel_percent": "68.80", "long_charge": 75, "long_min_length_in": 96,
             "density_lb_per_cuft": 10, "gst_percent": 5}
    lanes = {(lane["origin"], lane["destination"]): lane for lane in table["lanes"]}
    vancouver = lanes[("milton", "vancouver")]
    vancouver["min"] = None
    vancouver["rates"] = {name: None for name in BREAKS}
    lanes[("redcliff", "calgary")]["rates"]["L5C"] = None
    missing = rate_pieces([_piece(48, 40, 40, 500)], "milton", "vancouver", table, setup)
    assert missing["shipment"]["rated"] is False
    assert missing["shipment"]["message"] == NO_CONTRACT_RATE
    empty_cell = rate_pieces([_piece(48, 40, 40, 200)], "redcliff", "calgary", table, setup)
    assert empty_cell["shipment"]["rated"] is False
    assert empty_cell["shipment"]["message"] == NO_CONTRACT_RATE


def test_billed_weight_uses_exact_cube_before_rounding():
    cube = cube_cuft(48, 40, 24)
    assert billed_weight(250, cube, 10) == D("266.67")
    assert billed_weight(1000, cube_cuft(210, 28, 36), 10) == D("1225.00")


def test_rate_table_is_imported_from_the_agreement_workbook():
    table = load_rate_table()
    assert table["agreement"] == AGREEMENT
    assert table["placeholder"] is False
    assert table["status"] == "imported"
    assert "signed" in table["notice"]
    assert len(table["lanes"]) == 21
    assert list(table["breaks"]) == list(BREAKS)
    for lane in table["lanes"]:
        assert lane["min"] is not None
        assert all(value is not None for value in lane["rates"].values())
        assert not lane.get("conflicts")


def test_workbook_import_reads_the_city_prov_layout(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.append(["FROM", None, "TO"])
    sheet.append(["City", "Prov.", "City", "Prov.", "MIN", "L5C", "500", "1000", "2000", "5000", 10000, 20000])
    sheet.append(["Redcliff", "AB", "Regina", "SK", 76, 32.63, 25.59, 20, 16.65, 12.87, 9.84, 8.33])
    sheet.append(["Milton", "ON", "Calgary", "AB", 160, 87.43, 77.1, 68.77, 62.97, 56.89, 46.01, 44.44])
    path = tmp_path / "city_prov.xlsx"
    workbook.save(path)
    lanes = {(row["origin"], row["destination"]): row for row in extract_lanes_from_workbook(str(path))}
    assert lanes[("redcliff", "regina")]["min"] == 76
    assert lanes[("redcliff", "regina")]["rates"]["L5C"] == 32.63
    assert lanes[("redcliff", "regina")]["rates"]["20000"] == 8.33
    assert lanes[("milton", "calgary")]["rates"]["500"] == 77.1
    assert len(lanes) == 2


def test_workbook_import_fills_a_stacked_sheet(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.append(["ORIGIN: REDCLIFF AB"])
    sheet.append(["Destination", "MIN", "L5C", "500", "1000", "2000", "5000", "10000", "20000"])
    sheet.append(["Calgary", 66, 40, 30, 14.41, 11.42, 9, 8, 7])
    sheet.append(["Edmonton", 80, 41, 31, 20.50, 16.97, 12, 10, 9])
    sheet.append([])
    sheet.append(["FROM MILTON ON"])
    sheet.append(["Destination", "MIN", "L5C", "500", "1000", "2000", "5000", "10000", "20000"])
    sheet.append(["Vancouver", 150, 55, 40, 28, 22, 18, 15, 12])
    path = tmp_path / "190674sa26.xlsx"
    workbook.save(path)

    extracted = extract_lanes_from_workbook(str(path))
    document = apply_extracted(placeholder_document(), extracted, path.name)
    lanes = {(lane["origin"], lane["destination"]): lane for lane in document["lanes"]}
    assert lanes[("redcliff", "calgary")]["rates"]["L5C"] == 40
    assert lanes[("redcliff", "calgary")]["rates"]["1000"] == 14.41
    assert lanes[("redcliff", "edmonton")]["min"] == 80
    assert lanes[("milton", "vancouver")]["rates"]["500"] == 40
    # A destination the sheet did not list stays null.
    assert lanes[("milton", "regina")]["rates"]["1000"] is None
    assert lanes[("redcliff", "regina")]["rates"]["L5C"] == 32.63
    assert document["status"] == "partial"
    assert document["placeholder"] is True


def test_estimate_matches_the_calgary_fixture_without_touching_bc():
    result = estimate_freight({
        "origin": "Redcliff AB",
        "destination": "Calgary",
        "doors": [],
        "skids": [{
            "label": "Crate",
            "length_in": 210,
            "width_in": 28,
            "height_in": 36,
            "weight_lb": 1000,
        }],
    })
    assert result["signed_note"] == SIGNED_NOTE
    assert "signed" in result["signed_note"].lower()
    assert _money(result["shipment"]["linehaul"]) == "176.52"
    assert _money(result["shipment"]["gst"]) == "18.65"
    assert result["rate_table"]["placeholder"] is False


def test_sixteen_foot_door_crates_at_210_inches():
    result = estimate_freight({
        "origin": "redcliff",
        "destination": "calgary",
        "doors": [{
            "doorSeries": "TX450",
            "doorType": "commercial",
            "doorWidth": 192,
            "doorHeight": 96,
            "doorCount": 1,
            "trackThickness": "2",
            "trackMount": "bracket",
            "liftType": "standard",
            "trackRadius": "15",
            "operator": "NONE",
        }],
    })
    line = result["lines"][0]
    assert line["sections"]["count"] == 4
    assert line["sections"]["sections_24"] == 4
    assert line["sections"]["thickness_in"] == 1.75
    assert line["components"]["hanging_lb"] > 0
    assert line["components"]["track_lb"] > 0
    assert line["components"]["springs_lb"] > 0
    assert line["components"]["shaft_lb"] > 0
    assert line["components"]["drums_lb"] > 0
    assert line["components"]["bearings_lb"] > 0
    assert line["components"]["cones_lb"] > 0
    assert line["components"]["operator_lb"] == 0
    component_sum = sum(line["components"].values())
    assert _money(component_sum) == _money(line["product_weight_lb"])
    crate = result["pieces"][0]
    assert crate["kind"] == "crate"
    assert crate["length_in"] == 210
    assert crate["width_in"] == 28
    assert crate["door_count"] == 1
    assert crate["ship_weight_lb"] > line["product_weight_lb"]
    assert crate["tare_lb"] > 0


def test_two_same_width_doors_share_one_crate_in_the_estimate():
    door = {
        "doorSeries": "TX380",
        "doorType": "commercial",
        "doorWidth": 96,
        "doorHeight": 84,
        "doorCount": 2,
        "trackThickness": "2",
        "liftType": "standard",
        "operator": "residential_trolley",
    }
    result = estimate_freight({"origin": "redcliff", "destination": "edmonton", "doors": [door]})
    assert result["lines"][0]["qty"] == 2
    assert result["lines"][0]["operator_family"] == "residential_trolley"
    assert result["lines"][0]["components"]["operator_lb"] == 55
    crates = [piece for piece in result["pieces"] if piece["kind"] == "crate"]
    assert len(crates) == 1
    assert crates[0]["door_count"] == 2


def test_feature_modules_do_not_write_to_business_central():
    banned = ("bc_client", "create_sales_quote", "add_quote_line", "convert_quote_to_order", "BCClient")
    for relative in FREIGHT_SOURCES:
        text = (ROOT / relative).read_text()
        for token in banned:
            assert token not in text, f"{relative} mentions {token}"


def test_permissions_cover_the_estimator_and_leave_the_switch_on_settings():
    assert permission_for("GET", "/api/freight-estimator/settings") == ("perm", "settings.view")
    assert permission_for("PUT", "/api/freight-estimator/settings") == ("perm", "settings.edit")
    estimate = permission_for("POST", "/api/freight-estimator/estimate")
    assert estimate[0] == "any"
    assert "configurator.use" in estimate
    assert "quotes.edit" in estimate
    enabled = permission_for("GET", "/api/freight-estimator/enabled")
    assert enabled[0] == "any"


def test_direct_door_line_build_reports_a_solid_shaft_on_a_light_commercial_door():
    line = build_door_line({
        "doorSeries": "TX450-20",
        "doorType": "commercial",
        "doorWidth": 96,
        "doorHeight": 84,
        "trackThickness": "2",
        "trackMount": "bracket",
        "liftType": "standard",
        "operator": "NONE",
    }, load_constants())
    assert line["shaft_type"] == "solid"
    # 8 ft door, single 1 in solid shaft at door width + 18 in = 9.5 ft * 2.670 lb/ft.
    assert line["components"]["shaft_lb"] == 25.37
    assert line["spring_weight_source"] == "formula"


def test_cheapest_higher_break_can_skip_the_one_above():
    # 400 lb at $100/CWT is $400. The 500 break at its minimum is $450, so the
    # next column is not the win. The 1000 break at its minimum is $200, and
    # the 2000 break is $300. The 1000 column is the one to use.
    lane = {
        "min": 50,
        "rates": {
            "L5C": 100,
            "500": 90,
            "1000": 20,
            "2000": 15,
            "5000": None,
            "10000": None,
            "20000": None,
        },
    }
    result = rate_billed_weight(D(400), lane)
    assert result["rated"] is True
    assert result["break"] == "1000"
    assert result["rated_weight_lb"] == 1000
    assert result["deficit_used"] is True
    assert _money(result["linehaul"]) == "200.00"
    assert result["minimum_applied"] is False


def test_estimate_and_settings_reject_bad_numbers():
    from fastapi import HTTPException
    from app.api.freight_estimator import (
        EstimateRequest,
        _check_non_negative_map,
        validate_estimate_request,
    )

    def rejected(call):
        with pytest.raises(HTTPException) as caught:
            call()
        assert caught.value.status_code == 400

    ok = EstimateRequest(
        destination="calgary",
        doors=[{"doorWidth": 192, "doorHeight": 96, "doorCount": 2}],
        skids=[{"length_in": 48, "width_in": 40, "height_in": 24, "weight_lb": 250}],
    )
    validate_estimate_request(ok)

    rejected(lambda: validate_estimate_request(EstimateRequest(
        destination="calgary", fuel_percent=float("nan"), doors=[{"doorWidth": 96, "doorHeight": 84}],
    )))
    rejected(lambda: validate_estimate_request(EstimateRequest(
        destination="calgary", density_lb_per_cuft=float("inf"),
        skids=[{"length_in": 48, "width_in": 40, "height_in": 24, "weight_lb": 10}],
    )))
    rejected(lambda: validate_estimate_request(EstimateRequest(
        destination="calgary", long_charge=-1,
        skids=[{"length_in": 48, "width_in": 40, "height_in": 24, "weight_lb": 10}],
    )))
    rejected(lambda: validate_estimate_request(EstimateRequest(
        destination="calgary",
        doors=[{"doorWidth": float("inf"), "doorHeight": 84}],
    )))
    rejected(lambda: validate_estimate_request(EstimateRequest(
        destination="calgary",
        doors=[{"doorWidth": 96, "doorHeight": float("nan")}],
    )))
    rejected(lambda: validate_estimate_request(EstimateRequest(
        destination="calgary",
        doors=[{"doorWidth": 0, "doorHeight": 84}],
    )))
    rejected(lambda: validate_estimate_request(EstimateRequest(
        destination="calgary",
        doors=[{"doorWidth": 96, "doorHeight": 84, "doorCount": 51}],
    )))
    rejected(lambda: validate_estimate_request(EstimateRequest(
        destination="calgary",
        doors=[{"doorWidth": 96, "doorHeight": 84} for _ in range(101)],
    )))
    rejected(lambda: validate_estimate_request(EstimateRequest(
        destination="calgary",
        skids=[{"length_in": 48, "width_in": 40, "height_in": 0, "weight_lb": 10}],
    )))
    rejected(lambda: validate_estimate_request(EstimateRequest(
        destination="calgary",
        skids=[{"length_in": 48, "width_in": 40, "height_in": 24, "weight_lb": float("nan")}],
    )))
    rejected(lambda: _check_non_negative_map("crate", {"dunnage_in": -1}))
    rejected(lambda: _check_non_negative_map("operator_lb", {"residential_trolley": float("nan")}))
    rejected(lambda: _check_non_negative_map("shaft_lb_per_ft", {"solid": float("inf")}))
    rejected(lambda: _check_non_negative_map("drum_lb_each", {"D400": -0.1}))
    _check_non_negative_map("crate", {"dunnage_in": 0, "tare_lb_per_ft": 8})
