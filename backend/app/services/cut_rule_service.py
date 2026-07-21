"""Cut rules — turn accumulated verdicts into ratified, human-approved policy.

The learning loop closes here. cut_feedback records every verdict; this service
spots pairs that are consistently rejected, PROPOSES a suppression rule, and —
once Joey approves it — stores it as an active CutRule the solver honours. The
approval gate is the whole point: a pattern of rejections is only a suggestion
until a human ratifies it, so nothing silently suppresses a product line.
"""

import logging
from typing import Dict, List, Optional, Set, Tuple

from sqlalchemy.orm import Session

from app.db.models import CutRule
from app.services.cut_feedback_service import cut_feedback_service

logger = logging.getLogger(__name__)

# A pair needs at least this many rejections, and no approvals, before we
# propose suppressing it — enough repetition to be a pattern, not a one-off.
MIN_REJECTIONS_TO_PROPOSE = 3


class CutRuleService:
    def propose(self, db: Session) -> List[dict]:
        """Candidate suppression rules from the verdict history. Proposals only
        — nothing here changes the solver until create_rule() ratifies one.

        Skips pairs already covered by an active rule so the same proposal does
        not resurface after it has been decided.
        """
        summary = cut_feedback_service.pair_summary(db)
        active_pairs, active_families = self.active_suppressions(db)

        proposals = []
        for s in summary:
            donor, target = s["donor_sku"], s["target_sku"]
            if (donor, target) in active_pairs or s.get("cut_family") in active_families:
                continue
            # Consistently rejected: enough rejections, never approved.
            if s.get("rejected", 0) >= MIN_REJECTIONS_TO_PROPOSE and s.get("approved", 0) == 0:
                proposals.append({
                    "scope": "pair",
                    "donor_sku": donor,
                    "target_sku": target,
                    "cut_family": s.get("cut_family"),
                    "rejected": s["rejected"],
                    "approved": s.get("approved", 0),
                    "last_reason": s.get("last_reason"),
                    "suggestion": (
                        f"Stop proposing {donor} -> {target}: rejected "
                        f"{s['rejected']}x, never approved."
                    ),
                })
        return proposals

    def create_rule(
        self, db: Session, scope: str, action: str = "suppress",
        donor_sku: Optional[str] = None, target_sku: Optional[str] = None,
        cut_family: Optional[str] = None, reason: Optional[str] = None,
        created_by: Optional[int] = None,
    ) -> CutRule:
        """Ratify a rule. Only after this does the solver honour it."""
        if scope not in ("pair", "family"):
            raise ValueError(f"scope must be pair|family, got {scope!r}")
        if scope == "pair" and not (donor_sku and target_sku):
            raise ValueError("pair rule needs donor_sku and target_sku")
        if scope == "family" and not cut_family:
            raise ValueError("family rule needs cut_family")
        rule = CutRule(
            scope=scope, action=action, donor_sku=donor_sku, target_sku=target_sku,
            cut_family=cut_family, reason=reason, active=True, created_by=created_by,
        )
        db.add(rule)
        db.flush()
        logger.info("Cut rule created: %r", rule)
        return rule

    def deactivate(self, db: Session, rule_id: int) -> Optional[CutRule]:
        rule = db.query(CutRule).filter(CutRule.id == rule_id).first()
        if rule:
            rule.active = False
            db.flush()
        return rule

    def list_rules(self, db: Session, active_only: bool = True) -> List[CutRule]:
        q = db.query(CutRule)
        if active_only:
            q = q.filter(CutRule.active.is_(True))
        return q.order_by(CutRule.created_at.desc()).all()

    def active_suppressions(self, db: Session) -> Tuple[Set[tuple], Set[str]]:
        """(suppressed (donor,target) pairs, suppressed families) — what the
        solver must skip. One cheap query, cached by the caller per run."""
        pairs: Set[tuple] = set()
        families: Set[str] = set()
        for r in db.query(CutRule).filter(
            CutRule.active.is_(True), CutRule.action == "suppress"
        ).all():
            if r.scope == "family" and r.cut_family:
                families.add(r.cut_family)
            elif r.donor_sku and r.target_sku:
                pairs.add((r.donor_sku, r.target_sku))
        return pairs, families


cut_rule_service = CutRuleService()
