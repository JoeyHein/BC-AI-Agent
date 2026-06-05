"""
Audit BC's actual price-group state:
  1. Distinct Source_Type values present in SalesPriceLists
  2. Distinct Assign_to_No values for Customer / Customer Price Group lines
  3. Distinct customerPriceGroup codes across all BC customers
  4. Customers missing a customerPriceGroup
"""
import requests
from collections import Counter
from app.integrations.bc.client import BusinessCentralClient


def fetch_all(bc, url, headers):
    """Page through @odata.nextLink."""
    rows = []
    while url:
        resp = requests.get(url, headers=headers, timeout=30)
        if resp.status_code >= 400:
            print(f"  HTTP {resp.status_code}: {resp.text[:200]}")
            break
        data = resp.json()
        rows.extend(data.get("value", []))
        url = data.get("@odata.nextLink")
    return rows


def main():
    bc = BusinessCentralClient()
    token = bc._get_access_token()
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    seg = bc._odata_v4_company_segment(None)

    # 1+2: SalesPriceLists breakdown
    url = f"{bc.odata_url}/{seg}/SalesPriceLists?$select=Source_Type,Assign_to_No,Price_List_Code"
    print("Fetching SalesPriceLists...")
    rows = fetch_all(bc, url, headers)
    print(f"  Total rows: {len(rows)}")
    by_source = Counter(r.get("Source_Type") for r in rows)
    print("  By Source_Type:")
    for k, v in by_source.most_common():
        print(f"    {k!r:30} {v}")
    print("  Customer Price Group -> distinct Assign_to_No values:")
    cpg = sorted({r.get("Assign_to_No") for r in rows if r.get("Source_Type") == "Customer Price Group"})
    for code in cpg:
        n = sum(1 for r in rows if r.get("Source_Type") == "Customer Price Group" and r.get("Assign_to_No") == code)
        print(f"    {code!r:30} {n} lines")
    print("  Customer -> distinct Assign_to_No values (sample 10):")
    cust = sorted({r.get("Assign_to_No") for r in rows if r.get("Source_Type") == "Customer"})
    for code in cust[:10]:
        print(f"    {code!r}")
    print(f"  ({len(cust)} distinct customer-specific entries total)")
    print("  Distinct Price_List_Codes:")
    for code in sorted({r.get("Price_List_Code") for r in rows}):
        print(f"    {code!r}")

    # 3+4: customer price-group assignments
    print("\nFetching all BC customers (api/v2.0)...")
    url2 = f"{bc.base_url}/companies({bc.company_id})/customers?$top=1000"
    customers = fetch_all(bc, url2, headers)
    print(f"  Total customers: {len(customers)}")
    groups = Counter(c.get("customerPriceGroup") or "<empty>" for c in customers)
    print("  customerPriceGroup distribution:")
    for k, v in groups.most_common():
        print(f"    {k!r:30} {v}")


if __name__ == "__main__":
    main()
