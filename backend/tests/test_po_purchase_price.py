"""PO create paths leave purchase price to Business Central.

directUnitCost is omitted unless someone typed an override. A missing
price is not sent as zero. Draft review warns when the vendor price list
or the line price is missing, or when that price differs from the item card.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import requests
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.api.bc_read import require_staff, router as bc_read_router
from app.api.purchasing import get_current_admin, router as purchasing_router
from app.db.models import ExternalPurchaseOrder, POAgentLog, User, UserRole
from app.integrations.bc.client import BusinessCentralClient
from app.services import draft_po_review_service as review_mod
from app.services import external_purchase_order_service
from app.services.auto_po_service import AutoPoService
from app.services.draft_po_review_service import validate_po
from app.services.external_purchase_order_service import (
    PoLine,
    PoResult,
    _build_line_data,
    create_external_purchase_order,
)
from app.services.po_agent_service import POAgentService
from app.services.purchasing_po_service import purchasing_po_service
from app.services.so_po_generation_service import _write_plan_lines
from app.services.vendor_receipt_lead_time import receipt_plan_for_new_po


def _item_bodies(calls):
    return [body for body in calls if body.get("lineType") == "Item"]


class RecordingBC:
    def __init__(self):
        self.lines = []
        self.updates = []

    def create_purchase_order(self, body, company_id=None):
        return {"id": "po-1", "number": "PO-1", "status": "Draft"}

    def add_purchase_order_line(self, po_id, body, company_id=None):
        self.lines.append(body)
        return {"id": f"line-{len(self.lines)}"}

    def update_purchase_order_line(self, po_id, line_id, body, company_id=None):
        self.updates.append(body)
        return body

    def get_purchase_order_by_number(self, number):
        return {
            "id": "po-1",
            "number": number,
            "status": "Draft",
            "purchaseOrderLines": [{
                "id": "ln-1",
                "sequence": 10000,
                "lineType": "Item",
                "lineObjectNumber": "PN10",
                "description": "Panel",
                "quantity": 2,
                "directUnitCost": 8,
                "unitOfMeasureCode": "EA",
                "receivedQuantity": 0,
            }],
        }

    def get_purchase_order_with_lines(self, po_id):
        return self.get_purchase_order_by_number("PO-1")


def test_so_po_omits_direct_unit_cost_unless_overridden(monkeypatch):
    from app.services import so_po_generation_service as svc

    bc = RecordingBC()
    monkeypatch.setattr(svc, "bc_client", bc)
    plan = {
        "customer_name": "Acme",
        "mode": "complete",
        "has_doors": False,
        "by_door": [],
        "shared": {"included": [], "component_shortfall": []},
        "included": [
            {"item_no": "PN10", "description": "Panel", "quantity": 2, "unit_cost": 9.5, "uom": "EA"},
            {"item_no": "HK02", "description": "Kit", "quantity": 1, "unit_cost": 0, "uom": "EA",
             "unit_cost_override": 4.25},
        ],
        "component_shortfall": [],
    }
    _write_plan_lines("po-1", plan, "SO-000001")
    items = _item_bodies(bc.lines)
    assert "directUnitCost" not in items[0]
    assert items[0]["lineObjectNumber"] == "PN10"
    assert items[1]["directUnitCost"] == 4.25


def test_purchasing_generate_omits_item_card_cost(monkeypatch):
    bc = RecordingBC()
    receipt = receipt_plan_for_new_po("UPW", "UPWARDOR")
    monkeypatch.setattr("app.services.purchasing_po_service.bc_client", bc)
    monkeypatch.setattr(
        "app.services.purchasing_po_service.create_purchase_order_with_receipt",
        lambda *args, **kwargs: ({
            "id": "po-1",
            "number": "PO-1",
            "status": "Draft",
            "orderDate": receipt.po_date.isoformat(),
            "requestedReceiptDate": receipt.requested_receipt_date.isoformat(),
        }, receipt),
    )
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    POAgentLog.__table__.create(engine)
    db = sessionmaker(bind=engine)()
    purchasing_po_service.create_with_review_draft(
        db, vendor_no="UPW", vendor_name="UPWARDOR",
        lines=[
            {"item_no": "PN10", "description": "Panel", "quantity": 2, "unit_cost": 10.5},
            {"item_no": "HK02", "description": "Kit", "quantity": 1, "unit_cost": 0,
             "unit_cost_override": 3.5},
        ],
        user_id=1,
        create_review_draft=False,
    )
    items = _item_bodies(bc.lines)
    plain = next(row for row in items if row["lineObjectNumber"] == "PN10")
    overridden = next(row for row in items if row["lineObjectNumber"] == "HK02")
    assert "directUnitCost" not in plain
    assert plain.get("directUnitCost", None) != 0
    assert overridden["directUnitCost"] == 3.5


def test_auto_po_omits_direct_unit_cost_even_when_card_cost_is_zero(monkeypatch):
    bc = RecordingBC()
    monkeypatch.setattr("app.services.auto_po_service.bc_client", bc)
    monkeypatch.setattr(
        "app.services.auto_po_service.create_purchase_order_with_receipt",
        lambda *args, **kwargs: ({"id": "po-1", "number": "PO-1", "status": "Draft"}, None),
    )
    engine = create_engine("sqlite://")
    POAgentLog.__table__.create(engine)
    db = sessionmaker(bind=engine)()
    AutoPoService()._create_bc_draft_po(db, {
        "vendor_no": "UPW",
        "vendor_name": "UPWARDOR",
        "sales_orders": ["SO-1"],
        "estimated_cost": 0,
        "lines": [{
            "item_no": "PN10", "description": "Panel", "quantity": 2,
            "unit_cost": 0, "per_so": {"SO-1": 2},
        }],
    }, "run-1", None)
    items = _item_bodies(bc.lines)
    assert len(items) == 1
    assert "directUnitCost" not in items[0]


def test_po_agent_omits_zero_part_cost(monkeypatch):
    bc = RecordingBC()
    monkeypatch.setattr("app.services.po_agent_service.bc_client", bc)
    po = SimpleNamespace(
        vendor_id="UPW",
        vendor_name="UPWARDOR",
        line_items=[{
            "bc_item_number": "PN10",
            "description": "Panel",
            "quantity": 2,
            "unit_cost": 0,
        }, {
            "bc_item_number": "HK02",
            "description": "Kit",
            "quantity": 1,
            "unit_cost": 9,
            "unit_cost_override": 6.5,
        }],
    )
    POAgentService()._create_bc_purchase_order(po)
    items = _item_bodies(bc.lines)
    assert "directUnitCost" not in items[0]
    assert items[1]["directUnitCost"] == 6.5


def test_external_line_ignores_unit_cost_cents_and_honours_override():
    plain = _build_line_data(PoLine(sku="PN10", quantity=5, unit_cost_cents=700, description="Spring"))
    assert "directUnitCost" not in plain
    omitted = _build_line_data(PoLine(sku="PN10", quantity=5, description="Spring"))
    assert "directUnitCost" not in omitted
    override = _build_line_data(PoLine(
        sku="PN10", quantity=5, unit_cost_cents=700, unit_cost_override_cents=450,
    ))
    assert override["directUnitCost"] == 4.5


def test_external_create_does_not_send_a_default_price(monkeypatch):
    bc = RecordingBC()
    monkeypatch.setattr(external_purchase_order_service, "bc_client", bc)
    engine = create_engine("sqlite://")
    ExternalPurchaseOrder.__table__.create(engine)
    db = sessionmaker(bind=engine)()
    result = create_external_purchase_order(
        db,
        api_key_id=1,
        account_code="ED-001",
        external_po_id="ext-plain",
        po_number=None,
        lines=[PoLine(sku="PN10", quantity=5, unit_cost_cents=700, description="Spring")],
    )
    assert isinstance(result, PoResult)
    assert "directUnitCost" not in bc.lines[0]

    overridden = create_external_purchase_order(
        db,
        api_key_id=1,
        account_code="ED-001",
        external_po_id="ext-override",
        po_number=None,
        lines=[PoLine(sku="PN10", quantity=1, unit_cost_override_cents=450)],
    )
    assert isinstance(overridden, PoResult)
    assert bc.lines[-1]["directUnitCost"] == 4.5


@pytest.fixture
def draft_client(monkeypatch):
    bc = RecordingBC()
    monkeypatch.setattr("app.services.draft_po_lines_service.bc_client", bc)
    admin = User(
        id=1, email="joey@opendc.ca", password_hash="x",
        role=UserRole.ADMIN, is_active=True, user_type="INTERNAL",
    )
    app = FastAPI()
    app.include_router(purchasing_router)
    app.dependency_overrides[get_current_admin] = lambda: admin
    return TestClient(app), bc


def test_draft_add_omits_price_and_honours_override(draft_client):
    client, bc = draft_client
    added = client.post("/api/admin/purchasing/draft-pos/PO-1/lines", json={
        "line_type": "Item",
        "item_no": "PN10",
        "description": "Panel",
        "quantity": 2,
    })
    assert added.status_code == 200, added.text
    assert "directUnitCost" not in bc.lines[-1]

    override = client.post("/api/admin/purchasing/draft-pos/PO-1/lines", json={
        "line_type": "Item",
        "item_no": "HK02",
        "quantity": 1,
        "unit_cost_override": 12.5,
    })
    assert override.status_code == 200, override.text
    assert bc.lines[-1]["directUnitCost"] == 12.5

    legacy = client.post("/api/admin/purchasing/draft-pos/PO-1/lines", json={
        "line_type": "Item",
        "item_no": "PL10",
        "quantity": 4,
        "unit_cost": 1.25,
    })
    assert legacy.status_code == 200, legacy.text
    assert bc.lines[-1]["directUnitCost"] == 1.25


def test_draft_edit_leaves_price_unless_it_changes(draft_client):
    client, bc = draft_client
    qty_only = client.patch("/api/admin/purchasing/draft-pos/PO-1/lines/ln-1", json={"quantity": 6})
    assert qty_only.status_code == 200, qty_only.text
    assert bc.updates[-1] == {"quantity": 6}
    assert "directUnitCost" not in bc.updates[-1]

    priced = client.patch(
        "/api/admin/purchasing/draft-pos/PO-1/lines/ln-1",
        json={"unit_cost": 12.5},
    )
    assert priced.status_code == 200, priced.text
    assert bc.updates[-1] == {"directUnitCost": 12.5}


def test_purchase_price_lines_filter_uses_vendor_uom_qty_and_dates(monkeypatch):
    client = BusinessCentralClient.__new__(BusinessCentralClient)
    client.odata_url = "https://bc.example/ODataV4"
    client.company_id = "Open Distribution"
    seen = {}

    def fake_get(url, headers=None, timeout=None):
        seen["url"] = url
        response = requests.Response()
        response.status_code = 200
        response._content = (
            b'{"value":[{"Product_No":"PN10","Direct_Unit_Cost":4.5,'
            b'"Minimum_Quantity":1,"Starting_Date":"2026-01-01","Ending_Date":"2026-12-31"}]}'
        )
        return response

    monkeypatch.setattr(client, "_get_access_token", lambda: "tok")
    monkeypatch.setattr("app.integrations.bc.client.requests.get", fake_get)
    result = client.get_purchase_price_lines(
        item_no="PN10",
        vendor_no="UPW",
        unit_of_measure="EA",
        qty=4,
        as_of_date="2026-10-20",
    )
    assert result["available"] is True
    assert result["entries"][0]["Direct_Unit_Cost"] == 4.5
    url = seen["url"]
    assert "PurchasePriceLists" in url
    assert "Product_No eq 'PN10'" in url
    assert "Source_Type eq 'Vendor'" in url
    assert "Assign_to_No eq 'UPW'" in url
    assert "Unit_of_Measure_Code eq 'EA'" in url
    assert "Minimum_Quantity le 4" in url
    assert "Starting_Date le 2026-10-20" in url
    assert "Ending_Date ge 2026-10-20" in url
    assert "0001-01-01" in url


def test_purchase_price_lines_404_is_unavailable(monkeypatch):
    client = BusinessCentralClient.__new__(BusinessCentralClient)
    client.odata_url = "https://bc.example/ODataV4"
    client.company_id = "Open Distribution"

    def fake_get(url, headers=None, timeout=None):
        response = requests.Response()
        response.status_code = 404
        response._content = b""
        return response

    monkeypatch.setattr(client, "_get_access_token", lambda: "tok")
    monkeypatch.setattr("app.integrations.bc.client.requests.get", fake_get)
    result = client.get_purchase_price_lines(item_no="PN10", vendor_no="UPW", as_of_date="2026-10-20")
    assert result["available"] is False
    assert result["entries"] == []


def _po(lines, vendor="UPW", order_date="2026-10-20"):
    return {
        "id": "guid-po",
        "number": "PO-000100",
        "status": "Draft",
        "vendorNumber": vendor,
        "vendorName": "UPWARDOR",
        "orderDate": order_date,
        "purchaseOrderLines": lines,
    }


def _line(item, cost, qty=2):
    return {
        "lineType": "Item",
        "lineObjectNumber": item,
        "description": f"desc {item}",
        "quantity": qty,
        "directUnitCost": cost,
        "unitOfMeasureCode": "EA",
        "receivedQuantity": 0,
    }


def test_review_warns_when_bc_price_missing_or_differs_from_card(monkeypatch):
    calls = []

    def prices(**kwargs):
        calls.append(kwargs)
        item = kwargs["item_no"]
        if item == "ZERO":
            return {"available": True, "entries": []}
        if item == "DIFF":
            return {"available": True, "entries": [{
                "Product_No": "DIFF",
                "Direct_Unit_Cost": 12,
                "Minimum_Quantity": 1,
                "Starting_Date": "2026-01-01",
                "Unit_of_Measure_Code": "EA",
            }]}
        return {"available": True, "entries": [{
            "Product_No": item,
            "Direct_Unit_Cost": 10,
            "Minimum_Quantity": 0,
            "Starting_Date": "2026-01-01",
        }]}

    monkeypatch.setattr(review_mod.bc_client, "get_purchase_price_lines", prices)
    monkeypatch.setattr(
        review_mod.bc_client,
        "get_items_by_numbers",
        lambda numbers: {n: {"unitCost": 10, "number": n} for n in numbers},
    )
    result = validate_po(_po([
        _line("OK", 10),
        _line("ZERO", 0),
        _line("DIFF", 12),
    ]))
    by_item = {}
    for issue in result["issues"]:
        by_item.setdefault(issue["item_number"], set()).add(issue["code"])
    assert "OK" not in by_item
    assert by_item["ZERO"] == {"bc_price_missing"}
    assert "bc_price_differs_from_item_cost" in by_item["DIFF"]
    assert calls[0]["vendor_no"] == "UPW"
    assert calls[0]["as_of_date"] == "2026-10-20"
    assert calls[0]["unit_of_measure"] == "EA"


def test_review_does_not_invent_a_missing_price_when_lookup_fails(monkeypatch):
    monkeypatch.setattr(
        review_mod.bc_client,
        "get_purchase_price_lines",
        lambda **kwargs: {"available": False, "entries": [], "error": "404"},
    )
    monkeypatch.setattr(review_mod.bc_client, "get_items_by_numbers", lambda numbers: {})
    result = validate_po(_po([_line("BOLT-1", 8)]))
    assert result["issues"] == []


def test_purchase_price_read_route(monkeypatch):
    monkeypatch.setattr(
        "app.api.bc_read.bc_client.get_purchase_price_lines",
        lambda **kwargs: {
            "available": True,
            "error": None,
            "entries": [{"Product_No": "PN10", "Direct_Unit_Cost": 4.5}],
        },
    )
    app = FastAPI()
    app.include_router(bc_read_router)
    app.dependency_overrides[require_staff] = lambda: object()
    client = TestClient(app)
    res = client.get("/api/bc/purchase-price-lines", params={
        "item_no": "PN10", "vendor_no": "UPW", "unit_of_measure": "EA", "qty": 2, "as_of": "2026-10-20",
    })
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["lines"][0]["Direct_Unit_Cost"] == 4.5
    assert body["vendor_no"] == "UPW"
