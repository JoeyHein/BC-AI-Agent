"""
Purchasing intelligence: cost, last-purchase and lead-time signals that enrich
the purchasing requirements so buyers can make sourcing decisions.

Sources (all read-only):
  - last received per item   ← api/v2.0 purchaseReceipts + lines (actual qty/cost/date/vendor)
  - last direct cost per item ← ODataV4 Items.Last_Direct_Cost
  - vendor lead times         ← ODataV4 PurchRcptHeader (Posting_Date − Order_Date),
                                median days per vendor. Returns {} until that web
                                service is published (graceful, like production WS).

Pulls are bulk + cached briefly (TTL) so the dashboard/digest stays responsive.
"""

import logging
import statistics
import time
from datetime import date
from typing import Dict, List, Optional

from app.integrations.bc.client import bc_client
from app.services.bc_production_service import bc_production_service

logger = logging.getLogger(__name__)

_CACHE_TTL_SECONDS = 600  # 10 min — this data changes slowly


class PurchasingIntelService:
    def __init__(self):
        self._cache: Dict[str, tuple] = {}  # key -> (expires_at, value)

    def _cached(self, key: str, producer):
        hit = self._cache.get(key)
        if hit and hit[0] > time.monotonic():
            return hit[1]
        value = producer()
        self._cache[key] = (time.monotonic() + _CACHE_TTL_SECONDS, value)
        return value

    # ─── last received per item (actual purchases) ────────────────
    def last_received_by_item(self) -> Dict[str, dict]:
        """{item_no: {date, vendor_no, vendor_name, unit_cost}} — most recent
        posted receipt line per item. Reflects who we actually bought from last
        and at what real cost (may differ from the item card's default vendor)."""
        return self._cached("last_received", self._build_last_received)

    def _build_last_received(self) -> Dict[str, dict]:
        out: Dict[str, dict] = {}
        try:
            receipts = bc_client.get_purchase_receipts_with_lines()
        except Exception as e:
            logger.warning(f"[PurchIntel] receipt history unavailable: {e}")
            return out
        for r in receipts:
            d = r.get("postingDate") or ""
            for ln in r.get("purchaseReceiptLines", []):
                if ln.get("lineType") != "Item":
                    continue
                item = ln.get("lineObjectNumber")
                if not item:
                    continue
                prev = out.get(item)
                if prev is None or d > prev["date"]:
                    out[item] = {
                        "date": d,
                        "vendor_no": r.get("vendorNumber"),
                        "vendor_name": r.get("vendorName"),
                        "unit_cost": float(ln.get("unitCost") or 0),
                    }
        return out

    # ─── last direct cost per item (BC item card) ─────────────────
    def last_direct_cost_by_item(self) -> Dict[str, float]:
        """{item_no: Last_Direct_Cost} from the BC item card."""
        return self._cached("last_direct_cost", self._build_last_direct_cost)

    def _build_last_direct_cost(self) -> Dict[str, float]:
        out: Dict[str, float] = {}
        try:
            rows = bc_production_service._make_odata_request_all(
                "Items", query_params={"$select": "No,Last_Direct_Cost"}
            )
        except Exception as e:
            logger.warning(f"[PurchIntel] last direct cost unavailable: {e}")
            return out
        for r in rows:
            no = r.get("No")
            if no and r.get("Last_Direct_Cost") is not None:
                out[no] = float(r["Last_Direct_Cost"])
        return out

    # ─── vendor lead times (empirical) ────────────────────────────
    def vendor_lead_times(self) -> Dict[str, dict]:
        """{vendor_no: {median_days, sample_size}} from posted receipts
        (Posting_Date − Order_Date). Needs the PurchRcptHeader web service
        published; returns {} (graceful) until then."""
        return self._cached("vendor_lead_times", self._build_vendor_lead_times)

    def _build_vendor_lead_times(self) -> Dict[str, dict]:
        # Fetch without $select so we adapt to whatever the PurchRcptHeader
        # publication exposes. Receipt-based lead time = Posting_Date − Order_Date,
        # but the current publication (Page 138) does NOT expose Order Date, so
        # this yields {} and manual item_lead_time entries are the source. It
        # self-heals: republish PurchRcptHeader as a query including the Order
        # Date column and this lights up with no code change.
        try:
            rows = bc_production_service._make_odata_request_all("PurchRcptHeader")
        except Exception as e:
            logger.warning(f"[PurchIntel] PurchRcptHeader unavailable: {e}")
            return {}
        if not rows or "Order_Date" not in (rows[0] or {}):
            return {}
        by_vendor: Dict[str, List[int]] = {}
        for r in rows:
            v = r.get("Buy_from_Vendor_No")
            days = _days_between(r.get("Order_Date"), r.get("Posting_Date"))
            if v and days is not None and days >= 0:
                by_vendor.setdefault(v, []).append(days)
        return {
            v: {"median_days": round(statistics.median(ds)), "sample_size": len(ds)}
            for v, ds in by_vendor.items()
        }


def _days_between(order_str: Optional[str], posting_str: Optional[str]) -> Optional[int]:
    if not order_str or not posting_str:
        return None
    try:
        o = date.fromisoformat(order_str[:10])
        p = date.fromisoformat(posting_str[:10])
        return (p - o).days
    except ValueError:
        return None


purchasing_intel_service = PurchasingIntelService()
