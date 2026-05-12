"""Investigate Jayco TEMP- placeholder bc_customer_id."""

from app.db.database import SessionLocal
from app.db.models import User, BCCustomer
from app.integrations.bc.client import BusinessCentralClient


def main():
    db = SessionLocal()
    print("=== Jayco / braden users ===")
    users = (
        db.query(User)
        .filter(
            (User.email.ilike("%jayco%"))
            | (User.email.ilike("%braden%"))
        )
        .all()
    )
    for u in users:
        print(
            f"  id={u.id} email={u.email!r} name={u.name!r} "
            f"bc_customer_id={u.bc_customer_id!r} "
            f"account_type={u.account_type} status={u.account_status}"
        )

    print()
    print("=== BC customers with Jayco in displayName ===")
    bc = BusinessCentralClient()
    res = bc._make_request(
        "GET",
        f"companies({bc.company_id})/customers?$filter=contains(displayName,'Jayco')",
    ).get("value", [])
    for c in res[:10]:
        print(
            f"  number={c.get('number')} "
            f"displayName={c.get('displayName')!r} "
            f"id={c.get('id')} "
            f"email={c.get('email')}"
        )

    print()
    print("=== Other users with TEMP- bc_customer_id (same gap, will hit the same error) ===")
    temp_users = db.query(User).filter(User.bc_customer_id.like("TEMP-%")).all()
    for u in temp_users:
        print(
            f"  id={u.id} email={u.email!r} bc_customer_id={u.bc_customer_id!r} "
            f"account_type={u.account_type} status={u.account_status}"
        )
    db.close()


if __name__ == "__main__":
    main()
