"""
Freight Service
Calculates freight charges based on province and delivery type.
Rates are percentage-based and configurable via AppSettings.
"""

import logging
from typing import Dict, Any, Optional
from sqlalchemy.orm import Session

from app.db.models import AppSettings

logger = logging.getLogger(__name__)

FREIGHT_CONFIG_KEY = "freight_config"


def get_default_freight_config() -> Dict[str, Any]:
    """Hardcoded default freight configuration."""
    return {
        "default_rate": 5.0,
        "province_overrides": {
            "SK": 7.0,
            "MB": 7.0,
            "BC": 7.0,
        },
        "freight_item_number": "FREIGHT",
        "fallback_to_comment": True,
    }


def get_freight_config(db: Session) -> Dict[str, Any]:
    """Load freight config from AppSettings, falling back to defaults."""
    setting = db.query(AppSettings).filter(
        AppSettings.setting_key == FREIGHT_CONFIG_KEY
    ).first()

    if setting and setting.setting_value:
        return setting.setting_value

    return get_default_freight_config()


def calculate_freight(
    product_subtotal: float,
    province: Optional[str],
    delivery_type: str,
    db: Session,
) -> Dict[str, Any]:
    """
    Calculate freight charge for a quote.

    Args:
        product_subtotal: Total of product lines (excl. tax)
        province: Customer province code (e.g. "AB", "SK", "BC")
        delivery_type: "delivery" or "pickup"
        db: Database session

    Returns:
        dict with: amount, rate, description, skip (True if pickup or zero)
    """
    if delivery_type == "pickup":
        return {
            "amount": 0,
            "rate": 0,
            "description": "Pickup - No Freight",
            "skip": True,
        }

    config = get_freight_config(db)
    default_rate = config.get("default_rate", 5.0)
    province_overrides = config.get("province_overrides", {})

    # Look up province-specific rate (normalize to uppercase)
    province_upper = (province or "").upper().strip()
    rate = province_overrides.get(province_upper, default_rate)

    amount = round(product_subtotal * rate / 100, 2)

    # Build description
    if province_upper and province_upper in province_overrides:
        description = f"Freight ({rate}% - {province_upper})"
    else:
        description = f"Freight ({rate}%)"

    return {
        "amount": amount,
        "rate": rate,
        "description": description,
        "skip": amount <= 0,
    }
