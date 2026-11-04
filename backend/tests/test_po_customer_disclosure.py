"""Who may see the customer on a purchase order.

Elton, Upwardor, and Nice/Micanan may. Ultra-Lite, DEK, Lynx, and everyone
else may not. Our own SO number is not customer info.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.po_customer_disclosure import (
    CustomerDisclosureError,
    CustomerIdentity,
    find_customer_leaks,
    guard_vendor_texts,
    vendor_may_see_customer_info,
)


def _identity(**kwargs):
    return CustomerIdentity.from_sales_order(kwargs)


class TestAllowlist:
    @pytest.mark.parametrize("number,name", [
        ("UPW", "somebody else"),
        ("upw", ""),
        ("", "Upwardor Doors"),
        ("ELT", "other"),
        ("", "Elton Manufacturing"),
        ("NICE", "operator desk"),
        ("", "Nice Canada Inc."),
        ("", "Micanan"),
        ("", "Nice"),
        ("", "Nice/Micanan"),
        ("ELT", "Bernice"),
    ])
    def test_allowlisted(self, number, name):
        assert vendor_may_see_customer_info(number, name) is True

    @pytest.mark.parametrize("number,name", [
        ("ULTR", "Ultra-Lite"),
        ("ULTRA", "Ultra-Lite"),
        ("DEK", "DEK Canada"),
        ("LYNX", "Lynx"),
        ("", "Cardinal Fasteners"),
        ("", "Equal Door"),
        ("", "NWD Hörmann"),
        ("", "Bernice Windows"),
        ("", ""),
    ])
    def test_not_allowlisted(self, number, name):
        assert vendor_may_see_customer_info(number, name) is False


class TestLeakFinder:
    def test_phrase_and_identity(self):
        identity = _identity(
            customerName="Prairie Door Co",
            externalDocumentNumber="JOB-8841",
            shipToName="North Hill Site",
            shipToAddressLine1="100 8 Avenue SW",
            shipToPostCode="T2E 4N4",
            phoneNumber="780-555-0199",
        )
        assert "customer_po_phrase" in find_customer_leaks("please use cust PO 12")
        assert "customer_po_phrase" in find_customer_leaks("Customer P.O. 9")
        assert "customer_po_phrase" in find_customer_leaks("customer's purchase order")
        assert find_customer_leaks("customer portal login") == []
        assert "customer_name" in find_customer_leaks("ship for Prairie Door Co", [identity])
        assert "external_document" in find_customer_leaks("their PO is JOB-8841", [identity])
        assert "ship_to" in find_customer_leaks("job is North Hill Site", [identity])
        assert "ship_to" in find_customer_leaks("deliver to 100 8 Avenue SW", [identity])
        assert "ship_to" in find_customer_leaks("call 780.555.0199", [identity])
        assert "ship_to" in find_customer_leaks("postal T2E 4N4", [identity])

    def test_our_so_number_and_built_from_line_are_safe(self):
        identity = _identity(
            customerName="Prairie Door Co",
            externalDocumentNumber="SO-001300",
        )
        text = "Built from SO-001300 - 2026-11-04 - opendc purchasing (complete order)"
        assert find_customer_leaks(text, [identity]) == []

    def test_door_color_is_not_a_customer_name(self):
        identity = _identity(customerName="Black")
        header = '(1) 10\'0" x 8\'0" TX450, BLACK, UDC'
        assert find_customer_leaks(header, [identity]) == []
        assert find_customer_leaks("Black", [identity]) == ["customer_name"]

    def test_short_customer_name_still_matches_as_a_word(self):
        identity = _identity(customerName="Acme")
        assert find_customer_leaks("call Acme before shipping", [identity]) == ["customer_name"]
        assert find_customer_leaks("AcmeDoors welded", [identity]) == []

    def test_guard_rejects_only_non_allowlisted_vendors(self):
        identity_lookup = lambda number: {  # noqa: E731
            "customerName": "Prairie Door Co",
            "externalDocumentNumber": "JOB-8841",
        } if number == "SO-001300" else None
        guard_vendor_texts("UPW", "UPWARDOR", ["cust PO 1 for Prairie Door Co"], ["SO-001300"], lookup=identity_lookup)
        with pytest.raises(CustomerDisclosureError, match="cannot see the customer"):
            guard_vendor_texts(
                "ULTR", "Ultra-Lite", ["for Prairie Door Co"], ["SO-001300"], lookup=identity_lookup,
            )
        with pytest.raises(CustomerDisclosureError, match="customer PO"):
            guard_vendor_texts("DEK", "DEK Canada", ["customer PO 55"], [])
