"""Sales-order purchasing coverage tests.

The point of this view is separating three things that all look like "shortfall"
in the raw demand engine:
  - nothing ordered for this job at all
  - the job was worked but specific items were skipped  (the dangerous one)
  - everything is on order, just short on quantity

and grading them by how close delivery is, because buying late is deliberate.
"""
import sys
import os
from datetime import date

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.so_coverage_service import (
    so_coverage_service,
    _classify,
    _urgency,
    BUY_WINDOW_DAYS_DEFAULT,
    ATTENTION_WINDOW_DAYS_DEFAULT,
)

TODAY = date(2026, 8, 3)


def _item(no, net_need=0.0, on_order=0.0, on_hand=0.0, jobs=None):
    return {
        "item_no": no, "description": f"desc {no}", "net_need": net_need,
        "on_order": on_order, "on_hand": on_hand, "demand": net_need + on_hand,
        "unit_of_measure": "EA", "vendor_name": "UPWARDOR", "unit_cost": 1.0,
        "jobs": jobs if jobs is not None else [],
    }


def _so(number, rdd=None, items=(), customer="ACME"):
    return {
        "number": number, "customerName": customer, "status": "Open",
        "requestedDeliveryDate": rdd,
        "salesOrderLines": [
            {"lineType": "Item", "lineObjectNumber": i, "quantity": 1, "shippedQuantity": 0}
            for i in items
        ],
    }


def _build(items, sales_orders, today=TODAY, **kw):
    return so_coverage_service.build_rows(
        {"items": items}, sales_orders, today=today, **kw
    )


class TestClassify:
    def test_no_shortfall_is_covered(self):
        status, uncovered = _classify([], [_item("A", net_need=0, on_order=0)])
        assert status == "covered" and uncovered == []

    def test_nothing_on_order_anywhere_is_not_started(self):
        items = [_item("A", net_need=5), _item("B", net_need=3)]
        status, uncovered = _classify(items, items)
        assert status == "not_started"
        assert {i["item_no"] for i in uncovered} == {"A", "B"}

    def test_some_ordered_some_not_is_a_gap(self):
        a, b = _item("A", net_need=5, on_order=10), _item("B", net_need=3)
        status, uncovered = _classify([a, b], [a, b])
        assert status == "gap"
        assert [i["item_no"] for i in uncovered] == ["B"]

    def test_all_partially_ordered_is_short(self):
        a, b = _item("A", net_need=5, on_order=2), _item("B", net_need=3, on_order=1)
        status, uncovered = _classify([a, b], [a, b])
        assert status == "short" and uncovered == []

    def test_covered_sibling_item_does_not_mask_an_untouched_job(self):
        # An item with no net need but also nothing on order (covered from stock)
        # must not make a job with zero POs look like it was worked.
        stocked = _item("A", net_need=0, on_hand=99, on_order=0)
        short = _item("B", net_need=3, on_order=0)
        status, _ = _classify([short], [stocked, short])
        assert status == "not_started"

    def test_prior_po_on_a_covered_item_counts_as_worked(self):
        ordered = _item("A", net_need=0, on_order=50)
        short = _item("B", net_need=3, on_order=0)
        status, uncovered = _classify([short], [ordered, short])
        assert status == "gap"
        assert [i["item_no"] for i in uncovered] == ["B"]


class TestUrgency:
    @pytest.mark.parametrize("days,expected", [
        (-1, "overdue"), (-100, "overdue"),
        (0, "urgent"), (7, "urgent"),
        (8, "soon"), (21, "soon"),
        (22, "scheduled"), (365, "scheduled"),
        (None, "undated"),
    ])
    def test_buckets(self, days, expected):
        assert _urgency(days, BUY_WINDOW_DAYS_DEFAULT, ATTENTION_WINDOW_DAYS_DEFAULT) == expected

    def test_buy_window_is_configurable(self):
        # A 14-day buy window pulls a 10-day-out order from "soon" into "urgent".
        assert _urgency(10, 7, 21) == "soon"
        assert _urgency(10, 14, 21) == "urgent"


class TestRows:
    def test_deliberate_deferral_is_not_flagged_urgent(self):
        # Far-out order with nothing ordered: real, but scheduled — this is the
        # cash-flow deferral case and must not read as an emergency.
        items = [_item("A", net_need=5)]
        rows = _build(items, [_so("SO-1", rdd="2027-01-01", items=["A"])])
        assert rows[0]["status"] == "not_started"
        assert rows[0]["urgency"] == "scheduled"
        assert "deliberate deferral" in rows[0]["reason"]

    def test_same_gap_inside_buy_window_is_urgent(self):
        items = [_item("A", net_need=5)]
        rows = _build(items, [_so("SO-1", rdd="2026-08-06", items=["A"])])
        assert rows[0]["urgency"] == "urgent"
        assert "buy window" in rows[0]["reason"]

    def test_past_due_is_overdue_and_flagged(self):
        items = [_item("A", net_need=5)]
        rows = _build(items, [_so("SO-1", rdd="2026-07-01", items=["A"])])
        assert rows[0]["urgency"] == "overdue"
        assert rows[0]["past_due"] is True
        assert rows[0]["days_to_delivery"] < 0

    def test_missing_delivery_date_is_undated_not_scheduled(self):
        items = [_item("A", net_need=5)]
        rows = _build(items, [_so("SO-1", rdd=None, items=["A"])])
        assert rows[0]["urgency"] == "undated"
        assert rows[0]["days_to_delivery"] is None

    def test_bc_null_date_sentinel_treated_as_missing(self):
        items = [_item("A", net_need=5)]
        rows = _build(items, [_so("SO-1", rdd="0001-01-01", items=["A"])])
        assert rows[0]["urgency"] == "undated"

    def test_items_carry_the_no_po_flag(self):
        a = _item("A", net_need=5, on_order=10)
        b = _item("B", net_need=3, on_order=0)
        rows = _build([a, b], [_so("SO-1", rdd="2026-08-10", items=["A", "B"])])
        flags = {i["item_no"]: i["has_po"] for i in rows[0]["items"]}
        assert flags == {"A": True, "B": False}
        assert rows[0]["uncovered_item_count"] == 1

    def test_shared_jobs_exclude_self(self):
        a = _item("A", net_need=5, jobs=["SO-1", "SO-2", "SO-3"])
        rows = _build([a], [_so("SO-1", rdd="2026-08-10", items=["A"])])
        assert rows[0]["items"][0]["shared_with"] == ["SO-2", "SO-3"]

    def test_sorted_worst_first(self):
        items = [_item("A", net_need=5), _item("B", net_need=5, on_order=99)]
        sos = [
            _so("SO-COVERED", rdd="2026-08-05", items=["B"]),
            _so("SO-FAR", rdd="2027-01-01", items=["A"]),
            _so("SO-LATE", rdd="2026-07-01", items=["A"]),
        ]
        rows = _build(items, sos)
        assert [r["so_number"] for r in rows] == ["SO-LATE", "SO-FAR", "SO-COVERED"]

    def test_order_with_no_demand_rows_is_covered(self):
        # Item isn't in the demand engine at all (e.g. non-stock) — not a gap.
        rows = _build([], [_so("SO-1", rdd="2026-08-05", items=["NONSTOCK"])])
        assert rows[0]["status"] == "covered"
        assert rows[0]["items"] == []
