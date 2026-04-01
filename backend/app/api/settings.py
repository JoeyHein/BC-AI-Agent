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
    BC_GROUP_MAPPING_KEY,
    PREFIX_MARGINS_KEY,
    VALID_TIERS,
    POSTING_GROUP_LABELS,
)
from app.services.bc_part_number_mapper import get_bc_mapper
from app.services.freight_service import (
    FREIGHT_CONFIG_KEY,
    get_default_freight_config,
    get_freight_config,
)

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


class BCGroupMappingUpdate(BaseModel):
    """Request model for updating BC price group → portal tier mapping"""
    mapping: Dict[str, str]  # { "RETAIL": "retail", "CONTRACTOR": "gold", ... }


class FreightConfigUpdate(BaseModel):
    """Request model for updating freight configuration"""
    config: Dict[str, Any]  # { "default_rate": 5.0, "province_overrides": { "SK": 7.0, ... }, ... }


class PrefixMarginsUpdate(BaseModel):
    """Request model for updating part-number prefix margin overrides"""
    overrides: Dict[str, Any]  # { "GK17": { "margin": 60, "note": "Aluminum glazing" }, ... }


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

    # Merge saved margins with defaults so new categories (e.g. glazing) always appear
    defaults = get_default_tier_margins()
    merged = dict(defaults)
    if setting.setting_value:
        merged.update(setting.setting_value)

    return {
        "success": True,
        "data": {
            "margins": merged,
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
        if door_type not in ("residential", "commercial", "aluminium", "glazing"):
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
# Part-Number Prefix Margin Override Endpoints
# ============================================================================

@router.get("/pricing-prefix-margins/current")
async def get_prefix_margins(db: Session = Depends(get_db)):
    """Get current part-number prefix margin overrides (or empty dict if none saved)."""
    setting = db.query(AppSettings).filter(
        AppSettings.setting_key == PREFIX_MARGINS_KEY
    ).first()

    overrides = setting.setting_value if setting else {}

    return {
        "success": True,
        "data": {
            "overrides": overrides,
            "isDefault": not bool(setting),
            "updatedAt": setting.updated_at.isoformat() if setting and setting.updated_at else None,
        }
    }


@router.put("/pricing-prefix-margins")
async def update_prefix_margins(
    update: PrefixMarginsUpdate,
    db: Session = Depends(get_db),
):
    """Validate and save part-number prefix margin overrides."""
    for prefix, entry in update.overrides.items():
        if not prefix.strip():
            raise HTTPException(status_code=400, detail="Prefix cannot be empty")
        if not isinstance(entry, dict):
            raise HTTPException(status_code=400, detail=f"Override for '{prefix}' must be an object")
        margin = entry.get("margin")
        if margin is None:
            raise HTTPException(status_code=400, detail=f"Override for '{prefix}' is missing 'margin'")
        if not (0 <= float(margin) <= 99):
            raise HTTPException(
                status_code=400,
                detail=f"Margin for prefix '{prefix}' must be between 0% and 99% (got {margin}%)"
            )

    # Normalize prefix keys to uppercase
    normalized = {
        k.upper().strip(): v
        for k, v in update.overrides.items()
        if k.strip()
    }

    setting = db.query(AppSettings).filter(
        AppSettings.setting_key == PREFIX_MARGINS_KEY
    ).first()

    if setting:
        setting.setting_value = normalized
        setting.updated_at = datetime.utcnow()
    else:
        setting = AppSettings(
            setting_key=PREFIX_MARGINS_KEY,
            setting_value=normalized,
            description="Part-number prefix margin overrides (e.g. GK17 → 60%)",
            updated_at=datetime.utcnow(),
        )
        db.add(setting)

    db.commit()
    db.refresh(setting)
    logger.info(f"Prefix margin overrides updated: {normalized}")

    return {
        "success": True,
        "message": "Prefix margin overrides updated successfully",
        "data": {
            "overrides": setting.setting_value,
            "updatedAt": setting.updated_at.isoformat() if setting.updated_at else None,
        }
    }


# ============================================================================
# BC Price Group → Tier Mapping Endpoints
# ============================================================================

@router.get("/bc-group-mapping/current")
async def get_bc_group_mapping(db: Session = Depends(get_db)):
    """Get current BC price group → portal tier mapping (or empty if none saved)."""
    setting = db.query(AppSettings).filter(
        AppSettings.setting_key == BC_GROUP_MAPPING_KEY
    ).first()

    mapping = setting.setting_value if setting else {}

    return {
        "success": True,
        "data": {
            "mapping": mapping,
            "isDefault": not bool(setting),
            "updatedAt": setting.updated_at.isoformat() if setting and setting.updated_at else None,
        }
    }


@router.put("/bc-group-mapping")
async def update_bc_group_mapping(
    update: BCGroupMappingUpdate,
    db: Session = Depends(get_db),
):
    """Save BC price group → portal tier mapping. Tier values must be gold/silver/bronze/retail."""
    for group_code, tier in update.mapping.items():
        if not group_code.strip():
            raise HTTPException(status_code=400, detail="Group code cannot be empty")
        if tier not in VALID_TIERS:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid tier '{tier}' for group '{group_code}'. Must be one of: {', '.join(sorted(VALID_TIERS))}"
            )

    # Normalize keys to uppercase
    normalized = {k.upper().strip(): v for k, v in update.mapping.items() if k.strip()}

    setting = db.query(AppSettings).filter(
        AppSettings.setting_key == BC_GROUP_MAPPING_KEY
    ).first()

    if setting:
        setting.setting_value = normalized
        setting.updated_at = datetime.utcnow()
    else:
        setting = AppSettings(
            setting_key=BC_GROUP_MAPPING_KEY,
            setting_value=normalized,
            description="BC customer price group code → portal pricing tier mapping",
            updated_at=datetime.utcnow(),
        )
        db.add(setting)

    db.commit()
    db.refresh(setting)
    logger.info(f"BC group tier mapping updated: {normalized}")

    return {
        "success": True,
        "message": "BC group tier mapping updated successfully",
        "data": {
            "mapping": setting.setting_value,
            "updatedAt": setting.updated_at.isoformat() if setting.updated_at else None,
        }
    }


@router.get("/bc-group-mapping/bc-groups")
async def get_bc_price_groups(db: Session = Depends(get_db)):
    """Return distinct BC price group codes seen across synced customers."""
    from app.db.models import BCCustomer
    rows = db.query(BCCustomer.bc_price_group).filter(
        BCCustomer.bc_price_group.isnot(None),
        BCCustomer.bc_price_group != "",
    ).distinct().all()
    groups = sorted({r[0] for r in rows})
    return {"success": True, "data": groups}


# ============================================================================
# Freight Configuration Endpoints
# ============================================================================

@router.get("/freight-config/current")
async def get_freight_config_endpoint(db: Session = Depends(get_db)):
    """Get current freight configuration (or defaults if not yet saved)."""
    setting = db.query(AppSettings).filter(
        AppSettings.setting_key == FREIGHT_CONFIG_KEY
    ).first()

    if not setting:
        return {
            "success": True,
            "data": {
                "config": get_default_freight_config(),
                "isDefault": True,
            }
        }

    return {
        "success": True,
        "data": {
            "config": setting.setting_value,
            "isDefault": False,
            "updatedAt": setting.updated_at.isoformat() if setting.updated_at else None,
        }
    }


@router.put("/freight-config")
async def update_freight_config(
    update: FreightConfigUpdate,
    db: Session = Depends(get_db),
):
    """Validate and save freight configuration."""
    config = update.config

    # Validate default_rate
    default_rate = config.get("default_rate", 5.0)
    if not (0 <= default_rate <= 100):
        raise HTTPException(
            status_code=400,
            detail=f"Default rate must be between 0% and 100% (got {default_rate}%)"
        )

    # Validate province overrides
    province_overrides = config.get("province_overrides", {})
    for prov, rate in province_overrides.items():
        if not (0 <= float(rate) <= 100):
            raise HTTPException(
                status_code=400,
                detail=f"Rate for province '{prov}' must be between 0% and 100% (got {rate}%)"
            )

    # Normalize province keys to uppercase
    normalized_overrides = {
        k.upper().strip(): float(v)
        for k, v in province_overrides.items()
        if k.strip()
    }

    normalized_config = {
        "default_rate": float(default_rate),
        "province_overrides": normalized_overrides,
        "freight_item_number": config.get("freight_item_number", "FREIGHT"),
        "fallback_to_comment": config.get("fallback_to_comment", True),
    }

    setting = db.query(AppSettings).filter(
        AppSettings.setting_key == FREIGHT_CONFIG_KEY
    ).first()

    if setting:
        setting.setting_value = normalized_config
        setting.updated_at = datetime.utcnow()
    else:
        setting = AppSettings(
            setting_key=FREIGHT_CONFIG_KEY,
            setting_value=normalized_config,
            description="Freight charge configuration (rates, province overrides)",
            updated_at=datetime.utcnow(),
        )
        db.add(setting)

    db.commit()
    db.refresh(setting)
    logger.info(f"Freight config updated: {normalized_config}")

    return {
        "success": True,
        "message": "Freight configuration updated successfully",
        "data": {
            "config": setting.setting_value,
            "updatedAt": setting.updated_at.isoformat() if setting.updated_at else None,
        }
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
