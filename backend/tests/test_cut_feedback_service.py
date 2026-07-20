"""Tests for the cutting-stock feedback layer (verdicts + item lead times)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.models import CutFeedback, ItemLeadTime
from app.services.cut_feedback_service import cut_feedback_service as svc


def _db():
    engine = create_engine("sqlite:///:memory:")
    # SQLite does not enforce the FK to users.id without PRAGMA, so the two
    # feedback tables stand alone for the test.
    CutFeedback.__table__.create(engine)
    ItemLeadTime.__table__.create(engine)
    return sessionmaker(bind=engine)()


class TestVerdicts:
    def test_record_and_read_back(self):
        db = _db()
        row = svc.record_verdict(
            db, target_sku="PN40-21400-1800", donor_sku="PN40-21400-3204",
            verdict="approved", reason="good cut, 14ft4 offcut sells",
            so_number="SO-001238", qty_pieces=6, scrap_inches=0.0,
        )
        assert row.id is not None
        assert row.cut_family == "PN40-21400"        # derived, not passed
        got = svc.latest_verdict_for_pair(db, "PN40-21400-1800", "PN40-21400-3204")
        assert got.verdict == "approved"
        assert got.so_number == "SO-001238"

    def test_history_is_append_only(self):
        db = _db()
        pair = dict(target_sku="SH11-10906-00", donor_sku="SH11-11306-00")
        svc.record_verdict(db, verdict="rejected", reason="too much scrap", **pair)
        svc.record_verdict(db, verdict="approved", reason="needed for completion", **pair)
        rows = svc.verdicts_for_pair(db, **pair)
        assert len(rows) == 2                        # both kept, not overwritten
        assert rows[0].verdict == "approved"         # newest first
        assert svc.latest_verdict_for_pair(db, **pair).reason == "needed for completion"

    def test_invalid_verdict_rejected(self):
        db = _db()
        with pytest.raises(ValueError):
            svc.record_verdict(db, target_sku="X", donor_sku="Y", verdict="maybe")

    def test_annotate_attaches_prior_verdict(self):
        db = _db()
        svc.record_verdict(db, target_sku="PN40-21400-1800",
                           donor_sku="PN40-21400-3204", verdict="approved")

        class Rec:
            def to_dict(self):
                return {"target_sku": "PN40-21400-1800",
                        "donor_sku": "PN40-21400-3204", "qty_needed": 6}

        out = svc.annotate_recommendations(db, [Rec()])
        assert out[0]["prior_verdict"]["verdict"] == "approved"

    def test_annotate_none_when_no_history(self):
        db = _db()

        class Rec:
            def to_dict(self):
                return {"target_sku": "NEW-SKU-0001", "donor_sku": "NEW-SKU-9999"}

        out = svc.annotate_recommendations(db, [Rec()])
        assert out[0]["prior_verdict"] is None

    def test_pair_summary_counts(self):
        db = _db()
        pair = dict(target_sku="SH11-10906-00", donor_sku="SH11-11306-00")
        svc.record_verdict(db, verdict="rejected", **pair)
        svc.record_verdict(db, verdict="rejected", **pair)
        svc.record_verdict(db, verdict="approved", **pair)
        summ = svc.pair_summary(db)
        assert len(summ) == 1
        s = summ[0]
        assert s["rejected"] == 2 and s["approved"] == 1 and s["total"] == 3


class TestLeadTimes:
    def test_upsert_latest_wins(self):
        db = _db()
        svc.set_lead_time(db, item_no="PN40-21400-3204", lead_time_days=21)
        svc.set_lead_time(db, item_no="PN40-21400-3204", lead_time_days=28,
                          note="vendor slipped")
        rows = db.query(ItemLeadTime).filter(
            ItemLeadTime.item_no == "PN40-21400-3204").all()
        assert len(rows) == 1                        # upserted, not duplicated
        assert rows[0].lead_time_days == 28
        assert rows[0].note == "vendor slipped"

    def test_vendor_specific_overrides_general(self):
        db = _db()
        svc.set_lead_time(db, item_no="X", lead_time_days=30)                  # general
        svc.set_lead_time(db, item_no="X", lead_time_days=10, vendor_no="UPW") # specific
        lt = svc.lead_times_by_item(db)
        assert lt["X"] == 10

    def test_negative_lead_time_rejected(self):
        db = _db()
        with pytest.raises(ValueError):
            svc.set_lead_time(db, item_no="X", lead_time_days=-5)
