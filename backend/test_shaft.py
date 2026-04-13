from app.services.part_number_service import get_parts_for_door_config

def show_shafts(label, config, note=None):
    print('='*60)
    print(label)
    print('='*60)
    result = get_parts_for_door_config(config)
    shafts = result['by_category'].get('shaft', [])
    if shafts:
        for part in shafts:
            print(f'  {part["part_number"]}  x{part["quantity"]}  {part["description"]}')
    else:
        print('  (no shaft parts found)')
    if note:
        print(f'  NOTE: {note}')
    print()

base = {
    'doorCount': 1, 'panelColor': 'WHITE', 'panelDesign': 'SHXL',
    'trackRadius': '15', 'trackThickness': '2', 'hardware': {}
}

show_shafts("TEST 1: 12'6\" x 7'6\" Residential light (~540 lbs) -> tube shaft", {**base,
    'doorType': 'residential', 'doorSeries': 'KANATA',
    'doorWidth': 150, 'doorHeight': 90, 'targetCycles': 10000, 'shaftType': 'auto'},
    "12'6\" rounds up to next tube size (14') = SH12-11410-00")

show_shafts("TEST 2: 9' x 7' Commercial (solid single, 16\" overhang)", {**base,
    'doorType': 'commercial', 'doorSeries': 'TX450',
    'doorWidth': 108, 'doorHeight': 84, 'panelDesign': 'UDC', 'targetCycles': 25000, 'shaftType': 'auto'},
    "108\"+16\"=124\" -> FF>=ceil(118/12)=ceil(9.8)=10 -> SH11-11006-00 (10'6\"=126\")")

show_shafts("TEST 3: 9' x 7' Commercial, user forces SPLIT", {**base,
    'doorType': 'commercial', 'doorSeries': 'TX450',
    'doorWidth': 108, 'doorHeight': 84, 'panelDesign': 'UDC', 'targetCycles': 25000, 'shaftType': 'split'},
    "each half: ceil((108+4)/24)=ceil(4.67)=5 -> SH11-10506-00 (5'6\"=66\") x2 + coupler")

show_shafts("TEST 4: 16' x 8' Commercial (auto-split, 192\" > 170\")", {**base,
    'doorType': 'commercial', 'doorSeries': 'TX450',
    'doorWidth': 192, 'doorHeight': 96, 'panelDesign': 'UDC', 'targetCycles': 25000, 'shaftType': 'auto'},
    "each half: ceil((192+4)/24)=ceil(8.17)=9 -> SH11-10906-00 (9'6\"=114\") x2 + coupler")

show_shafts("TEST 5: 20' x 8' Commercial (auto-split)", {**base,
    'doorType': 'commercial', 'doorSeries': 'TX450',
    'doorWidth': 240, 'doorHeight': 96, 'panelDesign': 'UDC', 'targetCycles': 25000, 'shaftType': 'auto'},
    "each half: ceil((240+4)/24)=ceil(10.17)=11 -> SH11-11106-00 (11'6\"=138\") x2 + coupler")

show_shafts("TEST 6: 14'2\" = 170\" boundary (last single shaft)", {**base,
    'doorType': 'commercial', 'doorSeries': 'TX450',
    'doorWidth': 170, 'doorHeight': 96, 'panelDesign': 'UDC', 'targetCycles': 25000, 'shaftType': 'auto'},
    "170\"+16\"=186\" exactly -> FF=ceil(180/12)=15 -> SH11-11506-00 (15'6\"=186\") perfect fit")

show_shafts("TEST 7: 14'3\" = 171\" (1\" over boundary, auto-split)", {**base,
    'doorType': 'commercial', 'doorSeries': 'TX450',
    'doorWidth': 171, 'doorHeight': 96, 'panelDesign': 'UDC', 'targetCycles': 25000, 'shaftType': 'auto'},
    "each half: ceil((171+4)/24)=ceil(7.29)=8 -> SH11-10806-00 (8'6\"=102\") x2 + coupler")
