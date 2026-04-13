"""Debug hardware weight grams for 16x8 TX450"""
import math
from app.services.door_calculator_service import door_calculator, DoorDimensions, PanelConfiguration

dims = DoorDimensions(width=192, height=96)
panel = PanelConfiguration(total_sections=4, sections_21=0, sections_24=4, gauge=24, end_caps=1)

sections = 4
width_ft = 16.0

# Hinges
hinge_rows = sections + 1  # 5
hinges_per_row = max(2, math.ceil(192 / 48))  # 4
total_hinges = hinge_rows * hinges_per_row  # 20
hinge_grams = total_hinges * 323
print(f"Hinges: {total_hinges} hinges x 323g = {hinge_grams}g")

# Top brackets
tb = 2 * 312
print(f"Top Brackets: 2 x 312g = {tb}g")

# Bottom brackets
bb = 2 * 785
print(f"Bottom Brackets: 2 x 785g = {bb}g")

# L/S
ls_count = (sections - 1) * 2  # 6
ls = ls_count * 363
print(f"L/S: {ls_count} x 363g = {ls}g")

# S/S
ss = 2 * 308
print(f"S/S: 2 x 308g = {ss}g")

# Step kit
print(f"Step Kit: 605g")

# Tek screws
tek_per = max(12, round(2.2 * 16))  # 35
tek_total = sections * tek_per * 6
print(f"Tek Screws: {sections} sections x {tek_per} screws x 6g = {tek_total}g")

total = hinge_grams + tb + bb + ls + ss + 605 + tek_total
print(f"\nTotal: {total}g = {total/454:.1f} lbs -> round = {round(total/454)} lbs")

# What would it need to be for 21 lbs?
target = 21 * 454
print(f"\nTarget for 21 lbs: {target}g (diff: {total - target}g = {(total-target)/454:.1f} lbs)")
