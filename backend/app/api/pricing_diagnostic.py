"""
Pricing Diagnostic API

Read-only endpoint that compares the legacy margin-on-cost price (current
production behavior) against the BC Sales Price hierarchy result for the
same line. Used by finance to validate cutover before any customer is
flipped to BC-native pricing.

Hierarchy (BC convention):
    1. Customer-specific           (source_type=1, source_no=customer_no)
    2. Customer Price Group price  (source_type=2, source_no=group_code)
    3. All Customers price         (source_type=0)
    4. Item.unitPrice fallback     (item card)

The endpoint is read-only and admin-protected. It does not write to BC.
"""

import logging
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.auth import require_admin
from app.db.database import get_db
from app.db.models import BCCustomer, User
from app.integrations.bc.client import BusinessCentralClient
from app.services.pricing_service import (
    calculate_selling_price,
    resolve_tier,
    warm_bc_cost_cache,
    _get_live_item,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/pricing-diagnostic", tags=["pricing-diagnostic"])


# ============================================================================
# Request/response models
# ============================================================================

class DiagnosticLine(BaseModel):
    part_number: str
    qty: float = 1.0
    door_type: str = "residential"  # residential / commercial / aluminium / glazing


class DiagnosticRequest(BaseModel):
    customer_no: str  # BC customer number (e.g. "C00100"), not the GUID
    customer_price_group: Optional[str] = None  # e.g. "GOLD" — falls through to All Customers if blank
    tier: Optional[str] = None  # portal tier override; if None, resolved from BCCustomer
    bc_customer_id: Optional[str] = None  # GUID — used to look up tier from local cache
    as_of_date: Optional[str] = None  # YYYY-MM-DD; defaults to today
    lines: List[DiagnosticLine]


# ============================================================================
# Hierarchy resolution
# ============================================================================

def _first_price_from_entries(entries: list) -> Optional[float]:
    """
    Pick the best-matching price from a SalesPriceLists result set.

    All returned rows already match (item, source, qty, active-date) per the
    OData filter. When multiple match, prefer:
      1. Highest Minimum_Quantity that's still <= requested qty (best qty break)
      2. Most recent Starting_Date as tiebreaker
    """
    if not entries:
        return None
    sorted_entries = sorted(
        entries,
        key=lambda e: (
            e.get("Minimum_Quantity") or 0,
            e.get("Starting_Date") or "",
        ),
        reverse=True,
    )
    return sorted_entries[0].get("Unit_Price")


def _resolve_bc_hierarchy(
    bc_client: BusinessCentralClient,
    item_no: str,
    customer_no: str,
    customer_price_group: Optional[str],
    qty: float,
    as_of_date: str,
    item_unit_price_fallback: Optional[float],
) -> dict:
    """
    Walk the BC Sales Price hierarchy for a single line.

    Returns dict with each level's outcome plus the resolved price and the
    name of the level that won.
    """
    levels = []

    # 1. Customer-specific
    cust_result = bc_client.get_sales_price_lines(
        item_no=item_no, source_type=1, source_no=customer_no, qty=qty, as_of_date=as_of_date
    )
    cust_price = _first_price_from_entries(cust_result.get("entries", []))
    levels.append({
        "level": "customer",
        "source_no": customer_no,
        "price": cust_price,
        "matched": cust_price is not None,
        "available": cust_result.get("available"),
        "error": cust_result.get("error"),
    })

    # 2. Customer Price Group
    group_price = None
    group_result_meta = {"available": None, "error": "skipped — no group provided"}
    if customer_price_group:
        group_result = bc_client.get_sales_price_lines(
            item_no=item_no, source_type=2, source_no=customer_price_group,
            qty=qty, as_of_date=as_of_date,
        )
        group_price = _first_price_from_entries(group_result.get("entries", []))
        group_result_meta = {
            "available": group_result.get("available"),
            "error": group_result.get("error"),
        }
    levels.append({
        "level": "customer_price_group",
        "source_no": customer_price_group,
        "price": group_price,
        "matched": group_price is not None,
        **group_result_meta,
    })

    # 3. All Customers
    all_result = bc_client.get_sales_price_lines(
        item_no=item_no, source_type=0, source_no="", qty=qty, as_of_date=as_of_date
    )
    all_price = _first_price_from_entries(all_result.get("entries", []))
    levels.append({
        "level": "all_customers",
        "source_no": None,
        "price": all_price,
        "matched": all_price is not None,
        "available": all_result.get("available"),
        "error": all_result.get("error"),
    })

    # 4. Item.unitPrice fallback
    levels.append({
        "level": "item_unit_price",
        "source_no": None,
        "price": item_unit_price_fallback,
        "matched": item_unit_price_fallback is not None and item_unit_price_fallback > 0,
        "available": True,
        "error": None,
    })

    # Pick the first level that matched
    resolved_level = None
    resolved_price = None
    for lvl in levels:
        if lvl["matched"]:
            resolved_level = lvl["level"]
            resolved_price = lvl["price"]
            break

    return {
        "levels": levels,
        "resolved_level": resolved_level,
        "resolved_price": resolved_price,
    }


# ============================================================================
# Endpoints
# ============================================================================

@router.get("/probe")
async def probe_bc_sales_prices(
    _admin: User = Depends(require_admin),
):
    """
    Quick connectivity probe. Hits BC OData V4 with a no-op Sales Price query
    and reports whether the entity is reachable so we know if the tenant has
    the Price List Lines / Sales Price page exposed.
    """
    bc = BusinessCentralClient()
    # Ask for prices on a definitely-nonexistent item — we just want to see
    # whether the entity itself responds with 200 (empty list) vs. 404.
    result = bc.get_sales_price_lines(
        item_no="__PROBE_NONEXISTENT__",
        source_type=0,
        qty=1,
    )
    return {
        "success": True,
        "data": {
            "entity_reachable": result.get("available"),
            "entity_used": result.get("entity"),
            "queried_url": result.get("queried_url"),
            "error": result.get("error"),
            "next_steps": (
                "Sales Prices entity is reachable — the diagnostic endpoint will return real data."
                if result.get("available")
                else "Expose Price_List_Lines (or SalesPrice) page as a web service in BC, "
                     "then re-run this probe. Until then, the diagnostic will only show legacy prices."
            ),
        },
    }


@router.post("")
async def run_pricing_diagnostic(
    request: DiagnosticRequest,
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """
    Compare legacy margin-on-cost pricing against BC Sales Price hierarchy
    for the supplied lines. Read-only — does not write to BC or the portal DB.

    Use this to validate the proposed BC-native pricing model before flipping
    any customer over. GNB Manitoba and other margin-on-cost holdouts will
    continue to ignore this hierarchy.
    """
    if not request.lines:
        raise HTTPException(status_code=400, detail="lines is required")

    as_of_date = request.as_of_date or datetime.utcnow().strftime("%Y-%m-%d")

    # Resolve customer tier — explicit override > local BCCustomer cache > "retail"
    tier = (request.tier or "").strip().lower()
    bc_customer_record = None
    if request.bc_customer_id:
        bc_customer_record = (
            db.query(BCCustomer)
            .filter(BCCustomer.bc_customer_id == request.bc_customer_id)
            .first()
        )
    if not tier and bc_customer_record:
        tier = (bc_customer_record.pricing_tier or "retail").lower()
    if not tier:
        tier = "retail"

    # Resolve customer_price_group with strict priority:
    #   1. Explicit override on the request
    #   2. Live OData V4 lookup against BC CustomerList (authoritative)
    #   3. Local BCCustomer.bc_price_group (cached, may be stale)
    bc = BusinessCentralClient()
    price_group = request.customer_price_group
    price_group_source = "request_override" if price_group else None
    if not price_group:
        live_group = bc.get_customer_price_group(request.customer_no)
        if live_group:
            price_group = live_group
            price_group_source = "bc_live"
    if not price_group and bc_customer_record:
        price_group = bc_customer_record.bc_price_group
        price_group_source = "local_cache_stale" if price_group else None

    # Warm cost cache for all lines in one BC call
    part_numbers = [ln.part_number for ln in request.lines]
    warm_bc_cost_cache(part_numbers)

    line_results = []
    legacy_total = 0.0
    bc_total = 0.0
    bc_total_available = True

    for ln in request.lines:
        item = _get_live_item(ln.part_number) or {}
        unit_cost = item.get("unitCost")
        unit_price_fallback = item.get("unitPrice")
        posting_group = item.get("generalProductPostingGroupCode")

        # Legacy price (current production behavior)
        legacy_price = calculate_selling_price(
            part_number=ln.part_number,
            door_type=ln.door_type,
            tier=tier,
            db=db,
        )
        _tier_used, margin_pct = resolve_tier(tier, ln.door_type, db)

        # BC hierarchy
        hierarchy = _resolve_bc_hierarchy(
            bc_client=bc,
            item_no=ln.part_number,
            customer_no=request.customer_no,
            customer_price_group=price_group,
            qty=ln.qty,
            as_of_date=as_of_date,
            item_unit_price_fallback=unit_price_fallback,
        )
        bc_price = hierarchy["resolved_price"]

        # Cost analysis (kept alive for GNB Manitoba + every quote regardless of pricing path)
        legacy_margin_dollars = (legacy_price - unit_cost) if (legacy_price and unit_cost) else None
        bc_margin_dollars = (bc_price - unit_cost) if (bc_price and unit_cost) else None
        bc_margin_pct = (
            round(bc_margin_dollars / bc_price * 100, 2)
            if (bc_margin_dollars is not None and bc_price)
            else None
        )

        if legacy_price:
            legacy_total += legacy_price * ln.qty
        if bc_price is not None:
            bc_total += bc_price * ln.qty
        else:
            bc_total_available = False

        line_results.append({
            "part_number": ln.part_number,
            "qty": ln.qty,
            "door_type": ln.door_type,
            "posting_group": posting_group,
            "cost_analysis": {
                "unit_cost": unit_cost,
                "legacy_margin_dollars": legacy_margin_dollars,
                "legacy_margin_pct_applied": margin_pct,
                "bc_margin_dollars": bc_margin_dollars,
                "bc_margin_pct_realized": bc_margin_pct,
            },
            "legacy": {
                "price": legacy_price,
                "tier": tier,
                "margin_pct": margin_pct,
                "formula": "(unitCost × (1 + adj%)) / (1 - margin%)",
            },
            "bc_hierarchy": hierarchy,
            "delta_dollars": (
                round((bc_price - legacy_price) * ln.qty, 2)
                if (legacy_price is not None and bc_price is not None)
                else None
            ),
        })

    return {
        "success": True,
        "data": {
            "customer": {
                "customer_no": request.customer_no,
                "bc_customer_id": request.bc_customer_id,
                "tier_used": tier,
                "price_group_used": price_group,
                "price_group_source": price_group_source,
            },
            "as_of_date": as_of_date,
            "lines": line_results,
            "summary": {
                "legacy_total": round(legacy_total, 2),
                "bc_total": round(bc_total, 2) if bc_total_available else None,
                "bc_total_available": bc_total_available,
                "delta_dollars": (
                    round(bc_total - legacy_total, 2) if bc_total_available else None
                ),
                "delta_pct": (
                    round((bc_total - legacy_total) / legacy_total * 100, 2)
                    if (bc_total_available and legacy_total)
                    else None
                ),
            },
            "notes": [
                "Read-only. Does not write to BC.",
                "Legacy column reflects current production pricing (margin-on-cost).",
                "BC hierarchy column reflects what BC Sales Prices would resolve to today.",
                "Cost analysis is kept alive for every quote regardless of which pricing path is chosen.",
            ],
        },
    }
