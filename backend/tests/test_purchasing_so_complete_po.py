"""Staff complete SO→PO preview and create.

Lines come from so_po_generation_service.build_upwardor_po (mode complete):
door groups, full quantity, OP* and WRAP* skipped. The Outlook review draft
uses the BC purchase-order PDF and is never sent.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.api.purchasing import get_current_admin, get_db, router as purchasing_router
from app.db.models import POAgentLog, User, UserRole
from app.services import so_po_generation_service as so_po


BC_PDF = b"%PDF-1.4 bc-purchase-order-report\n%%EOF\n"
PO_GUID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
SO_NUMBER = "SO-001299"
DOOR_1 = '(1) 18\'0" x 8\'0" TX450, BLACK, UDC'
DOOR_2 = '(2) 16\'0" x 8\'0" TX450, BLACK, UDC'


def _db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    POAgentLog.__table__.create(engine)
    return sessionmaker(bind=engine)()


def _comment(desc, seq):
    return {
        "lineType": "Comment", "sequence": seq, "lineObjectNumber": None,
        "quantity": 0, "description": desc,
    }


def _item(item, qty, seq):
    return {
        "lineType": "Item", "sequence": seq, "lineObjectNumber": item,
        "quantity": qty, "description": f"desc {item}",
    }


def _sales_order(number=SO_NUMBER):
    return {
        "id": "so-1",
        "number": number,
        "customerName": "Acme Doors",
        "salesOrderLines": [
            _comment(DOOR_1, 10000),
            _item("PN45-24405-1200", 11, 20000),
            _item("SH12-11810-00", 1, 30000),
            _comment(DOOR_2, 40000),
            _item("PN45-24405-1200", 18, 50000),
            _item("OP20-01056-00", 1, 60000),
            _item("WRAPALU", 57.3, 70000),
            _item("FREIGHT", 1, 80000),
        ],
    }


class FakeBC:
    def __init__(self, so, email="buyer@upwardor.example", pdf=BC_PDF, pdf_error=None):
        self.so = so
        self.company_id = "cid-1"
        self.email = email
        self.pdf = pdf
        self.pdf_error = pdf_error
        self.created = []
        self.lines = []
        self.pdf_calls = []
        self.fail_create = False

    def get_sales_order_by_number(self, number):
        return self.so if number == self.so["number"] else None

    def get_order_lines(self, so_id):
        return self.so["salesOrderLines"]

    def get_items_by_numbers(self, numbers):
        return {n: {"unitCost": 2.5, "baseUnitOfMeasureCode": "EA"} for n in numbers}

    def create_purchase_order(self, body):
        if self.fail_create:
            raise RuntimeError("bc down")
        po = {"id": PO_GUID, "number": "PO-000100", "status": "Draft", **body}
        self.created.append(body)
        return po

    def add_purchase_order_line(self, po_id, body):
        self.lines.append((po_id, body))
        return {"id": f"line-{len(self.lines)}"}

    def get_purchase_order_pdf(self, po_id, company_id=None):
        self.pdf_calls.append(po_id)
        if self.pdf_error:
            raise RuntimeError(self.pdf_error)
        return self.pdf

    def _make_request(self, method, endpoint, **kwargs):
        if "vendors" in endpoint:
            return {"value": [{"number": "UPW", "email": self.email}] if self.email else []}
        raise AssertionError(f"unexpected _make_request {method} {endpoint}")


class FakeProd:
    """Tripwire: a netted plan would buy nothing here (stock covers the SO,
    and PN45 is buy-complete so it is not exploded). Complete mode ignores it."""

    def _make_odata_request_all(self, endpoint, query_params=None):
        if endpoint == "Items":
            return [
                {
                    "No": "PN45-24405-1200", "InventoryField": 500,
                    "Qty_on_Purch_Order": 0, "Qty_on_Sales_Order": 29,
                    "Qty_on_Component_Lines": 0, "Replenishment_System": "Prod. Order",
                    "Production_BOM_No": "BOM-PN45", "Description": "panel",
                },
                {
                    "No": "SH12-11810-00", "InventoryField": 100,
                    "Qty_on_Purch_Order": 0, "Qty_on_Sales_Order": 1,
                    "Qty_on_Component_Lines": 0, "Replenishment_System": "Purchase",
                    "Production_BOM_No": "", "Description": "shaft",
                },
            ]
        if endpoint == "ProductionBomLines":
            return [{"Production_BOM_No": "BOM-PN45", "No": "RAW-CORE", "Quantity_per": 1}]
        raise AssertionError(endpoint)


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
        return {
            "id": "draft-1",
            "webLink": "https://outlook.office.com/mail/draft/1",
            "isDraft": True,
        }


@pytest.fixture
def db():
    session = _db()
    yield session
    session.close()


@pytest.fixture
def bc_graph(monkeypatch):
    bc = FakeBC(_sales_order())
    graph = FakeGraph()
    monkeypatch.setattr(so_po, "bc_client", bc)
    monkeypatch.setattr(so_po, "bc_production_service", FakeProd())
    monkeypatch.setattr("app.services.purchasing_po_service.bc_client", bc)
    monkeypatch.setattr("app.services.purchasing_po_service.graph_client", graph)
    monkeypatch.setattr(
        "app.services.purchasing_po_service.settings.NOTIFICATION_SENDER_EMAIL",
        "joey@opendc.ca",
    )
    return bc, graph


@pytest.fixture
def client(db, bc_graph):
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


def _qty_map(lines):
    return {row["item_no"]: row["quantity"] for row in lines}


class TestPreview:
    def test_door_groups_skipped_operators_and_no_create(self, client, bc_graph):
        bc, graph = bc_graph
        res = client.get("/api/admin/purchasing/so-complete-po/preview", params={"so_number": "1299"})
        assert res.status_code == 200, res.text
        data = res.json()

        plan = so_po.compute_complete_po_lines(SO_NUMBER)
        assert data["so_number"] == SO_NUMBER
        assert data["customer_name"] == "Acme Doors"
        assert data["mode"] == "complete"
        assert data["dry_run"] is True
        assert data["bc_po_number"] is None
        assert data["bc_po_id"] is None
        assert data["vendor_no"] == "UPW"
        assert data["has_doors"] is True
        assert data["item_line_count"] == 3
        assert [door["label"] for door in data["doors"]] == [DOOR_1, DOOR_2]
        assert _qty_map(data["doors"][0]["lines"]) == {"PN45-24405-1200": 11, "SH12-11810-00": 1}
        assert _qty_map(data["doors"][1]["lines"]) == {"PN45-24405-1200": 18}
        assert data["shared_lines"] == []
        assert _qty_map(data["lines"]) == {"PN45-24405-1200": 29, "SH12-11810-00": 1}
        assert _qty_map(data["lines"]) == {row["item_no"]: row["quantity"] for row in plan["included"]}
        skipped = {row["item_no"]: row for row in data["skipped"]}
        assert set(skipped) == {"OP20-01056-00", "WRAPALU"}
        assert skipped["OP20-01056-00"]["quantity"] == 1
        assert skipped["WRAPALU"]["quantity"] == 57.3
        assert "operator" in skipped["OP20-01056-00"]["reason"]
        assert "wrapping" in skipped["WRAPALU"]["reason"]
        assert "FREIGHT" not in _qty_map(data["lines"])
        assert "RAW-CORE" not in _qty_map(data["lines"])
        assert bc.created == []
        assert bc.lines == []
        assert bc.pdf_calls == []
        assert graph.drafts == []
        assert graph.sent == []

    def test_unknown_so_is_404(self, client):
        res = client.get(
            "/api/admin/purchasing/so-complete-po/preview",
            params={"so_number": "SO-009999"},
        )
        assert res.status_code == 404, res.text

    def test_bad_number_is_400(self, client, bc_graph):
        bc, graph = bc_graph
        res = client.get(
            "/api/admin/purchasing/so-complete-po/preview",
            params={"so_number": "not-an-so"},
        )
        assert res.status_code == 400, res.text
        assert bc.created == []
        assert graph.sent == []


class TestCreate:
    def _post(self, client, **extra):
        body = {"so_number": "SO-001299"}
        body.update(extra)
        return client.post("/api/admin/purchasing/so-complete-po", json=body)

    def test_default_saves_unsent_outlook_draft_with_bc_pdf(self, client, bc_graph, db):
        bc, graph = bc_graph
        res = self._post(client, notes="ship dock 2", cc=["buyer@opendc.ca"])
        assert res.status_code == 200, res.text
        data = res.json()
        assert data["success"] is True
        assert data["created"] is True
        assert data["dry_run"] is False
        assert data["mode"] == "complete"
        assert data["bc_po_id"] == PO_GUID
        assert data["bc_po_number"] == "PO-000100"
        assert data["email_sent"] is False
        assert data["emailed_to"] is None
        assert data["review_draft_created"] is True
        assert data["review_mailbox"] == "joey@opendc.ca"
        assert data["draft_id"] == "draft-1"
        assert data["draft_to"] == "mpadda@upwardor.com, mviljoen@upwardor.com"
        assert data["pdf_source"] == "bc"
        assert data["pdf_error"] is None
        assert data["draft_error"] is None
        assert _qty_map(data["lines"]) == {"PN45-24405-1200": 29, "SH12-11810-00": 1}
        assert {row["item_no"] for row in data["skipped"]} == {"OP20-01056-00", "WRAPALU"}

        assert bc.created == [{"vendorNumber": "UPW"}]
        assert bc.pdf_calls == [PO_GUID]
        item_nos = [body.get("lineObjectNumber") for _, body in bc.lines if body["lineType"] == "Item"]
        assert item_nos == ["PN45-24405-1200", "SH12-11810-00", "PN45-24405-1200"]
        assert "OP20-01056-00" not in item_nos
        assert "WRAPALU" not in item_nos
        assert "RAW-CORE" not in item_nos
        comments = [body["description"] for _, body in bc.lines if body["lineType"] == "Comment"]
        assert DOOR_1 in comments
        assert DOOR_2 in comments
        assert any("(complete order)" in text for text in comments)

        assert graph.sent == []
        assert len(graph.drafts) == 1
        draft = graph.drafts[0]
        assert draft["mailbox"] == "joey@opendc.ca"
        assert draft["to"] == ["mpadda@upwardor.com", "mviljoen@upwardor.com"]
        assert draft["cc"] == ["buyer@opendc.ca"]
        assert "PO-000100" in draft["subject"]
        assert "Open Distribution Company Inc." in draft["subject"]
        assert "ship dock 2" in draft["html_body"]
        assert "sendMail" not in draft["subject"]
        att = draft["attachments"][0]
        assert att["content_bytes"] == BC_PDF
        assert att["content_type"] == "application/pdf"
        assert att["name"] == "PO_PO-000100.pdf"

        log = db.query(POAgentLog).one()
        assert log.bc_po_number == "PO-000100"
        assert log.emailed_to is None
        assert log.emailed_at is None
        assert log.bc_status == "Draft"
        assert log.is_auto is False
        assert log.so_allocations[SO_NUMBER] == [
            {"item_no": "PN45-24405-1200", "qty": 29},
            {"item_no": "SH12-11810-00", "qty": 1},
        ]

    def test_create_review_draft_false_skips_pdf_and_graph(self, client, bc_graph, db):
        bc, graph = bc_graph
        res = self._post(client, create_review_draft=False)
        assert res.status_code == 200, res.text
        data = res.json()
        assert data["created"] is True
        assert data["bc_po_number"] == "PO-000100"
        assert data["email_sent"] is False
        assert data["emailed_to"] is None
        assert data["review_draft_created"] is False
        assert data["review_mailbox"] is None
        assert data["pdf_source"] is None
        assert data["pdf_error"] is None
        assert data["draft_error"] is None
        assert bc.created == [{"vendorNumber": "UPW"}]
        assert bc.pdf_calls == []
        assert graph.drafts == []
        assert graph.sent == []
        assert db.query(POAgentLog).one().emailed_to is None

    def test_vendor_override_is_passed_to_bc(self, client, bc_graph):
        bc, graph = bc_graph
        res = self._post(
            client,
            vendor_no="VEND9",
            vendor_name="Other Vendor",
            create_review_draft=False,
        )
        assert res.status_code == 200, res.text
        data = res.json()
        assert data["vendor_no"] == "VEND9"
        assert data["vendor_name"] == "Other Vendor"
        assert bc.created == [{"vendorNumber": "VEND9"}]
        assert graph.sent == []
        assert graph.drafts == []

    def test_pdf_failure_keeps_po_and_skips_draft(self, client, bc_graph):
        bc, graph = bc_graph
        bc.pdf_error = "mediaReadLink missing"
        res = self._post(client)
        assert res.status_code == 200, res.text
        data = res.json()
        assert data["created"] is True
        assert data["email_sent"] is False
        assert data["review_draft_created"] is False
        assert "mediaReadLink missing" in data["pdf_error"]
        assert "Outlook review draft not created" in data["draft_error"]
        assert bc.created
        assert graph.drafts == []
        assert graph.sent == []

    def test_graph_failure_keeps_po(self, client, bc_graph):
        bc, graph = bc_graph
        graph.fail = True
        res = self._post(client)
        assert res.status_code == 200, res.text
        data = res.json()
        assert data["created"] is True
        assert data["email_sent"] is False
        assert data["review_draft_created"] is False
        assert data["pdf_source"] == "bc"
        assert "graph drafts folder" in data["draft_error"]
        assert graph.sent == []
        assert bc.created

    def test_nothing_to_order_does_not_create_or_draft(self, client, bc_graph, db):
        bc, graph = bc_graph
        empty = {
            "id": "so-empty",
            "number": "SO-001300",
            "customerName": "Acme Doors",
            "salesOrderLines": [
                _item("OP20-01056-00", 2, 10000),
                _item("WRAPALU", 10, 20000),
                _item("FREIGHT", 1, 30000),
            ],
        }
        bc.so = empty
        res = client.post("/api/admin/purchasing/so-complete-po", json={"so_number": "1300"})
        assert res.status_code == 200, res.text
        data = res.json()
        assert data["created"] is False
        assert data["bc_po_number"] is None
        assert data["email_sent"] is False
        assert data["review_draft_created"] is False
        assert data["review_mailbox"] is None
        assert "Nothing to order" in (data["note"] or "")
        assert {row["item_no"] for row in data["skipped"]} == {"OP20-01056-00", "WRAPALU"}
        assert bc.created == []
        assert bc.pdf_calls == []
        assert graph.drafts == []
        assert graph.sent == []
        assert db.query(POAgentLog).count() == 0

    def test_bc_create_failure_does_not_touch_graph(self, client, bc_graph):
        bc, graph = bc_graph
        bc.fail_create = True
        res = self._post(client)
        assert res.status_code == 502, res.text
        assert bc.pdf_calls == []
        assert graph.drafts == []
        assert graph.sent == []

    def test_missing_vendor_email_still_saves_unaddressed_draft(self, client, bc_graph):
        bc, graph = bc_graph
        bc.email = ""
        # UPW has configured buyers, so a blank card still gets those addresses.
        # A vendor without an override keeps the old "no To" behavior.
        res = self._post(client, vendor_no="LYNX", vendor_name="LYNX")
        assert res.status_code == 200, res.text
        data = res.json()
        assert data["review_draft_created"] is True
        assert data["draft_to"] is None
        assert data["email_sent"] is False
        assert "no To address" in data["draft_warning"]
        assert graph.drafts[0]["to"] is None
        assert graph.sent == []
