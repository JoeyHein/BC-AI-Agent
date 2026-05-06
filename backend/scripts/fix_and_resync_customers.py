"""
1. Replace the broken bc_group_tier_mapping (BD/JH sales-rep codes from a
   prior misconfiguration) with the real BC Customer_Price_Group codes.
2. Run the customer sync against live BC.
3. Report the resulting tier distribution + flag any customers still empty.
"""
import asyncio
import json
from collections import Counter
from datetime import datetime

from app.db.database import SessionLocal
from app.db.models import AppSettings, BCCustomer
from app.services.bc_sync_service import BCSyncService
from app.services.pricing_service import BC_GROUP_MAPPING_KEY


# BC group code -> portal tier. OPIN is BC's "list pricing" reference; no
# customers are assigned to it currently, so it stays out of the active
# mapping. UNLI -> unlisted is the placeholder tier for new/unassigned.
CORRECT_MAPPING = {
    "PLAT": "platinum",
    "GOLD": "gold",
    "SILV": "silver",
    "BRON": "bronze",
    "UNLI": "unlisted",
    "OPIN": "retail",
}


def replace_mapping(db):
    setting = db.query(AppSettings).filter(
        AppSettings.setting_key == BC_GROUP_MAPPING_KEY
    ).first()
    old = setting.setting_value if setting else None
    if setting:
        setting.setting_value = CORRECT_MAPPING
        setting.updated_at = datetime.utcnow()
    else:
        setting = AppSettings(
            setting_key=BC_GROUP_MAPPING_KEY,
            setting_value=CORRECT_MAPPING,
            description="BC customer price group code -> portal pricing tier",
            updated_at=datetime.utcnow(),
        )
        db.add(setting)
    db.commit()
    print(f"Mapping updated. Old: {old}")
    print(f"             New: {CORRECT_MAPPING}\n")


async def main():
    db = SessionLocal()
    try:
        replace_mapping(db)

        print("Running customer sync (api/v2.0 + OData V4 enrichment)...")
        svc = BCSyncService()
        result = await svc.sync_customers(db)
        print(json.dumps(result, indent=2, default=str))
        print()

        # Refresh from DB and report
        rows = db.query(BCCustomer).all()
        print(f"BCCustomer rows in local cache: {len(rows)}")
        groups = Counter((r.bc_price_group or "<empty>") for r in rows)
        tiers = Counter((r.pricing_tier or "<empty>") for r in rows)
        print("bc_price_group distribution:")
        for k, v in groups.most_common():
            print(f"  {k!r:15} {v}")
        print("pricing_tier distribution:")
        for k, v in tiers.most_common():
            print(f"  {k!r:15} {v}")

        empty_post = [r for r in rows if not r.bc_price_group]
        print(f"\nStill missing bc_price_group: {len(empty_post)}")
        for r in empty_post:
            print(f"  {r.company_name}")
    finally:
        db.close()


if __name__ == "__main__":
    asyncio.run(main())
