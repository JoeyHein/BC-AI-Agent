"""
Order Lifecycle Service
Orchestrates the full order-to-cash workflow:
Quote -> Sales Order -> Production -> Shipping -> Invoice
"""

import logging
from typing import Dict, List, Any, Optional
from datetime import datetime, timedelta
from sqlalchemy.orm import Session

from app.integrations.bc.client import bc_client
from app.db.models import (
    QuoteRequest, SalesOrder, ProductionOrder, Shipment, Invoice,
    OrderStatus, ProductionStatus, InvoiceStatus, AuditTrail
)

logger = logging.getLogger(__name__)


class OrderLifecycleService:
    """Orchestrates the full order-to-cash workflow"""

    def __init__(self):
        self.bc_client = bc_client

    # ==================== Quote to Order Conversion ====================

    def convert_quote_to_order(
        self,
        db: Session,
        quote_request_id: int,
        user_id: str
    ) -> Dict[str, Any]:
        """
        Convert an approved quote to a sales order in BC.

        This creates the order in BC and stores a local reference.

        Args:
            db: Database session
            quote_request_id: QuoteRequest ID
            user_id: User performing the action

        Returns:
            Dict with order data and status
        """
        logger.info(f"Converting quote request {quote_request_id} to order")

        # Get the quote request
        quote_request = db.query(QuoteRequest).filter(
            QuoteRequest.id == quote_request_id
        ).first()

        if not quote_request:
            return {"success": False, "error": "Quote request not found"}

        if not quote_request.bc_quote_id:
            return {"success": False, "error": "No BC quote ID found - create BC quote first"}

        try:
            # Find the BC quote by number
            bc_quotes = self.bc_client.get_sales_quotes(top=100)
            bc_quote = None
            for q in bc_quotes:
                if q.get("number") == quote_request.bc_quote_id:
                    bc_quote = q
                    break

            if not bc_quote:
                return {"success": False, "error": f"BC quote {quote_request.bc_quote_id} not found"}

            bc_quote_guid = bc_quote.get("id")

            # Convert quote to order in BC using makeOrder action
            bc_order = self.bc_client.convert_quote_to_order(bc_quote_guid)

            # Create local SalesOrder record
            sales_order = SalesOrder(
                quote_request_id=quote_request_id,
                bc_order_id=bc_order.get("id"),
                bc_order_number=bc_order.get("number"),
                bc_quote_number=quote_request.bc_quote_id,
                customer_id=bc_order.get("customerId"),
                customer_name=bc_order.get("customerName"),
                customer_email=quote_request.contact_email,
                status=OrderStatus.CONFIRMED,
                total_amount=bc_order.get("totalAmountIncludingTax"),
                external_document_number=bc_order.get("externalDocumentNumber"),
                confirmed_at=datetime.utcnow(),
                last_synced_at=datetime.utcnow()
            )
            db.add(sales_order)

            # Update quote request status
            quote_request.status = "converted_to_order"
            db.commit()

            # Audit trail
            self._create_audit(
                db, user_id, "quote_converted_to_order",
                "sales_order", bc_order.get("number"),
                {
                    "quote_request_id": quote_request_id,
                    "bc_quote_number": quote_request.bc_quote_id,
                    "bc_order_number": bc_order.get("number")
                }
            )

            logger.info(f"Created sales order {bc_order.get('number')} from quote {quote_request.bc_quote_id}")

            return {
                "success": True,
                "sales_order_id": sales_order.id,
                "bc_order_number": bc_order.get("number"),
                "bc_order_id": bc_order.get("id"),
                "total_amount": bc_order.get("totalAmountIncludingTax"),
                "bc_order": bc_order
            }

        except Exception as e:
            error_msg = str(e)

            # Check for Table 50005 permission error (Open DC custom extension)
            if "TableData 50005" in error_msg or "Unscheduled Lines" in error_msg:
                logger.warning(f"BC permission error on Table 50005: {error_msg}")
                return {
                    "success": False,
                    "error": "BC API permission denied for custom extension table",
                    "error_code": "BC_TABLE_PERMISSION",
                    "details": "The Open Distribution Company has a custom extension requiring "
                              "Table 50005 (Unscheduled Lines) Read permission. Grant this permission "
                              "to the Azure AD Application in BC Admin Center.",
                    "raw_error": error_msg[:300]
                }

            # Check for BC dialog blocking
            if "DialogException" in error_msg or "client callback" in error_msg:
                return {
                    "success": False,
                    "error": "BC custom extension is blocking with a modal dialog",
                    "error_code": "BC_DIALOG_BLOCKED"
                }

            logger.error(f"Failed to convert quote to order: {e}", exc_info=True)
            return {"success": False, "error": str(e)}

    # ==================== Sales Order Management ====================

    def get_sales_orders(
        self,
        db: Session,
        status: Optional[OrderStatus] = None,
        limit: int = 50
    ) -> List[SalesOrder]:
        """Get local sales order records with optional filtering"""
        query = db.query(SalesOrder)
        if status:
            query = query.filter(SalesOrder.status == status)
        return query.order_by(SalesOrder.created_at.desc()).limit(limit).all()

    def get_order_with_details(
        self,
        db: Session,
        order_id: int
    ) -> Optional[Dict[str, Any]]:
        """Get comprehensive order details including production, shipments, invoices"""
        order = db.query(SalesOrder).filter(SalesOrder.id == order_id).first()
        if not order:
            return None

        # Get BC data for up-to-date info
        bc_order = None
        if order.bc_order_id:
            try:
                bc_order = self.bc_client.get_sales_order(order.bc_order_id)
            except Exception as e:
                logger.warning(f"Could not fetch BC order: {e}")

        return {
            "order": order,
            "bc_order": bc_order,
            "production_orders": order.production_orders,
            "shipments": order.shipments,
            "invoices": order.invoices,
            "timeline": self._build_order_timeline(order)
        }

    def sync_order_from_bc(
        self,
        db: Session,
        order_id: int
    ) -> Dict[str, Any]:
        """Sync a local order record with BC data"""
        order = db.query(SalesOrder).filter(SalesOrder.id == order_id).first()
        if not order or not order.bc_order_id:
            return {"success": False, "error": "Order not found or no BC ID"}

        try:
            bc_order = self.bc_client.get_sales_order(order.bc_order_id)

            # Update local record
            order.customer_name = bc_order.get("customerName")
            order.total_amount = bc_order.get("totalAmountIncludingTax")
            order.last_synced_at = datetime.utcnow()

            # Map BC status to local status
            bc_status = bc_order.get("status", "").lower()
            if bc_status == "open":
                order.status = OrderStatus.CONFIRMED
            elif bc_status == "released":
                order.status = OrderStatus.IN_PRODUCTION

            db.commit()

            return {"success": True, "order": order, "bc_order": bc_order}

        except Exception as e:
            logger.error(f"Failed to sync order: {e}")
            return {"success": False, "error": str(e)}

    # ==================== Production Orders ====================

    def create_production_orders(
        self,
        db: Session,
        sales_order_id: int,
        user_id: str
    ) -> Dict[str, Any]:
        """
        Create production orders from a sales order.

        This pulls line items from the original quote and creates production
        orders for each item type (doors, springs, hardware, etc.).
        Spring production orders include full Canimex specifications.

        Args:
            db: Database session
            sales_order_id: Local SalesOrder ID
            user_id: User performing the action

        Returns:
            Dict with created production orders and status
        """
        from app.db.models import QuoteItem

        logger.info(f"Creating production orders for sales order {sales_order_id}")

        # Get the sales order
        order = db.query(SalesOrder).filter(SalesOrder.id == sales_order_id).first()
        if not order:
            return {"success": False, "error": "Sales order not found"}

        if not order.quote_request_id:
            return {"success": False, "error": "Sales order has no linked quote request"}

        # Get quote items (which contain the spring specifications)
        quote_items = db.query(QuoteItem).filter(
            QuoteItem.quote_request_id == order.quote_request_id
        ).all()

        if not quote_items:
            return {"success": False, "error": "No quote items found for this order"}

        production_orders = []
        inventory_warnings = []

        for quote_item in quote_items:
            # Create production order for each quote item
            prod_order = self._create_production_order_from_quote_item(
                db, order, quote_item, user_id
            )

            if prod_order:
                production_orders.append(prod_order)

                # Check inventory for this item
                inventory_check = self._check_and_allocate_inventory(
                    db, prod_order, quote_item
                )
                if not inventory_check.get("sufficient"):
                    inventory_warnings.append({
                        "item_code": prod_order.item_code,
                        "item_type": prod_order.item_type,
                        "required": prod_order.quantity,
                        "available": inventory_check.get("available", 0),
                        "shortfall": inventory_check.get("shortfall", 0)
                    })

        # Update sales order status
        order.status = OrderStatus.IN_PRODUCTION
        order.production_started_at = datetime.utcnow()
        db.commit()

        # Audit trail
        self._create_audit(
            db, user_id, "production_orders_created",
            "sales_order", str(order.id),
            {
                "sales_order_id": sales_order_id,
                "bc_order_number": order.bc_order_number,
                "production_order_count": len(production_orders),
                "has_inventory_warnings": len(inventory_warnings) > 0
            }
        )

        logger.info(f"Created {len(production_orders)} production orders for sales order {sales_order_id}")

        return {
            "success": True,
            "sales_order_id": sales_order_id,
            "production_orders": [
                {
                    "id": po.id,
                    "item_type": po.item_type,
                    "item_code": po.item_code,
                    "description": po.item_description,
                    "quantity": po.quantity,
                    "specifications": po.specifications,
                    "inventory_allocated": po.inventory_allocated,
                    "stock_available": po.stock_available,
                    "stock_reserved": po.stock_reserved
                }
                for po in production_orders
            ],
            "inventory_warnings": inventory_warnings
        }

    def _create_production_order_from_quote_item(
        self,
        db: Session,
        sales_order: SalesOrder,
        quote_item: "QuoteItem",
        user_id: str
    ) -> Optional[ProductionOrder]:
        """
        Create a single production order from a quote item.

        For spring items, this preserves all Canimex calculation data:
        - Wire diameter, coil diameter, length
        - IPPT, MIP per spring, turns
        - Cycle life, drum model
        - Door weight and height

        Args:
            db: Database session
            sales_order: Parent sales order
            quote_item: Quote item to convert
            user_id: User performing the action

        Returns:
            Created ProductionOrder or None
        """
        # Extract specifications from quote item metadata
        specifications = None
        if quote_item.item_metadata:
            if quote_item.item_type == "spring":
                # Preserve full spring specifications from Canimex calculator
                specifications = {
                    "wire_diameter": quote_item.item_metadata.get("wire_diameter"),
                    "coil_diameter": quote_item.item_metadata.get("coil_diameter"),
                    "length": quote_item.item_metadata.get("length"),
                    "ippt": quote_item.item_metadata.get("ippt"),
                    "mip_per_spring": quote_item.item_metadata.get("mip_per_spring"),
                    "turns": quote_item.item_metadata.get("turns"),
                    "cycle_life": quote_item.item_metadata.get("cycle_life"),
                    "drum_model": quote_item.item_metadata.get("drum_model"),
                    "door_weight": quote_item.item_metadata.get("door_weight"),
                    "door_height_inches": quote_item.item_metadata.get("door_height_inches"),
                    "track_radius": quote_item.item_metadata.get("track_radius"),
                    "wind": quote_item.item_metadata.get("wind", "LH")  # Left-hand or Right-hand
                }
            elif quote_item.item_type == "door":
                specifications = {
                    "model": quote_item.item_metadata.get("model"),
                    "size": quote_item.item_metadata.get("size"),
                    "color": quote_item.item_metadata.get("color"),
                    "panel_config": quote_item.item_metadata.get("panel_config")
                }
            elif quote_item.item_type == "hardware":
                specifications = {
                    "track_type": quote_item.item_metadata.get("track_type"),
                    "size": quote_item.item_metadata.get("size")
                }
            else:
                # Generic metadata storage for other item types
                specifications = quote_item.item_metadata

        # Create production order
        prod_order = ProductionOrder(
            sales_order_id=sales_order.id,
            status=ProductionStatus.PLANNED,
            item_type=quote_item.item_type,
            item_code=quote_item.product_code,
            item_description=quote_item.description,
            quantity=quote_item.quantity,
            specifications=specifications,
            due_date=sales_order.confirmed_at + timedelta(days=7) if sales_order.confirmed_at else None
        )

        db.add(prod_order)
        db.flush()  # Get the ID without committing

        logger.info(f"Created production order for {quote_item.item_type}: {quote_item.product_code}")

        return prod_order

    def _check_and_allocate_inventory(
        self,
        db: Session,
        prod_order: ProductionOrder,
        quote_item: "QuoteItem"
    ) -> Dict[str, Any]:
        """
        Check inventory availability and allocate stock for a production order.

        For springs, checks BC inventory by part number (e.g., SP11-23420-01).

        Args:
            db: Database session
            prod_order: Production order to allocate for
            quote_item: Source quote item

        Returns:
            Dict with allocation status
        """
        result = {
            "sufficient": False,
            "available": 0,
            "required": prod_order.quantity,
            "shortfall": 0,
            "allocated": False
        }

        try:
            # Search for item in BC by part number
            items = self.bc_client.search_items(prod_order.item_code)

            if items:
                bc_item = items[0]
                available = bc_item.get("inventory", 0)
                result["available"] = available
                result["bc_item_id"] = bc_item.get("id")

                if available >= prod_order.quantity:
                    result["sufficient"] = True
                    result["allocated"] = True

                    # Update production order with inventory info
                    prod_order.stock_available = available
                    prod_order.stock_reserved = prod_order.quantity
                    prod_order.inventory_allocated = True
                    prod_order.inventory_allocation_id = bc_item.get("id")

                    logger.info(
                        f"Allocated {prod_order.quantity} of {prod_order.item_code} "
                        f"(available: {available})"
                    )
                else:
                    result["shortfall"] = prod_order.quantity - available
                    prod_order.stock_available = available
                    prod_order.stock_reserved = available  # Reserve what we have
                    prod_order.inventory_allocated = False

                    logger.warning(
                        f"Insufficient inventory for {prod_order.item_code}: "
                        f"need {prod_order.quantity}, have {available}"
                    )
            else:
                logger.warning(f"Item not found in BC inventory: {prod_order.item_code}")
                prod_order.stock_available = 0
                prod_order.inventory_allocated = False

        except Exception as e:
            logger.error(f"Error checking inventory for {prod_order.item_code}: {e}")

        return result

    def get_production_orders(
        self,
        db: Session,
        sales_order_id: Optional[int] = None,
        status: Optional[ProductionStatus] = None,
        item_type: Optional[str] = None,
        limit: int = 50
    ) -> List[ProductionOrder]:
        """
        Get production orders with optional filtering.

        Args:
            db: Database session
            sales_order_id: Filter by sales order
            status: Filter by production status
            item_type: Filter by item type (door, spring, hardware)
            limit: Maximum results

        Returns:
            List of ProductionOrder objects
        """
        query = db.query(ProductionOrder)

        if sales_order_id:
            query = query.filter(ProductionOrder.sales_order_id == sales_order_id)
        if status:
            query = query.filter(ProductionOrder.status == status)
        if item_type:
            query = query.filter(ProductionOrder.item_type == item_type)

        return query.order_by(ProductionOrder.created_at.desc()).limit(limit).all()

    def get_spring_production_orders(
        self,
        db: Session,
        sales_order_id: Optional[int] = None,
        status: Optional[ProductionStatus] = None
    ) -> List[Dict[str, Any]]:
        """
        Get spring production orders with full specifications.

        Returns detailed spring data including Canimex calculations.

        Args:
            db: Database session
            sales_order_id: Optional filter by sales order
            status: Optional filter by status

        Returns:
            List of spring production order dicts with specs
        """
        orders = self.get_production_orders(
            db, sales_order_id=sales_order_id, status=status, item_type="spring"
        )

        return [
            {
                "id": order.id,
                "sales_order_id": order.sales_order_id,
                "status": order.status.value,
                "item_code": order.item_code,
                "description": order.item_description,
                "quantity": order.quantity,
                "quantity_completed": order.quantity_completed,
                "specifications": order.specifications,
                "inventory": {
                    "allocated": order.inventory_allocated,
                    "available": order.stock_available,
                    "reserved": order.stock_reserved
                },
                "scheduling": {
                    "due_date": order.due_date.isoformat() if order.due_date else None,
                    "start_date": order.start_date.isoformat() if order.start_date else None,
                    "end_date": order.end_date.isoformat() if order.end_date else None
                },
                "created_at": order.created_at.isoformat()
            }
            for order in orders
        ]

    def update_production_status(
        self,
        db: Session,
        production_order_id: int,
        new_status: ProductionStatus,
        user_id: str,
        quantity_completed: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Update production order status.

        Args:
            db: Database session
            production_order_id: Production order ID
            new_status: New status to set
            user_id: User performing the action
            quantity_completed: Optional quantity completed update

        Returns:
            Dict with update result
        """
        prod_order = db.query(ProductionOrder).filter(
            ProductionOrder.id == production_order_id
        ).first()

        if not prod_order:
            return {"success": False, "error": "Production order not found"}

        old_status = prod_order.status
        prod_order.status = new_status

        # Update timestamps based on status
        if new_status == ProductionStatus.IN_PROGRESS and not prod_order.started_at:
            prod_order.started_at = datetime.utcnow()
            prod_order.start_date = datetime.utcnow()

        elif new_status == ProductionStatus.FINISHED:
            prod_order.finished_at = datetime.utcnow()
            prod_order.end_date = datetime.utcnow()
            if quantity_completed is None:
                prod_order.quantity_completed = prod_order.quantity

        if quantity_completed is not None:
            prod_order.quantity_completed = quantity_completed

        db.commit()

        # Check if all production orders for the sales order are complete
        self._check_and_update_sales_order_status(db, prod_order.sales_order_id)

        # Audit trail
        self._create_audit(
            db, user_id, "production_status_updated",
            "production_order", str(production_order_id),
            {
                "old_status": old_status.value,
                "new_status": new_status.value,
                "quantity_completed": prod_order.quantity_completed
            }
        )

        logger.info(
            f"Updated production order {production_order_id} status: "
            f"{old_status.value} -> {new_status.value}"
        )

        return {
            "success": True,
            "production_order_id": production_order_id,
            "old_status": old_status.value,
            "new_status": new_status.value,
            "quantity_completed": prod_order.quantity_completed
        }

    def _check_and_update_sales_order_status(
        self,
        db: Session,
        sales_order_id: int
    ):
        """
        Check if all production orders are complete and update sales order status.

        Args:
            db: Database session
            sales_order_id: Sales order to check
        """
        # Get all production orders for this sales order
        prod_orders = db.query(ProductionOrder).filter(
            ProductionOrder.sales_order_id == sales_order_id
        ).all()

        if not prod_orders:
            return

        # Check if all are finished
        all_finished = all(
            po.status == ProductionStatus.FINISHED for po in prod_orders
        )

        if all_finished:
            order = db.query(SalesOrder).filter(SalesOrder.id == sales_order_id).first()
            if order and order.status == OrderStatus.IN_PRODUCTION:
                order.status = OrderStatus.READY_TO_SHIP
                order.production_completed_at = datetime.utcnow()
                db.commit()
                logger.info(f"Sales order {sales_order_id} marked ready to ship")

    # ==================== Shipping ====================

    def ship_order(
        self,
        db: Session,
        order_id: int,
        user_id: str,
        tracking_number: Optional[str] = None,
        carrier: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Ship a sales order.

        This calls the BC ship action and creates a local shipment record.
        """
        order = db.query(SalesOrder).filter(SalesOrder.id == order_id).first()
        if not order or not order.bc_order_id:
            return {"success": False, "error": "Order not found or no BC ID"}

        try:
            # Ship in BC
            result = self.bc_client.ship_sales_order(order.bc_order_id)

            # Get the shipment created
            shipments = self.bc_client.get_shipments_for_order(order.bc_order_number)

            # Create local shipment record
            shipment = Shipment(
                sales_order_id=order.id,
                bc_shipment_id=shipments[0].get("id") if shipments else None,
                shipment_number=shipments[0].get("number") if shipments else None,
                shipped_date=datetime.utcnow(),
                tracking_number=tracking_number,
                carrier=carrier,
                ship_to_name=order.customer_name
            )
            db.add(shipment)

            # Update order status
            order.status = OrderStatus.SHIPPED
            order.shipped_at = datetime.utcnow()
            db.commit()

            self._create_audit(
                db, user_id, "order_shipped",
                "shipment", shipment.shipment_number,
                {"order_id": order.id, "bc_order_number": order.bc_order_number}
            )

            logger.info(f"Shipped order {order.bc_order_number}")

            return {
                "success": True,
                "shipment_id": shipment.id,
                "shipment_number": shipment.shipment_number
            }

        except Exception as e:
            error_msg = str(e)

            # Check for BC custom extension dialog blocking
            if "DialogException" in error_msg or "client callback" in error_msg:
                logger.warning(f"BC extension blocking ship: {error_msg}")
                return {
                    "success": False,
                    "error": "BC custom extension is blocking the operation with a modal dialog",
                    "error_code": "BC_DIALOG_BLOCKED",
                    "details": "Contact BC admin to resolve custom extension dialog issue."
                }

            logger.error(f"Failed to ship order: {e}", exc_info=True)
            return {"success": False, "error": str(e)}

    def ship_and_invoice_order(
        self,
        db: Session,
        order_id: int,
        user_id: str
    ) -> Dict[str, Any]:
        """
        Ship and invoice an order in one operation.

        This is the most common flow for completed production.
        """
        order = db.query(SalesOrder).filter(SalesOrder.id == order_id).first()
        if not order or not order.bc_order_id:
            return {"success": False, "error": "Order not found or no BC ID"}

        try:
            # Call BC shipAndInvoice action
            result = self.bc_client.ship_and_invoice(order.bc_order_id)

            # Get created shipments and invoices
            shipments = self.bc_client.get_shipments_for_order(order.bc_order_number)
            invoices = self.bc_client.get_invoices_for_order(order.bc_order_number)

            # Create shipment record
            if shipments:
                shipment = Shipment(
                    sales_order_id=order.id,
                    bc_shipment_id=shipments[-1].get("id"),
                    shipment_number=shipments[-1].get("number"),
                    shipped_date=datetime.utcnow(),
                    ship_to_name=order.customer_name
                )
                db.add(shipment)

            # Create invoice record
            if invoices:
                bc_invoice = invoices[-1]
                invoice = Invoice(
                    sales_order_id=order.id,
                    bc_invoice_id=bc_invoice.get("id"),
                    invoice_number=bc_invoice.get("number"),
                    status=InvoiceStatus.POSTED,
                    total_amount=bc_invoice.get("totalAmountIncludingTax"),
                    tax_amount=bc_invoice.get("totalTaxAmount"),
                    due_date=datetime.fromisoformat(bc_invoice.get("dueDate").replace("Z", "+00:00")) if bc_invoice.get("dueDate") else None,
                    posted_at=datetime.utcnow()
                )
                db.add(invoice)

            # Update order status
            order.status = OrderStatus.INVOICED
            order.shipped_at = datetime.utcnow()
            order.invoiced_at = datetime.utcnow()
            db.commit()

            self._create_audit(
                db, user_id, "order_shipped_and_invoiced",
                "sales_order", order.bc_order_number,
                {
                    "shipment_count": len(shipments),
                    "invoice_count": len(invoices)
                }
            )

            logger.info(f"Shipped and invoiced order {order.bc_order_number}")

            return {
                "success": True,
                "order_id": order.id,
                "bc_order_number": order.bc_order_number,
                "shipments": len(shipments),
                "invoices": len(invoices)
            }

        except Exception as e:
            error_msg = str(e)

            # Check for BC custom extension dialog blocking
            if "DialogException" in error_msg or "client callback" in error_msg:
                logger.warning(f"BC extension blocking ship/invoice: {error_msg}")
                return {
                    "success": False,
                    "error": "BC custom extension is blocking the operation with a modal dialog",
                    "error_code": "BC_DIALOG_BLOCKED",
                    "details": "The BC environment has a custom extension (Page 50502 Posting Date Dialog) "
                              "that shows a modal dialog during shipping/invoicing. Modal dialogs cannot "
                              "work via API. Contact BC admin to resolve.",
                    "raw_error": error_msg[:500]
                }

            logger.error(f"Failed to ship and invoice: {e}", exc_info=True)
            return {"success": False, "error": str(e)}

    # ==================== Invoicing ====================

    def post_invoice(
        self,
        db: Session,
        invoice_id: int,
        user_id: str
    ) -> Dict[str, Any]:
        """Post a draft invoice to the general ledger"""
        invoice = db.query(Invoice).filter(Invoice.id == invoice_id).first()
        if not invoice or not invoice.bc_invoice_id:
            return {"success": False, "error": "Invoice not found or no BC ID"}

        try:
            # Post in BC
            result = self.bc_client.post_sales_invoice(invoice.bc_invoice_id)

            # Update local record
            invoice.status = InvoiceStatus.POSTED
            invoice.posted_at = datetime.utcnow()
            db.commit()

            self._create_audit(
                db, user_id, "invoice_posted",
                "invoice", invoice.invoice_number,
                {"total_amount": float(invoice.total_amount) if invoice.total_amount else 0}
            )

            logger.info(f"Posted invoice {invoice.invoice_number}")

            return {"success": True, "invoice_id": invoice.id}

        except Exception as e:
            error_msg = str(e)

            if "DialogException" in error_msg or "client callback" in error_msg:
                return {
                    "success": False,
                    "error": "BC custom extension is blocking posting with a modal dialog",
                    "error_code": "BC_DIALOG_BLOCKED"
                }

            logger.error(f"Failed to post invoice: {e}", exc_info=True)
            return {"success": False, "error": str(e)}

    # ==================== Pipeline Statistics ====================

    def get_pipeline_stats(self, db: Session) -> Dict[str, Any]:
        """Get order pipeline statistics for dashboard"""
        from sqlalchemy import func

        stats = {
            "by_status": {},
            "totals": {
                "total_orders": 0,
                "total_revenue": 0,
                "pending_shipment": 0,
                "pending_invoice": 0
            }
        }

        # Count orders by status
        status_counts = db.query(
            SalesOrder.status,
            func.count(SalesOrder.id).label("count"),
            func.sum(SalesOrder.total_amount).label("total")
        ).group_by(SalesOrder.status).all()

        for status, count, total in status_counts:
            stats["by_status"][status.value] = {
                "count": count,
                "total_amount": float(total) if total else 0
            }
            stats["totals"]["total_orders"] += count
            stats["totals"]["total_revenue"] += float(total) if total else 0

        # Pending counts
        stats["totals"]["pending_shipment"] = db.query(SalesOrder).filter(
            SalesOrder.status.in_([OrderStatus.CONFIRMED, OrderStatus.IN_PRODUCTION, OrderStatus.READY_TO_SHIP])
        ).count()

        stats["totals"]["pending_invoice"] = db.query(SalesOrder).filter(
            SalesOrder.status == OrderStatus.SHIPPED
        ).count()

        return stats

    # ==================== Helpers ====================

    def _build_order_timeline(self, order: SalesOrder) -> List[Dict[str, Any]]:
        """Build a timeline of events for an order"""
        timeline = []

        if order.created_at:
            timeline.append({
                "event": "Order Created",
                "timestamp": order.created_at.isoformat(),
                "status": "completed"
            })

        if order.confirmed_at:
            timeline.append({
                "event": "Order Confirmed",
                "timestamp": order.confirmed_at.isoformat(),
                "status": "completed"
            })

        if order.production_started_at:
            timeline.append({
                "event": "Production Started",
                "timestamp": order.production_started_at.isoformat(),
                "status": "completed"
            })

        if order.production_completed_at:
            timeline.append({
                "event": "Production Completed",
                "timestamp": order.production_completed_at.isoformat(),
                "status": "completed"
            })

        if order.shipped_at:
            timeline.append({
                "event": "Shipped",
                "timestamp": order.shipped_at.isoformat(),
                "status": "completed"
            })

        if order.invoiced_at:
            timeline.append({
                "event": "Invoiced",
                "timestamp": order.invoiced_at.isoformat(),
                "status": "completed"
            })

        if order.completed_at:
            timeline.append({
                "event": "Completed",
                "timestamp": order.completed_at.isoformat(),
                "status": "completed"
            })

        return sorted(timeline, key=lambda x: x["timestamp"])

    def _create_audit(
        self,
        db: Session,
        user_id: str,
        action: str,
        entity_type: str,
        entity_id: str,
        details: Dict[str, Any]
    ):
        """Create audit trail entry"""
        try:
            audit = AuditTrail(
                user_id=user_id,
                action=action,
                entity_type=entity_type,
                entity_id=entity_id,
                details=details,
                timestamp=datetime.utcnow()
            )
            db.add(audit)
            db.commit()
        except Exception as e:
            logger.error(f"Failed to create audit: {e}")
            db.rollback()


# Global instance
order_lifecycle_service = OrderLifecycleService()
