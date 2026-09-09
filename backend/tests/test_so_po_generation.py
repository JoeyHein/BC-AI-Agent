"""so_po_generation_service: netting rules for a single-SO Upwardor PO.

Covers the defect found in PO-000962 (SO-001299, 2026-09-08): a hand-built
PO mirrored every SO item line 1:1 with no inventory check, so 96% of it
either shouldn't have been purchased at all (manufactured in-house) or was
already covered by stock/other open POs.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from app.services import so_po_generation_service as svc


class FakeBC:
    def __init__(self, so, cost_by_item=None):
        self._so = so
        self.cost_by_item = cost_by_item or {}
        self.created = []
        self.lines = []

    def get_sales_order_by_number(self, number):
        return self._so if number == self._so["number"] else None

    def get_order_lines(self, so_id):
        return self._so["salesOrderLines"]

    def get_items_by_numbers(self, numbers):
        return {n: self.cost_by_item.get(n, {"unitCost": 0, "baseUnitOfMeasureCode": "EA"})
                for n in numbers}

    def create_purchase_order(self, body):
        po = {"id": "po-guid-1", "number": "PO-TEST-001", **body}
        self.created.append(po)
        return po

    def add_purchase_order_line(self, po_id, body):
        self.lines.append((po_id, body))
        return {"id": f"line-{len(self.lines)}"}


class FakeProd:
    def __init__(self, item_cards):
        self._cards = item_cards

    def _make_odata_request_all(self, endpoint, query_params=None):
        assert endpoint == "Items"
        return self._cards


def _line(item, qty, seq=10000, ltype="Item"):
    return {"lineType": ltype, "sequence": seq, "lineObjectNumber": item,
            "quantity": qty, "description": f"desc {item}"}


def _card(no, on_hand=0, on_po=0, on_so=0, on_comp=0, replen="Purchase"):
    return {"No": no, "InventoryField": on_hand, "Qty_on_Purch_Order": on_po,
            "Qty_on_Sales_Order": on_so, "Qty_on_Component_Lines": on_comp,
            "Replenishment_System": replen}


def _setup(monkeypatch, so, cards, cost_by_item=None):
    bc = FakeBC(so, cost_by_item)
    prod = FakeProd(cards)
    monkeypatch.setattr(svc, "bc_client", bc)
    monkeypatch.setattr(svc, "bc_production_service", prod)
    return bc, prod


class TestNetting:
    def test_manufactured_item_excluded_entirely(self, monkeypatch):
        so = {"id": "so-1", "number": "SO-TEST", "customerName": "Acme",
              "salesOrderLines": [_line("PN46-24405-1800", 3)]}
        cards = [_card("PN46-24405-1800", on_hand=0, replen="Prod. Order")]
        _setup(monkeypatch, so, cards)

        plan = svc.compute_netted_po_lines("SO-TEST")
        assert plan["included"] == []
        assert len(plan["excluded_manufactured"]) == 1
        assert plan["excluded_manufactured"][0]["item_no"] == "PN46-24405-1800"

    def test_fully_in_stock_item_excluded(self, monkeypatch):
        so = {"id": "so-1", "number": "SO-TEST", "customerName": "Acme",
              "salesOrderLines": [_line("SH12-11810-00", 1)]}
        cards = [_card("SH12-11810-00", on_hand=47, on_so=1)]
        _setup(monkeypatch, so, cards)

        plan = svc.compute_netted_po_lines("SO-TEST")
        assert plan["included"] == []
        assert len(plan["excluded_in_stock"]) == 1
        assert plan["excluded_in_stock"][0]["avail"] >= 1

    def test_partial_stock_trims_to_net_need(self, monkeypatch):
        # ordered 10, 4 on hand, nothing else claiming it -> net 6
        so = {"id": "so-1", "number": "SO-TEST", "customerName": "Acme",
              "salesOrderLines": [_line("WIDGET-01", 10)]}
        cards = [_card("WIDGET-01", on_hand=4, on_so=10)]
        _setup(monkeypatch, so, cards, {"WIDGET-01": {"unitCost": 2.5, "baseUnitOfMeasureCode": "EA"}})

        plan = svc.compute_netted_po_lines("SO-TEST")
        assert len(plan["included"]) == 1
        row = plan["included"][0]
        assert row["quantity"] == 6
        assert row["unit_cost"] == 2.5
        assert len(plan["trimmed"]) == 1

    def test_other_open_so_demand_reserves_stock_first(self, monkeypatch):
        # 5 on hand total, but another open SO already needs all 5 -> nothing free for us
        so = {"id": "so-1", "number": "SO-TEST", "customerName": "Acme",
              "salesOrderLines": [_line("SHARED-01", 3)]}
        cards = [_card("SHARED-01", on_hand=5, on_so=8)]  # 8 total demand incl. our 3
        _setup(monkeypatch, so, cards, {"SHARED-01": {"unitCost": 1.0, "baseUnitOfMeasureCode": "EA"}})

        plan = svc.compute_netted_po_lines("SO-TEST")
        assert len(plan["included"]) == 1
        assert plan["included"][0]["quantity"] == 3  # avail = 5 - (8-3) = 0, net = 3

    def test_freight_and_installation_lines_never_priced(self, monkeypatch):
        so = {"id": "so-1", "number": "SO-TEST", "customerName": "Acme",
              "salesOrderLines": [_line("FREIGHT", 1), _line("INSTALLATION", 1)]}
        _setup(monkeypatch, so, [])

        plan = svc.compute_netted_po_lines("SO-TEST")
        assert plan["included"] == []
        assert plan["excluded_manufactured"] == []
        assert plan["excluded_in_stock"] == []

    def test_genuine_shortfall_included_at_full_qty(self, monkeypatch):
        so = {"id": "so-1", "number": "SO-TEST", "customerName": "Acme",
              "salesOrderLines": [_line("SHORT-01", 5)]}
        cards = [_card("SHORT-01", on_hand=0, on_po=0, on_so=5)]
        _setup(monkeypatch, so, cards, {"SHORT-01": {"unitCost": 10.0, "baseUnitOfMeasureCode": "EA"}})

        plan = svc.compute_netted_po_lines("SO-TEST")
        assert len(plan["included"]) == 1
        assert plan["included"][0]["quantity"] == 5
        assert plan["trimmed"] == []

    def test_unknown_so_raises(self, monkeypatch):
        _setup(monkeypatch, {"id": "x", "number": "SO-OTHER", "customerName": "x",
                              "salesOrderLines": []}, [])
        with pytest.raises(ValueError):
            svc.compute_netted_po_lines("SO-MISSING")


class TestBuildPo:
    def test_dry_run_creates_nothing(self, monkeypatch):
        so = {"id": "so-1", "number": "SO-TEST", "customerName": "Acme",
              "salesOrderLines": [_line("SHORT-01", 5)]}
        cards = [_card("SHORT-01", on_hand=0, on_so=5)]
        bc, _ = _setup(monkeypatch, so, cards, {"SHORT-01": {"unitCost": 10.0, "baseUnitOfMeasureCode": "EA"}})

        result = svc.build_upwardor_po("SO-TEST", dry_run=True)
        assert result["bc_po_number"] is None
        assert bc.created == []

    def test_nothing_to_order_short_circuits_before_bc_call(self, monkeypatch):
        so = {"id": "so-1", "number": "SO-TEST", "customerName": "Acme",
              "salesOrderLines": [_line("SH12-11810-00", 1)]}
        cards = [_card("SH12-11810-00", on_hand=47, on_so=1)]
        bc, _ = _setup(monkeypatch, so, cards)

        result = svc.build_upwardor_po("SO-TEST", dry_run=False)
        assert result["bc_po_number"] is None
        assert "Nothing to order" in result["note"]
        assert bc.created == []

    def test_commit_creates_po_with_comment_then_provenance_then_items(self, monkeypatch):
        so = {"id": "so-1", "number": "SO-TEST", "customerName": "Acme",
              "salesOrderLines": [_line("SHORT-01", 5)]}
        cards = [_card("SHORT-01", on_hand=0, on_so=5)]
        bc, _ = _setup(monkeypatch, so, cards, {"SHORT-01": {"unitCost": 10.0, "baseUnitOfMeasureCode": "EA"}})

        result = svc.build_upwardor_po("SO-TEST", dry_run=False)
        assert result["bc_po_number"] == "PO-TEST-001"
        assert bc.created[0]["vendorNumber"] == "UPW"
        kinds = [(b["lineType"], b.get("lineObjectNumber")) for _, b in bc.lines]
        assert kinds[0] == ("Comment", None)
        assert kinds[1] == ("Comment", None)
        assert kinds[2] == ("Item", "SHORT-01")
        assert bc.lines[2][1]["quantity"] == 5
