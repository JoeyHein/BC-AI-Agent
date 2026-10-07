"""Staff service API keys.

Covers create/hash/verify, revoked and expired rejection, scope default-deny,
and that a normal staff JWT still behaves the way it did before keys existed.
"""
from __future__ import annotations

import ast
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import bcrypt
import pytest
from fastapi import FastAPI
from pydantic import BaseModel
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.models import StaffServiceKey, StaffServiceKeyAudit, User, UserRole
from app.services.auth_service import AuthService, auth_service
from app.services import staff_service_keys_service as staff_keys
from app.services.staff_service_keys_service import (
    AUTOMATION_SCOPES,
    SERVICE_USER_EMAIL,
    create_key,
    evaluate,
    generate_plaintext,
    hash_plaintext,
    normalize_scopes,
    prefix_for,
    revoke_key,
    route_allowed,
)


# ─────────────────────────────────────────────────────────────────────────────
# Unit fixtures
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def session():
    engine = create_engine("sqlite://", future=True)
    User.__table__.create(engine, checkfirst=True)
    StaffServiceKey.__table__.create(engine, checkfirst=True)
    StaffServiceKeyAudit.__table__.create(engine, checkfirst=True)
    db = sessionmaker(bind=engine, autoflush=False, autocommit=False)()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture
def admin_user(session):
    user = User(
        email="admin@example.com",
        password_hash=AuthService.get_password_hash("test123"),
        name="Joey",
        role=UserRole.ADMIN,
        is_active=True,
        user_type="INTERNAL",
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


# ─────────────────────────────────────────────────────────────────────────────
# Create / hash / verify
# ─────────────────────────────────────────────────────────────────────────────


class TestCreateAndVerify:
    def test_plaintext_is_hashed_and_verifies(self, session, admin_user):
        row, plaintext = create_key(
            session, name="Hourly PO check", created_by_user_id=admin_user.id
        )
        assert plaintext.startswith("osk_live_")
        assert row.key_prefix == plaintext[:12]
        assert row.key_hash != plaintext
        assert row.key_hash.startswith("$2")
        assert bcrypt.checkpw(plaintext.encode("utf-8"), row.key_hash.encode("ascii"))
        assert "key_hash" not in (row.scopes or [])
        assert row.scopes == AUTOMATION_SCOPES
        assert row.expires_at is None
        assert row.created_by_user_id == admin_user.id
        assert row.created_at is not None

        decision = evaluate(session, plaintext, "GET", "/api/orders")
        assert decision.ok is True
        assert decision.user is not None
        assert decision.user.user_type == "SERVICE"
        assert decision.user.role == UserRole.ADMIN
        assert decision.user.email == SERVICE_USER_EMAIL
        assert decision.key_name == "Hourly PO check"
        session.refresh(row)
        assert row.last_used_at is not None

    def test_wrong_secret_does_not_verify(self, session, admin_user):
        _row, plaintext = create_key(
            session, name="X", created_by_user_id=admin_user.id
        )
        forged = prefix_for(plaintext) + "not-the-real-secret-value"
        decision = evaluate(session, forged, "GET", "/api/orders")
        assert decision.ok is False
        assert decision.status_code == 401
        assert decision.outcome == "invalid"

    def test_hash_helper_round_trip(self):
        plaintext = generate_plaintext()
        hashed = hash_plaintext(plaintext)
        assert hashed != plaintext
        assert bcrypt.checkpw(plaintext.encode(), hashed.encode("ascii"))

    def test_unknown_scope_rejected(self, session, admin_user):
        with pytest.raises(ValueError, match="Unknown scope"):
            create_key(
                session,
                name="X",
                created_by_user_id=admin_user.id,
                scopes=["users:write"],
            )

    def test_subset_of_scopes_is_stored(self, session, admin_user):
        row, _plaintext = create_key(
            session,
            name="Read orders only",
            created_by_user_id=admin_user.id,
            scopes=["orders:read"],
        )
        assert row.scopes == ["orders:read"]

    def test_automation_preset_expands(self):
        assert normalize_scopes(["automation"]) == AUTOMATION_SCOPES
        assert normalize_scopes(None) == AUTOMATION_SCOPES

    def test_past_expiry_rejected(self, session, admin_user):
        with pytest.raises(ValueError, match="future"):
            create_key(
                session,
                name="X",
                created_by_user_id=admin_user.id,
                expires_at=datetime.utcnow() - timedelta(minutes=5),
            )


class TestRevokedAndExpired:
    def test_revoked_key_is_rejected(self, session, admin_user):
        row, plaintext = create_key(
            session, name="X", created_by_user_id=admin_user.id
        )
        revoke_key(session, key_id=row.id, revoked_by_user_id=admin_user.id)
        decision = evaluate(session, plaintext, "GET", "/api/orders")
        assert decision.ok is False
        assert decision.status_code == 401
        assert decision.outcome == "revoked"
        assert "revoked" in decision.detail.lower()

    def test_revoke_is_idempotent(self, session, admin_user):
        row, _plaintext = create_key(
            session, name="X", created_by_user_id=admin_user.id
        )
        first = revoke_key(session, key_id=row.id, revoked_by_user_id=admin_user.id)
        second = revoke_key(session, key_id=row.id, revoked_by_user_id=admin_user.id)
        assert first.status == "revoked"
        assert second.status == "revoked"
        assert second.revoked_at == first.revoked_at

    def test_expired_key_is_rejected(self, session, admin_user):
        row, plaintext = create_key(
            session, name="X", created_by_user_id=admin_user.id
        )
        row.expires_at = datetime.utcnow() - timedelta(seconds=1)
        session.commit()
        decision = evaluate(session, plaintext, "GET", "/api/orders")
        assert decision.ok is False
        assert decision.status_code == 401
        assert decision.outcome == "expired"


class TestScopeRules:
    def test_default_deny_user_management_and_settings(self):
        granted = set(AUTOMATION_SCOPES)
        assert route_allowed("GET", "/api/auth/users", b"", granted)[0] is False
        assert route_allowed("DELETE", "/api/auth/users/1", b"", granted)[0] is False
        assert route_allowed("PUT", "/api/settings/pricing-tiers", b"", granted)[0] is False
        assert route_allowed("POST", "/api/orders/1/ship", b"", granted)[0] is False
        assert route_allowed("POST", "/api/orders/invoices/9/post", b"", granted)[0] is False
        assert route_allowed("POST", "/api/quotes/3/approve", b"", granted)[0] is False

    def test_allowed_reads_and_draft_lines(self):
        granted = set(AUTOMATION_SCOPES)
        assert route_allowed("GET", "/api/orders", b"", granted)[0] is True
        assert route_allowed("GET", "/api/orders/bc/orders", b"", granted)[0] is True
        assert route_allowed("GET", "/api/inventory/levels", b"", granted)[0] is True
        assert route_allowed("GET", "/inventory/item/PN10", b"", granted)[0] is True
        assert route_allowed("GET", "/api/admin/purchasing/so-po-links", b"", granted)[0] is True
        assert route_allowed("GET", "/api/admin/purchasing/requirements", b"", granted)[0] is True
        assert route_allowed("DELETE", "/api/admin/purchasing/draft-pos/PO-000962/lines/10", b"", granted)[0] is True
        assert route_allowed("POST", "/api/admin/purchasing/draft-pos/PO-000962/lines/normalize-order", b"", granted)[0] is True
        assert route_allowed("POST", "/api/admin/vendor-acks/run", b"", granted)[0] is True
        assert route_allowed("GET", "/api/admin/quote-review/reviews", b"", granted)[0] is True
        assert route_allowed("POST", "/api/admin/purchasing/draft-pos/PO-000962/review-draft", b"", granted)[0] is True

    def test_generate_po_requires_send_email_false(self):
        granted = set(AUTOMATION_SCOPES)
        path = "/api/admin/purchasing/generate-po"
        assert route_allowed("POST", path, b"{}", granted)[0] is False
        assert route_allowed("POST", path, b'{"send_email": true}', granted)[0] is False
        assert route_allowed("POST", path, b'{"send_email": false}', granted)[0] is True
        assert route_allowed("POST", path, b'{"create_review_draft": false}', granted)[0] is True
        # create_review_draft wins. true means an Outlook draft, which this call must not do.
        both = b'{"send_email": false, "create_review_draft": true}'
        assert route_allowed("POST", path, both, granted)[0] is False

    def test_narrow_key_cannot_call_purchasing(self):
        granted = {"orders:read"}
        assert route_allowed("GET", "/api/orders", b"", granted)[0] is True
        assert route_allowed("GET", "/api/admin/purchasing/so-po-links", b"", granted)[0] is False


class TestHumanLoginUnchanged:
    def test_staff_password_login_still_works(self, session, admin_user):
        user = auth_service.authenticate_user(session, "admin@example.com", "test123")
        assert user is not None
        assert user.id == admin_user.id
        assert user.role == UserRole.ADMIN

    def test_service_identity_cannot_password_login(self, session):
        user = User(
            email=SERVICE_USER_EMAIL,
            password_hash=AuthService.get_password_hash("test123"),
            name="Automation",
            role=UserRole.ADMIN,
            is_active=True,
            user_type="SERVICE",
        )
        session.add(user)
        session.commit()
        assert auth_service.authenticate_user(session, SERVICE_USER_EMAIL, "test123") is None

    def test_bad_password_still_rejected(self, session, admin_user):
        assert auth_service.authenticate_user(session, "admin@example.com", "nope") is None


def test_migration_revises_current_head():
    path = (
        Path(__file__).resolve().parents[1]
        / "alembic"
        / "versions"
        / "p6q7r8s9t0u1_add_staff_service_keys.py"
    )
    module = ast.parse(path.read_text())
    assigned = {}
    for node in module.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            name = getattr(node.targets[0], "id", None)
            if name in {"revision", "down_revision"} and isinstance(node.value, ast.Constant):
                assigned[name] = node.value.value
    assert assigned["revision"] == "p6q7r8s9t0u1"
    assert assigned["down_revision"] == "o5p6q7r8s9t0"


def test_every_staff_jwt_check_accepts_service_keys():
    api = Path(__file__).resolve().parents[1] / "app" / "api"
    expected = [
        "auth.py",
        "purchasing.py",
        "po_agent.py",
        "vendor_acks.py",
        "inventory_agent.py",
        "invoice_intake.py",
        "admin_customers.py",
        "catalog.py",
        "public.py",
        "email_agent.py",
        "metrics.py",
    ]
    for name in expected:
        text = (api / name).read_text()
        assert "service_user_if_key" in text, name
    customer = (api / "customer_auth.py").read_text()
    assert "service_user_if_key" not in customer


# ─────────────────────────────────────────────────────────────────────────────
# HTTP: scopes, revocation, and unchanged JWT
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def db_factory():
    engine = create_engine(
        "sqlite://",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    User.__table__.create(engine, checkfirst=True)
    StaffServiceKey.__table__.create(engine, checkfirst=True)
    StaffServiceKeyAudit.__table__.create(engine, checkfirst=True)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


@pytest.fixture
def client(db_factory, monkeypatch):
    monkeypatch.setattr(staff_keys, "new_session", db_factory)

    db = db_factory()
    db.add(
        User(
            email="admin@example.com",
            password_hash=AuthService.get_password_hash("test123"),
            name="Joey",
            role=UserRole.ADMIN,
            is_active=True,
            user_type="INTERNAL",
        )
    )
    db.add(
        User(
            email="viewer@example.com",
            password_hash=AuthService.get_password_hash("test123"),
            name="Viewer",
            role=UserRole.VIEWER,
            is_active=True,
            user_type="INTERNAL",
        )
    )
    db.commit()
    db.close()

    from app.api import auth, purchasing
    from app.api.staff_service_key_middleware import staff_service_key_middleware
    from app.api.staff_service_keys import router as keys_router

    test_app = FastAPI()
    test_app.middleware("http")(staff_service_key_middleware)
    test_app.include_router(auth.router)
    test_app.include_router(keys_router)

    @test_app.get("/api/orders")
    def list_orders(user: User = Depends_user(auth.get_current_user)):
        return _who(user)

    @test_app.get("/api/admin/purchasing/so-po-links")
    def links(admin: User = Depends_user(purchasing.get_current_admin)):
        return _who(admin)

    @test_app.post("/api/admin/purchasing/generate-po")
    def generate_po(
        payload: _GeneratePO,
        admin: User = Depends_user(purchasing.get_current_admin),
    ):
        return {
            "send_email": payload.send_email,
            "create_review_draft": payload.create_review_draft,
            **_who(admin),
        }

    @test_app.get("/api/admin/quote-review/reviews")
    def reviews(user: User = Depends_user(auth.require_admin)):
        return _who(user)

    @test_app.put("/api/settings/pricing-tiers")
    def update_settings(user: User = Depends_user(auth.require_admin)):
        return _who(user)

    def _override():
        scoped = db_factory()
        try:
            yield scoped
        finally:
            scoped.close()

    test_app.dependency_overrides[auth.get_db] = _override
    test_app.dependency_overrides[purchasing.get_db] = _override
    return TestClient(test_app)


class _GeneratePO(BaseModel):
    vendor_name: str = "UPW"
    lines: list = []
    send_email: Optional[bool] = None
    create_review_draft: Optional[bool] = None


def Depends_user(dependency):
    from fastapi import Depends

    return Depends(dependency)


def _who(user: User) -> dict:
    role = user.role.value if hasattr(user.role, "value") else user.role
    return {"email": user.email, "type": user.user_type, "role": role}


def _login(client: TestClient, email: str, password: str = "test123") -> str:
    response = client.post("/api/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


class TestHttpAuth:
    def test_jwt_staff_auth_is_unchanged(self, client):
        admin = _login(client, "admin@example.com")
        me = client.get("/api/auth/me", headers=_auth(admin))
        assert me.status_code == 200
        assert me.json()["email"] == "admin@example.com"
        assert me.json()["role"] == "admin"

        users = client.get("/api/auth/users", headers=_auth(admin))
        assert users.status_code == 200
        emails = {row["email"] for row in users.json()}
        assert "admin@example.com" in emails

        viewer = _login(client, "viewer@example.com")
        forbidden = client.get("/api/auth/users", headers=_auth(viewer))
        assert forbidden.status_code == 403
        assert forbidden.json()["detail"] == "Admin access required"

        bogus = client.get(
            "/api/auth/me",
            headers={"Authorization": "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.e30.bad"},
        )
        assert bogus.status_code == 401
        assert bogus.json()["detail"] == "Invalid authentication credentials"

        # A human session wins when a service key is also attached.
        created = client.post(
            "/api/admin/service-keys",
            json={"name": "Ignore me"},
            headers=_auth(admin),
        )
        assert created.status_code == 201
        plaintext = created.json()["plaintext"]
        client.post(f"/api/admin/service-keys/{created.json()['id']}/revoke", headers=_auth(admin))
        me_again = client.get(
            "/api/auth/me",
            headers={**_auth(admin), "X-API-Key": plaintext},
        )
        assert me_again.status_code == 200
        assert me_again.json()["email"] == "admin@example.com"

    def test_create_lists_prefix_only_and_scope_gates(self, client, db_factory):
        admin = _login(client, "admin@example.com")
        created = client.post(
            "/api/admin/service-keys",
            json={"name": "Hourly PO check"},
            headers=_auth(admin),
        )
        assert created.status_code == 201, created.text
        body = created.json()
        plaintext = body["plaintext"]
        assert plaintext.startswith("osk_live_")
        assert "key_hash" not in body
        assert body["scopes"] == AUTOMATION_SCOPES

        listed = client.get("/api/admin/service-keys", headers=_auth(admin))
        assert listed.status_code == 200
        dumped = listed.text
        assert plaintext not in dumped
        assert "key_hash" not in dumped
        assert listed.json()[0]["key_prefix"] == plaintext[:12]
        assert listed.json()[0]["name"] == "Hourly PO check"

        db = db_factory()
        row = db.query(StaffServiceKey).one()
        assert row.key_hash != plaintext
        assert row.key_hash.startswith("$2")
        db.close()

        viewer = _login(client, "viewer@example.com")
        assert client.post(
            "/api/admin/service-keys",
            json={"name": "nope"},
            headers=_auth(viewer),
        ).status_code == 403

        orders = client.get("/api/orders", headers=_auth(plaintext))
        assert orders.status_code == 200, orders.text
        assert orders.json()["email"] == SERVICE_USER_EMAIL
        assert orders.json()["type"] == "SERVICE"
        assert orders.json()["role"] == "admin"

        links = client.get("/api/admin/purchasing/so-po-links", headers=_auth(plaintext))
        assert links.status_code == 200, links.text
        assert links.json()["type"] == "SERVICE"

        reviews = client.get("/api/admin/quote-review/reviews", headers=_auth(plaintext))
        assert reviews.status_code == 200, reviews.text
        assert reviews.json()["role"] == "admin"

        # Same purchasing route with a person's JWT is still that person.
        as_admin = client.get("/api/admin/purchasing/so-po-links", headers=_auth(admin))
        assert as_admin.status_code == 200
        assert as_admin.json()["email"] == "admin@example.com"

        blocked = client.get("/api/auth/users", headers=_auth(plaintext))
        assert blocked.status_code == 403
        assert "not allowed" in blocked.json()["detail"]

        settings = client.put("/api/settings/pricing-tiers", headers=_auth(plaintext))
        assert settings.status_code == 403

        manage = client.post(
            "/api/admin/service-keys",
            json={"name": "nested"},
            headers=_auth(plaintext),
        )
        assert manage.status_code == 403

        # X-API-Key alone is accepted on an allowed route.
        via_header = client.get("/api/orders", headers={"X-API-Key": plaintext})
        assert via_header.status_code == 200
        assert via_header.json()["type"] == "SERVICE"

        # The service identity cannot sign in as a person.
        login = client.post(
            "/api/auth/login",
            json={"email": SERVICE_USER_EMAIL, "password": "anything"},
        )
        assert login.status_code == 401
        assert login.json()["detail"] == "Incorrect email or password"

        audit = client.get("/api/admin/service-keys/audit", headers=_auth(admin))
        assert audit.status_code == 200
        rows = audit.json()
        assert rows
        assert any(row["key_name"] == "Hourly PO check" and row["path"] == "/api/orders" for row in rows)
        assert any(row["decision"] == "denied" and row["path"] == "/api/auth/users" for row in rows)
        assert plaintext not in audit.text

    def test_revoked_and_expired_rejected_on_the_next_request(self, client, db_factory):
        admin = _login(client, "admin@example.com")
        created = client.post(
            "/api/admin/service-keys",
            json={"name": "Temporary"},
            headers=_auth(admin),
        )
        plaintext = created.json()["plaintext"]
        key_id = created.json()["id"]
        assert client.get("/api/orders", headers=_auth(plaintext)).status_code == 200

        revoked = client.post(f"/api/admin/service-keys/{key_id}/revoke", headers=_auth(admin))
        assert revoked.status_code == 200
        assert revoked.json()["status"] == "revoked"
        again = client.post(f"/api/admin/service-keys/{key_id}/revoke", headers=_auth(admin))
        assert again.status_code == 200

        after = client.get("/api/orders", headers=_auth(plaintext))
        assert after.status_code == 401
        assert "revoked" in after.json()["detail"].lower()

        # A second key that is already past expires_at.
        live = client.post(
            "/api/admin/service-keys",
            json={"name": "Will expire", "scopes": ["orders:read"]},
            headers=_auth(admin),
        )
        assert live.status_code == 201, live.text
        expired_plain = live.json()["plaintext"]
        db = db_factory()
        row = db.query(StaffServiceKey).filter(StaffServiceKey.name == "Will expire").one()
        row.expires_at = datetime.utcnow() - timedelta(minutes=1)
        db.commit()
        db.close()
        expired = client.get("/api/orders", headers=_auth(expired_plain))
        assert expired.status_code == 401
        assert "expired" in expired.json()["detail"].lower()

        narrow = client.get("/api/admin/purchasing/so-po-links", headers=_auth(expired_plain))
        # Expired wins over the scope check: the key is not usable at all.
        assert narrow.status_code == 401

    def test_generate_po_send_email_false_only(self, client):
        admin = _login(client, "admin@example.com")
        created = client.post(
            "/api/admin/service-keys",
            json={"name": "PO"},
            headers=_auth(admin),
        )
        plaintext = created.json()["plaintext"]
        headers = {**_auth(plaintext), "Content-Type": "application/json"}

        denied = client.post(
            "/api/admin/purchasing/generate-po",
            headers=headers,
            json={"vendor_name": "UPW", "lines": [], "send_email": True},
        )
        assert denied.status_code == 403
        assert "send_email" in denied.json()["detail"]

        omitted = client.post(
            "/api/admin/purchasing/generate-po",
            headers=headers,
            json={"vendor_name": "UPW", "lines": []},
        )
        assert omitted.status_code == 403

        allowed = client.post(
            "/api/admin/purchasing/generate-po",
            headers=headers,
            json={"vendor_name": "UPW", "lines": [], "send_email": False},
        )
        assert allowed.status_code == 200, allowed.text
        assert allowed.json()["send_email"] is False
        assert allowed.json()["type"] == "SERVICE"

    def test_past_expiry_on_create_is_400(self, client):
        admin = _login(client, "admin@example.com")
        response = client.post(
            "/api/admin/service-keys",
            json={
                "name": "Already dead",
                "expires_at": (datetime.utcnow() - timedelta(days=1)).isoformat() + "Z",
            },
            headers=_auth(admin),
        )
        assert response.status_code == 400
