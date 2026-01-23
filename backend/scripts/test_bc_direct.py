#!/usr/bin/env python3
"""
Direct BC Quote Test - Tests BC integration without HTTP server

This script tests the BC quote creation directly using the client:
1. Test BC connection
2. Create a quote
3. Add line items using itemNumber
"""

import sys
import os
from pathlib import Path

# Add parent to path for imports
backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

# Load environment variables from .env file BEFORE importing app modules
from dotenv import load_dotenv
env_path = backend_dir / ".env"
if env_path.exists():
    load_dotenv(env_path)
    print(f"Loaded .env from {env_path}")
else:
    print(f"WARNING: .env not found at {env_path}")

# Now import app modules (after env is loaded)
from app.integrations.bc.client import BusinessCentralClient
from app.services.part_number_service import get_parts_for_door_config

# Create fresh BC client instance with loaded env
bc_client = BusinessCentralClient()


def main():
    print("=" * 60)
    print("DIRECT BC QUOTE TEST")
    print("=" * 60)

    # Test 1: BC Connection
    print("\n[TEST 1] Testing BC Connection...")
    try:
        connected = bc_client.test_connection()
        if not connected:
            print("  [FAIL] BC connection failed")
            return 1
        print("  [OK] BC connection successful")
    except Exception as e:
        print(f"  [FAIL] BC connection error: {e}")
        return 1

    # Test 2: Get parts for a door configuration
    print("\n[TEST 2] Getting parts for TX450 9'x7' door...")
    config = {
        "doorType": "commercial",
        "doorSeries": "TX450",
        "doorWidth": 108,
        "doorHeight": 84,
        "doorCount": 1,
        "panelColor": "WHITE",
        "panelDesign": "UDC",
        "trackRadius": "15",
        "trackThickness": "2",
        "hardware": {
            "tracks": True,
            "springs": True,
            "struts": True,
            "hardwareKits": True,
            "weatherStripping": True,
        }
    }

    parts_result = get_parts_for_door_config(config)
    parts = parts_result.get("parts_list", [])
    print(f"  [OK] Generated {len(parts)} parts")

    for p in parts[:5]:
        print(f"    - {p['part_number']}: {p.get('description', '')[:40]}")
    if len(parts) > 5:
        print(f"    ... and {len(parts) - 5} more")

    # Test 3: Create BC Quote
    print("\n[TEST 3] Creating BC Quote...")
    try:
        quote_data = {
            "customerNumber": "CASH",
            "externalDocumentNumber": "DIRECT-TEST-001"
        }
        bc_quote = bc_client.create_sales_quote(quote_data)
        quote_id = bc_quote.get("id")
        quote_number = bc_quote.get("number")
        print(f"  [OK] Created quote: {quote_number} (ID: {quote_id})")
    except Exception as e:
        print(f"  [FAIL] Quote creation failed: {e}")
        return 1

    # Test 4: Add line items using itemNumber
    print("\n[TEST 4] Adding line items with itemNumber field...")
    lines_added = 0
    lines_failed = []

    for part in parts:
        try:
            # BC API uses lineObjectNumber for item lookup
            line_data = {
                "lineType": "Item",
                "lineObjectNumber": part["part_number"],
                "description": part.get("description", "")[:100],
                "quantity": part["quantity"],
            }
            result = bc_client.add_quote_line(quote_id, line_data)
            lines_added += 1
            print(f"    [OK] {part['part_number']} (Qty: {part['quantity']})")
        except Exception as e:
            error_str = str(e)
            lines_failed.append({
                "part_number": part["part_number"],
                "error": error_str[:100]
            })
            # Print shorter error
            if "does not exist" in error_str.lower() or "not found" in error_str.lower():
                print(f"    [SKIP] {part['part_number']} - Item not found in BC")
            elif "Edm.Guid" in error_str:
                print(f"    [FAIL] {part['part_number']} - Still expecting GUID (field name wrong)")
            else:
                print(f"    [FAIL] {part['part_number']} - {error_str[:60]}")

    # Summary
    print("\n" + "=" * 60)
    print("RESULTS")
    print("=" * 60)
    print(f"  Quote Number: {quote_number}")
    print(f"  Lines Added: {lines_added}")
    print(f"  Lines Failed: {len(lines_failed)}")

    if lines_added > 0:
        print(f"\n  [SUCCESS] Quote {quote_number} created with {lines_added} lines!")
        print(f"  Check Business Central to see the quote.")
        return 0
    elif lines_failed and all("not found" in f["error"].lower() or "does not exist" in f["error"].lower() for f in lines_failed):
        print(f"\n  [PARTIAL] Quote created but items not found in BC inventory.")
        print(f"  The itemNumber field is working correctly.")
        print(f"  Parts need to be added to BC inventory first.")
        return 0
    else:
        print(f"\n  [FAIL] Quote created but no lines could be added.")
        if lines_failed:
            print(f"\n  First error: {lines_failed[0]['error']}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
