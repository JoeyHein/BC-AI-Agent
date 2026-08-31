"""
Sales-order → purchase-order linkage.

BC does not publish PO comment lines as a web service in this tenant, so the
reliable record of "which PO covers which sales order" is our own
POAgentLog.so_allocations — written whenever a PO is drafted through the
tool (nightly auto-PO, and manual per-vendor generation). POs a buyer keys
straight into BC by hand won't appear here.

Used by the production schedule to show, per open SO, whether material has
been ordered and on which PO.
"""

import logging
from collections import defaultdict
from typing import Dict, List

from sqlalchemy.orm import Session

from app.db.models import POAgentLog

logger = logging.getLogger(__name__)

# Statuses that mean the PO is dead — its allocation no longer counts.
_DEAD = {"rejected", "failed", "cancelled", "canceled"}


class PoSoLinkService:
    def links_by_so(self, db: Session) -> Dict[str, List[dict]]:
        """{so_number: [{po_number, po_id, vendor_name, status, is_auto,
        created_at, items:[{item_no, qty}]}]}, newest PO first."""
        out: Dict[str, List[dict]] = defaultdict(list)
        rows = (
            db.query(POAgentLog)
            .filter(POAgentLog.so_allocations.isnot(None))
            .order_by(POAgentLog.created_at.desc())
            .all()
        )
        for r in rows:
            if (r.status or "").lower() in _DEAD:
                continue
            alloc = r.so_allocations or {}
            for so_no, items in alloc.items():
                out[so_no].append({
                    "po_number": r.bc_po_number,
                    "po_id": r.bc_po_id,
                    "vendor_name": r.vendor_name,
                    "vendor_no": r.vendor_id,
                    "status": r.bc_status or r.status,
                    "is_auto": bool(r.is_auto),
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                    "items": items,
                })
        return out

    def summary_by_so(self, db: Session) -> Dict[str, dict]:
        """Compact per-SO rollup for a spreadsheet cell: the PO numbers and a
        one-line label."""
        result: Dict[str, dict] = {}
        for so_no, links in self.links_by_so(db).items():
            numbers = [l["po_number"] for l in links if l["po_number"]]
            labels = []
            for l in links:
                tag = l["po_number"] or "(pending)"
                if str(l["status"]).lower() in ("draft", "auto_draft", "submitted"):
                    tag += " (draft)"
                labels.append(tag)
            result[so_no] = {
                "po_numbers": numbers,
                "label": ", ".join(labels),
                "count": len(links),
                "any_auto": any(l["is_auto"] for l in links),
            }
        return result


po_so_link_service = PoSoLinkService()
