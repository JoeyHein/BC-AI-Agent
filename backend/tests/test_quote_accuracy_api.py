"""Read-only internal sales-quote accuracy API.

Covers auth (dedicated QUOTE_ACCURACY_API_KEY), validation, header+line
mapping, line pagination, BC error mapping, and the OData nextLink helper.
BC is stubbed — these tests never call production and never write quotes.
"""
from __future__ import annotations

import os
import sys
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock

import pytest
import requests
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.api import internal_quotes
from app.api.internal_auth import _digests_match
from app.config import settings
from app.integrations.bc.client import BusinessCentralClient
from app.services import quote_accuracy_service as qa_service
from app.services.quote_accuracy_service import (
    QuoteAccuracyError,
    fetch_sales_quote_for_accuracy,
    normalize_quote_number,
)


TEST_KEY = "qak_test_quote_accuracy_key_value"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _header() -> Dict[str, Any]:
    return {
        "id": "guid-quote-1",
        "number": "SQ-003058",
        "status": "Draft",
        "customerNumber": "C000123",
        "customerName": "Example Ltd",
        "documentDate": "2026-05-01",
        "validUntilDate": "2026-06-01",
        "salesperson": "JOEY",
        "externalDocumentNumber": "PORTAL-99",
        "currencyCode": "CAD",
        "discountAmount": 0,
        "totalAmountExcludingTax": 1000.0,
        "totalTaxAmount": 50.0,
        "totalAmountIncludingTax": 1050.0,
        "email": "should-not-need-to-be-secret@example.com",
        "@odata.etag": "W/\"secret-etag\"",
    }


def _lines() -> List[Dict[str, Any]]:
    return [
        {
            "id": "line-1",
            "sequence": 10000,
            "lineType": "Comment",
            "lineObjectNumber": "",
            "description": '(1) 10x9 TX450, WHITE, UDC, 2" HW, STD LIFT',
            "quantity": 0,
            "unitPrice": 0,
        },
        {
            "id": "line-2",
            "sequence": 20000,
            "lineType": "Item",
            "lineObjectNumber": "PN45-24400-1000",
            "description": "TX450 24 WHITE",
            "description2": "10x9",
            "quantity": 4,
            "unitPrice": 120.0,
            "discountPercent": 0,
            "discountAmount": 0,
            "amountExcludingTax": 480.0,
            "taxCode": "GST",
            "taxPercent": 5,
            "totalTaxAmount": 24.0,
            "amountIncludingTax": 504.0,
            "dimensionSetLines": [
                {
                    "code": "AREA",
                    "displayName": "Area",
                    "valueCode": "AB",
                    "valueDisplayName": "Alberta",
                    "@odata.etag": "W/\"dim-etag\"",
                }
            ],
        },
        {
            "id": "line-3",
            "sequence": 30000,
            "lineType": "Item",
            "lineObjectNumber": "FREIGHT",
            "description": "Freight - AB delivery",
            "quantity": 1,
            "unitPrice": 85.0,
            "amountExcludingTax": 85.0,
            "amountIncludingTax": 85.0,
        },
    ]


class FakeBC:
    """Read-only stub. Write methods raise so a regression is obvious."""

    def __init__(self, header=None, lines=None, header_error=None, lines_error=None):
        self.header = header if header is not None else _header()
        self.lines = lines if lines is not None else _lines()
        self.header_error = header_error
        self.lines_error = lines_error
        self.header_calls = []
        self.line_calls = []

    def get_sales_quote_by_number(self, quote_number: str, company_id: Optional[str] = None):
        self.header_calls.append({"quote_number": quote_number, "company_id": company_id})
        if self.header_error:
            raise self.header_error
        return self.header

    def get_quote_lines(self, quote_id: str, company_id: Optional[str] = None, **kwargs):
        self.line_calls.append(
            {"quote_id": quote_id, "company_id": company_id, "kwargs": kwargs}
        )
        if self.lines_error:
            raise self.lines_error
        return self.lines

    def create_sales_quote(self, *args, **kwargs):
        raise AssertionError("create_sales_quote must not be called")

    def update_sales_quote(self, *args, **kwargs):
        raise AssertionError("update_sales_quote must not be called")

    def add_quote_line(self, *args, **kwargs):
        raise AssertionError("add_quote_line must not be called")

    def convert_quote_to_order(self, *args, **kwargs):
        raise AssertionError("convert_quote_to_order must not be called")

    def delete_sales_quote(self, *args, **kwargs):
        raise AssertionError("delete_sales_quote must not be called")


def _app(monkeypatch, key=TEST_KEY, fake: Optional[FakeBC] = None) -> FastAPI:
    monkeypatch.setattr(settings, "QUOTE_ACCURACY_API_KEY", key)
    if fake is not None:
        monkeypatch.setattr(qa_service, "bc_client", fake)
    test_app = FastAPI()
    test_app.include_router(internal_quotes.router)
    return test_app


def _client(monkeypatch, **kwargs) -> TestClient:
    return TestClient(_app(monkeypatch, **kwargs))


# ---------------------------------------------------------------------------
# Quote number validation
# ---------------------------------------------------------------------------


class TestNormalizeQuoteNumber:
    def test_full_document_number(self):
        assert normalize_quote_number("SQ-003058") == "SQ-003058"

    def test_short_and_unpadded(self):
        assert normalize_quote_number("3058") == "SQ-003058"
        assert normalize_quote_number("sq-3058") == "SQ-003058"

    def test_rejects_odata_metacharacters(self):
        with pytest.raises(QuoteAccuracyError) as exc:
            normalize_quote_number("SQ-001' or 1 eq 1")
        assert exc.value.code == "INVALID_REQUEST"

    def test_rejects_blank(self):
        with pytest.raises(QuoteAccuracyError) as exc:
            normalize_quote_number("   ")
        assert exc.value.code == "INVALID_REQUEST"


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


class TestAuth:
    def test_unconfigured_returns_503(self, monkeypatch):
        client = _client(monkeypatch, key=None, fake=FakeBC())
        res = client.get("/api/internal/sales-quotes/SQ-003058", headers={"X-API-Key": TEST_KEY})
        assert res.status_code == 503
        assert "not configured" in res.json()["detail"].lower()

    def test_missing_and_wrong_key_same_401(self, monkeypatch):
        fake = FakeBC()
        client = _client(monkeypatch, fake=fake)
        missing = client.get("/api/internal/sales-quotes/SQ-003058")
        wrong = client.get(
            "/api/internal/sales-quotes/SQ-003058",
            headers={"X-API-Key": "qak_this_is_not_the_key"},
        )
        assert missing.status_code == 401
        assert wrong.status_code == 401
        assert missing.json()["detail"] == wrong.json()["detail"]
        assert "qak_" not in str(missing.json())
        assert "qak_" not in str(wrong.json())
        assert fake.header_calls == []

    def test_digests_match_is_length_independent(self):
        assert _digests_match(TEST_KEY, TEST_KEY) is True
        assert _digests_match("short", TEST_KEY) is False
        assert _digests_match(TEST_KEY + "x", TEST_KEY) is False


# ---------------------------------------------------------------------------
# API contract
# ---------------------------------------------------------------------------


class TestGetSalesQuote:
    def test_happy_path_header_and_lines(self, monkeypatch):
        fake = FakeBC()
        client = _client(monkeypatch, fake=fake)
        res = client.get(
            "/api/internal/sales-quotes/3058",
            headers={"X-API-Key": TEST_KEY},
        )
        assert res.status_code == 200
        body = res.json()
        assert body["ok"] is True
        quote = body["data"]["quote"]
        assert quote["number"] == "SQ-003058"
        assert quote["customerNumber"] == "C000123"
        assert quote["totalAmountIncludingTax"] == 1050.0
        assert quote["totalTaxAmount"] == 50.0
        assert "@odata.etag" not in quote

        lines = body["data"]["lines"]
        assert body["data"]["lineCount"] == 3
        assert body["data"]["hasMore"] is False
        assert lines[0]["flags"] == ["comment"]
        assert lines[0]["description"].startswith("(1) 10x9")
        assert lines[1]["itemNumber"] == "PN45-24400-1000"
        assert lines[1]["quantity"] == 4
        assert lines[1]["unitPrice"] == 120.0
        assert "tax" in lines[1]["flags"]
        assert lines[1]["dimensionSetLines"][0]["valueCode"] == "AB"
        assert "@odata.etag" not in lines[1]["dimensionSetLines"][0]
        assert "freight" in lines[2]["flags"]

        assert fake.header_calls[0]["quote_number"] == "SQ-003058"
        assert fake.header_calls[0]["company_id"] is None
        assert fake.line_calls[0]["kwargs"].get("expand_dimensions") is True

    def test_line_pagination(self, monkeypatch):
        many = [
            {"id": f"l{i}", "sequence": i * 10000, "lineType": "Item",
             "lineObjectNumber": f"PN{i}", "description": f"item {i}",
             "quantity": 1, "unitPrice": 1.0}
            for i in range(5)
        ]
        fake = FakeBC(lines=many)
        client = _client(monkeypatch, fake=fake)
        page = client.get(
            "/api/internal/sales-quotes/SQ-003058",
            params={"line_skip": 2, "line_limit": 2},
            headers={"X-API-Key": TEST_KEY},
        )
        assert page.status_code == 200
        data = page.json()["data"]
        assert data["lineCount"] == 5
        assert data["lineSkip"] == 2
        assert data["lineLimit"] == 2
        assert data["hasMore"] is True
        assert [row["itemNumber"] for row in data["lines"]] == ["PN2", "PN3"]

        last = client.get(
            "/api/internal/sales-quotes/SQ-003058",
            params={"line_skip": 4, "line_limit": 2},
            headers={"X-API-Key": TEST_KEY},
        )
        last_data = last.json()["data"]
        assert last_data["hasMore"] is False
        assert [row["itemNumber"] for row in last_data["lines"]] == ["PN4"]

    def test_invalid_quote_number_400(self, monkeypatch):
        fake = FakeBC()
        client = _client(monkeypatch, fake=fake)
        res = client.get(
            "/api/internal/sales-quotes/not-a-quote",
            headers={"X-API-Key": TEST_KEY},
        )
        assert res.status_code == 400
        assert res.json()["ok"] is False
        assert res.json()["error"]["code"] == "INVALID_REQUEST"
        assert fake.header_calls == []

    def test_not_found_404(self, monkeypatch):
        fake = FakeBC(header=None)
        client = _client(monkeypatch, fake=fake)
        res = client.get(
            "/api/internal/sales-quotes/SQ-009999",
            headers={"X-API-Key": TEST_KEY},
        )
        assert res.status_code == 404
        assert res.json()["error"]["code"] == "NOT_FOUND"

    def test_upstream_error_502(self, monkeypatch):
        err = requests.HTTPError("500", response=MagicMock(status_code=500))
        fake = FakeBC(header_error=err)
        client = _client(monkeypatch, fake=fake)
        res = client.get(
            "/api/internal/sales-quotes/SQ-003058",
            headers={"X-API-Key": TEST_KEY},
        )
        assert res.status_code == 502
        body = res.json()
        assert body["error"]["code"] == "UPSTREAM_ERROR"
        assert body["error"]["retryable"] is True

    def test_post_not_allowed(self, monkeypatch):
        client = _client(monkeypatch, fake=FakeBC())
        res = client.post(
            "/api/internal/sales-quotes/SQ-003058",
            headers={"X-API-Key": TEST_KEY},
            json={},
        )
        assert res.status_code == 405

    def test_response_does_not_echo_api_key(self, monkeypatch):
        client = _client(monkeypatch, fake=FakeBC())
        res = client.get(
            "/api/internal/sales-quotes/SQ-003058",
            headers={"X-API-Key": TEST_KEY},
        )
        assert TEST_KEY not in res.text


class TestServiceDoesNotWrite:
    def test_lookup_never_touches_write_methods(self):
        fake = FakeBC()
        result = fetch_sales_quote_for_accuracy("SQ-003058", client=fake)
        assert result.quote["number"] == "SQ-003058"
        assert len(result.lines) == 3


# ---------------------------------------------------------------------------
# OData pagination helper
# ---------------------------------------------------------------------------


class TestFollowOdataPages:
    def test_follows_next_link_until_exhausted(self, monkeypatch):
        client = BusinessCentralClient.__new__(BusinessCentralClient)
        first = {
            "value": [{"id": "a"}],
            "@odata.nextLink": "https://bc.example/page2",
        }
        second = {"value": [{"id": "b"}]}
        client._make_request = MagicMock(return_value=first)
        client._get_access_token = MagicMock(return_value="tok")

        def fake_get(url, headers=None, timeout=None):
            assert url == "https://bc.example/page2"
            assert headers["Authorization"] == "Bearer tok"
            resp = MagicMock()
            resp.status_code = 200
            resp.content = b"{}"
            resp.json.return_value = second
            return resp

        monkeypatch.setattr("app.integrations.bc.client.requests.get", fake_get)
        rows = client._follow_odata_pages("companies(x)/salesQuotes(y)/salesQuoteLines?$top=200")
        assert [r["id"] for r in rows] == ["a", "b"]
        client._make_request.assert_called_once()

    def test_page_failure_raises_instead_of_truncating(self, monkeypatch):
        client = BusinessCentralClient.__new__(BusinessCentralClient)
        client._make_request = MagicMock(
            return_value={"value": [{"id": "a"}], "@odata.nextLink": "https://bc.example/page2"}
        )
        client._get_access_token = MagicMock(return_value="tok")

        def fake_get(url, headers=None, timeout=None):
            resp = MagicMock()
            resp.status_code = 500
            resp.reason = "Internal Server Error"
            resp.text = "boom"
            resp.content = b"boom"
            resp.json.side_effect = ValueError("not json")
            return resp

        monkeypatch.setattr("app.integrations.bc.client.requests.get", fake_get)
        with pytest.raises(requests.HTTPError):
            client._follow_odata_pages("companies(x)/salesQuotes(y)/salesQuoteLines")

    def test_get_quote_lines_retries_without_expand_on_400(self):
        client = BusinessCentralClient.__new__(BusinessCentralClient)
        client.company_id = "company-guid"
        calls = []

        def fake_follow(endpoint):
            calls.append(endpoint)
            if "$expand=dimensionSetLines" in endpoint:
                resp = MagicMock(status_code=400, text="no expand", reason="Bad Request")
                raise requests.HTTPError("400", response=resp)
            return [{"id": "line-ok"}]

        client._follow_odata_pages = fake_follow
        rows = client.get_quote_lines("quote-guid", expand_dimensions=True)
        assert rows == [{"id": "line-ok"}]
        assert any("$expand=dimensionSetLines" in c for c in calls)
        assert any("$expand=" not in c for c in calls)
