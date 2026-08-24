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


def test_order_no_longer_open_freezes_at_last_known_values():
    """PRD-999 was typed onto the sheet previously but is no longer in BC's
    open (Released) set — the row must stay, with frozen descriptive fields,
    not disappear or blank out."""
    prior = {
        "PRD-999": {
            "priority": 1, "assigned_to": "Dave", "complete_by": date(2026, 9, 5),
            "item": "PN10-24101-0802", "description": "Panel section", "qty": 1,
            "status": "Released", "due_date": date(2026, 8, 20), "related_so": "SO-100",
        }
    }

    data = _build_bytes(prod_orders=[], prior=prior)
    parsed = svc.parse_assignments_from_bytes(data)

    rec = parsed["PRD-999"]
    assert rec["item"] == "PN10-24101-0802"
    assert rec["status"] == "NOT IN OPEN ORDERS"


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
