"""Trace the cross-customer leak: Judy Frost (Global Overhead) sees a
BAKKE Buildings draft in Recent Drafts."""

from app.db.database import SessionLocal
from app.db.models import User, SavedQuoteConfig

JUDY_USER_ID = 76  # confirmed in prior run
BAKKE_DISPLAY = "BAKKE Buildings Inc"


def main():
    db = SessionLocal()

    judy = db.query(User).filter(User.id == JUDY_USER_ID).first()
    print(f"Judy: id={judy.id} email={judy.email} bc_customer_id={judy.bc_customer_id}")

    # Replicate _company_user_ids
    sibling_users = db.query(User).filter(
        User.bc_customer_id == judy.bc_customer_id,
        User.user_type == "CUSTOMER",
    ).all()
    print(f"\nUsers sharing Judy's bc_customer_id ({len(sibling_users)} total):")
    for u in sibling_users:
        print(
            f"  id={u.id} email={u.email!r} name={u.name!r} "
            f"account_type={u.account_type} customer_admin={u.is_customer_admin}"
        )

    # The exact query Recent Drafts runs
    sibling_ids = [u.id for u in sibling_users]
    if JUDY_USER_ID not in sibling_ids:
        sibling_ids.append(JUDY_USER_ID)
    configs = db.query(SavedQuoteConfig).filter(
        SavedQuoteConfig.user_id.in_(sibling_ids)
    ).order_by(SavedQuoteConfig.updated_at.desc().nullslast()).all()

    print(f"\nWhat Judy's Recent Drafts query returns ({len(configs)} configs):")
    for c in configs:
        u = db.query(User).filter(User.id == c.user_id).first()
        ue = u.email if u else "?"
        ub = u.bc_customer_id if u else "?"
        un = u.name if u else "?"
        print(
            f"  config_id={c.id} name={c.name!r} submitted={c.is_submitted} "
            f"updated={c.updated_at}\n"
            f"      owner: user_id={c.user_id} email={ue!r} name={un!r} bc_customer_id={ub}"
        )

    # Look for any user with BAKKE in name regardless of bc_customer_id
    print(f"\nAll users with BAKKE in their name:")
    bakke_users = db.query(User).filter(User.name.ilike("%bakke%")).all()
    for u in bakke_users:
        print(
            f"  id={u.id} email={u.email!r} name={u.name!r} "
            f"bc_customer_id={u.bc_customer_id} user_type={u.user_type}"
        )

    db.close()


if __name__ == "__main__":
    main()
