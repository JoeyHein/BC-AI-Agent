"""SQ-003183 part 5b: the short 1-1/4" SH10 lengths (7', 7'10", 9'11") have no
price for GNB; quote priced 19' stock (SH10-21900-00) cut to the original
piece lengths instead (2 pieces per stick), with a cut-list comment per group.
"""
import json, sys
from pathlib import Path
for _s in (sys.stdout, sys.stderr):
    try: _s.reconfigure(encoding="utf-8")
    except Exception: pass
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.integrations.bc.client import bc_client

STICK = ("SH10-21900-00", 'SOLID 1-1/4" KEYED SHAFT, 19\'')
PLAN = {  # zero-priced seqs to remove -> (insert seq, sticks, cut list)
    "24x24": ([154500, 156500], 154500, 27, "CUT 27x 19' 1-1/4\" stock -> 54 pcs @ 8'6\" (2/stick)"),
    "16x18": ([368500, 371500], 368500, 32, "CUT 32x 19' 1-1/4\" stock -> 32 @ 8'6\" + 32 @ 9'6\" (1 each/stick)"),
    "14x14": ([691500, 701500], 691500, 2,  "CUT 2x 19' 1-1/4\" stock -> 2 @ 7'6\" + 2 @ 8'6\" (1 each/stick)"),
    "20x20": ([1080500, 1082500], 1080500, 24, "CUT 24x 19' 1-1/4\" stock -> 32 @ 6'6\" + 16 @ 8'6\""),
}
q = bc_client.get_sales_quote_by_number("SQ-003183"); qid = q["id"]
lines = bc_client.get_quote_lines(qid)
bk = Path(__file__).with_name("sq003183_lines_backup_part5b.json")
if not bk.exists(): bk.write_text(json.dumps(lines, indent=1, default=str))
by_seq = {l["sequence"]: l for l in lines}
for g, (dels, at, n, cut) in PLAN.items():
    print(f"=== {g} ===")
    for s in dels:
        l = by_seq[s]; assert l["lineObjectNumber"].startswith("SH10-") and l["unitPrice"] == 0, l
        bc_client.delete_quote_line(qid, l["id"]); print(f"  del {s} {l['lineObjectNumber']} x{l['quantity']}")
    assert len(cut) <= 100
    bc_client.add_quote_line(qid, {"lineType": "Item", "lineObjectNumber": STICK[0], "quantity": n, "description": STICK[1], "sequence": at + 100})
    bc_client.add_quote_line(qid, {"lineType": "Comment", "description": cut, "sequence": at + 200})
    print(f"  add {at+100} {STICK[0]} x{n}\n  add {at+200} {cut}")
