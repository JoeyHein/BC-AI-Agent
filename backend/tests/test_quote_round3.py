"""Round 3: always-on 3 inch radius, approval follow-ups, and DoorTech gaps.

The DoorTech switches default to off. The price check turns them on, except
struts-per-section: the hand-corrected DoorTech quote prices one 16 foot strut.
That switch is covered on its own.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.models import (
    AIDecision,
    AppSettings,
    BCCustomer,
    CustomerOrderApproval,
    CustomerProfile,
    EmailLog,
    QuoteItem,
    QuoteRequest,
)
from app.services.email_monitor import EmailMonitorService
from app.services.inbox_settings import set_inbox_mode
from app.services.part_number_service import get_parts_for_door_config


DOORTECH_EMAIL = """\
Qty.1 16'0" x 7'0" TX450-20S or the TX500-20S in black
Windows as shown in photo above
Truss on every section
2" hardware
Standard lift 12" radius
Weather stripping
Qty.1 Liftmaster 3/4 horse power chain drive (base)
Adjustable prep
Keyless entry
"""

DOORTECH_FOLLOWUP = "If you can quote as black flush or something similar. If flush isn't available whatever the closest is."

EXTRACTED_DOOR = {
    "model": "TX450-20S",
    "width_ft": 16,
    "height_ft": 7,
    "color": "BLACK",
    "design": "FLUSH",
    "window_pattern": "3/2/1/0",
    "window_size": "long",
    "operator": "LiftMaster 3/4 horse power chain drive (base)",
    "keypad": "878MAX",
    "notes": "Truss on every section. Adjustable prep. Keyless entry. Weather stripping.",
}

MAPPED_DOOR = {
    "doorType": "commercial",
    "doorSeries": "TX450",
    "doorWidth": 192,
    "doorHeight": 84,
    "doorCount": 1,
    "panelColor": "BLACK",
    "panelDesign": "FLUSH",
    "hasWindows": True,
    "windowSize": "long",
    "windowPositions": [],
    "windowQty": 0,
    "trackRadius": "12",
    "trackThickness": "2",
    "trackMount": "bracket",
    "liftType": "standard",
    "hardware": {
        "tracks": True,
        "springs": True,
        "shafts": True,
        "struts": True,
        "hardwareKits": True,
        "weatherStripping": True,
        "bottomRetainer": True,
    },
    "operator": "LiftMaster 3/4 HP chain drive (base)",
    "operatorAccessories": None,
    "notes": "Windows per customer photo. Truss every section. Adjustable prep, keyless entry.",
    "targetCycles": 10000,
}

# SILV / all-customers unit prices from the hand-corrected DoorTech quote.
SILV_PRICES = {
    "PN65-21005-1600": 380.96,
    "PL10-00146-01": 21.90,
    "PL10-00005-01": 0.06,
    "FH17-00003-00": 45.54,
    "GK15-11205-00": 206.45,
    "TR02-STDBM-0712": 158.54,
    "HK10-00704-1316": 129.01,
    "SP11-26220-01": 1.97,
    "SP11-26220-02": 1.97,
    "SP12-00231-00": 12.47,
    "SP12-00237-00": 12.47,
    "SH12-11610-00": 23.99,
    "PL10-07203-05": 22.81,
    "PL10-16203-05": 52.15,
    "OP19-01118-00": 403.51,
    "OP19-02077-00": 91.27,
    "OP19-02004-00": 93.88,
    "WRAP": 0.95,
}

HAND_QTY = {
    "PN65-21005-1600": 4,
    "PL10-00146-01": 1,
    "PL10-00005-01": 192,
    "FH17-00003-00": 1,
    "GK15-11205-00": 6,
    "TR02-STDBM-0712": 1,
    "HK10-00704-1316": 1,
    "SP11-26220-01": 34,
    "SP11-26220-02": 34,
    "SP12-00231-00": 1,
    "SP12-00237-00": 1,
    "SH12-11610-00": 1,
    "PL10-07203-05": 2,
    "PL10-16203-05": 1,
    "OP19-01118-00": 1,
    "OP19-02077-00": 1,
    "OP19-02004-00": 1,
    "WRAP": 112,
}

PRICE_FLAGS = (
    "quote_window_patterns",
    "quote_opener_mapping",
    "quote_crating_history",
    "quote_kanata_series_history",
    "quote_adjustable_prep",
    "quote_series_fallback",
)


class _Memory:
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
def session():
    engine = create_engine(
        "sqlite://",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    for model in (
        EmailLog, BCCustomer, QuoteRequest, AIDecision, QuoteItem,
        AppSettings, CustomerOrderApproval, CustomerProfile,
    ):
        model.__table__.create(engine, checkfirst=True)
    db = sessionmaker(bind=engine, autoflush=False, autocommit=False)()
    try:
        yield db
    finally:
        db.close()


def _service(monkeypatch):
    import app.services.email_monitor as email_monitor_mod
    monkeypatch.setattr(email_monitor_mod, "get_memory_service", lambda db: _Memory())
    return EmailMonitorService()


def _run_doortech(session, monkeypatch, *, flags, message_id="doortech"):
    for key in PRICE_FLAGS:
        set_inbox_mode(session, key, "on" if key in flags else "off")
    set_inbox_mode(session, "quote_struts_per_section", "on" if "quote_struts_per_section" in flags else "off")
    session.commit()
    service = _service(monkeypatch)
    body = f"{DOORTECH_EMAIL}\n{DOORTECH_FOLLOWUP}"
    log = EmailLog(
        message_id=message_id,
        from_address="preston@doortechenterprises.com",
        subject="Quote 16x7 Black with customer windows ?",
        body=body,
        status="new",
    )
    session.add(log)
    session.flush()
    monkeypatch.setattr(service.ai_client, "parse_email_for_quote", lambda *a, **k: {
        "success": True,
        "confidence": 0.95,
        "model": "stub",
        "tokens": {"input": 1, "output": 1},
        "data": {
            "customer": {
                "company_name": "DoorTech Enterprises",
                "email": "preston@doortechenterprises.com",
                "confidence": 0.95,
            },
            "doors": [dict(EXTRACTED_DOOR)],
            "project": {"tag": "Quote 16x7 Black with customer windows"},
        },
    })
    monkeypatch.setattr(service.ai_client, "map_email_to_configurator", lambda *a, **k: {
        "success": True,
        "request_kind": "door_quote",
        "confidence": 0.95,
        "doors": [dict(MAPPED_DOOR)],
    })
    seen = {}

    def _build(request, db, source="email", **kwargs):
        seen["door"] = request.doors[0]
        return {"success": False, "data": {}}

    import app.api.door_configurator as dc
    monkeypatch.setattr(dc, "build_bc_quote_from_doors", _build)
    service._parse_quote_request(
        session, log, log.subject, body, "Preston Griffiths", log.from_address,
    )
    return seen.get("door")


def test_doortech_flags_off_keeps_the_unmapped_door(session, monkeypatch):
    door = _run_doortech(session, monkeypatch, flags=())
    assert door is not None
    assert door.doorSeries == "TX450"
    assert door.panelDesign == "FLUSH"
    assert door.operator == "LiftMaster 3/4 HP chain drive (base)"
    assert not door.windowPositions
    assert door.trackThickness == "2"
    assert door.trackRadius == "12"
    assert door.strutsPerSection is False
    assert door.includeCrating is False


def test_doortech_flags_on_matches_the_hand_corrected_quote(session, monkeypatch):
    door = _run_doortech(session, monkeypatch, flags=PRICE_FLAGS)
    assert door.doorSeries == "KANATA"
    assert door.doorType == "residential"
    assert door.panelColor == "BLACK"
    assert door.panelDesign == "FLUSH"
    assert door.trackThickness == "2"
    assert door.trackRadius == "12"
    assert door.trackMount == "bracket"
    assert door.operator == "OP19-01118-00"
    assert "OP19-02077-00" in (door.operatorAccessories or [])
    assert [(p.section, p.col) for p in door.windowPositions] == [
        (1, 1), (1, 2), (1, 3),
        (2, 2), (2, 3),
        (3, 3),
    ]
    parts = get_parts_for_door_config(door.model_dump())
    priced = {
        item["part_number"]: item
        for item in parts["parts_list"]
        if item.get("part_number")
    }
    missing = [sku for sku in HAND_QTY if sku not in priced]
    extra = sorted(set(priced) - set(HAND_QTY))
    assert missing == [], missing
    assert extra == []
    for sku, qty in HAND_QTY.items():
        assert priced[sku]["quantity"] == qty, sku
    subtotal = round(sum(priced[sku]["quantity"] * SILV_PRICES[sku] for sku in HAND_QTY), 2)
    assert subtotal == 4104.77
    freight = round(subtotal * 0.09, 2)
    assert freight == 369.43
    assert round(subtotal + freight, 2) == 4474.20
    assert "CRATING" not in priced


def test_struts_per_section_is_off_until_the_switch_is_on(session, monkeypatch):
    off = _run_doortech(session, monkeypatch, flags=PRICE_FLAGS, message_id="strut-off")
    assert off.strutsPerSection is False
    on = _run_doortech(
        session, monkeypatch,
        flags=PRICE_FLAGS + ("quote_struts_per_section",),
        message_id="strut-on",
    )
    assert on.strutsPerSection is True
    parts = get_parts_for_door_config(on.model_dump())
    strut = next(item for item in parts["parts_list"] if item["part_number"] == "FH17-00003-00")
    assert strut["quantity"] == 4


def test_opener_flag_off_leaves_free_text_and_on_refuses_an_unknown_model():
    from app.services.quote_round3 import plan_round3
    door = {"doorType": "residential", "operator": "LiftMaster 8500W", "doorWidth": 96, "doorHeight": 84}
    off = plan_round3([door], email_text="LiftMaster 8500W jackshaft", modes={})
    assert off.doors[0]["operator"] == "LiftMaster 8500W"
    on = plan_round3(
        [dict(door)],
        email_text="Please quote a LiftMaster 8500W jackshaft and an L979S keypad.",
        modes={"quote_opener_mapping": "on"},
    )
    assert on.doors[0]["operator"] is None
    reasons = " ".join(item.get("reason", "") for item in on.unresolved)
    assert "8500W" in reasons
    assert "L979S" in reasons
    assert "OP19-" not in reasons


def test_window_pattern_flag_is_shadow_only_until_on():
    from app.services.quote_round3 import plan_round3
    door = {"doorWidth": 192, "doorHeight": 84, "windowPositions": []}
    shadow = plan_round3(
        [door],
        email_text="3 windows in the top section, 2 windows in section 2, 1 window in section 3",
        modes={"quote_window_patterns": "shadow"},
    )
    assert shadow.doors[0]["windowPositions"] == []
    assert shadow.shadow_notes
    on = plan_round3(
        [dict(door)],
        email_text="staggered windows 3/2/1/0",
        modes={"quote_window_patterns": "on"},
    )
    assert len(on.doors[0]["windowPositions"]) == 6


def test_kanata_pn65_is_counted_only_when_the_switch_is_on(session):
    from app.services.customer_profile_service import parse_history_line, seed_profiles_from_documents
    line = {"number": "PN65-21005-1600", "description": "SECTION, KANATA, FLUSH, BLACK", "lineType": "Item"}
    assert "door_series" not in parse_history_line(line)
    assert parse_history_line(line, count_kanata=True)["door_series"] == "KANATA"
    session.add(BCCustomer(bc_customer_id="DTE", company_name="DoorTech", email="preston@doortechenterprises.com"))
    session.commit()
    docs = [{
        "customer_id": "DTE",
        "lines": [
            line,
            {"number": "PN45-21000-1600", "description": "SECTION, TX450", "lineType": "Item"},
            line,
        ],
    }]
    seed_profiles_from_documents(session, docs)
    session.commit()
    fields = session.query(CustomerProfile).filter_by(bc_customer_id="DTE").one().fields
    assert fields["door_series"]["value"] == "TX450"
    set_inbox_mode(session, "quote_kanata_series_history", "on")
    session.commit()
    seed_profiles_from_documents(session, docs)
    session.commit()
    fields = session.query(CustomerProfile).filter_by(bc_customer_id="DTE").one().fields
    assert fields["door_series"]["value"] == "KANATA"


def test_crating_comes_from_history_only_when_the_switch_is_on():
    from app.services.quote_round3 import plan_round3
    door = {"doorWidth": 192, "doorHeight": 84}
    history = {"crating": {"value": "yes", "locked": False, "confidence": 1, "support": 3, "total": 3}}
    off = plan_round3([door], email_text="Please quote a door.", profile_fields=history, modes={})
    assert "includeCrating" not in off.doors[0]
    on = plan_round3(
        [dict(door)],
        email_text="Please quote a door.",
        profile_fields=history,
        modes={"quote_crating_history": "on"},
    )
    assert on.doors[0]["includeCrating"] is True
    pickup = plan_round3(
        [dict(door)],
        email_text="We will pick up.",
        modes={"quote_crating_history": "on"},
    )
    assert pickup.delivery_type == "pickup"


def test_adjustable_prep_does_not_invent_a_part():
    from app.services.quote_round3 import plan_round3
    planned = plan_round3(
        [{"doorWidth": 96, "doorHeight": 84, "notes": ""}],
        email_text="Adjustable prep please.",
        modes={"quote_adjustable_prep": "on"},
    )
    door = planned.doors[0]
    assert door["adjustablePrep"] is True
    parts = get_parts_for_door_config({
        "doorType": "residential",
        "doorSeries": "KANATA",
        "doorWidth": 96,
        "doorHeight": 84,
        "panelColor": "WHITE",
        "panelDesign": "FLUSH",
        "hasWindows": False,
        "hardware": {"struts": False, "tracks": False, "springs": False, "shafts": False,
                     "hardwareKits": False, "weatherStripping": False, "bottomRetainer": False},
        "adjustablePrep": True,
    })
    assert all(item.get("part_number") != "ADJUSTABLE-PREP" for item in parts["parts_list"])
    assert any(item.get("kind") == "unresolved_option" for item in parts["deviations"])


def _categorize(monkeypatch, category):
    class Categorizer:
        def categorize_email(self, *args, **kwargs):
            return {
                "category": category,
                "confidence": 0.9,
                "reasoning": "",
                "is_modification": False,
            }

    monkeypatch.setattr(
        "app.services.email_categorization_service.get_categorization_service",
        lambda db: Categorizer(),
    )


def _graph(service):
    class Graph:
        def get_message_attachments(self, *args, **kwargs):
            return []

    service.graph_client = Graph()


def test_repeated_size_does_not_create_a_second_quote(session, monkeypatch):
    set_inbox_mode(session, "customer_approval_detection", "on")
    session.commit()
    log = EmailLog(
        message_id="sent", from_address="buyer@acme.test", subject="warehouse",
        body="old", status="parsed",
    )
    session.add(log)
    session.flush()
    session.add(QuoteRequest(
        email_id=log.id, customer_name="Acme", contact_email="buyer@acme.test",
        status="bc_created", confidence_scores={"overall": 0.9},
        bc_quote_id="SQ-1001",
        parsed_data={"configurator_mapping": {"doors": [{"doorWidth": 120, "doorHeight": 120}]}},
        created_at=datetime.utcnow(),
    ))
    session.commit()
    service = _service(monkeypatch)
    _graph(service)
    seen = {}
    monkeypatch.setattr(service.ai_client, "parse_email_for_quote", lambda *a, **k: seen.setdefault("parsed", True))
    _categorize(monkeypatch, "order_confirmation")
    result = service._process_single_email(
        session,
        {
            "id": "g1",
            "internetMessageId": "ship-10",
            "subject": "Re: warehouse quote",
            "from": {"emailAddress": {"address": "buyer@acme.test", "name": "Buyer"}},
            "body": {"content": "Approved. Please ship the 10x10 as quoted.\n\nOn Tue, Joey wrote:\nAttached is quote SQ-1001.\n"},
            "receivedDateTime": "2026-11-11T12:00:00Z",
        },
        "joey@opendc.ca",
    )
    assert result == "customer_approval"
    assert "parsed" not in seen
    assert session.query(QuoteRequest).count() == 1
    assert session.query(CustomerOrderApproval).count() == 1


def test_a_new_size_on_an_approval_still_parses(session, monkeypatch):
    from app.services.quote_followup import contains_new_quote_ask
    assert contains_new_quote_ask("Re:", "Ship the 10x10 as quoted.", {(10, 10)}) is False
    assert contains_new_quote_ask("Re:", "Please quote a 12x8 as well.", {(10, 10)}) is True
    assert contains_new_quote_ask("Re:", "Go ahead. The shed is 8x7.", {(10, 10)}) is True
    assert contains_new_quote_ask("Re:", "Ship the 10x10 as quoted.") is False


def test_partial_approval_is_not_high_and_the_confirm_payload_shows_the_exception(session):
    from app.services.quote_followup import approval_level, approval_to_dict, handle_customer_approval, is_customer_approval
    text = "Approved SQ-1001, but no opener."
    assert approval_level("order_confirmation", "Re: quote", text) == "partial"
    assert is_customer_approval("order_confirmation", "Re: quote", text) is False
    set_inbox_mode(session, "customer_approval_detection", "on")
    log = EmailLog(message_id="p", from_address="buyer@acme.test", subject="Re: quote", body=text, status="parsed")
    session.add(log)
    session.flush()
    session.add(QuoteRequest(
        email_id=log.id, customer_name="Acme", contact_email="buyer@acme.test",
        status="bc_created", confidence_scores={"overall": 0.9},
        bc_quote_id="SQ-1001", created_at=datetime.utcnow(),
    ))
    session.commit()
    row = handle_customer_approval(
        session, log, subject="Re: quote", body=text, from_address="buyer@acme.test",
        confidence="partial", exception_text="Approved SQ-1001, but no opener.",
    )
    payload = approval_to_dict(row)
    assert payload["status"] == "partial"
    assert payload["confidence"] == "partial"
    assert "no opener" in (payload["exception_text"] or "")


def test_shadow_approval_does_not_send_a_sized_go_ahead_to_the_parser(session, monkeypatch):
    set_inbox_mode(session, "customer_approval_detection", "shadow")
    session.commit()
    service = _service(monkeypatch)
    _graph(service)
    seen = {}
    monkeypatch.setattr(service.ai_client, "parse_email_for_quote", lambda *a, **k: seen.setdefault("parsed", True))
    _categorize(monkeypatch, "order_confirmation")
    result = service._process_single_email(
        session,
        {
            "id": "g2",
            "internetMessageId": "shadow-size",
            "subject": "Re: warehouse",
            "from": {"emailAddress": {"address": "buyer@acme.test", "name": "Buyer"}},
            "body": {"content": "Go ahead and ship the 10x10.\n\nOn Tue, Joey wrote:\nAttached is quote SQ-1001.\n"},
            "receivedDateTime": "2026-11-11T12:00:00Z",
        },
        "joey@opendc.ca",
    )
    assert result != "quote_request"
    assert "parsed" not in seen
    assert session.query(CustomerOrderApproval).count() == 0


def test_bc_customer_ids_queries_only_the_matching_addresses(session):
    from app.services.quote_followup import _bc_customer_ids
    log = EmailLog(message_id="a", from_address="a@acme.test", subject="s", body="b", status="parsed")
    session.add(log)
    session.flush()
    session.add_all([
        QuoteRequest(
            email_id=log.id, customer_name="Acme", contact_email="buyer@acme.test",
            matched_bc_customer_id="ACME", status="bc_created",
            confidence_scores={"overall": 0.9}, created_at=datetime.utcnow(),
        ),
        QuoteRequest(
            email_id=log.id, customer_name="Other", contact_email="pat@other.test",
            matched_bc_customer_id="OTHER", status="bc_created",
            confidence_scores={"overall": 0.9}, created_at=datetime.utcnow(),
        ),
        QuoteRequest(
            email_id=log.id, customer_name="Sibling", contact_email="orders@acme.test",
            matched_bc_customer_id="ACME-2", status="bc_created",
            confidence_scores={"overall": 0.9}, created_at=datetime.utcnow(),
        ),
    ])
    session.commit()
    found = _bc_customer_ids(session, "buyer@acme.test")
    assert found == {"ACME", "ACME-2"}
    assert "OTHER" not in found
