"""Stage 1 tests for the framing shop drawing pipeline."""

import pytest
from datetime import datetime

from app.services.shop_drawings.framing import (
    DrawingContext,
    build_context_from_config,
    build_dxf,
    dxf_to_pdf_bytes,
    dxf_to_string,
    generate_framing_drawing,
)


SAMPLE_CONFIG = {
    "doors": [
        {
            "doorSeries": "SHXL",
            "doorType": "residential",
            "doorWidth": 192,
            "doorHeight": 96,
            "doorCount": 1,
        }
    ]
}


class TestContextBuilder:
    def test_basic_fields_populate(self):
        ctx = build_context_from_config(
            config_data=SAMPLE_CONFIG,
            customer_name="ABC Warehouse",
            job_number="JD-2026-045",
            drawing_date=datetime(2026, 4, 24),
            config_id=42,
        )
        assert ctx.job_number == "JD-2026-045"
        assert ctx.customer_name == "ABC Warehouse"
        assert ctx.door_series == "SHXL"
        assert ctx.door_width_in == 192
        assert ctx.door_height_in == 96
        assert ctx.drawing_date == "2026-04-24"

    def test_missing_doors_raises(self):
        with pytest.raises(ValueError, match="no doors"):
            build_context_from_config(
                config_data={"doors": []},
                customer_name="x",
                job_number="x",
            )

    def test_chain_hoist_maps_to_geared_hoist(self):
        config = {
            "doors": [{
                "doorSeries": "AL976",
                "doorType": "aluminium",
                "doorWidth": 120,
                "doorHeight": 96,
                "operator": "NONE",
                "chainHoist": "shaft",
            }]
        }
        ctx = build_context_from_config(
            config_data=config,
            customer_name="x",
            job_number="x",
        )
        assert ctx.operator == "CHAIN_HOIST"

    def test_electric_operator_wins_over_chain_hoist(self):
        config = {
            "doors": [{
                "doorSeries": "TX450",
                "doorType": "commercial",
                "doorWidth": 144,
                "doorHeight": 144,
                "operator": "OP19-01048-00",
                "chainHoist": "shaft",
            }]
        }
        ctx = build_context_from_config(
            config_data=config,
            customer_name="x",
            job_number="x",
        )
        assert ctx.operator == "OP19-01048-00"

    def test_door_index_out_of_range(self):
        with pytest.raises(ValueError, match="out of range"):
            build_context_from_config(
                config_data=SAMPLE_CONFIG,
                customer_name="x",
                job_number="x",
                door_index=5,
            )


class TestDxfBuild:
    def test_dxf_contains_title_block_text(self):
        ctx = DrawingContext(
            job_number="JD-2026-045",
            customer_name="ABC Warehouse",
            door_series="SHXL",
            door_type="residential",
            door_width_in=192,
            door_height_in=96,
            door_count=1,
            drawing_date="2026-04-24",
        )
        doc = build_dxf(ctx)
        dxf_bytes = dxf_to_string(doc)
        text = dxf_bytes.decode("utf-8")

        # Title block strings must be present
        assert "JD-2026-045" in text          # populated in PROJECT NAME / JOB # cell
        assert "ABC Warehouse" in text
        assert "SHXL" in text                  # series shown in SERIES cell + big banner
        assert "OPEN DISTRIBUTION" in text
        # Reference-style fields
        assert "ELECTRIC" in text and "OPERATOR" in text  # electric operator spec row
        assert "SPRINGS INFO" in text
        assert "DOOR OPENING" in text
        assert "SECTIONS" in text

    def test_dxf_has_expected_layers(self):
        ctx = DrawingContext(
            job_number="J1", customer_name="C", door_series="SHXL",
            door_type="residential", door_width_in=192, door_height_in=96,
            door_count=1, drawing_date="2026-04-24",
        )
        doc = build_dxf(ctx)
        layer_names = {layer.dxf.name for layer in doc.layers}
        for required in ("BORDER", "TITLE_BLOCK", "FRAMING", "TRACKS",
                         "DIMENSIONS", "ANNOTATIONS", "HIDDEN"):
            assert required in layer_names, f"missing layer {required}"

    def test_dxf_is_r2013(self):
        ctx = DrawingContext(
            job_number="J1", customer_name="C", door_series="SHXL",
            door_type="residential", door_width_in=192, door_height_in=96,
            door_count=1, drawing_date="2026-04-24",
        )
        doc = build_dxf(ctx)
        assert doc.dxfversion == "AC1027"  # R2013

    def test_units_set_to_inches(self):
        ctx = DrawingContext(
            job_number="J1", customer_name="C", door_series="SHXL",
            door_type="residential", door_width_in=192, door_height_in=96,
            door_count=1, drawing_date="2026-04-24",
        )
        doc = build_dxf(ctx)
        assert doc.header["$INSUNITS"] == 1  # 1 = inches
        assert doc.header["$MEASUREMENT"] == 0  # 0 = imperial


class TestPdfExport:
    def test_pdf_is_valid_pdf(self):
        pdf = generate_framing_drawing(
            config_data=SAMPLE_CONFIG,
            customer_name="ABC Warehouse",
            job_number="JD-2026-045",
            fmt="pdf",
            drawing_date=datetime(2026, 4, 24),
            config_id=42,
        )
        assert pdf[:4] == b"%PDF"
        assert len(pdf) > 1000  # non-trivial PDF

    def test_dxf_format(self):
        dxf = generate_framing_drawing(
            config_data=SAMPLE_CONFIG,
            customer_name="ABC Warehouse",
            job_number="JD-2026-045",
            fmt="dxf",
            drawing_date=datetime(2026, 4, 24),
            config_id=42,
        )
        # DXF starts with the SECTION header
        assert b"SECTION" in dxf[:100]
        assert b"HEADER" in dxf[:200]

    def test_unsupported_format_raises(self):
        with pytest.raises(ValueError, match="Unsupported format"):
            generate_framing_drawing(
                config_data=SAMPLE_CONFIG,
                customer_name="x", job_number="x", fmt="svg",
            )


class TestSizeFormatting:
    def test_multi_door_prefix(self):
        from app.services.shop_drawings.framing import _fmt_size
        assert _fmt_size(192, 96, 3) == "(3) 16'-0\" x 8'-0\""

    def test_single_door_no_prefix(self):
        from app.services.shop_drawings.framing import _fmt_size
        assert _fmt_size(108, 84, 1) == "9'-0\" x 7'-0\""

    def test_partial_inches_preserved(self):
        from app.services.shop_drawings.framing import _fmt_size
        assert _fmt_size(110, 85, 1) == "9'-2\" x 7'-1\""


class TestLengthDualFormat:
    def test_basic_conversion(self):
        from app.services.shop_drawings.framing import fmt_length_dual
        assert fmt_length_dual(192) == "16'-0\" [4877mm]"
        assert fmt_length_dual(96) == "8'-0\" [2438mm]"

    def test_partial_inches(self):
        from app.services.shop_drawings.framing import fmt_length_dual
        # 110.5" = 9'-2.5" = 2806.7mm → rounds to 2807mm
        assert fmt_length_dual(110.5) == "9'-2.5\" [2807mm]"

    def test_zero_length(self):
        from app.services.shop_drawings.framing import fmt_length_dual
        assert fmt_length_dual(0) == "0'-0\" [0mm]"


# Normalized DXF hashes of the schematic sheet, with the flag off.
# Header clocks, ezdxf GUIDs, and the "ezdxf x.y.z @ timestamp" comment
# move between writes. CLASS records (LAYOUT vs ACDBPLACEHOLDER) are
# also emitted in either order, so those records are sorted before hashing.
_VOLATILE_HEADER = {
    "$TDCREATE", "$TDUCREATE", "$TDUPDATE", "$TDUUPDATE",
    "$TDINDWG", "$TDUSRTIMER", "$FINGERPRINTGUID", "$VERSIONGUID",
}
_FLAG_OFF_SHA256 = {
    "shxl_wood": "98c16517601e474773fc1b8b76206c6c98e08acaf04a29d6b200922cd955be14",
    "tx450_steel": "544ff95918fc2a2a847eeeb7ce2582262aba70ad7827260e1feb5e59f98abf3e",
    "tx450_wood": "385c469b30e22552228df35c734034f74e03bee3a66b725ad2291a98420c8021",
    "tx380_steel": "1096bdd1d172fd66c310478b0ebc4b01b7885a606ccf9a0c984c609c56bd0cea",
    "tx380_wood": "339d951877508db3439167627c2f6641866b1fac4d950d1742ea4f8d28afa5a2",
    "tx500_steel": "3402f9ae3d35db9b9e84e65d30c09579c7c6201080f75d0a69085f7c9eb21977",
    "tx450_20": "75a1a1422950873d003ef2b9b0a8945d686a5afcb16a8f2fe2809f7bc4a7c378",
    "pano_wood": "67daaa008c5339e7b90aebdef9b3c90c24d1e837e18c444d7b0d304dd97acee7",
}


def _class_name(block: list[str]) -> str:
    for i, line in enumerate(block[:-1]):
        if line.strip() == "1":
            return block[i + 1].strip()
    return ""


def _normalize_dxf(raw: bytes) -> bytes:
    import re
    lines = raw.decode("utf-8").splitlines()
    cleaned = []
    i = 0
    while i < len(lines):
        token = lines[i].strip()
        if token in _VOLATILE_HEADER and i + 2 < len(lines):
            cleaned.append(lines[i])
            cleaned.append(lines[i + 1])
            cleaned.append("<volatile>")
            i += 3
            continue
        if re.match(r"\d+\.\d+\.\d+ @ ", token):
            cleaned.append("<volatile>")
            i += 1
            continue
        cleaned.append(lines[i])
        i += 1

    out = []
    i = 0
    while i < len(cleaned):
        # Group code 0 is the three-character field "  0". A numeric
        # value of 0 is just "0", so the two must not be confused.
        is_class = (
            cleaned[i] == "  0"
            and i + 1 < len(cleaned)
            and cleaned[i + 1].strip() == "CLASS"
        )
        if not is_class:
            out.append(cleaned[i])
            i += 1
            continue
        blocks = []
        while (
            i < len(cleaned)
            and cleaned[i] == "  0"
            and i + 1 < len(cleaned)
            and cleaned[i + 1].strip() == "CLASS"
        ):
            start = i
            i += 2
            while i < len(cleaned) and cleaned[i] != "  0":
                i += 1
            blocks.append(cleaned[start:i])
        for block in sorted(blocks, key=_class_name):
            out.extend(block)
    return ("\n".join(out) + "\n").encode()


def _profile_context(**overrides) -> DrawingContext:
    fields = dict(
        job_number="J1",
        customer_name="C",
        door_series="TX450",
        door_type="commercial",
        door_width_in=96,
        door_height_in=96,
        door_count=1,
        drawing_date="2026-04-24",
        section_height_in=24,
        jamb_type="steel",
    )
    fields.update(overrides)
    return DrawingContext(**fields)


def _dxf_text(ctx: DrawingContext) -> str:
    return dxf_to_string(build_dxf(ctx)).decode("utf-8")


class TestRealProfilesFlagOff:
    def test_schematic_bytes_match_today(self):
        import hashlib
        samples = {
            "shxl_wood": _profile_context(
                door_series="SHXL", door_type="residential", section_height_in=21,
                jamb_type="wood", door_width_in=192, door_height_in=96,
            ),
            "tx450_steel": _profile_context(door_series="TX450", jamb_type="steel"),
            "tx450_wood": _profile_context(door_series="TX450", jamb_type="wood"),
            "tx380_steel": _profile_context(door_series="TX380", jamb_type="steel"),
            "tx380_wood": _profile_context(door_series="TX380", jamb_type="wood"),
            "tx500_steel": _profile_context(door_series="TX500", jamb_type="steel"),
            "tx450_20": _profile_context(door_series="TX450-20", jamb_type="steel"),
            "pano_wood": _profile_context(
                door_series="PANORAMA", door_type="aluminium",
                section_height_in=21, jamb_type="wood",
            ),
        }
        for name, ctx in samples.items():
            assert ctx.real_profiles is False
            digest = hashlib.sha256(_normalize_dxf(dxf_to_string(build_dxf(ctx)))).hexdigest()
            assert digest == _FLAG_OFF_SHA256[name], name

    def test_missing_setting_leaves_the_schematic(self):
        from app.services.shop_drawing_settings import real_profiles_enabled
        assert real_profiles_enabled(None) is False


class TestRealProfilesFlagOn:
    def _on(self, **overrides) -> str:
        return _dxf_text(_profile_context(real_profiles=True, **overrides))

    def test_thickness_comes_from_the_series_number(self):
        from app.services.shop_drawings.real_profiles import (
            nominal_inches,
            parse_tx_series,
            real_panel_thickness_in,
        )
        assert parse_tx_series("TX-450") == (45.0, "")
        assert parse_tx_series("TX450-20") == (45.0, "20")
        assert parse_tx_series("TX-500-20") == (50.0, "20")
        assert parse_tx_series("TX380") == (38.0, "")
        assert nominal_inches(38) == 1.5
        assert nominal_inches(45) == 1.75
        assert nominal_inches(50) == 2.0
        assert real_panel_thickness_in("TX380") == 1.5
        assert real_panel_thickness_in("TX-450") == 1.75
        assert real_panel_thickness_in("TX450-20") == 1.75
        assert real_panel_thickness_in("TX500") == 2.0
        assert real_panel_thickness_in("TX500-20") == 2.0
        assert real_panel_thickness_in("PANORAMA") == 1.75

    def test_tx450_uses_the_supplier_callouts(self):
        text = self._on(door_series="TX450", jamb_type="wood")
        assert '1-3/4"' in text
        assert "FULL" in text and "HINGE" in text and "APPLICATION" in text
        assert "2 STEEL STRIPS" in text
        assert '1-1/4" W' in text
        assert "26GA STUCCO" in text
        assert "EMBOSSED FINISH: WHITE" in text
        assert "20GA STUCCO" not in text
        assert "FOAMED-IN-PLACE" in text
        assert "POLYURETHANE" in text
        assert "POLYURETHENE" not in text
        assert "2.5 PCF" in text
        assert "THERMALLY" in text and "BROKEN" in text
        assert "P.V.C." in text and "RETAINER" in text
        assert "WEATHER SEAL" in text
        assert "BOTTOM ASTRAGAL" in text
        assert "TOP SEAL" in text and "OPTIONAL" in text
        assert "PROVISIONAL" not in text
        assert '3.75"' in text
        assert "RAMSET" in text
        assert "WOOD JAMB APPLICATION" in text

    def test_tx380_is_half_hinge_at_one_and_a_half(self):
        text = self._on(door_series="TX380", jamb_type="steel")
        assert '1-1/2"' in text
        assert "HALF" in text and "HINGE" in text
        assert "STEEL STRIP" in text
        assert "2 STEEL STRIPS" not in text
        assert "26GA STUCCO" in text
        assert "20GA STUCCO" not in text
        assert '1-3/4"' not in text
        assert "POLYURETHANE" in text
        assert "POLYURETHENE" not in text
        assert "SIDEROOM\\P3.5\"" in text
        assert "SIDEROOM\\P3.75\"" not in text
        assert "STEEL JAMB WELD APPLICATION" in text

    def test_tx500_is_the_tx450_joint_at_50mm(self):
        text = self._on(door_series="TX500", jamb_type="steel")
        assert '2" (50 mm)' in text
        assert "2 STEEL STRIPS" in text
        assert "POLYURETHANE" in text
        assert '1-3/4"' not in text
        assert "PROVISIONAL" not in text
        assert '3.5"' in text

    def test_twenty_gauge_exterior_keeps_26ga_interior(self):
        tx450 = self._on(door_series="TX450-20", jamb_type="steel")
        tx500 = self._on(door_series="TX500-20", jamb_type="wood")
        for text in (tx450, tx500):
            assert "20GA STUCCO" in text
            assert "FLUSH WHITE" in text
            assert "26GA STUCCO" in text
            assert "POLYURETHANE" in text
            assert "POLYURETHENE" not in text
        assert '1-3/4"' in tx450
        assert '2" (50 mm)' in tx500
        assert '3.75"' in tx500

    def test_panorama_is_aluminum_full_view(self):
        text = self._on(
            door_series="PANORAMA", door_type="aluminium",
            section_height_in=21, jamb_type="wood",
        )
        assert '1-3/4"' in text
        assert "GLAZING" in text and "MOULDING" in text
        assert "ADJUSTABLE TOP ROLLER" in text
        assert "BOTTOM BRACKET 12GA" in text
        assert "BRACKET12GA" not in text
        assert "WEATHER" in text and "SEAL" in text
        assert "BOTTOM" in text and "ASTRAGAL" in text
        assert "POLYURETHANE" not in text
        assert "PROVISIONAL" not in text
        assert '3.75"' in text

    def test_wood_and_steel_sideroom(self):
        from app.services.shop_drawings.real_profiles import real_sideroom_in
        assert real_sideroom_in("wood") == 3.75
        assert real_sideroom_in("steel") == 3.5
        assert real_sideroom_in("") == 3.75
        wood = self._on(door_series="TX450", jamb_type="wood")
        steel = self._on(door_series="TX450", jamb_type="steel")
        assert "SIDEROOM\\P3.75\"" in wood
        assert "MIN. REQ." in wood and "SIDEROOM" in wood
        assert "SIDEROOM\\P3.5\"" in steel
        assert "SIDEROOM\\P3.75\"" not in steel

    def test_full_sheet_uses_calculator_numbers(self):
        resi = self._on(
            door_series="TX450", door_type="residential",
            door_width_in=192, door_height_in=84, jamb_type="wood",
            lift_type="standard", section_height_in=24,
        )
        assert '0.2437" x 2" ID x 30"' in resi
        assert "1 LH" in resi and "1 RH" in resi
        assert "TURNS 7.9" in resi
        assert "D400-96" in resi
        assert '1" TUBULAR' in resi
        assert "16'-10\"" in resi
        assert "REQ. HEADROOM 1'-3.75\"" in resi
        assert "BACKROOM 8'-6\"" in resi
        assert "3.75\"" in resi
        assert '1-3/4"' in resi
        assert "POLYURETHANE" in resi
        assert "BY FACTORY" in resi

        comm = self._on(
            door_series="TX450", door_type="commercial",
            door_width_in=144, door_height_in=144, jamb_type="steel",
            lift_type="high_lift", high_lift_inches=24, section_height_in=24,
        )
        assert "D400-54" in comm
        assert "0.273" in comm
        assert "TURNS 13.5" in comm
        assert '1" SOLID KEYED' in comm
        assert "REQ. HEADROOM 2'-10\"" in comm
        assert "BACKROOM 12'-6\"" in comm
        assert "UNDERSIDE OF TRACK 14'-0\"" in comm
        assert "HI-LIFT 2'-0\"" in comm
        assert "3.5\"" in comm
        assert "12'-0\"" in comm
        assert "16'-0\"" not in comm

    def test_library_is_the_supplier_linework(self):
        from app.services.shop_drawings.real_profiles import load_profile
        for name, minimum in (
            ("tx450", 1500), ("tx450_20", 1500), ("tx380", 1500),
            ("panorama", 400), ("wood_jamb", 800), ("steel_jamb", 800),
        ):
            lines = sum(1 for item in load_profile(name)["items"] if item[0] == "L")
            assert lines >= minimum, name


class TestShopDrawingFlagSetting:
    def test_round_trip_defaults_off(self):
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from sqlalchemy.pool import StaticPool
        from app.db.models import AppSettings
        from app.services.shop_drawing_settings import (
            REAL_PROFILES,
            real_profiles_enabled,
            set_shop_drawing_mode,
        )
        engine = create_engine(
            "sqlite://",
            future=True,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        AppSettings.__table__.create(engine)
        db = sessionmaker(bind=engine, autoflush=False, autocommit=False)()
        try:
            assert real_profiles_enabled(db) is False
            assert set_shop_drawing_mode(db, REAL_PROFILES, "on") == "on"
            assert real_profiles_enabled(db) is True
            assert set_shop_drawing_mode(db, REAL_PROFILES, "off") == "off"
            assert real_profiles_enabled(db) is False
            with pytest.raises(ValueError):
                set_shop_drawing_mode(db, REAL_PROFILES, "shadow")
        finally:
            db.close()

    def test_generator_reads_the_setting(self):
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from sqlalchemy.pool import StaticPool
        from app.db.models import AppSettings
        from app.services.shop_drawing_settings import REAL_PROFILES, set_shop_drawing_mode
        engine = create_engine(
            "sqlite://",
            future=True,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        AppSettings.__table__.create(engine)
        db = sessionmaker(bind=engine, autoflush=False, autocommit=False)()
        config = {"doors": [{
            "doorSeries": "TX450",
            "doorType": "commercial",
            "doorWidth": 96,
            "doorHeight": 96,
        }]}
        try:
            off = generate_framing_drawing(
                config_data=config, customer_name="C", job_number="J",
                fmt="dxf", drawing_date=datetime(2026, 4, 24), db=db,
            )
            assert b"SIDE VIEW ILLUSTRATION" not in off
            set_shop_drawing_mode(db, REAL_PROFILES, "on")
            on = generate_framing_drawing(
                config_data=config, customer_name="C", job_number="J",
                fmt="dxf", drawing_date=datetime(2026, 4, 24), db=db,
            )
            assert b"SIDE VIEW ILLUSTRATION" in on
            assert b"1-3/4\"" in on
            assert b"POLYURETHANE" in on
            assert b"POLYURETHENE" not in on
        finally:
            db.close()


class TestSheetSize:
    def test_ansi_b_landscape_dimensions(self):
        from app.services.shop_drawings.framing import SHEET_W, SHEET_H
        assert SHEET_W == 17.0
        assert SHEET_H == 11.0

    def test_title_block_fits_within_sheet(self):
        from app.services.shop_drawings.framing import (
            SHEET_W, MARGIN_L, MARGIN_R, TITLE_BLOCK_W, TITLE_BLOCK_H, SHEET_H, MARGIN_B,
        )
        assert TITLE_BLOCK_W <= SHEET_W - MARGIN_L - MARGIN_R
        assert TITLE_BLOCK_H <= SHEET_H - MARGIN_B
