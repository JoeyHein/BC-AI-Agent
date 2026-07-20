"""Cut-feedback service — record and read human verdicts on cut recommendations.

This is the learning loop's storage layer. The engine proposes cuts; a human
approves, rejects, or modifies each; those verdicts accumulate here. Over
repetition, the aggregate across a cut pair (donor -> target) is what will let
the engine stop re-proposing something Joey keeps rejecting — but ONLY once a
proposed rule is explicitly approved. Nothing in this service turns a verdict
into a hard constraint on its own.

Also holds purchaser-entered per-item lead times, which feed timeline
projections and route around BC's unpublished receipt-header web service.
"""

import logging
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from app.db.models import CutFeedback, ItemLeadTime
from app.services import sku_geometry

logger = logging.getLogger(__name__)

VALID_VERDICTS = {"approved", "rejected", "modified"}


class CutFeedbackService:
    # ---- verdicts -----------------------------------------------------------

    def record_verdict(
        self,
        db: Session,
        target_sku: str,
        donor_sku: str,
        verdict: str,
        reason: Optional[str] = None,
        so_number: Optional[str] = None,
        qty_pieces: Optional[int] = None,
        scrap_inches: Optional[float] = None,
        opportunity: Optional[dict] = None,
        source: str = "portal",
        created_by: Optional[int] = None,
    ) -> CutFeedback:
        """Append one verdict. Never updates in place — the history IS the
        signal, so a changed mind is a new row, not an overwrite."""
        verdict = (verdict or "").strip().lower()
        if verdict not in VALID_VERDICTS:
            raise ValueError(f"verdict must be one of {sorted(VALID_VERDICTS)}, got {verdict!r}")

        # Derive the cut family from whichever SKU parses, so grouping works
        # even if a caller passes only one recognisable SKU.
        family = sku_geometry.cut_family(donor_sku) or sku_geometry.cut_family(target_sku)

        row = CutFeedback(
            target_sku=target_sku,
            donor_sku=donor_sku,
            cut_family=family,
            so_number=so_number,
            qty_pieces=qty_pieces,
            scrap_inches=scrap_inches,
            verdict=verdict,
            reason=reason,
            opportunity_json=opportunity,
            source=source,
            created_by=created_by,
        )
        db.add(row)
        db.flush()
        logger.info(
            "Cut verdict recorded: %s->%s %s (so=%s, src=%s)",
            donor_sku, target_sku, verdict, so_number, source,
        )
        return row

    def verdicts_for_pair(
        self, db: Session, target_sku: str, donor_sku: str
    ) -> List[CutFeedback]:
        """All verdicts for a donor->target pair, newest first."""
        return (
            db.query(CutFeedback)
            .filter(CutFeedback.target_sku == target_sku,
                    CutFeedback.donor_sku == donor_sku)
            .order_by(CutFeedback.created_at.desc())
            .all()
        )

    def latest_verdict_for_pair(
        self, db: Session, target_sku: str, donor_sku: str
    ) -> Optional[CutFeedback]:
        """The current call on a cut pair (most recent verdict), or None."""
        rows = self.verdicts_for_pair(db, target_sku, donor_sku)
        return rows[0] if rows else None

    def annotate_recommendations(self, db: Session, recs: List) -> List[dict]:
        """Attach each recommendation's latest verdict so the report/portal can
        show "you approved this before" without a per-row DB round trip.

        Accepts CutRecommendation objects (or their dicts) and returns dicts
        with a ``prior_verdict`` field. Pure read — records nothing.
        """
        if not recs:
            return []

        # One query for every pair in the batch.
        pairs = set()
        norm = []
        for r in recs:
            d = r.to_dict() if hasattr(r, "to_dict") else dict(r)
            norm.append(d)
            pairs.add((d.get("target_sku"), d.get("donor_sku")))

        latest: Dict[tuple, CutFeedback] = {}
        rows = (
            db.query(CutFeedback)
            .filter(CutFeedback.target_sku.in_([p[0] for p in pairs]))
            .order_by(CutFeedback.created_at.desc())
            .all()
        )
        for row in rows:
            key = (row.target_sku, row.donor_sku)
            if key in pairs and key not in latest:
                latest[key] = row   # first seen = newest, given the ordering

        for d in norm:
            v = latest.get((d.get("target_sku"), d.get("donor_sku")))
            d["prior_verdict"] = v.to_dict() if v else None
        return norm

    def pair_summary(self, db: Session) -> List[dict]:
        """Aggregate verdicts per cut pair — the raw material for rule
        proposals. Reports counts only; proposing/approving rules is a separate,
        human-gated step (deliberately not done here)."""
        rows = db.query(CutFeedback).all()
        agg: Dict[tuple, dict] = {}
        for r in rows:
            key = (r.donor_sku, r.target_sku)
            a = agg.setdefault(key, {
                "donor_sku": r.donor_sku, "target_sku": r.target_sku,
                "cut_family": r.cut_family,
                "approved": 0, "rejected": 0, "modified": 0, "total": 0,
                "last_reason": None,
            })
            a[r.verdict] = a.get(r.verdict, 0) + 1
            a["total"] += 1
            if a["last_reason"] is None and r.reason:
                a["last_reason"] = r.reason
        return sorted(agg.values(), key=lambda x: x["total"], reverse=True)

    # ---- lead times ---------------------------------------------------------

    def set_lead_time(
        self,
        db: Session,
        item_no: str,
        lead_time_days: int,
        vendor_no: Optional[str] = None,
        note: Optional[str] = None,
        source: str = "portal",
        created_by: Optional[int] = None,
    ) -> ItemLeadTime:
        """Upsert the lead time for (item_no, vendor_no) — latest value wins."""
        if lead_time_days is None or lead_time_days < 0:
            raise ValueError(f"lead_time_days must be a non-negative int, got {lead_time_days!r}")

        row = (
            db.query(ItemLeadTime)
            .filter(ItemLeadTime.item_no == item_no,
                    ItemLeadTime.vendor_no == vendor_no)
            .first()
        )
        if row:
            row.lead_time_days = lead_time_days
            row.note = note
            row.source = source
            row.created_by = created_by
        else:
            row = ItemLeadTime(
                item_no=item_no, vendor_no=vendor_no,
                lead_time_days=lead_time_days, note=note,
                source=source, created_by=created_by,
            )
            db.add(row)
        db.flush()
        return row

    def lead_times_by_item(self, db: Session) -> Dict[str, int]:
        """{item_no: lead_time_days} for projections. When an item has both a
        vendor-specific and a general entry, the general one (vendor_no is null)
        is the fallback; a specific vendor entry wins."""
        out: Dict[str, int] = {}
        specific: Dict[str, int] = {}
        for r in db.query(ItemLeadTime).all():
            if r.vendor_no:
                specific[r.item_no] = r.lead_time_days
            else:
                out[r.item_no] = r.lead_time_days
        out.update(specific)   # vendor-specific overrides the general fallback
        return out


cut_feedback_service = CutFeedbackService()
