"""
BC Production Workflow Explorer
Explores inventory, production orders, and scheduling in Business Central
to understand the workflow for OPENDC integration.
"""

import msal
import requests
import json
import os
from datetime import datetime

# Azure AD / BC Configuration
TENANT_ID = "f791be27-77c5-4334-88d0-cfc053e4f091"
CLIENT_ID = "e95810a7-0f6f-462b-9fc2-e60aa04a7bb8"
BC_ENVIRONMENT = "Sandbox_Internal"
BC_COMPANY_ID = "OPENDC"

AUTHORITY = f"https://login.microsoftonline.com/{TENANT_ID}"
SCOPES = ["https://api.businesscentral.dynamics.com/.default"]

# API Base URLs
BC_API_BASE = f"https://api.businesscentral.dynamics.com/v2.0/{TENANT_ID}/{BC_ENVIRONMENT}/api/v2.0"
BC_ODATA_BASE = f"https://api.businesscentral.dynamics.com/v2.0/{TENANT_ID}/{BC_ENVIRONMENT}/ODataV4"

def get_access_token():
    """Get access token using device code flow"""
    app = msal.PublicClientApplication(
        CLIENT_ID,
        authority=AUTHORITY
    )

    # Try to get cached token first
    accounts = app.get_accounts()
    if accounts:
        result = app.acquire_token_silent(SCOPES, account=accounts[0])
        if result and "access_token" in result:
            print("Using cached token")
            return result["access_token"]

    # Device code flow
    flow = app.initiate_device_flow(scopes=SCOPES)
    if "user_code" not in flow:
        raise Exception(f"Failed to create device flow: {flow.get('error_description', 'Unknown error')}")

    print("\n" + "=" * 60)
    print("AUTHENTICATION REQUIRED")
    print("=" * 60)
    print(f"\n{flow['message']}\n")
    print("=" * 60 + "\n")

    result = app.acquire_token_by_device_flow(flow)

    if "access_token" not in result:
        raise Exception(f"Authentication failed: {result.get('error_description', 'Unknown error')}")

    return result["access_token"]


def explore_api(token: str):
    """Explore BC API to understand available endpoints and data"""

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "Content-Type": "application/json"
    }

    results = {
        "exploration_date": datetime.now().isoformat(),
        "api_base": BC_API_BASE,
        "odata_base": BC_ODATA_BASE,
        "findings": {}
    }

    # 1. Explore Companies
    print("\n" + "=" * 60)
    print("1. EXPLORING COMPANIES")
    print("=" * 60)

    try:
        resp = requests.get(f"{BC_API_BASE}/companies", headers=headers)
        if resp.status_code == 200:
            companies = resp.json().get("value", [])
            results["findings"]["companies"] = companies
            print(f"Found {len(companies)} companies:")
            for c in companies:
                print(f"  - {c.get('name')} (ID: {c.get('id')})")
                if "OPENDC" in c.get('name', '').upper():
                    results["company_id"] = c.get('id')
                    results["company_name"] = c.get('name')
        else:
            print(f"Error: {resp.status_code} - {resp.text}")
    except Exception as e:
        print(f"Error exploring companies: {e}")

    company_id = results.get("company_id")
    if not company_id:
        print("Could not find OPENDC company. Checking all companies...")
        if results["findings"].get("companies"):
            company_id = results["findings"]["companies"][0].get("id")
            results["company_id"] = company_id
            results["company_name"] = results["findings"]["companies"][0].get("name")
            print(f"Using first company: {results['company_name']}")

    if not company_id:
        print("No company found!")
        return results

    # 2. Explore Items (Inventory)
    print("\n" + "=" * 60)
    print("2. EXPLORING ITEMS / INVENTORY")
    print("=" * 60)

    try:
        # Get items with inventory info
        resp = requests.get(
            f"{BC_API_BASE}/companies({company_id})/items?$top=20&$select=id,number,displayName,type,inventory,unitCost,unitPrice,itemCategoryCode",
            headers=headers
        )
        if resp.status_code == 200:
            items = resp.json().get("value", [])
            results["findings"]["sample_items"] = items
            print(f"Found items (showing first 20):")
            for item in items[:10]:
                print(f"  - {item.get('number')}: {item.get('displayName')} | Inventory: {item.get('inventory', 0)} | Type: {item.get('type')}")
        else:
            print(f"Error: {resp.status_code} - {resp.text}")
    except Exception as e:
        print(f"Error exploring items: {e}")

    # 3. Explore Item Categories
    print("\n" + "=" * 60)
    print("3. EXPLORING ITEM CATEGORIES")
    print("=" * 60)

    try:
        resp = requests.get(
            f"{BC_API_BASE}/companies({company_id})/itemCategories",
            headers=headers
        )
        if resp.status_code == 200:
            categories = resp.json().get("value", [])
            results["findings"]["item_categories"] = categories
            print(f"Found {len(categories)} item categories:")
            for cat in categories:
                print(f"  - {cat.get('code')}: {cat.get('displayName')}")
        else:
            print(f"Error: {resp.status_code} - {resp.text}")
    except Exception as e:
        print(f"Error exploring item categories: {e}")

    # 4. Explore Sales Orders
    print("\n" + "=" * 60)
    print("4. EXPLORING SALES ORDERS")
    print("=" * 60)

    try:
        resp = requests.get(
            f"{BC_API_BASE}/companies({company_id})/salesOrders?$top=10&$orderby=orderDate desc",
            headers=headers
        )
        if resp.status_code == 200:
            orders = resp.json().get("value", [])
            results["findings"]["sample_sales_orders"] = orders
            print(f"Found sales orders (showing recent 10):")
            for order in orders:
                print(f"  - {order.get('number')}: Customer {order.get('customerNumber')} | Date: {order.get('orderDate')} | Status: {order.get('status')}")
        else:
            print(f"Error: {resp.status_code} - {resp.text}")
    except Exception as e:
        print(f"Error exploring sales orders: {e}")

    # 5. Explore Sales Quotes
    print("\n" + "=" * 60)
    print("5. EXPLORING SALES QUOTES")
    print("=" * 60)

    try:
        resp = requests.get(
            f"{BC_API_BASE}/companies({company_id})/salesQuotes?$top=10&$orderby=documentDate desc",
            headers=headers
        )
        if resp.status_code == 200:
            quotes = resp.json().get("value", [])
            results["findings"]["sample_sales_quotes"] = quotes
            print(f"Found sales quotes (showing recent 10):")
            for quote in quotes:
                print(f"  - {quote.get('number')}: Customer {quote.get('customerNumber')} | Date: {quote.get('documentDate')}")
        else:
            print(f"Error: {resp.status_code} - {resp.text}")
    except Exception as e:
        print(f"Error exploring sales quotes: {e}")

    # 6. Explore Production-related OData endpoints
    print("\n" + "=" * 60)
    print("6. EXPLORING PRODUCTION ORDERS (OData)")
    print("=" * 60)

    # Try different production order endpoints
    production_endpoints = [
        "ProductionOrders",
        "Released_Production_Orders",
        "Firm_Planned_Prod_Orders",
        "Production_Order",
        "ProductionOrder",
        "Prod_Orders",
        "ProdOrders"
    ]

    for endpoint in production_endpoints:
        try:
            resp = requests.get(
                f"{BC_ODATA_BASE}/Company('{results.get('company_name', 'OPENDC')}'/{endpoint}?$top=5",
                headers=headers
            )
            if resp.status_code == 200:
                data = resp.json().get("value", [])
                results["findings"][f"production_{endpoint}"] = data
                print(f"\n{endpoint}: Found {len(data)} records")
                for item in data[:3]:
                    print(f"  {json.dumps(item, indent=2)[:200]}...")
            else:
                print(f"{endpoint}: {resp.status_code}")
        except Exception as e:
            print(f"{endpoint}: Error - {e}")

    # 7. Explore Work Centers
    print("\n" + "=" * 60)
    print("7. EXPLORING WORK CENTERS")
    print("=" * 60)

    work_center_endpoints = ["WorkCenters", "Work_Centers", "workCenters"]

    for endpoint in work_center_endpoints:
        try:
            resp = requests.get(
                f"{BC_ODATA_BASE}/Company('{results.get('company_name', 'OPENDC')}'/{endpoint}?$top=10",
                headers=headers
            )
            if resp.status_code == 200:
                data = resp.json().get("value", [])
                results["findings"]["work_centers"] = data
                print(f"Found {len(data)} work centers:")
                for wc in data:
                    print(f"  - {wc}")
                break
            else:
                print(f"{endpoint}: {resp.status_code}")
        except Exception as e:
            print(f"{endpoint}: Error - {e}")

    # 8. Explore Production BOMs
    print("\n" + "=" * 60)
    print("8. EXPLORING PRODUCTION BOMs")
    print("=" * 60)

    bom_endpoints = ["ProductionBOMs", "Production_BOMs", "ProductionBOM", "Production_BOM_Header"]

    for endpoint in bom_endpoints:
        try:
            resp = requests.get(
                f"{BC_ODATA_BASE}/Company('{results.get('company_name', 'OPENDC')}'/{endpoint}?$top=10",
                headers=headers
            )
            if resp.status_code == 200:
                data = resp.json().get("value", [])
                results["findings"]["production_boms"] = data
                print(f"Found {len(data)} production BOMs:")
                for bom in data[:5]:
                    print(f"  - {bom}")
                break
            else:
                print(f"{endpoint}: {resp.status_code}")
        except Exception as e:
            print(f"{endpoint}: Error - {e}")

    # 9. Explore Item Ledger Entries (Inventory Transactions)
    print("\n" + "=" * 60)
    print("9. EXPLORING ITEM LEDGER ENTRIES")
    print("=" * 60)

    try:
        resp = requests.get(
            f"{BC_API_BASE}/companies({company_id})/itemLedgerEntries?$top=20&$orderby=postingDate desc",
            headers=headers
        )
        if resp.status_code == 200:
            entries = resp.json().get("value", [])
            results["findings"]["item_ledger_entries"] = entries
            print(f"Found item ledger entries (showing recent 20):")
            for entry in entries[:10]:
                print(f"  - {entry.get('itemNumber')}: {entry.get('entryType')} | Qty: {entry.get('quantity')} | Date: {entry.get('postingDate')}")
        else:
            print(f"Error: {resp.status_code} - {resp.text}")
    except Exception as e:
        print(f"Error exploring item ledger entries: {e}")

    # 10. Explore Locations (Warehouses)
    print("\n" + "=" * 60)
    print("10. EXPLORING LOCATIONS (Warehouses)")
    print("=" * 60)

    try:
        resp = requests.get(
            f"{BC_API_BASE}/companies({company_id})/locations",
            headers=headers
        )
        if resp.status_code == 200:
            locations = resp.json().get("value", [])
            results["findings"]["locations"] = locations
            print(f"Found {len(locations)} locations:")
            for loc in locations:
                print(f"  - {loc.get('code')}: {loc.get('displayName')}")
        else:
            print(f"Error: {resp.status_code} - {resp.text}")
    except Exception as e:
        print(f"Error exploring locations: {e}")

    # 11. Explore Purchase Orders
    print("\n" + "=" * 60)
    print("11. EXPLORING PURCHASE ORDERS")
    print("=" * 60)

    try:
        resp = requests.get(
            f"{BC_API_BASE}/companies({company_id})/purchaseOrders?$top=10&$orderby=orderDate desc",
            headers=headers
        )
        if resp.status_code == 200:
            pos = resp.json().get("value", [])
            results["findings"]["purchase_orders"] = pos
            print(f"Found purchase orders (showing recent 10):")
            for po in pos:
                print(f"  - {po.get('number')}: Vendor {po.get('vendorNumber')} | Date: {po.get('orderDate')} | Status: {po.get('status')}")
        else:
            print(f"Error: {resp.status_code} - {resp.text}")
    except Exception as e:
        print(f"Error exploring purchase orders: {e}")

    # 12. Try to list all available API endpoints
    print("\n" + "=" * 60)
    print("12. DISCOVERING AVAILABLE API ENDPOINTS")
    print("=" * 60)

    # Standard v2.0 API entities
    standard_endpoints = [
        "items", "customers", "vendors", "salesOrders", "salesQuotes",
        "salesInvoices", "purchaseOrders", "purchaseInvoices", "employees",
        "itemCategories", "locations", "itemLedgerEntries", "generalLedgerEntries",
        "accounts", "dimensions", "dimensionValues", "currencies",
        "paymentTerms", "shipmentMethods", "customerPayments", "vendorPayments",
        "bankAccounts", "journals", "journalLines", "taxGroups",
        "unitsOfMeasure", "countries", "salesOrderLines", "purchaseOrderLines"
    ]

    available_endpoints = []
    for endpoint in standard_endpoints:
        try:
            resp = requests.get(
                f"{BC_API_BASE}/companies({company_id})/{endpoint}?$top=1",
                headers=headers
            )
            if resp.status_code == 200:
                available_endpoints.append(endpoint)
                print(f"  [OK] {endpoint}")
            else:
                print(f"  [--] {endpoint}: {resp.status_code}")
        except Exception as e:
            print(f"  [ERR] {endpoint}: {e}")

    results["findings"]["available_v2_endpoints"] = available_endpoints

    # 13. Explore Custom APIs (OPENDC-specific)
    print("\n" + "=" * 60)
    print("13. EXPLORING CUSTOM/OPENDC APIs")
    print("=" * 60)

    # Try to discover custom APIs
    custom_api_patterns = [
        "/api/opendc/v1.0",
        "/api/opendc/v2.0",
        "/api/v1.0",
        "/api/beta"
    ]

    for pattern in custom_api_patterns:
        try:
            base_url = f"https://api.businesscentral.dynamics.com/v2.0/{TENANT_ID}/{BC_ENVIRONMENT}{pattern}"
            resp = requests.get(f"{base_url}/companies", headers=headers)
            if resp.status_code == 200:
                print(f"  [OK] Custom API found at: {pattern}")
                results["findings"]["custom_api_base"] = pattern
            else:
                print(f"  [--] {pattern}: {resp.status_code}")
        except Exception as e:
            print(f"  [ERR] {pattern}: {e}")

    # 14. Get detailed item with all fields
    print("\n" + "=" * 60)
    print("14. DETAILED ITEM STRUCTURE")
    print("=" * 60)

    try:
        resp = requests.get(
            f"{BC_API_BASE}/companies({company_id})/items?$top=1",
            headers=headers
        )
        if resp.status_code == 200:
            items = resp.json().get("value", [])
            if items:
                print("Sample item structure:")
                print(json.dumps(items[0], indent=2))
                results["findings"]["item_schema"] = list(items[0].keys())
        else:
            print(f"Error: {resp.status_code}")
    except Exception as e:
        print(f"Error: {e}")

    return results


def main():
    print("=" * 60)
    print("BC Production Workflow Explorer")
    print("=" * 60)

    try:
        token = get_access_token()
        print("\nAuthentication successful!")

        results = explore_api(token)

        # Save results
        output_dir = os.path.join(os.path.dirname(__file__), "..", "data", "bc_analysis")
        os.makedirs(output_dir, exist_ok=True)

        output_file = os.path.join(output_dir, "bc_workflow_exploration.json")
        with open(output_file, "w") as f:
            json.dump(results, f, indent=2, default=str)

        print(f"\n\nResults saved to: {output_file}")

        # Summary
        print("\n" + "=" * 60)
        print("EXPLORATION SUMMARY")
        print("=" * 60)
        print(f"Company: {results.get('company_name', 'Unknown')}")
        print(f"Available v2.0 endpoints: {len(results['findings'].get('available_v2_endpoints', []))}")
        print(f"Sample items found: {len(results['findings'].get('sample_items', []))}")
        print(f"Item categories: {len(results['findings'].get('item_categories', []))}")
        print(f"Locations: {len(results['findings'].get('locations', []))}")

    except Exception as e:
        print(f"\nError: {e}")
        raise


if __name__ == "__main__":
    main()
