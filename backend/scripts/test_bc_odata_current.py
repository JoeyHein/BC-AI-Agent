"""
Test currently published BC OData services
"""

import sys
import msal
import requests

# Flush output immediately for real-time display
sys.stdout.reconfigure(line_buffering=True)

TENANT_ID = "f791be27-77c5-4334-88d0-cfc053e4f091"
CLIENT_ID = "e95810a7-0f6f-462b-9fc2-e60aa04a7bb8"
BC_ENVIRONMENT = "Sandbox_Internal"
COMPANY_NAME = "OPENDC"

AUTHORITY = f"https://login.microsoftonline.com/{TENANT_ID}"
SCOPES = ["https://api.businesscentral.dynamics.com/.default"]
BC_ODATA_BASE = f"https://api.businesscentral.dynamics.com/v2.0/{TENANT_ID}/{BC_ENVIRONMENT}/ODataV4"

# Services visible in screenshot + variations to try
SERVICES_TO_TEST = [
    # From screenshot
    "ProdOrderComponents",
    "ProdOrderComp",
    "ProdOrderRouting",
    "Production_BOM",
    # Production orders variations
    "ReleasedProductionOrders",
    "Released_Production_Orders",
    "ProductionOrders",
    "Production_Orders",
    # Work centers
    "WorkCenters",
    "Work_Centers",
    "WorkCenter",
]

def get_token():
    app = msal.PublicClientApplication(CLIENT_ID, authority=AUTHORITY)
    accounts = app.get_accounts()
    if accounts:
        result = app.acquire_token_silent(SCOPES, account=accounts[0])
        if result and "access_token" in result:
            print("[OK] Using cached token")
            return result["access_token"]

    flow = app.initiate_device_flow(scopes=SCOPES)
    print(f"\nGo to {flow['verification_uri']} and enter code: {flow['user_code']}\n")
    result = app.acquire_token_by_device_flow(flow, timeout=300)
    return result.get("access_token")

def main():
    token = get_token()
    if not token:
        print("Auth failed")
        return

    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}

    print("\n" + "=" * 60)
    print("Testing BC OData Services")
    print("=" * 60)

    found = []
    not_found = []

    for service in SERVICES_TO_TEST:
        url = f"{BC_ODATA_BASE}/Company('{COMPANY_NAME}')/{service}?$top=1"
        try:
            resp = requests.get(url, headers=headers, timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                count = len(data.get("value", []))
                print(f"  [FOUND] {service} - {count} record(s)")
                found.append(service)
            elif resp.status_code == 404:
                not_found.append(service)
            else:
                print(f"  [{resp.status_code}] {service}")
        except Exception as e:
            print(f"  [ERROR] {service}: {e}")

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"\nFound ({len(found)}):")
    for s in found:
        print(f"  - {s}")

    print(f"\nNot Found ({len(not_found)}):")
    for s in not_found:
        print(f"  - {s}")

if __name__ == "__main__":
    main()
