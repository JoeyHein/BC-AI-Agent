"""
External pricing resolver (SQB-04).

Wraps BC's SalesPriceLists query with a small in-memory cache so the
live-quote UI can re-fetch on every keystroke without hammering BC.

Resolution order per (account_code, sku, qty):
    1. source_type=1 (Customer-specific) keyed by `bc_customer.bc_price_group`
       Wait — source_type=1 is Customer; group is source_type=2. Real order:
    1. source_type=1 (Customer)              — keyed by account_code itself
    2. source_type=2 (Customer Price Group)  — keyed by bc_customer.bc_price_group
    3. source_type=0 (All Customers)
    4. fall back to item.unitPrice (rare; most items have it set to 0)

unit_cost comes from the BC item record's `unitCost` field (always
populated even when SalesPriceLists has no entry).

The resolver is intentionally narrower than the legacy
`pricing_service.calculate_selling_price` — that function applies the
old margin engine which is no longer in the live path (see
project_pricing_flow memory). For the external API, BC's
SalesPriceLists IS the price; Service.AI layers its own margin on top.

Cache:
    * In-memory dict keyed by (account_code, sku, qty), 60 s TTL.
    * No Redis dependency for v1 — single-process. A Redis swap is a
      drop-in: replace `_PriceCache` with a Redis-backed equivalent
      that exposes the same `get` / `set` shape.
    * Tests inject a stub cache or a 0 s TTL via the optional
      `cache_ttl_seconds=0` constructor param.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from threading import Lock
from typing import Any, Dict, Optional, Tuple

from sqlalchemy.orm import Session

from app.db.models import BCCustomer
from app.integrations.bc.client import bc_client

logger = logging.getLogger(__name__)

DEFAULT_CACHE_TTL_SECONDS = 60


@dataclass
class ResolvedPrice:
    sku: str
    quantity: int
    unit_price_cents: int
    unit_cost_cents: int
    line_total_cents: int
    item_category: Optional[str]
    description: str
    currency: str  # 'CAD' / 'USD'
    """Whichever SalesPriceLists tier the price was sourced from."""
    price_source: str  # 'customer' | 'group' | 'all_customers' | 'item_default'


CacheKey = Tuple[str, str, int]


class _PriceCache:
    """Thread-safe (single-process) in-memory cache with TTL.

    Keys are (account_code, sku, qty). Values are (expires_at_epoch,
    ResolvedPrice). Reads check the timestamp before returning.
    """

    def __init__(self, ttl_seconds: int) -> None:
        self._ttl = ttl_seconds
        self._store: Dict[CacheKey, Tuple[float, ResolvedPrice]] = {}
        self._lock = Lock()

    def get(self, key: CacheKey) -> Optional[ResolvedPrice]:
        if self._ttl <= 0:
            return None
        now = time.monotonic()
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            expires_at, value = entry
            if now >= expires_at:
                # Lazy purge.
                self._store.pop(key, None)
                return None
            return value

    def set(self, key: CacheKey, value: ResolvedPrice) -> None:
        if self._ttl <= 0:
            return
        with self._lock:
            self._store[key] = (time.monotonic() + self._ttl, value)

    def clear(self) -> None:
        with self._lock:
            self._store.clear()


# Module-level singleton. Tests that need a fresh cache call clear().
_price_cache = _PriceCache(DEFAULT_CACHE_TTL_SECONDS)


def clear_cache() -> None:
    """Test helper — drop every cached entry."""
    _price_cache.clear()


# Decimal-to-cents conversion is brittle when BC returns floats. We
# round half-to-even via Python's built-in `round`, which is what every
# other money column in this codebase does.
def _to_cents(amount: Any) -> int:
    if amount is None:
        return 0
    try:
        return int(round(float(amount) * 100))
    except (TypeError, ValueError):
        return 0


def _resolve_customer_price_group(db: Session, account_code: str) -> Optional[str]:
    """Look up `bc_customers.bc_price_group` for the account code.

    `bc_customer_id` is the BC customer-number string (e.g. "ED-001"),
    not a GUID — it matches the `customerNumber` field on BC's API
    side which is what the supplier_account_code carries.
    """
    row = (
        db.query(BCCustomer)
        .filter(BCCustomer.bc_customer_id == account_code)
        .first()
    )
    if row is None:
        return None
    return getattr(row, "bc_price_group", None) or None


def _first_entry_price(entries: list) -> Optional[float]:
    """SalesPriceLists query returns a list of matching rows; pick the
    one with the lowest Unit_Price (most-favorable to the buyer). v1
    keeps this simple — the BC SalesPriceLists active-window filter
    already narrows to currently-effective prices."""
    if not entries:
        return None
    best: Optional[float] = None
    for e in entries:
        unit_price = e.get("Unit_Price") if isinstance(e, dict) else None
        if unit_price is None:
            continue
        try:
            v = float(unit_price)
        except (TypeError, ValueError):
            continue
        if best is None or v < best:
            best = v
    return best


def _query_bc_price(account_code: str, sku: str, qty: float, db: Session) -> Tuple[Optional[float], str]:
    """Run the customer → group → all-customers fall-through. Returns
    (unit_price_dollars, source_label)."""

    # 1. Customer-specific.
    try:
        customer_result = bc_client.get_sales_price_lines(
            item_no=sku, source_type=1, source_no=account_code, qty=qty,
        )
        if customer_result.get("available"):
            p = _first_entry_price(customer_result.get("entries", []))
            if p is not None:
                return p, "customer"
    except Exception as exc:  # pragma: no cover — bc transport
        logger.warning("BC customer-price query failed for %s/%s: %s", account_code, sku, exc)

    # 2. Customer price group.
    group = _resolve_customer_price_group(db, account_code)
    if group:
        try:
            group_result = bc_client.get_sales_price_lines(
                item_no=sku, source_type=2, source_no=group, qty=qty,
            )
            if group_result.get("available"):
                p = _first_entry_price(group_result.get("entries", []))
                if p is not None:
                    return p, "group"
        except Exception as exc:  # pragma: no cover
            logger.warning("BC group-price query failed for %s/%s/%s: %s", account_code, group, sku, exc)

    # 3. All customers.
    try:
        all_result = bc_client.get_sales_price_lines(
            item_no=sku, source_type=0, qty=qty,
        )
        if all_result.get("available"):
            p = _first_entry_price(all_result.get("entries", []))
            if p is not None:
                return p, "all_customers"
    except Exception as exc:  # pragma: no cover
        logger.warning("BC all-customers price query failed for %s: %s", sku, exc)

    return None, "none"


def _get_item(sku: str) -> Optional[dict]:
    """Pull the BC item record for unitCost + category + display name.

    Wraps the BC client. Tests stub this via monkeypatch.
    """
    try:
        # bc_client exposes a single-item fetch via the search method
        # plus a batched get; the single fetch is fine for SQB-04.
        result = bc_client.search_items(query=sku, limit=1)
        items = result.get("items", []) if isinstance(result, dict) else []
        for item in items:
            if not isinstance(item, dict):
                continue
            if item.get("number") == sku:
                return item
    except Exception as exc:  # pragma: no cover
        logger.warning("BC item lookup failed for %s: %s", sku, exc)
    return None


def resolve_price(
    db: Session,
    account_code: str,
    sku: str,
    quantity: int,
) -> Optional[ResolvedPrice]:
    """Resolve a single line's unit price + cost for the external API.

    Returns None when BC has no record of the SKU at all — caller
    surfaces a per-line zero entry in the response so the UI can flag
    the missing SKU without dropping the whole batch.
    """
    if quantity <= 0:
        return None

    key: CacheKey = (account_code, sku, quantity)
    hit = _price_cache.get(key)
    if hit is not None:
        return hit

    item = _get_item(sku)
    if not item:
        return None

    unit_cost_dollars = item.get("unitCost", 0) or 0
    description = item.get("displayName") or sku
    item_category = item.get("itemCategoryCode") or None

    price_dollars, source = _query_bc_price(account_code, sku, float(quantity), db)
    if price_dollars is None:
        # Last-chance fallback: item's own unitPrice (often 0 on
        # OPENDC's catalog, but a non-zero value beats returning None).
        fallback = item.get("unitPrice") or 0
        try:
            price_dollars = float(fallback) if fallback else None
        except (TypeError, ValueError):
            price_dollars = None
        if price_dollars is None or price_dollars <= 0:
            return None
        source = "item_default"

    unit_price_cents = _to_cents(price_dollars)
    unit_cost_cents = _to_cents(unit_cost_dollars)
    line_total_cents = unit_price_cents * quantity

    resolved = ResolvedPrice(
        sku=sku,
        quantity=quantity,
        unit_price_cents=unit_price_cents,
        unit_cost_cents=unit_cost_cents,
        line_total_cents=line_total_cents,
        item_category=item_category,
        description=description,
        currency="CAD",
        price_source=source,
    )
    _price_cache.set(key, resolved)
    return resolved
