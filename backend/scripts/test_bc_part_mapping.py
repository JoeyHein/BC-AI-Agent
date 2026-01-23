#!/usr/bin/env python3
"""
Test script for BC Part Number Mapping

Tests the integration of:
1. Spring calculator -> BC spring part numbers
2. Door configuration -> BC panel part numbers
3. All accessories -> BC part numbers

Run from backend directory:
    python scripts/test_bc_part_mapping.py
"""

import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.bc_part_number_mapper import (
    BCPartNumberMapper,
    get_bc_mapper,
    SpringType,
    DoorModel,
    EndCapType,
    LiftType,
    TrackMount,
)
from app.services.part_number_service import (
    PartNumberService,
    DoorConfiguration,
    get_parts_for_door_config,
)


def test_spring_part_numbers():
    """Test spring part number generation"""
    print("\n" + "=" * 60)
    print("TESTING SPRING PART NUMBER GENERATION")
    print("=" * 60)

    mapper = get_bc_mapper()

    # Test cases based on user examples
    test_cases = [
        # (wire_size, coil_id, wind, expected_part)
        (0.234, 2.0, "LH", "SP11-23420-01"),
        (0.234, 2.0, "RH", "SP11-23420-02"),
        (0.250, 2.0, "LH", "SP11-25020-01"),
        (0.250, 2.0, "RH", "SP11-25020-02"),
        (0.273, 2.0, "LH", "SP11-27320-01"),
        (0.273, 3.75, "LH", "SP11-27336-01"),
        (0.393, 6.0, "LH", "SP11-39360-01"),
    ]

    all_passed = True
    for wire, coil, wind, expected in test_cases:
        result = mapper.get_spring_part_number(wire, coil, wind)
        status = "[PASS]" if result.part_number == expected else "[FAIL]"
        if result.part_number != expected:
            all_passed = False
        print(f"{status} {wire}\" x {coil}\" {wind} -> {result.part_number} (expected: {expected})")
        print(f"    Description: {result.description}")

    print(f"\nSpring tests: {'ALL PASSED' if all_passed else 'SOME FAILED'}")
    return all_passed


def test_winder_stationary_sets():
    """Test winder/stationary set part numbers"""
    print("\n" + "=" * 60)
    print("TESTING WINDER/STATIONARY SET PART NUMBERS")
    print("=" * 60)

    mapper = get_bc_mapper()

    test_cases = [
        (2.0, 1.0, "LH", "SP12-00231-00"),
        (2.0, 1.0, "RH", "SP12-00237-00"),
        (2.625, 1.0, "LH", "SP12-00232-00"),
        (3.75, 1.0, "LH", "SP12-00233-00"),
        (6.0, 1.0, "LH", "SP12-00234-00"),
    ]

    all_passed = True
    for coil, bore, wind, expected in test_cases:
        result = mapper.get_winder_stationary_set(coil, bore, wind)
        status = "[PASS]" if result.part_number == expected else "[FAIL]"
        if result.part_number != expected:
            all_passed = False
        print(f"{status} Coil: {coil}\", Bore: {bore}\", {wind} -> {result.part_number}")
        print(f"    Description: {result.description}")

    print(f"\nWinder set tests: {'ALL PASSED' if all_passed else 'SOME FAILED'}")
    return all_passed


def test_panel_part_numbers():
    """Test panel part number generation"""
    print("\n" + "=" * 60)
    print("TESTING PANEL PART NUMBER GENERATION")
    print("=" * 60)

    mapper = get_bc_mapper()

    # Test TX450 9' wide, 24" tall, white, UDC stamp, single end cap
    # Expected: PN45-24400-0900
    result = mapper.get_panel_part_number(
        model=DoorModel.TX450,
        width_feet=9,
        height_inches=24,
        color="WHITE",
        end_cap_type=EndCapType.SINGLE,
        stamp="UDC"
    )
    expected = "PN45-24400-0108"  # 9ft = 108 inches
    print(f"TX450 9'x24\" White UDC SEC -> {result.part_number}")
    print(f"    Description: {result.description}")

    # Test TX450 16' wide with double end caps
    result2 = mapper.get_panel_part_number(
        model=DoorModel.TX450,
        width_feet=16,
        height_inches=24,
        color="WHITE",
        end_cap_type=EndCapType.DOUBLE,
        stamp="UDC"
    )
    print(f"\nTX450 16'x24\" White UDC DEC -> {result2.part_number}")
    print(f"    Description: {result2.description}")

    return True


def test_weather_stripping():
    """Test weather stripping part numbers"""
    print("\n" + "=" * 60)
    print("TESTING WEATHER STRIPPING PART NUMBERS")
    print("=" * 60)

    mapper = get_bc_mapper()

    test_cases = [
        (7, "WHITE", "PL10-07203-00"),
        (8, "WHITE", "PL10-08203-00"),
        (9, "WHITE", "PL10-09203-00"),
        (9, "BLACK", "PL10-09203-05"),
        (16, "WHITE", "PL10-16203-00"),
    ]

    all_passed = True
    for height, color, expected in test_cases:
        result = mapper.get_weather_stripping(height, color)
        status = "[PASS]" if result.part_number == expected else "[FAIL]"
        if result.part_number != expected:
            all_passed = False
        print(f"{status} {height}' {color} -> {result.part_number} (expected: {expected})")

    print(f"\nWeather stripping tests: {'ALL PASSED' if all_passed else 'SOME FAILED'}")
    return all_passed


def test_astragal():
    """Test astragal part numbers"""
    print("\n" + "=" * 60)
    print("TESTING ASTRAGAL PART NUMBERS")
    print("=" * 60)

    mapper = get_bc_mapper()

    # Test 3" astragal for doors <=16'
    result1 = mapper.get_astragal(9)
    print(f"9' wide door -> {result1.part_number} (3\" expected)")
    print(f"    Description: {result1.description}")

    result2 = mapper.get_astragal(16)
    print(f"16' wide door -> {result2.part_number} (3\" expected)")

    result3 = mapper.get_astragal(18)
    print(f"18' wide door -> {result3.part_number} (4\" expected)")

    return True


def test_complete_door_configuration():
    """Test complete door configuration with all parts"""
    print("\n" + "=" * 60)
    print("TESTING COMPLETE DOOR CONFIGURATION")
    print("=" * 60)

    # Use the PartNumberService which integrates everything
    config = DoorConfiguration(
        door_type="commercial",
        door_series="TX450",
        door_width=108,  # 9' in inches
        door_height=84,  # 7' in inches
        door_count=1,
        panel_color="WHITE",
        panel_design="UDC",
        track_radius="12",
        track_thickness="2",
        hardware={
            "tracks": True,
            "springs": True,
            "shafts": True,
            "struts": True,
            "hardwareKits": False,  # Skip hardware kits for now
            "weatherStripping": True,
            "bottomRetainer": True,
        },
        door_weight=200,  # Estimated door weight
        target_cycles=10000,
        spring_quantity=2,
    )

    service = PartNumberService()
    parts = service.get_parts_for_configuration(config)

    print(f"\nDoor Configuration: TX450 9'x7' WHITE Commercial")
    print(f"Estimated Weight: 200 lbs")
    print("-" * 40)

    for part in parts:
        print(f"{part.category.upper():15} | {part.part_number:20} | Qty: {part.quantity:3}")
        print(f"                  {part.description}")
        if part.notes:
            print(f"                  Notes: {part.notes}")
        print()

    print(f"\nTotal parts: {len(parts)}")
    return True


def test_user_example():
    """Test the exact user example: TX450 white 9' wide 24" tall UDC stamp"""
    print("\n" + "=" * 60)
    print("USER EXAMPLE: TX450 WHITE 9' WIDE 24\" TALL UDC")
    print("=" * 60)

    print("\nExpected per user:")
    print("- Panel: PN45-24400-0900 (TX450 single end cap)")
    print("- Spring: SP11-23420-01 (LH) and SP11-23420-02 (RH)")
    print("- Winder Set: SP12-00231-00")
    print("- Weather Stripping: PL10-07203-00 (white 7')")
    print("- Retainer: PL10-00141-00 (1-3/4\")")
    print("- Astragal: PL10-00005-01 (3\")")

    mapper = get_bc_mapper()

    print("\n--- Generated Part Numbers ---\n")

    # Panel
    panel = mapper.get_panel_part_number(
        model=DoorModel.TX450,
        width_feet=9,
        height_inches=24,
        color="WHITE",
        end_cap_type=EndCapType.SINGLE,
        stamp="UDC"
    )
    print(f"Panel:     {panel.part_number}")

    # Springs (using 0.234 x 2.0" as typical for this door size)
    spring_lh = mapper.get_spring_part_number(0.234, 2.0, "LH")
    spring_rh = mapper.get_spring_part_number(0.234, 2.0, "RH")
    print(f"Spring LH: {spring_lh.part_number}")
    print(f"Spring RH: {spring_rh.part_number}")

    # Winder set
    winder = mapper.get_winder_stationary_set(2.0, 1.0, "LH")
    print(f"Winder:    {winder.part_number}")

    # Weather stripping
    ws = mapper.get_weather_stripping(7, "WHITE")
    print(f"W/Strip:   {ws.part_number}")

    # Retainer
    ret = mapper.get_retainer()
    print(f"Retainer:  {ret.part_number}")

    # Astragal
    ast = mapper.get_astragal(9)
    print(f"Astragal:  {ast.part_number}")

    return True


def main():
    print("\n" + "=" * 60)
    print("BC PART NUMBER MAPPING TEST SUITE")
    print("=" * 60)

    results = []
    results.append(("Spring Part Numbers", test_spring_part_numbers()))
    results.append(("Winder/Stationary Sets", test_winder_stationary_sets()))
    results.append(("Panel Part Numbers", test_panel_part_numbers()))
    results.append(("Weather Stripping", test_weather_stripping()))
    results.append(("Astragal", test_astragal()))
    results.append(("Complete Door Config", test_complete_door_configuration()))
    results.append(("User Example", test_user_example()))

    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)

    for name, passed in results:
        status = "[PASSED]" if passed else "[FAILED]"
        print(f"{name:30} {status}")

    all_passed = all(r[1] for r in results)
    print("\n" + "=" * 60)
    print(f"OVERALL: {'ALL TESTS PASSED' if all_passed else 'SOME TESTS FAILED'}")
    print("=" * 60)


if __name__ == "__main__":
    main()
