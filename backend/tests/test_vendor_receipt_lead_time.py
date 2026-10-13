"""Vendor lead-time rule for purchase-order requested receipt dates."""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.vendor_receipt_lead_time import (
    create_purchase_order_with_receipt,
    email_line,
    match_vendor_lead_time,
    parse_po_date,
    receipt_plan_for_new_po,
    requested_receipt_on,
    sentence_for_vendor,
)


TODAY = date(2026, 10, 13)


@pytest.fixture
def frozen_today(monkeypatch):
    monkeypatch.setattr(
        "app.services.vendor_receipt_lead_time.business_today",
        lambda: TODAY,
    )


class TestMatch:
    @pytest.mark.parametrize(
        "number,name,key,days,ship",
        [
            ("UPW", "somebody", "upwardor", 21, False),
            ("upw", "LYNX", "upwardor", 21, False),
            ("", "Upwardor Ltd", "upwardor", 21, False),
            ("", "UPW", "upwardor", 21, False),
            ("ELT", "other", "elton", 14, False),
            ("X", "Elton Manufacturing Ltd.", "elton", 14, False),
            ("LYNX", "LYNX", "lynx", 14, False),
            ("", "Lynx Industries", "lynx", 14, False),
            ("", "Nice Canada Inc.", "nice_canada", 14, False),
            ("", "NICE", "nice_canada", 14, False),
            ("", "Micanan Systems", "nice_canada", 14, False),
            ("", "Nice / Micanan", "nice_canada", 14, False),
            ("DEK", "Dek Canada", "ship_when_ready", 2, True),
            ("", "Bernice Supplies", "ship_when_ready", 2, True),
            ("", "Acme Doors", "ship_when_ready", 2, True),
            (None, None, "ship_when_ready", 2, True),
        ],
    )
    def test_number_then_name(self, number, name, key, days, ship):
        rule = match_vendor_lead_time(number, name)
        assert rule.key == key
        assert rule.days == days
        assert rule.ship_when_ready is ship

    def test_offsets_are_calendar_days(self):
        upwardor = requested_receipt_on("UPW", "UPWARDOR", TODAY)
        elton = requested_receipt_on("ELT", "Elton Manufacturing", TODAY)
        other = requested_receipt_on("DEK", "Dek Canada", TODAY)
        assert upwardor.requested_receipt_date == date(2026, 11, 3)
        assert elton.requested_receipt_date == date(2026, 10, 27)
        assert other.requested_receipt_date == date(2026, 10, 15)
        assert upwardor.email_line() == "Required in our warehouse by November 3, 2026."
        assert other.email_line() == "Please ship when ready."

    def test_blank_bc_date_is_not_a_date(self):
        assert parse_po_date("0001-01-01") is None
        assert parse_po_date("0001-01-01T00:00:00Z") is None
        assert parse_po_date("") is None
        assert parse_po_date(None) is None
        assert parse_po_date("2026-11-03T00:00:00Z") == date(2026, 11, 3)


class TestEmailSentence:
    def test_named_vendor_uses_header_date(self):
        text = sentence_for_vendor("UPW", "UPWARDOR", "2026-09-22", "2026-09-01")
        assert text == "Required in our warehouse by September 22, 2026."

    def test_named_vendor_blank_header_counts_from_order_date(self, frozen_today):
        text = sentence_for_vendor("LYNX", "LYNX", "0001-01-01", "2026-10-01")
        assert text == "Required in our warehouse by October 15, 2026."

    def test_named_vendor_blank_dates_count_from_today(self, frozen_today):
        text = sentence_for_vendor("", "Nice Canada", None, "0001-01-01")
        assert text == "Required in our warehouse by October 27, 2026."

    def test_other_vendor_ships_when_ready_even_with_a_date(self):
        text = sentence_for_vendor("DEK", "Dek Canada", "2026-12-01", "2026-10-13")
        assert text == "Please ship when ready."
        assert email_line(match_vendor_lead_time("DEK", "Dek"), date(2026, 10, 15)) == (
            "Please ship when ready."
        )


class TestCreateHeader:
    def test_echoed_date_is_not_patched_again(self, frozen_today):
        class Fake:
            def __init__(self):
                self.created = []
                self.updated = []

            def create_purchase_order(self, body):
                self.created.append(body)
                return {"id": "po-1", "number": "PO-1", "status": "Draft", **body}

            def update_purchase_order(self, po_id, data, company_id=None):
                self.updated.append((po_id, data))
                raise AssertionError("header already has the receipt date")

        fake = Fake()
        po, plan = create_purchase_order_with_receipt(fake, "ELT", "Elton Manufacturing")
        assert fake.updated == []
        assert fake.created == [{
            "vendorNumber": "ELT",
            "requestedReceiptDate": "2026-10-27",
        }]
        assert plan.requested_receipt_date == date(2026, 10, 27)
        assert po["number"] == "PO-1"
        assert "requestedDeliveryDate" not in fake.created[0]

    def test_bc_order_date_wins_over_today_and_blank_receipt_is_patched(self, frozen_today):
        class Fake:
            def __init__(self):
                self.created = []
                self.updated = []

            def create_purchase_order(self, body):
                self.created.append(dict(body))
                return {
                    "id": "po-1",
                    "number": "PO-000200",
                    "orderDate": "2026-09-01",
                    "requestedReceiptDate": "0001-01-01",
                    "vendorNumber": body["vendorNumber"],
                }

            def update_purchase_order(self, po_id, data, company_id=None):
                self.updated.append((po_id, dict(data)))
                return {
                    "id": po_id,
                    "number": "PO-000200",
                    "orderDate": "2026-09-01",
                    **data,
                }

            def get_purchase_order(self, po_id, company_id=None):
                raise AssertionError("patch response already confirmed the date")

        fake = Fake()
        po, plan = create_purchase_order_with_receipt(fake, "UPW", "UPWARDOR")
        assert fake.created[0]["requestedReceiptDate"] == "2026-11-03"
        assert fake.updated == [("po-1", {"requestedReceiptDate": "2026-09-22"})]
        assert plan.po_date == date(2026, 9, 1)
        assert plan.requested_receipt_date == date(2026, 9, 22)
        assert po["requestedReceiptDate"] == "2026-09-22"

    def test_new_po_plan_uses_today(self, frozen_today):
        plan = receipt_plan_for_new_po("UPW", "UPWARDOR")
        assert plan.po_date == TODAY
        assert plan.public_dict()["receipt_rule"] == "upwardor"
        assert plan.public_dict()["ship_when_ready"] is False
