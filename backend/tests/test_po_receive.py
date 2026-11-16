"""Receive selected purchase-order lines without invoicing.

Dry-run must refuse a quantity above outstanding and must not call Business
Central. A real receipt requires confirm, posts only the named lines, and a
repeat vendor shipment number returns the same receipt.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
import requests
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.api.bc_read import require_staff, router as bc_router
from app.config import settings
from app.db.database import get_db
from app.db.models import AuditTrail, User, UserRole
from app.integrations.bc.client import (
    PURCHASE_ORDER_RECEIPT_LOOKUP_ACTION,
    PURCHASE_ORDER_RECEIVE_ACTION,
    PURCHASE_ORDER_RECEIVE_ENTITY,
    BusinessCentralClient,
    PurchaseOrderReceiveNotPublished,
)
from app.services import po_receive_service as receive_mod
from app.services.staff_permissions import PRESETS, has_permission, permission_for


PO_NUMBER = "PO-001058"
PO_ID = "po-guid-1058"
REPO = Path(__file__).resolve().parents[2]


def _line(item="PN10", qty=30, sequence=10000, **extra):
    row = {
        "id": extra.pop("id", f"ln-{sequence}"),
        "sequence": sequence,
        "lineType": extra.pop("lineType", "Item"),
        "lineObjectNumber": item,
        "description": extra.pop("description", "Panel"),
        "quantity": qty,
        "directUnitCost": 10,
        "unitOfMeasureCode": "EA",
        "receivedQuantity": extra.pop("receivedQuantity", 0),
    }
    row.update(extra)
    return row


def _po(status="Open", lines=None):
    return {
        "id": PO_ID,
        "number": PO_NUMBER,
        "status": status,
        "vendorNumber": "UPW",
        "vendorName": "UPWARDOR",
        "purchaseOrderLines": lines if lines is not None else [
            _line(qty=30, sequence=10000),
            _line(item="HW1", qty=4, sequence=20000, description="Hinge"),
        ],
    }


class MemBC:
    def __init__(self, po):
        self.po = po
        self.receive_calls = []
        self.find_calls = []
        self.release_calls = []
        self.receive_error = None
        self.find_error = None
        self.receipts = {}
        self.next_receipt = "PR-1058"
        self.force_invoiced = False

    def get_purchase_order_by_number(self, number, company_id=None):
        if self.po and self.po.get("number") == number:
            return self.po
        return None

    def get_purchase_order_with_lines(self, po_id, company_id=None):
        if not self.po or self.po.get("id") != po_id:
            err = requests.HTTPError(f"404 missing {po_id}")
            err.response = type("R", (), {"status_code": 404, "text": "missing"})()
            raise err
        return self.po

    def find_posted_purchase_receipt(self, po_id, vendor_shipment_no, company_id=None):
        if self.find_error is not None:
            raise self.find_error
        self.find_calls.append((po_id, vendor_shipment_no))
        return self.receipts.get(vendor_shipment_no, {"postedReceiptNo": ""})

    def receive_purchase_order(self, po_id, vendor_shipment_no, lines_json, company_id=None):
        if self.receive_error is not None:
            raise self.receive_error
        self.receive_calls.append({
            "po_id": po_id,
            "vendor_shipment_no": vendor_shipment_no,
            "lines_json": lines_json,
        })
        released = (self.po.get("status") or "").casefold() == "draft"
        if released:
            self.po["status"] = "Open"
        body = {
            "postedReceiptNo": self.next_receipt,
            "postedReceiptId": "rcpt-guid-1058",
            "idempotent": False,
            "releasedForReceipt": released,
            "invoiced": self.force_invoiced,
            "lastReceivingNo": self.next_receipt,
            "number": self.po.get("number"),
        }
        if vendor_shipment_no:
            self.receipts[vendor_shipment_no] = {
                **body,
                "idempotent": True,
                "postedReceiptNo": self.next_receipt,
            }
        return body

    def release_purchase_order(self, *args, **kwargs):
        self.release_calls.append(args)
        raise AssertionError("receive must not call the release action")


@pytest.fixture
def mem():
    return MemBC(_po())


@pytest.fixture
def session_factory():
    engine = create_engine(
        "sqlite://",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    AuditTrail.__table__.create(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


@pytest.fixture
def client(mem, session_factory, monkeypatch):
    monkeypatch.setattr(receive_mod, "bc_client", mem)
    admin = User(
        id=1,
        email="joey@opendc.ca",
        password_hash="x",
        role=UserRole.ADMIN,
        is_active=True,
        user_type="INTERNAL",
    )
    app = FastAPI()
    app.include_router(bc_router)

    def _db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[require_staff] = lambda: admin
    app.dependency_overrides[get_db] = _db
    return TestClient(app)


def _post(client, body=None, number=PO_NUMBER):
    payload = {"confirm": True, "lines": [{"line_no": 10000, "qty": 30}]}
    if body:
        payload.update(body)
    return client.post(f"/api/bc/purchase-orders/{number}/receive", json=payload)


def _audits(session_factory):
    db = session_factory()
    try:
        return [
            {
                "action": row.action,
                "entity_id": row.entity_id,
                "user_id": row.user_id,
                "details": row.details,
            }
            for row in db.query(AuditTrail).all()
        ]
    finally:
        db.close()


class TestDryRun:
    def test_qty_30_on_po_001058_would_post_and_leave_the_other_line(self, client, mem):
        res = _post(client, {"dry_run": True, "confirm": False, "vendor_shipment_no": "pack-1058"})
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["dry_run"] is True
        assert body["would_post"] is True
        assert body["posted"] is False
        assert body["invoiced"] is False
        assert body["emailed"] is False
        assert body["bc_post_called"] is False
        assert body["would_release"] is False
        assert body["number"] == PO_NUMBER
        assert body["vendor_shipment_no"] == "PACK-1058"
        assert body["lines"] == [{
            "line_no": 10000,
            "qty": 30,
            "outstanding": 30,
            "outstanding_after": 0,
            "item_no": "PN10",
            "description": "Panel",
            "line_type": "Item",
        }]
        assert body["untouched_lines"][0]["line_no"] == 20000
        assert body["untouched_lines"][0]["qty_to_receive"] == 0
        assert mem.receive_calls == []
        assert mem.release_calls == []

    def test_partial_qty_under_outstanding(self, client, mem):
        mem.po["purchaseOrderLines"][0]["quantity"] = 40
        mem.po["purchaseOrderLines"][0]["receivedQuantity"] = 10
        res = _post(client, {"dry_run": True, "lines": [{"line_no": 10000, "qty": 30}]})
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["would_post"] is True
        assert body["lines"][0]["outstanding"] == 30
        assert body["lines"][0]["outstanding_after"] == 0
        assert mem.receive_calls == []

    def test_qty_over_outstanding_does_not_post(self, client, mem):
        res = _post(client, {"dry_run": True, "lines": [{"line_no": 10000, "qty": 31}]})
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["would_post"] is False
        assert body["posted"] is False
        assert body["reasons"][0]["code"] == "qty_exceeds_outstanding"
        assert body["reasons"][0]["outstanding"] == 30
        assert mem.receive_calls == []

    def test_draft_would_release_then_receive(self, client, mem):
        mem.po["status"] = "Draft"
        res = _post(client, {"dry_run": True})
        assert res.status_code == 200, res.text
        assert res.json()["would_release"] is True
        assert res.json()["would_post"] is True
        assert mem.receive_calls == []
        assert mem.po["status"] == "Draft"

    def test_in_review_would_not_post(self, client, mem):
        mem.po["status"] = "In Review"
        res = _post(client, {"dry_run": True})
        assert res.status_code == 200, res.text
        assert res.json()["would_post"] is False
        assert res.json()["reasons"][0]["code"] == "not_receivable_status"
        assert mem.receive_calls == []


class TestPost:
    def test_confirm_posts_only_the_named_line(self, client, mem, session_factory):
        res = _post(client, {"vendor_shipment_no": "PACK-1058"})
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["posted"] is True
        assert body["invoiced"] is False
        assert body["emailed"] is False
        assert body["idempotent"] is False
        assert body["posted_receipt_no"] == "PR-1058"
        assert body["bc_action"] == "Microsoft.NAV.Receive"
        assert body["bc_post_called"] is True
        assert mem.release_calls == []
        assert len(mem.receive_calls) == 1
        sent = mem.receive_calls[0]
        assert sent["po_id"] == PO_ID
        assert sent["vendor_shipment_no"] == "PACK-1058"
        assert sent["lines_json"] == '[{"lineNo":10000,"qty":30}]'
        assert "20000" not in sent["lines_json"]
        assert "receiveAndInvoice" not in sent["lines_json"]
        rows = _audits(session_factory)
        assert rows[-1]["action"] == "purchase_order_receive_received"
        assert rows[-1]["entity_id"] == PO_NUMBER
        assert rows[-1]["user_id"] == "joey@opendc.ca"
        assert rows[-1]["details"]["posted_receipt_no"] == "PR-1058"
        assert rows[-1]["details"]["lines"][0]["qty"] == 30
        assert rows[-1]["details"]["invoiced"] is False
        assert rows[-1]["details"]["emailed"] is False

    def test_draft_is_released_by_the_receive_page_not_the_release_action(self, client, mem):
        mem.po["status"] = "Draft"
        res = _post(client, {"vendor_shipment_no": "PACK-1058"})
        assert res.status_code == 200, res.text
        assert res.json()["released"] is True
        assert res.json()["posted_receipt_no"] == "PR-1058"
        assert mem.release_calls == []
        assert mem.po["status"] == "Open"

    def test_confirm_is_required(self, client, mem):
        res = _post(client, {"confirm": False})
        assert res.status_code == 422, res.text
        assert res.json()["detail"]["reasons"][0]["code"] == "confirm_required"
        assert mem.receive_calls == []

    def test_repeat_vendor_shipment_does_not_post_again(self, client, mem):
        first = _post(client, {"vendor_shipment_no": "pack-1058"})
        assert first.status_code == 200, first.text
        second = _post(client, {"vendor_shipment_no": "PACK-1058", "lines": [{"line_no": 10000, "qty": 30}]})
        assert second.status_code == 200, second.text
        body = second.json()
        assert body["idempotent"] is True
        assert body["posted"] is False
        assert body["posted_receipt_no"] == "PR-1058"
        assert body["invoiced"] is False
        assert body["emailed"] is False
        assert len(mem.receive_calls) == 1

    def test_existing_bc_receipt_is_returned_without_posting(self, client, mem):
        mem.receipts["PACK-1058"] = {
            "postedReceiptNo": "PR-EXISTING",
            "postedReceiptId": "old",
            "idempotent": True,
        }
        res = _post(client, {"vendor_shipment_no": "PACK-1058", "lines": [{"line_no": 10000, "qty": 99}]})
        assert res.status_code == 200, res.text
        assert res.json()["idempotent"] is True
        assert res.json()["posted_receipt_no"] == "PR-EXISTING"
        assert mem.receive_calls == []

    def test_unknown_line_and_missing_po(self, client, mem):
        missing_line = _post(client, {"lines": [{"line_no": 30000, "qty": 1}]})
        assert missing_line.status_code == 422
        assert missing_line.json()["detail"]["reasons"][0]["code"] == "unknown_line"
        missing_po = _post(client, {}, number="PO-009999")
        assert missing_po.status_code == 404
        assert mem.receive_calls == []

    def test_over_qty_on_a_real_call_is_422(self, client, mem):
        res = _post(client, {"lines": [{"line_no": 10000, "qty": 31}]})
        assert res.status_code == 422
        assert res.json()["detail"]["reasons"][0]["code"] == "qty_exceeds_outstanding"
        assert mem.receive_calls == []

    def test_in_review_is_422(self, client, mem):
        mem.po["status"] = "In Review"
        res = _post(client)
        assert res.status_code == 422
        assert res.json()["detail"]["posted"] is False
        assert mem.receive_calls == []

    def test_unpublished_page_is_502_and_does_not_invoice(self, client, mem):
        mem.find_error = PurchaseOrderReceiveNotPublished(
            "No HTTP resource was found", status_code=404,
        )
        res = _post(client, {"vendor_shipment_no": "PACK-1058"})
        assert res.status_code == 502, res.text
        detail = res.json()["detail"]
        assert "OPENDC API PO Receive" in detail
        assert "receiveAndInvoice" in detail
        assert mem.receive_calls == []

    def test_bc_quantity_error_stays_a_422(self, client, mem):
        err = requests.HTTPError(
            "400 Microsoft.NAV.Receive on purchase order: RECEIVE:qty Line 10000 exceeds outstanding. Nothing was posted."
        )
        mem.receive_error = err
        res = _post(client)
        assert res.status_code == 422, res.text
        assert res.json()["detail"]["posted"] is False
        assert res.json()["detail"]["invoiced"] is False

    def test_reported_invoice_is_not_a_success(self, client, mem):
        mem.force_invoiced = True
        res = _post(client)
        assert res.status_code == 502, res.text
        assert res.json()["detail"]["invoiced"] is True
        assert res.json()["detail"]["posted"] is False


class TestActionAndPermissions:
    def test_posts_the_custom_bound_action_not_v2(self, monkeypatch):
        captured = {}

        def fake_post(url, headers=None, timeout=None, json=None, **kwargs):
            captured["url"] = url
            captured["json"] = json
            captured["timeout"] = timeout
            response = type("Resp", (), {})()
            response.status_code = 200
            response.content = b'{"postedReceiptNo":"PR-1058","invoiced":false}'
            response.text = response.content.decode()
            response.json = lambda: {"postedReceiptNo": "PR-1058", "invoiced": False}
            return response

        monkeypatch.setattr(
            settings, "PO_RECEIVE_BC_API_URL",
            "https://bc.example/api/opendc/purchasing/v1.0",
        )
        client = BusinessCentralClient.__new__(BusinessCentralClient)
        client.company_id = "company-guid"
        client._get_access_token = lambda: "token"
        import app.integrations.bc.client as client_mod
        monkeypatch.setattr(client_mod.requests, "post", fake_post)

        result = client.receive_purchase_order(PO_ID, "PACK-1058", '[{"lineNo":10000,"qty":30}]')
        assert result["postedReceiptNo"] == "PR-1058"
        assert captured["url"] == (
            "https://bc.example/api/opendc/purchasing/v1.0"
            f"/companies(company-guid)/{PURCHASE_ORDER_RECEIVE_ENTITY}({PO_ID})"
            f"/{PURCHASE_ORDER_RECEIVE_ACTION}"
        )
        assert PURCHASE_ORDER_RECEIVE_ACTION == "Microsoft.NAV.Receive"
        assert captured["json"]["vendorShipmentNo"] == "PACK-1058"
        assert captured["json"]["linesJson"] == '[{"lineNo":10000,"qty":30}]'
        assert "receiveAndInvoice" not in captured["url"]
        assert "/api/v2.0/" not in captured["url"]
        assert captured["timeout"] == 120

        captured.clear()
        client.find_posted_purchase_receipt(PO_ID, "PACK-1058")
        assert captured["url"].endswith(f"/{PURCHASE_ORDER_RECEIPT_LOOKUP_ACTION}")
        assert captured["json"] == {"vendorShipmentNo": "PACK-1058"}
        assert captured["timeout"] == 60

    def test_purchasing_role_can_receive_and_sales_cannot(self):
        assert permission_for("POST", "/api/bc/purchase-orders/PO-001058/receive") == (
            "perm", "purchase_orders.send",
        )
        assert has_permission(type("U", (), {"role": "purchasing", "permissions": None, "user_type": "INTERNAL", "email": "buyer@opendc.ca"})(), "purchase_orders.send")
        assert PRESETS["purchasing"]["purchase_orders.send"] is True
        assert PRESETS["warehouse"]["purchase_orders.send"] is False
        assert PRESETS["sales"]["purchase_orders.send"] is False

    def test_al_receives_without_invoicing_or_email(self):
        page = (REPO / "bc-extension/purchase-order-receive/PurchaseOrderReceive.API.al").read_text()
        permission = (REPO / "bc-extension/purchase-order-receive/PurchaseOrderReceive.PermissionSet.al").read_text()
        assert 'page 70152 "OPENDC API PO Receive"' in page
        assert "PurchHeader.Receive := true" in page
        assert "PurchHeader.Invoice := false" in page
        assert 'Codeunit::"Purch.-Post"' in page
        assert "procedure ReceiveAndInvoice" not in page
        assert "ReceiveAndInvoice(" not in page
        assert "Document-Mailing" not in page
        assert "SMTP" not in page
        assert 'codeunit "Email"' not in page
        assert 'permissionset 70153 "OPENDC PO Receive"' in permission
        assert 'codeunit "Purch.-Post" = X' in permission

    def test_other_purchasing_paths_do_not_receive(self):
        quiet = [
            "backend/app/services/auto_po_service.py",
            "backend/app/services/purchasing_po_service.py",
            "backend/app/services/so_po_generation_service.py",
            "backend/app/services/draft_po_lines_service.py",
            "backend/app/services/draft_po_receipt_service.py",
            "backend/app/services/po_release_service.py",
            "backend/app/services/scheduler_service.py",
        ]
        for rel in quiet:
            text = (REPO / rel).read_text()
            assert "receive_purchase_order" not in text, rel
            assert "po_receive_service" not in text, rel
