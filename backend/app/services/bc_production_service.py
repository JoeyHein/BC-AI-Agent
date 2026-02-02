"""
BC Production Order Service

Manages production orders, scheduling, and work center capacity in Business Central.

BC OData Web Services are now available:
- ReleasedProductionOrders (Page 5405/9326)
- ProdOrderComponents (Page 99000818)
- ProdOrderRouting (Page 99000789)
- WorkCenters (Page 99000754)
- ProductionBomLines (Production BOM lines)
"""

import logging
import urllib.parse
import requests
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field
from datetime import datetime, date, timedelta
from enum import Enum

from app.integrations.bc.client import bc_client
from app.config import settings

logger = logging.getLogger(__name__)

# Configuration flag - BC OData production services are available!
PRODUCTION_API_AVAILABLE = True

# OData endpoint names (as published in BC Web Services)
ODATA_ENDPOINTS = {
    "production_orders": "ReleasedProductionOrders",
    "components": "ProdOrderComponents",
    "routing": "ProdOrderRouting",
    "work_centers": "WorkCenters",
    "bom_lines": "ProductionBomLines",
}


class ProductionOrderStatus(Enum):
    """BC Production Order status values"""
    SIMULATED = "Simulated"
    PLANNED = "Planned"
    FIRM_PLANNED = "Firm Planned"
    RELEASED = "Released"
    FINISHED = "Finished"


class SchedulePriority(Enum):
    """Production order priority levels"""
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


@dataclass
class ProductionOrder:
    """Production Order data model"""
    order_no: str = ""
    description: str = ""
    item_no: str = ""
    item_description: str = ""
    quantity: float = 0
    quantity_completed: float = 0
    quantity_remaining: float = 0
    status: ProductionOrderStatus = ProductionOrderStatus.PLANNED
    due_date: Optional[date] = None
    starting_date: Optional[date] = None
    ending_date: Optional[date] = None
    routing_no: str = ""
    production_bom_no: str = ""
    location_code: str = ""
    bin_code: str = ""
    sales_order_no: str = ""
    priority: SchedulePriority = SchedulePriority.NORMAL
    work_center_no: str = ""
    created_at: Optional[datetime] = None
    last_modified: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "orderNo": self.order_no,
            "description": self.description,
            "itemNo": self.item_no,
            "itemDescription": self.item_description,
            "quantity": self.quantity,
            "quantityCompleted": self.quantity_completed,
            "quantityRemaining": self.quantity_remaining,
            "status": self.status.value,
            "dueDate": self.due_date.isoformat() if self.due_date else None,
            "startingDate": self.starting_date.isoformat() if self.starting_date else None,
            "endingDate": self.ending_date.isoformat() if self.ending_date else None,
            "routingNo": self.routing_no,
            "productionBomNo": self.production_bom_no,
            "locationCode": self.location_code,
            "salesOrderNo": self.sales_order_no,
            "priority": self.priority.value,
            "workCenterNo": self.work_center_no
        }


@dataclass
class ProductionScheduleSlot:
    """A time slot in the production schedule"""
    date: date
    work_center: str
    available_hours: float = 8.0
    scheduled_hours: float = 0
    orders: List[ProductionOrder] = field(default_factory=list)
    utilization_percent: float = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "date": self.date.isoformat(),
            "workCenter": self.work_center,
            "availableHours": self.available_hours,
            "scheduledHours": self.scheduled_hours,
            "utilizationPercent": self.utilization_percent,
            "orders": [o.to_dict() for o in self.orders]
        }


@dataclass
class ProductionScheduleResult:
    """Result of production scheduling"""
    success: bool = False
    message: str = ""
    scheduled_orders: List[ProductionOrder] = field(default_factory=list)
    unscheduled_orders: List[ProductionOrder] = field(default_factory=list)
    schedule_slots: List[ProductionScheduleSlot] = field(default_factory=list)
    bottlenecks: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "message": self.message,
            "summary": {
                "scheduledCount": len(self.scheduled_orders),
                "unscheduledCount": len(self.unscheduled_orders),
                "bottleneckCount": len(self.bottlenecks)
            },
            "scheduledOrders": [o.to_dict() for o in self.scheduled_orders],
            "unscheduledOrders": [o.to_dict() for o in self.unscheduled_orders],
            "scheduleSlots": [s.to_dict() for s in self.schedule_slots],
            "bottlenecks": self.bottlenecks
        }


class BCProductionService:
    """
    Service for managing production orders and scheduling in Business Central.

    This service provides:
    - Production order retrieval via OData
    - Work center capacity from BC
    - Production order components and routing
    - Backward scheduling from due dates
    - Production calendar generation
    """

    def __init__(self):
        self.client = bc_client
        self.api_available = PRODUCTION_API_AVAILABLE
        self.company_name = settings.BC_COMPANY_NAME
        self.odata_base = settings.bc_odata_url

    def _get_odata_url(self, endpoint: str, query_params: Optional[Dict[str, str]] = None) -> str:
        """Build OData URL for a given endpoint"""
        encoded_company = urllib.parse.quote(self.company_name)
        url = f"{self.odata_base}/Company('{encoded_company}')/{endpoint}"
        if query_params:
            params = "&".join(f"{k}={v}" for k, v in query_params.items())
            url += f"?{params}"
        return url

    def _make_odata_request(
        self,
        endpoint: str,
        method: str = "GET",
        query_params: Optional[Dict[str, str]] = None,
        data: Optional[Dict[str, Any]] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Make an OData request to BC.

        NOTE: OData endpoints may require delegated permissions (user auth) rather than
        client credentials. If you get 401 errors, the Azure AD app registration needs
        to be updated with OData/Web Service permissions, or use device code flow.
        """
        try:
            url = self._get_odata_url(endpoint, query_params)
            token = self.client._get_access_token()

            if not token:
                logger.error("No access token available for OData request")
                return None

            headers = {
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
                "Content-Type": "application/json"
            }

            if method == "GET":
                response = requests.get(url, headers=headers, timeout=30)
            elif method == "POST":
                response = requests.post(url, headers=headers, json=data, timeout=30)
            elif method == "PATCH":
                response = requests.patch(url, headers=headers, json=data, timeout=30)
            else:
                logger.error(f"Unsupported HTTP method: {method}")
                return None

            if response.status_code in [200, 201]:
                return response.json()
            elif response.status_code == 404:
                logger.warning(f"OData endpoint not found: {endpoint}")
                return None
            elif response.status_code == 401:
                logger.warning(
                    f"OData authentication failed (401). The Azure AD app may need "
                    f"OData/Web Service permissions, or delegated auth may be required. "
                    f"Endpoint: {endpoint}"
                )
                return None
            else:
                logger.error(f"OData request failed: {response.status_code} - {response.text[:200]}")
                return None

        except Exception as e:
            logger.error(f"OData request error: {e}")
            return None

    def _check_api_available(self) -> bool:
        """Check if production API is available"""
        if not self.api_available:
            logger.warning("Production API not available - BC must expose production order endpoints")
        return self.api_available

    # ==================== Production Order CRUD ====================

    async def get_production_orders(
        self,
        status_filter: Optional[ProductionOrderStatus] = None,
        item_no: Optional[str] = None,
        date_from: Optional[date] = None,
        date_to: Optional[date] = None,
        limit: int = 100
    ) -> List[ProductionOrder]:
        """
        Get production orders from BC via OData.
        """
        if not self._check_api_available():
            logger.warning("Cannot fetch production orders - API not available")
            return []

        try:
            # Build OData filter
            filters = []
            if status_filter:
                filters.append(f"Status eq '{status_filter.value}'")
            if item_no:
                filters.append(f"Source_No eq '{item_no}'")
            if date_from:
                filters.append(f"Due_Date ge {date_from.isoformat()}")
            if date_to:
                filters.append(f"Due_Date le {date_to.isoformat()}")

            query_params = {"$top": str(limit)}
            if filters:
                query_params["$filter"] = " and ".join(filters)

            response = self._make_odata_request(
                ODATA_ENDPOINTS["production_orders"],
                query_params=query_params
            )

            if not response or "value" not in response:
                return []

            orders = []
            for item in response["value"]:
                order = ProductionOrder(
                    order_no=item.get("No", ""),
                    description=item.get("Description", ""),
                    item_no=item.get("Source_No", ""),
                    item_description=item.get("Description", ""),
                    quantity=float(item.get("Quantity", 0)),
                    status=self._parse_status(item.get("Status", "")),
                    due_date=self._parse_date(item.get("Due_Date")),
                    starting_date=self._parse_date(item.get("Starting_Date_Time")),
                    ending_date=self._parse_date(item.get("Ending_Date_Time")),
                    routing_no=item.get("Routing_No", ""),
                    location_code=item.get("Location_Code", "")
                )
                orders.append(order)

            logger.info(f"Fetched {len(orders)} production orders from BC")
            return orders

        except Exception as e:
            logger.error(f"Error fetching production orders: {e}")
            return []

    def _parse_status(self, status_str: str) -> ProductionOrderStatus:
        """Parse BC status string to enum"""
        status_map = {
            "Simulated": ProductionOrderStatus.SIMULATED,
            "Planned": ProductionOrderStatus.PLANNED,
            "Firm Planned": ProductionOrderStatus.FIRM_PLANNED,
            "Released": ProductionOrderStatus.RELEASED,
            "Finished": ProductionOrderStatus.FINISHED,
        }
        return status_map.get(status_str, ProductionOrderStatus.PLANNED)

    async def get_production_order(self, order_no: str) -> Optional[ProductionOrder]:
        """Get a specific production order by number"""
        if not self._check_api_available():
            return None

        try:
            # TODO: Implement when API available
            return None
        except Exception as e:
            logger.error(f"Error fetching production order {order_no}: {e}")
            return None

    async def create_production_order(
        self,
        item_no: str,
        quantity: float,
        due_date: date,
        status: ProductionOrderStatus = ProductionOrderStatus.FIRM_PLANNED,
        sales_order_no: Optional[str] = None,
        location_code: str = "",
        priority: SchedulePriority = SchedulePriority.NORMAL
    ) -> Optional[ProductionOrder]:
        """
        Create a new production order in BC.

        Args:
            item_no: Item number to produce
            quantity: Quantity to produce
            due_date: Required completion date
            status: Initial status (default: Firm Planned)
            sales_order_no: Link to sales order if applicable
            location_code: Production location
            priority: Scheduling priority

        Returns:
            Created ProductionOrder or None if failed
        """
        if not self._check_api_available():
            logger.error("Cannot create production order - API not available")
            return None

        try:
            # Calculate start date using backward scheduling
            lead_time_days = self._estimate_lead_time(item_no)
            starting_date = due_date - timedelta(days=lead_time_days)

            order_data = {
                "Source_Type": "Item",
                "Source_No": item_no,
                "Quantity": quantity,
                "Due_Date": due_date.isoformat(),
                "Starting_Date": starting_date.isoformat(),
                "Status": status.value,
                "Location_Code": location_code
            }

            if sales_order_no:
                order_data["Description"] = f"For Sales Order {sales_order_no}"

            # TODO: Make actual API call when endpoint is available
            # response = self.client._make_request("POST", endpoint, json=order_data)

            logger.info(f"Would create production order for {item_no} x {quantity} due {due_date}")
            return None

        except Exception as e:
            logger.error(f"Error creating production order: {e}")
            return None

    async def release_production_order(self, order_no: str) -> bool:
        """
        Release a production order (change status from Firm Planned to Released).

        This makes the order available for shop floor processing.
        """
        if not self._check_api_available():
            return False

        try:
            # TODO: Implement when API available
            # This typically uses a bound action: Microsoft.NAV.release
            return False
        except Exception as e:
            logger.error(f"Error releasing production order {order_no}: {e}")
            return False

    async def finish_production_order(self, order_no: str) -> bool:
        """
        Finish a production order (mark as completed).

        This updates inventory with produced quantity.
        Uses the BC OData bound action Microsoft.NAV.finish
        """
        if not self._check_api_available():
            logger.warning(f"Cannot finish production order {order_no} - API not available")
            return False

        try:
            # Build the URL for the finish action
            # POST /companies({companyId})/releasedProductionOrders(No='{order_no}')/Microsoft.NAV.finish
            encoded_company = urllib.parse.quote(self.company_name)
            url = f"{self.odata_base}/Company('{encoded_company}')/ReleasedProductionOrders(No='{order_no}')/Microsoft.NAV.finish"

            token = self.client._get_access_token()
            if not token:
                logger.error("No access token available for finish action")
                return False

            headers = {
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
                "Content-Type": "application/json"
            }

            response = requests.post(url, headers=headers, timeout=30)

            if response.status_code in [200, 204]:
                logger.info(f"Successfully finished production order {order_no}")
                return True
            elif response.status_code == 404:
                logger.warning(f"Production order not found: {order_no}")
                return False
            else:
                logger.error(f"Failed to finish production order {order_no}: {response.status_code} - {response.text[:200]}")
                return False

        except Exception as e:
            logger.error(f"Error finishing production order {order_no}: {e}")
            return False

    async def ship_sales_order(self, sales_order_id: str) -> Dict[str, Any]:
        """
        Ship a sales order in BC.

        Uses the BC OData bound action Microsoft.NAV.ship
        Returns shipment details including the shipment number.
        """
        if not self._check_api_available():
            logger.warning(f"Cannot ship sales order {sales_order_id} - API not available")
            return {"success": False, "error": "API not available"}

        try:
            # Build the URL for the ship action
            # POST /companies({companyId})/salesOrders({id})/Microsoft.NAV.ship
            encoded_company = urllib.parse.quote(self.company_name)
            url = f"{self.odata_base}/Company('{encoded_company}')/salesOrders({sales_order_id})/Microsoft.NAV.ship"

            token = self.client._get_access_token()
            if not token:
                logger.error("No access token available for ship action")
                return {"success": False, "error": "No access token"}

            headers = {
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
                "Content-Type": "application/json"
            }

            response = requests.post(url, headers=headers, timeout=30)

            if response.status_code in [200, 201, 204]:
                result = response.json() if response.text else {}
                shipment_number = result.get("number", result.get("shipmentNumber", f"SS-{sales_order_id}"))
                logger.info(f"Successfully shipped sales order {sales_order_id}, shipment: {shipment_number}")
                return {
                    "success": True,
                    "shipmentNumber": shipment_number,
                    "data": result
                }
            elif response.status_code == 404:
                logger.warning(f"Sales order not found: {sales_order_id}")
                return {"success": False, "error": "Sales order not found"}
            else:
                logger.error(f"Failed to ship sales order {sales_order_id}: {response.status_code} - {response.text[:200]}")
                return {"success": False, "error": f"BC API error: {response.status_code}"}

        except Exception as e:
            logger.error(f"Error shipping sales order {sales_order_id}: {e}")
            return {"success": False, "error": str(e)}

    async def get_components_with_availability(
        self,
        prod_order_no: str
    ) -> List[Dict[str, Any]]:
        """
        Get production order components with inventory availability.

        Combines component data with current inventory levels.
        """
        components = await self.get_production_order_components(prod_order_no=prod_order_no)

        for comp in components:
            item_no = comp.get("itemNo", "")
            if item_no:
                # Get inventory for this item
                inventory = await self._get_item_inventory(item_no)
                comp["inventoryAvailable"] = inventory.get("available", 0)
                comp["inventoryNeeded"] = comp.get("quantityPer", 0)

                # Calculate availability status
                available = comp["inventoryAvailable"]
                needed = comp["inventoryNeeded"]
                if available >= needed:
                    comp["availabilityStatus"] = "sufficient"
                elif available > 0:
                    comp["availabilityStatus"] = "partial"
                else:
                    comp["availabilityStatus"] = "unavailable"
            else:
                comp["inventoryAvailable"] = 0
                comp["availabilityStatus"] = "unknown"

        return components

    async def _get_item_inventory(self, item_no: str) -> Dict[str, Any]:
        """Get inventory level for a specific item from BC."""
        try:
            # Query items endpoint for inventory
            encoded_company = urllib.parse.quote(self.company_name)
            url = f"{self.odata_base}/Company('{encoded_company}')/items"
            query_params = {"$filter": f"number eq '{item_no}'", "$select": "number,inventory"}

            response = self._make_odata_request("items", query_params=query_params)

            if response and "value" in response and len(response["value"]) > 0:
                item = response["value"][0]
                return {"available": float(item.get("inventory", 0))}

            return {"available": 0}

        except Exception as e:
            logger.error(f"Error getting inventory for {item_no}: {e}")
            return {"available": 0}

    # ==================== Scheduling ====================

    def calculate_schedule(
        self,
        orders_to_schedule: List[Dict[str, Any]],
        start_date: date,
        end_date: date,
        work_center_capacity: float = 8.0  # hours per day
    ) -> ProductionScheduleResult:
        """
        Calculate production schedule using backward scheduling.

        This method works even without BC API access - it performs
        schedule calculation locally based on provided order data.

        Args:
            orders_to_schedule: List of orders with itemNo, quantity, dueDate
            start_date: Schedule window start
            end_date: Schedule window end
            work_center_capacity: Available hours per day

        Returns:
            ProductionScheduleResult with scheduled orders and calendar
        """
        result = ProductionScheduleResult()

        try:
            # Convert input to ProductionOrder objects
            orders = []
            for order_data in orders_to_schedule:
                order = ProductionOrder(
                    item_no=order_data.get("itemNo", ""),
                    quantity=float(order_data.get("quantity", 1)),
                    due_date=self._parse_date(order_data.get("dueDate")),
                    sales_order_no=order_data.get("salesOrderNo", ""),
                    priority=SchedulePriority(order_data.get("priority", "normal"))
                )
                orders.append(order)

            # Sort by due date and priority (urgent first)
            priority_order = {
                SchedulePriority.URGENT: 0,
                SchedulePriority.HIGH: 1,
                SchedulePriority.NORMAL: 2,
                SchedulePriority.LOW: 3
            }
            orders.sort(key=lambda o: (o.due_date or date.max, priority_order[o.priority]))

            # Create schedule slots
            current_date = start_date
            slots_by_date: Dict[date, ProductionScheduleSlot] = {}

            while current_date <= end_date:
                # Skip weekends
                if current_date.weekday() < 5:  # Monday = 0, Friday = 4
                    slots_by_date[current_date] = ProductionScheduleSlot(
                        date=current_date,
                        work_center="MAIN",  # Default work center
                        available_hours=work_center_capacity
                    )
                current_date += timedelta(days=1)

            # Backward schedule each order
            for order in orders:
                if not order.due_date:
                    result.unscheduled_orders.append(order)
                    continue

                # Calculate required hours (simplified - 1 hour per unit)
                required_hours = self._calculate_production_hours(order.item_no, order.quantity)

                # Find starting slot using backward scheduling
                scheduled = self._backward_schedule_order(
                    order, slots_by_date, required_hours, order.due_date
                )

                if scheduled:
                    result.scheduled_orders.append(order)
                else:
                    result.unscheduled_orders.append(order)
                    result.bottlenecks.append({
                        "orderItemNo": order.item_no,
                        "orderQuantity": order.quantity,
                        "dueDate": order.due_date.isoformat() if order.due_date else None,
                        "reason": "Insufficient capacity before due date"
                    })

            # Finalize slots
            for slot_date, slot in slots_by_date.items():
                slot.utilization_percent = (slot.scheduled_hours / slot.available_hours * 100) if slot.available_hours > 0 else 0
                result.schedule_slots.append(slot)

            result.schedule_slots.sort(key=lambda s: s.date)
            result.success = len(result.unscheduled_orders) == 0
            result.message = f"Scheduled {len(result.scheduled_orders)} orders" + (
                f", {len(result.unscheduled_orders)} could not be scheduled" if result.unscheduled_orders else ""
            )

        except Exception as e:
            logger.error(f"Error calculating schedule: {e}")
            result.success = False
            result.message = f"Scheduling error: {str(e)}"

        return result

    def _backward_schedule_order(
        self,
        order: ProductionOrder,
        slots: Dict[date, ProductionScheduleSlot],
        required_hours: float,
        due_date: date
    ) -> bool:
        """
        Backward schedule an order from its due date.

        Starts from due date and works backward to find available capacity.
        """
        remaining_hours = required_hours
        scheduled_dates = []

        # Start from day before due date (due date is completion date)
        current_date = due_date - timedelta(days=1)
        min_date = min(slots.keys()) if slots else date.min

        while remaining_hours > 0 and current_date >= min_date:
            if current_date in slots:
                slot = slots[current_date]
                available = slot.available_hours - slot.scheduled_hours

                if available > 0:
                    hours_to_schedule = min(available, remaining_hours)
                    slot.scheduled_hours += hours_to_schedule
                    slot.orders.append(order)
                    remaining_hours -= hours_to_schedule
                    scheduled_dates.append(current_date)

            current_date -= timedelta(days=1)

        if remaining_hours <= 0 and scheduled_dates:
            order.starting_date = min(scheduled_dates)
            order.ending_date = max(scheduled_dates)
            return True

        return False

    # ==================== Helper Methods ====================

    def _estimate_lead_time(self, item_no: str) -> int:
        """Estimate production lead time in days for an item"""
        # Hardware kits: 3 days
        if item_no.startswith("HK"):
            return 3
        # Panels: 5 days
        elif item_no.startswith("PN"):
            return 5
        # Springs: 2 days
        elif item_no.startswith("SP"):
            return 2
        # Door assemblies: 7 days
        elif item_no.startswith("DR"):
            return 7
        # Default
        return 5

    def _calculate_production_hours(self, item_no: str, quantity: float) -> float:
        """Calculate production hours needed for an item"""
        # Simplified calculation - would come from BC routing
        if item_no.startswith("HK"):
            return quantity * 0.5  # 30 min per hardware kit
        elif item_no.startswith("PN"):
            return quantity * 0.25  # 15 min per panel
        elif item_no.startswith("SP"):
            return quantity * 0.1  # 6 min per spring
        elif item_no.startswith("DR"):
            return quantity * 2.0  # 2 hours per door
        return quantity * 0.5  # Default 30 min per unit

    def _parse_date(self, date_value: Any) -> Optional[date]:
        """Parse various date formats"""
        if not date_value:
            return None
        if isinstance(date_value, date):
            return date_value
        if isinstance(date_value, datetime):
            return date_value.date()
        if isinstance(date_value, str):
            try:
                return datetime.fromisoformat(date_value.replace('Z', '+00:00')).date()
            except:
                return None
        return None

    # ==================== Work Center Capacity ====================

    async def get_work_centers(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Get work centers from BC via OData"""
        if not self._check_api_available():
            return []

        try:
            response = self._make_odata_request(
                ODATA_ENDPOINTS["work_centers"],
                query_params={"$top": str(limit)}
            )

            if not response or "value" not in response:
                return []

            work_centers = []
            for item in response["value"]:
                work_centers.append({
                    "no": item.get("No", ""),
                    "name": item.get("Name", ""),
                    "groupCode": item.get("Work_Center_Group_Code", ""),
                    "type": item.get("Type", ""),
                    "blocked": item.get("Blocked", False),
                    "startingTime": item.get("Starting_Time", ""),
                    "endingTime": item.get("Ending_Time", ""),
                    "directUnitCost": item.get("Direct_Unit_Cost", 0),
                    "unitCost": item.get("Unit_Cost", 0),
                })

            logger.info(f"Fetched {len(work_centers)} work centers from BC")
            return work_centers

        except Exception as e:
            logger.error(f"Error fetching work centers: {e}")
            return []

    async def get_production_order_components(
        self,
        prod_order_no: Optional[str] = None,
        limit: int = 500
    ) -> List[Dict[str, Any]]:
        """Get production order components from BC via OData"""
        if not self._check_api_available():
            return []

        try:
            query_params = {"$top": str(limit)}
            if prod_order_no:
                query_params["$filter"] = f"Prod_Order_No eq '{prod_order_no}'"

            response = self._make_odata_request(
                ODATA_ENDPOINTS["components"],
                query_params=query_params
            )

            if not response or "value" not in response:
                return []

            components = []
            for item in response["value"]:
                components.append({
                    "prodOrderNo": item.get("Prod_Order_No", ""),
                    "lineNo": item.get("Line_No", 0),
                    "itemNo": item.get("Item_No", ""),
                    "description": item.get("Description", ""),
                    "quantityPer": item.get("Quantity_per", 0),
                    "dueDate": item.get("Due_Date", ""),
                    "status": item.get("Status", ""),
                })

            return components

        except Exception as e:
            logger.error(f"Error fetching production order components: {e}")
            return []

    async def get_production_order_routing(
        self,
        prod_order_no: Optional[str] = None,
        limit: int = 500
    ) -> List[Dict[str, Any]]:
        """Get production order routing from BC via OData"""
        if not self._check_api_available():
            return []

        try:
            query_params = {"$top": str(limit)}
            # Note: ProdOrderRouting might need different filter field

            response = self._make_odata_request(
                ODATA_ENDPOINTS["routing"],
                query_params=query_params
            )

            if not response or "value" not in response:
                return []

            routing = []
            for item in response["value"]:
                routing.append({
                    "productionBomNo": item.get("Production_BOM_No", ""),
                    "lineNo": item.get("Line_No", 0),
                    "type": item.get("Type", ""),
                    "no": item.get("No", ""),
                    "description": item.get("Description", ""),
                    "quantityPer": item.get("Quantity_per", 0),
                    "unitOfMeasure": item.get("Unit_of_Measure_Code", ""),
                    "routingLinkCode": item.get("Routing_Link_Code", ""),
                })

            return routing

        except Exception as e:
            logger.error(f"Error fetching production order routing: {e}")
            return []

    async def get_work_center_capacity(
        self,
        work_center_no: Optional[str] = None,
        date_from: Optional[date] = None,
        date_to: Optional[date] = None
    ) -> List[Dict[str, Any]]:
        """
        Get work center capacity from BC.

        Combines work center data with calculated capacity based on
        starting/ending times.
        """
        if not self._check_api_available():
            return self._get_simulated_capacity(date_from, date_to)

        try:
            # Get work centers from BC
            work_centers = await self.get_work_centers()

            if not work_centers:
                return self._get_simulated_capacity(date_from, date_to)

            # Build capacity data from work centers
            start = date_from or date.today()
            end = date_to or (start + timedelta(days=30))

            capacity = []
            current = start
            while current <= end:
                if current.weekday() < 5:  # Weekdays only
                    for wc in work_centers:
                        if not wc.get("blocked", False):
                            # Calculate available hours from starting/ending time
                            # Default to 8 hours if times not parseable
                            available_hours = 8.0
                            try:
                                start_time = wc.get("startingTime", "07:00:00")
                                end_time = wc.get("endingTime", "15:00:00")
                                if start_time and end_time:
                                    start_parts = start_time.split(":")
                                    end_parts = end_time.split(":")
                                    start_hours = int(start_parts[0]) + int(start_parts[1]) / 60
                                    end_hours = int(end_parts[0]) + int(end_parts[1]) / 60
                                    available_hours = end_hours - start_hours
                            except:
                                pass

                            capacity.append({
                                "date": current.isoformat(),
                                "workCenter": wc.get("no", "MAIN"),
                                "workCenterName": wc.get("name", ""),
                                "availableHours": available_hours,
                                "efficiency": 0.9
                            })
                current += timedelta(days=1)

            return capacity

        except Exception as e:
            logger.error(f"Error fetching work center capacity: {e}")
            return self._get_simulated_capacity(date_from, date_to)

    def _get_simulated_capacity(
        self,
        date_from: Optional[date] = None,
        date_to: Optional[date] = None
    ) -> List[Dict[str, Any]]:
        """Return simulated capacity data for testing"""
        start = date_from or date.today()
        end = date_to or (start + timedelta(days=30))

        capacity = []
        current = start
        while current <= end:
            if current.weekday() < 5:  # Weekdays only
                capacity.append({
                    "date": current.isoformat(),
                    "workCenter": "MAIN",
                    "availableHours": 8.0,
                    "efficiency": 0.9
                })
            current += timedelta(days=1)

        return capacity


# Global instance
bc_production_service = BCProductionService()
