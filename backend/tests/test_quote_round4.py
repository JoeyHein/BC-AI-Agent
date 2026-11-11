"""Round 4 price overrides. Both settings default to off.

Off leaves the line on the price list, which is the current sell price.
Shadow logs the price it would set. On writes a fixed unit price.

Card unit prices below are the BC item card (bc_items.json unitPrice).
They are the price BC starts from before a customer price list. Off mode
must not replace them. DoorTech SILV for the black long kit is $206.45
and for the Kanata flush section is $380.96; those stay in the round 3
regression.
"""
from __future__ import annotations

import logging
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.door_configurator import _format_scope_label
from app.db.models import AppSettings
from app.services.bc_part_number_mapper import get_bc_mapper
from app.services.part_number_service import get_parts_for_door_config
from app.services.quote_price_overrides import (
    PriceOverrideSettings,
    SECTION_PRICING_KEY,
    apply_door_price_overrides,
    apply_price_overrides,
    classify_residential_window,
    load_price_overrides,
    note_parts_request,
    replacement_request_kind,
    save_price_overrides,
    section_only_scope,
)


# BC item card unitPrice. Off mode must keep these.
CARD_UNIT_PRICE = {
    "GK15-11200-00": 189.90,   # long clear white
    "GK15-11205-00": 189.90,   # long clear black; DoorTech SILV is 206.45
    "GK15-11251-00": 154.00,   # long clear walnut
    "GK15-10200-00": 108.37,   # short clear white
    "GK15-10205-00": 108.37,   # short clear black
    "GK15-55200-00": 240.11,   # Craft long clear white
    "GK16-23205-00": 111.98,   # TX450 commercial black
    "GK17-10100-00": 27.14,    # aluminum glazing
    "PN65-21005-1600": 454.34, # Kanata flush black; DoorTech SILV is 380.96
    "PN45-24400-0900": 288.00, # TX450 UDC white
}

DOORTECH_SILV = {
    "GK15-11205-00": 206.45,
    "PN65-21005-1600": 380.96,
}

COMPLETE = {
    "panels": True, "tracks": True, "springs": True, "struts": True,
    "hardwareKits": True, "weatherStripping": True, "bottomRetainer": True,
    "shafts": True,
}
DOOR_FACE = {
    "panels": True, "tracks": False, "springs": False, "struts": False,
    "hardwareKits": False, "weatherStripping": False, "bottomRetainer": True,
    "shafts": False,
}
PANELS_ONLY = {**DOOR_FACE, "bottomRetainer": False}

ON = PriceOverrideSettings(
    panel_mode="on",
    window_mode="on",
    long_price=165.00,
    short_price=120.00,
)
OFF = PriceOverrideSettings()


def _window(part_number, qty=1, description=""):
    return {
        "part_number": part_number,
        "description": description,
        "quantity": qty,
        "category": "window",
    }


def _panel(part_number, qty=1):
    return {
        "part_number": part_number,
        "description": "SECTION",
        "quantity": qty,
        "category": "panel",
    }


def _apply(parts, *, hardware, door_type, door_series, settings, costs=None):
    costs = costs or {}

    def lookup(part_number):
        return costs.get(part_number)

    return apply_price_overrides(
        parts,
        hardware=hardware,
        door_type=door_type,
        door_series=door_series,
        settings=settings,
        list_lookup=lookup,
    )


def test_card_prices_and_doortech_silv_are_the_current_sell_prices():
    """Pins the prices off mode is required to leave in place."""
    assert CARD_UNIT_PRICE["GK15-11205-00"] == 189.90
    assert DOORTECH_SILV["GK15-11205-00"] == 206.45
    assert CARD_UNIT_PRICE["PN65-21005-1600"] == 454.34
    assert DOORTECH_SILV["PN65-21005-1600"] == 380.96
    assert CARD_UNIT_PRICE["GK15-11200-00"] == 189.90
    assert CARD_UNIT_PRICE["GK15-11251-00"] == 154.00
    assert CARD_UNIT_PRICE["GK16-23205-00"] == 111.98
    assert CARD_UNIT_PRICE["GK17-10100-00"] == 27.14


def test_off_mode_matches_current_pricing():
    parts = [
        _window("GK15-11205-00", 6, "GLASS KIT, KANATA, LONG, CLEAR, BLACK"),
        _window("GK15-10200-00", 2, "GLASS KIT, KANATA, SHORT, CLEAR, WHITE"),
        _window("GK16-23205-00", 4, "GLASS KIT, TX 450, BLACK"),
        _panel("PN65-21005-1600", 4),
    ]
    called = []
    apply_price_overrides(
        parts,
        hardware=DOOR_FACE,
        door_type="residential",
        door_series="KANATA",
        settings=OFF,
        list_lookup=lambda pn: called.append(pn),
    )
    assert called == []
    assert len(parts) == 4
    for part in parts:
        assert "fixed_unit_price" not in part
        assert "pricing_override" not in part
        assert "pricing_flag" not in part


def test_doortech_six_long_clear_kits_are_165_each():
    line = _window("GK15-11205-00", 6, "GLASS KIT, KANATA, LONG, THERM - CLEAR, BLACK")
    parts = _apply(
        [line],
        hardware=COMPLETE,
        door_type="residential",
        door_series="KANATA",
        settings=ON,
    )
    assert line["quantity"] == 6
    assert line["fixed_unit_price"] == 165.00
    assert line["quantity"] * line["fixed_unit_price"] == 990.00
    assert parts[1]["lineType"] == "Comment"
    assert "165.00" in parts[1]["description"]
    assert line["part_number"] == "GK15-11205-00"


def test_six_separate_long_kits_are_still_165_each():
    lines = [
        _window("GK15-11205-00", 1, "GLASS KIT, KANATA, LONG, CLEAR, BLACK")
        for _ in range(6)
    ]
    _apply(lines, hardware=COMPLETE, door_type="residential", door_series="KANATA", settings=ON)
    kits = [line for line in lines if line.get("category") == "window"]
    assert len(kits) == 6
    assert [line["fixed_unit_price"] for line in kits] == [165.00] * 6
    assert sum(line["quantity"] * line["fixed_unit_price"] for line in kits) == 990.00


@pytest.mark.parametrize("part_number,card", [
    ("GK15-11200-00", 189.90),
    ("GK15-11205-00", 189.90),
    ("GK15-11251-00", 154.00),
])
def test_long_window_colors_share_one_rate(part_number, card):
    assert CARD_UNIT_PRICE[part_number] == card
    line = _window(part_number, 1, "GLASS KIT, KANATA, LONG, THERM - CLEAR")
    _apply([line], hardware=COMPLETE, door_type="residential", door_series="KANATA", settings=ON)
    assert line["fixed_unit_price"] == 165.00
    assert card != 165.00


def test_short_windows_are_120_each():
    white = _window("GK15-10200-00", 3, "GLASS KIT, KANATA, SHORT, THERM - CLEAR, WHITE")
    black = _window("GK15-10205-00", 1, "GLASS KIT, KANATA, SHORT, THERM - CLEAR, BLACK")
    _apply(
        [white, black],
        hardware=COMPLETE,
        door_type="residential",
        door_series="KANATA",
        settings=ON,
    )
    assert white["fixed_unit_price"] == 120.00
    assert white["quantity"] == 3
    assert white["quantity"] * white["fixed_unit_price"] == 360.00
    assert black["fixed_unit_price"] == 120.00
    assert CARD_UNIT_PRICE["GK15-10200-00"] == 108.37
    assert CARD_UNIT_PRICE["GK15-10205-00"] == 108.37


def test_craft_long_kit_is_the_long_rate():
    line = _window("GK15-55200-00", 2, "GLASS KIT, CRAFT, LONG, THERM - CLEAR, WHITE")
    _apply([line], hardware=COMPLETE, door_type="residential", door_series="CRAFT", settings=ON)
    assert line["fixed_unit_price"] == 165.00
    assert CARD_UNIT_PRICE["GK15-55200-00"] == 240.11


def test_decorative_insert_uses_the_same_per_window_rate():
    insert = {
        "part_number": "GL18-11205-00",
        "description": "FRAME INSERT, LONG, BLACK",
        "quantity": 6,
        "category": "window",
    }
    _apply([insert], hardware=COMPLETE, door_type="residential", door_series="KANATA", settings=ON)
    assert insert["fixed_unit_price"] == 165.00
    assert insert["quantity"] == 6


def test_commercial_and_aluminum_windows_are_unchanged():
    commercial = _window("GK16-23205-00", 4, "GLASS KIT, TX 450, 24 X 12, THERM - CLEAR, BLACK")
    aluminum = _window("GK17-10100-00", 8, "GLAZING KIT, ALUM, THERM, ETCHED/ CLEAR")
    _apply(
        [commercial],
        hardware=COMPLETE,
        door_type="commercial",
        door_series="TX450",
        settings=ON,
    )
    _apply(
        [aluminum],
        hardware=COMPLETE,
        door_type="aluminium",
        door_series="AL976",
        settings=ON,
    )
    assert "fixed_unit_price" not in commercial
    assert "fixed_unit_price" not in aluminum
    assert commercial["quantity"] == 4
    assert CARD_UNIT_PRICE["GK16-23205-00"] == 111.98
    assert CARD_UNIT_PRICE["GK17-10100-00"] == 27.14


def test_aluminum_door_does_not_take_the_residential_rate():
    line = _window("GK15-11205-00", 2, "GLASS KIT, KANATA, LONG, CLEAR, BLACK")
    _apply([line], hardware=COMPLETE, door_type="aluminium", door_series="AL976", settings=ON)
    assert "fixed_unit_price" not in line


def test_unknown_window_size_is_flagged_and_not_priced():
    line = _window("GK15-99200-00", 1, "GLASS KIT, KANATA, LONG, CLEAR, WHITE")
    parts = _apply(
        [line],
        hardware=COMPLETE,
        door_type="residential",
        door_series="KANATA",
        settings=ON,
    )
    assert "fixed_unit_price" not in line
    assert "unknown" in line["pricing_flag"]
    assert parts[-1]["lineType"] == "Comment"


def test_replacement_sections_use_the_card_list_price():
    kanata = _panel("PN65-21005-1600", 2)
    tx450 = _panel("PN45-24400-0900", 1)
    _apply(
        [kanata],
        hardware=DOOR_FACE,
        door_type="residential",
        door_series="KANATA",
        settings=ON,
        costs={"PN65-21005-1600": 454.34},
    )
    _apply(
        [tx450],
        hardware=PANELS_ONLY,
        door_type="commercial",
        door_series="TX450",
        settings=ON,
        costs={"PN45-24400-0900": 288.00},
    )
    assert kanata["fixed_unit_price"] == 454.34
    assert kanata["quantity"] == 2
    assert kanata["quantity"] * kanata["fixed_unit_price"] == 908.68
    assert tx450["fixed_unit_price"] == 288.00
    assert "list price" in kanata["pricing_override"]
    assert DOORTECH_SILV["PN65-21005-1600"] == 380.96
    assert CARD_UNIT_PRICE["PN65-21005-1600"] == 454.34
    assert CARD_UNIT_PRICE["PN45-24400-0900"] == 288.00


def test_complete_door_section_is_not_overridden():
    panel = _panel("PN65-21005-1600", 4)
    window = _window("GK15-11205-00", 6, "GLASS KIT, KANATA, LONG, CLEAR, BLACK")
    called = []

    def lookup(part_number):
        called.append(part_number)
        return 204.45

    apply_price_overrides(
        [panel, window],
        hardware=COMPLETE,
        door_type="residential",
        door_series="KANATA",
        settings=ON,
        list_lookup=lookup,
    )
    assert called == []
    assert "fixed_unit_price" not in panel
    assert window["fixed_unit_price"] == 165.00
    assert panel["quantity"] == 4


def test_missing_or_zero_cost_is_flagged():
    missing = _panel("PN65-21005-1600", 1)
    zero = _panel("PN45-24400-0900", 1)
    _apply(
        [missing],
        hardware=DOOR_FACE,
        door_type="residential",
        door_series="KANATA",
        settings=ON,
        costs={},
    )
    _apply(
        [zero],
        hardware=PANELS_ONLY,
        door_type="commercial",
        door_series="TX450",
        settings=ON,
        costs={"PN45-24400-0900": 0},
    )
    assert "fixed_unit_price" not in missing
    assert "fixed_unit_price" not in zero
    assert "list price missing" in missing["pricing_flag"]
    assert "list price missing" in zero["pricing_flag"]


def _generated(overrides):
    base = {
        "doorWidth": 96,
        "doorHeight": 84,
        "doorCount": 1,
        "panelColor": "WHITE",
        "hardware": COMPLETE,
        "trackThickness": "2",
        "trackRadius": "15",
        "trackMount": "bracket",
        "liftType": "standard",
        "hasWindows": True,
    }
    base.update(overrides)
    return get_parts_for_door_config(base).get("parts_list", [])


def test_commercial_tx450_windows_keep_list_price():
    """A commercial TX450 emits GK15 kits. Those stay on the price list."""
    parts = _generated({
        "doorType": "commercial",
        "doorSeries": "TX450",
        "doorWidth": 144,
        "doorHeight": 144,
        "panelColor": "WHITE",
        "panelDesign": "FLUSH",
        "windowCount": 3,
        "windowSize": "long",
    })
    kits = [part for part in parts if part.get("part_number") == "GK15-11200-00"]
    assert len(kits) == 1
    assert kits[0]["quantity"] == 3
    apply_price_overrides(
        parts,
        hardware=COMPLETE,
        door_type="commercial",
        door_series="TX450",
        settings=ON,
    )
    assert "fixed_unit_price" not in kits[0]
    assert kits[0]["quantity"] == 3
    assert not any(part.get("pricing_note") for part in parts)


def test_decorative_kit_and_insert_are_one_price_per_window():
    """Real generator output: the kit carries the rate and the insert is $0.

    Short inserts are not emitted (the short catalog is not offered), so the
    short pair is the generator's GK15 plus the GL19 row that same lookup
    returns. A lone insert, with no kit, still takes the per-window rate.
    """
    long_parts = _generated({
        "doorType": "residential",
        "doorSeries": "KANATA",
        "doorWidth": 192,
        "doorHeight": 84,
        "panelColor": "BLACK",
        "panelDesign": "SHXL",
        "windowCount": 6,
        "windowSize": "long",
        "windowInsert": "STOCKTON_STANDARD",
    })
    long_kits = [part for part in long_parts if str(part.get("part_number", "")).startswith("GK15-")]
    long_inserts = [part for part in long_parts if str(part.get("part_number", "")).startswith("GL18-")]
    assert len(long_kits) == 1 and long_kits[0]["part_number"] == "GK15-11205-00"
    assert long_kits[0]["quantity"] == 6
    assert len(long_inserts) == 1 and long_inserts[0]["quantity"] == 6

    apply_price_overrides(
        long_parts,
        hardware=COMPLETE,
        door_type="residential",
        door_series="KANATA",
        settings=ON,
    )
    assert long_kits[0]["fixed_unit_price"] == 165.00
    assert long_inserts[0]["fixed_unit_price"] == 0.00
    assert "included in flat window rate" in long_inserts[0]["pricing_override"]
    assert long_kits[0]["quantity"] * long_kits[0]["fixed_unit_price"] == 990.00
    assert long_inserts[0]["quantity"] * long_inserts[0]["fixed_unit_price"] == 0.00

    short_parts = _generated({
        "doorType": "residential",
        "doorSeries": "KANATA",
        "doorWidth": 96,
        "doorHeight": 84,
        "panelColor": "SANDTONE",
        "panelDesign": "SH",
        "windowCount": 2,
        "windowSize": "short",
        "windowInsert": "STOCKTON_STANDARD",
    })
    short_kits = [part for part in short_parts if str(part.get("part_number", "")).startswith("GK15-")]
    assert len(short_kits) == 1 and short_kits[0]["part_number"].startswith("GK15-10")
    assert short_kits[0]["quantity"] == 2
    assert not any(str(part.get("part_number", "")).startswith("GL") for part in short_parts)
    insert = get_bc_mapper().get_frame_insert("STOCKTON_STANDARD", "SANDTONE", insert_prefix="GL19")
    assert insert is not None
    short_parts.append({
        "part_number": insert.part_number,
        "description": insert.description,
        "quantity": short_kits[0]["quantity"],
        "category": "window",
    })
    apply_price_overrides(
        short_parts,
        hardware=COMPLETE,
        door_type="residential",
        door_series="KANATA",
        settings=ON,
    )
    priced_insert = next(
        part for part in short_parts if part.get("part_number") == insert.part_number
    )
    assert short_kits[0]["fixed_unit_price"] == 120.00
    assert priced_insert["fixed_unit_price"] == 0.00
    assert "included in flat window rate" in priced_insert["pricing_override"]
    assert short_kits[0]["quantity"] * short_kits[0]["fixed_unit_price"] == 240.00


def test_card_list_price_is_used_when_bc_is_down(monkeypatch):
    import app.integrations.bc.client as bc_client_mod
    import app.services.pricing_service as pricing
    from app.services.quote_price_overrides import card_list_price

    exported = get_bc_mapper().bc_items["PN65-21005-1600"]
    assert exported["unitPrice"] == 454.34
    assert exported["unitCost"] == 204.45
    monkeypatch.setattr(pricing, "_cache_expiry", 0)
    monkeypatch.setattr(pricing, "_bc_cost_cache", {})

    def offline(part_numbers):
        raise RuntimeError("BC unavailable")

    monkeypatch.setattr(bc_client_mod.bc_client, "get_items_by_numbers", offline)
    assert card_list_price("PN65-21005-1600") == 454.34
    line = _panel("PN65-21005-1600", 1)
    apply_price_overrides(
        [line],
        hardware=DOOR_FACE,
        door_type="residential",
        door_series="KANATA",
        settings=PriceOverrideSettings(panel_mode="on", window_mode="off"),
    )
    assert line["fixed_unit_price"] == 454.34
    assert DOORTECH_SILV["PN65-21005-1600"] == 380.96


def test_shadow_logs_only(caplog):
    window = _window("GK15-11205-00", 6, "GLASS KIT, KANATA, LONG, CLEAR, BLACK")
    panel = _panel("PN65-21005-1600", 1)
    unknown = _window("GK15-99200-00", 1, "GLASS KIT")
    settings = PriceOverrideSettings(
        panel_mode="shadow",
        window_mode="shadow",
        long_price=165,
        short_price=120,
    )
    parts = [window, panel, unknown]
    with caplog.at_level(logging.INFO):
        _apply(
            parts,
            hardware=DOOR_FACE,
            door_type="residential",
            door_series="KANATA",
            settings=settings,
            costs={"PN65-21005-1600": 454.34},
        )
    assert len(parts) == 3
    for part in parts:
        assert "fixed_unit_price" not in part
        assert "pricing_flag" not in part
    text = caplog.text
    assert "SHADOW quote_flat_residential_windows: GK15-11205-00 qty 6.0 would be $165.00 each (long)" in text
    assert "SHADOW quote_replacement_section_pricing: PN65-21005-1600 would be list price $454.34" in text
    assert "GK15-99200-00 size unknown" in text


def test_window_patterns():
    assert classify_residential_window("GK15-11205-00", "", "window", "residential", "KANATA") == "long"
    assert classify_residential_window("GK15-55200-00", "", "window", "residential", "CRAFT") == "long"
    assert classify_residential_window("GL18-10000-00", "", "window", "residential", "KANATA") == "long"
    assert classify_residential_window("GL17-10000-00", "", "window", "residential", "CRAFT") == "long"
    assert classify_residential_window("GK15-10205-00", "", "window", "residential", "KANATA") == "short"
    assert classify_residential_window("GL19-10000-00", "", "window", "residential", "KANATA") == "short"
    assert classify_residential_window(
        "GK15-LONG-KIT", "GLASS KIT LONG", "window", "residential", "KANATA",
    ) == "long"
    assert classify_residential_window("GK15-99200-00", "LONG", "window", "residential", "KANATA") == "unknown"
    assert classify_residential_window("GK16-23205-00", "LONG", "window", "commercial", "TX450") is None
    assert classify_residential_window("GK17-10100-00", "", "window", "aluminium", "AL976") is None
    assert classify_residential_window("GK15-11205-00", "", "window", "commercial", "TX450") is None
    assert classify_residential_window("GK15-11205-00", "", "window", "commercial", "KANATA") is None
    assert classify_residential_window("GK15-11205-00", "", "window", "residential", "TX450") == "long"
    assert classify_residential_window("GK15-11205-00", "", "window", "commercial", "TX760") is None


def test_replacement_request_text():
    assert replacement_request_kind("need 2 replacement panels") == "section"
    assert replacement_request_kind("Bottom section for the Kanata") == "section"
    assert replacement_request_kind("panels only, no hardware") == "section"
    assert replacement_request_kind("loose sections") == "section"
    assert replacement_request_kind("torsion springs") == "other_parts"
    assert replacement_request_kind("new struts") == "other_parts"
    assert replacement_request_kind("truss on every section") == "other_parts"


@pytest.mark.parametrize("hardware,door_type,label", [
    (COMPLETE, "residential", None),
    (DOOR_FACE, "residential", "DOOR FACE ONLY"),
    (PANELS_ONLY, "residential", "PANELS ONLY"),
    ({}, "residential", None),
])
def test_section_scope_matches_the_configurator(hardware, door_type, label):
    assert section_only_scope(hardware, door_type) == label
    assert section_only_scope(hardware, door_type) == _format_scope_label(hardware, door_type)


def test_portal_dict_and_configurator_model_use_the_same_price():
    class Door:
        doorType = "residential"
        doorSeries = "KANATA"
        hardware = DOOR_FACE

    portal = {"doorType": "residential", "doorSeries": "KANATA", "hardware": DOOR_FACE}
    staff = _panel("PN65-21005-1600")
    portal_line = _panel("PN65-21005-1600")
    apply_door_price_overrides(
        [staff], Door(), ON, list_lookup=lambda pn: 454.34, emit_notes=False,
    )
    apply_door_price_overrides(
        [portal_line], portal, ON, list_lookup=lambda pn: 454.34, emit_notes=False,
    )
    assert staff["fixed_unit_price"] == portal_line["fixed_unit_price"] == 454.34
    assert "pricing_override" in staff


def test_existing_fixed_price_is_left_alone():
    wrap = {
        "part_number": "WRAP",
        "description": "DOOR WRAPPING",
        "quantity": 1,
        "category": "wrapping",
        "fixed_unit_price": 0.95,
    }
    _apply([wrap], hardware=COMPLETE, door_type="residential", door_series="KANATA", settings=ON)
    assert wrap["fixed_unit_price"] == 0.95


@pytest.fixture
def session():
    engine = create_engine(
        "sqlite://",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    AppSettings.__table__.create(engine, checkfirst=True)
    db = sessionmaker(bind=engine, autoflush=False, autocommit=False)()
    try:
        yield db
    finally:
        db.close()


def test_settings_default_off_and_round_trip(session):
    loaded = load_price_overrides(session)
    assert loaded.panel_mode == "off"
    assert loaded.finder_mode == "off"
    assert loaded.window_mode == "off"
    assert loaded.long_price == 165.00
    assert loaded.short_price == 120.00
    assert load_price_overrides(None) == loaded

    save_price_overrides(
        session,
        panel_mode="on",
        finder_mode="shadow",
        window_mode="shadow",
        long_price=170,
        short_price=110,
    )
    session.commit()
    again = load_price_overrides(session)
    assert again.panel_mode == "on"
    assert again.finder_mode == "shadow"
    assert again.window_mode == "shadow"
    assert again.long_price == 170
    assert again.short_price == 110

    save_price_overrides(session, panel_mode="off")
    session.commit()
    kept = load_price_overrides(session)
    assert kept.panel_mode == "off"
    assert kept.finder_mode == "shadow"

    retired = AppSettings(
        setting_key="quote_replacement_panel_margin",
        setting_value={"mode": "on", "margin_percent": 50},
    )
    session.add(retired)
    session.commit()
    assert load_price_overrides(session).panel_mode == "off"


def test_parts_request_note_logs_only_when_enabled(session, caplog):
    with caplog.at_level(logging.INFO):
        note_parts_request(session, "RFQ", "need 2 replacement panels")
    assert SECTION_PRICING_KEY not in caplog.text

    save_price_overrides(session, panel_mode="shadow")
    session.commit()
    caplog.clear()
    with caplog.at_level(logging.INFO):
        note_parts_request(session, "RFQ", "need 2 replacement panels")
    assert "SHADOW quote_replacement_section_pricing" in caplog.text
    assert "replacement panel or section" in caplog.text
    assert "stays in manual pricing" in caplog.text

    save_price_overrides(session, panel_mode="on")
    session.commit()
    caplog.clear()
    with caplog.at_level(logging.INFO):
        note_parts_request(session, "RFQ", "torsion springs")
    assert "quote_replacement_section_pricing: email" in caplog.text
    assert "not a section" in caplog.text
    assert "SHADOW" not in caplog.text
