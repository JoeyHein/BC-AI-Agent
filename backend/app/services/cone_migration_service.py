"""Replace retired universal spring-cone lines with LH and RH items.

Upwardor invoices a left-hand cone and a right-hand cone. The portal's
universal -01 items (SP12-00231-01 and the other coil sizes) are retired.
New quotes already emit LH/RH. This module:

- previews the same split on open sales orders and Draft purchase orders
- keeps a sales order's extended amount exactly the same (odd cents land
  on the LH line)
- prices Draft PO lines at the LH/RH item-card cost
- expands SO lines inside PO generation so a new PO does not reorder -01

Dry-run is the default. ``apply=True`` writes to Business Central.
"""

from __future__ import annotations

import logging
import re
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

# Same door-header shape as so_po_generation_service._DOOR_HEADER_RE.
_DOOR_HEADER_RE = re.compile(r'^\(\d+\)\s+\d+\'\d+"\s*x\s*\d+\'\d+"')
_SPRING_RE = re.compile(r"^SP1[01]-(\d{3})(\d{2})-(01|02)$", re.IGNORECASE)
_LH_RH_COMMENT = re.compile(r"(\d+)\s*LH\s*\+\s*(\d+)\s*RH", re.IGNORECASE)
_LH_ONLY_COMMENT = re.compile(r"(\d+)\s*LH\b", re.IGNORECASE)

_MONEY = Decimal("0.01")


def _d(value) -> Decimal:
    return Decimal(str(value if value is not None else 0))


def _money(value: Decimal) -> str:
    """Fixed-point string so a dry-run diff does not pick up binary float noise."""
    return format(value.quantize(_MONEY, rounding=ROUND_HALF_UP), "f")


def _qty_int(qty) -> Tuple[int, bool]:
    """Whole cones. The flag is set when the source quantity was not integral."""
    dec = _d(qty)
    rounded = int(dec.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    fractional = dec != Decimal(rounded)
    return max(rounded, 0), fractional


def split_hand_qty(qty, lh_weight: int, rh_weight: int) -> Tuple[int, int, str, List[str]]:
    """Split a cone quantity across hands.

    Weights come from the springs (or the spring comment) on the order.
    When both weights are zero the hands could not be read, so the quantity
    is split evenly and an odd quantity is flagged. The extra piece, and any
    leftover cent of a ratio that does not divide evenly, goes to LH — that
    is also the hand a single-spring door uses.
    """
    qty_int, fractional = _qty_int(qty)
    flags: List[str] = []
    if fractional:
        flags.append("fractional_quantity")
    if lh_weight <= 0 and rh_weight <= 0:
        lh = (qty_int + 1) // 2
        rh = qty_int // 2
        if qty_int % 2 == 1:
            flags.append("odd_quantity")
        return lh, rh, "even", flags
    if rh_weight <= 0:
        return qty_int, 0, "determined", flags
    if lh_weight <= 0:
        return 0, qty_int, "determined", flags
    weight = lh_weight + rh_weight
    if (qty_int * lh_weight) % weight != 0:
        flags.append("odd_quantity")
    rh = (qty_int * rh_weight) // weight
    lh = qty_int - rh
    return lh, rh, "determined", flags


def _unit_price_for(qty: int, amount_cents: int) -> Optional[Decimal]:
    """A unit price whose rounded extension equals ``amount_cents``.

    Two decimals first, then up to five, which is as far as BC unit prices
    are useful. None when no such price exists.
    """
    if qty <= 0:
        return Decimal("0")
    if amount_cents < 0:
        return None
    target = (Decimal(amount_cents) / Decimal(100)).quantize(_MONEY)
    for places in range(2, 6):
        quantum = Decimal(1).scaleb(-places)
        price = (target / Decimal(qty)).quantize(quantum, rounding=ROUND_HALF_UP)
        got = (price * Decimal(qty)).quantize(_MONEY, rounding=ROUND_HALF_UP)
        if got == target:
            return price
    return None


def allocate_sales_prices(total_amount, lh_qty: int, rh_qty: int) -> Dict[str, Any]:
    """LH and RH unit prices whose extensions sum to ``total_amount``.

    Line amounts are proportional to quantity. A leftover cent goes to the
    LH line. If a 2-to-5 decimal unit price cannot reproduce that cent
    split, cents are moved between the lines until both extensions are exact.
    """
    total = _d(total_amount).quantize(_MONEY, rounding=ROUND_HALF_UP)
    total_cents = int(total * 100)
    if lh_qty < 0 or rh_qty < 0 or (lh_qty == 0 and rh_qty == 0):
        raise ValueError("cone split has no quantity")

    if lh_qty and rh_qty:
        rh_cents = (total_cents * rh_qty) // (lh_qty + rh_qty)
        lh_cents = total_cents - rh_cents
    elif lh_qty:
        lh_cents, rh_cents = total_cents, 0
    else:
        lh_cents, rh_cents = 0, total_cents

    def _pair(lc: int, rc: int):
        if lc < 0 or rc < 0 or lc + rc != total_cents:
            return None
        lp = _unit_price_for(lh_qty, lc) if lh_qty else Decimal("0")
        rp = _unit_price_for(rh_qty, rc) if rh_qty else Decimal("0")
        if lp is None or rp is None:
            return None
        return lp, rp, Decimal(lc) / Decimal(100), Decimal(rc) / Decimal(100)

    found = _pair(lh_cents, rh_cents)
    if found is None and lh_qty and rh_qty:
        limit = max(lh_qty, rh_qty) * 20 + 5
        for delta in range(1, limit + 1):
            for lc in (lh_cents + delta, lh_cents - delta):
                found = _pair(lc, total_cents - lc)
                if found is not None:
                    break
            if found is not None:
                break
    if found is None:
        raise ValueError(
            f"cannot price {lh_qty} LH + {rh_qty} RH to {total}"
        )
    lp, rp, la, ra = found
    return {
        "lh_unit_price": lp,
        "rh_unit_price": rp,
        "lh_amount": la,
        "rh_amount": ra,
    }


def _is_door_header(line: dict) -> bool:
    if (line.get("lineType") or "") != "Comment":
        return False
    return bool(_DOOR_HEADER_RE.match((line.get("description") or "").strip()))


def _spring_weights(lines: Iterable[dict], coil_code: str) -> Tuple[int, int, bool]:
    """Inch-quantities of LH (-01) and RH (-02) springs at this coil code.

    Spring lines are billed in inches, not pieces. The ratio of the two
    inch totals is the ratio of the spring counts when both hands share a
    length, which they do.
    """
    lh = rh = 0
    found = False
    for line in lines:
        if (line.get("lineType") or "Item") != "Item":
            continue
        match = _SPRING_RE.match((line.get("lineObjectNumber") or "").strip())
        if not match or match.group(2) != coil_code:
            continue
        found = True
        qty = int(_d(line.get("quantity")).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        if match.group(3) == "01":
            lh += qty
        else:
            rh += qty
    return lh, rh, found


def _comment_weights(lines: Iterable[dict]) -> Tuple[int, int, bool]:
    lh = rh = 0
    found = False
    for line in lines:
        if (line.get("lineType") or "") != "Comment":
            continue
        text = line.get("description") or ""
        both = _LH_RH_COMMENT.search(text)
        if both:
            lh += int(both.group(1))
            rh += int(both.group(2))
            found = True
            continue
        if "SPRING" not in text.upper():
            continue
        only = _LH_ONLY_COMMENT.search(text)
        if only and "RH" not in text.upper():
            lh += int(only.group(1))
            found = True
    return lh, rh, found


def _sections(lines: Sequence[dict]):
    """Map each line object to the door section it sits in.

    Lines before the first door header share section 0.
    """
    ordered = sorted(
        enumerate(lines),
        key=lambda pair: ((pair[1].get("sequence") or 0), pair[0]),
    )
    section = 0
    by_line = {}
    grouped: Dict[int, List[dict]] = {0: []}
    for _, line in ordered:
        if _is_door_header(line):
            section += 1
            grouped.setdefault(section, [])
        by_line[id(line)] = section
        grouped.setdefault(section, []).append(line)
    return by_line, grouped


def _line_amount(line: dict) -> Decimal:
    for key in ("amountExcludingTax", "netAmount"):
        if line.get(key) is not None and line.get(key) != "":
            return _d(line.get(key)).quantize(_MONEY, rounding=ROUND_HALF_UP)
    qty = _d(line.get("quantity"))
    price = _d(line.get("unitPrice") or 0)
    return (qty * price).quantize(_MONEY, rounding=ROUND_HALF_UP)


def _already_moved(line: dict) -> bool:
    for key in ("shippedQuantity", "invoicedQuantity", "receivedQuantity"):
        if _d(line.get(key)) > 0:
            return True
    return False


def _hands_for(spec: dict, section_lines: Sequence[dict], all_lines: Sequence[dict]):
    coil = spec["coil_code"]
    lh, rh, found = _spring_weights(section_lines, coil)
    if found:
        return lh, rh, "springs"
    lh, rh, found = _comment_weights(section_lines)
    if found:
        return lh, rh, "comment"
    lh, rh, found = _spring_weights(all_lines, coil)
    if found:
        return lh, rh, "springs"
    lh, rh, found = _comment_weights(all_lines)
    if found:
        return lh, rh, "comment"
    return 0, 0, "even"


def _part_for(spec: dict, hand: str) -> Tuple[str, str]:
    from app.services.bc_part_number_mapper import get_bc_mapper

    expected = spec["lh"] if hand == "LH" else spec["rh"]
    part = get_bc_mapper().get_winder_stationary_set(spec["coil"], spec["bore"], hand)
    description = part.description if part.part_number == expected else (
        f"SPRING, WINDERS & STATIONARY PLUGS SET, {hand}"
    )
    return expected, description


def plan_cone_replacements(lines: Sequence[dict], *, price_sales: bool = False) -> List[dict]:
    """One replacement plan per retired universal cone line.

    ``price_sales`` fills unit prices so the two new lines extend to the
    original line amount. Purchase orders leave prices empty; the caller
    fills item-card costs.
    """
    from app.services.bc_part_number_mapper import BCPartNumberMapper

    by_line, grouped = _sections(lines)
    plans = []
    for index, line in enumerate(lines):
        if (line.get("lineType") or "Item") != "Item":
            continue
        spec = BCPartNumberMapper.retired_universal_cone(line.get("lineObjectNumber") or "")
        if not spec:
            continue
        section_lines = grouped.get(by_line.get(id(line), 0), [])
        lh_w, rh_w, source = _hands_for(spec, section_lines, lines)
        lh_qty, rh_qty, _method, flags = split_hand_qty(
            line.get("quantity") or 0, lh_w, rh_w,
        )
        split_source = source if (lh_w or rh_w) else "even"
        amount = _line_amount(line) if price_sales else None
        prices = None
        if price_sales and (lh_qty or rh_qty):
            prices = allocate_sales_prices(amount, lh_qty, rh_qty)

        replacements = []
        for hand, qty in (("LH", lh_qty), ("RH", rh_qty)):
            if qty <= 0:
                continue
            item_no, description = _part_for(spec, hand)
            row = {
                "hand": hand,
                "item_no": item_no,
                "description": description,
                "quantity": qty,
                "unit_price": None,
                "line_amount": None,
                "unit_cost": None,
            }
            if prices is not None:
                unit = prices["lh_unit_price"] if hand == "LH" else prices["rh_unit_price"]
                ext = prices["lh_amount"] if hand == "LH" else prices["rh_amount"]
                row["unit_price"] = _money(unit)
                row["line_amount"] = _money(ext)
            replacements.append(row)

        skipped = False
        skip_reason = None
        if _already_moved(line):
            skipped = True
            skip_reason = "line already has a shipped, invoiced, or received quantity"
        elif price_sales and not line.get("id"):
            skipped = True
            skip_reason = "sales order line has no id, so it cannot be edited"

        plans.append({
            "line_index": index,
            "line_id": line.get("id"),
            "sequence": line.get("sequence"),
            "from_item": (line.get("lineObjectNumber") or "").strip(),
            "from_description": line.get("description") or "",
            "from_quantity": float(line.get("quantity") or 0),
            "from_unit_price": (
                _money(_d(line.get("unitPrice"))) if line.get("unitPrice") is not None else None
            ),
            "from_amount": _money(amount) if amount is not None else None,
            "split_source": split_source,
            "flags": flags,
            "skipped": skipped,
            "skip_reason": skip_reason,
            "replacements": replacements,
        })
    return plans


def split_retired_component(item_no: str, qty) -> Optional[dict]:
    """Even LH/RH split for a universal cone that arrived from a BOM.

    Returns None when ``item_no`` is not a retired cone. There are no
    spring lines on a BOM, so the hand split cannot be read.
    """
    from app.services.bc_part_number_mapper import BCPartNumberMapper

    spec = BCPartNumberMapper.retired_universal_cone(item_no)
    if not spec:
        return None
    lh_qty, rh_qty, _method, flags = split_hand_qty(qty, 0, 0)
    lines = []
    for hand, hand_qty in (("LH", lh_qty), ("RH", rh_qty)):
        if hand_qty <= 0:
            continue
        pn, _desc = _part_for(spec, hand)
        lines.append((pn, float(hand_qty)))
    return {"lines": lines, "flags": flags}


def expand_retired_cone_lines(lines: Sequence[dict]) -> Tuple[List[dict], List[dict]]:
    """Copy ``lines``, replacing each retired cone with LH and RH items.

    A line that already moved (shipped, received, invoiced) is left in
    place and reported. Used by PO generation so a new purchase order does
    not reorder the universal item.
    """
    plans = {p["line_index"]: p for p in plan_cone_replacements(lines, price_sales=False)}
    out: List[dict] = []
    warnings: List[dict] = []
    for index, line in enumerate(lines):
        plan = plans.get(index)
        if plan is None:
            out.append(line)
            continue
        warnings.append({
            "code": "retired_universal_cone",
            "from_item": plan["from_item"],
            "quantity": plan["from_quantity"],
            "split_source": plan["split_source"],
            "flags": plan["flags"],
            "skipped": plan["skipped"],
            "message": (
                plan["skip_reason"]
                if plan["skipped"]
                else (
                    f"Replaced retired cone {plan['from_item']} with "
                    + ", ".join(
                        f"{r['quantity']} {r['item_no']}" for r in plan["replacements"]
                    )
                    + f" ({plan['split_source']}"
                    + (f", flags: {', '.join(plan['flags'])}" if plan["flags"] else "")
                    + ")."
                )
            ),
        })
        if plan["skipped"]:
            out.append(line)
            continue
        for repl in plan["replacements"]:
            cloned = dict(line)
            cloned["lineObjectNumber"] = repl["item_no"]
            cloned["description"] = repl["description"]
            cloned["quantity"] = repl["quantity"]
            for key in ("amountExcludingTax", "netAmount", "unitPrice", "directUnitCost"):
                cloned.pop(key, None)
            out.append(cloned)
    return out, warnings


def _matches(number: str, wanted: set) -> bool:
    if not wanted:
        return True
    return (number or "").strip().upper() in wanted


class ConeMigrationService:
    """Dry-run (default) or apply the universal-cone replacement in BC."""

    def run(
        self,
        *,
        apply: bool = False,
        document_numbers: Optional[Sequence[str]] = None,
        client=None,
    ) -> dict:
        if client is None:
            from app.integrations.bc.client import bc_client
            client = bc_client

        wanted = {
            n.strip().upper() for n in (document_numbers or []) if n and str(n).strip()
        }
        sales_orders = client.get_open_sales_orders_with_lines() or []
        draft_pos = client.get_draft_purchase_orders_with_lines() or []

        so_docs = []
        for order in sales_orders:
            number = order.get("number") or ""
            if not _matches(number, wanted):
                continue
            lines = order.get("salesOrderLines")
            if lines is None and order.get("id"):
                lines = client.get_order_lines(order["id"])
            changes = [
                c for c in plan_cone_replacements(lines or [], price_sales=True)
            ]
            if not changes:
                continue
            so_docs.append({
                "document_type": "sales_order",
                "number": number,
                "id": order.get("id"),
                "status": order.get("status"),
                "customer_name": order.get("customerName"),
                "changes": changes,
            })

        po_docs = []
        for po in draft_pos:
            status = po.get("status") or ""
            if status and status != "Draft":
                continue
            number = po.get("number") or ""
            if not _matches(number, wanted):
                continue
            lines = po.get("purchaseOrderLines")
            if lines is None and po.get("id"):
                lines = []
            changes = plan_cone_replacements(lines or [], price_sales=False)
            if not changes:
                continue
            po_docs.append({
                "document_type": "purchase_order",
                "number": number,
                "id": po.get("id"),
                "status": status or "Draft",
                "vendor_name": po.get("vendorName"),
                "changes": changes,
            })

        self._fill_po_costs(client, po_docs)

        result = {
            "dry_run": not apply,
            "apply": bool(apply),
            "scanned_sales_orders": len(sales_orders),
            "scanned_purchase_orders": len(draft_pos),
            "sales_order_count": len(so_docs),
            "purchase_order_count": len(po_docs),
            "sales_orders": so_docs,
            "purchase_orders": po_docs,
        }
        if not apply:
            return result

        result["applied"] = []
        result["errors"] = []
        for doc in so_docs:
            self._apply_sales_order(client, doc, result)
        for doc in po_docs:
            self._apply_purchase_order(client, doc, result)
        return result

    def _fill_po_costs(self, client, po_docs: List[dict]) -> None:
        needed = sorted({
            repl["item_no"]
            for doc in po_docs
            for change in doc["changes"]
            if not change.get("skipped")
            for repl in change["replacements"]
        })
        cards = client.get_items_by_numbers(needed) if needed else {}
        for doc in po_docs:
            for change in doc["changes"]:
                if change.get("skipped"):
                    continue
                missing = []
                for repl in change["replacements"]:
                    card = (cards or {}).get(repl["item_no"]) or {}
                    cost = card.get("unitCost")
                    if cost is None or _d(cost) <= 0:
                        missing.append(repl["item_no"])
                        repl["unit_cost"] = None
                    else:
                        repl["unit_cost"] = _money(_d(cost))
                    if card.get("displayName"):
                        repl["description"] = card["displayName"]
                if missing:
                    change["flags"] = list(change.get("flags") or []) + ["missing_item_cost"]
                    change["missing_costs"] = missing

    def _apply_sales_order(self, client, doc: dict, result: dict) -> None:
        order_id = doc.get("id")
        if not order_id:
            result["errors"].append({
                "document": doc.get("number"), "error": "sales order has no id",
            })
            return
        for change in doc["changes"]:
            if change.get("skipped"):
                result["errors"].append({
                    "document": doc.get("number"),
                    "line_id": change.get("line_id"),
                    "error": change.get("skip_reason") or "skipped",
                })
                continue
            try:
                for repl in change["replacements"]:
                    client.add_order_line(order_id, {
                        "lineType": "Item",
                        "lineObjectNumber": repl["item_no"],
                        "description": (repl["description"] or "")[:100],
                        "quantity": repl["quantity"],
                        "unitPrice": float(repl["unit_price"]),
                    })
                client.delete_order_line(order_id, change["line_id"])
                result["applied"].append({
                    "document": doc.get("number"),
                    "document_type": "sales_order",
                    "line_id": change.get("line_id"),
                    "from_item": change["from_item"],
                })
            except Exception as exc:
                logger.exception("Cone migration failed on %s", doc.get("number"))
                result["errors"].append({
                    "document": doc.get("number"),
                    "line_id": change.get("line_id"),
                    "error": str(exc),
                })
                return

    def _apply_purchase_order(self, client, doc: dict, result: dict) -> None:
        po_id = doc.get("id")
        if not po_id:
            result["errors"].append({
                "document": doc.get("number"), "error": "purchase order has no id",
            })
            return
        if (doc.get("status") or "Draft") != "Draft":
            result["errors"].append({
                "document": doc.get("number"), "error": "only Draft purchase orders are edited",
            })
            return
        for change in doc["changes"]:
            if change.get("skipped") or "missing_item_cost" in (change.get("flags") or []):
                result["errors"].append({
                    "document": doc.get("number"),
                    "line_id": change.get("line_id"),
                    "error": change.get("skip_reason") or "LH/RH item cost is missing",
                })
                continue
            if not change.get("line_id"):
                result["errors"].append({
                    "document": doc.get("number"),
                    "error": "purchase order line has no id",
                })
                continue
            try:
                for repl in change["replacements"]:
                    client.add_purchase_order_line(po_id, {
                        "lineType": "Item",
                        "lineObjectNumber": repl["item_no"],
                        "description": (repl["description"] or "")[:100],
                        "quantity": repl["quantity"],
                        "directUnitCost": float(repl["unit_cost"]),
                    })
                client.delete_purchase_order_line(po_id, change["line_id"])
                result["applied"].append({
                    "document": doc.get("number"),
                    "document_type": "purchase_order",
                    "line_id": change.get("line_id"),
                    "from_item": change["from_item"],
                })
            except Exception as exc:
                logger.exception("Cone migration failed on %s", doc.get("number"))
                result["errors"].append({
                    "document": doc.get("number"),
                    "line_id": change.get("line_id"),
                    "error": str(exc),
                })
                return


cone_migration_service = ConeMigrationService()
