"""Staff Draft-PO list + buy-complete validation.

GET /api/admin/purchasing/draft-pos and .../validate must:
  - reject unauthenticated callers
  - list live BC Draft POs (status filter) with lines + SO links
  - flag missing ASTRAGAL/RETAINER/TOP SEAL when panels are on the PO
  - flag exploded-looking leftovers when buy-complete parents are present
  - leave customer-portal routes out of this surface
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.api.purchasing import get_current_admin, router as purchasing_router
from app.db.models import User, UserRole
from app.services import draft_po_review_service as mod
from app.integrations.bc.client import BusinessCentralClient
from app.services.draft_po_review_service import (
    DraftPoReviewService,
    summarize_po,
    validate_po,
)


def _line(item, qty, desc=None, seq=10000, ltype="Item"):
    return {
        "sequence": seq,
        "lineType": ltype,
        "lineObjectNumber": item if ltype == "Item" else None,
        "description": desc if desc is not None else (f"desc {item}" if item else ""),
        "quantity": qty,
        "receivedQuantity": 0,
        "unitOfMeasureCode": "EA",
    }


def _po(number="PO-000962", status="Draft", vendor="UPWARDOR", vendor_no="UPW",
        ext_doc="", lines=None, order_date="2026-09-08"):
    return {
        "id": f"guid-{number}",
        "number": number,
        "status": status,
        "vendorNumber": vendor_no,
        "vendorName": vendor,
        "orderDate": order_date,
        "postingDate": None,
        "requestedReceiptDate": "2026-09-20",
        "externalDocumentNumber": ext_doc,
        "purchaseOrderLines": lines or [],
    }


@pytest.fixture
def admin_user():
    return User(
        id=1,
        email="joey@opendc.ca",
        password_hash="x",
        role=UserRole.ADMIN,
        is_active=True,
        user_type="INTERNAL",
    )


@pytest.fixture
def app(admin_user):
    test_app = FastAPI()
    test_app.include_router(purchasing_router)
    test_app.dependency_overrides[get_current_admin] = lambda: admin_user
    return test_app


@pytest.fixture
def client(app):
    return TestClient(app)


@pytest.fixture
def unauth_client():
    test_app = FastAPI()
    test_app.include_router(purchasing_router)
    return TestClient(test_app)


@pytest.fixture
def bc(monkeypatch):
    mock = MagicMock()
    mock.get_draft_purchase_orders_with_lines.return_value = []
    mock.get_purchase_order_by_number.return_value = None
    monkeypatch.setattr(mod, "bc_client", mock)
    monkeypatch.setattr("app.api.purchasing.bc_client", mock)
    return mock


class TestBcClientDraftPoQuery:
    def test_draft_list_filters_status_and_expands_lines(self):
        calls = []
        client = BusinessCentralClient.__new__(BusinessCentralClient)
        client.base_url = "https://api.businesscentral.example/v2.0"
        client.company_id = "cid-1"

        def fake_paginate(url, label):
            calls.append((url, label))
            return []

        client._paginate_v2 = fake_paginate
        client.get_draft_purchase_orders_with_lines()
        assert len(calls) == 1
        url, label = calls[0]
        assert "purchaseOrders" in url
        assert "status eq 'Draft'" in url
        assert "$expand=purchaseOrderLines" in url
        assert label == "draft purchase orders"

    def test_get_by_number_expands_lines(self):
        client = BusinessCentralClient.__new__(BusinessCentralClient)
        client.company_id = "cid-1"
        seen = {}

        def fake_request(method, endpoint, **kwargs):
            seen["method"] = method
            seen["endpoint"] = endpoint
            return {"value": []}

        client._make_request = fake_request
        assert client.get_purchase_order_by_number("PO-000962") is None
        assert seen["method"] == "GET"
        assert "number eq 'PO-000962'" in seen["endpoint"]
        assert "$expand=purchaseOrderLines" in seen["endpoint"]


class TestSummarizeAndValidate:
    def test_extracts_so_from_external_doc_and_comments(self):
        po = _po(
            ext_doc="SO-001299",
            lines=[
                _line(None, 0, desc="Built from SO-001300 - 2026-09-10", ltype="Comment", seq=10000),
                _line("PN45-24400-0900", 3, seq=20000),
            ],
        )
        summary = summarize_po(po)
        assert summary["number"] == "PO-000962"
        assert summary["vendor_name"] == "UPWARDOR"
        assert summary["status"] == "Draft"
        assert summary["external_document_number"] == "SO-001299"
        assert summary["sales_orders"] == ["SO-001299", "SO-001300"]
        assert summary["item_line_count"] == 1
        assert summary["lines"][1]["item_number"] == "PN45-24400-0900"
        assert summary["lines"][1]["quantity"] == 3

    def test_clean_buy_complete_po_with_companions_is_ok(self):
        po = _po(lines=[
            _line("PN45-24405-1000", 3, desc="SECTION TX450"),
            _line("HK02-14120-RC", 1, desc="HARDWARE BOX STD LIFT"),
            _line("PL10-00141-00", 240, desc='ASTRAGAL, 3" RESI/COMM BOTTOM RUBBER'),
            _line("PL10-00141-00", 240, desc='BOTTOM RETAINER, 1 3/4" RESI RIGID BLACK'),
            _line("PL10-00127-00", 216, desc="TOP SEAL RUBBER (FS-1864 Die # 206)"),
        ])
        result = validate_po(po)
        assert result["ok"] is True
        assert result["has_panels"] is True
        assert "PN45-24405-1000" in result["buy_complete_parents"]
        assert "HK02-14120-RC" in result["buy_complete_parents"]
        assert result["issues"] == []

    def test_missing_companions_when_panels_present(self):
        po = _po(lines=[_line("PN45-24405-1000", 3, desc="SECTION TX450")])
        result = validate_po(po)
        assert result["ok"] is False
        assert {i["keyword"] for i in result["issues"]} == {"ASTRAGAL", "RETAINER", "TOP SEAL"}
        assert all(i["code"] == "missing_companion" for i in result["issues"])

    def test_weatherstrip_does_not_count_as_companion(self):
        po = _po(lines=[
            _line("PN46-24405-1800", 2, desc="SECTION TX450 DEC"),
            _line("PL10-08203-00", 4,
                  desc="PLASTICS, WEATHER STRIP, GALVANIZED STEEL/FLEXIBLE VINYL, WHITE, 8' (SIDES)"),
        ])
        result = validate_po(po)
        codes = {(i["code"], i.get("keyword")) for i in result["issues"]}
        assert ("missing_companion", "ASTRAGAL") in codes
        assert ("missing_companion", "RETAINER") in codes
        assert ("missing_companion", "TOP SEAL") in codes

    def test_no_companion_requirement_without_panels(self):
        po = _po(lines=[_line("HK02-14120-RC", 1, desc="HARDWARE BOX")])
        result = validate_po(po)
        assert result["has_panels"] is False
        assert result["issues"] == []
        assert result["ok"] is True

    def test_exploded_hardware_leftover_flagged_when_hk_parent_present(self):
        po = _po(lines=[
            _line("HK02-14120-RC", 1, desc="HARDWARE BOX"),
            _line("FH12-00016-00", 12, desc="END HINGE"),
        ])
        result = validate_po(po)
        leftovers = [i for i in result["issues"] if i["code"] == "exploded_leftover"]
        assert [i["item_number"] for i in leftovers] == ["FH12-00016-00"]
        assert "HK" in leftovers[0]["parent_prefixes"]

    def test_pn40_core_flagged_when_pn45_parent_present(self):
        po = _po(lines=[
            _line("PN45-24405-1000", 3, desc="SECTION TX450"),
            _line("PN40-24405-1000", 3, desc="BULK CORE"),
            _line("PL10-x", 240, desc="ASTRAGAL, 3\""),
            _line("PL10-y", 240, desc="BOTTOM RETAINER"),
            _line("PL10-z", 216, desc="TOP SEAL RUBBER"),
        ])
        result = validate_po(po)
        leftovers = [i for i in result["issues"] if i["code"] == "exploded_leftover"]
        assert [i["item_number"] for i in leftovers] == ["PN40-24405-1000"]
        assert "PN45-" in leftovers[0]["parent_prefixes"]

    def test_gl12_flagged_when_gk17_parent_present(self):
        po = _po(lines=[
            _line("GK17-25100-00", 196, desc="GLAZING KIT"),
            _line("GL12-00000-01", 208, desc="POLYCARBONATE SHEET"),
        ])
        result = validate_po(po)
        leftovers = [i for i in result["issues"] if i["code"] == "exploded_leftover"]
        assert [i["item_number"] for i in leftovers] == ["GL12-00000-01"]
        assert "GK17-" in leftovers[0]["parent_prefixes"]

    def test_raw_track_flagged_when_tr02_parent_present(self):
        po = _po(lines=[
            _line("TR02-STDBM-0812", 2, desc="2IN TRACK ASSEMBLY"),
            _line("TR11-31850-00", 2, desc="VERTICAL TRACK"),
        ])
        result = validate_po(po)
        leftovers = [i for i in result["issues"] if i["code"] == "exploded_leftover"]
        assert [i["item_number"] for i in leftovers] == ["TR11-31850-00"]

    def test_leftover_not_flagged_without_matching_parent(self):
        """A raw hinge on a PO with no hardware-kit parent is a real buy, not leftover."""
        po = _po(lines=[_line("FH12-00016-00", 12, desc="END HINGE")])
        result = validate_po(po)
        assert result["issues"] == []
        assert result["ok"] is True

    def test_companion_zero_qty_flagged(self):
        po = _po(lines=[
            _line("PN45-24405-1000", 3, desc="SECTION TX450"),
            _line("PL10-a", 0, desc="ASTRAGAL, 3\""),
            _line("PL10-b", 240, desc="BOTTOM RETAINER"),
            _line("PL10-c", 216, desc="TOP SEAL RUBBER"),
        ])
        result = validate_po(po)
        zeros = [i for i in result["issues"] if i["code"] == "companion_zero_qty"]
        assert [i["keyword"] for i in zeros] == ["ASTRAGAL"]

    def test_freight_lines_ignored(self):
        po = _po(lines=[
            _line("HK02-14120-RC", 1, desc="HARDWARE BOX"),
            _line("FREIGHT", 1, desc="FREIGHT"),
        ])
        result = validate_po(po)
        assert result["ok"] is True
        assert result["buy_complete_parents"] == ["HK02-14120-RC"]


class TestDraftPoReviewService:
    def test_list_filters_non_draft_and_optional_number(self, bc):
        bc.get_draft_purchase_orders_with_lines.return_value = [
            _po("PO-000961", status="Open", lines=[_line("HK02-1", 1)]),
            _po("PO-000962", lines=[_line("PN45-1", 2)]),
            _po("PO-000963", lines=[_line("TR02-1", 1)]),
        ]
        svc = DraftPoReviewService()
        all_drafts = svc.list_drafts()
        assert all_drafts["count"] == 2
        assert [p["number"] for p in all_drafts["purchase_orders"]] == ["PO-000962", "PO-000963"]

        one = svc.list_drafts(number="po-000962")
        assert one["count"] == 1
        assert one["purchase_orders"][0]["number"] == "PO-000962"

    def test_validate_all_bundles_issues(self, bc):
        bc.get_draft_purchase_orders_with_lines.return_value = [
            _po("PO-CLEAN", lines=[_line("HK02-14120-RC", 1, desc="HARDWARE BOX")]),
            _po("PO-PANELS", lines=[_line("PN45-24405-1000", 3, desc="SECTION")]),
        ]
        bundled = DraftPoReviewService().validate_all()
        assert bundled["count"] == 2
        assert bundled["ok"] is False
        assert "HK" in bundled["buy_complete_prefixes"]
        assert "ASTRAGAL" in bundled["companion_keywords"]
        by_no = {r["number"]: r for r in bundled["results"]}
        assert by_no["PO-CLEAN"]["ok"] is True
        assert by_no["PO-PANELS"]["ok"] is False

    def test_validate_one_missing_raises_keyerror(self, bc):
        bc.get_purchase_order_by_number.return_value = None
        with pytest.raises(KeyError):
            DraftPoReviewService().validate_one("PO-MISSING")

    def test_validate_one_non_draft_raises_valueerror(self, bc):
        bc.get_purchase_order_by_number.return_value = _po("PO-000900", status="Open")
        with pytest.raises(ValueError) as exc:
            DraftPoReviewService().validate_one("PO-000900")
        assert "not Draft" in str(exc.value)


class TestDraftPoApi:
    def test_unauthenticated_list_rejected(self, unauth_client, bc):
        res = unauth_client.get("/api/admin/purchasing/draft-pos")
        assert res.status_code in (401, 403)
        bc.get_draft_purchase_orders_with_lines.assert_not_called()

    def test_unauthenticated_validate_rejected(self, unauth_client, bc):
        res = unauth_client.get("/api/admin/purchasing/draft-pos/validate")
        assert res.status_code in (401, 403)

    def test_list_happy_path(self, client, bc):
        bc.get_draft_purchase_orders_with_lines.return_value = [
            _po(
                "PO-000962",
                ext_doc="SO-001299",
                lines=[
                    _line(None, 0, desc="Built from SO-001299", ltype="Comment"),
                    _line("PN45-24400-0900", 3, desc="SECTION TX450"),
                ],
            ),
        ]
        res = client.get("/api/admin/purchasing/draft-pos")
        assert res.status_code == 200
        body = res.json()
        assert body["count"] == 1
        po = body["purchase_orders"][0]
        assert po["number"] == "PO-000962"
        assert po["status"] == "Draft"
        assert po["vendor_name"] == "UPWARDOR"
        assert "SO-001299" in po["sales_orders"]
        items = [ln for ln in po["lines"] if ln["line_type"] == "Item"]
        assert items[0]["item_number"] == "PN45-24400-0900"
        assert items[0]["quantity"] == 3
        bc.get_draft_purchase_orders_with_lines.assert_called_once()

    def test_validate_all_endpoint(self, client, bc):
        bc.get_draft_purchase_orders_with_lines.return_value = [
            _po("PO-000962", lines=[
                _line("PN45-24405-1000", 3, desc="SECTION TX450"),
                _line("PN40-24405-1000", 3, desc="BULK CORE"),
            ]),
        ]
        res = client.get("/api/admin/purchasing/draft-pos/validate")
        assert res.status_code == 200
        body = res.json()
        assert body["ok"] is False
        assert body["count"] == 1
        codes = {i["code"] for i in body["results"][0]["issues"]}
        assert "missing_companion" in codes
        assert "exploded_leftover" in codes

    def test_validate_one_404(self, client, bc):
        bc.get_purchase_order_by_number.return_value = None
        res = client.get("/api/admin/purchasing/draft-pos/PO-MISSING/validate")
        assert res.status_code == 404

    def test_validate_one_not_draft_422(self, client, bc):
        bc.get_purchase_order_by_number.return_value = _po("PO-000900", status="Released")
        res = client.get("/api/admin/purchasing/draft-pos/PO-000900/validate")
        assert res.status_code == 422
        assert "Draft" in res.json()["detail"]

    def test_validate_one_happy_path(self, client, bc):
        bc.get_purchase_order_by_number.return_value = _po(
            "PO-000963",
            lines=[_line("HK03-20181-RC", 1, desc="COMM HARDWARE BOX")],
        )
        res = client.get("/api/admin/purchasing/draft-pos/PO-000963/validate")
        assert res.status_code == 200
        body = res.json()
        assert body["number"] == "PO-000963"
        assert body["ok"] is True
        assert body["buy_complete_parents"] == ["HK03-20181-RC"]
        bc.get_purchase_order_by_number.assert_called_once_with("PO-000963")
