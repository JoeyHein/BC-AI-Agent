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
    def __init__(self, so, cost_by_item=None, existing_po=None):
        self._so = so
        self.cost_by_item = cost_by_item or {}
        self.created = []
        self.lines = []
        self.company_id = "cid-1"
        # {po_number: {"id", "status", "purchaseOrderLines": [...]}}, for
        # rewrite_po_lines tests only.
        self._existing_pos = existing_po or {}
        self.deleted_line_ids = []

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

    def _make_request(self, method, endpoint, **kwargs):
        if method == "GET" and "/purchaseOrders?" in endpoint:
            import re
            m = re.search(r"number eq '([^']+)'", endpoint)
            po = self._existing_pos.get(m.group(1)) if m else None
            return {"value": [po] if po else []}
        if method == "DELETE" and "/purchaseOrderLines(" in endpoint:
            line_id = endpoint.rsplit("(", 1)[1].rstrip(")")
            self.deleted_line_ids.append(line_id)
            return {}
        raise AssertionError(f"unexpected _make_request {method} {endpoint}")


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


def _door_header(label, seq):
    """A door-header Comment line in the exact shape the configurator
    writes — e.g. "(1) 18'0" x 8'0" TX450, , UDC, ..." — so
    _DOOR_HEADER_RE detects it as a new door group."""
    return {"lineType": "Comment", "sequence": seq, "lineObjectNumber": None,
            "quantity": 0, "description": label}


def _setup(monkeypatch, so, cards, cost_by_item=None, bom_lines=None, existing_po=None):
    bc = FakeBC(so, cost_by_item, existing_po)
    prod = FakeProd(cards, bom_lines)
    monkeypatch.setattr(svc, "bc_client", bc)
    monkeypatch.setattr(svc, "bc_production_service", prod)
    return bc, prod


class TestNetting:
    def test_manufactured_item_excluded_entirely(self, monkeypatch):
        so = {"id": "so-1", "number": "SO-TEST", "customerName": "Acme",
              "salesOrderLines": [_line("MFG-PANEL-01", 3)]}
        cards = [_card("MFG-PANEL-01", on_hand=0, replen="Prod. Order")]
        _setup(monkeypatch, so, cards)

        plan = svc.compute_netted_po_lines("SO-TEST")
        assert plan["included"] == []
        assert len(plan["excluded_manufactured"]) == 1
        assert plan["excluded_manufactured"][0]["item_no"] == "MFG-PANEL-01"

    def test_manufactured_item_never_becomes_a_po_line_but_its_raw_material_does(self, monkeypatch):
        """MFG-PANEL-01 (manufactured) explodes to a raw BULK panel we're
        short on — the panel itself must never be a line, but the raw
        material it's built from must show up as a real shortfall."""
        so = {"id": "so-1", "number": "SO-TEST", "customerName": "Acme",
              "salesOrderLines": [_line("MFG-PANEL-01", 3)]}
        cards = [
            _card("MFG-PANEL-01", replen="Prod. Order", bom="PN46-BOM"),
            _card("RAW-CORE-01", on_hand=2),  # need 3, have 2 -> short 1
        ]
        boms = [_bom_line("PN46-BOM", "RAW-CORE-01", 1.0)]
        _setup(monkeypatch, so, cards, {"RAW-CORE-01": {"unitCost": 257.51, "baseUnitOfMeasureCode": "EA"}},
               bom_lines=boms)

        plan = svc.compute_netted_po_lines("SO-TEST")
        assert plan["included"] == []  # the panel itself is never a PO line
        assert [r["item_no"] for r in plan["excluded_manufactured"]] == ["MFG-PANEL-01"]
        assert len(plan["component_shortfall"]) == 1
        row = plan["component_shortfall"][0]
        assert row["item_no"] == "RAW-CORE-01"
        assert row["quantity"] == 1
        assert row["needed_for"] == ["MFG-PANEL-01"]

    def test_manufactured_items_raw_material_already_covered_is_not_a_line(self, monkeypatch):
        so = {"id": "so-1", "number": "SO-TEST", "customerName": "Acme",
              "salesOrderLines": [_line("MFG-PANEL-02", 3)]}
        cards = [
            _card("MFG-PANEL-02", replen="Prod. Order", bom="PN45-BOM"),
            _card("RAW-CORE-02", on_hand=10),  # need 3, have plenty
        ]
        boms = [_bom_line("PN45-BOM", "RAW-CORE-02", 1.0)]
        _setup(monkeypatch, so, cards, bom_lines=boms)

        plan = svc.compute_netted_po_lines("SO-TEST")
        assert plan["component_shortfall"] == []
        assert len(plan["component_covered"]) == 1
        assert plan["component_covered"][0]["item_no"] == "RAW-CORE-02"

    def test_bom_explosion_recurses_through_sub_assemblies(self, monkeypatch):
        """A two-level BOM (kit -> sub-assembly -> raw plugs) must explode
        all the way to the purchasable leaf, not stop one level up — for
        sub-assemblies that aren't themselves bought complete."""
        so = {"id": "so-1", "number": "SO-TEST", "customerName": "Acme",
              "salesOrderLines": [_line("MFG-KIT-01", 1)]}
        cards = [
            _card("MFG-KIT-01", replen="Prod. Order", bom="KIT-BOM"),
            _card("MFG-SUBKIT-01", replen="Prod. Order", bom="SUB-BOM"),  # sub-assembly, also manufactured
            _card("RAW-PLUG-01", on_hand=0),
        ]
        boms = [
            _bom_line("KIT-BOM", "MFG-SUBKIT-01", 2.0),
            _bom_line("SUB-BOM", "RAW-PLUG-01", 4.0),
        ]
        _setup(monkeypatch, so, cards, {"RAW-PLUG-01": {"unitCost": 3.95, "baseUnitOfMeasureCode": "EA"}},
               bom_lines=boms)

        plan = svc.compute_netted_po_lines("SO-TEST")
        # need 1 kit -> 2 subkits -> 8 raw plugs, none on hand
        assert len(plan["component_shortfall"]) == 1
        row = plan["component_shortfall"][0]
        assert row["item_no"] == "RAW-PLUG-01"
        assert row["quantity"] == 8

    def test_buy_complete_sub_assembly_is_a_leaf_not_exploded_further(self, monkeypatch):
        """A winder set / track kit nested inside a still-exploded item's
        BOM (e.g. a glass kit) is bought whole, not broken into plugs —
        Joey, 2026-09-10 extended buy-complete to SP12/TR02/TR03."""
        so = {"id": "so-1", "number": "SO-TEST", "customerName": "Acme",
              "salesOrderLines": [_line("MFG-GLASSKIT-01", 1)]}
        cards = [
            _card("MFG-GLASSKIT-01", replen="Prod. Order", bom="GK-BOM"),
            _card("SP12-00231-01", replen="Prod. Order", bom="SP12-BOM", on_hand=0),
            _card("RAW-PLUG-01", on_hand=0),
        ]
        boms = [
            _bom_line("GK-BOM", "SP12-00231-01", 2.0),
            _bom_line("SP12-BOM", "RAW-PLUG-01", 4.0),
        ]
        _setup(monkeypatch, so, cards, {"SP12-00231-01": {"unitCost": 12.0, "baseUnitOfMeasureCode": "EA"}},
               bom_lines=boms)

        plan = svc.compute_netted_po_lines("SO-TEST")
        assert [r["item_no"] for r in plan["component_shortfall"]] == ["SP12-00231-01"]
        assert plan["component_shortfall"][0]["quantity"] == 2  # 2 sets, not 8 plugs

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


class TestBuyComplete:
    """Joey, 2026-09-10: HK0x hardware kits and TX450 (PN45/PN46) panels are
    'Prod. Order' in BC (we CAN build them) but Upwardor also sells them
    complete under the same part number — buy the finished item, don't
    explode it to 30 raw fasteners or a raw panel core + end caps."""

    def test_hk02_bought_complete_not_exploded(self, monkeypatch):
        so = {"id": "so-1", "number": "SO-TEST", "customerName": "Acme",
              "salesOrderLines": [_line("HK02-14120-RC", 1)]}
        cards = [
            _card("HK02-14120-RC", replen="Prod. Order", bom="HK02-BOM", on_hand=0, on_so=1),
            _card("RAW-HINGE-01", on_hand=0),  # would-be component if exploded
        ]
        boms = [_bom_line("HK02-BOM", "RAW-HINGE-01", 12.0)]
        _setup(monkeypatch, so, cards, {"HK02-14120-RC": {"unitCost": 137.79, "baseUnitOfMeasureCode": "EA"}},
               bom_lines=boms)

        plan = svc.compute_netted_po_lines("SO-TEST")
        assert plan["excluded_manufactured"] == []
        assert [r["item_no"] for r in plan["included"]] == ["HK02-14120-RC"]
        assert plan["included"][0]["quantity"] == 1
        assert plan["component_shortfall"] == []  # never exploded

    @pytest.mark.parametrize("kit_no", ["HK03-20181-RC", "HK13-1412007-RC", "HK32-16080-RC"])
    def test_whole_hk_family_bought_complete_not_just_hk02(self, monkeypatch, kit_no):
        """Joey, 2026-09-10, after reviewing the other 6 POs: "what I'm
        seeing is exploded hardware box BOMs instead of just a complete
        hardware box order" — HK03 (commercial 3" kits) and HK13
        (high-lift extension) were still exploding on PO-000959/960/963.
        The whole HK family gets the same treatment, not just HK02."""
        so = {"id": "so-1", "number": "SO-TEST", "customerName": "Acme",
              "salesOrderLines": [_line(kit_no, 1)]}
        cards = [
            _card(kit_no, replen="Prod. Order", bom="HK-BOM", on_hand=0, on_so=1),
            _card("RAW-HINGE-01", on_hand=0),
        ]
        boms = [_bom_line("HK-BOM", "RAW-HINGE-01", 12.0)]
        _setup(monkeypatch, so, cards, {kit_no: {"unitCost": 200.0, "baseUnitOfMeasureCode": "EA"}},
               bom_lines=boms)

        plan = svc.compute_netted_po_lines("SO-TEST")
        assert plan["excluded_manufactured"] == []
        assert [r["item_no"] for r in plan["included"]] == [kit_no]
        assert plan["component_shortfall"] == []

    @pytest.mark.parametrize("kit_no", [
        "TR02-STDBM-0812", "TR02-LHR-08", "TR03-STDAM-22", "TR03-EXT7-00",
        "SP12-00231-01", "SP12-00234-01",
    ])
    def test_tr02_tr03_and_sp12_winder_sets_bought_complete(self, monkeypatch, kit_no):
        """Joey, 2026-09-10: "extend the same fix to TR02/TR03 and SP12
        winder sets." Track assemblies and winder+plug sets are complete
        Upwardor items, not something to break into raw track/spring
        pieces."""
        so = {"id": "so-1", "number": "SO-TEST", "customerName": "Acme",
              "salesOrderLines": [_line(kit_no, 2)]}
        cards = [
            _card(kit_no, replen="Prod. Order", bom="ASSY-BOM", on_hand=0, on_so=2),
            _card("RAW-TRACK-01", on_hand=0),
        ]
        boms = [_bom_line("ASSY-BOM", "RAW-TRACK-01", 3.0)]
        _setup(monkeypatch, so, cards, {kit_no: {"unitCost": 90.0, "baseUnitOfMeasureCode": "EA"}},
               bom_lines=boms)

        plan = svc.compute_netted_po_lines("SO-TEST")
        assert plan["excluded_manufactured"] == []
        assert [(r["item_no"], r["quantity"]) for r in plan["included"]] == [(kit_no, 2)]
        assert plan["component_shortfall"] == []

    def test_individual_track_and_spring_pieces_still_purchased_normally(self, monkeypatch):
        """TR10/TR11/TR12 raw track pieces and individual SP12 spring parts
        are Replenishment_System='Purchase' — they were always bought
        directly and the TR02-/TR03-/SP12- prefix widening doesn't touch
        them (the buy-complete check only fires for Prod. Order items)."""
        so = {"id": "so-1", "number": "SO-TEST", "customerName": "Acme", "salesOrderLines": [
            _line("TR11-31850-00", 2), _line("SP12-00257-00", 4),
        ]}
        cards = [_card("TR11-31850-00", replen="Purchase", on_hand=0, on_so=2),
                 _card("SP12-00257-00", replen="Purchase", on_hand=0, on_so=4)]
        _setup(monkeypatch, so, cards, {
            "TR11-31850-00": {"unitCost": 128.0, "baseUnitOfMeasureCode": "PR"},
            "SP12-00257-00": {"unitCost": 11.5, "baseUnitOfMeasureCode": "EA"},
        })

        plan = svc.compute_netted_po_lines("SO-TEST")
        assert {r["item_no"] for r in plan["included"]} == {"TR11-31850-00", "SP12-00257-00"}

    def test_hk10_unaffected_since_it_was_never_manufactured(self, monkeypatch):
        """HK10 is Replenishment_System='Purchase' in BC already (not a
        Prod. Order item) — the HK prefix widening must not change
        anything about how it's netted, since it never explodes to begin
        with."""
        so = {"id": "so-1", "number": "SO-TEST", "customerName": "Acme",
              "salesOrderLines": [_line("HK10-00804-0809", 1)]}
        cards = [_card("HK10-00804-0809", replen="Purchase", on_hand=0, on_so=1)]
        _setup(monkeypatch, so, cards, {"HK10-00804-0809": {"unitCost": 77.67, "baseUnitOfMeasureCode": "EA"}})

        plan = svc.compute_netted_po_lines("SO-TEST")
        assert plan["excluded_manufactured"] == []
        assert [r["item_no"] for r in plan["included"]] == ["HK10-00804-0809"]

    def test_pn45_pn46_bought_complete_not_exploded(self, monkeypatch):
        so = {"id": "so-1", "number": "SO-TEST", "customerName": "Acme", "salesOrderLines": [
            _line("PN46-24405-1800", 3), _line("PN45-24405-1000", 3),
        ]}
        cards = [
            _card("PN46-24405-1800", replen="Prod. Order", bom="PN46-BOM", on_hand=0, on_so=3),
            _card("PN45-24405-1000", replen="Prod. Order", bom="PN45-BOM", on_hand=0, on_so=3),
            _card("PN40-24405-1800", on_hand=0), _card("PN40-24405-1000", on_hand=0),
        ]
        boms = [_bom_line("PN46-BOM", "PN40-24405-1800", 1.0), _bom_line("PN45-BOM", "PN40-24405-1000", 1.0)]
        _setup(monkeypatch, so, cards, {
            "PN46-24405-1800": {"unitCost": 269.89, "baseUnitOfMeasureCode": "EA"},
            "PN45-24405-1000": {"unitCost": 232.36, "baseUnitOfMeasureCode": "EA"},
        }, bom_lines=boms)

        plan = svc.compute_netted_po_lines("SO-TEST")
        assert plan["excluded_manufactured"] == []
        assert {r["item_no"] for r in plan["included"]} == {"PN46-24405-1800", "PN45-24405-1000"}
        assert plan["component_shortfall"] == []

    def test_buy_complete_item_still_netted_against_stock(self, monkeypatch):
        """Complete-purchase items are not a blank check — already-covered
        stock still excludes them, same as any other purchasable item."""
        so = {"id": "so-1", "number": "SO-TEST", "customerName": "Acme",
              "salesOrderLines": [_line("PN46-24405-1800", 2)]}
        cards = [_card("PN46-24405-1800", replen="Prod. Order", bom="PN46-BOM", on_hand=5, on_so=2)]
        _setup(monkeypatch, so, cards, {"PN46-24405-1800": {"unitCost": 269.89, "baseUnitOfMeasureCode": "EA"}},
               bom_lines=[])

        plan = svc.compute_netted_po_lines("SO-TEST")
        assert plan["included"] == []
        assert [r["item_no"] for r in plan["excluded_in_stock"]] == ["PN46-24405-1800"]

    def test_other_manufactured_prefixes_still_explode(self, monkeypatch):
        """PN80 (Panorama), TR02 (lift bracket mounts), SP12-00231-01
        (winder set) are NOT in the buy-complete list yet — regression
        guard so widening the list later is a deliberate, visible change."""
        so = {"id": "so-1", "number": "SO-TEST", "customerName": "Acme",
              "salesOrderLines": [_line("PN80-24100-1202", 1)]}
        cards = [
            _card("PN80-24100-1202", replen="Prod. Order", bom="PN80-BOM", on_hand=0, on_so=1),
            _card("AL97-RAW", on_hand=0),
        ]
        boms = [_bom_line("PN80-BOM", "AL97-RAW", 5.0)]
        _setup(monkeypatch, so, cards, {"AL97-RAW": {"unitCost": 10.0, "baseUnitOfMeasureCode": "EA"}},
               bom_lines=boms)

        plan = svc.compute_netted_po_lines("SO-TEST")
        assert [r["item_no"] for r in plan["excluded_manufactured"]] == ["PN80-24100-1202"]
        assert [r["item_no"] for r in plan["component_shortfall"]] == ["AL97-RAW"]


class TestByDoorLayout:
    """Joey, 2026-09-09: "create the layout that we create the purchase
    orders in... in the same sort of format as we do the sales orders. So
    by door, and in order on the PO based on what we need." """

    def test_no_door_headers_means_no_by_door_grouping(self, monkeypatch):
        so = {"id": "so-1", "number": "SO-TEST", "customerName": "Acme",
              "salesOrderLines": [_line("SHORT-01", 5)]}
        cards = [_card("SHORT-01", on_hand=0, on_so=5)]
        _setup(monkeypatch, so, cards, {"SHORT-01": {"unitCost": 10.0, "baseUnitOfMeasureCode": "EA"}})

        plan = svc.compute_netted_po_lines("SO-TEST")
        assert plan["by_door"] == []
        # everything with no door attribution falls into shared, not dropped
        assert [r["item_no"] for r in plan["shared"]["included"]] == ["SHORT-01"]

    def test_items_grouped_under_their_own_door(self, monkeypatch):
        so = {"id": "so-1", "number": "SO-TEST", "customerName": "Acme", "salesOrderLines": [
            _door_header("(1) 8'0\" x 7'0\" TX450, , UDC", 10000),
            _line("DOOR1-ONLY", 3, seq=20000),
            _door_header("(1) 10'0\" x 8'0\" TX450, , UDC", 30000),
            _line("DOOR2-ONLY", 2, seq=40000),
        ]}
        cards = [_card("DOOR1-ONLY", on_hand=0, on_so=3), _card("DOOR2-ONLY", on_hand=0, on_so=2)]
        _setup(monkeypatch, so, cards, {
            "DOOR1-ONLY": {"unitCost": 1.0, "baseUnitOfMeasureCode": "EA"},
            "DOOR2-ONLY": {"unitCost": 1.0, "baseUnitOfMeasureCode": "EA"},
        })

        plan = svc.compute_netted_po_lines("SO-TEST")
        assert len(plan["by_door"]) == 2
        assert plan["by_door"][0]["door_index"] == 1
        assert plan["by_door"][0]["label"].startswith("(1) 8'0\"")
        assert [r["item_no"] for r in plan["by_door"][0]["included"]] == ["DOOR1-ONLY"]
        assert plan["by_door"][1]["door_index"] == 2
        assert [r["item_no"] for r in plan["by_door"][1]["included"]] == ["DOOR2-ONLY"]
        assert plan["shared"]["included"] == []

    def test_item_ordered_under_two_doors_is_split_per_door_like_the_SO(self, monkeypatch):
        """Joey, 2026-09-10, "revisit the panels on PO 959": the same
        20'-wide section serves door 1 (11) and door 2 (18) — it must show
        as 11 under door 1 and 18 under door 2, mirroring the SO, not one
        lumped line of 29 in a "shared" bucket."""
        so = {"id": "so-1", "number": "SO-TEST", "customerName": "Acme", "salesOrderLines": [
            _door_header("(1) 8'0\" x 7'0\" TX450, , UDC", 10000),
            _line("PANEL-X", 11, seq=20000),
            _door_header("(2) 10'0\" x 8'0\" TX450, , UDC", 30000),
            _line("PANEL-X", 18, seq=40000),
        ]}
        cards = [_card("PANEL-X", on_hand=0, on_so=29)]
        _setup(monkeypatch, so, cards, {"PANEL-X": {"unitCost": 285.0, "baseUnitOfMeasureCode": "EA"}})

        plan = svc.compute_netted_po_lines("SO-TEST")
        assert plan["shared"]["included"] == []
        d1 = next(g for g in plan["by_door"] if g["door_index"] == 1)
        d2 = next(g for g in plan["by_door"] if g["door_index"] == 2)
        assert [(r["item_no"], r["quantity"]) for r in d1["included"]] == [("PANEL-X", 11)]
        assert [(r["item_no"], r["quantity"]) for r in d2["included"]] == [("PANEL-X", 18)]

    def test_multi_door_item_partial_stock_fills_doors_in_SO_order(self, monkeypatch):
        # 29 wanted (11 + 18), 15 already on hand -> net 14: door 1 takes
        # its full 11 first, door 2 gets the remaining 3.
        so = {"id": "so-1", "number": "SO-TEST", "customerName": "Acme", "salesOrderLines": [
            _door_header("(1) 8'0\" x 7'0\" TX450, , UDC", 10000),
            _line("PANEL-X", 11, seq=20000),
            _door_header("(1) 10'0\" x 8'0\" TX450, , UDC", 30000),
            _line("PANEL-X", 18, seq=40000),
        ]}
        cards = [_card("PANEL-X", on_hand=15, on_so=29)]
        _setup(monkeypatch, so, cards, {"PANEL-X": {"unitCost": 285.0, "baseUnitOfMeasureCode": "EA"}})

        plan = svc.compute_netted_po_lines("SO-TEST")
        d1 = next(g for g in plan["by_door"] if g["door_index"] == 1)
        d2 = next(g for g in plan["by_door"] if g["door_index"] == 2)
        assert d1["included"][0]["quantity"] == 11
        assert d2["included"][0]["quantity"] == 3

    def test_manufactured_items_raw_material_attributed_to_its_door(self, monkeypatch):
        so = {"id": "so-1", "number": "SO-TEST", "customerName": "Acme", "salesOrderLines": [
            _door_header("(1) 18'0\" x 8'0\" TX450, , UDC", 10000),
            _line("MFG-PANEL-03", 3, seq=20000),
        ]}
        cards = [
            _card("MFG-PANEL-03", replen="Prod. Order", bom="PN46-BOM"),
            _card("RAW-CORE-03", on_hand=0),
        ]
        boms = [_bom_line("PN46-BOM", "RAW-CORE-03", 1.0)]
        _setup(monkeypatch, so, cards, {"RAW-CORE-03": {"unitCost": 257.51, "baseUnitOfMeasureCode": "EA"}},
               bom_lines=boms)

        plan = svc.compute_netted_po_lines("SO-TEST")
        assert len(plan["by_door"]) == 1
        assert [r["item_no"] for r in plan["by_door"][0]["component_shortfall"]] == ["RAW-CORE-03"]
        assert plan["shared"]["component_shortfall"] == []

    def test_build_upwardor_po_writes_a_comment_heading_per_door_in_order(self, monkeypatch):
        so = {"id": "so-1", "number": "SO-TEST", "customerName": "Acme", "salesOrderLines": [
            _door_header("(1) 8'0\" x 7'0\" TX450, , UDC", 10000),
            _line("DOOR1-ONLY", 3, seq=20000),
            _door_header("(1) 10'0\" x 8'0\" TX450, , UDC", 30000),
            _line("DOOR2-ONLY", 2, seq=40000),
        ]}
        cards = [_card("DOOR1-ONLY", on_hand=0, on_so=3), _card("DOOR2-ONLY", on_hand=0, on_so=2)]
        bc, _ = _setup(monkeypatch, so, cards, {
            "DOOR1-ONLY": {"unitCost": 1.0, "baseUnitOfMeasureCode": "EA"},
            "DOOR2-ONLY": {"unitCost": 1.0, "baseUnitOfMeasureCode": "EA"},
        })

        result = svc.build_upwardor_po("SO-TEST", dry_run=False)
        assert result["bc_po_number"] == "PO-TEST-001"
        kinds = [(b["lineType"], b.get("lineObjectNumber"), b.get("description")) for _, b in bc.lines]
        # header, provenance, then door 1's heading + item, door 2's heading + item
        assert kinds[2][0] == "Comment" and kinds[2][2].startswith("(1) 8'0\"")
        assert kinds[3] == ("Item", "DOOR1-ONLY", "desc DOOR1-ONLY")
        assert kinds[4][0] == "Comment" and kinds[4][2].startswith("(1) 10'0\"")
        assert kinds[5] == ("Item", "DOOR2-ONLY", "desc DOOR2-ONLY")

    def test_build_upwardor_po_splits_multi_door_item_under_each_door(self, monkeypatch):
        so = {"id": "so-1", "number": "SO-TEST", "customerName": "Acme", "salesOrderLines": [
            _door_header("(1) 8'0\" x 7'0\" TX450, , UDC", 10000),
            _line("PANEL-X", 11, seq=20000),
            _door_header("(1) 10'0\" x 8'0\" TX450, , UDC", 30000),
            _line("PANEL-X", 18, seq=40000),
        ]}
        cards = [_card("PANEL-X", on_hand=0, on_so=29)]
        bc, _ = _setup(monkeypatch, so, cards, {"PANEL-X": {"unitCost": 285.0, "baseUnitOfMeasureCode": "EA"}})

        svc.build_upwardor_po("SO-TEST", dry_run=False)
        kinds = [(b["lineType"], b.get("lineObjectNumber"), b.get("quantity")) for _, b in bc.lines]
        assert kinds[2][0] == "Comment"
        assert kinds[3] == ("Item", "PANEL-X", 11)
        assert kinds[4][0] == "Comment"
        assert kinds[5] == ("Item", "PANEL-X", 18)
        # no "shared" section — every line landed under a door
        assert not any(b.get("description") == "ITEMS SHARED ACROSS MULTIPLE DOORS ON THIS ORDER"
                       for _, b in bc.lines)

    def test_item_with_no_door_attribution_stays_in_shared(self, monkeypatch):
        # An item that appears BEFORE any door header (unusual, but a
        # manually-edited SO can look like this) has no door and lands in
        # the shared section.
        so = {"id": "so-1", "number": "SO-TEST", "customerName": "Acme", "salesOrderLines": [
            _line("NO-DOOR-ITEM", 2, seq=5000),
            _door_header("(1) 8'0\" x 7'0\" TX450, , UDC", 10000),
            _line("DOOR1-ITEM", 1, seq=20000),
        ]}
        cards = [_card("NO-DOOR-ITEM", on_hand=0, on_so=2), _card("DOOR1-ITEM", on_hand=0, on_so=1)]
        _setup(monkeypatch, so, cards, {
            "NO-DOOR-ITEM": {"unitCost": 1.0, "baseUnitOfMeasureCode": "EA"},
            "DOOR1-ITEM": {"unitCost": 1.0, "baseUnitOfMeasureCode": "EA"},
        })

        plan = svc.compute_netted_po_lines("SO-TEST")
        assert [r["item_no"] for r in plan["shared"]["included"]] == ["NO-DOOR-ITEM"]
        assert [r["item_no"] for r in plan["by_door"][0]["included"]] == ["DOOR1-ITEM"]


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
              "salesOrderLines": [_line("MFG-PANEL-03", 3)]}
        cards = [
            _card("MFG-PANEL-03", replen="Prod. Order", bom="PN46-BOM"),
            _card("RAW-CORE-03", on_hand=0),
        ]
        boms = [_bom_line("PN46-BOM", "RAW-CORE-03", 1.0)]
        bc, _ = _setup(monkeypatch, so, cards, {"RAW-CORE-03": {"unitCost": 257.51, "baseUnitOfMeasureCode": "EA"}},
                        bom_lines=boms)

        result = svc.build_upwardor_po("SO-TEST", dry_run=False)
        assert result["bc_po_number"] == "PO-TEST-001"
        kinds = [(b["lineType"], b.get("lineObjectNumber"), b.get("description")) for _, b in bc.lines]
        # header comment, provenance comment, marker comment, then the raw material
        assert kinds[2][0] == "Comment" and "Raw materials" in kinds[2][2]
        # BC Comment lines 400 past 100 chars (Application_StringExceededLength) — hit live on 2026-09-09.
        assert len(kinds[2][2]) <= 100
        assert kinds[3] == ("Item", "RAW-CORE-03", "desc RAW-CORE-03")
        assert bc.lines[3][1]["quantity"] == 3


class TestRewritePoLines:
    """rewrite_po_lines corrects an EXISTING Draft PO — used to fix the 6
    other hand-built POs (PO-000956..PO-000961) the same way PO-000962 was
    fixed. Must delete the PO's own current lines BEFORE netting, or its
    own (possibly wrong) quantities look like "already on order" and
    silently suppress real demand — confirmed live 2026-09-09."""

    def _existing_po(self, lines):
        return {"PO-EXIST-001": {
            "id": "po-existing-1", "number": "PO-EXIST-001", "status": "Draft",
            "purchaseOrderLines": lines,
        }}

    def test_deletes_old_lines_before_computing_the_new_plan(self, monkeypatch):
        # The existing PO already lists SHORT-01 at the full (wrong,
        # unnetted) SO quantity — if that were still present when netting
        # runs, on_po_other would make it look covered. It must be gone
        # first, so the real shortfall (5) comes through.
        old_lines = [{"id": "old-line-1", "lineType": "Item",
                      "lineObjectNumber": "SHORT-01", "quantity": 5, "receivedQuantity": 0}]
        existing = self._existing_po(old_lines)
        so = {"id": "so-1", "number": "SO-TEST", "customerName": "Acme",
              "salesOrderLines": [_line("SHORT-01", 5)]}
        cards = [_card("SHORT-01", on_hand=0, on_so=5)]
        bc, _ = _setup(monkeypatch, so, cards, {"SHORT-01": {"unitCost": 10.0, "baseUnitOfMeasureCode": "EA"}},
                        existing_po=existing)

        result = svc.rewrite_po_lines("PO-EXIST-001", "SO-TEST")
        assert bc.deleted_line_ids == ["old-line-1"]
        assert result["lines_deleted"] == 1
        assert result["lines_written"] == 1
        assert result["included"][0]["quantity"] == 5  # not suppressed by its own stale line

    def test_refuses_non_draft_po(self, monkeypatch):
        existing = {"PO-EXIST-001": {"id": "x", "number": "PO-EXIST-001", "status": "Released",
                                      "purchaseOrderLines": []}}
        so = {"id": "so-1", "number": "SO-TEST", "customerName": "Acme", "salesOrderLines": []}
        bc, _ = _setup(monkeypatch, so, [], existing_po=existing)
        with pytest.raises(ValueError, match="Draft"):
            svc.rewrite_po_lines("PO-EXIST-001", "SO-TEST")
        assert bc.deleted_line_ids == []

    def test_refuses_po_with_received_quantity(self, monkeypatch):
        old_lines = [{"id": "old-line-1", "lineType": "Item",
                      "lineObjectNumber": "SHORT-01", "quantity": 5, "receivedQuantity": 2}]
        existing = self._existing_po(old_lines)
        so = {"id": "so-1", "number": "SO-TEST", "customerName": "Acme", "salesOrderLines": []}
        bc, _ = _setup(monkeypatch, so, [], existing_po=existing)
        with pytest.raises(ValueError, match="received"):
            svc.rewrite_po_lines("PO-EXIST-001", "SO-TEST")
        assert bc.deleted_line_ids == []

    def test_unknown_po_raises(self, monkeypatch):
        so = {"id": "so-1", "number": "SO-TEST", "customerName": "Acme", "salesOrderLines": []}
        _setup(monkeypatch, so, [], existing_po={})
        with pytest.raises(ValueError, match="not found"):
            svc.rewrite_po_lines("PO-MISSING", "SO-TEST")

    def test_writes_by_door_layout_into_the_same_po(self, monkeypatch):
        old_lines = [{"id": "old-line-1", "lineType": "Item",
                      "lineObjectNumber": "DOOR1-ONLY", "quantity": 3, "receivedQuantity": 0}]
        existing = self._existing_po(old_lines)
        so = {"id": "so-1", "number": "SO-TEST", "customerName": "Acme", "salesOrderLines": [
            _door_header("(1) 8'0\" x 7'0\" TX450, , UDC", 10000),
            _line("DOOR1-ONLY", 3, seq=20000),
        ]}
        cards = [_card("DOOR1-ONLY", on_hand=0, on_so=3)]
        bc, _ = _setup(monkeypatch, so, cards, {"DOOR1-ONLY": {"unitCost": 1.0, "baseUnitOfMeasureCode": "EA"}},
                        existing_po=existing)

        result = svc.rewrite_po_lines("PO-EXIST-001", "SO-TEST")
        assert result["lines_written"] == 1
        kinds = [(b["lineType"], b.get("lineObjectNumber"), b.get("description")) for _, b in bc.lines]
        assert kinds[2][2].startswith("(1) 8'0\"")
        assert kinds[3] == ("Item", "DOOR1-ONLY", "desc DOOR1-ONLY")

    def test_nothing_to_order_still_clears_old_lines(self, monkeypatch):
        old_lines = [{"id": "old-line-1", "lineType": "Item",
                      "lineObjectNumber": "COVERED-01", "quantity": 1, "receivedQuantity": 0}]
        existing = self._existing_po(old_lines)
        so = {"id": "so-1", "number": "SO-TEST", "customerName": "Acme",
              "salesOrderLines": [_line("COVERED-01", 1)]}
        cards = [_card("COVERED-01", on_hand=99, on_so=1)]
        bc, _ = _setup(monkeypatch, so, cards, existing_po=existing)

        result = svc.rewrite_po_lines("PO-EXIST-001", "SO-TEST")
        assert bc.deleted_line_ids == ["old-line-1"]
        assert result["lines_written"] == 0
        assert bc.lines == []  # no comments/items written when there's nothing to order
