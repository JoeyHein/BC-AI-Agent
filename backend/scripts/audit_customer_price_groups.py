"""Audit real BC customer-to-price-group assignments via OData V4 CustomerList."""
import requests
from collections import Counter
from app.integrations.bc.client import BusinessCentralClient


def main():
    bc = BusinessCentralClient()
    seg = bc._odata_v4_company_segment(None)
    headers = {"Authorization": f"Bearer {bc._get_access_token()}", "Accept": "application/json"}
    url = (
        f"{bc.odata_url}/{seg}/CustomerList"
        f"?$select=No,Name,Customer_Price_Group,Customer_Posting_Group&$top=500"
    )
    rows = []
    while url:
        r = requests.get(url, headers=headers, timeout=30)
        if r.status_code >= 400:
            print(f"HTTP {r.status_code}: {r.text[:200]}")
            return
        d = r.json()
        rows.extend(d.get("value", []))
        url = d.get("@odata.nextLink")

    print(f"Total customers via OData V4 CustomerList: {len(rows)}")
    groups = Counter(c.get("Customer_Price_Group") or "<empty>" for c in rows)
    print("Customer_Price_Group distribution:")
    for k, v in groups.most_common():
        print(f"  {k!r:15} {v}")

    empty = [c for c in rows if not c.get("Customer_Price_Group")]
    print(f"\nCustomers WITHOUT a price group: {len(empty)}")
    for c in empty[:30]:
        print(f"  #{c.get('No'):>8}  {c.get('Name')}")
    if len(empty) > 30:
        print(f"  ...and {len(empty) - 30} more")


if __name__ == "__main__":
    main()
