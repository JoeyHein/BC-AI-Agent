"""Staff PDF-by-SQ endpoint tests.

GET /api/admin/quotes/by-number/{sq_number}/pdf must:
  - reject unauthenticated callers
  - look up the BC sales quote by SQ number (or GUID) then stream get_quote_pdf
  - normalize bare numeric ids the same way door-config load-quote does
  - 404 when BC has no matching quote
  - leave the customer-portal PDF route out of this surface
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.api.admin_customers import get_current_admin
from app.api.admin_quotes import normalize_staff_quote_ref, router as admin_quotes_router
from app.db.models import User, UserRole


PDF_BYTES = b"%PDF-1.4 staff-quote-fixture\n%%EOF\n"
QUOTE_GUID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


class TestNormalizeStaffQuoteRef:
    def test_sq_number(self):
        assert normalize_staff_quote_ref("SQ-003132") == ("number", "SQ-003132")

    def test_sq_number_lower(self):
        assert normalize_staff_quote_ref("sq-003132") == ("number", "SQ-003132")

    def test_bare_int_padded(self):
        assert normalize_staff_quote_ref("3132") == ("number", "SQ-003132")

    def test_zero_padded_digits(self):
        assert normalize_staff_quote_ref("003132") == ("number", "SQ-003132")

    def test_guid(self):
        assert normalize_staff_quote_ref(QUOTE_GUID) == ("guid", QUOTE_GUID)

    def test_empty_rejected(self):
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc:
            normalize_staff_quote_ref("   ")
        assert exc.value.status_code == 400

    def test_garbage_rejected(self):
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc:
            normalize_staff_quote_ref("not-a-quote")
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
    test_app.include_router(admin_quotes_router)
    test_app.dependency_overrides[get_current_admin] = lambda: admin_user
    return test_app


@pytest.fixture
def client(app):
    return TestClient(app)


@pytest.fixture
def unauth_client():
    test_app = FastAPI()
    test_app.include_router(admin_quotes_router)
    return TestClient(test_app)


@pytest.fixture
def bc(monkeypatch):
    mock = MagicMock()
    mock.get_sales_quote_by_number.return_value = {
        "id": QUOTE_GUID,
        "number": "SQ-003132",
        "externalDocumentNumber": "PO-99",
    }
    mock.get_sales_quote.return_value = {
        "id": QUOTE_GUID,
        "number": "SQ-003132",
    }
    mock.get_quote_pdf.return_value = PDF_BYTES
    monkeypatch.setattr("app.api.admin_quotes.bc_client", mock)
    return mock


class TestDownloadQuotePdfByNumber:
    def test_unauthenticated_rejected(self, unauth_client, bc):
        res = unauth_client.get("/api/admin/quotes/by-number/SQ-003132/pdf")
        assert res.status_code in (401, 403)
        bc.get_quote_pdf.assert_not_called()

    def test_sq_number_happy_path(self, client, bc):
        res = client.get("/api/admin/quotes/by-number/SQ-003132/pdf")
        assert res.status_code == 200
        assert res.content == PDF_BYTES
        assert res.headers["content-type"].startswith("application/pdf")
        assert "Quote_SQ-003132.pdf" in res.headers.get("content-disposition", "")
        bc.get_sales_quote_by_number.assert_called_once_with("SQ-003132")
        bc.get_quote_pdf.assert_called_once_with(QUOTE_GUID)
        bc.get_sales_quote.assert_not_called()

    def test_bare_number_normalized(self, client, bc):
        res = client.get("/api/admin/quotes/by-number/3132/pdf")
        assert res.status_code == 200
        bc.get_sales_quote_by_number.assert_called_once_with("SQ-003132")
        bc.get_quote_pdf.assert_called_once_with(QUOTE_GUID)

    def test_guid_looks_up_by_id(self, client, bc):
        res = client.get(f"/api/admin/quotes/by-number/{QUOTE_GUID}/pdf")
        assert res.status_code == 200
        assert res.content == PDF_BYTES
        bc.get_sales_quote.assert_called_once_with(QUOTE_GUID)
        bc.get_sales_quote_by_number.assert_not_called()
        bc.get_quote_pdf.assert_called_once_with(QUOTE_GUID)

    def test_missing_quote_404(self, client, bc):
        bc.get_sales_quote_by_number.return_value = None
        res = client.get("/api/admin/quotes/by-number/SQ-009999/pdf")
        assert res.status_code == 404
        assert "SQ-009999" in res.json()["detail"]
        bc.get_quote_pdf.assert_not_called()

    def test_invalid_ref_400(self, client, bc):
        res = client.get("/api/admin/quotes/by-number/not-a-quote/pdf")
        assert res.status_code == 400
        bc.get_quote_pdf.assert_not_called()

    def test_pdf_failure_500(self, client, bc):
        bc.get_quote_pdf.side_effect = RuntimeError("mediaReadLink missing")
        res = client.get("/api/admin/quotes/by-number/SQ-003132/pdf")
        assert res.status_code == 500
        assert "Failed to download PDF" in res.json()["detail"]

    def test_bc_http_404_mapped(self, client, bc):
        import requests
        err = requests.HTTPError("404")
        err.response = MagicMock(status_code=404)
        bc.get_sales_quote_by_number.side_effect = err
        res = client.get("/api/admin/quotes/by-number/SQ-003132/pdf")
        assert res.status_code == 404
        bc.get_quote_pdf.assert_not_called()
