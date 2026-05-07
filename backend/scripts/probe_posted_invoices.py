"""See what fields BC's PostedSalesInvoices entity exposes — specifically
whether it carries the originating sales-order number and dates we need
for the order-to-invoice cycle-time view."""
import json
import requests
from app.integrations.bc.client import BusinessCentralClient


def main():
    bc = BusinessCentralClient()
    hdr = {"Authorization": f"Bearer {bc._get_access_token()}", "Accept": "application/json"}

    # 1. api/v2.0 — try the standard endpoint
    url = f"{bc.base_url}/companies({bc.company_id})/salesInvoices?$top=2"
    r = requests.get(url, headers=hdr, timeout=30)
    print(f"=== api/v2.0 salesInvoices ({r.status_code}) ===")
    if r.status_code == 200:
        rows = r.json().get("value", [])
        if rows:
            for k in sorted(rows[0].keys()):
                v = rows[0][k]
                if isinstance(v, str) and len(v) > 50:
                    v = v[:50] + "..."
                print(f"  {k:35} {v!r}")
        else:
            print("  (empty)")
    else:
        print(f"  {r.text[:300]}")

    # 2. OData V4 PostedSalesInvoices
    seg = bc._odata_v4_company_segment(None)
    url2 = f"{bc.odata_url}/{seg}/PostedSalesInvoices?$top=2"
    r2 = requests.get(url2, headers=hdr, timeout=30)
    print(f"\n=== OData V4 PostedSalesInvoices ({r2.status_code}) ===")
    if r2.status_code == 200:
        rows = r2.json().get("value", [])
        if rows:
            for k in sorted(rows[0].keys()):
                v = rows[0][k]
                if isinstance(v, str) and len(v) > 50:
                    v = v[:50] + "..."
                print(f"  {k:35} {v!r}")
        else:
            print("  (empty)")
    else:
        print(f"  {r2.text[:300]}")


if __name__ == "__main__":
    main()
