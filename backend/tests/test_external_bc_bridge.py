"""BCB-02 tests — external check-availability + purchase-orders endpoints.

Mirrors test_external_quote_convert_to_order fixtures: in-memory SQLite, a
TestClient over a FastAPI app mounting the two new routers, monkeypatched BC
client + inventory service.
"""
import os
import sys
import uuid
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import external_inventory, external_purchase_orders
from app.api.auth import get_db
from app.db.models import ExternalApiKey, ExternalPurchaseOrder, User, UserRole
from app.services import external_purchase_order_service
from app.services.external_api_keys_service import create_key


@pytest.fixture
def db_factory():
    engine = create_engine(
        "sqlite://",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    User.__table__.create(engine, checkfirst=True)
    ExternalApiKey.__table__.create(engine, checkfirst=True)
    ExternalPurchaseOrder.__table__.create(engine, checkfirst=True)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


@pytest.fixture
def session(db_factory):
    db = db_factory()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture
def admin_user(session):
    u = User(email="admin@test.local", password_hash="x", role=UserRole.ADMIN, is_active=True)
    session.add(u)
    session.commit()
    session.refresh(u)
    return u


@pytest.fixture
def primary_key(session, admin_user):
    _row, plaintext = create_key(
        session, name="BCB key", supplier_account_code="ED-001", created_by_user_id=admin_user.id
    )
    return plaintext


@pytest.fixture
def other_key(session, admin_user):
    _row, plaintext = create_key(
        session, name="BCB other", supplier_account_code="ED-OTHER", created_by_user_id=admin_user.id
    )
    return plaintext


@pytest.fixture
def app(db_factory):
    test_app = FastAPI()
    test_app.include_router(external_inventory.router)
    test_app.include_router(external_purchase_orders.router)

    def _override_get_db():
        db = db_factory()
        try:
            yield db
        finally:
            db.close()

    test_app.dependency_overrides[get_db] = _override_get_db
    return test_app


@pytest.fixture
def client(app):
    return TestClient(app)


# ── BC stubs ────────────────────────────────────────────────────────────────


class FakeBcClient:
    def __init__(self) -> None:
        self.create_calls: List[Dict[str, Any]] = []
        self.line_calls: List[Dict[str, Any]] = []
        self._serial = 104_820

    def create_purchase_order(self, po_data, company_id=None) -> Dict[str, Any]:
        self.create_calls.append(po_data)
        self._serial += 1
        return {"id": str(uuid.uuid4()), "number": str(self._serial)}

    def add_purchase_order_line(self, po_id, line_data, company_id=None) -> Dict[str, Any]:
        self.line_calls.append({"po_id": po_id, **line_data})
        return {"id": str(uuid.uuid4())}


@pytest.fixture
def fake_bc(monkeypatch):
    fake = FakeBcClient()
    monkeypatch.setattr(external_purchase_order_service, "bc_client", fake)
    yield fake


class _FakeAvailabilityResult:
    def __init__(self, payload: Dict[str, Any]) -> None:
        self._payload = payload

    def to_dict(self) -> Dict[str, Any]:
        return self._payload


class FakeInventoryService:
    def __init__(self) -> None:
        self.calls: List[List[Dict[str, Any]]] = []

    def check_availability(self, items, required_date=None):
        self.calls.append(items)
        return _FakeAvailabilityResult(
            {
                "allAvailable": False,
                "items": [
                    {"itemNumber": "PN10", "onHand": 12, "available": 12, "shortfall": 0, "status": "available", "leadTimeDays": 0},
                    {"itemNumber": "PN99", "onHand": 0, "available": 0, "shortfall": 3, "status": "unavailable", "leadTimeDays": 7},
                ],
            }
        )


@pytest.fixture
def fake_inventory(monkeypatch):
    fake = FakeInventoryService()
    monkeypatch.setattr(external_inventory, "bc_inventory_service", fake)
    yield fake


# ── check-availability ────────────────────────────────────────────────────────


class TestCheckAvailability:
    def test_401_missing_header(self, client, fake_inventory):
        r = client.post("/api/external/check-availability", json={"supplierAccountCode": "ED-001", "items": [{"sku": "PN10", "quantity": 2}]})
        assert r.status_code == 401

    def test_404_cross_account(self, client, other_key, fake_inventory):
        r = client.post(
            "/api/external/check-availability",
            headers={"X-Service-AI-Key": other_key},
            json={"supplierAccountCode": "ED-001", "items": [{"sku": "PN10", "quantity": 2}]},
        )
        assert r.status_code == 404

    def test_happy_maps_envelope(self, client, primary_key, fake_inventory):
        r = client.post(
            "/api/external/check-availability",
            headers={"X-Service-AI-Key": primary_key},
            json={"supplierAccountCode": "ED-001", "items": [{"sku": "PN10", "quantity": 2}, {"sku": "PN99", "quantity": 3}]},
        )
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["allAvailable"] is False
        assert data["items"][0]["sku"] == "PN10"
        assert data["items"][1]["status"] == "unavailable"


# ── purchase-orders ────────────────────────────────────────────────────────────


class TestCreatePurchaseOrder:
    def _body(self, ext_id: str):
        return {
            "supplierAccountCode": "ED-001",
            "externalPoId": ext_id,
            "poNumber": "PO-000123",
            "lines": [{"sku": "PN10", "quantity": 5, "unitCostCents": 700, "description": "Spring"}],
        }

    def test_401_missing_header(self, client, fake_bc):
        r = client.post("/api/external/purchase-orders", json=self._body("x"))
        assert r.status_code == 401

    def test_404_cross_account(self, client, other_key, fake_bc):
        r = client.post("/api/external/purchase-orders", headers={"X-Service-AI-Key": other_key}, json=self._body("x"))
        assert r.status_code == 404
        assert fake_bc.create_calls == []

    def test_happy_create_then_idempotent_replay(self, client, primary_key, fake_bc):
        ext = str(uuid.uuid4())
        first = client.post("/api/external/purchase-orders", headers={"X-Service-AI-Key": primary_key}, json=self._body(ext))
        assert first.status_code == 201
        ref = first.json()["data"]["supplierPoRef"]
        assert ref == "104821"
        assert len(fake_bc.create_calls) == 1
        assert len(fake_bc.line_calls) == 1

        # Replay with the same externalPoId → cached, no second BC PO.
        second = client.post("/api/external/purchase-orders", headers={"X-Service-AI-Key": primary_key}, json=self._body(ext))
        assert second.status_code == 200
        assert second.json()["data"]["supplierPoRef"] == ref
        assert len(fake_bc.create_calls) == 1
