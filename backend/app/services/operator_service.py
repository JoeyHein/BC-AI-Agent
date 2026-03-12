"""
Operator Service
Loads operator catalog from CSV, provides filtered options by brand/type.
Uses real BC part numbers for quote line items.
"""

import csv
import logging
import os
from typing import Dict, List, Any, Optional

logger = logging.getLogger(__name__)

_CATALOG_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "operator_catalog.csv"
)

# Module-level cache
_catalog: Optional[List[Dict[str, Any]]] = None


def _load_catalog() -> List[Dict[str, Any]]:
    """Load and cache the operator catalog from CSV."""
    global _catalog
    if _catalog is not None:
        return _catalog

    items = []
    path = os.path.normpath(_CATALOG_PATH)
    try:
        with open(path, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                items.append({
                    "partNumber": row["PartNumber"].strip(),
                    "brand": row["Brand"].strip(),
                    "type": row["Type"].strip(),           # Residential, Commercial, Accessory
                    "displayName": row["DisplayName"].strip(),
                    "unitCost": float(row["UnitCost"] or 0),
                    "status": row["Status"].strip(),
                    "replacement": row.get("Replacement", "").strip(),
                    "notes": row.get("Notes", "").strip(),
                    "include": row.get("Include", "").strip().upper() == "Y",
                })
    except FileNotFoundError:
        logger.error(f"Operator catalog not found at {path}")
        return []

    _catalog = items
    logger.info(f"Loaded operator catalog: {len(items)} items, {sum(1 for i in items if i['include'])} active")
    return _catalog


def get_operator_options(door_type: str = "residential") -> Dict[str, Any]:
    """
    Get operator options grouped by brand for the given door type.
    Returns structure suitable for frontend rendering.
    """
    catalog = _load_catalog()
    active = [i for i in catalog if i["include"] and i["status"] == "CURRENT"]

    if door_type == "commercial":
        # Commercial: show commercial operators + accessories from all brands
        units = [i for i in active if i["type"] == "Commercial"]
        accessories = [i for i in active if i["type"] == "Accessory"]
    else:
        # Residential: show residential operators + LiftMaster residential accessories
        units = [i for i in active if i["type"] == "Residential"]
        accessories = [i for i in active if i["type"] == "Accessory" and i["brand"] == "LiftMaster"]

    # Group units by brand
    brands: Dict[str, List[Dict]] = {}
    for item in units:
        brand = item["brand"]
        if brand not in brands:
            brands[brand] = []
        brands[brand].append(_format_operator(item))

    # Group accessories by brand
    acc_brands: Dict[str, List[Dict]] = {}
    for item in accessories:
        brand = item["brand"]
        if brand not in acc_brands:
            acc_brands[brand] = []
        acc_brands[brand].append(_format_accessory(item))

    return {
        "operators": brands,
        "accessories": acc_brands,
    }


def get_all_operator_options() -> Dict[str, Any]:
    """Get all operator options for both door types (used by full-config endpoint)."""
    return {
        "residential": get_operator_options("residential"),
        "commercial": get_operator_options("commercial"),
    }


def get_operator_part_number(operator_id: str) -> Optional[str]:
    """
    Given an operator ID (which IS the BC part number), return it.
    Returns None if not found or not active.
    """
    if not operator_id or operator_id == "NONE":
        return None

    catalog = _load_catalog()
    item = next((i for i in catalog if i["partNumber"] == operator_id and i["include"]), None)
    if item:
        return item["partNumber"]

    # Fallback: return as-is (might be a direct BC part number)
    return operator_id


def get_operator_display_name(operator_id: str) -> str:
    """Get display name for an operator part number."""
    if not operator_id or operator_id == "NONE":
        return "No Operator"

    catalog = _load_catalog()
    item = next((i for i in catalog if i["partNumber"] == operator_id), None)
    if item:
        return f"{item['brand']} {item['displayName']}"
    return operator_id


def _format_operator(item: Dict) -> Dict:
    """Format a catalog item for frontend display."""
    return {
        "id": item["partNumber"],
        "name": item["displayName"],
        "brand": item["brand"],
        "partNumber": item["partNumber"],
        "unitCost": item["unitCost"],
        "notes": item["notes"],
    }


def _format_accessory(item: Dict) -> Dict:
    """Format an accessory item for frontend display."""
    return {
        "id": item["partNumber"],
        "name": item["displayName"],
        "brand": item["brand"],
        "partNumber": item["partNumber"],
        "unitCost": item["unitCost"],
    }
