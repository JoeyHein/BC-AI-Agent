"""Phase 1 smoke test — trend + customer breakdown."""
from app.services.order_age_service import _compute_cycle_time, _CYCLE_CACHE


def main():
    _CYCLE_CACHE.clear()
    r = _compute_cycle_time(90)
    print(f"Window: {r['invoice_count']} invoices, avg={r['avg_days']}d, median={r['median_days']}d")
    print()
    print(f"Monthly trend ({len([m for m in r['monthly_trend'] if m['invoice_count']])} months with data):")
    for m in r["monthly_trend"]:
        if m["invoice_count"]:
            print(
                f"  {m['month']}: {m['invoice_count']:>3} invoices, "
                f"avg {m['avg_days']}d, median {m['median_days']}d, "
                f"${m['amount']:>12,.0f}"
            )
    print()
    print(f"Customer breakdown ({len(r['by_customer'])} with >=2 invoices):")
    for c in r["by_customer"][:8]:
        print(
            f"  {(c['customer_name'] or c['customer_no'])[:35]:35} "
            f"avg={c['avg_days']:>5}d  n={c['invoice_count']:>3}  max={c['max_days']:>4}d"
        )


if __name__ == "__main__":
    main()
