"""Release one unreleased purchase order. Never invoice, delete, or reopen.

Draft line edits and requested-receipt dates are covered by their own tests
and are not changed here. Receiving a released PO stays on the receive route.
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
from app.db.models import PurchaseReleaseAudit, User, UserRole
from app.integrations.bc.client import BusinessCentralClient
from app.services.staff_service_keys_service import (
    AUTOMATION_SCOPES,
    grant_release_scope,
    route_allowed,
)


PO_NUMBER = "PO-000962"
PO_ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
OTHER_ID = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"


def _line(line_id, item, qty, sequence=10000, line_type="Item"):
    return {
        "id": line_id,
        "sequence": sequence,
        "lineType": line_type,
        "lineObjectNumber": item,
        "description": "panel" if item else "note",
        "quantity": qty,
        "directUnitCost": 12.5,
        "amountExcludingTax": qty * 12.5,
    }


def _po(**overrides):
    row = {
        "id": PO_ID,
        "number": PO_NUMBER,
        "status": "Draft",
        "vendorNumber": "UPW",
        "vendorName": "UPWARDOR",
        "shipToName": "OpenDC",
        "shipToContact": "Joey",
        "shipToAddressLine1": "1 Shop Road",
        "shipToAddressLine2": "",
        "shipToCity": "Edmonton",
        "shipToState": "AB",
        "shipToPostCode": "T5T 0A1",
        "shipToCountry": "CA",
        "totalAmountExcludingTax": 150,
        "totalTaxAmount": 7.5,
        "totalAmountIncludingTax": 157.5,
        "purchaseOrderLines": [
            _line("11111111-1111-1111-1111-111111111111", "PN10", 10, sequence=10000),
            _line("22222222-2222-2222-2222-222222222222", "", 0, sequence=20000, line_type="Comment"),
        ],
    }
    row.update(overrides)
    return row


class _Response:
    def __init__(self, status_code, text="no"):
        self.status_code = status_code
        self.text = text
        self.content = text.encode()

    def json(self):
        return {"error": {"message": self.text}}


class MemBC:
    def __init__(self, pos):
        self.pos = {po["number"]: po for po in pos}
        self.by_id = {po["id"]: po for po in pos}
        self.reads = []
        self.release_calls = []
        self.fail_release = None

    def get_purchase_order_by_number(self, number, company_id=None):
        self.reads.append(("number", number))
        po = self.pos.get(number)
        return dict(po) if po else None

    def get_purchase_order_with_lines(self, po_id, company_id=None):
        self.reads.append(("id", po_id))
        po = self.by_id.get(po_id)
        if po is None:
            raise requests.HTTPError("404", response=_Response(404, "missing"))
        return dict(po)

    def post_purchase_order_release(self, po_id, company_id=None):
        self.release_calls.append(po_id)
        if self.fail_release:
            raise self.fail_release
        po = self.by_id[po_id]
        po["status"] = "Open"
        return {
            "action": "release",
            "status_code": 204,
            "url": f"https://bc.example/purchaseOrders({po_id})/Microsoft.NAV.release",
        }


@pytest.fixture
def session():
    engine = create_engine(
        "sqlite://",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    PurchaseReleaseAudit.__table__.create(engine, checkfirst=True)
    db = sessionmaker(bind=engine, autoflush=False, autocommit=False)()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture
def mem(monkeypatch):
    bc = MemBC([_po()])
    monkeypatch.setattr("app.services.po_release_service.bc_client", bc)
    return bc


@pytest.fixture
def client(mem, session):
    admin = User(
        id=7, email="joey@opendc.ca", password_hash="x", name="Joey",
        role=UserRole.ADMIN, is_active=True, user_type="INTERNAL",
    )
    app = FastAPI()
    app.include_router(purchasing_router)

    @app.middleware("http")
    async def _key(request, call_next):
        request.state.staff_service_key_name = "Joey assistant"
        request.state.staff_service_key_id = 3
        return await call_next(request)

    def _admin():
        return admin

    def _db():
        yield session

    app.dependency_overrides[get_current_admin] = _admin
    app.dependency_overrides[get_db] = _db
    return TestClient(app)


def _audits(session):
    return session.query(PurchaseReleaseAudit).order_by(PurchaseReleaseAudit.id).all()


class TestReleasePreview:
    def test_empty_body_previews_and_does_not_write(self, client, mem, session):
        res = client.post(f"/api/admin/purchasing/draft-pos/{PO_NUMBER}/release")
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["bc_po_number"] == PO_NUMBER
        assert body["vendor_number"] == "UPW"
        assert body["vendor_name"] == "UPWARDOR"
        assert body["status"] == "Draft"
        assert body["bc_page_status"] == "Open"
        assert body["dry_run"] is True
        assert body["released"] is False
        assert body["wrote"] is False
        assert body["status_after_release"] == "Open"
        assert body["bc_page_status_after_release"] == "Released"
        assert body["ship_to"]["name"] == "OpenDC"
        assert body["ship_to"]["city"] == "Edmonton"
        assert body["ship_to"]["post_code"] == "T5T 0A1"
        assert body["totals"]["total_amount_excluding_tax"] == 150
        assert body["totals"]["total_amount_including_tax"] == 157.5
        assert body["lines"][0]["item_number"] == "PN10"
        assert body["lines"][0]["quantity"] == 10
        assert body["lines"][0]["direct_unit_cost"] == 12.5
        assert mem.release_calls == []
        assert len(mem.reads) == 1
        rows = _audits(session)
        assert len(rows) == 1
        assert rows[0].outcome == "dry_run"
        assert rows[0].released is False
        assert rows[0].actor_name == "Joey assistant"
        assert rows[0].service_key_name == "Joey assistant"
        assert rows[0].po_number == PO_NUMBER
        assert rows[0].vendor_name == "UPWARDOR"

    def test_explicit_dry_run_true_does_not_post(self, client, mem):
        res = client.post(
            f"/api/admin/purchasing/draft-pos/962/release",
            json={"dry_run": True},
        )
        assert res.status_code == 200, res.text
        assert res.json()["bc_po_number"] == PO_NUMBER
        assert mem.release_calls == []


class TestReleasePost:
    def test_dry_run_false_releases_the_named_po_once(self, client, mem, session):
        res = client.post(
            f"/api/admin/purchasing/draft-pos/{PO_NUMBER}/release",
            json={"dry_run": False, "po_number": "962"},
        )
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["released"] is True
        assert body["wrote"] is True
        assert body["dry_run"] is False
        assert body["status"] == "Open"
        assert body["bc_page_status"] == "Released"
        assert body["status_after"] == "Open"
        assert mem.release_calls == [PO_ID]
        rows = _audits(session)
        assert [row.outcome for row in rows] == ["released"]
        finished = rows[-1]
        assert finished.outcome == "released"
        assert finished.released is True
        assert finished.status_before == "Draft"
        assert finished.status_after == "Open"
        assert finished.actor_name == "Joey assistant"

    def test_body_po_number_must_match(self, client, mem, session):
        res = client.post(
            f"/api/admin/purchasing/draft-pos/{PO_NUMBER}/release",
            json={"dry_run": False, "po_number": "PO-000999"},
        )
        assert res.status_code == 400, res.text
        assert "does not match" in res.json()["detail"]
        assert mem.reads == []
        assert mem.release_calls == []
        rows = _audits(session)
        assert len(rows) == 1
        assert rows[0].outcome == "rejected"

    def test_body_id_must_match_the_loaded_order(self, client, mem, session):
        res = client.post(
            f"/api/admin/purchasing/draft-pos/{PO_NUMBER}/release",
            json={"dry_run": False, "po_number": OTHER_ID},
        )
        assert res.status_code == 400, res.text
        assert mem.release_calls == []
        assert _audits(session)[-1].outcome == "rejected"

    def test_already_released_is_rejected_without_a_release_call(self, client, mem, session):
        mem.pos[PO_NUMBER]["status"] = "Open"
        res = client.post(
            f"/api/admin/purchasing/draft-pos/{PO_NUMBER}/release",
            json={"dry_run": False},
        )
        assert res.status_code == 422, res.text
        assert "already released" in res.json()["detail"]
        assert mem.release_calls == []
        assert _audits(session)[-1].outcome == "rejected"

    def test_in_review_is_rejected(self, client, mem, session):
        mem.pos[PO_NUMBER]["status"] = "In Review"
        res = client.post(
            f"/api/admin/purchasing/draft-pos/{PO_NUMBER}/release",
            json={"dry_run": False},
        )
        assert res.status_code == 422, res.text
        assert mem.release_calls == []
        assert _audits(session)[-1].outcome == "rejected"

    def test_missing_po_is_404(self, client, mem, session):
        res = client.post(
            "/api/admin/purchasing/draft-pos/PO-000111/release",
            json={"dry_run": False},
        )
        assert res.status_code == 404, res.text
        assert mem.release_calls == []
        assert _audits(session)[-1].outcome == "rejected"
        assert _audits(session)[-1].po_number == "PO-000111"

    def test_bc_404_does_not_retry(self, client, mem, session):
        mem.fail_release = requests.HTTPError("404 missing", response=_Response(404, "missing"))
        res = client.post(
            f"/api/admin/purchasing/draft-pos/{PO_NUMBER}/release",
            json={"dry_run": False},
        )
        assert res.status_code == 502, res.text
        assert "70912" in res.json()["detail"]
        assert mem.release_calls == [PO_ID]
        assert mem.pos[PO_NUMBER]["status"] == "Draft"
        assert _audits(session)[-1].outcome == "bc_error"
        assert _audits(session)[-1].released is False

    def test_bc_500_does_not_retry(self, client, mem, session):
        mem.fail_release = requests.HTTPError("500 down", response=_Response(500, "down"))
        res = client.post(
            f"/api/admin/purchasing/draft-pos/{PO_NUMBER}/release",
            json={"dry_run": False},
        )
        assert res.status_code == 502, res.text
        assert "did not retry" in res.json()["detail"]
        assert mem.release_calls == [PO_ID]
        assert _audits(session)[-1].outcome == "bc_error"


class TestReleaseClient:
    def _client(self, monkeypatch, action="release", entity="purchaseOrderReleases"):
        bc = BusinessCentralClient.__new__(BusinessCentralClient)
        bc.company_id = "company-guid"
        bc._get_access_token = lambda: "tok"
        monkeypatch.setattr(settings, "BC_TENANT_ID", "tenant")
        monkeypatch.setattr(settings, "BC_ENVIRONMENT", "Production")
        monkeypatch.setattr(settings, "BC_BASE_URL", "https://api.businesscentral.dynamics.com/v2.0")
        monkeypatch.setattr(settings, "BC_PO_RELEASE_ACTION", action)
        monkeypatch.setattr(settings, "BC_PO_RELEASE_ENTITY", entity)
        monkeypatch.setattr(settings, "BC_PO_RECEIVE_PUBLISHER", "opendc")
        monkeypatch.setattr(settings, "BC_PO_RECEIVE_GROUP", "purchasing")
        monkeypatch.setattr(settings, "BC_PO_RECEIVE_VERSION", "v1.0")
        return bc

    def test_reopen_and_invoice_are_refused_before_http(self, monkeypatch):
        import app.integrations.bc.client as bc_mod

        def fail_post(*args, **kwargs):
            raise AssertionError("HTTP was called")

        monkeypatch.setattr(bc_mod.requests, "post", fail_post)
        for action in ("reopen", "receiveAndInvoice", "ReleaseAndInvoice"):
            bc = self._client(monkeypatch, action=action)
            with pytest.raises(RuntimeError, match="release"):
                bc.post_purchase_order_release(PO_ID)

    def test_standard_404_falls_back_to_the_extension_once(self, monkeypatch):
        bc = self._client(monkeypatch)
        seen = []

        class Resp:
            def __init__(self, status_code):
                self.status_code = status_code
                self.content = b"" if status_code == 204 else b'{"error":{"message":"missing"}}'
                self.text = "missing"
                self.headers = {}

            def json(self):
                return {"error": {"message": self.text}}

        def fake_post(url, headers=None, json=None, timeout=None):
            seen.append(url)
            if len(seen) == 1:
                return Resp(404)
            return Resp(204)

        import app.integrations.bc.client as bc_mod
        monkeypatch.setattr(bc_mod.requests, "post", fake_post)
        result = bc.post_purchase_order_release(PO_ID)
        assert len(seen) == 2
        assert seen[0].endswith(f"/purchaseOrders({PO_ID})/Microsoft.NAV.release")
        assert "/api/v2.0/" in seen[0]
        assert seen[1].endswith(f"/purchaseOrderReleases({PO_ID})/Microsoft.NAV.release")
        assert "/api/opendc/purchasing/v1.0/" in seen[1]
        assert "reopen" not in seen[0].lower()
        assert "reopen" not in seen[1].lower()
        assert "invoice" not in seen[0].lower()
        assert "invoice" not in seen[1].lower()
        assert result["action"] == "release"
        assert result["url"] == seen[1]

    def test_standard_500_does_not_try_the_extension(self, monkeypatch):
        bc = self._client(monkeypatch)
        seen = []

        class Resp:
            status_code = 500
            content = b'{"error":{"message":"down"}}'
            text = "down"
            headers = {}

            def json(self):
                return {"error": {"message": "down"}}

        def fake_post(url, headers=None, json=None, timeout=None):
            seen.append(url)
            return Resp()

        import app.integrations.bc.client as bc_mod
        monkeypatch.setattr(bc_mod.requests, "post", fake_post)
        with pytest.raises(requests.HTTPError, match="500"):
            bc.post_purchase_order_release(PO_ID)
        assert len(seen) == 1
        assert seen[0].endswith("/Microsoft.NAV.release")


class TestReleaseScope:
    def test_read_scope_cannot_release(self):
        granted = {"purchasing:read"}
        ok, reason = route_allowed(
            "POST", f"/api/admin/purchasing/draft-pos/{PO_NUMBER}/release", b"{}", granted,
        )
        assert ok is False
        assert "does not include permission" in reason

    def test_release_scope_can_release_one_po_and_nothing_else(self):
        granted = {"purchasing:release"}
        assert route_allowed(
            "POST", f"/api/admin/purchasing/draft-pos/{PO_NUMBER}/release", b"{}", granted,
        )[0] is True
        assert "purchasing:release" in set(AUTOMATION_SCOPES)
        not_on_the_list = [
            ("POST", "/api/admin/purchasing/draft-pos/release"),
            ("POST", f"/api/admin/purchasing/draft-pos/{PO_NUMBER}/reopen"),
            ("POST", f"/api/admin/purchasing/draft-pos/{PO_NUMBER}/invoice"),
            ("DELETE", f"/api/admin/purchasing/draft-pos/{PO_NUMBER}"),
            ("POST", f"/api/admin/purchasing/released-pos/{PO_NUMBER}/release"),
            ("POST", f"/api/admin/purchasing/released-pos/{PO_NUMBER}/invoice"),
            ("DELETE", f"/api/admin/purchasing/released-pos/{PO_NUMBER}"),
        ]
        for method, path in not_on_the_list:
            ok, reason = route_allowed(method, path, b"", granted)
            assert ok is False, (method, path)
            assert reason == "This service key is not allowed to call this route."
        needs_another_scope = [
            ("DELETE", f"/api/admin/purchasing/draft-pos/{PO_NUMBER}/lines/10"),
            ("POST", f"/api/admin/purchasing/released-pos/{PO_NUMBER}/receive"),
        ]
        for method, path in needs_another_scope:
            ok, reason = route_allowed(method, path, b"", granted)
            assert ok is False, (method, path)
            assert reason == "This service key does not include permission for this route."

    def test_existing_purchasing_key_gains_release_scope(self):
        assert grant_release_scope(["purchasing:read", "orders:read"]) == [
            "purchasing:read", "orders:read", "purchasing:release",
        ]
        assert grant_release_scope(["orders:read"]) is None
        assert grant_release_scope(["purchasing:read", "purchasing:release"]) is None
        assert grant_release_scope('["purchasing:read"]') == [
            "purchasing:read", "purchasing:release",
        ]


def test_migration_revises_receipt_audit():
    path = (
        Path(__file__).resolve().parents[1]
        / "alembic"
        / "versions"
        / "s9t0u1v2w3x4_add_purchase_release_audit.py"
    )
    module = ast.parse(path.read_text())
    assigned = {}
    for node in module.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            name = getattr(node.targets[0], "id", None)
            if name in {"revision", "down_revision"} and isinstance(node.value, ast.Constant):
                assigned[name] = node.value.value
    assert assigned["revision"] == "s9t0u1v2w3x4"
    assert assigned["down_revision"] == "r8s9t0u1v2w3"
