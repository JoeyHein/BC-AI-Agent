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

# BC sends full province names — map to codes for freight lookup
PROVINCE_NAME_TO_CODE = {
    "ALBERTA": "AB",
    "BRITISH COLUMBIA": "BC",
    "MANITOBA": "MB",
    "NEW BRUNSWICK": "NB",
    "NEWFOUNDLAND AND LABRADOR": "NL",
    "NORTHWEST TERRITORIES": "NT",
    "NOVA SCOTIA": "NS",
    "NUNAVUT": "NU",
    "ONTARIO": "ON",
    "PRINCE EDWARD ISLAND": "PE",
    "QUEBEC": "QC",
    "SASKATCHEWAN": "SK",
    "YUKON": "YT",
}


def get_default_freight_config() -> Dict[str, Any]:
    """Hardcoded default freight configuration."""
    return {
        "default_rate": 9.0,
        "province_overrides": {
            "AB": 7.0,
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

    # Normalize province — BC sends full names like "Manitoba", we need codes like "MB"
    province_upper = (province or "").upper().strip()
    province_code = PROVINCE_NAME_TO_CODE.get(province_upper, province_upper)
    rate = province_overrides.get(province_code, default_rate)

    amount = round(product_subtotal * rate / 100, 2)

    # Build description
    if province_code and province_code in province_overrides:
        description = f"Freight ({rate}% - {province_code})"
    else:
        description = f"Freight ({rate}%)"

    return {
        "amount": amount,
        "rate": rate,
        "description": description,
        "skip": amount <= 0,
    }


def freight_settings(db) -> Dict[str, Any]:
    """Freight config, including when the caller has no database session.

    Saved settings override the defaults key by key. A missing item number
    or comment-fallback flag still resolves to the default.
    """
    defaults = get_default_freight_config()
    if db is None:
        return defaults
    try:
        config = get_freight_config(db)
    except Exception:
        logger.warning("Could not load freight config; using defaults", exc_info=True)
        return defaults
    if not isinstance(config, dict):
        return defaults
    merged = dict(defaults)
    merged.update(config)
    return merged


def freight_pricing_row(
    freight: Dict[str, Any],
    item_number: str = "FREIGHT",
    with_line_type: bool = False,
) -> Dict[str, Any]:
    """One quote-level freight row for portal line pricing."""
    amount = round(float(freight.get("amount") or 0), 2)
    row = {
        "part_number": item_number or "FREIGHT",
        "description": freight.get("description") or "Freight",
        "quantity": 1,
        "unit_price": amount,
        "line_total": amount,
    }
    if with_line_type:
        row["line_type"] = "Item"
    return row


def quote_freight_source_line(freight: Dict[str, Any], item_number: str = "FREIGHT") -> Dict[str, Any]:
    """Line dict stored on the quote snapshot, matching the posted FREIGHT item.

    No door_index: freight belongs to the quote, not to a door package.
    """
    amount = round(float(freight.get("amount") or 0), 2)
    return {
        "lineType": "Item",
        "part_number": item_number or "FREIGHT",
        "description": freight.get("description") or "Freight",
        "quantity": 1,
        "category": "freight",
        "unit_price": amount,
        "fixed_unit_price": amount,
    }


def post_quote_freight_line(
    bc_client,
    bc_quote_id: str,
    freight: Dict[str, Any],
    config: Optional[Dict[str, Any]] = None,
    on_added=None,
    on_output=None,
) -> Dict[str, Any]:
    """Append one FREIGHT item at the end of a BC sales quote.

    Callers calculate ``freight["amount"]`` from the goods subtotal before
    this line exists, so the charge is not a percent of itself. That amount
    is the same total the old per-door shares added up to: one province
    percent of the combined goods, not a separate percent inside each door.
    A failed item post falls back to a comment when the config allows it.
    """
    config = config or get_default_freight_config()
    item_number = config.get("freight_item_number") or "FREIGHT"
    amount = round(float(freight.get("amount") or 0), 2)
    full_description = freight.get("description") or "Freight"
    description = full_description[:100]
    result = {
        "posted": False,
        "as_item": False,
        "line": None,
        "item_number": item_number,
        "amount": amount,
        "description": full_description,
    }

    added = None
    try:
        added = bc_client.add_quote_line(bc_quote_id, {
            "lineType": "Item",
            "lineObjectNumber": item_number,
            "description": description,
            "quantity": 1,
        })
    except Exception as exc:
        logger.warning("Could not add freight as Item '%s': %s", item_number, exc)

    if added and added.get("id"):
        try:
            bc_client.update_quote_line(
                bc_quote_id,
                added["id"],
                added.get("@odata.etag", "*"),
                {"unitPrice": amount, "description": description},
            )
        except Exception as exc:
            logger.warning("Could not price freight line: %s", exc)
        if on_added:
            on_added(added)
        if on_output:
            try:
                on_output(added)
            except Exception as exc:
                logger.warning("Could not set Output on freight line: %s", exc)
        result.update(posted=True, as_item=True, line=added)
        logger.info("Added freight line: $%.2f (%s)", amount, description)
        return result

    if not config.get("fallback_to_comment", True):
        return result
    try:
        comment = bc_client.add_quote_line(bc_quote_id, {
            "lineType": "Comment",
            "description": f"{description}: ${amount:.2f}",
        })
    except Exception as exc:
        logger.warning("Could not add freight as comment: %s", exc)
        return result
    if on_added and comment:
        on_added(comment)
    result.update(posted=True, as_item=False, line=comment)
    logger.info("Added freight as comment fallback: $%.2f", amount)
    return result
