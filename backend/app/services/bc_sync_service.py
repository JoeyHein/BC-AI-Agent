"""
BC Data Sync Service

Syncs data from Business Central to local database:
- Sales Orders with Line Items
- Production Orders
- Customers
- Auto-links production orders to sales order lines by item number
"""

import logging
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime, date
from sqlalchemy.orm import Session
from sqlalchemy import and_

from app.integrations.bc.client import bc_client
from app.config import settings
from app.db.models import (
    SalesOrder, SalesOrderLineItem, ProductionOrder,
    OrderStatus, ProductionStatus, BCCustomer, AppSettings
)
from app.services.pricing_service import BC_GROUP_MAPPING_KEY

logger = logging.getLogger(__name__)


class BCSyncService:
    """Service for syncing BC data to local database"""

    def __init__(self):
        self.client = bc_client
        self.company_id = settings.BC_COMPANY_ID

    def _get_headers(self) -> Dict[str, str]:
        """Get authorization headers"""
        token = self.client._get_access_token()
        return {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json"
        }

    # ==================== Sales Orders Sync ====================

    async def sync_sales_orders_with_lines(
        self,
        db: Session,
        order_numbers: Optional[List[str]] = None,
        sync_all: bool = False,
        limit: int = 100
    ) -> Dict[str, Any]:
        """
        Sync sales orders and their line items from BC.

        Args:
            db: Database session
            order_numbers: Specific order numbers to sync (e.g., ['SO-000857'])
            sync_all: If True, sync all open orders
            limit: Maximum number of orders to sync

        Returns:
            Summary of sync results
        """
        import requests

        base_url = settings.bc_api_url
        headers = self._get_headers()

        results = {
            "orders_synced": 0,
            "orders_updated": 0,
            "lines_synced": 0,
            "lines_updated": 0,
            "errors": []
        }

        try:
            # Build the query
            if order_numbers:
                # Sync specific orders
                for order_no in order_numbers:
                    url = f"{base_url}/companies({self.company_id})/salesOrders?$filter=number eq '{order_no}'&$expand=salesOrderLines"
                    response = requests.get(url, headers=headers, timeout=60)

                    if response.status_code == 200:
                        data = response.json()
                        for order in data.get("value", []):
                            await self._sync_single_order(db, order, results)
                    else:
                        results["errors"].append(f"Failed to fetch {order_no}: {response.status_code}")

            elif sync_all:
                # Sync all orders (paginated)
                url = f"{base_url}/companies({self.company_id})/salesOrders?$top={limit}&$expand=salesOrderLines&$orderby=orderDate desc"
                response = requests.get(url, headers=headers, timeout=120)

                if response.status_code == 200:
                    data = response.json()
                    for order in data.get("value", []):
                        await self._sync_single_order(db, order, results)
                else:
                    results["errors"].append(f"Failed to fetch orders: {response.status_code}")

            db.commit()
            logger.info(f"Sales order sync complete: {results['orders_synced']} orders, {results['lines_synced']} lines")

        except Exception as e:
            db.rollback()
            logger.error(f"Sales order sync error: {e}")
            results["errors"].append(str(e))

        return results

    async def _sync_single_order(
        self,
        db: Session,
        bc_order: Dict[str, Any],
        results: Dict[str, Any]
    ):
        """Sync a single sales order and its lines"""

        bc_order_number = bc_order.get("number")
        bc_id = bc_order.get("id")

        # Check if order exists
        existing = db.query(SalesOrder).filter(
            SalesOrder.bc_order_number == bc_order_number
        ).first()

        if existing:
            # Update existing order
            existing.customer_name = bc_order.get("customerName")
            existing.customer_number = bc_order.get("customerNumber")
            existing.bc_customer_id = bc_order.get("customerId")
            existing.total_amount = bc_order.get("totalAmountIncludingTax", 0)
            existing.order_date = self._parse_date(bc_order.get("orderDate"))
            existing.requested_delivery_date = self._parse_date(bc_order.get("requestedDeliveryDate"))
            existing.last_synced_at = datetime.utcnow()
            sales_order = existing
            results["orders_updated"] += 1
        else:
            # Create new order
            sales_order = SalesOrder(
                bc_order_number=bc_order_number,
                bc_id=bc_id,
                customer_name=bc_order.get("customerName"),
                customer_number=bc_order.get("customerNumber"),
                bc_customer_id=bc_order.get("customerId"),
                customer_email=bc_order.get("email"),
                total_amount=bc_order.get("totalAmountIncludingTax", 0),
                status=OrderStatus.PENDING,
                order_date=self._parse_date(bc_order.get("orderDate")),
                requested_delivery_date=self._parse_date(bc_order.get("requestedDeliveryDate")),
                shipping_address=self._build_address(bc_order, "shipTo"),
                billing_address=self._build_address(bc_order, "billTo"),
                last_synced_at=datetime.utcnow()
            )
            db.add(sales_order)
            db.flush()  # Get the ID
            results["orders_synced"] += 1

        # Sync line items
        bc_lines = bc_order.get("salesOrderLines", [])
        await self._sync_order_lines(db, sales_order, bc_lines, bc_order_number, results)

    async def _sync_order_lines(
        self,
        db: Session,
        sales_order: SalesOrder,
        bc_lines: List[Dict[str, Any]],
        bc_order_number: str,
        results: Dict[str, Any]
    ):
        """Sync line items for a sales order"""

        # Get existing line items for this order
        existing_lines = {
            line.bc_line_no: line
            for line in db.query(SalesOrderLineItem).filter(
                SalesOrderLineItem.sales_order_id == sales_order.id
            ).all()
        }

        for bc_line in bc_lines:
            bc_line_no = bc_line.get("sequence", 0)

            if bc_line_no in existing_lines:
                # Update existing line
                line = existing_lines[bc_line_no]
                line.item_no = bc_line.get("lineObjectNumber") or None
                line.description = bc_line.get("description")
                line.quantity = bc_line.get("quantity", 0)
                line.unit_of_measure = bc_line.get("unitOfMeasureCode")
                line.unit_price = bc_line.get("unitPrice", 0)
                line.line_amount = bc_line.get("amountExcludingTax", 0)
                line.line_type = bc_line.get("lineType", "Item")
                line.last_synced_at = datetime.utcnow()
                results["lines_updated"] += 1
            else:
                # Create new line
                line = SalesOrderLineItem(
                    sales_order_id=sales_order.id,
                    bc_line_no=bc_line_no,
                    bc_document_no=bc_order_number,
                    item_no=bc_line.get("lineObjectNumber") or None,
                    description=bc_line.get("description"),
                    quantity=bc_line.get("quantity", 0),
                    unit_of_measure=bc_line.get("unitOfMeasureCode"),
                    unit_price=bc_line.get("unitPrice", 0),
                    line_amount=bc_line.get("amountExcludingTax", 0),
                    line_type=bc_line.get("lineType", "Item"),
                    last_synced_at=datetime.utcnow()
                )
                db.add(line)
                results["lines_synced"] += 1

    # ==================== Production Orders Sync ====================

    async def sync_production_orders(
        self,
        db: Session,
        limit: int = 100
    ) -> Dict[str, Any]:
        """
        Sync production orders from BC OData endpoint.
        """
        import requests
        import urllib.parse

        odata_base = settings.bc_odata_url
        company_name = settings.BC_COMPANY_NAME
        encoded_company = urllib.parse.quote(company_name)
        headers = self._get_headers()

        results = {
            "orders_synced": 0,
            "orders_updated": 0,
            "errors": []
        }

        try:
            url = f"{odata_base}/Company('{encoded_company}')/ReleasedProductionOrders?$top={limit}"
            response = requests.get(url, headers=headers, timeout=60)

            if response.status_code == 200:
                data = response.json()
                for bc_order in data.get("value", []):
                    await self._sync_single_production_order(db, bc_order, results)

                db.commit()
                logger.info(f"Production order sync complete: {results['orders_synced']} synced, {results['orders_updated']} updated")
            else:
                results["errors"].append(f"Failed to fetch production orders: {response.status_code}")

        except Exception as e:
            db.rollback()
            logger.error(f"Production order sync error: {e}")
            results["errors"].append(str(e))

        return results

    async def _sync_single_production_order(
        self,
        db: Session,
        bc_order: Dict[str, Any],
        results: Dict[str, Any]
    ):
        """Sync a single production order"""

        bc_order_no = bc_order.get("No")

        # Check if exists
        existing = db.query(ProductionOrder).filter(
            ProductionOrder.bc_prod_order_number == bc_order_no
        ).first()

        # Map BC status to our enum
        bc_status = bc_order.get("Status", "Released")
        status_map = {
            "Simulated": ProductionStatus.PLANNED,
            "Planned": ProductionStatus.PLANNED,
            "Firm Planned": ProductionStatus.PLANNED,
            "Released": ProductionStatus.RELEASED,
            "Finished": ProductionStatus.FINISHED
        }
        status = status_map.get(bc_status, ProductionStatus.PLANNED)

        if existing:
            existing.item_code = bc_order.get("Source_No")
            existing.item_description = bc_order.get("Description")
            existing.quantity = bc_order.get("Quantity", 1)
            existing.status = status
            existing.due_date = self._parse_date(bc_order.get("Due_Date"))
            existing.last_synced_at = datetime.utcnow()
            results["orders_updated"] += 1
        else:
            prod_order = ProductionOrder(
                bc_prod_order_number=bc_order_no,
                item_code=bc_order.get("Source_No"),
                item_description=bc_order.get("Description"),
                quantity=bc_order.get("Quantity", 1),
                status=status,
                due_date=self._parse_date(bc_order.get("Due_Date")),
                last_synced_at=datetime.utcnow()
            )
            db.add(prod_order)
            results["orders_synced"] += 1

    # ==================== Auto-Linking ====================

    async def auto_link_production_orders(
        self,
        db: Session
    ) -> Dict[str, Any]:
        """
        Attempt to auto-link production orders to sales order lines by matching item numbers.

        Logic:
        1. Get all unlinked production orders (sales_order_id is NULL)
        2. For each, find sales order lines with matching item_no = production order's item_code
        3. Use smart matching to resolve multiple matches:
           - Prefer lines that don't already have a linked production order
           - Prefer lines with matching quantity
           - Prefer lines on sales orders with closest date to production due date
        """
        results = {
            "linked": 0,
            "already_linked": 0,
            "no_match": 0,
            "multiple_matches": 0,
            "smart_linked": 0,
            "details": []
        }

        # Get unlinked production orders
        unlinked_orders = db.query(ProductionOrder).filter(
            ProductionOrder.sales_order_id == None
        ).all()

        logger.info(f"Attempting to auto-link {len(unlinked_orders)} production orders")

        for prod_order in unlinked_orders:
            if not prod_order.item_code:
                results["no_match"] += 1
                continue

            # Find sales order lines with matching item number
            matching_lines = db.query(SalesOrderLineItem).filter(
                SalesOrderLineItem.item_no == prod_order.item_code
            ).all()

            if len(matching_lines) == 0:
                results["no_match"] += 1
                results["details"].append({
                    "prod_order": prod_order.bc_prod_order_number,
                    "item_code": prod_order.item_code,
                    "status": "no_match"
                })

            elif len(matching_lines) == 1:
                # Single match - link it
                line = matching_lines[0]
                prod_order.sales_order_id = line.sales_order_id
                prod_order.line_item_id = line.id
                results["linked"] += 1
                results["details"].append({
                    "prod_order": prod_order.bc_prod_order_number,
                    "item_code": prod_order.item_code,
                    "linked_to_so": line.sales_order_id,
                    "linked_to_line": line.id,
                    "status": "linked"
                })

            else:
                # Multiple matches - use smart matching
                best_line = self._find_best_matching_line(
                    db, prod_order, matching_lines
                )

                if best_line:
                    prod_order.sales_order_id = best_line.sales_order_id
                    prod_order.line_item_id = best_line.id
                    results["smart_linked"] += 1
                    results["details"].append({
                        "prod_order": prod_order.bc_prod_order_number,
                        "item_code": prod_order.item_code,
                        "linked_to_so": best_line.sales_order_id,
                        "linked_to_line": best_line.id,
                        "match_count": len(matching_lines),
                        "status": "smart_linked"
                    })
                else:
                    results["multiple_matches"] += 1
                    results["details"].append({
                        "prod_order": prod_order.bc_prod_order_number,
                        "item_code": prod_order.item_code,
                        "match_count": len(matching_lines),
                        "status": "multiple_matches"
                    })

        db.commit()
        logger.info(f"Auto-link complete: {results['linked']} linked, {results['smart_linked']} smart-linked, {results['no_match']} no match, {results['multiple_matches']} multiple matches")

        return results

    def _find_best_matching_line(
        self,
        db: Session,
        prod_order: ProductionOrder,
        matching_lines: List[SalesOrderLineItem]
    ) -> Optional[SalesOrderLineItem]:
        """
        Find the best matching sales order line when there are multiple candidates.

        Scoring criteria:
        1. Line doesn't already have a linked production order (+100 points)
        2. Quantity matches exactly (+50 points)
        3. Sales order date is closest to production due date (+25 points max)
        """
        if not matching_lines:
            return None

        scored_lines = []
        for line in matching_lines:
            score = 0

            # Check if this line already has a linked production order
            existing_link = db.query(ProductionOrder).filter(
                ProductionOrder.line_item_id == line.id,
                ProductionOrder.id != prod_order.id
            ).first()

            if not existing_link:
                score += 100  # Strong preference for unlinked lines

            # Check quantity match
            if line.quantity and prod_order.quantity:
                if line.quantity == prod_order.quantity:
                    score += 50
                elif abs(line.quantity - prod_order.quantity) <= 1:
                    score += 25  # Close match

            # Check date proximity
            if prod_order.due_date and line.sales_order:
                so = line.sales_order
                so_date = so.requested_delivery_date or so.order_date
                if so_date:
                    days_diff = abs((prod_order.due_date - so_date).days)
                    if days_diff <= 7:
                        score += 25
                    elif days_diff <= 30:
                        score += 15
                    elif days_diff <= 90:
                        score += 5

            scored_lines.append((score, line))

        # Sort by score descending
        scored_lines.sort(key=lambda x: x[0], reverse=True)

        # Return the best match if it has a meaningful score
        if scored_lines and scored_lines[0][0] >= 100:
            return scored_lines[0][1]

        # If top candidates have same score, still can't determine
        if len(scored_lines) >= 2:
            if scored_lines[0][0] == scored_lines[1][0]:
                return None  # Ambiguous

        return scored_lines[0][1] if scored_lines else None

    # ==================== Customer Sync ====================

    async def sync_customers(
        self,
        db: Session
    ) -> Dict[str, Any]:
        """
        Sync all BC customers to local cache, including price_multiplier.
        """
        results = {
            "customers_synced": 0,
            "customers_updated": 0,
            "errors": []
        }

        try:
            bc_customers = self.client.get_customers_with_multiplier()

            # Load group mapping once for the whole batch
            group_mapping = self._load_group_mapping(db)

            for bc_cust in bc_customers:
                try:
                    self._upsert_customer(db, bc_cust, results, group_mapping)
                except Exception as e:
                    results["errors"].append(f"Error syncing customer {bc_cust.get('displayName', '?')}: {e}")

            db.commit()
            logger.info(
                f"Customer sync complete: {results['customers_synced']} new, "
                f"{results['customers_updated']} updated"
            )

        except Exception as e:
            db.rollback()
            logger.error(f"Customer sync error: {e}")
            results["errors"].append(str(e))

        return results

    async def sync_single_customer(
        self,
        db: Session,
        bc_customer_id: str
    ) -> Dict[str, Any]:
        """
        Sync a single BC customer by ID for on-demand refresh.
        """
        results = {
            "customers_synced": 0,
            "customers_updated": 0,
            "errors": []
        }

        try:
            bc_cust = self.client.get_customer_with_multiplier(bc_customer_id)
            group_mapping = self._load_group_mapping(db)
            self._upsert_customer(db, bc_cust, results, group_mapping)
            db.commit()
            logger.info(f"Single customer sync complete: {bc_cust.get('displayName', bc_customer_id)}")
        except Exception as e:
            db.rollback()
            logger.error(f"Single customer sync error: {e}")
            results["errors"].append(str(e))

        return results

    def _load_group_mapping(self, db: Session) -> Dict[str, str]:
        """Load BC price group → portal tier mapping from AppSettings."""
        setting = db.query(AppSettings).filter(
            AppSettings.setting_key == BC_GROUP_MAPPING_KEY
        ).first()
        if setting and setting.setting_value:
            return setting.setting_value
        return {}

    def _upsert_customer(
        self,
        db: Session,
        bc_cust: Dict[str, Any],
        results: Dict[str, Any],
        group_mapping: Optional[Dict[str, str]] = None,
    ):
        """Insert or update a single BCCustomer record from BC API data."""
        bc_id = bc_cust.get("id")
        if not bc_id:
            return

        # BC may expose the multiplier as priceMultiplierPercent or similar
        multiplier = (
            bc_cust.get("priceMultiplierPercent")
            or bc_cust.get("priceMultiplier")
            or bc_cust.get("price_multiplier_percent")
        )

        # Capture BC customer price group.
        # The standard BC API v2.0 does not expose customerPriceGroup directly,
        # so we fall back to salespersonCode as the grouping mechanism.
        bc_price_group = (
            bc_cust.get("customerPriceGroup")
            or bc_cust.get("priceGroup")
            or bc_cust.get("customer_price_group")
            or bc_cust.get("salespersonCode")   # fallback: use salesperson as grouping
            or ""
        ).strip().upper() or None

        # Build address from BC fields
        address = None
        addr_parts = []
        for field in ["addressLine1", "addressLine2", "city", "state", "postalCode", "country"]:
            val = bc_cust.get(field)
            if val:
                addr_parts.append(val)
        if addr_parts:
            address = {
                "street": bc_cust.get("addressLine1", ""),
                "city": bc_cust.get("city", ""),
                "province": bc_cust.get("state", ""),
                "postal": bc_cust.get("postalCode", ""),
            }

        # Resolve portal pricing tier from BC price group mapping
        # Only auto-set if there's a mapping for this group; never clear a manually-set tier
        mapped_tier = None
        if bc_price_group and group_mapping:
            mapped_tier = group_mapping.get(bc_price_group)

        existing = db.query(BCCustomer).filter(
            BCCustomer.bc_customer_id == bc_id
        ).first()

        if existing:
            existing.company_name = bc_cust.get("displayName")
            existing.contact_name = bc_cust.get("contactName") or bc_cust.get("displayName")
            existing.email = bc_cust.get("email")
            existing.phone = bc_cust.get("phoneNumber")
            existing.price_multiplier = float(multiplier) if multiplier is not None else None
            existing.bc_price_group = bc_price_group
            # Apply mapped tier only if there is one; preserve existing manual tier otherwise
            if mapped_tier:
                existing.pricing_tier = mapped_tier
            if address:
                existing.address = address
            existing.last_synced = datetime.utcnow()
            results["customers_updated"] += 1
        else:
            new_customer = BCCustomer(
                bc_customer_id=bc_id,
                company_name=bc_cust.get("displayName"),
                contact_name=bc_cust.get("contactName") or bc_cust.get("displayName"),
                email=bc_cust.get("email"),
                phone=bc_cust.get("phoneNumber"),
                price_multiplier=float(multiplier) if multiplier is not None else None,
                bc_price_group=bc_price_group,
                pricing_tier=mapped_tier,
                address=address,
                last_synced=datetime.utcnow()
            )
            db.add(new_customer)
            results["customers_synced"] += 1

    # ==================== Full Sync ====================

    async def full_sync(
        self,
        db: Session,
        order_limit: int = 200
    ) -> Dict[str, Any]:
        """
        Perform a full sync of all BC data:
        1. Sync sales orders with lines
        2. Sync production orders
        3. Auto-link production orders to sales lines
        """
        results = {
            "customers": {},
            "sales_orders": {},
            "production_orders": {},
            "auto_link": {},
            "total_time_seconds": 0
        }

        import time
        start_time = time.time()

        logger.info("Starting full BC sync...")

        # 1. Sync customers
        logger.info("Syncing customers...")
        results["customers"] = await self.sync_customers(db=db)

        # 2. Sync sales orders
        logger.info("Syncing sales orders...")
        results["sales_orders"] = await self.sync_sales_orders_with_lines(
            db=db,
            sync_all=True,
            limit=order_limit
        )

        # 3. Sync production orders
        logger.info("Syncing production orders...")
        results["production_orders"] = await self.sync_production_orders(
            db=db,
            limit=order_limit
        )

        # 4. Auto-link
        logger.info("Auto-linking production orders...")
        results["auto_link"] = await self.auto_link_production_orders(db=db)

        results["total_time_seconds"] = round(time.time() - start_time, 2)

        logger.info(f"Full sync complete in {results['total_time_seconds']}s")

        return results

    # ==================== Helpers ====================

    def _parse_date(self, date_str: Optional[str]) -> Optional[datetime]:
        """Parse a date string from BC"""
        if not date_str or date_str == "0001-01-01":
            return None
        try:
            if "T" in date_str:
                return datetime.fromisoformat(date_str.replace("Z", "+00:00"))
            return datetime.strptime(date_str, "%Y-%m-%d")
        except Exception:
            return None

    def _build_address(self, order: Dict[str, Any], prefix: str) -> Optional[str]:
        """Build address string from BC order fields"""
        parts = []
        for field in ["Name", "AddressLine1", "AddressLine2", "City", "State", "PostCode", "Country"]:
            value = order.get(f"{prefix}{field}")
            if value:
                parts.append(value)
        return ", ".join(parts) if parts else None


# Singleton instance
bc_sync_service = BCSyncService()
