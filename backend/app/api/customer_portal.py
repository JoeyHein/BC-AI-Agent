"""
Customer Portal API Endpoints
Saved quotes, BC quotes, orders, and history for customer users
"""

import logging
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional, List, Any, Dict

from app.db.database import SessionLocal
from app.db.models import User, SavedQuoteConfig, SalesOrder, Shipment, Invoice, BCCustomer
from app.api.customer_auth import get_current_customer
from app.integrations.bc.client import bc_client
from app.services.part_number_service import get_parts_for_door_config

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
        # Config changed - clear stale BC quote so pricing must be re-requested
        if config.bc_quote_id:
            try:
                bc_client.delete_sales_quote(config.bc_quote_id)
                logger.info(f"Deleted stale BC quote {config.bc_quote_number} after config update")
            except Exception as e:
                logger.warning(f"Could not delete stale BC quote {config.bc_quote_id}: {e}")
            config.bc_quote_id = None
            config.bc_quote_number = None

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


# ============================================================================
# QUOTE PRICING HELPERS (mirrors admin door_configurator.py generate-quote logic)
# ============================================================================

# Standard line item ordering for BC quotes (same as door_configurator.py)
LINE_ORDER = [
    "comment", "panel", "retainer", "astragal", "strut", "window",
    "track", "highlift_track", "hardware", "spring", "spring_accessory",
    "shaft", "weather_stripping", "accessory", "operator",
]


def _sort_parts_by_category(parts: List[dict]) -> List[dict]:
    """Sort parts list according to BC quote line ordering standard."""
    def sort_key(part):
        category = part.get("category", "other").lower()
        try:
            return LINE_ORDER.index(category)
        except ValueError:
            return len(LINE_ORDER)
    return sorted(parts, key=sort_key)


def _format_door_description(door: dict) -> str:
    """Format door description for BC quote comment line."""
    width_ft = door.get("doorWidth", 0) // 12
    height_ft = door.get("doorHeight", 0) // 12
    track_display = f"{door.get('trackThickness', '2')}\" HW"
    lift_type = "LHR" if door.get("trackRadius") == "12" else "STD LIFT"
    return (
        f"({door.get('doorCount', 1)}) {width_ft}x{height_ft} "
        f"{door.get('doorSeries', '')}, {door.get('panelColor', '')}, "
        f"{door.get('panelDesign', '')}, {track_display}, {lift_type}"
    )


def _validate_doors_config(config_data: dict) -> List[dict]:
    """Validate and extract doors from config_data. Raises HTTPException on failure."""
    doors = config_data.get("doors", [])
    if not doors:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No doors found in configuration. Please add at least one door."
        )
    for i, door in enumerate(doors):
        missing = []
        if not door.get("doorSeries"):
            missing.append("series")
        if not door.get("doorWidth"):
            missing.append("width")
        if not door.get("doorHeight"):
            missing.append("height")
        if missing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Door {i + 1} is missing required fields: {', '.join(missing)}"
            )
    return doors


def _generate_bc_quote_with_items(
    doors: List[dict],
    bc_customer_id: str,
    config_id: int,
) -> Dict[str, Any]:
    """
    Create a BC sales quote with real item lines for all doors.

    Returns dict with: bc_quote_id, bc_quote_number, lines_added, lines_failed,
    pricing, line_pricing, door_results
    """
    # Step 1: Build all ordered lines from door configs
    all_lines = []
    door_results = []

    for i, door in enumerate(doors):
        door_index = i + 1
        door_desc = _format_door_description(door)

        # Comment line for this door
        all_lines.append({
            "lineType": "Comment",
            "description": door_desc,
            "category": "COMMENT",
            "door_index": door_index,
        })

        # Get parts for this door configuration
        config_dict = {
            "doorType": door.get("doorType", "residential"),
            "doorSeries": door.get("doorSeries"),
            "doorWidth": door.get("doorWidth"),
            "doorHeight": door.get("doorHeight"),
            "doorCount": door.get("doorCount", 1),
            "panelColor": door.get("panelColor", "WHITE"),
            "panelDesign": door.get("panelDesign", "SHXL"),
            "windowInsert": door.get("windowInsert"),
            "windowPositions": door.get("windowPositions", []),
            "windowCount": door.get("windowCount") or (
                len(door.get("windowPositions", [])) if door.get("windowPositions")
                else (door.get("windowQty", 0) if door.get("windowQty")
                      else (1 if door.get("windowSection") else 0))
            ),
            "windowSection": door.get("windowSection"),
            "glazingType": door.get("glazingType"),
            "trackRadius": door.get("trackRadius", "15"),
            "trackThickness": door.get("trackThickness", "2"),
            "hardware": door.get("hardware", {}),
            "operator": door.get("operator"),
        }

        try:
            door_parts = get_parts_for_door_config(config_dict)
            parts_list = door_parts.get("parts_list", [])
            sorted_parts = _sort_parts_by_category(parts_list)

            for part in sorted_parts:
                part["door_index"] = door_index
                all_lines.append(part)

            door_results.append({
                "door_index": door_index,
                "door_description": door_desc,
                "parts_count": len(parts_list),
                "success": True,
            })
        except Exception as e:
            logger.warning(f"Failed to get parts for door {door_index}: {e}")
            door_results.append({
                "door_index": door_index,
                "door_description": door_desc,
                "parts_count": 0,
                "success": False,
                "error": str(e),
            })

    # Step 2: Create BC Quote
    quote_data = {
        "customerId": bc_customer_id,
        "externalDocumentNumber": f"PORTAL-{config_id}",
    }
    bc_quote = bc_client.create_sales_quote(quote_data)
    if not bc_quote:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create quote in Business Central"
        )
    bc_quote_id = bc_quote.get("id")
    bc_quote_number = bc_quote.get("number")
    logger.info(f"Created BC quote: {bc_quote_number} (ID: {bc_quote_id})")

    # Step 3: Add line items
    lines_added = 0
    lines_failed = []

    for line in all_lines:
        try:
            if line.get("lineType") == "Comment":
                line_data = {
                    "lineType": "Comment",
                    "description": line["description"],
                }
            else:
                line_data = {
                    "lineType": "Item",
                    "lineObjectNumber": line["part_number"],
                    "description": line.get("description", ""),
                    "quantity": line["quantity"],
                }

            bc_client.add_quote_line(bc_quote_id, line_data)
            lines_added += 1

        except Exception as line_error:
            part_id = line.get("part_number", line.get("description", "unknown"))
            logger.warning(f"Failed to add line {part_id}: {line_error}")

            # Fall back to comment line for failed items
            if line.get("lineType") != "Comment" and line.get("part_number"):
                try:
                    comment_line = {
                        "lineType": "Comment",
                        "description": f"{line['part_number']} - {line.get('description', '')} (Qty: {line['quantity']})",
                    }
                    bc_client.add_quote_line(bc_quote_id, comment_line)
                    lines_added += 1
                    lines_failed.append({
                        "part_number": line.get("part_number"),
                        "description": line.get("description", ""),
                        "error": str(line_error),
                        "fallback": "comment",
                    })
                except Exception:
                    lines_failed.append({
                        "part_number": line.get("part_number"),
                        "description": line.get("description", ""),
                        "error": str(line_error),
                        "fallback": "failed",
                    })
            else:
                lines_failed.append({
                    "part_number": part_id,
                    "error": str(line_error),
                })

    # Step 4: Fetch pricing back from BC
    pricing = None
    line_pricing = []
    try:
        updated_quote = bc_client.get_sales_quote(bc_quote_id)
        quote_lines = bc_client.get_quote_lines(bc_quote_id)

        subtotal = updated_quote.get("totalAmountExcludingTax", 0)
        total_with_tax = updated_quote.get("totalAmountIncludingTax", 0)
        tax_amount = total_with_tax - subtotal

        pricing = {
            "subtotal": round(subtotal, 2),
            "tax": round(tax_amount, 2),
            "total": round(total_with_tax, 2),
            "currency": "CAD",
        }

        for ql in quote_lines:
            line_pricing.append({
                "line_type": ql.get("lineType", ""),
                "part_number": ql.get("lineObjectNumber", ""),
                "description": ql.get("description", ""),
                "quantity": ql.get("quantity", 0),
                "unit_price": ql.get("unitPrice", 0),
                "line_total": ql.get("netAmount", 0),
                "door_index": None,  # BC doesn't track this, but comments delimit doors
            })

    except Exception as pricing_error:
        logger.warning(f"Could not fetch pricing for quote {bc_quote_number}: {pricing_error}")

    return {
        "bc_quote_id": bc_quote_id,
        "bc_quote_number": bc_quote_number,
        "lines_added": lines_added,
        "lines_failed": lines_failed if lines_failed else None,
        "pricing": pricing,
        "line_pricing": line_pricing if line_pricing else None,
        "door_results": door_results,
    }


# ============================================================================
# PRICING ENDPOINTS
# ============================================================================

@router.post("/saved-quotes/{config_id}/get-pricing")
def get_pricing_for_saved_quote(
    config_id: int,
    current_user: User = Depends(get_current_customer),
    db: Session = Depends(get_db)
):
    """
    Generate a real BC sales quote with item lines to get customer-specific pricing.

    Creates the quote in BC with the customer's ID so BC applies their pricing.
    Stores the bc_quote_id on the saved config but does NOT mark as submitted.
    """
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

    # If there's already a BC quote from a previous pricing request, delete it first
    if config.bc_quote_id:
        try:
            bc_client.delete_sales_quote(config.bc_quote_id)
            logger.info(f"Deleted previous BC quote {config.bc_quote_number} for config {config_id}")
        except Exception as e:
            logger.warning(f"Could not delete previous BC quote {config.bc_quote_id}: {e}")

    try:
        doors = _validate_doors_config(config.config_data or {})

        result = _generate_bc_quote_with_items(
            doors=doors,
            bc_customer_id=current_user.bc_customer_id,
            config_id=config.id,
        )

        # Store BC quote reference (but NOT submitted)
        config.bc_quote_id = result["bc_quote_id"]
        config.bc_quote_number = result["bc_quote_number"]
        config.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(config)

        logger.info(
            f"Pricing generated for config {config_id}: "
            f"BC Quote {result['bc_quote_number']}, "
            f"{result['lines_added']} lines"
        )

        return {
            "success": True,
            "config_id": config.id,
            "bc_quote_id": result["bc_quote_id"],
            "bc_quote_number": result["bc_quote_number"],
            "lines_added": result["lines_added"],
            "lines_failed": result["lines_failed"],
            "pricing": result["pricing"],
            "line_pricing": result["line_pricing"],
            "door_results": result["door_results"],
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error generating pricing for config {config_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate pricing: {str(e)}"
        )


@router.post("/saved-quotes/{config_id}/confirm", response_model=SavedQuoteConfigResponse)
def confirm_saved_quote(
    config_id: int,
    current_user: User = Depends(get_current_customer),
    db: Session = Depends(get_db)
):
    """
    Confirm a priced quote - marks it as submitted.

    Requires that pricing has already been generated (bc_quote_id exists).
    """
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

    if not config.bc_quote_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Pricing has not been generated yet. Please get pricing first."
        )

    config.is_submitted = True
    config.submitted_at = datetime.utcnow()
    db.commit()
    db.refresh(config)

    logger.info(f"Quote confirmed: config {config_id}, BC Quote {config.bc_quote_number}")

    return config


@router.post("/saved-quotes/{config_id}/refresh-pricing")
def refresh_pricing_for_saved_quote(
    config_id: int,
    current_user: User = Depends(get_current_customer),
    db: Session = Depends(get_db)
):
    """
    Refresh pricing for a saved quote after config changes.

    Deletes the old BC quote (if any) and generates a new one.
    """
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
            detail="Cannot refresh pricing on a submitted configuration"
        )

    if not current_user.bc_customer_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Your account is not linked to a Business Central customer. Please contact support."
        )

    # Delete old BC quote if one exists
    if config.bc_quote_id:
        try:
            bc_client.delete_sales_quote(config.bc_quote_id)
            logger.info(f"Deleted old BC quote {config.bc_quote_number} for refresh")
        except Exception as e:
            logger.warning(f"Could not delete old BC quote {config.bc_quote_id}: {e}")

    try:
        doors = _validate_doors_config(config.config_data or {})

        result = _generate_bc_quote_with_items(
            doors=doors,
            bc_customer_id=current_user.bc_customer_id,
            config_id=config.id,
        )

        config.bc_quote_id = result["bc_quote_id"]
        config.bc_quote_number = result["bc_quote_number"]
        config.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(config)

        logger.info(f"Pricing refreshed for config {config_id}: BC Quote {result['bc_quote_number']}")

        return {
            "success": True,
            "config_id": config.id,
            "bc_quote_id": result["bc_quote_id"],
            "bc_quote_number": result["bc_quote_number"],
            "lines_added": result["lines_added"],
            "lines_failed": result["lines_failed"],
            "pricing": result["pricing"],
            "line_pricing": result["line_pricing"],
            "door_results": result["door_results"],
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error refreshing pricing for config {config_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to refresh pricing: {str(e)}"
        )


@router.post("/saved-quotes/{config_id}/submit", response_model=SavedQuoteConfigResponse)
def submit_saved_quote(
    config_id: int,
    current_user: User = Depends(get_current_customer),
    db: Session = Depends(get_db)
):
    """
    Submit a saved configuration.

    If the quote already has BC pricing (bc_quote_id), just confirms it.
    If no pricing yet, generates the full BC quote with item lines first, then confirms.
    """
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
        # If no BC quote yet, generate one with real item lines
        if not config.bc_quote_id:
            doors = _validate_doors_config(config.config_data or {})

            result = _generate_bc_quote_with_items(
                doors=doors,
                bc_customer_id=current_user.bc_customer_id,
                config_id=config.id,
            )

            config.bc_quote_id = result["bc_quote_id"]
            config.bc_quote_number = result["bc_quote_number"]

        # Mark as submitted
        config.is_submitted = True
        config.submitted_at = datetime.utcnow()
        db.commit()
        db.refresh(config)

        logger.info(f"Quote submitted: config {config_id}, BC Quote {config.bc_quote_number}")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error submitting quote for config {config_id}: {e}", exc_info=True)
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


@router.get("/bc-quotes/{quote_id}/pdf")
def download_customer_quote_pdf(
    quote_id: str,
    current_user: User = Depends(get_current_customer),
    db: Session = Depends(get_db)
):
    """
    Download quote PDF from Business Central for the customer portal.

    Uses BC's built-in PDF generation. Verifies the quote belongs to the customer.
    """
    if not current_user.bc_customer_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account not linked to Business Central customer"
        )

    try:
        # Verify quote belongs to customer
        quote = bc_client.get_sales_quote(quote_id)
        if not quote:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Quote not found"
            )

        if quote.get("customerId") != current_user.bc_customer_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied"
            )

        # Download PDF from BC
        pdf_bytes = bc_client.get_quote_pdf(quote_id)

        ext_doc = quote.get("externalDocumentNumber", "")
        filename = f"Quote_{ext_doc or quote.get('number', quote_id)}.pdf"

        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"'
            }
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error downloading quote PDF: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to download quote PDF"
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
