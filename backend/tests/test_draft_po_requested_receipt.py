"""Set, recompute, and backfill requested receipt dates on Draft POs only."""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pytest
import requests
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.api.purchasing import get_current_admin, router as purchasing_router
from app.db.models import User, UserRole


TODAY = date(2026, 10, 13)
PO_NUMBER = "PO-000962"
PO_ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


def _po(**overrides):
    row = {
        "id": PO_ID,
        "number": PO_NUMBER,
        "status": "Draft",
        "vendorNumber": "UPW",
        "vendorName": "UPWARDOR",
        "orderDate": "2026-09-01",
        "requestedReceiptDate": "0001-01-01",
    }
    row.update(overrides)
    return row


class _Response:
    def __init__(self, status_code):
        self.status_code = status_code
        self.text = "missing"


class MemBC:
    def __init__(self, pos):
        self.pos = {po["number"]: po for po in pos}
        self.by_id = {po["id"]: po for po in pos}
        self.patches = []
        self.drafts = list(pos)
        self.fail_ids = set()

    def get_purchase_order_by_number(self, number, company_id=None):
        return self.pos.get(number)

    def get_purchase_order(self, po_id, company_id=None):
        po = self.by_id.get(po_id)
        if po is None:
            raise requests.HTTPError("404", response=_Response(404))
        return po

    def update_purchase_order(self, po_id, data, company_id=None):
        if po_id in self.fail_ids:
            raise requests.HTTPError("500 rejected")
        self.patches.append((po_id, dict(data)))
        po = self.by_id[po_id]
        po.update(data)
        return dict(po)

    def get_draft_purchase_orders(self, company_id=None):
        return [dict(po) for po in self.drafts]


@pytest.fixture
def frozen_today(monkeypatch):
    monkeypatch.setattr(
        "app.services.draft_po_receipt_service.business_today",
        lambda: TODAY,
    )


@pytest.fixture
def mem(monkeypatch):
    bc = MemBC([_po()])
    monkeypatch.setattr("app.services.draft_po_receipt_service.bc_client", bc)
    return bc


@pytest.fixture
def client(mem):
    admin = User(
        id=7, email="joey@opendc.ca", password_hash="x",
        role=UserRole.ADMIN, is_active=True, user_type="INTERNAL",
    )
    app = FastAPI()
    app.include_router(purchasing_router)
    app.dependency_overrides[get_current_admin] = lambda: admin
    return TestClient(app)


def _post(client, ref=PO_NUMBER, **body):
    return client.post(
        f"/api/admin/purchasing/draft-pos/{ref}/requested-receipt",
        json=body,
    )


class TestSetOrRecompute:
    def test_recompute_uses_the_po_date(self, client, mem, frozen_today):
        res = _post(client, recompute=True)
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["requested_receipt_date"] == "2026-09-22"
        assert body["receipt_base_date"] == "2026-09-01"
        assert body["receipt_rule"] == "upwardor"
        assert body["receipt_lead_days"] == 21
        assert body["ship_when_ready"] is False
        assert body["previous_requested_receipt_date"] is None
        assert body["changed"] is True
        assert body["applied"] is True
        assert body["email_line"] == "Required in our warehouse by September 22, 2026."
        assert mem.patches == [(PO_ID, {"requestedReceiptDate": "2026-09-22"})]
        assert mem.pos[PO_NUMBER]["requestedReceiptDate"] == "2026-09-22"

    def test_recompute_again_does_not_write(self, client, mem, frozen_today):
        first = _post(client, recompute=True)
        assert first.status_code == 200, first.text
        mem.patches.clear()
        second = _post(client, recompute=True)
        assert second.status_code == 200, second.text
        assert second.json()["changed"] is False
        assert second.json()["applied"] is False
        assert mem.patches == []

    def test_blank_order_date_recomputes_from_today(self, client, mem, frozen_today):
        mem.pos[PO_NUMBER]["orderDate"] = "0001-01-01"
        res = _post(client, recompute=True)
        assert res.status_code == 200, res.text
        assert res.json()["receipt_base_date"] == "2026-10-13"
        assert res.json()["requested_receipt_date"] == "2026-11-03"
        assert mem.patches == [(PO_ID, {"requestedReceiptDate": "2026-11-03"})]

    def test_as_of_overrides_the_po_date(self, client, mem):
        res = _post(client, recompute=True, as_of="2026-10-13")
        assert res.status_code == 200, res.text
        assert res.json()["requested_receipt_date"] == "2026-11-03"
        assert res.json()["receipt_base_date"] == "2026-10-13"

    def test_explicit_date_on_a_named_vendor(self, client, mem):
        res = _post(client, requested_receipt_date="2026-12-01")
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["source"] == "set"
        assert body["requested_receipt_date"] == "2026-12-01"
        assert body["receipt_base_date"] is None
        assert body["email_line"] == "Required in our warehouse by December 1, 2026."
        assert mem.patches == [(PO_ID, {"requestedReceiptDate": "2026-12-01"})]

    def test_other_vendor_email_says_ship_when_ready(self, client, mem):
        mem.pos[PO_NUMBER]["vendorNumber"] = "DEK"
        mem.pos[PO_NUMBER]["vendorName"] = "Dek Canada"
        res = _post(client, recompute=True, as_of="2026-10-13")
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["receipt_rule"] == "ship_when_ready"
        assert body["receipt_lead_days"] == 2
        assert body["requested_receipt_date"] == "2026-10-15"
        assert body["ship_when_ready"] is True
        assert body["email_line"] == "Please ship when ready."

    def test_nice_and_elton_are_fourteen_days(self, client, mem):
        mem.pos[PO_NUMBER]["vendorNumber"] = ""
        mem.pos[PO_NUMBER]["vendorName"] = "Nice Canada"
        nice = _post(client, recompute=True, as_of="2026-10-13")
        assert nice.json()["receipt_rule"] == "nice_canada"
        assert nice.json()["requested_receipt_date"] == "2026-10-27"
        mem.pos[PO_NUMBER]["vendorNumber"] = "ELT"
        mem.pos[PO_NUMBER]["vendorName"] = "Elton Manufacturing"
        mem.pos[PO_NUMBER]["requestedReceiptDate"] = "0001-01-01"
        elton = _post(client, recompute=True, as_of="2026-10-13")
        assert elton.json()["receipt_rule"] == "elton"
        assert elton.json()["requested_receipt_date"] == "2026-10-27"

    def test_open_and_released_are_not_written(self, client, mem):
        for status in ("Open", "Released"):
            mem.patches.clear()
            mem.pos[PO_NUMBER]["status"] = status
            mem.pos[PO_NUMBER]["requestedReceiptDate"] = "0001-01-01"
            res = _post(client, recompute=True)
            assert res.status_code == 422, res.text
            assert "not Draft" in res.json()["detail"]
            assert mem.patches == []
            assert mem.pos[PO_NUMBER]["requestedReceiptDate"] == "0001-01-01"

    def test_missing_po_is_404(self, client, mem):
        res = _post(client, ref="PO-009999", recompute=True)
        assert res.status_code == 404, res.text
        assert mem.patches == []

    def test_bad_identifier_is_400(self, client, mem):
        res = _post(client, ref="not-a-po", recompute=True)
        assert res.status_code == 400, res.text
        assert mem.patches == []

    def test_guid_recompute(self, client, mem):
        res = _post(client, ref=PO_ID, recompute=True, as_of="2026-10-13")
        assert res.status_code == 200, res.text
        assert res.json()["bc_po_number"] == PO_NUMBER
        assert mem.patches

    def test_rejects_both_or_neither_or_a_blank_date(self, client, mem):
        both = _post(client, recompute=True, requested_receipt_date="2026-12-01")
        assert both.status_code == 400, both.text
        neither = _post(client)
        assert neither.status_code == 400, neither.text
        blank = _post(client, requested_receipt_date="0001-01-01")
        assert blank.status_code == 400, blank.text
        assert mem.patches == []

    def test_unauthenticated_rejected(self, mem):
        app = FastAPI()
        app.include_router(purchasing_router)
        anon = TestClient(app)
        res = anon.post(
            f"/api/admin/purchasing/draft-pos/{PO_NUMBER}/requested-receipt",
            json={"recompute": True},
        )
        assert res.status_code in (401, 403)
        assert mem.patches == []


class TestBackfill:
    def test_dry_run_previews_from_today_and_does_not_write(self, client, mem, frozen_today):
        other = _po(
            id="po-2",
            number="PO-000963",
            vendorNumber="DEK",
            vendorName="Dek Canada",
            orderDate="2026-01-01",
            requestedReceiptDate="0001-01-01",
        )
        released = _po(
            id="po-3",
            number="PO-000900",
            status="Released",
            vendorNumber="LYNX",
            vendorName="LYNX",
        )
        mem.drafts = [mem.pos[PO_NUMBER], other, released]
        mem.pos[other["number"]] = other
        mem.by_id[other["id"]] = other

        res = client.post("/api/admin/purchasing/draft-pos/requested-receipt/backfill", json={})
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["dry_run"] is True
        assert body["as_of"] == "2026-10-13"
        assert body["updated"] == 0
        assert body["would_update"] == 2
        assert body["skipped"] == 1
        assert body["failed"] == 0
        assert mem.patches == []
        by_number = {row["bc_po_number"]: row for row in body["results"]}
        assert by_number[PO_NUMBER]["requested_receipt_date"] == "2026-11-03"
        assert by_number[PO_NUMBER]["receipt_rule"] == "upwardor"
        assert by_number[PO_NUMBER]["applied"] is False
        assert by_number["PO-000963"]["requested_receipt_date"] == "2026-10-15"
        assert by_number["PO-000963"]["email_line"] == "Please ship when ready."
        assert by_number["PO-000900"]["skipped"] is True
        assert "not Draft" in by_number["PO-000900"]["error"]

    def test_apply_writes_drafts_only_and_is_idempotent(self, client, mem, frozen_today):
        nice = _po(
            id="po-nice",
            number="PO-000970",
            vendorNumber="",
            vendorName="Micanan",
            orderDate="2025-01-01",
            requestedReceiptDate="0001-01-01",
        )
        already = _po(
            id="po-done",
            number="PO-000971",
            vendorNumber="LYNX",
            vendorName="LYNX",
            requestedReceiptDate="2026-10-27",
        )
        mem.drafts = [mem.pos[PO_NUMBER], nice, already]
        for row in (nice, already):
            mem.pos[row["number"]] = row
            mem.by_id[row["id"]] = row

        res = client.post(
            "/api/admin/purchasing/draft-pos/requested-receipt/backfill",
            json={"dry_run": False},
        )
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["dry_run"] is False
        assert body["updated"] == 2
        assert body["unchanged"] == 1
        assert body["skipped"] == 0
        written = {po_id: data["requestedReceiptDate"] for po_id, data in mem.patches}
        assert written == {PO_ID: "2026-11-03", "po-nice": "2026-10-27"}
        assert "po-done" not in written

        mem.patches.clear()
        # The list endpoint returns copies taken at call time. Refresh them
        # from the documents the first apply wrote.
        mem.drafts = [mem.by_id[row["id"]] for row in mem.drafts]
        again = client.post(
            "/api/admin/purchasing/draft-pos/requested-receipt/backfill",
            json={"dry_run": False},
        )
        assert again.status_code == 200, again.text
        assert again.json()["updated"] == 0
        assert again.json()["unchanged"] == 3
        assert mem.patches == []

    def test_one_failure_does_not_stop_the_rest(self, client, mem, frozen_today):
        second = _po(id="po-2", number="PO-000963", vendorNumber="ELT", vendorName="Elton Manufacturing")
        mem.drafts = [mem.pos[PO_NUMBER], second]
        mem.pos[second["number"]] = second
        mem.by_id[second["id"]] = second
        mem.fail_ids.add(PO_ID)
        res = client.post(
            "/api/admin/purchasing/draft-pos/requested-receipt/backfill",
            json={"dry_run": False},
        )
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["failed"] == 1
        assert body["updated"] == 1
        assert mem.patches == [("po-2", {"requestedReceiptDate": "2026-10-27"})]
        failed = next(row for row in body["results"] if row["bc_po_number"] == PO_NUMBER)
        assert failed["error"]
        assert failed["applied"] is False

    def test_empty_body_is_a_dry_run(self, client, mem, frozen_today):
        res = client.post("/api/admin/purchasing/draft-pos/requested-receipt/backfill")
        assert res.status_code == 200, res.text
        assert res.json()["dry_run"] is True
        assert mem.patches == []
