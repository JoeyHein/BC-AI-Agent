"""
Settings API Router
Manages application settings including spring inventory
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import Dict, List, Any, Optional
from pydantic import BaseModel
from datetime import datetime
import logging

from app.db.database import get_db
from app.db.models import AppSettings
from app.services.spring_data_service import get_spring_data_service
from app.services.pricing_service import (
    get_default_tier_margins,
    get_default_cost_adjustments,
    TIER_MARGINS_KEY,
    COST_ADJUSTMENTS_KEY,
    POSTING_GROUP_LABELS,
)
from app.services.bc_part_number_mapper import get_bc_mapper

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/settings", tags=["settings"])


# ============================================================================
# Pydantic Models
# ============================================================================

class SettingUpdate(BaseModel):
    """Request model for updating a setting"""
    value: Any
    description: Optional[str] = None


class SpringInventoryUpdate(BaseModel):
    """Request model for updating spring inventory settings"""
    inventory: Dict[str, List[str]]  # { "2.0": ["0.1920", "0.2070"], ... }


class SettingResponse(BaseModel):
    """Response model for a setting"""
    setting_key: str
    setting_value: Any
    description: Optional[str]
    updated_at: Optional[datetime]


class TierMarginsUpdate(BaseModel):
    """Request model for updating tier margins"""
    margins: Dict[str, Dict[str, float]]  # { "residential": { "gold": 30, ... }, "commercial": { ... } }


class CostAdjustmentsUpdate(BaseModel):
    """Request model for updating cost adjustments"""
    adjustments: Dict[str, Any]  # { "RESI": { "adjustment": 5, "note": "..." }, ... }


# ============================================================================
# Constants
# ============================================================================

SPRING_INVENTORY_KEY = "spring_inventory"

# Default spring inventory (empty - all disabled by default)
DEFAULT_SPRING_INVENTORY = {
    "2.0": [],
    "2.625": [],
    "3.75": [],
    "6.0": [],
}


# ============================================================================
# Spring Inventory Endpoints (MUST be defined BEFORE generic /{setting_key})
# ============================================================================

@router.get("/spring-inventory/available-sizes")
async def get_available_spring_sizes():
    """Get all available wire sizes by coil diameter from spring data files"""
    spring_service = get_spring_data_service()

    coils = spring_service.get_available_coils()
    all_sizes = spring_service.get_all_wire_sizes()

    return {
        "success": True,
        "data": {
            "coils": coils,
            "wireSizes": all_sizes
        }
    }


@router.get("/spring-inventory/coils")
async def get_available_coils():
    """Get list of available coil diameters"""
    spring_service = get_spring_data_service()
    coils = spring_service.get_available_coils()

    return {
        "success": True,
        "data": coils
    }


@router.get("/spring-inventory/coils/{coil_id}/wire-sizes")
async def get_wire_sizes_for_coil(coil_id: str):
    """Get wire sizes for a specific coil diameter"""
    spring_service = get_spring_data_service()
    wire_sizes = spring_service.get_wire_sizes_for_coil(coil_id)

    if not wire_sizes:
        raise HTTPException(status_code=404, detail=f"Coil diameter '{coil_id}' not found")

    return {
        "success": True,
        "data": wire_sizes
    }


@router.get("/spring-inventory/current")
async def get_spring_inventory(db: Session = Depends(get_db)):
    """Get current spring inventory settings"""
    setting = db.query(AppSettings).filter(
        AppSettings.setting_key == SPRING_INVENTORY_KEY
    ).first()

    if not setting:
        # Return default empty inventory
        return {
            "success": True,
            "data": {
                "inventory": DEFAULT_SPRING_INVENTORY,
                "isDefault": True
            }
        }

    return {
        "success": True,
        "data": {
            "inventory": setting.setting_value,
            "isDefault": False,
            "updatedAt": setting.updated_at.isoformat() if setting.updated_at else None
        }
    }


@router.put("/spring-inventory")
async def update_spring_inventory(
    update: SpringInventoryUpdate,
    db: Session = Depends(get_db)
):
    """Update spring inventory settings"""
    # Validate the inventory structure
    spring_service = get_spring_data_service()
    available_coils = {coil["id"] for coil in spring_service.get_available_coils()}

    for coil_id, wire_sizes in update.inventory.items():
        if coil_id not in available_coils:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid coil diameter: {coil_id}"
            )

        # Validate wire sizes exist for this coil
        available_wires = {
            w["diameterFormatted"]
            for w in spring_service.get_wire_sizes_for_coil(coil_id)
        }

        for wire_size in wire_sizes:
            if wire_size not in available_wires:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid wire size '{wire_size}' for coil '{coil_id}'"
                )

    # Update or create the setting
    setting = db.query(AppSettings).filter(
        AppSettings.setting_key == SPRING_INVENTORY_KEY
    ).first()

    if setting:
        setting.setting_value = update.inventory
        setting.updated_at = datetime.utcnow()
    else:
        setting = AppSettings(
            setting_key=SPRING_INVENTORY_KEY,
            setting_value=update.inventory,
            description="Spring wire sizes stocked per coil diameter",
            updated_at=datetime.utcnow()
        )
        db.add(setting)

    db.commit()
    db.refresh(setting)

    # Count total selected wire sizes
    total_selected = sum(len(sizes) for sizes in update.inventory.values())

    logger.info(f"Spring inventory updated: {total_selected} wire sizes selected")

    return {
        "success": True,
        "message": f"Spring inventory updated successfully ({total_selected} wire sizes selected)",
        "data": {
            "inventory": setting.setting_value,
            "updatedAt": setting.updated_at.isoformat() if setting.updated_at else None,
            "totalSelected": total_selected
        }
    }


@router.get("/spring-inventory/summary")
async def get_spring_inventory_summary(db: Session = Depends(get_db)):
    """Get a summary of the spring inventory settings"""
    setting = db.query(AppSettings).filter(
        AppSettings.setting_key == SPRING_INVENTORY_KEY
    ).first()

    spring_service = get_spring_data_service()
    coils = spring_service.get_available_coils()

    inventory = setting.setting_value if setting else DEFAULT_SPRING_INVENTORY

    summary = []
    for coil in coils:
        coil_id = coil["id"]
        selected = inventory.get(coil_id, [])
        available = spring_service.get_wire_sizes_for_coil(coil_id)

        summary.append({
            "coilId": coil_id,
            "coilName": coil["name"],
            "displayName": coil["displayName"],
            "selectedCount": len(selected),
            "availableCount": len(available),
            "selectedSizes": selected
        })

    return {
        "success": True,
        "data": {
            "summary": summary,
            "totalSelected": sum(len(inventory.get(c["id"], [])) for c in coils),
            "totalAvailable": sum(len(spring_service.get_wire_sizes_for_coil(c["id"])) for c in coils)
        }
    }


# ============================================================================
# Pricing Tier & Cost Adjustment Endpoints
# ============================================================================

@router.get("/pricing-tiers/current")
async def get_pricing_tiers(db: Session = Depends(get_db)):
    """Get current pricing tier margins (or defaults if not yet saved)"""
    setting = db.query(AppSettings).filter(
        AppSettings.setting_key == TIER_MARGINS_KEY
    ).first()

    if not setting:
        return {
            "success": True,
            "data": {
                "margins": get_default_tier_margins(),
                "isDefault": True,
            }
        }

    return {
        "success": True,
        "data": {
            "margins": setting.setting_value,
            "isDefault": False,
            "updatedAt": setting.updated_at.isoformat() if setting.updated_at else None,
        }
    }


@router.put("/pricing-tiers")
async def update_pricing_tiers(
    update: TierMarginsUpdate,
    db: Session = Depends(get_db),
):
    """Validate and save tier margin percentages"""
    # Validate all margins are 0-99%
    for door_type, tiers in update.margins.items():
        if door_type not in ("residential", "commercial"):
            raise HTTPException(status_code=400, detail=f"Invalid door type: {door_type}")
        for tier_name, margin in tiers.items():
            if not (0 <= margin <= 99):
                raise HTTPException(
                    status_code=400,
                    detail=f"Margin for {door_type}/{tier_name} must be between 0% and 99% (got {margin}%)"
                )

    setting = db.query(AppSettings).filter(
        AppSettings.setting_key == TIER_MARGINS_KEY
    ).first()

    if setting:
        setting.setting_value = update.margins
        setting.updated_at = datetime.utcnow()
    else:
        setting = AppSettings(
            setting_key=TIER_MARGINS_KEY,
            setting_value=update.margins,
            description="Pricing tier margin percentages by door type",
            updated_at=datetime.utcnow(),
        )
        db.add(setting)

    db.commit()
    db.refresh(setting)
    logger.info("Pricing tier margins updated")

    return {
        "success": True,
        "message": "Pricing tier margins updated successfully",
        "data": {
            "margins": setting.setting_value,
            "updatedAt": setting.updated_at.isoformat() if setting.updated_at else None,
        }
    }


@router.get("/pricing-cost-adjustments/current")
async def get_pricing_cost_adjustments(db: Session = Depends(get_db)):
    """Get current cost adjustments per category (or defaults if not yet saved)"""
    setting = db.query(AppSettings).filter(
        AppSettings.setting_key == COST_ADJUSTMENTS_KEY
    ).first()

    if not setting:
        return {
            "success": True,
            "data": {
                "adjustments": get_default_cost_adjustments(),
                "isDefault": True,
            }
        }

    return {
        "success": True,
        "data": {
            "adjustments": setting.setting_value,
            "isDefault": False,
            "updatedAt": setting.updated_at.isoformat() if setting.updated_at else None,
        }
    }


@router.put("/pricing-cost-adjustments")
async def update_pricing_cost_adjustments(
    update: CostAdjustmentsUpdate,
    db: Session = Depends(get_db),
):
    """Validate and save cost adjustment percentages per category"""
    for code, entry in update.adjustments.items():
        adj = entry.get("adjustment", 0) if isinstance(entry, dict) else 0
        if not (-50 <= adj <= 100):
            raise HTTPException(
                status_code=400,
                detail=f"Cost adjustment for {code} must be between -50% and +100% (got {adj}%)"
            )

    setting = db.query(AppSettings).filter(
        AppSettings.setting_key == COST_ADJUSTMENTS_KEY
    ).first()

    if setting:
        setting.setting_value = update.adjustments
        setting.updated_at = datetime.utcnow()
    else:
        setting = AppSettings(
            setting_key=COST_ADJUSTMENTS_KEY,
            setting_value=update.adjustments,
            description="Cost adjustment percentages by BC posting group code",
            updated_at=datetime.utcnow(),
        )
        db.add(setting)

    db.commit()
    db.refresh(setting)
    logger.info("Pricing cost adjustments updated")

    return {
        "success": True,
        "message": "Cost adjustments updated successfully",
        "data": {
            "adjustments": setting.setting_value,
            "updatedAt": setting.updated_at.isoformat() if setting.updated_at else None,
        }
    }


@router.get("/pricing-categories")
async def get_pricing_categories():
    """Get distinct generalProductPostingGroupCode values from bc_items cache with labels"""
    mapper = get_bc_mapper()
    groups = set()
    for item in mapper.bc_items.values():
        code = item.get("generalProductPostingGroupCode", "")
        if code:
            groups.add(code)

    categories = []
    for code in sorted(groups):
        categories.append({
            "code": code,
            "label": POSTING_GROUP_LABELS.get(code, code),
        })

    return {
        "success": True,
        "data": categories,
    }


# ============================================================================
# Generic Settings Endpoints (MUST be defined AFTER specific routes)
# ============================================================================

@router.get("/{setting_key}")
async def get_setting(setting_key: str, db: Session = Depends(get_db)):
    """Get a specific setting by key"""
    setting = db.query(AppSettings).filter(
        AppSettings.setting_key == setting_key
    ).first()

    if not setting:
        raise HTTPException(status_code=404, detail=f"Setting '{setting_key}' not found")

    return {
        "success": True,
        "data": setting.to_dict()
    }


@router.put("/{setting_key}")
async def update_setting(
    setting_key: str,
    update: SettingUpdate,
    db: Session = Depends(get_db)
):
    """Update a setting value"""
    setting = db.query(AppSettings).filter(
        AppSettings.setting_key == setting_key
    ).first()

    if setting:
        # Update existing setting
        setting.setting_value = update.value
        if update.description:
            setting.description = update.description
        setting.updated_at = datetime.utcnow()
    else:
        # Create new setting
        setting = AppSettings(
            setting_key=setting_key,
            setting_value=update.value,
            description=update.description,
            updated_at=datetime.utcnow()
        )
        db.add(setting)

    db.commit()
    db.refresh(setting)

    return {
        "success": True,
        "message": f"Setting '{setting_key}' updated successfully",
        "data": setting.to_dict()
    }
