"""Delete the stray comment-fallback line at seq=180000 on SQ-002503."""

from sqlalchemy.orm.attributes import flag_modified

from app.db.database import SessionLocal
from app.db.models import SavedQuoteConfig
from app.integrations.bc.client import BusinessCentralClient


def main():
    db = SessionLocal()
    bc = BusinessCentralClient()
    c = db.query(SavedQuoteConfig).filter(SavedQuoteConfig.id == 60).first()

    lines = bc.get_quote_lines(c.bc_quote_id)
    targets = [l for l in lines if l.get("sequence") == 180000]
    if not targets:
        print("Nothing at seq=180000")
        return

    target = targets[0]
    print(f"Deleting stray line id={target['id']}")
    print(f"  desc: {(target.get('description') or '')[:80]}")
    bc.delete_quote_line(c.bc_quote_id, target["id"])

    lm = c.bc_line_map or {"doors": {}, "shared": {}}
    if target["id"] in lm.get("doors", {}).get("2", []):
        lm["doors"]["2"].remove(target["id"])
    c.bc_line_map = lm
    flag_modified(c, "bc_line_map")
    db.commit()
    print(f"line_map.doors[2] now has {len(lm['doors']['2'])} ids")

    q = bc.get_sales_quote(c.bc_quote_id)
    print(f"Final total: ${q.get('totalAmountIncludingTax', 0):.2f}")
    db.close()


if __name__ == "__main__":
    main()
