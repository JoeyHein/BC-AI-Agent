"""
Sales-order purchasing coverage.

Answers one question per open sales order: has anything been bought for this
job, and has anything been missed?

The distinction that matters is NOT "does this order have a shortfall" — on
live data almost every order does, because BC inventory is under-recorded and
manufactured items aren't BOM-exploded yet (same noise that forced the planning
workbook's RAG to be time-gated). The useful signals are:

  NOT_STARTED — the order has material needs and nothing at all has been
                ordered against any of its items. Nobody has touched it.
  GAP         — POs exist for some of the order's items but at least one item
                has no PO whatsoever. The order LOOKS handled, which is exactly
                what makes a miss here dangerous.
  SHORT       — every short item has some PO coverage, just not enough quantity.
  COVERED     — no outstanding material need.

Buying late is deliberate at OPENDC: some items are bought roughly a week
before delivery rather than months ahead, to keep cash out of stock. So an
uncovered item is only a problem relative to the DUE DATE. Urgency is derived
from days-to-delivery, and orders comfortably in the future are reported as
scheduled rather than flagged — otherwise the deliberate deferrals bury the
genuine misses.

NOTE: item lead times are not yet available (the BC `PurchRcptHeader` web
service that would expose order dates is unpublished, so `lead_time_days` is
None on every item). Once it is published, `_urgency` should widen the buy
window per item the way `classify_so_rag` already does.
"""

import logging
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from app.integrations.bc.client import bc_client
from app.services.purchasing_demand_service import purchasing_demand_service
from app.services.planning_workbook_service import _parse_date, _so_item_numbers

logger = logging.getLogger(__name__)

# Items bought this close to delivery are the deliberate just-in-time buys.
# Anything still uncovered inside this window is a genuine miss.
BUY_WINDOW_DAYS_DEFAULT = 7

# How far out an order still counts as "needs attention now".
ATTENTION_WINDOW_DAYS_DEFAULT = 21

# Coverage states, worst first — also the default sort order.
STATUS_ORDER = ["not_started", "gap", "short", "covered"]
URGENCY_ORDER = ["overdue", "urgent", "soon", "scheduled", "undated"]


def _urgency(
    days_to_delivery: Optional[int],
    buy_window_days: int,
    attention_window_days: int,
) -> str:
    """Bucket an order by how close its delivery date is.

    `undated` is kept distinct from `scheduled` — a missing delivery date means
    we genuinely don't know, and those shouldn't be quietly parked at the bottom
    of the list alongside orders we've confirmed are far out.
    """
    if days_to_delivery is None:
        return "undated"
    if days_to_delivery < 0:
        return "overdue"
    if days_to_delivery <= buy_window_days:
        return "urgent"
    if days_to_delivery <= attention_window_days:
        return "soon"
    return "scheduled"


def _classify(short_items: List[dict], all_items: List[dict]) -> tuple:
    """Return (status, uncovered_items) for one order's item rows."""
    if not short_items:
        return "covered", []

    uncovered = [i for i in short_items if (i.get("on_order") or 0) <= 0]

    # Nothing ordered against ANY of this job's items — not just the short ones.
    # Checking every item avoids calling an order untouched when earlier POs
    # already fully covered part of it.
    if all((i.get("on_order") or 0) <= 0 for i in all_items):
        return "not_started", uncovered
    if uncovered:
        return "gap", uncovered
    return "short", []


def _reason(status: str, urgency: str, uncovered: int, short: int) -> str:
    if status == "covered":
        return "everything needed is on hand or on order"
    if status == "short":
        return f"{short} item(s) on order but short on quantity"
    if status == "not_started":
        base = f"nothing ordered yet — {short} item(s) needed"
    else:
        base = f"{uncovered} of {short} short item(s) have no PO"
    if urgency == "overdue":
        return f"{base}; delivery date has passed"
    if urgency == "urgent":
        return f"{base}; due inside the buy window"
    if urgency == "scheduled":
        return f"{base}; due later, likely a deliberate deferral"
    if urgency == "undated":
        return f"{base}; no delivery date set"
    return base


class SOCoverageService:
    """Per-sales-order purchasing coverage, built on the demand engine."""

    def build(
        self,
        db: Session,
        buy_window_days: int = BUY_WINDOW_DAYS_DEFAULT,
        attention_window_days: int = ATTENTION_WINDOW_DAYS_DEFAULT,
        today: Optional[date] = None,
    ) -> Dict:
        """Coverage for every open sales order.

        No horizon is applied to the demand engine here — this view is about
        whether each order is covered, so an order due in six months still needs
        an honest answer rather than being filtered out of the demand pass.
        """
        today = today or date.today()
        req = purchasing_demand_service.compute_requirements(
            db, include_met=True, horizon_weeks=None
        )
        sales_orders = bc_client.get_open_sales_orders_with_lines()
        orders = self.build_rows(
            req, sales_orders,
            buy_window_days=buy_window_days,
            attention_window_days=attention_window_days,
            today=today,
        )

        summary = {s: 0 for s in STATUS_ORDER}
        for o in orders:
            summary[o["status"]] += 1
        needs_attention = sum(
            1 for o in orders
            if o["status"] in ("not_started", "gap")
            and o["urgency"] in ("overdue", "urgent", "soon", "undated")
        )

        return {
            "generated_at": datetime.utcnow().isoformat(),
            "today": today.isoformat(),
            "buy_window_days": buy_window_days,
            "attention_window_days": attention_window_days,
            "summary": {
                **summary,
                "total": len(orders),
                "needs_attention": needs_attention,
            },
            "orders": orders,
        }

    def build_rows(
        self,
        req: dict,
        sales_orders: List[dict],
        buy_window_days: int = BUY_WINDOW_DAYS_DEFAULT,
        attention_window_days: int = ATTENTION_WINDOW_DAYS_DEFAULT,
        today: Optional[date] = None,
    ) -> List[dict]:
        """Pure: one coverage row per sales order. Sorted worst-first."""
        today = today or date.today()
        items_by_no = {r["item_no"]: r for r in req.get("items", [])}

        rows = []
        for so in sales_orders:
            so_no = so.get("number") or "?"
            rdd = _parse_date(so.get("requestedDeliveryDate"))
            days = (rdd - today).days if rdd else None

            item_nos = _so_item_numbers(so)
            so_items = [items_by_no[n] for n in item_nos if n in items_by_no]
            short_items = [i for i in so_items if (i.get("net_need") or 0) > 0]

            status, uncovered = _classify(short_items, so_items)
            urgency = _urgency(days, buy_window_days, attention_window_days)
            uncovered_nos = {i["item_no"] for i in uncovered}

            rows.append({
                "so_number": so_no,
                "customer": so.get("customerName") or "",
                "bc_status": so.get("status") or "",
                "order_date": so.get("orderDate") or None,
                "rdd": rdd.isoformat() if rdd else None,
                "days_to_delivery": days,
                "past_due": bool(days is not None and days < 0),
                "status": status,
                "urgency": urgency,
                "reason": _reason(status, urgency, len(uncovered), len(short_items)),
                "short_item_count": len(short_items),
                "uncovered_item_count": len(uncovered),
                "items": [
                    {
                        "item_no": i["item_no"],
                        "description": i.get("description") or "",
                        "net_need": i.get("net_need") or 0,
                        "unit_of_measure": i.get("unit_of_measure") or "EA",
                        "on_hand": i.get("on_hand") or 0,
                        "on_order": i.get("on_order") or 0,
                        "vendor_name": i.get("vendor_name") or "",
                        "unit_cost": i.get("unit_cost") or 0,
                        # False = nothing ordered against this item at all. This
                        # is the "missed" flag the whole view exists to surface.
                        "has_po": i["item_no"] not in uncovered_nos,
                        "shared_with": [j for j in (i.get("jobs") or []) if j != so_no],
                    }
                    for i in sorted(short_items, key=lambda x: x["item_no"])
                ],
            })

        rows.sort(key=lambda r: (
            STATUS_ORDER.index(r["status"]),
            URGENCY_ORDER.index(r["urgency"]),
            r["days_to_delivery"] if r["days_to_delivery"] is not None else 10**6,
            r["so_number"],
        ))
        return rows


so_coverage_service = SOCoverageService()
