"""
Pricing Service
Margin-based pricing tier system for door quotes.

Formula: selling_price = (unitCost * (1 + cost_adjustment%/100)) / (1 - margin%/100)

Tiers (Residential): Gold 30%, Silver 35%, Bronze 40%, Retail 50%
Tiers (Commercial):  Gold 30%, Silver 33%, Bronze 36%, Retail 42%
"""

import logging
import time
from typing import Optional, Tuple, Dict, Any, List

from sqlalchemy.orm import Session

from app.db.models import AppSettings
from app.services.bc_part_number_mapper import get_bc_mapper

logger = logging.getLogger(__name__)

# ============================================================================
# Setting keys in AppSettings
# ============================================================================
TIER_MARGINS_KEY = "pricing_tier_margins"
COST_ADJUSTMENTS_KEY = "pricing_cost_adjustments"
BC_GROUP_MAPPING_KEY = "bc_group_tier_mapping"
PREFIX_MARGINS_KEY = "pricing_prefix_margins"

VALID_TIERS = {"gold", "silver", "bronze", "retail"}

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
            "retail": 42,
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


def _load_prefix_margins(db: Session) -> dict:
    """Load part-number prefix margin overrides from AppSettings."""
    setting = db.query(AppSettings).filter(
        AppSettings.setting_key == PREFIX_MARGINS_KEY
    ).first()
    if setting and setting.setting_value:
        return setting.setting_value
    return {}


def _load_bc_group_mapping(db: Session) -> dict:
    """Load BC price group → portal tier mapping from AppSettings."""
    setting = db.query(AppSettings).filter(
        AppSettings.setting_key == BC_GROUP_MAPPING_KEY
    ).first()
    if setting and setting.setting_value:
        return setting.setting_value
    return {}


def resolve_tier_from_bc_group(bc_price_group: Optional[str], db: Session) -> Optional[str]:
    """
    Look up which portal tier a BC price group maps to.
    Returns the tier string (e.g. 'gold') or None if no mapping exists.
    """
    if not bc_price_group:
        return None
    mapping = _load_bc_group_mapping(db)
    tier = mapping.get(bc_price_group.upper().strip())
    return tier if tier in VALID_TIERS else None


# ============================================================================
# Live BC cost cache
# ============================================================================

_bc_cost_cache: Dict[str, dict] = {}
_cache_expiry: float = 0.0
_CACHE_TTL = 3600  # 1 hour


def warm_bc_cost_cache(part_numbers: List[str]) -> None:
    """
    Batch-fetch item costs from live BC and populate the module cache.
    Call once before a pricing loop to avoid per-line API calls.
    """
    global _bc_cost_cache, _cache_expiry

    if not part_numbers:
        return

    # Deduplicate
    unique_pns = list(set(part_numbers))

    try:
        from app.integrations.bc.client import bc_client
        items = bc_client.get_items_by_numbers(unique_pns)
        _bc_cost_cache.update(items)
        _cache_expiry = time.time() + _CACHE_TTL
        logger.info(f"Warmed BC cost cache with {len(items)} items (requested {len(unique_pns)})")
    except Exception as e:
        logger.warning(f"Failed to warm BC cost cache: {e}")


def _get_live_item(part_number: str) -> Optional[dict]:
    """
    Return item data (unitCost, generalProductPostingGroupCode) from the
    live BC cache.  On cache miss, makes a single BC API call.
    Falls back to the static bc_items mapper if BC API fails entirely.
    """
    global _bc_cost_cache, _cache_expiry

    # Check cache (still valid?)
    if time.time() < _cache_expiry and part_number in _bc_cost_cache:
        return _bc_cost_cache[part_number]

    # Cache miss — try single-item fetch from live BC
    try:
        from app.integrations.bc.client import bc_client
        items = bc_client.get_items_by_numbers([part_number])
        if part_number in items:
            _bc_cost_cache[part_number] = items[part_number]
            return items[part_number]
    except Exception as e:
        logger.warning(f"Live BC lookup failed for {part_number}: {e}")

    # Final fallback: static mapper
    mapper = get_bc_mapper()
    return mapper.bc_items.get(part_number)


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

    # Handle missing/unknown/legacy tier values — always fall back to retail
    valid_tiers = set(type_margins.keys())
    if tier not in valid_tiers:
        tier = "retail"

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
    item = _get_live_item(part_number)
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

    # Check for part-number prefix override (longest prefix wins)
    prefix_overrides = _load_prefix_margins(db)
    if prefix_overrides:
        pn_upper = part_number.upper()
        best_prefix = ""
        for prefix in prefix_overrides:
            if pn_upper.startswith(prefix.upper()) and len(prefix) > len(best_prefix):
                best_prefix = prefix
        if best_prefix:
            override_margin = prefix_overrides[best_prefix].get("margin")
            if override_margin is not None:
                margin_pct = float(override_margin)

    # Apply formula: selling_price = (unitCost * (1 + adj%/100)) / (1 - margin%/100)
    adjusted_cost = unit_cost * (1 + cost_adj_pct / 100)
    if margin_pct >= 100:
        margin_pct = 99  # safety cap
    selling_price = adjusted_cost / (1 - margin_pct / 100)

    return round(selling_price, 2)
