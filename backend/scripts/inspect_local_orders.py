"""Show every local SalesOrder vs whether it actually exists in BC.

Local rows can come from:
  - The portal's quote-to-order conversion (creates a local row with bc_id)
  - Legacy code paths that never hit BC (local-only — bc_id NULL)
  - The new bulk sync (every BC order gets a row)

Goal: find rows the tracker is showing that aren't actually in BC.
"""
import requests
from app.db.database import SessionLocal
from app.db.models import SalesOrder
from app.integrations.bc.client import BusinessCentralClient


def main():
    bc = BusinessCentralClient()
    hdr = {"Authorization": f"Bearer {bc._get_access_token()}", "Accept": "application/json"}

    # Pull every BC order number in one shot
    url = (
        f"{bc.base_url}/companies({bc.company_id})/salesOrders"
        f"?$top=500&$select=number"
    )
    bc_numbers = set()
    while url:
        r = requests.get(url, headers=hdr, timeout=60)
        if r.status_code >= 400:
            print(f"BC HTTP {r.status_code}: {r.text[:200]}")
            return
        d = r.json()
        bc_numbers.update(o.get("number") for o in d.get("value", []) if o.get("number"))
        url = d.get("@odata.nextLink")
    print(f"BC has {len(bc_numbers)} sales orders")

    db = SessionLocal()
    try:
        rows = db.query(SalesOrder).all()
        print(f"Local SalesOrder rows: {len(rows)}\n")

        in_bc, not_in_bc = [], []
        for r in rows:
            (in_bc if r.bc_order_number in bc_numbers else not_in_bc).append(r)

        print(f"Rows present in BC      : {len(in_bc)}")
        print(f"Rows NOT in BC (orphans): {len(not_in_bc)}")
        print()
        if not_in_bc:
            print("Orphan rows (showing in tracker but not in BC):")
            for r in not_in_bc:
                print(
                    f"  bc_no={r.bc_order_number!r:20} customer={r.customer_name!r:30} "
                    f"status={r.status.value if r.status else None!r} "
                    f"bc_id={r.bc_id!r:40} last_synced={r.last_synced_at}"
                )
    finally:
        db.close()


if __name__ == "__main__":
    main()
