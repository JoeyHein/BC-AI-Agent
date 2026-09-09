"""Generate one BC purchase order per sales order, netted against stock.

Built to replace the ad-hoc, throwaway script used on 2026-09-08 to draft
7 Upwardor POs (PO-000956..PO-000962) that mirrored each SO's item lines
1:1 with no inventory check at all. That produced PO-000962 with 40 items /
$5,737 for SO-001299, of which 96% either shouldn't have been purchased at
all (13 manufactured-in-house panels, $4,585) or was already covered by
stock/other open POs ($901) — only $251 was a genuine shortfall.

Policy (Joey, 2026-09-09): "we do not include items that we have in stock
... the key goal is to reduce our stock and become more reliant on our
suppliers ... but we need to be rigid about reducing our own stock first."
So every line this module emits is netted against on-hand + what's already
on other open POs, minus what other open sales orders still need from that
same stock, before a single unit is drafted for purchase — and manufactured
items never appear at all (they need a production order, not a vendor PO).

Reuses the exclusion list from purchasing_demand_service (NON_STOCK_ITEMS)
and the replenishment lookup from bc_production_service (same ones the
nightly auto-PO job and the digest engine use) rather than re-deriving them,
so all three PO-generation paths agree on what "purchasable" means.
"""

import logging
from collections import defaultdict
from datetime import date
from typing import Dict, List, Optional

from app.integrations.bc.client import bc_client
from app.services.bc_production_service import bc_production_service
from app.services.purchasing_demand_service import NON_STOCK_ITEMS

logger = logging.getLogger(__name__)

_ITEM_SELECT = (
    "No,Description,InventoryField,Qty_on_Purch_Order,Qty_on_Sales_Order,"
    "Qty_on_Component_Lines,Replenishment_System"
)


def _f(v) -> float:
    return float(v or 0)


def compute_netted_po_lines(so_number: str) -> dict:
    """Net one sales order's item lines against current BC supply.

    Returns:
        {
          "so_number", "customer_name",
          "included": [{item_no, description, qty, unit_cost, uom}, ...],
          "excluded_manufactured": [{item_no, qty, ...}, ...],  # build, don't buy
          "excluded_in_stock": [{item_no, qty, on_hand, on_po_other, other_so, avail}, ...],
          "trimmed": [{item_no, ordered_qty, net_qty, ...}, ...],  # partial coverage
        }

    Netting rule per item (excluding manufactured items and NON_STOCK_ITEMS
    entirely): avail = on_hand + qty_on_other_open_POs - demand_from_OTHER_open_SOs
    - qty_already_claimed_by_component_lines. net_need = max(0, this_SO_qty - avail).
    Only items with net_need > 0 are included, at net_need (not the SO's full
    quantity) — so stock gets used before a supplier does.
    """
    so = bc_client.get_sales_order_by_number(so_number)
    if not so:
        raise ValueError(f"{so_number} not found in BC")
    so_id = so["id"]
    lines = bc_client.get_order_lines(so_id)

    so_qty: Dict[str, float] = defaultdict(float)
    line_desc: Dict[str, str] = {}
    for ln in lines:
        if ln.get("lineType") != "Item":
            continue
        item = ln.get("lineObjectNumber")
        if not item or item.upper() in NON_STOCK_ITEMS:
            continue
        so_qty[item] += _f(ln.get("quantity"))
        line_desc[item] = ln.get("description") or ""

    if not so_qty:
        return {
            "so_number": so_number, "customer_name": so.get("customerName"),
            "included": [], "excluded_manufactured": [], "excluded_in_stock": [], "trimmed": [],
        }

    items = {r["No"]: r for r in bc_production_service._make_odata_request_all(
        "Items", query_params={"$select": _ITEM_SELECT}) if r.get("No")}

    included, excluded_manufactured, excluded_in_stock, trimmed = [], [], [], []
    for item, qty in sorted(so_qty.items()):
        card = items.get(item, {})
        replen = (card.get("Replenishment_System") or "").strip()
        if replen == "Prod. Order":
            excluded_manufactured.append({
                "item_no": item, "qty": qty, "description": line_desc.get(item, ""),
                "reason": "manufactured in-house — needs a production order, not a PO",
            })
            continue

        on_hand = _f(card.get("InventoryField"))
        on_po_other = _f(card.get("Qty_on_Purch_Order"))  # includes this SO's own open POs, if any — best-effort
        on_so_total = _f(card.get("Qty_on_Sales_Order"))
        on_component_lines = _f(card.get("Qty_on_Component_Lines"))
        other_so = max(0.0, on_so_total - qty)
        avail = on_hand + on_po_other - other_so - on_component_lines
        net_need = max(0.0, qty - max(0.0, avail))

        row = {
            "item_no": item, "ordered_qty": qty, "on_hand": on_hand,
            "on_po_other": on_po_other, "other_so": other_so, "avail": round(avail, 2),
            "net_qty": round(net_need, 2), "description": line_desc.get(item, ""),
        }
        if net_need <= 0:
            excluded_in_stock.append(row)
            continue
        if net_need < qty:
            trimmed.append(row)

        included.append({
            "item_no": item,
            "description": line_desc.get(item, ""),
            "quantity": round(net_need, 2),
            "unit_cost": None,  # filled from item card cost below (base UoM)
        })

    # Price included lines from the same v2.0 item-cost source the rest of
    # purchasing uses (base-UoM unitCost), not receipt last-paid — see
    # [[project_purchasing_tool]] "Cost was pulled from receipt last-paid" fix.
    if included:
        cost_cards = bc_client.get_items_by_numbers([r["item_no"] for r in included])
        for row in included:
            meta = cost_cards.get(row["item_no"], {})
            row["unit_cost"] = _f(meta.get("unitCost"))
            row["uom"] = meta.get("baseUnitOfMeasureCode") or "EA"

    return {
        "so_number": so_number,
        "customer_name": so.get("customerName"),
        "included": included,
        "excluded_manufactured": excluded_manufactured,
        "excluded_in_stock": excluded_in_stock,
        "trimmed": trimmed,
    }


def build_upwardor_po(so_number: str, vendor_no: str = "UPW", vendor_name: str = "UPWARDOR",
                       dry_run: bool = True) -> dict:
    """Preview (dry_run=True) or create (dry_run=False) a Draft Upwardor PO
    for one sales order, netted per compute_netted_po_lines. Never emails —
    matches the existing "Draft in BC, human reviews" pattern.
    """
    plan = compute_netted_po_lines(so_number)
    result = {**plan, "vendor_no": vendor_no, "vendor_name": vendor_name, "dry_run": dry_run}

    if not plan["included"]:
        result["bc_po_number"] = None
        result["note"] = "Nothing to order — fully covered by stock/other open POs, or all items manufactured in-house."
        return result

    if dry_run:
        result["bc_po_number"] = None
        return result

    bc_po = bc_client.create_purchase_order({"vendorNumber": vendor_no})
    po_id, po_number = bc_po["id"], bc_po["number"]

    bc_client.add_purchase_order_line(po_id, {
        "sequence": 10000, "lineType": "Comment",
        "description": plan["customer_name"],
    })
    bc_client.add_purchase_order_line(po_id, {
        "sequence": 20000, "lineType": "Comment",
        "description": f"Built from {so_number} - {date.today().isoformat()} - opendc purchasing (netted vs stock)",
    })
    seq = 30000
    for row in plan["included"]:
        bc_client.add_purchase_order_line(po_id, {
            "sequence": seq, "lineType": "Item",
            "lineObjectNumber": row["item_no"], "quantity": row["quantity"],
            "unitOfMeasureCode": row.get("uom"), "directUnitCost": row["unit_cost"],
            "description": row["description"],
        })
        seq += 10000

    result["bc_po_number"] = po_number
    result["bc_po_id"] = po_id
    return result
