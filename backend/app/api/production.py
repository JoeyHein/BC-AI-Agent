"""
Production API Endpoints

Provides production order management and scheduling via REST API.

NOTE: Full production order functionality requires BC to expose
production order APIs via OData or custom API pages.
Currently, scheduling calculations work locally but actual
production order CRUD operations will return 501 errors.
"""

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import date

from app.services.bc_production_service import (
    bc_production_service,
    ProductionOrderStatus,
    SchedulePriority,
    PRODUCTION_API_AVAILABLE
)

router = APIRouter(prefix="/production", tags=["Production"])


# ==================== Request/Response Models ====================

class ProductionOrderRequest(BaseModel):
    """Request model for creating a production order"""
    itemNo: str = Field(..., description="Item number to produce")
    quantity: float = Field(..., gt=0, description="Quantity to produce")
    dueDate: date = Field(..., description="Required completion date")
    salesOrderNo: Optional[str] = Field(None, description="Linked sales order number")
    locationCode: str = Field(default="", description="Production location")
    priority: str = Field(default="normal", description="Priority: low, normal, high, urgent")


class ScheduleOrderItem(BaseModel):
    """Order item for schedule calculation"""
    itemNo: str = Field(..., description="Item number")
    quantity: float = Field(..., gt=0, description="Quantity")
    dueDate: date = Field(..., description="Due date")
    salesOrderNo: Optional[str] = Field(None, description="Sales order reference")
    priority: str = Field(default="normal", description="Priority level")


class ScheduleCalculationRequest(BaseModel):
    """Request model for calculating production schedule"""
    orders: List[ScheduleOrderItem] = Field(..., description="Orders to schedule")
    startDate: date = Field(..., description="Schedule window start")
    endDate: date = Field(..., description="Schedule window end")
    workCenterCapacity: float = Field(default=8.0, description="Hours per day per work center")


# ==================== Endpoints ====================

@router.get("/status")
async def get_production_api_status():
    """
    Check if BC production API is available.

    Returns current integration status and what actions are available.
    """
    return {
        "apiAvailable": PRODUCTION_API_AVAILABLE,
        "message": "Production API is available" if PRODUCTION_API_AVAILABLE else
            "Production API not available - BC must expose production order endpoints",
        "availableActions": {
            "getOrders": PRODUCTION_API_AVAILABLE,
            "createOrder": PRODUCTION_API_AVAILABLE,
            "releaseOrder": PRODUCTION_API_AVAILABLE,
            "calculateSchedule": True,  # Always available (local calculation)
            "getCapacity": True  # Simulated if API not available
        },
        "requirements": [] if PRODUCTION_API_AVAILABLE else [
            "BC admin must publish Production Orders page as OData web service",
            "OR create custom API page for Production Orders",
            "OR set up Power Automate integration"
        ]
    }


@router.get("/orders")
async def get_production_orders(
    status: Optional[str] = Query(None, description="Filter by status"),
    itemNo: Optional[str] = Query(None, description="Filter by item number"),
    dateFrom: Optional[date] = Query(None, description="Due date from"),
    dateTo: Optional[date] = Query(None, description="Due date to"),
    limit: int = Query(100, ge=1, le=500, description="Maximum results")
):
    """
    Get production orders from BC.

    NOTE: Requires BC to expose production order API.
    Returns empty list with warning if API not available.
    """
    if not PRODUCTION_API_AVAILABLE:
        return {
            "warning": "Production API not available",
            "count": 0,
            "orders": []
        }

    status_filter = ProductionOrderStatus(status) if status else None
    orders = await bc_production_service.get_production_orders(
        status_filter=status_filter,
        item_no=itemNo,
        date_from=dateFrom,
        date_to=dateTo,
        limit=limit
    )

    return {
        "count": len(orders),
        "orders": [o.to_dict() for o in orders]
    }


@router.get("/orders/{order_no}")
async def get_production_order(order_no: str):
    """
    Get a specific production order by number.

    NOTE: Requires BC to expose production order API.
    """
    if not PRODUCTION_API_AVAILABLE:
        raise HTTPException(
            status_code=501,
            detail="Production API not available - BC must expose production order endpoints"
        )

    order = await bc_production_service.get_production_order(order_no)
    if not order:
        raise HTTPException(status_code=404, detail=f"Production order not found: {order_no}")

    return order.to_dict()


@router.post("/orders")
async def create_production_order(request: ProductionOrderRequest):
    """
    Create a new production order in BC.

    The order will be created with Firm Planned status by default.
    Use the /release endpoint to change to Released status.

    NOTE: Requires BC to expose production order API.
    """
    if not PRODUCTION_API_AVAILABLE:
        raise HTTPException(
            status_code=501,
            detail="Production order creation not available - BC must expose production order API. "
                   "See GET /production/status for requirements."
        )

    try:
        priority = SchedulePriority(request.priority)
    except ValueError:
        priority = SchedulePriority.NORMAL

    order = await bc_production_service.create_production_order(
        item_no=request.itemNo,
        quantity=request.quantity,
        due_date=request.dueDate,
        sales_order_no=request.salesOrderNo,
        location_code=request.locationCode,
        priority=priority
    )

    if not order:
        raise HTTPException(status_code=500, detail="Failed to create production order")

    return order.to_dict()


@router.post("/orders/{order_no}/release")
async def release_production_order(order_no: str):
    """
    Release a production order (change from Firm Planned to Released).

    This makes the order available for shop floor processing.

    NOTE: Requires BC to expose production order API.
    """
    if not PRODUCTION_API_AVAILABLE:
        raise HTTPException(
            status_code=501,
            detail="Production API not available"
        )

    success = await bc_production_service.release_production_order(order_no)
    if not success:
        raise HTTPException(status_code=500, detail=f"Failed to release order {order_no}")

    return {"success": True, "message": f"Production order {order_no} released"}


@router.post("/orders/{order_no}/finish")
async def finish_production_order(order_no: str):
    """
    Finish a production order (mark as completed).

    This will update inventory with the produced quantity.

    NOTE: Requires BC to expose production order API.
    """
    if not PRODUCTION_API_AVAILABLE:
        raise HTTPException(
            status_code=501,
            detail="Production API not available"
        )

    success = await bc_production_service.finish_production_order(order_no)
    if not success:
        raise HTTPException(status_code=500, detail=f"Failed to finish order {order_no}")

    return {"success": True, "message": f"Production order {order_no} finished"}


# ==================== Scheduling Endpoints (Always Available) ====================

@router.post("/schedule/calculate")
async def calculate_schedule(request: ScheduleCalculationRequest):
    """
    Calculate production schedule using backward scheduling.

    This endpoint works even without BC production API access.
    It calculates an optimal schedule based on:
    - Order due dates
    - Order priorities
    - Work center capacity

    The algorithm uses backward scheduling:
    - Starts from due date and works backward
    - Finds available capacity slots
    - Respects priority ordering

    Returns:
    - Scheduled orders with start/end dates
    - Unscheduled orders (capacity issues)
    - Schedule calendar view
    - Bottleneck analysis
    """
    orders = [
        {
            "itemNo": o.itemNo,
            "quantity": o.quantity,
            "dueDate": o.dueDate,
            "salesOrderNo": o.salesOrderNo,
            "priority": o.priority
        }
        for o in request.orders
    ]

    result = bc_production_service.calculate_schedule(
        orders_to_schedule=orders,
        start_date=request.startDate,
        end_date=request.endDate,
        work_center_capacity=request.workCenterCapacity
    )

    return result.to_dict()


@router.get("/schedule/capacity")
async def get_work_center_capacity(
    workCenter: Optional[str] = Query(None, description="Work center number"),
    dateFrom: date = Query(..., description="Start date"),
    dateTo: date = Query(..., description="End date")
):
    """
    Get work center capacity for scheduling with production orders.

    Returns capacity per day with scheduled orders and utilization.
    """
    from collections import defaultdict
    from datetime import timedelta

    # Get raw capacity data (per work center per day)
    raw_capacity = await bc_production_service.get_work_center_capacity(
        work_center_no=workCenter,
        date_from=dateFrom,
        date_to=dateTo
    )

    # Get production orders in date range
    orders = await bc_production_service.get_production_orders(
        date_from=dateFrom,
        date_to=dateTo,
        limit=500
    )

    # Aggregate capacity by date (sum all work centers)
    daily_capacity = defaultdict(lambda: {"availableHours": 0, "workCenters": []})
    for cap in raw_capacity:
        date_key = cap["date"]
        daily_capacity[date_key]["availableHours"] += cap.get("availableHours", 0)
        daily_capacity[date_key]["workCenters"].append(cap.get("workCenter", ""))

    # Map orders to their due dates
    orders_by_date = defaultdict(list)
    for order in orders:
        if order.due_date:
            date_key = order.due_date.isoformat()
            orders_by_date[date_key].append({
                "orderNo": order.order_no,
                "itemNo": order.item_no,
                "description": order.description,
                "quantity": order.quantity,
                "status": order.status.value,
                "routingNo": order.routing_no
            })

    # Build final capacity list with scheduled hours
    capacity_result = []
    current = dateFrom
    while current <= dateTo:
        date_str = current.isoformat()
        day_cap = daily_capacity.get(date_str, {"availableHours": 0, "workCenters": []})
        day_orders = orders_by_date.get(date_str, [])

        # Estimate scheduled hours (1 hour per order as simple approximation)
        scheduled_hours = len(day_orders) * 1.0

        available = day_cap["availableHours"] or 8.0  # Default 8 hours if no data
        utilization = (scheduled_hours / available * 100) if available > 0 else 0

        capacity_result.append({
            "date": date_str,
            "availableHours": available,
            "scheduledHours": scheduled_hours,
            "utilizationPercent": min(utilization, 100),
            "orderCount": len(day_orders),
            "orders": day_orders,
            "workCenters": day_cap["workCenters"]
        })

        current += timedelta(days=1)

    return {
        "source": "bc" if PRODUCTION_API_AVAILABLE else "simulated",
        "workCenter": workCenter or "ALL",
        "dateRange": {
            "from": dateFrom.isoformat(),
            "to": dateTo.isoformat()
        },
        "capacity": capacity_result,
        "summary": {
            "totalOrders": len(orders),
            "totalDays": len(capacity_result)
        }
    }


@router.get("/schedule/lead-times")
async def get_lead_times():
    """
    Get estimated lead times by item type.

    These are used in scheduling calculations.
    """
    return {
        "leadTimes": [
            {"itemPrefix": "HK", "description": "Hardware Kits", "leadTimeDays": 3},
            {"itemPrefix": "PN", "description": "Panels", "leadTimeDays": 5},
            {"itemPrefix": "SP", "description": "Springs", "leadTimeDays": 2},
            {"itemPrefix": "DR", "description": "Door Assemblies", "leadTimeDays": 7},
            {"itemPrefix": "*", "description": "Default", "leadTimeDays": 5}
        ],
        "note": "Lead times are estimates. Actual times depend on current capacity and order queue."
    }


# ==================== BC Data Endpoints (OData) ====================

@router.get("/work-centers")
async def get_work_centers(limit: int = Query(100, ge=1, le=500)):
    """
    Get work centers from BC.

    Returns list of work centers with their capacity info.
    """
    if not PRODUCTION_API_AVAILABLE:
        return {
            "warning": "Production API not available",
            "count": 0,
            "workCenters": []
        }

    work_centers = await bc_production_service.get_work_centers(limit=limit)
    return {
        "count": len(work_centers),
        "workCenters": work_centers
    }


@router.get("/orders/{order_no}/components")
async def get_order_components(order_no: str):
    """
    Get components for a specific production order.
    """
    if not PRODUCTION_API_AVAILABLE:
        raise HTTPException(
            status_code=501,
            detail="Production API not available"
        )

    components = await bc_production_service.get_production_order_components(
        prod_order_no=order_no
    )
    return {
        "orderNo": order_no,
        "count": len(components),
        "components": components
    }


@router.get("/orders/{order_no}/routing")
async def get_order_routing(order_no: str):
    """
    Get routing information for a specific production order.
    """
    if not PRODUCTION_API_AVAILABLE:
        raise HTTPException(
            status_code=501,
            detail="Production API not available"
        )

    routing = await bc_production_service.get_production_order_routing(
        prod_order_no=order_no
    )
    return {
        "orderNo": order_no,
        "count": len(routing),
        "routing": routing
    }


@router.get("/components")
async def get_all_components(
    prodOrderNo: Optional[str] = Query(None, description="Filter by production order"),
    limit: int = Query(500, ge=1, le=1000)
):
    """
    Get production order components from BC.
    """
    if not PRODUCTION_API_AVAILABLE:
        return {
            "warning": "Production API not available",
            "count": 0,
            "components": []
        }

    components = await bc_production_service.get_production_order_components(
        prod_order_no=prodOrderNo,
        limit=limit
    )
    return {
        "count": len(components),
        "components": components
    }


@router.get("/routing")
async def get_all_routing(limit: int = Query(500, ge=1, le=1000)):
    """
    Get production routing data from BC.
    """
    if not PRODUCTION_API_AVAILABLE:
        return {
            "warning": "Production API not available",
            "count": 0,
            "routing": []
        }

    routing = await bc_production_service.get_production_order_routing(limit=limit)
    return {
        "count": len(routing),
        "routing": routing
    }
