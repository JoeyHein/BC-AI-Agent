"""
Production Tasks API Endpoints

Provides task completion functionality for shop floor employees.
Allows viewing tasks by date, marking tasks complete, and shipping completed orders.
Supports drag-and-drop scheduling of sales orders.
"""

from fastapi import APIRouter, HTTPException, Depends, Query
from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import date, datetime
from collections import defaultdict

from app.db.database import get_db
from sqlalchemy.orm import Session

from app.services.task_completion_service import task_completion_service
from app.services.bc_production_service import bc_production_service, PRODUCTION_API_AVAILABLE
from app.db.models import ProductionTask, ProductionOrder, SalesOrder, SalesOrderLineItem

router = APIRouter(prefix="/production/tasks", tags=["Production Tasks"])


# ==================== Request/Response Models ====================

class TaskCompleteRequest(BaseModel):
    """Request to mark a task complete"""
    taskId: int = Field(..., description="ID of the task to complete")
    userId: Optional[str] = Field(default="shop_floor", description="User ID completing the task")
    quantityCompleted: Optional[float] = Field(None, description="Quantity completed (defaults to required)")


class ShipOrderRequest(BaseModel):
    """Request to ship a completed order"""
    userId: Optional[str] = Field(default="shop_floor", description="User ID initiating shipment")


class ScheduleOrderRequest(BaseModel):
    """Request to schedule or reschedule a sales order"""
    salesOrderId: int = Field(..., description="ID of the sales order to schedule")
    scheduledDate: date = Field(..., description="Date to schedule the order")
    userId: Optional[str] = Field(default="shop_floor", description="User making the change")


class LinkWorkOrderRequest(BaseModel):
    """Request to link a work order to a sales order"""
    workOrderId: int = Field(..., description="ID of the work order (production order) to link")
    salesOrderId: int = Field(..., description="ID of the sales order to link to")


class TaskResponse(BaseModel):
    """Response model for a production task"""
    id: int
    productionOrderId: Optional[int]
    bcProdOrderNo: Optional[str]
    bcLineNo: Optional[int]
    itemNo: Optional[str]
    description: Optional[str]
    quantityRequired: float
    quantityCompleted: float
    unitOfMeasure: Optional[str]
    materialAvailable: float
    materialNeeded: float
    materialStatus: Optional[str]
    status: str
    scheduledDate: Optional[str]
    completedAt: Optional[str]
    completedBy: Optional[str]
    bcSynced: bool


# ==================== Endpoints ====================

@router.get("/by-date/{target_date}")
async def get_tasks_by_date(
    target_date: date,
    include_materials: bool = Query(default=True, description="Include material availability"),
    db: Session = Depends(get_db)
):
    """
    Get production tasks for a specific date, grouped by Sales Order > Line Item > Production Order.

    Returns tasks scheduled for the date with:
    - Task details (item, description, quantity)
    - Completion status
    - Material availability (green/yellow/red status)

    Hierarchy: Sales Order > Line Item > Production Order (Work Order) > Tasks

    Material status values:
    - 'sufficient': All materials available
    - 'partial': Some materials available
    - 'unavailable': No materials available
    - 'unknown': Could not determine status
    """
    try:
        tasks = await task_completion_service.get_tasks_by_date(
            db=db,
            target_date=target_date,
            include_materials=include_materials
        )

        # Build hierarchy: Sales Order > Line Item > Production Order > Tasks
        # First, get production order IDs from tasks
        prod_order_ids = set(t.get("productionOrderId") for t in tasks if t.get("productionOrderId"))

        # Query production orders, their line items, and sales orders
        prod_orders_data = {}
        line_items_data = {}
        sales_orders_data = {}

        for po_id in prod_order_ids:
            po = db.query(ProductionOrder).filter(ProductionOrder.id == po_id).first()
            if po:
                prod_orders_data[po_id] = po

                # Get linked line item
                if po.line_item_id:
                    if po.line_item_id not in line_items_data:
                        li = db.query(SalesOrderLineItem).filter(SalesOrderLineItem.id == po.line_item_id).first()
                        if li:
                            line_items_data[po.line_item_id] = li

                # Get linked sales order
                if po.sales_order_id:
                    if po.sales_order_id not in sales_orders_data:
                        so = db.query(SalesOrder).filter(SalesOrder.id == po.sales_order_id).first()
                        if so:
                            sales_orders_data[po.sales_order_id] = so
                            # Also fetch line items for this sales order
                            for li in so.line_items:
                                if li.id not in line_items_data:
                                    line_items_data[li.id] = li

        # Group tasks: Sales Order > Line Item > Production Order > Tasks
        sales_order_groups = defaultdict(lambda: {
            "salesOrderId": None,
            "bcOrderNumber": None,
            "customerName": "No Sales Order",
            "status": "unknown",
            "lineItems": defaultdict(lambda: {
                "lineItemId": None,
                "bcLineNo": None,
                "itemNo": None,
                "description": None,
                "quantity": 0,
                "unitOfMeasure": None,
                "lineType": None,
                "hasProductionOrder": False,
                "productionOrders": defaultdict(lambda: {
                    "productionOrderId": None,
                    "bcProdOrderNumber": None,
                    "itemCode": None,
                    "itemDescription": None,
                    "quantity": 0,
                    "status": "unknown",
                    "dueDate": None,
                    "tasks": [],
                    "totalTasks": 0,
                    "completedTasks": 0,
                    "allComplete": False
                }),
                "totalTasks": 0,
                "completedTasks": 0,
                "allComplete": False
            }),
            "totalTasks": 0,
            "completedTasks": 0,
            "allComplete": False
        })

        for task in tasks:
            po_id = task.get("productionOrderId")
            po = prod_orders_data.get(po_id) if po_id else None

            # Determine sales order key
            if po and po.sales_order_id:
                so = sales_orders_data.get(po.sales_order_id)
                so_key = po.sales_order_id
                so_number = so.bc_order_number if so else f"SO-{po.sales_order_id}"
                customer_name = so.customer_name if so else "Unknown Customer"
                so_status = so.status.value if so and so.status else "unknown"
            else:
                so_key = f"no-so-{po_id}" if po_id else "no-so-orphan"
                so_number = None
                customer_name = "No Sales Order"
                so_status = "unknown"

            # Update sales order group
            so_group = sales_order_groups[so_key]
            so_group["salesOrderId"] = po.sales_order_id if po else None
            so_group["bcOrderNumber"] = so_number
            so_group["customerName"] = customer_name
            so_group["status"] = so_status

            # Determine line item key - use line_item_id if available, otherwise create virtual from PO
            if po and po.line_item_id:
                li = line_items_data.get(po.line_item_id)
                li_key = po.line_item_id
            elif po:
                # Create a virtual line item key based on production order's item_code
                li_key = f"virtual-{po.item_code or po_id}"
                li = None
            else:
                li_key = "no-line-item"
                li = None

            # Update line item within sales order
            li_group = so_group["lineItems"][li_key]
            if li:
                li_group["lineItemId"] = li.id
                li_group["bcLineNo"] = li.bc_line_no
                li_group["itemNo"] = li.item_no
                li_group["description"] = li.description
                li_group["quantity"] = li.quantity
                li_group["unitOfMeasure"] = li.unit_of_measure
                li_group["lineType"] = li.line_type
            elif po:
                # Use production order data as virtual line item
                li_group["lineItemId"] = None
                li_group["bcLineNo"] = None
                li_group["itemNo"] = po.item_code
                li_group["description"] = po.item_description
                li_group["quantity"] = po.quantity
                li_group["unitOfMeasure"] = None
                li_group["lineType"] = "Item"

            li_group["hasProductionOrder"] = True

            # Update production order within line item
            po_key = po_id or "orphan"
            po_group = li_group["productionOrders"][po_key]

            if po:
                po_group["productionOrderId"] = po.id
                po_group["bcProdOrderNumber"] = po.bc_prod_order_number
                po_group["itemCode"] = po.item_code
                po_group["itemDescription"] = po.item_description
                po_group["quantity"] = po.quantity
                po_group["status"] = po.status.value if po.status else "unknown"
                po_group["dueDate"] = po.due_date.isoformat() if po.due_date else None

            po_group["tasks"].append(task)
            po_group["totalTasks"] += 1
            if task.get("status") == "completed":
                po_group["completedTasks"] += 1

            li_group["totalTasks"] += 1
            if task.get("status") == "completed":
                li_group["completedTasks"] += 1

            so_group["totalTasks"] += 1
            if task.get("status") == "completed":
                so_group["completedTasks"] += 1

        # Convert to list and calculate completion status
        sales_orders = []
        for so_key, so_group in sales_order_groups.items():
            # Convert line items defaultdict to list
            line_items_list = []
            for li_key, li_group in so_group["lineItems"].items():
                # Convert production orders defaultdict to list
                prod_orders_list = []
                for po_key, po_group in li_group["productionOrders"].items():
                    po_group["allComplete"] = po_group["completedTasks"] == po_group["totalTasks"] and po_group["totalTasks"] > 0
                    prod_orders_list.append(dict(po_group))

                li_group["productionOrders"] = prod_orders_list
                li_group["allComplete"] = li_group["completedTasks"] == li_group["totalTasks"] and li_group["totalTasks"] > 0
                line_items_list.append(dict(li_group))

            so_group["lineItems"] = line_items_list
            so_group["allComplete"] = so_group["completedTasks"] == so_group["totalTasks"] and so_group["totalTasks"] > 0
            sales_orders.append(dict(so_group))

        # Sort by customer name
        sales_orders.sort(key=lambda x: x.get("customerName") or "")

        return {
            "date": target_date.isoformat(),
            "totalTasks": len(tasks),
            "completedTasks": sum(1 for t in tasks if t.get("status") == "completed"),
            "salesOrders": sales_orders,
            "tasks": tasks  # Keep flat list for backward compatibility
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/order/{production_order_id}")
async def get_tasks_by_order(
    production_order_id: int,
    db: Session = Depends(get_db)
):
    """
    Get all tasks for a specific production order.

    Returns tasks with material availability status.
    """
    try:
        tasks = await task_completion_service.get_tasks_by_production_order(
            db=db,
            production_order_id=production_order_id
        )

        completed = sum(1 for t in tasks if t.get("status") == "completed")

        return {
            "productionOrderId": production_order_id,
            "totalTasks": len(tasks),
            "completedTasks": completed,
            "allComplete": completed == len(tasks),
            "tasks": tasks
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/complete")
async def complete_task(
    request: TaskCompleteRequest,
    db: Session = Depends(get_db)
):
    """
    Mark a production task as complete.

    This will:
    1. Update the task status locally
    2. Sync the completion to BC (if API available)
    3. Check if all tasks in the order are complete

    Returns completion status and whether the entire order is now complete.
    """
    try:
        success, result = await task_completion_service.complete_task(
            db=db,
            task_id=request.taskId,
            user_id=request.userId or "shop_floor",
            quantity_completed=request.quantityCompleted
        )

        if not success:
            raise HTTPException(status_code=400, detail=result.get("error", "Failed to complete task"))

        return {
            "success": True,
            "task": result.get("task"),
            "bcSynced": result.get("bcSynced", False),
            "bcSyncError": result.get("bcSyncError"),
            "orderComplete": result.get("orderComplete", False),
            "productionOrderId": result.get("productionOrderId"),
            "message": "Task marked complete" + (" - All tasks in this order are now complete!" if result.get("orderComplete") else "")
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/order/{production_order_id}/ship")
async def ship_completed_order(
    production_order_id: int,
    request: ShipOrderRequest = None,
    db: Session = Depends(get_db)
):
    """
    Ship a completed production order.

    Prerequisites:
    - All tasks in the order must be completed

    This will:
    1. Finish the production order in BC (Microsoft.NAV.finish)
    2. Ship the linked sales order in BC (Microsoft.NAV.ship)
    3. Generate packing slip automatically

    Returns shipment number and confirmation.
    """
    if not PRODUCTION_API_AVAILABLE:
        raise HTTPException(
            status_code=501,
            detail="BC Production API not available - cannot ship orders"
        )

    try:
        user_id = request.userId if request else "shop_floor"

        success, result = await task_completion_service.ship_completed_order(
            db=db,
            production_order_id=production_order_id,
            user_id=user_id
        )

        if not success:
            error_msg = result.get("error", "Failed to ship order")
            status_code = 400 if result.get("incompleteCount") else 500
            raise HTTPException(status_code=status_code, detail=result)

        return {
            "success": True,
            "productionOrderId": production_order_id,
            "shipmentNumber": result.get("shipmentNumber"),
            "packingSlipGenerated": result.get("packingSlipGenerated", True),
            "message": result.get("message", "Order shipped successfully")
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/order/{production_order_id}/components")
async def get_order_components_with_availability(
    production_order_id: int,
    order_no: Optional[str] = Query(None, description="BC production order number")
):
    """
    Get production order components with material availability.

    Returns each component line with:
    - Item details
    - Quantity required
    - Inventory available
    - Availability status (sufficient/partial/unavailable)
    """
    if not PRODUCTION_API_AVAILABLE:
        return {
            "warning": "BC Production API not available",
            "productionOrderId": production_order_id,
            "components": []
        }

    try:
        # Use order_no if provided, otherwise we'd need to look it up
        if not order_no:
            return {
                "error": "order_no query parameter required",
                "productionOrderId": production_order_id,
                "components": []
            }

        components = await bc_production_service.get_components_with_availability(
            prod_order_no=order_no
        )

        return {
            "productionOrderId": production_order_id,
            "orderNo": order_no,
            "count": len(components),
            "components": components,
            "summary": {
                "sufficient": sum(1 for c in components if c.get("availabilityStatus") == "sufficient"),
                "partial": sum(1 for c in components if c.get("availabilityStatus") == "partial"),
                "unavailable": sum(1 for c in components if c.get("availabilityStatus") == "unavailable")
            }
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/summary/{target_date}")
async def get_daily_summary(
    target_date: date,
    db: Session = Depends(get_db)
):
    """
    Get a summary of production tasks for a date.

    Useful for dashboard/overview displays.
    """
    try:
        tasks = await task_completion_service.get_tasks_by_date(
            db=db,
            target_date=target_date,
            include_materials=True
        )

        # Calculate summary statistics
        total = len(tasks)
        completed = sum(1 for t in tasks if t.get("status") == "completed")
        in_progress = sum(1 for t in tasks if t.get("status") == "in_progress")
        blocked = sum(1 for t in tasks if t.get("status") == "blocked")
        pending = total - completed - in_progress - blocked

        # Material availability breakdown
        sufficient = sum(1 for t in tasks if t.get("materialStatus") == "sufficient")
        partial = sum(1 for t in tasks if t.get("materialStatus") == "partial")
        unavailable = sum(1 for t in tasks if t.get("materialStatus") == "unavailable")

        # Unique production orders
        unique_orders = set(t.get("bcProdOrderNo") for t in tasks if t.get("bcProdOrderNo"))

        return {
            "date": target_date.isoformat(),
            "tasks": {
                "total": total,
                "completed": completed,
                "inProgress": in_progress,
                "pending": pending,
                "blocked": blocked,
                "completionPercent": round((completed / total * 100) if total > 0 else 0, 1)
            },
            "materials": {
                "sufficient": sufficient,
                "partial": partial,
                "unavailable": unavailable,
                "readyPercent": round((sufficient / total * 100) if total > 0 else 0, 1)
            },
            "orders": {
                "total": len(unique_orders)
            }
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ==================== Scheduling Endpoints ====================

@router.get("/open-orders")
async def get_open_sales_orders(
    db: Session = Depends(get_db)
):
    """
    Get all open sales orders with their work orders (production orders).

    Returns all sales orders that are not completed/cancelled, with expandable
    work orders inside. Used for the scheduling side panel.
    """
    try:
        from app.db.models import OrderStatus

        # Get all open sales orders (not completed, not cancelled)
        sales_orders = db.query(SalesOrder).filter(
            SalesOrder.status.notin_([OrderStatus.COMPLETED, OrderStatus.CANCELLED])
        ).order_by(SalesOrder.created_at.desc()).all()

        result = []
        for so in sales_orders:
            # Get production orders (work orders) for this sales order
            prod_orders = db.query(ProductionOrder).filter(
                ProductionOrder.sales_order_id == so.id
            ).all()

            total_tasks = 0
            completed_tasks = 0
            scheduled_tasks = 0

            work_orders = []
            for po in prod_orders:
                # Get tasks for this production order
                tasks = db.query(ProductionTask).filter(
                    ProductionTask.production_order_id == po.id
                ).all()

                po_total = len(tasks)
                po_completed = sum(1 for t in tasks if t.status.value == "completed")
                po_scheduled = sum(1 for t in tasks if t.scheduled_date is not None)

                total_tasks += po_total
                completed_tasks += po_completed
                scheduled_tasks += po_scheduled

                work_orders.append({
                    "id": po.id,
                    "bcProdOrderNumber": po.bc_prod_order_number,
                    "itemCode": po.item_code,
                    "itemDescription": po.item_description,
                    "quantity": po.quantity,
                    "status": po.status.value if po.status else "unknown",
                    "dueDate": po.due_date.isoformat() if po.due_date else None,
                    "taskCount": po_total,
                    "completedTasks": po_completed,
                    "scheduledTasks": po_scheduled,
                    "isFullyScheduled": po_scheduled == po_total and po_total > 0
                })

            # Calculate scheduling status
            is_fully_scheduled = scheduled_tasks == total_tasks and total_tasks > 0

            result.append({
                "id": so.id,
                "bcOrderNumber": so.bc_order_number,
                "customerName": so.customer_name,
                "customerEmail": so.customer_email,
                "totalAmount": float(so.total_amount) if so.total_amount else None,
                "status": so.status.value if so.status else "unknown",
                "createdAt": so.created_at.isoformat() if so.created_at else None,
                "workOrders": work_orders,
                "workOrderCount": len(work_orders),
                "totalTasks": total_tasks,
                "completedTasks": completed_tasks,
                "scheduledTasks": scheduled_tasks,
                "isFullyScheduled": is_fully_scheduled
            })

        # Also include orphan production orders (no sales order)
        orphan_prod_orders = db.query(ProductionOrder).filter(
            ProductionOrder.sales_order_id == None
        ).all()

        for po in orphan_prod_orders:
            tasks = db.query(ProductionTask).filter(
                ProductionTask.production_order_id == po.id
            ).all()

            po_total = len(tasks)
            po_completed = sum(1 for t in tasks if t.status.value == "completed")
            po_scheduled = sum(1 for t in tasks if t.scheduled_date is not None)

            result.append({
                "id": None,
                "bcOrderNumber": po.bc_prod_order_number,  # Just the WO number
                "customerName": po.item_description[:50] if po.item_description else "Work Order",  # Show item desc as "customer"
                "customerEmail": None,
                "totalAmount": None,
                "status": "unknown",
                "createdAt": po.created_at.isoformat() if po.created_at else None,
                "workOrders": [{
                    "id": po.id,
                    "bcProdOrderNumber": po.bc_prod_order_number,
                    "itemCode": po.item_code,
                    "itemDescription": po.item_description,
                    "quantity": po.quantity,
                    "status": po.status.value if po.status else "unknown",
                    "dueDate": po.due_date.isoformat() if po.due_date else None,
                    "taskCount": po_total,
                    "completedTasks": po_completed,
                    "scheduledTasks": po_scheduled,
                    "isFullyScheduled": po_scheduled == po_total and po_total > 0
                }],
                "workOrderCount": 1,
                "totalTasks": po_total,
                "completedTasks": po_completed,
                "scheduledTasks": po_scheduled,
                "isFullyScheduled": po_scheduled == po_total and po_total > 0
            })

        return {
            "count": len(result),
            "salesOrders": result
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/unscheduled")
async def get_unscheduled_orders(
    db: Session = Depends(get_db)
):
    """
    Get sales orders with unscheduled tasks (legacy endpoint).
    Prefer using /open-orders for the full list.
    """
    try:
        # Get sales orders that have production orders
        sales_orders = db.query(SalesOrder).join(
            ProductionOrder, SalesOrder.id == ProductionOrder.sales_order_id
        ).distinct().all()

        result = []
        for so in sales_orders:
            # Get production orders for this sales order
            prod_orders = db.query(ProductionOrder).filter(
                ProductionOrder.sales_order_id == so.id
            ).all()

            # Check if any production order has unscheduled tasks
            has_unscheduled = False
            total_tasks = 0
            completed_tasks = 0

            prod_order_data = []
            for po in prod_orders:
                # Get tasks for this production order
                tasks = db.query(ProductionTask).filter(
                    ProductionTask.production_order_id == po.id
                ).all()

                unscheduled_tasks = [t for t in tasks if t.scheduled_date is None]
                if unscheduled_tasks:
                    has_unscheduled = True

                po_completed = sum(1 for t in tasks if t.status.value == "completed")
                total_tasks += len(tasks)
                completed_tasks += po_completed

                prod_order_data.append({
                    "id": po.id,
                    "bcProdOrderNumber": po.bc_prod_order_number,
                    "itemCode": po.item_code,
                    "itemDescription": po.item_description,
                    "quantity": po.quantity,
                    "status": po.status.value if po.status else "unknown",
                    "dueDate": po.due_date.isoformat() if po.due_date else None,
                    "taskCount": len(tasks),
                    "completedTasks": po_completed,
                    "hasUnscheduledTasks": len(unscheduled_tasks) > 0
                })

            # Only include if there are unscheduled tasks
            if has_unscheduled:
                result.append({
                    "id": so.id,
                    "bcOrderNumber": so.bc_order_number,
                    "customerName": so.customer_name,
                    "customerEmail": so.customer_email,
                    "totalAmount": float(so.total_amount) if so.total_amount else None,
                    "status": so.status.value if so.status else "unknown",
                    "productionOrders": prod_order_data,
                    "totalTasks": total_tasks,
                    "completedTasks": completed_tasks,
                    "workOrderCount": len(prod_orders)
                })

        # Also check for orphan production orders (no sales order link)
        orphan_prod_orders = db.query(ProductionOrder).filter(
            ProductionOrder.sales_order_id == None
        ).all()

        for po in orphan_prod_orders:
            tasks = db.query(ProductionTask).filter(
                ProductionTask.production_order_id == po.id
            ).all()

            unscheduled_tasks = [t for t in tasks if t.scheduled_date is None]
            if unscheduled_tasks:
                po_completed = sum(1 for t in tasks if t.status.value == "completed")
                result.append({
                    "id": None,
                    "bcOrderNumber": f"WO-{po.bc_prod_order_number}",
                    "customerName": "No Sales Order",
                    "customerEmail": None,
                    "totalAmount": None,
                    "status": "unknown",
                    "productionOrders": [{
                        "id": po.id,
                        "bcProdOrderNumber": po.bc_prod_order_number,
                        "itemCode": po.item_code,
                        "itemDescription": po.item_description,
                        "quantity": po.quantity,
                        "status": po.status.value if po.status else "unknown",
                        "dueDate": po.due_date.isoformat() if po.due_date else None,
                        "taskCount": len(tasks),
                        "completedTasks": po_completed,
                        "hasUnscheduledTasks": True
                    }],
                    "totalTasks": len(tasks),
                    "completedTasks": po_completed,
                    "workOrderCount": 1
                })

        return {
            "count": len(result),
            "salesOrders": result
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/schedule")
async def schedule_order(
    request: ScheduleOrderRequest,
    db: Session = Depends(get_db)
):
    """
    Schedule or reschedule a sales order to a specific date.

    This updates the scheduled_date for all tasks under all production orders
    linked to the sales order.
    """
    try:
        scheduled_date_dt = datetime.combine(request.scheduledDate, datetime.min.time())

        # Get the sales order
        sales_order = db.query(SalesOrder).filter(
            SalesOrder.id == request.salesOrderId
        ).first()

        if not sales_order:
            raise HTTPException(status_code=404, detail="Sales order not found")

        # Get all production orders for this sales order
        prod_orders = db.query(ProductionOrder).filter(
            ProductionOrder.sales_order_id == request.salesOrderId
        ).all()

        if not prod_orders:
            raise HTTPException(status_code=404, detail="No production orders found for this sales order")

        # Update all tasks under all production orders
        tasks_updated = 0
        for po in prod_orders:
            tasks = db.query(ProductionTask).filter(
                ProductionTask.production_order_id == po.id
            ).all()

            for task in tasks:
                task.scheduled_date = scheduled_date_dt
                tasks_updated += 1

        db.commit()

        return {
            "success": True,
            "salesOrderId": request.salesOrderId,
            "bcOrderNumber": sales_order.bc_order_number,
            "scheduledDate": request.scheduledDate.isoformat(),
            "productionOrdersUpdated": len(prod_orders),
            "tasksUpdated": tasks_updated,
            "message": f"Scheduled {len(prod_orders)} work orders ({tasks_updated} tasks) to {request.scheduledDate}"
        }

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/schedule-production-order")
async def schedule_production_order(
    productionOrderId: int = Query(..., description="Production order ID"),
    scheduledDate: date = Query(..., description="Date to schedule"),
    db: Session = Depends(get_db)
):
    """
    Schedule a single production order (for orphan orders without a sales order).
    """
    try:
        scheduled_date_dt = datetime.combine(scheduledDate, datetime.min.time())

        # Get the production order
        prod_order = db.query(ProductionOrder).filter(
            ProductionOrder.id == productionOrderId
        ).first()

        if not prod_order:
            raise HTTPException(status_code=404, detail="Production order not found")

        # Update all tasks under this production order
        tasks = db.query(ProductionTask).filter(
            ProductionTask.production_order_id == productionOrderId
        ).all()

        for task in tasks:
            task.scheduled_date = scheduled_date_dt

        db.commit()

        return {
            "success": True,
            "productionOrderId": productionOrderId,
            "bcProdOrderNumber": prod_order.bc_prod_order_number,
            "scheduledDate": scheduledDate.isoformat(),
            "tasksUpdated": len(tasks),
            "message": f"Scheduled work order to {scheduledDate}"
        }

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/unschedule/{sales_order_id}")
async def unschedule_order(
    sales_order_id: int,
    db: Session = Depends(get_db)
):
    """
    Remove a sales order from the schedule (set scheduled_date to null).
    """
    try:
        # Get all production orders for this sales order
        prod_orders = db.query(ProductionOrder).filter(
            ProductionOrder.sales_order_id == sales_order_id
        ).all()

        if not prod_orders:
            raise HTTPException(status_code=404, detail="No production orders found for this sales order")

        # Clear scheduled_date for all tasks
        tasks_updated = 0
        for po in prod_orders:
            tasks = db.query(ProductionTask).filter(
                ProductionTask.production_order_id == po.id
            ).all()

            for task in tasks:
                task.scheduled_date = None
                tasks_updated += 1

        db.commit()

        return {
            "success": True,
            "salesOrderId": sales_order_id,
            "tasksUpdated": tasks_updated,
            "message": f"Removed {tasks_updated} tasks from schedule"
        }

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


# ==================== Work Order Linking Endpoints ====================

@router.post("/link-work-order")
async def link_work_order_to_sales_order(
    request: LinkWorkOrderRequest,
    db: Session = Depends(get_db)
):
    """
    Link a work order (production order) to a sales order.

    Used for manually associating orphan work orders with their sales orders
    when BC's API doesn't expose this relationship.
    """
    try:
        # Get the production order
        prod_order = db.query(ProductionOrder).filter(
            ProductionOrder.id == request.workOrderId
        ).first()

        if not prod_order:
            raise HTTPException(status_code=404, detail="Work order not found")

        # Get the sales order
        sales_order = db.query(SalesOrder).filter(
            SalesOrder.id == request.salesOrderId
        ).first()

        if not sales_order:
            raise HTTPException(status_code=404, detail="Sales order not found")

        # Link the work order to the sales order
        old_sales_order_id = prod_order.sales_order_id
        prod_order.sales_order_id = request.salesOrderId

        db.commit()

        return {
            "success": True,
            "workOrderId": prod_order.id,
            "bcProdOrderNumber": prod_order.bc_prod_order_number,
            "salesOrderId": sales_order.id,
            "bcOrderNumber": sales_order.bc_order_number,
            "customerName": sales_order.customer_name,
            "previousSalesOrderId": old_sales_order_id,
            "message": f"Linked work order {prod_order.bc_prod_order_number} to sales order {sales_order.bc_order_number}"
        }

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/unlink-work-order/{work_order_id}")
async def unlink_work_order_from_sales_order(
    work_order_id: int,
    db: Session = Depends(get_db)
):
    """
    Unlink a work order (production order) from its sales order.

    Makes the work order an orphan again.
    """
    try:
        # Get the production order
        prod_order = db.query(ProductionOrder).filter(
            ProductionOrder.id == work_order_id
        ).first()

        if not prod_order:
            raise HTTPException(status_code=404, detail="Work order not found")

        old_sales_order_id = prod_order.sales_order_id
        prod_order.sales_order_id = None

        db.commit()

        return {
            "success": True,
            "workOrderId": prod_order.id,
            "bcProdOrderNumber": prod_order.bc_prod_order_number,
            "previousSalesOrderId": old_sales_order_id,
            "message": f"Unlinked work order {prod_order.bc_prod_order_number} from sales order"
        }

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
