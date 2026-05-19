"""External price-items endpoint tests (SQB-04).

Exercises the FastAPI TestClient against `/api/external/price-items`
with the BC client stubbed and the DB pointed at in-memory SQLite.

Coverage:
    - 401 when X-Service-AI-Key is missing or invalid
    - 404 when the body's supplierAccountCode doesn't match the key's binding
    - 400 (Pydantic) when the body is malformed (empty items, qty < 1)
    - 200 happy path: customer-tier price returned
    - falls back: group-tier when no customer price
    - falls back: all-customers when no customer + no group
    - falls back: item.unitPrice when nothing in SalesPriceLists
    - missing sku returns a per-line "missing" entry, doesn't fail the batch
    - cache hit returns the same envelope without hitting BC twice
"""
from __future__ import annotations

import os
import sys
from typing import Any, Dict, Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import external_pricing, external_keys
from app.api.auth import get_db
from app.db.models import BCCustomer, ExternalApiKey, User, UserRole
from app.services import external_pricing_service
from app.services.external_api_keys_service import create_key


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def db_factory():
    # StaticPool + a single shared connection so every Session created
    # from the factory sees the same in-memory SQLite database. Without
    # this the TestClient and the fixture session get distinct
    # connections with distinct (empty) schemas.
    engine = create_engine(
        "sqlite://",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    User.__table__.create(engine, checkfirst=True)
    BCCustomer.__table__.create(engine, checkfirst=True)
    ExternalApiKey.__table__.create(engine, checkfirst=True)
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
def api_key(session, admin_user):
    _row, plaintext = create_key(
        session,
        name="SQB-04 test key",
        supplier_account_code="ED-001",
        created_by_user_id=admin_user.id,
    )
    return plaintext


@pytest.fixture
def bc_customer(session):
    c = BCCustomer(
        bc_customer_id="ED-001",
        bc_price_group="GOLD",
        company_name="Elevated Doors",
    )
    session.add(c)
    session.commit()


@pytest.fixture
def app(db_factory):
    """Minimal FastAPI app mounting just the two routers under test
    plus the get_db override pointing at our in-memory session."""
    test_app = FastAPI()
    test_app.include_router(external_keys.router)
    test_app.include_router(external_pricing.router)

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


# ─────────────────────────────────────────────────────────────────────────────
# BC client stubs
# ─────────────────────────────────────────────────────────────────────────────


class FakeBcClient:
    """Records BC calls + returns scripted responses. Stubs the
    bc_client singleton imported by external_pricing_service."""

    def __init__(self) -> None:
        # source_type -> list[ {filter_key, response} ]
        self._price_responses: Dict[int, Dict[str, Any]] = {}
        self._items: Dict[str, Dict[str, Any]] = {}
        self.price_calls: list[tuple[int, str, str]] = []
        self.item_calls: list[str] = []

    def set_item(self, sku: str, item: Dict[str, Any]) -> None:
        self._items[sku] = item

    def set_price(
        self,
        source_type: int,
        item_no: str,
        source_no: str,
        entries: list,
    ) -> None:
        self._price_responses[(source_type, item_no, source_no)] = {
            "available": bool(entries),
            "entries": entries,
        }

    # bc_client.get_sales_price_lines signature
    def get_sales_price_lines(
        self,
        item_no: str,
        source_type: int,
        source_no: str = "",
        qty: float = 1.0,
        as_of_date: Optional[str] = None,
        company_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        self.price_calls.append((source_type, item_no, source_no))
        return self._price_responses.get(
            (source_type, item_no, source_no),
            {"available": False, "entries": []},
        )

    # bc_client.search_items signature
    def search_items(self, query: str, limit: int = 25, **_) -> Dict[str, Any]:
        self.item_calls.append(query)
        item = self._items.get(query)
        return {"items": [item]} if item else {"items": []}


@pytest.fixture
def fake_bc(monkeypatch):
    fake = FakeBcClient()
    monkeypatch.setattr(external_pricing_service, "bc_client", fake)
    external_pricing_service.clear_cache()
    yield fake
    external_pricing_service.clear_cache()


def _seed_item(fake_bc: FakeBcClient, sku: str, *, unit_cost: float = 100.0, category: str = "ALUMINIUM") -> None:
    fake_bc.set_item(
        sku,
        {
            "number": sku,
            "displayName": f"Test {sku}",
            "unitCost": unit_cost,
            "unitPrice": 0,
            "itemCategoryCode": category,
        },
    )


# ─────────────────────────────────────────────────────────────────────────────
# Auth + body validation
# ─────────────────────────────────────────────────────────────────────────────


class TestAuth:
    def test_401_when_missing_header(self, client, fake_bc):
        res = client.post(
            "/api/external/price-items",
            json={"supplierAccountCode": "ED-001", "items": [{"sku": "X", "quantity": 1}]},
        )
        assert res.status_code == 401
        body = res.json()
        assert body["detail"]["error"]["code"] == "UNAUTHORIZED"

    def test_401_when_key_is_garbage(self, client, fake_bc):
        res = client.post(
            "/api/external/price-items",
            headers={"X-Service-AI-Key": "sai_live_NOPENOPENOPENOPENOPENOPE"},
            json={"supplierAccountCode": "ED-001", "items": [{"sku": "X", "quantity": 1}]},
        )
        assert res.status_code == 401

    def test_404_on_account_code_mismatch(self, client, api_key, fake_bc):
        res = client.post(
            "/api/external/price-items",
            headers={"X-Service-AI-Key": api_key},
            json={"supplierAccountCode": "SOMEONE-ELSE", "items": [{"sku": "X", "quantity": 1}]},
        )
        assert res.status_code == 404
        body = res.json()
        assert body["detail"]["error"]["code"] == "NOT_FOUND"

    def test_400_on_empty_items(self, client, api_key, fake_bc):
        res = client.post(
            "/api/external/price-items",
            headers={"X-Service-AI-Key": api_key},
            json={"supplierAccountCode": "ED-001", "items": []},
        )
        assert res.status_code == 422  # Pydantic validation

    def test_400_on_zero_quantity(self, client, api_key, fake_bc):
        res = client.post(
            "/api/external/price-items",
            headers={"X-Service-AI-Key": api_key},
            json={"supplierAccountCode": "ED-001", "items": [{"sku": "X", "quantity": 0}]},
        )
        assert res.status_code == 422


# ─────────────────────────────────────────────────────────────────────────────
# Pricing resolution path
# ─────────────────────────────────────────────────────────────────────────────


class TestPricingResolution:
    def test_customer_tier_wins(self, client, api_key, bc_customer, fake_bc):
        _seed_item(fake_bc, "PN10-CSTM")
        fake_bc.set_price(1, "PN10-CSTM", "ED-001", [{"Unit_Price": 99.50}])
        # group price exists but customer wins
        fake_bc.set_price(2, "PN10-CSTM", "GOLD", [{"Unit_Price": 88.00}])

        res = client.post(
            "/api/external/price-items",
            headers={"X-Service-AI-Key": api_key},
            json={"supplierAccountCode": "ED-001", "items": [{"sku": "PN10-CSTM", "quantity": 2}]},
        )
        assert res.status_code == 200
        line = res.json()["data"]["items"][0]
        assert line["unitPriceCents"] == 9_950
        assert line["lineTotalCents"] == 19_900
        assert line["unitCostCents"] == 10_000
        assert line["priceSource"] == "customer"
        assert line["itemCategory"] == "ALUMINIUM"

    def test_falls_back_to_group_when_no_customer_price(self, client, api_key, bc_customer, fake_bc):
        _seed_item(fake_bc, "PN10-GRP")
        fake_bc.set_price(2, "PN10-GRP", "GOLD", [{"Unit_Price": 75.00}])
        # All-customers also present but group should win.
        fake_bc.set_price(0, "PN10-GRP", "", [{"Unit_Price": 60.00}])

        res = client.post(
            "/api/external/price-items",
            headers={"X-Service-AI-Key": api_key},
            json={"supplierAccountCode": "ED-001", "items": [{"sku": "PN10-GRP", "quantity": 1}]},
        )
        line = res.json()["data"]["items"][0]
        assert line["unitPriceCents"] == 7_500
        assert line["priceSource"] == "group"

    def test_falls_back_to_all_customers(self, client, api_key, bc_customer, fake_bc):
        _seed_item(fake_bc, "PN10-ALL")
        fake_bc.set_price(0, "PN10-ALL", "", [{"Unit_Price": 50.00}])

        res = client.post(
            "/api/external/price-items",
            headers={"X-Service-AI-Key": api_key},
            json={"supplierAccountCode": "ED-001", "items": [{"sku": "PN10-ALL", "quantity": 1}]},
        )
        line = res.json()["data"]["items"][0]
        assert line["unitPriceCents"] == 5_000
        assert line["priceSource"] == "all_customers"

    def test_falls_back_to_item_default_unit_price(self, client, api_key, bc_customer, fake_bc):
        # No SalesPriceLists entries at any tier; only unitPrice on the item.
        fake_bc.set_item(
            "PN10-DEFAULT",
            {
                "number": "PN10-DEFAULT",
                "displayName": "Has unitPrice only",
                "unitCost": 40,
                "unitPrice": 65,
                "itemCategoryCode": "ALUMINIUM",
            },
        )
        res = client.post(
            "/api/external/price-items",
            headers={"X-Service-AI-Key": api_key},
            json={"supplierAccountCode": "ED-001", "items": [{"sku": "PN10-DEFAULT", "quantity": 1}]},
        )
        line = res.json()["data"]["items"][0]
        assert line["unitPriceCents"] == 6_500
        assert line["priceSource"] == "item_default"

    def test_missing_sku_returns_per_line_missing_entry(self, client, api_key, fake_bc):
        # No item set on fake_bc. The resolver returns None → per-line zero.
        res = client.post(
            "/api/external/price-items",
            headers={"X-Service-AI-Key": api_key},
            json={"supplierAccountCode": "ED-001", "items": [{"sku": "DOES-NOT-EXIST", "quantity": 1}]},
        )
        assert res.status_code == 200
        line = res.json()["data"]["items"][0]
        assert line["unitPriceCents"] == 0
        assert line["priceSource"] == "missing"
        assert line["description"] == "(price not available)"
        # Subtotal stays 0 — the batch did not get rejected.
        assert res.json()["data"]["subtotalCents"] == 0

    def test_quantity_multiplied_into_line_total(self, client, api_key, bc_customer, fake_bc):
        _seed_item(fake_bc, "PN10-QTY")
        fake_bc.set_price(1, "PN10-QTY", "ED-001", [{"Unit_Price": 12.34}])
        res = client.post(
            "/api/external/price-items",
            headers={"X-Service-AI-Key": api_key},
            json={"supplierAccountCode": "ED-001", "items": [{"sku": "PN10-QTY", "quantity": 7}]},
        )
        line = res.json()["data"]["items"][0]
        assert line["unitPriceCents"] == 1_234
        assert line["lineTotalCents"] == 1_234 * 7

    def test_subtotal_sums_across_lines(self, client, api_key, bc_customer, fake_bc):
        _seed_item(fake_bc, "A")
        _seed_item(fake_bc, "B")
        fake_bc.set_price(1, "A", "ED-001", [{"Unit_Price": 10.00}])
        fake_bc.set_price(1, "B", "ED-001", [{"Unit_Price": 5.00}])
        res = client.post(
            "/api/external/price-items",
            headers={"X-Service-AI-Key": api_key},
            json={
                "supplierAccountCode": "ED-001",
                "items": [
                    {"sku": "A", "quantity": 2},
                    {"sku": "B", "quantity": 3},
                ],
            },
        )
        data = res.json()["data"]
        # 2*1000 + 3*500 = 3500
        assert data["subtotalCents"] == 3_500
        assert data["totalCents"] == 3_500  # tax = 0 in v1


# ─────────────────────────────────────────────────────────────────────────────
# Cache behavior
# ─────────────────────────────────────────────────────────────────────────────


class TestCache:
    def test_repeat_call_hits_cache_not_bc(self, client, api_key, bc_customer, fake_bc):
        _seed_item(fake_bc, "CACHE-SKU")
        fake_bc.set_price(1, "CACHE-SKU", "ED-001", [{"Unit_Price": 42.00}])

        # First call — populates the cache.
        client.post(
            "/api/external/price-items",
            headers={"X-Service-AI-Key": api_key},
            json={"supplierAccountCode": "ED-001", "items": [{"sku": "CACHE-SKU", "quantity": 1}]},
        )
        item_call_count_after_first = len(fake_bc.item_calls)
        price_call_count_after_first = len(fake_bc.price_calls)

        # Second call — same args, should be cache-served.
        client.post(
            "/api/external/price-items",
            headers={"X-Service-AI-Key": api_key},
            json={"supplierAccountCode": "ED-001", "items": [{"sku": "CACHE-SKU", "quantity": 1}]},
        )
        assert len(fake_bc.item_calls) == item_call_count_after_first
        assert len(fake_bc.price_calls) == price_call_count_after_first

    def test_different_qty_misses_cache(self, client, api_key, bc_customer, fake_bc):
        _seed_item(fake_bc, "CACHE-QTY")
        fake_bc.set_price(1, "CACHE-QTY", "ED-001", [{"Unit_Price": 42.00}])

        client.post(
            "/api/external/price-items",
            headers={"X-Service-AI-Key": api_key},
            json={"supplierAccountCode": "ED-001", "items": [{"sku": "CACHE-QTY", "quantity": 1}]},
        )
        before = len(fake_bc.item_calls)
        client.post(
            "/api/external/price-items",
            headers={"X-Service-AI-Key": api_key},
            json={"supplierAccountCode": "ED-001", "items": [{"sku": "CACHE-QTY", "quantity": 2}]},
        )
        assert len(fake_bc.item_calls) > before  # qty=2 is a new key
