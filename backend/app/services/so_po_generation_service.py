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

Manufactured items don't mean "no purchasing needed" — Joey, 2026-09-09:
"we still need the material for that. We just need to make sure we have
the breakdown of what we need and what we don't need of the items that
are inside those production orders." So every excluded manufactured item
gets its Production BOM exploded (recursively — a component can itself be
built from a BOM) down to purchasable leaves, each leaf netted against
stock the same way a direct SO line is, and the real shortfall surfaces
as component_shortfall (component_covered lists what's already on hand).
"""

import logging
from collections import defaultdict
from datetime import date
from typing import Dict, List, Optional, Tuple

from app.integrations.bc.client import bc_client
from app.services.bc_production_service import bc_production_service
from app.services.purchasing_demand_service import NON_STOCK_ITEMS

logger = logging.getLogger(__name__)

_ITEM_SELECT = (
    "No,Description,InventoryField,Qty_on_Purch_Order,Qty_on_Sales_Order,"
    "Qty_on_Component_Lines,Replenishment_System,Production_BOM_No"
)

_MAX_BOM_DEPTH = 6  # defends against a cyclical/self-referencing BOM

# GL12 polycarbonate glazing sheet: Joey, 2026-09-09 — "the purchasing order
# should be full sheets", BC only carries one SKU per color (priced per SF,
# no per-length variant), and stock comes in 4' x {12',16',20',24'} pieces.
# So a raw SF need gets rounded up to the minimal-waste combination of those
# stocked lengths — never an arbitrary cut SF quantity Upwardor can't supply.
_GL12_SHEET_SF = [4 * ft for ft in (12, 16, 20, 24)]  # 48, 64, 80, 96
_GL12_MAX_SHEETS = 6


def _f(v) -> float:
    return float(v or 0)


def _round_to_full_sheets(item_no: str, sf_needed: float) -> float:
    """Round a GL12 (polycarbonate glazing sheet) need up to the smallest
    combination of stocked 4'-wide sheet lengths that covers it, minimizing
    both waste and sheet count. Every other item passes through unchanged."""
    if not item_no.startswith("GL12") or sf_needed <= 0:
        return sf_needed
    import itertools
    best: Optional[Tuple[float, int]] = None
    for n in range(1, _GL12_MAX_SHEETS + 1):
        for combo in itertools.combinations_with_replacement(_GL12_SHEET_SF, n):
            total = sum(combo)
            if total >= sf_needed and (best is None or (total, n) < best):
                best = (total, n)
        if best and best[0] - sf_needed < min(_GL12_SHEET_SF):
            break  # can't improve on this with more sheets
    return float(best[0]) if best else sf_needed


def _net_need(card: dict, qty: float) -> Tuple[float, float]:
    """(avail, net_need) for one item needing `qty` more, netted against
    on-hand + qty on other open POs, minus demand from OTHER open sales
    orders and whatever released production orders already claim. Shared
    by direct SO lines and BOM-exploded raw components — same rule either
    way: use what we have before we ask a supplier for more."""
    on_hand = _f(card.get("InventoryField"))
    on_po_other = _f(card.get("Qty_on_Purch_Order"))
    on_so_total = _f(card.get("Qty_on_Sales_Order"))
    on_component_lines = _f(card.get("Qty_on_Component_Lines"))
    other_so = max(0.0, on_so_total - qty)
    avail = on_hand + on_po_other - other_so - on_component_lines
    return avail, max(0.0, qty - max(0.0, avail))


def _explode_bom(item: str, qty: float, items: Dict[str, dict], boms: Dict[str, list],
                  depth: int = 0, seen: frozenset = frozenset()) -> Dict[str, float]:
    """Recursively explode a manufactured item's Production BOM down to
    purchasable leaves. A leaf is anything with no BOM of its own (or past
    the depth guard) — its needed quantity is qty_per * the parent's qty,
    aggregated across every path that demands it."""
    bom_no = (items.get(item, {}).get("Production_BOM_No") or "").strip()
    if not bom_no or bom_no in seen or depth >= _MAX_BOM_DEPTH:
        return {item: qty}
    need: Dict[str, float] = defaultdict(float)
    for line in boms.get(bom_no, []):
        comp = line.get("No")
        if not comp:
            continue
        comp_qty = qty * _f(line.get("Quantity_per"))
        for leaf, leaf_qty in _explode_bom(
            comp, comp_qty, items, boms, depth + 1, seen | {bom_no}
        ).items():
            need[leaf] += leaf_qty
    return dict(need)


def compute_netted_po_lines(so_number: str) -> dict:
    """Net one sales order's item lines against current BC supply.

    Returns:
        {
          "so_number", "customer_name",
          "included": [{item_no, description, quantity, unit_cost, uom}, ...],
          "excluded_manufactured": [{item_no, qty, ...}, ...],  # build, don't buy directly
          "excluded_in_stock": [{item_no, qty, on_hand, on_po_other, other_so, avail}, ...],
          "trimmed": [{item_no, ordered_qty, net_qty, ...}, ...],  # partial coverage
          "component_shortfall": [{item_no, description, quantity, unit_cost, uom,
                                    needed_for: [manufactured_item, ...]}, ...],
          "component_covered": [{item_no, needed, avail, needed_for: [...]}, ...],
        }

    Netting rule per item (see _net_need): avail = on_hand + qty_on_other_open_POs
    - demand_from_OTHER_open_SOs - qty_already_claimed_by_component_lines.
    net_need = max(0, this_SO_qty - avail). Only items with net_need > 0 are
    included, at net_need (not the SO's full quantity) — so stock gets used
    before a supplier does.

    A manufactured item never becomes a PO line itself — it needs a
    production order — but its Production BOM is exploded (recursively) to
    purchasable raw materials, each netted the same way. component_shortfall
    is what's actually short (buy it); component_covered is what's already
    on hand (the "what we don't need" half of the breakdown).
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

    empty = {
        "so_number": so_number, "customer_name": so.get("customerName"),
        "included": [], "excluded_manufactured": [], "excluded_in_stock": [], "trimmed": [],
        "component_shortfall": [], "component_covered": [],
    }
    if not so_qty:
        return empty

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

        avail, net_need = _net_need(card, qty)
        row = {
            "item_no": item, "ordered_qty": qty, "on_hand": _f(card.get("InventoryField")),
            "on_po_other": _f(card.get("Qty_on_Purch_Order")), "avail": round(avail, 2),
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

    # ── Explode manufactured items to raw components, net those too ────────
    component_shortfall, component_covered = [], []
    if excluded_manufactured:
        boms: Dict[str, list] = defaultdict(list)
        for r in bc_production_service._make_odata_request_all("ProductionBomLines"):
            boms[r.get("Production_BOM_No")].append(r)

        raw_need: Dict[str, float] = defaultdict(float)
        needed_for: Dict[str, set] = defaultdict(set)
        for m in excluded_manufactured:
            for leaf, leaf_qty in _explode_bom(m["item_no"], m["qty"], items, boms).items():
                raw_need[leaf] += leaf_qty
                needed_for[leaf].add(m["item_no"])

        for leaf, qty in sorted(raw_need.items()):
            card = items.get(leaf, {})
            avail, net_need = _net_need(card, qty)
            row = {
                "item_no": leaf, "description": card.get("Description", ""),
                "needed_qty": round(qty, 2), "avail": round(avail, 2),
                "needed_for": sorted(needed_for[leaf]),
            }
            if net_need <= 0:
                component_covered.append(row)
                continue
            rounded = _round_to_full_sheets(leaf, net_need)
            if rounded != net_need:
                row["net_need_raw"] = round(net_need, 2)  # pre-rounding, for traceability
            row["quantity"] = round(rounded, 2)
            component_shortfall.append(row)

        if component_shortfall:
            cost_cards = bc_client.get_items_by_numbers([r["item_no"] for r in component_shortfall])
            for row in component_shortfall:
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
        "component_shortfall": component_shortfall,
        "component_covered": component_covered,
    }


def build_upwardor_po(so_number: str, vendor_no: str = "UPW", vendor_name: str = "UPWARDOR",
                       dry_run: bool = True) -> dict:
    """Preview (dry_run=True) or create (dry_run=False) a Draft Upwardor PO
    for one sales order, netted per compute_netted_po_lines. Never emails —
    matches the existing "Draft in BC, human reviews" pattern.
    """
    plan = compute_netted_po_lines(so_number)
    result = {**plan, "vendor_no": vendor_no, "vendor_name": vendor_name, "dry_run": dry_run}

    po_lines = list(plan["included"])
    component_lines = plan["component_shortfall"]
    if not po_lines and not component_lines:
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
    for row in po_lines:
        bc_client.add_purchase_order_line(po_id, {
            "sequence": seq, "lineType": "Item",
            "lineObjectNumber": row["item_no"], "quantity": row["quantity"],
            "unitOfMeasureCode": row.get("uom"), "directUnitCost": row["unit_cost"],
            "description": row["description"],
        })
        seq += 10000

    if component_lines:
        bc_client.add_purchase_order_line(po_id, {
            "sequence": seq, "lineType": "Comment",
            # BC Comment lines cap at 100 chars (Application_StringExceededLength).
            "description": "Raw materials for in-house manufactured items (BOM-exploded, netted vs stock)",
        })
        seq += 10000
        for row in component_lines:
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
