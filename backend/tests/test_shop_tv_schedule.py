"""Manual shop schedule entries.

Typed rows fill the lanes Business Central leaves empty. Done rows and
dates past the window stay off. The same sales order and lane from
Business Central is hidden. A kiosk token cannot change the list.
"""
from __future__ import annotations

import sys
from datetime import date, datetime, time
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
from app.db.models import AppSettings, ShopScheduleEntry, ShopTvKioskToken, StaffServiceKey, User, UserRole
from app.services.auth_service import AuthService
from app.services.shop_tv_board import build_board, default_lane_config
from app.services.shop_tv_schedule import apply_schedule_entries
from app.services.staff_service_keys_service import AUTOMATION_SCOPES, SHOP_TV_SCHEDULE, create_key

TODAY = date(2026, 11, 16)
NOW = datetime(2026, 11, 16, 15, 0)


def _items(board, lane):
    rows = []
    for day in board["lanes"][lane]["days"]:
        rows.extend(day["items"])
    return rows


def _by_number(board, lane):
    return {item["order_number"]: item for item in _items(board, lane)}


def _order(**kwargs):
    base = {
        "number": "SO-1001",
        "customerName": "Prairie Door Co",
        "status": "Open",
        "fullyShipped": False,
        "shipmentMethodCode": "PICKUP",
        "requestedDeliveryDate": "2026-11-16T10:30:00",
    }
    base.update(kwargs)
    return base


def _bc_board():
    return build_board(
        {
            "sales_orders": [
                _order(number="SO-1001", shipmentMethodCode="PICKUP"),
                _order(
                    number="SO-1002",
                    customerName="North Hill",
                    shipmentMethodCode="TRUCK",
                    promisedDeliveryDate="2026-11-17",
                    requestedDeliveryDate=None,
                ),
            ],
            "scheduled_dates": {"SO-1001": "2026-11-16"},
        },
        today=TODAY,
        now=NOW,
        config=default_lane_config(),
    )


def _entry(**kwargs):
    base = {
        "id": 1,
        "so_number": "SO-1001",
        "customer_name": "Prairie Door Co",
        "lane": "pickup",
        "date": TODAY,
        "time": time(9, 0),
        "note": "ready for install Mon Nov 23",
        "done": False,
    }
    base.update(kwargs)
    return base


class TestScheduleMerge:
    def test_manual_row_replaces_the_same_sales_order_and_lane(self):
        board = apply_schedule_entries(_bc_board(), [_entry()], now=NOW)
        pickups = _by_number(board, "pickups")
        assert set(pickups) == {"SO-1001"}
        row = pickups["SO-1001"]
        assert row["manual"] is True
        assert row["id"] == "manual:1"
        assert row["note"] == "ready for install Mon Nov 23"
        assert row["time"] == "09:00"
        assert row["when_label"] == "Pickup"
        assert row["late"] is True
        assert row["overdue"] is False
        production = _by_number(board, "production")
        assert production["SO-1001"].get("manual") is not True
        assert "SO-1002" in _by_number(board, "deliveries")

    def test_delivery_entry_does_not_hide_the_pickup(self):
        board = apply_schedule_entries(
            _bc_board(),
            [_entry(id=2, lane="delivery", note="on the truck")],
            now=NOW,
        )
        assert _by_number(board, "pickups")["SO-1001"].get("manual") is not True
        deliveries = _by_number(board, "deliveries")
        assert deliveries["SO-1001"]["manual"] is True
        assert deliveries["SO-1001"]["note"] == "on the truck"
        assert deliveries["SO-1002"].get("manual") is not True

    def test_case_insensitive_sales_order_hides_the_business_central_row(self):
        board = apply_schedule_entries(
            _bc_board(),
            [_entry(so_number="so-1001")],
            now=NOW,
        )
        row = _by_number(board, "pickups")["SO-1001"]
        assert row["manual"] is True

    def test_done_and_outside_the_window_stay_off(self):
        board = apply_schedule_entries(
            _bc_board(),
            [
                _entry(id=3, done=True, note="finished"),
                _entry(id=4, so_number="SO-1099", date=date(2026, 11, 30), note="too far"),
                _entry(id=5, so_number="SO-1008", date=date(2026, 11, 10), time=None, note="partial receipt"),
            ],
            now=NOW,
        )
        pickups = _items(board, "pickups")
        notes = [item.get("note") for item in pickups]
        assert "finished" not in notes
        assert "too far" not in notes
        overdue = _by_number(board, "pickups")["SO-1008"]
        assert overdue["overdue"] is True
        assert overdue["late"] is False
        assert overdue["note"] == "partial receipt"
        assert _by_number(board, "pickups")["SO-1001"].get("manual") is not True

    def test_later_today_is_not_late(self):
        board = apply_schedule_entries(
            {"today": TODAY.isoformat(), "horizon_days": 7, "lanes": {}},
            [_entry(time=time(16, 30), so_number=None, customer_name="Walk-in")],
            now=NOW,
        )
        row = _items(board, "pickups")[0]
        assert row["late"] is False
        assert row["order_number"] == "—"
        assert row["customer"] == "Walk-in"
        assert row["time"] == "16:30"

    def test_receiving_goes_in_incoming_and_hides_the_linked_purchase_order(self):
        board = {
            "today": TODAY.isoformat(),
            "horizon_days": 7,
            "lanes": {
                "incoming": {
                    "days": [{
                        "date": TODAY.isoformat(),
                        "label": "Today",
                        "is_today": True,
                        "overdue": False,
                        "items": [{
                            "id": "incoming:PO-000100",
                            "lane": "incoming",
                            "order_number": "PO-000100",
                            "customer": "Upwardor",
                            "date": TODAY.isoformat(),
                            "time": None,
                            "sales_orders": [{"number": "SO-1001", "customer": "Prairie Door Co"}],
                            "manual": False,
                        }],
                    }],
                },
            },
        }
        merged = apply_schedule_entries(
            board,
            [_entry(id=8, lane="receiving", note="partial receipt", time=None)],
            now=NOW,
        )
        rows = _items(merged, "incoming")
        assert [row["order_number"] for row in rows] == ["SO-1001"]
        assert rows[0]["manual"] is True
        assert rows[0]["note"] == "partial receipt"
        assert rows[0]["when_label"] == "Receiving"
        assert "PO-000100" not in [row["order_number"] for row in rows]


@pytest.fixture
def client():
    engine = create_engine(
        "sqlite://",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    for table in (
        User.__table__,
        AppSettings.__table__,
        ShopScheduleEntry.__table__,
        ShopTvKioskToken.__table__,
        StaffServiceKey.__table__,
    ):
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
        email="sales@opendc.ca",
        password_hash=AuthService.get_password_hash("test123"),
        name="Sales",
        role=UserRole.SALES,
        is_active=True,
        user_type="INTERNAL",
    ))
    db.add(User(
        email="shop@opendc.ca",
        password_hash=AuthService.get_password_hash("test123"),
        name="Shop",
        role=UserRole.WAREHOUSE,
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


def _token_for(client, email):
    db = client.session_factory()
    try:
        user = db.query(User).filter(User.email == email).one()
        return AuthService.create_access_token({"sub": str(user.id)})
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
        },
    )
    assert response.status_code == 200, response.text
    return admin


def _board_snapshot():
    return {
        "today": TODAY.isoformat(),
        "horizon_days": 7,
        "lanes": {
            "production": {
                "days": [{
                    "date": TODAY.isoformat(),
                    "label": "Today",
                    "is_today": True,
                    "overdue": False,
                    "items": [{
                        "id": "production:SO-1001",
                        "lane": "production",
                        "order_number": "SO-1001",
                        "customer": "Prairie Door Co",
                        "date": TODAY.isoformat(),
                        "time": None,
                        "manual": False,
                    }],
                }],
            },
            "pickups": {
                "days": [{
                    "date": TODAY.isoformat(),
                    "label": "Today",
                    "is_today": True,
                    "overdue": False,
                    "items": [{
                        "id": "pickups:SO-1001",
                        "lane": "pickups",
                        "order_number": "SO-1001",
                        "customer": "From BC",
                        "date": TODAY.isoformat(),
                        "time": "10:30",
                        "manual": False,
                    }],
                }],
            },
            "deliveries": {"days": []},
        },
    }


class TestScheduleApi:
    def test_flag_off_is_404(self, client):
        assert client.get("/api/shop-tv/entries").status_code == 404
        admin = _token_for(client, "joey@opendc.ca")
        created = client.post(
            "/api/shop-tv/entries",
            headers=_auth(admin),
            json={"lane": "pickup", "date": "2026-11-16", "note": "nope"},
        )
        assert created.status_code == 404
        db = client.session_factory()
        try:
            assert db.query(ShopScheduleEntry).count() == 0
        finally:
            db.close()

    def test_sales_and_shop_can_write_and_a_configurator_cannot(self, client, monkeypatch):
        monkeypatch.setattr(
            "app.services.shop_tv_schedule.lookup_bc_customer_name",
            lambda number: "Prairie Door Co",
        )
        _enable(client)
        sales = _token_for(client, "sales@opendc.ca")
        created = client.post(
            "/api/shop-tv/entries",
            headers=_auth(sales),
            json={
                "so_number": "so-001278",
                "lane": "pickup",
                "date": "2026-11-16",
                "time": "09:15",
                "note": "ready for install Mon Nov 23",
            },
        )
        assert created.status_code == 201, created.text
        body = created.json()
        assert body["so_number"] == "SO-001278"
        assert body["customer_name"] == "Prairie Door Co"
        assert body["time"] == "09:15"
        assert body["done"] is False
        assert body["created_by"]

        shop = _token_for(client, "shop@opendc.ca")
        listed = client.get("/api/shop-tv/entries", headers=_auth(shop))
        assert listed.status_code == 200
        assert listed.json()["entries"][0]["note"] == "ready for install Mon Nov 23"

        desk = _token_for(client, "desk@opendc.ca")
        denied = client.post(
            "/api/shop-tv/entries",
            headers=_auth(desk),
            json={"lane": "pickup", "date": "2026-11-16"},
        )
        assert denied.status_code == 403
        settings = client.put(
            "/api/shop-tv/settings",
            headers=_auth(sales),
            json={"mode": "on"},
        )
        assert settings.status_code == 403

    def test_customer_name_is_kept_and_a_bc_miss_still_saves(self, client, monkeypatch):
        calls = {"n": 0}

        def _lookup(number):
            calls["n"] += 1
            raise AssertionError(number)

        monkeypatch.setattr("app.services.shop_tv_schedule.lookup_bc_customer_name", _lookup)
        admin = _enable(client)
        kept = client.post(
            "/api/shop-tv/entries",
            headers=_auth(admin),
            json={
                "so_number": "SO-001278",
                "customer_name": "North Hill",
                "lane": "delivery",
                "date": "2026-11-17",
            },
        )
        assert kept.status_code == 201, kept.text
        assert kept.json()["customer_name"] == "North Hill"
        assert calls["n"] == 0

        def _missing(number):
            calls["n"] += 1
            return None

        monkeypatch.setattr("app.services.shop_tv_schedule.lookup_bc_customer_name", _missing)
        blank = client.post(
            "/api/shop-tv/entries",
            headers=_auth(admin),
            json={"so_number": "SO-009999", "lane": "production", "date": "2026-11-18"},
        )
        assert blank.status_code == 201, blank.text
        assert blank.json()["customer_name"] is None
        assert calls["n"] == 1

    def test_lookup_reads_the_sales_order_and_does_not_write(self, client, monkeypatch):
        class FakeBc:
            def __init__(self):
                self.reads = []
                self.writes = []

            def get_sales_order_by_number(self, order_number, company_id=None):
                self.reads.append(order_number)
                return {"number": order_number, "customerName": "From BC", "status": "Draft"}

            def create_sales_order(self, *args, **kwargs):
                self.writes.append("create")
                raise AssertionError("sales order write")

            def update_sales_order(self, *args, **kwargs):
                self.writes.append("update")
                raise AssertionError("sales order write")

        fake = FakeBc()
        monkeypatch.setattr("app.integrations.bc.client.bc_client", fake)
        admin = _enable(client)
        created = client.post(
            "/api/shop-tv/entries",
            headers=_auth(admin),
            json={"so_number": "SO-001278", "lane": "receiving", "date": "2026-11-16", "note": "partial receipt"},
        )
        assert created.status_code == 201, created.text
        assert created.json()["customer_name"] == "From BC"
        assert fake.reads == ["SO-001278"]
        assert fake.writes == []

    def test_edit_done_and_delete(self, client, monkeypatch):
        monkeypatch.setattr("app.services.shop_tv_schedule.lookup_bc_customer_name", lambda number: None)
        admin = _enable(client)
        created = client.post(
            "/api/shop-tv/entries",
            headers=_auth(admin),
            json={"lane": "pickup", "date": "2026-11-16", "note": "first", "customer_name": "Walk-in"},
        )
        entry_id = created.json()["id"]
        edited = client.patch(
            f"/api/shop-tv/entries/{entry_id}",
            headers=_auth(admin),
            json={"note": "second", "time": "11:00"},
        )
        assert edited.status_code == 200, edited.text
        assert edited.json()["note"] == "second"
        assert edited.json()["time"] == "11:00"
        done = client.patch(
            f"/api/shop-tv/entries/{entry_id}",
            headers=_auth(admin),
            json={"done": True},
        )
        assert done.json()["done"] is True
        assert done.json()["note"] == "second"
        listed = client.get("/api/shop-tv/entries", headers=_auth(admin))
        assert listed.json()["entries"][0]["done"] is True
        removed = client.delete(f"/api/shop-tv/entries/{entry_id}", headers=_auth(admin))
        assert removed.status_code == 200
        assert client.get("/api/shop-tv/entries", headers=_auth(admin)).json()["entries"] == []
        missing = client.delete("/api/shop-tv/entries/999", headers=_auth(admin))
        assert missing.status_code == 404

    def test_bad_lane_and_long_note_are_rejected(self, client):
        admin = _enable(client)
        bad_lane = client.post(
            "/api/shop-tv/entries",
            headers=_auth(admin),
            json={"lane": "freight", "date": "2026-11-16"},
        )
        assert bad_lane.status_code == 400
        long_note = client.post(
            "/api/shop-tv/entries",
            headers=_auth(admin),
            json={"lane": "pickup", "date": "2026-11-16", "note": "x" * 201},
        )
        assert long_note.status_code == 400

    def test_kiosk_token_cannot_read_or_write_entries(self, client, monkeypatch):
        monkeypatch.setattr("app.services.shop_tv_schedule.lookup_bc_customer_name", lambda number: None)
        admin = _enable(client)
        client.post(
            "/api/shop-tv/entries",
            headers=_auth(admin),
            json={"lane": "pickup", "date": "2026-11-16", "note": "secret note", "customer_name": "Hidden"},
        )
        created = client.post(
            "/api/shop-tv/kiosk-tokens",
            headers=_auth(admin),
            json={"name": "Floor"},
        )
        token = created.json()["token"]
        listed = client.get("/api/shop-tv/entries", headers={"X-Shop-Tv-Token": token})
        assert listed.status_code == 403
        assert listed.json()["detail"] == "Kiosk token is read-only"
        assert "secret note" not in listed.text
        posted = client.post(
            "/api/shop-tv/entries",
            headers={"X-Shop-Tv-Token": token},
            json={"lane": "pickup", "date": "2026-11-16"},
        )
        assert posted.status_code == 403
        assert client.get("/api/shop-tv/entries").status_code == 401

    def test_board_shows_the_manual_row_and_hides_done(self, client, monkeypatch):
        monkeypatch.setattr("app.services.shop_tv_schedule.lookup_bc_customer_name", lambda number: None)
        monkeypatch.setattr("app.api.shop_tv.assemble_board", lambda db, now=None: _board_snapshot())
        admin = _enable(client)
        client.post(
            "/api/shop-tv/entries",
            headers=_auth(admin),
            json={
                "so_number": "SO-1001",
                "customer_name": "Prairie Door Co",
                "lane": "pickup",
                "date": "2026-11-16",
                "note": "ready for install Mon Nov 23",
            },
        )
        client.post(
            "/api/shop-tv/entries",
            headers=_auth(admin),
            json={
                "so_number": "SO-0042",
                "customer_name": "Stock",
                "lane": "receiving",
                "date": "2026-11-10",
                "note": "partial receipt",
            },
        )
        far = client.post(
            "/api/shop-tv/entries",
            headers=_auth(admin),
            json={"lane": "production", "date": "2026-12-20", "note": "next month", "customer_name": "Later"},
        )
        board = client.get("/api/shop-tv/board", headers=_auth(admin))
        assert board.status_code == 200, board.text
        payload = board.json()
        pickups = _items(payload, "pickups")
        assert len(pickups) == 1
        assert pickups[0]["manual"] is True
        assert pickups[0]["note"] == "ready for install Mon Nov 23"
        assert pickups[0]["order_number"] == "SO-1001"
        production = _items(payload, "production")
        assert [row["order_number"] for row in production] == ["SO-1001"]
        assert production[0]["manual"] is False
        incoming = _items(payload, "incoming")
        assert incoming[0]["order_number"] == "SO-0042"
        assert incoming[0]["note"] == "partial receipt"
        assert incoming[0]["overdue"] is True
        assert incoming[0]["manual"] is True
        assert "next month" not in board.text

        client.patch(
            f"/api/shop-tv/entries/{far.json()['id']}",
            headers=_auth(admin),
            json={"date": "2026-11-16", "done": True},
        )
        again = client.get("/api/shop-tv/board", headers=_auth(admin))
        assert "Later" not in again.text

    def test_service_key_scope_reads_and_writes(self, client, monkeypatch):
        monkeypatch.setattr("app.services.shop_tv_schedule.lookup_bc_customer_name", lambda number: None)
        _enable(client)
        db = client.session_factory()
        try:
            admin = db.query(User).filter(User.email == "joey@opendc.ca").one()
            _row, schedule_key = create_key(
                db,
                name="Shop schedule",
                created_by_user_id=admin.id,
                scopes=[SHOP_TV_SCHEDULE],
            )
            _auto, automation_key = create_key(
                db,
                name="Hourly",
                created_by_user_id=admin.id,
                scopes=list(AUTOMATION_SCOPES),
            )
        finally:
            db.close()

        denied = client.get("/api/shop-tv/entries", headers=_auth(automation_key))
        assert denied.status_code == 403
        created = client.post(
            "/api/shop-tv/entries",
            headers=_auth(schedule_key),
            json={"lane": "production", "date": "2026-11-16", "note": "from the key", "customer_name": "Key Co"},
        )
        assert created.status_code == 201, created.text
        listed = client.get("/api/shop-tv/entries", headers=_auth(schedule_key))
        assert listed.status_code == 200
        assert listed.json()["entries"][0]["note"] == "from the key"
        assert SHOP_TV_SCHEDULE not in AUTOMATION_SCOPES
