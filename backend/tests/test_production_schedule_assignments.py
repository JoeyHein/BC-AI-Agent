"""Assignments sheet on the production schedule workbook — Joey's curated,
prioritized week queue layered onto the raw BC production order list. See
production_schedule_service.py module docstring.

Unlike the Schedule sheet, Assignments is NOT a full listing: only production
orders Joey has actually typed onto the sheet appear at all, sorted by a
hand-typed Priority number.
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


def test_round_trips_priority_assigned_to_and_complete_by():
    prod_orders = [_prod_order("PRD-001")]
    prior = {"PRD-001": {"priority": 1, "assigned_to": "Dave", "complete_by": date(2026, 9, 5)}}

    data = _build_bytes(prod_orders, prior)
    parsed = svc.parse_assignments_from_bytes(data)

    rec = parsed["PRD-001"]
    assert rec["priority"] == 1
    assert rec["assigned_to"] == "Dave"
    assert rec["complete_by"] == date(2026, 9, 5)
    # Descriptive fields refreshed from the live BC match.
    assert rec["item"] == "PN10-24101-0802"
    assert rec["status"] == "Released"
    assert rec["due_date"] == date(2026, 9, 1)


def test_sheet_only_shows_rows_joey_put_there():
    """A production order NOT in `prior` must not appear at all — this is
    the curated-only behavior distinguishing Assignments from Schedule."""
    prod_orders = [_prod_order("PRD-001"), _prod_order("PRD-002")]
    prior = {"PRD-001": {"priority": 1, "assigned_to": "Dave", "complete_by": None}}

    data = _build_bytes(prod_orders, prior)
    parsed = svc.parse_assignments_from_bytes(data)

    assert "PRD-001" in parsed
    assert "PRD-002" not in parsed


def test_rows_sort_by_priority():
    prod_orders = [_prod_order("PRD-A"), _prod_order("PRD-B"), _prod_order("PRD-C")]
    prior = {
        "PRD-A": {"priority": 3, "assigned_to": "", "complete_by": None},
        "PRD-B": {"priority": 1, "assigned_to": "", "complete_by": None},
        "PRD-C": {"priority": 2, "assigned_to": "", "complete_by": None},
    }

    wb = Workbook()
    wb.remove(wb.active)
    svc._write_assignments_sheet(wb, prod_orders, prior)
    ws = wb["Assignments"]

    po_numbers = [row[1] for row in ws.iter_rows(min_row=2, values_only=True)]
    assert po_numbers == ["PRD-B", "PRD-C", "PRD-A"]


def test_blank_priority_sinks_to_bottom_but_still_shows():
    prod_orders = [_prod_order("PRD-A"), _prod_order("PRD-B")]
    prior = {
        "PRD-A": {"priority": None, "assigned_to": "", "complete_by": None},
        "PRD-B": {"priority": 1, "assigned_to": "", "complete_by": None},
    }

    wb = Workbook()
    wb.remove(wb.active)
    svc._write_assignments_sheet(wb, prod_orders, prior)
    ws = wb["Assignments"]

    po_numbers = [row[1] for row in ws.iter_rows(min_row=2, values_only=True)]
    assert po_numbers == ["PRD-B", "PRD-A"]


def test_finished_order_auto_closes_and_disappears():
    """PRD-999 previously had a confirmed BC match (item/status populated)
    but is no longer in the fresh Released set — treat it as finished/
    invoiced and drop the row entirely, no manual "done" step needed."""
    prior = {
        "PRD-999": {
            "priority": 1, "assigned_to": "Dave", "complete_by": date(2026, 9, 5),
            "item": "PN10-24101-0802", "description": "Panel section", "qty": 1,
            "status": "Released", "due_date": date(2026, 8, 20), "related_so": "SO-100",
        }
    }

    data = _build_bytes(prod_orders=[], prior=prior)
    parsed = svc.parse_assignments_from_bytes(data)

    assert "PRD-999" not in parsed


def test_never_matched_order_stays_flagged_not_found():
    """A Prod Order # that never had a confirmed BC match (typo, or never
    actually open) must NOT be silently dropped like a finished order —
    it needs a person to notice and fix it."""
    prior = {
        "PRD-000": {
            "priority": 1, "assigned_to": "Dave", "complete_by": None,
            "item": "", "description": "", "qty": None,
            "status": "", "due_date": None, "related_so": "",
        }
    }

    data = _build_bytes(prod_orders=[], prior=prior)
    parsed = svc.parse_assignments_from_bytes(data)

    assert parsed["PRD-000"]["status"] == "NOT FOUND"


def test_new_workbook_has_no_prior_assignments():
    wb = Workbook()
    wb.remove(wb.active)
    ws = wb.create_sheet("Schedule")
    ws.append(["not", "an", "assignments", "sheet"])
    buf = io.BytesIO()
    wb.save(buf)

    assert svc.parse_assignments_from_bytes(buf.getvalue()) == {}


def test_open_production_orders_sheet_lists_every_open_order_with_customer():
    prod_orders = [_prod_order("PRD-001", due="2026-09-10"), _prod_order("PRD-002", due="2026-09-01")]
    prod_so_map = {"PRD-001": "SO-100", "PRD-002": "SO-200"}
    so_customer_map = {"SO-100": "Acme Doors", "SO-200": "Beta Garage"}

    wb = Workbook()
    wb.remove(wb.active)
    svc._write_open_production_orders_sheet(wb, prod_orders, prod_so_map, so_customer_map)
    ws = wb["Open Production Orders"]

    data_rows = list(ws.iter_rows(min_row=2, values_only=True))
    assert [row[0] for row in data_rows] == ["PRD-002", "PRD-001"]  # sorted by due date
    assert data_rows[0][6] == "SO-200"
    assert data_rows[0][7] == "Beta Garage"


def test_empty_bytes_returns_empty_dict():
    assert svc.parse_assignments_from_bytes(b"") == {}
