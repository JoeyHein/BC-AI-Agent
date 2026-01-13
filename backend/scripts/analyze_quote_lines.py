"""
Analyze BC Quote Line Items - Deep Dive
Fetch multiple quotes and analyze their line items to understand product structure
"""

import sys
from pathlib import Path
import requests
import json
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
        url = f"{self.base_url}/{self.tenant_id}/{self.environment}/api/v2.0/companies({self.company_id})/salesQuotes"
        params = {'$top': top}
        response = requests.get(url, headers=self.get_headers(), params=params)

        if response.status_code == 200:
            return response.json().get('value', [])
        else:
            print(f"Failed to fetch quotes: {response.status_code}")
            return []

    def get_quote_lines(self, quote_id):
        """Get line items for a specific quote"""
        url = f"{self.base_url}/{self.tenant_id}/{self.environment}/api/v2.0/companies({self.company_id})/salesQuotes({quote_id})/salesQuoteLines"
        response = requests.get(url, headers=self.get_headers())

        if response.status_code == 200:
            return response.json().get('value', [])
        else:
            return []

    def get_item(self, item_id):
        """Get specific item by ID"""
        url = f"{self.base_url}/{self.tenant_id}/{self.environment}/api/v2.0/companies({self.company_id})/items({item_id})"
        response = requests.get(url, headers=self.get_headers())

        if response.status_code == 200:
            return response.json()
        else:
            return None


def analyze_line_item_patterns(client, quotes):
    """Analyze line items from multiple quotes to understand patterns"""
    print("\n" + "="*80)
    print("LINE ITEM PATTERN ANALYSIS")
    print("="*80)

    line_type_counts = defaultdict(int)
    item_lines = []
    comment_lines = []

    total_lines = 0
    quotes_with_lines = 0

    for i, quote in enumerate(quotes[:10]):  # Analyze first 10 quotes
        quote_number = quote.get('number')
        quote_id = quote.get('id')
        customer = quote.get('customerName')

        lines = client.get_quote_lines(quote_id)

        if not lines:
            continue

        quotes_with_lines += 1
        total_lines += len(lines)

        print(f"\n--- Quote {quote_number} - {customer} ({len(lines)} lines) ---")

        for line in lines:
            line_type = line.get('lineType', 'Unknown')
            line_type_counts[line_type] += 1

            # Categorize lines
            if line_type == 'Comment':
                comment_lines.append({
                    'quote': quote_number,
                    'description': line.get('description', '')
                })
                print(f"  [COMMENT] {line.get('description', '')[:80]}")
            else:
                item_number = line.get('lineObjectNumber', '')
                description = line.get('description', '')
                qty = line.get('quantity', 0)
                price = line.get('unitPrice', 0)
                amount = line.get('amountExcludingTax', 0)

                item_lines.append({
                    'quote': quote_number,
                    'item_number': item_number,
                    'description': description,
                    'quantity': qty,
                    'unit_price': price,
                    'amount': amount
                })

                print(f"  [{line_type:8}] {item_number:20} x{qty:5.1f} @ ${price:8.2f} = ${amount:10.2f}")
                if description:
                    print(f"               {description[:70]}")

    # Summary statistics
    print("\n" + "="*80)
    print("SUMMARY")
    print("="*80)
    print(f"Quotes analyzed: {quotes_with_lines}")
    print(f"Total line items: {total_lines}")
    print(f"\nLine Type Distribution:")
    for line_type, count in sorted(line_type_counts.items(), key=lambda x: x[1], reverse=True):
        percentage = (count / total_lines * 100) if total_lines > 0 else 0
        print(f"  {line_type:15} {count:4} ({percentage:5.1f}%)")

    # Analyze comment patterns
    print(f"\n\nCOMMENT LINE PATTERNS (showing first 20):")
    print("-" * 80)
    for comment in comment_lines[:20]:
        print(f"  {comment['quote']:12} | {comment['description'][:65]}")

    # Analyze item patterns
    print(f"\n\nITEM LINE PATTERNS (showing first 20):")
    print("-" * 80)
    for item in item_lines[:20]:
        print(f"  {item['quote']:12} | {item['item_number']:20} | ${item['amount']:10.2f}")

    # Look for door model patterns in comments
    print("\n\nDOOR MODEL DETECTION IN COMMENTS:")
    print("-" * 80)
    door_models = set()
    for comment in comment_lines:
        desc = comment['description'].upper()
        # Common door model patterns
        if 'AL976' in desc:
            door_models.add('AL976')
        if 'TX450' in desc:
            door_models.add('TX450')
        if 'SB100' in desc:
            door_models.add('SB100')
        # Add more patterns as needed

    print(f"Found door models: {', '.join(sorted(door_models))}")

    return {
        'line_type_counts': dict(line_type_counts),
        'item_lines': item_lines,
        'comment_lines': comment_lines
    }


def main():
    print("="*80)
    print("BC Quote Line Item Deep Dive Analysis")
    print("="*80)

    # Create BC client
    client = BCAPIClient()

    # Authenticate
    if not client.authenticate():
        print("\nFailed to authenticate. Check credentials in .env file")
        return

    # Get quotes
    print("\nFetching quotes...")
    quotes = client.get_quotes(top=20)
    print(f"Found {len(quotes)} quotes")

    if not quotes:
        print("No quotes found")
        return

    # Analyze line item patterns
    analysis = analyze_line_item_patterns(client, quotes)

    print("\n" + "="*80)
    print("ANALYSIS COMPLETE")
    print("="*80)


if __name__ == "__main__":
    main()
