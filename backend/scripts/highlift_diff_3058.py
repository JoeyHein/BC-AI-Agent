"""Recompute correct parts for the 12x12 TX450 door on SQ-003058 as 7' HIGH LIFT
(20' ceiling) and diff against what's currently on the quote."""
import sys
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass

from app.services.part_number_service import DoorConfiguration, PartNumberService

svc = PartNumberService()

config = DoorConfiguration(
    door_type="commercial",
    door_series="TX450",
    door_width=144,
    door_height=144,
    door_count=1,
    panel_color="BLACK",
    panel_design="UDC",
    track_thickness="3",
    track_mount="bracket",
    track_radius="15",
    lift_type="high_lift",
    high_lift_inches=84,  # 7'
    end_cap_type="SEC",
)

parts = svc.get_parts_for_configuration(config)

print("=== RECOMPUTED (7' HIGH LIFT, 20' ceiling) ===")
for p in parts:
    if not p.part_number:
        print(f"  (note) {p.description}")
        continue
    print(f"  {p.part_number:<18} qty={p.quantity:<4} {p.description[:70]}")
