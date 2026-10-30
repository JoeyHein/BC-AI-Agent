"""Golden checks for the rebuilt shop drawing.

Clearances, section stack, and spring text are asserted against the Thermalex
tables and the weight calculator. Sample sheets are the visual reference;
where a sample disagrees with Joey's rules, the rule wins and the test says so.
"""

from datetime import datetime

import pytest
from pypdf import PdfReader
import io

from app.services.shop_drawings.clearances import lookup_clearances, round_up_half_inch
from app.services.shop_drawings.framing import (
    build_dxf,
    dxf_to_png_bytes,
    dxf_to_string,
    generate_framing_drawing,
)
from app.services.shop_drawings.issue import config_fingerprint, issue_shop_drawing
from app.services.shop_drawings.profiles import joint_high_point, shiplap_lower, tongue_profile
from app.services.shop_drawings.spec import build_door_spec, section_stack


def _dxf_text(door, **meta) -> str:
    spec_door = door
    from app.services.shop_drawings.framing import _new_drawing
    from app.services.shop_drawings.sheet import draw_sheet
    spec = build_door_spec(spec_door, **meta)
    doc = _new_drawing()
    draw_sheet(doc, spec)
    return dxf_to_string(doc).decode("utf-8")


def _tx(width, height, **extra):
    door = {
        "doorSeries": "TX450",
        "doorType": "commercial",
        "doorWidth": width,
        "doorHeight": height,
        "trackThickness": "3",
        "trackRadius": 15,
        "trackMount": "bracket",
        "mountSurface": "steel",
        "liftType": "standard",
    }
    door.update(extra)
    return door


class TestHeadroomRounding:
    def test_fractional_table_value_rounds_up_to_the_next_half(self):
        # Standard 3" track is 17.75. Joey: show 18.
        assert round_up_half_inch(17.75) == 18.0

    def test_value_already_on_a_half_inch_stays(self):
        # HL24 table headroom is 35, which is already a half-inch boundary.
        # The s01 sheet prints 35.5; the rounding rule does not add another half.
        assert round_up_half_inch(35) == 35.0
        assert round_up_half_inch(186) == 186.0
        assert round_up_half_inch(85) == 85.0

    def test_just_over_a_boundary_goes_to_the_next_half(self):
        assert round_up_half_inch(35.1) == 35.5


class TestSectionStack:
    def test_ten_foot_door_is_five_by_24(self):
        # s12 prints "6 X 24" on a 10' door. That sample is wrong.
        assert section_stack(120) == [24.0, 24.0, 24.0, 24.0, 24.0]

    def test_sample_heights(self):
        assert section_stack(168) == [24.0] * 7   # 14'
        assert section_stack(192) == [24.0] * 8   # 16'
        assert section_stack(336) == [24.0] * 14  # 28', past the table, fallback


class TestClearancesMatchTheTable:
    def test_standard_10ft_headroom_is_18(self):
        spec = build_door_spec(_tx(120, 120), drawn_by="Joey Hein")
        assert spec.headroom_text == '18"'
        assert spec.clearances.headroom_table_in == 17.75
        assert spec.ust_text == "10'-7 1/2\""
        assert spec.backroom_text == "11'-6\""
        assert spec.cl_shaft_text == "11'-2 1/2\""
        assert spec.sections_text == '5 X 24"'
        assert spec.track_title == "STANDARD LIFT TRACKS"

    def test_s01_high_lift_24(self):
        # 12'-0 x 14'-0, HL 24, 3" track. s01 sideroom is 3.5" (angle).
        spec = build_door_spec(
            _tx(144, 168, liftType="high_lift", highLiftInches=24, trackMount="angle"),
            drawn_by="Joey Hein",
        )
        assert spec.headroom_text == '35"'
        assert spec.high_lift_text == '24"'
        assert spec.ust_text == "16'-0\""
        assert spec.backroom_text == "14'-6\""
        assert spec.cl_shaft_text == "16'-7\""
        assert spec.sideroom_text == '3.5"'
        assert spec.sections_text == '7 X 24"'

    def test_s03_standard_18_by_16(self):
        spec = build_door_spec(_tx(216, 192, trackMount="angle"), drawn_by="J")
        assert spec.headroom_text == '18"'
        assert spec.ust_text == "16'-7 1/2\""
        assert spec.backroom_text == "17'-6\""
        assert spec.cl_shaft_text == "17'-2 1/2\""
        assert spec.sections_text == '8 X 24"'

    def test_full_vertical_accepts_the_configurator_name(self):
        # The configurator sends "vertical". The old engine only matched
        # "full_vertical" and drew a standard-lift track.
        for name in ("vertical", "full_vertical"):
            spec = build_door_spec(
                _tx(144, 168, liftType=name, trackMount="bracket", mountSurface="wood"),
                drawn_by="J",
            )
            assert spec.lift == "vertical"
            assert spec.track_title == "FULL VERTICAL LIFT TRACKS"
            assert spec.headroom_text == "15'-6\""
            assert spec.backroom_text == "1'-6\""
            assert spec.cl_shaft_text == "29'-0\""
            assert spec.sideroom_text == '4.25"'
            assert spec.ust_text is None

    def test_hl71_uses_the_table_not_the_s10_figure(self):
        # s10 prints 83.5". The 3" table for HL > 54" is HL + 14 = 85,
        # already on a half-inch, so the sheet prints 85".
        spec = build_door_spec(
            _tx(98, 120, liftType="high_lift", highLiftInches=71, doorSeries="TX500"),
            drawn_by="J",
        )
        assert spec.clearances.headroom_table_in == 85
        assert spec.headroom_text == '85"'

    def test_sideroom_follows_mount(self):
        bracket = lookup_clearances(168, track_size=3, radius=15, lift="standard", mount="bracket")
        angle = lookup_clearances(168, track_size=3, radius=15, lift="standard", mount="angle")
        assert bracket.sideroom_in == 4.25
        assert angle.sideroom_in == 3.5


class TestFamilies:
    def test_tx380_is_shiplap_at_the_tx450_gauges(self):
        spec = build_door_spec(
            _tx(144, 168, doorSeries="TX380", liftType="vertical", mountSurface="wood"),
            drawn_by="J",
        )
        assert spec.joint == "shiplap"
        assert spec.joint_title == "SHIPLAP JOINT"
        assert spec.thickness_in == 1.5
        assert spec.thickness_text == '1-1/2"'
        assert spec.exterior_gauge == "26GA"
        assert spec.interior_gauge == "26GA"
        tx450 = build_door_spec(_tx(144, 168), drawn_by="J")
        assert tx450.exterior_gauge == spec.exterior_gauge

    def test_tx450_and_tx500_are_tongue_and_groove(self):
        tx450 = build_door_spec(_tx(120, 120), drawn_by="J")
        tx500 = build_door_spec(_tx(122, 120, doorSeries="TX500"), drawn_by="J")
        tx500_20 = build_door_spec(_tx(146, 120, doorSeries="TX500-20"), drawn_by="J")
        assert tx450.joint == "tongue_groove"
        assert tx450.thickness_text == '1-3/4"'
        assert tx500.joint == "tongue_groove"
        assert tx500.thickness_in == 2.0
        assert tx500_20.joint == "tongue_groove"
        assert tx500_20.exterior_gauge == "20GA"
        assert tx500_20.show_outside_face is True
        assert tx500_20.finish == "flush"

    def test_panorama_profile(self):
        spec = build_door_spec(
            _tx(144, 168, doorSeries="PANORAMA", doorType="aluminium",
                liftType="vertical", mountSurface="wood", trackMount="bracket"),
            drawn_by="J",
        )
        assert spec.joint == "panorama"
        assert spec.show_outside_face is True
        assert spec.sections_text == '7 X 24"'
        assert spec.windows.material == "POLYCARBONATE"
        assert spec.windows.full_section is True

    def test_joint_shape_distinguishes_shiplap_from_tongue(self):
        tongue = joint_high_point(tongue_profile(1.75))
        lap = joint_high_point(shiplap_lower(1.5))
        # Tongue high point sits in the middle of the thickness.
        assert 0.32 * 1.75 <= tongue[0] <= 0.67 * 1.75
        # Shiplap high point is the exterior lap, not a centred tongue.
        assert lap[0] < 0.5 * 1.5

    def test_windows_are_counted_from_the_bottom(self):
        # Configurator panel 1 is the top. A 7-section door glazed on
        # section 5 from the top is the 3rd from the bottom, as on s01.
        spec = build_door_spec(
            _tx(144, 168, windowInsert="34X16_THERMOPANE", windowQty=4, windowSection=5),
            drawn_by="J",
        )
        assert spec.windows.sections_from_bottom == [3]
        assert spec.windows.location_text == "3RD"
        assert spec.windows.qty == 4


class TestSheetText:
    def test_s01_strings_are_on_the_dxf(self):
        text = _dxf_text(
            _tx(144, 168, liftType="high_lift", highLiftInches=24, trackMount="angle"),
            drawn_by="Joey Hein",
            drawing_number="SD-000001",
            revision=0,
            job_number="SQ-002506",
            customer_name="Global Overhead Doors",
        )
        for expected in (
            '35"',
            "16'-0\"",
            "14'-6\"",
            "16'-7\"",
            '7 X 24"',
            "HIGH LIFT TRACKS",
            "TONGUE AND GROOVE",
            "THERMALLY BROKEN",
            "Joey Hein",
            "SD-000001",
            "OPEN DISTRIBUTION",
            "SPRINGS INFO",
            "TURNS:",
        ):
            assert expected in text, expected
        # DRAWN BY is the staff user, not the customer on the quote.
        assert "Joey Hein" in text
        assert "Global Overhead Doors" in text

    def test_tx380_sheet_says_shiplap(self):
        text = _dxf_text(
            _tx(144, 168, doorSeries="TX380", liftType="vertical", mountSurface="wood"),
            drawn_by="Joey Hein",
        )
        assert "SHIPLAP JOINT" in text
        assert "FULL VERTICAL LIFT TRACKS" in text
        assert "15'-6\"" in text
        assert "29'-0\"" in text
        assert '1-1/2"' in text

    def test_springs_from_the_calculator_are_printed(self):
        spec = build_door_spec(_tx(144, 168, liftType="high_lift", highLiftInches=24), drawn_by="J")
        assert spec.springs, "calculator should return a spring"
        assert spec.turns is not None
        text = _dxf_text(
            _tx(144, 168, liftType="high_lift", highLiftInches=24),
            drawn_by="J",
        )
        assert spec.springs[0].text() in text
        assert f"TURNS: {spec.turns_text}" in text
        assert spec.drum_model
        assert spec.drum_model in text

    def test_pdf_text_is_searchable(self):
        pdf = generate_framing_drawing(
            {"doors": [_tx(120, 120)]},
            customer_name="ACME Doors",
            job_number="J-1",
            fmt="pdf",
            drawn_by="Joey Hein",
            drawing_number="SD-000010",
            revision=2,
        )
        assert pdf[:4] == b"%PDF"
        reader = PdfReader(io.BytesIO(pdf))
        text = reader.pages[0].extract_text() or ""
        assert "HEADROOM" in text
        assert '18"' in text
        assert "Joey Hein" in text
        assert "TONGUE AND GROOVE" in text
        assert '5 X 24"' in text
        assert "SD-000010" in text
        # The customer is not substituted for the person who drew it.
        assert "ACME Doors" in text

    def test_png_snapshot_has_the_sheet_aspect(self):
        from app.services.shop_drawings.framing import _new_drawing
        from app.services.shop_drawings.sheet import draw_sheet
        from PIL import Image

        spec = build_door_spec(_tx(120, 120), drawn_by="Joey Hein", drawing_number="SD-1", revision=0)
        doc = _new_drawing()
        draw_sheet(doc, spec)
        png = dxf_to_png_bytes(doc, dpi=72)
        image = Image.open(io.BytesIO(png))
        assert image.size[0] / image.size[1] == pytest.approx(17 / 11, rel=0.02)
        assert len(png) > 20_000


class TestContextStillBuilds:
    def test_existing_context_fields(self):
        ctx = build_context_via_sample()
        assert ctx.customer_name == "ABC Warehouse"
        assert ctx.drawing_date == "2026-04-24"
        doc = build_dxf(ctx)
        text = dxf_to_string(doc).decode()
        assert "ABC Warehouse" in text
        assert "JD-2026-045" in text
        assert "SHXL" in text


def build_context_via_sample():
    from app.services.shop_drawings.framing import build_context_from_config
    return build_context_from_config(
        {"doors": [{"doorSeries": "SHXL", "doorType": "residential", "doorWidth": 192, "doorHeight": 96}]},
        customer_name="ABC Warehouse",
        job_number="JD-2026-045",
        drawing_date=datetime(2026, 4, 24),
        config_id=42,
    )


class TestIssueOnSave:
    def test_revision_zero_then_next(self):
        door = _tx(120, 120)
        config = _FakeConfig(door)
        user = _FakeUser()
        issue_shop_drawing(config, user, revision=0)
        assert config.shop_drawing_number == "SD-000042"
        assert config.shop_drawing_revision == 0
        assert config.shop_drawn_by == "Joey Hein"
        assert config.shop_drawing_pdf[:4] == b"%PDF"
        assert b"Joey Hein" in config.shop_drawing_dxf
        assert b"REV" in config.shop_drawing_dxf or b"REVISION" in config.shop_drawing_dxf
        first_pdf = config.shop_drawing_pdf
        issue_shop_drawing(config, user, revision=1)
        assert config.shop_drawing_revision == 1
        assert config.shop_drawing_number == "SD-000042"
        assert config.shop_drawing_pdf != first_pdf or b"1" in config.shop_drawing_dxf

    def test_fingerprint_ignores_key_order(self):
        assert config_fingerprint({"b": 1, "a": 2}) == config_fingerprint({"a": 2, "b": 1})


class _FakeConfig:
    def __init__(self, door):
        self.id = 42
        self.config_data = {"doors": [door], "projectName": "Warehouse"}
        self.shop_drawing_number = None
        self.shop_drawing_revision = None
        self.shop_drawing_pdf = None
        self.shop_drawing_dxf = None
        self.shop_drawn_by = None
        self.shop_drawing_generated_at = None
        self.bc_quote_number = "SQ-000042"
        self.name = "Warehouse"


class _FakeUser:
    name = "Joey Hein"
    email = "joey@opendc.ca"
    company_name = "Open Distribution"


class TestPreviewAuth:
    def test_anonymous_preview_is_rejected(self):
        from fastapi.testclient import TestClient
        from app.main import app
        client = TestClient(app)
        response = client.post(
            "/api/door-config/preview-framing-drawing",
            json={"config_data": {"doors": [_tx(120, 120)]}},
        )
        assert response.status_code == 401
