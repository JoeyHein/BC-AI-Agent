"""
Order Age Service
=================
Powers the team-facing Order Age Tracker dashboard.

Returns two parallel views in one payload:

1. **Open orders** — every order not yet shipped, with its current age in
   days/weeks. Bucketed for the UI's green / yellow / red coloring.

2. **Delivery success rate** — for orders that DID ship in a recent window,
   what percent left the shop within 4 / 6 / 8 / >8 weeks of order_date.
   This is the historical performance view the team uses to track itself.

Aging conventions (matches CLAUDE.md):
- Clock starts at `SalesOrder.order_date` (BC order date), with
  `created_at` as fallback if BC date isn't synced yet.
- For delivery success: clock stops at `shipped_at`. Orders that haven't
  shipped don't count toward the success rate (still "in flight").
- Cancelled orders are excluded from both views.
"""

import logging
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.db.models import OrderStatus, SalesOrder

logger = logging.getLogger(__name__)

# In-process cache for cycle-time data so multiple dashboard loads don't
# hammer BC. Keyed by lookback_days.
_CYCLE_CACHE: Dict[int, Dict[str, Any]] = {}
_CYCLE_CACHE_TTL_SECONDS = 300  # 5 min


# Buckets for the open-orders list coloring (matches the UI legend)
GREEN_MAX_DAYS = 28           # under 4 weeks
YELLOW_MAX_DAYS = 42          # 4 - 6 weeks
# anything > 42 is red

# Buckets for the historical success rate
SUCCESS_BUCKETS_DAYS = (28, 42, 56)  # 4w, 6w, 8w
# > 56 days = "over 8 weeks"

# Default lookback window for the success-rate stats
DEFAULT_SUCCESS_LOOKBACK_DAYS = 90

# Statuses that count as "open / in flight" (i.e. still aging)
OPEN_STATUSES = {
    OrderStatus.PENDING,
    OrderStatus.CONFIRMED,
    OrderStatus.IN_PRODUCTION,
    OrderStatus.READY_TO_SHIP,
}


def _start_date(order: SalesOrder) -> Optional[datetime]:
    """When did the clock start? BC order_date wins; created_at is the
    fallback for orders that haven't synced their BC date yet."""
    return order.order_date or order.created_at


def _bucket_for_open_age(days: int) -> str:
    if days < GREEN_MAX_DAYS:
        return "green"
    if days < YELLOW_MAX_DAYS:
        return "yellow"
    return "red"


def _bucket_for_delivery_age(days: int) -> str:
    """4w / 6w / 8w / over_8w — matches the four KPI tiles."""
    if days <= 28:
        return "under_4w"
    if days <= 42:
        return "under_6w"
    if days <= 56:
        return "under_8w"
    return "over_8w"


def _parse_iso_date(s: Optional[str]) -> Optional[datetime]:
    """Defensive ISO date parser. BC returns 'YYYY-MM-DD' or '0001-01-01'
    sentinel for unset; both handled."""
    if not s or s == "0001-01-01":
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None


def _median(values: List[float]) -> Optional[float]:
    if not values:
        return None
    s = sorted(values)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2.0


def _enrich_invoice(inv: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Parse one BC invoice row into our internal shape; None if unusable."""
    order_no = inv.get("Order_No") or ""
    order_date = _parse_iso_date(inv.get("Order_Date"))
    posting_date = _parse_iso_date(inv.get("Posting_Date"))
    if not (order_no and order_date and posting_date):
        return None
    return {
        "order_no": order_no,
        "invoice_no": inv.get("No"),
        "customer": inv.get("Sell_to_Customer_Name"),
        "customer_no": inv.get("Bill_to_Customer_No") or "",
        "order_date": inv.get("Order_Date"),
        "invoice_date": inv.get("Posting_Date"),
        "_order_dt": order_date,
        "_invoice_dt": posting_date,
        "cycle_days": max(0, (posting_date - order_date).days),
        "amount": float(inv.get("Amount_Including_VAT") or 0),
    }


def _compute_cycle_time(lookback_days: int) -> Dict[str, Any]:
    """
    Pull a fixed 365-day window of posted invoices once, then derive THREE
    views from the same data:

      1. Bucket stats for the user-selected window (lookback_days).
      2. Monthly trend over the full 12 months (avg / median / count per
         month) — always 12 months regardless of selector, so the team can
         see whether things are improving over time independent of the
         current page selection.
      3. Customer breakdown for the selected window (top customers by avg
         cycle time, with their volume).

    Cached per-process by lookback_days for 5 min so repeat dashboard
    loads don't re-hit BC.
    """
    now = time.time()
    cached = _CYCLE_CACHE.get(lookback_days)
    if cached and (now - cached["_t"]) < _CYCLE_CACHE_TTL_SECONDS:
        return cached["data"]

    from app.integrations.bc.client import bc_client
    today = datetime.utcnow()
    # Always pull a full year — Phase 1 trend requires it, and the
    # selected-window slice is just a filter on top.
    since = (today - timedelta(days=365)).strftime("%Y-%m-%d")

    empty_response = {
        "lookback_days": lookback_days,
        "invoice_count": 0,
        "avg_days": None,
        "median_days": None,
        "buckets": {"under_4w": 0, "under_6w": 0, "under_8w": 0, "over_8w": 0},
        "bucket_pct": {"under_4w": 0.0, "under_6w": 0.0, "under_8w": 0.0, "over_8w": 0.0},
        "samples": [],
        "monthly_trend": [],
        "by_customer": [],
        "error": None,
    }

    try:
        raw = bc_client.get_posted_sales_invoices(since_date=since)
    except Exception as e:
        logger.error(f"Cycle-time fetch failed: {e}", exc_info=True)
        empty_response["error"] = str(e)
        return empty_response

    enriched: List[Dict[str, Any]] = []
    for inv in raw:
        e = _enrich_invoice(inv)
        if e:
            enriched.append(e)

    if not enriched:
        return empty_response

    # ---- View 1: bucket stats for the selected window ----
    cutoff = today - timedelta(days=lookback_days)
    in_window = [e for e in enriched if e["_invoice_dt"] >= cutoff]
    cycles_w = [e["cycle_days"] for e in in_window]
    bucket_counts = {"under_4w": 0, "under_6w": 0, "under_8w": 0, "over_8w": 0}
    for c in cycles_w:
        bucket_counts[_bucket_for_delivery_age(c)] += 1
    n_w = len(cycles_w)

    def pct(c: int) -> float:
        return round((c / n_w) * 100, 1) if n_w else 0.0

    samples = sorted(in_window, key=lambda s: s["cycle_days"], reverse=True)[:50]
    samples_clean = [
        {k: v for k, v in s.items() if not k.startswith("_")} for s in samples
    ]

    # ---- View 2: monthly trend (always last 12 months) ----
    by_month: Dict[str, List[int]] = {}
    by_month_amount: Dict[str, float] = {}
    for e in enriched:
        key = e["_invoice_dt"].strftime("%Y-%m")
        by_month.setdefault(key, []).append(e["cycle_days"])
        by_month_amount[key] = by_month_amount.get(key, 0) + e["amount"]
    # Build ordered list of last 12 months (including months with no data
    # so the chart x-axis is continuous)
    monthly_trend: List[Dict[str, Any]] = []
    cursor = today.replace(day=1)
    months: List[str] = []
    for _ in range(12):
        months.append(cursor.strftime("%Y-%m"))
        # step back one month
        if cursor.month == 1:
            cursor = cursor.replace(year=cursor.year - 1, month=12)
        else:
            cursor = cursor.replace(month=cursor.month - 1)
    for key in reversed(months):
        cycles_m = by_month.get(key, [])
        monthly_trend.append({
            "month": key,
            "invoice_count": len(cycles_m),
            "avg_days": round(sum(cycles_m) / len(cycles_m), 1) if cycles_m else None,
            "median_days": _median(cycles_m),
            "amount": round(by_month_amount.get(key, 0), 2),
        })

    # ---- View 3: customer breakdown (selected window) ----
    by_cust: Dict[str, List[int]] = {}
    cust_meta: Dict[str, Dict[str, Any]] = {}
    for e in in_window:
        # Group by customer number when available; fall back to name.
        key = e["customer_no"] or e["customer"] or "(unknown)"
        by_cust.setdefault(key, []).append(e["cycle_days"])
        if key not in cust_meta:
            cust_meta[key] = {
                "customer_no": e["customer_no"],
                "customer_name": e["customer"],
            }
    by_customer = []
    for key, cycles in by_cust.items():
        avg = round(sum(cycles) / len(cycles), 1)
        by_customer.append({
            **cust_meta[key],
            "invoice_count": len(cycles),
            "avg_days": avg,
            "median_days": _median(cycles),
            "max_days": max(cycles),
        })
    # Filter out customers with very low volume (1 order isn't a pattern),
    # then sort slowest first
    by_customer = [c for c in by_customer if c["invoice_count"] >= 2]
    by_customer.sort(key=lambda c: c["avg_days"], reverse=True)
    by_customer = by_customer[:15]

    data = {
        "lookback_days": lookback_days,
        "invoice_count": n_w,
        "avg_days": round(sum(cycles_w) / n_w, 1) if n_w else None,
        "median_days": _median(cycles_w),
        "buckets": bucket_counts,
        "bucket_pct": {k: pct(v) for k, v in bucket_counts.items()},
        "samples": samples_clean,
        "monthly_trend": monthly_trend,
        "by_customer": by_customer,
        "error": None,
    }
    _CYCLE_CACHE[lookback_days] = {"_t": now, "data": data}
    return data


def get_order_age_metrics(
    db: Session,
    success_lookback_days: int = DEFAULT_SUCCESS_LOOKBACK_DAYS,
) -> Dict[str, Any]:
    """
    Return the dashboard payload.

    Shape (stable — frontend depends on these keys):

        {
          "generated_at": iso-8601,
          "success_lookback_days": int,
          "open_orders": [
            {
              "id": int,
              "bc_order_number": "SO-001234",
              "customer_name": "...",
              "customer_number": "C00123",
              "po_number": "...",
              "order_date": iso-8601,
              "age_days": int,
              "age_weeks": float,
              "status": "in_production",
              "bucket": "green" | "yellow" | "red",
              "total_amount": float | None,
            },
            ...
          ],
          "open_summary": {
            "total": int,
            "green": int,    # under 4 weeks
            "yellow": int,   # 4 - 6 weeks
            "red": int,      # over 6 weeks
          },
          "success_rate": {
            "lookback_days": int,
            "shipped_count": int,
            "under_4w": float,    # percent (0-100)
            "under_6w": float,
            "under_8w": float,
            "over_8w": float,
            "buckets": {
              "under_4w": int,
              "under_6w": int,
              "under_8w": int,
              "over_8w": int,
            },
            "avg_days_to_ship": float | None,
          }
        }
    """
    now = datetime.utcnow()

    # ----- Open orders -----
    # last_synced_at IS NOT NULL filters out local orphans (rows that were
    # created by some legacy code path but never made it into BC). BC is
    # the source of truth — anything not synced from BC doesn't belong.
    open_orders_q = (
        db.query(SalesOrder)
        .filter(
            SalesOrder.status.in_([s for s in OPEN_STATUSES]),
            SalesOrder.last_synced_at.isnot(None),
        )
        .order_by(SalesOrder.order_date.asc().nullslast())
    )

    open_rows: List[Dict[str, Any]] = []
    # Two parallel bucket counts so the UI can toggle between views:
    #   - schedule_buckets: judges orders by their requested delivery
    #     date (early / on_time / late). This is the default view —
    #     a 9-week-old order whose customer wanted a 4-month lead
    #     time is "Early", not "Late".
    #   - age_buckets: judges orders by raw calendar age (under 4 wks
    #     / 4-6 wks / over 6 wks). Kept as the legacy informational
    #     view since some teams still find it useful.
    age_buckets = {"green": 0, "yellow": 0, "red": 0}
    schedule_buckets = {"early": 0, "on_time": 0, "late": 0, "no_schedule": 0}

    # Schedule thresholds (in days from today to requested_delivery_date):
    #   late      — days_until_due < 0  (past due)
    #   on_time   — 0..14d out (actively being worked toward delivery)
    #   early     — > 14d out (sitting in queue, customer wanted it later)
    ON_TIME_WINDOW_DAYS = 14

    for o in open_orders_q.all():
        start = _start_date(o)
        if not start:
            continue
        age_days = max(0, (now - start).days)
        age_bucket = _bucket_for_open_age(age_days)
        age_buckets[age_bucket] += 1

        # Days remaining until requested delivery — negative if past due.
        rdd = o.requested_delivery_date
        days_until_due: Optional[int] = None
        if rdd:
            days_until_due = (rdd - now).days

        # Schedule status — judges the order against ITS OWN requested
        # delivery date, not against an arbitrary age threshold.
        if days_until_due is None:
            schedule_status = "no_schedule"
        elif days_until_due < 0:
            schedule_status = "late"
        elif days_until_due <= ON_TIME_WINDOW_DAYS:
            schedule_status = "on_time"
        else:
            schedule_status = "early"

        schedule_buckets[schedule_status] += 1

        open_rows.append({
            "id": o.id,
            "bc_order_number": o.bc_order_number,
            "customer_name": o.customer_name,
            "customer_number": o.customer_number,
            "po_number": o.external_document_number,
            "order_date": start.isoformat() if start else None,
            "requested_delivery_date": rdd.isoformat() if rdd else None,
            "days_until_due": days_until_due,
            "age_days": age_days,
            "age_weeks": round(age_days / 7, 1),
            "status": o.status.value if o.status else None,
            "bucket": age_bucket,
            "schedule_status": schedule_status,
            "total_amount": float(o.total_amount) if o.total_amount is not None else None,
        })

    # ----- Order-to-invoice cycle time (live from BC PostedSalesInvoices) -----
    # The local shipped_at-based "delivery success rate" was removed because
    # shipped_at isn't reliably populated by the sync; cycle_time pulls
    # straight from BC posted invoices and is the authoritative view.
    cycle_time = _compute_cycle_time(success_lookback_days)

    return {
        "generated_at": now.isoformat() + "Z",
        "success_lookback_days": success_lookback_days,
        "open_orders": open_rows,
        "open_summary": {
            "total": len(open_rows),
            # Age view (legacy): green / yellow / red
            **age_buckets,
            # Schedule view (default): early / on_time / late / no_schedule
            "by_schedule": schedule_buckets,
        },
        "cycle_time": cycle_time,
    }
