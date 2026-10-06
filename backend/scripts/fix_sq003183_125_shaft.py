"""SQ-003183 part 5: every door to a 1-1/4" shaft system.

- 1" SH11 shafts -> next-longer SH10 1-1/4" stock length (cut to fit)
- SP12-00160-00 1" couplers -> SP12-00161-00 1-1/4"
- 6" winder sets 1" universal -> 1-1/4" LH (SP12-00236-00) / RH (SP12-00242-00)
  (the 1-1/4" universal SP12-00236-01 is BLOCKED)
- 3-3/4" winder sets 1" -> SP12-00174-00 stationary plug (1" & 1-1/4" bore);
  no 3-3/4" 1-1/4" WINDER exists in BC -> comment for office
- drums/bearings live inside HK kits -> comment: supply 1-1/4" bore
Freight is hand-set ($25,000) and NOT touched.
"""
import json, sys
from pathlib import Path
for _s in (sys.stdout, sys.stderr):
    try: _s.reconfigure(encoding="utf-8")
    except Exception: pass
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.integrations.bc.client import bc_client

SHAFT_MAP = {  # 1" SH11 -> 1-1/4" SH10 (next stock length up)
    "SH11-10606-00": ("SH10-20700-00", 'SOLID 1-1/4" KEYED SHAFT, 07\''),
    "SH11-10706-00": ("SH10-20710-00", 'SOLID 1-1/4" KEYED SHAFT, 07\'- 10"'),
    "SH11-10806-00": ("SH10-20911-00", 'SOLID 1-1/4" KEYED SHAFT, 09\'-11"'),
    "SH11-10906-00": ("SH10-20911-00", 'SOLID 1-1/4" KEYED SHAFT, 09\'-11"'),
    "SH11-11006-00": ("SH10-21009-00", 'SOLID 1-1/4" KEYED SHAFT, 10\'- 09"'),
    "SH11-11106-00": ("SH10-21202-00", 'SOLID 1-1/4" KEYED SHAFT, 12\'- 02"'),
}
COUPLER = ("SP12-00161-00", 'SPRING ASSY CAST IRON COUPLER BLACK CANIMEX, 1-1/4" BORE')
W6_LH = ("SP12-00236-00", 'SPRING, WINDERS & STATIONARY PLUGS SET, 6", 1-1/4" BORE, LH')
W6_RH = ("SP12-00242-00", 'SPRING, WINDERS & STATIONARY PLUGS SET, 6", 1-1/4" BORE, RH')
PLUG375 = ("SP12-00174-00", 'SPRING ASSY PLUGS/STATIONARY, 3 3/4" (375), 1" & 1-1/4" BORE')
# group: (header seq, last seq, LH positions total, RH positions total)
GROUPS = {
    "24x24": (10000, 200000, 27, 27),
    "16x18": (210000, 480000, 32, 32),
    "14x14": (490000, 750000, 2, 2),
    "30x30": (760000, 930000, 16, 16),
    "20x20": (940000, 1130000, 24, 24),
}

q = bc_client.get_sales_quote_by_number("SQ-003183"); qid = q["id"]
lines = bc_client.get_quote_lines(qid)
bk = Path(__file__).with_name("sq003183_lines_backup_part5.json")
if not bk.exists(): bk.write_text(json.dumps(lines, indent=1, default=str))

def add(seq, ln):
    if ln[0] == "C":
        assert len(ln[1]) <= 100, ln[1]
        bc_client.add_quote_line(qid, {"lineType": "Comment", "description": ln[1], "sequence": seq})
    else:
        bc_client.add_quote_line(qid, {"lineType": "Item", "lineObjectNumber": ln[1], "quantity": ln[2], "description": ln[3], "sequence": seq})
    print(f"  add {seq} {ln[1][:80]}" + (f" x{ln[2]}" if ln[0] == "I" else ""))
def delete(l):
    bc_client.delete_quote_line(qid, l["id"]); print(f"  del {l['sequence']} {(l.get('lineObjectNumber') or l['description'])[:70]} x{l['quantity']}")

for g, (lo, hi, lh, rh) in GROUPS.items():
    print(f"=== {g} ===")
    grp = sorted((l for l in lines if lo <= l["sequence"] < hi), key=lambda l: l["sequence"])
    for l in grp:
        pn = l.get("lineObjectNumber") or ""
        desc = l.get("description") or ""
        qty = l["quantity"]; s = l["sequence"]
        if pn in SHAFT_MAP:
            delete(l); add(s + 500, ("I", SHAFT_MAP[pn][0], qty, SHAFT_MAP[pn][1]))
        elif pn == "SP12-00160-00":
            delete(l); add(s + 500, ("I", COUPLER[0], qty, COUPLER[1]))
        elif pn == "SP12-00234-01":
            assert qty == lh + rh, (g, qty, lh, rh)
            delete(l); add(s + 300, ("I", W6_LH[0], lh, W6_LH[1])); add(s + 600, ("I", W6_RH[0], rh, W6_RH[1]))
        elif pn == "SP12-00233-01":
            delete(l); add(s + 300, ("I", PLUG375[0], qty, PLUG375[1]))
            add(s + 600, ("C", f'3-3/4" WINDER 1-1/4" BORE x{int(qty)} - no BC SKU, office to source'))
        elif pn == "" and desc.startswith('6" WINDER SET 1-1/4" BORE'):      # 30x30 placeholder
            delete(l); add(s + 300, ("I", W6_LH[0], lh, W6_LH[1])); add(s + 600, ("I", W6_RH[0], rh, W6_RH[1]))
        elif pn == "" and desc.startswith('3-3/4" WINDER SET 1-1/4" BORE'):  # 30x30 placeholder
            n = lh + rh
            delete(l); add(s + 300, ("I", PLUG375[0], n, PLUG375[1]))
            add(s + 600, ("C", f'3-3/4" WINDER 1-1/4" BORE x{n} - no BC SKU, office to source'))
    # drum/bearing bore note right after the group header
    add(lo + 100, ("C", '1-1/4" SHAFT SYSTEM: drums + bearings (in HK kit) must be 1-1/4" bore - office to swap'))
