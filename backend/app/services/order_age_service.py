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

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.db.models import OrderStatus, SalesOrder


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
    bucket_counts = {"green": 0, "yellow": 0, "red": 0}
    for o in open_orders_q.all():
        start = _start_date(o)
        if not start:
            continue
        age_days = max(0, (now - start).days)
        bucket = _bucket_for_open_age(age_days)
        bucket_counts[bucket] += 1
        # Days remaining until requested delivery — negative if past due.
        # Lets the UI show "due in 12d" or "overdue 4d" without redoing
        # the date math client-side.
        rdd = o.requested_delivery_date
        days_until_due: Optional[int] = None
        if rdd:
            days_until_due = (rdd - now).days
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
            "bucket": bucket,
            "total_amount": float(o.total_amount) if o.total_amount is not None else None,
        })

    # ----- Delivery success rate -----
    cutoff = now - timedelta(days=success_lookback_days)
    shipped_q = (
        db.query(SalesOrder)
        .filter(
            SalesOrder.shipped_at.isnot(None),
            SalesOrder.shipped_at >= cutoff,
            SalesOrder.status != OrderStatus.CANCELLED,
        )
    )

    bucket_counts_ship = {"under_4w": 0, "under_6w": 0, "under_8w": 0, "over_8w": 0}
    days_to_ship: List[int] = []
    for o in shipped_q.all():
        start = _start_date(o)
        if not start or not o.shipped_at:
            continue
        days = max(0, (o.shipped_at - start).days)
        days_to_ship.append(days)
        bucket_counts_ship[_bucket_for_delivery_age(days)] += 1

    shipped_count = len(days_to_ship)

    def pct(n: int) -> float:
        return round((n / shipped_count) * 100, 1) if shipped_count else 0.0

    success_rate = {
        "lookback_days": success_lookback_days,
        "shipped_count": shipped_count,
        "under_4w": pct(bucket_counts_ship["under_4w"]),
        "under_6w": pct(bucket_counts_ship["under_6w"]),
        "under_8w": pct(bucket_counts_ship["under_8w"]),
        "over_8w": pct(bucket_counts_ship["over_8w"]),
        "buckets": bucket_counts_ship,
        "avg_days_to_ship": (
            round(sum(days_to_ship) / shipped_count, 1) if shipped_count else None
        ),
    }

    return {
        "generated_at": now.isoformat() + "Z",
        "success_lookback_days": success_lookback_days,
        "open_orders": open_rows,
        "open_summary": {
            "total": len(open_rows),
            **bucket_counts,
        },
        "success_rate": success_rate,
    }
