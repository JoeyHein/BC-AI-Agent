"""Framing-detail formulas against the Thermalex workbook, and Joey's pad rule."""

from app.services.shop_drawings.thermalex_framing import (
    CONE_ALLOWANCE_IN,
    DIFFERENCES_FOR_JOEY,
    WORKBOOK_2PAD_1_COUPLER_SIDE_IN,
    WORKBOOK_4PAD_CENTER_GAP_IN,
    SpringSpec,
    assembly_length,
    assembly_length_of,
    build_framing_detail,
    center_pickup_count,
    center_shaft_length,
    closest_workbook_sheet,
    excel_ceiling,
    installed_length,
    place_pads,
    track_clearance,
    workbook_drum_width,
    workbook_gaps,
    workbook_pad_positions,
)
from app.services.shop_drawings.framing_detail import (
    detail_to_dxf,
    framing_detail_kind,
    generate_framing_detail,
    layout_labels,
    required_components,
    sheet_lines,
)


def _spring(hand, wire=0.25, turns=10.0, cut=30.0, nested=False, coil=2.0):
    return SpringSpec(hand, wire, turns, cut, nested=nested, coil=coil)


def _installed(wire=0.25, turns=10.0, cut=30.0):
    return wire * turns + cut + CONE_ALLOWANCE_IN


class TestWorkbookAssemblyLength:
    def test_sheet_sample_matches_b13(self):
        # Spring Ass.Length sample: wire 0.343, turns 14, cut 77, 2 springs,
        # drum width 4.29, no center pickup.
        # (0.343*14 + 3 + 77)*2 + 6 + 4.29*2 = 184.184
        length = assembly_length(0.343, 14, 77, 2, 4.29, center_pickups=0)
        assert length == (0.343 * 14 + 3 + 77) * 2 + 6 + 4.29 * 2
        assert abs(length - 184.184) < 1e-9

    def test_center_pickup_adds_one_drum_width(self):
        plain = assembly_length(0.343, 14, 77, 2, 4.29, center_pickups=0)
        extra = assembly_length(0.343, 14, 77, 2, 4.29, center_pickups=1)
        assert abs((extra - plain) - 4.29) < 1e-9

    def test_installed_length_is_b33(self):
        assert installed_length(0.343, 14, 77) == 0.343 * 14 + 77 + 3

    def test_mixed_springs_sum_to_the_same_formula_when_equal(self):
        springs = [_spring("LH"), _spring("RH")]
        one = _installed()
        expected = one * 2 + 6 + 3.62 * 2
        assert abs(assembly_length_of(springs, 3.62) - expected) < 1e-9

    def test_center_pickup_count(self):
        assert center_pickup_count(2200) == 0
        assert center_pickup_count(2500) == 1
        assert center_pickup_count(3300) == 1
        assert center_pickup_count(3301) == 2

    def test_workbook_drum_widths(self):
        assert workbook_drum_width("D525-216") == 3.62
        assert workbook_drum_width("1100-216") == 4.29
        assert workbook_drum_width("850-132") == 3.33


class TestWorkbookTrackClearances:
    def test_standard_2_inch_15_radius(self):
        # 16' × 14', 2" track, standard 15" radius.
        clearance = track_clearance(
            door_width_in=192, door_height_in=168,
            lift_type="standard", track_size_in=2, radius_in=15,
        )
        assert clearance.ust_above_opening_in == 168 + 6.5
        assert clearance.cl_from_header_in == 12.5
        assert clearance.headroom_in == 15.75
        assert clearance.shaft_from_floor_in == 168 + 12.5
        assert clearance.high_lift_in is None
        assert clearance.vertical_track_in == 160
        assert clearance.extension_in == 0
        assert clearance.backroom_in == 168 + 18

    def test_standard_2_inch_12_radius(self):
        clearance = track_clearance(
            door_width_in=144, door_height_in=120,
            lift_type="standard", track_size_in=2, radius_in=12,
        )
        assert clearance.ust_above_opening_in == 120 + 3.5
        assert clearance.cl_from_header_in == 9.5
        assert clearance.headroom_in == 12.75
        assert clearance.shaft_from_floor_in == 120 + 9.5

    def test_standard_3_inch_up_to_18_feet(self):
        clearance = track_clearance(
            door_width_in=180, door_height_in=168,
            lift_type="standard", track_size_in=3, radius_in=15,
        )
        assert clearance.ust_above_opening_in == 168 + 7.5
        assert clearance.cl_from_header_in == 14.5
        assert clearance.headroom_in == 17.75

    def test_standard_3_inch_above_18_feet(self):
        clearance = track_clearance(
            door_width_in=216, door_height_in=240,
            lift_type="standard", track_size_in=3, radius_in=12,
        )
        # 3" track is 15" radius on the sheet even if 12 was requested.
        assert clearance.radius_in == 15
        assert clearance.cl_from_header_in == 15.5
        assert clearance.headroom_in == 20.5
        assert clearance.ust_above_opening_in == 240 + 7.5

    def test_high_lift_3_inch_45(self):
        clearance = track_clearance(
            door_width_in=240, door_height_in=240,
            lift_type="high_lift", track_size_in=3, radius_in=15,
            high_lift_in=45,
        )
        assert clearance.high_lift_in == 45
        assert clearance.ust_above_opening_in == 240 + 45
        assert clearance.cl_from_header_in == 45 + 7
        assert clearance.headroom_in == 45 + 11
        assert clearance.shaft_from_floor_in == 240 + 52
        assert clearance.vertical_track_in == 240 - 8
        assert clearance.extension_in == 45 - 15 + 8

    def test_high_lift_2_inch_above_54(self):
        clearance = track_clearance(
            door_width_in=192, door_height_in=168,
            lift_type="high_lift", track_size_in=2, radius_in=15,
            high_lift_in=80,
        )
        assert clearance.cl_from_header_in == 80 + 6.5
        assert clearance.headroom_in == 80 + 11.5
        assert clearance.ust_sheet_in == 168 + 80

    def test_vertical_lift_extension(self):
        clearance = track_clearance(
            door_width_in=144, door_height_in=144,
            lift_type="vertical", track_size_in=2, radius_in=15,
        )
        assert clearance.ust_label == "U.S.T. N/A"
        assert clearance.cl_from_header_in == 144 + 12
        assert clearance.headroom_in == 144 + 18
        assert clearance.shaft_from_floor_in == 144 + 156
        assert clearance.vertical_track_in == 144 - 11
        assert clearance.extension_in == 144 * 2 + 12 + 8 - (144 - 11)

    def test_low_headroom_prints_door_height_as_ust(self):
        front = track_clearance(
            door_width_in=96, door_height_in=84,
            lift_type="low_headroom", track_size_in=2, radius_in=15,
            lhr_mount="front",
        )
        assert front.ust_above_opening_in == 0
        assert front.ust_sheet_in == 84
        assert front.cl_from_header_in == 6.5
        assert front.headroom_in == 10
        assert front.vertical_track_in == 84 - 15
        assert front.extension_in == 0

        rear = track_clearance(
            door_width_in=120, door_height_in=96,
            lift_type="low_headroom", track_size_in=3, radius_in=15,
            lhr_mount="rear",
        )
        assert rear.cl_from_header_in == 3
        assert rear.headroom_in == 7
        assert rear.shaft_from_floor_in == 96 + 3

    def test_tandem_adds_12_inches(self):
        clearance = track_clearance(
            door_width_in=192, door_height_in=168,
            lift_type="standard", track_size_in=2, radius_in=15,
            tandem=True,
        )
        assert clearance.headroom_in == 15.75 + 12
        assert clearance.tandem_shaft_from_floor_in == 168 + 12.5 + 12
        assert clearance.shaft_from_floor_in == 168 + 12.5

    def test_modified_shaft_elevation(self):
        clearance = track_clearance(
            door_width_in=192, door_height_in=168,
            lift_type="standard", track_size_in=2, radius_in=15,
            modified_shaft_from_floor_in=200,
        )
        assert clearance.shaft_from_floor_in == 200
        assert clearance.cl_from_header_in == 200 - 168
        assert clearance.headroom_in == 200 - 168 + 4
        # U.S.T. stays on the lift table.
        assert clearance.ust_above_opening_in == 168 + 6.5


class TestWorkbookPadSpans:
    def test_ceiling_matches_excel(self):
        assert excel_ceiling(241 / 3, 1) == 81
        assert excel_ceiling(241 / 4, 0.5) == 60.5
        assert center_shaft_length(240, 2) == 80
        assert center_shaft_length(240, 3) == 60
        assert center_shaft_length(240, 1) == 0

    def test_center_pad_sheet(self):
        assert workbook_pad_positions("center", 192, 1) == [96]
        assert workbook_gaps("center", 192, 1) == [96, 96]

    def test_two_pads_two_couplers(self):
        # W=240, I15=80. Side spans 80, center shaft 80.
        assert workbook_gaps("2pad_2coupler", 240, 2) == [80, 80, 80]
        assert workbook_pad_positions("2pad_2coupler", 240, 2) == [80, 160]

    def test_two_pads_one_coupler_is_the_hardcoded_73(self):
        gaps = workbook_gaps("2pad_1coupler", 240, 1)
        assert gaps[0] == WORKBOOK_2PAD_1_COUPLER_SIDE_IN == 73
        assert gaps[2] == 73
        assert gaps[1] == 240 - 146
        assert abs(sum(gaps) - 240) < 1e-9

    def test_three_pads_one_coupler_quarters(self):
        assert workbook_pad_positions("3pad", 240, 1) == [60, 120, 180]
        assert workbook_gaps("3pad", 240, 1) == [60, 60, 60, 60]

    def test_three_pads_two_couplers(self):
        # Outer callout (W-80)/2 = 80. Center pad at W/2.
        assert workbook_pad_positions("3pad", 240, 2) == [80, 120, 160]
        assert abs(sum(workbook_gaps("3pad", 240, 2)) - 240) < 1e-9

    def test_four_pads_hardcoded_center_does_not_close(self):
        gaps = workbook_gaps("4pad", 240, 2)
        assert gaps[2] == WORKBOOK_4PAD_CENTER_GAP_IN == 8
        assert gaps[0] == 40
        # 4*40 + 8 = 168, short of 240 by I15-8.
        assert abs(sum(gaps) - 168) < 1e-9
        assert workbook_pad_positions("4pad", 240, 2) == [40, 80, 88, 128]

    def test_five_pads_closes_on_the_center_shaft(self):
        # Coupler qty 3 → I15 = 60. Spans (240-60)/4 = 45, halves 30.
        gaps = workbook_gaps("5pad", 240, 3)
        assert gaps == [45, 45, 30, 30, 45, 45]
        assert abs(sum(gaps) - 240) < 1e-9
        assert workbook_pad_positions("5pad", 240, 3) == [45, 90, 120, 150, 195]

    def test_tandem_sheet_names(self):
        assert closest_workbook_sheet(1, False, 1) == "Center Pad,  Jamb and Extension"
        assert closest_workbook_sheet(1, True, 1) == "Cen Pad,  Jamb and Exten Tandem"
        assert closest_workbook_sheet(2, False, 2) == "2 Pads,  Jamb and Ext 2 Coupler"
        assert closest_workbook_sheet(2, False, 1) == "2 Pads,  Jamb and Ext 1 Coupler"
        assert closest_workbook_sheet(2, True, 2) == "2 Pads,  Jamb and Exten Tandem"
        assert closest_workbook_sheet(3, False, 1) == "3 Pads,  Jamb and Extension Dwg"
        assert closest_workbook_sheet(3, True, 1) == "3 Pads,  Jamb and Extens Tandem"
        assert closest_workbook_sheet(4, False, 2) == "4 Pads,  Jamb and Extension"
        assert closest_workbook_sheet(5, False, 3) == "5 Pads,  Jamb and Extension"
        assert closest_workbook_sheet(6, False, 1) == "5 Pads,  Jamb and Extension"


class TestJoeyPadPlacement:
    def _xs(self, springs, width=240):
        pads, _notes = place_pads(springs, width)
        return [round(pad.x_from_center_in, 4) for pad in pads]

    def test_two_springs_one_center_pad(self):
        length = _installed()
        pads, notes = place_pads([_spring("LH"), _spring("RH")], 240)
        assert len(pads) == 1
        assert pads[0].x_from_center_in == 0
        assert pads[0].x_from_left_jamb(240) == 120
        assert pads[0].x_from_right_jamb(240) == 120
        assert not any("odd spring" in note for note in notes)
        # The drum width is not part of the pad station.
        assert length != 0

    def test_three_springs_three_pads(self):
        # Two LH share the center. The single RH does not, so its pad sits
        # one 6 in. gap plus its installed length off center.
        length = _installed()
        xs = self._xs([_spring("LH"), _spring("LH"), _spring("RH")])
        assert xs == [round(-length, 4), 0.0, round(6 + length, 4)]

    def test_four_springs_three_pads_at_the_inner_ends(self):
        length = _installed()
        xs = self._xs([_spring("LH"), _spring("LH"), _spring("RH"), _spring("RH")])
        assert xs == [round(-length, 4), 0, round(length, 4)]
        # Not the workbook's W/4 stations.
        assert round(240 / 4, 4) not in [120 + x for x in xs]

    def test_five_springs_five_pads(self):
        length = _installed()
        springs = [_spring("LH")] * 3 + [_spring("RH")] * 2
        xs = self._xs(springs)
        assert len(xs) == 5
        assert 0 in xs
        assert round(-length, 4) in xs
        assert round(-(length + 6 + length), 4) in xs
        assert round(6 + length, 4) in xs
        assert round(6 + length + 6 + length, 4) in xs

    def test_six_springs_five_pads(self):
        length = _installed()
        springs = [_spring("LH")] * 3 + [_spring("RH")] * 3
        xs = self._xs(springs)
        assert xs == [
            round(-(2 * length + 6), 4),
            round(-length, 4),
            0,
            round(length, 4),
            round(2 * length + 6, 4),
        ]

    def test_duplex_pair_is_one_center_pad(self):
        springs = [
            _spring("LH", coil=6.0),
            _spring("LH", wire=0.225, cut=28, nested=True, coil=3.75),
            _spring("RH", coil=6.0),
            _spring("RH", wire=0.225, cut=28, nested=True, coil=3.75),
        ]
        pads, notes = place_pads(springs, 192)
        assert len(pads) == 1
        assert pads[0].x_from_center_in == 0
        assert any("duplex" in note.lower() for note in notes)

    def test_single_spring_is_centered_and_flagged(self):
        pads, notes = place_pads([_spring("LH")], 120)
        assert len(pads) == 1
        assert pads[0].x_from_left_jamb(120) == 60
        assert any("FLAG JOEY" in note for note in notes)

    def test_different_lengths_use_the_inner_spring(self):
        inner = _spring("LH", cut=20)  # installed 0.25*10+20+3 = 25.5
        outer = _spring("LH", cut=40)
        right = _spring("RH", cut=20)
        right_outer = _spring("RH", cut=40)
        xs = self._xs([inner, outer, right, right_outer])
        assert round(-25.5, 4) in xs
        assert round(25.5, 4) in xs


class TestFramingDetailSheet:
    def _door(self, **overrides):
        door = {
            "doorSeries": "TX450",
            "doorType": "commercial",
            "doorWidth": 240,
            "doorHeight": 168,
            "liftType": "standard",
            "trackThickness": "2",
            "trackRadius": "15",
            "operator": "NONE",
        }
        door.update(overrides)
        return door

    def test_four_spring_detail_is_dimensioned_from_jambs_and_center(self):
        springs = [_spring("LH"), _spring("LH"), _spring("RH"), _spring("RH")]
        detail = build_framing_detail(
            self._door(),
            springs=springs,
            drum_model="D525-216",
            coupler_qty=1,
            door_weight_lb=800,
        )
        assert detail.pad_count == 3
        assert detail.track.headroom_in == 15.75
        assert detail.sideroom_in == 3.5
        assert detail.workbook_sheet == "3 Pads,  Jamb and Extension Dwg"
        center = next(pad for pad in detail.pads if pad.role == "center")
        assert center.x_from_left_jamb(240) == 120
        text = "\n".join(sheet_lines(detail)).lower()
        for banned in ("price", "cost", "margin", "$"):
            assert banned not in text

    def test_tandem_headroom_and_sheet(self):
        detail = build_framing_detail(
            self._door(doorWidth=192),
            springs=[_spring("LH"), _spring("RH")],
            is_tandem=True,
            drum_model="D400-144",
            coupler_qty=1,
        )
        assert detail.pad_count == 1
        assert detail.track.headroom_in == 15.75 + 12
        assert detail.workbook_sheet == "Cen Pad,  Jamb and Exten Tandem"
        assert any("Tandem" in note or "tandem" in note for note in detail.notes)

    def test_high_lift_extension_on_the_detail(self):
        detail = build_framing_detail(
            self._door(liftType="high_lift", highLiftInches=45, trackThickness="3", doorHeight=240),
            springs=[_spring("LH"), _spring("RH")],
            coupler_qty=0,
        )
        assert detail.track.high_lift_in == 45
        assert detail.track.extension_in == 45 - 15 + 8
        assert detail.track.ust_sheet_in == 240 + 45

    def test_operator_plate_is_20_by_30_and_absent_for_a_hoist(self):
        electric = build_framing_detail(
            self._door(operator="OP19-01048-00", operatorSide="left"),
            springs=[_spring("LH"), _spring("RH")],
        )
        assert electric.operator_plate is True
        text = "\n".join(sheet_lines(electric))
        assert '20" × 30"' in text
        hoist = build_framing_detail(
            self._door(operator="NONE", chainHoist="shaft"),
            springs=[_spring("LH"), _spring("RH")],
        )
        assert hoist.operator == "CHAIN_HOIST"
        assert hoist.operator_plate is False

    def test_residential_jamb_uses_wood_sideroom(self):
        detail = build_framing_detail(
            self._door(doorType="residential", jambType="wood"),
            springs=[_spring("LH"), _spring("RH")],
        )
        assert detail.sideroom_in == 3.75

    def test_pdf_and_dxf_for_each_spring_count(self):
        for count, hands in (
            (2, ["LH", "RH"]),
            (3, ["LH", "LH", "RH"]),
            (4, ["LH", "LH", "RH", "RH"]),
            (5, ["LH", "LH", "LH", "RH", "RH"]),
            (6, ["LH", "LH", "LH", "RH", "RH", "RH"]),
        ):
            detail = build_framing_detail(
                self._door(),
                springs=[_spring(hand) for hand in hands],
                drum_model="D525-216",
                coupler_qty=1,
            )
            assert detail.spring_count == count
            pdf = __import__(
                "app.services.shop_drawings.framing_detail", fromlist=["detail_to_pdf"]
            ).detail_to_pdf(detail)
            assert pdf.startswith(b"%PDF")
            dxf = __import__(
                "app.services.shop_drawings.framing_detail", fromlist=["detail_to_dxf"]
            ).detail_to_dxf(detail)
            assert b"CENTER PAD" in dxf or b"FRAMING DETAIL" in dxf

    def test_non_tx_falls_back_to_the_shop_drawing(self):
        assert framing_detail_kind("TX450") == "thermalex"
        assert framing_detail_kind("TX450-20") == "thermalex"
        assert framing_detail_kind("TX500") == "thermalex"
        assert framing_detail_kind("SHXL") == "shop"
        assert framing_detail_kind("PANORAMA") == "shop"
        pdf = generate_framing_detail(
            config_data={"doors": [{
                "doorSeries": "SHXL",
                "doorType": "residential",
                "doorWidth": 192,
                "doorHeight": 96,
            }]},
            customer_name="Test",
            job_number="T-1",
            fmt="pdf",
        )
        assert pdf.startswith(b"%PDF")
        assert b"OpenDC framing detail" not in pdf

    def test_differences_are_recorded(self):
        blob = " ".join(DIFFERENCES_FOR_JOEY).lower()
        assert "w/4" in blob
        assert "73" in blob
        assert "8 in." in blob
        assert "tandem" in blob
        assert "ola" in blob
        assert "3.62" in blob


class TestEverySheetDrawsItsComponents:
    """Each of the nine Thermalex layouts draws the components on that sheet."""

    def _door(self, **overrides):
        door = {
            "doorSeries": "TX450",
            "doorType": "commercial",
            "doorWidth": 240,
            "doorHeight": 168,
            "liftType": "standard",
            "trackThickness": "3",
            "trackRadius": "15",
            "operator": "OP19-01048-00",
        }
        door.update(overrides)
        return door

    def _detail(self, hands, tandem=False, couplers=1, jamb="steel"):
        return build_framing_detail(
            self._door(jambType=jamb),
            springs=[_spring(hand) for hand in hands],
            drum_model="D525-216",
            coupler_qty=couplers,
            is_tandem=tandem,
            door_weight_lb=900,
        )

    def test_nine_layouts_include_every_component(self):
        cases = [
            ("center", ["LH", "RH"], False, 1),
            ("center tandem", ["LH", "RH"], True, 1),
            ("2 pads, 2 couplers", ["LH", "LH"], False, 2),
            ("2 pads, 1 coupler", ["LH", "LH"], False, 1),
            ("2 pads tandem", ["LH", "LH"], True, 1),
            ("3 pads", ["LH", "LH", "RH", "RH"], False, 1),
            ("3 pads tandem", ["LH", "LH", "RH", "RH"], True, 1),
            ("4 pads", ["LH", "LH", "LH", "RH"], False, 2),
            ("5 pads", ["LH", "LH", "LH", "RH", "RH"], False, 3),
        ]
        seen = set()
        for name, hands, tandem, couplers in cases:
            detail = self._detail(hands, tandem=tandem, couplers=couplers)
            seen.add(detail.workbook_sheet)
            text = "\n".join(layout_labels(detail))
            missing = [item for item in required_components(detail) if item not in text]
            assert not missing, f"{name} / {detail.workbook_sheet} missing {missing}"
            dxf = detail_to_dxf(detail).decode("utf-8")
            for item in required_components(detail):
                assert item in dxf, f"{name} DXF missing {item}"
        assert len(seen) == 9
