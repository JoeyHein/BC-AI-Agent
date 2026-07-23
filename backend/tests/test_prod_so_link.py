"""Tests for linking production orders to sales orders via BC reservations,
then grouping cut work orders under the parent sales order."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from app.services.bc_production_service import (
    build_prod_so_map, RES_SRC_SALES_LINE, RES_SRC_PROD_ORDER_LINE,
)
from app.services.cutting_stock_service import CuttingStockService
from app.services.cut_work_order_service import cut_work_order_service as wos


def _res(entry, src_type, src_id):
    return {"Reservation_Entry": entry, "Source_Type": src_type, "Source_ID": src_id}


class TestReservationMap:
    def test_pairs_prod_and_sales_on_shared_entry(self):
        entries = [
            _res(101, RES_SRC_PROD_ORDER_LINE, "PROD-000828"),
            _res(101, RES_SRC_SALES_LINE, "SO-001187"),
            _res(102, RES_SRC_PROD_ORDER_LINE, "PROD-001339"),
            _res(102, RES_SRC_SALES_LINE, "SO-001187"),
        ]
        m = build_prod_so_map(entries)
        assert m == {"PROD-000828": "SO-001187", "PROD-001339": "SO-001187"}

    def test_pairs_on_component_source_type_5406(self):
        """Live data pairs the sales line with a Prod. Order COMPONENT (5406),
        not the line (5407) — pairing must work by document prefix regardless."""
        entries = [
            _res(10780, RES_SRC_SALES_LINE, "SO-000661"),
            _res(10780, 5406, "PROD-000429"),   # Prod. Order Component
        ]
        assert build_prod_so_map(entries) == {"PROD-000429": "SO-000661"}

    def test_ignores_non_so_non_prod_sides(self):
        # A PLANNING reservation (type 246) shouldn't produce a mapping.
        entries = [
            _res(12893, 246, "PLANNING"),
            _res(12893, RES_SRC_SALES_LINE, "SO-000900"),
        ]
        assert build_prod_so_map(entries) == {}

    def test_unpaired_prod_is_ignored(self):
        # A prod order with no sales-line partner (make-to-stock) doesn't map.
        entries = [_res(200, RES_SRC_PROD_ORDER_LINE, "PROD-000828")]
        assert build_prod_so_map(entries) == {}

    def test_empty_entries(self):
        assert build_prod_so_map([]) == {}
        assert build_prod_so_map(None) == {}


def _rows_for_prod(prod):
    return [
        {"item_no": "PN40-21400-1000", "demand": 3, "on_hand": 0, "on_order": 0,
         "net_need": 3, "unit_cost": 100.0, "unit_of_measure": "EA", "jobs": [prod]},
        {"item_no": "PN40-21400-3204", "demand": 0, "on_hand": 8, "on_order": 0,
         "net_need": 0, "unit_cost": 393.0, "unit_of_measure": "EA", "jobs": []},
    ]
CAT = ["PN40-21400-3204", "PN40-21400-1000", "PN40-21400-1604"]


class TestRegrouping:
    def test_prod_order_regrouped_under_sales_order(self):
        recs = CuttingStockService().analyze(_rows_for_prod("PROD-000828"))
        wo = wos.build_proposed(recs, CAT, prod_so_map={"PROD-000828": "SO-001187"})
        assert len(wo) == 1
        assert wo[0]["so_number"] == "SO-001187"          # grouped under the SO
        assert wo[0]["prod_orders"] == ["PROD-000828"]     # prod noted
        assert wo[0]["cuts"][0]["prod_order"] == "PROD-000828"
        # Journal document is keyed to the SALES order now.
        assert wo[0]["journal"]["document_no"] == "CUT-001187"

    def test_unmapped_prod_stands_alone(self):
        """No reservation link yet -> production order is its own work order."""
        recs = CuttingStockService().analyze(_rows_for_prod("PROD-000828"))
        wo = wos.build_proposed(recs, CAT, prod_so_map={})
        assert wo[0]["so_number"] == "PROD-000828"
        assert wo[0]["prod_orders"] == []

    def test_two_prods_under_one_so_merge(self):
        recs = (CuttingStockService().analyze(_rows_for_prod("PROD-000828"))
                + CuttingStockService().analyze(_rows_for_prod("PROD-000841")))
        wo = wos.build_proposed(recs, CAT, prod_so_map={
            "PROD-000828": "SO-001187", "PROD-000841": "SO-001187"})
        assert len(wo) == 1                                # one SO card
        assert wo[0]["so_number"] == "SO-001187"
        assert set(wo[0]["prod_orders"]) == {"PROD-000828", "PROD-000841"}
