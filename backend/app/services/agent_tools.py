"""
Agent Tools Service

Implements the tools that the BC AI Agent can call.
Each tool maps to existing service methods to perform actions.
"""

import logging
from typing import Dict, Any, Optional, List
from datetime import datetime, date
from sqlalchemy.orm import Session
from sqlalchemy import or_

from app.db.models import (
    SalesOrder, SalesOrderLineItem, ProductionOrder, ProductionTask,
    OrderStatus, ProductionStatus
)

logger = logging.getLogger(__name__)


class AgentTools:
    """Tool implementations for the BC AI Agent"""

    def __init__(self, db: Session):
        self.db = db

    async def schedule_order(self, order_identifier: str, target_date: str) -> Dict[str, Any]:
        """
        Schedule a sales order to a specific production date.

        Works for orders with or without production orders (work orders).
        - Orders WITH work orders: schedules all production tasks
        - Orders WITHOUT work orders: schedules the order directly for picking/packing

        Args:
            order_identifier: Sales order ID (number) or BC order number (e.g., 'SO-000857')
            target_date: Target date in YYYY-MM-DD format

        Returns:
            Result with success status and details
        """
        try:
            # Parse the date
            scheduled_date = datetime.strptime(target_date, "%Y-%m-%d")

            # Find the sales order - try by ID first, then by BC order number
            sales_order = None

            # Try as integer ID
            try:
                order_id = int(order_identifier)
                sales_order = self.db.query(SalesOrder).filter(
                    SalesOrder.id == order_id
                ).first()
            except ValueError:
                pass

            # Try by BC order number
            if not sales_order:
                sales_order = self.db.query(SalesOrder).filter(
                    SalesOrder.bc_order_number == order_identifier
                ).first()

            # Also try with/without SO- prefix
            if not sales_order and not order_identifier.startswith("SO-"):
                sales_order = self.db.query(SalesOrder).filter(
                    SalesOrder.bc_order_number == f"SO-{order_identifier}"
                ).first()

            if not sales_order:
                return {
                    "success": False,
                    "error": f"Sales order '{order_identifier}' not found"
                }

            # Always set the scheduled_date on the sales order itself
            sales_order.scheduled_date = scheduled_date

            # Get all production orders for this sales order
            prod_orders = self.db.query(ProductionOrder).filter(
                ProductionOrder.sales_order_id == sales_order.id
            ).all()

            # Update all tasks under all production orders (if any)
            tasks_updated = 0
            for po in prod_orders:
                tasks = self.db.query(ProductionTask).filter(
                    ProductionTask.production_order_id == po.id
                ).all()

                for task in tasks:
                    task.scheduled_date = scheduled_date
                    tasks_updated += 1

            # Get line item count for orders without work orders
            line_items = self.db.query(SalesOrderLineItem).filter(
                SalesOrderLineItem.sales_order_id == sales_order.id
            ).all()

            self.db.commit()

            # Build appropriate message based on whether there are work orders
            if prod_orders:
                message = f"Scheduled {sales_order.bc_order_number} ({sales_order.customer_name}) to {target_date}. {len(prod_orders)} work orders with {tasks_updated} tasks scheduled."
            else:
                message = f"Scheduled {sales_order.bc_order_number} ({sales_order.customer_name}) to {target_date} for picking/packing. {len(line_items)} line items to fulfill."

            return {
                "success": True,
                "salesOrderId": sales_order.id,
                "bcOrderNumber": sales_order.bc_order_number,
                "customerName": sales_order.customer_name,
                "scheduledDate": target_date,
                "productionOrdersUpdated": len(prod_orders),
                "tasksUpdated": tasks_updated,
                "lineItemCount": len(line_items),
                "hasWorkOrders": len(prod_orders) > 0,
                "message": message
            }

        except Exception as e:
            self.db.rollback()
            logger.error(f"Error scheduling order: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e)
            }

    async def unschedule_order(self, order_identifier: str) -> Dict[str, Any]:
        """
        Remove a sales order from the production schedule.

        Args:
            order_identifier: Sales order ID or BC order number

        Returns:
            Result with success status and details
        """
        try:
            # Find the sales order
            sales_order = None

            try:
                order_id = int(order_identifier)
                sales_order = self.db.query(SalesOrder).filter(
                    SalesOrder.id == order_id
                ).first()
            except ValueError:
                pass

            if not sales_order:
                sales_order = self.db.query(SalesOrder).filter(
                    SalesOrder.bc_order_number == order_identifier
                ).first()

            if not sales_order and not order_identifier.startswith("SO-"):
                sales_order = self.db.query(SalesOrder).filter(
                    SalesOrder.bc_order_number == f"SO-{order_identifier}"
                ).first()

            if not sales_order:
                return {
                    "success": False,
                    "error": f"Sales order '{order_identifier}' not found"
                }

            # Clear scheduled_date on the sales order itself
            sales_order.scheduled_date = None

            # Get all production orders
            prod_orders = self.db.query(ProductionOrder).filter(
                ProductionOrder.sales_order_id == sales_order.id
            ).all()

            # Clear scheduled_date for all tasks
            tasks_updated = 0
            for po in prod_orders:
                tasks = self.db.query(ProductionTask).filter(
                    ProductionTask.production_order_id == po.id
                ).all()

                for task in tasks:
                    task.scheduled_date = None
                    tasks_updated += 1

            self.db.commit()

            if prod_orders:
                message = f"Removed {sales_order.bc_order_number} from schedule. {tasks_updated} tasks unscheduled."
            else:
                message = f"Removed {sales_order.bc_order_number} from picking/packing schedule."

            return {
                "success": True,
                "salesOrderId": sales_order.id,
                "bcOrderNumber": sales_order.bc_order_number,
                "tasksUpdated": tasks_updated,
                "message": message
            }

        except Exception as e:
            self.db.rollback()
            logger.error(f"Error unscheduling order: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e)
            }

    async def get_order_details(self, order_identifier: str) -> Dict[str, Any]:
        """
        Get detailed information about a sales order.

        Args:
            order_identifier: Sales order ID or BC order number

        Returns:
            Order details including line items and work orders
        """
        try:
            # Find the sales order
            sales_order = None

            try:
                order_id = int(order_identifier)
                sales_order = self.db.query(SalesOrder).filter(
                    SalesOrder.id == order_id
                ).first()
            except ValueError:
                pass

            if not sales_order:
                sales_order = self.db.query(SalesOrder).filter(
                    SalesOrder.bc_order_number == order_identifier
                ).first()

            if not sales_order and not order_identifier.startswith("SO-"):
                sales_order = self.db.query(SalesOrder).filter(
                    SalesOrder.bc_order_number == f"SO-{order_identifier}"
                ).first()

            if not sales_order:
                return {
                    "success": False,
                    "error": f"Sales order '{order_identifier}' not found"
                }

            # Get line items
            line_items = self.db.query(SalesOrderLineItem).filter(
                SalesOrderLineItem.sales_order_id == sales_order.id
            ).all()

            # Get production orders with task counts
            prod_orders = self.db.query(ProductionOrder).filter(
                ProductionOrder.sales_order_id == sales_order.id
            ).all()

            work_orders_data = []
            total_tasks = 0
            completed_tasks = 0
            scheduled_tasks = 0

            for po in prod_orders:
                tasks = self.db.query(ProductionTask).filter(
                    ProductionTask.production_order_id == po.id
                ).all()

                po_completed = sum(1 for t in tasks if t.status.value == "completed")
                po_scheduled = sum(1 for t in tasks if t.scheduled_date is not None)

                total_tasks += len(tasks)
                completed_tasks += po_completed
                scheduled_tasks += po_scheduled

                scheduled_date = None
                if tasks and tasks[0].scheduled_date:
                    scheduled_date = tasks[0].scheduled_date.strftime("%Y-%m-%d")

                work_orders_data.append({
                    "id": po.id,
                    "bcProdOrderNumber": po.bc_prod_order_number,
                    "itemCode": po.item_code,
                    "itemDescription": po.item_description,
                    "quantity": po.quantity,
                    "status": po.status.value if po.status else "unknown",
                    "taskCount": len(tasks),
                    "completedTasks": po_completed,
                    "scheduledDate": scheduled_date
                })

            return {
                "success": True,
                "order": {
                    "id": sales_order.id,
                    "bcOrderNumber": sales_order.bc_order_number,
                    "customerName": sales_order.customer_name,
                    "customerNumber": sales_order.customer_number,
                    "customerEmail": sales_order.customer_email,
                    "status": sales_order.status.value if sales_order.status else "unknown",
                    "totalAmount": float(sales_order.total_amount) if sales_order.total_amount else None,
                    "orderDate": sales_order.order_date.strftime("%Y-%m-%d") if sales_order.order_date else None,
                    "lineItemCount": len(line_items),
                    "workOrderCount": len(work_orders_data),
                    "totalTasks": total_tasks,
                    "completedTasks": completed_tasks,
                    "scheduledTasks": scheduled_tasks,
                    "isFullyScheduled": scheduled_tasks == total_tasks and total_tasks > 0,
                    "workOrders": work_orders_data
                }
            }

        except Exception as e:
            logger.error(f"Error getting order details: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e)
            }

    async def list_unscheduled_orders(self) -> Dict[str, Any]:
        """
        Get a list of all sales orders that have not yet been scheduled.

        Includes:
        - Orders with work orders that have unscheduled tasks
        - Orders without work orders that haven't been scheduled for picking/packing

        Returns:
            List of unscheduled orders with basic info
        """
        try:
            # Get all sales orders that are not completed/cancelled
            sales_orders = self.db.query(SalesOrder).filter(
                SalesOrder.status.notin_([OrderStatus.COMPLETED, OrderStatus.CANCELLED])
            ).all()

            unscheduled = []
            for so in sales_orders:
                # Get production orders
                prod_orders = self.db.query(ProductionOrder).filter(
                    ProductionOrder.sales_order_id == so.id
                ).all()

                # Get line items
                line_items = self.db.query(SalesOrderLineItem).filter(
                    SalesOrderLineItem.sales_order_id == so.id
                ).all()

                if prod_orders:
                    # Has work orders - check if tasks are scheduled
                    total_tasks = 0
                    scheduled_tasks = 0

                    for po in prod_orders:
                        tasks = self.db.query(ProductionTask).filter(
                            ProductionTask.production_order_id == po.id
                        ).all()
                        total_tasks += len(tasks)
                        scheduled_tasks += sum(1 for t in tasks if t.scheduled_date is not None)

                    # Only include if not fully scheduled
                    if scheduled_tasks < total_tasks:
                        unscheduled.append({
                            "id": so.id,
                            "bcOrderNumber": so.bc_order_number,
                            "customerName": so.customer_name,
                            "totalAmount": float(so.total_amount) if so.total_amount else None,
                            "workOrderCount": len(prod_orders),
                            "lineItemCount": len(line_items),
                            "totalTasks": total_tasks,
                            "scheduledTasks": scheduled_tasks,
                            "unscheduledTasks": total_tasks - scheduled_tasks,
                            "hasWorkOrders": True,
                            "type": "production"
                        })
                else:
                    # No work orders - check if order itself is scheduled
                    if so.scheduled_date is None and len(line_items) > 0:
                        unscheduled.append({
                            "id": so.id,
                            "bcOrderNumber": so.bc_order_number,
                            "customerName": so.customer_name,
                            "totalAmount": float(so.total_amount) if so.total_amount else None,
                            "workOrderCount": 0,
                            "lineItemCount": len(line_items),
                            "totalTasks": 0,
                            "scheduledTasks": 0,
                            "unscheduledTasks": 0,
                            "hasWorkOrders": False,
                            "type": "pick_pack"
                        })

            return {
                "success": True,
                "count": len(unscheduled),
                "orders": unscheduled,
                "message": f"Found {len(unscheduled)} orders needing scheduling."
            }

        except Exception as e:
            logger.error(f"Error listing unscheduled orders: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e)
            }

    async def get_schedule_for_date(self, target_date: str, date_to: Optional[str] = None) -> Dict[str, Any]:
        """
        Get all sales orders scheduled for a specific date or date range.

        Includes:
        - Orders with work orders (via production task scheduled dates)
        - Orders without work orders (via sales order scheduled_date for picking/packing)

        Args:
            target_date: Start date in YYYY-MM-DD format
            date_to: Optional end date for range

        Returns:
            List of scheduled orders for the date(s)
        """
        try:
            start_date = datetime.strptime(target_date, "%Y-%m-%d")
            end_date = datetime.strptime(date_to, "%Y-%m-%d") if date_to else start_date
            # Include full end day
            end_date_inclusive = datetime(end_date.year, end_date.month, end_date.day, 23, 59, 59)

            orders_by_date = {}

            # 1. Get orders with production tasks scheduled in this date range
            scheduled_tasks = self.db.query(ProductionTask).filter(
                ProductionTask.scheduled_date >= start_date,
                ProductionTask.scheduled_date <= end_date_inclusive
            ).all()

            for task in scheduled_tasks:
                if not task.scheduled_date:
                    continue

                date_str = task.scheduled_date.strftime("%Y-%m-%d")
                if date_str not in orders_by_date:
                    orders_by_date[date_str] = {}

                if task.production_order_id:
                    prod_order = self.db.query(ProductionOrder).filter(
                        ProductionOrder.id == task.production_order_id
                    ).first()

                    if prod_order and prod_order.sales_order_id:
                        sales_order = self.db.query(SalesOrder).filter(
                            SalesOrder.id == prod_order.sales_order_id
                        ).first()

                        if sales_order:
                            so_key = sales_order.id
                            if so_key not in orders_by_date[date_str]:
                                orders_by_date[date_str][so_key] = {
                                    "id": sales_order.id,
                                    "bcOrderNumber": sales_order.bc_order_number,
                                    "customerName": sales_order.customer_name,
                                    "taskCount": 0,
                                    "completedTasks": 0,
                                    "type": "production"
                                }
                            orders_by_date[date_str][so_key]["taskCount"] += 1
                            if task.status and task.status.value == "completed":
                                orders_by_date[date_str][so_key]["completedTasks"] += 1

            # 2. Get orders scheduled directly (pick/pack orders without work orders)
            direct_scheduled = self.db.query(SalesOrder).filter(
                SalesOrder.scheduled_date >= start_date,
                SalesOrder.scheduled_date <= end_date_inclusive,
                SalesOrder.status.notin_([OrderStatus.COMPLETED, OrderStatus.CANCELLED])
            ).all()

            for so in direct_scheduled:
                # Check if this order has production orders - if so, it's already included above
                prod_count = self.db.query(ProductionOrder).filter(
                    ProductionOrder.sales_order_id == so.id
                ).count()

                if prod_count == 0:  # Only include if no production orders
                    date_str = so.scheduled_date.strftime("%Y-%m-%d")
                    if date_str not in orders_by_date:
                        orders_by_date[date_str] = {}

                    # Get line item count
                    line_count = self.db.query(SalesOrderLineItem).filter(
                        SalesOrderLineItem.sales_order_id == so.id
                    ).count()

                    orders_by_date[date_str][so.id] = {
                        "id": so.id,
                        "bcOrderNumber": so.bc_order_number,
                        "customerName": so.customer_name,
                        "taskCount": 0,
                        "completedTasks": 0,
                        "lineItemCount": line_count,
                        "type": "pick_pack"
                    }

            # Format response
            result = {}
            for date_str, orders_dict in orders_by_date.items():
                result[date_str] = list(orders_dict.values())

            total_orders = sum(len(orders) for orders in result.values())

            return {
                "success": True,
                "dateFrom": target_date,
                "dateTo": date_to or target_date,
                "totalOrders": total_orders,
                "byDate": result,
                "message": f"Found {total_orders} orders scheduled between {target_date} and {date_to or target_date}."
            }

        except Exception as e:
            logger.error(f"Error getting schedule for date: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e)
            }

    async def ship_order(self, order_identifier: str) -> Dict[str, Any]:
        """
        Ship a completed sales order.

        Args:
            order_identifier: Sales order ID or BC order number

        Returns:
            Shipment result
        """
        try:
            # Find the sales order
            sales_order = None

            try:
                order_id = int(order_identifier)
                sales_order = self.db.query(SalesOrder).filter(
                    SalesOrder.id == order_id
                ).first()
            except ValueError:
                pass

            if not sales_order:
                sales_order = self.db.query(SalesOrder).filter(
                    SalesOrder.bc_order_number == order_identifier
                ).first()

            if not sales_order:
                return {
                    "success": False,
                    "error": f"Sales order '{order_identifier}' not found"
                }

            # Check if all tasks are completed
            prod_orders = self.db.query(ProductionOrder).filter(
                ProductionOrder.sales_order_id == sales_order.id
            ).all()

            total_tasks = 0
            completed_tasks = 0

            for po in prod_orders:
                tasks = self.db.query(ProductionTask).filter(
                    ProductionTask.production_order_id == po.id
                ).all()
                total_tasks += len(tasks)
                completed_tasks += sum(1 for t in tasks if t.status.value == "completed")

            if completed_tasks < total_tasks:
                return {
                    "success": False,
                    "error": f"Cannot ship order - {total_tasks - completed_tasks} tasks still incomplete"
                }

            # Update order status
            sales_order.status = OrderStatus.SHIPPED
            sales_order.shipped_at = datetime.utcnow()
            self.db.commit()

            return {
                "success": True,
                "salesOrderId": sales_order.id,
                "bcOrderNumber": sales_order.bc_order_number,
                "message": f"Shipped order {sales_order.bc_order_number} ({sales_order.customer_name}). All {total_tasks} tasks were completed."
            }

        except Exception as e:
            self.db.rollback()
            logger.error(f"Error shipping order: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e)
            }

    async def sync_from_bc(self, sync_type: str) -> Dict[str, Any]:
        """
        Synchronize data from Business Central.

        Args:
            sync_type: Type of sync - 'full', 'sales_orders', 'production_orders', 'auto_link'

        Returns:
            Sync results
        """
        try:
            from app.services.bc_sync_service import bc_sync_service

            if sync_type == "full":
                results = await bc_sync_service.full_sync(db=self.db, order_limit=200)
                return {
                    "success": True,
                    "syncType": "full",
                    "results": results,
                    "message": f"Full sync complete in {results.get('total_time_seconds', 0)}s"
                }

            elif sync_type == "sales_orders":
                results = await bc_sync_service.sync_sales_orders_with_lines(
                    db=self.db,
                    sync_all=True,
                    limit=100
                )
                return {
                    "success": True,
                    "syncType": "sales_orders",
                    "results": results,
                    "message": f"Synced {results.get('orders_synced', 0)} sales orders, {results.get('lines_synced', 0)} lines"
                }

            elif sync_type == "production_orders":
                results = await bc_sync_service.sync_production_orders(db=self.db, limit=100)
                return {
                    "success": True,
                    "syncType": "production_orders",
                    "results": results,
                    "message": f"Synced {results.get('orders_synced', 0)} production orders"
                }

            elif sync_type == "auto_link":
                results = await bc_sync_service.auto_link_production_orders(db=self.db)
                return {
                    "success": True,
                    "syncType": "auto_link",
                    "results": results,
                    "message": f"Auto-linked {results.get('linked', 0)} orders, {results.get('no_match', 0)} no match"
                }

            else:
                return {
                    "success": False,
                    "error": f"Unknown sync type: {sync_type}. Valid types: full, sales_orders, production_orders, auto_link"
                }

        except Exception as e:
            logger.error(f"Error syncing from BC: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e)
            }


# Tool definitions for Claude's tool calling format
AGENT_TOOLS = [
    {
        "name": "schedule_order",
        "description": "Schedule a sales order to a specific production date. The order will be removed from the unscheduled list and appear on the calendar.",
        "input_schema": {
            "type": "object",
            "properties": {
                "order_identifier": {
                    "type": "string",
                    "description": "The sales order ID (number) or BC order number (e.g., 'SO-000857')"
                },
                "date": {
                    "type": "string",
                    "description": "The target date in YYYY-MM-DD format"
                }
            },
            "required": ["order_identifier", "date"]
        }
    },
    {
        "name": "unschedule_order",
        "description": "Remove a sales order from the production schedule. The order will return to the unscheduled list.",
        "input_schema": {
            "type": "object",
            "properties": {
                "order_identifier": {
                    "type": "string",
                    "description": "The sales order ID or BC order number"
                }
            },
            "required": ["order_identifier"]
        }
    },
    {
        "name": "get_order_details",
        "description": "Get detailed information about a sales order including customer, line items, linked work orders, and scheduling status.",
        "input_schema": {
            "type": "object",
            "properties": {
                "order_identifier": {
                    "type": "string",
                    "description": "The sales order ID or BC order number"
                }
            },
            "required": ["order_identifier"]
        }
    },
    {
        "name": "list_unscheduled_orders",
        "description": "Get a list of all sales orders that have not yet been scheduled for production.",
        "input_schema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "get_schedule_for_date",
        "description": "Get all sales orders scheduled for a specific date or date range.",
        "input_schema": {
            "type": "object",
            "properties": {
                "date": {
                    "type": "string",
                    "description": "The date in YYYY-MM-DD format"
                },
                "date_to": {
                    "type": "string",
                    "description": "Optional end date for a range"
                }
            },
            "required": ["date"]
        }
    },
    {
        "name": "ship_order",
        "description": "Ship a completed sales order. This will update the order status to shipped. All tasks must be completed first.",
        "input_schema": {
            "type": "object",
            "properties": {
                "order_identifier": {
                    "type": "string",
                    "description": "The sales order ID or BC order number"
                }
            },
            "required": ["order_identifier"]
        }
    },
    {
        "name": "sync_from_bc",
        "description": "Synchronize data from Business Central. Use this to refresh sales orders, production orders, or run auto-linking.",
        "input_schema": {
            "type": "object",
            "properties": {
                "sync_type": {
                    "type": "string",
                    "enum": ["full", "sales_orders", "production_orders", "auto_link"],
                    "description": "Type of sync to perform"
                }
            },
            "required": ["sync_type"]
        }
    }
]
