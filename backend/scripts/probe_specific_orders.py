"""Look up specific order numbers in BC to confirm whether they exist."""
import sys
import requests
from app.integrations.bc.client import BusinessCentralClient


def main():
    numbers = sys.argv[1:] or ["SO-001048", "SO-001049", "SO-001074"]
    bc = BusinessCentralClient()
    hdr = {"Authorization": f"Bearer {bc._get_access_token()}", "Accept": "application/json"}
    for n in numbers:
        safe = n.replace("'", "''")
        url = (
            f"{bc.base_url}/companies({bc.company_id})/salesOrders"
            f"?$filter=number eq '{safe}'&$select=number,status,customerName,orderDate"
        )
        r = requests.get(url, headers=hdr, timeout=30)
        if r.status_code >= 400:
            print(f"  {n}: HTTP {r.status_code}")
            continue
        rows = r.json().get("value", [])
        if not rows:
            print(f"  {n}: NOT in BC")
        else:
            o = rows[0]
            print(f"  {n}: in BC, status={o.get('status')!r}, customer={o.get('customerName')!r}")


if __name__ == "__main__":
    main()
