"""Tests for cut rules: propose from verdicts, ratify, suppress in the solver."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.models import CutRule, CutFeedback
from app.services.cut_rule_service import cut_rule_service as rules, MIN_REJECTIONS_TO_PROPOSE
from app.services.cut_feedback_service import cut_feedback_service as fb
from app.services.cutting_stock_service import CuttingStockService


def _db():
    engine = create_engine("sqlite:///:memory:")
    CutRule.__table__.create(engine)
    CutFeedback.__table__.create(engine)
    return sessionmaker(bind=engine)()


def _reject(db, donor, target, n):
    for _ in range(n):
        fb.record_verdict(db, target_sku=target, donor_sku=donor, verdict="rejected")


class TestProposals:
    def test_consistently_rejected_pair_is_proposed(self):
        db = _db()
        _reject(db, "SH11-11306-00", "SH11-10906-00", MIN_REJECTIONS_TO_PROPOSE)
        props = rules.propose(db)
        assert len(props) == 1
        assert props[0]["donor_sku"] == "SH11-11306-00"
        assert props[0]["rejected"] == MIN_REJECTIONS_TO_PROPOSE

    def test_a_single_rejection_is_not_enough(self):
        db = _db()
        _reject(db, "A-1", "A-2", 1)
        assert rules.propose(db) == []

    def test_pair_with_any_approval_is_not_proposed(self):
        db = _db()
        _reject(db, "A-1", "A-2", MIN_REJECTIONS_TO_PROPOSE)
        fb.record_verdict(db, target_sku="A-2", donor_sku="A-1", verdict="approved")
        assert rules.propose(db) == []

    def test_already_ruled_pair_not_reproposed(self):
        db = _db()
        _reject(db, "A-1", "A-2", MIN_REJECTIONS_TO_PROPOSE)
        rules.create_rule(db, scope="pair", donor_sku="A-1", target_sku="A-2")
        assert rules.propose(db) == []


class TestRuleLifecycle:
    def test_create_and_active_suppressions(self):
        db = _db()
        rules.create_rule(db, scope="pair", donor_sku="A-1", target_sku="A-2")
        rules.create_rule(db, scope="family", cut_family="PN65-24100")
        pairs, families = rules.active_suppressions(db)
        assert ("A-1", "A-2") in pairs
        assert "PN65-24100" in families

    def test_deactivate_removes_from_suppressions(self):
        db = _db()
        r = rules.create_rule(db, scope="pair", donor_sku="A-1", target_sku="A-2")
        rules.deactivate(db, r.id)
        pairs, _ = rules.active_suppressions(db)
        assert ("A-1", "A-2") not in pairs

    def test_pair_rule_needs_both_skus(self):
        db = _db()
        with pytest.raises(ValueError):
            rules.create_rule(db, scope="pair", donor_sku="A-1")

    def test_family_rule_needs_family(self):
        db = _db()
        with pytest.raises(ValueError):
            rules.create_rule(db, scope="family")


def _row(item_no, demand=0, on_hand=0, net_need=0, unit_cost=100.0, jobs=None):
    return {"item_no": item_no, "demand": demand, "on_hand": on_hand, "on_order": 0,
            "net_need": net_need, "unit_cost": unit_cost, "unit_of_measure": "EA",
            "jobs": jobs or []}


class TestSolverSuppression:
    def setup_method(self):
        self.svc = CuttingStockService()

    def test_suppressed_pair_is_skipped(self):
        rows = [
            _row("PN40-24400-1602", demand=4, net_need=4),
            _row("PN40-24400-3204", on_hand=9),
        ]
        # Without a rule, the cut is found.
        assert self.svc.analyze(rows)
        # With the pair suppressed, nothing.
        assert self.svc.analyze(
            rows, suppressed_pairs={("PN40-24400-3204", "PN40-24400-1602")}
        ) == []

    def test_suppressed_family_is_skipped(self):
        rows = [
            _row("PN40-24400-1602", demand=4, net_need=4),
            _row("PN40-24400-3204", on_hand=9),
        ]
        assert self.svc.analyze(rows, suppressed_families={"PN40-24400"}) == []
