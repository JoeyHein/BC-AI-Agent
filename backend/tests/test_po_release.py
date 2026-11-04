"""Explicit release of one purchase order.

The route must refuse a comment-only PO and a customer-info leak, accept
Elton / Upwardor / Nice, return 409 when the order is already released,
support dry-run, and call the BC release action only when confirm is true.
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

from app.api.purchasing import get_current_admin, get_db, router as purchasing_router
from app.db.models import AuditTrail, User, UserRole
from app.integrations.bc.client import (
    PURCHASE_ORDER_RELEASE_ACTION,
    BusinessCentralClient,
    PurchaseOrderReleaseNotPublished,
)
from app.services import po_release_service as release_mod
from app.config import settings


PO_NUMBER = "PO-000962"
PO_ID = "po-guid-962"
REPO = Path(__file__).resolve().parents[2]


def _line(item="PN10", qty=2, **extra):
    row = {
        "id": extra.pop("id", "ln-1"),
        "sequence": extra.pop("sequence", 20000),
        "lineType": "Item",
        "lineObjectNumber": item,
        "description": extra.pop("description", "Panel"),
        "quantity": qty,
        "directUnitCost": 10,
        "unitOfMeasureCode": "EA",
        "receivedQuantity": 0,
    }
    row.update(extra)
    return row


def _comment(text, line_id="c1"):
    return {
        "id": line_id,
        "sequence": 10000,
        "lineType": "Comment",
        "description": text,
        "quantity": 0,
        "receivedQuantity": 0,
    }


def _po(status="Draft", vendor="UPWARDOR", vendor_no="UPW", lines=None, **extra):
    po = {
        "id": PO_ID,
        "number": PO_NUMBER,
        "status": status,
        "vendorNumber": vendor_no,
        "vendorName": vendor,
        "orderDate": "2026-09-08",
        "externalDocumentNumber": extra.pop("externalDocumentNumber", "SO-001299"),
        "purchaseOrderLines": lines if lines is not None else [
            _comment("Built from SO-001299"),
            _line(),
        ],
    }
    po.update(extra)
    return po


class MemBC:
    def __init__(self, po):
        self.po = po
        self.released = []
        self.sales_orders = {}
        self.release_error = None

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

    def get_purchase_order(self, po_id, company_id=None):
        if self.po and self.po.get("id") == po_id:
            return self.po
        return None

    def get_sales_order_by_number(self, number, company_id=None):
        return self.sales_orders.get(number)

    def release_purchase_order(self, po_id, company_id=None):
        if self.release_error is not None:
            raise self.release_error
        self.released.append(po_id)
        self.po = {**self.po, "status": "Open"}
        return {"id": po_id, "number": self.po["number"], "status": "Released"}


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
    monkeypatch.setattr(release_mod, "bc_client", mem)
    monkeypatch.setattr(
        release_mod,
        "validate_po",
        lambda po: {"ok": True, "issues": [], "issue_count": 0},
    )
    admin = User(
        id=1,
        email="joey@opendc.ca",
        password_hash="x",
        role=UserRole.ADMIN,
        is_active=True,
        user_type="INTERNAL",
    )
    app = FastAPI()
    app.include_router(purchasing_router)

    def _db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_current_admin] = lambda: admin
    app.dependency_overrides[get_db] = _db
    return TestClient(app)


def _post(client, body=None, number=PO_NUMBER):
    payload = {"confirm": True, "approved_by": "joey@opendc.ca"}
    if body:
        payload.update(body)
    return client.post(
        f"/api/admin/purchasing/draft-pos/{number}/release",
        json=payload,
    )


def _audits(session_factory):
    db = session_factory()
    try:
        rows = db.query(AuditTrail).all()
        return [
            {
                "action": row.action,
                "entity_type": row.entity_type,
                "entity_id": row.entity_id,
                "user_id": row.user_id,
                "details": row.details,
                "timestamp": row.timestamp,
            }
            for row in rows
        ]
    finally:
        db.close()


def _codes(res):
    detail = res.json()["detail"]
    return [row["code"] for row in detail["reasons"]]


class TestRefusals:
    def test_comment_only_is_refused(self, client, mem, session_factory):
        mem.po["purchaseOrderLines"] = [_comment("Built from SO-001299")]
        res = _post(client)
        assert res.status_code == 422, res.text
        assert "no_item_quantity" in _codes(res)
        assert "comment-only" in res.json()["detail"]["reasons"][0]["message"]
        assert mem.released == []
        rows = _audits(session_factory)
        assert len(rows) == 1
        assert rows[0]["action"] == "purchase_order_release_refused"
        assert rows[0]["entity_id"] == PO_NUMBER
        assert rows[0]["details"]["actor"] == "joey@opendc.ca"
        assert rows[0]["details"]["approved_by"] == "joey@opendc.ca"
        assert rows[0]["details"]["reasons"][0]["code"] == "no_item_quantity"
        assert rows[0]["timestamp"] is not None

    def test_item_line_with_zero_qty_is_refused(self, client, mem):
        mem.po["purchaseOrderLines"] = [_line(qty=0), _comment("note")]
        res = _post(client)
        assert res.status_code == 422, res.text
        assert "no_item_quantity" in _codes(res)
        assert mem.released == []

    def test_customer_info_leak_is_refused_for_other_vendors(self, client, mem):
        mem.po["vendorNumber"] = "DEK"
        mem.po["vendorName"] = "DEK Canada"
        mem.po["purchaseOrderLines"] = [
            _comment("customer PO 4451 — ship to Prairie Door Co"),
            _line(),
        ]
        res = _post(client)
        assert res.status_code == 422, res.text
        assert "customer_info_on_vendor_po" in _codes(res)
        assert "Elton" in res.json()["detail"]["reasons"][0]["message"]
        assert mem.released == []

    def test_ship_to_header_leak_is_refused(self, client, mem):
        mem.po["vendorNumber"] = "DEK"
        mem.po["vendorName"] = "DEK Canada"
        mem.po["shipToName"] = "Prairie Door Co"
        mem.sales_orders["SO-001299"] = {"customerName": "Prairie Door Co"}
        res = _post(client)
        assert res.status_code == 422, res.text
        assert "customer_info_on_vendor_po" in _codes(res)
        assert mem.released == []

    def test_sales_order_number_alone_is_not_a_leak(self, client, mem):
        mem.po["vendorNumber"] = "DEK"
        mem.po["vendorName"] = "DEK Canada"
        mem.po["externalDocumentNumber"] = "SO-001299"
        mem.po["purchaseOrderLines"] = [_comment("Built from SO-001299"), _line()]
        mem.sales_orders["SO-001299"] = {
            "customerName": "Prairie Door Co",
            "externalDocumentNumber": "4451",
        }
        res = _post(client)
        assert res.status_code == 200, res.text
        assert res.json()["released"] is True
        assert mem.released == [PO_ID]

    def test_bernice_is_not_treated_as_nice(self, client, mem):
        mem.po["vendorNumber"] = "BER"
        mem.po["vendorName"] = "Bernice Doors"
        mem.po["purchaseOrderLines"] = [_comment("customer PO 9"), _line()]
        res = _post(client)
        assert res.status_code == 422, res.text
        assert "customer_info_on_vendor_po" in _codes(res)
        assert mem.released == []

    @pytest.mark.parametrize(
        "vendor_no,vendor_name",
        [
            ("UPW", "UPWARDOR"),
            ("ELT", "Elton Manufacturing"),
            ("NICE", "Nice Canada"),
            ("", "Micanan"),
        ],
    )
    def test_allowed_vendor_passes(self, client, mem, vendor_no, vendor_name):
        mem.po["vendorNumber"] = vendor_no
        mem.po["vendorName"] = vendor_name
        mem.po["purchaseOrderLines"] = [
            _comment("customer PO 4451 for Prairie Door Co"),
            _line(),
        ]
        mem.po["shipToName"] = "Prairie Door Co"
        res = _post(client)
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["released"] is True
        assert body["bc_document_status"] == "Released"
        assert body["api_status_after"] == "Open"
        assert "Released" in body["message"]
        assert mem.released == [PO_ID]

    def test_confirm_is_required(self, client, mem):
        res = client.post(
            f"/api/admin/purchasing/draft-pos/{PO_NUMBER}/release",
            json={"approved_by": "Joey"},
        )
        assert res.status_code == 422, res.text
        assert "confirm_required" in _codes(res)
        assert mem.released == []

    def test_approved_by_is_required(self, client, mem):
        res = client.post(
            f"/api/admin/purchasing/draft-pos/{PO_NUMBER}/release",
            json={"confirm": True, "approved_by": "  "},
        )
        assert res.status_code == 422, res.text
        assert "approved_by_required" in _codes(res)
        assert mem.released == []

    def test_draft_review_error_blocks_and_warning_does_not(self, client, mem, monkeypatch):
        monkeypatch.setattr(
            release_mod,
            "validate_po",
            lambda po: {
                "ok": False,
                "issue_count": 1,
                "issues": [{
                    "code": "missing_companion",
                    "severity": "warning",
                    "message": "Panels present but no ASTRAGAL line",
                }],
            },
        )
        warned = _post(client)
        assert warned.status_code == 200, warned.text
        assert warned.json()["warnings"][0]["code"] == "missing_companion"
        assert mem.released == [PO_ID]

        mem.released.clear()
        mem.po["status"] = "Draft"
        monkeypatch.setattr(
            release_mod,
            "validate_po",
            lambda po: {
                "ok": False,
                "issue_count": 1,
                "issues": [{
                    "code": "customer_info_on_vendor_po",
                    "severity": "error",
                    "message": "blocked by draft validation",
                }],
            },
        )
        blocked = _post(client)
        assert blocked.status_code == 422, blocked.text
        assert "customer_info_on_vendor_po" in _codes(blocked)
        assert mem.released == []


class TestAlreadyReleased:
    @pytest.mark.parametrize("status", ["Open", "Released", "open"])
    def test_already_released_is_a_noop(self, client, mem, session_factory, status):
        mem.po["status"] = status
        res = _post(client)
        assert res.status_code == 409, res.text
        detail = res.json()["detail"]
        assert detail["noop"] is True
        assert detail["released"] is False
        assert "already released" in detail["message"].lower()
        assert mem.released == []
        rows = _audits(session_factory)
        assert rows[-1]["action"] == "purchase_order_release_noop"
        assert rows[-1]["details"]["po_number"] == PO_NUMBER

    def test_dry_run_of_released_po_does_not_call_bc(self, client, mem):
        mem.po["status"] = "Open"
        res = _post(client, {"dry_run": True})
        assert res.status_code == 409, res.text
        assert mem.released == []

    def test_bc_already_released_error_is_a_noop(self, client, mem):
        err = requests.HTTPError(
            "400 releasing purchase order: Purchase order PO-000962 is already released."
        )
        err.response = type("R", (), {"status_code": 400, "text": "already released"})()
        mem.release_error = err
        res = _post(client)
        assert res.status_code == 409, res.text
        assert res.json()["detail"]["noop"] is True
        assert mem.released == []

    def test_in_review_is_not_released(self, client, mem):
        mem.po["status"] = "In Review"
        res = _post(client)
        assert res.status_code == 422, res.text
        assert "not_draft" in _codes(res)
        assert mem.released == []

    def test_missing_po_is_404(self, client, mem, session_factory):
        res = _post(client, number="PO-009999")
        assert res.status_code == 404, res.text
        assert mem.released == []
        assert _audits(session_factory) == []


class TestDryRunAndSuccess:
    def test_dry_run_does_not_call_bc(self, client, mem, session_factory):
        res = client.post(
            f"/api/admin/purchasing/draft-pos/{PO_NUMBER}/release",
            json={"dry_run": True},
        )
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["dry_run"] is True
        assert body["would_release"] is True
        assert body["released"] is False
        assert body["bc_called"] is False
        assert body["vendor_quote_price_check"]["applied"] is False
        assert mem.released == []
        assert mem.po["status"] == "Draft"
        rows = _audits(session_factory)
        assert rows[0]["action"] == "purchase_order_release_dry_run"
        assert rows[0]["details"]["outcome"] == "dry_run"
        assert rows[0]["details"]["when"]

    def test_dry_run_reports_a_comment_only_refusal(self, client, mem):
        mem.po["purchaseOrderLines"] = [_comment("note only")]
        res = client.post(
            f"/api/admin/purchasing/draft-pos/{PO_NUMBER}/release",
            json={"dry_run": True, "approved_by": "Joey"},
        )
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["would_release"] is False
        assert body["reasons"][0]["code"] == "no_item_quantity"
        assert mem.released == []

    def test_successful_release_calls_bc_once(self, client, mem, session_factory):
        res = _post(client)
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["released"] is True
        assert body["bc_called"] is True
        assert body["bc_action"] == "Microsoft.NAV.Release"
        assert body["api_status_before"] == "Draft"
        assert body["api_status_after"] == "Open"
        assert body["bc_document_status"] == "Released"
        assert body["approved_by"] == "joey@opendc.ca"
        assert body["audit_logged"] is True
        assert mem.released == [PO_ID]
        assert mem.po["status"] == "Open"
        rows = _audits(session_factory)
        assert len(rows) == 1
        assert rows[0]["action"] == "purchase_order_release_released"
        assert rows[0]["entity_type"] == "purchase_order"
        assert rows[0]["details"]["approved_by"] == "joey@opendc.ca"
        assert rows[0]["details"]["api_status_after"] == "Open"
        assert rows[0]["user_id"] == "joey@opendc.ca"

    def test_unconfirmed_release_is_not_reported_as_released(self, client, mem):
        mem.release_purchase_order = lambda po_id, company_id=None: {}
        res = _post(client)
        assert res.status_code == 502, res.text
        detail = res.json()["detail"]
        assert detail["released"] is False
        assert detail["bc_called"] is True
        assert mem.po["status"] == "Draft"

    def test_unpublished_action_is_502(self, client, mem):
        mem.release_error = PurchaseOrderReleaseNotPublished(
            "No HTTP resource was found", status_code=404,
        )
        res = _post(client)
        assert res.status_code == 502, res.text
        assert "OPENDC API PO Release" in res.json()["detail"]
        assert "receiveAndInvoice" in res.json()["detail"]
        assert mem.released == []


class TestReleaseAction:
    def test_posts_the_custom_bound_action_not_v2(self, monkeypatch):
        captured = {}

        def fake_post(url, headers=None, timeout=None, **kwargs):
            captured["url"] = url
            captured["timeout"] = timeout
            captured["extra"] = kwargs
            response = type("Resp", (), {})()
            response.status_code = 204
            response.content = b""
            response.text = ""
            response.json = lambda: {}
            return response

        monkeypatch.setattr(
            settings, "PO_RELEASE_BC_API_URL",
            "https://bc.example/api/opendc/purchasing/v1.0",
        )
        client = BusinessCentralClient.__new__(BusinessCentralClient)
        client.company_id = "company-guid"
        client._get_access_token = lambda: "token"
        import app.integrations.bc.client as client_mod
        monkeypatch.setattr(client_mod.requests, "post", fake_post)

        result = client.release_purchase_order(PO_ID)
        assert result == {}
        assert captured["url"] == (
            "https://bc.example/api/opendc/purchasing/v1.0"
            f"/companies(company-guid)/purchaseOrders({PO_ID})"
            f"/{PURCHASE_ORDER_RELEASE_ACTION}"
        )
        assert PURCHASE_ORDER_RELEASE_ACTION == "Microsoft.NAV.Release"
        assert "receiveAndInvoice" not in captured["url"]
        assert "/api/v2.0/" not in captured["url"]
        assert captured["extra"].get("json") is None
        assert captured["timeout"] == 120

    def test_other_purchasing_paths_do_not_release(self):
        quiet = [
            "backend/app/services/auto_po_service.py",
            "backend/app/services/purchasing_po_service.py",
            "backend/app/services/so_po_generation_service.py",
            "backend/app/services/draft_po_lines_service.py",
            "backend/app/services/draft_po_receipt_service.py",
            "backend/app/services/scheduler_service.py",
        ]
        for rel in quiet:
            text = (REPO / rel).read_text()
            assert "release_purchase_order" not in text, rel
            assert "po_release_service" not in text, rel
