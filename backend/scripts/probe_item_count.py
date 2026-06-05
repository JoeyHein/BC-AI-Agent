"""Find the true count of BC items via multiple endpoints."""
import requests
from app.integrations.bc.client import BusinessCentralClient


def main():
    bc = BusinessCentralClient()
    headers = {"Authorization": f"Bearer {bc._get_access_token()}", "Accept": "application/json"}

    # api/v2.0 items: try $count
    url = f"{bc.base_url}/companies({bc.company_id})/items?$count=true&$top=1"
    r = requests.get(url, headers=headers, timeout=30)
    data = r.json()
    print(f"api/v2.0 items $count: {data.get('@odata.count', '(not exposed)')}")
    print(f"  has nextLink: {'@odata.nextLink' in data}")
    print(f"  first page len: {len(data.get('value', []))}")

    # OData V4 ItemCard or similar
    seg = bc._odata_v4_company_segment(None)
    for entity in ("Items", "ItemCard", "Item_List", "Item_Card"):
        url2 = f"{bc.odata_url}/{seg}/{entity}?$count=true&$top=1"
        r2 = requests.get(url2, headers=headers, timeout=30)
        if r2.status_code == 200:
            d2 = r2.json()
            print(f"OData V4 {entity}: count={d2.get('@odata.count', '?')} status=200")
        else:
            print(f"OData V4 {entity}: HTTP {r2.status_code}")

    # api/v2.0 with $skip pagination test
    print("\nManual $skip pagination test on api/v2.0 items:")
    skip = 0
    total = 0
    pages = 0
    while True:
        url3 = f"{bc.base_url}/companies({bc.company_id})/items?$top=1000&$skip={skip}&$select=number"
        r3 = requests.get(url3, headers=headers, timeout=30)
        if r3.status_code >= 400:
            print(f"  page {pages}: HTTP {r3.status_code}")
            break
        d3 = r3.json()
        n = len(d3.get("value", []))
        total += n
        pages += 1
        print(f"  page {pages} (skip={skip}): {n} items")
        if n < 1000:
            break
        skip += 1000
        if pages > 30:
            break
    print(f"  TOTAL via $skip: {total} items in {pages} pages")


if __name__ == "__main__":
    main()
