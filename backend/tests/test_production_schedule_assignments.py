"""Assignments sheet on the production schedule workbook — Joey's curated
shop-floor picker (Include / Assigned To / Complete By) layered onto the raw
BC production order list. See production_schedule_service.py module docstring.
"""
import io
import sys
import os
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from openpyxl import Workbook

from app.services.production_schedule_service import production_schedule_service as svc


def _prod_order(no, item="PN10-24101-0802", desc="Panel section", qty=1,
                status="Released", due="2026-09-01"):
    return {"No": no, "Source_No": item, "Description": desc,
            "Quantity": qty, "Status": status, "Due_Date": due}


def _build_bytes(prod_orders, prior=None, prod_so_map=None):
    wb = Workbook()
    wb.remove(wb.active)
    svc._write_assignments_sheet(wb, prod_orders, prior or {}, prod_so_map)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_round_trips_include_assigned_to_and_complete_by():
    prod_orders = [_prod_order("PRD-001")]
    prior = {"PRD-001": {"include": True, "assigned_to": "Dave", "complete_by": date(2026, 9, 5)}}

    data = _build_bytes(prod_orders, prior)
    parsed = svc.parse_assignments_from_bytes(data)

    assert parsed["PRD-001"] == {
        "include": True, "assigned_to": "Dave", "complete_by": date(2026, 9, 5),
    }


def test_unincluded_order_defaults_blank():
    data = _build_bytes([_prod_order("PRD-002")])
    parsed = svc.parse_assignments_from_bytes(data)
    assert parsed["PRD-002"] == {"include": False, "assigned_to": "", "complete_by": None}


def test_included_rows_sort_above_uncluded_rows():
    prod_orders = [_prod_order("PRD-A", due="2026-08-01"), _prod_order("PRD-B", due="2026-08-02")]
    prior = {"PRD-B": {"include": True, "assigned_to": "Sam", "complete_by": date(2026, 8, 10)}}

    wb = Workbook()
    wb.remove(wb.active)
    svc._write_assignments_sheet(wb, prod_orders, prior)
    ws = wb["Assignments"]

    first_data_row = next(ws.iter_rows(min_row=2, max_row=2, values_only=True))
    assert first_data_row[1] == "PRD-B"  # included row sorts to the top despite later due date


def test_new_workbook_has_no_prior_assignments():
    wb = Workbook()
    wb.remove(wb.active)
    ws = wb.create_sheet("Schedule")
    ws.append(["not", "an", "assignments", "sheet"])
    buf = io.BytesIO()
    wb.save(buf)

    assert svc.parse_assignments_from_bytes(buf.getvalue()) == {}


def test_empty_bytes_returns_empty_dict():
    assert svc.parse_assignments_from_bytes(b"") == {}
