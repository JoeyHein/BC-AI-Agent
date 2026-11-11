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
    "OP19-02137-00": 70.09,
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
    "OP19-02137-00": 1,
    "OP19-02004-00": 1,
    "WRAP": 112,
}

PRICE_FLAGS = (
    "quote_window_patterns",
    "quote_opener_mapping",
    "quote_crating_history",
    "quote_kanata_series_history",
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
    assert "OP19-02137-00" in (door.operatorAccessories or [])
    assert "OP19-02077-00" not in (door.operatorAccessories or [])
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
    # Keyless entry is L979S at the confirmed BC unit price 70.09, not 878MAX at 91.27.
    # 4104.77 - 91.27 + 70.09 = 4083.59. Freight is 9% of that subtotal.
    assert subtotal == 4083.59
    freight = round(subtotal * 0.09, 2)
    assert freight == 367.52
    assert round(subtotal + freight, 2) == 4451.11
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


def test_8500w_is_discontinued_and_l979s_is_the_keyless_default():
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
    assert "OP19-02137-00" in (on.doors[0].get("operatorAccessories") or [])
    reasons = " ".join(item.get("reason", "") for item in on.unresolved)
    assert "discontinued" in reasons.lower()
    assert "8500W" in reasons
    named = plan_round3(
        [{"doorType": "residential", "doorWidth": 96, "doorHeight": 84}],
        email_text="Keyless entry, and also an 878MAX.",
        modes={"quote_opener_mapping": "on"},
    )
    accessories = named.doors[0].get("operatorAccessories") or []
    assert accessories == ["OP19-02077-00"]
    generic = plan_round3(
        [{"doorType": "residential", "doorWidth": 96, "doorHeight": 84}],
        email_text="Please add a wireless keypad. Model LM L979S.",
        modes={"quote_opener_mapping": "on"},
    )
    assert generic.doors[0].get("operatorAccessories") == ["OP19-02137-00"]
    plain = plan_round3(
        [{"doorType": "residential", "doorWidth": 96, "doorHeight": 84}],
        email_text="Keyless entry please.",
        modes={"quote_opener_mapping": "on"},
    )
    assert plain.doors[0].get("operatorAccessories") == ["OP19-02137-00"]


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


def test_adjustable_prep_adds_one_operator_bracket_per_door():
    from app.services.quote_round3 import plan_round3
    shadow = plan_round3(
        [{"doorWidth": 96, "doorHeight": 84}],
        email_text="Adjustable opener prep.",
        modes={"quote_adjustable_prep": "shadow"},
    )
    assert shadow.doors[0].get("adjustablePrep") is not True
    assert shadow.shadow_notes
    planned = plan_round3(
        [{"doorWidth": 96, "doorHeight": 84, "notes": ""}],
        email_text="Adjustable prep please.",
        modes={"quote_adjustable_prep": "on"},
    )
    assert planned.doors[0]["adjustablePrep"] is True
    base = {
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
    }
    parts = get_parts_for_door_config(base)
    brackets = [item for item in parts["parts_list"] if item["part_number"] == "FH12-00179-02"]
    assert len(brackets) == 1
    assert brackets[0]["quantity"] == 1
    two = get_parts_for_door_config({**base, "doorCount": 2})
    again = [item for item in two["parts_list"] if item["part_number"] == "FH12-00179-02"]
    assert len(again) == 1 and again[0]["quantity"] == 2
    already = get_parts_for_door_config({
        **base,
        "operator": "OP19-01118-00",
        "operatorAccessories": ["FH12-00179-02"],
    })
    found = [item for item in already["parts_list"] if item["part_number"] == "FH12-00179-02"]
    assert len(found) == 1
    assert found[0]["quantity"] == 1


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
    # The referenced quote could not be found, so the size is treated as new.
    assert contains_new_quote_ask("Re:", "Ship the 10x10 as quoted.") is True
    assert contains_new_quote_ask("Re:", "The opening is 8'4 x 7.") is False


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


@pytest.mark.parametrize("mode", ["off", "shadow"])
def test_explicit_12_on_3_inch_is_held_in_every_mode(session, monkeypatch, mode):
    """Panorama on 3 inch track asking for 12 inch radius is held, and no quote is built."""
    from app.integrations.ai.client import ClaudeAIClient
    from app.services.customer_profile_service import set_quoting_mode
    if mode != "off":
        set_quoting_mode(session, mode)
        session.commit()
    service = _service(monkeypatch)
    body = "Please quote one 10x8 Panorama with 12 inch radius."
    log = EmailLog(
        message_id=f"radius-{mode}",
        from_address="buyer@acme.test",
        subject="Panorama",
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
            "customer": {"company_name": "Acme", "email": "buyer@acme.test", "confidence": 0.9},
            "doors": [{"model": "PANORAMA", "width_ft": 10, "height_ft": 8, "track_radius": "12"}],
            "project": {},
        },
    })

    def _map(parsed, subject, email_body):
        raw = [{
            "doorType": "aluminium",
            "doorSeries": "PANORAMA",
            "doorWidth": 120,
            "doorHeight": 96,
            "panelColor": "WHITE",
            "panelDesign": "FLUSH",
            "trackThickness": "3",
            "trackRadius": "12",
        }]
        return {
            "success": True,
            "request_kind": "door_quote",
            "confidence": 0.9,
            "doors": ClaudeAIClient._normalize_configurator_doors(raw),
        }

    monkeypatch.setattr(service.ai_client, "map_email_to_configurator", _map)

    def _build(*args, **kwargs):
        raise AssertionError("Business Central quote was built")

    import app.api.door_configurator as dc
    monkeypatch.setattr(dc, "build_bc_quote_from_doors", _build)
    service._parse_quote_request(session, log, "Panorama", body, "Buyer", "buyer@acme.test")
    quote = session.query(QuoteRequest).one()
    assert quote.status == "held_for_standard_deviation"
    assert quote.bc_quote_id is None
    assert any(item.get("kind") == "track_radius_not_available" for item in (quote.deviations or []))
    stored = quote.parsed_data["configurator_mapping"]["doors"][0]
    assert stored["trackRadius"] == "15"
    assert stored["trackThickness"] == "3"
    assert not stored.get("requestedTrackRadius")


def test_email_radius_does_not_hold_a_silent_3_inch_door_beside_a_2_inch_door():
    """A 12 on the 2 inch door is not an ask for the 3 inch door next to it."""
    from app.services.track_defaults import unavailable_3_inch_radius
    mapped = [
        {"trackThickness": "2", "trackRadius": "12"},
        {"trackThickness": "3", "trackRadius": "15"},
    ]
    parsed = [{"track_radius": "12"}, {}]
    email = 'The first door is 2" track with 12" radius. The second is 3" track.'
    assert unavailable_3_inch_radius(mapped, parsed, email) == []
    # The same sentence does hold when that is the only door, or every door is 3".
    only = unavailable_3_inch_radius(
        [{"trackThickness": "3"}], [], 'Please quote 12" radius.',
    )
    assert [item["door_index"] for item in only] == [1]
    both = unavailable_3_inch_radius(
        [{"trackThickness": "3"}, {"trackThickness": "3"}],
        [{}, {}],
        'Both doors, 12" radius.',
    )
    assert [item["door_index"] for item in both] == [1, 2]
    # A parsed ask on the 3 inch door still holds that door alone.
    own = unavailable_3_inch_radius(
        mapped,
        [{"track_radius": "12"}, {"track_radius": "12"}],
        email,
    )
    assert [item["door_index"] for item in own] == [2]


def test_mapper_radius_alone_does_not_hold_a_3_inch_door(session, monkeypatch):
    """The mapper filling 12 is not a customer request. Quote 15 and do not hold."""
    from app.integrations.ai.client import ClaudeAIClient
    service = _service(monkeypatch)
    body = "Please quote one 10x8 Panorama."
    log = EmailLog(
        message_id="mapper-12",
        from_address="buyer@acme.test",
        subject="Panorama",
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
            "customer": {"company_name": "Acme", "email": "buyer@acme.test", "confidence": 0.9},
            "doors": [{"model": "PANORAMA", "width_ft": 10, "height_ft": 8}],
            "project": {},
        },
    })

    def _map(parsed, subject, email_body):
        raw = [{
            "doorType": "aluminium",
            "doorSeries": "PANORAMA",
            "doorWidth": 120,
            "doorHeight": 96,
            "panelColor": "WHITE",
            "panelDesign": "FLUSH",
            "trackThickness": "3",
            "trackRadius": "12",
            "doorCount": 1,
            "hardware": {"tracks": True},
        }]
        return {
            "success": True,
            "request_kind": "door_quote",
            "confidence": 0.9,
            "doors": ClaudeAIClient._normalize_configurator_doors(raw),
        }

    monkeypatch.setattr(service.ai_client, "map_email_to_configurator", _map)
    seen = {}

    def _build(request, db, source="email", **kwargs):
        seen["radius"] = request.doors[0].trackRadius
        return {"success": False, "data": {}}

    import app.api.door_configurator as dc
    monkeypatch.setattr(dc, "build_bc_quote_from_doors", _build)
    service._parse_quote_request(session, log, "Panorama", body, "Buyer", "buyer@acme.test")
    quote = session.query(QuoteRequest).one()
    assert quote.status != "held_for_standard_deviation"
    assert not any(
        item.get("kind") == "track_radius_not_available" for item in (quote.deviations or [])
    )
    assert seen["radius"] == "15"


def test_radius_check_failure_does_not_hold(session, monkeypatch):
    service = _service(monkeypatch)
    body = "Please quote one 10x8 Panorama with 12 inch radius."
    log = EmailLog(
        message_id="radius-boom",
        from_address="buyer@acme.test",
        subject="Panorama",
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
            "customer": {"company_name": "Acme", "email": "buyer@acme.test", "confidence": 0.9},
            "doors": [{"model": "PANORAMA", "width_ft": 10, "height_ft": 8, "track_radius": "12"}],
            "project": {},
        },
    })
    monkeypatch.setattr(service.ai_client, "map_email_to_configurator", lambda *a, **k: {
        "success": True,
        "request_kind": "door_quote",
        "confidence": 0.9,
        "doors": [{
            "doorType": "aluminium",
            "doorSeries": "PANORAMA",
            "doorWidth": 120,
            "doorHeight": 96,
            "panelColor": "WHITE",
            "panelDesign": "FLUSH",
            "trackThickness": "3",
            "trackRadius": "15",
            "doorCount": 1,
            "hardware": {"tracks": True},
        }],
    })

    def _explode(*args, **kwargs):
        raise RuntimeError("radius check failed")

    monkeypatch.setattr("app.services.track_defaults.unavailable_3_inch_radius", _explode)
    seen = {}

    def _build(request, db, source="email", **kwargs):
        seen["built"] = True
        return {"success": False, "data": {}}

    import app.api.door_configurator as dc
    monkeypatch.setattr(dc, "build_bc_quote_from_doors", _build)
    service._parse_quote_request(session, log, "Panorama", body, "Buyer", "buyer@acme.test")
    quote = session.query(QuoteRequest).one()
    assert seen.get("built") is True
    assert quote.status != "held_for_standard_deviation"


def test_20_inch_radius_is_kept_only_for_craft():
    from app.services.track_defaults import quoted_track_radius
    assert quoted_track_radius("2", "20", series="CRAFT") == "20"
    assert quoted_track_radius("2", "20", series="TX450") == "15"
    assert quoted_track_radius("2", "12", series="TX450") == "12"
    parts = get_parts_for_door_config({
        "doorType": "commercial",
        "doorSeries": "TX450",
        "doorWidth": 120,
        "doorHeight": 120,
        "panelColor": "WHITE",
        "panelDesign": "UDC",
        "hasWindows": False,
        "trackThickness": "2",
        "trackRadius": "20",
        "trackMount": "bracket",
        "liftType": "standard",
        "hardware": {"tracks": True, "springs": False, "struts": False, "hardwareKits": False,
                     "weatherStripping": False, "bottomRetainer": False, "shafts": False},
    })
    numbers = [item["part_number"] for item in parts["parts_list"]]
    assert "TR02-STDBM-1020" not in numbers
    assert any(number.endswith("15") and number.startswith("TR02") for number in numbers)


def test_empty_2_inch_radius_in_part_selection_stays_12():
    """get_parts_for_door_config with a blank radius on 2 inch track stays on main's 12."""
    blank = get_parts_for_door_config({
        "doorType": "residential",
        "doorSeries": "KANATA",
        "doorWidth": 96,
        "doorHeight": 84,
        "panelColor": "WHITE",
        "panelDesign": "SHXL",
        "hasWindows": False,
        "trackThickness": "2",
        "trackRadius": "",
        "trackMount": "bracket",
        "hardware": {"tracks": True, "springs": False, "struts": False, "hardwareKits": False,
                     "weatherStripping": False, "bottomRetainer": False, "shafts": False},
    })
    tracks = [item["part_number"] for item in blank["parts_list"] if str(item["part_number"]).startswith("TR02")]
    assert tracks
    assert all(number.endswith("12") for number in tracks)
    missing = get_parts_for_door_config({
        "doorType": "residential",
        "doorSeries": "KANATA",
        "doorWidth": 96,
        "doorHeight": 84,
        "panelColor": "WHITE",
        "panelDesign": "SHXL",
        "hasWindows": False,
        "trackThickness": "2",
        "trackRadius": None,
        "trackMount": "bracket",
        "hardware": {"tracks": True, "springs": False, "struts": False, "hardwareKits": False,
                     "weatherStripping": False, "bottomRetainer": False, "shafts": False},
    })
    tracks = [item["part_number"] for item in missing["parts_list"] if str(item["part_number"]).startswith("TR02")]
    assert all(number.endswith("12") for number in tracks)


def test_legacy_quote_service_keeps_explicit_12_on_2_inch_track(monkeypatch):
    """Intentional: QuoteGenerationService now honours an explicit 12 on 2 inch track.

    The part list for an 8x7 Kanata is the 12 inch track and 30 inch springs.
    """
    from app.services.quote_service import QuoteGenerationService
    service = QuoteGenerationService(None)
    monkeypatch.setattr(service, "_get_part_price", lambda *args, **kwargs: 1)
    monkeypatch.setattr(service, "_apply_pricing_rules", lambda price, *args, **kwargs: price)
    spec = {"width_ft": 8, "height_ft": 7, "model": "KANATA", "track_type": "2", "track_radius": "12"}
    items = service._generate_door_items(spec, None)
    tracks = [item for item in items if str(item["product_code"]).startswith("TR02")]
    springs = [item for item in items if str(item["product_code"]).startswith("SP11")]
    assert tracks and all(item["product_code"].endswith("12") for item in tracks)
    assert springs
    assert all(item["quantity"] == 30 for item in springs)


def test_rail_dedupe_is_off_until_opener_mapping_is_on():
    door = {
        "doorType": "residential",
        "doorSeries": "KANATA",
        "doorWidth": 96,
        "doorHeight": 84,
        "panelColor": "WHITE",
        "panelDesign": "SHXL",
        "hasWindows": False,
        "trackThickness": "2",
        "trackRadius": "15",
        "operator": "OP19-01118-00",
        "operatorAccessories": ["OP19-02005-00"],
        "hardware": {"tracks": False, "springs": False, "struts": False, "hardwareKits": False,
                     "weatherStripping": False, "bottomRetainer": False, "shafts": False},
    }
    off = get_parts_for_door_config(dict(door))
    off_numbers = [item["part_number"] for item in off["parts_list"]]
    assert "OP19-02005-00" in off_numbers
    assert "OP19-02004-00" in off_numbers
    on = get_parts_for_door_config({**door, "dedupeOperatorRails": True})
    on_numbers = [item["part_number"] for item in on["parts_list"]]
    assert "OP19-02005-00" in on_numbers
    assert "OP19-02004-00" not in on_numbers


def test_crating_is_one_charge_for_the_order():
    parts = get_parts_for_door_config({
        "doorType": "residential",
        "doorSeries": "KANATA",
        "doorWidth": 96,
        "doorHeight": 84,
        "doorCount": 3,
        "panelColor": "WHITE",
        "panelDesign": "SHXL",
        "hasWindows": False,
        "includeCrating": True,
        "hardware": {"tracks": False, "springs": False, "struts": False, "hardwareKits": False,
                     "weatherStripping": False, "bottomRetainer": False, "shafts": False},
    })
    crating = [item for item in parts["parts_list"] if item["part_number"] == "CRATING"]
    assert len(crating) == 1
    assert crating[0]["quantity"] == 1


def test_partial_phrases_for_leaving_the_opener_off():
    from app.services.quote_followup import approval_level, is_customer_approval
    phrases = (
        "SQ-1234 approved. We don't need the opener.",
        "approved, leave off the opener.",
        "Approved SQ-1234. Leave out the opener.",
        "SQ-1234 approved. Remove the opener.",
        "Approved. Drop the opener.",
    )
    for phrase in phrases:
        assert approval_level("order_confirmation", "Re: quote", phrase) == "partial", phrase
        assert is_customer_approval("order_confirmation", "Re: quote", phrase) is False


def test_partial_approval_failure_rolls_back_the_session(session, monkeypatch):
    set_inbox_mode(session, "customer_approval_detection", "on")
    session.commit()
    service = _service(monkeypatch)
    _graph(service)
    _categorize(monkeypatch, "order_confirmation")

    def _boom(db, email_log, **kwargs):
        from app.db.models import CustomerOrderApproval
        db.add(CustomerOrderApproval(
            email_log_id=email_log.id,
            status="partial",
            excerpt="should not stick",
            from_address="buyer@acme.test",
            created_at=datetime.utcnow(),
        ))
        db.flush()
        raise RuntimeError("approval write failed")

    monkeypatch.setattr("app.services.quote_followup.handle_customer_approval", _boom)
    result = service._process_single_email(
        session,
        {
            "id": "g-partial",
            "internetMessageId": "partial-fail",
            "subject": "Re: quote",
            "from": {"emailAddress": {"address": "buyer@acme.test", "name": "Buyer"}},
            "body": {"content": "SQ-1234 approved. We don't need the opener."},
            "receivedDateTime": "2026-11-11T12:00:00Z",
        },
        "joey@opendc.ca",
    )
    assert result != "quote_request"
    assert session.query(CustomerOrderApproval).count() == 0
    assert session.query(EmailLog).count() >= 1


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
