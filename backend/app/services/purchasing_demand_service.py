"""
Purchasing Demand Engine

Computes per-item net purchasing requirement by netting committed demand
against supply, straight from Business Central:

    net_need = outstanding_sales_demand
             + outstanding_production_component_demand   (Phase 4, when published)
             - on_hand
             - on_open_purchase_orders

Outstanding demand is taken from OPEN sales orders (quantity not yet shipped)
and, once the production web services are published, from released
production-order components. Supply nets out current stock and quantity
already on open purchase orders so we never double-buy.

This is allocation-driven (what is committed to real jobs), not a forecast
from historical velocity — OPENDC runs lean / buy-to-order, so on-hand is
typically zero and demand comes from live orders.
"""

import logging
from collections import defaultdict
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.integrations.bc.client import bc_client
from app.services.bc_production_service import bc_production_service, ODATA_ENDPOINTS
from app.services.vendor_map_service import vendor_map_service
from app.services.purchasing_intel_service import purchasing_intel_service

logger = logging.getLogger(__name__)

UNASSIGNED = "Unassigned"

# Item-typed lines that are charges, not purchasable stock — excluded from demand.
NON_STOCK_ITEMS = {"FREIGHT", "INSTALLATION", "DISCOUNT", "SHIPPING", "MISC", "LABOUR", "LABOR"}


class PurchasingDemandService:
    """Nets committed job demand against stock to produce a purchasing shortfall list."""

    def compute_requirements(self, db: Session, include_met: bool = False) -> Dict:
        """
        Build the full purchasing requirement picture.

        Args:
            db: DB session (for vendor resolution).
            include_met: if True, also return items whose demand is fully covered
                         (net_need <= 0). Default False — only shortfalls.

        Returns a dict with: generated_at, summary, items[], vendors[] (grouped),
        and production_included (whether prod-order demand was folded in).
        """
        # 1. Outstanding demand from open sales orders (committed to jobs).
        demand: Dict[str, float] = defaultdict(float)
        item_jobs: Dict[str, set] = defaultdict(set)
        try:
            for so in bc_client.get_open_sales_orders_with_lines(top=100):
                so_no = so.get("number") or "?"
                for ln in so.get("salesOrderLines", []):
                    if ln.get("lineType") != "Item":
                        continue
                    item = ln.get("lineObjectNumber")
                    if not item or item.upper() in NON_STOCK_ITEMS:
                        continue
                    outstanding = self._outstanding(ln, "shippedQuantity")
                    if outstanding <= 0:
                        continue
                    demand[item] += outstanding
                    item_jobs[item].add(so_no)
        except Exception as e:
            logger.error(f"[Purchasing] Failed to read open sales orders: {e}")

        # 2. Outstanding demand from production-order components (Phase 4).
        production_included = False
        prod_demand, prod_refs = self._production_component_demand()
        if prod_demand:
            production_included = True
            for item, qty in prod_demand.items():
                demand[item] += qty
                item_jobs[item].update(prod_refs.get(item, set()))

        # 3. Supply already on open purchase orders (avoid double-buying).
        on_order: Dict[str, float] = defaultdict(float)
        try:
            for po in bc_client.get_open_purchase_orders_with_lines(top=100):
                for ln in po.get("purchaseOrderLines", []):
                    if ln.get("lineType") != "Item":
                        continue
                    item = ln.get("lineObjectNumber")
                    if not item:
                        continue
                    on_order[item] += self._outstanding(ln, "receivedQuantity")
        except Exception as e:
            logger.error(f"[Purchasing] Failed to read open purchase orders: {e}")

        # 4. On-hand stock + item metadata.
        item_numbers = sorted(demand.keys())
        items_meta: Dict[str, dict] = {}
        if item_numbers:
            try:
                items_meta = bc_client.get_items_by_numbers(item_numbers)
            except Exception as e:
                logger.error(f"[Purchasing] Failed to fetch item stock/meta: {e}")

        # 5. Build per-item rows.
        vendor_map = vendor_map_service.load_map(db)
        # Purchasing intelligence (cost / last-purchase / lead time) — best-effort;
        # never let it break the core requirements computation.
        try:
            last_received = purchasing_intel_service.last_received_by_item()
            vendor_leads = purchasing_intel_service.vendor_lead_times()
        except Exception as e:
            logger.warning(f"[Purchasing] intel enrichment unavailable: {e}")
            last_received, vendor_leads = {}, {}
        rows: List[dict] = []
        for item in item_numbers:
            dmd = demand[item]
            meta = items_meta.get(item, {})
            if (meta.get("type") or "").lower() == "service":
                continue  # service charges aren't purchasable stock
            on_hand = float(meta.get("inventory") or 0)
            oo = on_order.get(item, 0.0)
            net_need = dmd - on_hand - oo
            if net_need <= 0 and not include_met:
                continue
            vinfo = vendor_map.get(item, {})
            vendor_no, vendor_name = vinfo.get("vendor_no"), vinfo.get("vendor_name")
            lr = last_received.get(item, {})
            lead = vendor_leads.get(vendor_no or "", {})
            rows.append({
                "item_no": item,
                "description": meta.get("displayName") or "",
                "demand": round(dmd, 2),
                "on_hand": round(on_hand, 2),
                "on_order": round(oo, 2),
                "net_need": round(net_need, 2),
                "unit_cost": float(meta.get("unitCost") or 0),
                "unit_of_measure": meta.get("baseUnitOfMeasureCode") or "EA",
                "vendor_no": vendor_no,
                "vendor_name": vendor_name or UNASSIGNED,
                "last_purchase_vendor": lr.get("vendor_name"),
                "last_purchase_date": lr.get("date"),
                "last_purchase_cost": lr.get("unit_cost"),
                "lead_time_days": lead.get("median_days"),
                "jobs": sorted(item_jobs[item]),
            })

        rows.sort(key=lambda r: r["net_need"], reverse=True)
        vendors = self._group_by_vendor(rows)

        shortfall_rows = [r for r in rows if r["net_need"] > 0]
        return {
            "generated_at": datetime.utcnow().isoformat(),
            "production_included": production_included,
            "summary": {
                "shortfall_items": len(shortfall_rows),
                "vendor_count": len(vendors),
                "unassigned_items": sum(1 for r in shortfall_rows if r["vendor_name"] == UNASSIGNED),
                "estimated_cost": round(sum(r["net_need"] * r["unit_cost"] for r in shortfall_rows), 2),
            },
            "items": rows,
            "vendors": vendors,
        }

    # ─── helpers ───────────────────────────────────────────────

    @staticmethod
    def _outstanding(line: dict, fulfilled_field: str) -> float:
        """Quantity on a line not yet shipped/received, floored at 0."""
        qty = float(line.get("quantity") or 0)
        done = float(line.get(fulfilled_field) or 0)
        return max(0.0, qty - done)

    @staticmethod
    def _group_by_vendor(rows: List[dict]) -> List[dict]:
        """Group shortfall rows by vendor for the per-vendor purchasing view."""
        groups: Dict[str, dict] = {}
        for r in rows:
            if r["net_need"] <= 0:
                continue
            key = r["vendor_name"] or UNASSIGNED
            g = groups.setdefault(key, {
                "vendor_name": key,
                "vendor_no": r["vendor_no"],
                "item_count": 0,
                "estimated_cost": 0.0,
                "items": [],
            })
            g["item_count"] += 1
            g["estimated_cost"] = round(g["estimated_cost"] + r["net_need"] * r["unit_cost"], 2)
            g["items"].append(r)
        # Unassigned last, otherwise by spend desc.
        return sorted(
            groups.values(),
            key=lambda g: (g["vendor_name"] == UNASSIGNED, -g["estimated_cost"]),
        )

    def _production_component_demand(self) -> Tuple[Dict[str, float], Dict[str, set]]:
        """
        Outstanding raw-material demand from released production-order components.

        Returns ({item_no: qty}, {item_no: {prod_order_no, ...}}). Returns empty
        dicts when the BC production web services are not published (404) — the
        engine then runs on sales-order demand alone. Field mapping is finalized
        in Phase 4 once ReleasedProductionOrders/ProdOrderComponents are live.
        """
        demand: Dict[str, float] = defaultdict(float)
        refs: Dict[str, set] = defaultdict(set)
        try:
            # Released components only (committed jobs) — exclude Finished/Planned.
            # Paged via $skip: this web service silently caps at $top with no
            # nextLink, and the table is ~9.5k rows, so a single page truncates.
            components = bc_production_service._make_odata_request_all(
                ODATA_ENDPOINTS["components"],
                query_params={"$filter": "Status eq 'Released'"},
            )
            if not components:
                return {}, {}
            for c in components:
                item = c.get("Item_No")
                if not item:
                    continue
                # Prefer remaining (still-to-consume) qty; fall back to expected.
                remaining = (
                    c.get("Remaining_Quantity")
                    if c.get("Remaining_Quantity") is not None
                    else c.get("Expected_Quantity", c.get("Quantity", 0))
                )
                qty = float(remaining or 0)
                if qty <= 0:
                    continue
                demand[item] += qty
                refs[item].add(c.get("Prod_Order_No") or "?")
        except Exception as e:
            logger.warning(f"[Purchasing] Production component demand unavailable: {e}")
            return {}, {}
        return demand, refs


purchasing_demand_service = PurchasingDemandService()
