"""Receive released purchase orders. Receive only — never invoice.

Draft requested-receipt behaviour is covered by test_draft_po_requested_receipt
and is not changed here.
"""
from __future__ import annotations

import ast
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
from app.config import settings
from app.db.models import PurchaseReceiptAudit, User, UserRole
from app.integrations.bc.client import BusinessCentralClient
from app.services.po_receiving_service import PoReceiveError, po_receiving_service
from app.services.staff_service_keys_service import (
    AUTOMATION_SCOPES,
    grant_receive_scope,
    route_allowed,
)


PO_NUMBER = "PO-000962"
PO_ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
LINE_A = "11111111-1111-1111-1111-111111111111"
LINE_B = "22222222-2222-2222-2222-222222222222"


def _line(line_id, item, qty, received=0, receive=None, sequence=10000, line_type="Item"):
    if receive is None:
        receive = qty - received
    return {
        "id": line_id,
        "sequence": sequence,
        "lineType": line_type,
        "lineObjectNumber": item,
        "description": item or "note",
        "quantity": qty,
        "receivedQuantity": received,
        "receiveQuantity": receive,
        "invoiceQuantity": qty - received,
        "directUnitCost": 10,
    }


def _po(**overrides):
    row = {
        "id": PO_ID,
        "number": PO_NUMBER,
        "status": "Open",
        "vendorNumber": "UPW",
        "vendorName": "UPWARDOR",
        "orderDate": "2026-10-01",
        "purchaseOrderLines": [
            _line(LINE_A, "PN10", 10, received=4, sequence=10000),
            _line(LINE_B, "HK02", 2, received=0, sequence=20000),
            _line("33333333-3333-3333-3333-333333333333", "", 0, received=0, receive=0, sequence=30000, line_type="Comment"),
        ],
    }
    row.update(overrides)
    return row


class _Response:
    def __init__(self, status_code, text="no"):
        self.status_code = status_code
        self.text = text


class MemBC:
    def __init__(self, pos):
        self.pos = {po["number"]: po for po in pos}
        self.by_id = {po["id"]: po for po in pos}
        self.line_patches = []
        self.shipment_nos = []
        self.actions = []
        self.fail_post = None
        self.receipts = []
        self.receive_header = {"lastReceivingNo": "PR-100001"}

    def get_released_purchase_orders_with_lines(self, company_id=None):
        return [dict(po) for po in self.pos.values()]

    def get_purchase_order_by_number(self, number, company_id=None):
        po = self.pos.get(number)
        return dict(po) if po else None

    def get_purchase_order_with_lines(self, po_id, company_id=None):
        po = self.by_id.get(po_id)
        if po is None:
            raise requests.HTTPError("404", response=_Response(404))
        return dict(po)

    def update_purchase_order_line(self, po_id, line_id, data, company_id=None):
        self.line_patches.append((po_id, line_id, dict(data)))
        po = self.by_id[po_id]
        for line in po["purchaseOrderLines"]:
            if line["id"] == line_id:
                line.update(data)
        return dict(data)

    def set_purchase_order_vendor_shipment_no(self, po_number, vendor_shipment_no, company_id=None):
        self.shipment_nos.append((po_number, vendor_shipment_no))
        return {"number": po_number, "Vendor_Shipment_No": vendor_shipment_no}

    def post_purchase_order_receive(self, po_id, company_id=None):
        self.actions.append(po_id)
        if self.fail_post:
            raise self.fail_post
        return {"action": "receive", "status_code": 204, "location": None, "body": {}}

    def get_purchase_order_receive_header(self, po_id, company_id=None):
        return dict(self.receive_header)

    def list_purchase_receipts_for_order(self, order_number, company_id=None):
        return list(self.receipts)


@pytest.fixture
def session():
    engine = create_engine(
        "sqlite://",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    PurchaseReceiptAudit.__table__.create(engine, checkfirst=True)
    db = sessionmaker(bind=engine, autoflush=False, autocommit=False)()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture
def mem(monkeypatch):
    bc = MemBC([_po()])
    monkeypatch.setattr("app.services.po_receiving_service.bc_client", bc)
    return bc


@pytest.fixture
def client(mem, session):
    admin = User(
        id=7, email="joey@opendc.ca", password_hash="x", name="Joey",
        role=UserRole.ADMIN, is_active=True, user_type="INTERNAL",
    )
    app = FastAPI()
    app.include_router(purchasing_router)

    def _admin():
        return admin

    def _db():
        yield session

    app.dependency_overrides[get_current_admin] = _admin
    app.dependency_overrides[get_db] = _db
    return TestClient(app)


def _body(**overrides):
    payload = {
        "vendor_shipment_no": "PACK-100",
        "lines": [{"item_number": "PN10", "qty_to_receive": 2}],
    }
    payload.update(overrides)
    return payload


def _audits(session):
    return session.query(PurchaseReceiptAudit).order_by(PurchaseReceiptAudit.id).all()


class TestReleasedRead:
    def test_list_shows_ordered_received_and_outstanding(self, client, mem):
        mem.pos["PO-DRAFT"] = _po(
            id="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
            number="PO-DRAFT",
            status="Draft",
        )
        res = client.get("/api/admin/purchasing/released-pos")
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["count"] == 1
        po = body["purchase_orders"][0]
        assert po["bc_po_number"] == PO_NUMBER
        assert po["status"] == "Open"
        assert po["released"] is True
        pn10 = next(ln for ln in po["lines"] if ln["item_number"] == "PN10")
        assert pn10["ordered_quantity"] == 10
        assert pn10["quantity"] == 10
        assert pn10["received_quantity"] == 4
        assert pn10["outstanding_quantity"] == 6
        assert mem.line_patches == []
        assert mem.actions == []

    def test_one_po_and_outstanding_filter(self, client, mem):
        one = client.get(f"/api/admin/purchasing/released-pos/{PO_NUMBER}")
        assert one.status_code == 200, one.text
        assert one.json()["lines"][0]["outstanding_quantity"] == 6
        bare = client.get("/api/admin/purchasing/released-pos/962")
        assert bare.status_code == 200
        assert bare.json()["bc_po_number"] == PO_NUMBER

        mem.pos[PO_NUMBER]["purchaseOrderLines"] = [
            _line(LINE_A, "PN10", 10, received=10, receive=0),
        ]
        only = client.get("/api/admin/purchasing/released-pos?outstanding_only=true")
        assert only.json()["count"] == 0

    def test_missing_and_draft_are_not_receivable(self, client, mem):
        missing = client.get("/api/admin/purchasing/released-pos/PO-009999")
        assert missing.status_code == 404
        mem.pos[PO_NUMBER]["status"] = "Draft"
        draft = client.get(f"/api/admin/purchasing/released-pos/{PO_NUMBER}")
        assert draft.status_code == 422
        assert "not released" in draft.json()["detail"]
        assert mem.line_patches == []
        mem.pos[PO_NUMBER]["status"] = "Released"
        released = client.get(f"/api/admin/purchasing/released-pos/{PO_NUMBER}")
        assert released.status_code == 200
        assert released.json()["released"] is True


class TestReceiveValidation:
    def test_preview_does_not_write(self, client, mem, session):
        res = client.post(f"/api/admin/purchasing/released-pos/{PO_NUMBER}/receive", json=_body())
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["dry_run"] is True
        assert body["posted"] is False
        assert body["posting"] == "Receive"
        assert body["invoice"] is False
        assert body["vendor_shipment_no"] == "PACK-100"
        assert body["receiving"][0]["item_number"] == "PN10"
        assert body["receiving"][0]["qty_to_receive"] == 2
        assert body["receiving"][0]["outstanding_quantity"] == 6
        cleared = {row["id"] for row in body["lines_to_clear"]}
        assert LINE_B in cleared
        assert mem.line_patches == []
        assert mem.shipment_nos == []
        assert mem.actions == []
        audit = _audits(session)
        assert len(audit) == 1
        assert audit[0].outcome == "dry_run"
        assert audit[0].posted is False
        assert audit[0].invoice is False
        assert audit[0].posting == "Receive"
        assert audit[0].vendor_shipment_no == "PACK-100"
        assert audit[0].actor_email == "joey@opendc.ca"
        assert audit[0].actor_name == "Joey"
        assert audit[0].po_number == PO_NUMBER
        assert audit[0].lines[0]["qty_to_receive"] == 2

    def test_qty_above_outstanding_is_rejected(self, client, mem, session):
        res = client.post(
            f"/api/admin/purchasing/released-pos/{PO_NUMBER}/receive",
            json=_body(lines=[{"line_id": LINE_A, "qty_to_receive": 7}]),
        )
        assert res.status_code == 422
        assert "outstanding 6" in res.json()["detail"]
        assert mem.actions == []
        assert _audits(session)[0].outcome == "rejected"
        assert _audits(session)[0].posted is False

    def test_unknown_line_and_unknown_item(self, client, mem):
        missing_line = client.post(
            f"/api/admin/purchasing/released-pos/{PO_NUMBER}/receive",
            json=_body(lines=[{"line_id": "nope", "qty_to_receive": 1}]),
        )
        assert missing_line.status_code == 422
        assert "not on" in missing_line.json()["detail"]
        missing_item = client.post(
            f"/api/admin/purchasing/released-pos/{PO_NUMBER}/receive",
            json=_body(lines=[{"item_number": "NO-SUCH", "qty_to_receive": 1}]),
        )
        assert missing_item.status_code == 422
        assert "NO-SUCH" in missing_item.json()["detail"]
        assert mem.line_patches == []

    def test_comment_line_and_duplicate_item(self, client):
        comment = client.post(
            f"/api/admin/purchasing/released-pos/{PO_NUMBER}/receive",
            json=_body(lines=[{"sequence": 30000, "qty_to_receive": 1}]),
        )
        assert comment.status_code == 422
        assert "comment" in comment.json()["detail"]

    def test_duplicate_item_needs_a_line(self, client, mem):
        mem.pos[PO_NUMBER]["purchaseOrderLines"].append(
            _line("44444444-4444-4444-4444-444444444444", "PN10", 3, sequence=40000),
        )
        res = client.post(
            f"/api/admin/purchasing/released-pos/{PO_NUMBER}/receive",
            json=_body(),
        )
        assert res.status_code == 422
        assert "more than one line" in res.json()["detail"]

    def test_draft_post_does_not_receive(self, client, mem, session):
        mem.pos[PO_NUMBER]["status"] = "Draft"
        res = client.post(
            f"/api/admin/purchasing/released-pos/{PO_NUMBER}/receive",
            json=_body(dry_run=False),
        )
        assert res.status_code == 422
        assert mem.actions == []
        assert mem.line_patches == []
        assert mem.shipment_nos == []
        assert _audits(session)[0].outcome == "rejected"

    def test_packing_slip_is_required(self, client, mem):
        res = client.post(
            f"/api/admin/purchasing/released-pos/{PO_NUMBER}/receive",
            json={"lines": [{"item_number": "PN10", "qty_to_receive": 1}]},
        )
        assert res.status_code == 400
        assert "vendor_shipment_no" in res.json()["detail"]
        clash = client.post(
            f"/api/admin/purchasing/released-pos/{PO_NUMBER}/receive",
            json=_body(vendor_packing_slip="OTHER"),
        )
        assert clash.status_code == 400
        assert mem.actions == []


class TestReceivePost:
    def test_posts_receive_only_and_audits(self, client, mem, session):
        res = client.post(
            f"/api/admin/purchasing/released-pos/{PO_NUMBER}/receive",
            json=_body(dry_run=False, vendor_packing_slip="PACK-100"),
        )
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["posted"] is True
        assert body["dry_run"] is False
        assert body["invoice"] is False
        assert body["posting"] == "Receive"
        assert body["bc_receipt_no"] == "PR-100001"
        assert body["receiving"][0]["qty_to_receive"] == 2
        assert mem.shipment_nos == [(PO_NUMBER, "PACK-100")]
        assert mem.actions == [PO_ID]
        patches = {(line_id, tuple(sorted(data.items()))) for _po, line_id, data in mem.line_patches}
        assert (LINE_A, tuple(sorted({"receiveQuantity": 2.0, "invoiceQuantity": 0}.items()))) in patches
        assert any(line_id == LINE_B and data.get("receiveQuantity") == 0 for _po, line_id, data in mem.line_patches)
        audit = _audits(session)[-1]
        assert audit.outcome == "posted"
        assert audit.posted is True
        assert audit.invoice is False
        assert audit.bc_receipt_no == "PR-100001"
        assert audit.vendor_shipment_no == "PACK-100"
        assert audit.actor_name == "Joey"
        assert audit.lines[0]["item_number"] == "PN10"
        assert audit.lines[0]["qty_to_receive"] == 2

    def test_partial_receipt_leaves_the_rest_outstanding(self, client, mem):
        res = client.post(
            f"/api/admin/purchasing/released-pos/{PO_NUMBER}/receive",
            json=_body(dry_run=False, lines=[{"sequence": 10000, "item_number": "PN10", "qty_to_receive": 1}]),
        )
        assert res.status_code == 200, res.text
        assert res.json()["receiving"][0]["ordered_quantity"] == 10
        assert res.json()["receiving"][0]["received_quantity"] == 4
        assert res.json()["receiving"][0]["qty_to_receive"] == 1

    def test_refused_post_restores_quantities_and_audits(self, client, mem, session):
        mem.fail_post = requests.HTTPError("404 missing action", response=_Response(404))
        res = client.post(
            f"/api/admin/purchasing/released-pos/{PO_NUMBER}/receive",
            json=_body(dry_run=False),
        )
        assert res.status_code == 502
        assert "receiveAndInvoice" in res.json()["detail"]
        restored = [patch for patch in mem.line_patches if patch[2].get("receiveQuantity") == 6.0]
        assert restored, mem.line_patches
        assert _audits(session)[-1].outcome == "bc_error"
        assert _audits(session)[-1].posted is False

    def test_server_error_does_not_restore(self, client, mem):
        mem.fail_post = requests.HTTPError("500", response=_Response(500))
        before = len(mem.line_patches)
        res = client.post(
            f"/api/admin/purchasing/released-pos/{PO_NUMBER}/receive",
            json=_body(dry_run=False),
        )
        assert res.status_code == 502
        assert "may have posted" in res.json()["detail"]
        assert len(mem.line_patches) == before + 2


class TestReceiveClient:
    def test_receive_url_is_receive_only(self, monkeypatch):
        bc = BusinessCentralClient.__new__(BusinessCentralClient)
        bc.company_id = "company-guid"
        monkeypatch.setattr(settings, "BC_TENANT_ID", "tenant")
        monkeypatch.setattr(settings, "BC_ENVIRONMENT", "Production")
        monkeypatch.setattr(settings, "BC_BASE_URL", "https://api.businesscentral.dynamics.com/v2.0")
        monkeypatch.setattr(settings, "BC_PO_RECEIVE_ACTION", "receive")
        url = bc.purchase_order_receive_url(PO_ID)
        assert url.endswith(f"/purchaseOrderReceives({PO_ID})/Microsoft.NAV.receive")
        assert "receiveAndInvoice" not in url
        assert "/api/opendc/purchasing/v1.0/" in url

    def test_invoice_action_is_refused_before_http(self, monkeypatch):
        bc = BusinessCentralClient.__new__(BusinessCentralClient)
        bc.company_id = "company-guid"
        monkeypatch.setattr(settings, "BC_TENANT_ID", "tenant")
        monkeypatch.setattr(settings, "BC_ENVIRONMENT", "Production")
        monkeypatch.setattr(settings, "BC_BASE_URL", "https://api.businesscentral.dynamics.com/v2.0")
        monkeypatch.setattr(settings, "BC_PO_RECEIVE_ACTION", "receiveAndInvoice")
        with pytest.raises(RuntimeError, match="Receive only"):
            bc.purchase_order_receive_url(PO_ID)

    def test_post_calls_receive_and_does_not_retry(self, monkeypatch):
        bc = BusinessCentralClient.__new__(BusinessCentralClient)
        bc.company_id = "company-guid"
        bc._get_access_token = lambda: "tok"
        monkeypatch.setattr(settings, "BC_TENANT_ID", "tenant")
        monkeypatch.setattr(settings, "BC_ENVIRONMENT", "Production")
        monkeypatch.setattr(settings, "BC_BASE_URL", "https://api.businesscentral.dynamics.com/v2.0")
        monkeypatch.setattr(settings, "BC_PO_RECEIVE_ACTION", "receive")
        seen = {}

        class Resp:
            status_code = 204
            content = b""
            text = ""
            headers = {"Location": "https://bc.example/receipts('PR-1')"}

            def json(self):
                return {}

        def fake_post(url, headers=None, json=None, timeout=None):
            seen["url"] = url
            seen["calls"] = seen.get("calls", 0) + 1
            return Resp()

        import app.integrations.bc.client as bc_mod
        monkeypatch.setattr(bc_mod.requests, "post", fake_post)
        result = bc.post_purchase_order_receive(PO_ID)
        assert seen["calls"] == 1
        assert seen["url"].endswith("/Microsoft.NAV.receive")
        assert "receiveAndInvoice" not in seen["url"]
        assert result["action"] == "receive"


class TestServiceKeyScope:
    def test_read_scope_can_list_and_not_receive(self):
        granted = {"purchasing:read"}
        assert route_allowed("GET", "/api/admin/purchasing/released-pos", b"", granted)[0] is True
        assert route_allowed("GET", f"/api/admin/purchasing/released-pos/{PO_NUMBER}", b"", granted)[0] is True
        ok, reason = route_allowed(
            "POST", f"/api/admin/purchasing/released-pos/{PO_NUMBER}/receive", b"{}", granted,
        )
        assert ok is False
        assert "does not include permission" in reason

    def test_receive_scope_can_post_and_not_release_invoice_or_delete(self):
        granted = set(AUTOMATION_SCOPES)
        assert "purchasing:receive" in granted
        assert route_allowed(
            "POST", f"/api/admin/purchasing/released-pos/{PO_NUMBER}/receive", b"{}", granted,
        )[0] is True
        for method, path in (
            ("POST", f"/api/admin/purchasing/released-pos/{PO_NUMBER}/release"),
            ("POST", f"/api/admin/purchasing/released-pos/{PO_NUMBER}/invoice"),
            ("DELETE", f"/api/admin/purchasing/released-pos/{PO_NUMBER}"),
            ("POST", f"/api/admin/purchasing/released-pos/{PO_NUMBER}/receiveAndInvoice"),
        ):
            ok, reason = route_allowed(method, path, b"", granted)
            assert ok is False, (method, path)
            assert reason == "This service key is not allowed to call this route."

    def test_receive_scope_does_not_grant_draft_deletes(self):
        granted = {"purchasing:receive"}
        assert route_allowed(
            "DELETE", "/api/admin/purchasing/draft-pos/PO-000962/lines/10", b"", granted,
        )[0] is False
        assert route_allowed(
            "POST", "/api/admin/purchasing/draft-pos/PO-000962/requested-receipt", b"{}", granted,
        )[0] is False

    def test_existing_purchasing_key_gains_receive_scope(self):
        assert grant_receive_scope(["purchasing:read", "orders:read"]) == [
            "purchasing:read", "orders:read", "purchasing:receive",
        ]
        assert grant_receive_scope(["orders:read"]) is None
        assert grant_receive_scope(["purchasing:read", "purchasing:receive"]) is None
        assert grant_receive_scope('["purchasing:read"]') == [
            "purchasing:read", "purchasing:receive",
        ]


def test_migration_revises_kpi_snapshot_head():
    path = (
        Path(__file__).resolve().parents[1]
        / "alembic"
        / "versions"
        / "r8s9t0u1v2w3_add_purchase_receipt_audit.py"
    )
    module = ast.parse(path.read_text())
    assigned = {}
    for node in module.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            name = getattr(node.targets[0], "id", None)
            if name in {"revision", "down_revision"} and isinstance(node.value, ast.Constant):
                assigned[name] = node.value.value
    assert assigned["revision"] == "r8s9t0u1v2w3"
    assert assigned["down_revision"] == "q7r8s9t0u1v2"


def test_actor_name_is_the_service_key(mem):
    from types import SimpleNamespace
    from app.api.purchasing import _receive_actor

    request = SimpleNamespace(
        state=SimpleNamespace(staff_service_key_name="Joey assistant", staff_service_key_id=3),
    )
    admin = SimpleNamespace(id=1, email="automation@keys.opendc.internal", name="Automation")
    actor = _receive_actor(request, admin)
    assert actor["actor_name"] == "Joey assistant"
    assert actor["actor_email"] == "automation@keys.opendc.internal"
    assert actor["service_key_id"] == 3
    assert mem.actions == []


def test_service_rejects_a_plan_without_touching_bc(mem):
    with pytest.raises(PoReceiveError) as raised:
        po_receiving_service._plan(_po(), [])
    assert raised.value.status_code == 400
    assert mem.actions == []
