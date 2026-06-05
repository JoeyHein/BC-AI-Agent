"""Smoke-test: run the diagnostic resolver end-to-end without going through HTTP."""
import json
from app.api.pricing_diagnostic import _resolve_bc_hierarchy
from app.integrations.bc.client import BusinessCentralClient
from app.services.pricing_service import (
    calculate_selling_price,
    warm_bc_cost_cache,
    _get_live_item,
)
from app.db.database import SessionLocal


def main():
    bc = BusinessCentralClient()
    db = SessionLocal()
    try:
        # Customer #56 FIFTY6 — verified assigned to BRON group in BC
        customer_no = "56"
        live_group = bc.get_customer_price_group(customer_no)
        print(f"Live BC Customer_Price_Group for #{customer_no}: {live_group!r}\n")

        part = "AL95-67400-01"
        warm_bc_cost_cache([part])
        item = _get_live_item(part) or {}
        legacy = calculate_selling_price(part, "aluminium", "bronze", db)
        hierarchy = _resolve_bc_hierarchy(
            bc_client=bc,
            item_no=part,
            customer_no=customer_no,
            customer_price_group=live_group,
            qty=1,
            as_of_date="2026-05-06",
            item_unit_price_fallback=item.get("unitPrice"),
        )
        print(json.dumps({
            "part": part,
            "customer_no": customer_no,
            "live_price_group": live_group,
            "unit_cost": item.get("unitCost"),
            "item_unit_price": item.get("unitPrice"),
            "legacy_margin_price_bronze": legacy,
            "bc_resolved_level": hierarchy["resolved_level"],
            "bc_resolved_price": hierarchy["resolved_price"],
            "levels": [{
                "level": l["level"], "matched": l["matched"],
                "price": l["price"], "source_no": l.get("source_no"),
            } for l in hierarchy["levels"]],
        }, indent=2, default=str))
    finally:
        db.close()


if __name__ == "__main__":
    main()
