"""Inspect UOM, category, description, and price for the springs that
showed up odd on the diagnostic."""
import sys
import requests
from app.integrations.bc.client import BusinessCentralClient


def show(bc, headers, item_no):
    safe = item_no.replace("'", "''")
    url = f"{bc.base_url}/companies({bc.company_id})/items?$filter=number eq '{safe}'"
    r = requests.get(url, headers=headers, timeout=30)
    rows = r.json().get("value", [])
    if not rows:
        print(f"  {item_no}: not found via api/v2.0")
        return
    item = rows[0]
    keys = (
        "number", "displayName", "baseUnitOfMeasureCode",
        "unitCost", "unitPrice", "inventory", "itemCategoryCode",
    )
    print(f"  --- {item_no} ---")
    for k in keys:
        if k in item:
            print(f"    {k:28} {item[k]!r}")


def main():
    items = sys.argv[1:] or ["SP11-42160-01", "SP11-42160-02", "SP12-00234-00", "SH11-11006-00"]
    bc = BusinessCentralClient()
    headers = {"Authorization": f"Bearer {bc._get_access_token()}", "Accept": "application/json"}
    for it in items:
        show(bc, headers, it)


if __name__ == "__main__":
    main()
