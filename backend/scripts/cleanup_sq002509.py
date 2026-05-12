"""Clean up SQ-002509: delete its multi-line install block + replace with a
single consolidated INSTALLATION line that includes Raymore travel."""

from sqlalchemy.orm.attributes import flag_modified

from app.db.database import SessionLocal
from app.db.models import SavedQuoteConfig
from app.integrations.bc.client import BusinessCentralClient
from app.services.install_pricing_service import install_pricing_service


def main():
    db = SessionLocal()
    bc = BusinessCentralClient()

    quotes = bc._make_request(
        "GET",
        f"companies({bc.company_id})/salesQuotes?$filter=number eq 'SQ-002509'",
    ).get("value", [])
    if not quotes:
        print("SQ-002509 not found in BC")
        return
    q = quotes[0]
    qid = q["id"]
    print(f"SQ-002509 id={qid}")

    config = db.query(SavedQuoteConfig).filter(
        SavedQuoteConfig.bc_quote_number == "SQ-002509"
    ).first()
    if not config:
        print("No SavedQuoteConfig — cannot reconstruct doors. Aborting.")
        return

    doors = (config.config_data or {}).get("doors", [])
    install_town = doors[0].get("installTown") if doors else None
    print(f"  saved town: {install_town!r}")
    print(f"  saved doors: {len(doors)}")

    # Recompute install with the new model (will hit Google for Raymore).
    install_result = install_pricing_service.calculate_total_install_price(
        customer_id=config.user_id,
        doors=doors,
        town=install_town,
        db=db,
    )
    print(
        f"  recomputed install: ${install_result['grand_total']:.2f} "
        f"(base ${install_result['base_install_price']}, "
        f"lift ${install_result['lift_total']}, "
        f"per diem ${install_result['per_diem_total']}, "
        f"operator ${install_result['operator_addon_total']}, "
        f"travel ${install_result['travel_price']} via {install_result['travel_source']})"
    )

    # Delete the existing install block lines on BC (lineObjectNumber=INSTALLATION
    # plus any Comment line beginning with "INSTALLATION").
    lines = bc.get_quote_lines(qid)
    victims = []
    for l in lines:
        pn = (l.get("lineObjectNumber") or "").strip().upper()
        desc = (l.get("description") or "").strip()
        if pn == "INSTALLATION":
            victims.append(l)
        elif l.get("lineType") == "Comment" and desc.upper().startswith("INSTALLATION"):
            victims.append(l)
    print(f"  deleting {len(victims)} stale install line(s)")
    deleted_ids = set()
    for l in victims:
        try:
            bc.delete_quote_line(qid, l["id"])
            deleted_ids.add(l["id"])
            print(f"    deleted seq={l.get('sequence')} desc={(l.get('description') or '')[:60]}")
        except Exception as e:
            print(f"    FAILED seq={l.get('sequence')}: {e}")

    # Add one consolidated INSTALLATION line.
    sqft = install_result["total_sqft"]
    door_count = install_result["door_count_total"]
    town = install_result.get("town")
    desc = f"Installation - {town} ({sqft:.0f} sqft, {door_count} door(s))" if town \
           else f"Installation ({sqft:.0f} sqft, {door_count} door(s))"
    new_line = bc.add_quote_line(qid, {
        "lineType": "Item",
        "lineObjectNumber": "INSTALLATION",
        "description": desc[:100],
        "quantity": 1,
    })
    etag = new_line.get("@odata.etag", "*")
    bc.update_quote_line(qid, new_line["id"], etag, {"unitPrice": install_result["grand_total"]})
    print(f"  added consolidated INSTALLATION: ${install_result['grand_total']:.2f}")

    # Flip Output=true so it prints on the quote.
    seq = new_line.get("sequence")
    if seq:
        try:
            bc.set_quote_line_output(q["number"], seq, output=True)
        except Exception as e:
            print(f"  could not set Output flag: {e}")

    # Update line_map.shared.install to track only the new line.
    lm = config.bc_line_map or {"doors": {}, "shared": {}}
    lm.setdefault("shared", {})
    existing_install_ids = lm["shared"].get("install", [])
    kept = [i for i in existing_install_ids if i not in deleted_ids]
    kept.append(new_line["id"])
    lm["shared"]["install"] = kept
    config.bc_line_map = lm
    flag_modified(config, "bc_line_map")
    db.commit()
    print(f"  line_map.shared.install -> {len(kept)} id(s)")

    final = bc.get_sales_quote(qid)
    print(f"  final total: ${final.get('totalAmountIncludingTax', 0):.2f}")
    db.close()


if __name__ == "__main__":
    main()
