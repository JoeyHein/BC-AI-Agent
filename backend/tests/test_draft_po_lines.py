"""Draft PO line edit / delete / add / reorder / normalize. BC is in-memory."""
from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest
import requests
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.api.purchasing import get_current_admin, router as purchasing_router
from app.db.models import User, UserRole
from app.services.draft_po_lines_service import DraftPoEditError, draft_po_lines_service


PO_NUMBER = "PO-000962"
PO_ID = "po-guid-962"


def _line(line_id, item, seq, **extra):
    row = {
        "id": line_id,
        "sequence": seq,
        "lineType": "Item",
        "lineObjectNumber": item,
        "description": extra.pop("description", f"desc {item}"),
        "quantity": extra.pop("quantity", 2),
        "directUnitCost": extra.pop("directUnitCost", 10),
        "unitOfMeasureCode": extra.pop("unitOfMeasureCode", "EA"),
        "receivedQuantity": extra.pop("receivedQuantity", 0),
        "locationId": extra.pop("locationId", "loc-1"),
    }
    row.update(extra)
    return row


def _comment(line_id, text, seq):
    return {
        "id": line_id,
        "sequence": seq,
        "lineType": "Comment",
        "description": text,
        "quantity": 0,
        "receivedQuantity": 0,
    }


def _po(status="Draft", lines=None):
    return {
        "id": PO_ID,
        "number": PO_NUMBER,
        "status": status,
        "purchaseOrderLines": lines if lines is not None else [
            _comment("c1", '(1) 18\'0" x 8\'0" TX450, BLACK', 10000),
            _line("hk", "HK02-14120-RC", 20000, description="HARDWARE BOX"),
            _line("glass", "PN12-24300820-1602", 30000, description="GLASS SECTION", dropShipment=True),
            _line("panel", "PN45-24400-0900", 40000, description="INSULATED SECTION"),
        ],
    }


class MemBC:
    def __init__(self, po):
        self.po = po
        self.adds = 0
        self.fail_on_add = set()
        self.corrupt_next_reread = False
        self._corrupted = False
        self.deleted = []

    def get_purchase_order_by_number(self, number):
        if self.po and self.po.get("number") == number:
            return self._view()
        return None

    def get_purchase_order_with_lines(self, po_id):
        if not self.po or self.po.get("id") != po_id:
            err = requests.HTTPError(f"404 missing {po_id}")
            err.response = type("R", (), {"status_code": 404, "text": "missing"})()
            raise err
        return self._view(reread=True)

    def _view(self, *, reread=False):
        po = copy.deepcopy(self.po)
        if reread and self.corrupt_next_reread and self.adds and not self._corrupted:
            self._corrupted = True
            item_lines = [ln for ln in po.get("purchaseOrderLines") or [] if ln.get("lineType") == "Item"]
            if item_lines:
                item_lines[0]["quantity"] = 999
        return po

    def update_purchase_order_line(self, po_id, line_id, data):
        for ln in self.po["purchaseOrderLines"]:
            if ln["id"] == line_id:
                ln.update(data)
                return copy.deepcopy(ln)
        raise requests.HTTPError(f"404 line {line_id}")

    def delete_purchase_order_line(self, po_id, line_id):
        before = len(self.po["purchaseOrderLines"])
        self.po["purchaseOrderLines"] = [
            ln for ln in self.po["purchaseOrderLines"] if ln["id"] != line_id
        ]
        if len(self.po["purchaseOrderLines"]) == before:
            raise requests.HTTPError(f"404 line {line_id}")
        self.deleted.append(line_id)
        return True

    def add_purchase_order_line(self, po_id, data):
        self.adds += 1
        if self.adds in self.fail_on_add:
            raise requests.HTTPError(f"500 add {self.adds} failed")
        line = {
            "id": f"new-{self.adds}",
            "receivedQuantity": 0,
            "unitOfMeasureCode": data.get("unitOfMeasureCode"),
            "locationId": data.get("locationId"),
            "directUnitCost": data.get("directUnitCost", 0),
            "quantity": data.get("quantity", 0),
            "description": data.get("description") or "",
            "lineObjectNumber": data.get("lineObjectNumber"),
            "lineType": data.get("lineType"),
            "sequence": data.get("sequence"),
        }
        for key in (
            "dropShipment", "specialOrder", "salesOrderId", "salesOrderLineId",
            "description2",
        ):
            if key in data:
                line[key] = data[key]
        self.po["purchaseOrderLines"].append(line)
        return copy.deepcopy(line)


@pytest.fixture
def mem(monkeypatch):
    bc = MemBC(_po())
    monkeypatch.setattr("app.services.draft_po_lines_service.bc_client", bc)
    return bc


@pytest.fixture
def admin_user():
    return User(
        id=7, email="joey@opendc.ca", password_hash="x",
        role=UserRole.ADMIN, is_active=True, user_type="INTERNAL",
    )


@pytest.fixture
def client(admin_user):
    app = FastAPI()
    app.include_router(purchasing_router)
    app.dependency_overrides[get_current_admin] = lambda: admin_user
    return TestClient(app)


def _items(payload):
    return [
        (ln["line_type"], ln["item_number"], ln["description"])
        for ln in payload["lines"]
    ]


class TestEdits:
    def test_patch_quantity_description_cost_and_item(self, client, mem):
        res = client.patch(
            f"/api/admin/purchasing/draft-pos/{PO_NUMBER}/lines/panel",
            json={
                "quantity": 6,
                "description": "TX450 section",
                "unit_cost": 12.5,
                "item_no": "PN45-24405-1000",
            },
        )
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["changed"] is True
        panel = next(ln for ln in body["lines"] if ln["id"] == "panel")
        assert panel["quantity"] == 6
        assert panel["description"] == "TX450 section"
        assert panel["unit_cost"] == 12.5
        assert panel["item_number"] == "PN45-24405-1000"
        assert panel["panel_class"] == "insulated"
        stored = next(ln for ln in mem.po["purchaseOrderLines"] if ln["id"] == "panel")
        assert stored["directUnitCost"] == 12.5
        assert mem.deleted == []

    def test_description_over_100_is_400_and_does_not_write(self, client, mem):
        res = client.patch(
            f"/api/admin/purchasing/draft-pos/{PO_NUMBER}/lines/panel",
            json={"description": "x" * 101},
        )
        assert res.status_code == 400, res.text
        assert "100" in res.json()["detail"]
        stored = next(ln for ln in mem.po["purchaseOrderLines"] if ln["id"] == "panel")
        assert stored["description"] == "INSULATED SECTION"

    def test_delete_and_add_comment_and_item(self, client, mem):
        deleted = client.delete(f"/api/admin/purchasing/draft-pos/{PO_NUMBER}/lines/hk")
        assert deleted.status_code == 200, deleted.text
        assert "hk" in mem.deleted
        assert all(ln["id"] != "hk" for ln in deleted.json()["lines"])

        comment = client.post(
            f"/api/admin/purchasing/draft-pos/{PO_NUMBER}/lines",
            json={"line_type": "blank", "description": "Five wall required"},
        )
        assert comment.status_code == 200, comment.text
        assert any(ln["description"] == "Five wall required" and ln["line_type"] == "Comment"
                   for ln in comment.json()["lines"])

        added = client.post(
            f"/api/admin/purchasing/draft-pos/{PO_NUMBER}/lines",
            json={
                "line_type": "Item",
                "item_no": "PL10-00141-00",
                "description": "RETAINER",
                "quantity": 4,
                "unit_cost": 1.25,
                "unit_of_measure": "EA",
            },
        )
        assert added.status_code == 200, added.text
        retainer = next(ln for ln in added.json()["lines"] if ln["item_number"] == "PL10-00141-00")
        assert retainer["quantity"] == 4
        assert retainer["unit_cost"] == 1.25
        assert retainer["panel_class"] == "rest"

    def test_comment_rejects_item_number(self, client, mem):
        res = client.patch(
            f"/api/admin/purchasing/draft-pos/{PO_NUMBER}/lines/c1",
            json={"item_no": "PN45-24400-0900"},
        )
        assert res.status_code == 400, res.text
        assert mem.deleted == []

    def test_unknown_line_is_404(self, client, mem):
        res = client.delete(f"/api/admin/purchasing/draft-pos/{PO_NUMBER}/lines/missing")
        assert res.status_code == 404, res.text


class TestReleased:
    def test_released_is_refused_with_a_clear_error(self, client, mem):
        mem.po["status"] = "Released"
        res = client.post(
            f"/api/admin/purchasing/draft-pos/{PO_NUMBER}/lines/normalize-order",
            json={"dry_run": True},
        )
        assert res.status_code == 422, res.text
        detail = res.json()["detail"]
        assert "Released" in detail
        assert "not Draft" in detail
        assert "not reopened" in detail
        assert mem.deleted == []
        assert mem.adds == 0

    def test_open_status_is_refused(self, client, mem):
        mem.po["status"] = "Open"
        res = client.patch(
            f"/api/admin/purchasing/draft-pos/{PO_NUMBER}/lines/panel",
            json={"quantity": 3},
        )
        assert res.status_code == 422, res.text
        assert mem.po["purchaseOrderLines"][3]["quantity"] == 2

    def test_received_quantity_is_refused(self, client, mem):
        mem.po["purchaseOrderLines"][1]["receivedQuantity"] = 1
        res = client.delete(f"/api/admin/purchasing/draft-pos/{PO_NUMBER}/lines/hk")
        assert res.status_code == 422, res.text
        assert "received" in res.json()["detail"]
        assert mem.deleted == []


class TestReorderAndNormalize:
    def test_reorder_rebuilds_and_preserves_linkage(self, client, mem):
        res = client.post(
            f"/api/admin/purchasing/draft-pos/{PO_NUMBER}/lines/reorder",
            json={"line_ids": ["c1", "panel", "glass", "hk"]},
        )
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["dry_run"] is False
        assert body["changed"] is True
        assert [ln["item_number"] for ln in body["lines"]] == [
            None, "PN45-24400-0900", "PN12-24300820-1602", "HK02-14120-RC",
        ]
        stored = {ln["lineObjectNumber"]: ln for ln in mem.po["purchaseOrderLines"]}
        glass = stored["PN12-24300820-1602"]
        assert glass["dropShipment"] is True
        assert glass["locationId"] == "loc-1"
        assert glass["quantity"] == 2
        assert glass["directUnitCost"] == 10
        assert glass["unitOfMeasureCode"] == "EA"
        assert glass["description"] == "GLASS SECTION"
        # Original ids were deleted; the PO now has the rebuilt lines only.
        assert {ln["id"] for ln in mem.po["purchaseOrderLines"]} == {f"new-{n}" for n in range(1, 5)}

    def test_reorder_must_list_every_line(self, client, mem):
        res = client.post(
            f"/api/admin/purchasing/draft-pos/{PO_NUMBER}/lines/reorder",
            json={"line_ids": ["c1", "panel"]},
        )
        assert res.status_code == 400, res.text
        assert mem.adds == 0
        assert mem.deleted == []

    def test_normalize_dry_run_does_not_write(self, client, mem):
        before = copy.deepcopy(mem.po["purchaseOrderLines"])
        res = client.post(
            f"/api/admin/purchasing/draft-pos/{PO_NUMBER}/lines/normalize-order",
            json={"dry_run": True},
        )
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["dry_run"] is True
        assert body["changed"] is True
        assert [ln["item_number"] for ln in body["lines"]] == [
            None, "PN45-24400-0900", "PN12-24300820-1602", "HK02-14120-RC",
        ]
        assert [ln["panel_class"] for ln in body["lines"]] == [
            "comment", "insulated", "glass", "rest",
        ]
        assert [ln["id"] for ln in body["current_lines"]] == ["c1", "hk", "glass", "panel"]
        assert mem.po["purchaseOrderLines"] == before
        assert mem.adds == 0

    def test_normalize_apply_writes_panels_first(self, client, mem):
        res = client.post(
            f"/api/admin/purchasing/draft-pos/{PO_NUMBER}/lines/normalize-order",
            json={"dry_run": False},
        )
        assert res.status_code == 200, res.text
        assert res.json()["dry_run"] is False
        assert [ln["item_number"] for ln in res.json()["lines"]] == [
            None, "PN45-24400-0900", "PN12-24300820-1602", "HK02-14120-RC",
        ]
        assert mem.adds == 4

    def test_normalize_defaults_to_dry_run(self, client, mem):
        res = client.post(
            f"/api/admin/purchasing/draft-pos/{PO_NUMBER}/lines/normalize-order",
            json={},
        )
        assert res.status_code == 200, res.text
        assert res.json()["dry_run"] is True
        assert mem.adds == 0

    def test_failed_rebuild_restores_the_snapshot(self, client, mem):
        snapshot = copy.deepcopy(mem.po["purchaseOrderLines"])
        mem.fail_on_add = {2}
        res = client.post(
            f"/api/admin/purchasing/draft-pos/{PO_NUMBER}/lines/reorder",
            json={"line_ids": ["panel", "glass", "hk", "c1"]},
        )
        assert res.status_code == 502, res.text
        assert "restored" in res.json()["detail"]
        restored = mem.po["purchaseOrderLines"]
        assert [(ln["lineType"], ln.get("lineObjectNumber"), ln.get("description")) for ln in restored] == [
            (ln["lineType"], ln.get("lineObjectNumber"), ln.get("description")) for ln in snapshot
        ]
        assert restored[2]["dropShipment"] is True
        assert len(restored) == len(snapshot)

    def test_verification_mismatch_rolls_back(self, client, mem):
        snapshot_items = [ln.get("lineObjectNumber") for ln in mem.po["purchaseOrderLines"]]
        mem.corrupt_next_reread = True
        res = client.post(
            f"/api/admin/purchasing/draft-pos/{PO_NUMBER}/lines/normalize-order",
            json={"dry_run": False},
        )
        assert res.status_code == 502, res.text
        assert "restored" in res.json()["detail"]
        assert [ln.get("lineObjectNumber") for ln in mem.po["purchaseOrderLines"]] == snapshot_items


class TestAuth:
    def test_unauthenticated_rejected(self, mem):
        app = FastAPI()
        app.include_router(purchasing_router)
        client = TestClient(app)
        res = client.post(
            f"/api/admin/purchasing/draft-pos/{PO_NUMBER}/lines/normalize-order",
            json={"dry_run": False},
        )
        assert res.status_code in (401, 403)
        assert mem.adds == 0
        assert mem.deleted == []


def test_service_refuses_missing_po(mem):
    with pytest.raises(DraftPoEditError) as caught:
        draft_po_lines_service.get_lines("number", "PO-000001")
    assert caught.value.status_code == 404
