"""Configurator quotes record who generated them without clobbering a typed PO.

The tag is ``<SHORTNAME>-<NNNN>`` (``EMAIL-<NNNN>`` when no staff user).
It is stored on the portal snapshot / saved quote. External Document No.
keeps a typed PO exactly, and uses the tag only when that field is blank.
Your Reference is never sent: the standard api/v2.0 salesQuotes entity has
no such property and BC rejects the whole request with a 400.
"""
from __future__ import annotations

import sys
import tempfile
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.api.admin_customers import get_current_admin
from app.api.admin_quotes import router as admin_quotes_router
from app.api.door_configurator import (
    DoorConfigRequest,
    QuoteGenerationRequest,
    build_bc_quote_from_doors,
)
from app.db.models import (
    AppSettings,
    BCCustomer,
    ConfiguratorQuoteCounter,
    QuoteReview,
    QuoteSnapshot,
    SalesOrder,
    SavedQuoteConfig,
    User,
    UserRole,
)
from app.services.auth_service import AuthService
from app.services.configurator_quote_tag import (
    allocate_creator_tag,
    external_document_number,
    format_creator_tag,
    shortname_from_email,
)
from app.services.quote_review_service import save_quote_snapshot


_DOOR = {
    "doorType": "residential",
    "doorSeries": "KANATA",
    "doorWidth": 96,
    "doorHeight": 84,
    "panelColor": "WHITE",
    "panelDesign": "FLUSH",
}


def _shortname_cases():
    assert shortname_from_email("mpadda@upwardor.com") == "MPADDA"
    assert shortname_from_email("joey@opendc.ca") == "JOEY"
    assert shortname_from_email("m.padda+sales@upwardor.com") == "MPADDASALES"
    assert shortname_from_email("...@opendc.ca") == "USER"
    assert shortname_from_email("") == "USER"
    assert shortname_from_email(None) == "USER"


def test_shortname_from_email():
    _shortname_cases()


def test_tag_is_zero_padded_and_fits_bc_limit():
    assert format_creator_tag("JOEY", 1) == "JOEY-0001"
    assert format_creator_tag("MPADDA", 12) == "MPADDA-0012"
    assert format_creator_tag("EMAIL", 1) == "EMAIL-0001"

    long_prefix = "A" * 40
    tag = format_creator_tag(long_prefix, 1)
    assert len(tag) == 35
    assert tag.endswith("-0001")
    assert tag.startswith("A")

    wide = format_creator_tag(long_prefix, 10000)
    assert len(wide) <= 35
    assert wide.endswith("-10000")


def test_typed_po_is_kept_exactly_and_blank_uses_the_tag():
    assert external_document_number("PO-123", "JOEY-0001") == "PO-123"
    assert external_document_number(" PO-9 ", "JOEY-0001") == " PO-9 "
    assert external_document_number(None, "JOEY-0001") == "JOEY-0001"
    assert external_document_number("   ", "JOEY-0001") == "JOEY-0001"
    assert external_document_number("", "EMAIL-0004") == "EMAIL-0004"


def _engine(shared=True):
    if shared:
        engine = create_engine(
            "sqlite://",
            future=True,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
    else:
        path = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
        engine = create_engine(
            f"sqlite:///{path}",
            future=True,
            connect_args={"check_same_thread": False, "timeout": 30},
        )
    for table in (
        User.__table__,
        AppSettings.__table__,
        ConfiguratorQuoteCounter.__table__,
        SavedQuoteConfig.__table__,
        QuoteSnapshot.__table__,
        QuoteReview.__table__,
        BCCustomer.__table__,
        SalesOrder.__table__,
    ):
        table.create(engine, checkfirst=True)
    return engine


def _sessions(engine):
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


def _user(email, *, user_type="INTERNAL", role=UserRole.ADMIN):
    return User(
        email=email,
        password_hash=AuthService.get_password_hash("test123"),
        name=email.split("@")[0],
        role=role,
        is_active=True,
        user_type=user_type,
        invite_pending=False,
    )


def test_counters_are_per_user_and_email_has_its_own():
    Session = _sessions(_engine())
    db = Session()
    joey = _user("joey@opendc.ca")
    other_joey = _user("joey@upwardor.com")
    mpadda = _user("mpadda@upwardor.com")
    db.add_all([joey, other_joey, mpadda])
    db.commit()

    first, joey_id, joey_email = allocate_creator_tag(db, joey)
    second, _, _ = allocate_creator_tag(db, joey)
    sibling, _, _ = allocate_creator_tag(db, other_joey)
    manveer, manveer_id, manveer_email = allocate_creator_tag(db, mpadda)
    email_tag, email_id, email_addr = allocate_creator_tag(db, None)
    email_tag_2, _, _ = allocate_creator_tag(db, None)
    db.commit()

    assert first == "JOEY-0001"
    assert second == "JOEY-0002"
    assert sibling == "JOEY-0001"
    assert manveer == "MPADDA-0001"
    assert joey_id == joey.id and joey_email == "joey@opendc.ca"
    assert manveer_id == mpadda.id and manveer_email == "mpadda@upwardor.com"
    assert email_tag == "EMAIL-0001"
    assert email_tag_2 == "EMAIL-0002"
    assert email_id is None and email_addr is None

    rows = {row.counter_key: row.last_issued for row in db.query(ConfiguratorQuoteCounter).all()}
    assert rows[f"user:{joey.id}"] == 2
    assert rows[f"user:{other_joey.id}"] == 1
    assert rows[f"user:{mpadda.id}"] == 1
    assert rows["email"] == 2
    db.close()


def test_concurrent_clicks_get_unique_numbers():
    Session = _sessions(_engine(shared=False))
    db = Session()
    joey = _user("joey@opendc.ca")
    db.add(joey)
    db.commit()
    principal = SimpleNamespace(id=joey.id, email=joey.email)
    db.close()

    tags = []
    errors = []
    lock = threading.Lock()

    def worker():
        session = Session()
        try:
            tag, _, _ = allocate_creator_tag(session, principal)
            session.commit()
            with lock:
                tags.append(tag)
        except Exception as exc:  # pragma: no cover - assertion below
            session.rollback()
            with lock:
                errors.append(repr(exc))
        finally:
            session.close()

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    assert sorted(tags) == [f"JOEY-{n:04d}" for n in range(1, 9)]


# Writable header properties on the standard BC api/v2.0 salesQuote entity
# (Microsoft Learn, "salesQuote resource type"). Real BC answers any other
# key with 400 "The property 'X' does not exist on type
# 'Microsoft.NAV.salesQuote'" and creates nothing.
_SALES_QUOTE_V2_PROPERTIES = {
    "number", "externalDocumentNumber", "documentDate", "postingDate",
    "dueDate", "customerId", "customerNumber", "customerName", "billToName",
    "billToCustomerId", "billToCustomerNumber", "shipToName", "shipToContact",
    "sellToAddressLine1", "sellToAddressLine2", "sellToCity", "sellToCountry",
    "sellToState", "sellToPostCode", "billToAddressLine1", "billToAddressLine2",
    "billToCity", "billToCountry", "billToState", "billToPostCode",
    "shipToAddressLine1", "shipToAddressLine2", "shipToCity", "shipToCountry",
    "shipToState", "shipToPostCode", "shortcutDimension1Code",
    "shortcutDimension2Code", "currencyId", "currencyCode", "paymentTermsId",
    "shipmentMethodId", "salesperson", "discountAmount", "status",
    "validUntilDate", "phoneNumber", "email",
}


def _reject_unknown_quote_properties(quote_data):
    unknown = sorted(set(quote_data) - _SALES_QUOTE_V2_PROPERTIES)
    if unknown:
        raise RuntimeError(
            f"400 Bad Request | BC: The property '{unknown[0]}' does not "
            f"exist on type 'Microsoft.NAV.salesQuote'."
        )


class _RecordingBC:
    def __init__(self):
        self.created = []
        self.updated = []
        self.n = 0

    def create_sales_quote(self, quote_data, company_id=None):
        _reject_unknown_quote_properties(quote_data)
        self.n += 1
        self.created.append(dict(quote_data))
        return {"id": f"quote-{self.n}", "number": f"SQ-90000{self.n}"}

    def update_sales_quote(self, quote_id, quote_data, etag="*", company_id=None):
        _reject_unknown_quote_properties(quote_data)
        self.updated.append({"id": quote_id, "data": dict(quote_data), "etag": etag})
        return {"id": quote_id, "number": "SQ-900001"}

    def get_sales_quote(self, quote_id):
        return {
            "id": quote_id,
            "number": "SQ-900001",
            "@odata.etag": 'W/"1"',
            "totalAmountExcludingTax": 100.0,
            "totalAmountIncludingTax": 105.0,
        }

    def get_quote_lines(self, quote_id):
        return [{
            "id": "line-1",
            "lineType": "Item",
            "lineObjectNumber": "PN-TEST",
            "description": "Test panel",
            "quantity": 1,
            "unitPrice": 100.0,
            "netAmount": 100.0,
            "@odata.etag": "*",
        }]

    def add_quote_line(self, quote_id, line_data):
        return {"id": "line-1", "sequence": 10000, "@odata.etag": "*"}

    def delete_quote_line(self, quote_id, line_id):
        return None

    def update_quote_line(self, quote_id, line_id, etag, data):
        return {"id": line_id}

    def set_quote_line_output(self, number, sequence, output=True):
        return None


def _fake_parts(config_dict, spring_inventory=None):
    return {
        "parts_list": [{
            "lineType": "Item",
            "part_number": "PN-TEST",
            "description": "Test panel",
            "quantity": 1,
            "category": "panel",
            "unit_price": 100,
            "unit_cost": 40,
        }]
    }


def _install_mocks(monkeypatch, bc):
    import app.api.door_configurator as door_config

    monkeypatch.setattr(door_config, "get_bc_spring_inventory", lambda: {})
    monkeypatch.setattr(door_config, "get_parts_for_door_config", _fake_parts)
    monkeypatch.setattr(door_config, "bc_client", bc)
    monkeypatch.setattr(
        "app.services.bc_part_number_mapper.get_bc_mapper",
        lambda: SimpleNamespace(bc_items={"PN-TEST": {"displayName": "Test panel"}}),
    )


def _generate(db, user, bc, **kwargs):
    request = QuoteGenerationRequest(
        doors=[DoorConfigRequest(**_DOOR)],
        deliveryType="pickup",
        **kwargs,
    )
    return build_bc_quote_from_doors(request, db, source="email" if user is None else "admin", user=user)


@pytest.fixture
def quote_db():
    Session = _sessions(_engine())
    db = Session()
    joey = _user("joey@opendc.ca")
    dealer = _user("dealer@example.com", user_type="CUSTOMER", role=UserRole.VIEWER)
    db.add_all([joey, dealer])
    db.commit()
    db.refresh(joey)
    db.refresh(dealer)
    config = SavedQuoteConfig(
        user_id=dealer.id,
        name="Lot 4",
        config_data={"doors": []},
        bc_quote_id="quote-1",
        bc_quote_number="SQ-900001",
    )
    db.add(config)
    db.commit()
    yield db, joey
    db.close()


def test_typed_po_is_preserved_and_tag_is_stored(monkeypatch, quote_db):
    db, joey = quote_db
    bc = _RecordingBC()
    _install_mocks(monkeypatch, bc)

    result = _generate(db, joey, bc, poNumber=" PO-123 ")
    data = result["data"]

    assert data["creator_tag"] == "JOEY-0001"
    assert data["created_by_user_id"] == joey.id
    assert data["created_by_email"] == "joey@opendc.ca"
    assert data["po_number"] == " PO-123 "
    assert bc.created[0]["externalDocumentNumber"] == " PO-123 "
    assert "yourReference" not in bc.created[0]
    assert bc.updated == []

    snap = db.query(QuoteSnapshot).filter(QuoteSnapshot.bc_quote_id == data["bc_quote_id"]).one()
    assert snap.creator_tag == "JOEY-0001"
    assert snap.creator_user_id == joey.id
    assert snap.creator_email == "joey@opendc.ca"

    saved = db.query(SavedQuoteConfig).filter(SavedQuoteConfig.bc_quote_id == "quote-1").one()
    assert saved.creator_tag == "JOEY-0001"
    assert saved.creator_user_id == joey.id
    assert saved.creator_email == "joey@opendc.ca"
    assert saved.name == "Lot 4"


def test_blank_po_uses_the_tag_and_the_counter_advances(monkeypatch, quote_db):
    db, joey = quote_db
    bc = _RecordingBC()
    _install_mocks(monkeypatch, bc)

    first = _generate(db, joey, bc, poNumber=None)
    second = _generate(db, joey, bc, poNumber="   ")

    assert first["data"]["creator_tag"] == "JOEY-0001"
    assert first["data"]["po_number"] == "JOEY-0001"
    assert bc.created[0]["externalDocumentNumber"] == "JOEY-0001"
    assert "yourReference" not in bc.created[0]

    assert second["data"]["creator_tag"] == "JOEY-0002"
    assert second["data"]["po_number"] == "JOEY-0002"
    assert bc.created[1]["externalDocumentNumber"] == "JOEY-0002"
    assert "yourReference" not in bc.created[1]


def test_email_path_has_its_own_counter_and_keeps_a_supplied_reference(monkeypatch, quote_db):
    db, _joey = quote_db
    bc = _RecordingBC()
    _install_mocks(monkeypatch, bc)

    blank = _generate(db, None, bc)
    supplied = _generate(db, None, bc, poNumber="EMAIL-QR-9")

    assert blank["data"]["creator_tag"] == "EMAIL-0001"
    assert blank["data"]["created_by_user_id"] is None
    assert blank["data"]["created_by_email"] is None
    assert blank["data"]["po_number"] == "EMAIL-0001"
    assert "yourReference" not in bc.created[0]
    assert bc.created[0]["externalDocumentNumber"] == "EMAIL-0001"

    assert supplied["data"]["creator_tag"] == "EMAIL-0002"
    assert supplied["data"]["po_number"] == "EMAIL-QR-9"
    assert "yourReference" not in bc.created[1]
    assert bc.created[1]["externalDocumentNumber"] == "EMAIL-QR-9"

    snap = db.query(QuoteSnapshot).filter(
        QuoteSnapshot.bc_quote_number == supplied["data"]["bc_quote_number"]
    ).one()
    assert snap.creator_tag == "EMAIL-0002"
    assert snap.creator_user_id is None
    assert snap.source == "email"


def test_typed_reference_generates_against_strict_v2_quote_entity(monkeypatch, quote_db):
    """Regression: Oct 28 2026, PO / Reference 'Vern' -> BC 400 on yourReference."""
    db, joey = quote_db
    bc = _RecordingBC()
    _install_mocks(monkeypatch, bc)

    result = _generate(db, joey, bc, poNumber="Vern")

    assert result["data"]["bc_quote_number"] == "SQ-900001"
    assert result["data"]["po_number"] == "Vern"
    assert result["data"]["creator_tag"] == "JOEY-0001"
    assert len(bc.created) == 1
    assert set(bc.created[0]) <= _SALES_QUOTE_V2_PROPERTIES
    assert bc.created[0]["externalDocumentNumber"] == "Vern"

    snap = db.query(QuoteSnapshot).filter(
        QuoteSnapshot.bc_quote_id == result["data"]["bc_quote_id"]
    ).one()
    assert snap.creator_tag == "JOEY-0001"


def test_regenerating_a_quote_reuses_the_tag(monkeypatch, quote_db):
    db, joey = quote_db
    bc = _RecordingBC()
    _install_mocks(monkeypatch, bc)

    first = _generate(db, joey, bc, poNumber="JOB-1")
    quote_id = first["data"]["bc_quote_id"]
    second = _generate(db, joey, bc, poNumber="JOB-2", bcQuoteId=quote_id)

    assert first["data"]["creator_tag"] == "JOEY-0001"
    assert second["data"]["creator_tag"] == "JOEY-0001"
    assert second["data"]["po_number"] == "JOB-2"
    assert bc.updated[-1]["data"] == {"externalDocumentNumber": "JOB-2"}
    assert bc.updated[-1]["data"]["externalDocumentNumber"] == "JOB-2"
    assert len(bc.created) == 1

    issued = db.query(ConfiguratorQuoteCounter).filter(
        ConfiguratorQuoteCounter.counter_key == f"user:{joey.id}"
    ).one()
    assert issued.last_issued == 1


def test_snapshot_refresh_keeps_creator_when_not_passed(quote_db):
    db, joey = quote_db
    save_quote_snapshot(
        db=db,
        bc_quote_id="quote-keep",
        bc_quote_number="SQ-1",
        source="admin",
        all_lines=[],
        creator_user_id=joey.id,
        creator_email=joey.email,
        creator_tag="JOEY-0007",
    )
    save_quote_snapshot(
        db=db,
        bc_quote_id="quote-keep",
        bc_quote_number="SQ-1",
        source="customer",
        all_lines=[{"part_number": "PN-TEST"}],
    )
    snap = db.query(QuoteSnapshot).filter(QuoteSnapshot.bc_quote_id == "quote-keep").one()
    assert snap.creator_tag == "JOEY-0007"
    assert snap.creator_email == joey.email
    assert snap.creator_user_id == joey.id
    assert snap.source == "customer"


def test_staff_quote_search_returns_creator_even_when_po_was_typed():
    Session = _sessions(_engine())
    db = Session()
    dealer = _user("dealer@example.com", user_type="CUSTOMER", role=UserRole.VIEWER)
    db.add(dealer)
    db.commit()
    db.add(SavedQuoteConfig(
        user_id=dealer.id,
        name="Typed PO",
        config_data={"poNumber": "PO-55"},
        bc_quote_number="SQ-100",
        bc_quote_id="guid-saved",
        is_submitted=True,
        creator_user_id=None,
        creator_email="joey@opendc.ca",
        creator_tag="JOEY-0004",
    ))
    db.add(QuoteSnapshot(
        bc_quote_id="guid-email",
        bc_quote_number="SQ-200",
        source="email",
        original_lines=[],
        creator_tag="EMAIL-0003",
        creator_email=None,
        creator_user_id=None,
    ))
    db.commit()

    from app.api import admin_quotes as admin_quotes_module

    def _override():
        session = Session()
        try:
            yield session
        finally:
            session.close()

    app = FastAPI()
    app.include_router(admin_quotes_router)
    app.dependency_overrides[admin_quotes_module.get_db] = _override
    app.dependency_overrides[get_current_admin] = lambda: _user("joey@opendc.ca")
    client = TestClient(app)

    listed = client.get("/api/admin/quotes")
    assert listed.status_code == 200, listed.text
    by_number = {row["bc_quote_number"]: row for row in listed.json()}
    assert by_number["SQ-100"]["creator_tag"] == "JOEY-0004"
    assert by_number["SQ-100"]["creator_email"] == "joey@opendc.ca"
    assert by_number["SQ-100"]["name"] == "Typed PO"
    assert by_number["SQ-200"]["creator_tag"] == "EMAIL-0003"
    assert by_number["SQ-200"]["creator_email"] is None

    found = client.get("/api/admin/quotes", params={"search": "JOEY-0004"})
    assert found.status_code == 200
    assert [row["bc_quote_number"] for row in found.json()] == ["SQ-100"]

    email_hit = client.get("/api/admin/quotes", params={"search": "EMAIL-0003"})
    assert [row["bc_quote_number"] for row in email_hit.json()] == ["SQ-200"]
    db.close()
