#!/usr/bin/env python3
"""
Live BC Quote Test - Actually creates quotes in Business Central

This script tests the complete flow:
1. Configure a door
2. Generate BC part numbers
3. Create a real quote in BC via API
4. Verify the quote exists

WARNING: This creates REAL quotes in BC. Use test customer if available.
"""

import sys
import json
import requests
from pathlib import Path

# API base URL
API_BASE = "http://localhost:8000"


def test_bc_connection():
    """Test BC API connectivity"""
    print("\n" + "="*60)
    print("TEST 1: BC Connection")
    print("="*60)

    try:
        resp = requests.get(f"{API_BASE}/api/bc/test-connection", timeout=30)
        if resp.status_code == 200:
            data = resp.json()
            print(f"  [OK] BC Connection: {data}")
            return True
        else:
            print(f"  [FAIL] BC Connection failed: {resp.status_code}")
            print(f"  Response: {resp.text}")
            return False
    except Exception as e:
        print(f"  [FAIL] BC Connection error: {e}")
        return False


def test_generate_quote_tx450():
    """Create a live BC quote for TX450 door"""
    print("\n" + "="*60)
    print("TEST 2: Create BC Quote - TX450 9'x7' White")
    print("="*60)

    payload = {
        "doors": [
            {
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
                    "bottomRetainer": True,
                    "shafts": True
                }
            }
        ],
        "poNumber": "TEST-LIVE-001",
        "tagName": "Live BC Test - TX450"
    }

    try:
        print("  Sending request to /api/door-config/generate-quote...")
        resp = requests.post(
            f"{API_BASE}/api/door-config/generate-quote",
            json=payload,
            timeout=60
        )

        if resp.status_code == 200:
            data = resp.json()
            print(f"  [OK] Quote created successfully!")
            print(f"\n  BC Quote Number: {data['data'].get('bc_quote_number', 'N/A')}")
            print(f"  BC Quote ID: {data['data'].get('bc_quote_id', 'N/A')}")
            print(f"  PO Number: {data['data'].get('po_number', 'N/A')}")
            print(f"  Total Parts: {data['data'].get('total_parts', 0)}")
            print(f"  Lines Added: {data['data'].get('lines_added', 0)}")

            if data['data'].get('lines_failed'):
                print(f"  Lines Failed: {len(data['data']['lines_failed'])}")
                for fail in data['data']['lines_failed']:
                    print(f"    - {fail['part_number']}: {fail['error']}")

            print(f"\n  Parts Summary:")
            for part in data['data'].get('parts_summary', [])[:10]:
                print(f"    - {part['part_number']}: {part.get('description', '')[:50]}... (Qty: {part['quantity']})")

            if len(data['data'].get('parts_summary', [])) > 10:
                print(f"    ... and {len(data['data']['parts_summary']) - 10} more parts")

            return data['data']
        else:
            print(f"  [FAIL] Quote creation failed: {resp.status_code}")
            print(f"  Response: {resp.text[:500]}")
            return None

    except Exception as e:
        print(f"  [FAIL] Error creating quote: {e}")
        return None


def test_generate_quote_kanata():
    """Create a live BC quote for KANATA residential door"""
    print("\n" + "="*60)
    print("TEST 3: Create BC Quote - KANATA 16'x7' White Sheridan")
    print("="*60)

    payload = {
        "doors": [
            {
                "doorType": "residential",
                "doorSeries": "KANATA",
                "doorWidth": 192,
                "doorHeight": 84,
                "doorCount": 1,
                "panelColor": "WHITE",
                "panelDesign": "SHXL",
                "trackRadius": "15",
                "trackThickness": "2",
                "hardware": {
                    "tracks": True,
                    "springs": True,
                    "struts": True,
                    "hardwareKits": True,
                    "weatherStripping": True,
                    "bottomRetainer": True,
                    "shafts": True
                }
            }
        ],
        "poNumber": "TEST-LIVE-002",
        "tagName": "Live BC Test - KANATA"
    }

    try:
        print("  Sending request to /api/door-config/generate-quote...")
        resp = requests.post(
            f"{API_BASE}/api/door-config/generate-quote",
            json=payload,
            timeout=60
        )

        if resp.status_code == 200:
            data = resp.json()
            print(f"  [OK] Quote created successfully!")
            print(f"\n  BC Quote Number: {data['data'].get('bc_quote_number', 'N/A')}")
            print(f"  BC Quote ID: {data['data'].get('bc_quote_id', 'N/A')}")
            print(f"  Lines Added: {data['data'].get('lines_added', 0)}")
            return data['data']
        else:
            print(f"  [FAIL] Quote creation failed: {resp.status_code}")
            print(f"  Response: {resp.text[:500]}")
            return None

    except Exception as e:
        print(f"  [FAIL] Error creating quote: {e}")
        return None


def test_multi_door_quote():
    """Create a BC quote with multiple doors"""
    print("\n" + "="*60)
    print("TEST 4: Create BC Quote - Multi-Door (2x TX450)")
    print("="*60)

    payload = {
        "doors": [
            {
                "doorType": "commercial",
                "doorSeries": "TX450",
                "doorWidth": 108,
                "doorHeight": 84,
                "doorCount": 2,
                "panelColor": "WHITE",
                "panelDesign": "UDC",
                "trackRadius": "15",
                "trackThickness": "2",
                "hardware": {
                    "tracks": True,
                    "springs": True,
                    "struts": True
                }
            },
            {
                "doorType": "commercial",
                "doorSeries": "TX450",
                "doorWidth": 192,
                "doorHeight": 96,
                "doorCount": 1,
                "panelColor": "WHITE",
                "panelDesign": "UDC",
                "trackRadius": "15",
                "trackThickness": "3",
                "hardware": {
                    "tracks": True,
                    "springs": True,
                    "struts": True
                }
            }
        ],
        "poNumber": "TEST-LIVE-003",
        "tagName": "Live BC Test - Multi-Door"
    }

    try:
        print("  Sending request with 2 door configs (3 total doors)...")
        resp = requests.post(
            f"{API_BASE}/api/door-config/generate-quote",
            json=payload,
            timeout=60
        )

        if resp.status_code == 200:
            data = resp.json()
            print(f"  [OK] Multi-door quote created!")
            print(f"\n  BC Quote Number: {data['data'].get('bc_quote_number', 'N/A')}")
            print(f"  Total Doors: {data['data'].get('total_doors', 0)}")
            print(f"  Total Parts: {data['data'].get('total_parts', 0)}")
            print(f"  Lines Added: {data['data'].get('lines_added', 0)}")
            return data['data']
        else:
            print(f"  [FAIL] Multi-door quote failed: {resp.status_code}")
            print(f"  Response: {resp.text[:500]}")
            return None

    except Exception as e:
        print(f"  [FAIL] Error: {e}")
        return None


def verify_quote_in_bc(quote_id):
    """Verify the quote exists in BC"""
    print("\n" + "="*60)
    print(f"TEST 5: Verify Quote in BC (ID: {quote_id})")
    print("="*60)

    try:
        resp = requests.get(
            f"{API_BASE}/api/bc/quotes/{quote_id}",
            timeout=30
        )

        if resp.status_code == 200:
            data = resp.json()
            print(f"  [OK] Quote found in BC!")
            print(f"  Quote Number: {data.get('number', 'N/A')}")
            print(f"  Customer: {data.get('customerName', 'N/A')}")
            print(f"  Status: {data.get('status', 'N/A')}")
            return True
        else:
            print(f"  [WARN] Could not verify quote: {resp.status_code}")
            return False

    except Exception as e:
        print(f"  [WARN] Verification error: {e}")
        return False


def main():
    print("="*60)
    print("LIVE BC QUOTE CREATION TEST")
    print("="*60)
    print("\nWARNING: This creates REAL quotes in Business Central!")
    print("         Quotes can be deleted manually if needed.\n")

    results = {
        "bc_connection": False,
        "tx450_quote": None,
        "kanata_quote": None,
        "multi_door_quote": None
    }

    # Test 1: BC Connection
    results["bc_connection"] = test_bc_connection()

    if not results["bc_connection"]:
        print("\n[ABORT] BC connection failed. Cannot proceed with live tests.")
        print("        Check BC credentials in .env file.")
        return 1

    # Test 2: TX450 Quote
    results["tx450_quote"] = test_generate_quote_tx450()

    # Test 3: KANATA Quote
    results["kanata_quote"] = test_generate_quote_kanata()

    # Test 4: Multi-door Quote
    results["multi_door_quote"] = test_multi_door_quote()

    # Test 5: Verify first quote in BC
    if results["tx450_quote"] and results["tx450_quote"].get("bc_quote_id"):
        verify_quote_in_bc(results["tx450_quote"]["bc_quote_id"])

    # Summary
    print("\n" + "="*60)
    print("TEST SUMMARY")
    print("="*60)

    quotes_created = []
    if results["tx450_quote"]:
        quotes_created.append(f"TX450: {results['tx450_quote'].get('bc_quote_number', 'N/A')}")
    if results["kanata_quote"]:
        quotes_created.append(f"KANATA: {results['kanata_quote'].get('bc_quote_number', 'N/A')}")
    if results["multi_door_quote"]:
        quotes_created.append(f"Multi-Door: {results['multi_door_quote'].get('bc_quote_number', 'N/A')}")

    print(f"\n  BC Connection: {'[OK]' if results['bc_connection'] else '[FAIL]'}")
    print(f"  Quotes Created: {len(quotes_created)}")
    for q in quotes_created:
        print(f"    - {q}")

    if quotes_created:
        print(f"\n  [SUCCESS] Live BC integration working!")
        print(f"  Check Business Central to see the created quotes.")
        return 0
    else:
        print(f"\n  [FAIL] No quotes were created.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
