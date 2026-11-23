"""Late sales orders, supplier confirmations, customer drafts, packing slips.

Business Central and Graph are fakes. The tests assert the email counts
only unshipped late orders, date writes touch expectedReceiptDate only,
customer drafts are not sent, and packing slips stay drafts unless a
person approves them.
"""

import io
import os
import sys
from datetime import date
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from openpyxl import Workbook
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.api.ops_dispatch import get_current_admin, get_db, router as dispatch_router
from app.db.models import (
    OpsActionItem,
    OpsOutboundMessage,
    PackingSlip,
    SupplierConfirmation,
    SupplierConfirmationSource,
    SupplierDateChange,
)
from app.services import late_orders
from app.services import packing_slip_service as slips
from app.services import planning_workbook_service as planning
from app.services import supplier_confirmation_service as confirm
from app.services.scheduler_service import SchedulerService
from app.services.supplier_confirmation_parser import (
    parse_confirmation_text,
    parse_open_order_text,
    parse_open_order_xlsx,
)

TODAY = date(2026, 11, 23)  # Monday


def _db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    for model in (
        SupplierConfirmation, SupplierConfirmationSource, SupplierDateChange,
        OpsOutboundMessage, OpsActionItem, PackingSlip,
    ):
        model.__table__.create(engine)
    return sessionmaker(bind=engine)()


def _so(number, customer, requested, qty=2, shipped=0, status="Open", **extra):
    row = {
        "number": number,
        "customerName": customer,
        "status": status,
        "requestedDeliveryDate": requested,
        "salesOrderLines": [{
            "lineType": "Item",
            "lineObjectNumber": "PN10",
            "description": f"Built for {number}",
            "quantity": qty,
            "shippedQuantity": shipped,
        }],
    }
    row.update(extra)
    return row


def _po(number, vendor, expected, sent="2026-10-01", so=None, status="Open", qty=2, received=0):
    description = f"Built from {so}" if so else "Stock panels"
    return {
        "id": f"id-{number}",
        "number": number,
        "vendorName": vendor,
        "status": status,
        "orderDate": sent,
        "purchaseOrderLines": [{
            "id": f"line-{number}",
            "lineType": "Item",
            "lineObjectNumber": "PN10",
            "description": description,
            "quantity": qty,
            "receivedQuantity": received,
            "expectedReceiptDate": expected,
        }],
    }


class TestLateOrders:
    def test_shipped_invoiced_and_freight_are_not_late(self):
        orders = [
            _so("SO-000001", "Shipped Co", "2026-10-01", qty=2, shipped=2),
            _so("SO-000002", "Invoiced Co", "2026-10-01", status="Invoiced"),
            _so("SO-000003", "Freight Co", "2026-10-01"),
        ]
        orders[2]["salesOrderLines"] = [{
            "lineType": "Item", "lineObjectNumber": "FREIGHT",
            "quantity": 1, "shippedQuantity": 0,
        }]
        report = late_orders.classify_late_sales_orders(orders, [], today=TODAY)
        assert report["open_count"] == 0
        assert report["late"] == []

    def test_past_requested_or_promised_date_is_late_with_the_reason(self):
        orders = [
            _so("SO-000010", "Past Co", "2026-11-01"),
            _so("SO-000011", "Future Co", "2026-12-20"),
            _so("SO-000012", "Promised Co", None, promisedDeliveryDate="2026-11-02"),
        ]
        report = late_orders.classify_late_sales_orders(orders, [], today=TODAY)
        by_no = {row["so_number"]: row for row in report["late"]}
        assert report["open_count"] == 3
        assert set(by_no) == {"SO-000010", "SO-000012"}
        assert "requested date 2026-11-01 has passed" in by_no["SO-000010"]["reason"]
        assert "promised date 2026-11-02 has passed" in by_no["SO-000012"]["reason"]

    def test_supplier_date_plus_internal_lead_after_requested_is_late(self):
        # Friday Nov 27 + 3 business days = Wednesday Dec 2, after Dec 1.
        orders = [_so("SO-000020", "Horizon", "2026-12-01")]
        pos = [_po("PO-001107", "Upwardor", "2026-11-27", so="SO-000020")]
        report = late_orders.classify_late_sales_orders(
            orders, pos, today=TODAY, internal_lead=3,
        )
        assert report["late_count"] == 1
        reason = report["late"][0]["reason"]
        assert "PO-001107" in reason
        assert "supplier date 2026-11-27" in reason
        assert "2026-12-02" in reason
        assert report["late"][0]["customer"] == "Horizon"
        assert report["late"][0]["requested_date"] == "2026-12-01"

    def test_shared_placeholder_date_is_not_a_supplier_date(self):
        orders = [
            _so("SO-000030", "A", "2026-12-20"),
            _so("SO-000031", "B", "2026-12-20"),
            _so("SO-000032", "C", "2026-12-20"),
        ]
        pos = [
            _po("PO-000001", "Upwardor", "2026-11-03", so="SO-000030"),
            _po("PO-000002", "Elton", "2026-11-03", so="SO-000031"),
            _po("PO-000003", "Upwardor", "2026-11-03", so="SO-000032"),
        ]
        report = late_orders.classify_late_sales_orders(orders, pos, today=TODAY, internal_lead=3)
        assert report["placeholder_dates"] == ["2026-11-03"]
        assert report["late"] == []

    def test_material_short_orders_are_not_counted_late(self):
        # Eight open orders, only one past its requested date. The old email
        # would have called the short-due ones "behind".
        orders = [_so(f"SO-{i:06d}", f"Customer {i}", "2026-12-15") for i in range(1, 8)]
        orders.append(_so("SO-000008", "Late Co", "2026-11-01"))
        report = late_orders.classify_late_sales_orders(orders, [], today=TODAY)
        assert report["open_count"] == 8
        assert report["late_count"] == 1
        assert report["late"][0]["so_number"] == "SO-000008"
        assert "behind" not in late_orders.email_subject(report)


class TestSupplierParsing:
    def test_upwardor_acknowledgement_po_space_and_sord(self):
        parsed = parse_confirmation_text(
            subject="Confirmation Order#116307 / PO 1107",
            sender="andrew@upwardor.com",
            body="Completion Date: December 4, 2026\nTAG:SO-001295",
        )
        assert len(parsed) == 1
        row = parsed[0]
        assert row.vendor_key == "upwardor"
        assert row.supplier_order_no == "S-ORD116307"
        assert row.po_numbers == ["PO-001107"]
        assert row.expected_date == date(2026, 12, 4)
        assert "SO-001295" in row.our_so_numbers

    def test_elton_confirmation(self):
        parsed = parse_confirmation_text(
            subject="Order Confirmation",
            sender="orders@eltonmfg.com",
            body=(
                "Elton Manufacturing\n"
                "Customer PO: PO-001107\n"
                "Our Order: E-44521\n"
                "Expected Ship Date: December 4, 2026\n"
            ),
        )
        assert len(parsed) == 1
        row = parsed[0]
        assert row.vendor_key == "elton"
        assert row.supplier_order_no == "E-44521"
        assert row.po_numbers == ["PO-001107"]
        assert row.expected_date == date(2026, 12, 4)

    def test_michael_open_order_lines_and_workbook(self):
        text = parse_open_order_text(
            "Michael open orders\nPO-001107  S-ORD116500  2026-12-04\n"
        )
        assert text[0].supplier_order_no == "S-ORD116500"
        assert text[0].po_numbers == ["PO-001107"]
        assert text[0].expected_date == date(2026, 12, 4)
        assert text[0].source == "open_orders"

        wb = Workbook()
        ws = wb.active
        ws.append(["Sales Order No.", "Your PO", "Expected Receipt"])
        ws.append(["116307", "PO 1107", "2026-12-04"])
        buf = io.BytesIO()
        wb.save(buf)
        rows = parse_open_order_xlsx(buf.getvalue())
        assert rows[0].supplier_order_no == "S-ORD116307"
        assert rows[0].po_numbers == ["PO-001107"]
        assert rows[0].expected_date == date(2026, 12, 4)


class TestSupplierApply:
    def test_flags_placeholder_and_missing_confirmation_after_three_business_days(self):
        pos = [
            _po(f"PO-00000{i}", "Upwardor", "2026-11-03", sent="2026-11-16", so=f"SO-00010{i}")
            for i in range(1, 4)
        ]
        recent = _po("PO-000099", "Elton", None, sent="2026-11-20", so="SO-000199")
        flagged = confirm.po_flags(pos + [recent], today=TODAY)
        numbers = {row["po_number"] for row in flagged}
        assert numbers == {"PO-000001", "PO-000002", "PO-000003"}
        assert "placeholder" in flagged[0]["reason"]
        assert "no supplier confirmation" in flagged[0]["reason"]

    def test_confirmed_real_date_clears_the_flag(self):
        pos = [
            _po(f"PO-00000{i}", "Upwardor", "2026-11-03", sent="2026-10-01")
            for i in range(1, 4)
        ]
        flagged = confirm.po_flags(
            pos, today=TODAY,
            confirmed_po_numbers=["PO-000001"],
            confirmed_dates={"PO-000001": date(2026, 12, 4)},
        )
        assert "PO-000001" not in {row["po_number"] for row in flagged}

    def test_date_is_held_and_customer_draft_is_not_sent(self, monkeypatch):
        def _boom(*args, **kwargs):
            raise AssertionError("mail was sent")

        monkeypatch.setattr(confirm.graph_client, "send_mail", _boom)
        monkeypatch.setattr(confirm.bc_client, "update_purchase_order_line", _boom)
        db = _db()
        parsed = parse_confirmation_text(
            subject="Confirmation Order#116500 / PO-000959",
            sender="andrew@upwardor.com",
            body="Completion Date: December 4, 2026\nTAG:SO-001295",
        )
        orders = [_so(
            "SO-001295", "O'Regan", "2026-11-20",
            email="buyer@oregan.example",
        )]
        pos = [_po("PO-000959", "Upwardor", "2026-11-03", so="SO-001295")]
        result = confirm.apply_confirmations(
            db, parsed, purchase_orders=pos, sales_orders=orders,
            write_bc=False, lead_days=3,
        )
        db.commit()
        assert result["write_bc"] is False
        assert result["bc_held"] == 1
        assert result["bc_written"] == 0
        change = db.query(SupplierDateChange).one()
        assert change.bc_status == "held"
        assert change.new_date == date(2026, 12, 4)
        assert change.po_number == "PO-000959"
        stored = db.query(SupplierConfirmation).one()
        assert stored.supplier_order_no == "S-ORD116500"
        draft = db.query(OpsOutboundMessage).filter_by(kind="customer_update").one()
        assert draft.status == "pending"
        assert "SO-001295" in draft.body_text
        assert "Sorry for the change" in draft.body_text
        assert draft.context_json["auto_send"] is False

    def test_bc_write_patches_only_expected_receipt_date(self, monkeypatch):
        calls = []

        class FakeBC:
            def get_purchase_order_by_number(self, number):
                return _po(number, "Upwardor", "2026-11-03", so="SO-001295")

            def update_purchase_order_line(self, po_id, line_id, data):
                calls.append({"po_id": po_id, "line_id": line_id, "data": data})
                return data

        monkeypatch.setattr(confirm, "bc_client", FakeBC())
        db = _db()
        parsed = parse_confirmation_text(
            subject="Revised Confirmation Order#116500 / PO#000959",
            sender="mpadda@upwardor.com",
            body="Completion Date: 2026-12-04",
        )
        result = confirm.apply_confirmations(
            db, parsed, purchase_orders=[_po("PO-000959", "Upwardor", "2026-11-03")],
            sales_orders=[], write_bc=True,
        )
        db.commit()
        assert result["bc_written"] == 1
        assert calls == [{
            "po_id": "id-PO-000959",
            "line_id": "line-PO-000959",
            "data": {"expectedReceiptDate": "2026-12-04"},
        }]
        assert db.query(SupplierDateChange).one().bc_status == "written"

    def test_oregan_seed_is_a_pending_draft(self):
        db = _db()
        first = confirm.ensure_oregan_seed(db)
        second = confirm.ensure_oregan_seed(db)
        db.commit()
        assert first == second
        draft = db.query(OpsOutboundMessage).one()
        assert draft.status == "pending"
        assert draft.so_number == "SO-001295"
        assert "2026-12-04" in draft.body_text
        assert draft.context_json["po_numbers"] == ["PO-000959", "PO-001049"]
        assert draft.to_email is None


class TestPackingSlips:
    def _shipment(self):
        return {
            "id": "ship-1",
            "number": "SS-000321",
            "orderNumber": "SO-001295",
            "customerName": "O'Regan",
            "externalDocumentNumber": "REGAN-PO-44",
            "postingDate": "2026-11-20",
            "email": "buyer@oregan.example",
            "salesShipmentLines": [{
                "lineType": "Item",
                "lineObjectNumber": "PN10",
                "description": "Panel",
                "quantity": 4,
            }],
        }

    def _order(self):
        return _so("SO-001295", "O'Regan", "2026-11-01", qty=6, shipped=4, externalDocumentNumber="REGAN-PO-44")

    def test_pdf_lists_shipment_customer_po_qty_and_backorder(self):
        payload = slips.slip_payload(self._shipment(), self._order())
        pdf = slips.build_packing_slip_pdf(payload)
        assert pdf.startswith(b"%PDF")
        assert payload["customer_po"] == "REGAN-PO-44"
        assert payload["lines"][0]["quantity"] == 4
        assert payload["backorders"][0]["item"] == "PN10"
        assert payload["backorders"][0]["quantity"] == 2
        text = _pdf_text(pdf)
        if text is not None:
            assert "SO-001295" in text
            assert "REGAN-PO-44" in text
            assert "Bay 2, 125 Lockwood St NE" in text
            assert "Redcliff AB" in text
            assert "PN10" in text

    def test_queue_stays_draft_until_approve(self, monkeypatch):
        sent = []
        monkeypatch.setattr(
            slips.graph_client, "send_mail",
            lambda *args, **kwargs: sent.append(kwargs) or True,
        )
        db = _db()
        row = slips.queue_shipment(db, self._shipment(), self._order(), auto_send=False)
        again = slips.queue_shipment(db, self._shipment(), self._order(), auto_send=False)
        db.commit()
        assert row.id == again.id
        assert row.status == "draft"
        assert sent == []
        approved = slips.approve_slip(db, row.id)
        db.commit()
        assert approved.status == "sent"
        assert len(sent) == 1
        attachment = sent[0]["attachments"][0]
        assert attachment["content_type"] == "application/pdf"
        assert attachment["name"] == "SS-000321.pdf"
        slips.approve_slip(db, row.id)
        assert len(sent) == 1

    def test_auto_send_flag_sends(self, monkeypatch):
        sent = []
        monkeypatch.setattr(slips.graph_client, "send_mail", lambda *a, **k: sent.append(1) or True)
        db = _db()
        row = slips.queue_shipment(db, self._shipment(), self._order(), auto_send=True)
        db.commit()
        assert row.status == "sent"
        assert sent == [1]


class TestPlanningEmail:
    def test_subject_is_the_late_count_not_the_material_watchlist(self, monkeypatch):
        class _FixedDate(date):
            @classmethod
            def today(cls):
                return TODAY

        monkeypatch.setattr(planning, "date", _FixedDate)
        orders = [_so(f"SO-{i:06d}", "Watch", "2026-12-20") for i in range(1, 6)]
        orders.append(_so("SO-000099", "Late Co", "2026-11-01"))
        req = {
            "summary": {},
            "production_included": False,
            "items": [],
            "vendors": [],
        }
        monkeypatch.setattr(
            planning.planning_workbook_service, "gather",
            lambda db, horizon_weeks=None: {
                "req": req, "sales_orders": orders, "purchase_orders": [], "production": [],
            },
        )
        monkeypatch.setattr(planning.planning_workbook_service, "upsert_weekly_snapshots", lambda *a, **k: 0)
        captured = {}

        def _send(sender, recipients, subject, html, attachments=None):
            captured["subject"] = subject
            captured["html"] = html
            return True

        monkeypatch.setattr(planning.graph_client, "send_mail", _send)
        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        db = sessionmaker(bind=engine)()
        result = planning.planning_workbook_service.build_and_deliver(db)
        assert "behind" not in captured["subject"]
        assert "at risk" not in captured["subject"]
        assert "1 late sales order" in captured["subject"]
        assert "SO-000099" in captured["html"]
        assert "Late Co" in captured["html"]
        assert "requested date 2026-11-01 has passed" in captured["html"]
        assert result["late_count"] == 1


class TestSchedulerFlags:
    def test_jobs_stay_idle_when_flags_are_off(self, monkeypatch):
        monkeypatch.setattr(confirm.settings, "SUPPLIER_CONFIRM_INTAKE_ENABLED", False)
        monkeypatch.setattr(slips.settings, "PACKING_SLIP_ENABLED", False)

        def _boom(*args, **kwargs):
            raise AssertionError("job ran")

        monkeypatch.setattr(confirm, "process_inbox", _boom)
        monkeypatch.setattr(slips, "process_recent", _boom)
        SchedulerService()._supplier_confirmation_job()
        SchedulerService()._packing_slip_job()


class TestDispatchApi:
    def test_summary_includes_seed_and_requires_auth(self, monkeypatch):
        db = _db()
        monkeypatch.setattr(confirm.bc_client, "get_open_purchase_orders_with_lines", lambda: [])
        monkeypatch.setattr(confirm.bc_client, "get_open_sales_orders_with_lines", lambda: [
            _so("SO-000008", "Late Co", "2026-11-01"),
        ])
        app = FastAPI()
        app.include_router(dispatch_router)

        def _override_db():
            yield db

        app.dependency_overrides[get_db] = _override_db
        app.dependency_overrides[get_current_admin] = lambda: SimpleNamespace(id=1, is_active=True)
        client = TestClient(app)
        bare = FastAPI()
        bare.include_router(dispatch_router)
        assert TestClient(bare).get("/api/admin/ops-dispatch").status_code in (401, 403)

        listed = client.get("/api/admin/ops-dispatch")
        assert listed.status_code == 200
        body = listed.json()
        assert body["late"]["late_count"] == 1
        assert body["customer_updates"][0]["so_number"] == "SO-001295"
        assert body["flags_enabled"]["packing_slip_auto_send"] is False
        assert body["flags_enabled"]["supplier_confirm_bc_write"] is False


def _pdf_text(pdf: bytes):
    import shutil
    import subprocess
    import tempfile
    if not shutil.which("pdftotext"):
        return None
    path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as handle:
            handle.write(pdf)
            path = handle.name
        proc = subprocess.run(["pdftotext", "-layout", path, "-"], capture_output=True, check=False)
        if proc.returncode != 0:
            return None
        return proc.stdout.decode("utf-8", errors="replace")
    finally:
        if path:
            os.unlink(path)
