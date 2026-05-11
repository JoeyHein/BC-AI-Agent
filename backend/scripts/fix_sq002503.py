"""
One-off cleanup for SQ-002503 (config id=60, customer ABES).

Door 2 on the BC quote is broken: missing door description, missing both
PL10-00141-00 retainers, ASTRAGAL downgraded to a comment fallback. The
saved line_map.doors[2] also holds 17 ghost IDs pointing at lines BC
deleted during an earlier edit (root cause: SQLAlchemy JSON column
mutation tracking — fixed separately in models.py).

This script:
  1. Deletes every line on BC starting from sequence 170000 (the door-2
     block) through to the freight line.
  2. Regenerates door 2 cleanly via get_parts_for_door_config, mirroring
     _edit_bc_quote_lines step 4.
  3. Recalculates and re-adds freight.
  4. Rewrites line_map.doors[2] and line_map.shared.freight with the
     real new BC line IDs, then flag_modified + commit.
"""

import sys
from typing import List

from sqlalchemy.orm.attributes import flag_modified

from app.db.database import SessionLocal
from app.db.models import SavedQuoteConfig, BCCustomer
from app.integrations.bc.client import BusinessCentralClient
from app.api.customer_portal import (
    _build_door_config_dict,
    _format_door_description,
    _sort_parts_by_category,
)
from app.services.part_number_service import get_parts_for_door_config
from app.services.spring_data_service import get_bc_spring_inventory
from app.services.freight_service import calculate_freight, get_freight_config

CONFIG_ID = 60
DOOR_INDEX = 2  # 1-based; door 2 is the broken one


def main():
    db = SessionLocal()
    bc = BusinessCentralClient()

    config = db.query(SavedQuoteConfig).filter(SavedQuoteConfig.id == CONFIG_ID).first()
    if not config:
        sys.exit(f"config id={CONFIG_ID} not found")
    print(f"Config {config.id} bc_quote={config.bc_quote_number} bc_quote_id={config.bc_quote_id}")

    doors = (config.config_data or {}).get("doors", [])
    if len(doors) < DOOR_INDEX:
        sys.exit(f"config only has {len(doors)} doors, can't fix door {DOOR_INDEX}")
    door = doors[DOOR_INDEX - 1]

    bc_quote_id = config.bc_quote_id
    lines = bc.get_quote_lines(bc_quote_id)
    print(f"Current BC line count: {len(lines)}")

    # Anything at sequence >= 170000 is broken door-2 content + freight
    DOOR2_START_SEQ = 170000
    victims = [l for l in lines if (l.get("sequence") or 0) >= DOOR2_START_SEQ]
    print(f"Deleting {len(victims)} lines (door-2 block + freight)...")
    for l in victims:
        try:
            bc.delete_quote_line(bc_quote_id, l["id"])
            print(f"  deleted seq={l['sequence']} {l.get('lineObjectNumber') or l.get('lineType')}")
        except Exception as e:
            print(f"  FAILED seq={l['sequence']} id={l['id']}: {e}")

    # Regen door 2 — mirror _edit_bc_quote_lines step 4
    print(f"\nRegenerating door {DOOR_INDEX}...")
    door_desc = _format_door_description(door)
    config_dict = _build_door_config_dict(door)

    spring_inventory = get_bc_spring_inventory()
    door_parts = get_parts_for_door_config(config_dict, spring_inventory=spring_inventory)
    parts_list = door_parts.get("parts_list", [])
    sorted_parts = _sort_parts_by_category(parts_list)

    new_door_lines: List[str] = []

    # 1. Door description Comment
    head = bc.add_quote_line(bc_quote_id, {"lineType": "Comment", "description": door_desc})
    if head.get("id"):
        new_door_lines.append(head["id"])
        print(f"  + Comment (door desc): {door_desc[:60]}")

    # 2. Parts (Item lines + spring/highlift Comments)
    for part in sorted_parts:
        cat = part.get("category", "")
        if cat in ("spring_comment", "highlift_comment"):
            r = bc.add_quote_line(bc_quote_id, {"lineType": "Comment", "description": part["description"]})
            if r.get("id"):
                new_door_lines.append(r["id"])
                print(f"  + Comment: {part['description'][:60]}")
            continue

        line_data = {
            "lineType": "Item",
            "lineObjectNumber": part["part_number"],
            "description": part.get("description", ""),
            "quantity": part["quantity"],
        }
        try:
            r = bc.add_quote_line(bc_quote_id, line_data)
            # Always restore our description (BC overwrites with item-card displayName)
            intended_desc = part.get("description", "")
            if intended_desc and r.get("description", "") != intended_desc:
                try:
                    etag = r.get("@odata.etag", "*")
                    bc.update_quote_line(bc_quote_id, r["id"], etag, {"description": intended_desc[:100]})
                except Exception as pe:
                    print(f"  desc PATCH failed for {part['part_number']}: {pe}")
            if r.get("id"):
                new_door_lines.append(r["id"])
                print(f"  + Item {part['part_number']:25} qty={part['quantity']}")

            # Add window placement note Comment immediately after the window
            if part.get("notes") and cat in ("window", "commercial_window"):
                nr = bc.add_quote_line(bc_quote_id, {"lineType": "Comment", "description": part["notes"]})
                if nr.get("id"):
                    new_door_lines.append(nr["id"])
        except Exception as e:
            print(f"  FAILED Item {part['part_number']}: {e}")
            # Fallback to Comment so the line is at least visible
            try:
                fb = bc.add_quote_line(bc_quote_id, {
                    "lineType": "Comment",
                    "description": f"{part['part_number']} - {part.get('description', '')} (Qty: {part['quantity']})",
                })
                if fb.get("id"):
                    new_door_lines.append(fb["id"])
                    print(f"    -> fallback Comment")
            except Exception as fe:
                print(f"    fallback also failed: {fe}")

    # 3. Trailing separator
    sep = bc.add_quote_line(bc_quote_id, {"lineType": "Comment", "description": "-"})
    if sep.get("id"):
        new_door_lines.append(sep["id"])

    print(f"\nDoor 2 regenerated with {len(new_door_lines)} lines.")

    # Freight
    print("\nRecalculating freight...")
    pricing_q = bc.get_sales_quote(bc_quote_id)
    subtotal = pricing_q.get("totalAmountExcludingTax", 0)
    print(f"  subtotal excl tax = ${subtotal:.2f}")

    delivery_type = (config.config_data or {}).get("deliveryType", "delivery")
    bc_cust = db.query(BCCustomer).filter(BCCustomer.bc_customer_id == config.user.bc_customer_id).first() if hasattr(config, 'user') else None
    # Fall back: pull customer province from config or default
    province = None
    if bc_cust and bc_cust.address:
        province = bc_cust.address.get("province")

    freight = calculate_freight(product_subtotal=subtotal, province=province, delivery_type=delivery_type, db=db)
    new_freight_ids: List[str] = []
    if not freight["skip"] and freight["amount"] > 0:
        freight_item = get_freight_config(db).get("freight_item_number", "FREIGHT")
        try:
            f = bc.add_quote_line(bc_quote_id, {
                "lineType": "Item", "lineObjectNumber": freight_item,
                "description": freight["description"], "quantity": 1,
            })
            etag = f.get("@odata.etag", "*")
            bc.update_quote_line(bc_quote_id, f["id"], etag, {"unitPrice": freight["amount"]})
            if f.get("id"):
                new_freight_ids.append(f["id"])
            print(f"  + FREIGHT ${freight['amount']:.2f} ({freight['description']})")
        except Exception as e:
            print(f"  Freight Item failed, trying Comment: {e}")
            try:
                fc = bc.add_quote_line(bc_quote_id, {
                    "lineType": "Comment",
                    "description": f"{freight['description']}: ${freight['amount']:.2f}",
                })
                if fc.get("id"):
                    new_freight_ids.append(fc["id"])
            except Exception as fe:
                print(f"  Freight Comment also failed: {fe}")
    else:
        print(f"  Pickup or zero freight — skipping")

    # Rewrite line_map
    print("\nUpdating line_map...")
    lm = dict(config.bc_line_map or {"doors": {}, "shared": {}})
    lm.setdefault("doors", {})
    lm.setdefault("shared", {})
    lm["doors"][str(DOOR_INDEX)] = new_door_lines
    if new_freight_ids:
        lm["shared"]["freight"] = new_freight_ids
    else:
        lm["shared"].pop("freight", None)

    config.bc_line_map = lm
    flag_modified(config, "bc_line_map")
    db.commit()

    print(f"\n✓ line_map.doors[{DOOR_INDEX}] -> {len(new_door_lines)} ids")
    print(f"✓ line_map.shared.freight -> {len(new_freight_ids)} ids")

    # Final quote view
    print("\nFinal BC line summary:")
    final = bc.get_quote_lines(bc_quote_id)
    for l in final:
        pn = (l.get("lineObjectNumber") or "").strip() or l.get("lineType", "")
        seq = l.get("sequence")
        up = l.get("unitPrice", 0) or 0
        qty = l.get("quantity", 0) or 0
        desc = (l.get("description") or "")[:60]
        print(f"  seq={seq:>7} {pn:25} qty={qty:>4} unit=${up:>9.2f}  {desc}")

    q = bc.get_sales_quote(bc_quote_id)
    print(f"\nFinal total: ${q.get('totalAmountIncludingTax',0):.2f}  (excl tax: ${q.get('totalAmountExcludingTax',0):.2f})")

    db.close()


if __name__ == "__main__":
    main()
