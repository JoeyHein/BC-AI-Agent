"""
BC Inventory Service

Provides inventory visibility and availability checking using BC standard API.
This service works with the existing BC v2.0 API endpoints.

Future: Will integrate with production orders once BC exposes them via API.
"""

import logging
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field
from datetime import datetime, date
from enum import Enum

from app.integrations.bc.client import bc_client

logger = logging.getLogger(__name__)


class AvailabilityStatus(Enum):
    """Item availability status"""
    AVAILABLE = "available"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"
    PRODUCTION_REQUIRED = "production_required"


@dataclass
class ItemAvailability:
    """Represents availability status for a single item"""
    item_number: str
    display_name: str = ""
    requested_quantity: float = 0
    on_hand: float = 0
    available: float = 0  # On hand minus already committed
    on_production: float = 0  # Quantity on open production orders
    on_purchase: float = 0  # Quantity on open purchase orders
    shortfall: float = 0
    status: AvailabilityStatus = AvailabilityStatus.UNAVAILABLE
    lead_time_days: int = 0
    unit_of_measure: str = "EA"
    unit_cost: float = 0
    unit_price: float = 0
    location_code: str = ""
    error: Optional[str] = None


@dataclass
class AvailabilityCheckResult:
    """Result of availability check for multiple items"""
    check_date: datetime = field(default_factory=datetime.utcnow)
    all_available: bool = False
    items: List[ItemAvailability] = field(default_factory=list)
    shortages: List[ItemAvailability] = field(default_factory=list)
    production_needed: List[Dict[str, Any]] = field(default_factory=list)
    total_items: int = 0
    available_count: int = 0
    shortage_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API response"""
        return {
            "checkDate": self.check_date.isoformat(),
            "allAvailable": self.all_available,
            "summary": {
                "totalItems": self.total_items,
                "availableCount": self.available_count,
                "shortageCount": self.shortage_count
            },
            "items": [
                {
                    "itemNumber": item.item_number,
                    "displayName": item.display_name,
                    "requestedQuantity": item.requested_quantity,
                    "onHand": item.on_hand,
                    "available": item.available,
                    "onProduction": item.on_production,
                    "onPurchase": item.on_purchase,
                    "shortfall": item.shortfall,
                    "status": item.status.value,
                    "leadTimeDays": item.lead_time_days,
                    "unitOfMeasure": item.unit_of_measure,
                    "unitCost": item.unit_cost,
                    "unitPrice": item.unit_price,
                    "error": item.error
                }
                for item in self.items
            ],
            "shortages": [
                {
                    "itemNumber": item.item_number,
                    "displayName": item.display_name,
                    "requestedQuantity": item.requested_quantity,
                    "available": item.available,
                    "shortfall": item.shortfall,
                    "status": item.status.value
                }
                for item in self.shortages
            ],
            "productionNeeded": self.production_needed
        }


class BCInventoryService:
    """
    Service for checking inventory availability in Business Central.

    Currently uses the standard BC v2.0 API which provides:
    - Item inventory levels (on-hand quantity)
    - Item details (cost, price, unit of measure)
    - Item ledger entries (movement history)

    Future enhancements (requires BC to expose production APIs):
    - Check production order quantities
    - Check purchase order quantities
    - Reserve inventory for orders
    - Automatic production order creation
    """

    def __init__(self):
        self.client = bc_client
        self._item_cache: Dict[str, Dict[str, Any]] = {}
        self._cache_ttl_seconds = 300  # 5 minute cache

    def get_item_by_number(self, item_number: str) -> Optional[Dict[str, Any]]:
        """
        Get item details from BC by item number.

        Args:
            item_number: BC item number (e.g., 'HK02-16080-RC')

        Returns:
            Item dictionary or None if not found
        """
        try:
            # Use search to find by number
            items = self.client.search_items(item_number)
            # Find exact match
            for item in items:
                if item.get("number") == item_number:
                    return item
            return None
        except Exception as e:
            logger.error(f"Error fetching item {item_number}: {e}")
            return None

    def get_items_by_numbers(self, item_numbers: List[str]) -> Dict[str, Dict[str, Any]]:
        """
        Get multiple items from BC by their numbers.

        Args:
            item_numbers: List of BC item numbers

        Returns:
            Dictionary mapping item numbers to item data
        """
        result = {}

        # Batch items into groups to avoid overwhelming the API
        batch_size = 20
        for i in range(0, len(item_numbers), batch_size):
            batch = item_numbers[i:i + batch_size]

            for item_number in batch:
                item = self.get_item_by_number(item_number)
                if item:
                    result[item_number] = item

        return result

    def check_availability(
        self,
        items: List[Dict[str, Any]],
        required_date: Optional[date] = None
    ) -> AvailabilityCheckResult:
        """
        Check availability for a list of items.

        Args:
            items: List of dicts with 'itemNumber' and 'quantity' keys
            required_date: Optional date when items are needed

        Returns:
            AvailabilityCheckResult with status for each item
        """
        result = AvailabilityCheckResult()
        result.total_items = len(items)

        for item_request in items:
            item_number = item_request.get("itemNumber") or item_request.get("item_number")
            requested_qty = float(item_request.get("quantity", 1))

            availability = self._check_single_item(item_number, requested_qty)
            result.items.append(availability)

            if availability.status == AvailabilityStatus.AVAILABLE:
                result.available_count += 1
            else:
                result.shortage_count += 1
                result.shortages.append(availability)

                if availability.shortfall > 0:
                    result.production_needed.append({
                        "itemNumber": item_number,
                        "displayName": availability.display_name,
                        "quantityNeeded": availability.shortfall,
                        "leadTimeDays": availability.lead_time_days
                    })

        result.all_available = (result.shortage_count == 0)
        return result

    def _check_single_item(self, item_number: str, requested_qty: float) -> ItemAvailability:
        """Check availability for a single item"""
        availability = ItemAvailability(
            item_number=item_number,
            requested_quantity=requested_qty
        )

        try:
            # Fetch item from BC
            item = self.get_item_by_number(item_number)

            if not item:
                availability.error = f"Item not found in BC: {item_number}"
                availability.status = AvailabilityStatus.UNAVAILABLE
                return availability

            # Extract item details
            availability.display_name = item.get("displayName", "")
            availability.on_hand = float(item.get("inventory", 0))
            availability.unit_of_measure = item.get("baseUnitOfMeasureCode", "EA")
            availability.unit_cost = float(item.get("unitCost", 0))
            availability.unit_price = float(item.get("unitPrice", 0))

            # For now, available = on_hand (until we have reservation tracking)
            # TODO: Subtract reserved quantities once BC reservation API is available
            availability.available = availability.on_hand

            # Calculate shortfall
            if availability.available >= requested_qty:
                availability.shortfall = 0
                availability.status = AvailabilityStatus.AVAILABLE
            elif availability.available > 0:
                availability.shortfall = requested_qty - availability.available
                availability.status = AvailabilityStatus.PARTIAL
            else:
                availability.shortfall = requested_qty
                availability.status = AvailabilityStatus.UNAVAILABLE

            # TODO: Check production orders (requires BC to expose production order API)
            # availability.on_production = self._get_on_production(item_number)

            # TODO: Check purchase orders (requires additional BC API call)
            # availability.on_purchase = self._get_on_purchase(item_number)

            # Estimate lead time (this would be configured per item category)
            availability.lead_time_days = self._estimate_lead_time(item)

        except Exception as e:
            logger.error(f"Error checking availability for {item_number}: {e}")
            availability.error = str(e)
            availability.status = AvailabilityStatus.UNAVAILABLE

        return availability

    def _estimate_lead_time(self, item: Dict[str, Any]) -> int:
        """
        Estimate production lead time for an item.

        This is a placeholder - actual lead times would come from:
        - Item card lead time field
        - Routing total time
        - Work center capacity
        """
        item_number = item.get("number", "")
        category = item.get("itemCategoryCode", "")

        # Hardware kits typically have 3-5 day lead time
        if item_number.startswith("HK"):
            return 3
        # Panels typically have 5-7 day lead time
        elif item_number.startswith("PN"):
            return 5
        # Springs typically have 2-3 day lead time
        elif item_number.startswith("SP"):
            return 2
        # Default lead time
        else:
            return 7

    def get_inventory_levels(
        self,
        item_numbers: Optional[List[str]] = None,
        category_code: Optional[str] = None,
        only_low_stock: bool = False,
        low_stock_threshold: float = 10
    ) -> List[Dict[str, Any]]:
        """
        Get current inventory levels for items.

        Args:
            item_numbers: Specific items to check (None = all)
            category_code: Filter by item category
            only_low_stock: Only return items below threshold
            low_stock_threshold: Threshold for low stock filter

        Returns:
            List of items with inventory levels
        """
        try:
            if item_numbers:
                items = self.get_items_by_numbers(item_numbers)
                result = list(items.values())
            else:
                # Get all items (limited)
                result = self.client.get_items(top=500)

            # Filter by category if specified
            if category_code:
                result = [i for i in result if i.get("itemCategoryCode") == category_code]

            # Filter by low stock if specified
            if only_low_stock:
                result = [i for i in result if float(i.get("inventory", 0)) < low_stock_threshold]

            # Format response
            return [
                {
                    "itemNumber": item.get("number"),
                    "displayName": item.get("displayName"),
                    "category": item.get("itemCategoryCode"),
                    "inventory": float(item.get("inventory", 0)),
                    "unitOfMeasure": item.get("baseUnitOfMeasureCode"),
                    "unitCost": float(item.get("unitCost", 0)),
                    "unitPrice": float(item.get("unitPrice", 0)),
                    "type": item.get("type"),
                    "lastModified": item.get("lastModifiedDateTime")
                }
                for item in result
            ]

        except Exception as e:
            logger.error(f"Error getting inventory levels: {e}")
            return []

    def get_item_movements(
        self,
        item_number: str,
        days: int = 30
    ) -> List[Dict[str, Any]]:
        """
        Get recent inventory movements for an item.

        Uses the Item Ledger Entries API to show:
        - Sales (negative movements)
        - Purchases (positive movements)
        - Production output (positive)
        - Production consumption (negative)
        - Adjustments
        """
        try:
            # Item ledger entries are available in v2.0 API
            company_id = self.client.company_id

            # Get item ledger entries filtered by item
            # Note: Filter syntax may need adjustment based on BC version
            entries = self.client._make_request(
                "GET",
                f"companies({company_id})/itemLedgerEntries?$filter=itemNumber eq '{item_number}'&$orderby=postingDate desc&$top=100"
            )

            return [
                {
                    "entryNo": entry.get("entryNumber"),
                    "postingDate": entry.get("postingDate"),
                    "entryType": entry.get("entryType"),
                    "documentType": entry.get("documentType"),
                    "documentNumber": entry.get("documentNumber"),
                    "quantity": float(entry.get("quantity", 0)),
                    "remainingQuantity": float(entry.get("remainingQuantity", 0)),
                    "invoicedQuantity": float(entry.get("invoicedQuantity", 0)),
                    "locationCode": entry.get("locationCode"),
                    "description": entry.get("description")
                }
                for entry in entries.get("value", [])
            ]

        except Exception as e:
            logger.error(f"Error getting item movements for {item_number}: {e}")
            return []

    # ==================== Future Methods (Require BC Production API) ====================

    async def reserve_inventory(
        self,
        sales_order_id: str,
        items: List[Dict[str, Any]]
    ) -> bool:
        """
        Reserve inventory for a sales order.

        NOTE: This is a placeholder - BC reservation requires either:
        1. Custom API page with reservation logic
        2. Power Automate flow
        3. Direct database access (not recommended for SaaS)
        """
        logger.warning("Inventory reservation not yet implemented - requires BC production API")
        # TODO: Implement when BC exposes reservation API
        return False

    async def create_production_order(
        self,
        item_number: str,
        quantity: float,
        due_date: date,
        sales_order_number: Optional[str] = None,
        priority: str = "normal"
    ) -> Optional[Dict[str, Any]]:
        """
        Create a production order in BC.

        NOTE: This is a placeholder - Production orders are not in standard API.
        Requires BC to publish Production Order page as OData or custom API.
        """
        logger.warning("Production order creation not yet implemented - requires BC production API")
        # TODO: Implement when BC exposes production order API
        return None

    async def get_production_schedule(
        self,
        start_date: date,
        end_date: date,
        work_center: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Get production schedule from BC.

        NOTE: This is a placeholder - requires BC to expose:
        - Production Orders
        - Work Center Calendar
        - Capacity Ledger Entries
        """
        logger.warning("Production schedule not yet implemented - requires BC production API")
        # TODO: Implement when BC exposes production APIs
        return []


# Global instance
bc_inventory_service = BCInventoryService()
