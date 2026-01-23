"""
Analyze BC Quote Patterns
Discover part number patterns from existing quotes in Business Central
"""

import sys
from pathlib import Path
from collections import defaultdict
import json
import re

# Add backend to path
backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

from app.integrations.bc.client import bc_client


def analyze_part_number(part_number: str) -> dict:
    """Analyze a part number to extract its components"""
    analysis = {
        "original": part_number,
        "prefix": None,
        "series": None,
        "size_code": None,
        "color_code": None,
        "variant": None,
        "category": "unknown"
    }

    if not part_number:
        return analysis

    # Clean the part number
    pn = part_number.upper().strip()
    analysis["original"] = pn

    # Extract prefix (first 2-3 characters before dash or number)
    prefix_match = re.match(r'^([A-Z]{2,4})[-\s]?', pn)
    if prefix_match:
        analysis["prefix"] = prefix_match.group(1)

    # Categorize based on prefix
    prefix_categories = {
        "PN": "panel",
        "GK": "glass_kit",
        "TR": "track",
        "HK": "hardware_kit",
        "HW": "hardware",
        "SH": "shaft",
        "SP": "spring",
        "PL": "seal",
        "OP": "operator",
        "FH": "strut",
        "AL": "aluminum",
        "TX": "door_package",
        "SB": "door_package",
    }

    for prefix, category in prefix_categories.items():
        if pn.startswith(prefix):
            analysis["prefix"] = prefix
            analysis["category"] = category
            break

    # Check for door package patterns (TX450-WWHH-CC)
    door_match = re.match(r'^(TX[45]00|SB\d+)-(\d{4})-(\d{2})$', pn)
    if door_match:
        analysis["series"] = door_match.group(1)
        analysis["size_code"] = door_match.group(2)
        analysis["variant"] = door_match.group(3)
        analysis["category"] = "door_package"

    # Check for simpler door patterns
    door_match2 = re.match(r'^(TX[45]00|AL\d+|KANATA|CRAFT)-(.+)$', pn)
    if door_match2:
        analysis["series"] = door_match2.group(1)

    return analysis


def main():
    print("=" * 80)
    print("BC QUOTE PATTERN ANALYSIS")
    print("Discovering part number patterns from existing quotes")
    print("=" * 80)

    # Test connection
    if not bc_client.test_connection():
        print("Failed to connect to BC. Check credentials.")
        return

    # Get all quotes
    print("\n1. Fetching sales quotes from BC...")
    quotes = bc_client.get_sales_quotes(top=500)
    print(f"   Found {len(quotes)} quotes")

    # Analyze quote lines
    all_items = []
    part_patterns = defaultdict(list)
    series_items = defaultdict(lambda: defaultdict(list))
    prefix_counts = defaultdict(int)
    category_items = defaultdict(list)

    print("\n2. Analyzing quote line items...")
    for i, quote in enumerate(quotes):
        quote_id = quote.get("id")
        quote_number = quote.get("number", "N/A")

        try:
            lines = bc_client.get_quote_lines(quote_id)
            for line in lines:
                item_number = line.get("itemId") or line.get("number") or ""
                description = line.get("description", "")
                quantity = line.get("quantity", 0)
                unit_price = line.get("unitPrice", 0)

                if not item_number:
                    continue

                # Analyze the part number
                analysis = analyze_part_number(item_number)

                item_data = {
                    "part_number": item_number,
                    "description": description,
                    "quantity": quantity,
                    "unit_price": unit_price,
                    "quote_number": quote_number,
                    "analysis": analysis
                }

                all_items.append(item_data)

                # Group by prefix
                if analysis["prefix"]:
                    prefix_counts[analysis["prefix"]] += 1

                # Group by category
                category_items[analysis["category"]].append(item_data)

                # Group by series
                if analysis["series"]:
                    series_items[analysis["series"]][analysis["category"]].append(item_data)

        except Exception as e:
            pass  # Skip quotes with errors

        if (i + 1) % 50 == 0:
            print(f"   Processed {i + 1}/{len(quotes)} quotes...")

    print(f"   Found {len(all_items)} line items total")

    # Print analysis
    print("\n" + "=" * 80)
    print("PART NUMBER PATTERNS")
    print("=" * 80)

    print("\n3. PREFIXES BY FREQUENCY:")
    print("-" * 40)
    for prefix, count in sorted(prefix_counts.items(), key=lambda x: -x[1])[:20]:
        print(f"   {prefix:10} {count:6} items")

    print("\n4. ITEMS BY CATEGORY:")
    print("-" * 40)
    for category, items in sorted(category_items.items(), key=lambda x: -len(x[1])):
        print(f"\n   {category.upper()} ({len(items)} items)")
        # Show unique part numbers
        unique_pns = set(i["part_number"] for i in items)
        for pn in sorted(unique_pns)[:10]:
            # Find one item with this PN for description
            item = next(i for i in items if i["part_number"] == pn)
            print(f"      {pn:30} {item['description'][:40]}")
        if len(unique_pns) > 10:
            print(f"      ... and {len(unique_pns) - 10} more unique part numbers")

    print("\n5. DOOR PACKAGE PATTERNS:")
    print("-" * 40)
    for series, categories in series_items.items():
        print(f"\n   {series}:")
        for category, items in categories.items():
            unique_pns = set(i["part_number"] for i in items)
            print(f"      {category}: {len(unique_pns)} unique part numbers")
            for pn in sorted(unique_pns)[:5]:
                item = next(i for i in items if i["part_number"] == pn)
                print(f"         {pn:25} {item['description'][:35]}")

    # Extract patterns for each component type
    print("\n6. PATTERN EXTRACTION:")
    print("-" * 40)

    patterns = {
        "panels": [],
        "tracks": [],
        "hardware": [],
        "springs": [],
        "windows": [],
        "other": []
    }

    for item in all_items:
        pn = item["part_number"]
        cat = item["analysis"]["category"]

        if cat == "panel":
            patterns["panels"].append(pn)
        elif cat == "track":
            patterns["tracks"].append(pn)
        elif cat in ["hardware", "hardware_kit"]:
            patterns["hardware"].append(pn)
        elif cat == "spring":
            patterns["springs"].append(pn)
        elif cat == "glass_kit":
            patterns["windows"].append(pn)

    for cat_name, pns in patterns.items():
        if pns:
            unique = sorted(set(pns))
            print(f"\n   {cat_name.upper()} ({len(unique)} unique):")
            for pn in unique[:15]:
                print(f"      {pn}")
            if len(unique) > 15:
                print(f"      ... and {len(unique) - 15} more")

    # Save detailed results
    print("\n7. SAVING DETAILED RESULTS...")
    results = {
        "summary": {
            "total_quotes": len(quotes),
            "total_line_items": len(all_items),
            "unique_part_numbers": len(set(i["part_number"] for i in all_items)),
            "prefix_counts": dict(prefix_counts),
        },
        "by_category": {
            cat: [{"part_number": i["part_number"], "description": i["description"]}
                  for i in items[:50]]  # Limit to 50 per category
            for cat, items in category_items.items()
        },
        "door_series": {
            series: {cat: list(set(i["part_number"] for i in items))
                    for cat, items in categories.items()}
            for series, categories in series_items.items()
        },
        "all_unique_part_numbers": sorted(set(i["part_number"] for i in all_items))
    }

    output_file = backend_dir / "bc_quote_patterns.json"
    with open(output_file, "w") as f:
        json.dump(results, f, indent=2)
    print(f"   Saved to {output_file}")

    # Print recommendations for part number service
    print("\n" + "=" * 80)
    print("RECOMMENDATIONS FOR PART NUMBER SERVICE")
    print("=" * 80)

    print("""
Based on the analysis, update the part_number_service.py with these patterns:

1. PANEL PATTERNS:
   - Look for PN- prefix items
   - Extract size/color codes from the patterns found

2. TRACK PATTERNS:
   - Look for TR- prefix items
   - Map to track radius and thickness

3. HARDWARE PATTERNS:
   - HK- for hardware kits
   - HW- for individual hardware items

4. SPRING PATTERNS:
   - SP- prefix with wire size codes

5. DOOR PACKAGES:
   - TX450-WWHH-CC format
   - WW = width code
   - HH = height code
   - CC = variant/color code

Review bc_quote_patterns.json for full details.
""")


if __name__ == "__main__":
    main()
