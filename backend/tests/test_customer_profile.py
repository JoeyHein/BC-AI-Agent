"""Customer profiles, quoting defaults, matching, and quote-number lookup.

The switch defaults to off. These tests turn it on, or to shadow, on the
database they build.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.models import (
    AIDecision,
    AppSettings,
    AuditTrail,
    BCCustomer,
    CustomerProfile,
    EmailLog,
    QuoteItem,
    QuoteRequest,
    SalesOrder,
)
from app.services.customer_profile_service import (
    apply_customer_profile,
    seed_profiles_from_documents,
    set_quoting_mode,
)
from app.services.order_lifecycle_service import OrderLifecycleService
from app.services.part_number_service import DoorConfiguration, part_number_service
import app.services.email_monitor as email_monitor_mod
from app.services.email_monitor import EmailMonitorService

BACKEND = Path(__file__).resolve().parent.parent


def _engine():
    engine = create_engine(
        "sqlite://",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    for model in (
        EmailLog, BCCustomer, CustomerProfile, AppSettings, QuoteRequest,
        AIDecision, QuoteItem, SalesOrder, AuditTrail,
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


def _mode(db, mode):
    set_quoting_mode(db, mode)
    db.commit()


def _gnb_history():
    docs = []
    for index in range(14):
        docs.append({
            "customer_id": "GNB",
            "customer_number": "C-GNB",
            "number": f"INV-AM-{index}",
            "email": "orders@gnb.example",
            "lines": [{
                "number": "TR03-STDAM-14",
                "description": "3 INCH STANDARD ANGLE MOUNT",
                "lineType": "Item",
            }],
        })
    for index in range(2):
        docs.append({
            "customer_id": "GNB",
            "customer_number": "C-GNB",
            "number": f"INV-BM-{index}",
            "email": "orders@gnb.example",
            "lines": [{
                "number": "TR02-STDBM-0815",
                "description": "2 INCH STANDARD BRACKET MOUNT",
                "lineType": "Item",
            }],
        })
    return docs


def test_seed_reads_angle_mount_from_gnb_style_history(session):
    stats = seed_profiles_from_documents(session, _gnb_history())
    session.commit()
    assert stats["customers"] == 1
    profile = session.query(CustomerProfile).one()
    mount = profile.fields["track_mount"]
    assert mount["value"] == "angle"
    assert mount["support"] == 14
    assert mount["total"] == 16
    assert mount["evidence"] == "angle on 14 of 16 orders"
    assert profile.email_domains == ["gnb.example"]
    assert "orders@gnb.example" in {row["email"] for row in profile.contacts}
    # Track with no freight line is a pickup.
    assert profile.fields["delivery_type"]["value"] == "pickup"
    assert profile.fields["track_size"]["value"] == "3"


def test_seed_does_not_overwrite_a_locked_field(session):
    seed_profiles_from_documents(session, _gnb_history())
    session.commit()
    profile = session.query(CustomerProfile).one()
    fields = dict(profile.fields)
    fields["track_mount"] = {**fields["track_mount"], "value": "bracket", "locked": True, "source": "staff"}
    profile.fields = fields
    session.commit()

    seed_profiles_from_documents(session, _gnb_history())
    session.commit()
    session.refresh(profile)
    assert profile.fields["track_mount"]["value"] == "bracket"
    assert profile.fields["track_mount"]["locked"] is True


def _profile(session, **fields):
    body = {}
    for key, spec in fields.items():
        body[key] = spec
    row = CustomerProfile(
        bc_customer_id="GNB",
        customer_number="C-GNB",
        fields=body,
        contacts=[{"email": "orders@gnb.example", "role": "quote"}],
        email_domains=["gnb.example"],
        documents_seen=16,
    )
    session.add(row)
    session.commit()
    return row


def _angle_spec(locked=False):
    return {
        "value": "angle",
        "locked": locked,
        "confidence": 0.875,
        "support": 14,
        "total": 16,
        "evidence": "angle on 14 of 16 orders",
        "source": "staff" if locked else "bc_history",
    }


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


def _email_service(monkeypatch):
    monkeypatch.setattr(email_monitor_mod, "get_memory_service", lambda db: _Memory())
    return EmailMonitorService()


def _mapped_door(**extra):
    door = {
        "doorType": "commercial",
        "doorSeries": "TX450",
        "doorWidth": 144,
        "doorHeight": 120,
        "panelColor": "WHITE",
        "panelDesign": "FLUSH",
        "doorCount": 1,
        "trackMount": "bracket",
        "trackThickness": "2",
        "hardware": {"tracks": True},
    }
    door.update(extra)
    return door


def _run_email(service, session, monkeypatch, *, subject, body, sender, company="GNB"):
    log = EmailLog(
        message_id=subject,
        from_address=sender,
        subject=subject,
        body=body,
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
            "customer": {"company_name": company, "email": sender, "confidence": 0.9},
            "doors": [{"model": "TX450", "width_ft": 12, "height_ft": 10}],
            "project": {},
        },
    })
    monkeypatch.setattr(service.ai_client, "map_email_to_configurator", lambda *a, **k: {
        "success": True,
        "request_kind": "door_quote",
        "confidence": 0.9,
        "doors": [_mapped_door()],
    })
    captured = {}

    def _fake_build(request, db, source="admin"):
        captured["customerId"] = request.customerId
        captured["deliveryType"] = request.deliveryType
        captured["trackMount"] = request.doors[0].trackMount
        captured["called"] = True
        return {"success": True, "data": {"bc_quote_number": "SQ-1", "pricing": {"total": 10}, "line_pricing": []}}

    import app.api.door_configurator as dc
    monkeypatch.setattr(dc, "build_bc_quote_from_doors", _fake_build)
    service._parse_quote_request(session, log, subject, body, "Buyer", sender)
    return captured


def test_silent_email_uses_angle_for_that_customer(session, monkeypatch):
    _mode(session, "on")
    session.add(BCCustomer(
        bc_customer_id="GNB", company_name="GNB", email="orders@gnb.example",
        bc_price_group="GNB-CONTRACT",
    ))
    _profile(session, track_mount=_angle_spec(), delivery_type={
        "value": "pickup", "locked": False, "confidence": 0.9, "support": 14, "total": 16,
        "evidence": "pickup on 14 of 16 orders", "source": "bc_history",
    })
    service = _email_service(monkeypatch)
    captured = _run_email(
        service, session, monkeypatch,
        subject="need a door",
        body="Please quote a 12x10 TX450. No mount mentioned.",
        sender="orders@gnb.example",
    )
    assert captured["trackMount"] == "angle"
    assert captured["deliveryType"] == "pickup"
    quote = session.query(QuoteRequest).one()
    assert quote.field_sources["doors"][0]["trackMount"]["source"] == "profile"
    assert quote.field_sources["deliveryType"]["source"] == "profile"


def test_locked_angle_overrides_a_silent_bracket_default(session, monkeypatch):
    _mode(session, "on")
    session.add(BCCustomer(bc_customer_id="GNB", company_name="GNB", email="orders@gnb.example"))
    _profile(session, track_mount=_angle_spec(locked=True))
    service = _email_service(monkeypatch)
    captured = _run_email(
        service, session, monkeypatch,
        subject="silent",
        body="Quote one 12 by 10 commercial door.",
        sender="orders@gnb.example",
    )
    assert captured["trackMount"] == "angle"
    assert session.query(QuoteRequest).one().field_sources["doors"][0]["trackMount"]["locked"] is True


def test_explicit_bracket_against_locked_angle_is_a_deviation(session, monkeypatch):
    _mode(session, "on")
    session.add(BCCustomer(bc_customer_id="GNB", company_name="GNB", email="orders@gnb.example"))
    _profile(session, track_mount=_angle_spec(locked=True))
    service = _email_service(monkeypatch)
    captured = _run_email(
        service, session, monkeypatch,
        subject="bracket",
        body="Please quote this one with bracket mount.",
        sender="orders@gnb.example",
    )
    assert captured["trackMount"] == "angle"
    deviations = session.query(QuoteRequest).one().deviations
    assert any(
        item["kind"] == "locked_rule" and item["field"] == "trackMount"
        and item["email_value"] == "bracket" and item["applied_value"] == "angle"
        for item in deviations
    )


def test_shadow_records_the_profile_and_does_not_change_the_quote(session, monkeypatch):
    _mode(session, "shadow")
    session.add(BCCustomer(bc_customer_id="GNB", company_name="GNB", email="orders@gnb.example"))
    _profile(session, track_mount=_angle_spec(), delivery_type={
        "value": "pickup", "locked": True, "confidence": 1, "support": 16, "total": 16,
        "evidence": "pickup on 16 of 16 orders", "source": "staff",
    })
    service = _email_service(monkeypatch)
    captured = _run_email(
        service, session, monkeypatch,
        subject="shadow",
        body="Quote a 12x10 door.",
        sender="orders@gnb.example",
    )
    assert captured["trackMount"] == "bracket"
    assert captured["deliveryType"] == "delivery"
    quote = session.query(QuoteRequest).one()
    assert quote.field_sources["mode"] == "shadow"
    assert quote.field_sources["doors"][0]["trackMount"]["value"] == "angle"
    assert quote.status == "bc_created"


def test_second_contact_on_the_domain_gets_that_price_group(session, monkeypatch):
    _mode(session, "on")
    session.add(BCCustomer(
        bc_customer_id="GNB",
        company_name="GNB Manitoba",
        email="orders@gnb.example",
        bc_price_group="GNB-CONTRACT",
    ))
    session.commit()
    service = _email_service(monkeypatch)
    captured = _run_email(
        service, session, monkeypatch,
        subject="new buyer",
        body="Quote a 12x10 TX450.",
        sender="jane@gnb.example",
        company="Job site trailer",
    )
    assert captured["customerId"] == "GNB"
    customer = session.query(BCCustomer).filter_by(bc_customer_id="GNB").one()
    assert customer.bc_price_group == "GNB-CONTRACT"
    assert session.query(QuoteRequest).one().customer_match["method"] == "domain"


def test_unmatched_sender_is_held_instead_of_retail(session, monkeypatch):
    _mode(session, "on")
    session.add(BCCustomer(
        bc_customer_id="GNB", company_name="GNB Manitoba", email="orders@gnb.example",
    ))
    session.commit()
    service = _email_service(monkeypatch)
    captured = _run_email(
        service, session, monkeypatch,
        subject="who",
        body="Please quote a door.",
        sender="someone@gmail.com",
        company="Totally Unknown Fabrication",
    )
    assert captured.get("called") is not True
    quote = session.query(QuoteRequest).one()
    assert quote.status == "held_for_customer_match"
    assert quote.bc_quote_id is None


def test_flag_off_still_prices_an_unmatched_sender_at_retail(session, monkeypatch):
    _mode(session, "off")
    service = _email_service(monkeypatch)
    captured = _run_email(
        service, session, monkeypatch,
        subject="retail",
        body="Please quote a door.",
        sender="someone@gmail.com",
        company="Totally Unknown Fabrication",
    )
    assert captured["called"] is True
    assert captured["customerId"] is None
    assert captured["deliveryType"] == "delivery"
    assert session.query(QuoteRequest).one().status == "bc_created"


def test_free_mail_domain_does_not_match_another_gmail_customer(session):
    from app.services.customer_profile_service import match_bc_customer
    session.add(BCCustomer(bc_customer_id="GNB", company_name="GNB", email="pat@gmail.com"))
    session.commit()
    match = match_bc_customer(session, email="other@gmail.com", company_name="Nobody")
    assert match.confident is False
    assert match.bc_customer_id is None


def test_bracket_that_does_not_fit_is_recorded_as_a_deviation():
    config = DoorConfiguration(
        door_type="commercial",
        door_series="TX450",
        door_width=144,
        door_height=18 * 12,
        door_count=1,
        panel_color="WHITE",
        panel_design="FLUSH",
        track_thickness="3",
        track_mount="bracket",
    )
    parts = part_number_service._get_track_parts(config)
    assert any("ANGLE" in part.description.upper() for part in parts)
    assert config.deviations[0]["kind"] == "silent_substitution"
    assert config.deviations[0]["from"] == "bracket"
    assert config.deviations[0]["to"] == "angle"


def test_unstocked_weatherstrip_colour_is_a_deviation():
    config = DoorConfiguration(
        door_type="commercial",
        door_series="TX450",
        door_width=96,
        door_height=84,
        door_count=1,
        panel_color="FRENCH_OAK",
        panel_design="FLUSH",
        track_thickness="2",
        track_mount="bracket",
    )
    part_number_service._get_seal_parts(config)
    swaps = [item for item in config.deviations if item["kind"] == "colour_swap"]
    assert swaps
    assert swaps[0]["to"].upper() == "NEW ALMOND"


def test_quote_lookup_finds_a_number_outside_the_first_hundred(session, monkeypatch):
    _mode(session, "on")
    log = EmailLog(message_id="q", from_address="a@b.test", subject="s", body="b", status="parsed")
    session.add(log)
    session.flush()
    quote = QuoteRequest(
        email_id=log.id,
        customer_name="GNB",
        contact_email="a@b.test",
        bc_quote_id="SQ-003132",
        status="bc_created",
    )
    session.add(quote)
    session.commit()

    class _BC:
        def get_sales_quotes(self, top=100):
            return [{"id": f"guid-{i}", "number": f"SQ-{i:06d}"} for i in range(1, top + 1)]

        def get_sales_quote_by_number(self, number):
            assert number == "SQ-003132"
            return {"id": "guid-3132", "number": number}

        def convert_quote_to_order(self, quote_id):
            assert quote_id == "guid-3132"
            return {
                "id": "order-guid",
                "number": "SO-003132",
                "customerId": "GNB",
                "customerName": "GNB",
                "totalAmountIncludingTax": 100,
            }

    service = OrderLifecycleService()
    service.bc_client = _BC()
    result = service.convert_quote_to_order(session, quote.id, "joey")
    assert result["success"] is True
    assert result["bc_order_number"] == "SO-003132"
    # The first 100 numbers are SQ-000001 through SQ-000100. SQ-003132 is not in them.
    assert "SQ-003132" not in {row["number"] for row in _BC().get_sales_quotes(top=100)}


def test_quote_lookup_stays_on_the_first_page_when_the_switch_is_off(session):
    _mode(session, "off")
    log = EmailLog(message_id="q2", from_address="a@b.test", subject="s", body="b", status="parsed")
    session.add(log)
    session.flush()
    quote = QuoteRequest(
        email_id=log.id, customer_name="GNB", bc_quote_id="SQ-003132", status="bc_created",
    )
    session.add(quote)
    session.commit()

    class _BC:
        def get_sales_quotes(self, top=100):
            return [{"id": f"guid-{i}", "number": f"SQ-{i:06d}"} for i in range(1, top + 1)]

        def get_sales_quote_by_number(self, number):
            raise AssertionError("number lookup must stay unused while the switch is off")

    service = OrderLifecycleService()
    service.bc_client = _BC()
    result = service.convert_quote_to_order(session, quote.id, "joey")
    assert result["success"] is False
    assert "not found" in result["error"]


def test_customer_profile_migration_upgrades_and_downgrades(tmp_path):
    db_path = tmp_path / "migrate.db"
    url = f"sqlite:///{db_path}"
    engine = create_engine(url)
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE quote_requests (id INTEGER PRIMARY KEY)"))
    env = {**os.environ, "DATABASE_URL": url}
    alembic = str(BACKEND / ".venv" / "bin" / "alembic")

    def run(*args):
        completed = subprocess.run(
            [alembic, *args],
            cwd=str(BACKEND),
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        assert completed.returncode == 0, completed.stderr
        return completed

    run("stamp", "f3a4b5c6d7e8")
    run("upgrade", "head")
    with engine.connect() as conn:
        tables = {row[0] for row in conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))}
        assert "customer_profiles" in tables
        columns = {row[1] for row in conn.execute(text("PRAGMA table_info(quote_requests)"))}
        assert {"field_sources", "deviations", "matched_bc_customer_id", "customer_match"} <= columns
    run("downgrade", "f3a4b5c6d7e8")
    with engine.connect() as conn:
        tables = {row[0] for row in conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))}
        assert "customer_profiles" not in tables
        columns = {row[1] for row in conn.execute(text("PRAGMA table_info(quote_requests)"))}
        assert "field_sources" not in columns
    run("upgrade", "head")
    with engine.connect() as conn:
        tables = {row[0] for row in conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))}
        assert "customer_profiles" in tables
