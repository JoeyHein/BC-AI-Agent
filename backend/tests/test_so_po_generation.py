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
    def __init__(self, item_cards, bom_lines=None):
        self._cards = item_cards
        self._bom_lines = bom_lines or []

    def _make_odata_request_all(self, endpoint, query_params=None):
        if endpoint == "Items":
            return self._cards
        if endpoint == "ProductionBomLines":
            return self._bom_lines
        raise AssertionError(f"unexpected endpoint {endpoint!r}")


def _line(item, qty, seq=10000, ltype="Item"):
    return {"lineType": ltype, "sequence": seq, "lineObjectNumber": item,
            "quantity": qty, "description": f"desc {item}"}


def _card(no, on_hand=0, on_po=0, on_so=0, on_comp=0, replen="Purchase", bom=""):
    return {"No": no, "InventoryField": on_hand, "Qty_on_Purch_Order": on_po,
            "Qty_on_Sales_Order": on_so, "Qty_on_Component_Lines": on_comp,
            "Replenishment_System": replen, "Production_BOM_No": bom, "Description": f"desc {no}"}


def _bom_line(bom_no, component, qty_per, comp_type="Item"):
    return {"Production_BOM_No": bom_no, "No": component, "Type": comp_type,
            "Quantity_per": qty_per}


def _setup(monkeypatch, so, cards, cost_by_item=None, bom_lines=None):
    bc = FakeBC(so, cost_by_item)
    prod = FakeProd(cards, bom_lines)
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

    def test_manufactured_item_never_becomes_a_po_line_but_its_raw_material_does(self, monkeypatch):
        """PN46-24405-1800 (manufactured) explodes to a raw BULK panel we're
        short on — the panel itself must never be a line, but the raw
        material it's built from must show up as a real shortfall."""
        so = {"id": "so-1", "number": "SO-TEST", "customerName": "Acme",
              "salesOrderLines": [_line("PN46-24405-1800", 3)]}
        cards = [
            _card("PN46-24405-1800", replen="Prod. Order", bom="PN46-BOM"),
            _card("PN40-24405-1800", on_hand=2),  # need 3, have 2 -> short 1
        ]
        boms = [_bom_line("PN46-BOM", "PN40-24405-1800", 1.0)]
        _setup(monkeypatch, so, cards, {"PN40-24405-1800": {"unitCost": 257.51, "baseUnitOfMeasureCode": "EA"}},
               bom_lines=boms)

        plan = svc.compute_netted_po_lines("SO-TEST")
        assert plan["included"] == []  # the panel itself is never a PO line
        assert [r["item_no"] for r in plan["excluded_manufactured"]] == ["PN46-24405-1800"]
        assert len(plan["component_shortfall"]) == 1
        row = plan["component_shortfall"][0]
        assert row["item_no"] == "PN40-24405-1800"
        assert row["quantity"] == 1
        assert row["needed_for"] == ["PN46-24405-1800"]

    def test_manufactured_items_raw_material_already_covered_is_not_a_line(self, monkeypatch):
        so = {"id": "so-1", "number": "SO-TEST", "customerName": "Acme",
              "salesOrderLines": [_line("PN45-24405-1000", 3)]}
        cards = [
            _card("PN45-24405-1000", replen="Prod. Order", bom="PN45-BOM"),
            _card("PN40-24405-1000", on_hand=10),  # need 3, have plenty
        ]
        boms = [_bom_line("PN45-BOM", "PN40-24405-1000", 1.0)]
        _setup(monkeypatch, so, cards, bom_lines=boms)

        plan = svc.compute_netted_po_lines("SO-TEST")
        assert plan["component_shortfall"] == []
        assert len(plan["component_covered"]) == 1
        assert plan["component_covered"][0]["item_no"] == "PN40-24405-1000"

    def test_bom_explosion_recurses_through_sub_assemblies(self, monkeypatch):
        """A two-level BOM (hardware kit -> winder set -> raw plugs) must
        explode all the way to the purchasable leaf, not stop one level up."""
        so = {"id": "so-1", "number": "SO-TEST", "customerName": "Acme",
              "salesOrderLines": [_line("HK02-14120-RC", 1)]}
        cards = [
            _card("HK02-14120-RC", replen="Prod. Order", bom="HK02-BOM"),
            _card("SP12-00231-01", replen="Prod. Order", bom="SP12-BOM"),  # sub-assembly, also manufactured
            _card("RAW-PLUG-01", on_hand=0),
        ]
        boms = [
            _bom_line("HK02-BOM", "SP12-00231-01", 2.0),
            _bom_line("SP12-BOM", "RAW-PLUG-01", 4.0),
        ]
        _setup(monkeypatch, so, cards, {"RAW-PLUG-01": {"unitCost": 3.95, "baseUnitOfMeasureCode": "EA"}},
               bom_lines=boms)

        plan = svc.compute_netted_po_lines("SO-TEST")
        # need 1 kit -> 2 winder sets -> 8 raw plugs, none on hand
        assert len(plan["component_shortfall"]) == 1
        row = plan["component_shortfall"][0]
        assert row["item_no"] == "RAW-PLUG-01"
        assert row["quantity"] == 8

    def test_two_manufactured_items_sharing_a_component_aggregate(self, monkeypatch):
        so = {"id": "so-1", "number": "SO-TEST", "customerName": "Acme",
              "salesOrderLines": [_line("PANEL-A", 2), _line("PANEL-B", 1)]}
        cards = [
            _card("PANEL-A", replen="Prod. Order", bom="BOM-A"),
            _card("PANEL-B", replen="Prod. Order", bom="BOM-B"),
            _card("SHARED-CAP", on_hand=1),
        ]
        boms = [_bom_line("BOM-A", "SHARED-CAP", 1.0), _bom_line("BOM-B", "SHARED-CAP", 1.0)]
        _setup(monkeypatch, so, cards, {"SHARED-CAP": {"unitCost": 5.0, "baseUnitOfMeasureCode": "EA"}},
               bom_lines=boms)

        plan = svc.compute_netted_po_lines("SO-TEST")
        # total need = 2 + 1 = 3, 1 on hand -> short 2
        assert len(plan["component_shortfall"]) == 1
        row = plan["component_shortfall"][0]
        assert row["quantity"] == 2
        assert sorted(row["needed_for"]) == ["PANEL-A", "PANEL-B"]

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

    def test_gl12_shortfall_rounds_up_to_full_sheets(self, monkeypatch):
        """GL12 polycarbonate only comes in 4' x {12',16',20',24'} sheets
        (48/64/80/96 SF), one BC SKU per color — a raw 196 SF need must
        round up to a real stocked combination (208 SF / 3 sheets), not an
        arbitrary cut size Upwardor can't supply."""
        so = {"id": "so-1", "number": "SO-TEST", "customerName": "Acme",
              "salesOrderLines": [_line("GK17-25100-00", 196)]}
        cards = [
            _card("GK17-25100-00", replen="Prod. Order", bom="GK17-BOM"),
            _card("GL12-00000-01", on_hand=0),
        ]
        boms = [_bom_line("GK17-BOM", "GL12-00000-01", 1.0)]
        _setup(monkeypatch, so, cards, {"GL12-00000-01": {"unitCost": 3.0, "baseUnitOfMeasureCode": "SF"}},
               bom_lines=boms)

        plan = svc.compute_netted_po_lines("SO-TEST")
        assert len(plan["component_shortfall"]) == 1
        row = plan["component_shortfall"][0]
        assert row["item_no"] == "GL12-00000-01"
        assert row["quantity"] == 208  # 48 + 64 + 96, minimal waste over 196
        assert row["net_need_raw"] == 196

    def test_non_gl12_shortfall_is_never_sheet_rounded(self, monkeypatch):
        assert svc._round_to_full_sheets("PN40-24405-1800", 3) == 3

    @pytest.mark.parametrize("need,expected_sf", [
        (1, 48), (48, 48), (49, 64), (96, 96), (97, 48 + 64),  # 97 -> 2 sheets beats 3
        (192, 48 * 4),  # 4x48=192 exact, better than 3x64=192 tie (same total, fewer... actually equal sheets)
    ])
    def test_round_to_full_sheets_table(self, need, expected_sf):
        assert svc._round_to_full_sheets("GL12-00000-01", need) == expected_sf

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

    def test_commit_appends_component_shortfall_after_a_marker_comment(self, monkeypatch):
        """A sales order that's ENTIRELY manufactured items (no direct
        purchase lines at all) must still produce a PO — for the raw
        material shortfall, with a comment marking where it starts."""
        so = {"id": "so-1", "number": "SO-TEST", "customerName": "Acme",
              "salesOrderLines": [_line("PN46-24405-1800", 3)]}
        cards = [
            _card("PN46-24405-1800", replen="Prod. Order", bom="PN46-BOM"),
            _card("PN40-24405-1800", on_hand=0),
        ]
        boms = [_bom_line("PN46-BOM", "PN40-24405-1800", 1.0)]
        bc, _ = _setup(monkeypatch, so, cards, {"PN40-24405-1800": {"unitCost": 257.51, "baseUnitOfMeasureCode": "EA"}},
                        bom_lines=boms)

        result = svc.build_upwardor_po("SO-TEST", dry_run=False)
        assert result["bc_po_number"] == "PO-TEST-001"
        kinds = [(b["lineType"], b.get("lineObjectNumber"), b.get("description")) for _, b in bc.lines]
        # header comment, provenance comment, marker comment, then the raw material
        assert kinds[2][0] == "Comment" and "Raw materials" in kinds[2][2]
        # BC Comment lines 400 past 100 chars (Application_StringExceededLength) — hit live on 2026-09-09.
        assert len(kinds[2][2]) <= 100
        assert kinds[3] == ("Item", "PN40-24405-1800", "desc PN40-24405-1800")
        assert bc.lines[3][1]["quantity"] == 3
