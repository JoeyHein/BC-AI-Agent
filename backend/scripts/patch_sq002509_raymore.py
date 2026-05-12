"""Patch the consolidated INSTALLATION line on SQ-002509 to include Raymore
travel ($578.7 km x $2 = $1157.40), and store installTown=Raymore on the
saved config so any future refresh-pricing keeps the travel charge."""

from sqlalchemy.orm.attributes import flag_modified

from app.db.database import SessionLocal
from app.db.models import SavedQuoteConfig
from app.integrations.bc.client import BusinessCentralClient
from app.services.install_pricing_service import install_pricing_service

NEW_TOWN = "Raymore"
NEW_TOTAL = 3435.40
NEW_DESC = "Installation - Raymore (384 sqft, 1 door(s))"


def main():
    db = SessionLocal()
    bc = BusinessCentralClient()

    quotes = bc._make_request(
        "GET",
        f"companies({bc.company_id})/salesQuotes?$filter=number eq 'SQ-002509'",
    ).get("value", [])
    q = quotes[0]
    qid = q["id"]

    # Find the single INSTALLATION line that should exist after cleanup.
    install_lines = [
        l for l in bc.get_quote_lines(qid)
        if (l.get("lineObjectNumber") or "").strip().upper() == "INSTALLATION"
    ]
    if len(install_lines) != 1:
        print(f"Expected exactly 1 INSTALLATION line; found {len(install_lines)}. Aborting.")
        for l in install_lines:
            print(f"  seq={l.get('sequence')} {l.get('description')!r}")
        return
    line = install_lines[0]
    print(f"Patching line seq={line.get('sequence')} id={line['id']}")
    print(f"  before: ${line.get('unitPrice', 0):.2f}  {line.get('description')!r}")

    etag = line.get("@odata.etag", "*")
    bc.update_quote_line(qid, line["id"], etag, {
        "unitPrice": NEW_TOTAL,
        "description": NEW_DESC[:100],
    })
    print(f"  after:  ${NEW_TOTAL:.2f}  {NEW_DESC!r}")

    # Write installTown=Raymore back into the saved config so a future edit
    # recomputes travel automatically instead of falling back to 0.
    config = db.query(SavedQuoteConfig).filter(
        SavedQuoteConfig.bc_quote_number == "SQ-002509"
    ).first()
    if config and config.config_data:
        cd = dict(config.config_data)
        doors = list(cd.get("doors") or [])
        if doors:
            doors[0] = {**doors[0], "installTown": NEW_TOWN}
            cd["doors"] = doors
            config.config_data = cd
            flag_modified(config, "config_data")
            db.commit()
            print(f"  saved config[doors[0].installTown] -> {NEW_TOWN!r}")
        else:
            print("  no doors in saved config — could not persist town")
    else:
        print("  saved config not found")

    final = bc.get_sales_quote(qid)
    print(f"\nFinal SQ-002509 total: ${final.get('totalAmountIncludingTax', 0):.2f}")
    db.close()


if __name__ == "__main__":
    main()
