"""
Orders API Router
Endpoints for managing the order-to-cash lifecycle
"""

import logging
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.models import SalesOrder, OrderStatus, ProductionOrder, Shipment, Invoice
from app.services.order_lifecycle_service import order_lifecycle_service
from app.integrations.bc.client import bc_client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/orders", tags=["orders"])


# ==================== Pydantic Models ====================

class ConvertQuoteRequest(BaseModel):
    quote_request_id: int
    user_id: str = "system"


class ShipOrderRequest(BaseModel):
    tracking_number: Optional[str] = None
    carrier: Optional[str] = None
    user_id: str = "system"


class OrderResponse(BaseModel):
    id: int
    quote_request_id: Optional[int]
    bc_order_id: Optional[str]
    bc_order_number: Optional[str]
    customer_name: Optional[str]
    status: str
    total_amount: Optional[float]
    created_at: str
    shipped_at: Optional[str]
    invoiced_at: Optional[str]

    class Config:
        from_attributes = True


class PipelineStats(BaseModel):
    by_status: dict
    totals: dict


# ==================== Order Management ====================

@router.get("")
async def list_orders(
    status: Optional[str] = Query(None, description="Filter by status"),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db)
):
    """
    List all sales orders from Business Central (source of truth).

    BC is the primary data source - we read directly from BC API.
    """
    try:
        # Get orders directly from BC
        bc_orders = bc_client.get_sales_orders(top=limit, status_filter=status)

        return {
            "count": len(bc_orders),
            "source": "bc",
            "orders": [
                {
                    "id": o.get("id"),
                    "order_number": o.get("number"),
                    "bc_order_number": o.get("number"),
                    "customer_id": o.get("customerId"),
                    "customer_name": o.get("customerName"),
                    "status": o.get("status", "Open"),
                    "total_amount": o.get("totalAmountIncludingTax", 0),
                    "order_date": o.get("orderDate"),
                    "requested_delivery_date": o.get("requestedDeliveryDate"),
                    "external_document_number": o.get("externalDocumentNumber"),
                    "shipment_method": o.get("shipmentMethodCode"),
                    "salesperson": o.get("salesperson"),
                }
                for o in bc_orders
            ]
        }
    except Exception as e:
        logger.error(f"Error fetching orders from BC: {e}")
        # Fallback to local DB if BC unavailable
        logger.warning("Falling back to local database")
        orders = order_lifecycle_service.get_sales_orders(db, status=None, limit=limit)
        return {
            "count": len(orders),
            "source": "local_fallback",
            "orders": [
                {
                    "id": o.id,
                    "order_number": o.bc_order_number,
                    "bc_order_number": o.bc_order_number,
                    "customer_name": o.customer_name,
                    "status": o.status.value if o.status else "unknown",
                    "total_amount": o.total_amount,
                    "order_date": o.created_at.isoformat() if o.created_at else None,
                }
                for o in orders
            ]
        }


@router.get("/legacy", response_model=List[OrderResponse])
async def list_orders_legacy(
    status: Optional[str] = Query(None, description="Filter by status"),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db)
):
    """Legacy endpoint - reads from local database. Use GET /api/orders for BC data."""
    status_enum = None
    if status:
        try:
            status_enum = OrderStatus(status)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid status: {status}")

    orders = order_lifecycle_service.get_sales_orders(db, status=status_enum, limit=limit)

    return [
        OrderResponse(
            id=o.id,
            quote_request_id=o.quote_request_id,
            bc_order_id=o.bc_order_id,
            bc_order_number=o.bc_order_number,
            customer_name=o.customer_name,
            status=o.status.value if o.status else "unknown",
            total_amount=float(o.total_amount) if o.total_amount else None,
            created_at=o.created_at.isoformat() if o.created_at else "",
            shipped_at=o.shipped_at.isoformat() if o.shipped_at else None,
            invoiced_at=o.invoiced_at.isoformat() if o.invoiced_at else None
        )
        for o in orders
    ]


@router.get("/stats/pipeline", response_model=PipelineStats)
async def get_pipeline_stats(db: Session = Depends(get_db)):
    """Get order pipeline statistics for dashboard"""
    stats = order_lifecycle_service.get_pipeline_stats(db)
    return stats


@router.get("/{order_id}")
async def get_order_details(
    order_id: int,
    db: Session = Depends(get_db)
):
    """Get detailed order information including production, shipments, invoices"""
    result = order_lifecycle_service.get_order_with_details(db, order_id)
    if not result:
        raise HTTPException(status_code=404, detail="Order not found")

    order = result["order"]

    return {
        "order": {
            "id": order.id,
            "bc_order_id": order.bc_order_id,
            "bc_order_number": order.bc_order_number,
            "bc_quote_number": order.bc_quote_number,
            "customer_id": order.customer_id,
            "customer_name": order.customer_name,
            "customer_email": order.customer_email,
            "status": order.status.value if order.status else None,
            "total_amount": float(order.total_amount) if order.total_amount else None,
            "created_at": order.created_at.isoformat() if order.created_at else None,
            "confirmed_at": order.confirmed_at.isoformat() if order.confirmed_at else None,
            "shipped_at": order.shipped_at.isoformat() if order.shipped_at else None,
            "invoiced_at": order.invoiced_at.isoformat() if order.invoiced_at else None
        },
        "bc_order": result["bc_order"],
        "production_orders": [
            {
                "id": p.id,
                "bc_prod_order_number": p.bc_prod_order_number,
                "item_code": p.item_code,
                "quantity": p.quantity,
                "status": p.status.value if p.status else None
            }
            for p in result["production_orders"]
        ],
        "shipments": [
            {
                "id": s.id,
                "shipment_number": s.shipment_number,
                "tracking_number": s.tracking_number,
                "carrier": s.carrier,
                "shipped_date": s.shipped_date.isoformat() if s.shipped_date else None
            }
            for s in result["shipments"]
        ],
        "invoices": [
            {
                "id": i.id,
                "invoice_number": i.invoice_number,
                "status": i.status.value if i.status else None,
                "total_amount": float(i.total_amount) if i.total_amount else None,
                "posted_at": i.posted_at.isoformat() if i.posted_at else None
            }
            for i in result["invoices"]
        ],
        "timeline": result["timeline"]
    }


@router.post("/{order_id}/sync")
async def sync_order(
    order_id: int,
    db: Session = Depends(get_db)
):
    """Sync order data from Business Central"""
    result = order_lifecycle_service.sync_order_from_bc(db, order_id)
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result.get("error", "Sync failed"))
    return {"success": True, "message": "Order synced successfully"}


# ==================== Quote to Order Conversion ====================

@router.post("/from-quote/{quote_request_id}")
async def convert_quote_to_order(
    quote_request_id: int,
    user_id: str = Query("system"),
    db: Session = Depends(get_db)
):
    """
    Convert an approved quote to a sales order.

    This calls the BC makeOrder action to create a sales order from the quote.
    """
    result = order_lifecycle_service.convert_quote_to_order(db, quote_request_id, user_id)

    if not result["success"]:
        raise HTTPException(status_code=400, detail=result.get("error", "Conversion failed"))

    return {
        "success": True,
        "message": f"Quote converted to order {result['bc_order_number']}",
        "sales_order_id": result["sales_order_id"],
        "bc_order_number": result["bc_order_number"]
    }


# ==================== Production Orders ====================

class CreateProductionOrdersRequest(BaseModel):
    user_id: str = "system"


class UpdateProductionStatusRequest(BaseModel):
    status: str
    quantity_completed: Optional[int] = None
    user_id: str = "system"


@router.post("/{order_id}/production-orders")
async def create_production_orders(
    order_id: int,
    request: CreateProductionOrdersRequest,
    db: Session = Depends(get_db)
):
    """
    Create production orders from a sales order.

    This pulls line items from the original quote and creates production
    orders for each item type. Spring production orders include full
    Canimex specifications (wire diameter, coil diameter, IPPT, MIP, etc.).
    """
    from app.db.models import ProductionStatus

    result = order_lifecycle_service.create_production_orders(db, order_id, request.user_id)

    if not result["success"]:
        raise HTTPException(status_code=400, detail=result.get("error", "Failed to create production orders"))

    return {
        "success": True,
        "message": f"Created {len(result['production_orders'])} production orders",
        "sales_order_id": result["sales_order_id"],
        "production_orders": result["production_orders"],
        "inventory_warnings": result.get("inventory_warnings", [])
    }


@router.get("/{order_id}/production-orders")
async def get_production_orders(
    order_id: int,
    item_type: Optional[str] = Query(None, description="Filter by item type: door, spring, hardware"),
    status: Optional[str] = Query(None, description="Filter by status: planned, released, in_progress, finished"),
    db: Session = Depends(get_db)
):
    """
    Get production orders for a sales order.

    For spring items, includes full Canimex specifications:
    - Wire diameter, coil diameter, length
    - IPPT, MIP per spring, turns
    - Cycle life, drum model
    - Door weight and height
    """
    from app.db.models import ProductionStatus

    status_enum = None
    if status:
        try:
            status_enum = ProductionStatus(status)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid status: {status}")

    orders = order_lifecycle_service.get_production_orders(
        db,
        sales_order_id=order_id,
        status=status_enum,
        item_type=item_type
    )

    return {
        "sales_order_id": order_id,
        "count": len(orders),
        "production_orders": [
            {
                "id": po.id,
                "item_type": po.item_type,
                "item_code": po.item_code,
                "description": po.item_description,
                "quantity": po.quantity,
                "quantity_completed": po.quantity_completed,
                "status": po.status.value if po.status else None,
                "specifications": po.specifications,
                "inventory": {
                    "allocated": po.inventory_allocated,
                    "available": po.stock_available,
                    "reserved": po.stock_reserved
                },
                "due_date": po.due_date.isoformat() if po.due_date else None,
                "started_at": po.started_at.isoformat() if po.started_at else None,
                "finished_at": po.finished_at.isoformat() if po.finished_at else None
            }
            for po in orders
        ]
    }


@router.get("/{order_id}/spring-production-orders")
async def get_spring_production_orders(
    order_id: int,
    status: Optional[str] = Query(None),
    db: Session = Depends(get_db)
):
    """
    Get spring production orders with full Canimex specifications.

    Returns detailed spring data including:
    - Wire diameter (e.g., 0.234")
    - Coil diameter (e.g., 2.0")
    - Length (e.g., 27.5")
    - IPPT (Inch-Pounds Per Turn)
    - MIP per spring (Moment Inch-Pounds)
    - Number of turns
    - Cycle life (e.g., 10000)
    - Drum model (e.g., D400-96)
    - Door weight and height
    """
    from app.db.models import ProductionStatus

    status_enum = None
    if status:
        try:
            status_enum = ProductionStatus(status)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid status: {status}")

    spring_orders = order_lifecycle_service.get_spring_production_orders(
        db,
        sales_order_id=order_id,
        status=status_enum
    )

    return {
        "sales_order_id": order_id,
        "count": len(spring_orders),
        "spring_production_orders": spring_orders
    }


@router.patch("/production-orders/{production_order_id}/status")
async def update_production_status(
    production_order_id: int,
    request: UpdateProductionStatusRequest,
    db: Session = Depends(get_db)
):
    """
    Update production order status.

    Valid statuses: planned, released, in_progress, finished, cancelled

    When status changes to 'finished', the system checks if all production
    orders for the sales order are complete and updates the sales order
    to 'ready_to_ship' if so.
    """
    from app.db.models import ProductionStatus

    try:
        status_enum = ProductionStatus(request.status)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status: {request.status}. Valid values: planned, released, in_progress, finished, cancelled"
        )

    result = order_lifecycle_service.update_production_status(
        db,
        production_order_id,
        status_enum,
        request.user_id,
        quantity_completed=request.quantity_completed
    )

    if not result["success"]:
        raise HTTPException(status_code=400, detail=result.get("error", "Update failed"))

    return {
        "success": True,
        "message": f"Production order status updated to {request.status}",
        "production_order_id": result["production_order_id"],
        "old_status": result["old_status"],
        "new_status": result["new_status"],
        "quantity_completed": result["quantity_completed"]
    }


# ==================== Shipping ====================

@router.post("/{order_id}/ship")
async def ship_order(
    order_id: int,
    request: ShipOrderRequest,
    db: Session = Depends(get_db)
):
    """
    Ship a sales order.

    Creates a shipment in BC and updates local records.
    """
    result = order_lifecycle_service.ship_order(
        db, order_id, request.user_id,
        tracking_number=request.tracking_number,
        carrier=request.carrier
    )

    if not result["success"]:
        raise HTTPException(status_code=400, detail=result.get("error", "Ship failed"))

    return {
        "success": True,
        "message": "Order shipped successfully",
        "shipment_id": result.get("shipment_id"),
        "shipment_number": result.get("shipment_number")
    }


@router.post("/{order_id}/ship-and-invoice")
async def ship_and_invoice_order(
    order_id: int,
    user_id: str = Query("system"),
    db: Session = Depends(get_db)
):
    """
    Ship and invoice an order in one operation.

    This is the most common flow for completed production.
    """
    result = order_lifecycle_service.ship_and_invoice_order(db, order_id, user_id)

    if not result["success"]:
        raise HTTPException(status_code=400, detail=result.get("error", "Ship and invoice failed"))

    return {
        "success": True,
        "message": "Order shipped and invoiced successfully",
        "bc_order_number": result.get("bc_order_number"),
        "shipments": result.get("shipments"),
        "invoices": result.get("invoices")
    }


@router.get("/{order_id}/shipments")
async def get_order_shipments(
    order_id: int,
    db: Session = Depends(get_db)
):
    """Get all shipments for an order"""
    order = db.query(SalesOrder).filter(SalesOrder.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    return {
        "shipments": [
            {
                "id": s.id,
                "bc_shipment_id": s.bc_shipment_id,
                "shipment_number": s.shipment_number,
                "shipped_date": s.shipped_date.isoformat() if s.shipped_date else None,
                "tracking_number": s.tracking_number,
                "carrier": s.carrier,
                "ship_to_name": s.ship_to_name
            }
            for s in order.shipments
        ]
    }


# ==================== Invoicing ====================

@router.get("/{order_id}/invoices")
async def get_order_invoices(
    order_id: int,
    db: Session = Depends(get_db)
):
    """Get all invoices for an order"""
    order = db.query(SalesOrder).filter(SalesOrder.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    return {
        "invoices": [
            {
                "id": i.id,
                "bc_invoice_id": i.bc_invoice_id,
                "invoice_number": i.invoice_number,
                "status": i.status.value if i.status else None,
                "total_amount": float(i.total_amount) if i.total_amount else None,
                "tax_amount": float(i.tax_amount) if i.tax_amount else None,
                "due_date": i.due_date.isoformat() if i.due_date else None,
                "posted_at": i.posted_at.isoformat() if i.posted_at else None,
                "paid_at": i.paid_at.isoformat() if i.paid_at else None
            }
            for i in order.invoices
        ]
    }


@router.post("/invoices/{invoice_id}/post")
async def post_invoice(
    invoice_id: int,
    user_id: str = Query("system"),
    db: Session = Depends(get_db)
):
    """Post a draft invoice to the general ledger"""
    result = order_lifecycle_service.post_invoice(db, invoice_id, user_id)

    if not result["success"]:
        raise HTTPException(status_code=400, detail=result.get("error", "Post failed"))

    return {"success": True, "message": "Invoice posted successfully"}


# ==================== BC Direct Access ====================

@router.get("/bc/orders")
async def list_bc_orders(
    top: int = Query(20, ge=1, le=100),
    status: Optional[str] = None
):
    """
    List sales orders directly from Business Central.

    Useful for viewing orders not yet tracked locally.
    """
    try:
        orders = bc_client.get_sales_orders(top=top, status_filter=status)
        return {
            "count": len(orders),
            "orders": [
                {
                    "id": o.get("id"),
                    "number": o.get("number"),
                    "customerName": o.get("customerName"),
                    "status": o.get("status"),
                    "totalAmountIncludingTax": o.get("totalAmountIncludingTax"),
                    "orderDate": o.get("orderDate"),
                    "lastModifiedDateTime": o.get("lastModifiedDateTime")
                }
                for o in orders
            ]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/bc/quotes")
async def list_bc_quotes(
    top: int = Query(20, ge=1, le=100)
):
    """List sales quotes directly from Business Central"""
    try:
        quotes = bc_client.get_sales_quotes(top=top)
        return {
            "count": len(quotes),
            "quotes": [
                {
                    "id": q.get("id"),
                    "number": q.get("number"),
                    "customerName": q.get("customerName"),
                    "status": q.get("status"),
                    "totalAmountIncludingTax": q.get("totalAmountIncludingTax"),
                    "documentDate": q.get("documentDate")
                }
                for q in quotes
            ]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/bc/invoices")
async def list_bc_invoices(
    top: int = Query(20, ge=1, le=100)
):
    """List sales invoices directly from Business Central"""
    try:
        invoices = bc_client.get_sales_invoices(top=top)
        return {
            "count": len(invoices),
            "invoices": [
                {
                    "id": i.get("id"),
                    "number": i.get("number"),
                    "customerName": i.get("customerName"),
                    "status": i.get("status"),
                    "totalAmountIncludingTax": i.get("totalAmountIncludingTax"),
                    "dueDate": i.get("dueDate")
                }
                for i in invoices
            ]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/bc/shipments")
async def list_bc_shipments(
    top: int = Query(20, ge=1, le=100)
):
    """List sales shipments directly from Business Central"""
    try:
        shipments = bc_client.get_sales_shipments(top=top)
        return {
            "count": len(shipments),
            "shipments": [
                {
                    "id": s.get("id"),
                    "number": s.get("number"),
                    "orderNumber": s.get("orderNumber"),
                    "customerName": s.get("customerName"),
                    "shipmentDate": s.get("shipmentDate")
                }
                for s in shipments
            ]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/bc/quotes/{quote_id}/convert-to-order")
async def convert_bc_quote_to_order(quote_id: str):
    """
    Convert a BC sales quote directly to a sales order.

    Uses BC's makeOrder bound action to create the order.
    The quote will be archived/deleted in BC after conversion.

    Args:
        quote_id: The BC quote GUID (from /bc/quotes endpoint)

    Returns:
        The newly created sales order details
    """
    try:
        # Call BC's makeOrder action
        result = bc_client.convert_quote_to_order(quote_id)

        return {
            "success": True,
            "message": f"Quote converted to order {result.get('number', 'N/A')}",
            "order": {
                "id": result.get("id"),
                "number": result.get("number"),
                "customerName": result.get("customerName"),
                "status": result.get("status"),
                "totalAmountIncludingTax": result.get("totalAmountIncludingTax"),
                "orderDate": result.get("orderDate")
            }
        }
    except Exception as e:
        logger.error(f"Failed to convert BC quote to order: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/bc/discover")
async def discover_bc_apis():
    """
    Discover available BC API endpoints.

    Useful for finding custom APIs for production orders, etc.
    """
    try:
        discovered = bc_client.discover_custom_apis()
        return {
            "success": True,
            "endpoints": discovered
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
