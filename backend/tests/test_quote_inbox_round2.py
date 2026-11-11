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
        def get_message_attachments(self, mailbox, message_id, **kwargs):
            calls["attachments"] += 1
            calls["cap_bytes"] = kwargs.get("cap_bytes")
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
    result = service._process_single_email(
        session,
        _email(subject="Approved", body="Approved SQ-9"),
        "joey@opendc.ca",
    )
    assert result == "other"
    assert session.query(CustomerOrderApproval).count() == 0
    log = session.query(EmailLog).one()
    assert not any(isinstance(item, dict) and item.get("kind") == "customer_approval" for item in (log.attachments or []))
    note = [item for item in (log.inbox_shadow or []) if item.get("kind") == "customer_approval"]
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


def test_shadow_approval_does_not_swallow_a_quote_request(session, monkeypatch):
    set_inbox_mode(session, "customer_approval_detection", "shadow")
    session.commit()
    service = EmailMonitorService()
    graph, calls = _graph([])
    service.graph_client = graph
    seen = {}
    _stub_ai(monkeypatch, service, seen, doors=[{"model": "TX450", "width_ft": 10, "height_ft": 10}])
    _categorize(monkeypatch, "quote_request")
    monkeypatch.setattr(service.ai_client, "map_email_to_configurator", lambda *a, **k: {
        "success": False, "error": "stop", "doors": [],
    })
    result = service._process_single_email(
        session,
        _email(subject="New door", body="Approved SQ-100. Please ignore that, this is a new note."),
        "joey@opendc.ca",
    )
    # "Approved SQ-100" with no new-quote wording is an approval. Shadow logs it
    # and still parses the message as the categorizer's quote request.
    assert result == "quote_request"
    assert "body" in seen
    assert session.query(QuoteRequest).count() == 1
    assert session.query(CustomerOrderApproval).count() == 0
    assert calls["send"] == 0


def test_approval_phrases_ignore_negation_changes_and_quoted_history():
    from app.services.quote_followup import customer_po_number, is_customer_approval
    assert is_customer_approval("order_confirmation", "Re: quote", "This is not approved yet") is False
    assert is_customer_approval("quote_modification", "Re: quote", "Go ahead and change the colour to black") is False
    assert is_customer_approval(
        "quote_request",
        "New opening",
        "Please quote a 10 ft x 12 ft TX450. The previous SQ-1001 was approved.",
    ) is False
    assert is_customer_approval("order_confirmation", "Re: quote", "Approved SQ-1001") is True
    po, source = customer_po_number(
        "Our PO is 11111.\n\nOn Tue, Pat wrote:\n> PO 99999",
        [],
    )
    assert po == "11111"
    assert source == "body"


def test_series_suffix_and_quoted_colour():
    from app.services.customer_profile_service import apply_customer_profile
    door = {
        "doorType": "commercial", "doorSeries": "TX450", "doorWidth": 120, "doorHeight": 96,
        "panelColor": "WHITE", "panelDesign": "FLUSH", "trackMount": "bracket", "trackThickness": "2",
        "doorCount": 1, "hardware": {"tracks": True},
    }
    from app.services.customer_profile_service import quote_email_text
    applied = apply_customer_profile(
        [dict(door)],
        email_text=quote_email_text(
            "",
            "Can you price the TX450-20S or the TX500-20S in black?\n\n"
            "On Tue, Preston wrote:\n> grey flush",
        ),
    )
    assert applied["doors"][0]["doorSeries"] == "TX450-20"
    assert applied["doors"][0]["panelColor"] == "BLACK"
    quiet = apply_customer_profile(
        [dict(door)],
        email_text=quote_email_text("", "Please quote a door.\n\nOn Tue, Pat wrote:\n> grey"),
    )
    assert quiet["doors"][0]["panelColor"] == "WHITE"
    only_500 = apply_customer_profile([dict(door)], email_text="Use the TX500-20S")
    assert only_500["doors"][0]["doorSeries"] == "TX500-20"


def test_man_door_and_brochure_are_not_overhead_openings():
    from app.services.attachment_text import find_openings, read_graph_attachments, PageText
    assert find_openings([PageText("note.txt", 1, "man door 3x7 at the office", "text_layer")]) == []
    pdf = _pdf("Door opening 10 ft x 12 ft grey bracket")
    pack = read_graph_attachments([{
        "name": "TX450 brochure.pdf",
        "contentType": "application/pdf",
        "contentBytes": base64.b64encode(pdf).decode(),
    }])
    assert pack.pages[0].counts_as_email is False
    assert "grey" not in pack.combined_text
    assert pack.as_email_log()[0]["extracted_text"] == ""
    assert pack.openings == []
    assert pack.reference_openings and pack.reference_openings[0]["label"]


def test_attachment_reader_caps_size_and_pages():
    from app.services.attachment_text import MAX_FILE_BYTES, read_graph_attachments
    huge = base64.b64encode(b"x" * (MAX_FILE_BYTES + 10)).decode()
    capped = read_graph_attachments([{"name": "big.pdf", "contentType": "application/pdf", "contentBytes": huge}])
    assert capped.pages[0].method == "too_large"
    from fpdf import FPDF
    pdf = FPDF()
    for index in range(25):
        pdf.add_page()
        pdf.set_font("Helvetica", size=12)
        pdf.cell(text=f"page {index}")
    packed = read_graph_attachments([{
        "name": "long.pdf",
        "contentType": "application/pdf",
        "contentBytes": base64.b64encode(bytes(pdf.output())).decode(),
    }])
    assert any(page.method == "page_cap" for page in packed.pages)
    assert sum(1 for page in packed.pages if page.method == "text_layer") <= 20


def test_unknown_or_other_customers_sq_is_not_ready(session, monkeypatch):
    set_inbox_mode(session, "customer_approval_detection", "on")
    log = EmailLog(message_id="other", from_address="other@shop.test", subject="old", body="old", status="parsed")
    session.add(log)
    session.flush()
    session.add(QuoteRequest(
        email_id=log.id, customer_name="Other", contact_email="other@shop.test",
        status="bc_created", confidence_scores={"overall": 0.9},
        bc_quote_id="SQ-1001", created_at=datetime.utcnow(),
    ))
    session.commit()
    service = EmailMonitorService()
    graph, _calls = _graph([])
    service.graph_client = graph
    _categorize(monkeypatch, "order_confirmation")
    service._process_single_email(
        session,
        _email(subject="Approved", body="Approved SQ-1001"),
        "joey@opendc.ca",
    )
    row = session.query(CustomerOrderApproval).one()
    assert row.status == "needs_choice"
    assert row.bc_quote_number is None
    assert row.candidates == []


def test_one_recent_quote_is_not_ready_on_its_own(session, monkeypatch):
    set_inbox_mode(session, "customer_approval_detection", "on")
    log = EmailLog(message_id="recent", from_address="buyer@acme.test", subject="old", body="old", status="parsed")
    session.add(log)
    session.flush()
    session.add(QuoteRequest(
        email_id=log.id, customer_name="Acme", contact_email="buyer@acme.test",
        status="bc_created", confidence_scores={"overall": 0.9},
        bc_quote_id="SQ-42", created_at=datetime.utcnow(),
    ))
    session.commit()
    service = EmailMonitorService()
    service.graph_client, _calls = _graph([])
    _categorize(monkeypatch, "order_confirmation")
    service._process_single_email(
        session,
        _email(subject="Go ahead", body="Go ahead."),
        "joey@opendc.ca",
    )
    row = session.query(CustomerOrderApproval).one()
    assert row.status == "needs_choice"
    assert row.bc_quote_number is None
    assert row.candidates[0]["bc_quote_number"] == "SQ-42"


def test_a_second_approval_for_the_same_sq_is_not_queued(session, monkeypatch):
    set_inbox_mode(session, "customer_approval_detection", "on")
    log = EmailLog(message_id="first-q", from_address="buyer@acme.test", subject="q", body="q", status="parsed")
    session.add(log)
    session.flush()
    session.add(QuoteRequest(
        email_id=log.id, customer_name="Acme", contact_email="buyer@acme.test",
        status="bc_created", confidence_scores={"overall": 0.9},
        bc_quote_id="SQ-77", created_at=datetime.utcnow(),
    ))
    session.commit()
    service = EmailMonitorService()
    service.graph_client = _graph([])[0]
    _categorize(monkeypatch, "order_confirmation")
    service._process_single_email(
        session, _email(internet="a", message_id="g1", subject="Approved", body="Approved SQ-77"), "joey@opendc.ca",
    )
    service._process_single_email(
        session, _email(internet="b", message_id="g2", subject="Approved", body="Approved SQ-77 again"), "joey@opendc.ca",
    )
    assert session.query(CustomerOrderApproval).count() == 1


def test_convert_refuses_an_unknown_sq_and_a_repeat(session, monkeypatch):
    from app.db.models import SalesOrder
    from app.services.quote_followup import convert_customer_approval
    SalesOrder.__table__.create(session.get_bind(), checkfirst=True)
    log = EmailLog(message_id="conv", from_address="buyer@acme.test", subject="q", body="q", status="parsed")
    session.add(log)
    session.flush()
    quote = QuoteRequest(
        email_id=log.id, customer_name="Acme", contact_email="buyer@acme.test",
        status="converted_to_order", confidence_scores={"overall": 0.9},
        bc_quote_id="SQ-55", created_at=datetime.utcnow(),
    )
    session.add(quote)
    session.flush()
    session.add(SalesOrder(
        quote_request_id=quote.id, bc_order_number="SO-55", bc_order_id="guid-55",
        customer_name="Acme", status="confirmed",
    ))
    session.add(CustomerOrderApproval(
        email_log_id=log.id, status="ready", match_method="number",
        bc_quote_number="SQ-55", quote_request_id=quote.id,
        candidates=[{"bc_quote_number": "SQ-55", "quote_request_id": quote.id, "method": "number"}],
        from_address="buyer@acme.test", subject="Approved", excerpt="Approved SQ-55",
        created_at=datetime.utcnow(),
    ))
    session.commit()
    called = []
    monkeypatch.setattr(
        "app.integrations.bc.client.bc_client.convert_quote_to_order",
        lambda *a, **k: called.append(a),
    )
    approval = session.query(CustomerOrderApproval).one()
    result = convert_customer_approval(session, approval.id, bc_quote_number=None, user_email="joey@opendc.ca")
    assert result["bc_order_number"] == "SO-55"
    assert result["already"] is True
    assert called == []
    unknown = CustomerOrderApproval(
        email_log_id=log.id, status="ready", match_method="number",
        bc_quote_number="SQ-000",
        candidates=[{"bc_quote_number": "SQ-000", "method": "number"}],
        from_address="buyer@acme.test", subject="Approved", excerpt="Approved SQ-000",
        created_at=datetime.utcnow(),
    )
    session.add(unknown)
    session.commit()
    with pytest.raises(HTTPException) as caught:
        convert_customer_approval(session, unknown.id, bc_quote_number=None, user_email="joey@opendc.ca")
    assert caught.value.status_code == 400


def test_reply_draft_honours_an_edit_and_deletes_a_partial_draft():
    from app.integrations.email.client import GraphEmailClient as GraphClient
    from app.services.ops_tracker_service import default_sender
    sent = {}

    class Graph:
        app = object()

        def send_reply(self, *args, **kwargs):
            sent["reply"] = args

        def send_mail(self, **kwargs):
            sent["mail"] = kwargs

    import app.services.ops_tracker_service as ops
    import app.integrations.email.client as email_client
    email_client.graph_client = Graph()
    # default_sender imports graph_client inside the function, so patch the module it imports.
    original = email_client.graph_client
    try:
        message = {
            "to_email": "buyer@acme.test",
            "subject": "Re: plans",
            "body_text": "Attached is quote SQ-1.",
            "context": {
                "reply_to_message_id": "graph-1",
                "reply_to_address": "buyer@acme.test",
                "reply_subject": "Re: plans",
                "mailbox": "joey@opendc.ca",
            },
        }
        default_sender(message)
        assert sent["reply"][1] == "graph-1"
        sent.clear()
        default_sender({**message, "to_email": "pat@acme.test", "subject": "Your quote"})
        assert sent["mail"]["to"] == "pat@acme.test"
        assert sent["mail"]["subject"] == "Your quote"
        assert "reply" not in sent
    finally:
        email_client.graph_client = original

    calls = []

    class Broken(GraphClient):
        def __init__(self):
            pass

        def _make_request(self, method, endpoint, **kwargs):
            calls.append((method, endpoint))
            if method == "POST" and endpoint.endswith("/createReply"):
                return {"id": "draft-1"}
            if method == "PATCH":
                raise RuntimeError("patch failed")
            if method == "DELETE":
                return {}
            raise AssertionError(method)

    client = Broken()
    with pytest.raises(RuntimeError):
        client.send_reply("joey@opendc.ca", "msg-1", "<p>Hi</p>")
    assert ("DELETE", "users/joey@opendc.ca/messages/draft-1") in calls


def test_quote_send_body_keeps_internal_reasons_off_the_customer_draft():
    from app.services.quote_followup import quote_send_body
    body = quote_send_body(
        "SQ-310",
        ["Track radius: 15"],
        [{"reason": "Email requests bracket mount; Acme standard is angle (locked)"}],
    )
    assert "SQ-310" in body
    assert "Track radius: 15" in body
    assert "locked" not in body
    assert "standard is" not in body


def test_post_bc_failure_still_keeps_the_quote_number(session, monkeypatch):
    from app.api.feedback import release_held_quote
    log = EmailLog(message_id="keep", from_address="a@b.test", subject="s", body="b", status="parsed")
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

    def _build(request, db, source="admin", **kwargs):
        return {"success": True, "data": {"bc_quote_number": "SQ-KEEP", "line_pricing": [{"quantity": "bad"}], "pricing": {"total": 1}}}

    import app.api.door_configurator as dc
    monkeypatch.setattr(dc, "build_bc_quote_from_doors", _build)

    def _boom(*args, **kwargs):
        raise RuntimeError("local lines failed")

    monkeypatch.setattr(
        "app.services.email_monitor.EmailMonitorService._persist_quote_items_from_pricing",
        _boom,
    )
    release_held_quote(quote.id, session, SimpleNamespace(email="joey@opendc.ca"))
    session.refresh(quote)
    assert quote.bc_quote_id == "SQ-KEEP"
    assert quote.status == "bc_created"


def test_mail_pointer_is_absent_when_every_switch_is_off(session, monkeypatch):
    service = EmailMonitorService()
    service.graph_client, calls = _graph([])
    seen = {}
    _stub_ai(monkeypatch, service, seen)
    _categorize(monkeypatch, "quote_request")
    monkeypatch.setattr(service.ai_client, "map_email_to_configurator", lambda *a, **k: {
        "success": False, "error": "skip", "doors": [],
    })
    service._process_single_email(session, _email(), "joey@opendc.ca")
    quote = session.query(QuoteRequest).one()
    assert "mail" not in (quote.parsed_data or {})
    assert calls["attachments"] == 0


def test_forwarded_request_is_addressed_to_the_customer():
    from app.services.email_text import reply_recipient
    address, forwarded = reply_recipient(
        "FW: shop plans",
        "See below.\n\n---------- Forwarded message ----------\nFrom: Pat Buyer <buyer@acme.test>\nSubject: doors",
        "joey@opendc.ca",
    )
    assert forwarded is True
    assert address == "buyer@acme.test"


OUTLOOK_REPLY = """<html><body>
<div>Approved SQ-1001. Our PO is 44521.</div>
<div id="divRplyFwdMsg" dir="ltr"><font face="Calibri, sans-serif"><b>From:</b> Joey Heinrichs &lt;joey@opendc.ca&gt;<br>
<b>Sent:</b> Tuesday, November 10, 2026 9:00 AM<br>
<b>To:</b> Preston &lt;preston@doortech.ca&gt;<br>
<b>Subject:</b> RE: warehouse quote</font></div>
<div>Please quote this grey.</div>
</body></html>"""

GMAIL_REPLY = """<div dir="ltr">Approved SQ-1001. Our PO is 44521.</div>
<div class="gmail_quote">
<div class="gmail_attr">On Tue, Nov 10, 2026 at 9:00 AM Pat &lt;pat@acme.test&gt; wrote:</div>
<blockquote class="gmail_quote">Please quote this grey.</blockquote>
</div>"""

APPLE_REPLY = """<html><body>
<div>Approved SQ-1001.</div>
<blockquote type="cite">
<div>On Nov 10, 2026, at 9:00 AM, Pat &lt;pat@acme.test&gt; wrote:</div>
Please quote this grey.
</blockquote>
</body></html>"""

DOORTECH_REPLY = """Thanks Joey, we are good with the price.

-------- Original message --------
From: Joey Heinrichs <joey@opendc.ca>
Date: Tue, 10 Nov 2026 09:00:00 -0600
Subject: RE: warehouse quote

Can you confirm the black TX450?
"""


def test_doortech_reply_is_not_a_forward_to_joey():
    from app.services.email_text import reply_recipient
    address, forwarded = reply_recipient(
        "Re: warehouse quote",
        DOORTECH_REPLY,
        "preston@doortech.ca",
    )
    assert forwarded is False
    assert address == "preston@doortech.ca"
    html = (
        "<div>Thanks, we are good.</div>"
        "<div>-------- Original message --------<br>"
        "From: Joey Heinrichs &lt;joey@opendc.ca&gt;</div>"
    )
    address, forwarded = reply_recipient("Re: warehouse quote", html, "preston@doortech.ca")
    assert forwarded is False
    assert address == "preston@doortech.ca"


def test_outlook_and_gmail_html_quotes_do_not_set_the_old_colour():
    from app.services.customer_profile_service import apply_customer_profile, quote_email_text
    from app.services.quote_followup import customer_po_number, is_customer_approval
    door = {
        "doorType": "commercial", "doorSeries": "TX450", "doorWidth": 120, "doorHeight": 96,
        "panelColor": "WHITE", "panelDesign": "FLUSH", "trackMount": "bracket",
        "trackThickness": "2", "doorCount": 1, "hardware": {"tracks": True},
    }
    for html in (OUTLOOK_REPLY, GMAIL_REPLY, APPLE_REPLY):
        assert is_customer_approval("order_confirmation", "Re: warehouse quote", html) is True
        po, _source = customer_po_number(html, [])
        assert po == "44521" or "PO" not in html
        text = quote_email_text("Re: warehouse quote", html, [{
            "name": "plan.pdf",
            "extracted_text": "12x14 TX450 BLACK",
        }])
        assert "grey" not in text.lower()
        assert "BLACK" in text
        applied = apply_customer_profile([dict(door)], email_text=text)
        assert applied["doors"][0]["panelColor"] == "BLACK"


def test_approval_is_conservative_about_questions_and_changes(session, monkeypatch):
    from app.services.quote_followup import approval_level, is_customer_approval
    assert is_customer_approval("order_confirmation", "Re:", "This hasn't been approved") is False
    assert is_customer_approval("order_confirmation", "Re:", "Has SQ-1001 been approved?") is False
    assert is_customer_approval("order_confirmation", "Re:", "Once SQ-1001 is approved by the GC we can order") is False
    assert is_customer_approval("quote_modification", "Re:", "Please go ahead with the colour change") is False
    assert is_customer_approval("order_confirmation", "Re:", "We can't go ahead with SQ-1001 at this price") is False
    assert is_customer_approval("order_confirmation", "Re:", "Don't go ahead yet") is False
    assert approval_level(
        "quote_modification", "Re: quote", "Go ahead with SQ-1001 but make it black",
    ) == "low"
    set_inbox_mode(session, "customer_approval_detection", "on")
    session.commit()
    service = EmailMonitorService()
    service.graph_client, _calls = _graph([])
    seen = {}
    _stub_ai(monkeypatch, service, seen)
    _categorize(monkeypatch, "quote_modification")

    def _mod(*args, **kwargs):
        seen["modification"] = True

    monkeypatch.setattr(service, "_parse_quote_modification", _mod)
    result = service._process_single_email(
        session,
        _email(subject="Re: quote", body="Go ahead with SQ-1001 but make it black"),
        "joey@opendc.ca",
    )
    assert result == "quote_modification"
    assert seen["modification"] is True
    assert session.query(CustomerOrderApproval).count() == 0
    log = session.query(EmailLog).one()
    assert any(item.get("kind") == "customer_approval_low" for item in (log.inbox_shadow or []))


def test_a_specific_approval_replaces_a_vague_one(session, monkeypatch):
    set_inbox_mode(session, "customer_approval_detection", "on")
    log = EmailLog(message_id="vague-q", from_address="buyer@acme.test", subject="q", body="q", status="parsed")
    session.add(log)
    session.flush()
    session.add(QuoteRequest(
        email_id=log.id, customer_name="Acme", contact_email="buyer@acme.test",
        status="bc_created", confidence_scores={"overall": 0.9},
        bc_quote_id="SQ-1077", matched_bc_customer_id="ACME", created_at=datetime.utcnow(),
    ))
    session.add(CustomerOrderApproval(
        email_log_id=log.id, status="needs_choice", match_method="customer_recent",
        bc_quote_number=None,
        candidates=[{"bc_quote_number": "SQ-1070", "method": "customer_recent", "quote_request_id": None}],
        from_address="buyer@acme.test", subject="Go ahead", excerpt="Go ahead.",
        created_at=datetime.utcnow(),
    ))
    session.commit()
    service = EmailMonitorService()
    service.graph_client = _graph([])[0]
    _categorize(monkeypatch, "order_confirmation")
    service._process_single_email(
        session,
        _email(subject="Approved", body="Approved SQ-1077. PO 44521."),
        "joey@opendc.ca",
    )
    rows = session.query(CustomerOrderApproval).all()
    assert len(rows) == 1
    assert rows[0].status == "ready"
    assert rows[0].bc_quote_number == "SQ-1077"
    assert rows[0].customer_po == "44521"


def test_same_company_domain_matches_and_gmail_does_not(session, monkeypatch):
    set_inbox_mode(session, "customer_approval_detection", "on")
    log = EmailLog(message_id="domain", from_address="orders@acme.test", subject="q", body="q", status="parsed")
    session.add(log)
    session.flush()
    session.add(QuoteRequest(
        email_id=log.id, customer_name="Acme", contact_email="orders@acme.test",
        status="bc_created", confidence_scores={"overall": 0.9},
        bc_quote_id="SQ-1088", matched_bc_customer_id="ACME", created_at=datetime.utcnow(),
    ))
    session.commit()
    service = EmailMonitorService()
    service.graph_client = _graph([])[0]
    _categorize(monkeypatch, "order_confirmation")
    service._process_single_email(
        session,
        _email(sender="pat@acme.test", subject="Approved", body="Approved SQ-1088"),
        "joey@opendc.ca",
    )
    row = session.query(CustomerOrderApproval).one()
    assert row.status == "ready"
    assert row.bc_quote_number == "SQ-1088"
    gmail_log = EmailLog(message_id="gmail", from_address="other@gmail.com", subject="q", body="q", status="parsed")
    session.add(gmail_log)
    session.flush()
    session.add(QuoteRequest(
        email_id=gmail_log.id, customer_name="Someone", contact_email="other@gmail.com",
        status="bc_created", confidence_scores={"overall": 0.9},
        bc_quote_id="SQ-1089", created_at=datetime.utcnow(),
    ))
    session.commit()
    service._process_single_email(
        session,
        _email(sender="pat@gmail.com", internet="g", message_id="g", subject="Approved", body="Approved SQ-1089"),
        "joey@opendc.ca",
    )
    gmail_row = session.query(CustomerOrderApproval).filter_by(from_address="pat@gmail.com").one()
    assert gmail_row.bc_quote_number is None


def test_staff_can_pick_another_sq_for_the_same_bc_customer(session, monkeypatch):
    from app.services.quote_followup import convert_customer_approval
    log = EmailLog(message_id="staff", from_address="pat@acme.test", subject="q", body="q", status="parsed")
    session.add(log)
    session.flush()
    session.add(QuoteRequest(
        email_id=log.id, customer_name="Acme", contact_email="pat@acme.test",
        status="bc_created", confidence_scores={"overall": 0.9},
        bc_quote_id="SQ-1", matched_bc_customer_id="ACME", created_at=datetime.utcnow(),
    ))
    session.add(QuoteRequest(
        email_id=log.id, customer_name="Acme", contact_email="billing@acme.test",
        status="bc_created", confidence_scores={"overall": 0.9},
        bc_quote_id="SQ-2", matched_bc_customer_id="ACME", created_at=datetime.utcnow(),
    ))
    session.flush()
    session.add(CustomerOrderApproval(
        email_log_id=log.id, status="needs_choice", match_method="customer_recent",
        candidates=[{"bc_quote_number": "SQ-1", "method": "customer_recent"}],
        from_address="pat@acme.test", subject="Go ahead", excerpt="Go ahead.",
        created_at=datetime.utcnow(),
    ))
    session.commit()
    monkeypatch.setattr(
        "app.services.quote_followup._convert_sq",
        lambda *a, **k: {"bc_order_number": "SO-2", "already": False},
    )
    approval = session.query(CustomerOrderApproval).one()
    result = convert_customer_approval(session, approval.id, bc_quote_number="SQ-2", user_email="joey@opendc.ca")
    assert result["bc_order_number"] == "SO-2"
    assert result["bc_quote_number"] == "SQ-2"


NEW_SHOP_APPROVED = (
    "Approved by the owner, please quote 3 doors 12x14 TX450 for the new shop."
)
NEW_SHOP_GO_AHEAD = (
    "We're ready to go ahead with the new shop. Please quote 2 doors 10x10."
)


def test_a_new_shop_request_is_parsed_not_diverted(session, monkeypatch):
    from app.services.quote_followup import approval_level
    set_inbox_mode(session, "customer_approval_detection", "on")
    session.commit()
    service = EmailMonitorService()
    service.graph_client, _calls = _graph([])
    seen = {}
    _stub_ai(monkeypatch, service, seen, doors=[{"model": "TX450", "width_ft": 12, "height_ft": 14}])
    _categorize(monkeypatch, "quote_request")
    monkeypatch.setattr(service.ai_client, "map_email_to_configurator", lambda *a, **k: {
        "success": False, "error": "stop", "doors": [],
    })
    for index, body in enumerate((NEW_SHOP_APPROVED, NEW_SHOP_GO_AHEAD)):
        seen.clear()
        result = service._process_single_email(
            session,
            _email(
                message_id=f"shop-{index}",
                internet=f"shop-{index}",
                subject="New shop",
                body=body,
            ),
            "joey@opendc.ca",
        )
        assert result == "quote_request"
        assert "body" in seen
        assert approval_level("quote_request", "New shop", body) == "none"
        assert approval_level("order_confirmation", "New shop", body) == "none"
    assert session.query(CustomerOrderApproval).count() == 0
    reply = (
        "Go ahead. The doors are 12x14.\n\n"
        "On Tue, Joey wrote:\n"
        "Attached is quote SQ-1001.\n"
    )
    assert approval_level("order_confirmation", "Re: warehouse quote", reply) == "high"


def test_purchase_order_header_in_an_attachment_keeps_the_colour():
    from app.services.customer_profile_service import analyse_email, quote_email_text
    door = {
        "doorType": "commercial", "doorSeries": "TX450", "doorWidth": 120, "doorHeight": 96,
        "panelColor": "WHITE", "panelDesign": "FLUSH", "trackMount": "bracket",
        "trackThickness": "2", "doorCount": 1, "hardware": {"tracks": True},
    }
    attachment = (
        "PURCHASE ORDER\nFrom: Buyer <buyer@acme.test>\nTo: Open Distribution\n"
        "Date: Nov 10, 2026\nItem: 12x14 TX450 BLACK\n"
    )
    text = quote_email_text(
        "Re: warehouse quote",
        "See the attached order.\n\nOn Tue, Pat wrote:\n> grey",
        [{"extracted_text": attachment}],
    )
    assert "BLACK" in text
    assert "grey" not in text.lower()
    reading = analyse_email(text)
    assert reading["panelColor"]["value"] == "BLACK"
    assert reading["panelColor"]["basis"] == "explicit"
    applied = apply_customer_profile([dict(door)], email_text=text)
    assert applied["doors"][0]["panelColor"] == "BLACK"


def test_no_changes_is_approval_and_update_me_is_not_a_change():
    from app.services.quote_followup import approval_level
    assert approval_level(
        "order_confirmation", "Re: quote", "Approved, no changes. PO 4501 attached.",
    ) == "high"
    assert approval_level(
        "order_confirmation", "Re: quote", "Approved SQ-1001. Please update me on lead time.",
    ) == "high"
    assert approval_level("order_confirmation", "Re:", "This hasn't been approved") == "none"
    assert approval_level("order_confirmation", "Re:", "Has SQ-1001 been approved?") == "none"
    assert approval_level("order_confirmation", "Re:", "Once SQ-1001 is approved by the GC we can order") == "none"
    assert approval_level("quote_modification", "Re:", "Please go ahead with the colour change") == "none"
    assert approval_level("order_confirmation", "Re:", "We can't go ahead with SQ-1001 at this price") == "none"
    assert approval_level("order_confirmation", "Re:", "Don't go ahead yet") == "none"
    assert approval_level(
        "quote_modification", "Re: quote", "Go ahead with SQ-1001 but make it black",
    ) == "low"


def test_gmail_on_wrote_can_wrap_onto_the_next_line():
    from app.services.customer_profile_service import quote_email_text
    from app.services.email_text import fresh_message_text
    body = (
        "Approved SQ-1001. The door is black.\n"
        "\n"
        "On Tue, Nov 10, 2026 at 9:00 AM Pat Buyer <pat@acme.test>\n"
        "wrote:\n"
        "Please quote this grey.\n"
    )
    fresh = fresh_message_text(body)
    assert "black" in fresh.lower()
    assert "grey" not in fresh.lower()
    text = quote_email_text("Re: warehouse quote", body, [])
    assert "grey" not in text.lower()
    assert "black" in text.lower()


def test_a_colleagues_approval_replaces_the_open_vague_row(session, monkeypatch):
    set_inbox_mode(session, "customer_approval_detection", "on")
    log = EmailLog(message_id="vague-colleague", from_address="orders@acme.test", subject="q", body="q", status="parsed")
    session.add(log)
    session.flush()
    session.add(QuoteRequest(
        email_id=log.id, customer_name="Acme", contact_email="orders@acme.test",
        status="bc_created", confidence_scores={"overall": 0.9},
        bc_quote_id="SQ-1077", matched_bc_customer_id="ACME", created_at=datetime.utcnow(),
    ))
    session.add(CustomerOrderApproval(
        email_log_id=log.id, status="needs_choice", match_method="customer_recent",
        bc_quote_number=None,
        candidates=[{"bc_quote_number": "SQ-1070", "method": "customer_recent", "quote_request_id": None}],
        from_address="orders@acme.test", subject="Go ahead", excerpt="Go ahead.",
        created_at=datetime.utcnow(),
    ))
    session.commit()
    service = EmailMonitorService()
    service.graph_client = _graph([])[0]
    _categorize(monkeypatch, "order_confirmation")
    service._process_single_email(
        session,
        _email(
            sender="pat@acme.test",
            subject="Approved",
            body="Approved SQ-1077. PO 44521.",
            message_id="pat-specific",
            internet="pat-specific",
        ),
        "joey@opendc.ca",
    )
    rows = session.query(CustomerOrderApproval).all()
    assert len(rows) == 1
    assert rows[0].status == "ready"
    assert rows[0].bc_quote_number == "SQ-1077"
    assert rows[0].customer_po == "44521"
    assert rows[0].from_address == "pat@acme.test"


def test_shadow_failure_rolls_back_its_own_row(session, monkeypatch):
    set_inbox_mode(session, "customer_approval_detection", "shadow")
    session.commit()
    service = EmailMonitorService()
    service.graph_client, _calls = _graph([])
    seen = {}
    _stub_ai(monkeypatch, service, seen, doors=[{"model": "TX450", "width_ft": 8, "height_ft": 8}])
    _categorize(monkeypatch, "quote_request")
    monkeypatch.setattr(service.ai_client, "map_email_to_configurator", lambda *a, **k: {
        "success": False, "error": "stop", "doors": [],
    })

    def _boom(db, email_log, **kwargs):
        db.add(CustomerOrderApproval(
            email_log_id=email_log.id, status="ready", match_method="number",
            bc_quote_number="SQ-1001", from_address="buyer@acme.test",
            subject="Approved", excerpt="Approved SQ-1001", created_at=datetime.utcnow(),
        ))
        db.flush()
        raise RuntimeError("shadow blew up")

    monkeypatch.setattr("app.services.quote_followup.handle_customer_approval", _boom)
    result = service._process_single_email(
        session,
        _email(subject="Approved", body="Approved SQ-1001"),
        "joey@opendc.ca",
    )
    assert result == "quote_request"
    assert "body" in seen
    assert session.query(CustomerOrderApproval).count() == 0
    assert session.query(EmailLog).count() == 1


def test_attachment_cap_is_opt_in_and_one_failure_skips_that_file():
    from app.integrations.email.client import GraphEmailClient
    from app.services.attachment_text import MAX_FILE_BYTES
    calls = []

    class Fake(GraphEmailClient):
        def __init__(self):
            pass

        def _make_request(self, method, endpoint, **kwargs):
            calls.append((endpoint, kwargs.get("params")))
            if kwargs.get("params") is None and endpoint.endswith("/attachments"):
                return {"value": [
                    {"id": "big", "name": "invoice.pdf", "size": 9_000_000, "contentBytes": "QQ=="},
                    {"id": "ok", "name": "a.pdf", "size": 10, "contentBytes": "YQ=="},
                ]}
            if endpoint.endswith("/attachments") and "/attachments/" not in endpoint:
                return {"value": [
                    {"id": "big", "name": "big.pdf", "size": 9_000_000},
                    {"id": "bad", "name": "bad.pdf", "size": 100},
                    {"id": "small", "name": "a.pdf", "size": 120},
                ]}
            if endpoint.endswith("/attachments/bad"):
                raise RuntimeError("graph 500")
            if endpoint.endswith("/attachments/small"):
                return {"id": "small", "name": "a.pdf", "size": 120, "contentBytes": "YQ=="}
            raise AssertionError(endpoint)

    client = Fake()
    plain = client.get_message_attachments("ap@opendc.ca", "invoice")
    assert [item["name"] for item in plain] == ["invoice.pdf", "a.pdf"]
    assert plain[0]["contentBytes"] == "QQ=="
    assert calls == [("users/ap@opendc.ca/messages/invoice/attachments", None)]
    capped = client.get_message_attachments("joey@opendc.ca", "msg", cap_bytes=MAX_FILE_BYTES)
    assert capped[0]["skipped"] == "too_large"
    assert capped[0].get("contentBytes") is None
    assert capped[1]["skipped"] == "fetch_failed"
    assert capped[2]["contentBytes"] == "YQ=="
    assert not any(endpoint.endswith("/attachments/big") for endpoint, _params in calls)


def test_graph_skips_download_when_the_attachment_is_over_8_mb():
    from app.integrations.email.client import GraphEmailClient
    calls = []

    class Fake(GraphEmailClient):
        def __init__(self):
            pass

        def _make_request(self, method, endpoint, **kwargs):
            calls.append((endpoint, kwargs.get("params"), kwargs.get("headers")))
            if endpoint.endswith("/attachments") and "/attachments/" not in endpoint:
                return {"value": [
                    {"id": "big", "name": "big.pdf", "size": 9_000_000, "contentType": "application/pdf"},
                    {"id": "small", "name": "a.pdf", "size": 120, "contentType": "application/pdf"},
                ]}
            if endpoint.endswith("/attachments/small"):
                return {"id": "small", "name": "a.pdf", "size": 120, "contentBytes": "YQ=="}
            if "mailFolders/inbox/messages" in endpoint:
                return {"value": []}
            raise AssertionError(endpoint)

    from app.services.attachment_text import MAX_FILE_BYTES
    items = Fake().get_message_attachments("joey@opendc.ca", "msg", cap_bytes=MAX_FILE_BYTES)
    assert items[0]["skipped"] == "too_large"
    assert items[0].get("contentBytes") is None
    assert items[1]["contentBytes"] == "YQ=="
    assert not any("/attachments/big" in endpoint for endpoint, _params, _headers in calls)
    Fake().get_inbox_emails("joey@opendc.ca")
    prefer = [
        headers for endpoint, _params, headers in calls
        if endpoint and "mailFolders/inbox/messages" in endpoint
    ]
    assert prefer and prefer[0].get("Prefer") == 'outlook.body-content-type="text"'


def test_shadow_failure_still_parses_the_quote(session, monkeypatch):
    set_inbox_mode(session, "customer_approval_detection", "shadow")
    session.commit()
    service = EmailMonitorService()
    service.graph_client, _calls = _graph([])
    seen = {}
    _stub_ai(monkeypatch, service, seen, doors=[{"model": "TX450", "width_ft": 8, "height_ft": 8}])
    _categorize(monkeypatch, "quote_request")
    monkeypatch.setattr(service.ai_client, "map_email_to_configurator", lambda *a, **k: {
        "success": False, "error": "stop", "doors": [],
    })

    def _boom(*args, **kwargs):
        raise RuntimeError("shadow blew up")

    monkeypatch.setattr("app.services.quote_followup.handle_customer_approval", _boom)
    result = service._process_single_email(
        session,
        _email(subject="Approved", body="Approved SQ-1001"),
        "joey@opendc.ca",
    )
    assert result == "quote_request"
    assert "body" in seen


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


def test_shadow_column_migration_upgrades_and_downgrades(tmp_path):
    import importlib.util
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import text
    engine = create_engine(f"sqlite:///{tmp_path}/shadow.db")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE email_logs (id INTEGER PRIMARY KEY)"))
    path = Path(__file__).resolve().parents[1] / "alembic" / "versions" / "c0d1e2f3a4b6_email_inbox_shadow.py"
    spec = importlib.util.spec_from_file_location("shadow_revision", path)
    revision = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(revision)
    with engine.begin() as connection:
        ctx = MigrationContext.configure(connection)
        with Operations.context(ctx):
            revision.upgrade()
    columns = {column["name"] for column in inspect(engine).get_columns("email_logs")}
    assert "inbox_shadow" in columns
    with engine.begin() as connection:
        ctx = MigrationContext.configure(connection)
        with Operations.context(ctx):
            revision.downgrade()
    columns = {column["name"] for column in inspect(engine).get_columns("email_logs")}
    assert "inbox_shadow" not in columns
