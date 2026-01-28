"""
Fetch BC items using OAuth Device Code Flow
This authenticates as the user, using their BC permissions
"""

import msal
import requests
import json
from pathlib import Path

# Azure AD / BC settings
TENANT_ID = "f791be27-77c5-4334-88d0-cfc053e4f091"
CLIENT_ID = "e95810a7-0f6f-462b-9fc2-e60aa04a7bb8"
BC_ENVIRONMENT = "Sandbox_Internal"

# BC API scope for delegated permissions
SCOPES = ["https://api.businesscentral.dynamics.com/Financials.ReadWrite.All"]

def get_token_device_code():
    """Authenticate using device code flow (user signs in via browser)"""
    app = msal.PublicClientApplication(
        CLIENT_ID,
        authority=f"https://login.microsoftonline.com/{TENANT_ID}"
    )

    # Start device code flow
    flow = app.initiate_device_flow(scopes=SCOPES)

    if "user_code" not in flow:
        print(f"Failed to create device flow: {flow}")
        return None

    print("\n" + "=" * 60)
    print("AUTHENTICATION REQUIRED")
    print("=" * 60)
    print(f"\n{flow['message']}\n")
    print("=" * 60)

    # Wait for user to authenticate
    result = app.acquire_token_by_device_flow(flow)

    if "access_token" in result:
        print("\nAuthentication successful!")
        return result["access_token"]
    else:
        print(f"\nAuthentication failed: {result.get('error_description', result)}")
        return None

def fetch_items_with_prefix(token, prefix):
    """Fetch items starting with a given prefix"""
    base_url = f"https://api.businesscentral.dynamics.com/v2.0/{TENANT_ID}/{BC_ENVIRONMENT}/api/v2.0"

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    # First get company ID
    print(f"\nFetching companies...")
    response = requests.get(f"{base_url}/companies", headers=headers)

    if response.status_code != 200:
        print(f"Error getting companies: {response.status_code} - {response.text}")
        return []

    companies = response.json().get("value", [])
    if not companies:
        print("No companies found!")
        return []

    # Use first company (or find the right one)
    company = companies[0]
    company_id = company["id"]
    print(f"Using company: {company['name']} ({company_id})")

    # Fetch items with prefix
    print(f"\nFetching items starting with '{prefix}'...")
    all_items = []

    filter_query = f"startswith(number,'{prefix}')"
    url = f"{base_url}/companies({company_id})/items?$filter={filter_query}&$top=500&$orderby=number"

    response = requests.get(url, headers=headers)

    if response.status_code != 200:
        print(f"Error fetching items: {response.status_code} - {response.text}")
        return []

    items = response.json().get("value", [])
    print(f"Found {len(items)} items with prefix '{prefix}'")

    return items

def main():
    print("=" * 60)
    print("BC Hardware Items Fetcher (OAuth User Authentication)")
    print("=" * 60)

    # Authenticate
    token = get_token_device_code()
    if not token:
        print("Failed to authenticate. Exiting.")
        return

    # Fetch HK items
    hk_items = fetch_items_with_prefix(token, "HK")

    # Fetch HW items
    hw_items = fetch_items_with_prefix(token, "HW")

    # Display results
    print("\n" + "=" * 60)
    print("HK ITEMS (Hardware Kits/Boxes)")
    print("=" * 60)
    for item in sorted(hk_items, key=lambda x: x.get("number", "")):
        num = item.get("number", "")
        name = item.get("displayName", "")[:50]
        price = item.get("unitPrice", 0)
        print(f"{num:25} {name:50} ${price:.2f}")

    print("\n" + "=" * 60)
    print("HW ITEMS (Commercial Hardware)")
    print("=" * 60)
    for item in sorted(hw_items, key=lambda x: x.get("number", "")):
        num = item.get("number", "")
        name = item.get("displayName", "")[:50]
        price = item.get("unitPrice", 0)
        print(f"{num:25} {name:50} ${price:.2f}")

    # Save to file
    output_dir = Path(__file__).parent.parent / "data" / "bc_analysis"
    output_dir.mkdir(parents=True, exist_ok=True)

    output_file = output_dir / "hardware_boxes_from_bc.json"

    result = {
        "fetched_at": str(Path(__file__)),
        "hk_items": [{"number": i.get("number"), "displayName": i.get("displayName"), "unitPrice": i.get("unitPrice")} for i in hk_items],
        "hw_items": [{"number": i.get("number"), "displayName": i.get("displayName"), "unitPrice": i.get("unitPrice")} for i in hw_items],
        "summary": {
            "total_hk_items": len(hk_items),
            "total_hw_items": len(hw_items)
        }
    }

    with open(output_file, "w") as f:
        json.dump(result, f, indent=2)

    print(f"\n\nResults saved to: {output_file}")
    print(f"\nTotal: {len(hk_items)} HK items, {len(hw_items)} HW items")

if __name__ == "__main__":
    main()
