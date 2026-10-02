"""SQ-003183 part 2: add the springs that actually work (25K cycles, duplex,
multi-shaft) to the 16x18 / 20x20 / 24x24 groups, and convert the 30x30 to
STANDARD LIFT (the only lift any of our drums/springs can carry it on).

Line plan comes from a JSON produced by the sizing run (see conversation
2026-10-02); this script only applies it. HL groups past 162" use D6375-164
turns/multiplier extrapolated along the table's own slope and are marked
ESTIMATE on the quote.
"""
import json, sys
from pathlib import Path
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.integrations.bc.client import bc_client

plan = json.load(open(sys.argv[1]))
q = bc_client.get_sales_quote_by_number("SQ-003183")
qid = q["id"]
lines = bc_client.get_quote_lines(qid)
by_seq = {l["sequence"]: l for l in lines}
bk = Path(__file__).with_name("sq003183_lines_backup_part2.json")
if not bk.exists():
    bk.write_text(json.dumps(lines, indent=1, default=str))
print("backup:", bk)

def delete(seq, expect):
    l = by_seq[seq]
    got = l.get("lineObjectNumber") or l.get("description")
    assert expect in got, (seq, got)
    bc_client.delete_quote_line(qid, l["id"]); print(f"  del {seq} {got[:60]}")

def patch(seq, desc):
    l = by_seq[seq]
    bc_client.update_quote_line(qid, l["id"], l.get("@odata.etag", "*"), {"description": desc[:100]})
    print(f"  patch {seq}: {desc[:100]}")

def add(seq, ln):
    if ln[0] == "C":
        assert len(ln[1]) <= 100, ln[1]
        bc_client.add_quote_line(qid, {"lineType": "Comment", "description": ln[1], "sequence": seq})
    else:
        _, pn, qty, desc = ln
        bc_client.add_quote_line(qid, {"lineType": "Item", "lineObjectNumber": pn, "quantity": qty,
                                       "description": desc[:100], "sequence": seq})
    print(f"  add {seq} {ln[1][:90]}" + (f" x{ln[2]}" if ln[0] == "I" else ""))

def place(start, step, group):
    for i, ln in enumerate(plan[group]):
        add(start + i * step, ln)

print("=== 24x24 ===")
delete(135000, "OFFICE REVIEW"); delete(140000, "SH11-11106-00"); delete(150000, "SH11-11506-00"); delete(160000, "SP12-00160-00")
place(136000, 2000, "24x24")

print("=== 16x18 ===")
delete(340000, "Door Weight"); delete(350000, "OFFICE REVIEW")
place(341000, 3000, "16x18")

print("=== 30x30 -> standard lift ===")
patch(760000, '(4) 30\'0" x 30\'0" TX450, WHITE, UDC, 3" ANGLE MOUNT, STANDARD LIFT')
delete(860000, "TR03-EXT20-00")
delete(880000, "HIGH LIFT")
delete(885000, "OFFICE REVIEW")
delete(890000, "SH10-00002-00")
patch(870000, "HARDWARE KIT: 30'x30' STANDARD LIFT, 3\" - no stocked HK; office to source")
add(851000, ("C", "TRACK: verify - no stocked 30' std-lift 3\" track kit (max TR03-STDAM-24)"))
place(881000, 1000, "30x30")

print("=== 20x20 ===")
delete(1065000, "OFFICE REVIEW"); delete(1070000, "SH11-11006-00"); delete(1080000, "SH11-11106-00"); delete(1090000, "SP12-00160-00")
place(1062000, 2000, "20x20")

print("=== freight ===")
lines = bc_client.get_quote_lines(qid)
fr = next(l for l in lines if l.get("lineObjectNumber") == "FREIGHT")
items = sum((l.get("quantity") or 0) * (l.get("unitPrice") or 0) for l in lines
            if l.get("lineType") == "Item" and l.get("lineObjectNumber") != "FREIGHT")
new_fr = round(items * 0.07, 2)
bc_client.update_quote_line(qid, fr["id"], fr.get("@odata.etag", "*"), {"unitPrice": new_fr})
print(f"  freight {fr['unitPrice']} -> {new_fr} (items {items:.2f})")
