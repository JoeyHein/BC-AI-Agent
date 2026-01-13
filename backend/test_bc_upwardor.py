"""
Test BC API connection and explore Upwardor-related endpoints
"""

import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, 'C:\\Users\\jhein\\bc-ai-agent\\backend')

from app.integrations.bc.client import bc_client
import json

print("=" * 70)
print("BC API -> UPWARDOR PORTAL CONNECTION TEST")
print("=" * 70)

# Test basic connection
print("\n1. Testing BC API connection...")
if bc_client.test_connection():
    print("   ✅ BC API connection successful!")
else:
    print("   ❌ BC API connection failed")
    sys.exit(1)

# Get companies
print("\n2. Getting companies...")
companies = bc_client.get_companies()
print(f"   Found {len(companies)} companies:")
for company in companies:
    print(f"   - {company.get('displayName')} (ID: {company.get('id')})")

# Get items (this might include Upwardor products)
print("\n3. Getting items from BC...")
items = bc_client.get_items(top=20)
print(f"   Found {len(items)} items (showing first 20):")
for item in items[:10]:
    print(f"   - {item.get('number')}: {item.get('displayName')} (${item.get('unitPrice', 0)})")

# Search for TX450 (common door series)
print("\n4. Searching for TX450 items...")
try:
    # BC API doesn't support OR in filters, so let's just filter by number
    all_items = bc_client.get_items(top=500)
    tx450_items = [item for item in all_items if 'TX450' in item.get('number', '')]
    print(f"   Found {len(tx450_items)} TX450 items:")
    for item in tx450_items[:10]:
        print(f"   - {item.get('number')}: {item.get('displayName')} (${item.get('unitPrice', 0)})")
except Exception as e:
    print(f"   Error searching: {e}")

# Get recent quotes
print("\n5. Getting recent sales quotes...")
quotes = bc_client.get_sales_quotes(top=5)
print(f"   Found {len(quotes)} recent quotes:")
for quote in quotes[:3]:
    print(f"   - Quote #{quote.get('number')}: {quote.get('customerName')} (${quote.get('totalAmountIncludingTax', 0)})")

# Try to explore BC API structure for custom endpoints
print("\n6. Exploring BC API for Upwardor-related endpoints...")
print("   Standard BC API endpoints we have access to:")
print("   - /companies")
print("   - /companies({id})/customers")
print("   - /companies({id})/items")
print("   - /companies({id})/salesQuotes")
print("   - /companies({id})/vendors")
print("   - /companies({id})/purchaseOrders")

print("\n7. Checking if BC has custom Upwardor integration...")
print("   Possible custom endpoint patterns to try:")
print("   - /companies({id})/upwardor/*")
print("   - /companies({id})/doorConfigurations")
print("   - /companies({id})/portalIntegration")

# Try to make a custom request to potential Upwardor endpoints
print("\n   Testing potential custom endpoints...")

potential_endpoints = [
    "upwardor",
    "upwardorIntegration",
    "doorConfigurations",
    "portalIntegration",
    "doorQuotes",
    "upwardorQuotes"
]

for endpoint in potential_endpoints:
    try:
        url = f"companies({bc_client.company_id})/{endpoint}"
        print(f"   Trying: {url}...", end=" ")
        result = bc_client._make_request("GET", url)
        print(f"✅ Found! Returned {len(result)} items")
        print(f"      Response: {json.dumps(result, indent=6)[:200]}...")
        break
    except Exception as e:
        error_msg = str(e)
        if "404" in error_msg:
            print("❌ Not found (404)")
        elif "400" in error_msg:
            print("❌ Bad request (400)")
        else:
            print(f"❌ Error: {error_msg[:50]}")

print("\n" + "=" * 70)
print("ANALYSIS")
print("=" * 70)

print("""
Based on this test, here's what we can do:

OPTION 1: BC has custom Upwardor endpoints (if we found any above)
- We can use BC as a proxy to access Upwardor portal
- BC handles authentication and data transformation
- We make requests through BC API

OPTION 2: BC stores Upwardor data in standard tables
- Items in BC might be synced from Upwardor
- We can search items by part number (TX450-*, etc.)
- We create quotes directly in BC using standard API
- BC might sync quotes back to Upwardor automatically

OPTION 3: BC and Upwardor are separate systems
- We need to integrate both APIs separately
- Parse email → Validate with Upwardor → Create in BC
- Keep both systems in sync manually

NEXT STEPS:
1. Check with your IT/BC admin: "Does BC have custom Upwardor API endpoints?"
2. Ask: "How does BC communicate with the Upwardor portal?"
3. Look for BC customizations/extensions that might expose Upwardor API
4. Check if there's documentation for BC-Upwardor integration
""")

print("\n" + "=" * 70)
