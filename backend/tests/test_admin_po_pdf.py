"""Staff PDF-by-PO endpoint tests.

GET /api/admin/purchasing/draft-pos/{po_number}/pdf must:
  - reject unauthenticated callers
  - look up the BC purchase order by PO number (or GUID) then stream
    get_purchase_order_pdf
  - normalize bare numeric ids to PO-XXXXXX
  - work for any status (Draft or Open/Released), unlike /validate
  - 404 when BC has no matching PO
  - hit purchaseOrders({id})/pdfDocument on the BC client
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.api.purchasing import (
    get_current_admin,
    normalize_staff_po_ref,
    router as purchasing_router,
)
from app.db.models import User, UserRole
from app.integrations.bc.client import BusinessCentralClient


PDF_BYTES = b"%PDF-1.4 staff-po-fixture\n%%EOF\n"
PO_GUID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


class TestNormalizeStaffPoRef:
    def test_po_number(self):
        assert normalize_staff_po_ref("PO-000962") == ("number", "PO-000962")

    def test_po_number_lower(self):
        assert normalize_staff_po_ref("po-000962") == ("number", "PO-000962")

    def test_bare_int_padded(self):
        assert normalize_staff_po_ref("962") == ("number", "PO-000962")

    def test_zero_padded_digits(self):
        assert normalize_staff_po_ref("000962") == ("number", "PO-000962")

    def test_guid(self):
        assert normalize_staff_po_ref(PO_GUID) == ("guid", PO_GUID)

    def test_empty_rejected(self):
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc:
            normalize_staff_po_ref("   ")
        assert exc.value.status_code == 400

    def test_garbage_rejected(self):
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc:
            normalize_staff_po_ref("not-a-po")
        assert exc.value.status_code == 400


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
    mock.get_purchase_order_by_number.return_value = {
        "id": PO_GUID,
        "number": "PO-000962",
        "status": "Draft",
    }
    mock.get_purchase_order.return_value = {
        "id": PO_GUID,
        "number": "PO-000962",
        "status": "Open",
    }
    mock.get_purchase_order_pdf.return_value = PDF_BYTES
    monkeypatch.setattr("app.api.purchasing.bc_client", mock)
    return mock


class TestBcClientPurchaseOrderPdf:
    def test_pdf_document_then_media_read_link(self):
        bc = BusinessCentralClient.__new__(BusinessCentralClient)
        bc.company_id = "cid-1"
        seen = {}

        def fake_request(method, endpoint, **kwargs):
            seen["method"] = method
            seen["endpoint"] = endpoint
            return {
                "content@odata.mediaReadLink": "https://bc.example/po.pdf",
            }

        bc._make_request = fake_request
        bc._fetch_raw_url = lambda url: seen.update(url=url) or PDF_BYTES

        pdf = bc.get_purchase_order_pdf(PO_GUID)
        assert pdf == PDF_BYTES
        assert seen["method"] == "GET"
        assert f"purchaseOrders({PO_GUID})/pdfDocument" in seen["endpoint"]
        assert seen["url"] == "https://bc.example/po.pdf"

    def test_alt_media_read_link_field(self):
        bc = BusinessCentralClient.__new__(BusinessCentralClient)
        bc.company_id = "cid-1"
        bc._make_request = lambda *a, **k: {
            "pdfDocumentContent@odata.mediaReadLink": "https://bc.example/alt.pdf",
        }
        bc._fetch_raw_url = lambda url: b"%PDF-alt"
        assert bc.get_purchase_order_pdf(PO_GUID) == b"%PDF-alt"

    def test_missing_media_link_raises(self):
        bc = BusinessCentralClient.__new__(BusinessCentralClient)
        bc.company_id = "cid-1"
        bc._make_request = lambda *a, **k: {"id": PO_GUID}
        with pytest.raises(ValueError, match="mediaReadLink"):
            bc.get_purchase_order_pdf(PO_GUID)

    def test_get_purchase_order_by_guid(self):
        bc = BusinessCentralClient.__new__(BusinessCentralClient)
        bc.company_id = "cid-1"
        seen = {}

        def fake_request(method, endpoint, **kwargs):
            seen["method"] = method
            seen["endpoint"] = endpoint
            return {"id": PO_GUID, "number": "PO-000962"}

        bc._make_request = fake_request
        row = bc.get_purchase_order(PO_GUID)
        assert row["number"] == "PO-000962"
        assert seen["method"] == "GET"
        assert f"purchaseOrders({PO_GUID})" in seen["endpoint"]
        assert "pdfDocument" not in seen["endpoint"]


class TestDownloadPoPdfByNumber:
    def test_unauthenticated_rejected(self, unauth_client, bc):
        res = unauth_client.get("/api/admin/purchasing/draft-pos/PO-000962/pdf")
        assert res.status_code in (401, 403)
        bc.get_purchase_order_pdf.assert_not_called()

    def test_po_number_happy_path(self, client, bc):
        res = client.get("/api/admin/purchasing/draft-pos/PO-000962/pdf")
        assert res.status_code == 200
        assert res.content == PDF_BYTES
        assert res.headers["content-type"].startswith("application/pdf")
        assert "PO-000962.pdf" in res.headers.get("content-disposition", "")
        bc.get_purchase_order_by_number.assert_called_once_with("PO-000962")
        bc.get_purchase_order_pdf.assert_called_once_with(PO_GUID)
        bc.get_purchase_order.assert_not_called()

    def test_bare_number_normalized(self, client, bc):
        res = client.get("/api/admin/purchasing/draft-pos/962/pdf")
        assert res.status_code == 200
        bc.get_purchase_order_by_number.assert_called_once_with("PO-000962")
        bc.get_purchase_order_pdf.assert_called_once_with(PO_GUID)

    def test_guid_looks_up_by_id(self, client, bc):
        res = client.get(f"/api/admin/purchasing/draft-pos/{PO_GUID}/pdf")
        assert res.status_code == 200
        assert res.content == PDF_BYTES
        bc.get_purchase_order.assert_called_once_with(PO_GUID)
        bc.get_purchase_order_by_number.assert_not_called()
        bc.get_purchase_order_pdf.assert_called_once_with(PO_GUID)

    def test_open_status_still_downloads(self, client, bc):
        bc.get_purchase_order_by_number.return_value = {
            "id": PO_GUID,
            "number": "PO-000962",
            "status": "Open",
        }
        res = client.get("/api/admin/purchasing/draft-pos/PO-000962/pdf")
        assert res.status_code == 200
        assert res.content == PDF_BYTES
        bc.get_purchase_order_pdf.assert_called_once_with(PO_GUID)

    def test_missing_po_404(self, client, bc):
        bc.get_purchase_order_by_number.return_value = None
        res = client.get("/api/admin/purchasing/draft-pos/PO-009999/pdf")
        assert res.status_code == 404
        assert "PO-009999" in res.json()["detail"]
        bc.get_purchase_order_pdf.assert_not_called()

    def test_invalid_ref_400(self, client, bc):
        res = client.get("/api/admin/purchasing/draft-pos/not-a-po/pdf")
        assert res.status_code == 400
        bc.get_purchase_order_pdf.assert_not_called()

    def test_pdf_failure_500(self, client, bc):
        bc.get_purchase_order_pdf.side_effect = RuntimeError("mediaReadLink missing")
        res = client.get("/api/admin/purchasing/draft-pos/PO-000962/pdf")
        assert res.status_code == 500
        assert "Failed to download PDF" in res.json()["detail"]

    def test_bc_http_404_mapped(self, client, bc):
        import requests
        err = requests.HTTPError("404")
        err.response = MagicMock(status_code=404)
        bc.get_purchase_order_by_number.side_effect = err
        res = client.get("/api/admin/purchasing/draft-pos/PO-000962/pdf")
        assert res.status_code == 404
        bc.get_purchase_order_pdf.assert_not_called()
