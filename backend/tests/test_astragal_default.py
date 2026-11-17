"""Bottom rubber defaults to 3" on every door.

Joey, 2026-11: a sales order and its Upwardor PO went out with
PL10-00005-02 (4" astragal) while Upwardor ships PL10-00005-01 (3").
Width no longer steps commercial doors 12' and wider, or any door over
16', up to 4". 4" and 6.5" stay available when someone asks for them.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from app.api.customer_portal import _build_door_config_dict
from app.api.door_configurator import DoorConfigRequest
from app.api.external_door_config import _map_widget_config
from app.integrations.ai.client import ClaudeAIClient
from app.services import so_po_generation_service as svc
from app.services.bc_part_number_mapper import (
    apply_explicit_bottom_rubber,
    explicit_bottom_rubber_inches,
    get_bc_mapper,
)
from app.services.part_number_service import get_parts_for_door_config
from app.services.quote_service import QuoteGenerationService
from tests.test_so_po_generation import _door_header, _line, _setup


THREE = "PL10-00005-01"
FOUR = "PL10-00005-02"
SIX = "PL10-00005-03"
ALUMINUM_THREE = "PL10-00004-00"
TX450_RETAINER = "PL10-00141-00"

# 16' x 14' commercial. The old rule billed 4" rubber at 12' and wider.
_WIDE = {
    "doorType": "commercial",
    "doorSeries": "TX450",
    "doorWidth": 16 * 12,
    "doorHeight": 14 * 12,
    "doorCount": 1,
    "panelColor": "WHITE",
    "panelDesign": "FLUSH",
    "hardware": {
        "panels": True,
        "struts": True,
        "tracks": True,
        "springs": True,
        "hardwareKits": True,
        "weatherStripping": True,
        "bottomRetainer": True,
        "shafts": True,
    },
    "targetCycles": 10000,
    "trackThickness": "3",
    "trackRadius": "15",
    "trackMount": "bracket",
    "liftType": "standard",
}


class _Rules:
    def filter(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def all(self):
        return []


class _DB:
    def query(self, *args, **kwargs):
        return _Rules()


def _legacy_quote(spec):
    return QuoteGenerationService(_DB())._generate_door_items(spec, None)


def _parts(**overrides):
    cfg = dict(_WIDE)
    cfg.update(overrides)
    return get_parts_for_door_config(cfg).get("parts_list", [])


def _astragal(parts):
    return [p for p in parts if p.get("category") == "astragal" and p.get("part_number")]


def _po_item_numbers(monkeypatch, parts):
    """Turn a BOM into an SO, then the Upwardor PO those lines would buy."""
    lines = [_door_header('(1) 16\'0" x 14\'0" TX450, WHITE, FLUSH', 10000)]
    seq = 20000
    for part in parts:
        number = part.get("part_number")
        if not number:
            continue
        row = _line(number, part.get("quantity") or 1, seq=seq)
        row["description"] = part.get("description") or ""
        lines.append(row)
        seq += 10000
    so = {
        "id": "so-1",
        "number": "SO-TEST",
        "customerName": "Acme",
        "salesOrderLines": lines,
    }
    bc, _ = _setup(monkeypatch, so, [])
    svc.build_upwardor_po("SO-TEST", dry_run=False)
    return [body.get("lineObjectNumber") for _, body in bc.lines if body.get("lineType") == "Item"]


class TestDefaultIsThreeInch:
    @pytest.mark.parametrize("width_ft,door_type", [
        (8, "residential"),
        (9, "commercial"),
        (12, "commercial"),
        (16, "commercial"),
        (18, "commercial"),
        (20, "residential"),
        (24, "commercial"),
    ])
    def test_mapper_ignores_width(self, width_ft, door_type):
        part = get_bc_mapper().get_astragal(width_ft, door_type=door_type)
        assert part.part_number == THREE
        assert part.description == 'ASTRAGAL, 3" RESI/COMM BOTTOM RUBBER'

    def test_aluminum_stays_on_its_own_3_inch_part(self):
        part = get_bc_mapper().get_astragal(18, door_type="aluminium")
        assert part.part_number == ALUMINUM_THREE
        spelled = get_bc_mapper().get_astragal(18, door_type="aluminum")
        assert spelled.part_number == ALUMINUM_THREE

    def test_wide_commercial_bom_is_3_inch_and_keeps_the_series_retainer(self):
        parts = _parts()
        astragal = _astragal(parts)
        assert [p["part_number"] for p in astragal] == [THREE]
        assert astragal[0]["quantity"] == 16 * 12
        numbers = {p["part_number"] for p in parts}
        assert FOUR not in numbers
        assert SIX not in numbers
        retainers = [p["part_number"] for p in parts if p.get("category") == "retainer"]
        assert retainers == [TX450_RETAINER, TX450_RETAINER]

    def test_wide_residential_bom_is_3_inch(self):
        parts = _parts(
            doorType="residential",
            doorSeries="KANATA",
            panelDesign="SHXL",
            doorWidth=18 * 12,
            trackThickness="2",
        )
        assert [p["part_number"] for p in _astragal(parts)] == [THREE]

    def test_customer_portal_dict_defaults_to_3_inch(self):
        cfg = _build_door_config_dict(dict(_WIDE))
        assert cfg.get("astragalSize") is None
        parts = get_parts_for_door_config(cfg).get("parts_list", [])
        assert [p["part_number"] for p in _astragal(parts)] == [THREE]

    def test_legacy_email_quote_for_a_wide_door_is_3_inch(self):
        items = _legacy_quote({
            "model": "TX450",
            "quantity": 1,
            "width_ft": 16,
            "width_in": 0,
            "height_ft": 14,
            "height_in": 0,
            "color": "WHITE",
        })
        codes = [item["product_code"] for item in items]
        assert THREE in codes
        assert FOUR not in codes


class TestExplicitFourInch:
    def test_mapper_honours_4_and_6_5(self):
        mapper = get_bc_mapper()
        four = mapper.get_astragal(8, door_type="residential", size_inches=4)
        assert four.part_number == FOUR
        assert four.description == 'ASTRAGAL, 4" RESI/COMM BOTTOM RUBBER'
        six = mapper.get_astragal(8, door_type="commercial", size_inches="6.5")
        assert six.part_number == SIX
        assert six.description == 'ASTRAGAL, 6.5" COMM BOTTOM RUBBER'

    def test_explicit_4_on_aluminum_uses_the_resi_comm_sku(self):
        part = get_bc_mapper().get_astragal(10, door_type="aluminum", size_inches="4")
        assert part.part_number == FOUR

    def test_bom_and_po_keep_an_explicit_4(self, monkeypatch):
        parts = _parts(astragalSize="4")
        assert [p["part_number"] for p in _astragal(parts)] == [FOUR]
        written = _po_item_numbers(monkeypatch, parts)
        assert FOUR in written
        assert THREE not in written
        assert TX450_RETAINER in written

    def test_configurator_request_field_reaches_the_bom(self):
        request = DoorConfigRequest(
            doorType="commercial",
            doorSeries="TX450",
            doorWidth=96,
            doorHeight=84,
            panelColor="WHITE",
            panelDesign="FLUSH",
            astragalSize="4",
        )
        assert request.astragalSize == "4"
        parts = get_parts_for_door_config({
            **_WIDE,
            "doorWidth": 96,
            "doorHeight": 84,
            "astragalSize": request.astragalSize,
        }).get("parts_list", [])
        assert [p["part_number"] for p in _astragal(parts)] == [FOUR]

    def test_customer_portal_passes_an_explicit_4(self):
        cfg = _build_door_config_dict({**_WIDE, "astragalSize": "4"})
        assert cfg["astragalSize"] == "4"
        parts = get_parts_for_door_config(cfg).get("parts_list", [])
        assert [p["part_number"] for p in _astragal(parts)] == [FOUR]

    def test_widget_notes_and_field(self):
        from_notes = _map_widget_config({
            "familyId": "tx450",
            "doorType": "commercial",
            "widthInches": 192,
            "heightInches": 168,
            "notes": 'customer asked for 4" bottom rubber',
        })
        assert from_notes["astragalSize"] == "4"
        from_field = _map_widget_config({
            "familyId": "tx450",
            "doorType": "commercial",
            "widthInches": 144,
            "heightInches": 120,
            "astragalSize": "6.5",
        })
        assert from_field["astragalSize"] == "6.5"
        silent = _map_widget_config({
            "familyId": "tx450",
            "doorType": "commercial",
            "widthInches": 192,
            "heightInches": 168,
        })
        assert "astragalSize" not in silent

    def test_legacy_email_special_feature_stays_4(self):
        items = _legacy_quote({
            "model": "TX450",
            "quantity": 1,
            "width_ft": 9,
            "width_in": 0,
            "height_ft": 8,
            "height_in": 0,
            "color": "WHITE",
            "special_features": "please use 4 inch astragal",
        })
        codes = [item["product_code"] for item in items]
        assert FOUR in codes
        assert THREE not in codes


class TestEmailWording:
    @pytest.mark.parametrize("text,expected", [
        ('need 4" bottom rubber on this door', 4.0),
        ("4 inch astragal", 4.0),
        ("4in bottom seal", 4.0),
        ('bottom rubber: 4"', 4.0),
        ("astragal should be 4 inches", 4.0),
        ("use PL10-00005-02", 4.0),
        ('4" bottom retainer', 4.0),
        ("6.5 inch bottom rubber", 6.5),
        ('6 1/2" astragal', 6.5),
        ("6-1/2 inch bottom seal", 6.5),
        ("3 inch bottom rubber", 3.0),
        ("12' x 16' TX450 white, 4 sections", None),
        ('4" track, 15" radius', None),
        ("4 inch high lift", None),
        ("not 4 inch astragal", None),
        ('do not use 4" bottom rubber', None),
        ('astragal on the 4" track', None),
        ('4" bottom rubber and 6.5" astragal', None),
    ])
    def test_only_an_explicit_rubber_size_counts(self, text, expected):
        assert explicit_bottom_rubber_inches(text) == expected

    def test_a_guessed_4_is_dropped_when_the_email_is_silent(self):
        doors = [{"doorWidth": 192, "doorType": "commercial", "astragalSize": "4"}]
        apply_explicit_bottom_rubber(doors, "Quote please: 16x14 TX450 white")
        assert "astragalSize" not in doors[0]

    def test_an_explicit_email_request_is_written_onto_the_door(self):
        doors = [{"doorWidth": 192, "doorType": "commercial"}]
        apply_explicit_bottom_rubber(doors, 'TX450 16x14, please spec 4" bottom rubber')
        assert doors[0]["astragalSize"] == "4"

    def test_normalizer_keeps_only_an_explicit_non_default_size(self):
        normalize = ClaudeAIClient._normalize_configurator_doors
        guessed = normalize([{
            "doorType": "commercial",
            "doorSeries": "TX450",
            "doorWidth": 192,
            "doorHeight": 168,
            "astragalSize": "4",
        }])
        assert guessed[0]["astragalSize"] == "4"
        silent = normalize([{
            "doorType": "commercial",
            "doorSeries": "TX450",
            "doorWidth": 192,
            "doorHeight": 168,
        }])
        assert "astragalSize" not in silent[0]
        apply_explicit_bottom_rubber(guessed, "16x14 TX450, no rubber size mentioned")
        assert "astragalSize" not in guessed[0]


class TestPurchaseOrderMirrorsTheThreeInchBom:
    def test_upwardor_po_carries_the_3_inch_part(self, monkeypatch):
        parts = _parts()
        written = _po_item_numbers(monkeypatch, parts)
        assert THREE in written
        assert FOUR not in written
        assert TX450_RETAINER in written
