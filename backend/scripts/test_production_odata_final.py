"""
Test BC Production OData services with correct company name
"""

import sys
import msal
import requests
import json

sys.stdout.reconfigure(line_buffering=True)

TENANT_ID = "f791be27-77c5-4334-88d0-cfc053e4f091"
CLIENT_ID = "e95810a7-0f6f-462b-9fc2-e60aa04a7bb8"
BC_ENVIRONMENT = "Sandbox_Internal"

# CORRECT company name from BC
COMPANY_NAME = "Open Distribution Company Inc."

AUTHORITY = f"https://login.microsoftonline.com/{TENANT_ID}"
SCOPES = ["https://api.businesscentral.dynamics.com/.default"]
BC_ODATA_BASE = f"https://api.businesscentral.dynamics.com/v2.0/{TENANT_ID}/{BC_ENVIRONMENT}/ODataV4"

# Production OData services discovered in metadata
PRODUCTION_SERVICES = [
    ("ReleasedProductionOrders", "Released Production Orders"),
    ("ProdOrderComponents", "Production Order Components"),
    ("ProdOrderRouting", "Production Order Routing"),
    ("WorkCenters", "Work Centers"),
    ("ProductionBomLines", "Production BOM Lines"),
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
    print("=" * 70)
    print("BC Production OData Services Test")
    print("=" * 70)
    print(f"\nCompany: {COMPANY_NAME}")
    print(f"Environment: {BC_ENVIRONMENT}")

    token = get_token()
    if not token:
        print("\nAuth failed!")
        return

    print("\n[OK] Authenticated!\n")

    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}

    # URL encode the company name
    import urllib.parse
    encoded_company = urllib.parse.quote(COMPANY_NAME)

    print("Testing OData Services...")
    print("-" * 70)

    results = []
    for service_name, description in PRODUCTION_SERVICES:
        url = f"{BC_ODATA_BASE}/Company('{encoded_company}')/{service_name}?$top=3"
        try:
            resp = requests.get(url, headers=headers, timeout=30)
            if resp.status_code == 200:
                data = resp.json()
                count = len(data.get("value", []))
                print(f"  [OK] {description}: {count} records found")
                results.append((service_name, "OK", count, data.get("value", [])[:1]))
            elif resp.status_code == 404:
                print(f"  [!!] {description}: NOT PUBLISHED (404)")
                results.append((service_name, "404", 0, None))
            else:
                print(f"  [!!] {description}: Error {resp.status_code}")
                results.append((service_name, f"ERR_{resp.status_code}", 0, None))
        except Exception as e:
            print(f"  [!!] {description}: {e}")
            results.append((service_name, "ERROR", 0, None))

    # Summary
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)

    ok_count = sum(1 for r in results if r[1] == "OK")
    print(f"\nServices Available: {ok_count}/{len(results)}")

    if ok_count == len(results):
        print("\n[SUCCESS] ALL PRODUCTION SERVICES AVAILABLE!")
        print("\nYou can now enable production integration:")
        print("1. Set PRODUCTION_API_AVAILABLE = True in bc_production_service.py")
        print("2. Restart the backend server")
    elif ok_count > 0:
        print(f"\n[PARTIAL] {ok_count} services working, some still missing")
    else:
        print("\n[FAILED] No production services available")

    # Show sample data
    print("\n" + "-" * 70)
    print("SAMPLE DATA")
    print("-" * 70)
    for service_name, status, count, sample in results:
        if status == "OK" and sample:
            print(f"\n{service_name}:")
            print(json.dumps(sample[0], indent=2, default=str)[:500])

if __name__ == "__main__":
    main()
