"""Test 16x8 TX450 weight calculation"""
from app.services.door_calculator_service import door_calculator

calc = door_calculator.calculate_door('TX450', 192, 96, track_size=3)
s = door_calculator.get_calculation_summary(calc)
w = s['weight']

print(f"Steel:    {w['steel_lbs']} lbs")
print(f"Hardware: {w['hardware_lbs']} lbs")
print(f"Struts:   {w['strut_lbs']} lbs")
print(f"Glazing:  {w['glazing_lbs']} lbs")
print(f"Total:    {w['total_lbs']} lbs")
print(f"Drum:     {s['drum']['model']}")
print(f"Strut details: {s['hardware']['struts']}")
print(f"Hinge details: {s['hardware']['hinges']}")
print(f"Brackets: {s['hardware']['brackets']}")
print(f"Bolts:    {s['hardware']['bolts']}")

# Also test 8x10 for reference comparison
print("\n--- 8'x10' TX450 reference ---")
calc2 = door_calculator.calculate_door('TX450', 96, 120, track_size=3)
s2 = door_calculator.get_calculation_summary(calc2)
w2 = s2['weight']
print(f"Steel:    {w2['steel_lbs']} lbs")
print(f"Hardware: {w2['hardware_lbs']} lbs")
print(f"Struts:   {w2['strut_lbs']} lbs")
print(f"Total:    {w2['total_lbs']} lbs")
