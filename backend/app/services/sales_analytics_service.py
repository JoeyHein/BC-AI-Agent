"""
Sales Analytics Service
=======================
Powers the Sales Analytics dashboard. Pulls posted sales invoices from BC
and aggregates them into the views finance and leadership need to make
decisions:

  1. Headline KPIs (revenue, invoices, avg invoice, active customers)
     with prior-period comparison.
  2. Monthly revenue trend with a 3-month rolling average.
  3. Quarterly summary with YoY change.
  4. Per-customer breakdown with current-vs-prior-period revenue delta.

Period definitions are flexible — anything that can be expressed as a
start/end date range works. The frontend passes one of a fixed set of
period keys; this service translates each into a date window and returns
the data.

Data is cached per-process for 5 minutes to keep dashboard latency
reasonable when multiple users browse at once.
"""

import logging
import time
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from app.integrations.bc.client import bc_client

logger = logging.getLogger(__name__)

# Cache: { cache_key: {"_t": timestamp, "data": payload} }
_CACHE: Dict[str, Dict[str, Any]] = {}
_CACHE_TTL_SECONDS = 300


# ----------------------------------------------------------------------
# Period definitions
# ----------------------------------------------------------------------

def _start_of_month(d: date) -> date:
    return d.replace(day=1)


def _start_of_quarter(d: date) -> date:
    qm = ((d.month - 1) // 3) * 3 + 1
    return d.replace(month=qm, day=1)


def _add_months(d: date, n: int) -> date:
    m = d.month + n
    y = d.year + (m - 1) // 12
    m = ((m - 1) % 12) + 1
    return d.replace(year=y, month=m, day=1)


def _quarter_label(d: date) -> str:
    return f"{d.year} Q{(d.month - 1) // 3 + 1}"


def _shift_year_back(d: date) -> date:
    """Subtract one year from a date, handling Feb 29 by clamping to Feb 28."""
    try:
        return d.replace(year=d.year - 1)
    except ValueError:
        return d.replace(year=d.year - 1, day=28)


def resolve_period(period: str, today: Optional[date] = None,
                    compare: str = "prior") -> Tuple[date, date, date, date, str, str]:
    """
    Translate a period key into (start, end, prior_start, prior_end, label,
    prior_label). The comparison window is selectable:

      compare='prior'    → immediately preceding equivalent window
                           (prior month, prior quarter, etc.)
      compare='year_ago' → same window shifted back one year

    For 12m / 24m the two options collapse to nearly the same result
    (prior 12m == 12m-ago 12m), so the toggle is informational only there.

    Inclusive of start, exclusive of end (BC's Posting_Date filter is
    'ge start and lt end' for cleaner month/quarter rollovers).

    Supported keys:
      this_month / last_month
      this_quarter / last_quarter
      ytd / 12m / 24m
    """
    today = today or datetime.utcnow().date()
    tomorrow = today + timedelta(days=1)

    # ---- Period window ----
    if period == "this_month":
        start, end, label = _start_of_month(today), tomorrow, "This Month"
    elif period == "last_month":
        end = _start_of_month(today)
        start, label = _add_months(end, -1), "Last Month"
    elif period == "this_quarter":
        start, end, label = _start_of_quarter(today), tomorrow, "This Quarter"
    elif period == "last_quarter":
        end = _start_of_quarter(today)
        start, label = _add_months(end, -3), "Last Quarter"
    elif period == "ytd":
        start, end = date(today.year, 1, 1), tomorrow
        label = f"YTD {today.year}"
    elif period == "24m":
        start = _add_months(_start_of_month(today), -24)
        end, label = tomorrow, "Last 24 Months"
    else:  # default 12m
        start = _add_months(_start_of_month(today), -12)
        end, label = tomorrow, "Last 12 Months"

    # ---- Comparison window ----
    if compare == "year_ago":
        # Same calendar window, shifted back one year — clean YoY comparison.
        prior_start = _shift_year_back(start)
        prior_end = _shift_year_back(end)
        if period == "ytd":
            prior_label = f"YTD {today.year - 1} (through {today.strftime('%b %d')})"
        elif period == "this_month":
            prior_label = f"{start.strftime('%B')} {start.year - 1}"
        elif period == "last_month":
            prior_label = f"{start.strftime('%B')} {start.year - 1}"
        elif period == "this_quarter":
            prior_label = f"Q{(start.month - 1) // 3 + 1} {start.year - 1}"
        elif period == "last_quarter":
            prior_label = f"Q{(start.month - 1) // 3 + 1} {start.year - 1}"
        elif period in ("12m", "24m"):
            prior_label = f"{label} (one year earlier)"
        else:
            prior_label = f"{label} Last Year"
    else:  # prior — the immediately preceding equivalent window
        if period == "this_month":
            prior_end, prior_start = start, _add_months(start, -1)
            prior_label = "Previous Month"
        elif period == "last_month":
            prior_end, prior_start = start, _add_months(start, -1)
            prior_label = "Month Before"
        elif period == "this_quarter":
            prior_end, prior_start = start, _add_months(start, -3)
            prior_label = "Previous Quarter"
        elif period == "last_quarter":
            prior_end, prior_start = start, _add_months(start, -3)
            prior_label = "Quarter Before"
        elif period == "ytd":
            # "Prior YTD" — same-day boundary last year, not full calendar year.
            prior_start = date(today.year - 1, 1, 1)
            prior_end = _shift_year_back(end)
            prior_label = f"YTD {today.year - 1} (through {today.strftime('%b %d')})"
        elif period == "24m":
            prior_end, prior_start = start, _add_months(start, -24)
            prior_label = "Previous 24 Months"
        else:  # 12m
            prior_end, prior_start = start, _add_months(start, -12)
            prior_label = "Previous 12 Months"

    return start, end, prior_start, prior_end, label, prior_label


# ----------------------------------------------------------------------
# Invoice loading + filtering
# ----------------------------------------------------------------------

def _parse_iso_date(s: Optional[str]) -> Optional[date]:
    if not s or s == "0001-01-01":
        return None
    try:
        return date.fromisoformat(s[:10])
    except Exception:
        return None


def _load_invoices(since: date) -> List[Dict[str, Any]]:
    """Pull BC PostedSalesInvoices since the given date. Cached at the BC
    client level by date; the service-level cache also covers this."""
    return bc_client.get_posted_sales_invoices(since_date=since.isoformat())


def _filter_window(rows: List[Dict[str, Any]], start: date, end: date) -> List[Dict[str, Any]]:
    out = []
    for inv in rows:
        pd = _parse_iso_date(inv.get("Posting_Date"))
        if pd and start <= pd < end:
            out.append(inv)
    return out


def _amount(inv: Dict[str, Any]) -> float:
    # Amount_Including_VAT is the customer-facing total. Use it for top-line
    # revenue figures; Amount is the pre-tax line and would understate.
    return float(inv.get("Amount_Including_VAT") or 0)


# ----------------------------------------------------------------------
# Roll-ups
# ----------------------------------------------------------------------

def _summarize(invs: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not invs:
        return {
            "revenue": 0.0,
            "invoice_count": 0,
            "avg_invoice": 0.0,
            "active_customers": 0,
        }
    customers = set()
    revenue = 0.0
    for inv in invs:
        revenue += _amount(inv)
        cust = inv.get("Bill_to_Customer_No") or inv.get("Sell_to_Customer_Name")
        if cust:
            customers.add(cust)
    return {
        "revenue": round(revenue, 2),
        "invoice_count": len(invs),
        "avg_invoice": round(revenue / len(invs), 2),
        "active_customers": len(customers),
    }


def _percent_change(curr: float, prior: float) -> Optional[float]:
    if not prior:
        return None
    return round(((curr - prior) / prior) * 100, 1)


def _monthly_trend(invs: List[Dict[str, Any]], months: int = 24) -> List[Dict[str, Any]]:
    """Last N months of revenue + invoice count, oldest to newest, with
    months that have no data rendered as zeros so the chart is contiguous."""
    today = date.today()
    bucket_rev: Dict[str, float] = defaultdict(float)
    bucket_count: Dict[str, int] = defaultdict(int)
    for inv in invs:
        pd = _parse_iso_date(inv.get("Posting_Date"))
        if pd:
            key = pd.strftime("%Y-%m")
            bucket_rev[key] += _amount(inv)
            bucket_count[key] += 1

    cursor = _start_of_month(today)
    out_keys: List[str] = []
    for _ in range(months):
        out_keys.append(cursor.strftime("%Y-%m"))
        cursor = _add_months(cursor, -1)
    out_keys.reverse()

    rolling: List[Dict[str, Any]] = []
    for i, key in enumerate(out_keys):
        rev = round(bucket_rev.get(key, 0.0), 2)
        cnt = bucket_count.get(key, 0)
        # 3-month rolling average for the line overlay
        window = out_keys[max(0, i - 2): i + 1]
        rolling_avg = round(
            sum(bucket_rev.get(k, 0.0) for k in window) / max(1, len(window)), 2
        )
        rolling.append({
            "month": key,
            "revenue": rev,
            "invoice_count": cnt,
            "rolling_3mo_avg": rolling_avg,
        })
    return rolling


def _quarterly_summary(invs: List[Dict[str, Any]], quarters: int = 8) -> List[Dict[str, Any]]:
    """Most recent N quarters with revenue, invoices, avg, and YoY delta
    against the same quarter the previous year."""
    bucket_rev: Dict[str, float] = defaultdict(float)
    bucket_count: Dict[str, int] = defaultdict(int)
    for inv in invs:
        pd = _parse_iso_date(inv.get("Posting_Date"))
        if pd:
            qkey = _quarter_label(pd)
            bucket_rev[qkey] += _amount(inv)
            bucket_count[qkey] += 1

    today = date.today()
    cursor = _start_of_quarter(today)
    qkeys: List[str] = []
    for _ in range(quarters):
        qkeys.append(_quarter_label(cursor))
        cursor = _add_months(cursor, -3)
    qkeys.reverse()

    out = []
    for qkey in qkeys:
        rev = round(bucket_rev.get(qkey, 0.0), 2)
        cnt = bucket_count.get(qkey, 0)
        # YoY: same quarter, previous year
        year, q = qkey.split(" Q")
        yoy_key = f"{int(year) - 1} Q{q}"
        prior_rev = bucket_rev.get(yoy_key, 0.0)
        yoy_change = _percent_change(rev, prior_rev)
        out.append({
            "quarter": qkey,
            "revenue": rev,
            "invoice_count": cnt,
            "avg_invoice": round(rev / cnt, 2) if cnt else 0.0,
            "yoy_revenue": round(prior_rev, 2),
            "yoy_change_pct": yoy_change,
        })
    return out


def _customer_breakdown(
    period_invs: List[Dict[str, Any]],
    prior_invs: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Customer-level rollup with current-vs-prior comparison."""
    curr: Dict[str, Dict[str, Any]] = {}
    for inv in period_invs:
        key = inv.get("Bill_to_Customer_No") or inv.get("Sell_to_Customer_Name") or "(unknown)"
        if key not in curr:
            curr[key] = {
                "customer_no": inv.get("Bill_to_Customer_No") or "",
                "customer_name": inv.get("Sell_to_Customer_Name") or "",
                "revenue": 0.0,
                "invoice_count": 0,
                "last_invoice_date": None,
            }
        curr[key]["revenue"] += _amount(inv)
        curr[key]["invoice_count"] += 1
        pd = _parse_iso_date(inv.get("Posting_Date"))
        if pd:
            prev = curr[key]["last_invoice_date"]
            if not prev or pd.isoformat() > prev:
                curr[key]["last_invoice_date"] = pd.isoformat()

    prior_rev: Dict[str, float] = defaultdict(float)
    for inv in prior_invs:
        key = inv.get("Bill_to_Customer_No") or inv.get("Sell_to_Customer_Name") or "(unknown)"
        prior_rev[key] += _amount(inv)

    out = []
    for key, c in curr.items():
        prior = prior_rev.get(key, 0.0)
        out.append({
            "customer_no": c["customer_no"],
            "customer_name": c["customer_name"],
            "revenue": round(c["revenue"], 2),
            "prior_revenue": round(prior, 2),
            "change_pct": _percent_change(c["revenue"], prior),
            "invoice_count": c["invoice_count"],
            "avg_invoice": round(c["revenue"] / c["invoice_count"], 2) if c["invoice_count"] else 0.0,
            "last_invoice_date": c["last_invoice_date"],
        })
    out.sort(key=lambda x: x["revenue"], reverse=True)
    return out


# ----------------------------------------------------------------------
# Public entry point
# ----------------------------------------------------------------------

def get_sales_analytics(period: str = "12m", compare: str = "prior") -> Dict[str, Any]:
    """Return the full payload for the Sales Analytics dashboard.

    compare: 'prior' (immediately preceding window) or 'year_ago' (same
    window shifted back one year for a clean YoY view).
    """
    if compare not in ("prior", "year_ago"):
        compare = "prior"
    cache_key = f"sales_{period}_{compare}"
    now_t = time.time()
    cached = _CACHE.get(cache_key)
    if cached and (now_t - cached["_t"]) < _CACHE_TTL_SECONDS:
        return cached["data"]

    today = datetime.utcnow().date()
    start, end, prior_start, prior_end, label, prior_label = resolve_period(
        period, today, compare=compare,
    )

    # Pull 24 months of invoices once (covers trend, quarterly, and current
    # period for any selector); slice in memory for each window.
    earliest = min(start, prior_start, _add_months(_start_of_month(today), -24))
    try:
        all_invs = _load_invoices(earliest)
    except Exception as e:
        logger.error(f"Sales analytics BC fetch failed: {e}", exc_info=True)
        return {
            "period": period,
            "label": label,
            "error": str(e),
            "kpis": {},
            "monthly_trend": [],
            "quarterly_summary": [],
            "top_customers": [],
        }

    period_invs = _filter_window(all_invs, start, end)
    prior_invs = _filter_window(all_invs, prior_start, prior_end)

    period_summary = _summarize(period_invs)
    prior_summary = _summarize(prior_invs)

    kpis = {
        "label": label,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "prior_label": prior_label,
        "prior_start": prior_start.isoformat(),
        "prior_end": prior_end.isoformat(),
        "compare": compare,
        "revenue": period_summary["revenue"],
        "prior_revenue": prior_summary["revenue"],
        "revenue_change_pct": _percent_change(
            period_summary["revenue"], prior_summary["revenue"]
        ),
        "invoice_count": period_summary["invoice_count"],
        "prior_invoice_count": prior_summary["invoice_count"],
        "invoice_count_change": period_summary["invoice_count"] - prior_summary["invoice_count"],
        "avg_invoice": period_summary["avg_invoice"],
        "prior_avg_invoice": prior_summary["avg_invoice"],
        "avg_invoice_change_pct": _percent_change(
            period_summary["avg_invoice"], prior_summary["avg_invoice"]
        ),
        "active_customers": period_summary["active_customers"],
        "prior_active_customers": prior_summary["active_customers"],
        "active_customers_change": (
            period_summary["active_customers"] - prior_summary["active_customers"]
        ),
    }

    payload = {
        "period": period,
        "compare": compare,
        "label": label,
        "prior_label": prior_label,
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "kpis": kpis,
        "monthly_trend": _monthly_trend(all_invs, months=24),
        "quarterly_summary": _quarterly_summary(all_invs, quarters=8),
        "top_customers": _customer_breakdown(period_invs, prior_invs),
        "error": None,
    }
    _CACHE[cache_key] = {"_t": now_t, "data": payload}
    return payload
