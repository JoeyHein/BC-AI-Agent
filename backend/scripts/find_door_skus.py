"""
Find Pre-Configured Door SKUs in BC
Search for complete door items (TX450, AL976, etc.) to understand product catalog
"""

import sys
from pathlib import Path
import requests
import json

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
        print("Authenticating with Business Central...")

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
            print("Authentication successful!")
            return True
        else:
            print(f"Authentication failed: {response.status_code}")
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
            print(f"Failed to fetch items: {response.status_code}")
            print(response.text)
            return []


def main():
    print("="*80)
    print("BC Door SKU Discovery")
    print("="*80)

    client = BCAPIClient()

    if not client.authenticate():
        print("\nFailed to authenticate")
        return

    # Search for different door model prefixes
    door_models = ['TX450', 'TX500', 'AL976', 'SB100', 'KANATA', 'PANORAMA']

    all_door_items = {}

    for model in door_models:
        print(f"\n\nSearching for {model} door items...")
        print("-" * 80)

        # Search by item number prefix
        items = client.search_items(filter_query=f"startswith(number,'{model}')", top=100)

        if items:
            print(f"Found {len(items)} items:")
            all_door_items[model] = items

            for item in items[:20]:  # Show first 20
                number = item.get('number', '')
                name = item.get('displayName', '')
                price = item.get('unitPrice', 0)
                cost = item.get('unitCost', 0)

                print(f"  {number:25} ${price:10.2f}  {name[:60]}")
        else:
            print(f"No items found starting with {model}")

    # Summary
    print("\n\n" + "="*80)
    print("SUMMARY")
    print("="*80)
    for model, items in all_door_items.items():
        print(f"{model:15} {len(items):4} items")

    # Look for size patterns in TX450 items
    if 'TX450' in all_door_items:
        print("\n\nTX450 Size Pattern Analysis:")
        print("-" * 80)
        tx450_items = all_door_items['TX450']

        size_patterns = {}
        for item in tx450_items:
            number = item.get('number', '')
            name = item.get('displayName', '')

            # Try to extract dimensions from item number (e.g., TX450-1210-03)
            parts = number.split('-')
            if len(parts) >= 2:
                size_code = parts[1] if len(parts) > 1 else ''
                if size_code:
                    if size_code not in size_patterns:
                        size_patterns[size_code] = []
                    size_patterns[size_code].append({
                        'number': number,
                        'name': name,
                        'price': item.get('unitPrice', 0)
                    })

        print("\nSize Codes Found:")
        for size_code, items_list in sorted(size_patterns.items()):
            print(f"\n  {size_code}:")
            for it in items_list[:5]:  # Show first 5 per size
                print(f"    {it['number']:25} ${it['price']:10.2f}  {it['name'][:50]}")


if __name__ == "__main__":
    main()
