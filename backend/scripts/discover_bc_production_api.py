"""
BC Production API Discovery
Discovers available production-related endpoints in Business Central.

The standard v2.0 API doesn't include production orders - they must be exposed via:
1. Custom API pages (APIPublisher/APIGroup pattern)
2. OData web services (published pages/queries)
"""

import msal
import requests
import json
import os
from datetime import datetime

# Configuration
TENANT_ID = "f791be27-77c5-4334-88d0-cfc053e4f091"
CLIENT_ID = "e95810a7-0f6f-462b-9fc2-e60aa04a7bb8"
BC_ENVIRONMENT = "Sandbox_Internal"

AUTHORITY = f"https://login.microsoftonline.com/{TENANT_ID}"
SCOPES = ["https://api.businesscentral.dynamics.com/.default"]

# BC API URLs
BC_V2_BASE = f"https://api.businesscentral.dynamics.com/v2.0/{TENANT_ID}/{BC_ENVIRONMENT}/api/v2.0"
BC_ODATA_BASE = f"https://api.businesscentral.dynamics.com/v2.0/{TENANT_ID}/{BC_ENVIRONMENT}/ODataV4"

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

    # Wait longer for user to authenticate (10 minutes)
    import time
    result = app.acquire_token_by_device_flow(flow, timeout=600)
    if "access_token" not in result:
        raise Exception(f"Auth failed: {result.get('error_description')}")

    return result["access_token"]


def discover_apis(token: str):
    """Discover available BC APIs including production-related"""

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json"
    }

    results = {
        "discovery_date": datetime.now().isoformat(),
        "companies": [],
        "standard_v2_endpoints": [],
        "odata_endpoints": [],
        "custom_apis": [],
        "production_related": [],
        "inventory_related": []
    }

    # 1. Get Companies
    print("\n[1] Fetching companies...")
    try:
        resp = requests.get(f"{BC_V2_BASE}/companies", headers=headers)
        if resp.status_code == 200:
            companies = resp.json().get("value", [])
            results["companies"] = companies
            for c in companies:
                print(f"    Company: {c.get('name')} (ID: {c.get('id')})")
    except Exception as e:
        print(f"    Error: {e}")

    if not results["companies"]:
        print("No companies found!")
        return results

    company = results["companies"][0]
    company_id = company["id"]
    company_name = company["name"]

    # 2. Test Standard v2.0 Endpoints
    print(f"\n[2] Testing standard v2.0 endpoints for {company_name}...")
    standard_endpoints = [
        "items", "customers", "vendors", "employees",
        "salesQuotes", "salesOrders", "salesInvoices", "salesShipments",
        "purchaseOrders", "purchaseInvoices",
        "locations", "itemCategories", "itemLedgerEntries",
        "accounts", "dimensions", "dimensionValues",
        "journals", "generalLedgerEntries",
        "unitsOfMeasure", "paymentTerms", "currencies"
    ]

    for ep in standard_endpoints:
        try:
            resp = requests.get(f"{BC_V2_BASE}/companies({company_id})/{ep}?$top=1", headers=headers)
            if resp.status_code == 200:
                results["standard_v2_endpoints"].append(ep)
                print(f"    [OK] {ep}")
            else:
                print(f"    [--] {ep}: {resp.status_code}")
        except Exception as e:
            print(f"    [ERR] {ep}: {e}")

    # 3. Try OData endpoints for production/manufacturing
    print(f"\n[3] Testing OData manufacturing/production endpoints...")

    # Common production-related page/table names in BC
    production_endpoints = [
        # Production Order related
        "Production_Orders",
        "ProductionOrders",
        "Released_Production_Orders",
        "Released_Prod_Orders",
        "Firm_Planned_Prod_Orders",
        "Production_Order",
        "Prod_Order_Lines",
        "Production_Order_Lines",
        "Prod_Order_Components",
        # BOMs and Routing
        "Production_BOM",
        "Production_BOM_Headers",
        "Production_BOM_Lines",
        "Routings",
        "Routing_Headers",
        "Routing_Lines",
        # Work Centers / Capacity
        "Work_Centers",
        "WorkCenters",
        "Machine_Centers",
        "MachineCenters",
        "Capacity_Ledger_Entries",
        "Work_Center_Calendar",
        # Planning
        "Planning_Worksheets",
        "Requisition_Lines",
        "Planning_Components"
    ]

    for ep in production_endpoints:
        try:
            # Try both URL encoding styles
            url = f"{BC_ODATA_BASE}/Company('{company_name}')/{ep}?$top=1"
            resp = requests.get(url, headers=headers)
            if resp.status_code == 200:
                data = resp.json().get("value", [])
                results["production_related"].append({
                    "endpoint": ep,
                    "count": len(data),
                    "sample": data[0] if data else None
                })
                print(f"    [OK] {ep} - Found {len(data)} records")
            else:
                # Try alternate URL format
                url2 = f"{BC_ODATA_BASE}/Company('{company_name}')/{ep.replace('_', '')}?$top=1"
                resp2 = requests.get(url2, headers=headers)
                if resp2.status_code == 200:
                    data = resp2.json().get("value", [])
                    results["production_related"].append({
                        "endpoint": ep.replace('_', ''),
                        "count": len(data),
                        "sample": data[0] if data else None
                    })
                    print(f"    [OK] {ep.replace('_', '')} - Found {len(data)} records")
                else:
                    print(f"    [--] {ep}: {resp.status_code}")
        except Exception as e:
            print(f"    [ERR] {ep}: {e}")

    # 4. Try Custom API patterns
    print(f"\n[4] Testing custom API patterns...")

    # Custom API patterns that might be published by OPENDC
    custom_patterns = [
        ("opendc", "v1.0"),
        ("opendc", "v2.0"),
        ("manufacturing", "v1.0"),
        ("production", "v1.0"),
        ("mfg", "v1.0")
    ]

    for publisher, version in custom_patterns:
        try:
            url = f"https://api.businesscentral.dynamics.com/v2.0/{TENANT_ID}/{BC_ENVIRONMENT}/api/{publisher}/manufacturing/{version}/companies"
            resp = requests.get(url, headers=headers)
            if resp.status_code == 200:
                print(f"    [OK] Custom API found: {publisher}/manufacturing/{version}")
                results["custom_apis"].append(f"{publisher}/manufacturing/{version}")
            else:
                print(f"    [--] {publisher}/manufacturing/{version}: {resp.status_code}")
        except Exception as e:
            print(f"    [ERR] {publisher}/manufacturing/{version}: {e}")

    # 5. Check inventory-related data
    print(f"\n[5] Checking inventory data...")

    # Get item with inventory levels
    try:
        resp = requests.get(
            f"{BC_V2_BASE}/companies({company_id})/items?$top=5&$filter=inventory gt 0",
            headers=headers
        )
        if resp.status_code == 200:
            items = resp.json().get("value", [])
            print(f"    Items with inventory: {len(items)} found")
            for item in items[:3]:
                print(f"      - {item.get('number')}: {item.get('inventory')} units")
            results["inventory_related"] = items
    except Exception as e:
        print(f"    Error: {e}")

    # 6. Check OData metadata to discover all available services
    print(f"\n[6] Fetching OData service metadata...")
    try:
        resp = requests.get(
            f"{BC_ODATA_BASE}/Company('{company_name}')/$metadata",
            headers=headers
        )
        if resp.status_code == 200:
            # Parse available entity sets from metadata
            metadata = resp.text
            # Save metadata for analysis
            output_dir = os.path.join(os.path.dirname(__file__), "..", "data", "bc_analysis")
            os.makedirs(output_dir, exist_ok=True)
            with open(os.path.join(output_dir, "odata_metadata.xml"), "w") as f:
                f.write(metadata)
            print(f"    Metadata saved to odata_metadata.xml")

            # Extract entity names (simple parsing)
            import re
            entities = re.findall(r'EntitySet\s+Name="([^"]+)"', metadata)
            results["odata_endpoints"] = entities
            print(f"    Found {len(entities)} OData entity sets")

            # Print production-related entities
            prod_entities = [e for e in entities if any(kw in e.lower() for kw in
                ['prod', 'manufact', 'work', 'routing', 'bom', 'capacity', 'plan'])]
            if prod_entities:
                print(f"\n    Production-related entities:")
                for e in prod_entities:
                    print(f"      - {e}")
    except Exception as e:
        print(f"    Error: {e}")

    return results


def main():
    print("=" * 60)
    print("BC Production API Discovery")
    print("=" * 60)

    try:
        token = get_token()
        print("\nAuthentication successful!")

        results = discover_apis(token)

        # Save results
        output_dir = os.path.join(os.path.dirname(__file__), "..", "data", "bc_analysis")
        os.makedirs(output_dir, exist_ok=True)

        output_file = os.path.join(output_dir, "production_api_discovery.json")
        with open(output_file, "w") as f:
            json.dump(results, f, indent=2, default=str)

        print(f"\n\nResults saved to: {output_file}")

        # Summary
        print("\n" + "=" * 60)
        print("DISCOVERY SUMMARY")
        print("=" * 60)
        print(f"Companies: {len(results.get('companies', []))}")
        print(f"Standard v2.0 endpoints: {len(results.get('standard_v2_endpoints', []))}")
        print(f"OData entity sets: {len(results.get('odata_endpoints', []))}")
        print(f"Production-related: {len(results.get('production_related', []))}")
        print(f"Custom APIs: {len(results.get('custom_apis', []))}")

        if results.get("production_related"):
            print("\nProduction endpoints found:")
            for ep in results["production_related"]:
                print(f"  - {ep['endpoint']}")
        else:
            print("\n*** No production order endpoints found in standard locations ***")
            print("Options to access production orders:")
            print("  1. Ask BC admin to publish Production Order page as OData web service")
            print("  2. Create custom API page extension in BC")
            print("  3. Use Power Automate / Logic Apps as middleware")

    except Exception as e:
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
