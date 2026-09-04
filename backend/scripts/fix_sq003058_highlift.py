"""Surgical fix for SQ-003058 (O'Regan Construction) door 3 (12'x12' TX450):
the door was manually converted to 7' high lift (20' ceiling) in BC, but the
downstream hardware kit and springs were never recalculated to match. Track
extension kit (TR03-EXT7-00) was already added manually. This patches the
remaining stale lines: header comment, hardware kit, drum/spring comments,
springs, and winder set. Everything else on the quote (doors 1 & 2, freight,
shaft, weatherstrip, operator) is untouched.
"""
import sys
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass

from app.integrations.bc.client import bc_client

QUOTE_NUMBER = "SQ-003058"

quote = bc_client.get_sales_quote_by_number(QUOTE_NUMBER)
qid = quote["id"]
lines = {ql["id"]: ql for ql in bc_client.get_quote_lines(qid)}

def by_id(line_id):
    ql = lines[line_id]
    return ql["id"], ql.get("@odata.etag", "*")

HEADER_ID = "967b5309-eea7-f111-aaa8-3833c5f95e01"
WEIGHT_COMMENT_ID = "af7b5309-eea7-f111-aaa8-3833c5f95e01"
SPRING_COMMENT_ID = "b07b5309-eea7-f111-aaa8-3833c5f95e01"
OLD_HK_ID = "ae7b5309-eea7-f111-aaa8-3833c5f95e01"
OLD_SPRING_LH_ID = "b17b5309-eea7-f111-aaa8-3833c5f95e01"
OLD_SPRING_RH_ID = "b27b5309-eea7-f111-aaa8-3833c5f95e01"
OLD_WINDER_ID = "a9eb5e0f-eea7-f111-aaa8-3833c5f95e01"

print("=== 1. PATCH header comment -> HIGH LIFT 84\" ===")
lid, etag = by_id(HEADER_ID)
bc_client.update_quote_line(qid, lid, etag, {
    "description": '(1) 12\'0" x 12\'0" TX450, BLACK, UDC, 3" BRACKET MOUNT, HIGH LIFT 84"'
})
print("  done")

print("=== 2. PATCH weight/drum/turns comment ===")
lid, etag = by_id(WEIGHT_COMMENT_ID)
bc_client.update_quote_line(qid, lid, etag, {
    "description": "Door Weight: 337 lbs | Drum: D525-54 | Turns: 12.0"
})
print("  done")

print("=== 3. PATCH springs comment ===")
lid, etag = by_id(SPRING_COMMENT_ID)
bc_client.update_quote_line(qid, lid, etag, {
    "description": 'Springs: 0.3065" wire x 3.75" ID x 41" long | 1 LH + 1 RH (2 total)'
})
print("  done")

print("=== 4. Add high-lift extension comment (was missing) ===")
bc_client.add_quote_line(qid, {
    "lineType": "Comment",
    "description": 'HIGH LIFT: 84" (7\') requested -> 7\' extension kit selected',
    "sequence": 526000,
})
print("  done")

print("=== 5. Swap hardware kit: HK03-14120-RC -> HK13-1412007-RC ===")
lid, etag = by_id(OLD_HK_ID)
bc_client.delete_quote_line(qid, lid)
bc_client.add_quote_line(qid, {
    "lineType": "Item",
    "lineObjectNumber": "HK13-1412007-RC",
    "description": 'HARDWARE KIT, HIGH LIFT 3", 11\'3"-14\'2" X 10\'3"-12\'2", SEC, 7\'-7\'11" EXT',
    "quantity": 1,
    "sequence": 531000,
})
print("  done")

print("=== 6. Swap springs: SP11-28325-01/02 (qty 37) -> SP11-30636-01/02 (qty 41) ===")
lid, etag = by_id(OLD_SPRING_LH_ID)
bc_client.delete_quote_line(qid, lid)
bc_client.add_quote_line(qid, {
    "lineType": "Item", "lineObjectNumber": "SP11-30636-01",
    "description": 'SPRINGS, OIL TEMPERED, .306 X 3 3/4"  LH',
    "quantity": 41, "sequence": 561000,
})
lid, etag = by_id(OLD_SPRING_RH_ID)
bc_client.delete_quote_line(qid, lid)
bc_client.add_quote_line(qid, {
    "lineType": "Item", "lineObjectNumber": "SP11-30636-02",
    "description": 'SPRINGS, OIL TEMPERED, .306 X 3 3/4"  RH',
    "quantity": 41, "sequence": 571000,
})
print("  done")

print("=== 7. Swap winder/plug set: SP12-00232-01 -> SP12-00233-01 ===")
lid, etag = by_id(OLD_WINDER_ID)
bc_client.delete_quote_line(qid, lid)
bc_client.add_quote_line(qid, {
    "lineType": "Item", "lineObjectNumber": "SP12-00233-01",
    "description": 'SPRING, WINDERS & STATIONARY PLUGS SET, 3 3/4", 1" BORE, UNIVERSAL',
    "quantity": 2, "sequence": 581000,
})
print("  done")

print("\n=== VERIFY: fresh pull of door 3 section ===")
fresh = bc_client.get_quote_lines(qid)
started = False
for ql in fresh:
    desc = ql.get("description", "")
    if '12\'0" x 12\'0"' in desc:
        started = True
    if started:
        pn = ql.get("lineObjectNumber", "") or "(comment)"
        print(f"  seq={ql.get('sequence'):<8} {pn:<18} qty={ql.get('quantity',0):<5} {desc[:70]}")
