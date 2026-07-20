"""Tests for per-SO cut work orders: build, journal spec, approve/reject."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.models import CutWorkOrder, CutFeedback
from app.services.cutting_stock_service import CuttingStockService
from app.services.cut_work_order_service import cut_work_order_service as wos


# The BusyBee cut family, enough sizes to resolve the offcut.
CATALOG = [
    "PN40-21400-3204",  # 32'4" donor
    "PN40-21400-1800",  # 18'   target
    "PN40-21400-1404",  # 14'4" offcut  (388 - 216 = 172")
    "PN40-21400-1000",
]


def _db():
    engine = create_engine("sqlite:///:memory:")
    CutWorkOrder.__table__.create(engine)
    CutFeedback.__table__.create(engine)
    return sessionmaker(bind=engine)()


def _busybee_recs():
    """Run the real solver on the BusyBee situation: 6x 18' short, 32'4" stock."""
    rows = [
        {"item_no": "PN40-21400-1800", "demand": 6, "on_hand": 0, "on_order": 0,
         "net_need": 6, "unit_cost": 206.73, "unit_of_measure": "EA",
         "jobs": ["SO-001238"]},
        {"item_no": "PN40-21400-3204", "demand": 0, "on_hand": 8, "on_order": 0,
         "net_need": 0, "unit_cost": 393.60, "unit_of_measure": "EA", "jobs": []},
    ]
    return CuttingStockService().analyze(rows)


class TestBuildAndJournal:
    def test_work_order_groups_by_so(self):
        wo = wos.build_proposed(_busybee_recs(), CATALOG)
        assert len(wo) == 1
        assert wo[0]["so_number"] == "SO-001238"
        assert wo[0]["makes_invoiceable"] is True
        assert wo[0]["purchase_avoided"] > 0

    def test_journal_has_negative_donor_and_positive_pieces(self):
        wo = wos.build_proposed(_busybee_recs(), CATALOG)[0]
        j = wo["journal"]
        assert j["document_no"] == "CUT-001238"
        by = {(l["item_no"], l["entry_type"]): l for l in j["lines"]}

        # Down the donor.
        assert ("PN40-21400-3204", "Negative Adjmt.") in by
        # Up the job pieces.
        assert ("PN40-21400-1800", "Positive Adjmt.") in by
        assert by[("PN40-21400-1800", "Positive Adjmt.")]["quantity"] >= 6
        # Up the received offcut (14'4").
        assert ("PN40-21400-1404", "Positive Adjmt.") in by

    def test_journal_is_balanced_in_direction(self):
        """Every donor line is negative-intent, every piece line positive."""
        wo = wos.build_proposed(_busybee_recs(), CATALOG)[0]
        neg = [l for l in wo["journal"]["lines"] if l["entry_type"] == "Negative Adjmt."]
        pos = [l for l in wo["journal"]["lines"] if l["entry_type"] == "Positive Adjmt."]
        assert neg and pos
        assert all(l["quantity"] > 0 for l in neg + pos)  # quantities are magnitudes

    def test_offcut_not_resolvable_without_catalog_size(self):
        """With no offcut SKU in the catalog, no phantom positive line appears."""
        wo = wos.build_proposed(_busybee_recs(),
                                ["PN40-21400-3204", "PN40-21400-1800"])[0]
        skus = {l["item_no"] for l in wo["journal"]["lines"]}
        assert "PN40-21400-1404" not in skus


class TestDecisions:
    def test_approve_persists_and_records_feedback(self):
        db = _db()
        wo_dict = wos.build_proposed(_busybee_recs(), CATALOG)[0]
        wo = wos.approve(db, wo_dict, created_by=1)
        assert wo.id is not None
        assert wo.status == "approved"
        assert wo.journal_json["document_no"] == "CUT-001238"

        # A verdict was recorded for each cut.
        fb = db.query(CutFeedback).all()
        assert len(fb) == len(wo_dict["cuts"])
        assert all(f.verdict == "approved" for f in fb)
        assert fb[0].so_number == "SO-001238"

    def test_reject_records_reason(self):
        db = _db()
        wo_dict = wos.build_proposed(_busybee_recs(), CATALOG)[0]
        wo = wos.reject(db, wo_dict, reason="saving that stock for a bigger job", created_by=1)
        assert wo.status == "rejected"
        fb = db.query(CutFeedback).all()
        assert all(f.verdict == "rejected" for f in fb)
        assert fb[0].reason == "saving that stock for a bigger job"

    def test_mark_posted(self):
        db = _db()
        wo = wos.approve(db, wos.build_proposed(_busybee_recs(), CATALOG)[0], created_by=1)
        posted = wos.mark_posted(db, wo.id, document_no="CUT-001238")
        assert posted.status == "posted"
        assert posted.posted_document_no == "CUT-001238"
        assert posted.posted_at is not None
