"""
Pricing Service
BC-driven pricing — Business Central is the single source of truth.

Lookup order (matches Upwardor portal PriceController.js):
  1. SalesPriceLists where Product_No=PN, Assign_to_No=PRICE_GROUP, UoM=UOM
     (the customer's tier-specific list price)
  2. SalesPriceLists where Product_No=PN, UoM=UOM
     (the "all customer" / default list price)
  3. ItemMasterList Unit_Price (item card fallback)

There is NO app-side margin math, cost adjustment, or door-type rule.
Tier-to-price mapping lives entirely in BC's published price lists.
"""

import logging
import time
from typing import Optional, Dict, List, Tuple

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# ============================================================================
# Module-level caches (per-process, TTL-bounded)
# ============================================================================

_price_cache: Dict[Tuple[str, str, str], Optional[float]] = {}
_uom_cache: Dict[str, str] = {}
_item_card_price_cache: Dict[str, Optional[float]] = {}
_cache_expiry: float = 0.0
_CACHE_TTL = 3600  # 1 hour

# Sentinels for the price cache key
_DEFAULT = "__DEFAULT__"


def _norm_group(g: Optional[str]) -> str:
    return (g or "").upper().strip()


def _norm_uom(u: Optional[str]) -> str:
    return (u or "").upper().strip()


def _expired() -> bool:
    return time.time() >= _cache_expiry


def _refresh_expiry() -> None:
    global _cache_expiry
    _cache_expiry = time.time() + _CACHE_TTL


def clear_pricing_cache() -> None:
    """Force-clear all pricing caches (useful after BC price list edits)."""
    global _price_cache, _uom_cache, _item_card_price_cache, _cache_expiry
    _price_cache = {}
    _uom_cache = {}
    _item_card_price_cache = {}
    _cache_expiry = 0.0


# ============================================================================
# Cache-warming helpers
# ============================================================================

def warm_sales_price_cache(
    part_numbers: List[str],
    bc_price_group: Optional[str] = None,
) -> None:
    """Pre-populate the price + UoM caches for a batch of parts.

    Loads ItemMasterList records (one batched call) so each part's Base UoM
    and item-card Unit_Price is cached. SalesPriceLists lookups happen
    lazily on first hit, but having the UoM up-front avoids a per-line
    item card round-trip later.
    """
    if not part_numbers:
        return
    if _expired():
        clear_pricing_cache()

    from app.integrations.bc.client import bc_client
    unique = list({pn for pn in part_numbers if pn})

    try:
        items = bc_client.get_item_masters(unique)
    except Exception as e:
        logger.warning(f"warm_sales_price_cache: ItemMasterList batch failed: {e}")
        items = {}

    for pn, row in items.items():
        uom = row.get("Base_Unit_of_Measure") or ""
        _uom_cache[pn] = _norm_uom(uom)
        unit_price = row.get("Unit_Price")
        try:
            _item_card_price_cache[pn] = float(unit_price) if unit_price else None
        except (TypeError, ValueError):
            _item_card_price_cache[pn] = None

    missing = [pn for pn in unique if pn not in items]
    logger.info(
        f"warm_sales_price_cache: loaded {len(items)} items, "
        f"{len(missing)} not found in ItemMasterList"
        + (f" (group={bc_price_group})" if bc_price_group else "")
    )
    if missing:
        logger.warning(f"ItemMasterList missing: {missing}")
    _refresh_expiry()


# Backwards-compat alias — old call sites import warm_bc_cost_cache
warm_bc_cost_cache = warm_sales_price_cache


# ============================================================================
# UoM + item-card lookup helpers (single-part fallback)
# ============================================================================

def _get_uom(part_number: str) -> Optional[str]:
    """Resolve a part's Base UoM from cache or via a single ItemMasterList call."""
    if part_number in _uom_cache:
        return _uom_cache[part_number] or None
    try:
        from app.integrations.bc.client import bc_client
        item = bc_client.get_item_master(part_number)
        if item:
            uom = _norm_uom(item.get("Base_Unit_of_Measure"))
            _uom_cache[part_number] = uom
            try:
                p = item.get("Unit_Price")
                _item_card_price_cache[part_number] = float(p) if p else None
            except (TypeError, ValueError):
                _item_card_price_cache[part_number] = None
            return uom or None
    except Exception as e:
        logger.warning(f"_get_uom: ItemMasterList lookup failed for {part_number}: {e}")
    return None


def _get_item_card_price(part_number: str) -> Optional[float]:
    """Resolve item-card Unit_Price from cache or via a single call."""
    if part_number in _item_card_price_cache:
        return _item_card_price_cache[part_number]
    # Trigger UoM lookup which also populates item-card price cache
    _get_uom(part_number)
    return _item_card_price_cache.get(part_number)


# ============================================================================
# Core pricing function — 3-step lookup, no math
# ============================================================================

def calculate_selling_price(
    part_number: str,
    bc_price_group: Optional[str] = None,
    db: Optional[Session] = None,  # unused; kept for API compatibility
) -> Optional[float]:
    """Look up the unit price for a part from BC.

    Lookup chain (matches Upwardor portal):
      1. SalesPriceLists with Assign_to_No = customer's BC price group
      2. SalesPriceLists with no group filter (default list price)
      3. ItemMasterList Unit_Price (item card)

    Returns the BC-defined unit price rounded to 2 decimals, or None if no
    price exists anywhere — in which case the caller should treat the line
    as needing manual pricing (e.g. CONTACT REP FOR PRICING).
    """
    if not part_number:
        return None

    if _expired():
        clear_pricing_cache()

    from app.integrations.bc.client import bc_client

    uom = _get_uom(part_number)
    if not uom:
        # Without a UoM we can't filter SalesPriceLists; skip to item card.
        card_price = _get_item_card_price(part_number)
        if card_price and card_price > 0:
            return round(card_price, 2)
        logger.warning(
            f"PRICING [{part_number}]: no UoM resolved and no item-card price — "
            f"item likely missing from BC"
        )
        return None

    group = _norm_group(bc_price_group)

    # Tier 1 — customer-group-specific price
    if group:
        key = (part_number, group, uom)
        if key in _price_cache:
            cached = _price_cache[key]
            if cached is not None:
                return round(cached, 2)
        else:
            try:
                row = bc_client.get_sales_price(part_number, group, uom)
                price = _extract_unit_price(row)
                _price_cache[key] = price
                if price is not None:
                    return round(price, 2)
            except Exception as e:
                logger.warning(
                    f"PRICING [{part_number}/{group}]: SalesPriceLists lookup failed: {e}"
                )

    # Tier 2 — default list price (no group)
    default_key = (part_number, _DEFAULT, uom)
    if default_key in _price_cache:
        cached = _price_cache[default_key]
        if cached is not None:
            return round(cached, 2)
    else:
        try:
            row = bc_client.get_default_sales_price(part_number, uom)
            price = _extract_unit_price(row)
            _price_cache[default_key] = price
            if price is not None:
                return round(price, 2)
        except Exception as e:
            logger.warning(
                f"PRICING [{part_number}/default]: SalesPriceLists lookup failed: {e}"
            )

    # Tier 3 — item card Unit_Price
    card_price = _get_item_card_price(part_number)
    if card_price and card_price > 0:
        return round(card_price, 2)

    logger.info(
        f"PRICING [{part_number}]: no price found "
        f"(group={group or 'n/a'}, uom={uom}) — caller should flag for review"
    )
    return None


def _extract_unit_price(row: Optional[Dict]) -> Optional[float]:
    if not row:
        return None
    val = row.get("Unit_Price")
    if val in (None, "", 0):
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None
