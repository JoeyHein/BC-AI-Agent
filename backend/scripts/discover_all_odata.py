"""
Discover ALL available OData services in BC
"""

import sys
import msal
import requests

sys.stdout.reconfigure(line_buffering=True)

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

    print("\n" + "=" * 70)
    print("Discovering ALL OData Services")
    print("=" * 70)

    # First, get the service document which lists all available entities
    print("\n1. Fetching OData service document...")
    url = f"{BC_ODATA_BASE}"
    try:
        resp = requests.get(url, headers=headers, timeout=30)
        print(f"   Status: {resp.status_code}")
        if resp.status_code == 200:
            data = resp.json()
            if "value" in data:
                print(f"\n   Found {len(data['value'])} entities at root level:")
                for item in data["value"][:20]:
                    print(f"   - {item.get('name', item.get('url', str(item)))}")
                if len(data["value"]) > 20:
                    print(f"   ... and {len(data['value']) - 20} more")
    except Exception as e:
        print(f"   Error: {e}")

    # Try company-specific endpoint
    print(f"\n2. Fetching company-specific services for '{COMPANY_NAME}'...")
    url = f"{BC_ODATA_BASE}/Company('{COMPANY_NAME}')"
    try:
        resp = requests.get(url, headers=headers, timeout=30)
        print(f"   Status: {resp.status_code}")
        if resp.status_code == 200:
            data = resp.json()
            print(f"\n   Company data keys: {list(data.keys())[:10]}")

            # Look for production-related items
            prod_related = []
            for key in data.keys():
                if any(term in key.lower() for term in ['prod', 'work', 'routing', 'bom', 'manufact']):
                    prod_related.append(key)

            if prod_related:
                print(f"\n   Production-related keys found:")
                for key in prod_related:
                    print(f"   - {key}")
        elif resp.status_code == 404:
            print(f"   Company '{COMPANY_NAME}' not found!")
            # List available companies
            print("\n   Trying to list available companies...")
            comp_url = f"{BC_ODATA_BASE}/Company"
            try:
                comp_resp = requests.get(comp_url, headers=headers, timeout=30)
                if comp_resp.status_code == 200:
                    companies = comp_resp.json().get("value", [])
                    print(f"   Available companies:")
                    for c in companies:
                        print(f"   - {c.get('name', c)}")
            except:
                pass
    except Exception as e:
        print(f"   Error: {e}")

    # Try $metadata
    print("\n3. Checking OData $metadata...")
    url = f"{BC_ODATA_BASE}/$metadata"
    try:
        resp = requests.get(url, headers=headers, timeout=30)
        print(f"   Status: {resp.status_code}")
        if resp.status_code == 200:
            # Look for production-related entity types in metadata
            content = resp.text
            import re
            entities = re.findall(r'EntityType Name="([^"]+)"', content)
            prod_entities = [e for e in entities if any(term in e.lower() for term in ['prod', 'work', 'routing', 'bom', 'manufact', 'released'])]
            if prod_entities:
                print(f"\n   Production-related EntityTypes in metadata:")
                for e in prod_entities[:15]:
                    print(f"   - {e}")
    except Exception as e:
        print(f"   Error: {e}")

if __name__ == "__main__":
    main()
