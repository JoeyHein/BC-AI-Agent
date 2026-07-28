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
import time
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

# The full proposal build hits BC hard (compute_requirements ~28s + a ledger
# call per donor), so the whole-queue result is cached briefly. Any decision
# (approve/reject/post) invalidates it so the queue reflects the change at once.
_PROPOSALS_TTL_SECONDS = 300


class CutWorkOrderService:
    def __init__(self):
        self._proposals_cache = None   # (expires_at_epoch, value)

    def invalidate_proposals_cache(self):
        self._proposals_cache = None

    def build_proposed(
        self,
        recs: List[CutRecommendation],
        catalog_skus,
        so_numbers: Optional[List[str]] = None,
        prod_so_map: Optional[Dict[str, str]] = None,
    ) -> List[dict]:
        """Group cut recommendations into per-SO work orders, live (not stored).

        ``recs`` are CutRecommendation objects from cutting_stock_service.
        ``catalog_skus`` is the SKU list used to resolve each offcut to a
        receivable size. ``prod_so_map`` ({PROD->SO} from BC reservations)
        re-anchors production orders under their parent sales order, so a job
        that surfaces as PROD-xxx is grouped and shown under SO-xxx with the
        production order noted on each cut. Empty map (service not yet
        published) => production orders stand on their own, as before.

        Returns work-order dicts ordered by purchase avoided descending.
        """
        prod_so_map = prod_so_map or {}

        # (grouping key, per-cut origin job) — the origin is the raw job so the
        # card can show which production order each cut belongs to.
        by_key: Dict[str, List[tuple]] = {}
        for r in recs:
            for job in (r.jobs or ["(unassigned)"]):
                key = prod_so_map.get(job, job)   # PROD -> its SO when known
                if so_numbers and key not in so_numbers:
                    continue
                by_key.setdefault(key, []).append((r, job))

        work_orders = []
        for key, pairs in by_key.items():
            so_recs = [r for r, _ in pairs]
            origin = {id(r): job for r, job in pairs}
            journal = self._build_journal(key, so_recs, catalog_skus)
            avoided = round(sum(r.unit_cost_avoided for r in so_recs), 2)
            all_within = all(r.within_tolerance for r in so_recs)
            # Production orders represented under this SO.
            prod_orders = sorted({job for _, job in pairs if job != key and str(job).startswith("PROD")})
            cuts = []
            for r in so_recs:
                d = r.to_dict()
                job = origin.get(id(r))
                d["prod_order"] = job if job != key and str(job).startswith("PROD") else None
                cuts.append(d)
            work_orders.append({
                "so_number": key,
                "status": "proposed",
                "makes_invoiceable": True,
                "purchase_avoided": avoided,
                "all_within_tolerance": all_within,
                "prod_orders": prod_orders,
                "cuts": cuts,
                "journal": journal,
            })

        work_orders.sort(key=lambda w: w["purchase_avoided"], reverse=True)
        return work_orders

    def build_live_proposals(self, db: Session, so_number: Optional[str] = None) -> List[dict]:
        """The full pipeline behind the approval window: demand -> donor stock
        from live inventory -> cut analysis -> per-SO work orders, each stamped
        with its prior verdict so the reviewer sees "you approved this before".

        Imports its heavy deps lazily to avoid a circular import at module load.
        The full-queue result is cached briefly (the build hits BC hard); an
        explicit so_number (the approve/reject rebuild path) always runs fresh.
        """
        if so_number is None and self._proposals_cache and self._proposals_cache[0] > time.time():
            return self._proposals_cache[1]

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

        from app.services.cut_rule_service import cut_rule_service
        sup_pairs, sup_families = cut_rule_service.active_suppressions(db)

        donors = cutting_stock_service.donor_rows_for_shortfalls(req["items"], catalog, inv_lookup)
        recs = cutting_stock_service.analyze(
            req["items"] + donors,
            suppressed_pairs=sup_pairs, suppressed_families=sup_families,
        )

        # PROD->SO reservation map + purchase-vs-manufacture map.
        from app.services.bc_production_service import bc_production_service
        try:
            prod_so_map = bc_production_service.get_prod_so_map()
        except Exception as e:
            logger.warning(f"prod->SO map unavailable: {e}")
            prod_so_map = {}
        try:
            replen_map = bc_production_service.get_replenishment_map()
        except Exception as e:
            logger.warning(f"replenishment map unavailable: {e}")
            replen_map = {}

        so_filter = [so_number] if so_number else None
        proposals = self.build_proposed(recs, catalog, so_numbers=so_filter, prod_so_map=prod_so_map)

        # Drop SOs already decided — an approved/posted cut plan shouldn't keep
        # reappearing in the queue for the same job. (When so_number is given
        # explicitly — the approve/reject path rebuilding to act — we keep it.)
        if not so_number:
            decided = {
                so for (so,) in db.query(CutWorkOrder.so_number)
                .filter(CutWorkOrder.status.in_(("approved", "posted")))
                .all()
            }
            if decided:
                proposals = [w for w in proposals if w["so_number"] not in decided]

        # Stamp each cut with its prior verdict (one batched query per WO).
        for wo in proposals:
            wo["cuts"] = fb.annotate_recommendations(db, wo["cuts"])

        self._assess_completeness(proposals, req, prod_so_map, replen_map)
        self._annotate_blocker_workarounds(proposals, get_bc_mapper(), inv_lookup)
        self._annotate_velocity(proposals)

        if so_number is None:
            self._proposals_cache = (time.time() + _PROPOSALS_TTL_SECONDS, proposals)
        return proposals

    def _annotate_blocker_workarounds(self, proposals, mapper, inv_lookup) -> None:
        """Tag glass-kit blockers with their workaround (paint a different-colour
        frame, commercial flexibility, residential long/short) so a blocked order
        still shows how it might be worked around rather than a dead end."""
        from app.services.glass_kit_service import glass_kit_service

        gk_catalog = {
            sku: (it.get("displayName") or it.get("description") or "")
            for sku, it in mapper.bc_items.items() if sku.startswith("GK")
        }
        # Which glass kits are blocking anything?
        gk_blockers = {
            b["item_no"] for wo in proposals for b in wo.get("blockers", [])
            if b["item_no"].startswith("GK")
        }
        if not gk_blockers:
            return

        # Candidate paint-substitutes: same paint_key, any colour. Look their
        # live stock up once, in a single batch.
        from app.services.glass_kit_service import parse_gk
        # Paint substitutes only matter for RESIDENTIAL (GK15) blockers.
        keys = {}
        for sku in gk_blockers:
            g = parse_gk(sku, gk_catalog.get(sku, ""))
            if g and g["paintable"]:
                keys[sku] = g["paint_key"]
        candidates = set()
        for sku, desc in gk_catalog.items():
            g = parse_gk(sku, desc)
            if g and g["paintable"] and g["paint_key"] in keys.values():
                candidates.add(sku)
        stock = {}
        if candidates:
            stock = {s: (m.get("inventory") or 0) for s, m in inv_lookup(list(candidates)).items()}

        for wo in proposals:
            for b in wo.get("blockers", []):
                if not b["item_no"].startswith("GK"):
                    continue
                wa = glass_kit_service.workaround(
                    b["item_no"], gk_catalog.get(b["item_no"], ""), gk_catalog, stock
                )
                if wa:
                    b["workaround"] = wa

    def _assess_completeness(self, proposals: List[dict], req: dict,
                             prod_so_map: Optional[Dict[str, str]] = None,
                             replen_map: Optional[Dict[str, str]] = None) -> None:
        """Decide whether each cut ACTUALLY makes its sales order shippable.

        A cut only earns "invoiceable now" if it clears the LAST thing standing
        between the order and the dock. Cutting a shaft for SO-1225 is pointless
        if the order still needs panels that aren't in stock — so the work order
        looks at ALL of the SO's shortfalls, marks the ones its cuts cover, and
        flags whatever still blocks the order. makes_invoiceable is true only
        when nothing is left blocking.

        Each blocker is classified by its FULFILLMENT PATH — a PO and a
        production order are completely different: an item is "needs_production"
        if BC replenishes it by Prod. Order, "cuttable" if we can cut it from
        stock, otherwise "needs_po". on_order (product already arriving on a PO)
        is carried too, so a blocker shows whether it's partly covered.

        Shortfalls tagged to a production order roll up to its sales order via
        prod_so_map, matching how the work orders are grouped.
        """
        prod_so_map = prod_so_map or {}
        replen_map = replen_map or {}
        # Per-item snapshot (net_need + on_order) and which SOs need it. net_need
        # is already netted against stock + open POs, so >0 means genuinely short.
        item_snap: Dict[str, dict] = {}
        so_short: Dict[str, Dict[str, float]] = {}
        for item in req.get("items", []):
            item_snap[item["item_no"]] = item
            nn = item.get("net_need") or 0
            if nn <= 0:
                continue
            for job in item.get("jobs", []):
                key = prod_so_map.get(job, job)
                so_short.setdefault(key, {})[item["item_no"]] = nn

        def _fulfillment(itm: str) -> str:
            # Replenishment wins over geometry: a finished SEC/DEC panel parses
            # as cuttable but is MANUFACTURED (Prod. Order) — it's made, not cut.
            # Only purchased bulk (Purchase + cuttable) is genuinely cuttable.
            #
            # No replenishment answer for this item (the BC Items page timed out,
            # or the item isn't on it) means we genuinely CANNOT tell a PO from a
            # production order — say "unknown" rather than defaulting to
            # needs_po, which reads as a confident answer we don't have.
            replen = replen_map.get(itm)
            if not replen:
                return "unknown"
            if str(replen).startswith("Prod"):
                return "needs_production"
            geo = sku_geometry.parse(itm)
            if geo and geo.cuttable:
                return "cuttable"
            return "needs_po"

        for wo in proposals:
            so = wo["so_number"]
            covered = {c["target_sku"] for c in wo["cuts"]}
            shortfall = so_short.get(so, {})
            blockers = []
            for itm, nn in sorted(shortfall.items()):
                if itm in covered:
                    continue
                snap = item_snap.get(itm, {})
                blockers.append({
                    "item_no": itm,
                    "net_need": nn,
                    "on_order": round(snap.get("on_order") or 0, 2),
                    "fulfillment": _fulfillment(itm),
                })
            wo["blockers"] = blockers
            wo["makes_invoiceable"] = len(blockers) == 0
            wo["so_short_item_count"] = len(shortfall)
            # Headline split for the card / report.
            wo["blocker_summary"] = {
                "needs_po": sum(1 for b in blockers if b["fulfillment"] == "needs_po"),
                "needs_production": sum(1 for b in blockers if b["fulfillment"] == "needs_production"),
                "cuttable": sum(1 for b in blockers if b["fulfillment"] == "cuttable"),
                "unknown": sum(1 for b in blockers if b["fulfillment"] == "unknown"),
                "on_order": sum(1 for b in blockers if b["on_order"] > 0),
            }

    def _annotate_velocity(self, proposals: List[dict]) -> None:
        """Tag each donor with how fast it moves and float slow-stock-clearing
        work orders up the queue — the 12-month goal is to hold only
        ~3-month-consumable stock, so cutting dead long-stock is the win."""
        from app.services.item_velocity_service import item_velocity_service

        on_hand = {}
        for wo in proposals:
            for c in wo["cuts"]:
                on_hand[c["donor_sku"]] = c.get("donor_on_hand") or 0
        if not on_hand:
            return
        vel = item_velocity_service.donor_velocity(on_hand)

        for wo in proposals:
            clears_slow = False
            for c in wo["cuts"]:
                v = vel.get(c["donor_sku"])
                c["donor_velocity"] = v
                if v and v.get("is_slow"):
                    clears_slow = True
            wo["clears_slow_stock"] = clears_slow

        # Truly shippable orders first (the cut clears the LAST blocker), then
        # slow-stock-clearing, then dollars avoided. A cut that doesn't complete
        # its order isn't "invoiceable now", so it sinks below the ones that are.
        proposals.sort(key=lambda w: (
            not w.get("makes_invoiceable"),
            not w.get("clears_slow_stock"),
            -w["purchase_avoided"],
        ))

    def _build_journal(
        self, so_number: str, recs: List[CutRecommendation], catalog_skus
    ) -> dict:
        """The item-journal spec: negative adjustment per donor stick, positive
        adjustments for the job pieces produced and the offcuts received.

        Mirrors the manual process exactly — down the donor, up the pieces —
        and every line shares one CUT document number so the whole cut is a
        single, attributable ledger event.

        NESTS across the SO's cuts within a family: when the job needs an 18'
        and a 14' of the same panel, both come off ONE 32'4" (not two), and the
        leftover is kept whole so it receives as the longest catalog size. This
        is computed here, at journal time, so the inventory move reflects the
        real minimum stick consumption; the per-target cut cards are unchanged.
        """
        from app.services.cutting_stock_service import (
            plan_family_cuts, KERF_BY_KIND, FIT_TOLERANCE_BY_KIND, DEFAULT_KERF_INCHES,
            DEFAULT_FIT_TOLERANCE_INCHES,
        )
        document_no = f"{CUT_DOC_PREFIX}-{so_number.replace('SO-', '') or so_number}"

        # Group the SO's cuts by family so nesting only mixes compatible pieces.
        by_family: Dict[str, List[CutRecommendation]] = {}
        for r in recs:
            geo = sku_geometry.parse(r.donor_sku)
            by_family.setdefault(geo.family if geo else r.donor_sku, []).append(r)

        lines: List[dict] = []
        for family, frecs in by_family.items():
            kind = None
            g = sku_geometry.parse(frecs[0].donor_sku)
            kind = g.kind if g else "panel"

            # Needed pieces + the donor sticks the solver earmarked for them.
            pieces = []
            donor_sticks = []
            for r in frecs:
                t_geo = sku_geometry.parse(r.target_sku)
                t_len = t_geo.length_inches if t_geo else r.target_length_inches
                pieces += [(t_len, r.target_sku)] * r.pieces_yielded
                d_geo = sku_geometry.parse(r.donor_sku)
                d_len = d_geo.length_inches if d_geo else r.donor_length_inches
                donor_sticks += [(d_len, r.donor_sku)] * r.donor_sticks_used

            plans, unmet = plan_family_cuts(
                pieces, donor_sticks,
                kerf=KERF_BY_KIND.get(kind, DEFAULT_KERF_INCHES),
                fit_tolerance=FIT_TOLERANCE_BY_KIND.get(kind, DEFAULT_FIT_TOLERANCE_INCHES),
            )

            donor_consumed: Dict[str, int] = {}
            pieces_made: Dict[str, int] = {}
            offcuts: Dict[str, int] = {}
            for p in plans:
                donor_consumed[p["donor_sku"]] = donor_consumed.get(p["donor_sku"], 0) + 1
                for _plen, tsku in p["pieces"]:
                    pieces_made[tsku] = pieces_made.get(tsku, 0) + 1
                offcut_sku = sku_geometry.resolve_length_to_sku(family, p["leftover"], catalog_skus)
                if offcut_sku and offcut_sku not in donor_consumed:
                    offcuts[offcut_sku] = offcuts.get(offcut_sku, 0) + 1

            for d_sku, n in donor_consumed.items():
                lines.append({"item_no": d_sku, "entry_type": "Negative Adjmt.",
                              "quantity": n, "reason": f"cut for {so_number}"})
            for t_sku, n in pieces_made.items():
                lines.append({"item_no": t_sku, "entry_type": "Positive Adjmt.",
                              "quantity": n, "reason": f"cut for {so_number}"})
            for o_sku, n in offcuts.items():
                if o_sku not in pieces_made:  # a produced piece is not also an offcut
                    lines.append({"item_no": o_sku, "entry_type": "Positive Adjmt.",
                                  "quantity": n, "reason": f"offcut for {so_number}"})

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
        self.invalidate_proposals_cache()   # the decided SO must drop out at once
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
        self.invalidate_proposals_cache()
        return wo


cut_work_order_service = CutWorkOrderService()
