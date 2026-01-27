"""
Customer Portal API Endpoints
Saved quotes, BC quotes, orders, and history for customer users
"""

import logging
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional, List, Any

from app.db.database import SessionLocal
from app.db.models import User, SavedQuoteConfig, SalesOrder, Shipment, Invoice, BCCustomer
from app.api.customer_auth import get_current_customer
from app.integrations.bc.client import bc_client

router = APIRouter(prefix="/api/customer/portal", tags=["customer-portal"])
logger = logging.getLogger(__name__)


# Dependency to get DB session
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ============================================================================
# REQUEST/RESPONSE MODELS
# ============================================================================

class SavedQuoteConfigCreate(BaseModel):
    """Create saved quote config"""
    name: str
    description: Optional[str] = None
    config_data: dict


class SavedQuoteConfigUpdate(BaseModel):
    """Update saved quote config"""
    name: Optional[str] = None
    description: Optional[str] = None
    config_data: Optional[dict] = None


class SavedQuoteConfigResponse(BaseModel):
    """Saved quote config response"""
    id: int
    name: Optional[str]
    description: Optional[str]
    config_data: dict
    is_submitted: bool
    bc_quote_number: Optional[str]
    bc_quote_id: Optional[str]
    created_at: datetime
    updated_at: Optional[datetime]
    submitted_at: Optional[datetime]

    class Config:
        from_attributes = True


class BCQuoteResponse(BaseModel):
    """BC Quote response"""
    id: str
    number: str
    customer_id: Optional[str]
    customer_name: Optional[str]
    document_date: Optional[str]
    due_date: Optional[str]
    status: Optional[str]
    total_amount: Optional[float]
    currency_code: Optional[str]


class BCQuoteLineResponse(BaseModel):
    """BC Quote line response"""
    id: str
    line_number: int
    item_id: Optional[str]
    description: Optional[str]
    quantity: float
    unit_price: float
    line_amount: float


class OrderResponse(BaseModel):
    """Order response for customer"""
    id: int
    bc_order_id: Optional[str]
    bc_order_number: Optional[str]
    status: str
    total_amount: Optional[float]
    currency: Optional[str]
    created_at: datetime
    confirmed_at: Optional[datetime]
    shipped_at: Optional[datetime]
    invoiced_at: Optional[datetime]

    class Config:
        from_attributes = True


class ShipmentResponse(BaseModel):
    """Shipment response"""
    id: int
    shipment_number: Optional[str]
    shipped_date: Optional[datetime]
    tracking_number: Optional[str]
    carrier: Optional[str]
    ship_to_name: Optional[str]
    delivered_at: Optional[datetime]

    class Config:
        from_attributes = True


class InvoiceResponse(BaseModel):
    """Invoice response"""
    id: int
    invoice_number: Optional[str]
    status: str
    total_amount: Optional[float]
    due_date: Optional[datetime]
    amount_paid: Optional[float]
    amount_remaining: Optional[float]
    posted_at: Optional[datetime]
    paid_at: Optional[datetime]

    class Config:
        from_attributes = True


class OrderDetailResponse(BaseModel):
    """Full order detail with shipments and invoices"""
    order: OrderResponse
    shipments: List[ShipmentResponse]
    invoices: List[InvoiceResponse]


class TrackingEvent(BaseModel):
    """Tracking event in timeline"""
    event_type: str
    description: str
    timestamp: Optional[datetime]
    status: str  # completed, current, pending


class OrderTrackingResponse(BaseModel):
    """Order tracking timeline"""
    order_number: Optional[str]
    current_status: str
    timeline: List[TrackingEvent]
    shipments: List[ShipmentResponse]


# ============================================================================
# SAVED QUOTE CONFIG ENDPOINTS
# ============================================================================

@router.get("/saved-quotes", response_model=List[SavedQuoteConfigResponse])
def list_saved_quotes(
    current_user: User = Depends(get_current_customer),
    db: Session = Depends(get_db)
):
    """List all saved quote configurations for current customer"""
    configs = db.query(SavedQuoteConfig).filter(
        SavedQuoteConfig.user_id == current_user.id
    ).order_by(SavedQuoteConfig.created_at.desc()).all()

    return configs


@router.post("/saved-quotes", response_model=SavedQuoteConfigResponse)
def create_saved_quote(
    config_data: SavedQuoteConfigCreate,
    current_user: User = Depends(get_current_customer),
    db: Session = Depends(get_db)
):
    """Save a new door configuration draft"""
    config = SavedQuoteConfig(
        user_id=current_user.id,
        name=config_data.name,
        description=config_data.description,
        config_data=config_data.config_data,
        is_submitted=False
    )

    db.add(config)
    db.commit()
    db.refresh(config)

    logger.info(f"Saved quote config created: {config.id} for user {current_user.email}")

    return config


@router.get("/saved-quotes/{config_id}", response_model=SavedQuoteConfigResponse)
def get_saved_quote(
    config_id: int,
    current_user: User = Depends(get_current_customer),
    db: Session = Depends(get_db)
):
    """Get a specific saved quote configuration"""
    config = db.query(SavedQuoteConfig).filter(
        SavedQuoteConfig.id == config_id,
        SavedQuoteConfig.user_id == current_user.id
    ).first()

    if not config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Saved configuration not found"
        )

    return config


@router.put("/saved-quotes/{config_id}", response_model=SavedQuoteConfigResponse)
def update_saved_quote(
    config_id: int,
    update_data: SavedQuoteConfigUpdate,
    current_user: User = Depends(get_current_customer),
    db: Session = Depends(get_db)
):
    """Update a saved quote configuration"""
    config = db.query(SavedQuoteConfig).filter(
        SavedQuoteConfig.id == config_id,
        SavedQuoteConfig.user_id == current_user.id
    ).first()

    if not config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Saved configuration not found"
        )

    if config.is_submitted:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot modify a submitted configuration"
        )

    if update_data.name is not None:
        config.name = update_data.name
    if update_data.description is not None:
        config.description = update_data.description
    if update_data.config_data is not None:
        config.config_data = update_data.config_data

    config.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(config)

    logger.info(f"Saved quote config updated: {config.id}")

    return config


@router.delete("/saved-quotes/{config_id}")
def delete_saved_quote(
    config_id: int,
    current_user: User = Depends(get_current_customer),
    db: Session = Depends(get_db)
):
    """Delete a saved quote configuration"""
    config = db.query(SavedQuoteConfig).filter(
        SavedQuoteConfig.id == config_id,
        SavedQuoteConfig.user_id == current_user.id
    ).first()

    if not config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Saved configuration not found"
        )

    if config.is_submitted:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete a submitted configuration"
        )

    db.delete(config)
    db.commit()

    logger.info(f"Saved quote config deleted: {config_id}")

    return {"message": "Configuration deleted successfully"}


@router.post("/saved-quotes/{config_id}/submit", response_model=SavedQuoteConfigResponse)
def submit_saved_quote(
    config_id: int,
    current_user: User = Depends(get_current_customer),
    db: Session = Depends(get_db)
):
    """Submit a saved configuration to create a BC quote"""
    config = db.query(SavedQuoteConfig).filter(
        SavedQuoteConfig.id == config_id,
        SavedQuoteConfig.user_id == current_user.id
    ).first()

    if not config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Saved configuration not found"
        )

    if config.is_submitted:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Configuration has already been submitted"
        )

    if not current_user.bc_customer_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Your account is not linked to a Business Central customer. Please contact support."
        )

    try:
        # Parse config data
        door_config = config.config_data or {}

        # Build description from config
        description_parts = []
        if door_config.get("door_type"):
            description_parts.append(door_config["door_type"].title())
        if door_config.get("width") and door_config.get("height"):
            description_parts.append(f'{door_config["width"]}" x {door_config["height"]}"')
        if door_config.get("color"):
            description_parts.append(door_config["color"])
        if door_config.get("window_type") and door_config["window_type"] != "none":
            description_parts.append(f"Windows: {door_config['window_type']}")

        door_description = " - ".join(description_parts) if description_parts else "Custom Door Configuration"

        # Create quote in BC
        quote_data = {
            "customerId": current_user.bc_customer_id,
            "externalDocumentNumber": f"PORTAL-{config.id}",
        }

        # Try to create quote in BC
        bc_quote = bc_client.create_sales_quote(quote_data)

        if not bc_quote:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to create quote in Business Central"
            )

        quote_id = bc_quote.get("id")

        # Add line item for the door configuration
        try:
            line_data = {
                "lineType": "Comment",  # Use Comment for custom descriptions, or "Item" if you have item numbers
                "description": door_description,
            }

            # If we have more detailed config, add additional comment lines
            bc_client.add_quote_line(quote_id, line_data)

            # Add notes as a separate line if present
            if door_config.get("notes"):
                notes_line = {
                    "lineType": "Comment",
                    "description": f"Notes: {door_config['notes'][:250]}"  # Truncate long notes
                }
                bc_client.add_quote_line(quote_id, notes_line)

            # Add detailed specifications as comment lines
            spec_lines = []
            if door_config.get("door_type"):
                spec_lines.append(f"Type: {door_config['door_type'].title()}")
            if door_config.get("width"):
                spec_lines.append(f"Width: {door_config['width']}\"")
            if door_config.get("height"):
                spec_lines.append(f"Height: {door_config['height']}\"")
            if door_config.get("color"):
                spec_lines.append(f"Color: {door_config['color']}")
            if door_config.get("panel_design"):
                spec_lines.append(f"Panel Design: {door_config['panel_design']}")
            if door_config.get("window_type") and door_config["window_type"] != "none":
                spec_lines.append(f"Windows: {door_config['window_type']}")
            if door_config.get("track_type"):
                spec_lines.append(f"Track: {door_config['track_type']}")

            if spec_lines:
                for spec in spec_lines:
                    spec_line_data = {
                        "lineType": "Comment",
                        "description": spec
                    }
                    bc_client.add_quote_line(quote_id, spec_line_data)

            logger.info(f"Added {len(spec_lines) + 2} line items to BC quote {quote_id}")

        except Exception as line_error:
            logger.warning(f"Failed to add some line items to quote: {line_error}")
            # Continue - quote header was created successfully

        # Update local record
        config.is_submitted = True
        config.submitted_at = datetime.utcnow()
        config.bc_quote_id = quote_id
        config.bc_quote_number = bc_quote.get("number")
        db.commit()
        db.refresh(config)

        logger.info(f"Quote submitted to BC: {config.bc_quote_number} for config {config_id}")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error submitting quote to BC: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to submit quote: {str(e)}"
        )

    return config


# ============================================================================
# BC QUOTES ENDPOINTS
# ============================================================================

@router.get("/bc-quotes", response_model=List[BCQuoteResponse])
def list_bc_quotes(
    current_user: User = Depends(get_current_customer),
    db: Session = Depends(get_db)
):
    """List all BC quotes for current customer"""
    if not current_user.bc_customer_id:
        return []

    try:
        quotes = bc_client.get_customer_quotes(current_user.bc_customer_id)
        return [
            BCQuoteResponse(
                id=q.get("id", ""),
                number=q.get("number", ""),
                customer_id=q.get("customerId"),
                customer_name=q.get("customerName"),
                document_date=q.get("documentDate"),
                due_date=q.get("dueDate"),
                status=q.get("status"),
                total_amount=q.get("totalAmountIncludingTax"),
                currency_code=q.get("currencyCode")
            )
            for q in quotes
        ]
    except Exception as e:
        logger.error(f"Error fetching BC quotes: {e}")
        return []


@router.get("/bc-quotes/{quote_id}")
def get_bc_quote_detail(
    quote_id: str,
    current_user: User = Depends(get_current_customer),
    db: Session = Depends(get_db)
):
    """Get BC quote details with line items"""
    if not current_user.bc_customer_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account not linked to Business Central customer"
        )

    try:
        # Get quote
        quote = bc_client.get_sales_quote(quote_id)
        if not quote:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Quote not found"
            )

        # Verify this quote belongs to the customer
        if quote.get("customerId") != current_user.bc_customer_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied"
            )

        # Get quote lines
        lines = bc_client.get_quote_lines(quote_id)

        return {
            "quote": BCQuoteResponse(
                id=quote.get("id", ""),
                number=quote.get("number", ""),
                customer_id=quote.get("customerId"),
                customer_name=quote.get("customerName"),
                document_date=quote.get("documentDate"),
                due_date=quote.get("dueDate"),
                status=quote.get("status"),
                total_amount=quote.get("totalAmountIncludingTax"),
                currency_code=quote.get("currencyCode")
            ),
            "lines": [
                BCQuoteLineResponse(
                    id=line.get("id", ""),
                    line_number=line.get("lineNumber", 0),
                    item_id=line.get("itemId"),
                    description=line.get("description"),
                    quantity=line.get("quantity", 0),
                    unit_price=line.get("unitPrice", 0),
                    line_amount=line.get("lineAmount", 0)
                )
                for line in lines
            ]
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching BC quote detail: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch quote details"
        )


# ============================================================================
# ORDERS ENDPOINTS
# ============================================================================

@router.get("/orders", response_model=List[OrderResponse])
def list_orders(
    current_user: User = Depends(get_current_customer),
    db: Session = Depends(get_db)
):
    """List all orders for current customer"""
    if not current_user.bc_customer_id:
        return []

    # Get orders from local DB
    orders = db.query(SalesOrder).filter(
        SalesOrder.customer_id == current_user.bc_customer_id
    ).order_by(SalesOrder.created_at.desc()).all()

    return [
        OrderResponse(
            id=order.id,
            bc_order_id=order.bc_order_id,
            bc_order_number=order.bc_order_number,
            status=order.status.value,
            total_amount=float(order.total_amount) if order.total_amount else None,
            currency=order.currency,
            created_at=order.created_at,
            confirmed_at=order.confirmed_at,
            shipped_at=order.shipped_at,
            invoiced_at=order.invoiced_at
        )
        for order in orders
    ]


@router.get("/orders/{order_id}", response_model=OrderDetailResponse)
def get_order_detail(
    order_id: int,
    current_user: User = Depends(get_current_customer),
    db: Session = Depends(get_db)
):
    """Get order detail with shipments and invoices"""
    if not current_user.bc_customer_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account not linked to Business Central customer"
        )

    order = db.query(SalesOrder).filter(
        SalesOrder.id == order_id,
        SalesOrder.customer_id == current_user.bc_customer_id
    ).first()

    if not order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Order not found"
        )

    # Get shipments
    shipments = db.query(Shipment).filter(
        Shipment.sales_order_id == order.id
    ).all()

    # Get invoices
    invoices = db.query(Invoice).filter(
        Invoice.sales_order_id == order.id
    ).all()

    return OrderDetailResponse(
        order=OrderResponse(
            id=order.id,
            bc_order_id=order.bc_order_id,
            bc_order_number=order.bc_order_number,
            status=order.status.value,
            total_amount=float(order.total_amount) if order.total_amount else None,
            currency=order.currency,
            created_at=order.created_at,
            confirmed_at=order.confirmed_at,
            shipped_at=order.shipped_at,
            invoiced_at=order.invoiced_at
        ),
        shipments=[
            ShipmentResponse(
                id=s.id,
                shipment_number=s.shipment_number,
                shipped_date=s.shipped_date,
                tracking_number=s.tracking_number,
                carrier=s.carrier,
                ship_to_name=s.ship_to_name,
                delivered_at=s.delivered_at
            )
            for s in shipments
        ],
        invoices=[
            InvoiceResponse(
                id=i.id,
                invoice_number=i.invoice_number,
                status=i.status.value,
                total_amount=float(i.total_amount) if i.total_amount else None,
                due_date=i.due_date,
                amount_paid=float(i.amount_paid) if i.amount_paid else None,
                amount_remaining=float(i.amount_remaining) if i.amount_remaining else None,
                posted_at=i.posted_at,
                paid_at=i.paid_at
            )
            for i in invoices
        ]
    )


@router.get("/orders/{order_id}/tracking", response_model=OrderTrackingResponse)
def get_order_tracking(
    order_id: int,
    current_user: User = Depends(get_current_customer),
    db: Session = Depends(get_db)
):
    """Get order tracking timeline"""
    if not current_user.bc_customer_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account not linked to Business Central customer"
        )

    order = db.query(SalesOrder).filter(
        SalesOrder.id == order_id,
        SalesOrder.customer_id == current_user.bc_customer_id
    ).first()

    if not order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Order not found"
        )

    # Build tracking timeline
    timeline = []

    # Order placed
    timeline.append(TrackingEvent(
        event_type="order_placed",
        description="Order placed",
        timestamp=order.created_at,
        status="completed"
    ))

    # Order confirmed
    if order.confirmed_at:
        timeline.append(TrackingEvent(
            event_type="order_confirmed",
            description="Order confirmed",
            timestamp=order.confirmed_at,
            status="completed"
        ))
    else:
        timeline.append(TrackingEvent(
            event_type="order_confirmed",
            description="Order confirmation",
            timestamp=None,
            status="pending" if order.status.value == "pending" else "current"
        ))

    # In production
    if order.production_started_at:
        timeline.append(TrackingEvent(
            event_type="in_production",
            description="In production",
            timestamp=order.production_started_at,
            status="completed"
        ))
    elif order.confirmed_at:
        timeline.append(TrackingEvent(
            event_type="in_production",
            description="Production",
            timestamp=None,
            status="current" if order.status.value in ["confirmed", "in_production"] else "pending"
        ))

    # Shipped
    if order.shipped_at:
        timeline.append(TrackingEvent(
            event_type="shipped",
            description="Shipped",
            timestamp=order.shipped_at,
            status="completed"
        ))
    elif order.production_completed_at:
        timeline.append(TrackingEvent(
            event_type="shipped",
            description="Shipping",
            timestamp=None,
            status="current" if order.status.value == "ready_to_ship" else "pending"
        ))

    # Invoiced
    if order.invoiced_at:
        timeline.append(TrackingEvent(
            event_type="invoiced",
            description="Invoiced",
            timestamp=order.invoiced_at,
            status="completed"
        ))

    # Completed
    if order.completed_at:
        timeline.append(TrackingEvent(
            event_type="completed",
            description="Completed",
            timestamp=order.completed_at,
            status="completed"
        ))

    # Get shipments
    shipments = db.query(Shipment).filter(
        Shipment.sales_order_id == order.id
    ).all()

    return OrderTrackingResponse(
        order_number=order.bc_order_number,
        current_status=order.status.value,
        timeline=timeline,
        shipments=[
            ShipmentResponse(
                id=s.id,
                shipment_number=s.shipment_number,
                shipped_date=s.shipped_date,
                tracking_number=s.tracking_number,
                carrier=s.carrier,
                ship_to_name=s.ship_to_name,
                delivered_at=s.delivered_at
            )
            for s in shipments
        ]
    )


# ============================================================================
# HISTORY ENDPOINTS
# ============================================================================

@router.get("/history")
def get_customer_history(
    current_user: User = Depends(get_current_customer),
    db: Session = Depends(get_db)
):
    """Get customer history - past orders and invoices summary"""
    if not current_user.bc_customer_id:
        return {
            "total_orders": 0,
            "total_spent": 0,
            "recent_orders": [],
            "recent_invoices": []
        }

    # Get completed orders count and total
    completed_orders = db.query(SalesOrder).filter(
        SalesOrder.customer_id == current_user.bc_customer_id,
        SalesOrder.status.in_(["completed", "invoiced"])
    ).all()

    total_spent = sum(
        float(o.total_amount) for o in completed_orders
        if o.total_amount
    )

    # Get recent orders
    recent_orders = db.query(SalesOrder).filter(
        SalesOrder.customer_id == current_user.bc_customer_id
    ).order_by(SalesOrder.created_at.desc()).limit(5).all()

    # Get recent invoices
    order_ids = [o.id for o in recent_orders]
    recent_invoices = db.query(Invoice).filter(
        Invoice.sales_order_id.in_(order_ids)
    ).order_by(Invoice.created_at.desc()).limit(5).all()

    return {
        "total_orders": len(completed_orders),
        "total_spent": total_spent,
        "currency": "CAD",
        "recent_orders": [
            {
                "id": o.id,
                "bc_order_number": o.bc_order_number,
                "status": o.status.value,
                "total_amount": float(o.total_amount) if o.total_amount else None,
                "created_at": o.created_at.isoformat() if o.created_at else None
            }
            for o in recent_orders
        ],
        "recent_invoices": [
            {
                "id": i.id,
                "invoice_number": i.invoice_number,
                "status": i.status.value,
                "total_amount": float(i.total_amount) if i.total_amount else None,
                "due_date": i.due_date.isoformat() if i.due_date else None
            }
            for i in recent_invoices
        ]
    }
