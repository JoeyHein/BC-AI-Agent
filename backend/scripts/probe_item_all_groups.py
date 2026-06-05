"""Show every SalesPriceLists row for a single item across all groups."""
import sys
import requests
from app.integrations.bc.client import BusinessCentralClient


def main():
    item = sys.argv[1] if len(sys.argv) > 1 else "AL95-67400-01"
    bc = BusinessCentralClient()
    seg = bc._odata_v4_company_segment(None)
    headers = {"Authorization": f"Bearer {bc._get_access_token()}", "Accept": "application/json"}
    safe = item.replace("'", "''")
    url = f"{bc.odata_url}/{seg}/SalesPriceLists?$filter=Product_No eq '{safe}'"
    r = requests.get(url, headers=headers, timeout=30)
    rows = r.json().get("value", [])
    print(f"All SalesPriceLists rows for {item}: {len(rows)}")
    for row in rows:
        print(
            f"  list={row.get('Price_List_Code'):15} "
            f"src={row.get('Source_Type'):25} "
            f"assign={row.get('Assign_to_No'):>8} "
            f"price={row.get('Unit_Price'):>10} "
            f"qty>={row.get('Minimum_Quantity'):>5} "
            f"start={row.get('Starting_Date')} end={row.get('Ending_Date')}"
        )


if __name__ == "__main__":
    main()
