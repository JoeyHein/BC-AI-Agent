"""Staff permissions: presets, closed signup, disabled logins, service keys.

The purchasing vendor list is the stand-in for purchasing. A viewer preset
cannot open it. A purchasing preset can. A staff service key still can,
because that route is on the existing allow-list. The users list is not.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.api import auth as auth_api
from app.api.purchasing import get_db as purchasing_get_db
from app.api.purchasing import router as purchasing_router
from app.api.staff_permission_middleware import staff_permission_middleware
from app.api.staff_service_key_middleware import staff_service_key_middleware
from app.db.models import StaffAccessAudit, StaffServiceKey, StaffServiceKeyAudit, User, UserRole
from app.services import staff_service_keys_service as staff_keys
from app.services.auth_service import AuthService
from app.services.staff_permissions import (
    PRESETS,
    legacy_viewer_permissions,
    permission_for,
    plan_backfill,
    redact_configurator_quote,
    redact_customer_search,
)
from app.services.staff_service_keys_service import create_key


def _engine():
    engine = create_engine(
        "sqlite://",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    for table in (
        User.__table__,
        StaffAccessAudit.__table__,
        StaffServiceKey.__table__,
        StaffServiceKeyAudit.__table__,
    ):
        table.create(engine, checkfirst=True)
    return engine


def _session_factory(engine):
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


def _user(email, role, password="test123", active=True):
    return User(
        email=email,
        password_hash=AuthService.get_password_hash(password),
        name=email.split("@")[0],
        role=role,
        is_active=active,
        user_type="INTERNAL",
        invite_pending=False,
    )


def _app(monkeypatch, Session):
    def new_session():
        return Session()

    monkeypatch.setattr(staff_keys, "new_session", new_session)
    monkeypatch.setattr(
        "app.api.purchasing.bc_client.get_vendors",
        lambda top=500, **kwargs: [{"number": "UPW", "displayName": "UPWARDOR"}],
    )

    def _override():
        scoped = Session()
        try:
            yield scoped
        finally:
            scoped.close()

    app = FastAPI()
    app.middleware("http")(staff_permission_middleware)
    app.middleware("http")(staff_service_key_middleware)
    app.include_router(auth_api.router)
    app.include_router(purchasing_router)
    app.dependency_overrides[auth_api.get_db] = _override
    app.dependency_overrides[purchasing_get_db] = _override
    return TestClient(app)


@pytest.fixture
def client(monkeypatch):
    engine = _engine()
    Session = _session_factory(engine)
    db = Session()
    db.add(_user("joey@opendc.ca", UserRole.ADMIN))
    db.add(_user("viewer@opendc.ca", UserRole.VIEWER))
    db.add(_user("buyer@opendc.ca", UserRole.PURCHASING))
    db.add(_user("config@upwardor.com", UserRole.CONFIGURATOR))
    db.add(_user("disabled@opendc.ca", UserRole.VIEWER, active=False))
    db.commit()
    db.close()
    return _app(monkeypatch, Session)


def _login(client, email, password="test123"):
    return client.post("/api/auth/login", json={"email": email, "password": password})


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


class TestPurchasingGate:
    def test_viewer_is_refused_and_purchasing_role_is_allowed(self, client):
        viewer = _login(client, "viewer@opendc.ca")
        assert viewer.status_code == 200, viewer.text
        refused = client.get("/api/admin/purchasing/vendors", headers=_auth(viewer.json()["access_token"]))
        assert refused.status_code == 403
        assert refused.json()["detail"] == "You do not have permission to do that"

        buyer = _login(client, "buyer@opendc.ca")
        assert buyer.status_code == 200, buyer.text
        allowed = client.get("/api/admin/purchasing/vendors", headers=_auth(buyer.json()["access_token"]))
        assert allowed.status_code == 200, allowed.text
        assert allowed.json()["vendors"][0]["number"] == "UPW"

        admin = _login(client, "joey@opendc.ca")
        admin_ok = client.get("/api/admin/purchasing/vendors", headers=_auth(admin.json()["access_token"]))
        assert admin_ok.status_code == 200, admin_ok.text


class TestDisabledLogin:
    def test_correct_password_is_forbidden_and_wrong_password_stays_unauthorized(self, client):
        disabled = _login(client, "disabled@opendc.ca")
        assert disabled.status_code == 403
        assert disabled.json()["detail"] == "This account is disabled."

        wrong = _login(client, "disabled@opendc.ca", password="not-the-password")
        assert wrong.status_code == 401
        assert wrong.json()["detail"] == "Incorrect email or password"


class TestClosedSignup:
    def test_first_account_is_admin_and_later_signup_is_rejected(self, monkeypatch):
        engine = _engine()
        Session = _session_factory(engine)
        client = _app(monkeypatch, Session)

        first = client.post(
            "/api/auth/register",
            json={"email": "first@opendc.ca", "password": "test1234", "name": "First"},
        )
        assert first.status_code == 200, first.text
        assert first.json()["role"] == "admin"

        second = client.post(
            "/api/auth/register",
            json={"email": "second@opendc.ca", "password": "test1234", "name": "Second"},
        )
        assert second.status_code == 403
        assert "setup link" in second.json()["detail"].lower()


class TestServiceKeyStillWorks:
    def test_allowlisted_vendors_succeed_and_users_stay_denied(self, client):
        admin = _login(client, "joey@opendc.ca")
        assert admin.status_code == 200, admin.text

        session = staff_keys.new_session()
        try:
            owner = session.query(User).filter(User.email == "joey@opendc.ca").one()
            _row, plaintext = create_key(session, name="Hourly PO check", created_by_user_id=owner.id)
            session.commit()
        finally:
            session.close()

        headers = _auth(plaintext)
        vendors = client.get("/api/admin/purchasing/vendors", headers=headers)
        assert vendors.status_code == 200, vendors.text
        assert vendors.json()["vendors"][0]["name"] == "UPWARDOR"

        users = client.get("/api/auth/users", headers=headers)
        assert users.status_code == 403
        assert "not allowed" in users.json()["detail"].lower()


class TestInvite:
    def test_invite_has_no_password_and_setup_activates_the_login(self, client, monkeypatch):
        monkeypatch.setattr(
            "app.services.notification_service.notification_service.send_email",
            lambda *args, **kwargs: False,
        )
        admin = _login(client, "joey@opendc.ca")
        headers = _auth(admin.json()["access_token"])
        rejected = client.post(
            "/api/auth/users",
            headers=headers,
            json={"email": "new@opendc.ca", "name": "New Person", "role": "sales", "password": "secret123"},
        )
        assert rejected.status_code == 400

        created = client.post(
            "/api/auth/users",
            headers=headers,
            json={"email": "new@opendc.ca", "name": "New Person", "role": "sales"},
        )
        assert created.status_code == 200, created.text
        body = created.json()
        assert body["email_sent"] is False
        assert body["user"]["invite_pending"] is True
        assert body["user"]["is_active"] is False
        token = body["setup_path"].split("token=", 1)[1]

        blocked = _login(client, "new@opendc.ca", password="anything1")
        assert blocked.status_code == 401

        setup = client.post(
            "/api/auth/setup",
            json={"token": token, "password": "chooseme1", "name": "New Person"},
        )
        assert setup.status_code == 200, setup.text
        assert setup.json()["user"]["is_active"] is True
        assert setup.json()["user"]["role"] == "sales"
        assert setup.json()["access_token"]

        signed_in = _login(client, "new@opendc.ca", password="chooseme1")
        assert signed_in.status_code == 200, signed_in.text

        audit = client.get("/api/auth/access-audit", headers=headers)
        assert audit.status_code == 200
        assert any(row["action"] == "invite" for row in audit.json())

        changed = client.patch(
            f"/api/auth/users/{setup.json()['user']['id']}",
            headers=headers,
            json={"role": "purchasing"},
        )
        assert changed.status_code == 200, changed.text
        assert changed.json()["role"] == "purchasing"
        assert changed.json()["permissions"]["purchase_orders.send"] is True
        assert changed.json()["permissions"]["quotes.edit"] is False

        disabled = client.post(
            f"/api/auth/users/{setup.json()['user']['id']}/disable",
            headers=headers,
        )
        assert disabled.status_code == 200, disabled.text
        assert disabled.json()["is_active"] is False

        locked = _login(client, "new@opendc.ca", password="chooseme1")
        assert locked.status_code == 403
        assert locked.json()["detail"] == "This account is disabled."

        pending = client.post(
            "/api/auth/users",
            headers=headers,
            json={"email": "pending@opendc.ca", "name": "Pending Person", "role": "viewer"},
        )
        assert pending.status_code == 200, pending.text
        pending_id = pending.json()["user"]["id"]
        held = client.post(f"/api/auth/users/{pending_id}/disable", headers=headers)
        assert held.status_code == 200, held.text
        assert held.json()["invite_pending"] is True
        assert held.json()["is_active"] is False
        reopened = client.post(f"/api/auth/users/{pending_id}/enable", headers=headers)
        assert reopened.status_code == 400
        assert "setup link" in reopened.json()["detail"].lower()


class TestPermissionMap:
    def test_public_door_math_customer_paths_and_purchasing_send(self):
        assert permission_for("GET", "/api/door-config/full-config") is None
        assert permission_for("POST", "/api/door-config/calculate-door") is None
        assert permission_for("GET", "/api/customer/portal/team") is None
        assert permission_for("POST", "/api/door-config/generate-quote") == (
            "any", "quotes.edit", "configurator.use",
        )
        assert permission_for("POST", "/api/admin/purchasing/generate-po") == ("perm", "purchase_orders.send")
        assert permission_for("GET", "/api/admin/purchasing/vendors") == ("perm", "purchase_orders.view")

    def test_backfill_promotes_joey_and_keeps_other_staff_equivalent(self):
        assert plan_backfill("joey@opendc.ca", "ADMIN", "INTERNAL", None) == ("OWNER", None)
        assert plan_backfill("other@opendc.ca", "ADMIN", "INTERNAL", None) is None
        assert plan_backfill("dealer@example.com", "VIEWER", "CUSTOMER", None) is None
        assert plan_backfill("automation@keys.opendc.internal", "ADMIN", "SERVICE", None) is None
        assert plan_backfill("already@opendc.ca", "VIEWER", "INTERNAL", {"quotes.view": True}) is None

        role_name, perms = plan_backfill("reviewer@opendc.ca", "REVIEWER", "INTERNAL", None)
        assert role_name == "MANAGER"
        assert perms["settings.edit"] is True
        assert perms["purchase_orders.send"] is True

        viewer_role, viewer_perms = plan_backfill("viewer@opendc.ca", "VIEWER", "INTERNAL", None)
        assert viewer_role == "VIEWER"
        assert viewer_perms["quotes.edit"] is True
        assert viewer_perms["purchase_orders.view"] is False
        assert viewer_perms["configurator.use"] is True
        assert viewer_perms == legacy_viewer_permissions()


def _person(role, permissions=None):
    return SimpleNamespace(
        role=role,
        permissions=permissions,
        user_type="INTERNAL",
        email="person@opendc.ca",
    )


_QUOTE_PAYLOAD = {
    "success": True,
    "message": "BC Quote SQ-1 created with 2 line items | Volume pricing: 32.0% GM (4.0% discount)",
    "data": {
        "bc_quote_number": "SQ-1",
        "pricing": {"subtotal": 100, "tax": 5, "total": 105},
        "line_pricing": [{
            "part_number": "P",
            "unit_price": 10,
            "line_total": 10,
            "unit_cost": 4,
            "margin": 0.6,
        }],
        "freight": {"amount": 5, "rate": 5, "description": "Freight (5% - AB)", "skip": False},
        "escalating_margin": {"target_gm": 32, "discount_pct": 4},
        "parts_summary": [{"part_number": "P", "quantity": 1}],
    },
}


class TestConfiguratorOnly:
    def test_preset_sees_selling_prices_and_blocks_the_rest(self):
        flags = PRESETS["configurator"]
        assert flags["configurator.use"] is True
        assert flags["pricing.view"] is True
        assert flags["pricing.edit"] is False
        for key in (
            "quotes.view",
            "quotes.edit",
            "sales_orders.view",
            "purchase_orders.view",
            "customers.view",
            "inventory.view",
            "production.view",
            "users.view",
            "settings.view",
            "receiving.view",
        ):
            assert flags[key] is False, key
        assert PRESETS["sales"]["pricing.view"] is True
        assert PRESETS["sales"]["configurator.use"] is True
        assert PRESETS["manager"]["configurator.use"] is True
        assert PRESETS["manager"]["pricing.edit"] is False

    def test_selling_prices_stay_and_cost_is_removed(self):
        assert permission_for("GET", "/api/door-config/load-quote/SQ-1") == (
            "any", "quotes.view", "configurator.use",
        )
        assert permission_for("GET", "/api/admin/customers/bc-customers") == (
            "any", "customers.view", "configurator.use",
        )
        assert permission_for("GET", "/api/admin/customers") == ("perm", "customers.view")
        assert permission_for("GET", "/api/settings/pricing-tiers/current") == ("perm", "pricing.edit")
        assert permission_for("GET", "/api/settings/freight-config/current") == ("perm", "pricing.edit")
        assert permission_for("GET", "/api/admin/pricing-diagnostic") == ("perm", "pricing.edit")
        assert permission_for("GET", "/api/bc/purchase-price-lines") == ("perm", "pricing.edit")
        assert permission_for("GET", "/api/bc/sales-price-lines") == ("perm", "pricing.view")
        assert permission_for("GET", "/api/chat/conversations")[0] == "any"

        seller = _person(UserRole.CONFIGURATOR)
        priced = redact_configurator_quote(seller, _QUOTE_PAYLOAD)
        assert priced["data"]["pricing"]["total"] == 105
        assert priced["data"]["line_pricing"][0]["unit_price"] == 10
        assert "unit_cost" not in priced["data"]["line_pricing"][0]
        assert "margin" not in priced["data"]["line_pricing"][0]
        assert priced["data"]["freight"] == {"amount": 5, "description": "Freight", "skip": False}
        assert "escalating_margin" not in priced["data"]
        assert "Volume pricing" not in priced["message"]
        assert priced["data"]["bc_quote_number"] == "SQ-1"
        assert "escalating_margin" in _QUOTE_PAYLOAD["data"]

        hidden = _person(
            UserRole.CONFIGURATOR,
            {"configurator.use": True, "pricing.view": False},
        )
        blind = redact_configurator_quote(hidden, _QUOTE_PAYLOAD)
        assert "pricing" not in blind["data"]
        assert "line_pricing" not in blind["data"]
        assert "freight" not in blind["data"]
        assert blind["data"]["parts_summary"] == [{"part_number": "P", "quantity": 1}]

        row = {
            "bc_customer_id": "guid",
            "company_name": "Upwardor",
            "contact_name": "Manveer",
            "email": "mpadda@upwardor.com",
            "phone": "555",
            "already_linked": False,
            "is_home_builder": True,
            "bc_price_group": "GOLD",
            "pricing_tier": "gold",
            "customer_number": "C100",
        }
        picked = redact_customer_search(seller, row)
        assert picked["company_name"] == "Upwardor"
        assert picked["is_home_builder"] is True
        assert picked["email"] is None
        assert picked["contact_name"] is None
        assert picked["phone"] is None
        assert picked["customer_number"] is None
        assert picked["bc_price_group"] is None
        assert picked["pricing_tier"] is None

        owner = _person(UserRole.ADMIN)
        full = redact_customer_search(owner, row)
        assert full["email"] == "mpadda@upwardor.com"
        assert full["pricing_tier"] == "gold"
        full_quote = redact_configurator_quote(owner, _QUOTE_PAYLOAD)
        assert full_quote["data"]["escalating_margin"]["target_gm"] == 32
        assert full_quote["data"]["freight"]["rate"] == 5
        assert "Volume pricing" in full_quote["message"]
        assert full_quote["data"]["line_pricing"][0]["unit_cost"] == 4

    def test_login_cannot_open_staff_modules(self, client, monkeypatch):
        monkeypatch.setattr(
            "app.services.notification_service.notification_service.send_email",
            lambda *args, **kwargs: False,
        )
        login = _login(client, "config@upwardor.com")
        assert login.status_code == 200, login.text
        user = login.json()["user"]
        assert user["role"] == "configurator"
        assert user["permissions"]["pricing.view"] is True
        assert user["permissions"]["pricing.edit"] is False
        assert user["permissions"]["quotes.view"] is False
        headers = _auth(login.json()["access_token"])
        for path in (
            "/api/admin/purchasing/vendors",
            "/api/orders",
            "/api/admin/customers",
            "/api/settings/pricing-tiers/current",
            "/api/settings/freight-config/current",
            "/api/admin/pricing-diagnostic",
            "/api/chat/conversations",
        ):
            refused = client.get(path, headers=headers)
            assert refused.status_code == 403, (path, refused.status_code, refused.text)
            assert refused.json()["detail"] == "You do not have permission to do that"

        for path in (
            "/api/admin/customers/bc-customers",
            "/api/door-config/load-quote/SQ-1",
        ):
            allowed = client.get(path, headers=headers)
            assert allowed.status_code == 404, (path, allowed.status_code, allowed.text)
        generate = client.post("/api/door-config/generate-quote", headers=headers, json={})
        assert generate.status_code == 404, generate.text

        buyer = _login(client, "buyer@opendc.ca")
        blocked = client.get(
            "/api/admin/customers/bc-customers",
            headers=_auth(buyer.json()["access_token"]),
        )
        assert blocked.status_code == 403

        admin = _login(client, "joey@opendc.ca")
        admin_headers = _auth(admin.json()["access_token"])
        invited = client.post(
            "/api/auth/users",
            headers=admin_headers,
            json={"email": "mpadda@upwardor.com", "name": "Manveer", "role": "configurator"},
        )
        assert invited.status_code == 200, invited.text
        invited_user = invited.json()["user"]
        assert invited_user["role"] == "configurator"
        assert invited_user["permissions"]["configurator.use"] is True
        assert invited_user["permissions"]["pricing.view"] is True
        assert invited_user["permissions"]["pricing.edit"] is False
        assert invited_user["invite_pending"] is True

        turned_off = client.patch(
            f"/api/auth/users/{invited_user['id']}",
            headers=admin_headers,
            json={"permissions": {**invited_user["permissions"], "pricing.view": False}},
        )
        assert turned_off.status_code == 200, turned_off.text
        assert turned_off.json()["permissions"]["pricing.view"] is False
        assert turned_off.json()["permissions"]["configurator.use"] is True
        assert turned_off.json()["permissions_custom"] is True
