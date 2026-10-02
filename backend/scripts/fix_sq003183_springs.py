"""SQ-003183 (GNB Doors): correct spring/drum lines after the calculator fixes.

- 14x14 (HL 120", 25K cycles): quoted 3 LH + 3 RH duplex = 2x the springs the
  door needs. Replace with 2 LH + 2 RH duplex sets (.3125x6" outer / .283x3.75"
  inner), matching winders and tandem shafts.
- 16x18 (HL 168"): sized off D800-120's 120" row and doubled; no drum we have
  data for covers 168" HL. Remove springs/winders/shafts, flag office review.
- 20x20 / 24x24 / 30x30 (HL 192/240/312"): no springs were ever quoted; add the
  same office-review flag so it's visible.
- Freight re-derived at 7% of the item subtotal.
Backup of every original line is written next to this script before changes.
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

QUOTE = "SQ-003183"
q = bc_client.get_sales_quote_by_number(QUOTE)
qid = q["id"]
lines = bc_client.get_quote_lines(qid)
by_seq = {l["sequence"]: l for l in lines}
backup = Path(__file__).with_name("sq003183_lines_backup.json")
if not backup.exists():
    backup.write_text(json.dumps(lines, indent=1, default=str))
print(f"backup: {backup}")

def patch(seq, desc):
    l = by_seq[seq]
    bc_client.update_quote_line(qid, l["id"], l.get("@odata.etag", "*"), {"description": desc})
    print(f"  patched {seq}: {desc}")

def delete(seq, expect_pn):
    l = by_seq[seq]
    assert (l.get("lineObjectNumber") or "") == expect_pn, (seq, l.get("lineObjectNumber"))
    bc_client.delete_quote_line(qid, l["id"])
    print(f"  deleted {seq} {expect_pn} x{l['quantity']}")

def add_item(seq, pn, qty, desc):
    bc_client.add_quote_line(qid, {"lineType": "Item", "lineObjectNumber": pn, "quantity": qty,
                                   "description": desc, "sequence": seq})
    print(f"  added {seq} {pn} x{qty}")

def add_comment(seq, desc):
    assert len(desc) <= 100, len(desc)
    bc_client.add_quote_line(qid, {"lineType": "Comment", "description": desc, "sequence": seq})
    print(f"  comment {seq}: {desc}")

REVIEW = 'OFFICE REVIEW - DRUM: {hl}" HL exceeds all HL drum data (max ~162"). Springs not quoted.'

print("=== 16x18 ===")
for seq, pn in [(360000, "SP11-34360-01"), (370000, "SP11-34360-02"), (380000, "SP11-31236-01"),
                (390000, "SP11-31236-02"), (400000, "SP12-00233-01"), (410000, "SP12-00234-01"),
                (420000, "SH11-10606-00"), (430000, "SH11-10606-00"), (440000, "SP12-00160-00")]:
    delete(seq, pn)
patch(340000, "Door Weight: 759 lbs | Drum: none - 168\" HL exceeds D800-120 (120\") / D6375-164")
patch(350000, REVIEW.format(hl=168))

print("=== 14x14 ===")
for seq, pn in [(630000, "SP11-33160-01"), (640000, "SP11-33160-02"), (650000, "SP11-29536-01"),
                (660000, "SP11-29536-02"), (670000, "SP12-00233-01"), (680000, "SP12-00234-01"),
                (690000, "SH11-10606-00"), (700000, "SH11-10606-00"), (710000, "SP12-00160-00")]:
    delete(seq, pn)
patch(610000, "Door Weight: 473 lbs | Drum: D800-120 | Turns: 14.3 | 25K cycles | TANDEM SHAFT")
patch(620000, 'Springs: Outer .3125x6"x64" + Inner .283x3.75"x61" | 2 LH + 2 RH duplex sets (8)')
add_item(631000, "SP11-31260-01", 128, 'SPRINGS, OIL TEMPERED, .312 X 6" LH')
add_item(641000, "SP11-31260-02", 128, 'SPRINGS, OIL TEMPERED, .312 X 6" RH')
add_item(651000, "SP11-28336-01", 122, 'SPRINGS, OIL TEMPERED, .283 X 3 3/4" LH')
add_item(661000, "SP11-28336-02", 122, 'SPRINGS, OIL TEMPERED, .283 X 3 3/4" RH')
add_item(671000, "SP12-00233-01", 4, 'SPRING, WINDERS & STATIONARY PLUGS SET, 3 3/4", 1" BORE, UNIVERSAL')
add_item(681000, "SP12-00234-01", 4, 'SPRING, WINDERS & STATIONARY PLUGS SET, 6", 1" BORE, UNIVERSAL')
add_comment(685000, "** TANDEM SHAFT ASSEMBLY: 2x shafts + couplers below. Tandem connector SKU pending **")
add_item(691000, "SH11-10706-00", 2, '1" Solid Shaft Keyed 7\'-6"')
add_item(701000, "SH11-10806-00", 2, '1" Solid Shaft Keyed 8\'-6"')
add_item(711000, "SP12-00160-00", 2, 'SPRING ASSY CAST IRON COUPLER BLACK CANIMEX, 1" BORE')

print("=== 24x24 / 30x30 / 20x20 flags ===")
add_comment(135000, REVIEW.format(hl=240))
add_comment(885000, REVIEW.format(hl=312))
add_comment(1065000, REVIEW.format(hl=192))

print("=== freight ===")
lines = bc_client.get_quote_lines(qid)
fr = next(l for l in lines if l.get("lineObjectNumber") == "FREIGHT")
items = sum((l.get("quantity") or 0) * (l.get("unitPrice") or 0) for l in lines
            if l.get("lineType") == "Item" and l.get("lineObjectNumber") != "FREIGHT")
new_fr = round(items * 0.07, 2)
bc_client.update_quote_line(qid, fr["id"], fr.get("@odata.etag", "*"), {"unitPrice": new_fr})
print(f"  freight {fr['unitPrice']} -> {new_fr} (items {items:.2f})")
