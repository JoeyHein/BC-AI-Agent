"""Tests for whole-order shippability: a cut only 'ships the order' if it clears
the LAST blocker. Cutting a shaft is pointless if panels are still missing."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from app.services.cut_work_order_service import cut_work_order_service as wos


def _wo(so, target_skus):
    return {"so_number": so, "cuts": [{"target_sku": t} for t in target_skus],
            "purchase_avoided": 100.0, "makes_invoiceable": True}


def _req(items):
    # items: [(item_no, net_need, [jobs])]
    return {"items": [{"item_no": i, "net_need": nn, "jobs": jobs} for i, nn, jobs in items]}


class TestCompleteness:
    def test_cut_clears_last_blocker_ships_order(self):
        # SO-500 is short ONLY the shaft, and the cut makes the shaft.
        proposals = [_wo("SO-500", ["SH11-10906-00"])]
        req = _req([("SH11-10906-00", 2, ["SO-500"])])
        wos._assess_completeness(proposals, req)
        assert proposals[0]["makes_invoiceable"] is True
        assert proposals[0]["blockers"] == []

    def test_cut_with_other_missing_item_does_not_ship(self):
        # SO-1225 needs a shaft (cut) AND panels (not cut, still short) -> blocked.
        proposals = [_wo("SO-1225", ["SH11-10906-00"])]
        req = _req([
            ("SH11-10906-00", 2, ["SO-1225"]),   # covered by the cut
            ("PN65-24000-1600", 6, ["SO-1225"]),  # NOT covered -> blocker
        ])
        wos._assess_completeness(proposals, req)
        assert proposals[0]["makes_invoiceable"] is False
        b = proposals[0]["blockers"]
        assert len(b) == 1 and b[0]["item_no"] == "PN65-24000-1600" and b[0]["net_need"] == 6
        assert proposals[0]["so_short_item_count"] == 2

    def test_blocker_fulfillment_split_po_vs_production(self):
        proposals = [_wo("SO-9", [])]
        req = {"items": [
            {"item_no": "FH12-00016-00", "net_need": 5, "on_order": 0, "jobs": ["SO-9"]},   # purchased
            {"item_no": "PN45-21400-1000", "net_need": 2, "on_order": 0, "jobs": ["SO-9"]}, # manufactured
            {"item_no": "GK16-23200-00", "net_need": 3, "on_order": 3, "jobs": ["SO-9"]},   # purchased, on order
        ]}
        replen = {"FH12-00016-00": "Purchase", "PN45-21400-1000": "Prod. Order",
                  "GK16-23200-00": "Purchase"}
        wos._assess_completeness(proposals, req, replen_map=replen)
        by = {b["item_no"]: b for b in proposals[0]["blockers"]}
        assert by["FH12-00016-00"]["fulfillment"] == "needs_po"
        assert by["PN45-21400-1000"]["fulfillment"] == "needs_production"
        assert by["GK16-23200-00"]["on_order"] == 3
        s = proposals[0]["blocker_summary"]
        assert s["needs_po"] == 2 and s["needs_production"] == 1 and s["on_order"] == 1

    def test_cuttable_shortfall_not_labelled_po_or_production(self):
        proposals = [_wo("SO-7", [])]  # no cuts in the WO, but the item IS cuttable
        req = {"items": [{"item_no": "SH11-10906-00", "net_need": 2, "on_order": 0, "jobs": ["SO-7"]}]}
        wos._assess_completeness(proposals, req, replen_map={"SH11-10906-00": "Purchase"})
        assert proposals[0]["blockers"][0]["fulfillment"] == "cuttable"

    def test_multiple_cuts_covering_all_shortfalls_ships(self):
        # SO-1222 needs panels AND shafts, and BOTH are cut in this one WO.
        proposals = [_wo("SO-1222", ["PN40-21400-1800", "SH11-10906-00"])]
        req = _req([
            ("PN40-21400-1800", 6, ["SO-1222"]),
            ("SH11-10906-00", 1, ["SO-1222"]),
        ])
        wos._assess_completeness(proposals, req)
        assert proposals[0]["makes_invoiceable"] is True
        assert proposals[0]["blockers"] == []

    def test_blockers_from_another_so_do_not_affect_this_one(self):
        proposals = [_wo("SO-1", ["SH11-10906-00"])]
        req = _req([
            ("SH11-10906-00", 1, ["SO-1"]),
            ("PN65-24000-1600", 6, ["SO-2"]),   # blocks SO-2, not SO-1
        ])
        wos._assess_completeness(proposals, req)
        assert proposals[0]["makes_invoiceable"] is True
