"""Pins that stay true with customer-profile quoting off, in shadow, and on.

These cover the quote-from-email path for a known customer with no profile,
the portal quote path, WRAP at $0.95/SF just above freight, the 3\" aluminum
and Panorama track default, PR 66 acknowledgement chasing and customer-update
drafts, and the order tracker. None of them send mail.
"""
from __future__ import annotations

import os
import sys
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.customer_portal import _apply_portal_profile
from app.db.models import (
    AIDecision,
    AppSettings,
    BCCustomer,
    CustomerProfile,
    EmailLog,
    OpsActionItem,
    OpsActivity,
    OpsFieldAudit,
    OpsOutboundMessage,
    OpsTrackedLine,
    OpsTrackedOrder,
    OpsTrackedPo,
    OpsTrackerMeta,
    QuoteItem,
    QuoteRequest,
    SavedQuoteConfig,
)
from app.services.customer_profile_service import set_quoting_mode
from app.services.freight_service import interleave_door_freight
from app.services.ops_tracker_service import Actor, apply_snapshot
from app.services.part_number_service import (
    WRAP_UNIT_PRICE,
    door_needs_wrapping,
    get_parts_for_door_config,
)
from app.services.track_defaults import default_track_thickness
import app.services.email_monitor as email_monitor_mod
from app.services.email_monitor import EmailMonitorService

TODAY = date(2026, 11, 3)
SYNC = Actor(email="Business Central", source="sync")


def _session():
    engine = create_engine(
        "sqlite://",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    for model in (
        EmailLog, BCCustomer, QuoteRequest, AIDecision, QuoteItem,
        AppSettings, CustomerProfile, SavedQuoteConfig,
    ):
        model.__table__.create(engine, checkfirst=True)
    db = sessionmaker(bind=engine, autoflush=False, autocommit=False)()
    return db


def _tracker_db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE users (id INTEGER PRIMARY KEY)"))
    for table in (
        OpsTrackerMeta.__table__,
        OpsTrackedOrder.__table__,
        OpsTrackedLine.__table__,
        OpsTrackedPo.__table__,
        OpsFieldAudit.__table__,
        OpsActionItem.__table__,
        OpsOutboundMessage.__table__,
        OpsActivity.__table__,
        AppSettings.__table__,
    ):
        table.create(engine)
    return sessionmaker(bind=engine)()


@pytest.fixture
def session():
    db = _session()
    try:
        yield db
    finally:
        db.close()


class _StubMemory:
    def retrieve_similar_examples(self, *args, **kwargs):
        return []

    def format_examples_for_prompt(self, examples):
        return ""

    def get_customer_context(self, *args, **kwargs):
        return None

    def get_calibrated_confidence(self, raw, **kwargs):
        return raw

    def _add_to_example_library(self, *args, **kwargs):
        return None

    def learn_customer_preferences(self, *args, **kwargs):
        return None


@pytest.fixture
def service(monkeypatch):
    monkeypatch.setattr(email_monitor_mod, "get_memory_service", lambda db: _StubMemory())
    return EmailMonitorService()


def _mode(db, mode):
    set_quoting_mode(db, mode)
    db.commit()


@pytest.mark.parametrize("mode", ["off", "shadow", "on"])
def test_email_quote_for_known_customer_without_a_profile_is_unchanged(service, session, monkeypatch, mode):
    """Exact email match, no profile: same customer, delivery, and mapped door."""
    _mode(session, mode)
    session.add(BCCustomer(
        bc_customer_id="BC-ACME",
        company_name="Acme Doors",
        email="buyer@acme.test",
        bc_price_group="CONTRACTOR",
    ))
    session.commit()
    log = EmailLog(
        message_id=f"reg-{mode}",
        from_address="buyer@acme.test",
        subject="RFQ",
        body="12x10 TX450",
        status="new",
    )
    session.add(log)
    session.flush()

    monkeypatch.setattr(service.ai_client, "parse_email_for_quote", lambda *a, **k: {
        "success": True,
        "confidence": 0.9,
        "model": "stub",
        "tokens": {"input": 1, "output": 1},
        "data": {
            "customer": {"company_name": "Acme Doors", "email": "buyer@acme.test", "confidence": 0.9},
            "doors": [{"model": "TX450", "width_ft": 12, "height_ft": 10}],
            "project": {"tag": "Acme"},
        },
    })
    monkeypatch.setattr(service.ai_client, "map_email_to_configurator", lambda *a, **k: {
        "success": True,
        "request_kind": "door_quote",
        "confidence": 0.9,
        "doors": [{
            "doorType": "commercial",
            "doorSeries": "TX450",
            "doorWidth": 144,
            "doorHeight": 120,
            "panelColor": "WHITE",
            "panelDesign": "FLUSH",
            "doorCount": 1,
            "trackMount": "bracket",
            "trackThickness": "2",
            "hardware": {"tracks": True, "springs": True},
        }],
    })
    captured = {}

    def _fake_build(request, db, source="admin"):
        captured["source"] = source
        captured["customerId"] = request.customerId
        captured["deliveryType"] = request.deliveryType
        captured["trackMount"] = request.doors[0].trackMount
        return {"success": True, "data": {"bc_quote_number": "SQ-REG", "pricing": {"total": 1}, "line_pricing": []}}

    import app.api.door_configurator as dc
    monkeypatch.setattr(dc, "build_bc_quote_from_doors", _fake_build)

    service._parse_quote_request(session, log, "RFQ", "12x10 TX450", "Buyer", "buyer@acme.test")

    quote = session.query(QuoteRequest).one()
    assert quote.status == "bc_created"
    assert captured["source"] == "email"
    assert captured["customerId"] == "BC-ACME"
    assert captured["deliveryType"] == "delivery"
    assert captured["trackMount"] == "bracket"


@pytest.mark.parametrize("mode", ["off", "shadow", "on"])
def test_portal_quote_without_a_profile_keeps_the_posted_door(session, mode):
    _mode(session, mode)
    session.add(BCCustomer(bc_customer_id="BC-PORTAL", company_name="Portal Co", email="a@portal.test"))
    config = SavedQuoteConfig(user_id=1, name="Draft", config_data={"doors": [], "deliveryType": "delivery"})
    session.add(config)
    session.commit()
    doors = [{
        "doorType": "commercial",
        "doorSeries": "TX450",
        "doorWidth": 144,
        "doorHeight": 120,
        "trackMount": "bracket",
        "trackThickness": "2",
        "panelColor": "WHITE",
    }]
    out_doors, delivery = _apply_portal_profile(
        session, "BC-PORTAL", doors, "delivery", config.id
    )
    assert delivery == "delivery"
    assert out_doors[0]["trackMount"] == "bracket"
    assert out_doors[0]["trackThickness"] == "2"
    assert out_doors[0]["doorSeries"] == "TX450"


@pytest.mark.parametrize("mode", ["off", "shadow", "on"])
def test_wrap_stays_095_per_square_foot_and_sits_above_freight(mode):
    assert WRAP_UNIT_PRICE == 0.95
    assert door_needs_wrapping("commercial", {"panels": True}) is True
    parts = get_parts_for_door_config({
        "doorType": "commercial",
        "doorSeries": "TX450",
        "doorWidth": 96,
        "doorHeight": 84,
        "doorCount": 1,
        "panelColor": "WHITE",
        "panelDesign": "FLUSH",
        "trackMount": "bracket",
        "trackThickness": "2",
        "hardware": {"panels": True, "tracks": True, "springs": True},
    })
    wrap = next(part for part in parts["parts_list"] if part["part_number"] == "WRAP")
    assert wrap["unit_price"] == 0.95
    assert wrap["fixed_unit_price"] == 0.95

    lines = [
        {"lineType": "Item", "part_number": "PN45-00000-0000", "door_index": 1, "category": "panel"},
        {"lineType": "Item", "part_number": "WRAP", "door_index": 1, "category": "wrapping", "fixed_unit_price": 0.95},
    ]
    ordered = interleave_door_freight(lines)
    numbers = [line["part_number"] for line in ordered]
    assert numbers == ["PN45-00000-0000", "WRAP", "FREIGHT"]


@pytest.mark.parametrize("mode", ["off", "shadow", "on"])
@pytest.mark.parametrize("series", ["AL976", "PANORAMA", "SWD", "SOLALITE"])
def test_aluminum_and_panorama_still_default_to_3_inch_track(mode, series):
    assert default_track_thickness(series, "aluminium") == "3"
    parts = get_parts_for_door_config({
        "doorType": "aluminium",
        "doorSeries": series,
        "doorWidth": 120,
        "doorHeight": 96,
        "doorCount": 1,
        "panelColor": "CLEAR_ANODIZED",
        "panelDesign": "FLUSH",
        "glazingType": "polycarbonate" if series == "PANORAMA" else "glass",
        "glassColor": "CLEAR",
        "hardware": {"tracks": True, "springs": True, "panels": True},
    })
    tracks = [part["part_number"] for part in parts["parts_list"] if str(part["part_number"]).startswith("TR0")]
    assert tracks, parts["parts_list"]
    assert all(number.startswith("TR03") for number in tracks)


def _order():
    return {
        "number": "SO-10421",
        "id": "guid-SO-10421",
        "customer_number": "C100",
        "customer_name": "Prairie Door Co",
        "customer_email": "pat@prairiedoor.ca",
        "external_document_number": "LOT-18",
        "order_date": "2026-10-01",
        "status": "Open",
        "fully_shipped": False,
        "lines": [{
            "line_no": 10000,
            "item_no": "PN10",
            "description": "Insulated panel",
            "quantity": 2,
            "shipped_quantity": 0,
            "line_type": "Item",
        }],
    }


def _po(**extra):
    body = {
        "number": "PO-001066",
        "vendor_number": "UPW",
        "vendor_name": "Upwardor",
        "vendor_email": "orders@upwardor.com",
        "status": "Open",
        "order_date": "2026-10-27",
        "expected_date": "2026-11-05",
        "external_document_number": "SO-10421",
        "lines": [{
            "item_no": "PN10",
            "description": "Built from SO-10421",
            "quantity": 2,
            "received_quantity": 0,
            "line_type": "Item",
        }],
    }
    body.update(extra)
    return body


def _pending(db, kind):
    return (
        db.query(OpsOutboundMessage)
        .filter(OpsOutboundMessage.kind == kind, OpsOutboundMessage.status == "pending")
        .all()
    )


@pytest.mark.parametrize("mode", ["off", "shadow", "on"])
def test_ack_chase_and_customer_update_stay_drafts(mode):
    """PR 66: a missing ack and a date change queue drafts. Nothing is sent."""
    db = _tracker_db()
    set_quoting_mode(db, mode)
    db.commit()
    sent = []
    apply_snapshot(
        db,
        {"orders": [_order()], "purchase_orders": [_po()], "vendors": [], "acks": [], "receipts": []},
        actor=SYNC,
        today=TODAY,
    )
    reminders = _pending(db, "supplier_reminder")
    assert len(reminders) == 1
    assert reminders[0].status == "pending"
    assert sent == []

    apply_snapshot(
        db,
        {"orders": [_order()], "purchase_orders": [_po(expected_date="2026-11-20")], "vendors": [], "acks": [], "receipts": []},
        actor=SYNC,
        today=TODAY,
    )
    updates = _pending(db, "customer_update")
    assert len(updates) == 1
    assert "2026-11-20" in updates[0].body_text
    assert updates[0].status == "pending"
    assert sent == []
    assert db.query(OpsTrackedOrder).filter_by(so_number="SO-10421").count() == 1
    db.close()
