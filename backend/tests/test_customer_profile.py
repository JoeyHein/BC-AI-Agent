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
    assert "delivery_type" not in profile.fields
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
    assert captured.get("called") is not True
    quote = session.query(QuoteRequest).one()
    assert quote.status == "held_for_standard_deviation"
    assert quote.bc_quote_id is None
    mount = quote.field_sources["doors"][0]["trackMount"]
    assert mount["used"] == "bracket"
    assert mount["email_says"] == "bracket"
    assert mount["profile_says"] == "angle"
    deviations = quote.deviations
    assert any(
        item["kind"] == "deviation_from_customer_standard"
        and item["field"] == "trackMount"
        and item["email_value"] == "bracket"
        and "GNB standard is angle (locked, 14/16 orders)" in item["reason"]
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
    assert captured.get("called") is not True
    quote = session.query(QuoteRequest).one()
    assert quote.status == "held_for_customer_match"
    assert quote.customer_match["method"] == "domain"
    assert quote.customer_match["suggested"] is True
    assert quote.customer_match["bc_customer_id"] == "GNB"
    assert quote.bc_quote_id is None


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


def test_quote_lookup_by_number_works_while_the_switch_is_off(session):
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
            raise AssertionError("page scan is only the fallback")

        def get_sales_quote_by_number(self, number):
            return {"id": "guid-3132", "number": number}

        def convert_quote_to_order(self, quote_id):
            return {"id": "order-guid", "number": "SO-1", "totalAmountIncludingTax": 1}

    service = OrderLifecycleService()
    service.bc_client = _BC()
    result = service.convert_quote_to_order(session, quote.id, "joey")
    assert result["success"] is True


def test_quote_lookup_falls_back_to_the_first_page_when_number_search_fails(session):
    log = EmailLog(message_id="q3", from_address="a@b.test", subject="s", body="b", status="parsed")
    session.add(log)
    session.flush()
    quote = QuoteRequest(
        email_id=log.id, customer_name="GNB", bc_quote_id="SQ-000007", status="bc_created",
    )
    session.add(quote)
    session.commit()

    class _BC:
        def get_sales_quotes(self, top=100):
            return [{"id": "guid-7", "number": "SQ-000007"}]

        def get_sales_quote_by_number(self, number):
            raise RuntimeError("odata down")

        def convert_quote_to_order(self, quote_id):
            assert quote_id == "guid-7"
            return {"id": "order-guid", "number": "SO-7", "totalAmountIncludingTax": 1}

    service = OrderLifecycleService()
    service.bc_client = _BC()
    assert service.convert_quote_to_order(session, quote.id, "joey")["success"] is True


def test_customer_profile_migration_upgrades_and_downgrades(tmp_path):
    pytest.importorskip("alembic")
    db_path = tmp_path / "migrate.db"
    url = f"sqlite:///{db_path}"
    engine = create_engine(url)
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE quote_requests (id INTEGER PRIMARY KEY)"))
    env = {**os.environ, "DATABASE_URL": url}
    def run(*args):
        completed = subprocess.run(
            [sys.executable, "-m", "alembic", *args],
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


def test_same_as_usual_uses_the_profile_and_marks_it(session, monkeypatch):
    _mode(session, "on")
    session.add(BCCustomer(bc_customer_id="GNB", company_name="GNB", email="orders@gnb.example"))
    _profile(session, track_mount=_angle_spec())
    service = _email_service(monkeypatch)
    captured = _run_email(
        service, session, monkeypatch,
        subject="reorder",
        body="Please quote a 12x10, same as usual.",
        sender="orders@gnb.example",
    )
    assert captured["trackMount"] == "angle"
    mount = session.query(QuoteRequest).one().field_sources["doors"][0]["trackMount"]
    assert mount["source"] == "profile"
    assert mount["resolution"] == "ambiguous"
    assert mount["marked"] is True
    assert "same as usual" in (mount.get("note") or "").lower()


def test_shadow_failure_still_prices_the_old_quote(session, monkeypatch):
    _mode(session, "shadow")
    session.add(BCCustomer(bc_customer_id="GNB", company_name="GNB", email="orders@gnb.example"))
    session.commit()
    service = _email_service(monkeypatch)

    def _boom(*args, **kwargs):
        raise RuntimeError("profile blew up")

    monkeypatch.setattr(
        "app.services.customer_profile_service.apply_profile_for_customer", _boom,
    )
    captured = _run_email(
        service, session, monkeypatch,
        subject="shadow-fail",
        body="Quote a 12x10 TX450.",
        sender="orders@gnb.example",
    )
    assert captured["called"] is True
    assert captured["trackMount"] == "bracket"
    assert captured["deliveryType"] == "delivery"
    assert session.query(QuoteRequest).one().status == "bc_created"


def test_explicit_defaults_survive_the_quote_builder(session):
    """white / bracket / 2 inch track must survive the real quote builder."""
    _mode(session, "on")
    session.add(BCCustomer(bc_customer_id="GNB", company_name="GNB", email="orders@gnb.example"))
    _profile(
        session,
        track_mount=_angle_spec(locked=False),
        panel_color={
            "value": "BLACK", "locked": False, "confidence": 0.9, "support": 14, "total": 16,
            "evidence": "BLACK on 14 of 16 orders", "source": "bc_history",
        },
        track_size={
            "value": "3", "locked": False, "confidence": 0.9, "support": 14, "total": 16,
            "evidence": '3" on 14 of 16 orders', "source": "bc_history",
        },
    )
    from app.api.door_configurator import DoorConfigRequest, QuoteGenerationRequest, build_bc_quote_from_doors
    from app.services.customer_profile_service import apply_profile_for_customer

    applied = apply_profile_for_customer(
        session, "GNB", [_mapped_door()],
        email_text="Please quote white, bracket mount, 2 inch track, 12x10 TX450.",
        customer_name="GNB",
    )
    door = applied["doors"][0]
    assert door["panelColor"] == "WHITE"
    assert door["trackMount"] == "bracket"
    assert door["trackThickness"] == "2"
    request = QuoteGenerationRequest(
        doors=[DoorConfigRequest(**door)],
        customerId="GNB",
        deliveryType=applied["delivery_type"],
        deliveryExplicit=True,
        profileApplied=True,
    )
    try:
        build_bc_quote_from_doors(request, session, source="email")
    except Exception:
        pass
    assert request.doors[0].panelColor == "WHITE"
    assert request.doors[0].trackMount == "bracket"
    assert request.doors[0].trackThickness == "2"


def test_free_mail_and_internal_domains_are_not_customer_domains(session):
    from app.services.customer_profile_service import match_bc_customer
    session.add(BCCustomer(bc_customer_id="GNB", company_name="GNB", email="pat@shaw.ca"))
    session.add(BCCustomer(bc_customer_id="STAFF", company_name="OpenDC", email="joey@opendc.ca"))
    session.commit()
    shaw = match_bc_customer(session, email="other@shaw.ca", company_name="Nobody")
    assert shaw.confident is False and shaw.bc_customer_id is None
    internal = match_bc_customer(session, email="sam@opendc.ca", company_name="Nobody")
    assert internal.bc_customer_id is None


def test_cash_customer_does_not_collect_contacts_or_domains(session):
    seed_profiles_from_documents(session, [{
        "customer_id": "CASH",
        "email": "someone@gmail.com",
        "lines": [{"number": "TR03-STDAM-10", "description": "ANGLE", "lineType": "Item"}],
    }])
    session.commit()
    profile = session.query(CustomerProfile).filter_by(bc_customer_id="CASH").one()
    assert profile.contacts == [] or profile.contacts is None or profile.contacts == []
    assert profile.email_domains in ([], None) or profile.email_domains == []


def test_missing_freight_is_not_inferred_as_pickup(session):
    seed_profiles_from_documents(session, [{
        "customer_id": "NOF",
        "lines": [{"number": "TR03-STDAM-10", "description": "ANGLE", "lineType": "Item"}],
    }])
    session.commit()
    assert "delivery_type" not in (session.query(CustomerProfile).filter_by(bc_customer_id="NOF").one().fields or {})


def test_gl_freight_line_counts_as_delivery(session):
    seed_profiles_from_documents(session, [{
        "customer_id": "GLF",
        "lines": [
            {"number": "TR03-STDAM-10", "description": "ANGLE", "lineType": "Item"},
            {"number": "", "description": "FREIGHT CHARGE", "lineType": "Account"},
        ],
    }])
    session.commit()
    assert session.query(CustomerProfile).filter_by(bc_customer_id="GLF").one().fields["delivery_type"]["value"] == "delivery"


def test_locked_contact_list_does_not_restore_a_removed_address(session):
    seed_profiles_from_documents(session, [{
        "customer_id": "LOCKC",
        "email": "keep@lock.example",
        "lines": [{"number": "TR03-STDAM-10", "description": "ANGLE", "lineType": "Item"}],
    }])
    session.commit()
    profile = session.query(CustomerProfile).filter_by(bc_customer_id="LOCKC").one()
    profile.contacts = [{"email": "keep@lock.example", "role": "quote"}]
    profile.contacts_locked = True
    session.commit()
    seed_profiles_from_documents(session, [{
        "customer_id": "LOCKC",
        "email": "removed@lock.example",
        "lines": [{"number": "TR03-STDAM-10", "description": "ANGLE", "lineType": "Item"}],
    }])
    session.commit()
    session.refresh(profile)
    assert [row["email"] for row in profile.contacts] == ["keep@lock.example"]


def test_pending_review_includes_held_customer_matches(session):
    from types import SimpleNamespace
    from app.api.quotes import get_pending_quotes
    log = EmailLog(message_id="held", from_address="a@b.test", subject="s", body="b", status="parsed")
    session.add(log)
    session.flush()
    session.add(QuoteRequest(
        email_id=log.id, customer_name="Maybe", contact_email="a@b.test",
        status="held_for_customer_match", confidence_scores={"overall": 0.5}, parsed_data={},
    ))
    session.commit()
    rows = get_pending_quotes(status="pending", db=session, current_user=SimpleNamespace(user_type="INTERNAL"))
    assert any(row.status == "held_for_customer_match" for row in rows)


def test_customer_token_cannot_read_the_review_queue(session):
    from types import SimpleNamespace
    from fastapi import HTTPException
    from app.api.quotes import get_pending_quotes
    with pytest.raises(HTTPException) as caught:
        get_pending_quotes(status="pending", db=session, current_user=SimpleNamespace(user_type="CUSTOMER"))
    assert caught.value.status_code == 403


def test_confirming_a_suggestion_remembers_the_contact(session):
    from types import SimpleNamespace
    from app.api.feedback import confirm_suggested_customer
    log = EmailLog(message_id="sug", from_address="jane@gnb.example", subject="s", body="b", status="parsed")
    session.add(log)
    session.flush()
    session.add(BCCustomer(bc_customer_id="GNB", company_name="GNB Manitoba", email="orders@gnb.example"))
    quote = QuoteRequest(
        email_id=log.id, customer_name="Jane", contact_email="jane@gnb.example",
        status="held_for_customer_match", confidence_scores={"overall": 0.5}, parsed_data={},
        customer_match={"bc_customer_id": "GNB", "method": "domain", "suggested": True, "confident": False},
    )
    session.add(quote)
    session.commit()
    confirm_suggested_customer(quote.id, session, SimpleNamespace(email="joey@opendc.ca", user_type="INTERNAL"))
    profile = session.query(CustomerProfile).filter_by(bc_customer_id="GNB").one()
    assert "jane@gnb.example" in {row["email"] for row in profile.contacts}
    session.refresh(quote)
    assert quote.status == "pending"
    assert quote.customer_match["method"] == "confirmed_contact"


def test_seed_keeps_catalog_operator_keys_and_drops_raw_text(session):
    seed_profiles_from_documents(session, [{
        "customer_id": "OPS",
        "lines": [
            {"number": "OP19-01073-00", "description": "LiftMaster 84505R", "lineType": "Item"},
            {"number": "OP19-01080-00", "description": "Trolley track", "lineType": "Item"},
            {"number": "MISC-1", "description": "wall mount operator", "lineType": "Item"},
        ],
    }])
    session.commit()
    fields = session.query(CustomerProfile).filter_by(bc_customer_id="OPS").one().fields
    assert fields["operator"]["value"] == "OP19-01073-00"
    assert fields["accessories"]["value"] == "OP19-01080-00"
    assert "wall mount" not in fields["operator"]["value"]


def test_silent_email_does_not_add_windows_or_operator_from_history(session):
    from app.services.customer_profile_service import apply_profile_for_customer
    _mode(session, "on")
    _profile(
        session,
        windows={"value": "yes", "locked": True, "confidence": 1, "support": 10, "total": 10, "evidence": "windows"},
        glass={"value": "single", "locked": True, "confidence": 1, "support": 10, "total": 10, "evidence": "glass"},
        operator={"value": "OP19-01073-00", "locked": True, "confidence": 1, "support": 10, "total": 10, "evidence": "op"},
    )
    applied = apply_profile_for_customer(
        session, "GNB", [_mapped_door()],
        email_text="Please quote a 12x10 TX450.",
        customer_name="GNB",
    )
    door = applied["doors"][0]
    assert door.get("hasWindows") in (False, None)
    assert door.get("operator") in (None, "", "NONE")
    assert door.get("glazingType") in (None, "", "NONE")


def test_stored_configs_drop_the_configurator_touch_map():
    from app.api.customer_portal import _strip_ephemeral_door_keys
    cleaned = _strip_ephemeral_door_keys({
        "deliveryType": "pickup",
        "doors": [{"panelColor": "WHITE", "_touched": {"panelColor": True}, "explicitFields": ["panelColor"]}],
    })
    assert cleaned["doors"] == [{"panelColor": "WHITE"}]
    assert cleaned["deliveryType"] == "pickup"
