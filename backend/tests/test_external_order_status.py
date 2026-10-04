"""External order status, shipment, and pickup/delivery (ED-008).

Covers:
    - Auth: 401 missing key, 401 garbage key.
    - Account: 400 when supplierAccountCode is omitted, 404 when it does
      not match the key, and no BC call on that mismatch.
    - Order lookup: 404 unknown, 404 when the order belongs to another
      customer, 400 for a path that is not a document number or GUID.
    - F1: open order lines, partial shipment, tracking passthrough,
      posted-only reconstruction, list drops foreign rows.
    - F2: pickup comment vs center-pickup hardware, delivery load method,
      draft scheduled vs open confirmed, picked up when fully shipped.
    - BC failure: 502 UPSTREAM_ERROR, retryable. A 404 from a GUID lookup
      is an unknown order, not an upstream error.
    - OData filters escape single quotes.
"""
from __future__ import annotations

import os
import sys
import uuid
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
import requests
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import external_orders
from app.api.auth import get_db
from app.db.models import ExternalApiKey, User, UserRole
from app.integrations.bc.client import BusinessCentralClient
from app.services import external_order_status_service
from app.services.external_api_keys_service import create_key
from app.services.external_order_status_service import (
    build_order_view,
    delivery_method,
    fulfillment_status,
)


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
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
    user = User(
        email="admin@test.local",
        password_hash="x",
        role=UserRole.ADMIN,
        is_active=True,
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


@pytest.fixture
def primary_key(session, admin_user):
    _row, plaintext = create_key(
        session,
        name="ED-008 test key",
        supplier_account_code="ED-001",
        created_by_user_id=admin_user.id,
    )
    return plaintext


@pytest.fixture
def other_key(session, admin_user):
    _row, plaintext = create_key(
        session,
        name="ED-008 other-account key",
        supplier_account_code="ED-OTHER",
        created_by_user_id=admin_user.id,
    )
    return plaintext


@pytest.fixture
def app(db_factory):
    test_app = FastAPI()
    test_app.include_router(external_orders.router)

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


class FakeBcClient:
    def __init__(self) -> None:
        self.orders_by_number: Dict[str, Optional[Dict[str, Any]]] = {}
        self.orders_by_id: Dict[str, Dict[str, Any]] = {}
        self.lines_by_id: Dict[str, List[Dict[str, Any]]] = {}
        self.shipments_by_order: Dict[str, List[Dict[str, Any]]] = {}
        self.orders_for_customer: Dict[str, Any] = {
            "value": [],
            "complete": True,
        }
        self.queue: List[Dict[str, Any]] = []
        self.posted_headers: List[Dict[str, Any]] = []
        self.picking_available = True
        self.fail: Optional[Exception] = None
        self.guid_status: Optional[int] = None
        self.calls: List[str] = []

    def _boom(self) -> None:
        if self.fail is not None:
            raise self.fail

    def get_sales_order_with_lines_by_number(self, order_number: str, company_id=None):
        self.calls.append(f"order:{order_number}")
        self._boom()
        return self.orders_by_number.get(order_number)

    def get_sales_order(self, order_id: str, company_id=None):
        self.calls.append(f"guid:{order_id}")
        self._boom()
        if self.guid_status == 404:
            response = requests.Response()
            response.status_code = 404
            raise requests.HTTPError("missing", response=response)
        return self.orders_by_id[order_id]

    def get_order_lines(self, order_id: str, company_id=None):
        self.calls.append(f"lines:{order_id}")
        self._boom()
        return self.lines_by_id.get(order_id, [])

    def get_sales_shipments_by_order_number(self, order_number: str, company_id=None):
        self.calls.append(f"ship:{order_number}")
        self._boom()
        return self.shipments_by_order.get(order_number, [])

    def get_sales_orders_by_customer_number(self, customer_number: str, company_id=None):
        self.calls.append(f"list:{customer_number}")
        self._boom()
        return self.orders_for_customer

    def get_picking_queue(self, company_id=None):
        self.calls.append("queue")
        return list(self.queue)

    def get_posted_picking_headers(self, sales_order_no=None, company_id=None):
        self.calls.append(f"posted-pick:{sales_order_no}")
        return [
            row for row in self.posted_headers
            if sales_order_no is None or row.get("salesOrderNo") == sales_order_no
        ]

    def picking_api_available(self) -> bool:
        return self.picking_available


@pytest.fixture
def fake_bc(monkeypatch):
    fake = FakeBcClient()
    monkeypatch.setattr(external_order_status_service, "bc_client", fake)
    return fake


ORDER_ID = "8f1c2c3a-0000-4000-8000-000000000001"


def _line(item, qty, shipped, line_type="Item", sequence=10000, description=None):
    return {
        "sequence": sequence,
        "lineType": line_type,
        "lineObjectNumber": item,
        "description": description or item,
        "quantity": qty,
        "shippedQuantity": shipped,
        "unitOfMeasureCode": "PCS",
    }


def _order(**overrides):
    base = {
        "id": ORDER_ID,
        "number": "SO-003132",
        "customerNumber": "ED-001",
        "customerName": "Elevated Doors",
        "externalDocumentNumber": "ED-PO-100",
        "status": "Open",
        "orderDate": "2026-09-01",
        "requestedDeliveryDate": "2026-10-15",
        "currencyCode": "CAD",
        "totalAmountExcludingTax": 1000,
        "totalTaxAmount": 130,
        "totalAmountIncludingTax": 1130,
        "fullyShipped": False,
        "shipmentMethodCode": None,
        "shipToName": "Elevated Doors",
        "shipToContact": "Joey",
        "shipToAddressLine1": "1 Yard Rd",
        "shipToCity": "Calgary",
        "shipToState": "AB",
        "shipToPostCode": "T2P 1A1",
        "shipToCountry": "CA",
        "salesOrderLines": [_line("PN65-18405-0800", 4, 0)],
    }
    base.update(overrides)
    return base


def _get(client, key, path, account="ED-001"):
    return client.get(
        path,
        params={"supplierAccountCode": account},
        headers={"X-Service-AI-Key": key},
    )


# ─────────────────────────────────────────────────────────────────────────────
# Pure classification
# ─────────────────────────────────────────────────────────────────────────────


class TestClassification:
    def test_partial_and_full_shipment_status(self):
        lines = [
            {"lineType": "Item", "itemNo": "PN65", "quantity": 4, "shippedQuantity": 1},
        ]
        assert fulfillment_status(
            lines, fully_shipped_flag=False, posted_only=False, shipment_count=1
        ) == "partially_shipped"
        lines[0]["shippedQuantity"] = 4
        assert fulfillment_status(
            lines, fully_shipped_flag=False, posted_only=False, shipment_count=1
        ) == "fully_shipped"

    def test_comment_lines_do_not_count_as_quantity(self):
        lines = [
            {"lineType": "Comment", "itemNo": None, "quantity": 0, "shippedQuantity": 0},
        ]
        assert fulfillment_status(
            lines, fully_shipped_flag=False, posted_only=False, shipment_count=0
        ) == "not_shipped"

    def test_center_pickup_kit_is_not_a_pickup_order(self):
        lines = [
            {"lineType": "Item", "description": "CENTER PICKUP KIT (2 PER DOOR)"},
        ]
        assert delivery_method(lines, None, None)["method"] == "unknown"

    def test_pickup_banner_comment_wins(self):
        lines = [
            {
                "lineType": "Comment",
                "description": "** PICKUP: This order is quoted for customer pickup **",
            },
            {"lineType": "Item", "description": "CENTER PICKUP KIT"},
        ]
        found = delivery_method(lines, "DELIVERY", "Delivery")
        assert found == {"method": "pickup", "methodSource": "order_comment"}

    def test_build_view_passes_tracking_through(self):
        view = build_order_view(
            _order(),
            [{
                "id": "ship-1",
                "number": "SS-000451",
                "orderNumber": "SO-003132",
                "customerNumber": "ED-001",
                "shipmentDate": "2026-09-20",
                "postingDate": "2026-09-20",
                "packageTrackingNo": "1Z999",
                "shippingAgentCode": "UPS",
                "shipToName": "Elevated Doors",
            }],
            {"available": False, "loadMethod": None, "shipmentDate": None, "posted": False},
            posted_only=False,
        )
        assert view["shipments"][0]["trackingNumber"] == "1Z999"
        assert view["shipments"][0]["carrier"] == "UPS"
        # A posted shipment while item quantity is still outstanding is partial.
        assert view["fulfillmentStatus"] == "partially_shipped"
        assert view["fulfillment"]["confirmation"] == "partially_fulfilled"
        assert view["outstandingKnown"] is True


# ─────────────────────────────────────────────────────────────────────────────
# Auth and account binding
# ─────────────────────────────────────────────────────────────────────────────


class TestAuth:
    def test_401_missing_header(self, client, fake_bc):
        res = client.get("/api/external/orders", params={"supplierAccountCode": "ED-001"})
        assert res.status_code == 401
        assert res.json()["detail"]["error"]["code"] == "UNAUTHORIZED"
        assert fake_bc.calls == []

    def test_401_garbage_key(self, client, fake_bc):
        res = client.get(
            "/api/external/orders",
            params={"supplierAccountCode": "ED-001"},
            headers={"X-Service-AI-Key": "sai_live_NOPENOPENOPENOPENOPENOPE"},
        )
        assert res.status_code == 401
        assert fake_bc.calls == []

    def test_400_missing_account(self, client, primary_key, fake_bc):
        res = client.get(
            "/api/external/orders",
            headers={"X-Service-AI-Key": primary_key},
        )
        assert res.status_code == 400
        body = res.json()
        assert body["ok"] is False
        assert body["error"]["code"] == "INVALID_REQUEST"
        assert fake_bc.calls == []

    def test_404_cross_key_account_and_no_bc_call(self, client, primary_key, fake_bc):
        res = _get(client, primary_key, "/api/external/orders", account="ED-OTHER")
        assert res.status_code == 404
        body = res.json()
        assert body["error"]["code"] == "NOT_FOUND"
        assert body["error"]["message"] == "Supplier account not found"
        assert fake_bc.calls == []


# ─────────────────────────────────────────────────────────────────────────────
# F1 order status and shipment
# ─────────────────────────────────────────────────────────────────────────────


class TestOrderStatus:
    def test_open_order_partial_shipment(self, client, primary_key, fake_bc):
        fake_bc.orders_by_number["SO-003132"] = _order(
            salesOrderLines=[
                _line("PN65-18405-0800", 4, 2),
                _line(None, 0, 0, line_type="Comment", sequence=20000,
                      description="Freight note"),
            ],
        )
        fake_bc.shipments_by_order["SO-003132"] = [{
            "id": "ship-1",
            "number": "SS-000451",
            "orderNumber": "SO-003132",
            "customerNumber": "ED-001",
            "shipmentDate": "2026-09-20",
            "postingDate": "2026-09-20",
            "packageTrackingNo": "1Z999",
            "shippingAgentCode": "UPS",
            "shipToName": "Elevated Doors",
            "shipToCity": "Calgary",
        }]
        res = _get(client, primary_key, "/api/external/orders/SO-003132")
        assert res.status_code == 200
        data = res.json()["data"]
        assert data["orderNumber"] == "SO-003132"
        assert data["status"] == "Open"
        assert data["source"] == "open_order"
        assert data["fulfillmentStatus"] == "partially_shipped"
        assert data["outstandingKnown"] is True
        assert data["lines"][0]["outstandingQuantity"] == 2
        assert data["lines"][1]["lineType"] == "Comment"
        assert data["shipments"][0]["trackingNumber"] == "1Z999"
        assert data["shipments"][0]["carrier"] == "UPS"
        assert data["shipTo"]["city"] == "Calgary"
        assert data["fulfillment"]["shipmentDate"] == "2026-09-20"
        assert data["fulfillment"]["confirmation"] == "partially_fulfilled"

    def test_404_unknown_order(self, client, primary_key, fake_bc):
        res = _get(client, primary_key, "/api/external/orders/SO-999999")
        assert res.status_code == 404
        assert res.json()["error"]["code"] == "NOT_FOUND"
        assert res.json()["error"]["message"] == "Order not found"

    def test_404_order_owned_by_someone_else(self, client, primary_key, fake_bc):
        fake_bc.orders_by_number["SO-003132"] = _order(customerNumber="OTHER")
        res = _get(client, primary_key, "/api/external/orders/SO-003132")
        assert res.status_code == 404
        assert res.json()["error"]["message"] == "Order not found"
        assert "ship:SO-003132" not in fake_bc.calls

    def test_400_rejects_filter_injection(self, client, primary_key, fake_bc):
        res = _get(client, primary_key, "/api/external/orders/SO-1'%20or%201%20eq%201")
        assert res.status_code == 400
        assert res.json()["error"]["code"] == "INVALID_REQUEST"
        assert fake_bc.calls == []

    def test_posted_order_reconstructs_from_shipments(self, client, primary_key, fake_bc):
        fake_bc.shipments_by_order["SO-003132"] = [{
            "id": "ship-9",
            "number": "SS-000900",
            "orderNumber": "SO-003132",
            "customerNumber": "ED-001",
            "customerName": "Elevated Doors",
            "shipmentDate": "2026-08-01",
            "postingDate": "2026-08-01",
            "currencyCode": "CAD",
            "shipToName": "Elevated Doors",
            "shipToCity": "Airdrie",
        }]
        res = _get(client, primary_key, "/api/external/orders/SO-003132")
        assert res.status_code == 200
        data = res.json()["data"]
        assert data["source"] == "posted_shipment"
        assert data["status"] == "Posted"
        assert data["fulfillmentStatus"] == "fully_shipped"
        assert data["outstandingKnown"] is False
        assert data["lines"] == []
        assert data["shipments"][0]["shipmentNumber"] == "SS-000900"
        assert data["shipments"][0]["trackingNumber"] is None

    def test_blank_customer_on_shipment_stays_with_an_owned_order(self, client, primary_key, fake_bc):
        fake_bc.orders_by_number["SO-003132"] = _order()
        fake_bc.shipments_by_order["SO-003132"] = [{
            "id": "ship-1",
            "number": "SS-1",
            "orderNumber": "SO-003132",
            "shipmentDate": "2026-09-20",
            "packageTrackingNo": "TRACK-1",
        }]
        res = _get(client, primary_key, "/api/external/orders/SO-003132")
        assert res.status_code == 200
        assert res.json()["data"]["shipments"][0]["trackingNumber"] == "TRACK-1"

    def test_foreign_posted_shipment_is_not_found(self, client, primary_key, fake_bc):
        fake_bc.shipments_by_order["SO-003132"] = [{
            "number": "SS-1",
            "orderNumber": "SO-003132",
            "customerNumber": "OTHER",
        }]
        res = _get(client, primary_key, "/api/external/orders/SO-003132")
        assert res.status_code == 404

    def test_guid_404_from_bc_is_not_found(self, client, primary_key, fake_bc):
        fake_bc.guid_status = 404
        res = _get(client, primary_key, f"/api/external/orders/{ORDER_ID}")
        assert res.status_code == 404
        assert res.json()["error"]["code"] == "NOT_FOUND"

    def test_guid_happy_path(self, client, primary_key, fake_bc):
        fake_bc.orders_by_id[ORDER_ID] = _order(salesOrderLines=[])
        fake_bc.lines_by_id[ORDER_ID] = [_line("PN65-18405-0800", 1, 0)]
        res = _get(client, primary_key, f"/api/external/orders/{ORDER_ID}")
        assert res.status_code == 200
        assert res.json()["data"]["orderNumber"] == "SO-003132"
        assert res.json()["data"]["lines"][0]["itemNo"] == "PN65-18405-0800"

    def test_bc_failure_is_502(self, client, primary_key, fake_bc):
        fake_bc.fail = RuntimeError("bc down")
        res = _get(client, primary_key, "/api/external/orders/SO-003132")
        assert res.status_code == 502
        body = res.json()["error"]
        assert body["code"] == "UPSTREAM_ERROR"
        assert body["retryable"] is True
        assert "bc down" not in body["message"]

    def test_list_keeps_only_this_customer(self, client, primary_key, fake_bc):
        fake_bc.orders_for_customer = {
            "value": [
                _order(number="SO-000002", orderDate="2026-09-02"),
                _order(number="SO-000001", orderDate="2026-09-01", customerNumber="OTHER"),
                _order(number="SO-000003", orderDate="2026-09-03", shipmentMethodCode="DEL"),
            ],
            "complete": True,
        }
        res = _get(client, primary_key, "/api/external/orders")
        assert res.status_code == 200
        data = res.json()["data"]
        assert data["customerNumber"] == "ED-001"
        assert data["complete"] is True
        numbers = [row["orderNumber"] for row in data["orders"]]
        assert numbers == ["SO-000003", "SO-000002"]
        delivered = next(row for row in data["orders"] if row["orderNumber"] == "SO-000003")
        assert delivered["method"] == "delivery"


# ─────────────────────────────────────────────────────────────────────────────
# F2 pickup and delivery
# ─────────────────────────────────────────────────────────────────────────────


class TestFulfillment:
    def test_pickup_comment_open_order_is_confirmed(self, client, primary_key, fake_bc):
        fake_bc.orders_by_number["SO-003132"] = _order(
            salesOrderLines=[
                _line(
                    None, 0, 0, line_type="Comment", sequence=10000,
                    description="** PICKUP: This order is quoted for customer pickup **",
                ),
                _line("PN65-18405-0800", 2, 0, sequence=20000),
            ],
        )
        res = _get(client, primary_key, "/api/external/orders/SO-003132/fulfillment")
        assert res.status_code == 200
        data = res.json()["data"]
        assert data["method"] == "pickup"
        assert data["methodSource"] == "order_comment"
        assert data["scheduledDate"] == "2026-10-15"
        assert data["confirmed"] is True
        assert data["confirmation"] == "confirmed"
        assert data["fulfillmentStatus"] == "not_shipped"

    def test_draft_with_a_date_is_scheduled_not_confirmed(self, client, primary_key, fake_bc):
        fake_bc.orders_by_number["SO-003132"] = _order(status="Draft")
        res = _get(client, primary_key, "/api/external/orders/SO-003132/fulfillment")
        data = res.json()["data"]
        assert data["confirmed"] is False
        assert data["confirmation"] == "scheduled"

    def test_fully_shipped_pickup_is_picked_up(self, client, primary_key, fake_bc):
        fake_bc.orders_by_number["SO-003132"] = _order(
            fullyShipped=True,
            salesOrderLines=[
                _line(
                    None, 0, 0, line_type="Comment", sequence=10000,
                    description="** PICKUP: customer pickup **",
                ),
                _line("PN65-18405-0800", 2, 2, sequence=20000),
            ],
        )
        fake_bc.shipments_by_order["SO-003132"] = [{
            "id": "ship-1",
            "number": "SS-1",
            "orderNumber": "SO-003132",
            "customerNumber": "ED-001",
            "shipmentDate": "2026-10-16",
        }]
        res = _get(client, primary_key, "/api/external/orders/SO-003132/fulfillment")
        data = res.json()["data"]
        assert data["method"] == "pickup"
        assert data["confirmation"] == "picked_up"
        assert data["confirmed"] is True
        assert data["shipmentDate"] == "2026-10-16"

    def test_load_method_delivery_on_posted_order(self, client, primary_key, fake_bc):
        fake_bc.shipments_by_order["SO-003132"] = [{
            "id": "ship-1",
            "number": "SS-1",
            "orderNumber": "SO-003132",
            "customerNumber": "ED-001",
            "shipmentDate": "2026-08-02",
        }]
        fake_bc.posted_headers = [{
            "salesOrderNo": "SO-003132",
            "customerNo": "ED-001",
            "loadMethod": "Delivery",
            "shipmentNo": "SS-1",
            "postingDate": "2026-08-02",
        }]
        res = _get(client, primary_key, "/api/external/orders/SO-003132/fulfillment")
        data = res.json()["data"]
        assert data["method"] == "delivery"
        assert data["methodSource"] == "load_method"
        assert data["confirmation"] == "delivered"
        assert data["picking"]["posted"] is True
        assert data["picking"]["loadMethod"] == "Delivery"
        assert data["picking"]["available"] is True

    def test_other_customer_picking_row_is_ignored(self, client, primary_key, fake_bc):
        fake_bc.orders_by_number["SO-003132"] = _order(shipmentMethodCode=None)
        fake_bc.queue = [{
            "salesOrderNo": "SO-003132",
            "customerNo": "ED-OTHER",
            "loadMethod": "Pickup",
            "status": "Picking",
        }]
        res = _get(client, primary_key, "/api/external/orders/SO-003132/fulfillment")
        data = res.json()["data"]
        assert data["method"] == "unknown"
        assert data["picking"]["queueStatus"] is None

    def test_fulfillment_404_matches_order_404(self, client, primary_key, other_key, fake_bc):
        fake_bc.orders_by_number["SO-003132"] = _order()
        res = _get(
            client, other_key, "/api/external/orders/SO-003132/fulfillment", account="ED-OTHER",
        )
        assert res.status_code == 404
        assert res.json()["error"]["message"] == "Order not found"


class TestODataEscaping:
    def test_customer_and_order_filters_escape_quotes(self):
        client = BusinessCentralClient.__new__(BusinessCentralClient)
        client.company_id = "company-guid"
        seen = {}

        def collect(endpoint, label, max_pages=25):
            seen["list"] = endpoint
            return {"value": [], "complete": True}

        def make(method, endpoint, **kwargs):
            seen["make"] = endpoint
            return {"value": []}

        client._collect_v2 = collect
        client._make_request = make
        client.get_sales_orders_by_customer_number("O'Brien")
        client.get_sales_order_with_lines_by_number("SO-1")
        order_filter = seen["make"]
        client.get_sales_shipments_by_order_number("SO-1'x")
        assert "customerNumber eq 'O''Brien'" in seen["list"]
        assert "number eq 'SO-1'" in order_filter
        assert "$expand=salesOrderLines" in order_filter
        assert "orderNumber eq 'SO-1''x'" in seen["make"]
