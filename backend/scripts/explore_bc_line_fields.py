#!/usr/bin/env python3
"""
Explore BC API salesQuoteLine fields
"""

import sys
import os
from pathlib import Path

backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

from dotenv import load_dotenv
load_dotenv(backend_dir / ".env")

from app.integrations.bc.client import BusinessCentralClient

bc_client = BusinessCentralClient()


def main():
    print("Exploring BC salesQuoteLine fields...\n")

    # Get existing quotes to find one with lines
    quotes = bc_client.get_sales_quotes(top=5)
    print(f"Found {len(quotes)} quotes")

    for quote in quotes:
        quote_id = quote.get("id")
        quote_num = quote.get("number")

        try:
            lines = bc_client.get_quote_lines(quote_id)
            if lines:
                print(f"\nQuote {quote_num} has {len(lines)} lines")
                print("\nSample line fields:")
                sample = lines[0]
                for key, value in sample.items():
                    print(f"  {key}: {value}")
                return
        except Exception as e:
            print(f"  Error getting lines for {quote_num}: {e}")

    # If no existing lines, create a test quote and try different field names
    print("\nNo existing quote lines found. Testing field names...")

    quote = bc_client.create_sales_quote({
        "customerNumber": "CASH",
        "externalDocumentNumber": "FIELD-TEST"
    })
    quote_id = quote["id"]
    print(f"Created test quote: {quote.get('number')}")

    # Try different possible field names
    test_fields = [
        {"lineType": "Item", "lineObjectNumber": "SP11-23420-01", "quantity": 1},
        {"lineType": "Item", "itemNo": "SP11-23420-01", "quantity": 1},
        {"lineType": "Item", "number": "SP11-23420-01", "quantity": 1},
        {"lineType": "Item", "no": "SP11-23420-01", "quantity": 1},
    ]

    for line_data in test_fields:
        # Extract the field we're testing
        field_name = [k for k in line_data.keys() if k not in ["lineType", "quantity"]][0]
        try:
            result = bc_client.add_quote_line(quote_id, line_data)
            print(f"  [SUCCESS] Field '{field_name}' works!")
            print(f"    Result: {result}")
            return
        except Exception as e:
            error_msg = str(e)
            if "does not exist on type" in error_msg:
                print(f"  [X] '{field_name}' - property does not exist")
            elif "not found" in error_msg.lower():
                print(f"  [OK] '{field_name}' - accepted but item not found (field is valid!)")
                return
            else:
                print(f"  [?] '{field_name}' - {error_msg[:80]}")


if __name__ == "__main__":
    main()
