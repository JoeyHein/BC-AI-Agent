"""My Quotes card title and the quote # / tag name search."""

from datetime import datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.customer_portal import SavedQuoteConfigResponse, router
from app.db.models import SavedQuoteConfig, SalesOrder, User, UserRole
from app.services.auth_service import AuthService
from app.services.saved_quote_title import quote_display_title, quote_matches_search


def test_title_prefers_the_job_name_over_description_and_the_sq_number():
    assert quote_display_title(
        "Lot 14 — Front Garage",
        "",
        "SQ-003428",
        {"poNumber": "PO-1"},
    ) == "Lot 14 — Front Garage"


def test_title_falls_back_to_description_then_reference_then_sq_number():
    assert quote_display_title("  ", "Side entrance", "SQ-003430") == "Side entrance"
    assert quote_display_title(None, None, "SQ-003430", {"poNumber": "PO-4491"}) == "PO-4491"
    assert quote_display_title(None, None, "SQ-003428") == "SQ-003428"
    assert quote_display_title(None, None, None) == "Quote"
    assert "No description" not in (
        quote_display_title(None, "", "SQ-003428"),
        quote_display_title("", None, None),
    )


def test_title_recovers_a_tag_stored_only_in_config_data():
    config = {"tagName": "Smith Residence", "doors": [{"panelColor": "BLACK"}]}
    assert quote_display_title(None, None, "SQ-003431", config) == "Smith Residence"
    assert quote_matches_search(None, "smith", None, "SQ-003431", config)
    # Door colors live in config_data too, and the search box is for the
    # quote name, not the panel color.
    assert not quote_matches_search(None, "black", None, "SQ-003431", config)


def test_search_matches_the_name_description_reference_and_quote_number():
    assert quote_matches_search("Lot 14 — Front Garage", "front garage", "", "SQ-003428")
    assert quote_matches_search("Lot 14", "LOT", "", "SQ-1")
    assert quote_matches_search("", "side", "Side entrance", "SQ-003430")
    assert quote_matches_search(None, "4491", None, "SQ-003430", {"poNumber": "PO-4491"})
    assert quote_matches_search(None, "3428", None, "SQ-003428")
    assert not quote_matches_search("Lot 14", "backyard", "", "SQ-003428")
    assert quote_matches_search("Anything", "   ", "", "SQ-1")


@pytest.fixture
def quote_client():
    from app.api import customer_portal as portal
    from app.api.customer_auth import get_current_customer

    engine = create_engine(
        "sqlite://",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    User.__table__.create(engine, checkfirst=True)
    SavedQuoteConfig.__table__.create(engine, checkfirst=True)
    SalesOrder.__table__.create(engine, checkfirst=True)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = Session()
    user = User(
        email="office@babebuilders.example",
        password_hash=AuthService.get_password_hash("preview123"),
        name="Babe Builders",
        role=UserRole.VIEWER,
        is_active=True,
        user_type="CUSTOMER",
        account_status="active",
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    def _db():
        try:
            yield db
        finally:
            pass

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[portal.get_db] = _db
    app.dependency_overrides[get_current_customer] = lambda: user
    client = TestClient(app)
    try:
        yield client, db, user
    finally:
        db.close()


def _door(series="KANATA"):
    return {
        "doors": [{
            "doorSeries": series,
            "doorWidth": 144,
            "doorHeight": 96,
            "panelColor": "BLACK",
        }],
        "deliveryType": "pickup",
    }


def test_create_saves_the_job_name_and_the_list_returns_it(quote_client):
    client, _db, _user = quote_client
    created = client.post("/api/customer/portal/saved-quotes", json={
        "name": "Lot 14 — Front Garage",
        "description": "",
        "config_data": _door(),
    })
    assert created.status_code == 200, created.text
    body = created.json()
    assert body["name"] == "Lot 14 — Front Garage"
    assert body["display_title"] == "Lot 14 — Front Garage"
    assert body["display_title"] != "No description"

    listed = client.get("/api/customer/portal/saved-quotes")
    assert listed.status_code == 200
    row = listed.json()[0]
    assert row["name"] == "Lot 14 — Front Garage"
    assert row["display_title"] == "Lot 14 — Front Garage"

    found = client.get("/api/customer/portal/saved-quotes", params={"search": "front garage"})
    assert [q["id"] for q in found.json()] == [body["id"]]
    missed = client.get("/api/customer/portal/saved-quotes", params={"search": "backyard"})
    assert missed.json() == []


def test_list_titles_and_search_cover_saved_rows_whose_name_column_is_blank(quote_client):
    client, db, user = quote_client
    db.add_all([
        SavedQuoteConfig(
            user_id=user.id,
            name="Lot 14 — Front Garage",
            description="",
            config_data=_door(),
            bc_quote_number="SQ-003428",
            bc_quote_id="guid-3428",
            created_at=datetime(2026, 11, 16, 15, 4),
        ),
        SavedQuoteConfig(
            user_id=user.id,
            name="",
            description="Side entrance, match the existing white door",
            config_data={**_door("TX450"), "poNumber": "PO-4491", "deliveryType": "delivery"},
            bc_quote_number="SQ-003430",
            bc_quote_id="guid-3430",
            created_at=datetime(2026, 11, 15, 12, 0),
        ),
        SavedQuoteConfig(
            user_id=user.id,
            name=None,
            description=None,
            config_data={**_door(), "tagName": "Smith Residence"},
            bc_quote_number="SQ-003431",
            bc_quote_id="guid-3431",
            created_at=datetime(2026, 11, 14, 9, 0),
        ),
        SavedQuoteConfig(
            user_id=user.id,
            name=None,
            description=None,
            config_data=_door(),
            bc_quote_number="SQ-003432",
            bc_quote_id="guid-3432",
            created_at=datetime(2026, 11, 13, 9, 0),
        ),
    ])
    db.commit()

    listed = client.get("/api/customer/portal/saved-quotes")
    assert listed.status_code == 200
    by_number = {row["bc_quote_number"]: row for row in listed.json()}
    assert by_number["SQ-003428"]["display_title"] == "Lot 14 — Front Garage"
    assert by_number["SQ-003430"]["display_title"] == "Side entrance, match the existing white door"
    assert by_number["SQ-003431"]["display_title"] == "Smith Residence"
    assert by_number["SQ-003432"]["display_title"] == "SQ-003432"
    assert all(row["display_title"] != "No description" for row in listed.json())

    # The response model accepts the title, so it is not dropped on the way out.
    SavedQuoteConfigResponse.model_validate(by_number["SQ-003431"])

    smith = client.get("/api/customer/portal/saved-quotes", params={"search": "smith"})
    assert [row["bc_quote_number"] for row in smith.json()] == ["SQ-003431"]
    po = client.get("/api/customer/portal/saved-quotes", params={"search": "po-4491"})
    assert [row["bc_quote_number"] for row in po.json()] == ["SQ-003430"]
    number = client.get("/api/customer/portal/saved-quotes", params={"search": "SQ-003432"})
    assert [row["bc_quote_number"] for row in number.json()] == ["SQ-003432"]
    # Panel color is not the quote name.
    color = client.get("/api/customer/portal/saved-quotes", params={"search": "BLACK"})
    assert color.json() == []


def test_list_ignores_another_customers_quotes(quote_client):
    client, db, user = quote_client
    other = User(
        email="other@example.com",
        password_hash="x",
        name="Other",
        role=UserRole.VIEWER,
        is_active=True,
        user_type="CUSTOMER",
    )
    db.add(other)
    db.commit()
    db.refresh(other)
    db.add(SavedQuoteConfig(
        user_id=other.id,
        name="Secret Job",
        description="",
        config_data=_door(),
        created_at=datetime(2026, 11, 16),
    ))
    db.add(SavedQuoteConfig(
        user_id=user.id,
        name="My Job",
        description="",
        config_data=_door(),
        created_at=datetime(2026, 11, 16),
    ))
    db.commit()
    listed = client.get("/api/customer/portal/saved-quotes", params={"search": "job"})
    names = [row["name"] for row in listed.json()]
    assert names == ["My Job"]
