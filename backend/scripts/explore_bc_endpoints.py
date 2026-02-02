"""
BC API Endpoint Discovery Script

Explores all available endpoints in Business Central:
1. Standard API v2.0 endpoints
2. OData Web Services endpoints
3. Lists all entities with their fields
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests
import urllib.parse
import json
from datetime import datetime

from app.config import settings
from app.integrations.bc.client import bc_client


def explore_bc_endpoints():
    """Discover and document all available BC endpoints"""

    print("=" * 80)
    print("BC API Endpoint Discovery")
    print(f"Started at: {datetime.now()}")
    print("=" * 80)

    # Get authentication token
    try:
        token = bc_client._get_access_token()
        print("[OK] Successfully authenticated with BC")
    except Exception as e:
        print(f"[ERROR] Authentication failed: {e}")
        return

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json"
    }

    results = {
        "discovered_at": datetime.now().isoformat(),
        "standard_api": {},
        "odata_services": {},
        "sales_order_lines": None,
        "production_order_lines": None,
    }

    # ==================== 1. Standard API Endpoints ====================
    print("\n" + "=" * 80)
    print("1. STANDARD API v2.0 ENDPOINTS")
    print("=" * 80)

    base_url = settings.bc_api_url
    company_id = settings.BC_COMPANY_ID

    # Get list of available entities from the company
    try:
        # First, list what's available at the company level
        url = f"{base_url}/companies({company_id})"
        response = requests.get(url, headers=headers, timeout=30)

        if response.status_code == 200:
            company_data = response.json()
            print(f"\nCompany: {company_data.get('name', 'Unknown')}")
            print(f"Company ID: {company_id}")
    except Exception as e:
        print(f"Error getting company: {e}")

    # Standard endpoints to check
    standard_endpoints = [
        # Sales
        "salesOrders",
        "salesOrderLines",
        "salesQuotes",
        "salesQuoteLines",
        "salesInvoices",
        "salesInvoiceLines",
        "salesCreditMemos",
        "salesCreditMemoLines",
        "salesShipments",
        "salesShipmentLines",

        # Purchase
        "purchaseOrders",
        "purchaseOrderLines",
        "purchaseInvoices",
        "purchaseInvoiceLines",

        # Inventory
        "items",
        "itemCategories",
        "itemVariants",
        "inventoryPostingGroups",
        "locations",
        "itemLedgerEntries",

        # Customers & Vendors
        "customers",
        "customerPaymentTerms",
        "customerPaymentMethods",
        "vendors",
        "contacts",

        # Production (standard API)
        "productionOrders",
        "productionOrderLines",
        "productionBOMHeaders",
        "productionBOMLines",
        "routings",
        "routingLines",
        "workCenters",
        "machineCenters",
        "capacityLedgerEntries",

        # General
        "accounts",
        "journals",
        "generalLedgerEntries",
        "dimensions",
        "dimensionValues",
        "currencies",
        "paymentTerms",
        "shipmentMethods",
        "unitsOfMeasure",
        "taxGroups",
        "taxAreas",

        # Documents
        "attachments",
        "pdfDocument",

        # Warehouse
        "warehouses",
        "warehouseShipments",
        "warehouseReceipts",
        "binContents",

        # Assembly
        "assemblyOrders",
        "assemblyOrderLines",

        # Jobs
        "jobs",
        "jobTasks",
        "jobTaskLines",
        "timeRegistrationEntries",
    ]

    print("\nChecking standard API endpoints...")
    found_endpoints = []

    for endpoint in standard_endpoints:
        try:
            url = f"{base_url}/companies({company_id})/{endpoint}?$top=1"
            response = requests.get(url, headers=headers, timeout=10)

            if response.status_code == 200:
                data = response.json()
                count = len(data.get("value", []))
                sample = data.get("value", [{}])[0] if data.get("value") else {}
                fields = list(sample.keys()) if sample else []

                results["standard_api"][endpoint] = {
                    "available": True,
                    "sample_fields": fields[:20],  # First 20 fields
                    "field_count": len(fields)
                }
                found_endpoints.append(endpoint)
                print(f"  [OK] {endpoint} - {len(fields)} fields")

                # Special handling for sales order lines
                if endpoint == "salesOrderLines" and sample:
                    results["sales_order_lines"] = {
                        "endpoint": endpoint,
                        "sample": sample,
                        "all_fields": fields
                    }
                    print(f"      *** SALES ORDER LINES FOUND! ***")
                    print(f"      Fields: {', '.join(fields[:10])}...")

            elif response.status_code == 404:
                pass  # Endpoint doesn't exist
            else:
                print(f"  [WARN] {endpoint} - Status {response.status_code}")

        except Exception as e:
            pass  # Timeout or error

    print(f"\nFound {len(found_endpoints)} standard API endpoints")

    # ==================== 2. OData Web Services ====================
    print("\n" + "=" * 80)
    print("2. ODATA WEB SERVICES")
    print("=" * 80)

    odata_base = settings.bc_odata_url
    company_name = settings.BC_COMPANY_NAME
    encoded_company = urllib.parse.quote(company_name)

    print(f"\nOData Base URL: {odata_base}")
    print(f"Company: {company_name}")

    # Try to get the service document (lists all available entities)
    try:
        url = f"{odata_base}/Company('{encoded_company}')"
        response = requests.get(url, headers=headers, timeout=30)

        if response.status_code == 200:
            service_doc = response.json()
            print("\n[OK] OData service document retrieved")

            # The service document should list available entities
            if "value" in service_doc:
                print(f"\nAvailable OData entities: {len(service_doc['value'])}")
                for entity in service_doc.get("value", []):
                    name = entity.get("name", entity.get("url", "unknown"))
                    print(f"  - {name}")
                    results["odata_services"][name] = {"from_service_doc": True}
        else:
            print(f"[WARN] Could not get OData service document: {response.status_code}")

    except Exception as e:
        print(f"Error getting OData service document: {e}")

    # Known OData endpoints to check (published web services)
    odata_endpoints = [
        # Production
        "ReleasedProductionOrders",
        "PlannedProductionOrders",
        "FirmPlannedProdOrders",
        "FinishedProductionOrders",
        "ProdOrderComponents",
        "ProdOrderRouting",
        "ProductionBomLines",
        "WorkCenters",
        "MachineCenters",
        "RoutingLines",

        # Sales
        "SalesOrders",
        "SalesOrderList",
        "SalesLines",
        "SalesOrderLines",
        "SalesOrderSubform",
        "PostedSalesShipments",
        "PostedSalesShipmentLines",
        "SalesInvoices",
        "SalesInvoiceLines",

        # Inventory
        "Items",
        "ItemList",
        "ItemLedgerEntries",
        "ItemAvailabilitybyLocation",
        "ItemAvailabilitybyPeriod",
        "Inventory",
        "InventoryAvailability",
        "BinContents",
        "Locations",

        # Customers
        "Customers",
        "CustomerList",
        "CustomerCard",

        # Purchase
        "PurchaseOrders",
        "PurchaseOrderLines",
        "PurchaseLines",

        # Warehouse
        "WarehouseShipments",
        "WarehouseShipmentLines",
        "WarehouseReceipts",
        "WarehouseReceiptLines",
        "WarehouseActivities",
        "WarehousePicks",
        "WarehousePickLines",

        # Jobs
        "Jobs",
        "JobTaskLines",
        "JobLedgerEntries",

        # General
        "Chart_of_Accounts",
        "GeneralLedgerEntries",
        "GLEntries",
        "DimensionValues",
        "Currencies",

        # Reservations and Tracking
        "ReservationEntries",
        "ItemTrackingLines",
        "TrackingSpecifications",
    ]

    print("\nChecking OData web service endpoints...")
    found_odata = []

    for endpoint in odata_endpoints:
        try:
            url = f"{odata_base}/Company('{encoded_company}')/{endpoint}?$top=1"
            response = requests.get(url, headers=headers, timeout=10)

            if response.status_code == 200:
                data = response.json()
                sample = data.get("value", [{}])[0] if data.get("value") else {}
                fields = list(sample.keys()) if sample else []

                results["odata_services"][endpoint] = {
                    "available": True,
                    "sample_fields": fields[:20],
                    "field_count": len(fields)
                }
                found_odata.append(endpoint)
                print(f"  [OK] {endpoint} - {len(fields)} fields")

                # Check for sales order line related endpoints
                if "sales" in endpoint.lower() and "line" in endpoint.lower():
                    print(f"      *** Potential sales lines endpoint!")
                    print(f"      Fields: {', '.join(fields[:10])}...")
                    if not results.get("sales_order_lines"):
                        results["sales_order_lines"] = {
                            "endpoint": endpoint,
                            "sample": sample,
                            "all_fields": fields,
                            "type": "odata"
                        }

            elif response.status_code == 404:
                pass
            elif response.status_code == 401:
                print(f"  [LOCKED] {endpoint} - Requires additional permissions")
            else:
                pass

        except Exception as e:
            pass

    print(f"\nFound {len(found_odata)} OData web service endpoints")

    # ==================== 3. Deep dive on Sales Orders ====================
    print("\n" + "=" * 80)
    print("3. SALES ORDER DETAILS")
    print("=" * 80)

    # Try to get a sample sales order with expanded lines
    try:
        # Standard API approach
        url = f"{base_url}/companies({company_id})/salesOrders?$top=1&$expand=salesOrderLines"
        response = requests.get(url, headers=headers, timeout=30)

        if response.status_code == 200:
            data = response.json()
            if data.get("value"):
                order = data["value"][0]
                print(f"\n[OK] Sample Sales Order (with expanded lines):")
                print(f"   Order Number: {order.get('number', 'N/A')}")
                print(f"   Customer: {order.get('customerName', 'N/A')}")

                lines = order.get("salesOrderLines", [])
                print(f"   Line Count: {len(lines)}")

                if lines:
                    print("\n   Sample Line Fields:")
                    line_fields = list(lines[0].keys())
                    for field in line_fields:
                        value = lines[0].get(field)
                        print(f"     - {field}: {value}")

                    results["sales_order_lines"] = {
                        "endpoint": "salesOrders?$expand=salesOrderLines",
                        "sample_line": lines[0],
                        "all_fields": line_fields,
                        "type": "standard_api_expand"
                    }
        else:
            print(f"[WARN] Could not expand sales order lines: {response.status_code}")

    except Exception as e:
        print(f"Error: {e}")

    # Try direct salesOrderLines endpoint
    try:
        url = f"{base_url}/companies({company_id})/salesOrderLines?$top=5"
        response = requests.get(url, headers=headers, timeout=30)

        if response.status_code == 200:
            data = response.json()
            if data.get("value"):
                print(f"\n[OK] Direct salesOrderLines endpoint works!")
                print(f"   Sample count: {len(data['value'])}")

                sample = data["value"][0]
                print("\n   All fields in salesOrderLines:")
                for key, value in sample.items():
                    print(f"     - {key}: {value}")

                results["sales_order_lines"] = {
                    "endpoint": "salesOrderLines",
                    "sample": sample,
                    "all_fields": list(sample.keys()),
                    "type": "standard_api_direct"
                }
    except Exception as e:
        print(f"Error checking salesOrderLines: {e}")

    # ==================== 4. Production Order Source Links ====================
    print("\n" + "=" * 80)
    print("4. PRODUCTION ORDER SOURCE LINKS")
    print("=" * 80)

    # Check production order fields for source document links
    try:
        url = f"{odata_base}/Company('{encoded_company}')/ReleasedProductionOrders?$top=5"
        response = requests.get(url, headers=headers, timeout=30)

        if response.status_code == 200:
            data = response.json()
            if data.get("value"):
                print("\n[OK] Production Order Fields (checking for source links):")
                sample = data["value"][0]

                # Look for source-related fields
                source_fields = [k for k in sample.keys() if any(
                    term in k.lower() for term in ['source', 'sales', 'order', 'document', 'line']
                )]

                print("\n   Source-related fields in Production Orders:")
                for field in source_fields:
                    print(f"     - {field}: {sample.get(field)}")

                print("\n   All Production Order fields:")
                for key, value in sample.items():
                    print(f"     - {key}: {value}")

                results["production_order_lines"] = {
                    "sample": sample,
                    "source_fields": source_fields,
                    "all_fields": list(sample.keys())
                }
    except Exception as e:
        print(f"Error: {e}")

    # ==================== 5. Save Results ====================
    print("\n" + "=" * 80)
    print("5. SAVING RESULTS")
    print("=" * 80)

    output_file = os.path.join(os.path.dirname(__file__), "bc_endpoints_discovery.json")
    with open(output_file, "w") as f:
        json.dump(results, f, indent=2, default=str)

    print(f"\n[OK] Results saved to: {output_file}")

    # Summary
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print(f"Standard API endpoints found: {len([k for k, v in results['standard_api'].items() if v.get('available')])}")
    print(f"OData endpoints found: {len([k for k, v in results['odata_services'].items() if v.get('available')])}")

    if results.get("sales_order_lines"):
        print(f"\n*** Sales Order Lines: {results['sales_order_lines'].get('endpoint')}")
        print(f"   Type: {results['sales_order_lines'].get('type')}")
        print(f"   Fields: {len(results['sales_order_lines'].get('all_fields', []))}")

    return results


if __name__ == "__main__":
    explore_bc_endpoints()
