"""Round 5: replacement sections sell at the item-card list price, and the
section finder resolves one stocked part or sends the request to staff.

Off mode does not set a fixed price, so a complete door and a sections-only
door both stay on the customer's price list.
"""
from __future__ import annotations

import base64
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.models import AppSettings, PublicQuoteRequest
from app.services.bc_part_number_mapper import get_bc_mapper
from app.services.quote_price_overrides import (
    PriceOverrideSettings,
    apply_price_overrides,
)
from app.services.section_finder import finder_options, resolve_section


DOOR_FACE = {
    "panels": True, "tracks": False, "springs": False, "struts": False,
    "hardwareKits": False, "weatherStripping": False, "bottomRetainer": True,
    "shafts": False,
}
COMPLETE = {key: True for key in DOOR_FACE}

KANATA_16_BLACK = {
    "application": "residential",
    "series": "KANATA",
    "thickness": "1-3/4",
    "gauge": "standard",
    "section_height": 21,
    "width_feet": 16,
    "width_inches": 0,
    "color": "BLACK",
    "design": "FLUSH",
    "position": "bottom",
    "windows": False,
    "quantity": 2,
}


def _list_price(part_number):
    item = get_bc_mapper().bc_items.get(part_number) or {}
    price = item.get("unitPrice")
    return float(price) if price else None


def test_doortech_panels_only_is_the_card_not_silv_or_margin():
    card = get_bc_mapper().bc_items["PN65-21005-1600"]["unitPrice"]
    assert card == 454.34
    line = {
        "part_number": "PN65-21005-1600",
        "description": "SECTION",
        "quantity": 2,
        "category": "panel",
    }
    apply_price_overrides(
        [line],
        hardware=DOOR_FACE,
        door_type="residential",
        door_series="KANATA",
        settings=PriceOverrideSettings(panel_mode="on"),
        list_lookup=lambda pn: card,
    )
    assert line["fixed_unit_price"] == 454.34
    assert line["fixed_unit_price"] != 380.96
    assert line["fixed_unit_price"] != 408.90


def test_complete_door_keeps_the_customer_price_list():
    line = {
        "part_number": "PN65-21005-1600",
        "description": "SECTION",
        "quantity": 4,
        "category": "panel",
    }
    apply_price_overrides(
        [line],
        hardware=COMPLETE,
        door_type="residential",
        door_series="KANATA",
        settings=PriceOverrideSettings(panel_mode="on"),
        list_lookup=lambda pn: 454.34,
    )
    assert "fixed_unit_price" not in line


def test_off_mode_does_not_set_a_list_price():
    line = {
        "part_number": "PN65-21005-1600",
        "quantity": 1,
        "category": "panel",
    }
    apply_price_overrides(
        [line],
        hardware=DOOR_FACE,
        door_type="residential",
        door_series="KANATA",
        settings=PriceOverrideSettings(),
        list_lookup=lambda pn: (_ for _ in ()).throw(AssertionError("lookup")),
    )
    assert "fixed_unit_price" not in line


def test_finder_resolves_the_doortech_kanata_section():
    result = resolve_section(KANATA_16_BLACK, list_price_lookup=_list_price)
    assert result["status"] == "resolved"
    assert result["part_number"] == "PN65-21005-1600"
    assert result["list_price"] == 454.34
    assert result["quantity"] == 2
    assert "FLUSH" in result["description"]


def test_finder_resolves_a_tx450_section_and_not_a_guessed_width():
    result = resolve_section({
        "application": "commercial",
        "series": "TX450",
        "thickness": "1-3/4",
        "gauge": "standard",
        "section_height": 24,
        "width_feet": 9,
        "width_inches": 0,
        "color": "WHITE",
        "design": "UDC",
        "position": "top",
        "windows": False,
        "end_caps": "single",
        "quantity": 1,
    }, list_price_lookup=_list_price)
    assert result["status"] == "resolved"
    assert result["part_number"] == "PN45-24400-0900"
    assert result["list_price"] == 288.00

    missing = resolve_section({
        "application": "commercial",
        "series": "TX450",
        "thickness": "1-3/4",
        "gauge": "standard",
        "section_height": 24,
        "width_feet": 12,
        "width_inches": 0,
        "color": "WHITE",
        "design": "FLUSH",
        "position": "top",
        "windows": False,
        "quantity": 1,
    }, list_price_lookup=_list_price)
    assert missing["status"] == "review"
    assert missing["part_number"] is None
    assert "PN45-24000-1200" in missing["reasons"][0]


def test_finder_does_not_guess():
    unsure = resolve_section({**KANATA_16_BLACK, "series": "not sure"})
    assert unsure["status"] == "review"
    assert any("not guessed" in reason for reason in unsure["reasons"])

    windows = resolve_section({**KANATA_16_BLACK, "windows": True})
    assert windows["status"] == "review"
    assert any("glass kit" in reason for reason in windows["reasons"])

    wrong_thickness = resolve_section({**KANATA_16_BLACK, "thickness": "2"})
    assert wrong_thickness["status"] == "review"

    options = finder_options()
    series_ids = {row["id"] for row in options["series"]}
    assert "KANATA" in series_ids
    assert "TX760" in series_ids
    assert "AL976" not in series_ids
    assert not any("Executive" in row["id"] for row in options["series"])
    assert any("full-view" in gap for gap in options["gaps"])


def test_craft_top_is_flush_for_every_design():
    denison = resolve_section({
        "application": "residential",
        "series": "CRAFT",
        "thickness": "1-3/4",
        "section_height": 28,
        "width_feet": 9,
        "width_inches": 0,
        "color": "WHITE",
        "design": "DENISON",
        "position": "top",
        "windows": False,
        "quantity": 1,
    }, list_price_lookup=_list_price)
    assert denison["status"] == "resolved"
    assert denison["part_number"] == "PN95-28000-0900"
    assert denison["part_number"] != "PN95-28600-0900"

    granville = resolve_section({
        "application": "residential",
        "series": "CRAFT",
        "thickness": "1-3/4",
        "section_height": 28,
        "width_feet": 9,
        "width_inches": 0,
        "color": "WHITE",
        "design": "GRANVILLE",
        "position": "top",
        "windows": False,
        "quantity": 1,
    }, list_price_lookup=_list_price)
    assert granville["part_number"] == "PN95-28000-0900"
    assert granville["part_number"] != "PN95-28700-0900"

    muskoka = resolve_section({
        "application": "residential",
        "series": "CRAFT",
        "thickness": "1-3/4",
        "section_height": 28,
        "width_feet": 9,
        "width_inches": 0,
        "color": "WHITE",
        "design": "MUSKOKA",
        "position": "top",
        "windows": False,
        "quantity": 1,
    }, list_price_lookup=_list_price)
    assert muskoka["part_number"] == "PN95-28000-0900"
    assert "top section" in muskoka["description"]


def test_end_caps_are_not_chosen_from_width():
    shared = {
        "application": "commercial",
        "series": "TX450",
        "thickness": "1-3/4",
        "section_height": 24,
        "width_feet": 9,
        "width_inches": 0,
        "color": "WHITE",
        "design": "UDC",
        "position": "intermediate",
        "windows": False,
        "quantity": 1,
    }
    single = resolve_section({**shared, "end_caps": "single"}, list_price_lookup=_list_price)
    double = resolve_section({**shared, "end_caps": "double"}, list_price_lookup=_list_price)
    unsure = resolve_section({**shared, "end_caps": "not sure"}, list_price_lookup=_list_price)
    assert single["part_number"] == "PN45-24400-0900"
    assert double["part_number"] == "PN46-24400-0900"
    assert unsure["status"] == "review"
    assert any("Both single and double" in reason for reason in unsure["reasons"])


def test_blank_gauge_uses_the_series_gauge():
    result = resolve_section({
        "application": "commercial",
        "series": "TX450-20",
        "thickness": "1-3/4",
        "section_height": 24,
        "width_feet": 9,
        "width_inches": 0,
        "color": "WHITE",
        "design": "UDC",
        "position": "top",
        "windows": False,
        "end_caps": "single",
        "quantity": 1,
    }, list_price_lookup=_list_price)
    assert not any("gauge" in reason for reason in result["reasons"])
    if result["status"] == "resolved":
        assert result["part_number"].startswith("PN47-")


def _png(payload=b"\x89PNG\r\n\x1a\nrest"):
    return "data:image/png;base64," + base64.b64encode(payload).decode()


def _answers(**extra):
    body = {
        "application": "residential",
        "series": "not sure",
        "thickness": "1-3/4",
        "section_height": 21,
        "width_feet": 16,
        "width_inches": 0,
        "color": "BLACK",
        "design": "FLUSH",
        "position": "bottom",
        "windows": False,
        "quantity": 1,
        "notes": "hinge side is worn",
    }
    body.update(extra)
    return body


@pytest.fixture
def finder_client():
    from app.api import customer_portal as portal
    from app.api.customer_auth import get_current_customer

    engine = create_engine(
        "sqlite://",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    AppSettings.__table__.create(engine, checkfirst=True)
    PublicQuoteRequest.__table__.create(engine, checkfirst=True)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = Session()
    user = SimpleNamespace(
        id=34,
        email="dealer@example.com",
        name="Dealer",
        company_name="Preview Doors",
        phone="555",
        bc_customer_id="C-100",
        is_active=True,
        user_type="CUSTOMER",
    )

    def _db():
        try:
            yield db
        finally:
            pass

    app = FastAPI()
    app.include_router(portal.router)
    app.dependency_overrides[portal.get_db] = _db
    app.dependency_overrides[get_current_customer] = lambda: user
    client = TestClient(app)
    try:
        yield client, db, user
    finally:
        db.close()


def test_finder_requires_a_customer_and_is_404_when_off():
    from app.api import customer_portal as portal
    app = FastAPI()
    app.include_router(portal.router)
    client = TestClient(app)
    denied = client.post("/api/customer/portal/section-finder/resolve", json=_answers())
    assert denied.status_code == 403

    engine = create_engine(
        "sqlite://",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    AppSettings.__table__.create(engine, checkfirst=True)
    Session = sessionmaker(bind=engine)
    db = Session()

    def _db():
        yield db

    from app.api.customer_auth import get_current_customer
    app.dependency_overrides[portal.get_db] = _db
    app.dependency_overrides[get_current_customer] = lambda: SimpleNamespace(
        id=1, email="a@b.c", name="A", company_name=None, phone=None,
        bc_customer_id="C-1", is_active=True,
    )
    authed = TestClient(app)
    missing = authed.post("/api/customer/portal/section-finder/resolve", json=_answers())
    assert missing.status_code == 404
    review = authed.post("/api/customer/portal/section-finder/review", json=_answers())
    assert review.status_code == 404
    db.close()


def test_finder_input_limits(finder_client):
    client, _db, _user = finder_client
    too_many = client.post(
        "/api/customer/portal/section-finder/resolve",
        json=_answers(quantity=101),
    )
    assert too_many.status_code == 422
    long_notes = client.post(
        "/api/customer/portal/section-finder/resolve",
        json=_answers(notes="x" * 2001),
    )
    assert long_notes.status_code == 422
    bad_photo = client.post(
        "/api/customer/portal/section-finder/review",
        json=_answers(photo="data:image/gif;base64,AAAA"),
    )
    assert bad_photo.status_code == 422
    fake_png = client.post(
        "/api/customer/portal/section-finder/review",
        json=_answers(photo="data:image/png;base64," + base64.b64encode(b"\xff\xd8\xffnotpng").decode()),
    )
    assert fake_png.status_code == 422
    huge = "data:image/png;base64," + ("A" * (3 * 1024 * 1024))
    too_big = client.post(
        "/api/customer/portal/section-finder/review",
        json=_answers(photo=huge),
    )
    assert too_big.status_code == 422


def test_shadow_review_saves_nothing_and_on_saves_the_customer(finder_client):
    from app.services.quote_price_overrides import save_price_overrides
    client, db, user = finder_client
    save_price_overrides(db, finder_mode="shadow")
    db.commit()
    shadow = client.post("/api/customer/portal/section-finder/review", json=_answers(photo=_png()))
    assert shadow.status_code == 200
    assert shadow.json()["saved"] is False
    assert db.query(PublicQuoteRequest).count() == 0

    save_price_overrides(db, finder_mode="on")
    db.commit()
    saved = client.post("/api/customer/portal/section-finder/review", json=_answers(photo=_png()))
    assert saved.status_code == 200
    body = saved.json()
    assert body["saved"] is True
    row = db.query(PublicQuoteRequest).one()
    assert row.source == "section_finder"
    assert row.door_config["user_id"] == user.id
    assert row.door_config["bc_customer_id"] == user.bc_customer_id
    assert row.door_image.startswith("data:image/png;base64,")
    assert len(row.notes) <= 2000


def test_cart_list_price_and_a_failed_price_write(finder_client, monkeypatch):
    from app.api import customer_portal as portal
    from app.services.quote_price_overrides import save_price_overrides
    client, db, _user = finder_client
    save_price_overrides(db, panel_mode="on")
    db.commit()

    monkeypatch.setattr(portal, "warm_bc_cost_cache", lambda *a, **k: None)
    monkeypatch.setattr(portal, "_get_customer_pricing_tier", lambda *a, **k: "retail")
    monkeypatch.setattr(
        portal.bc_client, "create_sales_quote",
        lambda data: {"id": "q1", "number": "SQ-1"},
    )
    monkeypatch.setattr(
        portal.bc_client, "get_sales_quote",
        lambda quote_id: {"totalAmountExcludingTax": 454.34, "totalAmountIncludingTax": 454.34},
    )
    monkeypatch.setattr(
        "app.services.quote_price_overrides.card_list_price",
        lambda part_number: 454.34,
    )
    added = {"calls": 0}

    def add_line(quote_id, line_data):
        added["calls"] += 1
        return {
            "id": "line-1",
            "@odata.etag": "W/\"1\"",
            "description": line_data.get("description"),
            "unitPrice": 380.96,
        }

    patches = {}

    def update_line(quote_id, line_id, etag, data):
        patches.update(data)
        return data

    monkeypatch.setattr(portal.bc_client, "add_quote_line", add_line)
    monkeypatch.setattr(portal.bc_client, "update_quote_line", update_line)
    ok = client.post("/api/customer/portal/cart/quote", json={
        "items": [{"item_number": "PN65-21005-1600", "description": "section", "quantity": 1}],
    })
    assert ok.status_code == 200
    payload = ok.json()
    assert payload["lines_failed"] == []
    assert payload["line_pricing"][0]["unit_price"] == 454.34
    assert payload["line_pricing"][0]["pricing_flag"] is None
    assert patches["unitPrice"] == 454.34
    assert patches["discountPercent"] == 0
    assert patches["discountAmount"] == 0
    assert added["calls"] == 1

    def fail_update(*a, **k):
        raise RuntimeError("etag mismatch")

    monkeypatch.setattr(portal.bc_client, "update_quote_line", fail_update)
    failed = client.post("/api/customer/portal/cart/quote", json={
        "items": [{"item_number": "PN65-21005-1600", "description": "section", "quantity": 1}],
    })
    assert failed.status_code == 200
    body = failed.json()
    assert body["lines_failed"] == []
    assert body["line_pricing"][0]["unit_price"] == 380.96
    assert "customer price kept" in body["line_pricing"][0]["pricing_flag"]
    assert added["calls"] == 2


def test_export_price_is_used_only_when_the_live_call_fails(monkeypatch):
    import app.integrations.bc.client as bc_client_mod
    import app.services.pricing_service as pricing
    from app.services.quote_price_overrides import card_list_price, apply_price_overrides, PriceOverrideSettings

    monkeypatch.setattr(pricing, "_cache_expiry", 0)
    monkeypatch.setattr(pricing, "_bc_cost_cache", {})

    def down(part_numbers, company_id=None, errors=None):
        if errors is not None:
            errors.append("bc down")
        return {}

    monkeypatch.setattr(bc_client_mod.bc_client, "get_items_by_numbers", down)
    price = card_list_price("PN65-21005-1600")
    assert float(price) == 454.34
    assert price.source == "export"
    line = {"part_number": "PN65-21005-1600", "quantity": 1, "category": "panel"}
    apply_price_overrides(
        [line],
        hardware={
            "panels": True, "tracks": False, "springs": False, "struts": False,
            "hardwareKits": False, "weatherStripping": False, "bottomRetainer": True,
            "shafts": False,
        },
        door_type="residential",
        door_series="KANATA",
        settings=PriceOverrideSettings(panel_mode="on"),
        list_lookup=lambda pn: price,
    )
    assert "(export price)" in line["pricing_override"]

    def missing(part_numbers, company_id=None, errors=None):
        return {}

    monkeypatch.setattr(bc_client_mod.bc_client, "get_items_by_numbers", missing)
    assert card_list_price("PN65-21005-1600") is None
