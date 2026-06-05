"""End-to-end check: GNB customer + GNB tier + the volume curve."""
import json
from app.api.pricing_diagnostic import _resolve_bc_hierarchy
from app.integrations.bc.client import BusinessCentralClient
from app.services.pricing_service import (
    calculate_selling_price, warm_bc_cost_cache, _get_live_item,
)
from app.services.escalating_margin_service import get_profile_by_key
from app.db.database import SessionLocal
from app.db.models import BCCustomer


def main():
    bc = BusinessCentralClient()
    db = SessionLocal()
    try:
        gnb = db.query(BCCustomer).filter(
            BCCustomer.company_name.ilike("%GNB Doors (Manitoba)%")
        ).first()
        print(f"GNB customer: {gnb.company_name} | tier={gnb.pricing_tier} | group={gnb.bc_price_group}\n")

        # Pick a representative item from each major posting group
        parts = ["AL95-67400-01", "PA17-00003-00", "OP21-01456-10"]
        warm_bc_cost_cache(parts)

        profile = get_profile_by_key("GNB_MANITOBA")
        # Sample volume scenarios for the curve
        volumes = [5_000, 25_000, 75_000]

        for part in parts:
            item = _get_live_item(part) or {}
            cost = item.get("unitCost") or 0
            base_price = calculate_selling_price(part, "commercial", "gnb", db)
            print(f"=== {part} | cost ${cost:.2f} | base 30% GM list = ${base_price} ===")

            hierarchy = _resolve_bc_hierarchy(
                bc_client=bc, item_no=part, customer_no=gnb.bc_customer_id,
                customer_price_group="GNB", qty=1, as_of_date="2026-05-06",
                item_unit_price_fallback=item.get("unitPrice"),
            )
            print(f"  BC hierarchy resolves at: {hierarchy['resolved_level']!r} -> ${hierarchy['resolved_price']}")
            print(f"  (Will become 'customer_price_group' once GNB list is imported into BC)")

            # Apply the volume curve at three quote-total scenarios
            print(f"  Volume curve applied to base list:")
            for vol in volumes:
                r = profile.calculate(vol)
                final = round(base_price * r["multiplier"], 2) if base_price else None
                print(f"    quote total ${vol:>7,}: GM {r['target_gm']:>5.1f}%  "
                      f"vol_mult {r['multiplier']:.4f}  ->  ${final} per unit")
            print()
    finally:
        db.close()


if __name__ == "__main__":
    main()
