"""Sanity check the sales analytics service against live BC."""
import json
from app.services.sales_analytics_service import get_sales_analytics, _CACHE


def main():
    _CACHE.clear()
    for period in ("this_month", "last_quarter", "ytd", "12m"):
        r = get_sales_analytics(period=period)
        k = r["kpis"]
        print(f"=== {r['label']} ===")
        print(f"  Window         : {k['start']} → {k['end']}")
        print(f"  Revenue        : ${k['revenue']:>13,.2f}  "
              f"(prior ${k['prior_revenue']:>12,.2f}, "
              f"change {k.get('revenue_change_pct')}%)")
        print(f"  Invoice count  : {k['invoice_count']:>13}  "
              f"(prior {k['prior_invoice_count']}, "
              f"diff {k['invoice_count_change']})")
        print(f"  Avg invoice    : ${k['avg_invoice']:>13,.2f}  "
              f"(prior ${k['prior_avg_invoice']:>12,.2f})")
        print(f"  Active customers: {k['active_customers']:>12}")
        print()

    r = get_sales_analytics(period="12m")
    print("Quarterly summary:")
    for q in r["quarterly_summary"]:
        print(f"  {q['quarter']}: ${q['revenue']:>13,.0f}  "
              f"invoices {q['invoice_count']:>3}  "
              f"YoY {q['yoy_change_pct']}%")
    print()
    print("Top 8 customers (last 12 months):")
    for c in r["top_customers"][:8]:
        change = c['change_pct']
        change_str = f"{change:+.1f}%" if change is not None else "  new"
        print(f"  {(c['customer_name'] or c['customer_no'])[:38]:38}  "
              f"${c['revenue']:>12,.0f}  "
              f"change {change_str:>8}  "
              f"invs {c['invoice_count']:>3}  "
              f"avg ${c['avg_invoice']:>8,.0f}")


if __name__ == "__main__":
    main()
