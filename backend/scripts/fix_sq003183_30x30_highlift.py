"""SQ-003183 part 4: 30x30 (x4) back to HIGH LIFT at the max the springs allow:
120" (10') on D800-120, 3 drums (center drum splits 3007 lb -> ~1002 lb/drum,
inside the 2200 lb rating), duplex springs on 3 shafts at 10K cycles
(8 positions 3/3/2: .4062x6"x94" outer / .3625x3.75"x83" inner, 4 LH + 4 RH).
25K/15K don't fit at any HL. No drum/HK/30' track SKUs exist in BC -> comments.
Freight is hand-set by Joey ($25,000) and is NOT touched.
"""
import json, sys
from pathlib import Path
for _s in (sys.stdout, sys.stderr):
    try: _s.reconfigure(encoding="utf-8")
    except Exception: pass
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.integrations.bc.client import bc_client

q = bc_client.get_sales_quote_by_number("SQ-003183"); qid = q["id"]
lines = bc_client.get_quote_lines(qid)
bk = Path(__file__).with_name("sq003183_lines_backup_part4.json")
if not bk.exists(): bk.write_text(json.dumps(lines, indent=1, default=str))
by_seq = {l["sequence"]: l for l in lines}

def patch(seq, desc):
    assert len(desc) <= 100, desc
    l = by_seq[seq]; bc_client.update_quote_line(qid, l["id"], l.get("@odata.etag", "*"), {"description": desc}); print(f"  patch {seq}: {desc}")
def add(seq, ln):
    if ln[0] == "C":
        assert len(ln[1]) <= 100, ln[1]
        bc_client.add_quote_line(qid, {"lineType": "Comment", "description": ln[1], "sequence": seq})
    else:
        bc_client.add_quote_line(qid, {"lineType": "Item", "lineObjectNumber": ln[1], "quantity": ln[2], "description": ln[3], "sequence": seq})
    print(f"  add {seq} {ln[1][:85]}" + (f" x{ln[2]}" if ln[0] == "I" else ""))

assert by_seq[850000]["lineObjectNumber"] == "TR03-EXT10-00"
patch(760000, '(4) 30\'0" x 30\'0" TX450, WHITE, UDC, 3" ANGLE MOUNT, HIGH LIFT 120"')
patch(850000, 'TRACK ASSEMBLY, 3" HIGH LIFT EXTENSION 10\' KIT')
patch(851000, "TRACK: 30' base vertical/horizontal track not stocked (max TR03-STDAM-24) - source")
patch(870000, "HARDWARE KIT: 30'W x 30'H HL 3\" +10' - no stocked HK (max 29'W x 26'H); source")
add(871000, ("C", 'HIGH LIFT: 120" (10\') = MAX for 30x30 (3 shafts, 10K). 312" (26\') requested - reduced'))
add(872000, ("C", "3 DRUMS/door: 2x D800-120 + 1 CENTER D800-120 (~1002 lb/drum vs 2200 rating)"))
add(873000, ("C", "CENTER LIFT: add 3rd 1/4\" cable + center bottom bracket per door - office to source"))

for s in sorted(k for k in by_seq if 881000 <= k <= 899000):
    l = by_seq[s]; bc_client.delete_quote_line(qid, l["id"]); print(f"  del {s} {(l.get('lineObjectNumber') or l['description'])[:70]}")

block = [
    ("C", "Door Weight: 3007 lbs | Drums: 3x D800-120 | Turns: 18.3 | 10K | 3 SHAFTS"),
    ("C", 'Springs/door: Outer 0.4062x6.0"x94" | Inner 0.3625x3.75"x83" | 4 LH + 4 RH duplex sets'),
    ("C", 'NOTE: 94" duplex springs - confirm length w/ spring supplier'),
    ("I", "SP11-40660-01", 1504, 'SPRINGS, OIL TEMPERED, .406 X 6" LH'),
    ("I", "SP11-40660-02", 1504, 'SPRINGS, OIL TEMPERED, .406 X 6" RH'),
    ("I", "SP11-36236-01", 1328, 'SPRINGS, OIL TEMPERED, .362 X 3 3/4"  LH'),
    ("I", "SP11-36236-02", 1328, 'SPRINGS, OIL TEMPERED, .362 X 3 3/4"  RH'),
    ("C", '6" WINDER SET 1-1/4" BORE x32 - SP12-00236-01 BLOCKED in BC, office to source'),
    ("C", '3-3/4" WINDER SET 1-1/4" BORE x32 - no BC SKU, office to source'),
    ("C", "** 3-SHAFT ASSEMBLY (3/3/2 positions), center drum on main shaft. Connector SKU pending **"),
    ("I", "SH10-21900-00", 12, 'SOLID 1-1/4" KEYED SHAFT, 19\''),
    ("I", "SH10-21506-00", 12, 'SOLID 1-1/4" KEYED SHAFT, 15\'- 06"'),
    ("I", "SP12-00161-00", 12, 'SPRING ASSY CAST IRON COUPLER BLACK CANIMEX, 1-1/4" BORE'),
]
for i, ln in enumerate(block): add(881000 + i * 1000, ln)
