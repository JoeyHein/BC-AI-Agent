"""SQ-003183 part 3: re-quote every door at the MAXIMUM high lift we can
support with real drum data on a tandem (2-shaft) duplex spring assembly at
25K cycles; where 25K isn't possible on tandem, the best cycle life we can do.

  16x18  168" req -> 156" (13')  25K  D6375-164
  20x20  192" req -> 132" (11')  25K  D6375-164
  24x24  240" req ->  60" (5')   25K  D800-120
  30x30  312" req -> standard lift, 10K (nothing higher fits a tandem)
  14x14  120" req -> 120" unchanged (already 25K tandem)
"""
import json, sys
from pathlib import Path
for _s in (sys.stdout, sys.stderr):
    try: _s.reconfigure(encoding="utf-8")
    except Exception: pass
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.integrations.bc.client import bc_client

plan = json.load(open(Path(__file__).with_name("sq003183_tandem_maxhl_plan.json")))
q = bc_client.get_sales_quote_by_number("SQ-003183"); qid = q["id"]
lines = bc_client.get_quote_lines(qid)
bk = Path(__file__).with_name("sq003183_lines_backup_part3.json")
if not bk.exists(): bk.write_text(json.dumps(lines, indent=1, default=str))
by_seq = {l["sequence"]: l for l in lines}

def delete(seq, expect=None):
    l = by_seq[seq]; got = l.get("lineObjectNumber") or l.get("description")
    if expect: assert expect in got, (seq, got)
    bc_client.delete_quote_line(qid, l["id"]); print(f"  del {seq} {got[:70]}")
def patch(seq, desc):
    assert len(desc) <= 100, desc
    l = by_seq[seq]; bc_client.update_quote_line(qid, l["id"], l.get("@odata.etag", "*"), {"description": desc}); print(f"  patch {seq}: {desc}")
def add(seq, ln):
    if ln[0] == "C":
        assert len(ln[1]) <= 100, ln[1]
        bc_client.add_quote_line(qid, {"lineType": "Comment", "description": ln[1], "sequence": seq})
    else:
        bc_client.add_quote_line(qid, {"lineType": "Item", "lineObjectNumber": ln[1], "quantity": ln[2],
                                       "description": ln[3][:100], "sequence": seq})
    print(f"  add {seq} {ln[1][:80]}" + (f" x{ln[2]}" if ln[0] == "I" else ""))
def clear_block(lo, hi):
    for s in sorted(k for k in by_seq if lo <= k <= hi): delete(s)
def place(start, step, group, limit):
    for i, ln in enumerate(plan[group]):
        seq = start + i * step; assert seq < limit, (group, seq); add(seq, ln)

print("=== 24x24 -> 60\" HL ===")
patch(10000, '(9) 24\'0" x 24\'0" TX450, WHITE, UDC, 3" ANGLE MOUNT, HIGH LIFT 60"')
delete(110000, "TR03-EXT20-00"); add(111000, ("I", "TR03-EXT5-00", 9, 'TRACK ASSEMBLY, 3" HIGH LIFT EXTENSION 5\' KIT'))
delete(120000, "HK13-2424113-RC"); add(121000, ("I", "HK13-2424105-RC", 9, 'HARDWARE KIT, HIGH LIFT 3", 22\'1"-24\'0" X 22\'3"-24\'0", DEC, 5\'-5\'11" EXT'))
patch(130000, 'HIGH LIFT: 60" (5\') = MAX on tandem @25K. 240" (20\') requested - reduced')
clear_block(131000, 169000); place(136000, 2000, "24x24", 170000)

print("=== 16x18 -> 156\" HL ===")
patch(210000, '(16) 16\'0" x 18\'0" TX450, WHITE, UDC, 3" ANGLE MOUNT, HIGH LIFT 156"')
delete(310000, "TR03-EXT14-00"); add(311000, ("I", "TR03-EXT13-00", 16, 'TRACK ASSEMBLY, 3" HIGH LIFT EXTENSION 13\' KIT'))
patch(330000, 'HIGH LIFT: 156" (13\') = MAX on tandem @25K. 168" (14\') requested - reduced')
clear_block(331000, 449000); place(341000, 3000, "16x18", 450000)

print("=== 30x30 standard lift, 10K tandem ===")
clear_block(881000, 899000); place(881000, 1000, "30x30", 900000)

print("=== 20x20 -> 132\" HL ===")
patch(940000, '(8) 20\'0" x 20\'0" TX450, WHITE, UDC, 3" ANGLE MOUNT, HIGH LIFT 132"')
delete(1040000, "TR03-EXT16-00"); add(1041000, ("I", "TR03-EXT11-00", 8, 'TRACK ASSEMBLY, 3" HIGH LIFT EXTENSION 11\' KIT'))
delete(1050000, "HK13-2020113-RC"); add(1051000, ("I", "HK13-2020111-RC", 8, 'HARDWARE KIT, HIGH LIFT 3", 19\'6"-20\'0" X 18\'3"-20\'2", DEC, 11\'-11\'11" EXT'))
patch(1060000, 'HIGH LIFT: 132" (11\') = MAX on tandem @25K. 192" (16\') requested - reduced')
clear_block(1061000, 1099000); place(1062000, 2000, "20x20", 1100000)

print("=== freight ===")
lines = bc_client.get_quote_lines(qid)
fr = next(l for l in lines if l.get("lineObjectNumber") == "FREIGHT")
items = sum((l.get("quantity") or 0) * (l.get("unitPrice") or 0) for l in lines
            if l.get("lineType") == "Item" and l.get("lineObjectNumber") != "FREIGHT")
new_fr = round(items * 0.07, 2)
bc_client.update_quote_line(qid, fr["id"], fr.get("@odata.etag", "*"), {"unitPrice": new_fr})
print(f"  freight {fr['unitPrice']} -> {new_fr} (items {items:.2f})")
