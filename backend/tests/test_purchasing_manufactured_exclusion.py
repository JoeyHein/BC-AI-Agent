"""compute_requirements must never buy an item BC flags as manufactured
in-house (Replenishment_System='Prod. Order') — it needs a production
order, not a vendor PO. Was a "~2 items, revisit if it grows" footnote;
PO-000962 (2026-09-08) showed 13 of 40 items on one hand-built PO were
manufactured panels/kits ($4,585 of $5,737), so the exclusion is now
enforced in the shared demand engine every PO-generation path reads from.

Exception (2026-09-15): _BUY_COMPLETE_PREFIXES items (PN45/PN46/HK/TR02/
TR03/SP12) stay IN the buy-list even though BC flags them Prod. Order —
OPENDC is moving toward buying more finished items complete instead of
releasing a production order to build them in-house, so demand for those
should resolve to the complete part number rather than vanish waiting on
a production order that's never coming.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.purchasing_demand_service import PurchasingDemandService


def _so_line(item, qty, shipped=0, seq=10000):
    return {"lineType": "Item", "sequence": seq, "lineObjectNumber": item,
            "quantity": qty, "shippedQuantity": shipped, "description": f"desc {item}"}


def _so(number, lines, rdd="2026-09-15"):
    return {"number": number, "requestedDeliveryDate": rdd, "salesOrderLines": lines}


def test_manufactured_item_dropped_even_when_short(monkeypatch):
    """A truly manufactured item (no buy-complete equivalent, e.g. a custom
    weld-up with its own real BOM) still gets dropped — it needs a
    production order, we can't just buy it from a vendor."""
    import app.services.purchasing_demand_service as mod

    monkeypatch.setattr(
        mod.bc_client, "get_open_sales_orders_with_lines",
        lambda: [_so("SO-1", [_so_line("CUSTOM-WELD-01", 3), _so_line("SHORT-01", 5)])],
    )
    monkeypatch.setattr(mod.bc_client, "get_open_purchase_orders_with_lines", lambda top=100: [])
    monkeypatch.setattr(
        mod.bc_client, "get_items_by_numbers",
        lambda nums: {
            "CUSTOM-WELD-01": {"inventory": 0, "displayName": "custom weldment",
                                "unitCost": 269.89, "baseUnitOfMeasureCode": "EA", "type": "Inventory"},
            "SHORT-01": {"inventory": 0, "displayName": "widget",
                         "unitCost": 10.0, "baseUnitOfMeasureCode": "EA", "type": "Inventory"},
        },
    )
    monkeypatch.setattr(
        mod.bc_production_service, "get_replenishment_map",
        lambda: {"CUSTOM-WELD-01": "Prod. Order", "SHORT-01": "Purchase"},
    )
    monkeypatch.setattr(
        mod.bc_production_service, "_make_odata_request_all", lambda *a, **k: []
    )
    monkeypatch.setattr(mod.vendor_map_service, "load_map", lambda db: {})
    monkeypatch.setattr(mod.purchasing_intel_service, "last_received_by_item", lambda: {})
    monkeypatch.setattr(mod.purchasing_intel_service, "vendor_lead_times", lambda: {})

    result = PurchasingDemandService().compute_requirements(db=None, horizon_weeks=None)

    item_numbers = {r["item_no"] for r in result["items"]}
    assert "CUSTOM-WELD-01" not in item_numbers, "manufactured item leaked into the buy-list"
    assert "SHORT-01" in item_numbers
    assert result["manufactured_excluded"] == ["CUSTOM-WELD-01"]
    assert result["summary"]["manufactured_excluded"] == 1


def test_buy_complete_item_stays_in_list_despite_prod_order_flag(monkeypatch):
    """PN46/PN45/HK/TR02/TR03/SP12 are Prod. Order in BC but also sold
    complete by the vendor — Joey's 2026-09-15 shift toward buying finished
    items instead of releasing production orders means these should NOT be
    dropped; they should surface as normal purchase demand at their own
    part number."""
    import app.services.purchasing_demand_service as mod

    monkeypatch.setattr(
        mod.bc_client, "get_open_sales_orders_with_lines",
        lambda: [_so("SO-1", [_so_line("PN46-24405-2000", 1)])],
    )
    monkeypatch.setattr(mod.bc_client, "get_open_purchase_orders_with_lines", lambda top=100: [])
    monkeypatch.setattr(
        mod.bc_client, "get_items_by_numbers",
        lambda nums: {
            "PN46-24405-2000": {"inventory": 0, "displayName": "black panel DEC",
                                 "unitCost": 269.89, "baseUnitOfMeasureCode": "EA", "type": "Inventory"},
        },
    )
    monkeypatch.setattr(
        mod.bc_production_service, "get_replenishment_map",
        lambda: {"PN46-24405-2000": "Prod. Order"},
    )
    monkeypatch.setattr(
        mod.bc_production_service, "_make_odata_request_all", lambda *a, **k: []
    )
    monkeypatch.setattr(mod.vendor_map_service, "load_map", lambda db: {})
    monkeypatch.setattr(mod.purchasing_intel_service, "last_received_by_item", lambda: {})
    monkeypatch.setattr(mod.purchasing_intel_service, "vendor_lead_times", lambda: {})

    result = PurchasingDemandService().compute_requirements(db=None, horizon_weeks=None)

    item_numbers = {r["item_no"] for r in result["items"]}
    assert "PN46-24405-2000" in item_numbers, "buy-complete item was wrongly excluded"
    assert result["manufactured_excluded"] == []


def test_replenishment_map_failure_degrades_gracefully(monkeypatch):
    """If the ODataV4 Items page is down, don't crash the whole engine —
    just stop filtering manufactured items for this run (same posture as
    every other best-effort enrichment here)."""
    import app.services.purchasing_demand_service as mod

    monkeypatch.setattr(
        mod.bc_client, "get_open_sales_orders_with_lines",
        lambda: [_so("SO-1", [_so_line("SHORT-01", 5)])],
    )
    monkeypatch.setattr(mod.bc_client, "get_open_purchase_orders_with_lines", lambda top=100: [])
    monkeypatch.setattr(
        mod.bc_client, "get_items_by_numbers",
        lambda nums: {"SHORT-01": {"inventory": 0, "displayName": "widget",
                                    "unitCost": 10.0, "baseUnitOfMeasureCode": "EA", "type": "Inventory"}},
    )

    def _boom():
        raise RuntimeError("odata down")

    monkeypatch.setattr(mod.bc_production_service, "get_replenishment_map", _boom)
    monkeypatch.setattr(mod.bc_production_service, "_make_odata_request_all", lambda *a, **k: [])
    monkeypatch.setattr(mod.vendor_map_service, "load_map", lambda db: {})
    monkeypatch.setattr(mod.purchasing_intel_service, "last_received_by_item", lambda: {})
    monkeypatch.setattr(mod.purchasing_intel_service, "vendor_lead_times", lambda: {})

    result = PurchasingDemandService().compute_requirements(db=None, horizon_weeks=None)

    assert {r["item_no"] for r in result["items"]} == {"SHORT-01"}
    assert result["manufactured_excluded"] == []
