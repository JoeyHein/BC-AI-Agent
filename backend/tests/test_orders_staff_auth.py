"""Sales orders and the other staff reads that were open to the internet.

Unauthenticated calls are 401. A staff login and a valid service key can
read orders. The service key can also read the new-sales-order purchase
preview and the vendor list, and it still cannot send email or change settings.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.api import auth as auth_api
from app.api import analytics, chat, feedback, inventory, orders, settings
from app.api.purchasing import get_db as purchasing_get_db
from app.api.purchasing import router as purchasing_router
from app.api.staff_service_key_middleware import staff_service_key_middleware
from app.db.database import get_db as database_get_db
from app.db.models import (
    AppSettings,
    OrderViewState,
    QuoteRequest,
    StaffServiceKey,
    StaffServiceKeyAudit,
    User,
    UserRole,
)
from app.services import staff_service_keys_service as staff_keys
from app.services.auth_service import AuthService, auth_service
from app.services.staff_service_keys_service import create_key


def _sample_order():
    return {
        "id": "guid-1",
        "number": "SO-001299",
        "customerId": "c1",
        "customerName": "Acme Doors",
        "status": "Open",
        "totalAmountIncludingTax": 1200.5,
        "orderDate": "2026-10-01",
        "requestedDeliveryDate": None,
        "externalDocumentNumber": "JOB-9",
        "shipmentMethodCode": "TRUCK",
        "salesperson": "Joey",
        "lastModifiedDateTime": "2026-10-01T12:00:00Z",
    }


@pytest.fixture
def client(monkeypatch):
    engine = create_engine(
        "sqlite://",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    for table in (
        User.__table__,
        OrderViewState.__table__,
        AppSettings.__table__,
        QuoteRequest.__table__,
        StaffServiceKey.__table__,
        StaffServiceKeyAudit.__table__,
    ):
        table.create(engine, checkfirst=True)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    db = Session()
    db.add(
        User(
            email="joey@opendc.ca",
            password_hash=AuthService.get_password_hash("test123"),
            name="Joey",
            role=UserRole.ADMIN,
            is_active=True,
            user_type="INTERNAL",
        )
    )
    db.add(
        User(
            email="viewer@opendc.ca",
            password_hash=AuthService.get_password_hash("test123"),
            name="Viewer",
            role=UserRole.VIEWER,
            is_active=True,
            user_type="INTERNAL",
        )
    )
    db.add(
        User(
            email="dealer@example.com",
            password_hash=AuthService.get_password_hash("test123"),
            name="Dealer",
            role=UserRole.VIEWER,
            is_active=True,
            user_type="CUSTOMER",
        )
    )
    db.commit()
    db.close()

    def new_session():
        return Session()

    monkeypatch.setattr(staff_keys, "new_session", new_session)
    monkeypatch.setattr(
        orders.bc_client,
        "get_sales_orders",
        lambda top=100, status_filter=None, **kwargs: [_sample_order()],
    )
    monkeypatch.setattr(
        "app.api.purchasing.purchasing_po_service.preview_complete_so_po",
        lambda so_number, vendor_no="UPW", vendor_name="UPWARDOR": {
            "so_number": so_number,
            "dry_run": True,
            "lines": [{"item_no": "PN10", "quantity": 2}],
            "bc_po_number": None,
        },
    )
    monkeypatch.setattr(
        "app.api.purchasing.bc_client.get_vendors",
        lambda top=500, **kwargs: [
            {"number": "UPW", "displayName": "UPWARDOR"},
            {"number": "", "displayName": "skip me"},
        ],
    )
    monkeypatch.setattr(
        "app.api.inventory.bc_inventory_service.get_inventory_levels",
        lambda **kwargs: [{"itemNumber": "PN10", "inventory": 4}],
    )

    def _override():
        scoped = Session()
        try:
            yield scoped
        finally:
            scoped.close()

    app = FastAPI()
    app.middleware("http")(staff_service_key_middleware)
    app.include_router(auth_api.router)
    app.include_router(orders.router)
    app.include_router(purchasing_router)
    app.include_router(settings.router)
    app.include_router(analytics.router)
    app.include_router(inventory.router)
    app.include_router(inventory.portal_router)
    app.include_router(feedback.router)
    app.include_router(chat.router)

    app.dependency_overrides[database_get_db] = _override
    app.dependency_overrides[auth_api.get_db] = _override
    app.dependency_overrides[purchasing_get_db] = _override
    app.dependency_overrides[feedback.get_db] = _override
    return TestClient(app)


def _login(client: TestClient, email: str, password: str = "test123") -> str:
    response = client.post("/api/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


class TestOrderRoutesRequireStaff:
    def test_anonymous_order_lists_are_401(self, client):
        orders_res = client.get("/api/orders")
        bc_res = client.get("/api/orders/bc/orders")
        assert orders_res.status_code == 401
        assert bc_res.status_code == 401
        assert "Acme" not in orders_res.text
        assert "Acme" not in bc_res.text

    def test_staff_login_can_read_orders(self, client):
        token = _login(client, "joey@opendc.ca")
        orders_res = client.get("/api/orders", headers=_auth(token))
        bc_res = client.get("/api/orders/bc/orders", headers=_auth(token))
        assert orders_res.status_code == 200, orders_res.text
        assert bc_res.status_code == 200, bc_res.text
        assert orders_res.json()["orders"][0]["customer_name"] == "Acme Doors"
        assert bc_res.json()["orders"][0]["customerName"] == "Acme Doors"

        viewer = _login(client, "viewer@opendc.ca")
        viewer_res = client.get("/api/orders", headers=_auth(viewer))
        assert viewer_res.status_code == 200, viewer_res.text

    def test_customer_login_cannot_read_staff_orders(self, client):
        # Customer tokens carry user_type=customer. They must not see every order.
        session = staff_keys.new_session()
        try:
            dealer = session.query(User).filter(User.email == "dealer@example.com").one()
            token = auth_service.create_access_token(
                data={"sub": str(dealer.id), "user_type": "customer"}
            )
        finally:
            session.close()
        res = client.get("/api/orders", headers=_auth(token))
        assert res.status_code == 403
        assert "Acme" not in res.text

    def test_service_key_can_read_orders(self, client):
        session = staff_keys.new_session()
        try:
            admin = session.query(User).filter(User.email == "joey@opendc.ca").one()
            _row, plaintext = create_key(session, name="Hourly PO check", created_by_user_id=admin.id)
        finally:
            session.close()

        orders_res = client.get("/api/orders", headers=_auth(plaintext))
        bc_res = client.get("/api/orders/bc/orders", headers=_auth(plaintext))
        assert orders_res.status_code == 200, orders_res.text
        assert bc_res.status_code == 200, bc_res.text
        assert orders_res.json()["count"] == 1
        assert bc_res.json()["orders"][0]["number"] == "SO-001299"

    def test_service_key_can_preview_and_list_vendors_but_not_email_or_settings(self, client):
        session = staff_keys.new_session()
        try:
            admin = session.query(User).filter(User.email == "joey@opendc.ca").one()
            _row, plaintext = create_key(session, name="Hourly PO check", created_by_user_id=admin.id)
        finally:
            session.close()
        headers = _auth(plaintext)

        preview = client.get(
            "/api/admin/purchasing/so-complete-po/preview",
            params={"so_number": "1299"},
            headers=headers,
        )
        assert preview.status_code == 200, preview.text
        assert preview.json()["dry_run"] is True
        assert preview.json()["bc_po_number"] is None

        vendors = client.get("/api/admin/purchasing/vendors", headers=headers)
        assert vendors.status_code == 200, vendors.text
        assert vendors.json()["vendors"] == [{"number": "UPW", "name": "UPWARDOR"}]

        send_email = client.post("/api/admin/purchasing/send-report", headers=headers, json={})
        assert send_email.status_code == 403
        assert "not allowed" in send_email.json()["detail"].lower()

        create_po = client.post(
            "/api/admin/purchasing/so-complete-po",
            headers=headers,
            json={"so_number": "1299"},
        )
        assert create_po.status_code == 403

        settings_res = client.put(
            "/api/settings/pricing-tiers",
            headers=headers,
            json={"margins": {}},
        )
        assert settings_res.status_code == 403
        assert "not allowed" in settings_res.json()["detail"].lower()

        # A staff person can still open pricing settings.
        staff = _login(client, "joey@opendc.ca")
        pricing = client.get("/api/settings/pricing-tiers/current", headers=_auth(staff))
        assert pricing.status_code == 200, pricing.text
        assert pricing.json()["success"] is True


class TestOtherOpenBusinessRoutes:
    """Same lock on staff pages that were also reachable with no login."""

    @pytest.mark.parametrize(
        "path",
        [
            "/api/settings/pricing-tiers/current",
            "/api/analytics/dashboard/summary",
            "/api/inventory/levels",
            "/inventory/levels",
            "/api/quotes/pending-review",
            "/api/chat/conversations",
        ],
    )
    def test_anonymous_is_401(self, client, path):
        res = client.get(path)
        assert res.status_code == 401, path

    def test_service_key_can_still_read_inventory_and_quote_queue(self, client):
        session = staff_keys.new_session()
        try:
            admin = session.query(User).filter(User.email == "joey@opendc.ca").one()
            _row, plaintext = create_key(session, name="Hourly PO check", created_by_user_id=admin.id)
        finally:
            session.close()
        headers = _auth(plaintext)

        levels = client.get("/api/inventory/levels", headers=headers)
        assert levels.status_code == 200, levels.text
        assert levels.json()["count"] == 1

        queue = client.get("/api/quotes/pending-review", headers=headers)
        assert queue.status_code == 200, queue.text
        assert queue.json() == []

    def test_staff_login_is_not_blocked_on_the_other_locked_pages(self, client):
        headers = _auth(_login(client, "joey@opendc.ca"))
        for path in (
            "/api/settings/pricing-tiers/current",
            "/api/inventory/levels",
            "/api/quotes/pending-review",
            "/api/analytics/dashboard/summary",
            "/api/chat/conversations",
        ):
            res = client.get(path, headers=headers)
            assert res.status_code not in (401, 403), (path, res.status_code, res.text)
