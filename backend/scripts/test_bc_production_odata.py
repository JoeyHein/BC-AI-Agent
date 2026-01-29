"""
Test BC Production OData Web Services

Run this script after BC admin publishes the required OData web services
to verify connectivity and access.

Usage:
    python scripts/test_bc_production_odata.py
"""

import msal
import requests
import json
from datetime import datetime

# Configuration
TENANT_ID = "f791be27-77c5-4334-88d0-cfc053e4f091"
CLIENT_ID = "e95810a7-0f6f-462b-9fc2-e60aa04a7bb8"
BC_ENVIRONMENT = "Sandbox_Internal"
COMPANY_NAME = "OPENDC"

AUTHORITY = f"https://login.microsoftonline.com/{TENANT_ID}"
SCOPES = ["https://api.businesscentral.dynamics.com/.default"]

BC_ODATA_BASE = f"https://api.businesscentral.dynamics.com/v2.0/{TENANT_ID}/{BC_ENVIRONMENT}/ODataV4"

# OData services to test (service names as configured in BC Web Services)
PRODUCTION_SERVICES = [
    ("ReleasedProductionOrders", "Production Orders"),
    ("ProdOrderComponents", "Production Order Components"),
    ("WorkCenters", "Work Centers"),
    ("ProdOrderRouting", "Production Order Routing"),
]


def get_token():
    """Get access token via device code flow"""
    app = msal.PublicClientApplication(CLIENT_ID, authority=AUTHORITY)

    # Check cache
    accounts = app.get_accounts()
    if accounts:
        result = app.acquire_token_silent(SCOPES, account=accounts[0])
        if result and "access_token" in result:
            print("[OK] Using cached token")
            return result["access_token"]

    # Device code flow
    flow = app.initiate_device_flow(scopes=SCOPES)
    if "user_code" not in flow:
        raise Exception(f"Device flow failed: {flow.get('error_description')}")

    print("\n" + "=" * 60)
    print("AUTHENTICATION REQUIRED")
    print("=" * 60)
    print(f"\n{flow['message']}\n")
    print("=" * 60)

    result = app.acquire_token_by_device_flow(flow, timeout=300)
    if "access_token" not in result:
        raise Exception(f"Auth failed: {result.get('error_description')}")

    return result["access_token"]


def test_odata_service(token: str, service_name: str, description: str) -> dict:
    """Test a single OData service"""
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json"
    }

    url = f"{BC_ODATA_BASE}/Company('{COMPANY_NAME}')/{service_name}?$top=3"

    result = {
        "service": service_name,
        "description": description,
        "url": url,
        "status": "unknown",
        "records": 0,
        "sample": None,
        "error": None
    }

    try:
        response = requests.get(url, headers=headers, timeout=30)

        if response.status_code == 200:
            data = response.json()
            records = data.get("value", [])
            result["status"] = "OK"
            result["records"] = len(records)
            if records:
                result["sample"] = records[0]
            print(f"  [OK] {description}: Found {len(records)} records")

        elif response.status_code == 404:
            result["status"] = "NOT_FOUND"
            result["error"] = "Service not published in BC Web Services"
            print(f"  [!!] {description}: NOT PUBLISHED (404)")

        elif response.status_code == 401:
            result["status"] = "UNAUTHORIZED"
            result["error"] = "Authentication failed or insufficient permissions"
            print(f"  [!!] {description}: AUTH ERROR (401)")

        elif response.status_code == 403:
            result["status"] = "FORBIDDEN"
            result["error"] = "User doesn't have permission to access this data"
            print(f"  [!!] {description}: NO PERMISSION (403)")

        else:
            result["status"] = f"ERROR_{response.status_code}"
            result["error"] = response.text[:200]
            print(f"  [!!] {description}: Error {response.status_code}")

    except requests.exceptions.Timeout:
        result["status"] = "TIMEOUT"
        result["error"] = "Request timed out"
        print(f"  [!!] {description}: TIMEOUT")

    except Exception as e:
        result["status"] = "ERROR"
        result["error"] = str(e)
        print(f"  [!!] {description}: {e}")

    return result


def main():
    print("=" * 60)
    print("BC Production OData Web Services Test")
    print("=" * 60)
    print(f"\nTenant: {TENANT_ID}")
    print(f"Environment: {BC_ENVIRONMENT}")
    print(f"Company: {COMPANY_NAME}")
    print(f"OData Base: {BC_ODATA_BASE}")

    try:
        token = get_token()
        print("\n[OK] Authentication successful!\n")

        print("Testing OData Web Services...")
        print("-" * 60)

        results = []
        for service_name, description in PRODUCTION_SERVICES:
            result = test_odata_service(token, service_name, description)
            results.append(result)

        # Summary
        print("\n" + "=" * 60)
        print("TEST RESULTS SUMMARY")
        print("=" * 60)

        ok_count = sum(1 for r in results if r["status"] == "OK")
        total = len(results)

        print(f"\nServices Available: {ok_count}/{total}")

        if ok_count == total:
            print("\n[SUCCESS] ALL SERVICES AVAILABLE!")
            print("\nNext steps:")
            print("1. Update PRODUCTION_API_AVAILABLE = True in bc_production_service.py")
            print("2. Restart the backend server")
            print("3. Test production order creation via API")
        else:
            print("\n[WARNING] SOME SERVICES MISSING")
            print("\nMissing services need to be published in BC:")
            for r in results:
                if r["status"] != "OK":
                    print(f"  - {r['description']} ({r['service']}): {r['error']}")

            print("\nSee docs/BC_ODATA_SETUP_GUIDE.md for setup instructions.")

        # Show sample data from working services
        print("\n" + "-" * 60)
        print("SAMPLE DATA FROM AVAILABLE SERVICES")
        print("-" * 60)

        for r in results:
            if r["status"] == "OK" and r["sample"]:
                print(f"\n{r['description']}:")
                print(json.dumps(r["sample"], indent=2, default=str)[:500])

        # Save results
        output = {
            "test_date": datetime.now().isoformat(),
            "tenant_id": TENANT_ID,
            "environment": BC_ENVIRONMENT,
            "company": COMPANY_NAME,
            "summary": {
                "services_available": ok_count,
                "services_total": total,
                "all_available": ok_count == total
            },
            "results": results
        }

        with open("data/bc_analysis/production_odata_test_results.json", "w") as f:
            json.dump(output, f, indent=2, default=str)

        print(f"\nResults saved to: data/bc_analysis/production_odata_test_results.json")

        return ok_count == total

    except Exception as e:
        print(f"\n[ERROR] {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = main()
    exit(0 if success else 1)
