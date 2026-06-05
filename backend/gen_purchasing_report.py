"""Generate a standalone 'what we have vs what to order' purchasing report (HTML).

Read-only: computes live requirements and writes an HTML file. Does NOT email.
"""
import sys
from datetime import datetime

from app.db.database import SessionLocal
from app.services.purchasing_demand_service import purchasing_demand_service, UNASSIGNED


def main(out_path: str):
    db = SessionLocal()
    try:
        r = purchasing_demand_service.compute_requirements(db, include_met=False)
    finally:
        db.close()
    s = r["summary"]
    when = datetime.utcnow().strftime("%A, %B %d, %Y · %H:%M UTC")

    rows_html = []
    for g in r["vendors"]:
        unassigned = g["vendor_name"] == UNASSIGNED
        color = "#b91c1c" if unassigned else "#1f2937"
        note = " — no vendor on item card / no purchase history; assign in portal" if unassigned else ""
        rows_html.append(
            f"<tr><td colspan='8' style='background:#f9fafb;color:{color};font-weight:700;"
            f"padding:10px 8px;border-top:2px solid #e5e7eb'>{g['vendor_name']} "
            f"<span style='font-weight:400;color:#6b7280'>· {g['item_count']} item(s) · "
            f"${g['estimated_cost']:,.2f}{note}</span></td></tr>"
        )
        for it in g["items"]:
            est = it["net_need"] * it["unit_cost"]
            jobs = ", ".join(it["jobs"][:4]) + ("…" if len(it["jobs"]) > 4 else "")
            rows_html.append(
                f"<tr style='border-top:1px solid #f3f4f6'>"
                f"<td style='font-family:monospace;padding:4px 8px'>{it['item_no']}</td>"
                f"<td style='padding:4px 8px'>{it['description']}</td>"
                f"<td style='text-align:right;padding:4px 8px'>{it['demand']:g}</td>"
                f"<td style='text-align:right;padding:4px 8px;color:#059669'>{it['on_hand']:g}</td>"
                f"<td style='text-align:right;padding:4px 8px;color:#2563eb'>{it['on_order']:g}</td>"
                f"<td style='text-align:right;padding:4px 8px;font-weight:700'>{it['net_need']:g} {it['unit_of_measure']}</td>"
                f"<td style='text-align:right;padding:4px 8px'>${it['unit_cost']:,.2f}</td>"
                f"<td style='padding:4px 8px;color:#6b7280'>{jobs}</td></tr>"
            )

    prod = ("Included" if r.get("production_included") else
            "<span style='color:#b91c1c'>NOT included</span>")
    html = f"""<!doctype html><meta charset="utf-8">
<title>OPENDC Purchasing Report — {when}</title>
<div style="font-family:-apple-system,Segoe UI,Arial,sans-serif;max-width:1000px;margin:24px auto;color:#111827">
  <h1 style="margin:0 0 2px">OPENDC Purchasing Report</h1>
  <p style="color:#6b7280;margin:0 0 16px;font-size:13px">{when} · Production-order demand: {prod}</p>
  <div style="display:flex;gap:16px;margin:16px 0">
    <div style="flex:1;background:#f3f4f6;border-radius:8px;padding:14px"><div style="font-size:24px;font-weight:700">{s['shortfall_items']}</div><div style="font-size:12px;color:#6b7280">Items to order</div></div>
    <div style="flex:1;background:#f3f4f6;border-radius:8px;padding:14px"><div style="font-size:24px;font-weight:700">{s['vendor_count']}</div><div style="font-size:12px;color:#6b7280">Vendors</div></div>
    <div style="flex:1;background:#f3f4f6;border-radius:8px;padding:14px"><div style="font-size:24px;font-weight:700">{s['unassigned_items']}</div><div style="font-size:12px;color:#6b7280">Unassigned items</div></div>
    <div style="flex:1;background:#f3f4f6;border-radius:8px;padding:14px"><div style="font-size:24px;font-weight:700">${s['estimated_cost']:,.0f}</div><div style="font-size:12px;color:#6b7280">Est. spend</div></div>
  </div>
  <p style="font-size:12px;color:#6b7280;margin:4px 0 12px">
    <b>Demand</b> = open sales orders + released production-order components ·
    <b>On Hand</b> = current stock · <b>On Order</b> = open POs ·
    <b>Net Need</b> = Demand − On Hand − On Order (what to buy)
  </p>
  <table style="width:100%;border-collapse:collapse;font-size:13px">
    <tr style="text-align:left;color:#6b7280;font-size:12px">
      <th style="padding:6px 8px">Item</th><th style="padding:6px 8px">Description</th>
      <th style="padding:6px 8px;text-align:right">Demand</th>
      <th style="padding:6px 8px;text-align:right">On Hand</th>
      <th style="padding:6px 8px;text-align:right">On Order</th>
      <th style="padding:6px 8px;text-align:right">Net Need</th>
      <th style="padding:6px 8px;text-align:right">Unit Cost</th>
      <th style="padding:6px 8px">Jobs</th></tr>
    {''.join(rows_html)}
  </table>
  <p style="margin:20px 0;font-size:13px"><a href="https://portal.opendc.ca/purchasing" style="color:#2563eb">Open the live Purchasing tool →</a></p>
</div>"""

    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Wrote {out_path}")
    print(f"  items_to_order={s['shortfall_items']} vendors={s['vendor_count']} "
          f"unassigned={s['unassigned_items']} est_spend=${s['estimated_cost']:,.2f}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "purchasing_report.html")
