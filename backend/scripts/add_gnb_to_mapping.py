"""
Add GNB to the BC group -> portal tier mapping. Idempotent — safe to re-run.
Also tags the local BCCustomer 'GNB Doors' record with bc_price_group='GNB'
and pricing_tier='gnb' so the diagnostic resolves it correctly even before
BC's customer record is updated to point at the new Customer Price Group.
"""
from datetime import datetime
from app.db.database import SessionLocal
from app.db.models import AppSettings, BCCustomer
from app.services.pricing_service import BC_GROUP_MAPPING_KEY


def main():
    db = SessionLocal()
    try:
        setting = db.query(AppSettings).filter(
            AppSettings.setting_key == BC_GROUP_MAPPING_KEY
        ).first()
        old = dict(setting.setting_value) if setting and setting.setting_value else {}
        new = dict(old)
        new["GNB"] = "gnb"

        if old == new:
            print(f"Mapping already has GNB. Current: {new}")
        else:
            if setting:
                setting.setting_value = new
                setting.updated_at = datetime.utcnow()
            else:
                setting = AppSettings(
                    setting_key=BC_GROUP_MAPPING_KEY,
                    setting_value=new,
                    description="BC customer price group code -> portal pricing tier",
                    updated_at=datetime.utcnow(),
                )
                db.add(setting)
            db.commit()
            print(f"Mapping updated. Old: {old}")
            print(f"             New: {new}")

        # Tag GNB Doors locally so diagnostic resolves it
        gnb = db.query(BCCustomer).filter(
            BCCustomer.company_name.ilike("%GNB%")
        ).all()
        for c in gnb:
            print(f"\nGNB customer in cache: id={c.bc_customer_id} name={c.company_name!r} "
                  f"old_group={c.bc_price_group!r} old_tier={c.pricing_tier!r}")
            c.bc_price_group = "GNB"
            c.pricing_tier = "gnb"
            c.updated_at = datetime.utcnow()
        if gnb:
            db.commit()
            print(f"\nTagged {len(gnb)} GNB customer record(s) locally.")
        else:
            print("\nNo GNB customer found in local cache.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
