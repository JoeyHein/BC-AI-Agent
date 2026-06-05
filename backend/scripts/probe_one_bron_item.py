"""Find one BRON-priced item and run the full hierarchy on it."""
import json
import requests
from app.integrations.bc.client import BusinessCentralClient
from app.api.pricing_diagnostic import _resolve_bc_hierarchy
from app.services.pricing_service import (
    calculate_selling_price, warm_bc_cost_cache, _get_live_item,
)
from app.db.database import SessionLocal


def main():
    bc = BusinessCentralClient()
    seg = bc._odata_v4_company_segment(None)
    headers = {"Authorization": f"Bearer {bc._get_access_token()}", "Accept": "application/json"}
    url = (
        f"{bc.odata_url}/{seg}/SalesPriceLists"
        f"?$filter=Source_Type eq 'Customer Price Group' and Assign_to_No eq 'BRON'&$top=1"
    )
    r = requests.get(url, headers=headers, timeout=30)
    rows = r.json().get("value", [])
    if not rows:
        print("no BRON rows found")
        return
    sample = rows[0]
    item = sample["Product_No"]
    print(f"Sample BRON row: item={item} price={sample['Unit_Price']}\n")

    db = SessionLocal()
    try:
        warm_bc_cost_cache([item])
        bc_item = _get_live_item(item) or {}
        legacy = calculate_selling_price(item, "residential", "bronze", db)
        hierarchy = _resolve_bc_hierarchy(
            bc_client=bc, item_no=item, customer_no="56",
            customer_price_group="BRON", qty=1, as_of_date="2026-05-06",
            item_unit_price_fallback=bc_item.get("unitPrice"),
        )
        print(json.dumps({
            "part": item,
            "unit_cost": bc_item.get("unitCost"),
            "item_unit_price_fallback": bc_item.get("unitPrice"),
            "legacy_bronze_residential": legacy,
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
