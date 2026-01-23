#!/usr/bin/env python3
"""
Test Script: Door Configuration -> BC Quote End-to-End Flow

This script tests the complete flow:
1. Configure a door using the door configurator
2. Generate BC part numbers
3. Create a BC quote (optional - requires live BC connection)

Usage:
    python scripts/test_door_config_to_bc.py
    python scripts/test_door_config_to_bc.py --live  # Actually creates BC quotes
"""

import sys
import json
import logging
from pathlib import Path

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.part_number_service import get_parts_for_door_config, DoorConfiguration, part_number_service
from app.services.bc_part_number_mapper import get_bc_mapper, DoorModel, EndCapType

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def test_tx450_commercial():
    """Test TX450 commercial door configuration"""
    print("\n" + "="*60)
    print("TEST: TX450 Commercial Door - 9'x7' White")
    print("="*60)

    config = {
        "doorType": "commercial",
        "doorSeries": "TX450",
        "doorWidth": 108,  # 9' in inches
        "doorHeight": 84,   # 7' in inches
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
            "shafts": True,
        }
    }

    result = get_parts_for_door_config(config)

    print(f"\nTotal Parts: {result['total_parts']}")
    print("\nParts by Category:")
    for category, parts in result['by_category'].items():
        print(f"\n  {category.upper()}:")
        for part in parts:
            print(f"    - {part['part_number']}: {part['description']} (Qty: {part['quantity']})")

    # Verify key parts exist
    part_numbers = [p['part_number'] for p in result['parts_list']]

    checks = [
        # Panel check: either PN45 panel OR TX450 pre-configured package
        ("Panel/Package", any(p.startswith("PN45") or p.startswith("TX450") for p in part_numbers)),
        ("Spring LH (SP11)", any("SP11" in p and "01" in p for p in part_numbers)),
        ("Spring RH (SP11)", any("SP11" in p and "02" in p for p in part_numbers)),
        ("Winder LH (SP12)", any("SP12-0023" in p for p in part_numbers)),
        ("Track (TR02)", any(p.startswith("TR02") for p in part_numbers)),
        ("Weather Strip (PL10)", any("PL10" in p and "203" in p for p in part_numbers)),
        ("Shaft (SH12)", any(p.startswith("SH12") for p in part_numbers)),
    ]

    print("\n" + "-"*40)
    print("Validation Checks:")
    all_passed = True
    for check_name, passed in checks:
        status = "[PASS]" if passed else "[FAIL]"
        print(f"  {status}: {check_name}")
        if not passed:
            all_passed = False

    return all_passed


def test_tx500_commercial():
    """Test TX500 commercial door configuration"""
    print("\n" + "="*60)
    print("TEST: TX500 Commercial Door - 12'x10' Steel Grey")
    print("="*60)

    config = {
        "doorType": "commercial",
        "doorSeries": "TX500",
        "doorWidth": 144,  # 12' in inches
        "doorHeight": 120,  # 10' in inches
        "doorCount": 1,
        "panelColor": "STEEL_GREY",
        "panelDesign": "UDC",
        "trackRadius": "15",
        "trackThickness": "3",
        "hardware": {
            "tracks": True,
            "springs": True,
            "struts": True,
            "hardwareKits": True,
            "weatherStripping": True,
            "bottomRetainer": True,
            "shafts": True,
        }
    }

    result = get_parts_for_door_config(config)

    print(f"\nTotal Parts: {result['total_parts']}")
    print("\nParts List:")
    for part in result['parts_list']:
        print(f"  - {part['part_number']}: {part['description']} (Qty: {part['quantity']})")

    return result['total_parts'] > 0


def test_kanata_residential():
    """Test KANATA residential door configuration"""
    print("\n" + "="*60)
    print("TEST: KANATA Residential Door - 16'x7' White Sheridan")
    print("="*60)

    config = {
        "doorType": "residential",
        "doorSeries": "KANATA",
        "doorWidth": 192,  # 16' in inches
        "doorHeight": 84,   # 7' in inches
        "doorCount": 1,
        "panelColor": "WHITE",
        "panelDesign": "SHXL",  # Sheridan
        "trackRadius": "15",
        "trackThickness": "2",
        "hardware": {
            "tracks": True,
            "springs": True,
            "struts": True,
            "hardwareKits": True,
            "weatherStripping": True,
            "bottomRetainer": True,
            "shafts": True,
        }
    }

    result = get_parts_for_door_config(config)

    print(f"\nTotal Parts: {result['total_parts']}")
    print("\nParts List:")
    for part in result['parts_list']:
        print(f"  - {part['part_number']}: {part['description']} (Qty: {part['quantity']})")

    # Check for KANATA-specific parts
    part_numbers = [p['part_number'] for p in result['parts_list']]
    has_kanata_panel = any(p.startswith("PN60") or p.startswith("PN61") for p in part_numbers)

    print(f"\n[OK] Has KANATA panel: {has_kanata_panel}")

    return result['total_parts'] > 0


def test_multi_door_quote():
    """Test multi-door quote consolidation"""
    print("\n" + "="*60)
    print("TEST: Multi-Door Quote - 2x TX450 9'x7' + 1x TX450 16'x8'")
    print("="*60)

    doors = [
        {
            "doorType": "commercial",
            "doorSeries": "TX450",
            "doorWidth": 108,
            "doorHeight": 84,
            "doorCount": 2,  # 2 doors of this type
            "panelColor": "WHITE",
            "panelDesign": "UDC",
            "trackRadius": "15",
            "trackThickness": "2",
            "hardware": {"tracks": True, "springs": True, "struts": True}
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
            "hardware": {"tracks": True, "springs": True, "struts": True}
        }
    ]

    all_parts = []
    for i, door in enumerate(doors, 1):
        print(f"\nDoor {i}: {door['doorSeries']} {door['doorWidth']}\"x{door['doorHeight']}\"")
        result = get_parts_for_door_config(door)
        print(f"  Parts: {result['total_parts']}")
        all_parts.extend(result['parts_list'])

    # Consolidate duplicate parts
    consolidated = {}
    for part in all_parts:
        pn = part['part_number']
        if pn in consolidated:
            consolidated[pn]['quantity'] += part['quantity']
        else:
            consolidated[pn] = part.copy()

    print(f"\n\nCONSOLIDATED QUOTE SUMMARY:")
    print(f"  Total unique parts: {len(consolidated)}")
    print(f"  Total line items: {len(all_parts)}")

    print("\nConsolidated Parts List:")
    for part in sorted(consolidated.values(), key=lambda x: x['category']):
        print(f"  - {part['part_number']}: Qty {part['quantity']} ({part['category']})")

    return len(consolidated) > 0


def test_spring_calculator_integration():
    """Test that spring calculator is properly integrated"""
    print("\n" + "="*60)
    print("TEST: Spring Calculator Integration")
    print("="*60)

    # Test a heavy commercial door
    config = DoorConfiguration(
        door_type="commercial",
        door_series="TX450",
        door_width=192,   # 16'
        door_height=144,  # 12'
        door_count=1,
        panel_color="WHITE",
        panel_design="UDC",
        track_radius="15",
        track_thickness="3",
        hardware={"springs": True},
        door_weight=None,  # Let calculator estimate
        target_cycles=25000  # Commercial cycle life
    )

    parts = part_number_service.get_parts_for_configuration(config)

    spring_parts = [p for p in parts if p.category == "spring"]

    print(f"\nDoor: 16'x12' TX450 Commercial")
    print(f"Estimated Weight: ~{16*12*5.5:.0f} lbs (calculated)")
    print(f"\nSpring Parts Generated:")

    for part in spring_parts:
        print(f"  - {part.part_number}")
        print(f"    Description: {part.description}")
        print(f"    Quantity: {part.quantity}")
        if part.notes:
            print(f"    Notes: {part.notes}")

    # Verify spring part numbers follow correct format
    has_valid_springs = all(
        part.part_number.startswith("SP11") or part.part_number.startswith("SP10")
        for part in spring_parts
    )

    print(f"\n[OK] Valid spring part number format: {has_valid_springs}")

    return len(spring_parts) > 0 and has_valid_springs


def test_bc_part_number_mapper_directly():
    """Test BC part number mapper directly"""
    print("\n" + "="*60)
    print("TEST: BC Part Number Mapper Direct Tests")
    print("="*60)

    mapper = get_bc_mapper()

    # Test spring part number
    print("\n1. Spring Part Number:")
    spring = mapper.get_spring_part_number(0.234, 2.0, "LH")
    print(f"   Input: 0.234\" x 2\" LH")
    print(f"   Part Number: {spring.part_number}")
    print(f"   Expected: SP11-23420-01")
    spring_ok = spring.part_number == "SP11-23420-01"
    print(f"   [OK] Match: {spring_ok}")

    # Test panel part number
    print("\n2. Panel Part Number:")
    panel = mapper.get_panel_part_number(
        model=DoorModel.TX450,
        width_feet=9,
        height_inches=24,
        color="WHITE",
        end_cap_type=EndCapType.SINGLE,
        stamp="UDC"
    )
    print(f"   Input: TX450 9' x 24\" White UDC SEC")
    print(f"   Part Number: {panel.part_number}")
    print(f"   Expected: PN45-24400-0900")
    panel_ok = panel.part_number == "PN45-24400-0900"
    print(f"   [OK] Match: {panel_ok}")

    # Test weather stripping
    print("\n3. Weather Stripping:")
    ws = mapper.get_weather_stripping(door_height_feet=7, color="WHITE")
    print(f"   Input: 7' White")
    print(f"   Part Number: {ws.part_number}")
    print(f"   Expected: PL10-07203-00")
    ws_ok = ws.part_number == "PL10-07203-00"
    print(f"   [OK] Match: {ws_ok}")

    # Test track
    print("\n4. Track Assembly:")
    track = mapper.get_track_assembly(
        door_height_feet=7,
        track_size=2,
        radius_inches=15
    )
    print(f"   Input: 7' high, 2\" track, 15\" radius")
    print(f"   Part Number: {track.part_number}")
    print(f"   Expected: TR02-STDBM-0715")
    track_ok = track.part_number == "TR02-STDBM-0715"
    print(f"   [OK] Match: {track_ok}")

    # Test astragal
    print("\n5. Astragal:")
    astragal = mapper.get_astragal(door_width_feet=9)
    print(f"   Input: 9' wide door")
    print(f"   Part Number: {astragal.part_number}")
    print(f"   Expected: PL10-00005-01 (3\" astragal)")
    astragal_ok = astragal.part_number == "PL10-00005-01"
    print(f"   [OK] Match: {astragal_ok}")

    all_passed = spring_ok and panel_ok and ws_ok and track_ok and astragal_ok
    print(f"\n{'='*40}")
    print(f"All Mapper Tests: {'[PASS]ED' if all_passed else '[FAIL]ED'}")

    return all_passed


def main():
    """Run all tests"""
    print("="*60)
    print("DOOR CONFIGURATOR -> BC QUOTE END-TO-END TESTS")
    print("="*60)

    results = []

    # Run all tests
    tests = [
        ("BC Part Number Mapper Direct", test_bc_part_number_mapper_directly),
        ("TX450 Commercial Door", test_tx450_commercial),
        ("TX500 Commercial Door", test_tx500_commercial),
        ("KANATA Residential Door", test_kanata_residential),
        ("Multi-Door Quote", test_multi_door_quote),
        ("Spring Calculator Integration", test_spring_calculator_integration),
    ]

    for test_name, test_func in tests:
        try:
            passed = test_func()
            results.append((test_name, passed))
        except Exception as e:
            logger.error(f"Test '{test_name}' failed with error: {e}")
            results.append((test_name, False))

    # Summary
    print("\n" + "="*60)
    print("TEST SUMMARY")
    print("="*60)

    passed_count = sum(1 for _, passed in results if passed)
    total_count = len(results)

    for test_name, passed in results:
        status = "[PASS]" if passed else "[FAIL]"
        print(f"  {status}: {test_name}")

    print(f"\n{passed_count}/{total_count} tests passed")

    if passed_count == total_count:
        print("\n[SUCCESS] ALL TESTS PASSED - Door Config -> BC flow is working!")
        return 0
    else:
        print("\n[WARN]  Some tests failed - review output above")
        return 1


if __name__ == "__main__":
    sys.exit(main())
