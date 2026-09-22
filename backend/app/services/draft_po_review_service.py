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
        lines.append({
            "sequence": ln.get("sequence"),
            "line_type": ln.get("lineType"),
            "item_number": ln.get("lineObjectNumber") or None,
            "description": ln.get("description") or "",
            "quantity": _f(ln.get("quantity")),
            "received_quantity": _f(ln.get("receivedQuantity")),
            "unit_of_measure": ln.get("unitOfMeasureCode") or None,
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
