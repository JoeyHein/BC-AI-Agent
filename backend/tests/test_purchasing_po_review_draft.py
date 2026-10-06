"""generate-po saves an Outlook review draft with the BC purchase-order PDF.

The vendor is not emailed. Graph sendMail must not run. The attachment is
BCClient.get_purchase_order_pdf, not a portal-rendered PDF.
"""
from __future__ import annotations

import base64
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.api.purchasing import (
    GeneratePORequest,
    get_current_admin,
    get_db,
    review_draft_requested,
    router as purchasing_router,
)
from app.db.models import POAgentLog, User, UserRole
from app.integrations.email.client import GraphEmailClient
from app.services.purchasing_po_service import purchasing_po_service


BC_PDF = b"%PDF-1.4 bc-purchase-order-report\n%%EOF\n"
PO_GUID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
LINES = [{
    "item_no": "PN10-1",
    "description": "Panel",
    "quantity": 2,
    "unit_cost": 10.5,
}]


def _db():
    # StaticPool keeps one shared :memory: connection so the TestClient thread
    # sees the table created on the test thread.
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    POAgentLog.__table__.create(engine)
    return sessionmaker(bind=engine)()


class FakeBC:
    def __init__(self, email="vendor@example.com", pdf=BC_PDF, pdf_error=None):
        self.company_id = "cid-1"
        self.email = email
        self.pdf = pdf
        self.pdf_error = pdf_error
        self.created = []
        self.lines = []
        self.pdf_calls = []
        self.fail_create = False

    def create_purchase_order(self, body):
        if self.fail_create:
            raise RuntimeError("bc down")
        po = {"id": PO_GUID, "number": "PO-000100", "status": "Draft", **body}
        self.created.append(po)
        return po

    def add_purchase_order_line(self, po_id, body):
        self.lines.append((po_id, body))
        return {"id": "line-1"}

    def get_purchase_order_pdf(self, po_id, company_id=None):
        self.pdf_calls.append(po_id)
        if self.pdf_error:
            raise RuntimeError(self.pdf_error)
        return self.pdf

    def _make_request(self, method, endpoint, **kwargs):
        return {"value": [{"number": "VEND1", "email": self.email}]}


class FakeGraph:
    def __init__(self):
        self.drafts = []
        self.sent = []
        self.fail = False
        self.draft_response = {
            "id": "draft-1",
            "webLink": "https://outlook.office.com/mail/draft/1",
            "isDraft": True,
        }

    def send_mail(self, *args, **kwargs):
        self.sent.append(kwargs)
        raise AssertionError("send_mail must not be called for purchase orders")

    def create_draft_with_attachment(self, **kwargs):
        self.drafts.append(kwargs)
        if self.fail:
            raise RuntimeError("graph drafts folder rejected the message")
        return dict(self.draft_response)


@pytest.fixture
def db():
    session = _db()
    yield session
    session.close()


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


def _create(db, **kwargs):
    return purchasing_po_service.create_with_review_draft(
        db,
        vendor_no=kwargs.get("vendor_no", "VEND1"),
        vendor_name=kwargs.get("vendor_name", "Acme Doors"),
        lines=kwargs.get("lines", LINES),
        user_id=7,
        notes=kwargs.get("notes"),
        create_review_draft=kwargs.get("create_review_draft", True),
        cc=kwargs.get("cc"),
    )


def _attachment(graph):
    assert len(graph.drafts) == 1
    atts = graph.drafts[0]["attachments"]
    assert len(atts) == 1
    return atts[0]


class TestReviewDraftFlag:
    def test_dashboard_default_is_draft(self):
        body = GeneratePORequest(vendor_name="Acme", lines=[{"item_no": "A", "quantity": 1}])
        assert review_draft_requested(body) is True

    def test_explicit_false_skips(self):
        body = GeneratePORequest(
            vendor_name="Acme", lines=[{"item_no": "A", "quantity": 1}],
            create_review_draft=False,
        )
        assert review_draft_requested(body) is False

    def test_send_email_alias_does_not_mean_send(self):
        body = GeneratePORequest(
            vendor_name="Acme", lines=[{"item_no": "A", "quantity": 1}],
            send_email=True,
        )
        assert review_draft_requested(body) is True
        skipped = GeneratePORequest(
            vendor_name="Acme", lines=[{"item_no": "A", "quantity": 1}],
            send_email=False,
        )
        assert review_draft_requested(skipped) is False

    def test_create_review_draft_wins_over_send_email(self):
        body = GeneratePORequest(
            vendor_name="Acme", lines=[{"item_no": "A", "quantity": 1}],
            create_review_draft=True,
            send_email=False,
        )
        assert review_draft_requested(body) is True


class TestCreateWithReviewDraft:
    def test_attaches_bc_pdf_and_does_not_send(self, db, bc_graph):
        bc, graph = bc_graph
        result = _create(db, notes="ship dock 2", cc=["buyer@opendc.ca"])

        assert result["success"] is True
        assert result["email_sent"] is False
        assert result["emailed_to"] is None
        assert result["bc_po_id"] == PO_GUID
        assert result["bc_po_number"] == "PO-000100"
        assert result["review_draft_created"] is True
        assert result["review_mailbox"] == "joey@opendc.ca"
        assert result["draft_id"] == "draft-1"
        assert result["draft_web_link"].endswith("/draft/1")
        assert result["draft_to"] == "vendor@example.com"
        assert result["draft_error"] is None
        assert result["pdf_error"] is None
        assert result["pdf_source"] == "bc"
        assert result["draft_warning"] is None

        assert bc.pdf_calls == [PO_GUID]
        assert graph.sent == []
        assert len(graph.drafts) == 1
        draft = graph.drafts[0]
        assert draft["mailbox"] == "joey@opendc.ca"
        assert draft["to"] == "vendor@example.com"
        assert draft["cc"] == ["buyer@opendc.ca"]
        assert "PO-000100" in draft["subject"]
        assert "Open Distribution Company Inc." in draft["subject"]
        assert "ship dock 2" in draft["html_body"]
        att = _attachment(graph)
        assert att["content_bytes"] == BC_PDF
        assert att["content_type"] == "application/pdf"
        assert att["name"] == "PO_PO-000100.pdf"
        assert b"PURCHASE ORDER" not in att["content_bytes"]

        log = db.query(POAgentLog).one()
        assert log.emailed_to is None
        assert log.emailed_at is None
        assert log.bc_po_number == "PO-000100"

    def test_pdf_failure_keeps_po_and_skips_draft(self, db, bc_graph, caplog):
        bc, graph = bc_graph
        bc.pdf_error = "mediaReadLink missing"
        result = _create(db)

        assert result["success"] is True
        assert result["email_sent"] is False
        assert result["review_draft_created"] is False
        assert result["draft_id"] is None
        assert result["pdf_source"] is None
        assert "mediaReadLink missing" in result["pdf_error"]
        assert "Outlook review draft not created" in result["draft_error"]
        assert graph.drafts == []
        assert graph.sent == []
        assert bc.created
        assert "Outlook review draft not created" in caplog.text
        assert db.query(POAgentLog).one().emailed_to is None

    def test_empty_bc_pdf_is_an_error(self, db, bc_graph):
        bc, graph = bc_graph
        bc.pdf = b""
        result = _create(db)
        assert result["review_draft_created"] is False
        assert "Empty PDF" in result["pdf_error"]
        assert graph.drafts == []
        assert graph.sent == []

    def test_graph_failure_keeps_po(self, db, bc_graph):
        bc, graph = bc_graph
        graph.fail = True
        result = _create(db)
        assert result["success"] is True
        assert result["email_sent"] is False
        assert result["review_draft_created"] is False
        assert result["pdf_source"] == "bc"
        assert result["pdf_error"] is None
        assert "graph drafts folder" in result["draft_error"]
        assert graph.sent == []
        assert db.query(POAgentLog).count() == 1

    def test_missing_vendor_email_still_saves_unaddressed_draft(self, db, bc_graph):
        bc, graph = bc_graph
        bc.email = ""
        result = _create(db)
        assert result["review_draft_created"] is True
        assert result["draft_to"] is None
        assert result["email_sent"] is False
        assert "no To address" in result["draft_warning"]
        assert graph.drafts[0]["to"] is None
        assert _attachment(graph)["content_bytes"] == BC_PDF
        assert graph.sent == []

    def test_create_review_draft_false_skips_pdf_and_graph(self, db, bc_graph):
        bc, graph = bc_graph
        result = _create(db, create_review_draft=False)
        assert result["success"] is True
        assert result["email_sent"] is False
        assert result["review_draft_created"] is False
        assert result["review_mailbox"] is None
        assert result["pdf_source"] is None
        assert result["pdf_error"] is None
        assert result["draft_error"] is None
        assert bc.pdf_calls == []
        assert graph.drafts == []
        assert graph.sent == []
        assert bc.created[0]["number"] == "PO-000100"

    def test_bc_create_failure_does_not_touch_graph(self, db, bc_graph):
        bc, graph = bc_graph
        bc.fail_create = True
        with pytest.raises(RuntimeError, match="bc down"):
            _create(db)
        assert bc.pdf_calls == []
        assert graph.drafts == []
        assert graph.sent == []

    def test_no_positive_qty_does_not_create(self, db, bc_graph):
        bc, graph = bc_graph
        with pytest.raises(ValueError):
            _create(db, lines=[{**LINES[0], "quantity": 0}])
        assert bc.created == []
        assert graph.drafts == []

    def test_notes_are_escaped_in_the_draft_body(self, db, bc_graph):
        _, graph = bc_graph
        _create(db, notes="<script>alert(1)</script>", vendor_name="A&B <Doors>")
        body = graph.drafts[0]["html_body"]
        assert "&lt;script&gt;" in body
        assert "<script>" not in body
        assert "A&amp;B &lt;Doors&gt;" in body


class TestGraphCreateDraft:
    def test_posts_to_drafts_folder_with_bc_bytes(self):
        client = GraphEmailClient.__new__(GraphEmailClient)
        seen = {}

        def fake(method, endpoint, **kwargs):
            seen["method"] = method
            seen["endpoint"] = endpoint
            seen["json"] = kwargs["json"]
            return {"id": "abc", "isDraft": True, "webLink": "https://outlook.example/draft"}

        client._make_request = fake
        result = client.create_draft_with_attachment(
            mailbox="joey@opendc.ca",
            to="vendor@example.com",
            subject="Purchase Order PO-000100 — Open Distribution Company Inc.",
            html_body="<p>Hello</p>",
            attachments=[{
                "name": "PO_PO-000100.pdf",
                "content_bytes": BC_PDF,
                "content_type": "application/pdf",
            }],
        )
        assert seen["method"] == "POST"
        assert seen["endpoint"] == "users/joey@opendc.ca/mailFolders/drafts/messages"
        assert "sendMail" not in seen["endpoint"]
        assert "/send" not in seen["endpoint"]
        payload = seen["json"]
        assert "saveToSentItems" not in payload
        assert payload["toRecipients"] == [
            {"emailAddress": {"address": "vendor@example.com"}},
        ]
        att = payload["attachments"][0]
        assert att["@odata.type"] == "#microsoft.graph.fileAttachment"
        assert att["name"] == "PO_PO-000100.pdf"
        assert att["contentType"] == "application/pdf"
        assert att["contentBytes"] == base64.b64encode(BC_PDF).decode("ascii")
        assert result["isDraft"] is True

    def test_non_draft_response_raises_without_a_second_call(self):
        client = GraphEmailClient.__new__(GraphEmailClient)
        calls = []

        def fake(method, endpoint, **kwargs):
            calls.append((method, endpoint))
            return {"id": "abc", "isDraft": False}

        client._make_request = fake
        with pytest.raises(RuntimeError, match="isDraft"):
            client.create_draft_with_attachment(
                mailbox="joey@opendc.ca",
                to="vendor@example.com",
                subject="PO",
                html_body="<p>x</p>",
            )
        assert calls == [("POST", "users/joey@opendc.ca/mailFolders/drafts/messages")]

    def test_send_mail_still_posts_sendmail(self):
        client = GraphEmailClient.__new__(GraphEmailClient)
        seen = {}

        def fake(method, endpoint, **kwargs):
            seen["endpoint"] = endpoint
            seen["json"] = kwargs["json"]
            return {}

        client._make_request = fake
        assert client.send_mail(
            from_email="joey@opendc.ca",
            to="someone@example.com",
            subject="hello",
            html_body="<p>hi</p>",
            attachments=[{"name": "a.pdf", "content_bytes": b"%PDF", "content_type": "application/pdf"}],
        ) is True
        assert seen["endpoint"] == "users/joey@opendc.ca/sendMail"
        assert seen["json"]["saveToSentItems"] is True
        assert seen["json"]["message"]["attachments"][0]["contentBytes"] == base64.b64encode(b"%PDF").decode()


class TestGeneratePoEndpoint:
    @pytest.fixture
    def client(self, db, bc_graph):
        admin = User(
            id=7,
            email="joey@opendc.ca",
            password_hash="x",
            role=UserRole.ADMIN,
            is_active=True,
            user_type="INTERNAL",
        )
        app = FastAPI()
        app.include_router(purchasing_router)
        app.dependency_overrides[get_current_admin] = lambda: admin

        def _override():
            yield db

        app.dependency_overrides[get_db] = _override
        return TestClient(app)

    def _post(self, client, **extra):
        body = {
            "vendor_no": "VEND1",
            "vendor_name": "Acme Doors",
            "lines": LINES,
        }
        body.update(extra)
        return client.post("/api/admin/purchasing/generate-po", json=body)

    def test_default_saves_draft_not_send(self, client, bc_graph):
        bc, graph = bc_graph
        res = self._post(client)
        assert res.status_code == 200, res.text
        data = res.json()
        assert data["email_sent"] is False
        assert data["emailed_to"] is None
        assert data["review_draft_created"] is True
        assert data["review_mailbox"] == "joey@opendc.ca"
        assert data["draft_to"] == "vendor@example.com"
        assert data["pdf_source"] == "bc"
        assert bc.pdf_calls == [PO_GUID]
        assert _attachment(graph)["content_bytes"] == BC_PDF
        assert graph.sent == []

    def test_send_email_true_still_does_not_send(self, client, bc_graph):
        _, graph = bc_graph
        res = self._post(client, send_email=True)
        assert res.status_code == 200, res.text
        assert res.json()["email_sent"] is False
        assert res.json()["review_draft_created"] is True
        assert graph.sent == []
        assert len(graph.drafts) == 1

    def test_send_email_false_skips_graph(self, client, bc_graph):
        bc, graph = bc_graph
        res = self._post(client, send_email=False)
        assert res.status_code == 200, res.text
        data = res.json()
        assert data["email_sent"] is False
        assert data["review_draft_created"] is False
        assert bc.pdf_calls == []
        assert graph.drafts == []
        assert graph.sent == []

    def test_create_review_draft_false_overrides_send_email(self, client, bc_graph):
        bc, graph = bc_graph
        res = self._post(client, create_review_draft=False, send_email=True)
        assert res.status_code == 200, res.text
        assert res.json()["review_draft_created"] is False
        assert bc.pdf_calls == []
        assert graph.sent == []

    def test_pdf_failure_is_200_with_error(self, client, bc_graph):
        bc, graph = bc_graph
        bc.pdf_error = "mediaReadLink missing"
        res = self._post(client)
        assert res.status_code == 200, res.text
        data = res.json()
        assert data["success"] is True
        assert data["email_sent"] is False
        assert "mediaReadLink missing" in data["pdf_error"]
        assert data["review_draft_created"] is False
        assert graph.sent == []
        assert graph.drafts == []
