"""Shop TV board lane mapping, window, and kiosk auth.

The flag defaults to off. Off is 404. A missing token is 401. A revoked
kiosk token is 403. The token is read-only and cannot change settings.
"""
from __future__ import annotations

import sys
from datetime import date, datetime
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.api.shop_tv import router
from app.db.database import get_db as database_get_db
from app.db.models import AppSettings, ShopTvKioskToken, User, UserRole
from app.services.auth_service import AuthService
from app.services.shop_tv_board import (
    OutlookShippingCalendarSource,
    build_board,
    default_lane_config,
)
from app.services.shop_tv_kiosk import create_token, revoke_token
from app.services.staff_permissions import permission_for

TODAY = date(2026, 11, 12)
NOW = datetime(2026, 11, 12, 15, 0)


def _items(board, lane):
    rows = []
    for day in board["lanes"][lane]["days"]:
        rows.extend(day["items"])
    return rows


def _by_number(board, lane):
    return {item["order_number"]: item for item in _items(board, lane)}


def _order(**kwargs):
    base = {
        "number": "SO-1000",
        "customerName": "Prairie Door Co",
        "status": "Open",
        "fullyShipped": False,
    }
    base.update(kwargs)
    return base


def _board(records, config=None, today=TODAY, now=NOW):
    return build_board(records, today=today, now=now, config=config or default_lane_config())


class TestLaneMapping:
    def test_pickup_delivery_and_production_use_real_dates_only(self):
        board = _board({
            "sales_orders": [
                _order(
                    number="SO-1001",
                    customerName="Prairie Door Co",
                    shipmentMethodCode="PICKUP",
                    requestedDeliveryDate="2026-11-12T10:30:00",
                    orderDate="2026-01-01",
                ),
                _order(
                    number="SO-1002",
                    customerName="North Hill",
                    shipmentMethodCode="TRUCK",
                    promisedDeliveryDate="2026-11-13",
                    shipToName="North Hill",
                    shipToAddressLine1="4500 Rochdale Blvd",
                    shipToCity="Regina",
                    shipToState="SK",
                ),
                _order(
                    number="SO-1003",
                    customerName="Mystery Method",
                    shipmentMethodCode="COUNTER",
                    requestedDeliveryDate="2026-11-12",
                ),
                _order(
                    number="SO-1004",
                    customerName="Guid Method",
                    shipmentMethodId="11111111-1111-1111-1111-111111111111",
                    shipmentMethodCode="11111111-1111-1111-1111-111111111111",
                    requestedDeliveryDate="2026-11-12",
                ),
                _order(
                    number="SO-1005",
                    customerName="Agent Only",
                    shippingAgentCode="PUROLATOR",
                    requestedDeliveryDate="2026-11-12",
                ),
                _order(
                    number="SO-1006",
                    customerName="Empty Date",
                    shipmentMethodCode="PICKUP",
                    requestedDeliveryDate="0001-01-01",
                    orderDate="2026-11-12",
                ),
            ],
            "production_orders": [
                {
                    "order_no": "PROD-1",
                    "sales_order_no": "SO-1001",
                    "status": "Released",
                    "due_date": "2026-11-12",
                    "description": "16x7 insulated",
                },
                {
                    "order_no": "PROD-2",
                    "sales_order_no": "SO-2000",
                    "status": "Finished",
                    "due_date": "2026-11-12",
                    "description": "done",
                },
                {
                    "order_no": "PROD-3",
                    "sales_order_no": "SO-2001",
                    "status": "Released",
                    "description": "no date",
                },
            ],
        })
        pickups = _by_number(board, "pickups")
        deliveries = _by_number(board, "deliveries")
        production = _by_number(board, "production")

        assert set(pickups) == {"SO-1001"}
        assert pickups["SO-1001"]["time"] == "10:30"
        assert pickups["SO-1001"]["when_label"] == "Requested"
        assert pickups["SO-1001"]["date"] == "2026-11-12"

        assert set(deliveries) == {"SO-1002"}
        assert deliveries["SO-1002"]["destination"] == "4500 Rochdale Blvd, Regina, SK"
        assert deliveries["SO-1002"]["when_label"] == "Promised"
        assert "North Hill" not in deliveries["SO-1002"]["destination"]

        assert "SO-1003" not in pickups and "SO-1003" not in deliveries
        assert "SO-1004" not in pickups and "SO-1004" not in deliveries
        assert "SO-1005" not in deliveries
        assert "SO-1006" not in pickups
        assert board["omitted"]["no_date"] >= 1
        assert board["omitted"]["unmapped_shipment"] >= 3

        assert set(production) == {"SO-1001"}
        assert production["SO-1001"]["when_label"] == "Build"
        assert production["SO-1001"]["detail"] == "16x7 insulated"
        assert production["SO-1001"]["date"] == "2026-11-12"

    def test_order_date_and_scheduled_date_alone_stay_off_the_board(self):
        board = _board({
            "sales_orders": [
                _order(number="SO-3001", orderDate="2026-11-12", shipmentMethodCode="PICKUP"),
            ],
            "sales_order_master": [
                {"Sales_Order_No": "SO-3002", "Status": "Unscheduled", "Prodn_Order_No": "PROD-9"},
            ],
            "scheduled_dates": {"SO-3003": "2026-11-12"},
        })
        assert _items(board, "pickups") == []
        assert _items(board, "production") == []
        assert board["omitted"]["no_date"] >= 1

    def test_master_unscheduled_uses_portal_scheduled_date_not_order_date(self):
        board = _board({
            "sales_orders": [
                _order(number="SO-3002", orderDate="2026-01-01", customerName="Glenview School"),
            ],
            "sales_order_master": [
                {"Sales_Order_No": "SO-3002", "Status": "Unscheduled"},
            ],
            "scheduled_dates": {"SO-3002": "2026-11-14"},
        })
        item = _by_number(board, "production")["SO-3002"]
        assert item["date"] == "2026-11-14"
        assert item["when_label"] == "Scheduled"
        assert item["customer"] == "Glenview School"

    def test_configurable_codes_and_shipping_agent(self):
        config = default_lane_config()
        config["pickup_shipment_methods"] = ["COUNTER"]
        config["delivery_shipment_methods"] = ["VAN"]
        config["delivery_shipping_agents"] = ["PUROLATOR"]
        board = _board({
            "sales_orders": [
                _order(number="SO-4001", shipmentMethodCode="PICKUP", requestedDeliveryDate="2026-11-12"),
                _order(number="SO-4002", shipmentMethodCode="COUNTER", requestedDeliveryDate="2026-11-12"),
                _order(number="SO-4003", shippingAgentCode="PUROLATOR", requestedDeliveryDate="2026-11-13"),
            ],
        }, config=config)
        assert set(_by_number(board, "pickups")) == {"SO-4002"}
        assert set(_by_number(board, "deliveries")) == {"SO-4003"}

    def test_two_jobs_use_the_earliest_due_date(self):
        board = _board({
            "production_orders": [
                {"order_no": "PROD-A", "sales_order_no": "SO-5001", "status": "Released", "due_date": "2026-11-15", "description": "A"},
                {"order_no": "PROD-B", "sales_order_no": "SO-5001", "status": "Firm Planned", "due_date": "2026-11-13", "description": "B"},
            ],
        })
        item = _by_number(board, "production")["SO-5001"]
        assert item["date"] == "2026-11-13"
        assert item["detail"] == "2 jobs"

    def test_line_shipment_date_and_midnight_has_no_invented_time(self):
        board = _board({
            "sales_orders": [
                _order(
                    number="SO-6001",
                    shipmentMethodCode="DELIVERY",
                    requestedDeliveryDate="0001-01-01T00:00:00Z",
                    salesOrderLines=[{"shipmentDate": "2026-11-16T00:00:00"}],
                ),
            ],
        })
        item = _by_number(board, "deliveries")["SO-6001"]
        assert item["date"] == "2026-11-16"
        assert item["time"] is None
        assert item["when_label"] == "Delivery"

    def test_draft_and_shipped_stay_off_outbound_lanes(self):
        board = _board({
            "sales_orders": [
                _order(number="SO-7001", status="Draft", shipmentMethodCode="PICKUP", requestedDeliveryDate="2026-11-12"),
                _order(number="SO-7002", fullyShipped=True, shipmentMethodCode="TRUCK", requestedDeliveryDate="2026-11-12"),
            ],
            "production_orders": [
                {"order_no": "PROD-7", "sales_order_no": "SO-7001", "status": "Released", "due_date": "2026-11-12"},
            ],
        })
        assert _items(board, "pickups") == []
        assert _items(board, "deliveries") == []
        assert "SO-7001" in _by_number(board, "production")

    def test_outlook_stub_adds_nothing(self):
        source = OutlookShippingCalendarSource()
        status = source.status()
        fetched = source.fetch()
        assert status["available"] is False
        assert status["configured"] is False
        assert status["mailbox"] == "shipping@opendc.ca"
        assert fetched["orders"] == []
        assert fetched["production_orders"] == []
        board = _board({"sales_orders": fetched["orders"], "production_orders": fetched["production_orders"]})
        assert _items(board, "pickups") == []
        assert _items(board, "deliveries") == []
        assert _items(board, "production") == []


class TestDateGroupingAndOverdue:
    def test_today_plus_seven_groups_and_later_days_drop(self):
        board = _board({
            "sales_orders": [
                _order(number="SO-Y", shipmentMethodCode="PICKUP", requestedDeliveryDate="2026-11-11T15:00:00"),
                _order(number="SO-T", shipmentMethodCode="PICKUP", requestedDeliveryDate="2026-11-12T10:00:00"),
                _order(number="SO-L", shipmentMethodCode="PICKUP", requestedDeliveryDate="2026-11-12T16:00:00"),
                _order(number="SO-N", shipmentMethodCode="PICKUP", requestedDeliveryDate="2026-11-12"),
                _order(number="SO-E", shipmentMethodCode="PICKUP", requestedDeliveryDate="2026-11-19"),
                _order(number="SO-X", shipmentMethodCode="PICKUP", requestedDeliveryDate="2026-11-20"),
            ],
        })
        days = board["lanes"]["pickups"]["days"]
        assert days[0]["label"] == "Overdue"
        assert days[0]["overdue"] is True
        assert days[0]["date"] == "2026-11-11"
        today = next(day for day in days if day["is_today"])
        assert today["label"] == "Today"
        assert today["date"] == "2026-11-12"
        numbers = {item["order_number"] for day in days for item in day["items"]}
        assert numbers == {"SO-Y", "SO-T", "SO-L", "SO-N", "SO-E"}
        assert "SO-X" not in numbers
        assert board["omitted"]["outside_window"] == 1
        assert board["window_end"] == "2026-11-19"

        by_number = _by_number(board, "pickups")
        assert by_number["SO-Y"]["overdue"] is True
        assert by_number["SO-Y"]["late"] is False
        assert by_number["SO-T"]["late"] is True
        assert by_number["SO-T"]["overdue"] is False
        assert by_number["SO-L"]["late"] is False
        assert by_number["SO-N"]["late"] is False
        assert by_number["SO-N"]["time"] is None

    def test_today_is_present_when_the_lane_is_empty(self):
        board = _board({"sales_orders": []})
        days = board["lanes"]["deliveries"]["days"]
        assert len(days) == 1
        assert days[0]["is_today"] is True
        assert days[0]["items"] == []


@pytest.fixture
def client():
    engine = create_engine(
        "sqlite://",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    for table in (User.__table__, AppSettings.__table__, ShopTvKioskToken.__table__):
        table.create(engine, checkfirst=True)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = Session()
    db.add(User(
        email="joey@opendc.ca",
        password_hash=AuthService.get_password_hash("test123"),
        name="Joey",
        role=UserRole.ADMIN,
        is_active=True,
        user_type="INTERNAL",
    ))
    db.add(User(
        email="desk@opendc.ca",
        password_hash=AuthService.get_password_hash("test123"),
        name="Desk",
        role=UserRole.CONFIGURATOR,
        is_active=True,
        user_type="INTERNAL",
    ))
    db.add(User(
        email="dealer@example.com",
        password_hash=AuthService.get_password_hash("test123"),
        name="Dealer",
        role=UserRole.VIEWER,
        is_active=True,
        user_type="CUSTOMER",
    ))
    db.commit()
    db.close()

    def _override():
        scoped = Session()
        try:
            yield scoped
        finally:
            scoped.close()

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[database_get_db] = _override
    test_client = TestClient(app)
    test_client.session_factory = Session
    return test_client


def _token_for(client, email, user_type=None):
    db = client.session_factory()
    try:
        user = db.query(User).filter(User.email == email).one()
        data = {"sub": str(user.id)}
        if user_type:
            data["user_type"] = user_type
        return AuthService.create_access_token(data)
    finally:
        db.close()


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _enable(client):
    admin = _token_for(client, "joey@opendc.ca")
    response = client.put(
        "/api/shop-tv/settings",
        headers=_auth(admin),
        json={
            "mode": "on",
            "pickup_shipment_methods": ["PICKUP"],
            "delivery_shipment_methods": ["TRUCK"],
            "pickup_shipping_agents": [],
            "delivery_shipping_agents": [],
            "shipping_agent_means_delivery": False,
        },
    )
    assert response.status_code == 200, response.text
    return admin


class TestShopTvAuthAndFlag:
    def test_permission_leaves_the_board_open_for_the_route_to_decide(self):
        assert permission_for("GET", "/api/shop-tv/board") is None
        assert permission_for("GET", "/api/shop-tv/enabled") is None
        assert permission_for("GET", "/api/shop-tv/board?kiosk=stv_secret") is None
        assert permission_for("PUT", "/api/shop-tv/settings") == ("perm", "users.manage")
        assert permission_for("POST", "/api/shop-tv/kiosk-tokens") == ("perm", "users.manage")
        assert permission_for("POST", "/api/shop-tv/kiosk-tokens/4/revoke") == ("perm", "users.manage")

    def test_flag_off_is_404_with_or_without_a_token(self, client, monkeypatch):
        called = []
        monkeypatch.setattr(
            "app.api.shop_tv.assemble_board",
            lambda db, now=None: called.append(True) or {"lanes": {}},
        )
        assert client.get("/api/shop-tv/board").status_code == 404
        admin = _token_for(client, "joey@opendc.ca")
        assert client.get("/api/shop-tv/board", headers=_auth(admin)).status_code == 404
        assert client.get("/api/shop-tv/enabled", headers=_auth(admin)).status_code == 404
        db = client.session_factory()
        try:
            user = db.query(User).filter(User.email == "joey@opendc.ca").one()
            _row, plaintext = create_token(db, name="Floor TV", created_by_user_id=user.id)
        finally:
            db.close()
        flagged = client.get("/api/shop-tv/board", headers={"X-Shop-Tv-Token": plaintext})
        assert flagged.status_code == 404
        assert called == []

    def test_no_token_is_401_and_revoked_token_is_rejected(self, client, monkeypatch):
        monkeypatch.setattr(
            "app.api.shop_tv.assemble_board",
            lambda db, now=None: {"lanes": {"pickups": {"days": []}}, "marker": "board"},
        )
        _enable(client)
        missing = client.get("/api/shop-tv/board")
        assert missing.status_code == 401
        assert "board" not in missing.text

        admin = _token_for(client, "joey@opendc.ca")
        created = client.post(
            "/api/shop-tv/kiosk-tokens",
            headers=_auth(admin),
            json={"name": "Shop floor"},
        )
        assert created.status_code == 201, created.text
        plaintext = created.json()["token"]
        assert created.json()["path"] == f"/shop-tv?kiosk={plaintext}"
        assert created.json()["scope"] == "shop_tv:read"

        listed = client.get("/api/shop-tv/settings", headers=_auth(admin))
        assert listed.status_code == 200
        assert plaintext not in listed.text
        assert "key_hash" not in listed.text

        ok = client.get("/api/shop-tv/board", params={"kiosk": plaintext})
        assert ok.status_code == 200, ok.text
        assert "lanes" in ok.json()

        header_ok = client.get("/api/shop-tv/board", headers={"X-Shop-Tv-Token": plaintext})
        assert header_ok.status_code == 200

        settings = client.put(
            "/api/shop-tv/settings",
            headers={"X-Shop-Tv-Token": plaintext},
            json={"mode": "off", "pickup_shipment_methods": [], "delivery_shipment_methods": []},
        )
        assert settings.status_code == 401
        as_bearer = client.post(
            "/api/shop-tv/kiosk-tokens",
            headers=_auth(plaintext),
            json={"name": "nope"},
        )
        assert as_bearer.status_code == 401

        token_id = created.json()["id"]
        revoked = client.post(f"/api/shop-tv/kiosk-tokens/{token_id}/revoke", headers=_auth(admin))
        assert revoked.status_code == 200
        assert revoked.json()["status"] == "revoked"

        rejected = client.get("/api/shop-tv/board", headers={"X-Shop-Tv-Token": plaintext})
        assert rejected.status_code == 403
        assert rejected.json()["detail"] == "Kiosk token revoked"
        assert "lanes" not in rejected.text

    def test_staff_can_read_and_other_logins_cannot(self, client, monkeypatch):
        monkeypatch.setattr(
            "app.api.shop_tv.assemble_board",
            lambda db, now=None: {"lanes": {"production": {"days": []}}},
        )
        _enable(client)
        admin = _token_for(client, "joey@opendc.ca")
        assert client.get("/api/shop-tv/board", headers=_auth(admin)).status_code == 200
        desk = _token_for(client, "desk@opendc.ca")
        assert client.get("/api/shop-tv/board", headers=_auth(desk)).status_code == 403
        dealer = _token_for(client, "dealer@example.com", user_type="customer")
        assert client.get("/api/shop-tv/board", headers=_auth(dealer)).status_code == 403

    def test_revoke_helper_is_idempotent(self, client):
        db = client.session_factory()
        try:
            user = db.query(User).filter(User.email == "joey@opendc.ca").one()
            row, _plaintext = create_token(db, name="Once", created_by_user_id=user.id)
            assert revoke_token(db, token_id=row.id, revoked_by_user_id=user.id).status == "revoked"
            assert revoke_token(db, token_id=row.id, revoked_by_user_id=user.id).status == "revoked"
            assert db.query(ShopTvKioskToken).one().status == "revoked"
        finally:
            db.close()
