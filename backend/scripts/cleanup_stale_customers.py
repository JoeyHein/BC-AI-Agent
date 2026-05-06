"""Show & clean up stale BCCustomer rows that didn't survive the OData V4 sync."""
import requests
from app.db.database import SessionLocal
from app.db.models import BCCustomer
from app.integrations.bc.client import BusinessCentralClient


def main():
    bc = BusinessCentralClient()
    seg = bc._odata_v4_company_segment(None)
    headers = {"Authorization": f"Bearer {bc._get_access_token()}", "Accept": "application/json"}

    db = SessionLocal()
    try:
        # Show all rows with bc_price_group still set to legacy values (BD/JH)
        # or NULL and let user decide what to do
        legacy = db.query(BCCustomer).filter(
            BCCustomer.bc_price_group.in_(["BD", "JH"])
        ).all()
        print(f"Legacy-coded rows (BD/JH from old sync): {len(legacy)}")
        for r in legacy:
            print(f"  id={r.bc_customer_id} name={r.company_name!r} group={r.bc_price_group} tier={r.pricing_tier}")

        empty = db.query(BCCustomer).filter(
            (BCCustomer.bc_price_group.is_(None)) | (BCCustomer.bc_price_group == "")
        ).all()
        print(f"\nEmpty bc_price_group rows: {len(empty)}")
        for r in empty:
            print(f"  name={r.company_name!r} tier={r.pricing_tier}")

        # Clear the legacy BD/JH values — they're stale references to a sales-rep
        # field that was incorrectly used as a price group. Keep tier untouched
        # so admin can reassign manually.
        if legacy:
            for r in legacy:
                r.bc_price_group = None
            db.commit()
            print(f"\nCleared bc_price_group on {len(legacy)} legacy rows.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
