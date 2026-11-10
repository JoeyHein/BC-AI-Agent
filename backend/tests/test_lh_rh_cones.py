"""LH/RH winder cones replace the retired universal -01 items.

Covers part selection, quote pricing, and the staff migration preview that
splits open sales orders and Draft POs without calling Business Central
for real.
"""
import os
import sys
from decimal import Decimal, ROUND_HALF_UP

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.bc_part_number_mapper import BCPartNumberMapper, get_bc_mapper
from app.services.cone_migration_service import (
    allocate_sales_prices,
    cone_migration_service,
    plan_cone_replacements,
)
from app.services.door_calculator_service import SpringSelection
from app.services.part_number_service import DoorConfiguration, PartNumberService, get_parts_for_door_config
from app.services.spring_builder_service import SpringBuilderService
from app.services import part_number_service as pns

RETIRED = set(BCPartNumberMapper.RETIRED_UNIVERSAL_CONES)


class _Drum:
    model = "D400-54"


def _config(**overrides):
    data = dict(
        door_type="residential",
        door_series="KANATA",
        door_width=108,
        door_height=84,
        door_count=1,
        panel_color="WHITE",
        panel_design="SHXL",
        door_weight=200,
        target_cycles=10000,
    )
    data.update(overrides)
    return DoorConfiguration(**data)


def _cones(parts):
    return [
        p for p in parts
        if (p.part_number or "").startswith("SP12-002")
        and p.category == "spring_accessory"
    ]


def _select(monkeypatch, selection):
    monkeypatch.setattr(pns.door_calculator, "_select_drum", lambda *a, **k: _Drum())
    monkeypatch.setattr(
        pns.door_calculator, "_calculate_springs", lambda *a, **k: selection,
    )


class TestWinderLookup:
    def test_every_coil_returns_its_own_hand_and_never_the_universal(self):
        mapper = get_bc_mapper()
        # Even if the retired item is still in the catalog, it is not sold.
        mapper.bc_items.setdefault("SP12-00233-01", {"number": "SP12-00233-01"})
        expected = {
            (2.0, 1.0, "LH"): "SP12-00231-00",
            (2.0, 1.0, "RH"): "SP12-00237-00",
            (2.625, 1.0, "LH"): "SP12-00232-00",
            (2.625, 1.0, "RH"): "SP12-00238-00",
            (3.75, 1.0, "LH"): "SP12-00233-00",
            (3.75, 1.0, "RH"): "SP12-00239-00",
            (6.0, 1.0, "LH"): "SP12-00234-00",
            (6.0, 1.0, "RH"): "SP12-00240-00",
            (6.0, 1.25, "LH"): "SP12-00236-00",
            (6.0, 1.25, "RH"): "SP12-00242-00",
        }
        assert set(BCPartNumberMapper.WINDER_SETS_UNIVERSAL.values()) == RETIRED
        for key, part in expected.items():
            got = mapper.get_winder_stationary_set(*key)
            assert got.part_number == part
            assert got.part_number not in RETIRED
            assert key[2] in got.description

    def test_format_for_quote_emits_one_line_per_hand(self):
        mapper = get_bc_mapper()
        door = mapper.generate_door_parts(
            door_width_feet=9, door_height_feet=7, spring_coil_id=2.0,
            spring_length_inches=30, spring_quantity_per_side=1,
        )
        lines = mapper.format_for_quote(door, door_description="(1) 9'0\" x 7'0\"", door_index=1)
        winders = [ln for ln in lines if ln["category"] == "SPRING_ACCESSORY"]
        assert [(ln["part_number"], ln["quantity"]) for ln in winders] == [
            ("SP12-00231-00", 1),
            ("SP12-00237-00", 1),
        ]

    def test_builder_cone_sets_are_distinct_hands(self):
        cones = SpringBuilderService()._resolve_cone_sets(3.75)
        assert cones["lh"]["part_number"] == "SP12-00233-00"
        assert cones["rh"]["part_number"] == "SP12-00239-00"
        assert cones["universal"] is None


class TestQuoteLines:
    def test_two_spring_door_is_one_lh_and_one_rh(self, monkeypatch):
        _select(monkeypatch, SpringSelection(
            quantity=2, coil_diameter=2.0, wire_diameter=0.250,
            length=30, cycles=10000, turns=8,
        ))
        parts, _positions, _tandem = PartNumberService()._get_spring_parts(_config())
        cones = _cones(parts)
        assert [(c.part_number, c.quantity) for c in cones] == [
            ("SP12-00231-00", 1),
            ("SP12-00237-00", 1),
        ]

    def test_single_spring_door_is_lh_only(self, monkeypatch):
        _select(monkeypatch, SpringSelection(
            quantity=1, coil_diameter=2.0, wire_diameter=0.250,
            length=30, cycles=10000, turns=8,
        ))
        parts, _positions, _tandem = PartNumberService()._get_spring_parts(_config())
        cones = _cones(parts)
        assert [(c.part_number, c.quantity) for c in cones] == [("SP12-00231-00", 1)]

    def test_duplex_cones_follow_each_coil_and_hand(self, monkeypatch):
        _select(monkeypatch, SpringSelection(
            quantity=4, coil_diameter=6.0, wire_diameter=0.312,
            length=30, cycles=25000, turns=8, is_duplex=True, duplex_pairs=2,
            inner_coil_diameter=3.75, inner_wire_diameter=0.262, inner_length=28,
        ))
        parts, _positions, _tandem = PartNumberService()._get_spring_parts(_config(door_weight=800))
        cones = _cones(parts)
        assert [(c.part_number, c.quantity) for c in cones] == [
            ("SP12-00233-00", 1),  # inner 3-3/4" LH
            ("SP12-00239-00", 1),  # inner 3-3/4" RH
            ("SP12-00234-00", 1),  # outer 6" LH
            ("SP12-00240-00", 1),  # outer 6" RH
        ]

    def test_heavy_six_inch_door_uses_one_and_a_quarter_bore(self, monkeypatch):
        _select(monkeypatch, SpringSelection(
            quantity=2, coil_diameter=6.0, wire_diameter=0.312,
            length=30, cycles=25000, turns=8,
        ))
        parts, _positions, _tandem = PartNumberService()._get_spring_parts(
            _config(door_type="commercial", door_series="TX450", door_weight=2500)
        )
        cones = _cones(parts)
        assert [(c.part_number, c.quantity) for c in cones] == [
            ("SP12-00236-00", 1),
            ("SP12-00242-00", 1),
        ]
        assert all("1-1/4" in c.description for c in cones)
        assert not any(p.notes == "winder_bore_mismatch" for p in parts)

    def test_unstocked_bore_does_not_fall_back_to_universal(self, monkeypatch):
        _select(monkeypatch, SpringSelection(
            quantity=2, coil_diameter=3.75, wire_diameter=0.262,
            length=30, cycles=25000, turns=8,
        ))
        parts, _positions, _tandem = PartNumberService()._get_spring_parts(
            _config(door_type="commercial", door_series="TX450", door_weight=2500)
        )
        cones = _cones(parts)
        assert [c.part_number for c in cones] == ["SP12-00233-00", "SP12-00239-00"]
        assert any(p.notes == "winder_bore_mismatch" for p in parts)
        assert not any(c.part_number in RETIRED for c in cones)

    def test_live_configurator_quote_has_no_universal_cone(self):
        retired_hits = []
        for cfg in (
            {
                "doorType": "residential", "doorSeries": "KANATA",
                "doorWidth": 108, "doorHeight": 84, "doorCount": 1,
                "panelColor": "WHITE", "panelDesign": "SHXL",
                "targetCycles": 10000, "trackThickness": "2",
            },
            {
                "doorType": "commercial", "doorSeries": "TX450",
                "doorWidth": 168, "doorHeight": 120, "doorCount": 2,
                "panelColor": "WHITE", "panelDesign": "UDC",
                "targetCycles": 25000, "trackThickness": "3",
            },
        ):
            parts = get_parts_for_door_config(cfg)["parts_list"]
            retired_hits.extend(
                p["part_number"] for p in parts if p.get("part_number") in RETIRED
            )
        assert retired_hits == []


class TestEqualizeConePrices:
    def test_higher_lh_rh_card_wins_and_universal_is_ignored(self, monkeypatch):
        from app.api import customer_portal as portal

        updates = []
        lines = [
            {"id": "a", "lineType": "Item", "lineObjectNumber": "SP12-00231-00",
             "unitPrice": 15.75, "@odata.etag": "e1"},
            {"id": "b", "lineType": "Item", "lineObjectNumber": "SP12-00237-00",
             "unitPrice": 18.00, "@odata.etag": "e2"},
            {"id": "c", "lineType": "Item", "lineObjectNumber": "SP12-00231-01",
             "unitPrice": 56.26, "@odata.etag": "e3"},
        ]

        class BC:
            def get_quote_lines(self, _qid):
                return lines

            def update_quote_line(self, _qid, lid, _etag, data):
                updates.append((lid, data))

        monkeypatch.setattr(portal, "bc_client", BC())
        portal._equalize_cone_prices("quote-1")
        assert updates == [("a", {"unitPrice": 18.00})]

    def test_single_spring_lh_cone_is_left_alone(self, monkeypatch):
        from app.api import customer_portal as portal

        updates = []

        class BC:
            def get_quote_lines(self, _qid):
                return [{
                    "id": "a", "lineType": "Item", "lineObjectNumber": "SP12-00231-00",
                    "unitPrice": 15.75, "@odata.etag": "e1",
                }]

            def update_quote_line(self, *args, **kwargs):
                updates.append(args)

        monkeypatch.setattr(portal, "bc_client", BC())
        portal._equalize_cone_prices("quote-1")
        assert updates == []


class TestSalesPriceSplit:
    def test_even_split_preserves_the_line_amount(self):
        prices = allocate_sales_prices("826.20", 5, 5)
        assert prices["lh_unit_price"] == prices["rh_unit_price"]
        assert prices["lh_amount"] + prices["rh_amount"] == Decimal("826.20")

    def test_odd_cent_lands_on_the_lh_line(self):
        prices = allocate_sales_prices("10.01", 1, 1)
        assert prices["lh_amount"] == Decimal("5.01")
        assert prices["rh_amount"] == Decimal("5.00")
        assert prices["lh_unit_price"] == Decimal("5.01")
        assert prices["rh_unit_price"] == Decimal("5.00")

    def test_uneven_quantities_still_sum_to_the_original(self):
        prices = allocate_sales_prices("10.00", 2, 1)
        assert format(prices["lh_amount"] + prices["rh_amount"], "f") == "10.00"
        # BC will recompute amount from unit price × qty. That must match too.
        for qty, unit, amount in (
            (2, prices["lh_unit_price"], prices["lh_amount"]),
            (1, prices["rh_unit_price"], prices["rh_amount"]),
        ):
            got = (unit * qty).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            assert got == amount


def _so_line(**kwargs):
    row = {
        "lineType": "Item", "sequence": 100, "quantity": 1,
        "description": "", "unitPrice": 10,
    }
    row.update(kwargs)
    return row


class TestMigrationPreview:
    def test_invoice_example_splits_ten_into_five_and_five(self):
        lines = [
            _so_line(
                id="L1", lineObjectNumber="SP12-00233-01", quantity=10,
                unitPrice=82.62, amountExcludingTax=826.20, sequence=100,
                description="UNIVERSAL",
            ),
            _so_line(id="L2", lineObjectNumber="SP11-25036-01", quantity=120, sequence=110),
            _so_line(id="L3", lineObjectNumber="SP11-25036-02", quantity=120, sequence=120),
        ]
        plan = plan_cone_replacements(lines, price_sales=True)[0]
        assert plan["split_source"] == "springs"
        assert plan["flags"] == []
        assert [(r["item_no"], r["quantity"], r["line_amount"]) for r in plan["replacements"]] == [
            ("SP12-00233-00", 5, "413.10"),
            ("SP12-00239-00", 5, "413.10"),
        ]

    def test_single_spring_order_keeps_every_cone_on_lh(self):
        lines = [
            _so_line(id="L1", lineObjectNumber="SP12-00231-01", quantity=4, unitPrice=10,
                     amountExcludingTax=40, sequence=2),
            _so_line(id="L2", lineObjectNumber="SP11-25020-01", quantity=80, sequence=1),
        ]
        plan = plan_cone_replacements(lines, price_sales=True)[0]
        assert [r["hand"] for r in plan["replacements"]] == ["LH"]
        assert plan["replacements"][0]["quantity"] == 4
        assert plan["flags"] == []
        assert plan["replacements"][0]["line_amount"] == "40.00"

    def test_unknown_hands_split_evenly_and_flag_an_odd_quantity(self):
        lines = [_so_line(id="L1", lineObjectNumber="SP12-00234-01", quantity=5,
                          unitPrice=10, amountExcludingTax=50)]
        plan = plan_cone_replacements(lines, price_sales=True)[0]
        assert plan["split_source"] == "even"
        assert "odd_quantity" in plan["flags"]
        qty = {r["hand"]: r["quantity"] for r in plan["replacements"]}
        assert qty == {"LH": 3, "RH": 2}
        total = sum(float(r["line_amount"]) for r in plan["replacements"])
        assert total == pytest.approx(50.00)

    def test_door_sections_do_not_share_a_hand_split(self):
        lines = [
            {"lineType": "Comment", "description": '(1) 9\'0" x 7\'0" KANATA', "sequence": 1},
            _so_line(lineObjectNumber="SP11-25020-01", quantity=30, sequence=2),
            _so_line(id="c1", lineObjectNumber="SP12-00231-01", quantity=1,
                     unitPrice=10, amountExcludingTax=10, sequence=3),
            {"lineType": "Comment", "description": '(2) 16\'0" x 8\'0" TX450', "sequence": 4},
            _so_line(lineObjectNumber="SP11-25020-01", quantity=40, sequence=5),
            _so_line(lineObjectNumber="SP11-25020-02", quantity=40, sequence=6),
            _so_line(id="c2", lineObjectNumber="SP12-00231-01", quantity=2,
                     unitPrice=10, amountExcludingTax=20, sequence=7),
        ]
        plans = plan_cone_replacements(lines, price_sales=True)
        by_id = {p["line_id"]: p for p in plans}
        assert [r["hand"] for r in by_id["c1"]["replacements"]] == ["LH"]
        assert [(r["hand"], r["quantity"]) for r in by_id["c2"]["replacements"]] == [
            ("LH", 1), ("RH", 1),
        ]

    def test_dry_run_does_not_write_and_apply_does(self):
        client = _FakeBC()
        client.sales_orders = [{
            "id": "so-1", "number": "SO-100", "status": "Open", "customerName": "Acme",
            "salesOrderLines": [
                _so_line(id="L1", lineObjectNumber="SP12-00233-01", quantity=10,
                         unitPrice=82.62, amountExcludingTax=826.20, sequence=1),
                _so_line(lineObjectNumber="SP11-25036-01", quantity=30, sequence=2),
                _so_line(lineObjectNumber="SP11-25036-02", quantity=30, sequence=3),
            ],
        }]
        client.purchase_orders = [
            {
                "id": "po-1", "number": "PO-10", "status": "Draft", "vendorName": "Upwardor",
                "purchaseOrderLines": [
                    {"id": "P1", "lineType": "Item", "lineObjectNumber": "SP12-00233-01",
                     "quantity": 10, "directUnitCost": 40, "sequence": 1, "description": "old"},
                ],
            },
            {
                "id": "po-2", "number": "PO-11", "status": "Open",
                "purchaseOrderLines": [
                    {"id": "P2", "lineType": "Item", "lineObjectNumber": "SP12-00233-01",
                     "quantity": 4, "sequence": 1},
                ],
            },
        ]
        client.cards = {
            "SP12-00233-00": {"unitCost": 8.10, "displayName": "LH CONE"},
            "SP12-00239-00": {"unitCost": 8.20, "displayName": "RH CONE"},
        }

        preview = cone_migration_service.run(apply=False, client=client)
        assert preview["dry_run"] is True
        assert preview["sales_order_count"] == 1
        assert preview["purchase_order_count"] == 1  # Open PO is not a Draft
        assert client.added_so == [] and client.deleted_so == []
        assert client.added_po == [] and client.deleted_po == []
        po_change = preview["purchase_orders"][0]["changes"][0]
        assert [(r["item_no"], r["quantity"], r["unit_cost"]) for r in po_change["replacements"]] == [
            ("SP12-00233-00", 5, "8.10"),
            ("SP12-00239-00", 5, "8.20"),
        ]

        applied = cone_migration_service.run(apply=True, client=client)
        assert applied["dry_run"] is False
        assert len(client.added_so) == 2
        assert client.deleted_so == [("so-1", "L1")]
        assert client.added_so[0][1]["unitPrice"] == pytest.approx(82.62)
        assert client.added_so[1][1]["unitPrice"] == pytest.approx(82.62)
        assert {row[1]["lineObjectNumber"] for row in client.added_so} == {
            "SP12-00233-00", "SP12-00239-00",
        }
        assert len(client.added_po) == 2
        assert client.deleted_po == [("po-1", "P1")]
        costs = {row[1]["lineObjectNumber"]: row[1]["directUnitCost"] for row in client.added_po}
        assert costs == {"SP12-00233-00": pytest.approx(8.10), "SP12-00239-00": pytest.approx(8.20)}

    def test_apply_refuses_a_line_whose_lh_rh_cost_is_missing(self):
        client = _FakeBC()
        client.purchase_orders = [{
            "id": "po-1", "number": "PO-10", "status": "Draft",
            "purchaseOrderLines": [
                {"id": "P1", "lineType": "Item", "lineObjectNumber": "SP12-00231-01",
                 "quantity": 2, "sequence": 1},
            ],
        }]
        result = cone_migration_service.run(apply=True, client=client)
        assert client.added_po == []
        assert client.deleted_po == []
        assert result["errors"]
        assert "missing" in result["errors"][0]["error"].lower() or result["purchase_orders"][0]["changes"][0]["flags"]

    def test_shipped_line_is_left_in_place(self):
        client = _FakeBC()
        client.sales_orders = [{
            "id": "so-1", "number": "SO-100", "status": "Open",
            "salesOrderLines": [
                _so_line(id="L1", lineObjectNumber="SP12-00231-01", quantity=2,
                         unitPrice=10, amountExcludingTax=20, shippedQuantity=1),
            ],
        }]
        result = cone_migration_service.run(apply=True, client=client)
        assert client.added_so == []
        assert client.deleted_so == []
        assert result["sales_orders"][0]["changes"][0]["skipped"] is True


class _FakeBC:
    def __init__(self):
        self.sales_orders = []
        self.purchase_orders = []
        self.cards = {}
        self.added_so = []
        self.deleted_so = []
        self.added_po = []
        self.deleted_po = []

    def get_open_sales_orders_with_lines(self):
        return self.sales_orders

    def get_draft_purchase_orders_with_lines(self):
        return self.purchase_orders

    def get_items_by_numbers(self, numbers):
        return {n: self.cards[n] for n in numbers if n in self.cards}

    def add_order_line(self, order_id, data):
        self.added_so.append((order_id, data))
        return {"id": "new-so"}

    def delete_order_line(self, order_id, line_id):
        self.deleted_so.append((order_id, line_id))
        return True

    def add_purchase_order_line(self, po_id, data):
        self.added_po.append((po_id, data))
        return {"id": "new-po"}

    def delete_purchase_order_line(self, po_id, line_id):
        self.deleted_po.append((po_id, line_id))
        return True
