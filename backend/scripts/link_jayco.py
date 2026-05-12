"""Link braden@jaycobuilders.ca to the real Jayco Builders Inc BC customer.

Replaces the TEMP- placeholder bc_customer_id on the user, and ensures a
local BCCustomer row exists (needed for things like the freight province
lookup that consult bc_customers.address)."""

from sqlalchemy.orm.attributes import flag_modified

from app.db.database import SessionLocal
from app.db.models import User, BCCustomer
from app.integrations.bc.client import BusinessCentralClient

USER_ID = 79
NEW_BC_CUSTOMER_ID = "3e8507e6-9e14-f011-9346-6045bd613a61"


def main():
    db = SessionLocal()
    bc = BusinessCentralClient()

    # Fetch the canonical BC customer record so we can mirror it into the
    # local BCCustomer table if it's not already there.
    cust = bc._make_request(
        "GET", f"companies({bc.company_id})/customers({NEW_BC_CUSTOMER_ID})"
    )
    print(f"BC customer fetched: number={cust.get('number')} displayName={cust.get('displayName')!r}")

    # Upsert local BCCustomer row.
    existing = (
        db.query(BCCustomer)
        .filter(BCCustomer.bc_customer_id == NEW_BC_CUSTOMER_ID)
        .first()
    )
    if existing:
        print(f"BCCustomer row already exists (id={existing.id})")
    else:
        address = cust.get("address") or {}
        new_row = BCCustomer(
            bc_customer_id=NEW_BC_CUSTOMER_ID,
            customer_number=cust.get("number"),
            display_name=cust.get("displayName"),
            email=cust.get("email") or None,
            address=address,
        )
        db.add(new_row)
        db.flush()
        print(f"Created local BCCustomer row id={new_row.id}")

    # Link user 79.
    user = db.query(User).filter(User.id == USER_ID).first()
    if not user:
        print(f"User {USER_ID} not found — aborting")
        return
    print(f"Before: user {user.id} bc_customer_id={user.bc_customer_id!r}")
    user.bc_customer_id = NEW_BC_CUSTOMER_ID
    db.commit()
    db.refresh(user)
    print(f"After:  user {user.id} bc_customer_id={user.bc_customer_id!r}")
    db.close()


if __name__ == "__main__":
    main()
