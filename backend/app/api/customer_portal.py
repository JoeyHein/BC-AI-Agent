"""
Customer Portal API Endpoints
Saved quotes, BC quotes, orders, and history for customer users
"""

import logging
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
from sqlalchemy import or_
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional, List, Any, Dict, Tuple

from app.db.database import SessionLocal
from app.db.models import User, SavedQuoteConfig, SalesOrder, OrderStatus, Shipment, Invoice, BCCustomer, Part, SpecialOrderRequest, AppSettings
from app.api.customer_auth import get_current_customer
from app.integrations.bc.client import bc_client
from app.integrations.ai.client import ai_client
from app.services.part_number_service import get_parts_for_door_config
from app.services.pricing_service import calculate_selling_price, warm_bc_cost_cache
from app.services.spring_data_service import get_bc_spring_inventory
from app.services.quote_review_service import save_quote_snapshot
from app.services.freight_service import calculate_freight, get_freight_config
from app.services.install_pricing_service import install_pricing_service


def _mount_surface_note(door: dict) -> Optional[str]:
    """Shop install note for the door's mount surface, or None for a plain wood
    mount. Steel (reverse-angle) and concrete are harder mounts that carry a
    builder install premium; the door product price is unaffected by mount."""
    mount = str(door.get("mountSurface", "wood") or "wood").lower()
    if mount == "steel":
        return "** STEEL MOUNT / REVERSE ANGLE INSTALL **"
    if mount == "concrete":
        return "** CONCRETE MOUNT INSTALL **"
    return None


def _account_provides_install(customer_user_id: Optional[int], db: Optional[Session]) -> bool:
    """True when the customer is a home-builder account.

    Home-builder quotes carry an INSTALLATION line whose total already includes
    per-km crew travel from Medicine Hat. Freight (a % of product) bills the same
    trip a second time, so we suppress freight whenever we're providing install.
    """
    if not customer_user_id or not db:
        return False
    from app.db.models import User as UserModel
    customer_user = db.query(UserModel).filter(UserModel.id == customer_user_id).first()
    return getattr(customer_user, "account_type", None) == "home_builder" if customer_user else False

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
    # True once a SalesOrder has been placed against this quote.
    # Clients should treat this as the true edit lock — not is_submitted.
    order_placed: bool = False
    # Multi-user accounts: who built this quote (the user the BC customer link
    # is shared across). Lets staff at the same dealership see each other's work.
    created_by_name: Optional[str] = None
    created_by_email: Optional[str] = None

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
# INSTALL PRICING ENDPOINTS
# ============================================================================

class InstallPriceCalculateRequest(BaseModel):
    door_width_inches: float
    door_height_inches: float
    door_type: str  # 'residential' or 'commercial'
    town: Optional[str] = None  # for travel calc


@router.post("/install-pricing/calculate")
def calculate_install_price(
    data: InstallPriceCalculateRequest,
    current_user: User = Depends(get_current_customer),
    db: Session = Depends(get_db)
):
    """Calculate installation price for a door based on the current customer's rates"""
    result = install_pricing_service.calculate_install_price(
        customer_id=current_user.id,
        door_width_inches=data.door_width_inches,
        door_height_inches=data.door_height_inches,
        door_type=data.door_type,
        db=db,
        town=data.town,
    )
    return result


@router.get("/install-travel-quote")
def install_travel_quote(
    town: str,
    current_user: User = Depends(get_current_customer),
    db: Session = Depends(get_db),
):
    """
    Resolve a town to road-km from Medicine Hat and return the travel cost
    at the current builder rate. Used by the configurator to show travel
    cost inline as the customer types their installation town. Hits the
    cached/static distance dict first, then Google Distance Matrix; caches
    the result so each unique town is paid for at most once.
    """
    if not town or not town.strip():
        return {"town": None, "distance_km": None, "travel_price": 0.0, "source": "unknown"}

    km, source = install_pricing_service.lookup_distance_km(town, db)

    # Use the customer's per-km rate override if configured, else default.
    pricing = install_pricing_service.get_customer_pricing(current_user.id, db)
    from app.services.install_pricing_service import BUILDER_TRAVEL_RATE_PER_KM
    rate = float(pricing.travel_rate_per_km) if pricing and pricing.travel_rate_per_km is not None else BUILDER_TRAVEL_RATE_PER_KM
    travel_price = round(km * rate, 2) if km is not None else 0.0

    return {
        "town": town,
        "distance_km": km,
        "travel_rate_per_km": rate,
        "travel_price": travel_price,
        "source": source,  # "static" | "google" | "unknown"
    }


# ============================================================================
# SAVED QUOTE CONFIG ENDPOINTS
# ============================================================================

def _company_user_ids(current_user: User, db: Session) -> List[int]:
    """All user IDs that share `current_user`'s BC customer link.

    Multi-user company accounts: two staff at e.g. Global Overhead Doors each
    have their own login, both linked to the same `bc_customer_id`. This helper
    drives the company-scoped saved-quotes queries so each can see the other's
    drafts. Falls back to just the current user when there's no BC link
    (legacy / pre-approval / one-off accounts).
    """
    if not current_user.bc_customer_id:
        return [current_user.id]
    rows = db.query(User.id).filter(
        User.bc_customer_id == current_user.bc_customer_id,
        User.user_type == "CUSTOMER",
    ).all()
    ids = [r[0] for r in rows]
    if current_user.id not in ids:
        ids.append(current_user.id)
    return ids


def _config_to_response(config: SavedQuoteConfig, db: Session) -> dict:
    """Serialize one SavedQuoteConfig to the response shape, hydrating order_placed."""
    creator = db.query(User).filter(User.id == config.user_id).first() if config.user_id else None
    return {
        "id": config.id,
        "name": config.name,
        "description": config.description,
        "config_data": config.config_data,
        "is_submitted": config.is_submitted,
        "bc_quote_number": config.bc_quote_number,
        "bc_quote_id": config.bc_quote_id,
        "created_at": config.created_at,
        "updated_at": config.updated_at,
        "submitted_at": config.submitted_at,
        "order_placed": _has_sales_order_for_quote(config, db),
        "created_by_name": creator.name if creator else None,
        "created_by_email": creator.email if creator else None,
    }


def _hydrate_order_placed(configs: List[SavedQuoteConfig], db: Session) -> List[dict]:
    """Hydrate order_placed + creator fields in one round-trip per dimension.
    Returns list of dicts ready for SavedQuoteConfigResponse."""
    quote_nums = [c.bc_quote_number for c in configs if c.bc_quote_number]
    ordered_nums = set()
    if quote_nums:
        rows = db.query(SalesOrder.bc_quote_number).filter(
            SalesOrder.bc_quote_number.in_(quote_nums)
        ).all()
        ordered_nums = {r[0] for r in rows if r[0]}

    user_ids = list({c.user_id for c in configs if c.user_id})
    creators_by_id: Dict[int, User] = {}
    if user_ids:
        for u in db.query(User).filter(User.id.in_(user_ids)).all():
            creators_by_id[u.id] = u

    result = []
    for c in configs:
        creator = creators_by_id.get(c.user_id) if c.user_id else None
        result.append({
            "id": c.id,
            "name": c.name,
            "description": c.description,
            "config_data": c.config_data,
            "is_submitted": c.is_submitted,
            "bc_quote_number": c.bc_quote_number,
            "bc_quote_id": c.bc_quote_id,
            "created_at": c.created_at,
            "updated_at": c.updated_at,
            "submitted_at": c.submitted_at,
            "order_placed": bool(c.bc_quote_number and c.bc_quote_number in ordered_nums),
            "created_by_name": creator.name if creator else None,
            "created_by_email": creator.email if creator else None,
        })
    return result


@router.get("/saved-quotes", response_model=List[SavedQuoteConfigResponse])
def list_saved_quotes(
    search: Optional[str] = None,
    current_user: User = Depends(get_current_customer),
    db: Session = Depends(get_db)
):
    """List all saved quote configurations for current customer.

    Optional ?search= filters by name (tag) or BC quote number, case-insensitive
    substring match. Useful for the customer "look up by quote # or tag" box.
    """
    # Company-scoped: any user sharing this BC customer link sees all the
    # quotes built by anyone on the account.
    q = db.query(SavedQuoteConfig).filter(
        SavedQuoteConfig.user_id.in_(_company_user_ids(current_user, db))
    )
    if search and search.strip():
        like = f"%{search.strip()}%"
        q = q.filter(or_(
            SavedQuoteConfig.name.ilike(like),
            SavedQuoteConfig.bc_quote_number.ilike(like),
        ))
    configs = q.order_by(SavedQuoteConfig.created_at.desc()).all()
    return _hydrate_order_placed(configs, db)


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

    return _config_to_response(config, db)


@router.get("/saved-quotes/{config_id}", response_model=SavedQuoteConfigResponse)
def get_saved_quote(
    config_id: int,
    current_user: User = Depends(get_current_customer),
    db: Session = Depends(get_db)
):
    """Get a specific saved quote configuration"""
    config = db.query(SavedQuoteConfig).filter(
        SavedQuoteConfig.id == config_id,
        SavedQuoteConfig.user_id.in_(_company_user_ids(current_user, db)),
    ).first()

    if not config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Saved configuration not found"
        )

    return _config_to_response(config, db)


@router.put("/saved-quotes/{config_id}", response_model=SavedQuoteConfigResponse)
def update_saved_quote(
    config_id: int,
    update_data: SavedQuoteConfigUpdate,
    current_user: User = Depends(get_current_customer),
    db: Session = Depends(get_db)
):
    """Update a saved quote configuration.

    Edit lock: a quote is editable until an order has been placed against it.
    Submit alone does NOT lock edits — the customer can still revise doors
    until they click Place Order.

    Behavior by state:
      - No BC quote yet: update config_data freely
      - BC quote exists (priced and/or submitted), no order placed:
            diff doors → surgically patch only changed doors' lines in BC,
            keeping the BC quote number stable
      - Order placed: reject edit (changes go through the order flow instead)
    """
    config = db.query(SavedQuoteConfig).filter(
        SavedQuoteConfig.id == config_id,
        SavedQuoteConfig.user_id.in_(_company_user_ids(current_user, db)),
    ).first()

    if not config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Saved configuration not found"
        )

    if _has_sales_order_for_quote(config, db):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot edit a quote once an order has been placed against it."
        )

    if update_data.name is not None:
        config.name = update_data.name
    if update_data.description is not None:
        config.description = update_data.description

    if update_data.config_data is not None:
        new_config_data = update_data.config_data
        if config.bc_quote_id:
            # Surgical edit against the existing BC quote (same quote number).
            try:
                pricing_tier = (
                    _get_customer_pricing_tier(current_user.bc_customer_id, db)
                    if current_user.bc_customer_id else "retail"
                )
                delivery_type = new_config_data.get("deliveryType", "delivery")
                result = _edit_bc_quote_lines(
                    config=config,
                    new_config_data=new_config_data,
                    bc_customer_id=current_user.bc_customer_id,
                    pricing_tier=pricing_tier,
                    db=db,
                    customer_user_id=current_user.id,
                    delivery_type=delivery_type,
                )
                config.config_data = new_config_data
                config.bc_line_map = result.get("line_map")
            except HTTPException:
                raise
            except Exception as e:
                logger.error(f"Failed to edit BC quote {config.bc_quote_number}: {e}", exc_info=True)
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Failed to edit quote: {str(e)}"
                )
        else:
            # Draft (no BC quote yet): just update config_data
            config.config_data = new_config_data

    config.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(config)

    logger.info(f"Saved quote config updated: {config.id}")

    return _config_to_response(config, db)


@router.delete("/saved-quotes/{config_id}")
def delete_saved_quote(
    config_id: int,
    current_user: User = Depends(get_current_customer),
    db: Session = Depends(get_db)
):
    """Delete a saved quote configuration"""
    config = db.query(SavedQuoteConfig).filter(
        SavedQuoteConfig.id == config_id,
        SavedQuoteConfig.user_id.in_(_company_user_ids(current_user, db)),
    ).first()

    if not config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Saved configuration not found"
        )

    if _has_sales_order_for_quote(config, db):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete a quote that has been converted to an order."
        )

    # Best-effort: clean up the BC quote if one exists and no order is attached
    if config.bc_quote_id:
        try:
            bc_client.delete_sales_quote(config.bc_quote_id)
            logger.info(f"Deleted BC quote {config.bc_quote_number} on config delete")
        except Exception as e:
            logger.warning(f"Could not delete BC quote {config.bc_quote_id}: {e}")

    db.delete(config)
    db.commit()

    logger.info(f"Saved quote config deleted: {config_id}")

    return {"message": "Configuration deleted successfully"}


@router.post("/saved-quotes/{config_id}/duplicate", response_model=SavedQuoteConfigResponse)
def duplicate_saved_quote(
    config_id: int,
    current_user: User = Depends(get_current_customer),
    db: Session = Depends(get_db),
):
    """Create a fresh copy of a saved quote.

    Use case: a customer wants to base a new quote on an existing one without
    losing the original (e.g. "same install but different door series"). The
    copy starts as a clean draft — fresh door uids, no BC quote linkage, no
    pricing, no line map, prefixed name. The original is untouched.
    """
    import uuid as _uuid

    source = db.query(SavedQuoteConfig).filter(
        SavedQuoteConfig.id == config_id,
        SavedQuoteConfig.user_id.in_(_company_user_ids(current_user, db)),
    ).first()
    if not source:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Saved configuration not found",
        )

    # Deep-clone the config_data and assign fresh door_uids so the copy diverges
    # from the original even if both go through edits independently. Strip any
    # state that's tied to the original BC quote (line counts, etc).
    src_data = source.config_data or {}
    new_doors = []
    for d in (src_data.get("doors") or []):
        clone = dict(d)
        clone["door_uid"] = str(_uuid.uuid4())
        new_doors.append(clone)
    new_data = {**src_data, "doors": new_doors}

    new_name = source.name or "Untitled Quote"
    if not new_name.lower().startswith("copy of "):
        new_name = f"Copy of {new_name}"

    copy = SavedQuoteConfig(
        user_id=current_user.id,
        name=new_name,
        description=source.description,
        config_data=new_data,
        is_submitted=False,
        # Explicitly NO bc_quote_id, bc_quote_number, bc_line_map — fresh draft.
    )

    db.add(copy)
    db.commit()
    db.refresh(copy)

    logger.info(
        f"Saved quote config duplicated: {source.id} -> {copy.id} "
        f"for user {current_user.email}"
    )

    return _config_to_response(copy, db)


# ============================================================================
# QUOTE PRICING HELPERS (mirrors admin door_configurator.py generate-quote logic)
# ============================================================================

# Standard line item ordering for BC quotes (same as door_configurator.py)
LINE_ORDER = [
    "comment", "panel", "v130g_section", "v130g_glass",
    "aluminum_section", "aluminum_glazing", "aluminum_glass", "commercial_window",
    "retainer", "astragal", "top_seal", "strut", "window",
    "track", "highlift_comment", "highlift_track", "hardware", "spring_comment", "spring", "spring_accessory",
    "shaft", "weather_stripping", "accessory", "operator",
]


def _sort_parts_by_category(parts: List[dict]) -> List[dict]:
    """Sort parts list according to BC quote line ordering standard.

    Uses a stable sort so items sharing the same category priority keep their
    original relative order.  spring_accessory (cone sets) shares the same
    priority as spring so that cones stay paired with their springs rather than
    being grouped at the end of all spring lines.
    """
    def sort_key(part):
        category = part.get("category", "other").lower()
        # Cone sets should stay inline with their spring pair, not sort separately
        if category == "spring_accessory":
            category = "spring"
        try:
            return LINE_ORDER.index(category)
        except ValueError:
            return len(LINE_ORDER)
    return sorted(parts, key=sort_key)


def _format_door_description(door: dict) -> str:
    """Format door description for BC quote comment line."""
    from app.api.door_configurator import (
        _format_lift_label, _format_mount_label, _format_design_for_comment,
        _format_scope_label,
    )
    width_ft, width_in = divmod(door.get("doorWidth", 0), 12)
    height_ft, height_in = divmod(door.get("doorHeight", 0), 12)
    width_str = f"{width_ft}'{width_in}\""
    height_str = f"{height_ft}'{height_in}\""

    track_display = _format_mount_label(door.get("trackMount", "bracket"), door.get("trackThickness", "2"))
    lift_type = _format_lift_label(door.get("liftType", "standard"), door.get("highLiftInches"))

    door_type = door.get("doorType", "")
    design_display = _format_design_for_comment(
        door_type,
        door.get("panelDesign", ""),
        door.get("glazingType", ""),
        door.get("glassPaneType", ""),
    )

    pocket_info = ""
    glass_pockets = door.get("glassPocketsPerSection")
    if door_type == "aluminium" and glass_pockets:
        pocket_counts = [str(glass_pockets.get(str(i), glass_pockets.get(i, ''))) for i in sorted(glass_pockets.keys(), key=lambda x: int(x))]
        if pocket_counts:
            pocket_info = f", POCKETS: {'/'.join(pocket_counts)}"

    scope_label = _format_scope_label(door.get("hardware", {}) or {}, door_type)
    face_only = scope_label in ("DOOR FACE ONLY", "PANELS ONLY")

    segments = [
        f"({door.get('doorCount', 1)}) {width_str} x {height_str} {door.get('doorSeries', '')}",
        door.get('panelColor', ''),
    ]
    if design_display:
        segments.append(design_display)
    # Track/mount + lift only apply when the door ships with hardware; a
    # face/panels-only order has no tracks, so omit those segments.
    if not face_only:
        segments.extend([track_display, lift_type])
    if scope_label:
        segments.append(scope_label)
    return ", ".join(segments) + pocket_info


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


def _equalize_cone_prices(bc_quote_id: str) -> None:
    """Equalize LH/RH winder/stationary set prices on a BC quote.

    LH and RH cones are different BC items (e.g. SP12-00231-00 vs SP12-00237-00)
    which can have different unit costs/prices. Customers expect them at the same
    price, so after all lines are priced we find LH/RH pairs and PATCH both to
    the higher unitPrice of the two.
    """
    quote_lines = bc_client.get_quote_lines(bc_quote_id)

    # Identify winder/stationary set lines (SP12-xxxxx-00 items)
    # They come in LH/RH pairs with sequential part numbers.
    # Known pairs: SP12-00231-00 (LH) / SP12-00237-00 (RH) for 2" coil
    #              SP12-00232-00 (LH) / SP12-00238-00 (RH) for 2-5/8" coil, etc.
    cone_lines = []
    for ql in quote_lines:
        obj_num = ql.get("lineObjectNumber", "")
        if obj_num.startswith("SP12-") and ql.get("lineType") == "Item":
            desc = (ql.get("description") or "").upper()
            if "WINDER" in desc or "STATIONARY" in desc or "CONE" in desc:
                cone_lines.append(ql)

    if len(cone_lines) < 2:
        return

    # Group by coil size — cone pairs share the same description pattern
    # except for LH/RH. We pair them by matching description minus LH/RH.
    import re

    def _normalize_desc(d: str) -> str:
        """Strip LH/RH from description to find pairs."""
        return re.sub(r'\b(LH|RH|LEFT|RIGHT)\b', '', d.upper()).strip()

    # Group by normalized description
    groups: Dict[str, list] = {}
    for cl in cone_lines:
        key = _normalize_desc(cl.get("description", ""))
        groups.setdefault(key, []).append(cl)

    for key, pair in groups.items():
        if len(pair) < 2:
            continue
        prices = [p.get("unitPrice", 0) for p in pair]
        max_price = max(prices)
        if max_price <= 0:
            continue
        for line in pair:
            if line.get("unitPrice", 0) < max_price:
                etag = line.get("@odata.etag", "*")
                try:
                    bc_client.update_quote_line(
                        bc_quote_id,
                        line["id"],
                        etag,
                        {"unitPrice": max_price},
                    )
                    logger.info(
                        f"Equalized cone price: {line.get('lineObjectNumber')} "
                        f"${line.get('unitPrice', 0):.2f} → ${max_price:.2f}"
                    )
                except Exception as e:
                    logger.warning(
                        f"Failed to equalize cone price for {line.get('lineObjectNumber')}: {e}"
                    )


def _generate_bc_quote_with_items(
    doors: List[dict],
    bc_customer_id: str,
    config_id: int,
    pricing_tier: Optional[str] = None,
    db: Optional[Session] = None,
    po_number: Optional[str] = None,
    delivery_type: str = "delivery",
    customer_user_id: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Create a BC sales quote with real item lines for all doors.

    Returns dict with: bc_quote_id, bc_quote_number, lines_added, lines_failed,
    pricing, line_pricing, door_results
    """
    # Guard: users not yet linked to a real BC customer carry a "TEMP-<email>"
    # placeholder in bc_customer_id. Passing that to BC's salesQuotes endpoint
    # yields a cryptic "Cannot convert literal to Edm.Guid" 400. Fail early
    # with a friendly message so the customer sees actionable guidance.
    if not bc_customer_id or str(bc_customer_id).startswith("TEMP-"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Your account is not yet linked to our business system. "
                "Please contact OPENDC support to finish setting up your account."
            ),
        )

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

        # Mount-surface install note for the shop.
        _mount_note = _mount_surface_note(door)
        if _mount_note:
            all_lines.append({
                "lineType": "Comment",
                "description": _mount_note,
                "category": "COMMENT",
                "door_index": door_index,
                "is_note": True,
            })

        # Sections + glass-pockets comment for aluminium doors
        if door.get("doorType") == "aluminium":
            from app.services.part_number_service import format_aluminum_section_comment
            all_lines.append({
                "lineType": "Comment",
                "description": format_aluminum_section_comment(
                    door.get("doorHeight", 84),
                    door.get("doorWidth", 96),
                    door.get("glassPocketsPerSection"),
                ),
                "category": "COMMENT",
                "door_index": door_index,
                "is_note": True,
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
            "glassType": door.get("glassType", "ANNEALED"),
            "glassColor": door.get("glassColor"),
            "trackRadius": door.get("trackRadius", "15"),
            "trackThickness": door.get("trackThickness", "2"),
            "trackMount": door.get("trackMount", "bracket"),
            "mountSurface": door.get("mountSurface", "wood"),
            "liftType": door.get("liftType", "standard"),
            "highLiftInches": door.get("highLiftInches"),
            "hardware": door.get("hardware", {}),
            "operator": door.get("operator"),
            "operatorAccessories": door.get("operatorAccessories", []),
            "chainHoist": door.get("chainHoist"),
            "targetCycles": door.get("targetCycles", 10000),
            "shaftType": door.get("shaftType", "auto"),
        }

        try:
            door_parts = get_parts_for_door_config(config_dict, spring_inventory=spring_inventory)
            parts_list = door_parts.get("parts_list", [])
            sorted_parts = _sort_parts_by_category(parts_list)
            part_door_type = config_dict.get("doorType", "residential")

            # For aluminum doors, use commercial pricing on everything EXCEPT
            # aluminum sections and glazing (which keep aluminium pricing)
            aluminum_panel_categories = {
                "aluminum_section", "aluminum_glazing", "aluminum_glass",
                "v130g_section", "v130g_glass",
            }

            # Track whether we've emitted window placement comment
            window_note_emitted = False

            for part in sorted_parts:
                part["door_index"] = door_index
                cat = part.get("category", "")

                if cat in aluminum_panel_categories:
                    # V130G/AL976 frames and glazing ALWAYS use aluminium pricing
                    part["door_type"] = "aluminium"
                elif part_door_type == "aluminium" and cat not in aluminum_panel_categories:
                    # Non-panel parts on aluminium doors use commercial pricing
                    part["door_type"] = "commercial"
                else:
                    part["door_type"] = part_door_type

                # Info comments → BC Comment line (not an item)
                # The "comment" category is the legacy duplicate door-header
                # note generated by part_number_service. customer_portal /
                # door_configurator already render the canonical
                # _format_door_description header; skip the duplicate.
                if part.get("category") == "comment":
                    continue
                if part.get("category") in ("spring_comment", "highlift_comment"):
                    part["lineType"] = "Comment"
                    part["is_note"] = True

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

        # Blank separator after every door (including last — separates from freight).
        # NBSP (U+00A0), not a regular space: BC's API drops whitespace-only
        # comment descriptions server-side, which used to make doors run
        # together in the printed quote with no visual break between them.
        all_lines.append({
            "lineType": "Comment",
            "description": "-",
            "category": "COMMENT",
            "door_index": door_index,
            "is_separator": True,
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

    # Flag pickup orders at the top of the BC quote so production sees it
    # without scrolling. Delivery quotes don't need a marker — that's the default.
    if (delivery_type or "").lower() == "pickup":
        try:
            bc_client.add_quote_line(bc_quote_id, {
                "lineType": "Comment",
                "description": "** PICKUP: This order is quoted for customer pickup **",
            })
            logger.info(f"Added pickup comment to BC quote {bc_quote_number}")
        except Exception as pickup_err:
            logger.warning(f"Failed to add pickup comment to {bc_quote_number}: {pickup_err}")

    # Step 3: Warm the BC cost cache so pricing uses live production costs
    if pricing_tier and db:
        item_pns = [l["part_number"] for l in all_lines if l.get("part_number")]
        warm_bc_cost_cache(item_pns)

    # BC SalesPriceLists is the single source of truth for unit prices.
    # The portal does NOT patch unitPrice on quote lines — BC resolves the
    # right price natively (Customer → Customer Price Group → All Customers
    # → Item.unitPrice). The legacy margin engine and volume curve are
    # disabled in the live path until BC costing is proven; once that's
    # done, discount logic can be re-enabled via the feature flag below.
    #
    # AppSettings.pricing_enable_volume_curve (default False) gates the
    # GNB-style escalating margin. While False the curve is skipped
    # entirely; while True it applies to BC's resolved prices.
    enable_volume_curve = False
    if db:
        flag_setting = db.query(AppSettings).filter(
            AppSettings.setting_key == "pricing_enable_volume_curve"
        ).first()
        enable_volume_curve = bool(flag_setting and flag_setting.setting_value)
    logger.info(
        f"PRICING MODE: trust_bc=True, enable_volume_curve={enable_volume_curve}"
    )

    # Step 4: Add line items
    lines_added = 0
    lines_failed = []
    bc_items_cache: dict = {}  # category prefix → list of BC items (populated lazily)
    tier_prices_by_line_id = {}  # Track per-line metadata for escalating margin

    # Per-door + shared BC line ID map (persisted on SavedQuoteConfig.bc_line_map).
    # Enables surgical per-door edits later without recreating the BC quote.
    line_map: Dict[str, Dict[str, List[str]]] = {"doors": {}, "shared": {}}

    def _track_door_line(door_index: Optional[int], bc_line: Optional[Dict[str, Any]]) -> None:
        if not bc_line or not bc_line.get("id") or not door_index:
            return
        line_map["doors"].setdefault(str(door_index), []).append(bc_line["id"])

    def _track_shared_line(bucket: str, bc_line: Optional[Dict[str, Any]]) -> None:
        if not bc_line or not bc_line.get("id"):
            return
        line_map["shared"].setdefault(bucket, []).append(bc_line["id"])

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
            _track_door_line(line.get("door_index"), added_line)

            # Set Output=True on door descriptions, operators, and accessories
            # so BC shows them on printed quotes and subtotals correctly.
            needs_output = (
                line.get("is_door_desc")
                or line.get("category") in ("operator",)
            )
            if needs_output and added_line.get("sequence"):
                try:
                    bc_client.set_quote_line_output(
                        bc_quote_number, added_line["sequence"], output=True
                    )
                except Exception as out_err:
                    logger.warning(f"Failed to set Output flag on line: {out_err}")

            # BC auto-populates description and unitPrice from the item card
            # on POST, overriding what we send.  PATCH afterward to restore
            # our intended description and lock in the customer-tier price.
            if line.get("lineType") != "Comment":
                patch_data = {}

                # Always restore our description (BC overwrites it with item card displayName)
                intended_desc = line.get("description", "")
                if intended_desc:
                    bc_desc = added_line.get("description", "")
                    if bc_desc != intended_desc:
                        patch_data["description"] = intended_desc[:100]

                # Trust BC. Track the line so the volume curve can find it
                # if/when re-enabled, but do NOT PATCH unitPrice.
                if line.get("lineType") != "Comment" and db:
                    part_num = line["part_number"]
                    from app.services.pricing_service import _get_live_item
                    live = _get_live_item(part_num) or {}
                    posting_group = live.get("generalProductPostingGroupCode", "")
                    tier_prices_by_line_id[added_line["id"]] = {
                        "qty": line.get("quantity", 1),
                        "posting_group": posting_group,
                    }
                    logger.info(
                        f"PRICING [{part_num}]: trust BC SalesPriceLists "
                        f"(no portal-side override)"
                    )

                if patch_data:
                    etag = added_line.get("@odata.etag", "*")
                    try:
                        bc_client.update_quote_line(
                            bc_quote_id,
                            added_line["id"],
                            etag,
                            patch_data,
                        )
                        logger.info(f"PATCH SUCCESS [{line['part_number']}]: {list(patch_data.keys())}")
                    except Exception as patch_err:
                        logger.error(f"PATCH FAILED [{line['part_number']}]: {patch_err}")

        except Exception as line_error:
            part_id = line.get("part_number", line.get("description", "unknown"))
            logger.warning(f"Failed to add line {part_id}: {line_error}")

            # ── PANEL: try stepping up to next biggest width in BC.
            line_category = line.get("category", "")
            if line_category == "panel":
                from app.services.bc_part_number_mapper import get_bc_mapper
                panel_mapper = get_bc_mapper()
                pn_parts = part_id.rsplit("-", 1)
                stepped_up = False
                if len(pn_parts) == 2:
                    pn_prefix = pn_parts[0]
                    width_code = pn_parts[1]
                    try:
                        orig_feet = int(width_code[:2])
                    except (ValueError, IndexError):
                        orig_feet = 0

                    for try_feet in range(orig_feet + 1, 31):
                        for try_inches in [0, 2]:
                            try_pn = f"{pn_prefix}-{try_feet:02d}{try_inches:02d}"
                            if try_pn in panel_mapper.bc_items:
                                logger.info(f"Panel {part_id} not in BC — stepped up to {try_pn}")
                                try:
                                    sub_data = {
                                        "lineType": "Item",
                                        "lineObjectNumber": try_pn,
                                        "description": line.get("description", ""),
                                        "quantity": line["quantity"],
                                    }
                                    added_sub = bc_client.add_quote_line(bc_quote_id, sub_data)
                                    lines_added += 1
                                    _track_door_line(line.get("door_index"), added_sub)
                                    stepped_up = True
                                except Exception:
                                    pass
                                break
                        if stepped_up:
                            break

                if not stepped_up:
                    logger.error(
                        f"PANEL PART FAILED — aborting quote {bc_quote_number}. "
                        f"Part: {part_id}, Error: {line_error}"
                    )
                    try:
                        bc_client.delete_sales_quote(bc_quote_id)
                    except Exception:
                        pass
                    return {
                        "success": False,
                        "error": (
                            f"Panel part number {part_id} could not be resolved in BC. "
                            f"Please contact the office to complete this quote."
                        ),
                        "bc_quote_id": None,
                        "bc_quote_number": None,
                        "lines_added": 0,
                        "lines_failed": [{"part_number": part_id, "error": str(line_error), "category": "panel"}],
                        "pricing": None,
                        "line_pricing": None,
                        "door_results": None,
                        "freight": None,
                        "escalating_margin": None,
                    }

            # ── Substitute lookup ──────────────────────────────────────────
            # 1) Deterministic step-up: if the SKU ends in a 4-digit width
            #    code, pick the smallest BC SKU with the same prefix and a
            #    LARGER width — never a smaller one. Catches PN80, PN10/12,
            #    PN20, PN70, PN97 and anything else size-keyed.
            # 2) Fallback to Claude for non-size-keyed parts (e.g. shafts,
            #    accessory items where AI similarity matching makes sense).
            ai_used = False
            substitute = None
            if line.get("lineType") != "Comment" and line.get("part_number"):
                from app.services.bc_part_number_mapper import get_bc_mapper
                from app.api.door_configurator import _next_bigger_width_skus
                mapper = get_bc_mapper()
                bigger_pn = _next_bigger_width_skus(line["part_number"], mapper.bc_items)
                if bigger_pn:
                    substitute = mapper.bc_items.get(bigger_pn) or {"number": bigger_pn}
                    if "number" not in substitute:
                        substitute = dict(substitute, number=bigger_pn)
                    logger.info(f"Step-up substitute: {line['part_number']} → {bigger_pn}")
                else:
                    substitute = _find_ai_substitute(
                        part_number=line["part_number"],
                        description=line.get("description", ""),
                        bc_items_cache=bc_items_cache,
                    )
                if substitute and substitute.get("number"):
                    try:
                        original_desc = line.get("description", "") or substitute.get('displayName', substitute['number'])
                        sub_line_data = {
                            "lineType": "Item",
                            "lineObjectNumber": substitute["number"],
                            "description": original_desc,
                            "quantity": line["quantity"],
                        }
                        added_sub = bc_client.add_quote_line(bc_quote_id, sub_line_data)
                        lines_added += 1
                        _track_door_line(line.get("door_index"), added_sub)
                        ai_used = True

                        # BC overwrites description with substitute's item card.
                        # PATCH to restore intended description + apply tier pricing.
                        sub_patch = {}
                        bc_sub_desc = added_sub.get("description", "")
                        if original_desc and bc_sub_desc != original_desc:
                            sub_patch["description"] = original_desc[:100]

                        # Trust BC for the substitute's price — it's a real BC
                        # SKU, so BC resolves it natively on POST (Customer →
                        # Price Group → All → Item card). Never override with the
                        # legacy margin engine; matches the rest of this path.
                        if sub_patch:
                            etag = added_sub.get("@odata.etag", "*")
                            bc_client.update_quote_line(
                                bc_quote_id,
                                added_sub["id"],
                                etag,
                                sub_patch,
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
                    added_fallback = bc_client.add_quote_line(bc_quote_id, comment_line)
                    lines_added += 1
                    _track_door_line(line.get("door_index"), added_fallback)
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

    # Step 4a: Equalize LH/RH cone (winder/stationary) set prices
    # LH and RH cones are different BC items (e.g. SP12-00231-00 vs SP12-00237-00)
    # but should show the same unit price. After all lines are added and priced,
    # fetch all quote lines, find cone pairs, and PATCH both to the higher price.
    try:
        _equalize_cone_prices(bc_quote_id)
    except Exception as cone_err:
        logger.warning(f"Could not equalize cone prices: {cone_err}")

    # Step 4b: Fetch pricing back from BC
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

    # Step 4c: Escalating margin (client-specific volume discount).
    # DISABLED by default — set AppSettings.pricing_enable_volume_curve = True
    # to re-enable once BC costing is reconciled. Until then BC's resolved
    # Sales Price stands as-is and we don't apply any portal-side discount.
    escalating_result = None
    if enable_volume_curve and tier_prices_by_line_id and db:
        try:
            from app.services.escalating_margin_service import get_escalating_margin
            bc_cust_for_esc = db.query(BCCustomer).filter(
                BCCustomer.bc_customer_id == bc_customer_id
            ).first()
            customer_display_name = bc_cust_for_esc.company_name if bc_cust_for_esc else ""
            esc_profile = get_escalating_margin(customer_display_name)

            if esc_profile:
                # Re-fetch lines so we read BC's resolved unitPrice (post-
                # SalesPriceLists). Aluminum lines bypass the curve entirely.
                esc_quote_lines = bc_client.get_quote_lines(bc_quote_id)
                # Index by line_id for split + multiplier application
                lines_indexed = {}
                for ql in esc_quote_lines:
                    line_id = ql.get("id")
                    if line_id and line_id in tier_prices_by_line_id:
                        lines_indexed[line_id] = {
                            "price": ql.get("unitPrice") or 0,
                            "qty": tier_prices_by_line_id[line_id]["qty"],
                            "posting_group": tier_prices_by_line_id[line_id]["posting_group"],
                            "etag": ql.get("@odata.etag", "*"),
                            "part_num": ql.get("lineObjectNumber", ""),
                        }
                curve_lines, excluded_lines = esc_profile.split_lines(lines_indexed)
                tier_subtotal = sum(lp["price"] * lp["qty"] for lp in curve_lines.values())
                esc_calc = esc_profile.calculate(tier_subtotal)
                multiplier = esc_calc["multiplier"]

                if multiplier < 1.0:
                    logger.info(
                        f"Applying escalating margin [{esc_profile.name}]: "
                        f"BC-resolved subtotal ${tier_subtotal:,.0f} × {multiplier:.4f} "
                        f"({len(excluded_lines)} aluminum line(s) excluded)"
                    )

                    for line_id, lp in curve_lines.items():
                        bc_price = lp["price"]
                        adj_price = round(bc_price * multiplier, 2)
                        try:
                            bc_client.update_quote_line(
                                bc_quote_id, line_id, lp["etag"],
                                {"unitPrice": adj_price},
                            )
                        except Exception as esc_patch_err:
                            logger.warning(
                                f"Escalating margin PATCH failed for "
                                f"{lp['part_num']}: {esc_patch_err}"
                            )

                    # Add a comment noting the volume discount
                    try:
                        added_vol_comment = bc_client.add_quote_line(bc_quote_id, {
                            "lineType": "Comment",
                            "description": (
                                f"** VOLUME PRICING: {esc_profile.name} — "
                                f"{esc_calc['discount_pct']:.1f}% volume discount applied **"
                            ),
                        })
                        _track_shared_line("volume_discount", added_vol_comment)
                    except Exception:
                        pass

                    # Re-fetch pricing totals after adjustment
                    try:
                        updated = bc_client.get_sales_quote(bc_quote_id)
                        pricing["subtotal"] = round(updated.get("totalAmountExcludingTax", 0), 2)
                        pricing["total"] = round(updated.get("totalAmountIncludingTax", 0), 2)
                        pricing["tax"] = round(pricing["total"] - pricing["subtotal"], 2)
                    except Exception:
                        pass

                    escalating_result = esc_calc
        except Exception as esc_err:
            logger.warning(f"Escalating margin check failed: {esc_err}")

    # Step 5: Add freight line if delivery.
    # Skip entirely for home-builder accounts — their INSTALLATION line already
    # bills per-km crew travel, so freight would charge the same trip twice.
    freight_info = None
    if pricing and db and not _account_provides_install(customer_user_id, db):
        try:
            # Get customer province
            customer_province = None
            bc_cust = db.query(BCCustomer).filter(
                BCCustomer.bc_customer_id == bc_customer_id
            ).first()
            if bc_cust and bc_cust.address:
                customer_province = bc_cust.address.get("province")

            freight = calculate_freight(
                product_subtotal=pricing["subtotal"],
                province=customer_province,
                delivery_type=delivery_type,
                db=db,
            )
            freight_info = freight

            if not freight["skip"] and freight["amount"] > 0:
                freight_config = get_freight_config(db)
                freight_item = freight_config.get("freight_item_number", "FREIGHT")
                freight_added = False

                # Try adding as Item line
                try:
                    freight_line_data = {
                        "lineType": "Item",
                        "lineObjectNumber": freight_item,
                        "description": freight["description"],
                        "quantity": 1,
                    }
                    added_freight = bc_client.add_quote_line(bc_quote_id, freight_line_data)
                    etag = added_freight.get("@odata.etag", "*")
                    bc_client.update_quote_line(
                        bc_quote_id,
                        added_freight["id"],
                        etag,
                        {"unitPrice": freight["amount"]},
                    )
                    _track_shared_line("freight", added_freight)
                    _set_output_true(bc_quote_number, added_freight, label="freight")
                    freight_added = True
                    logger.info(f"Added freight line: ${freight['amount']:.2f} ({freight['description']})")
                except Exception as freight_item_err:
                    logger.warning(f"Could not add freight as Item '{freight_item}': {freight_item_err}")

                    if freight_config.get("fallback_to_comment", True):
                        try:
                            comment_data = {
                                "lineType": "Comment",
                                "description": f"{freight['description']}: ${freight['amount']:.2f}",
                            }
                            added_freight_comment = bc_client.add_quote_line(bc_quote_id, comment_data)
                            _track_shared_line("freight", added_freight_comment)
                            freight_added = True
                            logger.info(f"Added freight as comment fallback: ${freight['amount']:.2f}")
                        except Exception as comment_err:
                            logger.warning(f"Could not add freight as comment: {comment_err}")

                # Re-fetch totals if freight was added
                if freight_added:
                    try:
                        updated_quote = bc_client.get_sales_quote(bc_quote_id)
                        subtotal = updated_quote.get("totalAmountExcludingTax", 0)
                        total_with_tax = updated_quote.get("totalAmountIncludingTax", 0)
                        tax_amount = total_with_tax - subtotal
                        pricing = {
                            "subtotal": round(subtotal, 2),
                            "tax": round(tax_amount, 2),
                            "total": round(total_with_tax, 2),
                            "currency": "CAD",
                        }
                    except Exception as refetch_err:
                        logger.warning(f"Could not re-fetch totals after freight: {refetch_err}")

        except Exception as freight_err:
            logger.warning(f"Could not calculate/add freight: {freight_err}")

    # Step 6: Add installation block for home builder customers.
    # Builder install pricing is a single sum-total across the quote,
    # not a per-door breakdown — see install_pricing_service for the model.
    install_info = None
    if customer_user_id and db:
        try:
            from app.services.install_pricing_service import install_pricing_service
            from app.db.models import User as UserModel

            customer_user = db.query(UserModel).filter(UserModel.id == customer_user_id).first()
            account_type = getattr(customer_user, 'account_type', None) if customer_user else None

            if account_type == 'home_builder':
                install_town = doors[0].get("installTown") if doors else None
                install_result = install_pricing_service.calculate_total_install_price(
                    customer_id=customer_user_id,
                    doors=doors,
                    town=install_town,
                    db=db,
                )
                _add_install_block(
                    bc_quote_id=bc_quote_id,
                    bc_quote_number=bc_quote_number,
                    install_result=install_result,
                    track_shared=_track_shared_line,
                )
                install_info = install_result

                # Re-fetch totals so the response reflects the install block.
                try:
                    updated_quote = bc_client.get_sales_quote(bc_quote_id)
                    subtotal = updated_quote.get("totalAmountExcludingTax", 0)
                    total_with_tax = updated_quote.get("totalAmountIncludingTax", 0)
                    pricing = {
                        "subtotal": round(subtotal, 2),
                        "tax": round(total_with_tax - subtotal, 2),
                        "total": round(total_with_tax, 2),
                        "currency": "CAD",
                    }
                except Exception:
                    pass
                logger.info(
                    f"Install block added to quote {bc_quote_number}: "
                    f"${install_result['grand_total']:.2f} "
                    f"({install_result['total_sqft']:.0f} sqft, town={install_town!r})"
                )

        except Exception as install_err:
            logger.warning(f"Could not add installation pricing: {install_err}")

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

    # Log pricing failures for admin visibility (not shown to customers)
    if lines_failed:
        failed_parts = [f"{f.get('part_number', '?')} ({f.get('fallback', 'failed')})" for f in lines_failed]
        logger.warning(
            f"Quote {bc_quote_number}: {len(lines_failed)} item(s) could not be priced: "
            f"{', '.join(failed_parts)}"
        )

    return {
        "bc_quote_id": bc_quote_id,
        "bc_quote_number": bc_quote_number,
        "lines_added": lines_added,
        "lines_failed": lines_failed if lines_failed else None,
        "pricing": pricing,
        "line_pricing": line_pricing if line_pricing else None,
        "door_results": door_results,
        "freight": freight_info,
        "escalating_margin": escalating_result,
        "line_map": line_map,
    }


def _has_sales_order_for_quote(config: SavedQuoteConfig, db: Session) -> bool:
    """Returns True if a SalesOrder has been placed against this quote. Order placement
    is the true edit lock — a quote can be freely edited until it becomes an order."""
    if not config.bc_quote_number:
        return False
    return db.query(SalesOrder).filter(
        SalesOrder.bc_quote_number == config.bc_quote_number
    ).first() is not None


def _diff_doors(old_doors: List[dict], new_doors: List[dict]) -> Dict[str, Any]:
    """Diff old vs new door configs.

    Identity-based when every door carries a `door_uid` — so reordering or
    inserting a door doesn't trigger spurious BC line regeneration.
    Falls back to position-based (legacy) when any uid is missing.

    Returns a dict with 1-based positions:
      changed: NEW positions whose uid existed in old but content differs
      added:   NEW positions whose uid is new
      removed: OLD positions whose uid is no longer present
      moved:   list of (old_pos, new_pos) — uid unchanged, content unchanged,
               but the door shifted position; pure line_map remap, no BC writes
    """
    def _content_only(d: dict) -> dict:
        # Compare door content WITHOUT the uid (the uid is identity, not content).
        return {k: v for k, v in d.items() if k != "door_uid"}

    have_all_uids = (
        bool(old_doors) and bool(new_doors)
        and all(d.get("door_uid") for d in old_doors)
        and all(d.get("door_uid") for d in new_doors)
    )

    if not have_all_uids:
        # Legacy positional diff
        changed: List[int] = []
        added: List[int] = []
        removed: List[int] = []
        max_len = max(len(old_doors), len(new_doors))
        for i in range(max_len):
            old = old_doors[i] if i < len(old_doors) else None
            new = new_doors[i] if i < len(new_doors) else None
            idx = i + 1
            if old is None:
                added.append(idx)
            elif new is None:
                removed.append(idx)
            elif _content_only(old) != _content_only(new):
                changed.append(idx)
        return {"changed": changed, "added": added, "removed": removed, "moved": []}

    # Identity-based diff
    old_by_uid = {d["door_uid"]: (i + 1, d) for i, d in enumerate(old_doors)}
    new_by_uid = {d["door_uid"]: (i + 1, d) for i, d in enumerate(new_doors)}

    changed = []
    added = []
    removed = []
    moved: List[Tuple[int, int]] = []

    for uid, (new_pos, new_d) in new_by_uid.items():
        if uid not in old_by_uid:
            added.append(new_pos)
        else:
            old_pos, old_d = old_by_uid[uid]
            if _content_only(old_d) != _content_only(new_d):
                changed.append(new_pos)
            elif old_pos != new_pos:
                moved.append((old_pos, new_pos))

    for uid, (old_pos, _) in old_by_uid.items():
        if uid not in new_by_uid:
            removed.append(old_pos)

    return {"changed": changed, "added": added, "removed": removed, "moved": moved}


def _set_output_true(bc_quote_number: str, added_line: dict, label: str = "line") -> None:
    """Flip BC's Output flag on so the line shows on printed quotes.
    Silent on failure — Output is cosmetic, never abort the quote over it."""
    seq = (added_line or {}).get("sequence")
    if not seq:
        return
    try:
        bc_client.set_quote_line_output(bc_quote_number, seq, output=True)
    except Exception as e:
        logger.warning(f"Failed to set Output flag on {label}: {e}")


def _add_install_block(
    *,
    bc_quote_id: str,
    bc_quote_number: str,
    install_result: dict,
    track_shared: callable,
) -> List[str]:
    """
    Append the installation as a SINGLE consolidated line on the BC quote.
    One Item INSTALLATION line carrying the grand total (base install + lift
    fee + per diem + operator add-on + travel) — no breakdown lines, no
    header comment. Output=True so it prints on the customer-facing quote.

    Returns the list of BC line IDs created so the caller can store them
    in line_map.shared.install.
    """
    added_ids: List[str] = []
    if not install_result or install_result.get("grand_total", 0) <= 0:
        return added_ids

    sqft = install_result["total_sqft"]
    door_count = install_result["door_count_total"]
    town = install_result.get("town")
    total = install_result["grand_total"]

    desc = f"Installation - {town} ({sqft:.0f} sqft, {door_count} door(s))" if town \
           else f"Installation ({sqft:.0f} sqft, {door_count} door(s))"

    try:
        line = bc_client.add_quote_line(bc_quote_id, {
            "lineType": "Item",
            "lineObjectNumber": "INSTALLATION",
            "description": desc[:100],
            "quantity": 1,
        })
        etag = line.get("@odata.etag", "*")
        bc_client.update_quote_line(bc_quote_id, line["id"], etag, {"unitPrice": total})
        if line.get("id"):
            added_ids.append(line["id"])
            track_shared("install", line)
        _set_output_true(bc_quote_number, line, label="installation")
    except Exception as e:
        logger.warning(f"Could not add INSTALLATION item: {e}")
        try:
            fb = bc_client.add_quote_line(bc_quote_id, {
                "lineType": "Comment",
                "description": f"{desc}: ${total:.2f}",
            })
            if fb.get("id"):
                added_ids.append(fb["id"])
                track_shared("install", fb)
            _set_output_true(bc_quote_number, fb, label="installation (comment fallback)")
        except Exception:
            pass

    return added_ids


def _delete_bc_lines(bc_quote_id: str, line_ids: List[str]) -> int:
    """Best-effort delete of BC lines. Logs failures, doesn't raise."""
    deleted = 0
    for line_id in line_ids:
        try:
            bc_client.delete_quote_line(bc_quote_id, line_id)
            deleted += 1
        except Exception as e:
            logger.warning(f"Could not delete BC line {line_id}: {e}")
    return deleted


def _sweep_freight_lines(bc_quote_id: str, freight_item: str = "FREIGHT") -> int:
    """
    Delete every freight line currently on the BC quote, regardless of whether
    it's tracked in line_map. Catches stale freight from a delivery→pickup flip,
    repeated edits where line_map missed the previous freight, or freight added
    by a code path that didn't update line_map. Required because the freight
    recompute reads `totalAmountExcludingTax` and would compound any leftover
    freight into the new freight amount (× 1.05 per round).
    """
    try:
        existing = bc_client.get_quote_lines(bc_quote_id)
    except Exception as e:
        logger.warning(f"Freight sweep — could not list quote lines: {e}")
        return 0
    stale_ids = []
    for ln in existing:
        if (ln.get("lineObjectNumber") or "").strip().upper() == freight_item.upper():
            stale_ids.append(ln["id"])
            continue
        # Catch the comment-fallback variant too: descriptions added by the
        # fallback path begin with "Freight (".
        desc = (ln.get("description") or "").strip()
        if ln.get("lineType") == "Comment" and desc.lower().startswith("freight ("):
            stale_ids.append(ln["id"])
    if stale_ids:
        deleted = _delete_bc_lines(bc_quote_id, stale_ids)
        logger.info(f"Freight sweep on quote {bc_quote_id}: deleted {deleted}/{len(stale_ids)} freight line(s)")
        return deleted
    return 0


def _build_door_config_dict(door: dict) -> dict:
    """Build the config_dict passed to get_parts_for_door_config. Matches the shape
    used in _generate_bc_quote_with_items step 1."""
    return {
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
        "glassType": door.get("glassType", "ANNEALED"),
        "glassColor": door.get("glassColor"),
        "trackRadius": door.get("trackRadius", "15"),
        "trackThickness": door.get("trackThickness", "2"),
        "trackMount": door.get("trackMount", "bracket"),
        "mountSurface": door.get("mountSurface", "wood"),
        "liftType": door.get("liftType", "standard"),
        "highLiftInches": door.get("highLiftInches"),
        "hardware": door.get("hardware", {}),
        "operator": door.get("operator"),
        "operatorAccessories": door.get("operatorAccessories", []),
        "targetCycles": door.get("targetCycles", 10000),
        "shaftType": door.get("shaftType", "auto"),
    }


def _edit_bc_quote_lines(
    config: SavedQuoteConfig,
    new_config_data: dict,
    bc_customer_id: str,
    pricing_tier: str,
    db: Session,
    customer_user_id: int,
    delivery_type: str = "delivery",
) -> Dict[str, Any]:
    """
    Surgically edit an existing BC sales quote.

    - Diffs old vs new doors; deletes only the lines for changed/removed doors
    - Deletes all shared lines (freight/install/travel/volume_discount)
    - Regenerates changed + added doors' lines at tier pricing
    - Regenerates shared lines from the new totals
    - KEEPS the same bc_quote_id and bc_quote_number

    Escalating margin is NOT recomputed here (customer clicks "Refresh Pricing"
    for that — which rebuilds the whole quote from scratch).
    """
    if not bc_customer_id or str(bc_customer_id).startswith("TEMP-"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Your account is not yet linked to our business system. "
                "Please contact OPENDC support to finish setting up your account."
            ),
        )

    bc_quote_id = config.bc_quote_id
    bc_quote_number = config.bc_quote_number
    if not bc_quote_id:
        raise HTTPException(400, "Quote has no BC reference to edit")

    # Keep External Document No. in sync with the customer's PO. The PO is only
    # stamped at quote-creation time, so a PO typed (or corrected) after the BC
    # quote already exists would otherwise stay as the PORTAL-<id> fallback all
    # the way through to the sales order. Non-fatal: never fail an edit over it.
    new_po = (new_config_data or {}).get("poNumber")
    old_po = (config.config_data or {}).get("poNumber")
    if new_po and new_po != old_po:
        try:
            bc_client.update_sales_quote(bc_quote_id, {"externalDocumentNumber": new_po})
            logger.info(f"Updated External Document No. on {bc_quote_number} to '{new_po}'")
        except Exception as po_err:
            logger.warning(f"Could not update External Document No. on {bc_quote_number}: {po_err}")

    old_doors = (config.config_data or {}).get("doors", [])
    new_doors = _validate_doors_config(new_config_data)

    diff = _diff_doors(old_doors, new_doors)
    logger.info(f"Edit diff for quote {bc_quote_number}: {diff}")

    # Load existing line_map (tolerate legacy configs without one)
    line_map = config.bc_line_map or {"doors": {}, "shared": {}}
    line_map.setdefault("doors", {})
    line_map.setdefault("shared", {})

    indices_to_regenerate = sorted(set(diff["changed"] + diff["added"]))
    indices_to_delete = sorted(set(diff["changed"] + diff["removed"]))
    moves = diff.get("moved") or []

    # ── Step 1 (precompute): Build new line dicts BEFORE touching BC ────────
    # Doing precompute first means a failure here (bad part numbers, BC
    # spring-inventory fetch error, etc.) raises cleanly without leaving the
    # BC quote in a half-deleted state. Only after precompute succeeds do we
    # commit to the destructive delete-then-recreate sequence below.
    try:
        spring_inventory = get_bc_spring_inventory()
    except Exception as inv_err:
        logger.error(f"Pre-edit spring inventory fetch failed: {inv_err}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not reach BC to validate edit. No changes were made — please try again.",
        )

    all_new_lines: List[dict] = []
    door_results: List[dict] = []
    aluminum_panel_categories = {
        "aluminum_section", "aluminum_glazing", "aluminum_glass",
        "v130g_section", "v130g_glass",
    }

    for door_index in indices_to_regenerate:
        if door_index > len(new_doors):
            continue  # defensive: don't regen a position that doesn't exist
        door = new_doors[door_index - 1]
        door_desc = _format_door_description(door)

        all_new_lines.append({
            "lineType": "Comment", "description": door_desc, "category": "COMMENT",
            "door_index": door_index, "is_door_desc": True,
        })

        _mount_note = _mount_surface_note(door)
        if _mount_note:
            all_new_lines.append({
                "lineType": "Comment",
                "description": _mount_note,
                "category": "COMMENT", "door_index": door_index, "is_note": True,
            })

        if door.get("doorType") == "aluminium":
            from app.services.part_number_service import format_aluminum_section_comment
            all_new_lines.append({
                "lineType": "Comment",
                "description": format_aluminum_section_comment(
                    door.get("doorHeight", 84),
                    door.get("doorWidth", 96),
                    door.get("glassPocketsPerSection"),
                ),
                "category": "COMMENT", "door_index": door_index, "is_note": True,
            })

        config_dict = _build_door_config_dict(door)
        try:
            door_parts = get_parts_for_door_config(config_dict, spring_inventory=spring_inventory)
            parts_list = door_parts.get("parts_list", [])
            sorted_parts = _sort_parts_by_category(parts_list)
            part_door_type = config_dict.get("doorType", "residential")
            window_note_emitted = False

            for part in sorted_parts:
                part["door_index"] = door_index
                cat = part.get("category", "")
                if cat in aluminum_panel_categories:
                    part["door_type"] = "aluminium"
                elif part_door_type == "aluminium" and cat not in aluminum_panel_categories:
                    part["door_type"] = "commercial"
                else:
                    part["door_type"] = part_door_type
                # The "comment" category is the legacy duplicate door-header
                # note generated by part_number_service. customer_portal /
                # door_configurator already render the canonical
                # _format_door_description header; skip the duplicate.
                if part.get("category") == "comment":
                    continue
                if part.get("category") in ("spring_comment", "highlift_comment"):
                    part["lineType"] = "Comment"
                    part["is_note"] = True
                all_new_lines.append(part)
                if not window_note_emitted and part.get("notes") and part.get("category") in ("window", "commercial_window"):
                    window_note_emitted = True
                    all_new_lines.append({
                        "lineType": "Comment", "description": part["notes"],
                        "category": "COMMENT", "door_index": door_index, "is_note": True,
                    })

            door_results.append({
                "door_index": door_index, "door_description": door_desc,
                "parts_count": len(parts_list), "success": True,
            })
        except Exception as e:
            logger.warning(f"Failed to get parts for door {door_index}: {e}")
            door_results.append({
                "door_index": door_index, "door_description": door_desc,
                "parts_count": 0, "success": False, "error": str(e),
            })

        all_new_lines.append({
            "lineType": "Comment", "description": "-", "category": "COMMENT",
            "door_index": door_index, "is_separator": True,
        })

    # Warm BC cost cache for regenerated parts
    item_pns = [l["part_number"] for l in all_new_lines if l.get("part_number")]
    if item_pns:
        warm_bc_cost_cache(item_pns)

    # ── Step 2: Delete old door lines for changed/removed doors ─────────────
    # Done AFTER precompute so a precompute failure leaves BC untouched.
    # Done BEFORE move remap so we delete from the ORIGINAL position keys.
    for idx in indices_to_delete:
        line_ids = line_map["doors"].pop(str(idx), [])
        if line_ids:
            _delete_bc_lines(bc_quote_id, line_ids)
            logger.info(f"Deleted {len(line_ids)} line(s) for door {idx}")

    # ── Step 2b: Remap line_map for doors that just moved position ──────────
    # An identity-based diff produces "moved" entries when a door's content is
    # unchanged but its index shifted (e.g. the user removed door 1 so door 2
    # is now door 1). The BC lines don't need to change — only our internal
    # index → line-id mapping.
    if moves:
        moving_old_keys = {str(old_pos) for old_pos, _ in moves}
        relocations = {
            str(new_pos): line_map["doors"].get(str(old_pos), [])
            for old_pos, new_pos in moves
        }
        target_keys = set(relocations.keys())
        preserved = {
            k: v for k, v in line_map["doors"].items()
            if k not in moving_old_keys and k not in target_keys
        }
        line_map["doors"] = {**preserved, **relocations}
        logger.info(f"Remapped {len(moves)} door position(s) without BC writes: {moves}")

    # ── Step 3: Delete all shared lines (always regenerated) ────────────────
    for bucket, line_ids in list(line_map["shared"].items()):
        _delete_bc_lines(bc_quote_id, line_ids)
    line_map["shared"] = {}

    # Belt-and-suspenders: sweep any freight lines that line_map missed. Without
    # this, leftover freight gets folded into `totalAmountExcludingTax` below
    # and the recomputed freight stacks at × 1.05 per edit (see SQ-002500).
    try:
        freight_item_no = get_freight_config(db).get("freight_item_number", "FREIGHT")
    except Exception:
        freight_item_no = "FREIGHT"
    _sweep_freight_lines(bc_quote_id, freight_item=freight_item_no)

    # ── Step 4: Push new lines to BC with tier pricing ──────────────────────
    lines_added = 0
    lines_failed: List[dict] = []

    for line in all_new_lines:
        try:
            if line.get("lineType") == "Comment":
                line_data = {"lineType": "Comment", "description": line["description"]}
            else:
                line_data = {
                    "lineType": "Item",
                    "lineObjectNumber": line["part_number"],
                    "description": line.get("description", ""),
                    "quantity": line["quantity"],
                }
            added_line = bc_client.add_quote_line(bc_quote_id, line_data)
            lines_added += 1
            di = line.get("door_index")
            if di and added_line and added_line.get("id"):
                line_map["doors"].setdefault(str(di), []).append(added_line["id"])

            needs_output = line.get("is_door_desc") or line.get("category") in ("operator",)
            if needs_output and added_line.get("sequence"):
                try:
                    bc_client.set_quote_line_output(bc_quote_number, added_line["sequence"], output=True)
                except Exception as out_err:
                    logger.warning(f"Failed to set Output flag on line: {out_err}")

            if line.get("lineType") != "Comment":
                patch_data = {}
                intended_desc = line.get("description", "")
                if intended_desc and added_line.get("description", "") != intended_desc:
                    patch_data["description"] = intended_desc[:100]
                # Trust BC SalesPriceLists for unit price — do NOT override with
                # the legacy margin engine. This matches the new-quote generate
                # path (_generate_bc_quote_with_items / build_bc_quote_from_doors),
                # which leave unitPrice untouched so BC resolves it natively
                # (Customer → Customer Price Group → All Customers → Item card).
                # Editing a quote must not silently re-price it off BC's prices.
                if patch_data:
                    etag = added_line.get("@odata.etag", "*")
                    try:
                        bc_client.update_quote_line(bc_quote_id, added_line["id"], etag, patch_data)
                    except Exception as patch_err:
                        logger.error(f"PATCH FAILED [{line['part_number']}]: {patch_err}")
        except Exception as line_error:
            part_id = line.get("part_number", line.get("description", "unknown"))
            logger.warning(f"Failed to add line {part_id} during edit: {line_error}")
            if line.get("lineType") != "Comment" and line.get("part_number"):
                try:
                    fb_line = bc_client.add_quote_line(bc_quote_id, {
                        "lineType": "Comment",
                        "description": f"{line['part_number']} - {line.get('description', '')} (Qty: {line['quantity']})",
                    })
                    lines_added += 1
                    di = line.get("door_index")
                    if di and fb_line and fb_line.get("id"):
                        line_map["doors"].setdefault(str(di), []).append(fb_line["id"])
                    lines_failed.append({
                        "part_number": line.get("part_number"),
                        "error": str(line_error), "fallback": "comment",
                    })
                except Exception:
                    lines_failed.append({
                        "part_number": line.get("part_number"),
                        "error": str(line_error), "fallback": "failed",
                    })

    # Equalize cone prices across whole quote
    try:
        _equalize_cone_prices(bc_quote_id)
    except Exception as cone_err:
        logger.warning(f"Could not equalize cone prices: {cone_err}")

    # ── Step 5: Fetch pricing subtotal for freight calc ─────────────────────
    pricing = None
    try:
        updated_quote = bc_client.get_sales_quote(bc_quote_id)
        subtotal = updated_quote.get("totalAmountExcludingTax", 0)
        total_with_tax = updated_quote.get("totalAmountIncludingTax", 0)
        pricing = {
            "subtotal": round(subtotal, 2),
            "tax": round(total_with_tax - subtotal, 2),
            "total": round(total_with_tax, 2),
            "currency": "CAD",
        }
    except Exception as e:
        logger.warning(f"Could not fetch pricing after edit: {e}")

    # ── Step 6: Re-add freight ──────────────────────────────────────────────
    # Skipped for home-builder accounts — install travel already covers the trip.
    freight_info = None
    if pricing and not _account_provides_install(customer_user_id, db):
        try:
            customer_province = None
            bc_cust = db.query(BCCustomer).filter(BCCustomer.bc_customer_id == bc_customer_id).first()
            if bc_cust and bc_cust.address:
                customer_province = bc_cust.address.get("province")
            freight = calculate_freight(
                product_subtotal=pricing["subtotal"],
                province=customer_province,
                delivery_type=delivery_type, db=db,
            )
            freight_info = freight
            if not freight["skip"] and freight["amount"] > 0:
                freight_config = get_freight_config(db)
                freight_item = freight_config.get("freight_item_number", "FREIGHT")
                try:
                    added_freight = bc_client.add_quote_line(bc_quote_id, {
                        "lineType": "Item", "lineObjectNumber": freight_item,
                        "description": freight["description"], "quantity": 1,
                    })
                    etag = added_freight.get("@odata.etag", "*")
                    bc_client.update_quote_line(bc_quote_id, added_freight["id"], etag, {"unitPrice": freight["amount"]})
                    if added_freight.get("id"):
                        line_map["shared"].setdefault("freight", []).append(added_freight["id"])
                    _set_output_true(bc_quote_number, added_freight, label="freight")
                except Exception as fe:
                    logger.warning(f"Could not add freight as Item: {fe}")
                    if freight_config.get("fallback_to_comment", True):
                        try:
                            added_fc = bc_client.add_quote_line(bc_quote_id, {
                                "lineType": "Comment",
                                "description": f"{freight['description']}: ${freight['amount']:.2f}",
                            })
                            if added_fc.get("id"):
                                line_map["shared"].setdefault("freight", []).append(added_fc["id"])
                        except Exception:
                            pass
        except Exception as freight_err:
            logger.warning(f"Could not add freight during edit: {freight_err}")

    # ── Step 7: Re-add install block for home builder customers ─────────────
    if customer_user_id:
        try:
            customer_user = db.query(User).filter(User.id == customer_user_id).first()
            account_type = getattr(customer_user, 'account_type', None) if customer_user else None
            if account_type == 'home_builder':
                install_town = new_doors[0].get("installTown") if new_doors else None
                install_result = install_pricing_service.calculate_total_install_price(
                    customer_id=customer_user_id,
                    doors=new_doors,
                    town=install_town,
                    db=db,
                )

                def _track_shared_during_edit(bucket: str, bc_line: Optional[Dict[str, Any]]) -> None:
                    if bc_line and bc_line.get("id"):
                        line_map["shared"].setdefault(bucket, []).append(bc_line["id"])

                _add_install_block(
                    bc_quote_id=bc_quote_id,
                    bc_quote_number=bc_quote_number,
                    install_result=install_result,
                    track_shared=_track_shared_during_edit,
                )
                logger.info(
                    f"Install regen on edit {bc_quote_number}: "
                    f"${install_result['grand_total']:.2f}"
                )
        except Exception as install_err:
            logger.warning(f"Install regen failed during edit: {install_err}")

    # Final pricing after shared lines added
    try:
        updated_quote = bc_client.get_sales_quote(bc_quote_id)
        subtotal = updated_quote.get("totalAmountExcludingTax", 0)
        total_with_tax = updated_quote.get("totalAmountIncludingTax", 0)
        pricing = {
            "subtotal": round(subtotal, 2),
            "tax": round(total_with_tax - subtotal, 2),
            "total": round(total_with_tax, 2),
            "currency": "CAD",
        }
    except Exception:
        pass

    logger.info(
        f"Edited BC quote {bc_quote_number}: "
        f"deleted={len(indices_to_delete)} door(s), "
        f"regenerated={len(indices_to_regenerate)} door(s), "
        f"lines_added={lines_added}"
    )

    return {
        "bc_quote_id": bc_quote_id,
        "bc_quote_number": bc_quote_number,
        "line_map": line_map,
        "pricing": pricing,
        "lines_added": lines_added,
        "lines_failed": lines_failed if lines_failed else None,
        "door_results": door_results,
        "freight": freight_info,
        "diff": diff,
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
    delivery_type: str = "delivery",
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

        # Mount-surface install note for the shop.
        _mount_note = _mount_surface_note(door)
        if _mount_note:
            all_lines.append({
                "lineType": "Comment",
                "description": _mount_note,
                "door_index": door_index,
            })

        # Sections + glass-pockets comment for aluminium doors
        if door.get("doorType") == "aluminium":
            from app.services.part_number_service import format_aluminum_section_comment
            all_lines.append({
                "lineType": "Comment",
                "description": format_aluminum_section_comment(
                    door.get("doorHeight", 84),
                    door.get("doorWidth", 96),
                    door.get("glassPocketsPerSection"),
                ),
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
            "glassType": door.get("glassType", "ANNEALED"),
            "glassColor": door.get("glassColor"),
            "trackRadius": door.get("trackRadius", "15"),
            "trackThickness": door.get("trackThickness", "2"),
            "trackMount": door.get("trackMount", "bracket"),
            "mountSurface": door.get("mountSurface", "wood"),
            "liftType": door.get("liftType", "standard"),
            "highLiftInches": door.get("highLiftInches"),
            "hardware": door.get("hardware", {}),
            "operator": door.get("operator"),
            "operatorAccessories": door.get("operatorAccessories", []),
            "chainHoist": door.get("chainHoist"),
            "targetCycles": door.get("targetCycles", 10000),
            "shaftType": door.get("shaftType", "auto"),
        }

        try:
            door_parts = get_parts_for_door_config(config_dict, spring_inventory=spring_inventory)
            parts_list = door_parts.get("parts_list", [])
            sorted_parts = _sort_parts_by_category(parts_list)
            part_door_type = config_dict.get("doorType", "residential")

            # For aluminum doors, use commercial pricing on everything EXCEPT
            # aluminum sections and glazing (which keep aluminium pricing)
            aluminum_panel_categories = {
                "aluminum_section", "aluminum_glazing", "aluminum_glass",
                "v130g_section", "v130g_glass",
            }

            # Track whether we've emitted window placement comment
            window_note_emitted = False

            for part in sorted_parts:
                part["door_index"] = door_index
                cat = part.get("category", "")

                if cat in aluminum_panel_categories:
                    # V130G/AL976 frames and glazing ALWAYS use aluminium pricing
                    part["door_type"] = "aluminium"
                elif part_door_type == "aluminium" and cat not in aluminum_panel_categories:
                    # Non-panel parts on aluminium doors use commercial pricing
                    part["door_type"] = "commercial"
                else:
                    part["door_type"] = part_door_type

                # Info comments → BC Comment line (not an item)
                # The "comment" category is the legacy duplicate door-header
                # note generated by part_number_service. customer_portal /
                # door_configurator already render the canonical
                # _format_door_description header; skip the duplicate.
                if part.get("category") == "comment":
                    continue
                if part.get("category") in ("spring_comment", "highlift_comment"):
                    part["lineType"] = "Comment"
                    part["is_note"] = True

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

        # Blank separator after every door — NBSP for parity with the BC
        # path (description=" " gets stripped server-side, leaving doors
        # running together with no break).
        all_lines.append({
            "lineType": "Comment",
            "description": "-",
            "category": "COMMENT",
            "door_index": door_index,
            "is_separator": True,
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

    # Calculate freight for local estimate
    freight_info = None
    try:
        freight = calculate_freight(
            product_subtotal=subtotal,
            province=None,  # No province for unlinked customers
            delivery_type=delivery_type,
            db=db,
        )
        freight_info = freight

        if not freight["skip"] and freight["amount"] > 0:
            subtotal_with_freight = round(subtotal + freight["amount"], 2)
        else:
            subtotal_with_freight = subtotal
    except Exception as freight_err:
        logger.warning(f"Could not calculate freight for local estimate: {freight_err}")
        subtotal_with_freight = subtotal

    return {
        "bc_quote_id": None,
        "bc_quote_number": None,
        "lines_added": len([l for l in all_lines if l.get("lineType") != "Comment"]),
        "lines_failed": None,
        "pricing": {
            "subtotal": subtotal_with_freight,
            "tax": 0,
            "total": subtotal_with_freight,
            "currency": "CAD",
            "is_estimate": True,
        },
        "line_pricing": line_pricing if line_pricing else None,
        "door_results": door_results,
        "freight": freight_info,
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
        SavedQuoteConfig.user_id.in_(_company_user_ids(current_user, db)),
    ).first()

    if not config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Saved configuration not found"
        )

    if _has_sales_order_for_quote(config, db):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot re-price a quote that has been converted to an order."
        )

    try:
        doors = _validate_doors_config(config.config_data or {})

        if current_user.bc_customer_id:
            # Linked customer: create a real BC quote for accurate pricing (incl. tax)
            pricing_tier = _get_customer_pricing_tier(current_user.bc_customer_id, db)
            delivery_type = (config.config_data or {}).get("deliveryType", "delivery")

            if config.bc_quote_id:
                # Existing BC quote: edit in place so the same quote number
                # stays in BC across re-prices. Only the lines that changed
                # are touched, via the bc_line_map / surgical edit path.
                # Without this, every "Build Quote" click would create a
                # duplicate BC quote and orphan the previous one.
                logger.info(
                    f"Re-pricing existing BC quote {config.bc_quote_number} "
                    f"for config {config_id} via surgical edit"
                )
                result = _edit_bc_quote_lines(
                    config=config,
                    new_config_data=config.config_data or {},
                    bc_customer_id=current_user.bc_customer_id,
                    pricing_tier=pricing_tier,
                    db=db,
                    customer_user_id=current_user.id,
                    delivery_type=delivery_type,
                )
            else:
                # First-time pricing: create the BC quote.
                result = _generate_bc_quote_with_items(
                    doors=doors,
                    bc_customer_id=current_user.bc_customer_id,
                    config_id=config.id,
                    pricing_tier=pricing_tier,
                    db=db,
                    po_number=(config.config_data or {}).get("poNumber"),
                    delivery_type=delivery_type,
                    customer_user_id=current_user.id,
                )

            # Store BC quote reference (but NOT submitted)
            config.bc_quote_id = result["bc_quote_id"]
            config.bc_quote_number = result["bc_quote_number"]
            config.bc_line_map = result.get("line_map")
        else:
            # Unlinked customer: estimate locally at retail, no BC quote created
            pricing_tier = "retail"
            delivery_type = (config.config_data or {}).get("deliveryType", "delivery")
            result = _estimate_pricing_locally(
                doors=doors,
                pricing_tier=pricing_tier,
                config_id=config.id,
                db=db,
                delivery_type=delivery_type,
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
            "lines_added": result.get("lines_added"),
            "lines_failed": result.get("lines_failed"),
            "pricing": result.get("pricing"),
            "line_pricing": result.get("line_pricing"),
            "door_results": result.get("door_results"),
            "freight": result.get("freight"),
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
        SavedQuoteConfig.user_id.in_(_company_user_ids(current_user, db)),
    ).first()

    if not config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Saved configuration not found"
        )

    if _has_sales_order_for_quote(config, db):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot confirm a quote that has already been converted to an order."
        )

    if not config.bc_quote_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Pricing has not been generated yet. Please get pricing first."
        )

    # Confirm is idempotent — safe to re-confirm after an edit (the customer may
    # edit and re-confirm multiple times until they place the order).
    if not config.is_submitted:
        config.is_submitted = True
        config.submitted_at = datetime.utcnow()
        db.commit()
        db.refresh(config)

    logger.info(f"Quote confirmed: config {config_id}, BC Quote {config.bc_quote_number}")

    return _config_to_response(config, db)


@router.post("/saved-quotes/{config_id}/refresh-pricing")
def refresh_pricing_for_saved_quote(
    config_id: int,
    current_user: User = Depends(get_current_customer),
    db: Session = Depends(get_db)
):
    """
    Refresh pricing for a saved quote after config changes.

    Edits the existing BC quote in place if one exists (preserving the
    same quote number across re-prices), or creates a new one if this
    is the first time pricing is requested.
    """
    config = db.query(SavedQuoteConfig).filter(
        SavedQuoteConfig.id == config_id,
        SavedQuoteConfig.user_id.in_(_company_user_ids(current_user, db)),
    ).first()

    if not config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Saved configuration not found"
        )

    if _has_sales_order_for_quote(config, db):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot refresh pricing on a quote that has been converted to an order."
        )

    try:
        doors = _validate_doors_config(config.config_data or {})

        if current_user.bc_customer_id:
            # Linked customer: edit existing BC quote in place if one
            # already exists, otherwise create a new one. Same logic as
            # /get-pricing — never delete + recreate when an unsubmitted
            # BC quote is sitting there, that just orphans it.
            pricing_tier = _get_customer_pricing_tier(current_user.bc_customer_id, db)
            delivery_type = (config.config_data or {}).get("deliveryType", "delivery")

            if config.bc_quote_id:
                logger.info(
                    f"Refreshing pricing on existing BC quote "
                    f"{config.bc_quote_number} for config {config_id} via surgical edit"
                )
                result = _edit_bc_quote_lines(
                    config=config,
                    new_config_data=config.config_data or {},
                    bc_customer_id=current_user.bc_customer_id,
                    pricing_tier=pricing_tier,
                    db=db,
                    customer_user_id=current_user.id,
                    delivery_type=delivery_type,
                )
            else:
                result = _generate_bc_quote_with_items(
                    doors=doors,
                    bc_customer_id=current_user.bc_customer_id,
                    config_id=config.id,
                    pricing_tier=pricing_tier,
                    db=db,
                    po_number=(config.config_data or {}).get("poNumber"),
                    delivery_type=delivery_type,
                    customer_user_id=current_user.id,
                )

            config.bc_quote_id = result["bc_quote_id"]
            config.bc_quote_number = result["bc_quote_number"]
            config.bc_line_map = result.get("line_map")
        else:
            # Unlinked customer: recalculate local estimate at retail
            pricing_tier = "retail"
            delivery_type = (config.config_data or {}).get("deliveryType", "delivery")
            result = _estimate_pricing_locally(
                doors=doors,
                pricing_tier=pricing_tier,
                config_id=config.id,
                db=db,
                delivery_type=delivery_type,
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
            "lines_added": result.get("lines_added"),
            "lines_failed": result.get("lines_failed"),
            "pricing": result.get("pricing"),
            "line_pricing": result.get("line_pricing"),
            "door_results": result.get("door_results"),
            "freight": result.get("freight"),
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
        SavedQuoteConfig.user_id.in_(_company_user_ids(current_user, db)),
    ).first()

    if not config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Saved configuration not found"
        )

    if _has_sales_order_for_quote(config, db):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot submit a quote that has been converted to an order."
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
                customer_user_id=current_user.id,
            )

            config.bc_quote_id = result["bc_quote_id"]
            config.bc_quote_number = result["bc_quote_number"]
            config.bc_line_map = result.get("line_map")

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

    return _config_to_response(config, db)


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
        SavedQuoteConfig.user_id.in_(_company_user_ids(current_user, db)),
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
            config.bc_line_map = None
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
# SHOP DRAWINGS (Stage 1: framing drawing pipeline)
# ============================================================================

@router.post("/saved-quotes/{config_id}/framing-drawing")
def generate_framing_drawing_endpoint(
    config_id: int,
    fmt: str = "pdf",
    door_index: int = 0,
    current_user: User = Depends(get_current_customer),
    db: Session = Depends(get_db),
):
    """Generate a framing shop drawing for a saved quote.

    Stage 1 returns a formatted sheet with title block and a placeholder
    viewport — actual door geometry lands in Stage 2.

    Query params:
      fmt: "pdf" (default) or "dxf"
      door_index: which door in the config to draw (0-based; default 0)
    """
    from app.services.shop_drawings import generate_framing_drawing

    fmt = (fmt or "pdf").lower()
    if fmt not in ("pdf", "dxf"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="fmt must be 'pdf' or 'dxf'",
        )

    config = db.query(SavedQuoteConfig).filter(
        SavedQuoteConfig.id == config_id,
        SavedQuoteConfig.user_id.in_(_company_user_ids(current_user, db)),
    ).first()
    if not config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Saved configuration not found",
        )

    try:
        content = generate_framing_drawing(
            config_data=config.config_data or {},
            customer_name=current_user.name or current_user.email,
            job_number=config.bc_quote_number or f"Q-{config.id}",
            fmt=fmt,
            drawing_date=config.updated_at or config.created_at,
            config_id=config.id,
            door_index=door_index,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    media_type = "application/pdf" if fmt == "pdf" else "application/dxf"
    filename = f"framing-{config.bc_quote_number or config.id}.{fmt}"
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
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


# ============================================================================
# PARTS CATALOG (Customer Browse - Read Only)
# ============================================================================

def _is_catalog_visible(db: Session) -> bool:
    """Check if catalog is enabled for customers."""
    setting = db.query(AppSettings).filter(
        AppSettings.setting_key == "catalog_visible_to_customers"
    ).first()
    if not setting:
        return False  # Hidden by default until admin enables
    return setting.setting_value is True or setting.setting_value == "true"


@router.get("/catalog")
def browse_catalog(
    category: Optional[str] = None,
    search: Optional[str] = None,
    skip: int = 0,
    limit: int = 50,
    current_user: User = Depends(get_current_customer),
    db: Session = Depends(get_db),
):
    """Browse parts catalog (active items only, with tier pricing)."""
    if not _is_catalog_visible(db):
        return {"items": [], "count": 0, "pricing_tier": None, "catalog_hidden": True}
    q = db.query(Part).filter(Part.catalog_status == "active")
    if category:
        q = q.filter(Part.category == category)
    if search:
        q = q.filter(
            (Part.bc_item_number.ilike(f"%{search}%")) |
            (Part.bc_description.ilike(f"%{search}%"))
        )
    parts = q.order_by(Part.bc_item_number).offset(skip).limit(limit).all()

    # Get customer pricing tier
    tier = _get_customer_pricing_tier(current_user.bc_customer_id, db)

    return {
        "items": [
            {
                "id": p.id,
                "item_number": p.bc_item_number,
                "description": p.bc_description,
                "category": p.category,
                "subcategory": p.subcategory,
                "attributes": p.attributes,
                "retail_price": float(p.retail_price) if p.retail_price else None,
                "lead_time_days": p.lead_time_days,
            }
            for p in parts
        ],
        "count": len(parts),
        "pricing_tier": tier,
    }


@router.get("/catalog/search")
def search_catalog(
    q: str,
    category: Optional[str] = None,
    skip: int = 0,
    limit: int = 50,
    current_user: User = Depends(get_current_customer),
    db: Session = Depends(get_db),
):
    """Keyword search in parts catalog."""
    if not _is_catalog_visible(db):
        return {"items": [], "count": 0, "catalog_hidden": True}
    query = db.query(Part).filter(
        Part.catalog_status == "active",
        (Part.bc_item_number.ilike(f"%{q}%")) |
        (Part.bc_description.ilike(f"%{q}%"))
    )
    if category:
        query = query.filter(Part.category == category)
    parts = query.order_by(Part.bc_item_number).offset(skip).limit(limit).all()

    return {
        "items": [
            {
                "id": p.id,
                "item_number": p.bc_item_number,
                "description": p.bc_description,
                "category": p.category,
                "subcategory": p.subcategory,
                "attributes": p.attributes,
                "retail_price": float(p.retail_price) if p.retail_price else None,
            }
            for p in parts
        ],
        "count": len(parts),
    }


# ============================================================================
# SPRING BUILDER (Customer Portal)
# ============================================================================

class SpringBuilderRequest(BaseModel):
    door_weight: float
    door_height: int
    door_width: Optional[float] = None
    track_radius: int = 15
    spring_qty: int = 2
    target_cycles: int = 10000
    coil_diameter: float = 2.0
    drum_model: str
    high_lift_inches: int = 0
    lift_type: str = "standard_15"   # standard_12, standard_15, high_lift, vertical, low_headroom
    assembly: str = "standard"        # standard, single


class SpringLookupRequest(BaseModel):
    wire_diameter: float
    coil_diameter: float
    spring_length: Optional[float] = None


class SpringConversionRequest(BaseModel):
    current_wire: float
    current_coil: float
    current_length: float
    current_spring_qty: int = 1
    replacement_spring_qty: int = 1
    replacement_coil: Optional[float] = None
    replacement_wire: Optional[float] = None


class SpecialOrderSubmit(BaseModel):
    wire_diameter: float
    coil_diameter: float
    spring_length: float
    wind_direction: str
    quantity: int = 1
    spring_type: str = "SP11"
    door_width: Optional[float] = None
    door_height: Optional[float] = None
    door_weight: Optional[float] = None
    calculation_data: Optional[dict] = None


@router.post("/spring-builder/calculate")
def spring_builder_calculate(
    body: SpringBuilderRequest,
    current_user: User = Depends(get_current_customer),
    db: Session = Depends(get_db),
):
    """Calculate spring specs and match to catalog SKUs."""
    from app.services.spring_builder_service import spring_builder_service

    # Derive track_radius and high_lift_inches from lift_type
    lift_type = body.lift_type
    track_radius = body.track_radius
    high_lift_inches = body.high_lift_inches
    drum_model = body.drum_model

    if lift_type == "standard_12":
        track_radius = 12
        high_lift_inches = 0
    elif lift_type == "standard_15":
        track_radius = 15
        high_lift_inches = 0
    elif lift_type == "high_lift":
        track_radius = 15
        # high_lift_inches comes from body
    elif lift_type == "vertical":
        track_radius = 15
        high_lift_inches = 0
    elif lift_type == "low_headroom":
        track_radius = 12
        high_lift_inches = 0

    # Map assembly to spring_qty (body.spring_qty still overrides if not default)
    spring_qty = body.spring_qty
    if body.assembly == "single" and body.spring_qty == 2:
        spring_qty = 1

    result = spring_builder_service.calculate_and_match(
        db=db,
        door_weight=body.door_weight,
        door_height=body.door_height,
        door_width=body.door_width,
        track_radius=track_radius,
        spring_qty=spring_qty,
        target_cycles=body.target_cycles,
        coil_diameter=body.coil_diameter,
        drum_model=drum_model,
        high_lift_inches=high_lift_inches,
        lift_type=lift_type,
    )
    return result


@router.get("/spring-builder/drums")
def get_available_drums(
    lift_type: str = "standard",
    current_user: User = Depends(get_current_customer),
):
    """Return available drum models for a given lift type."""
    from app.services.spring_builder_service import spring_builder_service

    return spring_builder_service.get_drum_list(lift_type)


@router.post("/spring-builder/convert")
def spring_builder_convert(
    body: SpringConversionRequest,
    current_user: User = Depends(get_current_customer),
    db: Session = Depends(get_db),
):
    """Convert current spring specs to replacement spring specs."""
    from app.services.spring_builder_service import spring_builder_service

    return spring_builder_service.convert_spring(
        db=db,
        current_wire=body.current_wire,
        current_coil=body.current_coil,
        current_length=body.current_length,
        current_spring_qty=body.current_spring_qty,
        replacement_spring_qty=body.replacement_spring_qty,
        replacement_coil=body.replacement_coil,
        replacement_wire=body.replacement_wire,
    )


@router.post("/spring-builder/lookup")
def spring_builder_lookup(
    body: SpringLookupRequest,
    current_user: User = Depends(get_current_customer),
    db: Session = Depends(get_db),
):
    """Look up a spring by direct specs (wire, coil diameter) and match to catalog."""
    from app.services.spring_builder_service import spring_builder_service

    return spring_builder_service.lookup_by_specs(
        db=db,
        wire_diameter=body.wire_diameter,
        coil_diameter=body.coil_diameter,
        spring_length=body.spring_length,
    )


@router.post("/spring-builder/special-order")
def submit_special_order(
    body: SpecialOrderSubmit,
    current_user: User = Depends(get_current_customer),
    db: Session = Depends(get_db),
):
    """Submit a special order for a spring that can't be fulfilled from catalog."""
    from app.services.spring_builder_service import spring_builder_service

    order = spring_builder_service.submit_special_order(
        db=db,
        user=current_user,
        wire_diameter=body.wire_diameter,
        coil_diameter=body.coil_diameter,
        spring_length=body.spring_length,
        wind_direction=body.wind_direction,
        quantity=body.quantity,
        spring_type=body.spring_type,
        door_width=body.door_width,
        door_height=body.door_height,
        door_weight=body.door_weight,
        calculation_data=body.calculation_data,
    )
    db.commit()
    return {
        "success": True,
        "order_id": order.id,
        "status": order.status,
    }


@router.get("/special-orders")
def list_special_orders(
    skip: int = 0,
    limit: int = 50,
    current_user: User = Depends(get_current_customer),
    db: Session = Depends(get_db),
):
    """List customer's special orders."""
    from app.services.spring_builder_service import spring_builder_service

    orders = spring_builder_service.get_customer_special_orders(
        db, current_user.id, skip=skip, limit=limit
    )
    return {
        "items": [
            {
                "id": o.id,
                "wire_diameter": o.wire_diameter,
                "coil_diameter": o.coil_diameter,
                "spring_length": o.spring_length,
                "wind_direction": o.wind_direction,
                "quantity": o.quantity,
                "status": o.status,
                "quoted_price": float(o.quoted_price) if o.quoted_price else None,
                "quoted_lead_time_days": o.quoted_lead_time_days,
                "admin_notes": o.admin_notes,
                "created_at": o.created_at.isoformat() if o.created_at else None,
            }
            for o in orders
        ],
        "count": len(orders),
    }


# ============================================================================
# PARTS CART ENDPOINTS
# ============================================================================

class CartItem(BaseModel):
    item_number: str
    description: Optional[str] = None
    quantity: int = 1

class CartQuoteRequest(BaseModel):
    items: List[CartItem]

class CartPlaceOrderRequest(BaseModel):
    bc_quote_id: str


@router.post("/cart/quote")
def create_cart_quote(
    body: CartQuoteRequest,
    current_user: User = Depends(get_current_customer),
    db: Session = Depends(get_db),
):
    """
    Create a BC sales quote from parts cart items.
    Applies customer's pricing tier to each line.
    """
    if not current_user.bc_customer_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Your account is not linked to a Business Central customer."
        )

    if not body.items:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cart is empty."
        )

    try:
        pricing_tier = _get_customer_pricing_tier(current_user.bc_customer_id, db)

        # Warm BC cost cache for all part numbers
        part_numbers = [item.item_number for item in body.items]
        warm_bc_cost_cache(part_numbers)

        # Create BC quote
        quote_data = {
            "customerId": current_user.bc_customer_id,
            "externalDocumentNumber": f"CART-{current_user.id}",
        }
        bc_quote = bc_client.create_sales_quote(quote_data)
        if not bc_quote:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to create quote in Business Central"
            )

        bc_quote_id = bc_quote.get("id")
        bc_quote_number = bc_quote.get("number")
        logger.info(f"Created cart BC quote: {bc_quote_number} (ID: {bc_quote_id})")

        # Add line items
        line_pricing = []
        lines_failed = []

        for item in body.items:
            try:
                line_data = {
                    "lineType": "Item",
                    "lineObjectNumber": item.item_number,
                    "description": item.description or "",
                    "quantity": item.quantity,
                }
                added_line = bc_client.add_quote_line(bc_quote_id, line_data)

                # Trust BC SalesPriceLists for the price — do NOT override with
                # the legacy margin engine. BC resolves the unit price on POST
                # (Customer → Price Group → All Customers → Item card).
                unit_price = added_line.get("unitPrice", 0)
                line_pricing.append({
                    "item_number": item.item_number,
                    "description": added_line.get("description", item.description or ""),
                    "quantity": item.quantity,
                    "unit_price": unit_price,
                    "line_total": round(unit_price * item.quantity, 2),
                })

            except Exception as line_err:
                logger.warning(f"Cart: failed to add line {item.item_number}: {line_err}")
                # Fall back to Comment line
                try:
                    comment_data = {
                        "lineType": "Comment",
                        "description": f"{item.item_number} - {item.description or 'N/A'} (x{item.quantity}) [item not found]",
                    }
                    bc_client.add_quote_line(bc_quote_id, comment_data)
                except Exception:
                    pass
                lines_failed.append(item.item_number)

        # Fetch final quote totals from BC
        final_quote = bc_client.get_sales_quote(bc_quote_id)
        subtotal = final_quote.get("totalAmountExcludingTax", 0)
        total = final_quote.get("totalAmountIncludingTax", 0)
        tax = round(total - subtotal, 2) if total and subtotal else 0

        return {
            "bc_quote_id": bc_quote_id,
            "bc_quote_number": bc_quote_number,
            "pricing": {
                "subtotal": subtotal,
                "tax": tax,
                "total": total,
            },
            "line_pricing": line_pricing,
            "lines_failed": lines_failed,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating cart quote: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create quote: {str(e)}"
        )


@router.post("/cart/place-order")
def place_order_from_cart(
    body: CartPlaceOrderRequest,
    current_user: User = Depends(get_current_customer),
    db: Session = Depends(get_db),
):
    """
    Convert a cart BC quote to a sales order.
    """
    if not current_user.bc_customer_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Your account is not linked to a Business Central customer."
        )

    if not body.bc_quote_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No quote ID provided."
        )

    try:
        # Verify quote exists and belongs to customer
        quote = bc_client.get_sales_quote(body.bc_quote_id)
        if not quote:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Quote not found"
            )
        if quote.get("customerId") != current_user.bc_customer_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="This quote does not belong to your account."
            )

        bc_quote_number = quote.get("number")

        # Check for existing order
        existing_order = db.query(SalesOrder).filter(
            SalesOrder.bc_quote_number == bc_quote_number
        ).first()
        if existing_order:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"An order already exists for this quote (Order #{existing_order.bc_order_number})"
            )

        # Convert quote to order
        bc_order = bc_client.convert_quote_to_order(body.bc_quote_id)

        bc_order_id = bc_order.get("id")
        bc_order_number = bc_order.get("number")
        total_amount = bc_order.get("totalAmountIncludingTax", 0)

        # Parse delivery date
        bc_delivery_date = None
        raw_delivery = bc_order.get("requestedDeliveryDate")
        if raw_delivery and raw_delivery != "0001-01-01":
            try:
                bc_delivery_date = datetime.strptime(raw_delivery[:10], "%Y-%m-%d")
            except (ValueError, TypeError):
                pass

        # Create local SalesOrder record
        sales_order = SalesOrder(
            quote_request_id=None,
            bc_order_id=bc_order_id,
            bc_order_number=bc_order_number,
            bc_quote_number=bc_quote_number,
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
        db.commit()
        db.refresh(sales_order)

        logger.info(
            f"Cart order placed: BC Order {bc_order_number}, Amount: {total_amount}"
        )

        return {
            "success": True,
            "order_id": sales_order.id,
            "bc_order_number": bc_order_number,
            "total_amount": float(total_amount) if total_amount else None,
        }

    except HTTPException:
        raise
    except Exception as e:
        error_msg = str(e)
        logger.error(f"Error placing cart order: {error_msg}", exc_info=True)

        if "404" in error_msg or "not found" in error_msg.lower():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Quote not found in Business Central. It may have expired or been deleted."
            )

        if "DialogException" in error_msg or "50005" in error_msg:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="This quote cannot be converted to an order. It may have already been converted."
            )

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to place order: {error_msg}"
        )
