"""
Spring Data Service
Loads spring wire data from the spring-calculator JSON files
"""

import json
import os
import re
import time
from typing import List, Dict, Optional
from pathlib import Path
import logging

logger = logging.getLogger(__name__)


class SpringDataService:
    """Load spring wire data from spring-calculator JSON files"""

    # Path to spring data files
    SPRING_DATA_PATH = Path("C:/Users/jhein/spring-calculator/data/springs")

    # Mapping of coil diameter IDs to file names
    COIL_FILES = {
        "2.0": "coil-2.00.json",
        "2.625": "coil-2.63.json",
        "3.75": "coil-3.75.json",
        "6.0": "coil-6.00.json",
    }

    # Coil information
    COILS = [
        {
            "id": "2.0",
            "name": '2"',
            "displayName": '2" Coil',
            "description": "Standard residential",
            "fileName": "coil-2.00.json",
        },
        {
            "id": "2.625",
            "name": '2-5/8"',
            "displayName": '2-5/8" Coil',
            "description": "Light commercial",
            "fileName": "coil-2.63.json",
        },
        {
            "id": "3.75",
            "name": '3-3/4"',
            "displayName": '3-3/4" Coil',
            "description": "Commercial",
            "fileName": "coil-3.75.json",
        },
        {
            "id": "6.0",
            "name": '6"',
            "displayName": '6" Coil',
            "description": "Heavy commercial",
            "fileName": "coil-6.00.json",
        },
    ]

    def __init__(self):
        self._cache: Dict[str, dict] = {}

    def _load_coil_data(self, coil_id: str) -> Optional[dict]:
        """Load spring data for a specific coil diameter from JSON file"""
        if coil_id in self._cache:
            return self._cache[coil_id]

        file_name = self.COIL_FILES.get(coil_id)
        if not file_name:
            logger.warning(f"Unknown coil diameter: {coil_id}")
            return None

        file_path = self.SPRING_DATA_PATH / file_name
        if not file_path.exists():
            logger.error(f"Spring data file not found: {file_path}")
            return None

        try:
            with open(file_path, 'r') as f:
                data = json.load(f)
                self._cache[coil_id] = data
                return data
        except Exception as e:
            logger.error(f"Error loading spring data from {file_path}: {e}")
            return None

    def get_available_coils(self) -> List[dict]:
        """Get list of available coil diameters with metadata"""
        result = []
        for coil in self.COILS:
            coil_data = self._load_coil_data(coil["id"])
            wire_count = len(coil_data.get("wireSizes", [])) if coil_data else 0
            result.append({
                "id": coil["id"],
                "name": coil["name"],
                "displayName": coil["displayName"],
                "description": coil["description"],
                "wireSizeCount": wire_count,
            })
        return result

    def get_wire_sizes_for_coil(self, coil_id: str) -> List[dict]:
        """Get all wire sizes available for a coil diameter"""
        coil_data = self._load_coil_data(coil_id)
        if not coil_data:
            return []

        wire_sizes = []
        for wire in coil_data.get("wireSizes", []):
            wire_sizes.append({
                "diameter": wire["diameter"],
                "diameterFormatted": f"{wire['diameter']:.4f}",
                "rate": wire.get("rate"),
                "liftPerTurn": wire.get("liftPerTurn"),
                "mip": wire.get("mip", {}),
            })

        return wire_sizes

    def get_all_wire_sizes(self) -> Dict[str, List[dict]]:
        """Get wire sizes for all coil diameters"""
        result = {}
        for coil in self.COILS:
            result[coil["id"]] = self.get_wire_sizes_for_coil(coil["id"])
        return result

    def get_coil_info(self, coil_id: str) -> Optional[dict]:
        """Get information about a specific coil diameter"""
        for coil in self.COILS:
            if coil["id"] == coil_id:
                coil_data = self._load_coil_data(coil_id)
                return {
                    "id": coil["id"],
                    "name": coil["name"],
                    "displayName": coil["displayName"],
                    "description": coil["description"],
                    "minWire": coil_data.get("minWire") if coil_data else None,
                    "maxWire": coil_data.get("maxWire") if coil_data else None,
                    "wireSizeCount": len(coil_data.get("wireSizes", [])) if coil_data else 0,
                }
        return None


# Singleton instance
_spring_data_service: Optional[SpringDataService] = None


def get_spring_data_service() -> SpringDataService:
    """Get the singleton SpringDataService instance"""
    global _spring_data_service
    if _spring_data_service is None:
        _spring_data_service = SpringDataService()
    return _spring_data_service


def get_spring_inventory_settings(db_session) -> Dict[str, List[str]]:
    """
    Get current spring inventory settings from the database.

    Args:
        db_session: SQLAlchemy database session

    Returns:
        Dictionary mapping coil IDs to lists of stocked wire size strings
        Example: {"2.0": ["0.1920", "0.2070"], "2.625": ["0.2070", "0.2180"], ...}
    """
    from app.db.models import AppSettings

    setting = db_session.query(AppSettings).filter(
        AppSettings.setting_key == "spring_inventory"
    ).first()

    if setting and setting.setting_value:
        return setting.setting_value

    # Return default empty inventory if no settings exist
    return {
        "2.0": [],
        "2.625": [],
        "3.75": [],
        "6.0": [],
    }


def is_wire_size_stocked(
    db_session,
    coil_diameter: float,
    wire_diameter: float
) -> bool:
    """
    Check if a specific wire size is stocked for a coil diameter.

    Args:
        db_session: SQLAlchemy database session
        coil_diameter: Coil diameter (e.g., 2.0, 2.625, 3.75, 6.0)
        wire_diameter: Wire diameter (e.g., 0.2070, 0.2340)

    Returns:
        True if the wire size is stocked, False otherwise
    """
    inventory = get_spring_inventory_settings(db_session)

    # Convert coil diameter to string key format
    coil_key = str(coil_diameter)
    if coil_key not in inventory:
        return False

    # Format wire diameter to match stored format (4 decimal places)
    wire_formatted = f"{wire_diameter:.4f}"

    return wire_formatted in inventory.get(coil_key, [])


def filter_springs_by_inventory(
    db_session,
    spring_options: List[dict],
    prefer_stocked: bool = True
) -> List[dict]:
    """
    Filter and sort spring options based on inventory settings.

    If prefer_stocked is True:
      - Stocked springs are sorted to the top
      - Non-stocked springs are still included but marked

    Args:
        db_session: SQLAlchemy database session
        spring_options: List of spring option dictionaries with 'wire_diameter' and 'coil_diameter'
        prefer_stocked: If True, prefer stocked springs; if False, filter to only stocked

    Returns:
        Filtered/sorted list with 'is_stocked' field added to each option
    """
    inventory = get_spring_inventory_settings(db_session)

    result = []
    for option in spring_options:
        wire_diam = option.get('wire_diameter', option.get('wireDiameter'))
        coil_diam = option.get('coil_diameter', option.get('coilDiameter'))

        # Format for comparison
        coil_key = str(coil_diam)
        wire_formatted = f"{wire_diam:.4f}"

        is_stocked = wire_formatted in inventory.get(coil_key, [])

        option_copy = option.copy()
        option_copy['is_stocked'] = is_stocked

        if prefer_stocked or is_stocked:
            result.append(option_copy)

    # Sort: stocked first, then by original order
    result.sort(key=lambda x: (not x.get('is_stocked', False), spring_options.index(option) if option in spring_options else 999))

    return result


# ==================== BC-Driven Spring Inventory ====================

# Module-level cache (same pattern as pricing_service)
_bc_spring_inventory_cache: Optional[Dict[str, List[str]]] = None
_bc_spring_inventory_cache_time: float = 0
_BC_SPRING_INVENTORY_TTL = 3600  # 1 hour


def _build_reverse_lookups():
    """Build reverse mappings from BC codes back to float values."""
    from app.services.bc_part_number_mapper import BCPartNumberMapper
    mapper = BCPartNumberMapper

    # code -> float wire size  (e.g. "234" -> 0.234)
    wire_code_to_float = {code: size for size, code in mapper.WIRE_SIZE_CODES.items()}
    # code -> float coil size  (e.g. "20" -> 2.0)
    coil_code_to_float = {code: size for size, code in mapper.COIL_SIZE_CODES.items()}

    return wire_code_to_float, coil_code_to_float


# Regex: SP{type 2 digits}-{wire 3 digits}{coil 2 digits}-{hand 2 digits}
_SPRING_PN_RE = re.compile(r'^SP\d{2}-(\d{3})(\d{2})-\d{2}$')


def get_bc_spring_inventory() -> Dict[str, List[str]]:
    """
    Fetch all spring items from live BC, parse wire/coil from part numbers,
    return in the same format as get_spring_inventory_settings():
    {"2.0": ["0.2180", "0.2340", ...], "2.625": [...], "3.75": [...], "6.0": [...]}

    Results are cached for 1 hour. Falls back to DB settings on BC API failure.
    """
    global _bc_spring_inventory_cache, _bc_spring_inventory_cache_time

    # Return cache if fresh
    if _bc_spring_inventory_cache is not None and (time.time() - _bc_spring_inventory_cache_time) < _BC_SPRING_INVENTORY_TTL:
        return _bc_spring_inventory_cache

    try:
        from app.integrations.bc.client import bc_client

        wire_code_to_float, coil_code_to_float = _build_reverse_lookups()

        # Fetch all items starting with SP1 (covers SP10, SP11, SP16)
        items = bc_client.search_items_by_prefix("SP1")

        # Parse into {coil_key: set(wire_str)}
        inventory: Dict[str, set] = {}
        for item in items:
            number = item.get("number", "")
            match = _SPRING_PN_RE.match(number)
            if not match:
                continue

            wire_code = match.group(1)  # e.g. "234"
            coil_code = match.group(2)  # e.g. "20"

            wire_float = wire_code_to_float.get(wire_code)
            coil_float = coil_code_to_float.get(coil_code)

            if wire_float is None or coil_float is None:
                continue

            # Filter wire >= 0.218 (BC minimum)
            if wire_float < 0.218:
                continue

            coil_key = str(coil_float)
            if coil_key not in inventory:
                inventory[coil_key] = set()
            inventory[coil_key].add(f"{wire_float:.4f}")

        # Convert sets to sorted lists, ensure all coil keys present
        result: Dict[str, List[str]] = {}
        for coil_key in ["2.0", "2.625", "3.75", "6.0"]:
            wires = sorted(inventory.get(coil_key, set()))
            result[coil_key] = wires

        total = sum(len(v) for v in result.values())
        logger.info(f"BC spring inventory: {total} wire/coil combos from {len(items)} items")

        _bc_spring_inventory_cache = result
        _bc_spring_inventory_cache_time = time.time()
        return result

    except Exception as e:
        logger.warning(f"Failed to fetch BC spring inventory, falling back to DB settings: {e}")

        # Return cached result if we have one (even if stale)
        if _bc_spring_inventory_cache is not None:
            return _bc_spring_inventory_cache

        # Last resort: try DB settings
        try:
            from app.db.database import SessionLocal
            db = SessionLocal()
            try:
                return get_spring_inventory_settings(db)
            finally:
                db.close()
        except Exception:
            return {"2.0": [], "2.625": [], "3.75": [], "6.0": []}
