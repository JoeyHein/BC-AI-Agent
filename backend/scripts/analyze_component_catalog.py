"""
Analyze Component Catalog - Understand part number structure
Search for sections, hardware, glass, springs, etc.
"""

import sys
from pathlib import Path
import requests
from collections import defaultdict

# Add backend to path
backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

from app.config import settings

class BCAPIClient:
    """Business Central API Client"""

    def __init__(self):
        self.tenant_id = settings.BC_TENANT_ID
        self.client_id = settings.BC_CLIENT_ID
        self.client_secret = settings.BC_CLIENT_SECRET
        self.environment = settings.BC_ENVIRONMENT
        self.company_id = settings.BC_COMPANY_ID
        self.base_url = settings.BC_BASE_URL
        self.access_token = None

    def authenticate(self):
        """Get OAuth2 access token from Azure AD"""
        token_url = f"https://login.microsoftonline.com/{self.tenant_id}/oauth2/v2.0/token"

        data = {
            'client_id': self.client_id,
            'client_secret': self.client_secret,
            'scope': 'https://api.businesscentral.dynamics.com/.default',
            'grant_type': 'client_credentials'
        }

        response = requests.post(token_url, data=data)
        if response.status_code == 200:
            self.access_token = response.json()['access_token']
            return True
        return False

    def get_headers(self):
        """Get API request headers with auth token"""
        return {
            'Authorization': f'Bearer {self.access_token}',
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        }

    def search_items(self, filter_query=None, top=200):
        """Search items with optional OData filter"""
        url = f"{self.base_url}/{self.tenant_id}/{self.environment}/api/v2.0/companies({self.company_id})/items"

        params = {'$top': top}
        if filter_query:
            params['$filter'] = filter_query

        response = requests.get(url, headers=self.get_headers(), params=params)

        if response.status_code == 200:
            return response.json().get('value', [])
        else:
            return []


def main():
    print("="*80)
    print("BC Component Catalog Analysis")
    print("="*80)

    client = BCAPIClient()

    if not client.authenticate():
        print("\nFailed to authenticate")
        return

    # Component prefixes from quote analysis
    component_types = {
        'PN': 'Panel/Section',
        'GK': 'Glass Kit',
        'TR': 'Track',
        'HK': 'Hardware Kit',
        'HW': 'Hardware Box',
        'SH': 'Shaft',
        'SP': 'Springs',
        'PL': 'Plastics/Seals',
        'OP': 'Operator',
        'FH': 'Struts',
        'AL': 'Aluminum Components'
    }

    catalog_summary = {}

    for prefix, description in component_types.items():
        print(f"\n\nSearching for {description} ({prefix}...)...")
        print("-" * 80)

        items = client.search_items(filter_query=f"startswith(number,'{prefix}')", top=50)

        if items:
            print(f"Found {len(items)} items (showing first 10):")
            catalog_summary[prefix] = len(items)

            for item in items[:10]:
                number = item.get('number', '')
                name = item.get('displayName', '')[:60]
                price = item.get('unitPrice') or item.get('unitCost', 0)

                print(f"  {number:25} ${price:10.2f}  {name}")
        else:
            print(f"No items found with prefix {prefix}")
            catalog_summary[prefix] = 0

    # Look for special items
    print("\n\nSearching for Special Items...")
    print("-" * 80)
    special_items = ['POWDERCOAT', 'FREIGHT', 'CUSTOM', 'WRAP']

    for special in special_items:
        items = client.search_items(filter_query=f"number eq '{special}'", top=10)
        if items:
            for item in items:
                number = item.get('number', '')
                name = item.get('displayName', '')
                price = item.get('unitPrice') or item.get('unitCost', 0)
                print(f"  {number:25} ${price:10.2f}  {name}")

    # Summary
    print("\n\n" + "="*80)
    print("CATALOG SUMMARY")
    print("="*80)
    print(f"{'Component Type':30} {'Prefix':10} {'Count':>10}")
    print("-" * 80)
    for prefix, description in component_types.items():
        count = catalog_summary.get(prefix, 0)
        print(f"{description:30} {prefix:10} {count:>10}")

    print(f"\n\nTotal Component Types: {len([c for c in catalog_summary.values() if c > 0])}")
    print(f"Total Items Found: {sum(catalog_summary.values())} (limited to 50 per type)")


if __name__ == "__main__":
    main()
