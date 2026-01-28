"""
Fetch all hardware box items from Business Central
Queries for HK* and HW* items to discover available part numbers
"""

import sys
import os
import json
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.integrations.bc.client import BusinessCentralClient
from app.config import settings

def fetch_items_by_prefix(client: BusinessCentralClient, prefix: str, max_items: int = 1000) -> list:
    """Fetch items starting with a given prefix using OData filter"""
    cid = client.company_id

    # Use OData startswith filter
    filter_query = f"startswith(number,'{prefix}')"

    all_items = []
    skip = 0
    batch_size = 100

    while len(all_items) < max_items:
        try:
            result = client._make_request(
                "GET",
                f"companies({cid})/items?$filter={filter_query}&$top={batch_size}&$skip={skip}&$orderby=number"
            )
            items = result.get("value", [])
            if not items:
                break
            all_items.extend(items)
            skip += batch_size
            print(f"  Fetched {len(all_items)} items with prefix '{prefix}'...")

            # Check if we've reached the end
            if len(items) < batch_size:
                break
        except Exception as e:
            print(f"  Error fetching items: {e}")
            break

    return all_items

def analyze_hardware_patterns(items: list, prefix: str) -> dict:
    """Analyze part number patterns from fetched items"""
    patterns = {}

    for item in items:
        number = item.get("number", "")
        display_name = item.get("displayName", "")
        unit_price = item.get("unitPrice", 0)

        # Extract pattern components
        parts = number.split("-")
        if len(parts) >= 1:
            pattern_prefix = parts[0]
            if pattern_prefix not in patterns:
                patterns[pattern_prefix] = []

            patterns[pattern_prefix].append({
                "number": number,
                "displayName": display_name,
                "unitPrice": unit_price,
                "parts": parts
            })

    return patterns

def main():
    print("=" * 60)
    print("Fetching Hardware Items from Business Central")
    print("=" * 60)

    # Initialize BC client
    client = BusinessCentralClient()

    # Fetch HK* items (hardware kits and boxes)
    print("\n1. Fetching HK* items (hardware kits/boxes)...")
    hk_items = fetch_items_by_prefix(client, "HK")
    print(f"   Total HK items found: {len(hk_items)}")

    # Fetch HW* items (commercial hardware)
    print("\n2. Fetching HW* items (commercial hardware boxes)...")
    hw_items = fetch_items_by_prefix(client, "HW")
    print(f"   Total HW items found: {len(hw_items)}")

    # Analyze patterns
    print("\n3. Analyzing part number patterns...")
    hk_patterns = analyze_hardware_patterns(hk_items, "HK")
    hw_patterns = analyze_hardware_patterns(hw_items, "HW")

    # Print HK patterns summary
    print("\n" + "=" * 60)
    print("HK HARDWARE PATTERNS")
    print("=" * 60)
    for prefix, items in sorted(hk_patterns.items()):
        print(f"\n{prefix} ({len(items)} items):")
        for item in sorted(items, key=lambda x: x["number"])[:10]:  # Show first 10
            print(f"  {item['number']:25} - {item['displayName'][:40]:40} ${item['unitPrice']:.2f}")
        if len(items) > 10:
            print(f"  ... and {len(items) - 10} more")

    # Print HW patterns summary
    print("\n" + "=" * 60)
    print("HW COMMERCIAL HARDWARE PATTERNS")
    print("=" * 60)
    for prefix, items in sorted(hw_patterns.items()):
        print(f"\n{prefix} ({len(items)} items):")
        for item in sorted(items, key=lambda x: x["number"])[:10]:  # Show first 10
            print(f"  {item['number']:25} - {item['displayName'][:40]:40} ${item['unitPrice']:.2f}")
        if len(items) > 10:
            print(f"  ... and {len(items) - 10} more")

    # Save full results to JSON for analysis
    output_dir = Path(__file__).parent.parent / "data" / "bc_analysis"
    output_dir.mkdir(parents=True, exist_ok=True)

    output_file = output_dir / "hardware_boxes_from_bc.json"

    result = {
        "hk_items": [{"number": i["number"], "displayName": i["displayName"], "unitPrice": i["unitPrice"]} for i in hk_items],
        "hw_items": [{"number": i["number"], "displayName": i["displayName"], "unitPrice": i["unitPrice"]} for i in hw_items],
        "hk_patterns": {k: [{"number": i["number"], "displayName": i["displayName"], "unitPrice": i["unitPrice"]} for i in v] for k, v in hk_patterns.items()},
        "hw_patterns": {k: [{"number": i["number"], "displayName": i["displayName"], "unitPrice": i["unitPrice"]} for i in v] for k, v in hw_patterns.items()},
        "summary": {
            "total_hk_items": len(hk_items),
            "total_hw_items": len(hw_items),
            "hk_prefixes": list(hk_patterns.keys()),
            "hw_prefixes": list(hw_patterns.keys())
        }
    }

    with open(output_file, "w") as f:
        json.dump(result, f, indent=2)

    print(f"\n\nFull results saved to: {output_file}")

    # Print detailed pattern analysis
    print("\n" + "=" * 60)
    print("DETAILED PATTERN ANALYSIS")
    print("=" * 60)

    # Analyze HK10 pattern (residential hardware boxes)
    if "HK10" in hk_patterns:
        print("\nHK10 (Residential 2\" Track Hardware Boxes):")
        hk10_items = hk_patterns["HK10"]
        print(f"  Found {len(hk10_items)} items")
        # Group by pattern structure
        for item in sorted(hk10_items, key=lambda x: x["number"]):
            parts = item["number"].split("-")
            if len(parts) >= 3:
                print(f"    {item['number']} -> height/section: {parts[1]}, width: {parts[2]}")

    # Analyze HK02, HK03, etc. patterns
    for prefix in ["HK02", "HK03", "HK12", "HK13", "HK22", "HK23", "HK32", "HK33"]:
        if prefix in hk_patterns:
            print(f"\n{prefix} (Extended Hardware Boxes):")
            items = hk_patterns[prefix]
            print(f"  Found {len(items)} items")
            for item in sorted(items, key=lambda x: x["number"]):
                print(f"    {item['number']} - {item['displayName']}")

    # Analyze complete kits (HK01-HK06)
    for prefix in ["HK01", "HK02", "HK03", "HK04", "HK05", "HK06"]:
        if prefix in hk_patterns:
            items = hk_patterns[prefix]
            # Check if these are complete kits (format HKnn-00000-XX)
            complete_kits = [i for i in items if "00000" in i["number"]]
            if complete_kits:
                print(f"\n{prefix} Complete Kits:")
                for item in sorted(complete_kits, key=lambda x: x["number"]):
                    print(f"    {item['number']} - {item['displayName']} ${item['unitPrice']:.2f}")

if __name__ == "__main__":
    main()
