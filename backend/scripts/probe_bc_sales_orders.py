"""See exactly what BC's salesOrders endpoint returns."""
import requests
from collections import Counter
from app.integrations.bc.client import BusinessCentralClient


def main():
    bc = BusinessCentralClient()
    hdr = {"Authorization": f"Bearer {bc._get_access_token()}", "Accept": "application/json"}
    url = (
        f"{bc.base_url}/companies({bc.company_id})/salesOrders"
        f"?$top=200&$select=number,status,customerName,orderDate"
    )
    r = requests.get(url, headers=hdr, timeout=60)
    print(f"HTTP {r.status_code}")
    if r.status_code >= 400:
        print(r.text[:500])
        return
    data = r.json().get("value", [])
    print(f"Total BC sales orders returned: {len(data)}")
    statuses = Counter(o.get("status", "<empty>") for o in data)
    print("By status:")
    for k, v in statuses.most_common():
        print(f"  {k!r:25} {v}")
    print()
    print("Sample 5:")
    for o in data[:5]:
        print(f"  {o.get('number'):15} status={o.get('status')!r:15} customer={o.get('customerName')!r}")


if __name__ == "__main__":
    main()
