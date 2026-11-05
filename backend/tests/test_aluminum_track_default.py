"""Aluminum doors standard to 3\" track. 2\" stays a real option.

Every aluminum series in the portal (AL976, SWD, Panorama, Solalite)
used to fall through to the 2\" default. Steel doors keep that 2\"
fallback. An explicit trackThickness of \"2\" on an aluminum door still
bills 2\" track and 2\" hardware.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from app.api.customer_portal import _build_door_config_dict, _format_door_description
from app.api.door_configurator import DoorConfigRequest, _parse_door_header
from app.api.external_door_config import _map_widget_config
from app.integrations.ai.client import ClaudeAIClient
from app.services.bc_part_number_mapper import get_bc_mapper
from app.services.part_number_service import DoorConfiguration, get_parts_for_door_config
from app.services.quote_service import QuoteGenerationService
from app.services.shop_drawings.framing import build_context_from_config, build_dxf, dxf_to_string
from app.services.track_defaults import default_track_thickness, resolve_track_thickness


ALUMINUM_SERIES = ["AL976", "SWD", "PANORAMA", "SOLALITE"]
# 10'0" x 8'0" — a stock aluminum size. 8' hits TR03-STDBM-08 directly.
WIDTH = 10 * 12
HEIGHT = 8 * 12


def _door(**overrides):
    cfg = {
        "doorType": "aluminium",
        "doorSeries": "PANORAMA",
        "doorWidth": WIDTH,
        "doorHeight": HEIGHT,
        "doorCount": 1,
        "panelColor": "CLEAR_ANODIZED",
        "panelDesign": "FLUSH",
        "glazingType": "polycarbonate",
        "glassColor": "CLEAR",
        "hasWindows": True,
        "trackRadius": "15",
        "trackMount": "bracket",
        "liftType": "standard",
        "hardware": {
            "tracks": True,
            "springs": True,
            "struts": True,
            "hardwareKits": True,
            "weatherStripping": True,
            "bottomRetainer": True,
            "shafts": True,
        },
    }
    cfg.update(overrides)
    return cfg


def _parts(cfg):
    return get_parts_for_door_config(cfg).get("parts_list", [])


def _one(parts, category):
    rows = [p for p in parts if p.get("category") == category and p.get("part_number")]
    assert rows, f"expected a {category} line, got {[p.get('category') for p in parts]}"
    return rows[0]


def _comment(parts):
    rows = [p for p in parts if p.get("category") == "comment"]
    assert rows
    return rows[0]["description"]


def _assert_sellable(pn, ctx=""):
    item = get_bc_mapper().bc_items.get(pn)
    assert item is not None, f"{ctx}{pn} is not in the BC part catalog"
    assert not item.get("blocked"), f"{ctx}{pn} is blocked and cannot be sold"
    assert float(item.get("unitCost") or 0) > 0, f"{ctx}{pn} has no unit cost"
    return item


class TestTrackDefaultHelper:
    @pytest.mark.parametrize("series", ALUMINUM_SERIES)
    def test_aluminum_series_defaults_to_3(self, series):
        assert default_track_thickness(series, "aluminium") == "3"
        assert resolve_track_thickness(None, series, "aluminium") == "3"
        assert resolve_track_thickness("", series, "aluminium") == "3"
        assert resolve_track_thickness("2", series, "aluminium") == "2"
        assert resolve_track_thickness("2 inch", series, "aluminium") == "2"
        assert resolve_track_thickness("3", series, "aluminium") == "3"

    @pytest.mark.parametrize("series,door_type", [
        ("KANATA", "residential"),
        ("CRAFT", "residential"),
        ("TX450", "commercial"),
        ("TX380", "commercial"),
        ("TX500", "commercial"),
        ("TX760", "commercial"),
    ])
    def test_steel_defaults_stay_2(self, series, door_type):
        assert default_track_thickness(series, door_type) == "2"
        assert resolve_track_thickness(None, series, door_type) == "2"
        assert resolve_track_thickness("3", series, door_type) == "3"


class TestAluminumQuoteLines:
    @pytest.mark.parametrize("series", ALUMINUM_SERIES)
    def test_omitted_track_bills_3_inch_parts(self, series):
        parts = _parts(_door(doorSeries=series))
        track = _one(parts, "track")
        hardware = _one(parts, "hardware")
        assert track["part_number"].startswith("TR03-"), track
        assert hardware["part_number"].startswith("HK03-"), hardware
        _assert_sellable(track["part_number"], f"{series} default track ")
        _assert_sellable(hardware["part_number"], f"{series} default hardware ")
        assert '3"' in _comment(parts)
        assert '2"' not in _comment(parts)

    @pytest.mark.parametrize("series", ALUMINUM_SERIES)
    def test_explicit_2_inch_still_bills_2_inch_parts(self, series):
        default_parts = _parts(_door(doorSeries=series))
        chosen = _parts(_door(doorSeries=series, trackThickness="2"))
        track = _one(chosen, "track")
        hardware = _one(chosen, "hardware")
        assert track["part_number"].startswith("TR02-"), track
        assert hardware["part_number"].startswith("HK02-"), hardware
        two = _assert_sellable(track["part_number"], f"{series} 2\" track ")
        three = _assert_sellable(_one(default_parts, "track")["part_number"])
        assert track["part_number"] != _one(default_parts, "track")["part_number"]
        assert hardware["part_number"] != _one(default_parts, "hardware")["part_number"]
        assert two["unitCost"] != three["unitCost"]
        assert '2"' in _comment(chosen)
        assert '3"' not in _comment(chosen)

    def test_door_configuration_omitted_track_follows_series(self):
        aluminum = DoorConfiguration(
            door_type="aluminium", door_series="PANORAMA",
            door_width=WIDTH, door_height=HEIGHT, door_count=1,
            panel_color="CLEAR_ANODIZED", panel_design="FLUSH",
        )
        steel = DoorConfiguration(
            door_type="residential", door_series="KANATA",
            door_width=WIDTH, door_height=HEIGHT, door_count=1,
            panel_color="WHITE", panel_design="SHXL",
        )
        explicit = DoorConfiguration(
            door_type="aluminium", door_series="SOLALITE",
            door_width=WIDTH, door_height=HEIGHT, door_count=1,
            panel_color="CLEAR_ANODIZED", panel_design="FLUSH",
            track_thickness="2",
        )
        assert aluminum.track_thickness == "3"
        assert steel.track_thickness == "2"
        assert explicit.track_thickness == "2"

    def test_widget_aluminum_without_track_resolves_to_3(self):
        mapped = _map_widget_config({
            "family": "aluminum",
            "widthInches": WIDTH,
            "heightInches": HEIGHT,
            "windows": "none",
        })
        assert "trackThickness" not in mapped
        assert mapped["doorSeries"] == "AL976"
        track = _one(_parts(mapped), "track")
        assert track["part_number"].startswith("TR03-")
        _assert_sellable(track["part_number"])


class TestSteelDefaultsUnchanged:
    def test_kanata_omitted_stays_2_inch(self):
        parts = _parts({
            "doorType": "residential", "doorSeries": "KANATA",
            "doorWidth": 9 * 12, "doorHeight": 7 * 12,
            "panelColor": "WHITE", "panelDesign": "SHXL",
        })
        assert _one(parts, "track")["part_number"].startswith("TR02-")
        assert '2"' in _comment(parts)

    def test_tx450_omitted_stays_2_inch_until_the_portal_sends_3(self):
        """Commercial steel is set to 3\" by the portal when the series is
        picked. The resolver's omitted-track fallback stays 2\"."""
        omitted = _parts({
            "doorType": "commercial", "doorSeries": "TX450",
            "doorWidth": WIDTH, "doorHeight": HEIGHT,
            "panelColor": "WHITE", "panelDesign": "UDC",
        })
        explicit = _parts({
            "doorType": "commercial", "doorSeries": "TX450",
            "doorWidth": WIDTH, "doorHeight": HEIGHT,
            "panelColor": "WHITE", "panelDesign": "UDC",
            "trackThickness": "3",
        })
        assert _one(omitted, "track")["part_number"].startswith("TR02-")
        assert _one(explicit, "track")["part_number"].startswith("TR03-")

    def test_craft_stays_on_its_2_inch_track_kit(self):
        parts = _parts({
            "doorType": "residential", "doorSeries": "CRAFT",
            "doorWidth": 8 * 12, "doorHeight": 7 * 12,
            "panelColor": "WHITE", "panelDesign": "SHXL",
        })
        track = _one(parts, "track")["part_number"]
        assert track.startswith("TR25-")
        assert '2"' in _comment(parts)


class TestConfiguratorAndPortals:
    def _request(self, **overrides):
        fields = {
            "doorType": "aluminium",
            "doorSeries": "PANORAMA",
            "doorWidth": WIDTH,
            "doorHeight": HEIGHT,
            "panelColor": "CLEAR_ANODIZED",
            "panelDesign": "FLUSH",
        }
        fields.update(overrides)
        return DoorConfigRequest(**fields)

    @pytest.mark.parametrize("series", ALUMINUM_SERIES)
    def test_api_model_omits_track_as_3_and_keeps_explicit_2(self, series):
        assert self._request(doorSeries=series).trackThickness == "3"
        assert self._request(doorSeries=series, trackThickness="2").trackThickness == "2"

    def test_steel_api_model_still_defaults_to_2(self):
        assert self._request(
            doorType="residential", doorSeries="KANATA",
            panelColor="WHITE", panelDesign="SHXL",
        ).trackThickness == "2"
        assert self._request(
            doorType="commercial", doorSeries="TX450",
            panelColor="WHITE", panelDesign="UDC",
        ).trackThickness == "2"

    def test_customer_portal_description_and_bom_follow_the_default(self):
        door = {
            "doorType": "aluminium", "doorSeries": "PANORAMA",
            "doorWidth": WIDTH, "doorHeight": HEIGHT,
            "doorCount": 1, "panelColor": "CLEAR_ANODIZED",
            "panelDesign": "FLUSH",
        }
        assert _build_door_config_dict(door)["trackThickness"] == "3"
        assert '3" BRACKET MOUNT' in _format_door_description(door)
        door["trackThickness"] = "2"
        assert _build_door_config_dict(door)["trackThickness"] == "2"
        assert '2" BRACKET MOUNT' in _format_door_description(door)

    def test_reloaded_header_keeps_an_explicit_2_and_defaults_a_blank_to_3(self):
        explicit = _parse_door_header(
            '(1) 10\'0" x 8\'0" PANORAMA, CLEAR ANODIZED, 2" BRACKET MOUNT, STD LIFT'
        )
        blank = _parse_door_header(
            '(1) 10\'0" x 8\'0" PANORAMA, CLEAR ANODIZED, STD LIFT'
        )
        steel = _parse_door_header(
            '(1) 9\'0" x 7\'0" KANATA, WHITE, SHXL, STD LIFT'
        )
        assert explicit["trackThickness"] == "2"
        assert blank["trackThickness"] == "3"
        assert steel["trackThickness"] == "2"

    def test_email_normalizer_defaults_aluminum_to_3(self):
        omitted = ClaudeAIClient._normalize_configurator_doors([{
            "doorType": "aluminium", "doorSeries": "PANORAMA",
            "doorWidth": WIDTH, "doorHeight": HEIGHT,
        }])
        chosen = ClaudeAIClient._normalize_configurator_doors([{
            "doorType": "aluminium", "doorSeries": "AL976",
            "doorWidth": WIDTH, "doorHeight": HEIGHT,
            "trackThickness": "2 inch",
        }])
        steel = ClaudeAIClient._normalize_configurator_doors([{
            "doorType": "commercial", "doorWidth": WIDTH, "doorHeight": HEIGHT,
        }])
        assert omitted[0]["trackThickness"] == "3"
        assert chosen[0]["trackThickness"] == "2"
        assert steel[0]["trackThickness"] == "2"
        assert steel[0]["trackRadius"] == "15"


class TestShopDrawingPdf:
    def _ctx(self, **door):
        base = {
            "doorSeries": "PANORAMA",
            "doorType": "aluminium",
            "doorWidth": WIDTH,
            "doorHeight": HEIGHT,
            "doorCount": 1,
        }
        base.update(door)
        return build_context_from_config(
            config_data={"doors": [base]},
            customer_name="Test",
            job_number="TRACK-DEFAULT",
        )

    def test_drawing_checks_3_inch_unless_2_was_chosen(self):
        default_ctx = self._ctx()
        chosen_ctx = self._ctx(trackThickness="2")
        steel = {
            "doorSeries": "KANATA", "doorType": "residential",
            "doorWidth": 108, "doorHeight": 84, "doorCount": 1,
        }
        steel_ctx = build_context_from_config(
            config_data={"doors": [steel]},
            customer_name="Test",
            job_number="STEEL",
        )
        assert default_ctx.track_thickness_ga == "3"
        assert chosen_ctx.track_thickness_ga == "2"
        assert steel_ctx.track_thickness_ga == "2"

        default_text = dxf_to_string(build_dxf(default_ctx)).decode("utf-8")
        chosen_text = dxf_to_string(build_dxf(chosen_ctx)).decode("utf-8")
        assert '3" TRACK APPLICATION' in default_text
        assert '2" TRACK APPLICATION' in chosen_text


class TestEmailQuoteGeneration:
    def _service(self):
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

        return QuoteGenerationService(_DB())

    def _tracks(self, **spec):
        base = {
            "model": "Panorama",
            "quantity": 1,
            "width_ft": 10,
            "width_in": 0,
            "height_ft": 8,
            "height_in": 0,
            "color": "clear anodized",
        }
        base.update(spec)
        items = self._service()._generate_door_items(base, None)
        return [i for i in items if i["item_type"] == "track"]

    def test_panorama_email_without_a_track_uses_3_inch(self):
        tracks = self._tracks(track_type=None)
        assert tracks and tracks[0]["product_code"].startswith("TR03-")
        _assert_sellable(tracks[0]["product_code"])
        assert tracks[0]["unit_price"] > 0

    def test_panorama_email_asking_for_2_inch_keeps_2_inch(self):
        tracks = self._tracks(track_type="2")
        assert tracks and tracks[0]["product_code"].startswith("TR02-")
        _assert_sellable(tracks[0]["product_code"])

    def test_kanata_email_without_a_track_stays_2_inch(self):
        tracks = self._tracks(model="Kanata", track_type=None, color="white")
        assert tracks and tracks[0]["product_code"].startswith("TR02-")
