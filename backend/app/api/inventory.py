"""
Inventory API Endpoints

Provides inventory visibility and availability checking via REST API.
Integrates with Business Central for real-time inventory data.
"""

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import date

from app.services.bc_inventory_service import bc_inventory_service

router = APIRouter(prefix="/inventory", tags=["Inventory"])


# ==================== Request/Response Models ====================

class ItemQuantity(BaseModel):
    """Request model for item availability check"""
    itemNumber: str = Field(..., description="BC item number")
    quantity: float = Field(default=1, ge=0, description="Quantity needed")


class AvailabilityCheckRequest(BaseModel):
    """Request model for checking availability of multiple items"""
    items: List[ItemQuantity] = Field(..., description="Items to check")
    requiredDate: Optional[date] = Field(None, description="Date when items are needed")


class InventoryLevelResponse(BaseModel):
    """Response model for inventory level"""
    itemNumber: str
    displayName: str
    category: Optional[str]
    inventory: float
    unitOfMeasure: str
    unitCost: float
    unitPrice: float
    type: Optional[str]
    lastModified: Optional[str]


# ==================== Endpoints ====================

@router.post("/check-availability")
async def check_availability(request: AvailabilityCheckRequest):
    """
    Check inventory availability for a list of items.

    Returns:
    - Overall availability status
    - Per-item availability details
    - List of shortages
    - Production orders needed

    This endpoint uses the BC Items API to check on-hand inventory.
    Future: Will also check production orders and purchase orders.
    """
    try:
        items = [{"itemNumber": item.itemNumber, "quantity": item.quantity} for item in request.items]
        result = bc_inventory_service.check_availability(items, request.requiredDate)
        return result.to_dict()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error checking availability: {str(e)}")


@router.get("/levels")
async def get_inventory_levels(
    itemNumbers: Optional[str] = Query(None, description="Comma-separated item numbers"),
    category: Optional[str] = Query(None, description="Filter by item category"),
    lowStock: bool = Query(False, description="Only show items with low stock"),
    threshold: float = Query(10, description="Low stock threshold")
):
    """
    Get current inventory levels.

    Args:
        itemNumbers: Comma-separated list of specific items to check
        category: Filter by item category code
        lowStock: Only return items below threshold
        threshold: Low stock threshold (default 10)

    Returns:
        List of items with their current inventory levels
    """
    try:
        item_list = itemNumbers.split(",") if itemNumbers else None
        levels = bc_inventory_service.get_inventory_levels(
            item_numbers=item_list,
            category_code=category,
            only_low_stock=lowStock,
            low_stock_threshold=threshold
        )
        return {
            "count": len(levels),
            "items": levels
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting inventory levels: {str(e)}")


@router.get("/item/{item_number}")
async def get_item_inventory(item_number: str):
    """
    Get inventory details for a specific item.

    Returns:
        - Current on-hand quantity
        - Item details (cost, price, UOM)
        - Availability status
    """
    try:
        item = bc_inventory_service.get_item_by_number(item_number)
        if not item:
            raise HTTPException(status_code=404, detail=f"Item not found: {item_number}")

        return {
            "itemNumber": item.get("number"),
            "displayName": item.get("displayName"),
            "category": item.get("itemCategoryCode"),
            "type": item.get("type"),
            "inventory": float(item.get("inventory", 0)),
            "unitOfMeasure": item.get("baseUnitOfMeasureCode"),
            "unitCost": float(item.get("unitCost", 0)),
            "unitPrice": float(item.get("unitPrice", 0)),
            "taxGroup": item.get("taxGroupCode"),
            "blocked": item.get("blocked", False),
            "lastModified": item.get("lastModifiedDateTime")
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting item: {str(e)}")


@router.get("/item/{item_number}/movements")
async def get_item_movements(
    item_number: str,
    days: int = Query(30, ge=1, le=365, description="Number of days of history")
):
    """
    Get recent inventory movements for an item.

    Returns:
        List of inventory transactions (sales, purchases, production, adjustments)
    """
    try:
        movements = bc_inventory_service.get_item_movements(item_number, days)
        return {
            "itemNumber": item_number,
            "days": days,
            "count": len(movements),
            "movements": movements
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting movements: {str(e)}")


@router.get("/categories")
async def get_item_categories():
    """
    Get list of item categories from BC.

    Returns:
        List of item category codes and names
    """
    try:
        company_id = bc_inventory_service.client.company_id
        categories = bc_inventory_service.client._make_request(
            "GET",
            f"companies({company_id})/itemCategories"
        )
        return {
            "count": len(categories.get("value", [])),
            "categories": [
                {
                    "code": cat.get("code"),
                    "displayName": cat.get("displayName"),
                    "parentCategoryCode": cat.get("parentCategoryCode")
                }
                for cat in categories.get("value", [])
            ]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting categories: {str(e)}")


@router.get("/locations")
async def get_locations():
    """
    Get list of inventory locations (warehouses) from BC.

    Returns:
        List of location codes and names
    """
    try:
        company_id = bc_inventory_service.client.company_id
        locations = bc_inventory_service.client._make_request(
            "GET",
            f"companies({company_id})/locations"
        )
        return {
            "count": len(locations.get("value", [])),
            "locations": [
                {
                    "code": loc.get("code"),
                    "displayName": loc.get("displayName"),
                    "address": loc.get("address"),
                    "city": loc.get("city"),
                    "country": loc.get("countryRegionCode")
                }
                for loc in locations.get("value", [])
            ]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting locations: {str(e)}")


# ==================== Future Endpoints (Require BC Production API) ====================

@router.post("/reserve", include_in_schema=False)
async def reserve_inventory():
    """
    Reserve inventory for a sales order.

    NOTE: This endpoint is not yet implemented.
    Requires BC to expose reservation API.
    """
    raise HTTPException(
        status_code=501,
        detail="Inventory reservation not yet implemented - requires BC production API exposure"
    )


@router.post("/production-order", include_in_schema=False)
async def create_production_order():
    """
    Create a production order in BC.

    NOTE: This endpoint is not yet implemented.
    Requires BC to expose production order API.
    """
    raise HTTPException(
        status_code=501,
        detail="Production order creation not yet implemented - requires BC production API exposure"
    )


@router.get("/production-schedule", include_in_schema=False)
async def get_production_schedule():
    """
    Get production schedule from BC.

    NOTE: This endpoint is not yet implemented.
    Requires BC to expose production order and work center APIs.
    """
    raise HTTPException(
        status_code=501,
        detail="Production schedule not yet implemented - requires BC production API exposure"
    )
