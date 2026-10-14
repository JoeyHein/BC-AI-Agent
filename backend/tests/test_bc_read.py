"""Read-only BC routes return headers and every line, including comments."""
from __future__ import annotations

import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import bc_read
from app.api.admin_customers import get_current_admin, get_db as admin_get_db
from app.api.admin_customers import router as admin_customers_router
from app.api.staff_principal import require_staff
from app.db.database import get_db
from app.db.models import BCCustomer, User, UserRole

QUOTE_ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
ORDER_ID = "bbbbbbbb-bbbb-cccc-dddd-eeeeeeeeeeee"


def _quote_header():
    return {
        "@odata.etag": "W/\"ignore\"",
        "id": QUOTE_ID,
        "number": "SQ-003132",
        "customerNumber": "ABES",
        "customerName": "Abe's Door Service LTD",
        "status": "Open",
        "validUntilDate": "2026-12-01",
        "totalAmountExcludingTax": 1000.0,
        "totalTaxAmount": 50.0,
        "totalAmountIncludingTax": 1050.0,
        "salesQuoteLines": [{"lineType": "Item", "description": "should not leak from the header"}],
    }


def _lines():
    return [
        {
            "@odata.etag": "W/\"line\"",
            "id": "line-item",
            "sequence": 20000,
            "lineType": "Item",
            "lineObjectNumber": "PN10",
            "description": "Panel",
            "quantity": 2,
            "unitPrice": 10,
        },
        {
            "id": "line-comment",
            "sequence": 10000,
            "lineType": "Comment",
            "lineObjectNumber": "",
            "description": "18 x 7 BCXL, NEW BROWN",
            "quantity": 0,
        },
    ]


def test_public_lines_keep_comments_and_drop_odata():
    lines = bc_read.public_lines(_lines())
    assert [line["lineType"] for line in lines] == ["Comment", "Item"]
    assert lines[0]["description"].startswith("18 x 7")
    assert all("@odata.etag" not in line for line in lines)


def test_quote_by_number_returns_header_and_comment_lines(monkeypatch):
    monkeypatch.setattr(bc_read, "_lookup_bc_quote", lambda kind, value: _quote_header())
    monkeypatch.setattr(
        bc_read.bc_client,
        "get_document_lines",
        lambda path: _lines(),
    )
    app = FastAPI()
    app.include_router(bc_read.router)
    app.dependency_overrides[require_staff] = lambda: object()
    client = TestClient(app)

    response = client.get("/api/bc/sales-quotes/3132")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["number"] == "SQ-003132"
    assert body["customerNumber"] == "ABES"
    assert body["customerName"] == "Abe's Door Service LTD"
    assert body["status"] == "Open"
    assert body["validUntilDate"] == "2026-12-01"
    assert body["totalAmountIncludingTax"] == 1050.0
    assert "@odata.etag" not in body
    assert "salesQuoteLines" not in body
    assert [line["lineType"] for line in body["lines"]] == ["Comment", "Item"]


def test_quote_list_is_paged_and_searches_by_number(monkeypatch):
    seen = {}

    def list_sales_quotes(search=None, skip=0, top=50, company_id=None):
        seen.update(search=search, skip=skip, top=top)
        return [_quote_header(), {**_quote_header(), "number": "SQ-003131"}]

    monkeypatch.setattr(bc_read.bc_client, "list_sales_quotes", list_sales_quotes)
    app = FastAPI()
    app.include_router(bc_read.router)
    app.dependency_overrides[require_staff] = lambda: object()
    client = TestClient(app)

    response = client.get("/api/bc/sales-quotes", params={"search": "3132", "offset": 20, "top": 10})
    assert response.status_code == 200, response.text
    body = response.json()
    assert seen == {"search": "3132", "skip": 20, "top": 10}
    assert body["skip"] == 20
    assert body["count"] == 2
    assert body["quotes"][0]["number"] == "SQ-003132"
    assert "lines" not in body["quotes"][0]


def test_sales_order_and_purchase_order_include_lines(monkeypatch):
    calls = []

    def lines(path):
        calls.append(path)
        return _lines()

    monkeypatch.setattr(bc_read.bc_client, "get_document_lines", lines)
    monkeypatch.setattr(
        bc_read.bc_client,
        "get_sales_order_by_number",
        lambda number: {"id": ORDER_ID, "number": number, "status": "Open", "customerNumber": "ABES"},
    )
    monkeypatch.setattr(
        bc_read.bc_client,
        "get_purchase_order_by_number",
        lambda number: {"id": ORDER_ID, "number": number, "status": "Released", "vendorNumber": "UPW"},
    )
    app = FastAPI()
    app.include_router(bc_read.router)
    app.dependency_overrides[require_staff] = lambda: object()
    client = TestClient(app)

    order = client.get("/api/bc/sales-orders/857")
    assert order.status_code == 200, order.text
    assert order.json()["number"] == "SO-000857"
    assert order.json()["lines"][0]["lineType"] == "Comment"
    assert calls[-1] == f"salesOrders({ORDER_ID})/salesOrderLines"

    po = client.get("/api/bc/purchase-orders/PO-000962")
    assert po.status_code == 200, po.text
    assert po.json()["status"] == "Released"
    assert len(po.json()["lines"]) == 2
    assert calls[-1] == f"purchaseOrders({ORDER_ID})/purchaseOrderLines"


def test_posted_invoice_includes_lines_and_draft_is_hidden(monkeypatch):
    monkeypatch.setattr(bc_read.bc_client, "get_document_lines", lambda path: _lines())
    monkeypatch.setattr(
        bc_read.bc_client,
        "get_sales_invoice_by_number",
        lambda number: {
            "id": ORDER_ID,
            "number": number,
            "status": "Paid",
            "customerNumber": "ABES",
            "totalAmountIncludingTax": 80,
        },
    )

    def purchase(number):
        if number.endswith("DRAFT"):
            return {"id": ORDER_ID, "number": number, "status": "Draft"}
        return {"id": ORDER_ID, "number": number, "status": "Open", "vendorNumber": "UPW"}

    monkeypatch.setattr(bc_read.bc_client, "get_purchase_invoice_by_number", purchase)
    app = FastAPI()
    app.include_router(bc_read.router)
    app.dependency_overrides[require_staff] = lambda: object()
    client = TestClient(app)

    sales = client.get("/api/bc/sales-invoices/PS-100001")
    assert sales.status_code == 200, sales.text
    assert sales.json()["status"] == "Paid"
    assert sales.json()["lines"][1]["lineObjectNumber"] == "PN10"

    draft = client.get("/api/bc/purchase-invoices/PI-DRAFT")
    assert draft.status_code == 404
    assert "not a posted" in draft.json()["detail"]

    posted = client.get("/api/bc/purchase-invoices/PI-100001")
    assert posted.status_code == 200, posted.text
    assert len(posted.json()["lines"]) == 2


def test_item_search_returns_price_cost_and_inventory(monkeypatch):
    monkeypatch.setattr(
        bc_read.bc_client,
        "search_items_for_read",
        lambda term, top: [{
            "number": "PN10",
            "displayName": "Panel 10",
            "unitPrice": 12.5,
            "unitCost": 8,
            "inventory": 40,
        }],
    )
    monkeypatch.setattr(
        bc_read.bc_client,
        "search_items",
        lambda number: [{
            "number": number,
            "displayName": "Panel 10",
            "unitPrice": 12.5,
            "unitCost": 8,
            "inventory": 40,
        }],
    )
    app = FastAPI()
    app.include_router(bc_read.router)
    app.dependency_overrides[require_staff] = lambda: object()
    client = TestClient(app)

    found = client.get("/api/bc/items", params={"search": "PN"})
    assert found.status_code == 200, found.text
    item = found.json()["items"][0]
    assert item["unitPrice"] == 12.5
    assert item["unitCost"] == 8
    assert item["inventory"] == 40

    one = client.get("/api/bc/items/PN10")
    assert one.status_code == 200, one.text
    assert one.json()["number"] == "PN10"


def test_price_lines_and_missing_order(monkeypatch):
    monkeypatch.setattr(
        bc_read.bc_client,
        "get_sales_price_lines",
        lambda **kwargs: {"available": True, "error": None, "entries": [{"Product_No": "PN10", "Unit_Price": 9}]},
    )
    monkeypatch.setattr(bc_read.bc_client, "get_sales_order_by_number", lambda number: None)
    app = FastAPI()
    app.include_router(bc_read.router)
    app.dependency_overrides[require_staff] = lambda: object()
    client = TestClient(app)

    prices = client.get("/api/bc/sales-price-lines", params={"item_no": "PN10", "source_type": 2, "source_no": "GOLD"})
    assert prices.status_code == 200, prices.text
    assert prices.json()["lines"][0]["Unit_Price"] == 9

    missing = client.get("/api/bc/sales-orders/SO-000001")
    assert missing.status_code == 404


def _customer_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    BCCustomer.__table__.create(engine, checkfirst=True)
    User.__table__.create(engine, checkfirst=True)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = Session()
    db.add(BCCustomer(
        bc_customer_id="guid-abes",
        company_name="Abe's Door Service LTD",
        contact_name="Allen",
        email="allen@abesdoor.ca",
        bc_price_group="GOLD",
        pricing_tier="gold",
        customer_metadata={"number": "ABES", "blocked": ""},
        created_at=datetime.utcnow(),
    ))
    db.commit()
    return Session


def test_customers_include_price_group(monkeypatch):
    Session = _customer_session()
    monkeypatch.setattr(bc_read.bc_client, "get_customer_by_number", lambda number: None)

    def override_db():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    app = FastAPI()
    app.include_router(bc_read.router)
    app.include_router(admin_customers_router)
    app.dependency_overrides[require_staff] = lambda: object()
    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[admin_get_db] = override_db
    app.dependency_overrides[get_current_admin] = lambda: User(
        id=1,
        email="joey@opendc.ca",
        password_hash="x",
        role=UserRole.ADMIN,
        is_active=True,
        user_type="INTERNAL",
    )
    client = TestClient(app)

    listed = client.get("/api/bc/customers", params={"search": "ABES"})
    assert listed.status_code == 200, listed.text
    row = listed.json()["customers"][0]
    assert row["customer_number"] == "ABES"
    assert row["bc_price_group"] == "GOLD"
    assert row["company_name"].startswith("Abe")

    one = client.get("/api/bc/customers/ABES")
    assert one.status_code == 200, one.text
    assert one.json()["bc_price_group"] == "GOLD"

    picker = client.get("/api/admin/customers/bc-customers", params={"q": "Abe"})
    assert picker.status_code == 200, picker.text
    assert picker.json()[0]["bc_price_group"] == "GOLD"
    assert picker.json()[0]["customer_number"] == "ABES"


def test_customer_number_falls_through_to_bc(monkeypatch):
    Session = _customer_session()
    monkeypatch.setattr(
        bc_read.bc_client,
        "get_customer_by_number",
        lambda number: {
            "id": "guid-bakk",
            "number": "BAKK",
            "displayName": "Baker Doors",
            "email": "a@baker.test",
        },
    )
    monkeypatch.setattr(bc_read.bc_client, "get_customer_price_group", lambda number: "SILVER")

    def override_db():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    app = FastAPI()
    app.include_router(bc_read.router)
    app.dependency_overrides[require_staff] = lambda: object()
    app.dependency_overrides[get_db] = override_db
    client = TestClient(app)

    response = client.get("/api/bc/customers/BAKK")
    assert response.status_code == 200, response.text
    assert response.json()["customer_number"] == "BAKK"
    assert response.json()["bc_price_group"] == "SILVER"
