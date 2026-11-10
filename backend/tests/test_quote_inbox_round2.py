"""Round 2 quote inbox: attachments, drafts, and customer approvals.

The switches default to off. These tests turn one on, or to shadow, on
the database they build. Graph and Business Central are the edges. The
parser, the draft text, and the match run for real.
"""
from __future__ import annotations

import base64
import os
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.db.models import (
    AIDecision,
    AppSettings,
    BCCustomer,
    CustomerOrderApproval,
    CustomerProfile,
    EmailLog,
    OpsOutboundMessage,
    QuoteItem,
    QuoteRequest,
)
from app.services.customer_profile_service import apply_customer_profile, set_quoting_mode
from app.services.email_monitor import EmailMonitorService
from app.services.inbox_settings import set_inbox_mode
from app.services.part_number_service import get_parts_for_door_config


def _engine():
    engine = create_engine(
        "sqlite://",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    for model in (
        EmailLog, BCCustomer, CustomerProfile, AppSettings, QuoteRequest,
        AIDecision, QuoteItem, OpsOutboundMessage, CustomerOrderApproval,
    ):
        model.__table__.create(engine, checkfirst=True)
    return engine


@pytest.fixture
def session():
    db = sessionmaker(bind=_engine(), autoflush=False, autocommit=False)()
    try:
        yield db
    finally:
        db.close()


def _pdf(text: str) -> bytes:
    from fpdf import FPDF
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", size=14)
    pdf.multi_cell(0, 8, text)
    return bytes(pdf.output())


def _graph(files):
    calls = {"attachments": 0, "send": 0}

    class Graph:
        def get_message_attachments(self, mailbox, message_id):
            calls["attachments"] += 1
            return files

        def send_mail(self, *args, **kwargs):
            calls["send"] += 1
            raise AssertionError("mail was sent")

        def send_reply(self, *args, **kwargs):
            calls["send"] += 1
            raise AssertionError("a reply was sent")

    return Graph(), calls


def _email(message_id="graph-1", internet="mid-1", subject="RFQ", body="Please quote.", sender="buyer@acme.test"):
    return {
        "id": message_id,
        "internetMessageId": internet,
        "subject": subject,
        "receivedDateTime": "2026-11-10T15:00:00Z",
        "from": {"emailAddress": {"address": sender, "name": "Buyer"}},
        "body": {"content": body},
    }


def _stub_ai(monkeypatch, service, seen, doors=None, confidence=0.9):
    doors = doors if doors is not None else [{"model": "TX450"}]

    def parse(subject, body, sender, example_context=None):
        seen["body"] = body
        return {
            "success": True,
            "confidence": confidence,
            "model": "stub",
            "tokens": {"input": 1, "output": 1},
            "data": {
                "customer": {"company_name": "Acme", "email": sender.get("email"), "confidence": 0.9},
                "doors": doors,
                "project": {},
            },
        }

    monkeypatch.setattr(service.ai_client, "parse_email_for_quote", parse)
    monkeypatch.setattr(
        "app.services.email_monitor.get_memory_service",
        lambda db: SimpleNamespace(
            retrieve_similar_examples=lambda *a, **k: [],
            format_examples_for_prompt=lambda *a, **k: "",
            get_customer_context=lambda *a, **k: "",
            get_calibrated_confidence=lambda raw, **k: raw,
            _add_to_example_library=lambda *a, **k: None,
            learn_customer_preferences=lambda *a, **k: None,
        ),
    )


def _categorize(monkeypatch, category):
    monkeypatch.setattr(
        "app.services.email_categorization_service.get_categorization_service",
        lambda db: SimpleNamespace(
            categorize_email=lambda subject, body, sender: {
                "category": category,
                "confidence": 0.9,
                "reasoning": "test",
                "is_modification": False,
            }
        ),
    )


def _mapped_door(**extra):
    door = {
        "doorType": "commercial",
        "doorSeries": "TX450",
        "doorWidth": 120,
        "doorHeight": 96,
        "panelColor": "WHITE",
        "panelDesign": "FLUSH",
        "doorCount": 1,
        "trackMount": "bracket",
        "trackThickness": "3",
        "hardware": {"tracks": True, "springs": True},
    }
    door.update(extra)
    return door


def test_release_refuses_a_customer_match_hold(session, monkeypatch):
    from app.api.feedback import release_held_quote
    log = EmailLog(message_id="hold", from_address="a@b.test", subject="s", body="b", status="parsed")
    session.add(log)
    session.flush()
    quote = QuoteRequest(
        email_id=log.id, customer_name="Acme", contact_email="a@b.test",
        status="held_for_customer_match", confidence_scores={"overall": 0.5},
        parsed_data={"configurator_mapping": {"doors": [_mapped_door()]}},
        customer_match={"bc_customer_id": "CASH", "suggested": True, "confident": False},
    )
    session.add(quote)
    session.commit()
    import app.api.door_configurator as dc
    monkeypatch.setattr(dc, "build_bc_quote_from_doors", lambda *a, **k: pytest.fail("must not price"))
    with pytest.raises(HTTPException) as caught:
        release_held_quote(quote.id, session, SimpleNamespace(email="joey@opendc.ca"))
    assert caught.value.status_code == 400
    session.refresh(quote)
    assert quote.bc_quote_id is None
    assert quote.status == "held_for_customer_match"


def test_release_is_idempotent(session, monkeypatch):
    from app.api.feedback import release_held_quote
    log = EmailLog(message_id="twice", from_address="a@b.test", subject="s", body="bracket", status="parsed")
    session.add(log)
    session.flush()
    quote = QuoteRequest(
        email_id=log.id, customer_name="Acme", contact_email="a@b.test",
        status="held_for_standard_deviation", confidence_scores={"overall": 0.9},
        matched_bc_customer_id="ACME",
        parsed_data={"configurator_mapping": {"doors": [_mapped_door()]}},
        field_sources={"deliveryType": {"value": "delivery", "used": "delivery"}},
    )
    session.add(quote)
    session.commit()
    calls = []

    def _build(request, db, source="admin", **kwargs):
        calls.append(request.doors[0].trackMount)
        return {"success": True, "data": {"bc_quote_number": "SQ-200", "line_pricing": [], "pricing": {"total": 1}}}

    import app.api.door_configurator as dc
    monkeypatch.setattr(dc, "build_bc_quote_from_doors", _build)
    user = SimpleNamespace(email="joey@opendc.ca")
    first = release_held_quote(quote.id, session, user)
    second = release_held_quote(quote.id, session, user)
    assert first["bc_quote_number"] == "SQ-200"
    assert second["already"] is True
    assert second["bc_quote_number"] == "SQ-200"
    assert calls == ["bracket"]


def test_confirm_off_does_not_apply_the_profile_or_label_itself_on(session, monkeypatch):
    from app.api.feedback import confirm_suggested_customer
    log = EmailLog(message_id="off", from_address="pat@acme.test", subject="q", body="Please quote a door.", status="parsed")
    session.add(log)
    session.flush()
    session.add(BCCustomer(bc_customer_id="ACME", company_name="Acme", email="orders@acme.test"))
    session.add(CustomerProfile(
        bc_customer_id="ACME",
        fields={"panel_color": {
            "value": "BLACK", "locked": True, "confidence": 1,
            "support": 4, "total": 4, "evidence": "black", "source": "staff",
        }},
        contacts=[], email_domains=[],
    ))
    quote = QuoteRequest(
        email_id=log.id, customer_name="Pat", contact_email="pat@acme.test",
        status="held_for_customer_match", confidence_scores={"overall": 0.5},
        parsed_data={"configurator_mapping": {"doors": [_mapped_door(panelColor="WHITE")]}},
        customer_match={"bc_customer_id": "ACME", "method": "domain", "suggested": True, "confident": False},
    )
    session.add(quote)
    session.commit()
    seen = {}

    def _build(request, db, source="admin", **kwargs):
        seen["color"] = request.doors[0].panelColor
        seen["applied"] = request.profileApplied
        return {"success": True, "data": {"bc_quote_number": "SQ-OFF", "line_pricing": [], "pricing": {"total": 1}}}

    import app.api.door_configurator as dc
    monkeypatch.setattr(dc, "build_bc_quote_from_doors", _build)
    result = confirm_suggested_customer(quote.id, session, SimpleNamespace(email="joey@opendc.ca"))
    session.refresh(quote)
    assert result["priced"] is True
    assert seen["color"] == "WHITE"
    assert seen["applied"] is False
    assert quote.field_sources["mode"] == "off"


def test_confirm_shadow_prices_the_original_door_and_labels_shadow(session, monkeypatch):
    from app.api.feedback import confirm_suggested_customer
    set_quoting_mode(session, "shadow")
    session.commit()
    log = EmailLog(message_id="sh", from_address="pat@acme.test", subject="q", body="Please quote a door.", status="parsed")
    session.add(log)
    session.flush()
    session.add(BCCustomer(bc_customer_id="ACME", company_name="Acme", email="orders@acme.test"))
    session.add(CustomerProfile(
        bc_customer_id="ACME",
        fields={"panel_color": {
            "value": "BLACK", "locked": True, "confidence": 1,
            "support": 4, "total": 4, "evidence": "black", "source": "staff",
        }},
        contacts=[], email_domains=[],
    ))
    quote = QuoteRequest(
        email_id=log.id, customer_name="Pat", contact_email="pat@acme.test",
        status="held_for_customer_match", confidence_scores={"overall": 0.5},
        parsed_data={"configurator_mapping": {"doors": [_mapped_door(panelColor="WHITE")]}},
        customer_match={"bc_customer_id": "ACME", "method": "domain", "suggested": True, "confident": False},
    )
    session.add(quote)
    session.commit()
    seen = {}

    def _build(request, db, source="admin", **kwargs):
        seen["color"] = request.doors[0].panelColor
        return {"success": True, "data": {"bc_quote_number": "SQ-SH", "line_pricing": [], "pricing": {"total": 1}}}

    import app.api.door_configurator as dc
    monkeypatch.setattr(dc, "build_bc_quote_from_doors", _build)
    confirm_suggested_customer(quote.id, session, SimpleNamespace(email="joey@opendc.ca"))
    session.refresh(quote)
    assert seen["color"] == "WHITE"
    assert quote.field_sources["mode"] == "shadow"
    color = quote.field_sources["doors"][0]["panelColor"]
    assert color["profile_says"] == "BLACK"


def test_omitted_3_inch_radius_is_15_and_an_explicit_12_is_a_deviation():
    door = {
        "doorType": "commercial", "doorSeries": "TX450",
        "doorWidth": 144, "doorHeight": 120, "doorCount": 1,
        "panelColor": "WHITE", "panelDesign": "FLUSH",
        "trackThickness": "3", "trackMount": "bracket",
        "hardware": {"tracks": True, "springs": True},
    }
    applied = apply_customer_profile([dict(door)], email_text="Please quote this door.")
    assert applied["doors"][0]["trackRadius"] == "15"
    parts = get_parts_for_door_config({**door, "trackRadius": "12"})
    kinds = [item.get("kind") for item in parts.get("deviations") or []]
    assert "track_radius_adjusted" in kinds


def test_attachment_reading_off_does_not_fetch_files(session, monkeypatch):
    service = EmailMonitorService()
    graph, calls = _graph([])
    service.graph_client = graph
    seen = {}
    _stub_ai(monkeypatch, service, seen)
    _categorize(monkeypatch, "quote_request")
    monkeypatch.setattr(service.ai_client, "map_email_to_configurator", lambda *a, **k: {
        "success": False, "error": "skip", "doors": [],
    })
    service._process_single_email(session, _email(), "joey@opendc.ca")
    assert calls["attachments"] == 0
    assert calls["send"] == 0
    assert "Door opening" not in (seen.get("body") or "")


def test_attachment_text_is_email_says_and_openings_name_the_page(session, monkeypatch):
    set_quoting_mode(session, "on")
    set_inbox_mode(session, "email_attachment_reading", "on")
    session.add(BCCustomer(bc_customer_id="ACME", company_name="Acme", email="buyer@acme.test"))
    session.add(CustomerProfile(
        bc_customer_id="ACME",
        fields={"track_mount": {
            "value": "angle", "locked": True, "confidence": 1,
            "support": 8, "total": 8, "evidence": "angle", "source": "staff",
        }},
        contacts=[], email_domains=[],
    ))
    session.commit()
    pdf = _pdf("Door opening 10 ft x 12 ft TX450 grey bracket mount")
    encoded = base64.b64encode(pdf).decode()
    graph, calls = _graph([{
        "name": "plan.pdf",
        "contentType": "application/pdf",
        "contentBytes": encoded,
    }])
    service = EmailMonitorService()
    service.graph_client = graph
    seen = {}
    _stub_ai(monkeypatch, service, seen, doors=[{"model": "TX450", "width_ft": 10, "height_ft": 12}])
    _categorize(monkeypatch, "quote_request")
    monkeypatch.setattr(service.ai_client, "map_email_to_configurator", lambda *a, **k: {
        "success": True,
        "request_kind": "door_quote",
        "confidence": 0.9,
        "doors": [_mapped_door(trackMount="bracket", trackThickness="2")],
    })
    import app.api.door_configurator as dc
    monkeypatch.setattr(dc, "build_bc_quote_from_doors", lambda *a, **k: pytest.fail("held quotes are not priced"))
    service._process_single_email(session, _email(body="See the attached plan."), "joey@opendc.ca")
    assert calls["send"] == 0
    assert "bracket" in seen["body"]
    assert "plan.pdf page 1" in seen["body"]
    quote = session.query(QuoteRequest).one()
    read = quote.parsed_data["attachments_read"]
    assert read["applied"] is True
    assert read["opening_count"] == 1
    assert read["openings"][0]["file"] == "plan.pdf"
    assert read["openings"][0]["page"] == 1
    assert quote.status == "held_for_standard_deviation"
    mount = quote.field_sources["doors"][0]["trackMount"]
    assert mount["email_says"] == "bracket"
    assert mount["used"] == "bracket"


def test_attachment_shadow_logs_openings_without_changing_the_parse(session, monkeypatch):
    set_inbox_mode(session, "email_attachment_reading", "shadow")
    session.commit()
    pdf = _pdf("Door opening 9 ft x 8 ft TX450 bracket mount")
    graph, calls = _graph([{
        "name": "shop.pdf",
        "contentType": "application/pdf",
        "contentBytes": base64.b64encode(pdf).decode(),
    }])
    service = EmailMonitorService()
    service.graph_client = graph
    seen = {}
    _stub_ai(monkeypatch, service, seen)
    _categorize(monkeypatch, "quote_request")
    monkeypatch.setattr(service.ai_client, "map_email_to_configurator", lambda *a, **k: {
        "success": False, "error": "skip", "doors": [],
    })
    service._process_single_email(session, _email(body="Please quote."), "joey@opendc.ca")
    assert calls["attachments"] == 1
    assert "bracket" not in seen["body"]
    quote = session.query(QuoteRequest).one()
    assert quote.parsed_data["attachments_read"]["applied"] is False
    assert quote.parsed_data["attachments_read"]["opening_count"] == 1
    assert session.query(OpsOutboundMessage).count() == 0


def test_image_page_is_listed_when_ocr_cannot_read_it():
    from app.services.attachment_text import read_graph_attachments
    png = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
    )
    pack = read_graph_attachments([{
        "name": "scan.png",
        "contentType": "image/png",
        "contentBytes": base64.b64encode(png).decode(),
    }])
    assert pack.pages[0].file_name == "scan.png"
    assert pack.pages[0].page == 1
    assert pack.pages[0].method in {"ocr", "ocr_unavailable"}
    view = pack.staff_payload(True)
    assert view["files"][0]["name"] == "scan.png"


def test_dxf_text_is_an_opening(tmp_path):
    import ezdxf
    from app.services.attachment_text import read_graph_attachments
    doc = ezdxf.new()
    doc.modelspace().add_text("Door opening 10 ft x 12 ft", dxfattribs={"insert": (0, 0), "height": 2.5})
    path = tmp_path / "shop.dxf"
    doc.saveas(path)
    pack = read_graph_attachments([{
        "name": "shop.dxf",
        "contentType": "application/dxf",
        "contentBytes": base64.b64encode(path.read_bytes()).decode(),
    }])
    assert pack.pages[0].method == "dxf"
    assert pack.openings[0]["file"] == "shop.dxf"
    assert pack.openings[0]["width_in"] == 120
    assert pack.openings[0]["height_in"] == 144


def test_missing_info_on_queues_one_draft_and_does_not_send(session, monkeypatch):
    set_inbox_mode(session, "missing_info_reply", "on")
    session.commit()
    service = EmailMonitorService()
    graph, calls = _graph([])
    service.graph_client = graph
    seen = {}
    _stub_ai(monkeypatch, service, seen, doors=[{"model": "TX450"}])
    _categorize(monkeypatch, "quote_request")
    monkeypatch.setattr(service.ai_client, "map_email_to_configurator", lambda *a, **k: {
        "success": False, "error": "no drawing", "doors": [],
    })
    service._process_single_email(session, _email(body="Can you quote a door?"), "joey@opendc.ca")
    rows = session.query(OpsOutboundMessage).all()
    assert len(rows) == 1
    assert rows[0].kind == "missing_info_reply"
    assert rows[0].status == "pending"
    assert "width and height" in rows[0].body_text
    assert "If we don't hear back" in rows[0].body_text
    assert calls["send"] == 0
    service._process_single_email(session, _email(internet="mid-2", message_id="graph-2"), "joey@opendc.ca")
    assert session.query(OpsOutboundMessage).count() == 2


def test_missing_info_shadow_does_not_create_a_draft(session, monkeypatch):
    set_inbox_mode(session, "missing_info_reply", "shadow")
    session.commit()
    service = EmailMonitorService()
    graph, calls = _graph([])
    service.graph_client = graph
    _stub_ai(monkeypatch, service, {})
    _categorize(monkeypatch, "quote_request")
    monkeypatch.setattr(service.ai_client, "map_email_to_configurator", lambda *a, **k: {
        "success": False, "error": "no drawing", "doors": [],
    })
    service._process_single_email(session, _email(), "joey@opendc.ca")
    assert session.query(OpsOutboundMessage).count() == 0
    quote = session.query(QuoteRequest).one()
    assert quote.parsed_data["inbox_shadow"][0]["kind"] == "missing_info_reply"
    assert calls["send"] == 0


def test_quote_send_draft_waits_for_approval_and_approve_attaches_the_pdf(session, monkeypatch):
    set_inbox_mode(session, "quote_send_draft", "on")
    session.commit()
    service = EmailMonitorService()
    graph, calls = _graph([])
    service.graph_client = graph
    _stub_ai(monkeypatch, service, {}, doors=[{"model": "TX450", "width_ft": 10, "height_ft": 10}])
    _categorize(monkeypatch, "quote_request")
    monkeypatch.setattr(service.ai_client, "map_email_to_configurator", lambda *a, **k: {
        "success": True,
        "request_kind": "door_quote",
        "confidence": 0.9,
        "doors": [_mapped_door()],
    })

    def _build(request, db, source="admin", **kwargs):
        return {"success": True, "data": {"bc_quote_number": "SQ-310", "line_pricing": [], "pricing": {"total": 10}}}

    import app.api.door_configurator as dc
    monkeypatch.setattr(dc, "build_bc_quote_from_doors", _build)
    service._process_single_email(
        session,
        _email(body="Please quote a 10x10 TX450."),
        "joey@opendc.ca",
    )
    assert calls["send"] == 0
    draft = session.query(OpsOutboundMessage).filter_by(kind="quote_send").one()
    assert draft.status == "pending"
    assert "SQ-310" in draft.body_text
    assert draft.context_json["attach_quote_pdf"] is True
    assert draft.context_json["reply_to_message_id"] == "graph-1"

    sent = {}

    def send_reply(mailbox, message_id, html, attachments=None):
        sent["reply"] = (mailbox, message_id, attachments)

    monkeypatch.setattr("app.integrations.email.client.graph_client.app", object())
    monkeypatch.setattr("app.integrations.email.client.graph_client.send_reply", send_reply)
    monkeypatch.setattr("app.integrations.email.client.graph_client.send_mail", lambda *a, **k: pytest.fail("new message"))
    monkeypatch.setattr(
        "app.integrations.bc.client.bc_client.get_sales_quote_by_number",
        lambda number: {"id": "guid-310", "number": number},
    )
    monkeypatch.setattr("app.integrations.bc.client.bc_client.get_quote_pdf", lambda guid: b"%PDF-1.4 quote")
    from app.services.ops_tracker_service import default_sender
    default_sender({
        "to_email": draft.to_email,
        "subject": draft.subject,
        "body_text": draft.body_text,
        "context": draft.context_json,
    })
    assert sent["reply"][0] == "joey@opendc.ca"
    assert sent["reply"][1] == "graph-1"
    assert sent["reply"][2][0]["name"].endswith(".pdf")
    assert sent["reply"][2][0]["content_bytes"].startswith(b"%PDF")


def test_order_confirmation_is_dropped_when_detection_is_off(session, monkeypatch):
    service = EmailMonitorService()
    graph, calls = _graph([])
    service.graph_client = graph
    _categorize(monkeypatch, "order_confirmation")
    monkeypatch.setattr(service.ai_client, "parse_email_for_quote", lambda *a, **k: pytest.fail("not a quote"))
    result = service._process_single_email(
        session,
        _email(subject="Re: quote", body="Approved SQ-1001"),
        "joey@opendc.ca",
    )
    assert result == "other"
    assert session.query(CustomerOrderApproval).count() == 0
    assert session.query(QuoteRequest).count() == 0
    assert calls["send"] == 0


def test_approval_matches_one_sq_and_convert_is_once(session, monkeypatch):
    set_inbox_mode(session, "customer_approval_detection", "on")
    log = EmailLog(message_id="old", from_address="buyer@acme.test", subject="Quote", body="old", status="parsed")
    session.add(log)
    session.flush()
    session.add(QuoteRequest(
        email_id=log.id, customer_name="Acme", contact_email="buyer@acme.test",
        status="bc_created", confidence_scores={"overall": 0.9},
        bc_quote_id="SQ-1001", created_at=datetime.utcnow(),
    ))
    session.commit()
    service = EmailMonitorService()
    pdf = _pdf("Purchase order")
    graph, calls = _graph([{
        "name": "PO-44521.pdf",
        "contentType": "application/pdf",
        "contentBytes": base64.b64encode(pdf).decode(),
    }])
    service.graph_client = graph
    _categorize(monkeypatch, "order_confirmation")
    monkeypatch.setattr(service.ai_client, "parse_email_for_quote", lambda *a, **k: pytest.fail("not a quote"))
    result = service._process_single_email(
        session,
        _email(subject="Go ahead", body="Approved SQ-1001. PO attached."),
        "joey@opendc.ca",
    )
    assert result == "customer_approval"
    assert calls["send"] == 0
    row = session.query(CustomerOrderApproval).one()
    assert row.status == "ready"
    assert row.bc_quote_number == "SQ-1001"
    assert row.customer_po == "44521"
    assert row.po_source.startswith("attachment")

    calls_convert = []

    def fake_convert(self, db, quote_id, user):
        calls_convert.append(quote_id)
        return {"success": True, "bc_order_number": "SO-88", "bc_order_id": "guid-so"}

    pos = []
    monkeypatch.setattr(
        "app.services.order_lifecycle_service.OrderLifecycleService.convert_quote_to_order",
        fake_convert,
    )
    monkeypatch.setattr(
        "app.integrations.bc.client.bc_client.update_sales_order",
        lambda order_id, data: pos.append(data),
    )
    from app.services.quote_followup import convert_customer_approval
    first = convert_customer_approval(session, row.id, bc_quote_number=None, user_email="joey@opendc.ca")
    second = convert_customer_approval(session, row.id, bc_quote_number=None, user_email="joey@opendc.ca")
    assert first["bc_order_number"] == "SO-88"
    assert second["already"] is True
    assert len(calls_convert) == 1
    assert pos == [{"externalDocumentNumber": "44521"}]


def test_ambiguous_approval_is_held_until_staff_choose(session, monkeypatch):
    set_inbox_mode(session, "customer_approval_detection", "on")
    session.commit()
    for number in ("SQ-1", "SQ-2"):
        log = EmailLog(
            message_id=number, from_address="buyer@acme.test",
            subject="Quote", body="old", status="parsed",
        )
        session.add(log)
        session.flush()
        session.add(QuoteRequest(
            email_id=log.id, customer_name="Acme", contact_email="buyer@acme.test",
            status="bc_created", confidence_scores={"overall": 0.9},
            bc_quote_id=number, created_at=datetime.utcnow(),
        ))
    session.commit()
    service = EmailMonitorService()
    graph, calls = _graph([])
    service.graph_client = graph
    _categorize(monkeypatch, "order_confirmation")
    result = service._process_single_email(
        session,
        _email(subject="Approved", body="Go ahead."),
        "joey@opendc.ca",
    )
    assert result == "customer_approval"
    row = session.query(CustomerOrderApproval).one()
    assert row.status == "needs_choice"
    assert row.bc_quote_number is None
    assert {item["bc_quote_number"] for item in row.candidates} == {"SQ-1", "SQ-2"}
    from app.services.quote_followup import convert_customer_approval
    with pytest.raises(HTTPException) as caught:
        convert_customer_approval(session, row.id, bc_quote_number=None, user_email="joey@opendc.ca")
    assert caught.value.status_code == 400
    assert calls["send"] == 0


def test_approval_shadow_does_not_queue(session, monkeypatch):
    set_inbox_mode(session, "customer_approval_detection", "shadow")
    session.commit()
    service = EmailMonitorService()
    graph, _calls = _graph([])
    service.graph_client = graph
    _categorize(monkeypatch, "order_confirmation")
    service._process_single_email(
        session,
        _email(subject="Approved", body="Approved SQ-9"),
        "joey@opendc.ca",
    )
    assert session.query(CustomerOrderApproval).count() == 0
    log = session.query(EmailLog).one()
    note = [item for item in (log.attachments or []) if isinstance(item, dict) and item.get("kind") == "customer_approval"]
    assert note and note[0]["shadow"] is True


def test_customer_approval_routes_require_a_token():
    from app.api import feedback
    from app.db.database import get_db as real_get_db
    app = FastAPI()
    app.include_router(feedback.router)

    def _db():
        yield None

    app.dependency_overrides[feedback.get_db] = _db
    app.dependency_overrides[real_get_db] = _db
    client = TestClient(app)
    assert client.get("/api/quotes/customer-approvals").status_code == 401
    assert client.post("/api/quotes/customer-approvals/1/convert").status_code == 401
    assert client.post("/api/quotes/customer-approvals/1/dismiss").status_code == 401


def test_inbox_migration_upgrades_and_downgrades(tmp_path):
    import importlib.util
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    engine = create_engine(f"sqlite:///{tmp_path}/inbox.db")
    path = Path(__file__).resolve().parents[1] / "alembic" / "versions" / "b9c0d1e2f4a5_quote_inbox_round2.py"
    spec = importlib.util.spec_from_file_location("inbox_revision", path)
    revision = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(revision)
    with engine.begin() as connection:
        ctx = MigrationContext.configure(connection)
        with Operations.context(ctx):
            revision.upgrade()
    assert "customer_order_approvals" in inspect(engine).get_table_names()
    with engine.begin() as connection:
        ctx = MigrationContext.configure(connection)
        with Operations.context(ctx):
            revision.downgrade()
    assert "customer_order_approvals" not in inspect(engine).get_table_names()
