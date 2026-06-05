"""Email-to-quote now runs through the door CONFIGURATOR.

The email auto-quote flow used to have its own pricing/part path
(quote_service.py margins + placeholder prices). It now:
  1. maps the parsed RFQ into the configurator's DoorConfigRequest schema
     (ClaudeAIClient.map_email_to_configurator + _normalize_configurator_doors),
  2. runs it through build_bc_quote_from_doors — the same engine the
     interactive configurator uses (BC SalesPriceLists pricing), and
  3. routes replacement-part requests and under-specified RFQs to a human
     instead of guessing.

These tests cover the deterministic mapping/normalization and the routing
decisions in EmailMonitorService._parse_quote_request (with the AI + BC
calls stubbed).
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.integrations.ai.client import ClaudeAIClient
from app.api.door_configurator import DoorConfigRequest
from app.db.models import EmailLog, QuoteRequest, QuoteItem, BCCustomer, AIDecision
import app.services.email_monitor as email_monitor_mod
from app.services.email_monitor import EmailMonitorService


# ─────────────────────────────────────────────────────────────────────────────
# 1. Normalization — LLM output is coerced to valid configurator values
# ─────────────────────────────────────────────────────────────────────────────

normalize = ClaudeAIClient._normalize_configurator_doors


def test_defaults_to_commercial_when_type_missing_or_junk():
    out = normalize([{"doorWidth": 144, "doorHeight": 120}])
    assert out[0]["doorType"] == "commercial"
    # commercial default series + design
    assert out[0]["doorSeries"] == "TX450"
    assert out[0]["panelDesign"] == "FLUSH"


def test_series_corrected_to_match_type():
    # residential type but a commercial series → snapped back to KANATA
    out = normalize([{"doorType": "residential", "doorSeries": "TX450",
                      "doorWidth": 108, "doorHeight": 84}])
    assert out[0]["doorSeries"] == "KANATA"
    assert out[0]["panelDesign"] == "SHXL"  # residential default design

    # aluminium type with junk series → AL976
    out = normalize([{"doorType": "aluminium", "doorSeries": "WHATEVER",
                      "doorWidth": 120, "doorHeight": 96}])
    assert out[0]["doorSeries"] == "AL976"


def test_color_and_dimension_coercion():
    out = normalize([{
        "doorType": "commercial", "doorSeries": "TX450",
        "doorWidth": "146", "doorHeight": 120.0,
        "panelColor": "brown", "doorCount": "2",
    }])
    d = out[0]
    assert d["panelColor"] == "NEW_BROWN"
    assert d["doorWidth"] == 146 and isinstance(d["doorWidth"], int)
    assert d["doorHeight"] == 120 and isinstance(d["doorHeight"], int)
    assert d["doorCount"] == 2


def test_bad_dimensions_become_zero():
    out = normalize([{"doorType": "commercial", "doorWidth": "n/a", "doorHeight": None}])
    assert out[0]["doorWidth"] == 0
    assert out[0]["doorHeight"] == 0


def test_track_radius_follows_thickness():
    out = normalize([{"doorType": "commercial", "doorWidth": 120, "doorHeight": 96,
                      "trackThickness": "3 inch"}])
    assert out[0]["trackThickness"] == "3"
    assert out[0]["trackRadius"] == "12"

    out = normalize([{"doorType": "commercial", "doorWidth": 120, "doorHeight": 96}])
    assert out[0]["trackThickness"] == "2"
    assert out[0]["trackRadius"] == "15"


def test_normalized_door_is_valid_configurator_request():
    """The whole point: mapper output must construct a DoorConfigRequest."""
    out = normalize([{"doorWidth": 144, "doorHeight": 120, "panelColor": "white"}])
    req = DoorConfigRequest(**out[0])  # must not raise
    assert req.doorType == "commercial"
    assert req.doorWidth == 144
    assert isinstance(req.hardware, dict) and req.hardware


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures for routing tests
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def session():
    engine = create_engine(
        "sqlite://", future=True,
        connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    # Create only the tables this flow touches (Base.metadata.create_all trips
    # over an ARRAY column on an unrelated table that SQLite can't render).
    for model in (EmailLog, BCCustomer, QuoteRequest, AIDecision, QuoteItem):
        model.__table__.create(engine, checkfirst=True)
    db = sessionmaker(bind=engine, autoflush=False, autocommit=False)()
    try:
        yield db
    finally:
        db.close()


class _StubMemory:
    """No-op stand-in for the RAG/learning memory service."""
    def retrieve_similar_examples(self, *a, **k):
        return []

    def format_examples_for_prompt(self, examples):
        return ""

    def get_customer_context(self, *a, **k):
        return None

    def get_calibrated_confidence(self, raw, **k):
        return raw

    def _add_to_example_library(self, *a, **k):
        return None

    def learn_customer_preferences(self, *a, **k):
        return None


@pytest.fixture
def service(monkeypatch):
    monkeypatch.setattr(email_monitor_mod, "get_memory_service", lambda db: _StubMemory())
    svc = EmailMonitorService()
    return svc


def _make_email(db) -> EmailLog:
    log = EmailLog(
        message_id="m1", from_address="buyer@acme.test", subject="RFQ",
        body="need doors", status="new",
    )
    db.add(log)
    db.flush()
    return log


def _stub_parse(monkeypatch, service, *, doors, confidence=0.9):
    """Stub the email->specs parse to return a high-confidence door list."""
    monkeypatch.setattr(service.ai_client, "parse_email_for_quote", lambda *a, **k: {
        "success": True,
        "confidence": confidence,
        "model": "stub",
        "tokens": {"input": 1, "output": 1},
        "data": {
            "customer": {"company_name": "Acme", "email": "buyer@acme.test", "confidence": 0.9},
            "doors": doors,
            "project": {"tag": "Acme Warehouse"},
            "overall_confidence": confidence,
        },
    })


# ─────────────────────────────────────────────────────────────────────────────
# 2. Routing decisions
# ─────────────────────────────────────────────────────────────────────────────


def test_parts_request_routes_to_manual_pricing(service, session, monkeypatch):
    _stub_parse(monkeypatch, service, doors=[{"model": "replacement panel"}])
    monkeypatch.setattr(service.ai_client, "map_email_to_configurator", lambda *a, **k: {
        "success": True, "request_kind": "parts_request", "doors": [], "confidence": 0.9,
    })
    # build must NOT be called for a parts request
    import app.api.door_configurator as dc
    monkeypatch.setattr(dc, "build_bc_quote_from_doors",
                        lambda *a, **k: pytest.fail("configurator should not run for parts_request"))

    log = _make_email(session)
    service._parse_quote_request(session, log, "RFQ", "need 2 replacement panels",
                                 "Buyer", "buyer@acme.test")

    qr = session.query(QuoteRequest).one()
    assert qr.status == "needs_manual_pricing"
    assert qr.bc_quote_id is None


def test_missing_dimensions_routes_to_manual_review(service, session, monkeypatch):
    _stub_parse(monkeypatch, service, doors=[{"model": "TX450"}])
    monkeypatch.setattr(service.ai_client, "map_email_to_configurator", lambda *a, **k: {
        "success": True, "request_kind": "door_quote", "confidence": 0.9,
        "doors": [{"doorType": "commercial", "doorSeries": "TX450",
                   "doorWidth": 0, "doorHeight": 0, "panelColor": "WHITE",
                   "panelDesign": "FLUSH", "hardware": {"springs": True}}],
    })
    import app.api.door_configurator as dc
    monkeypatch.setattr(dc, "build_bc_quote_from_doors",
                        lambda *a, **k: pytest.fail("configurator should not run without dims"))

    log = _make_email(session)
    service._parse_quote_request(session, log, "RFQ", "want a TX450",
                                 "Buyer", "buyer@acme.test")

    qr = session.query(QuoteRequest).one()
    assert qr.status == "needs_manual_review"


def test_mapping_failure_routes_to_manual_review(service, session, monkeypatch):
    _stub_parse(monkeypatch, service, doors=[{"model": "TX450"}])
    monkeypatch.setattr(service.ai_client, "map_email_to_configurator", lambda *a, **k: {
        "success": False, "error": "boom", "request_kind": "unknown", "doors": [],
    })
    log = _make_email(session)
    service._parse_quote_request(session, log, "RFQ", "body", "Buyer", "buyer@acme.test")
    qr = session.query(QuoteRequest).one()
    assert qr.status == "needs_manual_review"


def test_door_quote_runs_configurator_and_persists_bc_pricing(service, session, monkeypatch):
    _stub_parse(monkeypatch, service, doors=[{"model": "TX450", "width_ft": 12, "height_ft": 10}])
    monkeypatch.setattr(service.ai_client, "map_email_to_configurator", lambda *a, **k: {
        "success": True, "request_kind": "door_quote", "confidence": 0.9,
        "doors": [{"doorType": "commercial", "doorSeries": "TX450",
                   "doorWidth": 144, "doorHeight": 120, "panelColor": "WHITE",
                   "panelDesign": "FLUSH", "doorCount": 1,
                   "hardware": {"tracks": True, "springs": True}}],
    })

    captured = {}

    def _fake_build(request, db, source="admin"):
        captured["source"] = source
        captured["doors"] = request.doors
        captured["customerId"] = request.customerId
        return {
            "success": True,
            "data": {
                "bc_quote_number": "SQ-TEST-1",
                "pricing": {"subtotal": 1000.0, "tax": 50.0, "total": 1050.0},
                "line_pricing": [
                    {"part_number": "PN45-24400-1200", "description": "SECTION TX450",
                     "quantity": 5, "unit_price": 120.0, "line_total": 600.0},
                    {"part_number": "HK03-1612X-RC", "description": "HARDWARE",
                     "quantity": 1, "unit_price": 400.0, "line_total": 400.0},
                ],
            },
        }

    import app.api.door_configurator as dc
    monkeypatch.setattr(dc, "build_bc_quote_from_doors", _fake_build)

    log = _make_email(session)
    service._parse_quote_request(session, log, "RFQ", "12x10 TX450", "Buyer", "buyer@acme.test")

    qr = session.query(QuoteRequest).one()
    assert qr.status == "bc_created"
    assert qr.bc_quote_id == "SQ-TEST-1"
    # the configurator was driven through the email source + mapped door
    assert captured["source"] == "email"
    assert captured["doors"][0].doorSeries == "TX450"
    # BC line pricing mirrored into local QuoteItems (not placeholder margins)
    items = session.query(QuoteItem).filter_by(quote_request_id=qr.id).all()
    assert {i.product_code for i in items} == {"PN45-24400-1200", "HK03-1612X-RC"}
    assert sum(float(i.total_price) for i in items) == 1000.0


def test_resolve_bc_customer_matches_by_email_then_name(service, session):
    session.add(BCCustomer(bc_customer_id="BC-1", company_name="Acme Doors",
                           email="buyer@acme.test", pricing_tier="gold"))
    session.commit()

    qr_email = QuoteRequest(email_id=None, customer_name="Someone Else",
                            contact_email="buyer@acme.test")
    # email match wins
    assert service._resolve_bc_customer_id(session, qr_email) == "BC-1"

    # fall back to company-name match when email misses
    qr_name = QuoteRequest(email_id=None, customer_name="Acme Doors",
                           contact_email="nobody@nowhere.test")
    assert service._resolve_bc_customer_id(session, qr_name) == "BC-1"

    # no match → None (CASH/retail)
    qr_none = QuoteRequest(email_id=None, customer_name="Unknown Co",
                           contact_email="x@y.test")
    assert service._resolve_bc_customer_id(session, qr_none) is None
