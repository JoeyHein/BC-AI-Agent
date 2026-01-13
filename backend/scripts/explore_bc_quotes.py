"""
Explore Business Central Sandbox - Quote Data Analysis
Connect to BC API and analyze the 888 quotes
"""

import sys
from pathlib import Path
import requests
import json
from datetime import datetime

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
            print(response.text)
            return False

    def get_headers(self):
        """Get API request headers with auth token"""
        return {
            'Authorization': f'Bearer {self.access_token}',
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        }

    def get_quotes(self, top=10):
        """Get sales quotes from BC"""
        print(f"\nFetching sales quotes (top {top})...")

        # BC API endpoint for sales quotes
        url = f"{self.base_url}/{self.tenant_id}/{self.environment}/api/v2.0/companies({self.company_id})/salesQuotes"

        params = {'$top': top}

        response = requests.get(url, headers=self.get_headers(), params=params)

        if response.status_code == 200:
            data = response.json()
            quotes = data.get('value', [])
            print(f"Found {len(quotes)} quotes")
            return quotes
        else:
            print(f"Failed to fetch quotes: {response.status_code}")
            print(response.text)
            return []

    def get_quote_lines(self, quote_id):
        """Get line items for a specific quote"""
        url = f"{self.base_url}/{self.tenant_id}/{self.environment}/api/v2.0/companies({self.company_id})/salesQuotes({quote_id})/salesQuoteLines"

        response = requests.get(url, headers=self.get_headers())

        if response.status_code == 200:
            data = response.json()
            return data.get('value', [])
        else:
            return []

    def get_items(self, top=50):
        """Get items/products from BC"""
        print(f"\nFetching items/products (top {top})...")

        url = f"{self.base_url}/{self.tenant_id}/{self.environment}/api/v2.0/companies({self.company_id})/items"

        params = {'$top': top}

        response = requests.get(url, headers=self.get_headers(), params=params)

        if response.status_code == 200:
            data = response.json()
            items = data.get('value', [])
            print(f"Found {len(items)} items")
            return items
        else:
            print(f"Failed to fetch items: {response.status_code}")
            return []


def analyze_quote_structure(quotes):
    """Analyze quote structure and print findings"""
    if not quotes:
        print("\nNo quotes to analyze")
        return

    print("\n" + "="*80)
    print("QUOTE STRUCTURE ANALYSIS")
    print("="*80)

    # Analyze first quote in detail
    sample_quote = quotes[0]

    print("\nSample Quote Fields:")
    print("-" * 80)
    for key, value in sample_quote.items():
        value_preview = str(value)[:100] if value else "null"
        print(f"  {key:30} = {value_preview}")

    # Analyze all quotes for patterns
    print("\nQuote Statistics:")
    print("-" * 80)

    total = len(quotes)
    print(f"  Total quotes analyzed: {total}")

    # Check which fields are populated
    field_counts = {}
    for quote in quotes:
        for key, value in quote.items():
            if key not in field_counts:
                field_counts[key] = 0
            if value:
                field_counts[key] += 1

    print(f"\n  Field Population Rates:")
    for field, count in sorted(field_counts.items(), key=lambda x: x[1], reverse=True):
        percentage = (count / total) * 100
        print(f"    {field:30} {count:4}/{total} ({percentage:5.1f}%)")


def analyze_items(items):
    """Analyze item/product structure"""
    if not items:
        print("\nNo items to analyze")
        return

    print("\n" + "="*80)
    print("PRODUCT/ITEM ANALYSIS")
    print("="*80)

    # Sample item
    sample_item = items[0]

    print("\nSample Item Fields:")
    print("-" * 80)
    for key, value in sample_item.items():
        value_preview = str(value)[:100] if value else "null"
        print(f"  {key:30} = {value_preview}")

    # List all items
    print(f"\nProduct List (showing {len(items)} items):")
    print("-" * 80)
    for item in items[:20]:  # Show first 20
        number = item.get('number', 'N/A')
        description = item.get('displayName', item.get('description', 'N/A'))
        price = item.get('unitPrice', item.get('baseUnitOfMeasure', 'N/A'))
        print(f"  {number:20} | {description:50} | {price}")


def main():
    print("=" * 80)
    print("BC AI Agent - Business Central Sandbox Explorer")
    print("=" * 80)
    print(f"\nEnvironment: {settings.BC_ENVIRONMENT}")
    print(f"Company ID: {settings.BC_COMPANY_ID}")

    # Create BC client
    client = BCAPIClient()

    # Authenticate
    if not client.authenticate():
        print("\nFailed to authenticate. Check credentials in .env file")
        return

    # Get quotes
    quotes = client.get_quotes(top=50)  # Get first 50 quotes

    if quotes:
        analyze_quote_structure(quotes)

        # Get line items for first quote
        if quotes:
            print("\n" + "="*80)
            print("ANALYZING QUOTE LINE ITEMS")
            print("="*80)
            quote_id = quotes[0].get('id')
            print(f"\nGetting line items for quote: {quote_id}")
            lines = client.get_quote_lines(quote_id)
            if lines:
                print(f"\nFound {len(lines)} line items")
                print("\nSample line item:")
                print(json.dumps(lines[0], indent=2))
            else:
                print("No line items found")

    # Get items/products
    items = client.get_items(top=50)
    if items:
        analyze_items(items)

    print("\n" + "="*80)
    print("EXPLORATION COMPLETE")
    print("="*80)


if __name__ == "__main__":
    main()
