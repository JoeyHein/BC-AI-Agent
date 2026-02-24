"""
Pricing Service
Margin-based pricing tier system for door quotes.

Formula: selling_price = (unitCost * (1 + cost_adjustment%/100)) / (1 - margin%/100)

Tiers (Residential): Gold 30%, Silver 35%, Bronze 40%, Retail 50%
Tiers (Commercial):  Gold 30%, Silver 33%, Bronze 36%
"""

import logging
from typing import Optional, Tuple, Dict, Any

from sqlalchemy.orm import Session

from app.db.models import AppSettings
from app.services.bc_part_number_mapper import get_bc_mapper

logger = logging.getLogger(__name__)

# ============================================================================
# Setting keys in AppSettings
# ============================================================================
TIER_MARGINS_KEY = "pricing_tier_margins"
COST_ADJUSTMENTS_KEY = "pricing_cost_adjustments"

# ============================================================================
# Hardcoded defaults (used when no AppSettings saved yet)
# ============================================================================

def get_default_tier_margins() -> dict:
    """Default margin percentages by door_type and tier."""
    return {
        "residential": {
            "gold": 30,
            "silver": 35,
            "bronze": 40,
            "retail": 50,
        },
        "commercial": {
            "gold": 30,
            "silver": 33,
            "bronze": 36,
        },
    }


# Friendly labels for BC posting group codes
POSTING_GROUP_LABELS = {
    "RESI": "Panels (Residential)",
    "COMM": "Panels (Commercial)",
    "SPRI": "Springs",
    "HARD": "Hardware",
    "TRAC": "Tracks",
    "OPER": "Operators",
    "GLAZ": "Glazing / Windows",
    "ALUM": "Aluminum",
    "PLAS": "Plastics / Weather Stripping",
    "ACS": "Accessories",
    "GO": "Garage Openers",
    "MISC": "Miscellaneous",
    "CONS": "Consumables",
    "UPCW": "UPCW",
    "SAMP": "Samples",
    "LABR": "Labour",
    "FREIGHT": "Freight",
    "TARIFF": "Tariff",
}


def get_default_cost_adjustments() -> dict:
    """Default cost adjustments (all zeros), keyed by BC posting group codes."""
    mapper = get_bc_mapper()
    groups = set()
    for item in mapper.bc_items.values():
        code = item.get("generalProductPostingGroupCode", "")
        if code:
            groups.add(code)

    # If no items loaded, use known codes
    if not groups:
        groups = set(POSTING_GROUP_LABELS.keys())

    return {code: {"adjustment": 0, "note": ""} for code in sorted(groups)}


# ============================================================================
# Settings loaders
# ============================================================================

def _load_tier_margins(db: Session) -> dict:
    """Load tier margins from AppSettings or return defaults."""
    setting = db.query(AppSettings).filter(
        AppSettings.setting_key == TIER_MARGINS_KEY
    ).first()
    if setting and setting.setting_value:
        return setting.setting_value
    return get_default_tier_margins()


def _load_cost_adjustments(db: Session) -> dict:
    """Load cost adjustments from AppSettings or return defaults."""
    setting = db.query(AppSettings).filter(
        AppSettings.setting_key == COST_ADJUSTMENTS_KEY
    ).first()
    if setting and setting.setting_value:
        return setting.setting_value
    return get_default_cost_adjustments()


# ============================================================================
# Core pricing functions
# ============================================================================

def resolve_tier(customer_tier: Optional[str], door_type: str, db: Session) -> Tuple[str, float]:
    """
    Resolve what tier and margin % to use for a customer + door type.

    Returns (tier_name, margin_pct).
    """
    margins = _load_tier_margins(db)
    door_type_lower = (door_type or "residential").lower()

    # Normalize door type
    if door_type_lower not in ("residential", "commercial"):
        door_type_lower = "residential"

    type_margins = margins.get(door_type_lower, {})
    tier = (customer_tier or "").lower().strip()

    # Handle legacy/unknown tier values
    valid_tiers = set(type_margins.keys())
    if tier not in valid_tiers:
        # Default: retail for residential, bronze for commercial
        tier = "retail" if door_type_lower == "residential" else "bronze"

    # "retail" tier on commercial → fall back to bronze
    if tier == "retail" and door_type_lower == "commercial":
        tier = "bronze"

    margin_pct = type_margins.get(tier, 40)  # safe fallback
    return tier, margin_pct


def calculate_selling_price(
    part_number: str,
    door_type: str,
    tier: str,
    db: Session,
) -> Optional[float]:
    """
    Calculate margin-based selling price for a part number.

    Returns rounded selling price, or None if unitCost is 0/missing
    (let BC use its default pricing in that case).
    """
    mapper = get_bc_mapper()
    item = mapper.bc_items.get(part_number)
    if not item:
        return None

    unit_cost = item.get("unitCost", 0)
    if not unit_cost or unit_cost <= 0:
        return None

    # Get posting group for cost adjustment lookup
    posting_group = item.get("generalProductPostingGroupCode", "")

    # Load cost adjustments
    adjustments = _load_cost_adjustments(db)
    adj_entry = adjustments.get(posting_group, {})
    cost_adj_pct = adj_entry.get("adjustment", 0) if isinstance(adj_entry, dict) else 0

    # Resolve margin
    _tier_name, margin_pct = resolve_tier(tier, door_type, db)

    # Apply formula: selling_price = (unitCost * (1 + adj%/100)) / (1 - margin%/100)
    adjusted_cost = unit_cost * (1 + cost_adj_pct / 100)
    if margin_pct >= 100:
        margin_pct = 99  # safety cap
    selling_price = adjusted_cost / (1 - margin_pct / 100)

    return round(selling_price, 2)
