"""
Generate the GNB Customer Price Group price list for BC SalesPriceLists.

For every BC item with unitCost > 0, produces a row priced at the base
30%-GM list (cost × 1.4286). The volume-escalation curve in
escalating_margin_service.py continues to apply at quote-creation time
on top of these list prices (Option A — hybrid).

Outputs:
  data/gnb_price_list/gnb_price_list_{YYYYMMDD}.json — full review/audit trail
  data/gnb_price_list/gnb_price_list_{YYYYMMDD}.csv  — ready for BC import

Does NOT write to BC. Review the files, then import via BC's data
import tool (Configuration Package or Excel import).
"""
import csv
import json
from datetime import datetime
from pathlib import Path
from app.integrations.bc.client import BusinessCentralClient


PRICE_LIST_CODE = "GNB-01"
SOURCE_TYPE = "Customer Price Group"
ASSIGN_TO_NO = "GNB"

# Pricing rules for GNB:
#   - ALUM posting group  -> standard gold-tier aluminum margin (49% GM).
#     Aluminum is NOT subject to the volume escalation curve.
#   - Everything else     -> base 30% GM list. The volume curve in
#     escalating_margin_service.py applies on top at quote-creation time.
GRID_GM_PCT = 30.0
GRID_MULTIPLIER = 1 / (1 - GRID_GM_PCT / 100)        # 1.428571...
ALUM_GM_PCT = 49.0
ALUM_MULTIPLIER = 1 / (1 - ALUM_GM_PCT / 100)        # 1.960784...

OUTPUT_DIR = Path(__file__).parent.parent / "data" / "gnb_price_list"


def main():
    bc = BusinessCentralClient()
    print("Fetching all BC items (paginated)...")
    items = bc.get_all_items(
        select="number,displayName,unitCost,unitPrice,generalProductPostingGroupCode,baseUnitOfMeasureId,blocked"
    )
    print(f"Total items in BC: {len(items)}")

    # Build the price list rows
    rows = []
    skipped_no_cost = 0
    skipped_blocked = 0
    today = datetime.utcnow().strftime("%Y-%m-%d")

    for item in items:
        if item.get("blocked"):
            skipped_blocked += 1
            continue
        cost = item.get("unitCost") or 0
        if cost <= 0:
            skipped_no_cost += 1
            continue
        posting_group = item.get("generalProductPostingGroupCode", "")
        if posting_group == "ALUM":
            multiplier = ALUM_MULTIPLIER
            basis = "alum_gold_49"
        else:
            multiplier = GRID_MULTIPLIER
            basis = "gnb_grid_30"
        gnb_price = round(cost * multiplier, 2)
        rows.append({
            "Price_List_Code": PRICE_LIST_CODE,
            "Source_Type": SOURCE_TYPE,
            "Assign_to_No": ASSIGN_TO_NO,
            "Product_No": item["number"],
            "Description": item.get("displayName", ""),
            "Unit_Cost": cost,
            "Unit_Price": gnb_price,
            "Line_Discount_Percent": 0,
            "Minimum_Quantity": 0,
            "Starting_Date": today,
            "Ending_Date": "",  # open-ended
            "Posting_Group": posting_group,
            "Pricing_Basis": basis,
        })

    print(f"Priced rows: {len(rows)}")
    print(f"Skipped (cost <= 0): {skipped_no_cost}")
    print(f"Skipped (blocked): {skipped_blocked}")
    from collections import Counter
    by_basis = Counter(r["Pricing_Basis"] for r in rows)
    print(f"Rows by pricing basis: {dict(by_basis)}")

    # Stats by posting group (so we can see distribution vs current 73k Customer
    # Price Group lines per existing tier)
    by_group = Counter(r["Posting_Group"] or "<empty>" for r in rows)
    print("\nPriced rows by posting group:")
    for g, n in by_group.most_common():
        print(f"  {g!r:15} {n}")

    # Sample output for sanity check
    print("\nSample 5 rows (sorted by Unit_Price desc):")
    for r in sorted(rows, key=lambda x: -x["Unit_Price"])[:5]:
        print(f"  {r['Product_No']:25} cost=${r['Unit_Cost']:>10.2f}  "
              f"-> GNB price=${r['Unit_Price']:>10.2f}  ({r['Description'][:50]})")
    print("\nSample 5 rows (sorted by Unit_Price asc, cost > 0):")
    for r in sorted(rows, key=lambda x: x["Unit_Price"])[:5]:
        print(f"  {r['Product_No']:25} cost=${r['Unit_Cost']:>10.2f}  "
              f"-> GNB price=${r['Unit_Price']:>10.2f}  ({r['Description'][:50]})")

    # Write outputs
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")

    json_path = OUTPUT_DIR / f"gnb_price_list_{stamp}.json"
    with json_path.open("w", encoding="utf-8") as f:
        json.dump({
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "price_list_code": PRICE_LIST_CODE,
            "source_type": SOURCE_TYPE,
            "assign_to_no": ASSIGN_TO_NO,
            "grid_gm_pct": GRID_GM_PCT,
            "grid_multiplier": round(GRID_MULTIPLIER, 6),
            "alum_gm_pct": ALUM_GM_PCT,
            "alum_multiplier": round(ALUM_MULTIPLIER, 6),
            "total_items_in_bc": len(items),
            "priced_rows": len(rows),
            "skipped_no_cost": skipped_no_cost,
            "skipped_blocked": skipped_blocked,
            "rows": rows,
        }, f, indent=2, default=str)
    print(f"\nWrote review JSON: {json_path}")

    csv_path = OUTPUT_DIR / f"gnb_price_list_{stamp}.csv"
    fieldnames = [
        "Price_List_Code", "Source_Type", "Assign_to_No", "Product_No",
        "Description", "Unit_Cost", "Unit_Price", "Line_Discount_Percent",
        "Minimum_Quantity", "Starting_Date", "Ending_Date", "Posting_Group",
        "Pricing_Basis",
    ]
    with csv_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in rows:
            writer.writerow(r)
    print(f"Wrote BC import CSV: {csv_path}")


if __name__ == "__main__":
    main()
