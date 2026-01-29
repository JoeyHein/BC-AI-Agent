"""
Discover all available OData services in BC
"""

import msal
import requests

TENANT_ID = "f791be27-77c5-4334-88d0-cfc053e4f091"
CLIENT_ID = "e95810a7-0f6f-462b-9fc2-e60aa04a7bb8"
BC_ENVIRONMENT = "Sandbox_Internal"
COMPANY_NAME = "OPENDC"

AUTHORITY = f"https://login.microsoftonline.com/{TENANT_ID}"
SCOPES = ["https://api.businesscentral.dynamics.com/.default"]
BC_ODATA_BASE = f"https://api.businesscentral.dynamics.com/v2.0/{TENANT_ID}/{BC_ENVIRONMENT}/ODataV4"

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

    # Get OData metadata to find all available services
    print("\nFetching OData service document...")
    url = f"{BC_ODATA_BASE}/Company('{COMPANY_NAME}')"

    try:
        resp = requests.get(url, headers=headers)
        print(f"Status: {resp.status_code}")

        if resp.status_code == 200:
            data = resp.json()
            print(f"\nAvailable OData services in BC:")
            print("-" * 50)

            # The response should contain links to available entity sets
            if "value" in data:
                for item in data["value"]:
                    print(f"  - {item.get('name', item)}")
            else:
                # Try to extract from the response
                for key in data:
                    if key not in ["@odata.context", "@odata.metadataEtag"]:
                        print(f"  - {key}")
        else:
            print(f"Error: {resp.text[:500]}")

    except Exception as e:
        print(f"Error: {e}")

    # Also try common production-related variations
    print("\n\nTrying common production service name variations...")
    variations = [
        "Production_Orders", "ProductionOrders", "Prod_Orders",
        "Released_Production_Orders", "ReleasedProductionOrders",
        "Firm_Planned_Prod_Orders", "FirmPlannedProdOrders",
        "Production_Order", "Prod_Order",
        "Work_Center", "Work_Centers", "WorkCenter", "WorkCenters",
        "Machine_Center", "Machine_Centers",
        "Routing", "Routings", "Routing_Header",
        "Production_BOM", "ProductionBOM", "Prod_BOM",
    ]

    for name in variations:
        try:
            url = f"{BC_ODATA_BASE}/Company('{COMPANY_NAME}')/{name}?$top=1"
            resp = requests.get(url, headers=headers, timeout=10)
            if resp.status_code == 200:
                print(f"  [FOUND] {name}")
            elif resp.status_code == 404:
                pass  # Not found, skip
            else:
                print(f"  [{resp.status_code}] {name}")
        except:
            pass

if __name__ == "__main__":
    main()
