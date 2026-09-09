"""compute_requirements must never buy an item BC flags as manufactured
in-house (Replenishment_System='Prod. Order') — it needs a production
order, not a vendor PO. Was a "~2 items, revisit if it grows" footnote;
PO-000962 (2026-09-08) showed 13 of 40 items on one hand-built PO were
manufactured panels/kits ($4,585 of $5,737), so the exclusion is now
enforced in the shared demand engine every PO-generation path reads from.
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
    import app.services.purchasing_demand_service as mod

    monkeypatch.setattr(
        mod.bc_client, "get_open_sales_orders_with_lines",
        lambda: [_so("SO-1", [_so_line("PN46-24405-1800", 3), _so_line("SHORT-01", 5)])],
    )
    monkeypatch.setattr(mod.bc_client, "get_open_purchase_orders_with_lines", lambda top=100: [])
    monkeypatch.setattr(
        mod.bc_client, "get_items_by_numbers",
        lambda nums: {
            "PN46-24405-1800": {"inventory": 0, "displayName": "black panel",
                                 "unitCost": 269.89, "baseUnitOfMeasureCode": "EA", "type": "Inventory"},
            "SHORT-01": {"inventory": 0, "displayName": "widget",
                         "unitCost": 10.0, "baseUnitOfMeasureCode": "EA", "type": "Inventory"},
        },
    )
    monkeypatch.setattr(
        mod.bc_production_service, "get_replenishment_map",
        lambda: {"PN46-24405-1800": "Prod. Order", "SHORT-01": "Purchase"},
    )
    monkeypatch.setattr(
        mod.bc_production_service, "_make_odata_request_all", lambda *a, **k: []
    )
    monkeypatch.setattr(mod.vendor_map_service, "load_map", lambda db: {})
    monkeypatch.setattr(mod.purchasing_intel_service, "last_received_by_item", lambda: {})
    monkeypatch.setattr(mod.purchasing_intel_service, "vendor_lead_times", lambda: {})

    result = PurchasingDemandService().compute_requirements(db=None, horizon_weeks=None)

    item_numbers = {r["item_no"] for r in result["items"]}
    assert "PN46-24405-1800" not in item_numbers, "manufactured item leaked into the buy-list"
    assert "SHORT-01" in item_numbers
    assert result["manufactured_excluded"] == ["PN46-24405-1800"]
    assert result["summary"]["manufactured_excluded"] == 1


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
