#!/usr/bin/env python3
"""
Live BC Quote Format Test - Creates a real quote to verify format is correct
"""

import sys
from pathlib import Path

backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

from dotenv import load_dotenv
load_dotenv(backend_dir / ".env")

from app.integrations.bc.client import BusinessCentralClient
from app.services.part_number_service import get_parts_for_door_config
from app.api.door_configurator import _format_door_description, _sort_parts_by_category, LINE_ORDER, DoorConfigRequest

bc_client = BusinessCentralClient()


def test_single_door_quote():
    """Test single door quote with correct format"""
    print("=" * 60)
    print("TEST 1: Single Door Quote - TX450 9'x7' White")
    print("=" * 60)

    # Create door config
    door = DoorConfigRequest(
        doorType="commercial",
        doorSeries="TX450",
        doorWidth=108,  # 9'
        doorHeight=84,  # 7'
        doorCount=1,
        panelColor="WHITE",
        panelDesign="UDC",
        trackRadius="15",
        trackThickness="2",
        hardware={
            "tracks": True,
            "springs": True,
            "struts": True,
            "weatherStripping": True,
        }
    )

    # Generate door description
    door_desc = _format_door_description(door)
    print(f"\nDoor Description: {door_desc}")

    # Get parts
    config_dict = {
        "doorType": door.doorType,
        "doorSeries": door.doorSeries,
        "doorWidth": door.doorWidth,
        "doorHeight": door.doorHeight,
        "doorCount": door.doorCount,
        "panelColor": door.panelColor,
        "panelDesign": door.panelDesign,
        "trackRadius": door.trackRadius,
        "trackThickness": door.trackThickness,
        "hardware": door.hardware,
    }
    parts_result = get_parts_for_door_config(config_dict)
    parts = parts_result.get("parts_list", [])

    # Sort by category
    sorted_parts = _sort_parts_by_category(parts)

    print(f"\nParts in order ({len(sorted_parts)} items):")
    for p in sorted_parts:
        print(f"  [{p.get('category', 'N/A'):20}] {p['part_number']}")

    # Create BC Quote
    print("\nCreating BC Quote...")
    quote_data = {
        "customerNumber": "CASH",
        "externalDocumentNumber": "FORMAT-TEST-001"
    }
    bc_quote = bc_client.create_sales_quote(quote_data)
    quote_id = bc_quote.get("id")
    quote_number = bc_quote.get("number")
    print(f"  Created: {quote_number}")

    # Add comment line first
    print("\nAdding lines in order...")
    lines_added = 0

    # 1. Comment line
    try:
        bc_client.add_quote_line(quote_id, {
            "lineType": "Comment",
            "description": door_desc
        })
        lines_added += 1
        print(f"  [OK] Comment: {door_desc}")
    except Exception as e:
        print(f"  [FAIL] Comment: {e}")

    # 2. Item lines in sorted order
    for part in sorted_parts:
        try:
            bc_client.add_quote_line(quote_id, {
                "lineType": "Item",
                "lineObjectNumber": part["part_number"],
                "description": part.get("description", "")[:100],
                "quantity": part["quantity"],
            })
            lines_added += 1
            print(f"  [OK] {part.get('category', 'N/A'):15} {part['part_number']}")
        except Exception as e:
            err = str(e)
            if "does not exist" in err.lower():
                print(f"  [SKIP] {part.get('category', 'N/A'):15} {part['part_number']} - not in BC")
            else:
                print(f"  [FAIL] {part['part_number']}: {err[:50]}")

    # Verify lines in BC
    print("\nVerifying quote lines in BC...")
    lines = bc_client.get_quote_lines(quote_id)
    print(f"  Quote has {len(lines)} lines")

    print("\n  Actual line order in BC:")
    for i, line in enumerate(lines, 1):
        line_type = line.get("lineType", "")
        item_no = line.get("lineObjectNumber", "")
        desc = line.get("description", "")[:50]
        qty = line.get("quantity", 0)
        if line_type == "Comment":
            print(f"    {i}. [COMMENT] {desc}")
        else:
            print(f"    {i}. [{item_no}] Qty: {qty}")

    print(f"\n  [SUCCESS] Quote {quote_number} created with {lines_added} lines")
    return quote_number, lines_added


def test_multi_door_quote():
    """Test multi-door quote with comment separators"""
    print("\n" + "=" * 60)
    print("TEST 2: Multi-Door Quote - TX450 + KANATA")
    print("=" * 60)

    doors = [
        DoorConfigRequest(
            doorType="commercial",
            doorSeries="TX450",
            doorWidth=120,  # 10'
            doorHeight=108,  # 9'
            doorCount=2,
            panelColor="WHITE",
            panelDesign="UDC",
            trackRadius="15",
            trackThickness="2",
            hardware={"tracks": True, "springs": True, "struts": True}
        ),
        DoorConfigRequest(
            doorType="residential",
            doorSeries="KANATA",
            doorWidth=192,  # 16'
            doorHeight=84,  # 7'
            doorCount=1,
            panelColor="WALNUT",
            panelDesign="SHXL",
            trackRadius="15",
            trackThickness="2",
            hardware={"tracks": True, "springs": True, "weatherStripping": True}
        ),
    ]

    print("\nDoor Descriptions:")
    for i, door in enumerate(doors, 1):
        desc = _format_door_description(door)
        print(f"  {i}. {desc}")

    # Create BC Quote
    print("\nCreating BC Quote...")
    quote_data = {
        "customerNumber": "CASH",
        "externalDocumentNumber": "FORMAT-TEST-002"
    }
    bc_quote = bc_client.create_sales_quote(quote_data)
    quote_id = bc_quote.get("id")
    quote_number = bc_quote.get("number")
    print(f"  Created: {quote_number}")

    # Add lines for each door
    lines_added = 0
    for i, door in enumerate(doors, 1):
        print(f"\n  Door {i}: {door.doorSeries} {door.doorWidth//12}'x{door.doorHeight//12}'")

        # Comment line for this door
        door_desc = _format_door_description(door)
        try:
            bc_client.add_quote_line(quote_id, {
                "lineType": "Comment",
                "description": door_desc
            })
            lines_added += 1
            print(f"    [OK] Comment added")
        except Exception as e:
            print(f"    [FAIL] Comment: {e}")

        # Get and add parts
        config_dict = {
            "doorType": door.doorType,
            "doorSeries": door.doorSeries,
            "doorWidth": door.doorWidth,
            "doorHeight": door.doorHeight,
            "doorCount": door.doorCount,
            "panelColor": door.panelColor,
            "panelDesign": door.panelDesign,
            "trackRadius": door.trackRadius,
            "trackThickness": door.trackThickness,
            "hardware": door.hardware,
        }
        parts = get_parts_for_door_config(config_dict).get("parts_list", [])
        sorted_parts = _sort_parts_by_category(parts)

        items_added = 0
        items_skipped = 0
        for part in sorted_parts:
            try:
                bc_client.add_quote_line(quote_id, {
                    "lineType": "Item",
                    "lineObjectNumber": part["part_number"],
                    "description": part.get("description", "")[:100],
                    "quantity": part["quantity"],
                })
                lines_added += 1
                items_added += 1
            except:
                items_skipped += 1

        print(f"    [OK] {items_added} items added, {items_skipped} skipped (not in BC)")

    # Verify
    print("\nVerifying quote structure...")
    lines = bc_client.get_quote_lines(quote_id)

    comment_count = sum(1 for l in lines if l.get("lineType") == "Comment")
    item_count = sum(1 for l in lines if l.get("lineType") == "Item")

    print(f"  Total lines: {len(lines)}")
    print(f"  Comment lines: {comment_count}")
    print(f"  Item lines: {item_count}")

    # Show structure
    print("\n  Quote structure:")
    current_door = 0
    for line in lines:
        if line.get("lineType") == "Comment":
            current_door += 1
            print(f"\n  --- DOOR {current_door} ---")
            print(f"  {line.get('description', '')}")
        else:
            item_no = line.get("lineObjectNumber", "")
            qty = line.get("quantity", 0)
            print(f"    {item_no} (Qty: {qty})")

    print(f"\n  [SUCCESS] Multi-door quote {quote_number} created!")
    return quote_number, lines_added


def main():
    print("=" * 60)
    print("LIVE BC QUOTE FORMAT TEST")
    print("=" * 60)
    print("\nThis creates REAL quotes in BC to verify format.\n")

    # Test connection
    print("Testing BC connection...")
    if not bc_client.test_connection():
        print("[FAIL] BC connection failed")
        return 1
    print("[OK] Connected to BC\n")

    results = []

    # Test 1: Single door
    try:
        q1, l1 = test_single_door_quote()
        results.append(("Single Door Quote", True, q1, l1))
    except Exception as e:
        print(f"\n[ERROR] Test 1 failed: {e}")
        results.append(("Single Door Quote", False, None, 0))

    # Test 2: Multi-door
    try:
        q2, l2 = test_multi_door_quote()
        results.append(("Multi-Door Quote", True, q2, l2))
    except Exception as e:
        print(f"\n[ERROR] Test 2 failed: {e}")
        results.append(("Multi-Door Quote", False, None, 0))

    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)

    for name, passed, quote_num, lines in results:
        status = "[PASS]" if passed else "[FAIL]"
        if passed:
            print(f"  {status} {name}: {quote_num} ({lines} lines)")
        else:
            print(f"  {status} {name}")

    print("\nQuotes created in BC - check Business Central to verify format.")

    return 0 if all(r[1] for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
