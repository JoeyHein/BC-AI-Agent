"""
Item → Vendor mapping service for the purchasing tool.

Resolves which vendor supplies each item so shortfalls can be grouped and
turned into per-vendor purchase orders. Sources, highest precedence first:

    manual  — a purchaser assigned it in the UI (never auto-overwritten)
    bc      — the BC item card's default Vendor No. (once an Items web
              service exposing Vendor_No is published; graceful no-op until)
    history — derived from open + posted purchase orders/invoices (works today)
"""

import logging
from collections import defaultdict
from datetime import datetime
from typing import Dict, Optional, Tuple

from sqlalchemy.orm import Session

from app.db.models import ItemVendorMap
from app.integrations.bc.client import bc_client
from app.services.bc_production_service import bc_production_service
from app.services.vendor_policy import is_preferred

logger = logging.getLogger(__name__)

SOURCE_PRECEDENCE = {"manual": 3, "bc": 2, "history": 1}

# Candidate OData web-service names that may expose the item card's Vendor_No.
# Whichever responds is used; all 404 → vendor stays from history/manual.
BC_ITEM_CARD_ENDPOINTS = ("Items", "ItemCard", "ItemList")


class VendorMapService:
    def load_map(self, db: Session) -> Dict[str, dict]:
        """Return {item_no: {vendor_no, vendor_name, source}} for fast resolution."""
        rows = db.query(ItemVendorMap).all()
        return {
            r.bc_item_number: {
                "vendor_no": r.vendor_no,
                "vendor_name": r.vendor_name,
                "source": r.source,
            }
            for r in rows
        }

    def resolve(self, db: Session, item_no: str) -> Tuple[Optional[str], Optional[str]]:
        row = db.query(ItemVendorMap).get(item_no)
        if row:
            return row.vendor_no, row.vendor_name
        return None, None

    def set_manual(self, db: Session, item_no: str, vendor_no: Optional[str],
                   vendor_name: Optional[str]) -> ItemVendorMap:
        """Assign/override an item's vendor from the UI. Always wins."""
        row = db.query(ItemVendorMap).get(item_no)
        if not row:
            row = ItemVendorMap(bc_item_number=item_no)
            db.add(row)
        row.vendor_no = vendor_no
        row.vendor_name = vendor_name
        row.source = "manual"
        row.updated_at = datetime.utcnow()
        db.flush()
        return row

    def refresh(self, db: Session) -> dict:
        """Repopulate history/bc-sourced mappings without touching manual rows."""
        stats = {"history_upserts": 0, "bc_upserts": 0, "errors": []}

        derived = self._derive_from_purchase_history()
        for item_no, (vno, vname) in derived.items():
            if self._upsert(db, item_no, vno, vname, "history"):
                stats["history_upserts"] += 1

        # Flush history rows so the BC pass's .get() sees them as persistent and
        # UPDATEs (vs. adding a second pending row with the same PK → duplicate
        # key on an empty table — the two passes share many items).
        db.flush()

        try:
            from_bc = self._fetch_item_card_vendors()
            for item_no, (vno, vname) in from_bc.items():
                if self._upsert(db, item_no, vno, vname, "bc"):
                    stats["bc_upserts"] += 1
        except Exception as e:
            stats["errors"].append(f"bc item-card vendor pull skipped: {e}")

        db.flush()
        logger.info(f"[VendorMap] refresh: {stats}")
        return stats

    # ─── internals ─────────────────────────────────────────────

    def _upsert(self, db: Session, item_no: str, vendor_no: Optional[str],
                vendor_name: Optional[str], source: str) -> bool:
        """Write a mapping only if it doesn't downgrade an equal/higher-precedence
        source. Returns True if a row was created/updated."""
        row = db.query(ItemVendorMap).get(item_no)
        incoming = SOURCE_PRECEDENCE[source]
        if row and SOURCE_PRECEDENCE.get(row.source, 0) > incoming:
            return False  # keep higher-precedence (e.g. manual over history)
        if not row:
            row = ItemVendorMap(bc_item_number=item_no)
            db.add(row)
        row.vendor_no = vendor_no
        row.vendor_name = vendor_name
        row.source = source
        row.updated_at = datetime.utcnow()
        return True

    def _derive_from_purchase_history(self) -> Dict[str, Tuple[Optional[str], Optional[str]]]:
        """Best vendor to source each item from, per the sourcing policy:
        the most-recent PREFERRED vendor we've bought it from; only if there's
        no preferred-vendor history do we fall back to the most-recent vendor
        (which may be expedite-only, e.g. DEK). Pulls dated candidates from open
        POs, posted invoices and posted receipts."""
        # item -> list of (date_str, vendor_no, vendor_name)
        cands: Dict[str, list] = defaultdict(list)

        def add(item, date_str, vno, vname):
            if item and vno:
                cands[item].append((date_str or "", vno, vname))

        try:
            for po in bc_client.get_open_purchase_orders_with_lines():
                vno, vname, d = po.get("vendorNumber"), po.get("vendorName"), po.get("orderDate")
                for ln in po.get("purchaseOrderLines", []):
                    if ln.get("lineType") == "Item":
                        add(ln.get("lineObjectNumber"), d, vno, vname)
        except Exception as e:
            logger.warning(f"[VendorMap] open PO derivation failed: {e}")

        try:
            url = (f"{bc_client.base_url}/companies({bc_client.company_id})"
                   f"/purchaseInvoices?$expand=purchaseInvoiceLines")
            for inv in bc_client._paginate_v2(url, "purchase invoices"):
                vno, vname, d = inv.get("vendorNumber"), inv.get("vendorName"), inv.get("invoiceDate")
                for ln in inv.get("purchaseInvoiceLines", []):
                    if ln.get("lineType") == "Item":
                        add(ln.get("lineObjectNumber"), d, vno, vname)
        except Exception as e:
            logger.warning(f"[VendorMap] purchase-invoice derivation failed: {e}")

        try:
            for rcpt in bc_client.get_purchase_receipts_with_lines():
                vno, vname, d = rcpt.get("vendorNumber"), rcpt.get("vendorName"), rcpt.get("postingDate")
                for ln in rcpt.get("purchaseReceiptLines", []):
                    if ln.get("lineType") == "Item":
                        add(ln.get("lineObjectNumber"), d, vno, vname)
        except Exception as e:
            logger.warning(f"[VendorMap] receipt derivation failed: {e}")

        item_vendor: Dict[str, Tuple[Optional[str], Optional[str]]] = {}
        for item, rows in cands.items():
            preferred = [r for r in rows if is_preferred(r[1])]
            pool = preferred or rows  # prefer preferred vendors; else fall back
            best = max(pool, key=lambda r: r[0])  # most recent by date
            item_vendor[item] = (best[1], best[2])
        return item_vendor

    def _fetch_item_card_vendors(self) -> Dict[str, Tuple[Optional[str], Optional[str]]]:
        """Authoritative default vendor from the BC item card, if a web service
        exposing Vendor_No is published. Returns {} otherwise (graceful)."""
        out: Dict[str, Tuple[Optional[str], Optional[str]]] = {}
        vendor_names: Dict[str, str] = {}
        for endpoint in BC_ITEM_CARD_ENDPOINTS:
            resp = bc_production_service._make_odata_request(
                endpoint, query_params={"$select": "No,Vendor_No", "$top": "2000"}
            )
            if resp and "value" in resp and resp["value"]:
                # Lazily resolve vendor numbers → names once.
                for r in resp["value"]:
                    item_no = r.get("No")
                    vno = r.get("Vendor_No")
                    if not item_no or not vno:
                        continue
                    if vno not in vendor_names:
                        vendor_names[vno] = self._vendor_name(vno)
                    out[item_no] = (vno, vendor_names[vno])
                logger.info(f"[VendorMap] item-card vendors via '{endpoint}': {len(out)}")
                break
        return out

    @staticmethod
    def _vendor_name(vendor_no: str) -> Optional[str]:
        try:
            res = bc_client._make_request(
                "GET",
                f"companies({bc_client.company_id})/vendors?$filter=number eq '{vendor_no}'&$select=number,displayName",
            )
            vals = res.get("value", [])
            return vals[0].get("displayName") if vals else None
        except Exception:
            return None


vendor_map_service = VendorMapService()
