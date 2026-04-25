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
