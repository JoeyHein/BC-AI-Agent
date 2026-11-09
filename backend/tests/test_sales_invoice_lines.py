"""Staff posted-sales-invoice line API.

Covers the two BC paging bugs this endpoint has to survive:
- ODataV4 PostedSalesInvoices returns $top rows and no @odata.nextLink
- salesInvoiceLine has no postingDate, so the date filter belongs on the header
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.api.admin_customers import get_current_admin
from app.api.admin_sales import router as admin_sales_router
from app.db.models import User, UserRole
from app.integrations.bc.client import BusinessCentralClient
from app.integrations.bc.paging import collect_odata_pages
from app.services import sales_invoice_lines_service as lines_service
from app.services.bc_metrics_service import BCMetricsService
from app.services.sales_invoice_lines_service import flatten_invoice_lines


def _rows(n, start=0, key="id"):
    return [{key: f"row-{i}"} for i in range(start, start + n)]


class _Resp:
    def __init__(self, payload, status=200, text=""):
        self.status_code = status
        self._payload = payload
        self.text = text

    def json(self):
        return self._payload


class TestCollectOdataPages:
    def test_follows_next_link_past_500(self):
        def fetch(url):
            if url.endswith("/p1"):
                return {
                    "value": _rows(500),
                    "@odata.nextLink": "https://bc.test/p2",
                }
            return {"value": _rows(120, start=500)}

        rows, complete = collect_odata_pages(
            fetch, "https://bc.test/p1", lambda skip: f"https://bc.test/skip/{skip}", 500,
        )
        assert complete is True
        assert len(rows) == 620

    def test_skip_when_odata_omits_next_link(self):
        """The PostedSalesInvoices failure mode: $top=500, no nextLink, more rows exist."""
        calls = []

        def fetch(url):
            calls.append(url)
            skip = int(url.rsplit("/", 1)[-1]) if "/skip/" in url else 0
            if skip == 0:
                return {"value": _rows(500)}
            if skip == 500:
                return {"value": _rows(500, start=500)}
            if skip == 1000:
                return {"value": _rows(40, start=1000)}
            return {"value": []}

        rows, complete = collect_odata_pages(
            fetch,
            "https://bc.test/first",
            lambda skip: f"https://bc.test/skip/{skip}",
            page_size=500,
        )
        assert complete is True
        assert len(rows) == 1040
        assert calls == [
            "https://bc.test/first",
            "https://bc.test/skip/500",
            "https://bc.test/skip/1000",
        ]

    def test_known_silent_cap_still_skips_when_page_size_is_larger(self):
        def fetch(url):
            skip = int(url.rsplit("/", 1)[-1]) if "/skip/" in url else 0
            if skip >= 1000:
                return {"value": _rows(10, start=skip)}
            return {"value": _rows(500, start=skip)}

        rows, complete = collect_odata_pages(
            fetch, "https://bc.test/first", lambda skip: f"https://bc.test/skip/{skip}", 2000,
        )
        assert complete is True
        assert len(rows) == 1010

    def test_repeated_page_stops_instead_of_looping(self):
        def fetch(url):
            return {"value": _rows(500)}

        rows, complete = collect_odata_pages(
            fetch, "https://bc.test/first", lambda skip: f"https://bc.test/skip/{skip}", 500,
        )
        assert complete is False
        assert len(rows) == 500

    def test_http_error_is_incomplete_and_keeps_earlier_rows(self):
        def fetch(url):
            if "/skip/" in url:
                return {"value": [], "_error": True}
            return {"value": _rows(500)}

        rows, complete = collect_odata_pages(
            fetch, "https://bc.test/first", lambda skip: f"https://bc.test/skip/{skip}", 500,
        )
        assert complete is False
        assert len(rows) == 500


def _bare_client():
    client = BusinessCentralClient.__new__(BusinessCentralClient)
    client.base_url = "https://bc.test/api/v2.0"
    client.odata_url = "https://bc.test/ODataV4"
    client.company_id = "company-guid"
    client._get_access_token = lambda: "token"
    client._odata_v4_company_segment = lambda company_id=None: "Company('OPENDC')"
    return client


class TestPostedSalesInvoicePaging:
    def test_pages_past_the_old_500_cap(self, monkeypatch):
        client = _bare_client()
        calls = []

        def fake_get(url, headers=None, timeout=None):
            calls.append(url)
            if "$skip=1000" in url:
                n, start = 25, 1000
            elif "$skip=500" in url:
                n, start = 500, 500
            else:
                n, start = 500, 0
            return _Resp({"value": [{"No": f"PSI-{start + i}"} for i in range(n)]})

        monkeypatch.setattr("app.integrations.bc.client.requests.get", fake_get)
        rows = client.get_posted_sales_invoices("2025-01-01", page_size=500)
        assert len(rows) == 1025
        assert any("$skip=500" in url for url in calls)
        assert any("$skip=1000" in url for url in calls)
        assert all("Posting_Date ge 2025-01-01" in url for url in calls)

    def test_follows_next_link_without_also_skipping(self, monkeypatch):
        client = _bare_client()
        calls = []

        def fake_get(url, headers=None, timeout=None):
            calls.append(url)
            if url.endswith("/more"):
                return _Resp({"value": [{"No": f"B-{i}"} for i in range(10)]})
            return _Resp({
                "value": [{"No": f"A-{i}"} for i in range(500)],
                "@odata.nextLink": "https://bc.test/more",
            })

        monkeypatch.setattr("app.integrations.bc.client.requests.get", fake_get)
        rows = client.get_posted_sales_invoices("2025-06-01", page_size=500)
        assert len(rows) == 510
        assert calls[1] == "https://bc.test/more"
        assert not any("$skip=" in url for url in calls)


class TestSalesInvoicesWithLines:
    def test_header_filter_expand_and_skip_past_500(self, monkeypatch):
        client = _bare_client()
        calls = []

        def fake_get(url, headers=None, timeout=None):
            calls.append((url, headers))
            if "$skip=600" in url:
                n, start = 50, 600
            elif "$skip=400" in url:
                n, start = 200, 400
            elif "$skip=200" in url:
                n, start = 200, 200
            else:
                n, start = 200, 0
            value = []
            for i in range(n):
                idx = start + i
                value.append({
                    "id": f"inv-{idx}",
                    "number": f"INV-{idx}",
                    "postingDate": "2026-02-01",
                    "salesInvoiceLines": [{
                        "sequence": 10000,
                        "description": "Panel",
                        "amountExcludingTax": 10,
                    }],
                })
            return _Resp({"value": value})

        monkeypatch.setattr("app.integrations.bc.client.requests.get", fake_get)
        rows, complete = client.get_sales_invoices_with_lines(
            "2026-02-01", "2026-02-28", customer_number="C00100", page_size=200,
        )
        assert complete is True
        assert len(rows) == 650
        first_url, headers = calls[0]
        assert "/salesInvoices?" in first_url
        assert "$expand=salesInvoiceLines" in first_url
        assert "postingDate ge 2026-02-01 and postingDate le 2026-02-28" in first_url
        assert "customerNumber eq 'C00100'" in first_url
        assert "$top" not in first_url
        assert headers["Prefer"] == "odata.maxpagesize=200"
        assert any("$skip=600" in url for url, _ in calls)

    def test_rejects_non_iso_dates(self):
        client = _bare_client()
        with pytest.raises(ValueError):
            client.get_sales_invoices_with_lines("01/02/2026", "2026-02-28")


class TestFlatten:
    def test_copies_header_date_and_category_onto_each_line(self):
        invoices = [{
            "id": "guid-1",
            "number": "PSI-100",
            "invoiceDate": "2026-03-01",
            "postingDate": "2026-03-02",
            "customerNumber": "C00100",
            "customerName": "Acme Doors",
            "sellToCity": "Ottawa",
            "sellToState": "ON",
            "sellToPostCode": "K1A 0A1",
            "sellToCountry": "CA",
            "shipToCity": "Kanata",
            "shipToState": "ON",
            "shipToPostCode": "K2K 1A1",
            "shipToCountry": "CA",
            "salesInvoiceLines": [
                {
                    "sequence": 20000,
                    "lineType": "Item",
                    "lineObjectNumber": "PN45-24400-0900",
                    "description": "TX450 panel",
                    "quantity": 4,
                    "unitOfMeasureCode": "PCS",
                    "unitPrice": 80,
                    "amountExcludingTax": 320,
                    "amountIncludingTax": 361.6,
                },
                {
                    "sequence": 10000,
                    "lineType": "Comment",
                    "lineObjectNumber": "",
                    "description": "Job 42",
                    "quantity": 0,
                    "unitOfMeasureCode": "",
                    "unitPrice": 0,
                    "netAmount": 0,
                    "netAmountIncludingTax": 0,
                },
            ],
        }]
        rows = flatten_invoice_lines(invoices, {"PN45-24400-0900": "C424SC"})
        assert [r["lineNo"] for r in rows] == [10000, 20000]
        item = rows[1]
        assert item["invoiceNo"] == "PSI-100"
        assert item["postingDate"] == "2026-03-02"
        assert item["invoiceDate"] == "2026-03-01"
        assert item["customerNo"] == "C00100"
        assert item["customerName"] == "Acme Doors"
        assert item["shipToCity"] == "Kanata"
        assert item["sellToState"] == "ON"
        assert item["lineType"] == "Item"
        assert item["itemNo"] == "PN45-24400-0900"
        assert item["quantity"] == 4
        assert item["unitOfMeasure"] == "PCS"
        assert item["unitPrice"] == 80
        assert item["amountExcludingTax"] == 320
        assert item["amountIncludingTax"] == 361.6
        assert item["itemCategoryCode"] == "C424SC"
        comment = rows[0]
        assert comment["itemNo"] is None
        assert comment["itemCategoryCode"] is None
        assert comment["amountExcludingTax"] == 0
        assert comment["amountIncludingTax"] == 0
        assert "postingDate" not in invoices[0]["salesInvoiceLines"][0]


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
def client(admin_user):
    app = FastAPI()
    app.include_router(admin_sales_router)
    app.dependency_overrides[get_current_admin] = lambda: admin_user
    lines_service.clear_sales_invoice_cache()
    return TestClient(app)


@pytest.fixture
def unauth_client():
    app = FastAPI()
    app.include_router(admin_sales_router)
    return TestClient(app)


def _invoice(i, lines=1):
    return {
        "id": f"guid-{i}",
        "number": f"INV-{i:04d}",
        "invoiceDate": "2026-01-15",
        "postingDate": "2026-01-15",
        "customerNumber": "C00100",
        "customerName": "Acme",
        "sellToCity": "Ottawa",
        "sellToState": "ON",
        "sellToPostCode": "K1A 0A1",
        "sellToCountry": "CA",
        "shipToCity": "Kanata",
        "shipToState": "ON",
        "shipToPostCode": "K2K 1A1",
        "shipToCountry": "CA",
        "salesInvoiceLines": [
            {
                "sequence": 10000 + n,
                "lineType": "Item",
                "lineObjectNumber": "PN65-24400-0900",
                "description": "Kanata",
                "quantity": 1,
                "unitOfMeasureCode": "PCS",
                "unitPrice": 50,
                "amountExcludingTax": 50,
                "amountIncludingTax": 56.5,
            }
            for n in range(lines)
        ],
    }


class TestInvoiceLinesApi:
    def test_unauthenticated_rejected(self, unauth_client):
        res = unauth_client.get(
            "/api/admin/sales/invoice-lines",
            params={"start_date": "2026-01-01", "end_date": "2026-01-31"},
        )
        assert res.status_code in (401, 403)

    def test_pages_past_500_lines_with_window_totals(self, client, monkeypatch):
        invoices = [_invoice(i) for i in range(600)]
        seen = {"calls": 0}

        def fake_lines(start_date, end_date, customer_number=None, company_id=None, page_size=200):
            seen["calls"] += 1
            seen["customer"] = customer_number
            seen["start"] = start_date
            seen["end"] = end_date
            return invoices, True

        monkeypatch.setattr(lines_service.bc_client, "get_sales_invoices_with_lines", fake_lines)
        monkeypatch.setattr(
            lines_service.bc_client,
            "get_item_category_codes",
            lambda numbers, company_id=None: {"PN65-24400-0900": "RK24SC"},
        )
        res = client.get(
            "/api/admin/sales/invoice-lines",
            params={
                "start_date": "2026-01-01",
                "end_date": "2026-01-31",
                "customer_no": "C00100",
                "page": 3,
                "page_size": 200,
            },
        )
        assert res.status_code == 200
        body = res.json()
        assert body["complete"] is True
        assert body["totalInvoices"] == 600
        assert body["totalLines"] == 600
        assert body["totalPages"] == 3
        assert body["page"] == 3
        assert len(body["lines"]) == 200
        assert body["lines"][0]["invoiceNo"] == "INV-0400"
        assert body["lines"][-1]["invoiceNo"] == "INV-0599"
        row = body["lines"][0]
        assert row["postingDate"] == "2026-01-15"
        assert row["customerNo"] == "C00100"
        assert row["customerName"] == "Acme"
        assert row["itemNo"] == "PN65-24400-0900"
        assert row["itemCategoryCode"] == "RK24SC"
        assert row["amountExcludingTax"] == 50
        assert row["amountIncludingTax"] == 56.5
        assert row["shipToCity"] == "Kanata"
        assert seen["customer"] == "C00100"
        assert seen["start"] == "2026-01-01"
        assert seen["end"] == "2026-01-31"

        # Second page must not call BC again.
        res2 = client.get(
            "/api/admin/sales/invoice-lines",
            params={"start_date": "2026-01-01", "end_date": "2026-01-31", "customer_no": "C00100", "page": 1},
        )
        assert res2.status_code == 200
        assert res2.json()["lines"][0]["invoiceNo"] == "INV-0000"
        assert seen["calls"] == 1

    def test_empty_header_still_counts_toward_invoice_total(self, client, monkeypatch):
        invoices = [_invoice(1), {**_invoice(2), "salesInvoiceLines": []}]

        monkeypatch.setattr(
            lines_service.bc_client,
            "get_sales_invoices_with_lines",
            lambda **kwargs: (invoices, True),
        )
        monkeypatch.setattr(
            lines_service.bc_client,
            "get_item_category_codes",
            lambda *a, **k: {},
        )
        res = client.get(
            "/api/admin/sales/invoice-lines",
            params={"start_date": "2026-04-01", "end_date": "2026-04-30"},
        )
        body = res.json()
        assert body["totalInvoices"] == 2
        assert body["totalLines"] == 1

    def test_reversed_dates_and_bad_customer_are_400(self, client, monkeypatch):
        called = {"n": 0}

        def fake(**kwargs):
            called["n"] += 1
            return [], True

        monkeypatch.setattr(lines_service.bc_client, "get_sales_invoices_with_lines", fake)
        res = client.get(
            "/api/admin/sales/invoice-lines",
            params={"start_date": "2026-05-10", "end_date": "2026-05-01"},
        )
        assert res.status_code == 400
        res = client.get(
            "/api/admin/sales/invoice-lines",
            params={"start_date": "2026-05-01", "end_date": "2026-05-10", "customer_no": "C00' OR 1 eq 1"},
        )
        assert res.status_code == 400
        assert called["n"] == 0

    def test_truncated_bc_pull_is_flagged(self, client, monkeypatch):
        monkeypatch.setattr(
            lines_service.bc_client,
            "get_sales_invoices_with_lines",
            lambda **kwargs: ([_invoice(1)], False),
        )
        monkeypatch.setattr(
            lines_service.bc_client, "get_item_category_codes", lambda *a, **k: {},
        )
        res = client.get(
            "/api/admin/sales/invoice-lines",
            params={"start_date": "2026-07-01", "end_date": "2026-07-31"},
        )
        assert res.status_code == 200
        body = res.json()
        assert body["complete"] is False
        assert body["totalInvoices"] == 1
        assert body["totalLines"] == 1

    def test_bc_failure_is_502_not_an_empty_window(self, client, monkeypatch):
        monkeypatch.setattr(
            lines_service.bc_client,
            "get_sales_invoices_with_lines",
            lambda **kwargs: ([], False),
        )
        res = client.get(
            "/api/admin/sales/invoice-lines",
            params={"start_date": "2026-06-01", "end_date": "2026-06-02"},
        )
        assert res.status_code == 502

    def test_item_categories(self, client, monkeypatch):
        monkeypatch.setattr(
            lines_service.bc_client,
            "get_item_categories",
            lambda company_id=None: [
                {"code": "HRDWE", "displayName": "Hardware"},
                {"code": "RK24SC", "displayName": "Kanata 24in"},
            ],
        )
        monkeypatch.setattr(
            lines_service.bc_client,
            "get_all_items",
            lambda company_id=None, page_size=1000, select=None: [
                {"number": "PN65-24400-0900", "itemCategoryCode": "RK24SC"},
                {"number": "HK03-00001-00", "itemCategoryCode": "HRDWE"},
            ],
        )
        res = client.get("/api/admin/sales/item-categories")
        assert res.status_code == 200
        body = res.json()
        assert body["categoryCount"] == 2
        assert body["categories"][0]["parentCategoryCode"] is None
        by_no = {row["itemNo"]: row for row in body["items"]}
        assert by_no["PN65-24400-0900"]["categoryCode"] == "RK24SC"
        assert by_no["PN65-24400-0900"]["categoryDescription"] == "Kanata 24in"
        assert by_no["HK03-00001-00"]["categoryDescription"] == "Hardware"


class TestExecutiveProductMix:
    def test_uses_header_window_not_line_posting_date(self, monkeypatch):
        svc = BCMetricsService()
        captured = {}

        def fake_lines(start_date, end_date, customer_number=None, company_id=None, page_size=200):
            captured["start"] = start_date
            captured["end"] = end_date
            return [{
                "number": "INV-1",
                "salesInvoiceLines": [
                    {"description": "Panel", "amountExcludingTax": 10, "lineAmount": 999},
                    {"description": "Panel", "amountExcludingTax": 5},
                    {"description": "", "amountExcludingTax": 1},
                ],
            }], True

        monkeypatch.setattr(svc, "_get_all_pages", lambda endpoint, params=None: [])
        monkeypatch.setattr(svc.client, "get_sales_invoices_with_lines", fake_lines)
        data = svc.get_executive_metrics()
        assert data["productMix"][0] == {"name": "Panel", "value": 15.0}
        assert captured["start"] == f"{date.today().year}-01-01"
        assert captured["end"] == date.today().isoformat()
        assert "postingDate" not in captured
