"""Compare every cost field on the workflowItems entity for an item."""
import sys
import requests
from app.integrations.bc.client import BusinessCentralClient


def main():
    item_no = sys.argv[1] if len(sys.argv) > 1 else "GK16-23205-00"
    bc = BusinessCentralClient()
    seg = bc._odata_v4_company_segment(None)
    hdr = {"Authorization": f"Bearer {bc._get_access_token()}", "Accept": "application/json"}
    safe = item_no.replace("'", "''")
    url = f"{bc.odata_url}/{seg}/workflowItems?$filter=number eq '{safe}'"
    r = requests.get(url, headers=hdr, timeout=30)
    rows = r.json().get("value", [])
    if not rows:
        print(f"Status {r.status_code}, no rows. Body: {r.text[:300]}")
        return
    item = rows[0]
    keys = [
        "number", "displayName", "unitCost", "standardCost",
        "lastDirectCost", "indirectCostPercent", "lastUnitCostCalcDate",
        "costingMethod", "unitPrice",
    ]
    for k in keys:
        if k in item:
            print(f"  {k:30} {item[k]!r}")


if __name__ == "__main__":
    main()
