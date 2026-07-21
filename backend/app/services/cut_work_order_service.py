"""Cut work orders — per-SO cut plans, approved yay/nay, posted as inventory.

Ties the pieces together:
  - cutting_stock_service finds the cuts (which stock, how many, what offcut)
  - this groups them per sales order into a WORK ORDER: "cut X, Y, Z and this
    job is shippable"
  - generates the tagged item-journal spec (negative adjustment on each donor,
    positive adjustments on the job pieces + received offcuts) — the move Joey
    does by hand today, and the CUT-tagged document that makes the ledger a
    clean, auditable, mineable cut history going forward
  - on approve/reject, records a cut_feedback verdict per cut (the learning
    signal) and persists the decided work order

Proposed work orders are computed live and NOT stored; only a decided one
persists (like the buy-list vs POAgentLog). Execution is Tier A: the journal
spec is what a human posts in BC. Auto-posting waits on a BC write path.
"""

import logging
from datetime import datetime
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from app.db.models import CutWorkOrder
from app.services import sku_geometry
from app.services.cut_feedback_service import cut_feedback_service
from app.services.cutting_stock_service import CutRecommendation

logger = logging.getLogger(__name__)

# Item-journal batch tag. Every cut posts under a CUT-* document so it is
# distinguishable from count/correction adjustments in the ledger forever after.
CUT_DOC_PREFIX = "CUT"


class CutWorkOrderService:
    def build_proposed(
        self,
        recs: List[CutRecommendation],
        catalog_skus,
        so_numbers: Optional[List[str]] = None,
    ) -> List[dict]:
        """Group cut recommendations into per-SO work orders, live (not stored).

        ``recs`` are CutRecommendation objects from cutting_stock_service.
        ``catalog_skus`` is the SKU list used to resolve each offcut to a
        receivable size. Returns work-order dicts ordered by purchase avoided
        (the invoiceable-value proxy) descending.
        """
        by_so: Dict[str, List[CutRecommendation]] = {}
        for r in recs:
            for so in (r.jobs or ["(unassigned)"]):
                if so_numbers and so not in so_numbers:
                    continue
                by_so.setdefault(so, []).append(r)

        work_orders = []
        for so, so_recs in by_so.items():
            journal = self._build_journal(so, so_recs, catalog_skus)
            avoided = round(sum(r.unit_cost_avoided for r in so_recs), 2)
            all_within = all(r.within_tolerance for r in so_recs)
            work_orders.append({
                "so_number": so,
                "status": "proposed",
                "makes_invoiceable": True,   # every cut here satisfies a shortfall on this SO
                "purchase_avoided": avoided,
                "all_within_tolerance": all_within,
                "cuts": [r.to_dict() for r in so_recs],
                "journal": journal,
            })

        work_orders.sort(key=lambda w: w["purchase_avoided"], reverse=True)
        return work_orders

    def build_live_proposals(self, db: Session, so_number: Optional[str] = None) -> List[dict]:
        """The full pipeline behind the approval window: demand -> donor stock
        from live inventory -> cut analysis -> per-SO work orders, each stamped
        with its prior verdict so the reviewer sees "you approved this before".

        Imports its heavy deps lazily to avoid a circular import at module load.
        """
        from app.services.purchasing_demand_service import purchasing_demand_service
        from app.services.bc_part_number_mapper import get_bc_mapper
        from app.integrations.bc.client import bc_client
        from app.services.cutting_stock_service import cutting_stock_service
        from app.services.cut_feedback_service import cut_feedback_service as fb

        req = purchasing_demand_service.compute_requirements(db, include_met=True, horizon_weeks=None)
        catalog = list(get_bc_mapper().bc_items.keys())

        def inv_lookup(skus):
            return {
                s: {"inventory": m.get("inventory"), "unitCost": m.get("unitCost"),
                    "displayName": m.get("displayName")}
                for s, m in bc_client.get_items_by_numbers(skus).items()
            }

        donors = cutting_stock_service.donor_rows_for_shortfalls(req["items"], catalog, inv_lookup)
        recs = cutting_stock_service.analyze(req["items"] + donors)

        so_filter = [so_number] if so_number else None
        proposals = self.build_proposed(recs, catalog, so_numbers=so_filter)

        # Stamp each cut with its prior verdict (one batched query per WO).
        for wo in proposals:
            wo["cuts"] = fb.annotate_recommendations(db, wo["cuts"])
        return proposals

    def _build_journal(
        self, so_number: str, recs: List[CutRecommendation], catalog_skus
    ) -> dict:
        """The item-journal spec: negative adjustment per donor stick, positive
        adjustments for the job pieces produced and the offcuts received.

        Mirrors the manual process exactly — down the donor, up the pieces —
        and every line shares one CUT document number so the whole cut is a
        single, attributable ledger event.
        """
        document_no = f"{CUT_DOC_PREFIX}-{so_number.replace('SO-', '') or so_number}"
        lines: List[dict] = []

        for r in recs:
            geo = sku_geometry.parse(r.donor_sku)
            family = geo.family if geo else None

            # Negative: consume the donor sticks.
            lines.append({
                "item_no": r.donor_sku,
                "entry_type": "Negative Adjmt.",
                "quantity": r.donor_sticks_used,
                "reason": f"cut into {r.pieces_yielded}x {sku_geometry.format_inches(r.target_length_inches)} for {so_number}",
            })
            # Positive: the job pieces produced.
            lines.append({
                "item_no": r.target_sku,
                "entry_type": "Positive Adjmt.",
                "quantity": r.pieces_yielded,
                "reason": f"cut from {r.donor_sku} for {so_number}",
            })
            # Positive: received offcuts, resolved to a receivable catalog SKU.
            for plan in r.plans:
                leftover = int(round(plan.waste_inches))
                offcut_sku = sku_geometry.resolve_length_to_sku(family, leftover, catalog_skus) if family else None
                if offcut_sku and offcut_sku not in (r.donor_sku, r.target_sku):
                    lines.append({
                        "item_no": offcut_sku,
                        "entry_type": "Positive Adjmt.",
                        "quantity": 1,
                        "reason": f"offcut from {r.donor_sku}",
                    })

        return {"document_no": document_no, "lines": self._merge_lines(lines)}

    @staticmethod
    def _merge_lines(lines: List[dict]) -> List[dict]:
        """Combine identical (item, entry_type) lines so the journal shows one
        line per SKU per direction, not one per stick."""
        merged: Dict[tuple, dict] = {}
        order: List[tuple] = []
        for ln in lines:
            key = (ln["item_no"], ln["entry_type"])
            if key not in merged:
                merged[key] = dict(ln)
                order.append(key)
            else:
                merged[key]["quantity"] += ln["quantity"]
        return [merged[k] for k in order]

    # ---- decisions ----------------------------------------------------------

    def approve(
        self, db: Session, work_order: dict, created_by: Optional[int] = None,
        source: str = "portal",
    ) -> CutWorkOrder:
        """Approve a proposed work order: persist it and record an approved
        verdict for each cut (the learning signal)."""
        return self._decide(db, work_order, "approved", None, created_by, source)

    def reject(
        self, db: Session, work_order: dict, reason: str,
        created_by: Optional[int] = None, source: str = "portal",
    ) -> CutWorkOrder:
        """Reject a work order: persist it and record a rejected verdict + reason
        for each cut, so the engine learns not to keep proposing it."""
        return self._decide(db, work_order, "rejected", reason, created_by, source)

    def _decide(
        self, db: Session, work_order: dict, verdict: str,
        reason: Optional[str], created_by: Optional[int], source: str = "portal",
    ) -> CutWorkOrder:
        so = work_order["so_number"]
        now = datetime.utcnow()

        wo = CutWorkOrder(
            so_number=so,
            status=verdict,
            makes_invoiceable=work_order.get("makes_invoiceable", False),
            purchase_avoided=work_order.get("purchase_avoided"),
            plan_json=work_order.get("cuts"),
            journal_json=work_order.get("journal"),
            reason=reason,
            approved_by=created_by if verdict == "approved" else None,
            approved_at=now if verdict == "approved" else None,
            rejected_by=created_by if verdict == "rejected" else None,
            rejected_at=now if verdict == "rejected" else None,
        )
        db.add(wo)

        for cut in work_order.get("cuts", []):
            cut_feedback_service.record_verdict(
                db,
                target_sku=cut.get("target_sku"),
                donor_sku=cut.get("donor_sku"),
                verdict=verdict,
                reason=reason,
                so_number=so,
                qty_pieces=cut.get("pieces_yielded"),
                scrap_inches=cut.get("scrap_inches"),
                opportunity=cut,
                source=source,
                created_by=created_by,
            )
        db.flush()
        logger.info("Work order %s %s (%d cuts)", so, verdict, len(work_order.get("cuts", [])))
        return wo

    def pending_posting(self, db: Session) -> List[CutWorkOrder]:
        """Approved work orders whose inventory move has not yet been posted in
        BC — the manual posting queue. Oldest first, so nothing lingers."""
        return (
            db.query(CutWorkOrder)
            .filter(CutWorkOrder.status == "approved")
            .order_by(CutWorkOrder.created_at.asc())
            .all()
        )

    def mark_posted(
        self, db: Session, work_order_id: int, document_no: str
    ) -> Optional[CutWorkOrder]:
        """Record that the approved work order's journal was posted in BC."""
        wo = db.query(CutWorkOrder).filter(CutWorkOrder.id == work_order_id).first()
        if wo is None:
            return None
        wo.status = "posted"
        wo.posted_at = datetime.utcnow()
        wo.posted_document_no = document_no
        db.flush()
        return wo


cut_work_order_service = CutWorkOrderService()
