"""Sanity check the new compare=prior vs compare=year_ago options."""
from app.services.sales_analytics_service import get_sales_analytics, _CACHE


def main():
    _CACHE.clear()
    for period in ("this_quarter", "ytd", "12m"):
        print(f"=== {period} ===")
        for compare in ("prior", "year_ago"):
            r = get_sales_analytics(period, compare=compare)
            k = r["kpis"]
            print(f"  [{compare}]")
            print(f"    Period      : {k['start']} → {k['end']}  ({k['label']})")
            print(f"    Prior label : {k['prior_label']!r}")
            print(f"    Prior window: {k['prior_start']} → {k['prior_end']}")
            print(f"    Revenue     : ${k['revenue']:>12,.0f}  prior ${k['prior_revenue']:>12,.0f}  "
                  f"change {k.get('revenue_change_pct')}%")
        print()


if __name__ == "__main__":
    main()
