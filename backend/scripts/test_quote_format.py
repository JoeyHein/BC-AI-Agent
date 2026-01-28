#!/usr/bin/env python3
"""
Test BC Quote Format - Verifies correct line ordering and panel part numbers
"""

import sys
from pathlib import Path

backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

from dotenv import load_dotenv
load_dotenv(backend_dir / ".env")

from app.services.bc_part_number_mapper import (
    BCPartNumberMapper, DoorModel, EndCapType, get_bc_mapper
)


def test_panel_part_numbers():
    """Test that panel part numbers follow the correct pattern"""
    print("=" * 60)
    print("TEST: Panel Part Number Patterns")
    print("=" * 60)

    mapper = get_bc_mapper()

    test_cases = [
        # (model, width_feet, expected_prefix, description)
        (DoorModel.KANATA, 9, "PN65", "KANATA 9' wide"),
        (DoorModel.KANATA, 16, "PN65", "KANATA 16' wide"),
        (DoorModel.KANATA, 18, "PN65", "KANATA 18' wide (still PN65)"),
        (DoorModel.CRAFT, 9, "PN95", "CRAFT 9' wide"),
        (DoorModel.CRAFT, 16, "PN95", "CRAFT 16' wide"),
        (DoorModel.TX380, 9, "PN35", "TX380 9' wide"),
        (DoorModel.TX380, 16, "PN35", "TX380 16' wide (max width)"),
        (DoorModel.TX450, 9, "PN45", "TX450 9' wide (SEC)"),
        (DoorModel.TX450, 16, "PN45", "TX450 16' wide (SEC, boundary)"),
        (DoorModel.TX450, 18, "PN46", "TX450 18' wide (DEC)"),
        (DoorModel.TX450, 20, "PN46", "TX450 20' wide (DEC)"),
        (DoorModel.TX500, 9, "PN55", "TX500 9' wide (SEC)"),
        (DoorModel.TX500, 16, "PN55", "TX500 16' wide (SEC, boundary)"),
        (DoorModel.TX500, 18, "PN56", "TX500 18' wide (DEC)"),
    ]

    all_passed = True
    for model, width, expected_prefix, description in test_cases:
        try:
            panel = mapper.get_panel_part_number(
                model=model,
                width_feet=width,
                height_inches=24,
                color="WHITE",
                stamp="UDC"
            )
            actual_prefix = panel.part_number[:4]
            passed = actual_prefix == expected_prefix
            status = "[OK]" if passed else "[FAIL]"
            print(f"  {status} {description}")
            print(f"       Part Number: {panel.part_number}")
            if not passed:
                print(f"       Expected prefix: {expected_prefix}, got: {actual_prefix}")
                all_passed = False
        except Exception as e:
            print(f"  [ERR] {description}: {e}")
            all_passed = False

    return all_passed


def test_line_ordering():
    """Test that line items are ordered correctly"""
    print("\n" + "=" * 60)
    print("TEST: Line Item Ordering")
    print("=" * 60)

    # Import the LINE_ORDER constant
    sys.path.insert(0, str(backend_dir / "app" / "api"))
    from door_configurator import LINE_ORDER

    # Expected order per BC_QUOTE_FORMAT.md (lowercase to match part_number_service)
    # NOTE: door_package removed - always use individual panel part numbers
    expected_order = [
        "comment",           # 1. Door description
        "panel",             # 2. Panels (PN45, PN46, PN65, PN95, etc.)
        "retainer",          # 3. Retainer
        "astragal",          # 4. Astragal
        "strut",             # 5. Struts
        "window",            # 6. Windows
        "track",             # 7. Track
        "highlift_track",    # 7b. Highlift track
        "hardware",          # 8. Hardware box
        "spring",            # 9. Springs
        "spring_accessory",  # 9b. Winders, plugs
        "shaft",             # 9c. Shaft
        "weather_stripping", # 10. Weather seal
        "accessory",         # 11. Accessories
        "operator",          # 12. Operator
    ]

    print("  Line ordering constant:")
    for i, category in enumerate(LINE_ORDER):
        print(f"    {i+1}. {category}")

    # Verify order matches expected
    if LINE_ORDER == expected_order:
        print("\n  [OK] Line ordering matches specification")
        return True
    else:
        print("\n  [FAIL] Line ordering doesn't match specification")
        print(f"    Expected: {expected_order}")
        print(f"    Got:      {LINE_ORDER}")
        return False


def test_door_description_format():
    """Test door description comment format"""
    print("\n" + "=" * 60)
    print("TEST: Door Description Comment Format")
    print("=" * 60)

    # Import the helper function
    from app.api.door_configurator import _format_door_description, DoorConfigRequest

    # Create test door configs
    test_doors = [
        DoorConfigRequest(
            doorType="commercial",
            doorSeries="TX450",
            doorWidth=108,  # 9'
            doorHeight=84,  # 7'
            doorCount=1,
            panelColor="WHITE",
            panelDesign="UDC",
            trackRadius="15",
            trackThickness="2",
            hardware={}
        ),
        DoorConfigRequest(
            doorType="residential",
            doorSeries="KANATA",
            doorWidth=192,  # 16'
            doorHeight=84,  # 7'
            doorCount=2,
            panelColor="WALNUT",
            panelDesign="SHXL",
            trackRadius="15",
            trackThickness="2",
            hardware={}
        ),
    ]

    print("  Generated door descriptions:")
    for door in test_doors:
        desc = _format_door_description(door)
        print(f"    {desc}")

    # Check format
    desc1 = _format_door_description(test_doors[0])
    checks = [
        ("Starts with qty", desc1.startswith("(1)")),
        ("Contains series", "TX450" in desc1),
        ("Contains color", "WHITE" in desc1),
        ("Contains design", "UDC" in desc1),
        ("Contains HW size", '2" HW' in desc1),
    ]

    all_passed = True
    for check_name, passed in checks:
        status = "[OK]" if passed else "[FAIL]"
        print(f"  {status} {check_name}")
        if not passed:
            all_passed = False

    return all_passed


def main():
    print("=" * 60)
    print("BC QUOTE FORMAT VERIFICATION TESTS")
    print("=" * 60)

    results = []

    # Run tests
    results.append(("Panel Part Numbers", test_panel_part_numbers()))
    results.append(("Line Ordering", test_line_ordering()))
    results.append(("Door Description Format", test_door_description_format()))

    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)

    passed = sum(1 for _, r in results if r)
    total = len(results)

    for name, result in results:
        status = "[PASS]" if result else "[FAIL]"
        print(f"  {status} {name}")

    print(f"\n  {passed}/{total} tests passed")

    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
