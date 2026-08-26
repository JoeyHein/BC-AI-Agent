"""
Cross-check: our purchasing coverage vs BC's native SalesOrderMaster.

`so_coverage_service` answers "has anything been bought" by netting raw
materials (on-hand + open-PO vs open-SO/production demand) — reconstructed
externally, and BC's SO/PO fields have been unreliable in the past
(shippedQuantity unmaintained, fullyShipped wrong, best-effort SO<->prod-order
matching via reservation entries).

SalesOrderMaster (custom ODC page 50023, refreshed nightly in BC) is a
different, BC-native signal: one row per open sales-order LINE, each carrying
a Status BC computes itself, plus a direct Prodn_Order_No link — no
reservation-entry guessing needed. Inferred from live data (2026-08-26):

    From Stock  — fulfilled from on-hand inventory, no production order.
    Unscheduled — tied to a production order (Prodn_Order_No set) that
                  hasn't finished yet (Qty_to_Manufacture > 0).
    Finished    — tied to a production order that HAS finished
                  (Qty_to_Manufacture == 0).

These label meanings aren't documented in BC — they're inferred from
sampled rows, not confirmed by Joey. Treat disagreements as leads to
investigate, not proof either side is wrong.

The two signals track different axes: so_coverage is about raw-material
PURCHASING, SalesOrderMaster is about component BUILD status. An order can
be fully purchased and still not shippable if a line is mid-production —
that's exactly the case this cross-check is meant to surface. Disagreement
directions:

  our "covered" + BC has an Unscheduled line
      -> purchasing looks done but the order still can't ship; something is
         mid-production. NOT necessarily a bug in either tool.
  our "gap"/"not_started" + BC shows every line From Stock/Finished
      -> our raw-material netting may have a false positive (e.g. an
         unexploded manufactured-item BOM, a stale reservation). Worth
         checking so_coverage's item list against BC's Qty_In_Stock here.

See also [[project_so_coverage_tab]], [[project_purchasing_tool]].
"""
import logging
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from app.services.bc_production_service import bc_production_service
from app.services.so_coverage_service import so_coverage_service

logger = logging.getLogger(__name__)

BC_UNSCHEDULED_STATUS = "Unscheduled"


class SOMasterCrossCheckService:

    def fetch_by_so(self) -> Dict[str, List[dict]]:
        """{sales_order_no: [SalesOrderMaster line rows]}."""
        rows = bc_production_service.get_sales_order_master()
        by_so: Dict[str, List[dict]] = {}
        for r in rows:
            so_no = (r.get("Sales_Order_No") or "").strip()
            if so_no:
                by_so.setdefault(so_no, []).append(r)
        return by_so

    def _bc_signal(self, lines: List[dict]) -> dict:
        unscheduled = [ln for ln in lines if ln.get("Status") == BC_UNSCHEDULED_STATUS]
        return {
            "line_count": len(lines),
            "unscheduled_count": len(unscheduled),
            "bc_ready": len(unscheduled) == 0,
            "unscheduled_parts": sorted({
                ln.get("Part_No") for ln in unscheduled if ln.get("Part_No")
            }),
        }

    def build(self, db: Session, **coverage_kwargs) -> dict:
        """Pure w.r.t. its own inputs — coverage + BC master are each fetched
        once. Returns every matched SO (agree and disagree) plus the
        disagreement subset, since agreement counts are the trust signal for
        whether to lean on this more."""
        coverage = so_coverage_service.build(db, **coverage_kwargs)
        by_so = self.fetch_by_so()

        rows = []
        for order in coverage["orders"]:
            so_no = order["so_number"]
            lines = by_so.get(so_no)
            if lines is None:
                continue  # not in BC's current snapshot — closed/invoiced/typo'd SO
            bc = self._bc_signal(lines)
            our_says_done = order["status"] == "covered"
            agrees = our_says_done == bc["bc_ready"]
            rows.append({
                "so_number": so_no,
                "customer": order["customer"],
                "our_status": order["status"],
                "urgency": order["urgency"],
                "bc_ready": bc["bc_ready"],
                "bc_line_count": bc["line_count"],
                "bc_unscheduled_count": bc["unscheduled_count"],
                "bc_unscheduled_parts": bc["unscheduled_parts"],
                "agrees": agrees,
            })

        disagreements = [r for r in rows if not r["agrees"]]
        return {
            "generated_at": coverage["generated_at"],
            "total_open_orders": len(coverage["orders"]),
            "matched_in_bc_master": len(rows),
            "unmatched_in_bc_master": len(coverage["orders"]) - len(rows),
            "agree_count": len(rows) - len(disagreements),
            "disagree_count": len(disagreements),
            "disagreements": disagreements,
            "rows": rows,
        }


so_master_crosscheck_service = SOMasterCrossCheckService()
