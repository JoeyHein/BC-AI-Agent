"""POST an Outlook review draft for a purchase order that already exists.

The vendor is not emailed. Graph sendMail must not run. The attachment is
BCClient.get_purchase_order_pdf. A second call creates another draft.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
import requests
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.api.purchasing import get_current_admin, router as purchasing_router
from app.db.models import User, UserRole
from app.services.purchasing_po_service import purchasing_po_service


BC_PDF = b"%PDF-1.4 bc-purchase-order-report\n%%EOF\n"
PO_GUID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
PO_NUMBER = "PO-000962"


def _po(**overrides):
    row = {
        "id": PO_GUID,
        "number": PO_NUMBER,
        "status": "Draft",
        "vendorNumber": "VEND1",
        "vendorName": "Acme Doors",
    }
    row.update(overrides)
    return row


class _Response:
    def __init__(self, status_code):
        self.status_code = status_code


class FakeBC:
    def __init__(self, email="vendor@example.com", pdf=BC_PDF):
        self.company_id = "cid-1"
        self.email = email
        self.pdf = pdf
        self.pdf_error = None
        self.pdf_calls = []
        self.by_number = {PO_NUMBER: _po()}
        self.by_id = {PO_GUID: self.by_number[PO_NUMBER]}
        self.lookup_error = None
        self.vendor_lookup_error = None

    def get_purchase_order_by_number(self, number, company_id=None):
        if self.lookup_error and not _is_guid(number):
            raise self.lookup_error
        return self.by_number.get(number)

    def get_purchase_order(self, po_id, company_id=None):
        if self.lookup_error:
            raise self.lookup_error
        po = self.by_id.get(po_id)
        if po is None:
            raise requests.HTTPError("404", response=_Response(404))
        return po

    def get_purchase_order_pdf(self, po_id, company_id=None):
        self.pdf_calls.append(po_id)
        if self.pdf_error:
            raise RuntimeError(self.pdf_error)
        return self.pdf

    def _make_request(self, method, endpoint, **kwargs):
        if self.vendor_lookup_error:
            raise self.vendor_lookup_error
        return {"value": [{"number": "VEND1", "email": self.email}]}


def _is_guid(value: str) -> bool:
    return value.count("-") == 4 and len(value) == 36


class FakeGraph:
    def __init__(self):
        self.drafts = []
        self.sent = []
        self.fail = False

    def send_mail(self, *args, **kwargs):
        self.sent.append(kwargs)
        raise AssertionError("send_mail must not be called for purchase orders")

    def create_draft_with_attachment(self, **kwargs):
        self.drafts.append(kwargs)
        if self.fail:
            raise RuntimeError("graph drafts folder rejected the message")
        n = len(self.drafts)
        return {
            "id": f"draft-{n}",
            "webLink": f"https://outlook.office.com/mail/draft/{n}",
            "isDraft": True,
        }


@pytest.fixture
def bc_graph(monkeypatch):
    bc = FakeBC()
    graph = FakeGraph()
    monkeypatch.setattr("app.services.purchasing_po_service.bc_client", bc)
    monkeypatch.setattr("app.services.purchasing_po_service.graph_client", graph)
    monkeypatch.setattr(
        "app.services.purchasing_po_service.settings.NOTIFICATION_SENDER_EMAIL",
        "joey@opendc.ca",
    )
    return bc, graph


@pytest.fixture
def admin_user():
    return User(
        id=7,
        email="joey@opendc.ca",
        password_hash="x",
        role=UserRole.ADMIN,
        is_active=True,
        user_type="INTERNAL",
    )


@pytest.fixture
def client(admin_user):
    app = FastAPI()
    app.include_router(purchasing_router)
    app.dependency_overrides[get_current_admin] = lambda: admin_user
    return TestClient(app)


@pytest.fixture
def unauth_client():
    app = FastAPI()
    app.include_router(purchasing_router)
    return TestClient(app)


def _post(client, ref=PO_NUMBER, **body):
    if body:
        return client.post(
            f"/api/admin/purchasing/draft-pos/{ref}/review-draft",
            json=body,
        )
    return client.post(f"/api/admin/purchasing/draft-pos/{ref}/review-draft")


class TestExistingPoReviewDraft:
    def test_draft_po_attaches_bc_pdf_and_does_not_send(self, client, bc_graph):
        bc, graph = bc_graph
        res = _post(client, notes="ship dock 2", cc=["buyer@opendc.ca"])
        assert res.status_code == 200, res.text
        data = res.json()
        assert data["success"] is True
        assert data["email_sent"] is False
        assert data["emailed_to"] is None
        assert data["bc_po_id"] == PO_GUID
        assert data["bc_po_number"] == PO_NUMBER
        assert data["review_draft_created"] is True
        assert data["review_mailbox"] == "joey@opendc.ca"
        assert data["draft_id"] == "draft-1"
        assert data["draft_web_link"].endswith("/draft/1")
        assert data["draft_to"] == "vendor@example.com"
        assert data["draft_warning"] is None
        assert data["draft_error"] is None
        assert data["pdf_error"] is None
        assert data["pdf_source"] == "bc"

        assert bc.pdf_calls == [PO_GUID]
        assert graph.sent == []
        assert len(graph.drafts) == 1
        draft = graph.drafts[0]
        assert draft["mailbox"] == "joey@opendc.ca"
        assert draft["to"] == "vendor@example.com"
        assert draft["cc"] == ["buyer@opendc.ca"]
        assert draft["subject"] == (
            "Purchase Order PO-000962 — Open Distribution Company Inc."
        )
        assert "Hello Acme Doors" in draft["html_body"]
        assert "PO-000962" in draft["html_body"]
        assert "ship dock 2" in draft["html_body"]
        att = draft["attachments"][0]
        assert att["content_bytes"] == BC_PDF
        assert att["content_type"] == "application/pdf"
        assert att["name"] == "PO_PO-000962.pdf"

    def test_empty_body_is_enough(self, client, bc_graph):
        _, graph = bc_graph
        res = _post(client)
        assert res.status_code == 200, res.text
        assert res.json()["review_draft_created"] is True
        assert graph.drafts[0]["cc"] is None
        assert graph.sent == []

    def test_second_call_creates_another_draft(self, client, bc_graph):
        bc, graph = bc_graph
        first = _post(client)
        second = _post(client)
        assert first.status_code == 200
        assert second.status_code == 200
        assert first.json()["draft_id"] == "draft-1"
        assert second.json()["draft_id"] == "draft-2"
        assert second.json()["review_draft_created"] is True
        assert second.json()["email_sent"] is False
        assert bc.pdf_calls == [PO_GUID, PO_GUID]
        assert len(graph.drafts) == 2
        assert graph.drafts[0]["subject"] == graph.drafts[1]["subject"]
        assert graph.drafts[0]["attachments"][0]["content_bytes"] == BC_PDF
        assert graph.drafts[1]["attachments"][0]["content_bytes"] == BC_PDF
        assert graph.sent == []

    def test_bare_number_and_lowercase(self, client, bc_graph):
        bc, _ = bc_graph
        res = _post(client, ref="962")
        assert res.status_code == 200, res.text
        assert res.json()["bc_po_number"] == PO_NUMBER
        res = _post(client, ref="po-000962")
        assert res.status_code == 200, res.text
        assert bc.pdf_calls == [PO_GUID, PO_GUID]

    def test_guid_lookup(self, client, bc_graph):
        bc, graph = bc_graph
        res = _post(client, ref=PO_GUID)
        assert res.status_code == 200, res.text
        assert res.json()["bc_po_number"] == PO_NUMBER
        assert bc.pdf_calls == [PO_GUID]
        assert graph.sent == []

    def test_missing_vendor_email_still_saves_unaddressed_draft(self, client, bc_graph):
        bc, graph = bc_graph
        bc.email = ""
        res = _post(client)
        assert res.status_code == 200, res.text
        data = res.json()
        assert data["review_draft_created"] is True
        assert data["draft_to"] is None
        assert data["email_sent"] is False
        assert "no To address" in data["draft_warning"]
        assert data["pdf_error"] is None
        assert graph.drafts[0]["to"] is None
        assert graph.drafts[0]["attachments"][0]["content_bytes"] == BC_PDF
        assert graph.sent == []

    def test_vendor_lookup_failure_still_saves_unaddressed_draft(self, client, bc_graph):
        bc, graph = bc_graph
        bc.vendor_lookup_error = RuntimeError("vendors down")
        res = _post(client)
        assert res.status_code == 200, res.text
        data = res.json()
        assert data["review_draft_created"] is True
        assert data["draft_warning"]
        assert graph.drafts[0]["to"] is None
        assert graph.sent == []

    def test_pdf_failure_is_200_and_skips_graph(self, client, bc_graph):
        bc, graph = bc_graph
        bc.pdf_error = "mediaReadLink missing"
        res = _post(client)
        assert res.status_code == 200, res.text
        data = res.json()
        assert data["success"] is True
        assert data["email_sent"] is False
        assert data["review_draft_created"] is False
        assert "mediaReadLink missing" in data["pdf_error"]
        assert "Outlook review draft not created" in data["draft_error"]
        assert data["pdf_source"] is None
        assert graph.drafts == []
        assert graph.sent == []

    def test_graph_failure_is_200(self, client, bc_graph):
        bc, graph = bc_graph
        graph.fail = True
        res = _post(client)
        assert res.status_code == 200, res.text
        data = res.json()
        assert data["review_draft_created"] is False
        assert data["email_sent"] is False
        assert data["pdf_error"] is None
        assert data["pdf_source"] == "bc"
        assert "graph drafts folder" in data["draft_error"]
        assert bc.pdf_calls == [PO_GUID]
        assert graph.sent == []

    def test_not_draft_is_422_and_does_not_touch_graph(self, client, bc_graph):
        bc, graph = bc_graph
        bc.by_number[PO_NUMBER] = _po(status="Open")
        bc.by_id[PO_GUID] = bc.by_number[PO_NUMBER]
        res = _post(client)
        assert res.status_code == 422, res.text
        assert "not Draft" in res.json()["detail"]
        assert bc.pdf_calls == []
        assert graph.drafts == []
        assert graph.sent == []

    def test_missing_po_is_404(self, client, bc_graph):
        bc, graph = bc_graph
        bc.by_number.clear()
        res = _post(client)
        assert res.status_code == 404, res.text
        assert "not found" in res.json()["detail"].lower()
        assert bc.pdf_calls == []
        assert graph.drafts == []
        assert graph.sent == []

    def test_guid_404_from_bc(self, client, bc_graph):
        _, graph = bc_graph
        res = _post(client, ref="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
        assert res.status_code == 404, res.text
        assert graph.drafts == []
        assert graph.sent == []

    def test_bc_lookup_failure_is_502(self, client, bc_graph):
        bc, graph = bc_graph
        bc.lookup_error = requests.HTTPError("500 bc down", response=_Response(500))
        res = _post(client)
        assert res.status_code == 502, res.text
        assert bc.pdf_calls == []
        assert graph.drafts == []
        assert graph.sent == []

    def test_missing_id_is_502(self, client, bc_graph):
        bc, graph = bc_graph
        bc.by_number[PO_NUMBER] = _po(id=None)
        res = _post(client)
        assert res.status_code == 502, res.text
        assert bc.pdf_calls == []
        assert graph.sent == []

    def test_bad_identifier_is_400(self, client, bc_graph):
        bc, graph = bc_graph
        res = _post(client, ref="not-a-po")
        assert res.status_code == 400, res.text
        assert bc.pdf_calls == []
        assert graph.drafts == []

    def test_unauthenticated_rejected(self, unauth_client, bc_graph):
        _, graph = bc_graph
        res = _post(unauth_client)
        assert res.status_code in (401, 403)
        assert graph.drafts == []
        assert graph.sent == []

    def test_body_matches_generate_po_helper(self, bc_graph):
        result = purchasing_po_service.create_review_draft_for_existing(
            kind="number",
            value=PO_NUMBER,
            notes="dock 2",
        )
        assert result["review_draft_created"] is True
        assert result["email_sent"] is False
        draft = bc_graph[1].drafts[0]
        assert draft["subject"] == (
            "Purchase Order PO-000962 — Open Distribution Company Inc."
        )
        assert draft["html_body"] == purchasing_po_service._email_body(
            PO_NUMBER, "Acme Doors", "dock 2",
        )
        assert bc_graph[1].sent == []
