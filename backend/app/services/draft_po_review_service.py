"""Read-only review of Business Central Draft purchase orders.

Lists unsent POs (status Draft) with lines, and checks them against the same
buy-complete / panel-companion rules the SO→PO generator uses:

  * Buy complete (don't explode): HK, PN45-/PN46-/PN80-, TR02-/TR03-,
    SP12-, GK15-/GK16-/GK17- — see purchasing_demand_service._BUY_COMPLETE_PREFIXES.
  * When panels are on the PO, astragal / retainer / top seal must ride along
    at full qty — see so_po_generation_service._ALWAYS_FULL_QTY_KEYWORDS.
  * If a buy-complete parent is present, leftover BOM-looking lines (raw
    cores, fasteners, track pieces, glazing sheet) are flagged.

Does not release, email, or send. Source of truth is BC, not the portal UI.
"""

from __future__ import annotations

import logging
import re
from typing import Dict, List, Optional, Sequence, Tuple

from app.integrations.bc.client import bc_client
from app.services.purchasing_demand_service import (
    NON_STOCK_ITEMS,
    _BUY_COMPLETE_PREFIXES,
    _buy_complete,
)
from app.services.po_line_order import classify_line
from app.services.so_po_generation_service import (
    _ALWAYS_FULL_QTY_KEYWORDS,
    _always_full_qty,
)

logger = logging.getLogger(__name__)

_SO_RE = re.compile(r"\bSO-\d+\b", re.IGNORECASE)

# When a buy-complete parent family is on the PO, these leftover prefixes
# (and description keywords) look like the BOM was exploded instead of
# buying the finished item. Confirmed live on PO-000962 (HK → fasteners,
# PN45/PN46 → PN40 cores; later PN80 → AL extrusions, GK → GL12 sheet).
_EXPLODED_LEFTOVERS: Tuple[Tuple[str, Tuple[str, ...], Tuple[str, ...]], ...] = (
    ("HK", ("FH",), ("HINGE", "BOLT", "SCREW", "FASTENER", "NUT", "WASHER", "RIVET")),
    ("PN45-", ("PN40-",), ("BULK", "END CAP")),
    ("PN46-", ("PN40-",), ("BULK", "END CAP")),
    ("PN80-", ("AL",), ()),
    ("TR02-", ("TR10-", "TR11-", "TR12-"), ()),
    ("TR03-", ("TR10-", "TR11-", "TR12-"), ()),
    ("GK15-", ("GL12", "AL"), ("POLYCARBONATE",)),
    ("GK16-", ("GL12", "AL"), ("POLYCARBONATE",)),
    ("GK17-", ("GL12", "AL"), ("POLYCARBONATE",)),
)


def _f(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def _sales_orders_from_po(po: dict, lines: Sequence[dict]) -> List[str]:
    """SO numbers from externalDocumentNumber plus comment/item descriptions.

    Tool-built POs write 'Built from SO-…' or 'allocated to: SO-…' on comment
    lines; hand-keyed POs sometimes put the SO on externalDocumentNumber.
    """
    found: List[str] = []
    seen = set()

    def _add(text: str) -> None:
        for m in _SO_RE.finditer(text or ""):
            so = m.group(0).upper()
            if so not in seen:
                seen.add(so)
                found.append(so)

    _add(po.get("externalDocumentNumber") or "")
    for ln in lines:
        _add(ln.get("description") or "")
    return found


def _item_lines(po: dict) -> List[dict]:
    out = []
    for ln in po.get("purchaseOrderLines") or []:
        if (ln.get("lineType") or "") != "Item":
            continue
        item = (ln.get("lineObjectNumber") or "").strip()
        if not item or item.upper() in NON_STOCK_ITEMS:
            continue
        out.append(ln)
    return out


def summarize_po(po: dict) -> dict:
    """Normalize a BC purchaseOrder (+ expanded lines) for the CoS list API."""
    raw_lines = po.get("purchaseOrderLines") or []
    lines = []
    for ln in raw_lines:
        item_number = ln.get("lineObjectNumber") or None
        line_type = ln.get("lineType")
        lines.append({
            "id": ln.get("id"),
            "sequence": ln.get("sequence"),
            "line_type": line_type,
            "item_number": item_number,
            "description": ln.get("description") or "",
            "quantity": _f(ln.get("quantity")),
            "unit_cost": _f(ln.get("directUnitCost")),
            "received_quantity": _f(ln.get("receivedQuantity")),
            "unit_of_measure": ln.get("unitOfMeasureCode") or None,
            "panel_class": classify_line({
                "lineType": line_type,
                "lineObjectNumber": item_number or "",
                "description": ln.get("description") or "",
            }),
        })
    item_count = sum(1 for ln in lines if ln["line_type"] == "Item" and ln["item_number"])
    return {
        "id": po.get("id"),
        "number": po.get("number"),
        "vendor_number": po.get("vendorNumber"),
        "vendor_name": po.get("vendorName") or po.get("payToVendorName"),
        "status": po.get("status"),
        "order_date": po.get("orderDate") or None,
        "posting_date": po.get("postingDate") or None,
        "requested_receipt_date": po.get("requestedReceiptDate") or None,
        "external_document_number": po.get("externalDocumentNumber") or "",
        "sales_orders": _sales_orders_from_po(po, raw_lines),
        "line_count": len(lines),
        "item_line_count": item_count,
        "lines": lines,
    }


def _companion_hits(item_lines: Sequence[dict]) -> Dict[str, List[dict]]:
    hits: Dict[str, List[dict]] = {k: [] for k in _ALWAYS_FULL_QTY_KEYWORDS}
    for ln in item_lines:
        desc = (ln.get("description") or "").upper()
        qty = _f(ln.get("quantity"))
        for keyword in _ALWAYS_FULL_QTY_KEYWORDS:
            if keyword in desc:
                hits[keyword].append({
                    "item_number": ln.get("lineObjectNumber"),
                    "description": ln.get("description") or "",
                    "quantity": qty,
                })
    return hits


def _leftover_matches(item: str, description: str, present_parents: Sequence[str]
                      ) -> List[str]:
    """Parent prefixes that make this line look like an exploded leftover."""
    if _buy_complete(item) or _always_full_qty(description):
        return []
    desc_u = (description or "").upper()
    matched: List[str] = []
    for parent_prefix, leftover_prefixes, keywords in _EXPLODED_LEFTOVERS:
        if parent_prefix not in present_parents:
            continue
        if item.startswith(leftover_prefixes) or any(k in desc_u for k in keywords):
            if parent_prefix not in matched:
                matched.append(parent_prefix)
    return matched


def validate_po(po: dict) -> dict:
    """Run buy-complete / companion / leftover checks on one BC PO payload."""
    summary = summarize_po(po)
    item_lines = _item_lines(po)
    issues: List[dict] = []

    buy_complete_parents = sorted({
        (ln.get("lineObjectNumber") or "").strip()
        for ln in item_lines
        if _buy_complete((ln.get("lineObjectNumber") or "").strip())
    })
    present_parent_prefixes = [
        prefix for prefix in _BUY_COMPLETE_PREFIXES
        if any(p.startswith(prefix) for p in buy_complete_parents)
    ]
    has_panels = any(
        (ln.get("lineObjectNumber") or "").startswith("PN")
        for ln in item_lines
    )

    companions = _companion_hits(item_lines)
    if has_panels:
        for keyword in _ALWAYS_FULL_QTY_KEYWORDS:
            rows = companions[keyword]
            if not rows:
                issues.append({
                    "code": "missing_companion",
                    "severity": "warning",
                    "keyword": keyword,
                    "message": (
                        f"Panels present but no {keyword} line "
                        "(astragal / retainer / top seal must ride along at full qty)"
                    ),
                })
            elif all(_f(r.get("quantity")) <= 0 for r in rows):
                issues.append({
                    "code": "companion_zero_qty",
                    "severity": "warning",
                    "keyword": keyword,
                    "item_number": rows[0].get("item_number"),
                    "message": f"{keyword} is on the PO but quantity is 0 (expected full qty)",
                })

    for ln in item_lines:
        item = (ln.get("lineObjectNumber") or "").strip()
        desc = ln.get("description") or ""
        leftover_of = _leftover_matches(item, desc, present_parent_prefixes)
        if leftover_of:
            issues.append({
                "code": "exploded_leftover",
                "severity": "warning",
                "item_number": item,
                "description": desc,
                "quantity": _f(ln.get("quantity")),
                "parent_prefixes": leftover_of,
                "message": (
                    f"{item} looks like a BOM leftover of buy-complete "
                    f"{'/'.join(leftover_of)} parent(s) already on this PO"
                ),
            })

    try:
        issues.extend(_purchase_price_issues(po, item_lines))
    except Exception:
        logger.exception("Purchase price check failed for %s", po.get("number"))

    return {
        **{k: summary[k] for k in (
            "id", "number", "vendor_number", "vendor_name", "status",
            "order_date", "external_document_number", "sales_orders",
            "line_count", "item_line_count",
        )},
        "ok": not issues,
        "has_panels": has_panels,
        "buy_complete_parents": buy_complete_parents,
        "buy_complete_prefixes_present": present_parent_prefixes,
        "companions": {
            keyword: rows for keyword, rows in companions.items() if rows
        },
        "issue_count": len(issues),
        "issues": issues,
    }


def _line_direct_cost(ln: dict) -> Optional[float]:
    """PO line price when BC returned one. A missing field is unknown, not zero."""
    if "directUnitCost" in ln:
        return _f(ln.get("directUnitCost"))
    if "direct_unit_cost" in ln:
        return _f(ln.get("direct_unit_cost"))
    return None


def _entry_direct_cost(row: dict) -> Optional[float]:
    for key in ("Direct_Unit_Cost", "directUnitCost", "Unit_Cost", "Unit_Price"):
        if key not in row or row.get(key) in (None, ""):
            continue
        try:
            return float(row[key])
        except (TypeError, ValueError):
            continue
    return None


def _best_list_price(entries: Sequence[dict]) -> Optional[float]:
    """Highest minimum quantity, then the latest starting date, wins."""
    best_cost: Optional[float] = None
    best_key: Optional[Tuple[float, str]] = None
    for row in entries:
        if not isinstance(row, dict):
            continue
        cost = _entry_direct_cost(row)
        key = (_f(row.get("Minimum_Quantity")), str(row.get("Starting_Date") or ""))
        if best_key is None or key > best_key:
            best_key = key
            best_cost = cost
    return best_cost


def _money(value: Optional[float]) -> str:
    if value is None:
        return "blank"
    text = f"{float(value):.4f}".rstrip("0").rstrip(".")
    return text or "0"


def _as_of(po: dict) -> str:
    raw = (po.get("orderDate") or "")[:10]
    if len(raw) == 10 and raw[0].isdigit():
        return raw
    from datetime import datetime
    return datetime.utcnow().strftime("%Y-%m-%d")


def _item_card_costs(item_nos: Sequence[str]) -> Optional[Dict[str, Optional[float]]]:
    fn = getattr(bc_client, "get_items_by_numbers", None)
    if not callable(fn) or not item_nos:
        return None
    try:
        cards = fn(list(item_nos))
    except Exception:
        logger.warning("Item card cost lookup failed", exc_info=True)
        return None
    if not isinstance(cards, dict):
        return None
    out: Dict[str, Optional[float]] = {}
    for number, card in cards.items():
        if not isinstance(card, dict) or "unitCost" not in card or card.get("unitCost") in (None, ""):
            out[str(number)] = None
            continue
        out[str(number)] = _f(card.get("unitCost"))
    return out


def _list_price_for_line(po: dict, ln: dict, as_of: str) -> Tuple[str, Optional[float]]:
    """('unavailable'|'missing'|'priced', price).

    Unavailable means the lookup could not be read, so the review does not
    treat that as a missing vendor price.
    """
    fn = getattr(bc_client, "get_purchase_price_lines", None)
    if not callable(fn):
        return "unavailable", None
    item = (ln.get("lineObjectNumber") or "").strip()
    try:
        result = fn(
            item_no=item,
            vendor_no=(po.get("vendorNumber") or "").strip(),
            unit_of_measure=(ln.get("unitOfMeasureCode") or "").strip(),
            qty=_f(ln.get("quantity")) or 1.0,
            as_of_date=as_of,
        )
    except Exception:
        logger.warning("Purchase price list lookup failed for %s", item, exc_info=True)
        return "unavailable", None
    if not isinstance(result, dict) or result.get("available") is not True:
        return "unavailable", None
    entries = result.get("entries")
    if not isinstance(entries, list) or not entries:
        return "missing", None
    price = _best_list_price(entries)
    if price is None or price <= 0:
        return "missing", price
    return "priced", price


def _purchase_price_issues(po: dict, item_lines: Sequence[dict]) -> List[dict]:
    """Warn when BC has no purchase price, or it does not match the item card.

    The price Business Central should use is the vendor purchase-price line
    that is valid on the PO order date. When that lookup cannot be read, the
    price already on the PO line is checked instead.
    """
    if not item_lines:
        return []
    as_of = _as_of(po)
    vendor = (po.get("vendorNumber") or "").strip() or "the vendor"
    cards = _item_card_costs([(ln.get("lineObjectNumber") or "").strip() for ln in item_lines])
    issues: List[dict] = []
    for ln in item_lines:
        item = (ln.get("lineObjectNumber") or "").strip()
        if not item:
            continue
        line_price = _line_direct_cost(ln)
        list_status, list_price = _list_price_for_line(po, ln, as_of)
        card_cost = None if cards is None else cards.get(item)
        uom = (ln.get("unitOfMeasureCode") or "").strip() or "any unit"
        qty = _f(ln.get("quantity"))

        line_missing = line_price is not None and line_price <= 0
        list_missing = list_status == "missing"
        if line_missing or list_missing:
            if line_missing and list_missing:
                message = (
                    f"{item} has no purchase price on this PO (line cost is "
                    f"{_money(line_price)}) and {vendor} has no date-valid "
                    f"purchase price for {uom}, qty {qty:g}, as of {as_of}."
                )
            elif line_missing:
                extra = ""
                if list_status == "priced":
                    extra = f" The vendor price list has {_money(list_price)}."
                message = (
                    f"{item} has no purchase price on this PO (the line is "
                    f"blank or zero). Business Central should fill it from "
                    f"{vendor}'s price list for {as_of}.{extra}"
                )
            else:
                message = (
                    f"{item} has no date-valid purchase price for {vendor} "
                    f"({uom}, qty {qty:g}, as of {as_of})."
                )
            issues.append({
                "code": "bc_price_missing",
                "severity": "warning",
                "item_number": item,
                "line_price": line_price,
                "purchase_list_price": list_price,
                "item_card_cost": card_cost,
                "as_of": as_of,
                "message": message,
            })

        compare = list_price if list_status == "priced" else (
            line_price if line_price is not None and line_price > 0 else None
        )
        if compare is not None and card_cost is not None and abs(compare - card_cost) > 0.0001:
            source = "vendor price list" if list_status == "priced" else "PO line"
            issues.append({
                "code": "bc_price_differs_from_item_cost",
                "severity": "warning",
                "item_number": item,
                "line_price": line_price,
                "purchase_list_price": list_price,
                "item_card_cost": card_cost,
                "as_of": as_of,
                "message": (
                    f"{item} {source} price {_money(compare)} differs from "
                    f"the item card cost {_money(card_cost)}."
                ),
            })
    return issues


class DraftPoReviewService:
    """Staff-facing Draft PO inventory + buy-complete validation."""

    def list_drafts(self, number: Optional[str] = None) -> dict:
        pos = bc_client.get_draft_purchase_orders_with_lines()
        drafts = [p for p in pos if (p.get("status") or "") == "Draft"]
        if number:
            want = number.strip().upper()
            drafts = [p for p in drafts if (p.get("number") or "").upper() == want]
        summarized = [summarize_po(p) for p in drafts]
        summarized.sort(key=lambda r: r.get("number") or "")
        return {
            "count": len(summarized),
            "purchase_orders": summarized,
        }

    def validate_all(self) -> dict:
        pos = bc_client.get_draft_purchase_orders_with_lines()
        drafts = [p for p in pos if (p.get("status") or "") == "Draft"]
        results = [validate_po(p) for p in drafts]
        results.sort(key=lambda r: r.get("number") or "")
        return self._bundle(results)

    def validate_one(self, po_number: str) -> dict:
        po = bc_client.get_purchase_order_by_number(po_number)
        if not po:
            raise KeyError(po_number)
        if (po.get("status") or "") != "Draft":
            raise ValueError(
                f"{po.get('number') or po_number} is status "
                f"{po.get('status')!r}, not Draft"
            )
        return validate_po(po)

    @staticmethod
    def _bundle(results: List[dict]) -> dict:
        issue_count = sum(r["issue_count"] for r in results)
        return {
            "count": len(results),
            "ok": all(r["ok"] for r in results),
            "issue_count": issue_count,
            "buy_complete_prefixes": list(_BUY_COMPLETE_PREFIXES),
            "companion_keywords": list(_ALWAYS_FULL_QTY_KEYWORDS),
            "results": results,
        }


draft_po_review_service = DraftPoReviewService()
