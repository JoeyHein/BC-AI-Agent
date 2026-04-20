"""
Full integration test — verify parts generation against rulebook for all door types.
"""
from app.services.part_number_service import PartNumberService, DoorConfiguration

svc = PartNumberService()
errors = []
passes = []

def test(name, config_dict):
    try:
        config = DoorConfiguration(**config_dict)
        parts = svc.get_parts_for_configuration(config)
        cats = {}
        for p in parts:
            if p.category not in cats:
                cats[p.category] = []
            cats[p.category].append(p)
        return parts, cats
    except Exception as e:
        errors.append(f"{name}: CRASHED - {e}")
        import traceback; traceback.print_exc()
        return None, None

# =========================================================================
# 1. RESI KANATA — 9'2" x 8' SHXL White
# =========================================================================
parts, cats = test("Kanata 9x8 SHXL White", {
    "door_type": "residential", "door_series": "KANATA",
    "door_width": 110, "door_height": 96, "door_count": 1,
    "panel_color": "WHITE", "panel_design": "SHXL",
})
if parts:
    panels = cats.get("panel", [])
    panel_pns = [p.part_number for p in panels]
    if any("PN65" in pn for pn in panel_pns):
        passes.append("Kanata: PN65 prefix")
    else:
        errors.append(f"Kanata: expected PN65, got {panel_pns}")

    top_seals = [p for p in parts if p.category == "top_seal"]
    if len(top_seals) == 0:
        passes.append("Kanata: no top seal (residential)")
    else:
        errors.append("Kanata: should NOT have top seal")

    shafts = cats.get("shaft", [])
    shaft_pns = [p.part_number for p in shafts]
    if "SH12-10910-00" in shaft_pns:
        passes.append("Kanata: SH12-10910-00 shaft for 9ft door")
    else:
        errors.append(f"Kanata shaft: expected SH12-10910-00, got {shaft_pns}")

# =========================================================================
# 2. RESI KANATA — Almond color code = 03
# =========================================================================
parts2, cats2 = test("Kanata Almond color", {
    "door_type": "residential", "door_series": "KANATA",
    "door_width": 96, "door_height": 96, "door_count": 1,
    "panel_color": "ALMOND", "panel_design": "SHXL",
})
if parts2:
    panels = cats2.get("panel", [])
    panel_pns = [p.part_number for p in panels]
    if any("03" in pn for pn in panel_pns):
        passes.append("Kanata: Almond color code 03")
    else:
        errors.append(f"Kanata Almond: expected code 03 in {panel_pns}")

# =========================================================================
# 3. RESI KANATA — 20' split shaft
# =========================================================================
parts3, cats3 = test("Kanata 20ft split shaft", {
    "door_type": "residential", "door_series": "KANATA",
    "door_width": 240, "door_height": 96, "door_count": 1,
    "panel_color": "WHITE", "panel_design": "SHXL",
})
if parts3:
    shafts = cats3.get("shaft", [])
    shaft_pns = sorted([p.part_number for p in shafts])
    if "SH11-11006-00" in shaft_pns and "SH11-11106-00" in shaft_pns:
        passes.append("Kanata 20ft: split shaft correct")
    else:
        errors.append(f"Kanata 20ft: expected split shaft, got {shaft_pns}")

# =========================================================================
# 4. RESI CRAFT — 8' x 8' Muskoka Walnut
# =========================================================================
parts4, cats4 = test("Craft 8x8 Muskoka Walnut", {
    "door_type": "residential", "door_series": "CRAFT",
    "door_width": 96, "door_height": 96, "door_count": 1,
    "panel_color": "WALNUT", "panel_design": "MUSKOKA",
})
if parts4:
    panels = cats4.get("panel", [])
    descs = [p.description for p in panels]

    if len(panels) == 3:
        passes.append("Craft: 3 panels")
    else:
        errors.append(f"Craft: expected 3 panels, got {len(panels)}")

    if panels and "FLUSH" in str(descs[0]):
        passes.append("Craft: 1st panel FLUSH")
    else:
        errors.append(f"Craft: 1st panel should be FLUSH")

    if any("32" in p.part_number for p in panels):
        passes.append("Craft: 32in height for 8ft door")
    else:
        errors.append(f"Craft: expected 32in panels")

    tracks = cats4.get("track", [])
    if any("TR25" in p.part_number for p in tracks):
        passes.append("Craft: TR25 track")
    else:
        errors.append(f"Craft: expected TR25 track, got {[p.part_number for p in tracks]}")

    springs = cats4.get("spring", [])
    if any(p.part_number == "SP01-00000-00" for p in springs):
        passes.append("Craft: SP01-00000-00 spring")
    else:
        errors.append(f"Craft: expected SP01-00000-00")

    hw = cats4.get("hardware", [])
    if any("CR" in p.part_number for p in hw):
        passes.append("Craft: HK02-xxxxx-CR hardware")
    else:
        errors.append(f"Craft: expected -CR hardware kit, got {[p.part_number for p in hw]}")

# =========================================================================
# 5. COMMERCIAL — TX450 12'x10' UDC
# =========================================================================
parts5, cats5 = test("Commercial TX450 12x10", {
    "door_type": "commercial", "door_series": "TX450",
    "door_width": 144, "door_height": 120, "door_count": 1,
    "panel_color": "WHITE", "panel_design": "UDC",
    "track_thickness": "3",
})
if parts5:
    retainers = [p for p in parts5 if p.category == "retainer"]
    if any(p.part_number == "PL10-00141-00" for p in retainers):
        passes.append("Commercial TX450: retainer PL10-00141-00")
    else:
        errors.append(f"Commercial TX450: expected PL10-00141-00, got {[p.part_number for p in retainers]}")

    top_seals = [p for p in parts5 if p.category == "top_seal"]
    if len(top_seals) == 0:
        passes.append("Commercial 12x10: no top seal (width<18ft)")
    else:
        errors.append("Commercial 12x10: should NOT have top seal")

    springs = cats5.get("spring", [])
    if any(p.part_number == "SP01-00000-00" for p in springs):
        passes.append("Commercial: SP01-00000-00 spring")
    else:
        errors.append(f"Commercial: expected SP01-00000-00")

    ws = [p for p in parts5 if p.category == "weather_stripping"]
    if any("PL11-22" in p.part_number for p in ws):
        passes.append("Commercial: PL11-22 weather strip")
    else:
        errors.append(f"Commercial: expected PL11-22, got {[p.part_number for p in ws]}")

# =========================================================================
# 6. COMMERCIAL — TX500 20'x12' (top seal + doubled retainer)
# =========================================================================
parts6, cats6 = test("Commercial TX500 20x12", {
    "door_type": "commercial", "door_series": "TX500",
    "door_width": 240, "door_height": 144, "door_count": 1,
    "panel_color": "WHITE", "panel_design": "UDC",
    "track_thickness": "3",
})
if parts6:
    retainers = [p for p in parts6 if p.category == "retainer"]
    if any(p.part_number == "PL10-00135-00" for p in retainers):
        passes.append("Commercial TX500: retainer PL10-00135-00")
    else:
        errors.append(f"Commercial TX500: expected PL10-00135-00, got {[p.part_number for p in retainers]}")

    top_seals = [p for p in parts6 if p.category == "top_seal"]
    if len(top_seals) > 0:
        passes.append("Commercial 20x12: top seal present")
    else:
        errors.append("Commercial 20x12: should HAVE top seal (>=18W, >=10H)")

    if any(p.quantity == 480 for p in retainers):
        passes.append("Commercial 20ft: retainer qty doubled (480)")
    else:
        errors.append(f"Commercial 20ft: retainer qty should be 480, got {[p.quantity for p in retainers]}")

# =========================================================================
# 7. COMMERCIAL — V Groove stamp test
# =========================================================================
parts7, cats7 = test("Commercial V Groove stamp", {
    "door_type": "commercial", "door_series": "TX380",
    "door_width": 144, "door_height": 120, "door_count": 1,
    "panel_color": "NEW_BROWN", "panel_design": "V GROOVE",
    "track_thickness": "3",
})
if parts7:
    panels = cats7.get("panel", [])
    panel_pns = [p.part_number for p in panels]
    # V Groove = stamp code 2 (3rd char of middle segment, e.g. PN35-24210-1200 → stamp=2)
    if any(pn.split("-")[1][2] == "2" for pn in panel_pns if pn.startswith("PN")):
        passes.append("Commercial: V Groove stamp code 2")
    else:
        errors.append(f"Commercial V Groove: stamp issue, pns={panel_pns}")

# =========================================================================
# 8. ALUMINIUM — AL-SWD 10'x8'
# =========================================================================
parts8, cats8 = test("AL-SWD 10x8", {
    "door_type": "aluminium", "door_series": "AL-SWD",
    "door_width": 120, "door_height": 96, "door_count": 1,
    "panel_color": "CLEAR_ANODIZED", "panel_design": "FLUSH",
})
if parts8:
    sections = cats8.get("aluminum_section", [])
    if any("PN70" in p.part_number for p in sections):
        passes.append("AL-SWD: PN70 prefix")
    else:
        errors.append(f"AL-SWD: expected PN70, got {[p.part_number for p in sections]}")

    if any("PN70-24200" in p.part_number for p in sections):
        passes.append("AL-SWD 10ft: length code 2")
    else:
        errors.append(f"AL-SWD 10ft: expected length code 2")

# =========================================================================
# 9. ALUMINIUM — Solalite White finish
# =========================================================================
parts9, cats9 = test("Solalite White", {
    "door_type": "aluminium", "door_series": "SOLALITE",
    "door_width": 98, "door_height": 96, "door_count": 1,
    "panel_color": "WHITE", "panel_design": "FLUSH",
})
if parts9:
    sections = cats9.get("aluminum_section", [])
    if any("PN20" in p.part_number and "003" in p.part_number for p in sections):
        passes.append("Solalite: White finish code 3")
    else:
        errors.append(f"Solalite White: expected finish 3, got {[p.part_number for p in sections]}")

# =========================================================================
# RESULTS
# =========================================================================
print("=" * 60)
print(f"PASSED: {len(passes)}")
for p in passes:
    print(f"  [PASS] {p}")
print(f"\nFAILED: {len(errors)}")
for e in errors:
    print(f"  [FAIL] {e}")
print("=" * 60)
if not errors:
    print("\nALL TESTS PASSED!")
else:
    print(f"\n{len(errors)} FAILURES")
