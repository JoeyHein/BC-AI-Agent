"""
Customer Portal API Endpoints
Saved quotes, BC quotes, orders, and history for customer users
"""

import logging
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional, List, Any, Dict

from app.db.database import SessionLocal
from app.db.models import User, SavedQuoteConfig, SalesOrder, OrderStatus, Shipment, Invoice, BCCustomer
from app.api.customer_auth import get_current_customer
from app.integrations.bc.client import bc_client
from app.integrations.ai.client import ai_client
from app.services.part_number_service import get_parts_for_door_config
from app.services.pricing_service import calculate_selling_price, warm_bc_cost_cache
from app.services.spring_data_service import get_bc_spring_inventory
from app.services.quote_review_service import save_quote_snapshot

# Part number prefix → BC search keyword for AI substitute lookup
_CATEGORY_SEARCH_TERMS = {
    "SP": "spring",
    "PN": "panel",
    "TR": "track",
    "SH": "shaft",
    "HK": "hardware kit",
    "FH": "hardware",
    "PL": "weather",
    "AL": "aluminum",
}

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
    """Order response for customer — sourced from BC live"""
    id: str  # BC GUID
    number: Optional[str] = None
    status: str
    total_amount: Optional[float] = None
    currency: Optional[str] = None
    order_date: Optional[str] = None
    requested_delivery_date: Optional[str] = None


class OrderLineResponse(BaseModel):
    """Order line from BC"""
    line_number: Optional[int] = None
    item_number: Optional[str] = None
    description: Optional[str] = None
    quantity: Optional[float] = None
    unit_price: Optional[float] = None
    line_amount: Optional[float] = None


class ShipmentResponse(BaseModel):
    """Shipment from BC"""
    id: str
    number: Optional[str] = None
    shipment_date: Optional[str] = None
    ship_to_name: Optional[str] = None


class InvoiceResponse(BaseModel):
    """Invoice from BC"""
    id: str
    number: Optional[str] = None
    status: Optional[str] = None
    total_amount: Optional[float] = None
    due_date: Optional[str] = None
    invoice_date: Optional[str] = None


class OrderDetailResponse(BaseModel):
    """Full order detail with lines, shipments and invoices"""
    order: OrderResponse
    lines: List[OrderLineResponse] = []
    shipments: List[ShipmentResponse] = []
    invoices: List[InvoiceResponse] = []


class TrackingEvent(BaseModel):
    """Tracking event in timeline"""
    event_type: str
    description: str
    timestamp: Optional[str] = None
    status: str  # completed, current, pending


class OrderTrackingResponse(BaseModel):
    """Order tracking timeline"""
    order_number: Optional[str]
    current_status: str
    timeline: List[TrackingEvent]
    shipments: List[ShipmentResponse] = []


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
    "comment", "panel", "v130g_section", "v130g_glass",
    "aluminum_section", "aluminum_glazing", "aluminum_glass", "commercial_window",
    "retainer", "astragal", "top_seal", "strut", "window",
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
    lift_type_raw = door.get("liftType", "standard")
    if lift_type_raw == "low_headroom":
        lift_type = "LHR"
    elif lift_type_raw == "high_lift":
        lift_type = "HIGH LIFT"
    elif lift_type_raw == "vertical":
        lift_type = "VERTICAL"
    else:
        lift_type = "STD LIFT"
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


def _find_ai_substitute(
    part_number: str,
    description: str,
    bc_items_cache: dict,
) -> Optional[dict]:
    """
    Search BC for items similar to the missing part and use Claude to pick the
    closest match.  Uses an in-memory cache (bc_items_cache) so each category
    is only fetched once per quote generation call.
    """
    if not part_number or not ai_client.client:
        return None

    category = part_number[:2].upper() if len(part_number) >= 2 else ""

    if category not in bc_items_cache:
        search_term = _CATEGORY_SEARCH_TERMS.get(category, part_number[:4])
        try:
            items = bc_client.search_items_by_name(search_term)
            bc_items_cache[category] = items[:60]
            logger.info(f"Fetched {len(bc_items_cache[category])} BC items for category '{category}' (search: '{search_term}')")
        except Exception as e:
            logger.warning(f"BC item search failed for '{search_term}': {e}")
            bc_items_cache[category] = []

    available = bc_items_cache.get(category, [])
    if not available:
        return None

    match = ai_client.find_closest_bc_item(
        part_number=part_number,
        description=description,
        available_items=available,
    )
    if match:
        logger.info(f"AI substitute: {part_number} → {match.get('number')} ({match.get('displayName')})")
    return match


def _generate_bc_quote_with_items(
    doors: List[dict],
    bc_customer_id: str,
    config_id: int,
    pricing_tier: Optional[str] = None,
    db: Optional[Session] = None,
    po_number: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Create a BC sales quote with real item lines for all doors.

    Returns dict with: bc_quote_id, bc_quote_number, lines_added, lines_failed,
    pricing, line_pricing, door_results
    """
    # Load spring inventory so quotes use the same stocked springs as the specs tab
    spring_inventory = get_bc_spring_inventory()

    # Step 1: Build all ordered lines from door configs
    all_lines = []
    door_results = []

    for i, door in enumerate(doors):
        door_index = i + 1
        door_desc = _format_door_description(door)

        # Comment line for this door (is_door_desc triggers Output=True in BC)
        all_lines.append({
            "lineType": "Comment",
            "description": door_desc,
            "category": "COMMENT",
            "door_index": door_index,
            "is_door_desc": True,
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
            "windowInsert": door.get("windowInsert") if door.get("hasWindows") else None,
            "windowSize": door.get("windowSize", "long"),
            "windowPositions": door.get("windowPositions", []),
            "windowCount": door.get("windowCount") or (
                len(door.get("windowPositions", [])) if door.get("windowPositions")
                else (door.get("windowQty", 0) if door.get("windowQty")
                      else (1 if (door.get("hasWindows") and door.get("windowSection")) else 0))
            ),
            "windowSection": door.get("windowSection"),
            "windowQty": door.get("windowQty", 0),
            "windowPanels": door.get("windowPanels"),
            "windowFrameColor": door.get("windowFrameColor", "BLACK"),
            "glazingType": door.get("glazingType"),
            "glassPaneType": door.get("glassPaneType"),
            "glassColor": door.get("glassColor"),
            "trackRadius": door.get("trackRadius", "15"),
            "trackThickness": door.get("trackThickness", "2"),
            "trackMount": door.get("trackMount", "bracket"),
            "liftType": door.get("liftType", "standard"),
            "highLiftInches": door.get("highLiftInches"),
            "hardware": door.get("hardware", {}),
            "operator": door.get("operator"),
            "targetCycles": door.get("targetCycles", 10000),
            "shaftType": door.get("shaftType", "auto"),
        }

        try:
            door_parts = get_parts_for_door_config(config_dict, spring_inventory=spring_inventory)
            parts_list = door_parts.get("parts_list", [])
            sorted_parts = _sort_parts_by_category(parts_list)
            part_door_type = config_dict.get("doorType", "residential")

            # Track whether we've emitted window placement comment
            window_note_emitted = False

            for part in sorted_parts:
                part["door_index"] = door_index
                part["door_type"] = part_door_type
                all_lines.append(part)

                # After window parts, emit a placement comment if notes exist
                if not window_note_emitted and part.get("notes") and part.get("category") in ("window", "commercial_window"):
                    window_note_emitted = True
                    all_lines.append({
                        "lineType": "Comment",
                        "description": part["notes"],
                        "category": "COMMENT",
                        "door_index": door_index,
                        "is_note": True,  # Not a door delimiter — don't split pricing groups
                    })

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
    # Note: requestedDeliveryDate is not available on the v2.0 salesQuotes entity.
    # It gets set during order creation in convert_quote_to_order (6 weeks out).
    quote_data = {
        "customerId": bc_customer_id,
        "externalDocumentNumber": po_number or f"PORTAL-{config_id}",
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

    # Step 3: Warm the BC cost cache so pricing uses live production costs
    if pricing_tier and db:
        item_pns = [l["part_number"] for l in all_lines if l.get("part_number")]
        warm_bc_cost_cache(item_pns)

    # Step 4: Add line items
    lines_added = 0
    lines_failed = []
    bc_items_cache: dict = {}  # category prefix → list of BC items (populated lazily)

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

            added_line = bc_client.add_quote_line(bc_quote_id, line_data)
            lines_added += 1

            # Door description comments: set Output=True via OData so BC
            # shows them on printed quotes and subtotals items below them.
            if line.get("is_door_desc") and added_line.get("sequence"):
                try:
                    bc_client.set_quote_line_output(
                        bc_quote_number, added_line["sequence"], output=True
                    )
                except Exception as out_err:
                    logger.warning(f"Failed to set Output flag on door desc line: {out_err}")

            # BC's item price list overrides unitPrice on POST.
            # PATCH the line afterward to lock in the customer-tier price.
            if pricing_tier and db and line.get("lineType") != "Comment":
                selling_price = calculate_selling_price(
                    part_number=line["part_number"],
                    door_type=line.get("door_type", "residential"),
                    tier=pricing_tier,
                    db=db,
                )
                if selling_price is not None:
                    etag = added_line.get("@odata.etag", "*")
                    bc_client.update_quote_line(
                        bc_quote_id,
                        added_line["id"],
                        etag,
                        {"unitPrice": selling_price},
                    )

        except Exception as line_error:
            part_id = line.get("part_number", line.get("description", "unknown"))
            logger.warning(f"Failed to add line {part_id}: {line_error}")

            # ── AI substitute lookup ────────────────────────────────────────
            # Before falling back to a comment, ask Claude to find the closest
            # matching BC item so the quote has real billable lines.
            ai_used = False
            if line.get("lineType") != "Comment" and line.get("part_number"):
                substitute = _find_ai_substitute(
                    part_number=line["part_number"],
                    description=line.get("description", ""),
                    bc_items_cache=bc_items_cache,
                )
                if substitute and substitute.get("number"):
                    try:
                        sub_line_data = {
                            "lineType": "Item",
                            "lineObjectNumber": substitute["number"],
                            "description": (
                                f"{substitute.get('displayName', substitute['number'])} "
                                f"(sub for {line['part_number']})"
                            ),
                            "quantity": line["quantity"],
                        }
                        added_sub = bc_client.add_quote_line(bc_quote_id, sub_line_data)
                        lines_added += 1
                        ai_used = True

                        # Apply tier pricing to the substitute
                        if pricing_tier and db:
                            selling_price = calculate_selling_price(
                                part_number=substitute["number"],
                                door_type=line.get("door_type", "residential"),
                                tier=pricing_tier,
                                db=db,
                            )
                            if selling_price is not None:
                                etag = added_sub.get("@odata.etag", "*")
                                bc_client.update_quote_line(
                                    bc_quote_id,
                                    added_sub["id"],
                                    etag,
                                    {"unitPrice": selling_price},
                                )

                        logger.info(
                            f"AI substitute added: {line['part_number']} → "
                            f"{substitute['number']} ({substitute.get('displayName')})"
                        )
                    except Exception as sub_err:
                        logger.warning(
                            f"AI substitute {substitute['number']} also failed: {sub_err}"
                        )

            # ── Comment fallback (only if AI matching didn't succeed) ────────
            if not ai_used and line.get("lineType") != "Comment" and line.get("part_number"):
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
            elif not ai_used:
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

        # Build a price lookup from BC's returned lines keyed by part number.
        # BC may not return Comment-type lines in salesQuoteLines, so we rebuild
        # line_pricing from all_lines (which preserves Comment delimiters) and
        # enrich Item lines with the actual BC prices.
        bc_price_lookup = {}
        for ql in quote_lines:
            obj_num = ql.get("lineObjectNumber", "")
            if obj_num and obj_num not in bc_price_lookup:
                bc_price_lookup[obj_num] = {
                    "unit_price": ql.get("unitPrice", 0),
                }

        for line in all_lines:
            if line.get("lineType") == "Comment":
                # Window/note comments stay inside the current door group;
                # only door description comments act as group delimiters.
                ltype = "Note" if line.get("is_note") else "Comment"
                line_pricing.append({
                    "line_type": ltype,
                    "part_number": "",
                    "description": line["description"],
                    "quantity": 0,
                    "unit_price": 0,
                    "line_total": 0,
                })
            else:
                part_num = line.get("part_number", "")
                qty = line.get("quantity", 1)
                unit_price = bc_price_lookup.get(part_num, {}).get("unit_price", 0)
                line_pricing.append({
                    "line_type": "Item",
                    "part_number": part_num,
                    "description": line.get("description", ""),
                    "quantity": qty,
                    "unit_price": unit_price,
                    "line_total": round(unit_price * qty, 2),
                })

    except Exception as pricing_error:
        logger.warning(f"Could not fetch pricing for quote {bc_quote_number}: {pricing_error}")

    # Save snapshot for quote review system
    try:
        door_configs_summary = [
            {
                "series": d.get("doorSeries"), "type": d.get("doorType"),
                "width": d.get("doorWidth"), "height": d.get("doorHeight"),
                "count": d.get("doorCount", 1), "color": d.get("panelColor"),
            }
            for d in doors
        ]
        save_quote_snapshot(
            db=db,
            bc_quote_id=bc_quote_id,
            bc_quote_number=bc_quote_number,
            source="customer",
            all_lines=all_lines,
            line_pricing=line_pricing if line_pricing else None,
            pricing_totals=pricing,
            door_configs=door_configs_summary,
            bc_customer_id=bc_customer_id,
            pricing_tier=pricing_tier,
            saved_config_id=config_id,
        )
    except Exception as snap_err:
        logger.warning(f"Could not save quote snapshot: {snap_err}")

    return {
        "bc_quote_id": bc_quote_id,
        "bc_quote_number": bc_quote_number,
        "lines_added": lines_added,
        "lines_failed": lines_failed if lines_failed else None,
        "pricing": pricing,
        "line_pricing": line_pricing if line_pricing else None,
        "door_results": door_results,
    }


def _get_customer_pricing_tier(bc_customer_id: str, db: Session) -> str:
    """Look up the pricing tier for a BC customer. Returns 'retail' if not set."""
    bc_customer = db.query(BCCustomer).filter(
        BCCustomer.bc_customer_id == bc_customer_id
    ).first()
    if bc_customer and bc_customer.pricing_tier:
        tier = bc_customer.pricing_tier.lower().strip()
        if tier in {"gold", "silver", "bronze", "retail"}:
            return tier
    return "retail"


def _estimate_pricing_locally(
    doors: List[dict],
    pricing_tier: str,
    config_id: int,
    db: Session,
) -> Dict[str, Any]:
    """
    Calculate pricing locally without creating a BC quote.
    Used for customers who have no BC account link.
    Returns the same shape as _generate_bc_quote_with_items but with
    bc_quote_id=None and is_estimate=True in the pricing dict.
    """
    all_lines = []
    door_results = []

    for i, door in enumerate(doors):
        door_index = i + 1
        door_desc = _format_door_description(door)

        all_lines.append({
            "lineType": "Comment",
            "description": door_desc,
            "door_index": door_index,
        })

        config_dict = {
            "doorType": door.get("doorType", "residential"),
            "doorSeries": door.get("doorSeries"),
            "doorWidth": door.get("doorWidth"),
            "doorHeight": door.get("doorHeight"),
            "doorCount": door.get("doorCount", 1),
            "panelColor": door.get("panelColor", "WHITE"),
            "panelDesign": door.get("panelDesign", "SHXL"),
            "windowInsert": door.get("windowInsert") if door.get("hasWindows") else None,
            "windowSize": door.get("windowSize", "long"),
            "windowPositions": door.get("windowPositions", []),
            "windowCount": door.get("windowCount") or (
                len(door.get("windowPositions", [])) if door.get("windowPositions")
                else (door.get("windowQty", 0) if door.get("windowQty")
                      else (1 if (door.get("hasWindows") and door.get("windowSection")) else 0))
            ),
            "windowSection": door.get("windowSection"),
            "windowQty": door.get("windowQty", 0),
            "windowPanels": door.get("windowPanels"),
            "windowFrameColor": door.get("windowFrameColor", "BLACK"),
            "glazingType": door.get("glazingType"),
            "glassPaneType": door.get("glassPaneType"),
            "glassColor": door.get("glassColor"),
            "trackRadius": door.get("trackRadius", "15"),
            "trackThickness": door.get("trackThickness", "2"),
            "trackMount": door.get("trackMount", "bracket"),
            "liftType": door.get("liftType", "standard"),
            "highLiftInches": door.get("highLiftInches"),
            "hardware": door.get("hardware", {}),
            "operator": door.get("operator"),
            "targetCycles": door.get("targetCycles", 10000),
            "shaftType": door.get("shaftType", "auto"),
        }

        try:
            door_parts = get_parts_for_door_config(config_dict, spring_inventory=spring_inventory)
            parts_list = door_parts.get("parts_list", [])
            sorted_parts = _sort_parts_by_category(parts_list)
            part_door_type = config_dict.get("doorType", "residential")

            # Track whether we've emitted window placement comment
            window_note_emitted = False

            for part in sorted_parts:
                part["door_index"] = door_index
                part["door_type"] = part_door_type
                all_lines.append(part)

                # After window parts, emit a placement comment if notes exist
                if not window_note_emitted and part.get("notes") and part.get("category") in ("window", "commercial_window"):
                    window_note_emitted = True
                    all_lines.append({
                        "lineType": "Comment",
                        "description": part["notes"],
                        "category": "COMMENT",
                        "door_index": door_index,
                        "is_note": True,  # Not a door delimiter — don't split pricing groups
                    })

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

    # Warm the BC cost cache so pricing uses live production costs
    item_pns = [l["part_number"] for l in all_lines if l.get("part_number")]
    warm_bc_cost_cache(item_pns)

    # Build line pricing locally using calculate_selling_price
    line_pricing = []
    subtotal = 0.0

    for line in all_lines:
        if line.get("lineType") == "Comment":
            ltype = "Note" if line.get("is_note") else "Comment"
            line_pricing.append({
                "line_type": ltype,
                "part_number": "",
                "description": line["description"],
                "quantity": 0,
                "unit_price": 0,
                "line_total": 0,
            })
        else:
            part_number = line.get("part_number", "")
            quantity = line.get("quantity", 1)
            door_type = line.get("door_type", "residential")

            unit_price = calculate_selling_price(
                part_number=part_number,
                door_type=door_type,
                tier=pricing_tier,
                db=db,
            ) or 0.0

            line_total = round(unit_price * quantity, 2)
            subtotal += line_total

            line_pricing.append({
                "line_type": "Item",
                "part_number": part_number,
                "description": line.get("description", ""),
                "quantity": quantity,
                "unit_price": unit_price,
                "line_total": line_total,
            })

    subtotal = round(subtotal, 2)

    return {
        "bc_quote_id": None,
        "bc_quote_number": None,
        "lines_added": len([l for l in all_lines if l.get("lineType") != "Comment"]),
        "lines_failed": None,
        "pricing": {
            "subtotal": subtotal,
            "tax": 0,
            "total": subtotal,
            "currency": "CAD",
            "is_estimate": True,
        },
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

    try:
        doors = _validate_doors_config(config.config_data or {})

        if current_user.bc_customer_id:
            # Linked customer: create a real BC quote for accurate pricing (incl. tax)
            pricing_tier = _get_customer_pricing_tier(current_user.bc_customer_id, db)

            # Delete old BC quote if one exists
            if config.bc_quote_id:
                try:
                    bc_client.delete_sales_quote(config.bc_quote_id)
                    logger.info(f"Deleted previous BC quote {config.bc_quote_number} for config {config_id}")
                except Exception as e:
                    logger.warning(f"Could not delete previous BC quote {config.bc_quote_id}: {e}")

            result = _generate_bc_quote_with_items(
                doors=doors,
                bc_customer_id=current_user.bc_customer_id,
                config_id=config.id,
                pricing_tier=pricing_tier,
                db=db,
                po_number=(config.config_data or {}).get("poNumber"),
            )

            # Store BC quote reference (but NOT submitted)
            config.bc_quote_id = result["bc_quote_id"]
            config.bc_quote_number = result["bc_quote_number"]
        else:
            # Unlinked customer: estimate locally at retail, no BC quote created
            pricing_tier = "retail"
            result = _estimate_pricing_locally(
                doors=doors,
                pricing_tier=pricing_tier,
                config_id=config.id,
                db=db,
            )

        config.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(config)

        logger.info(
            f"Pricing generated for config {config_id}: "
            f"BC Quote {result['bc_quote_number']}, "
            f"{result['lines_added']} lines, tier={pricing_tier}"
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

    try:
        doors = _validate_doors_config(config.config_data or {})

        if current_user.bc_customer_id:
            # Linked customer: delete old quote and regenerate
            pricing_tier = _get_customer_pricing_tier(current_user.bc_customer_id, db)

            if config.bc_quote_id:
                try:
                    bc_client.delete_sales_quote(config.bc_quote_id)
                    logger.info(f"Deleted old BC quote {config.bc_quote_number} for refresh")
                except Exception as e:
                    logger.warning(f"Could not delete old BC quote {config.bc_quote_id}: {e}")

            result = _generate_bc_quote_with_items(
                doors=doors,
                bc_customer_id=current_user.bc_customer_id,
                config_id=config.id,
                pricing_tier=pricing_tier,
                db=db,
                po_number=(config.config_data or {}).get("poNumber"),
            )

            config.bc_quote_id = result["bc_quote_id"]
            config.bc_quote_number = result["bc_quote_number"]
        else:
            # Unlinked customer: recalculate local estimate at retail
            pricing_tier = "retail"
            result = _estimate_pricing_locally(
                doors=doors,
                pricing_tier=pricing_tier,
                config_id=config.id,
                db=db,
            )

        config.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(config)

        logger.info(f"Pricing refreshed for config {config_id}: BC Quote {result['bc_quote_number']}, tier={pricing_tier}")

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
            detail=(
                "Your account is not yet linked to a Business Central customer account. "
                "Please contact us to complete your account setup before submitting a quote."
            )
        )

    try:
        # If no BC quote yet, generate one with real item lines
        if not config.bc_quote_id:
            doors = _validate_doors_config(config.config_data or {})
            pricing_tier = _get_customer_pricing_tier(current_user.bc_customer_id, db)

            result = _generate_bc_quote_with_items(
                doors=doors,
                bc_customer_id=current_user.bc_customer_id,
                config_id=config.id,
                pricing_tier=pricing_tier,
                db=db,
                po_number=(config.config_data or {}).get("poNumber"),
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


@router.post("/saved-quotes/{config_id}/place-order")
def place_order_from_quote(
    config_id: int,
    current_user: User = Depends(get_current_customer),
    db: Session = Depends(get_db)
):
    """
    Convert a priced/submitted quote to a sales order via BC's makeOrder action.
    Auto-converts immediately (no admin approval gate).
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

    if not config.bc_quote_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This quote has not been priced yet. Please get pricing first."
        )

    if not current_user.bc_customer_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Your account is not linked to a Business Central customer."
        )

    # Check if an order already exists for this quote
    existing_order = db.query(SalesOrder).filter(
        SalesOrder.bc_quote_number == config.bc_quote_number
    ).first()

    if existing_order:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"An order has already been placed for this quote (Order #{existing_order.bc_order_number})"
        )

    try:
        # Convert quote to order in BC
        # If makeOrder fails (delivery date not settable on v2.0 quotes entity),
        # the client falls back to manual order creation with 6-week delivery date.
        bc_order = bc_client.convert_quote_to_order(config.bc_quote_id)

        bc_order_id = bc_order.get("id")
        bc_order_number = bc_order.get("number")
        total_amount = bc_order.get("totalAmountIncludingTax", 0)

        # Parse delivery date from BC order response
        bc_delivery_date = None
        raw_delivery = bc_order.get("requestedDeliveryDate")
        if raw_delivery and raw_delivery != "0001-01-01":
            try:
                bc_delivery_date = datetime.strptime(raw_delivery[:10], "%Y-%m-%d")
            except (ValueError, TypeError):
                pass

        # Create local SalesOrder record
        sales_order = SalesOrder(
            quote_request_id=None,  # Portal-originated, not from email QuoteRequest
            bc_order_id=bc_order_id,
            bc_order_number=bc_order_number,
            bc_quote_number=config.bc_quote_number,
            customer_id=current_user.bc_customer_id,
            bc_customer_id=current_user.bc_customer_id,
            customer_name=current_user.name,
            customer_email=current_user.email,
            status=OrderStatus.CONFIRMED,
            total_amount=total_amount,
            currency="CAD",
            order_date=datetime.utcnow(),
            confirmed_at=datetime.utcnow(),
            requested_delivery_date=bc_delivery_date,
        )
        db.add(sales_order)

        # Mark as submitted if not already
        if not config.is_submitted:
            config.is_submitted = True
            config.submitted_at = datetime.utcnow()

        db.commit()
        db.refresh(sales_order)

        logger.info(
            f"Order placed from quote: config {config_id}, "
            f"BC Order {bc_order_number}, Amount: {total_amount}"
        )

        return {
            "success": True,
            "order_id": sales_order.id,
            "bc_order_number": bc_order_number,
            "total_amount": float(total_amount) if total_amount else None,
            "requested_delivery_date": bc_delivery_date.strftime("%B %d, %Y") if bc_delivery_date else None,
            "message": f"Order {bc_order_number} placed successfully!"
        }

    except HTTPException:
        raise
    except Exception as e:
        error_msg = str(e)
        logger.error(f"Error placing order from quote config {config_id}: {error_msg}", exc_info=True)

        # Quote not found — likely generated against a different BC environment
        # (e.g., sandbox). Clear the stale quote ID so the customer can re-price.
        if "404" in error_msg or "Not Found" in error_msg or "not found" in error_msg.lower():
            config.bc_quote_id = None
            config.bc_quote_number = None
            config.bc_quote_data = None
            config.is_submitted = False
            db.commit()
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "Quote not found in Business Central — it may have been generated "
                    "against a different environment. Please click 'Get Pricing' to "
                    "generate a fresh quote, then place the order again."
                )
            )

        if "DialogException" in error_msg:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Business Central error: {error_msg}"
            )

        if "50005" in error_msg:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="This quote cannot be converted to an order. It may have already been converted or archived."
            )

        # Surface BC error detail if present (after "| BC:" marker)
        if "| BC:" in error_msg:
            bc_detail = error_msg.split("| BC:", 1)[1].strip()
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Business Central error: {bc_detail}"
            )

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to place order: {error_msg}"
        )


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

def _map_bc_order_status(bc_status: str) -> str:
    """Map BC order status to portal status"""
    mapping = {
        "Draft": "draft",
        "Open": "open",
        "Released": "released",
        "Pending Approval": "pending_approval",
        "Pending Prepayment": "pending_prepayment",
    }
    return mapping.get(bc_status, bc_status.lower() if bc_status else "unknown")


@router.get("/orders", response_model=List[OrderResponse])
def list_orders(
    current_user: User = Depends(get_current_customer),
):
    """List all orders for current customer — fetched live from BC"""
    if not current_user.bc_customer_id:
        return []

    try:
        bc_orders = bc_client.get_customer_orders(current_user.bc_customer_id)
    except Exception as e:
        logger.error(f"Error fetching orders from BC: {e}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to fetch orders from Business Central"
        )

    return [
        OrderResponse(
            id=o.get("id", ""),
            number=o.get("number"),
            status=_map_bc_order_status(o.get("status", "")),
            total_amount=o.get("totalAmountIncludingTax"),
            currency=o.get("currencyCode") or "CAD",
            order_date=o.get("orderDate"),
            requested_delivery_date=o.get("requestedDeliveryDate"),
        )
        for o in bc_orders
    ]


@router.get("/orders/estimated-timelines")
def get_estimated_timelines(
    current_user: User = Depends(get_current_customer),
    db: Session = Depends(get_db)
):
    """
    Get estimated timelines for order steps based on historical data.
    Uses averages from the last 4 months of completed/invoiced orders.
    Falls back to static defaults if < 3 completed orders.
    """
    from sqlalchemy import func

    # Static defaults (in days): confirmed, production, production_complete, shipped, invoiced
    DEFAULTS = [
        {"from_step": "order_placed", "to_step": "order_confirmed", "avg_days": 1},
        {"from_step": "order_confirmed", "to_step": "in_production", "avg_days": 3},
        {"from_step": "in_production", "to_step": "production_complete", "avg_days": 10},
        {"from_step": "production_complete", "to_step": "shipped", "avg_days": 2},
        {"from_step": "shipped", "to_step": "invoiced", "avg_days": 1},
    ]

    cutoff = datetime.utcnow() - timedelta(days=120)

    # Get completed/invoiced orders from last 4 months
    completed_orders = db.query(SalesOrder).filter(
        SalesOrder.status.in_([OrderStatus.COMPLETED, OrderStatus.INVOICED]),
        SalesOrder.created_at >= cutoff
    ).all()

    if len(completed_orders) < 3:
        return {
            "transitions": DEFAULTS,
            "data_source": "defaults",
            "sample_size": len(completed_orders)
        }

    # Calculate averages for each transition
    def avg_days_between(orders, from_attr, to_attr):
        deltas = []
        for o in orders:
            from_val = getattr(o, from_attr)
            to_val = getattr(o, to_attr)
            if from_val and to_val:
                delta = (to_val - from_val).total_seconds() / 86400
                if delta >= 0:
                    deltas.append(delta)
        return round(sum(deltas) / len(deltas), 1) if deltas else None

    transitions = []
    pairs = [
        ("order_placed", "order_confirmed", "created_at", "confirmed_at"),
        ("order_confirmed", "in_production", "confirmed_at", "production_started_at"),
        ("in_production", "production_complete", "production_started_at", "production_completed_at"),
        ("production_complete", "shipped", "production_completed_at", "shipped_at"),
        ("shipped", "invoiced", "shipped_at", "invoiced_at"),
    ]

    for from_step, to_step, from_attr, to_attr in pairs:
        avg = avg_days_between(completed_orders, from_attr, to_attr)
        default = next((d for d in DEFAULTS if d["from_step"] == from_step), None)
        transitions.append({
            "from_step": from_step,
            "to_step": to_step,
            "avg_days": avg if avg is not None else (default["avg_days"] if default else 1),
        })

    return {
        "transitions": transitions,
        "data_source": "historical",
        "sample_size": len(completed_orders)
    }


@router.get("/orders/{order_id}", response_model=OrderDetailResponse)
def get_order_detail(
    order_id: str,
    current_user: User = Depends(get_current_customer),
):
    """Get order detail with lines, shipments and invoices — fetched live from BC"""
    if not current_user.bc_customer_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account not linked to Business Central customer"
        )

    try:
        order_data = bc_client.get_customer_order_details(order_id, current_user.bc_customer_id)
    except Exception as e:
        logger.error(f"Error fetching order details from BC: {e}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to fetch order details from Business Central"
        )

    if not order_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Order not found"
        )

    # Map order lines
    lines = [
        OrderLineResponse(
            line_number=ln.get("lineObjectNumber") or ln.get("sequence"),
            item_number=ln.get("lineObjectNumber"),
            description=ln.get("description"),
            quantity=ln.get("quantity"),
            unit_price=ln.get("unitPrice"),
            line_amount=ln.get("amountIncludingTax") or ln.get("netAmount"),
        )
        for ln in order_data.get("lines", [])
    ]

    # Map shipments
    shipments = [
        ShipmentResponse(
            id=s.get("id", ""),
            number=s.get("number"),
            shipment_date=s.get("shipmentDate"),
            ship_to_name=s.get("shipToName"),
        )
        for s in order_data.get("shipments", [])
    ]

    # Map invoices
    invoices = [
        InvoiceResponse(
            id=inv.get("id", ""),
            number=inv.get("number"),
            status=inv.get("status"),
            total_amount=inv.get("totalAmountIncludingTax"),
            due_date=inv.get("dueDate"),
            invoice_date=inv.get("invoiceDate"),
        )
        for inv in order_data.get("invoices", [])
    ]

    return OrderDetailResponse(
        order=OrderResponse(
            id=order_data.get("id", ""),
            number=order_data.get("number"),
            status=_map_bc_order_status(order_data.get("status", "")),
            total_amount=order_data.get("totalAmountIncludingTax"),
            currency=order_data.get("currencyCode") or "CAD",
            order_date=order_data.get("orderDate"),
            requested_delivery_date=order_data.get("requestedDeliveryDate"),
        ),
        lines=lines,
        shipments=shipments,
        invoices=invoices,
    )


@router.get("/orders/{order_id}/tracking", response_model=OrderTrackingResponse)
def get_order_tracking(
    order_id: str,
    current_user: User = Depends(get_current_customer),
):
    """Get order tracking timeline — fetched live from BC"""
    if not current_user.bc_customer_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account not linked to Business Central customer"
        )

    try:
        order_data = bc_client.get_customer_order_details(order_id, current_user.bc_customer_id)
    except Exception as e:
        logger.error(f"Error fetching order tracking from BC: {e}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to fetch order tracking from Business Central"
        )

    if not order_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Order not found"
        )

    bc_status = order_data.get("status", "")
    portal_status = _map_bc_order_status(bc_status)

    # Build a simple timeline based on BC status
    # BC order statuses: Draft → Open → Released
    status_steps = [
        ("order_placed", "Order Placed"),
        ("open", "Open"),
        ("released", "Released"),
    ]

    # Determine which step is current
    status_order = {"draft": 0, "open": 1, "released": 2}
    current_idx = status_order.get(portal_status, 0)

    timeline = []
    for i, (event_type, description) in enumerate(status_steps):
        if i < current_idx:
            step_status = "completed"
        elif i == current_idx:
            step_status = "completed" if portal_status == "released" else "current"
        else:
            step_status = "pending"

        timeline.append(TrackingEvent(
            event_type=event_type,
            description=description,
            timestamp=order_data.get("orderDate") if i == 0 else None,
            status=step_status,
        ))

    # Check for shipments
    bc_shipments = order_data.get("shipments", [])
    has_shipments = len(bc_shipments) > 0

    # Add shipped step
    timeline.append(TrackingEvent(
        event_type="shipped",
        description="Shipped",
        timestamp=bc_shipments[0].get("shipmentDate") if has_shipments else None,
        status="completed" if has_shipments else "pending",
    ))

    # Check for invoices
    bc_invoices = order_data.get("invoices", [])
    has_invoices = len(bc_invoices) > 0

    # Add invoiced step
    timeline.append(TrackingEvent(
        event_type="invoiced",
        description="Invoiced",
        timestamp=bc_invoices[0].get("invoiceDate") if has_invoices else None,
        status="completed" if has_invoices else "pending",
    ))

    shipments = [
        ShipmentResponse(
            id=s.get("id", ""),
            number=s.get("number"),
            shipment_date=s.get("shipmentDate"),
            ship_to_name=s.get("shipToName"),
        )
        for s in bc_shipments
    ]

    return OrderTrackingResponse(
        order_number=order_data.get("number"),
        current_status=portal_status,
        timeline=timeline,
        shipments=shipments,
    )


@router.get("/orders/{order_id}/acknowledgement")
def download_order_acknowledgement(
    order_id: str,
    current_user: User = Depends(get_current_customer),
):
    """Download order acknowledgement PDF from Business Central"""
    if not current_user.bc_customer_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account not linked to Business Central customer"
        )

    # Verify customer ownership by fetching the order from BC
    try:
        order_data = bc_client.get_customer_order_details(order_id, current_user.bc_customer_id)
    except Exception as e:
        logger.error(f"Error verifying order ownership: {e}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to verify order in Business Central"
        )

    if not order_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Order not found"
        )

    try:
        pdf_bytes = bc_client.get_order_confirmation_pdf(order_id)

        order_number = order_data.get("number", order_id)
        filename = f"Order_Acknowledgement_{order_number}.pdf"

        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"'
            }
        )
    except Exception as e:
        logger.error(f"Error downloading order acknowledgement PDF: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to download order acknowledgement PDF"
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
