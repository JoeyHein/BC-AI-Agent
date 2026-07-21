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
        assert proposals[0]["blockers"] == [{"item_no": "PN65-24000-1600", "net_need": 6}]
        assert proposals[0]["so_short_item_count"] == 2

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
