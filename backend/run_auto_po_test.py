"""Live test harness for the nightly auto-PO job.

Builds a throwaway local SQLite DB, refreshes the item->vendor map from BC,
then runs auto_po_service. Pass --commit to actually create Draft POs in
BC (default is dry-run: BC reads only, no writes, no snapshot changes).
"""
import argparse
import json
import sys

from app.db.database import engine, SessionLocal
from app.db.models import AutoPoSnapshot, POAgentLog, ItemVendorMap


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true", help="actually draft POs in BC")
    ap.add_argument("--seed", action="store_true", help="seed the snapshot first (mark backlog covered)")
    args = ap.parse_args()

    for t in (ItemVendorMap, POAgentLog, AutoPoSnapshot):
        try:
            t.__table__.create(engine)
        except Exception as e:
            print(f"    (table {t.__tablename__}: {e})")
    db = SessionLocal()

    from app.services.vendor_map_service import vendor_map_service
    from app.services.auto_po_service import auto_po_service

    print(">>> refreshing item->vendor map from BC ...")
    stats = vendor_map_service.refresh(db)
    db.commit()
    print("    vendor map:", stats)

    if args.seed:
        print(">>> seeding snapshot (marking current backlog as covered) ...")
        print("   ", auto_po_service.seed_snapshot(db))
        db.commit()

    dry = not args.commit
    print(f">>> running auto_po_service.run(dry_run={dry}) ...")
    result = auto_po_service.run(db, dry_run=dry)
    db.commit()

    # readable summary
    print("\n" + "=" * 70)
    print(f"run_id             {result['run_id']}")
    print(f"dry_run            {result['dry_run']}")
    print(f"horizon_weeks      {result['horizon_weeks']}")
    print(f"drafted PO count   {result['drafted_po_count']}")
    print(f"drafted lines      {result['drafted_line_count']}")
    print(f"drafted est cost   ${result['drafted_est_cost']:,.2f}")
    print(f"skipped            {result['skipped_counts']}")
    if result["errors"]:
        print(f"ERRORS             {result['errors']}")
    print("=" * 70)

    for d in result["drafts"]:
        tag = "[DRY]" if d.get("dry_run") else f"[BC {d.get('bc_po_number')}]"
        print(f"\n{tag} {d['vendor_name']} ({d['vendor_no']})  "
              f"~${d['estimated_cost']:,.2f}  SOs: {', '.join(d['sales_orders'])}")
        for ln in d["lines"]:
            alloc = ", ".join(f"{so} x{q:g}" for so, q in sorted(ln["per_so"].items()))
            print(f"    {ln['item_no']:<20} qty {ln['quantity']:<8g} @ ${ln['unit_cost']:<10,.2f} "
                  f"{ln.get('unit_of_measure','')}   [{alloc}]  {ln['description'][:40]}")

    # full skip detail
    print("\n--- skipped detail ---")
    for reason, rows in result["skipped"].items():
        print(f"  {reason}: {len(rows)}")
        for r in rows[:25]:
            print(f"      {r.get('item_no'):<20} new={r.get('new_demand')}  {r.get('description','')[:40]}"
                  + (f"  vendor={r.get('vendor_no')}" if r.get("vendor_no") else ""))

    with open("auto_po_test_result.json", "w") as f:
        json.dump(result, f, indent=2, default=str)
    print("\nfull result -> auto_po_test_result.json")


if __name__ == "__main__":
    sys.exit(main())
