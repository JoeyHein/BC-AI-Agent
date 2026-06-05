"""
Pull every cost-related field BC exposes for a given item, plus the
SalesPriceLists Unit_Cost and Unit_Price across every group, to find
where the cost figure is actually coming from.
"""
import sys
import requests
from app.integrations.bc.client import BusinessCentralClient


def main():
    item_no = sys.argv[1] if len(sys.argv) > 1 else "GK16-23205-00"
    bc = BusinessCentralClient()
    headers = {"Authorization": f"Bearer {bc._get_access_token()}", "Accept": "application/json"}

    # 1. api/v2.0 — what the portal currently uses
    safe = item_no.replace("'", "''")
    url1 = f"{bc.base_url}/companies({bc.company_id})/items?$filter=number eq '{safe}'"
    r1 = requests.get(url1, headers=headers, timeout=30)
    rows1 = r1.json().get("value", [])
    print(f"=== api/v2.0 items endpoint for {item_no} ===")
    if rows1:
        item = rows1[0]
        cost_keys = [k for k in item.keys() if "cost" in k.lower() or "price" in k.lower()]
        for k in cost_keys:
            print(f"  {k:35} {item[k]!r}")
    else:
        print("  not found")

    # 2. OData V4 ItemCard or Item Card page — fuller schema
    seg = bc._odata_v4_company_segment(None)
    url2 = f"{bc.odata_url}/{seg}/Items?$filter=No eq '{safe}'&$top=1"
    r2 = requests.get(url2, headers=headers, timeout=30)
    print(f"\n=== OData V4 'Items' page for {item_no} ===")
    if r2.status_code == 200 and r2.json().get("value"):
        item2 = r2.json()["value"][0]
        cost_keys = [k for k in item2.keys() if "cost" in k.lower() or "price" in k.lower()]
        for k in cost_keys:
            print(f"  {k:35} {item2[k]!r}")
    else:
        print(f"  HTTP {r2.status_code} or empty")

    # 3. ItemCard page (alt name)
    url3 = f"{bc.odata_url}/{seg}/ItemList?$filter=No eq '{safe}'&$top=1"
    r3 = requests.get(url3, headers=headers, timeout=30)
    print(f"\n=== OData V4 'ItemList' page for {item_no} ===")
    if r3.status_code == 200 and r3.json().get("value"):
        item3 = r3.json()["value"][0]
        cost_keys = [k for k in item3.keys() if "cost" in k.lower() or "price" in k.lower() or k.lower() in ("no", "description")]
        for k in cost_keys:
            print(f"  {k:35} {item3[k]!r}")
    else:
        print(f"  HTTP {r3.status_code} or empty")

    # 4. Every SalesPriceLists row for this item
    url4 = f"{bc.odata_url}/{seg}/SalesPriceLists?$filter=Product_No eq '{safe}'"
    r4 = requests.get(url4, headers=headers, timeout=30)
    rows4 = r4.json().get("value", [])
    print(f"\n=== SalesPriceLists rows for {item_no} ({len(rows4)}) ===")
    for row in rows4:
        print(
            f"  list={row.get('Price_List_Code'):15} "
            f"src={row.get('Source_Type'):25} "
            f"assign={row.get('Assign_to_No') or '':>8} "
            f"price=${row.get('Unit_Price'):>9} "
            f"cost=${row.get('Unit_Cost'):>9} "
            f"qty>={row.get('Minimum_Quantity'):>3}"
        )


if __name__ == "__main__":
    main()
