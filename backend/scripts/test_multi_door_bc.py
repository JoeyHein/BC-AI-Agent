#!/usr/bin/env python3
"""
Multi-Door BC Quote Test - Tests creating a quote with multiple door configurations
"""

import sys
from pathlib import Path

backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

from dotenv import load_dotenv
load_dotenv(backend_dir / ".env")

from app.integrations.bc.client import BusinessCentralClient
from app.services.part_number_service import get_parts_for_door_config

bc_client = BusinessCentralClient()


def main():
    print("=" * 60)
    print("MULTI-DOOR BC QUOTE TEST")
    print("=" * 60)

    # Define multiple door configurations
    doors = [
        {
            "name": "TX450 9'x7' White",
            "config": {
                "doorType": "commercial",
                "doorSeries": "TX450",
                "doorWidth": 108,
                "doorHeight": 84,
                "doorCount": 2,  # 2 of these
                "panelColor": "WHITE",
                "panelDesign": "UDC",
                "trackRadius": "15",
                "trackThickness": "2",
                "hardware": {"tracks": True, "springs": True, "struts": True}
            }
        },
        {
            "name": "KANATA 16'x7' White Sheridan",
            "config": {
                "doorType": "residential",
                "doorSeries": "KANATA",
                "doorWidth": 192,
                "doorHeight": 84,
                "doorCount": 1,
                "panelColor": "WHITE",
                "panelDesign": "SHXL",
                "trackRadius": "15",
                "trackThickness": "2",
                "hardware": {"tracks": True, "springs": True, "struts": True, "weatherStripping": True}
            }
        }
    ]

    # Step 1: Collect all parts
    print("\n[STEP 1] Collecting parts for all doors...")
    all_parts = []
    for door in doors:
        parts_result = get_parts_for_door_config(door["config"])
        parts = parts_result.get("parts_list", [])
        print(f"  {door['name']}: {len(parts)} parts")
        all_parts.extend(parts)

    # Consolidate duplicate parts
    consolidated = {}
    for part in all_parts:
        pn = part["part_number"]
        if pn in consolidated:
            consolidated[pn]["quantity"] += part["quantity"]
        else:
            consolidated[pn] = part.copy()

    print(f"\n  Total unique parts: {len(consolidated)}")
    print(f"  Total line items before consolidation: {len(all_parts)}")

    # Step 2: Create BC Quote
    print("\n[STEP 2] Creating BC Quote...")
    try:
        quote_data = {
            "customerNumber": "CASH",
            "externalDocumentNumber": "MULTI-DOOR-TEST"
        }
        bc_quote = bc_client.create_sales_quote(quote_data)
        quote_id = bc_quote.get("id")
        quote_number = bc_quote.get("number")
        print(f"  [OK] Created quote: {quote_number}")
    except Exception as e:
        print(f"  [FAIL] Quote creation failed: {e}")
        return 1

    # Step 3: Add all line items
    print("\n[STEP 3] Adding line items...")
    lines_added = 0
    lines_failed = 0

    for part in consolidated.values():
        try:
            line_data = {
                "lineType": "Item",
                "lineObjectNumber": part["part_number"],
                "description": part.get("description", "")[:100],
                "quantity": part["quantity"],
            }
            bc_client.add_quote_line(quote_id, line_data)
            lines_added += 1
        except Exception as e:
            lines_failed += 1
            # Only print first few failures
            if lines_failed <= 3:
                print(f"    [SKIP] {part['part_number']} - Item not in BC")

    if lines_failed > 3:
        print(f"    ... and {lines_failed - 3} more items not in BC")

    # Step 4: Verify quote lines
    print("\n[STEP 4] Verifying quote lines in BC...")
    try:
        lines = bc_client.get_quote_lines(quote_id)
        print(f"  Quote has {len(lines)} lines in BC")

        # Show first few lines
        for line in lines[:5]:
            item_no = line.get("lineObjectNumber", "")
            desc = line.get("description", "")[:40]
            qty = line.get("quantity", 0)
            print(f"    - {item_no}: {desc}... (Qty: {qty})")
        if len(lines) > 5:
            print(f"    ... and {len(lines) - 5} more lines")
    except Exception as e:
        print(f"  [WARN] Could not verify lines: {e}")

    # Summary
    print("\n" + "=" * 60)
    print("RESULTS")
    print("=" * 60)
    print(f"  Quote Number: {quote_number}")
    print(f"  Doors: {sum(d['config']['doorCount'] for d in doors)} total")
    print(f"  Lines Added: {lines_added}")
    print(f"  Lines Failed: {lines_failed} (items not in BC inventory)")

    if lines_added > 0:
        print(f"\n  [SUCCESS] Multi-door quote created!")
        return 0
    else:
        print(f"\n  [FAIL] No lines added")
        return 1


if __name__ == "__main__":
    sys.exit(main())
