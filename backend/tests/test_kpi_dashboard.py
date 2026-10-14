"""KPI dashboard math, product-line mapping, and the read-only service route."""
from __future__ import annotations

import json
import os
import sys
from datetime import date
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.api import kpi_dashboard as kpi_api
from app.api.staff_principal import require_staff
from app.db.database import get_db
from app.services.kpi_compute import build_kpi_dashboard, empty_bundle
from app.services.kpi_dashboard_service import (
    _purchase_order,
    _sales_invoice,
    kpi_dashboard_service,
    resolve_range,
)
from app.services.kpi_product_map import classify_operator, classify_product_line, is_freight, load_product_map
from app.services.staff_service_keys_service import AUTOMATION_SCOPES, route_allowed

TODAY = date(2026, 10, 14)
START = date(2026, 10, 1)
END = date(2026, 10, 14)


def _bundle(**overrides):
    data = empty_bundle()
    data.update(overrides)
    return data


def _map():
    return load_product_map()


class TestProductMap:
    def test_series_and_brands(self):
        product_map = _map()
        assert classify_product_line(product_map, "TX450-0907", "section", "").id == "commercial"
        assert classify_product_line(product_map, "PN1", "Thermalex panel", "").id == "commercial"
        assert classify_product_line(product_map, "PN60", "Kanata flush", "").id == "residential"
        assert classify_product_line(product_map, "X", "Craft Muskoka", "").id == "residential"
        assert classify_product_line(product_map, "AL976-1", "", "").id == "aluminum"
        assert classify_product_line(product_map, "GL", "aluminum full view", "").id == "aluminum"
        assert classify_product_line(product_map, "TX4500", "not a series", "") is None
        assert classify_operator(product_map, "OP1", "LiftMaster 87504").id == "liftmaster"
        assert classify_operator(product_map, "OP2", "Micanan operator").id == "mckinnon"
        assert classify_operator(product_map, "OP3", "Guardian trolley").id == "guardian"
        assert is_freight(product_map, "FRT", "Outbound freight")
        assert not is_freight(product_map, "FREIGHTLINER", "truck")

    def test_env_override(self, monkeypatch):
        monkeypatch.setenv("KPI_PRODUCT_LINE_MAP", json.dumps({
            "lines": [{"id": "commercial", "label": "Commercial", "match": ["CUSTOM-SERIES"]}],
            "operators": [],
            "freight": [],
            "low_margin_pct": 15,
        }))
        product_map = load_product_map()
        assert product_map.low_margin_pct == 15
        assert classify_product_line(product_map, "CUSTOM-SERIES-1", "", "").id == "commercial"
        assert classify_product_line(product_map, "TX450", "", "") is None


class TestPurchasingKpis:
    def test_so_to_po_uses_email_time_then_order_date_and_flags_over_five_days(self):
        data = _bundle(
            sales_orders=[
                {"number": "SO-000101", "order_date": "2026-10-01", "customer_name": "Abe", "amount": 1, "lines": []},
                {"number": "SO-000102", "order_date": "2026-10-10", "customer_name": "Bea", "amount": 1, "lines": []},
                {"number": "SO-000103", "order_date": "2026-10-12", "customer_name": "Cam", "amount": 1, "lines": []},
                {"number": "SO-000104", "order_date": "2026-10-01", "customer_name": "Dee", "amount": 1, "lines": []},
                {"number": "SO-000105", "order_date": "2026-09-01", "customer_name": "Old", "amount": 1, "lines": []},
            ],
            purchase_orders=[
                {
                    "number": "PO-000201", "status": "Draft", "order_date": "2026-10-01",
                    "vendor_number": "UPW", "vendor_name": "Upwardor", "amount": 10,
                    "external_document": "", "lines": [{"line_type": "Comment", "description": "Built from SO-000101", "quantity": 0}],
                },
                {
                    "number": "PO-000202", "status": "Open", "order_date": "2026-10-12",
                    "vendor_number": "ACM", "vendor_name": "Acme", "amount": 10,
                    "external_document": "SO-000102", "lines": [],
                },
                {
                    "number": "PO-000203", "status": "Draft", "order_date": "2026-10-12",
                    "vendor_number": "ACM", "vendor_name": "Acme", "amount": 10,
                    "external_document": "SO-000103", "lines": [],
                },
                {
                    "number": "PO-000204", "status": "Draft", "order_date": "2026-10-01",
                    "vendor_number": "ACM", "vendor_name": "Acme", "amount": 10,
                    "external_document": "SO-000104", "lines": [],
                },
            ],
            po_sends=[{"po_number": "PO-000201", "emailed_at": "2026-10-08T18:00:00", "so_numbers": ["SO-000101"], "vendor_number": "UPW", "vendor_name": "Upwardor"}],
        )
        body = build_kpi_dashboard(data, START, END, TODAY, _map())
        card = body["sections"]["purchasing"]["so_to_po"]
        by_po = {row["purchase_order"]: row for row in card["pairs"]}
        assert by_po["PO-000201"]["days"] == 7
        assert by_po["PO-000201"]["sent_source"] == "portal_email"
        assert by_po["PO-000201"]["highlight"] is True
        assert by_po["PO-000202"]["days"] == 2
        assert by_po["PO-000202"]["sent_source"] == "bc_order_date"
        assert by_po["PO-000202"]["highlight"] is False
        assert by_po["PO-000203"]["sent"] is False
        assert by_po["PO-000203"]["highlight"] is False
        assert by_po["PO-000204"]["sent"] is False
        assert by_po["PO-000204"]["highlight"] is True
        assert "PO-000105" not in by_po
        assert card["average_days"] == 4.5
        assert card["status"] == "warn"
        assert card["late_count"] == 2

    def test_ack_average_uses_portal_receipt_not_promised_date(self):
        data = _bundle(
            purchase_orders=[
                {
                    "number": "PO-000301", "status": "Open", "order_date": "2026-10-01",
                    "requested_receipt_date": "2026-10-20", "vendor_number": "UPW", "vendor_name": "Upwardor",
                    "amount": 10, "lines": [{"line_type": "Item", "quantity": 1, "received_quantity": 0, "expected_receipt_date": "2026-10-20"}],
                },
                {
                    "number": "PO-000302", "status": "Open", "order_date": "2026-10-01",
                    "vendor_number": "ACM", "vendor_name": "Acme", "amount": 10,
                    "lines": [{"line_type": "Item", "quantity": 1, "received_quantity": 0}],
                },
                {
                    "number": "PO-000303", "status": "Open", "order_date": "2026-10-01",
                    "vendor_number": "UPW", "vendor_name": "Upwardor", "amount": 10,
                    "lines": [{"line_type": "Item", "quantity": 1, "received_quantity": 0}],
                },
            ],
            acks=[
                {"po_number": "PO-000301", "vendor_number": "UPW", "received_at": "2026-10-03", "status": "confirmed"},
                {"po_number": "PO-000302", "vendor_number": "ACM", "received_at": "2026-10-06", "status": "revised"},
                {"po_number": "PO-000303", "vendor_number": "UPW", "received_at": "2026-10-02", "status": "cancelled"},
            ],
        )
        body = build_kpi_dashboard(data, START, END, TODAY, _map())
        purchasing = body["sections"]["purchasing"]
        vendors = {row["vendor_number"]: row for row in purchasing["acknowledgements"]["vendors"]}
        assert vendors["UPW"]["average_days"] == 2
        assert vendors["ACM"]["average_days"] == 5
        assert purchasing["acknowledgements"]["average_days"] == 3.5
        numbers = {po["number"] for row in purchasing["unacknowledged"]["vendors"] for po in row["purchase_orders"]}
        assert numbers == {"PO-000303"}
        assert purchasing["unacknowledged"]["vendors"][0]["purchase_orders"][0]["age_days"] == 13

    def test_on_time_rate_needs_the_purchase_order_required_date(self):
        data = _bundle(
            purchase_orders=[
                {"number": "PO-000401", "status": "Open", "order_date": "2026-09-01", "requested_receipt_date": "2026-10-10",
                 "vendor_number": "UPW", "vendor_name": "Upwardor", "amount": 1, "lines": []},
                {"number": "PO-000402", "status": "Open", "order_date": "2026-09-01", "requested_receipt_date": "2026-10-01",
                 "vendor_number": "ACM", "vendor_name": "Acme", "amount": 1, "lines": []},
            ],
            receipts=[
                {"order_number": "PO-000401", "posting_date": "2026-10-05", "vendor_number": "UPW", "vendor_name": "Upwardor"},
                {"order_number": "PO-000402", "posting_date": "2026-10-12", "vendor_number": "ACM", "vendor_name": "Acme"},
                {"order_number": "PO-000499", "posting_date": "2026-10-06", "vendor_number": "ZZ", "vendor_name": "Gone"},
            ],
        )
        on_time = build_kpi_dashboard(data, START, END, TODAY, _map())["sections"]["purchasing"]["on_time"]
        assert on_time["on_time"] == 1
        assert on_time["late"] == 1
        assert on_time["unknown"] == 1
        assert on_time["rate_pct"] == 50.0
        assert on_time["status"] == "bad"


class TestSalesAndMoney:
    def _sales_bundle(self):
        def invoice(number, posted, lines, amount=None):
            return {
                "number": number,
                "posting_date": posted,
                "customer_name": "Abe",
                "customer_number": "C1",
                "amount": sum(line["amount"] for line in lines) if amount is None else amount,
                "status": "Paid",
                "lines": lines,
            }

        def line(item, description, amount, qty=1):
            return {"item_number": item, "description": description, "quantity": qty, "amount": amount, "line_type": "Item"}

        return _bundle(
            invoices=[
                invoice("PS-1", "2026-10-05", [
                    line("TX450-1", "TX450 section", 100),
                    line("PN60", "Kanata flush", 50),
                    line("AL976-1", "AL976 glass", 25),
                    line("OP1", "LiftMaster 87504", 10),
                    line("FRT", "Outbound freight", 5),
                    line("MISC", "Widget", 15),
                ]),
                invoice("PS-0", "2026-09-20", [line("TX450-1", "TX450 section", 40)]),
                invoice("PS-LY", "2025-10-05", [], 80),
            ],
            items=[
                {"number": "TX450-1", "description": "TX450", "on_hand": 0, "unit_cost": 60, "category": ""},
                {"number": "PN60", "description": "Kanata", "on_hand": 0, "unit_cost": 20, "category": ""},
                {"number": "AL976-1", "description": "AL976", "on_hand": 0, "unit_cost": 10, "category": ""},
                {"number": "OP1", "description": "LiftMaster", "on_hand": 0, "unit_cost": 4, "category": ""},
                {"number": "MISC", "description": "Widget", "on_hand": 0, "unit_cost": 90, "category": ""},
                {"number": "SLOW", "description": "Dusty hinge", "on_hand": 4, "unit_cost": 20, "category": "", "reorder_point": None},
                {"number": "LOW", "description": "Short bolt", "on_hand": 1, "unit_cost": 10, "category": "", "reorder_point": 5},
                {"number": "FAST", "description": "Fast panel", "on_hand": 10, "unit_cost": 5, "category": "", "reorder_point": 2},
            ],
            quotes=[
                {"number": "SQ-000001", "document_date": "2026-10-02", "amount": 1000},
                {"number": "SQ-000002", "document_date": "2026-10-03", "amount": 500},
                {"number": "SQ-000003", "document_date": "2026-01-01", "amount": 200},
            ],
            sales_orders=[
                {
                    "number": "SO-9", "order_date": "2026-10-04", "external_document": "SQ-000099",
                    "amount": 300, "lines": [
                        {"line_type": "Item", "item_number": "TX450-1", "description": "TX450", "quantity": 4, "shipped_quantity": 1, "amount": 400},
                    ],
                },
                {
                    "number": "SO-8", "order_date": "2026-10-04", "external_document": "SQ-000001",
                    "amount": 100, "lines": [
                        {"line_type": "Item", "quantity": 2, "shipped_quantity": 2, "amount": 100, "item_number": "PN60", "description": "Kanata"},
                    ],
                },
            ],
            open_invoices=[
                {"number": "PS-OPEN-1", "due_date": "2026-10-20", "status": "Open", "amount": 10},
                {"number": "PS-OPEN-2", "due_date": "2026-10-04", "status": "Open", "amount": 20},
                {"number": "PS-OPEN-3", "due_date": "2026-07-01", "status": "Open", "amount": 5},
                {"number": "PS-PAID", "due_date": "2026-01-01", "status": "Paid", "amount": 999},
            ],
            customers=[
                {"number": "C1", "name": "Abe", "balance": 100},
                {"number": "C2", "name": "Bea", "balance": 40},
                {"number": "C3", "name": "Cam", "balance": -15},
            ],
            purchase_orders=[
                {"number": "PO-000501", "status": "Open", "order_date": "2026-09-01", "amount": 100,
                 "vendor_number": "UPW", "vendor_name": "Upwardor", "lines": []},
            ],
            purchase_invoices=[
                {"number": "PI-1", "order_number": "PO-000501", "posting_date": "2026-10-06",
                 "vendor_number": "UPW", "vendor_name": "Upwardor", "amount": 110, "status": "Open"},
                {"number": "PI-2", "order_number": "PO-009999", "posting_date": "2026-10-07",
                 "vendor_number": "ACM", "vendor_name": "Acme", "amount": 50, "status": "Paid"},
            ],
            shipments=[
                {"number": "SH-1", "order_number": "SO-MISSING", "posting_date": "2026-10-10", "order_date": "2026-10-01"},
                {"number": "SH-2", "order_number": "SO-9", "posting_date": "2026-10-10", "order_date": None},
                {"number": "SH-3", "order_number": "SO-GONE", "posting_date": "2026-10-10", "order_date": None},
            ],
            reorder_state="ok",
            slow_window_start="2026-09-01",
            deposits={"state": "missing", "amount": None, "detail": "No deposit list."},
        )

    def test_sales_mix_quotes_margin_ar_backlog_inventory_and_freight(self):
        body = build_kpi_dashboard(self._sales_bundle(), START, END, TODAY, _map())
        sales = body["sections"]["sales"]
        assert sales["range_total"]["amount"] == 205
        assert sales["range_total"]["prior_amount"] == 40
        assert sales["range_total"]["year_ago_amount"] == 80
        assert sales["week"]["from"] == "2026-10-12"
        mix = {row["id"]: row for row in sales["product_mix"]["lines"]}
        assert mix["commercial"]["amount"] == 100
        assert mix["residential"]["amount"] == 50
        assert mix["aluminum"]["amount"] == 25
        assert sales["product_mix"]["other_amount"] == 15
        movers = sales["product_mix"]["top_movers"]["commercial"]
        assert movers[0]["item_number"] == "TX450-1"
        assert movers[0]["delta"] == 60
        brands = {row["id"]: row for row in sales["operators"]["brands"]}
        assert brands["liftmaster"]["amount"] == 10
        assert brands["mckinnon"]["amount"] == 0
        quotes = sales["quotes"]
        assert quotes["converted_count"] == 1
        assert quotes["open_in_period"] == 2
        assert quotes["conversion_pct"] == 33.3
        assert quotes["open_quote_value"] == 1700
        assert quotes["open_quote_count"] == 3

        margin = body["sections"]["financial"]["margin"]
        # Lines except freight: 100+50+25+10+15 = 200. Costs 60+20+10+4+90 = 184.
        assert margin["sales"] == 200
        assert margin["cost"] == 184
        assert margin["margin_pct"] == 8.0
        assert margin["status"] == "bad"
        assert any(row["invoice"] == "PS-1" for row in margin["low_margin_orders"])
        variance = body["sections"]["financial"]["po_variance"]
        assert variance["variance_amount"] == 10
        assert variance["missing_po_count"] == 1
        assert variance["compared_count"] == 1

        ar = body["sections"]["financial"]["ar"]
        assert ar["total"] == 140
        assert ar["credit_balances"] == 15
        buckets = {row["id"]: row["amount"] for row in ar["buckets"]}
        assert buckets == {"current": 10, "1_30": 20, "31_60": 0, "61_90": 0, "over_90": 5}
        assert ar["deposits"]["state"] == "missing"
        assert ar["status"] == "bad"
        assert body["sections"]["financial"]["backlog"]["amount"] == 300
        assert body["sections"]["financial"]["backlog"]["order_count"] == 1

        operations = body["sections"]["operations"]
        assert operations["order_to_ship"]["average_days"] == 7.5
        assert operations["order_to_ship"]["with_order_date"] == 2
        assert operations["order_to_ship"]["missing_order_date"] == 1
        assert operations["inventory"]["value"] == 140
        assert operations["inventory"]["slow_count"] == 3
        assert operations["inventory"]["slow_movers"][0]["item_number"] == "SLOW"
        assert operations["inventory"]["below_reorder"][0]["item_number"] == "LOW"
        assert operations["freight"]["amount"] == 5
        assert operations["freight"]["percent"] == 2.4
        assert operations["freight"]["status"] == "good"

    def test_missing_invoice_source_does_not_look_like_zero_sales(self):
        data = _bundle(errors={"sales_invoices": "Business Central did not return sales invoices."})
        body = build_kpi_dashboard(data, START, END, TODAY, _map())
        assert body["sections"]["sales"]["range_total"]["amount"] is None
        notes = {note["id"]: note for note in body["coverage"]}
        assert notes["sales"]["state"] == "missing"
        assert notes["so_to_po"]["state"] == "partial"
        assert notes["po_ack"]["state"] == "partial"
        assert notes["margin"]["state"] == "partial" or notes["margin"]["state"] == "missing"


class TestRoute:
    def test_service_key_needs_every_read_scope(self):
        granted = set(AUTOMATION_SCOPES)
        assert route_allowed("GET", "/api/kpi/dashboard", b"", granted)[0] is True
        assert route_allowed("GET", "/api/kpi/dashboard/purchasing", b"", granted)[0] is True
        assert route_allowed("GET", "/api/kpi/dashboard/sales", b"", granted)[0] is True
        assert route_allowed("POST", "/api/kpi/dashboard", b"{}", granted)[0] is False
        narrow = {"orders:read"}
        ok, reason = route_allowed("GET", "/api/kpi/dashboard", b"", narrow)
        assert ok is False
        assert "not include permission" in reason or "not allowed" in reason

    def test_service_module_does_not_write(self):
        text = Path(__file__).resolve().parents[1].joinpath("app/services/kpi_dashboard_service.py").read_text()
        lowered = text.lower()
        assert ".post(" not in lowered
        assert " patch" not in lowered
        assert ".delete(" not in lowered

    def test_normalizers_drop_bc_blank_dates(self):
        po = _purchase_order({
            "number": "PO-1",
            "status": "Open",
            "orderDate": "0001-01-01",
            "requestedReceiptDate": "2026-11-01",
            "vendorNumber": "UPW",
            "vendorName": "Upwardor",
            "totalAmountExcludingTax": 12,
            "purchaseOrderLines": [{"lineType": "Item", "lineObjectNumber": "PN10", "description": "SO-000010", "quantity": 2, "receivedQuantity": 0, "expectedReceiptDate": "0001-01-01"}],
        })
        assert po["order_date"] is None
        assert po["requested_receipt_date"] == "2026-11-01"
        assert po["lines"][0]["expected_receipt_date"] is None
        invoice = _sales_invoice({
            "number": "PS-1",
            "postingDate": "2026-10-02",
            "totalAmountExcludingTax": 8,
            "customerName": "Abe",
            "salesInvoiceLines": [{"lineType": "Item", "lineObjectNumber": "TX450", "description": "TX450", "quantity": 1, "amountExcludingTax": 8}],
        })
        assert invoice["lines"][0]["amount"] == 8

    def test_api_returns_dashboard_and_rejects_a_backwards_range(self, monkeypatch):
        monkeypatch.setattr(
            kpi_api.kpi_dashboard_service,
            "get_dashboard",
            lambda *args, **kwargs: {"sections": {"purchasing": {"ok": True}}, "coverage": [], "range": {}},
        )
        app = FastAPI()
        app.include_router(kpi_api.router)

        def _db():
            yield None

        app.dependency_overrides[get_db] = _db
        app.dependency_overrides[require_staff] = lambda: object()
        client = TestClient(app)
        ok = client.get("/api/kpi/dashboard?from=2026-10-01&to=2026-10-14")
        assert ok.status_code == 200, ok.text
        assert ok.json()["sections"]["purchasing"]["ok"] is True
        bad = client.get("/api/kpi/dashboard?from=2026-10-14&to=2026-10-01")
        assert bad.status_code == 400
        assert "end date" in bad.json()["detail"]
        section = client.get("/api/kpi/dashboard/sales?from=2026-10-01&to=2026-10-14")
        assert section.status_code == 200
        assert section.json()["section"] == "sales"
        missing = client.get("/api/kpi/dashboard/nope")
        assert missing.status_code == 404

    def test_default_range_is_thirty_days(self):
        start, end = resolve_range(None, None, today=TODAY)
        assert end == TODAY
        assert (end - start).days == 29

    def test_cache_returns_the_same_payload(self, monkeypatch):
        kpi_dashboard_service._cache.clear()
        calls = {"n": 0}

        def _build(db, start, end, today, product_map):
            calls["n"] += 1
            return {"marker": calls["n"], "coverage": []}

        monkeypatch.setattr(kpi_dashboard_service, "_build", _build)
        first = kpi_dashboard_service.get_dashboard(None, START, END, today=TODAY)
        second = kpi_dashboard_service.get_dashboard(None, START, END, today=TODAY)
        fresh = kpi_dashboard_service.get_dashboard(None, START, END, today=TODAY, refresh=True)
        assert first["cached"] is False
        assert second["cached"] is True
        assert second["marker"] == 1
        assert fresh["marker"] == 2
        kpi_dashboard_service._cache.clear()
