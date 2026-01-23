"""
Door Configurator API - Provides configuration options for building door quotes
Based on Upwardor brochure specifications (Residential 2025 & Commercial 2023)
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
import logging

from app.services.part_number_service import get_parts_for_door_config, part_number_service, DoorConfiguration
from app.services.door_calculator_service import door_calculator, calculate_door_from_config
from app.integrations.bc.client import bc_client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/door-config", tags=["door-configurator"])


# ============================================================================
# CONFIGURATION DATA (from UPWARDOR_PORTAL_CONFIGURATION.md)
# ============================================================================

DOOR_TYPES = [
    {"id": "residential", "name": "Residential", "description": "Standard residential garage doors"},
    {"id": "commercial", "name": "Commercial", "description": "Heavy-duty commercial doors"},
    {"id": "aluminium", "name": "Aluminium", "description": "Full-view aluminum and glass doors"},
    {"id": "executive", "name": "Executive", "description": "Premium wood overlay doors"},
]

DOOR_SERIES = {
    "residential": [
        {
            "id": "KANATA",
            "name": "Kanata Collection",
            "description": "Premium insulated steel door with R-16.3 value",
            "categoryValue": "678f8f79088796816d501456",
            "specs": {
                "thickness": "1 3/4\" (44.5mm)",
                "rValue": 16.3,
                "steel": "26-Gauge Pebble Embossed",
                "maxWidth": 216,  # 18'0" in inches
                "sectionHeights": [18, 21, 24],
                "warranty": "Limited Lifetime"
            }
        },
        {
            "id": "CRAFT",
            "name": "Craft Series",
            "description": "Value-oriented insulated door with R-16.3 value",
            "categoryValue": "678f8f79088796816d501457",
            "specs": {
                "thickness": "1 3/4\" (44.5mm)",
                "rValue": 16.3,
                "steel": "26-Gauge Pebble Embossed",
                "availableWidths": [96, 108, 144, 192],  # 8', 9', 12', 16'
                "maxHeight": 96,  # 8'
                "sectionHeights": [28, 32],
                "minHeaderClearance": 23,
                "warranty": "Limited Lifetime"
            }
        },
    ],
    "commercial": [
        {
            "id": "TX450",
            "name": "Thermalex TX450",
            "description": "Commercial insulated door with R-16.3 value",
            "categoryValue": "67ab1db858e8bd835f4898e4",
            "specs": {
                "rValue": 16.3,
                "features": ["Double Continuous Hinge Reinforcement", "Thermal Break", "Windload", "IECC Certified"],
                "warranty": "10 Year Limited"
            }
        },
        {
            "id": "TX500",
            "name": "Thermalex TX500",
            "description": "Premium commercial door with R-18.4 value",
            "categoryValue": "67ab1db858e8bd835f4898e5",
            "specs": {
                "rValue": 18.4,
                "features": ["Double Continuous Hinge Reinforcement", "Thermal Break", "Windload", "IECC Certified"],
                "warranty": "10 Year Limited"
            }
        },
        {
            "id": "TX450-20",
            "name": "Thermalex TX450-20",
            "description": "TX450 with 20-gauge steel",
            "categoryValue": "67ab1db858e8bd835f4898e6",
            "specs": {"rValue": 16.3, "steel": "20-gauge", "warranty": "10 Year Limited"}
        },
        {
            "id": "TX500-20",
            "name": "Thermalex TX500-20",
            "description": "TX500 with 20-gauge steel",
            "categoryValue": "67ab1db858e8bd835f4898e7",
            "specs": {"rValue": 18.4, "steel": "20-gauge", "warranty": "10 Year Limited"}
        },
    ],
    "aluminium": [
        {
            "id": "AL976",
            "name": "AL-976",
            "description": "Full-view aluminum door with glass panels",
            "categoryValue": "67f7c1c39cf0ed4a3b00baea",
            "specs": {
                "thickness": "1 3/4\" (44.5mm)",
                "material": "Extruded 6063-T6 Aluminum",
                "maxWidth": 288,  # 24' in inches
                "finishWarranty": "5 Year Limited",
                "workmanshipWarranty": "1 Year Limited"
            }
        },
    ],
    "executive": [
        {
            "id": "KANATA_EXECUTIVE",
            "name": "Kanata Executive Line",
            "description": "Premium wood overlay on insulated steel",
            "categoryValue": "678f8f79088796816d501456",  # Uses Kanata base
            "specs": {
                "thickness": "3\" (76.2mm)",
                "rValue": 16.3,
                "overlayOptions": ["Clear Cedar", "Red Grandis"],
                "sectionHeights": [18, 21, 24, 28, 32],
                "warranty": "Limited Lifetime"
            }
        },
    ],
}

COLORS = {
    "KANATA": [
        {"id": "WHITE", "name": "White", "hex": "#FFFFFF"},
        {"id": "NEW_ALMOND", "name": "New Almond", "hex": "#EFDECD"},
        {"id": "BLACK", "name": "Black", "hex": "#000000"},
        {"id": "WALNUT", "name": "Walnut", "hex": "#5D432C"},
        {"id": "IRON_ORE", "name": "Iron Ore", "hex": "#48464A"},
        {"id": "SANDTONE", "name": "Sandtone", "hex": "#D4C4A8"},
        {"id": "NEW_BROWN", "name": "New Brown", "hex": "#6B4423"},
        {"id": "BRONZE", "name": "Bronze", "hex": "#CD7F32"},
        {"id": "STEEL_GREY", "name": "Steel Grey", "hex": "#71797E"},
        {"id": "HAZELWOOD", "name": "Hazelwood", "hex": "#8E7618"},
        {"id": "ENGLISH_CHESTNUT", "name": "English Chestnut", "hex": "#954535"},
    ],
    "CRAFT": [
        {"id": "WHITE", "name": "White", "hex": "#FFFFFF"},
        {"id": "SANDTONE", "name": "Sandtone", "hex": "#D4C4A8"},
        {"id": "WALNUT", "name": "Walnut", "hex": "#5D432C", "note": "28\" section only"},
        {"id": "ENGLISH_CHESTNUT", "name": "English Chestnut", "hex": "#954535"},
        {"id": "IRON_ORE", "name": "Iron Ore", "hex": "#48464A"},
    ],
    "COMMERCIAL": [
        {"id": "BRIGHT_WHITE", "name": "Bright White", "hex": "#FFFFFF"},
        {"id": "NEW_BROWN", "name": "New Brown", "hex": "#6B4423"},
        {"id": "BLACK", "name": "Black", "hex": "#000000"},
        {"id": "STEEL_GREY", "name": "Steel Grey", "hex": "#71797E"},
    ],
    "AL976": [
        {"id": "CLEAR_ANODIZED", "name": "Clear Anodized (Standard)", "hex": "#C0C0C0"},
        {"id": "CUSTOM", "name": "Custom Powder Coat", "hex": None, "note": "Custom colors available"},
    ],
    "EXECUTIVE_STAINS": [
        {"id": "MEDIUM_OAK", "name": "Medium Oak", "hex": "#B5651D"},
        {"id": "MAHOGANY", "name": "Mahogany", "hex": "#C04000"},
        {"id": "NATURAL", "name": "Natural", "hex": "#DEB887"},
        {"id": "SLATE_DARK_GREY", "name": "Slate Dark Grey", "hex": "#708090"},
        {"id": "DARK_WALNUT", "name": "Dark Walnut", "hex": "#5C4033"},
    ],
}

PANEL_DESIGNS = {
    "KANATA": [
        {"id": "SHERIDAN", "code": "SHXL", "name": "Sheridan", "type": "Raised Panel (Short)"},
        {"id": "SHERIDAN_XL", "code": "LNXL", "name": "Sheridan XL", "type": "Raised Panel (Long)"},
        {"id": "BRONTE_CREEK", "code": "SHCH", "name": "Bronte Creek", "type": "Carriage House (Short)"},
        {"id": "BRONTE_CREEK_XL", "code": "LNCH", "name": "Bronte Creek XL", "type": "Carriage House (Long)"},
        {"id": "TRAFALGAR", "code": "RIB", "name": "Trafalgar", "type": "Ribbed Panel"},
        {"id": "FLUSH", "code": "FLUSH", "name": "Flush", "type": "Flush/Flat"},
    ],
    "CRAFT": [
        {"id": "MUSKOKA", "code": "MUSKOKA", "name": "Muskoka", "type": "Carriage House"},
        {"id": "DENISON", "code": "DENISON", "name": "Denison", "type": "Carriage House"},
        {"id": "GRANVILLE", "code": "GRANVILLE", "name": "Granville", "type": "Carriage House"},
    ],
    "EXECUTIVE": [
        {"id": "F01", "code": "F01", "name": "Flush Basic", "base": "Flush"},
        {"id": "F01A", "code": "F01A", "name": "Flush Arched Top", "base": "Flush"},
        {"id": "T01", "code": "T01", "name": "Textured Basic", "base": "Textured"},
        {"id": "T01A", "code": "T01A", "name": "Textured Arched Top", "base": "Textured"},
        {"id": "F04", "code": "F04", "name": "Diagonal", "base": "Flush"},
        {"id": "F04A", "code": "F04A", "name": "Diagonal Arched", "base": "Flush"},
        {"id": "F05", "code": "F05", "name": "V-Pattern", "base": "Flush"},
        {"id": "F05A", "code": "F05A", "name": "V-Pattern Arched", "base": "Flush"},
        {"id": "F06", "code": "F06", "name": "X-Pattern", "base": "Flush"},
        {"id": "F06A", "code": "F06A", "name": "X-Pattern Arched", "base": "Flush"},
    ],
}

WINDOW_INSERTS = {
    "STOCKTON": [
        {"id": "STOCKTON_STANDARD", "name": "Standard Stockton"},
        {"id": "STOCKTON_TEN_SQUARE_XL", "name": "Ten Square XL - Stockton"},
        {"id": "STOCKTON_ARCHED_XL", "name": "Arched XL - Stockton"},
        {"id": "STOCKTON_EIGHT_SQUARE", "name": "Eight Square"},
        {"id": "STOCKTON_ARCHED", "name": "Arched"},
    ],
    "STOCKBRIDGE": [
        {"id": "STOCKBRIDGE_STRAIGHT", "name": "Straight"},
        {"id": "STOCKBRIDGE_STRAIGHT_XL", "name": "Straight XL - Stockbridge"},
        {"id": "STOCKBRIDGE_ARCHED_XL", "name": "Arched XL - Stockbridge"},
        {"id": "STOCKBRIDGE_ARCHED", "name": "Arched"},
    ],
}

GLAZING_OPTIONS = {
    "standard": [
        {"id": "NONE", "name": "No Windows"},
        {"id": "CLEAR", "name": "Clear Glass"},
        {"id": "INSULATED", "name": "Insulated Glass"},
        {"id": "TINTED", "name": "Tinted Glass"},
        {"id": "TEMPERED", "name": "Tempered Glass"},
    ],
    "AL976": [
        {"id": "SINGLE", "name": "Single Glass"},
        {"id": "INSULATED", "name": "Insulated Glass"},
        {"id": "TINTED", "name": "Tinted Glass"},
        {"id": "TEMPERED", "name": "Tempered Glass"},
        {"id": "SPECIALTY", "name": "Specialty Glass"},
        {"id": "ACID_ETCHED", "name": "Acid Etched Glass"},
    ],
    "executive": [
        {"id": "CLEAR_ACID_ETCHED", "name": "Clear/Acid Etched"},
        {"id": "CLEAR_SUPER_GREY", "name": "Clear/Super Grey"},
        {"id": "CLEAR_CLEAR", "name": "Clear/Clear"},
    ],
}

TRACK_OPTIONS = {
    "radius": [
        {"id": "12", "name": "12\" (Low Headroom)", "minClearance": 12},
        {"id": "15", "name": "15\" (Standard Residential)", "minClearance": 15},
        {"id": "20", "name": "20\" (Craft Series Standard)", "minClearance": 20},
    ],
    "thickness": [
        {"id": "2", "name": "2\" Track"},
        {"id": "3", "name": "3\" Track (Heavy Duty)"},
    ],
    "gauge": [
        {"id": "18", "name": "18-Gauge"},
        {"id": "16", "name": "16-Gauge (Heavy Duty)"},
    ],
}

HARDWARE_OPTIONS = [
    {"id": "tracks", "name": "Tracks", "description": "Vertical and horizontal track system", "default": True},
    {"id": "springs", "name": "Springs", "description": "Torsion spring assembly", "default": True},
    {"id": "struts", "name": "Struts", "description": "Reinforcing struts", "default": True},
    {"id": "hardwareKits", "name": "Hardware Kits", "description": "Hinges, rollers, brackets", "default": True},
    {"id": "weatherStripping", "name": "Weather Stripping", "description": "Perimeter seal", "default": True},
    {"id": "bottomRetainer", "name": "Bottom Retainer", "description": "PVC bottom seal", "default": True},
    {"id": "shafts", "name": "Shafts", "description": "Torsion shaft", "default": True},
]

OPERATOR_OPTIONS = {
    "residential": [
        {"id": "NONE", "name": "No Operator"},
        {"id": "LIFTMASTER_BASIC", "name": "LiftMaster Basic", "features": ["Chain Drive"]},
        {"id": "LIFTMASTER_MYQ", "name": "LiftMaster with myQ", "features": ["WiFi", "myQ App"]},
        {"id": "LIFTMASTER_BATTERY", "name": "LiftMaster with Battery Backup", "features": ["myQ", "Battery Backup"]},
    ],
    "commercial": [
        {"id": "NONE", "name": "No Operator"},
        {"id": "PDC500", "name": "POWRDOR PDC500", "hp": "1/2 HP", "maxSize": 200},
        {"id": "PDC750_100", "name": "POWRDOR PDC750-100", "hp": "3/4 HP", "maxSize": 350},
        {"id": "PDC750_125", "name": "POWRDOR PDC750-125", "hp": "3/4 HP", "maxSize": 350},
        {"id": "PDC1000", "name": "POWRDOR PDC1000", "hp": "1.0 HP", "maxSize": 500},
        {"id": "PDC2000", "name": "POWRDOR PDC2000", "hp": "2.0 HP", "maxSize": 500},
        {"id": "PA15", "name": "POWAIRDOR PA15 (Pneumatic)", "features": ["Car Wash", "45\"/sec"]},
        {"id": "PA17", "name": "POWAIRDOR PA17 (Pneumatic)", "features": ["General", "45\"/sec"]},
    ],
}


# ============================================================================
# PYDANTIC MODELS
# ============================================================================

class DoorConfigRequest(BaseModel):
    doorType: str
    doorSeries: str
    doorWidth: int  # in inches
    doorHeight: int  # in inches
    doorCount: int = 1
    panelColor: str
    panelDesign: str
    windowInsert: Optional[str] = None
    windowSection: Optional[int] = None  # Which section has windows (1 = top)
    glazingType: Optional[str] = None
    trackRadius: str = "15"
    trackThickness: str = "2"
    hardware: Dict[str, bool] = {}
    operator: Optional[str] = None
    notes: Optional[str] = None


class QuoteGenerationRequest(BaseModel):
    doors: List[DoorConfigRequest]
    poNumber: Optional[str] = None
    tagName: Optional[str] = None
    customerId: Optional[str] = None


class DoorCalculationRequest(BaseModel):
    """Request for complete door calculation"""
    doorModel: str  # TX380, TX450, TX450-20, TX500, TX500-20
    widthFeet: int = 0
    widthInches: int = 0
    heightFeet: int = 0
    heightInches: int = 0
    liftType: str = "standard_15"  # standard_15, standard_12, lhr_front, lhr_rear, high_lift, vertical
    trackSize: int = 3  # 2 or 3 inches
    windowType: Optional[str] = None  # "18x8", "24x12", "34x16"
    windowQty: int = 0
    doubleEndCaps: bool = False
    heavyDutyHinges: bool = False
    targetCycles: int = 10000  # 10000, 15000, 25000, 50000, 100000


# ============================================================================
# API ENDPOINTS
# ============================================================================

@router.get("/types")
async def get_door_types():
    """Get available door types"""
    return {"success": True, "data": DOOR_TYPES}


@router.get("/series/{door_type}")
async def get_door_series(door_type: str):
    """Get available door series for a door type"""
    series = DOOR_SERIES.get(door_type, [])
    if not series:
        raise HTTPException(status_code=404, detail=f"Door type '{door_type}' not found")
    return {"success": True, "data": series}


@router.get("/colors/{series_id}")
async def get_colors(series_id: str):
    """Get available colors for a door series"""
    # Map series to color set
    color_map = {
        "KANATA": "KANATA",
        "CRAFT": "CRAFT",
        "TX450": "COMMERCIAL",
        "TX500": "COMMERCIAL",
        "TX450-20": "COMMERCIAL",
        "TX500-20": "COMMERCIAL",
        "AL976": "AL976",
        "KANATA_EXECUTIVE": "EXECUTIVE_STAINS",
    }
    color_key = color_map.get(series_id, "KANATA")
    colors = COLORS.get(color_key, COLORS["KANATA"])
    return {"success": True, "data": colors}


@router.get("/panel-designs/{series_id}")
async def get_panel_designs(series_id: str):
    """Get available panel designs for a door series"""
    design_map = {
        "KANATA": "KANATA",
        "CRAFT": "CRAFT",
        "KANATA_EXECUTIVE": "EXECUTIVE",
    }
    design_key = design_map.get(series_id, "KANATA")
    designs = PANEL_DESIGNS.get(design_key, [])
    return {"success": True, "data": designs}


@router.get("/window-inserts")
async def get_window_inserts():
    """Get available window insert styles"""
    return {"success": True, "data": WINDOW_INSERTS}


@router.get("/glazing-options/{door_type}")
async def get_glazing_options(door_type: str):
    """Get glazing options for door type"""
    glazing_map = {
        "residential": "standard",
        "commercial": "standard",
        "aluminium": "AL976",
        "executive": "executive",
    }
    glazing_key = glazing_map.get(door_type, "standard")
    options = GLAZING_OPTIONS.get(glazing_key, GLAZING_OPTIONS["standard"])
    return {"success": True, "data": options}


@router.get("/track-options")
async def get_track_options():
    """Get track configuration options"""
    return {"success": True, "data": TRACK_OPTIONS}


@router.get("/hardware-options")
async def get_hardware_options():
    """Get hardware options"""
    return {"success": True, "data": HARDWARE_OPTIONS}


@router.get("/operator-options/{door_type}")
async def get_operator_options(door_type: str):
    """Get operator options for door type"""
    op_type = "commercial" if door_type == "commercial" else "residential"
    operators = OPERATOR_OPTIONS.get(op_type, OPERATOR_OPTIONS["residential"])
    return {"success": True, "data": operators}


@router.get("/full-config")
async def get_full_configuration():
    """Get complete configuration options in one request"""
    return {
        "success": True,
        "data": {
            "doorTypes": DOOR_TYPES,
            "doorSeries": DOOR_SERIES,
            "colors": COLORS,
            "panelDesigns": PANEL_DESIGNS,
            "windowInserts": WINDOW_INSERTS,
            "glazingOptions": GLAZING_OPTIONS,
            "trackOptions": TRACK_OPTIONS,
            "hardwareOptions": HARDWARE_OPTIONS,
            "operatorOptions": OPERATOR_OPTIONS,
        }
    }


@router.post("/validate")
async def validate_door_config(config: DoorConfigRequest):
    """Validate a door configuration"""
    errors = []
    warnings = []

    # Get series specs
    series_list = DOOR_SERIES.get(config.doorType, [])
    series = next((s for s in series_list if s["id"] == config.doorSeries), None)

    if not series:
        errors.append(f"Invalid door series: {config.doorSeries}")
    else:
        specs = series.get("specs", {})

        # Validate dimensions
        if "maxWidth" in specs and config.doorWidth > specs["maxWidth"]:
            errors.append(f"Door width {config.doorWidth}\" exceeds maximum {specs['maxWidth']}\" for {series['name']}")

        if "maxHeight" in specs and config.doorHeight > specs["maxHeight"]:
            errors.append(f"Door height {config.doorHeight}\" exceeds maximum {specs['maxHeight']}\" for {series['name']}")

        if "availableWidths" in specs and config.doorWidth not in specs["availableWidths"]:
            warnings.append(f"Non-standard width. Available widths: {specs['availableWidths']}")

    # Validate track radius for low headroom
    if config.trackRadius == "12":
        warnings.append("12\" track radius requires minimum 12\" header clearance (low headroom)")

    return {
        "success": len(errors) == 0,
        "valid": len(errors) == 0,
        "errors": errors,
        "warnings": warnings
    }


@router.post("/calculate-panels")
async def calculate_panels(door_height: int):
    """Calculate panel quantity based on door height (in inches)"""
    # Standard panel height calculations
    if door_height <= 84:  # 7' or less
        panels = 4
    elif door_height <= 96:  # 8'
        panels = 4
    elif door_height <= 108:  # 9'
        panels = 5
    elif door_height <= 120:  # 10'
        panels = 5
    elif door_height <= 144:  # 12'
        panels = 6
    elif door_height <= 168:  # 14'
        panels = 7
    else:
        panels = 8

    return {
        "success": True,
        "data": {
            "panels": panels,
            "door_height": door_height,
            "calculated": True
        }
    }


@router.post("/calculate-struts")
async def calculate_struts(door_width: int, door_height: int = 84, window: str = "no"):
    """Calculate strut quantity based on door width and height"""
    # Strut calculation based on door size
    if door_width <= 108:  # Up to 9'
        struts = 1
    elif door_width <= 192:  # Up to 16'
        struts = 2
    else:
        struts = 3

    # Add extra strut for windows or tall doors
    has_windows = window.lower() in ["yes", "true", "1"]
    if has_windows and door_height > 96:
        struts += 1

    return {
        "success": True,
        "data": {
            "struts": struts,
            "door_width": door_width,
            "door_height": door_height,
            "has_windows": has_windows,
            "calculated": True
        }
    }


def _format_door_description(door: DoorConfigRequest) -> str:
    """
    Format door description for BC quote comment line.

    Format: ({qty}) {width}'x{height}' {series}, {color}, {design}, {track}" HW, {lift}
    Example: (1) 10x9 TX450, WHITE, UDC, 2" HW, STD LIFT
    """
    # Convert inches to feet for display
    width_ft = door.doorWidth // 12
    height_ft = door.doorHeight // 12

    # Get track size display
    track_display = f"{door.trackThickness}\" HW" if door.trackThickness else "2\" HW"

    # Determine lift type from track radius
    lift_type = "STD LIFT"
    if door.trackRadius == "12":
        lift_type = "LHR"

    # Format: (qty) WxH SERIES, COLOR, DESIGN, TRACK HW, LIFT
    return f"({door.doorCount}) {width_ft}x{height_ft} {door.doorSeries}, {door.panelColor}, {door.panelDesign}, {track_display}, {lift_type}"


# Define the standard line item ordering for BC quotes
# See docs/BC_QUOTE_FORMAT.md for full specification
LINE_ORDER = [
    "COMMENT",       # 1. Door description
    "PANEL",         # 2. Panels
    "RETAINER",      # 3. Retainer
    "ASTRAGAL",      # 4. Astragal
    "STRUT",         # 5. Struts
    "WINDOW",        # 6. Windows (if applicable)
    "TRACK",         # 7. Track
    "HIGHLIFT_TRACK",# 7b. Highlift track (if applicable)
    "HARDWARE",      # 8. Hardware box
    "SPRING",        # 9. Springs
    "SPRING_ACCESSORY",  # 9b. Winders, plugs
    "SHAFT",         # 9c. Shaft
    "WEATHER_STRIPPING", # 10. Weather seal
    "ACCESSORY",     # 11. Accessories
]


def _sort_parts_by_category(parts: List[dict]) -> List[dict]:
    """Sort parts list according to BC quote line ordering standard."""
    def sort_key(part):
        category = part.get("category", "OTHER")
        try:
            return LINE_ORDER.index(category)
        except ValueError:
            return len(LINE_ORDER)  # Unknown categories go at end

    return sorted(parts, key=sort_key)


@router.post("/generate-quote")
async def generate_door_quote(request: QuoteGenerationRequest):
    """
    Generate a quote directly in Business Central.

    This endpoint:
    1. Gets BC part numbers for each door configuration
    2. Creates a sales quote in BC
    3. Adds all parts as line items (with proper ordering per BC_QUOTE_FORMAT.md)
    4. Returns the BC quote number and details

    Line items are added in the following order for each door:
    1. Comment (door description)
    2. Panels
    3. Retainer
    4. Astragal
    5. Struts
    6. Windows (if applicable)
    7. Track
    8. Hardware box
    9. Springs
    10. Weather seal
    11. Accessories
    """
    try:
        # Step 1: Get parts for all doors with proper ordering
        all_lines = []  # Ordered lines ready for BC
        parts_by_door = []

        for i, door in enumerate(request.doors):
            door_index = i + 1

            # Generate door description for comment line
            door_desc = _format_door_description(door)

            # Add comment line FIRST (describes this door)
            all_lines.append({
                "lineType": "Comment",
                "description": door_desc,
                "category": "COMMENT",
                "door_index": door_index
            })

            # Get parts for this door configuration
            config_dict = {
                "doorType": door.doorType,
                "doorSeries": door.doorSeries,
                "doorWidth": door.doorWidth,
                "doorHeight": door.doorHeight,
                "doorCount": door.doorCount,
                "panelColor": door.panelColor,
                "panelDesign": door.panelDesign,
                "windowInsert": door.windowInsert,
                "windowSection": door.windowSection,
                "glazingType": door.glazingType,
                "trackRadius": door.trackRadius,
                "trackThickness": door.trackThickness,
                "hardware": door.hardware,
                "operator": door.operator,
            }

            door_parts = get_parts_for_door_config(config_dict)
            parts_list = door_parts.get("parts_list", [])

            # Sort parts by standard line ordering
            sorted_parts = _sort_parts_by_category(parts_list)

            # Add door index to each part for tracking
            for part in sorted_parts:
                part["door_index"] = door_index
                all_lines.append(part)

            parts_by_door.append({
                "door_index": door_index,
                "door_description": door_desc,
                "parts": door_parts
            })

        # Step 2: Create BC Quote
        quote_data = {}

        # Set customer - use customerId if provided, otherwise use default
        if request.customerId:
            quote_data["customerId"] = request.customerId
        else:
            # Default to standard customer number
            quote_data["customerNumber"] = "CASH"

        # Set external document number for tracking
        po_number = request.poNumber or f"CFG-{len(request.doors)}-DOORS"
        quote_data["externalDocumentNumber"] = po_number

        # Create the quote in BC
        bc_quote = bc_client.create_sales_quote(quote_data)
        bc_quote_id = bc_quote.get("id")
        bc_quote_number = bc_quote.get("number")

        logger.info(f"Created BC quote: {bc_quote_number} (ID: {bc_quote_id})")

        # Step 3: Add line items to the quote in proper order
        lines_added = 0
        lines_failed = []

        for line in all_lines:
            try:
                if line.get("lineType") == "Comment":
                    # Add comment line for door description
                    line_data = {
                        "lineType": "Comment",
                        "description": line["description"]
                    }
                else:
                    # Add item line
                    line_data = {
                        "lineType": "Item",
                        "lineObjectNumber": line["part_number"],
                        "description": line.get("description", ""),
                        "quantity": line["quantity"],
                    }

                bc_client.add_quote_line(bc_quote_id, line_data)
                lines_added += 1
                logger.debug(f"Added line: {line.get('part_number', line.get('description', ''))[:30]}")

            except Exception as line_error:
                part_id = line.get("part_number", line.get("description", "unknown"))
                logger.warning(f"Failed to add line {part_id}: {line_error}")

                # For item lines that fail, try adding as comment instead
                if line.get("lineType") != "Comment" and line.get("part_number"):
                    try:
                        comment_line = {
                            "lineType": "Comment",
                            "description": f"{line['part_number']} - {line.get('description', '')} (Qty: {line['quantity']})"
                        }
                        bc_client.add_quote_line(bc_quote_id, comment_line)
                        lines_added += 1
                    except Exception:
                        lines_failed.append({
                            "part_number": line.get("part_number", "N/A"),
                            "error": str(line_error)
                        })
                else:
                    lines_failed.append({
                        "part_number": part_id,
                        "error": str(line_error)
                    })

        # Build door summary for response
        door_summaries = []
        for door in request.doors:
            door_summaries.append({
                "series": door.doorSeries,
                "size": f"{door.doorWidth}\"x{door.doorHeight}\"",
                "color": door.panelColor,
                "quantity": door.doorCount
            })

        # Count actual parts (excluding comments)
        total_parts = sum(1 for line in all_lines if line.get("lineType") != "Comment")

        return {
            "success": True,
            "data": {
                "bc_quote_number": bc_quote_number,
                "bc_quote_id": bc_quote_id,
                "po_number": po_number,
                "tag_name": request.tagName or "Door Configurator Quote",
                "doors": door_summaries,
                "total_doors": len(request.doors),
                "total_parts": total_parts,
                "lines_added": lines_added,
                "lines_failed": lines_failed if lines_failed else None,
                "parts_summary": [l for l in all_lines if l.get("lineType") != "Comment"]
            },
            "message": f"BC Quote {bc_quote_number} created with {lines_added} line items"
        }

    except Exception as e:
        logger.error(f"Error generating BC quote: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/dimension-constraints/{series_id}")
async def get_dimension_constraints(series_id: str):
    """Get dimension constraints for a door series"""
    constraints = {
        "KANATA": {
            "minWidth": 60,
            "maxWidth": 216,
            "minHeight": 72,
            "maxHeight": 192,
            "widthIncrements": 3,
            "heightIncrements": 3,
            "sectionHeights": [18, 21, 24]
        },
        "CRAFT": {
            "availableWidths": [96, 108, 144, 192],
            "availableHeights": [84, 96],
            "sectionHeights": [28, 32],
            "minHeaderClearance": 23
        },
        "AL976": {
            "minWidth": 60,
            "maxWidth": 288,
            "minHeight": 72,
            "maxHeight": 192,
        },
        "TX450": {
            "minWidth": 72,
            "maxWidth": 288,
            "minHeight": 84,
            "maxHeight": 240,
        },
        "TX500": {
            "minWidth": 72,
            "maxWidth": 288,
            "minHeight": 84,
            "maxHeight": 240,
        },
    }

    if series_id not in constraints:
        # Default constraints
        return {
            "success": True,
            "data": {
                "minWidth": 60,
                "maxWidth": 216,
                "minHeight": 72,
                "maxHeight": 192,
            }
        }

    return {"success": True, "data": constraints[series_id]}


@router.post("/get-part-numbers")
async def get_part_numbers(config: DoorConfigRequest):
    """
    Get BC part numbers for a door configuration.

    Returns a list of part numbers needed to fulfill the door configuration,
    organized by category (panel, track, hardware, spring, etc.)
    """
    try:
        # Convert request to dict for part number service
        config_dict = {
            "doorType": config.doorType,
            "doorSeries": config.doorSeries,
            "doorWidth": config.doorWidth,
            "doorHeight": config.doorHeight,
            "doorCount": config.doorCount,
            "panelColor": config.panelColor,
            "panelDesign": config.panelDesign,
            "windowInsert": config.windowInsert,
            "windowSection": config.windowSection,
            "glazingType": config.glazingType,
            "trackRadius": config.trackRadius,
            "trackThickness": config.trackThickness,
            "hardware": config.hardware,
            "operator": config.operator,
        }

        # Get parts from service
        parts_summary = get_parts_for_door_config(config_dict)

        return {
            "success": True,
            "data": parts_summary,
            "message": f"Found {parts_summary['total_parts']} part numbers"
        }

    except Exception as e:
        logger.error(f"Error getting part numbers: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/get-parts-for-quote")
async def get_parts_for_quote(request: QuoteGenerationRequest):
    """
    Get BC part numbers for an entire quote (multiple doors).

    Returns consolidated part list for all doors in the quote.
    """
    try:
        all_parts = []
        parts_by_door = []

        for i, door in enumerate(request.doors):
            config_dict = {
                "doorType": door.doorType,
                "doorSeries": door.doorSeries,
                "doorWidth": door.doorWidth,
                "doorHeight": door.doorHeight,
                "doorCount": door.doorCount,
                "panelColor": door.panelColor,
                "panelDesign": door.panelDesign,
                "windowInsert": door.windowInsert,
                "windowSection": door.windowSection,
                "glazingType": door.glazingType,
                "trackRadius": door.trackRadius,
                "trackThickness": door.trackThickness,
                "hardware": door.hardware,
                "operator": door.operator,
            }

            door_parts = get_parts_for_door_config(config_dict)

            parts_by_door.append({
                "door_index": i + 1,
                "door_description": f"{door.doorSeries} {door.doorWidth}\"x{door.doorHeight}\" {door.panelColor}",
                "parts": door_parts
            })

            # Add to consolidated list
            all_parts.extend(door_parts.get("parts_list", []))

        # Consolidate duplicate parts
        consolidated = {}
        for part in all_parts:
            pn = part["part_number"]
            if pn in consolidated:
                consolidated[pn]["quantity"] += part["quantity"]
            else:
                consolidated[pn] = part.copy()

        return {
            "success": True,
            "data": {
                "total_doors": len(request.doors),
                "total_unique_parts": len(consolidated),
                "parts_by_door": parts_by_door,
                "consolidated_parts": list(consolidated.values())
            },
            "message": f"Generated part list for {len(request.doors)} door(s)"
        }

    except Exception as e:
        logger.error(f"Error getting parts for quote: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/calculate-door")
async def calculate_door_specifications(request: DoorCalculationRequest):
    """
    Calculate complete door specifications including:
    - Panel configuration (sections, gauge)
    - Door weight breakdown
    - Spring selection (coil, wire, length, cycles)
    - Drum selection with cable specifications
    - Shaft configuration
    - Track configuration
    - Hardware component list

    Based on Thermalex Door Weight Calculator formulas.
    """
    try:
        # Convert feet + inches to total inches
        width_inches = (request.widthFeet * 12) + request.widthInches
        height_inches = (request.heightFeet * 12) + request.heightInches

        if width_inches < 60 or width_inches > 360:
            raise HTTPException(status_code=400, detail="Door width must be between 60\" and 360\" (5' to 30')")
        if height_inches < 60 or height_inches > 288:
            raise HTTPException(status_code=400, detail="Door height must be between 60\" and 288\" (5' to 24')")

        # Calculate door
        calc = door_calculator.calculate_door(
            door_model=request.doorModel,
            width_inches=width_inches,
            height_inches=height_inches,
            lift_type=request.liftType,
            track_size=request.trackSize,
            window_type=request.windowType,
            window_qty=request.windowQty,
            double_end_caps=request.doubleEndCaps,
            heavy_duty_hinges=request.heavyDutyHinges,
            target_cycles=request.targetCycles,
        )

        # Get summary
        summary = door_calculator.get_calculation_summary(calc)

        return {
            "success": True,
            "data": summary,
            "message": f"Calculated specifications for {request.doorModel} {width_inches}\"x{height_inches}\""
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error calculating door specifications: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/lift-types")
async def get_lift_types():
    """Get available lift type configurations"""
    lift_types = [
        {"id": "standard_15", "name": "Standard Lift 15\" Radius", "description": "Standard residential/commercial", "radius": 15},
        {"id": "standard_12", "name": "Standard Lift 12\" Radius", "description": "Low headroom option", "radius": 12},
        {"id": "lhr_front", "name": "Low Head Room Front Mount", "description": "Front mount LHR hardware", "radius": 15},
        {"id": "lhr_rear", "name": "Low Head Room Rear Mount", "description": "Rear mount LHR hardware", "radius": 15},
        {"id": "high_lift", "name": "High Lift", "description": "For ceilings higher than standard", "radius": 15},
        {"id": "vertical", "name": "Vertical Lift", "description": "Door lifts straight up", "radius": None},
    ]
    return {"success": True, "data": lift_types}


@router.get("/spring-cycles")
async def get_spring_cycles():
    """Get available spring cycle options"""
    cycles = [
        {"id": 10000, "name": "10,000 Cycles", "description": "Standard residential (3-5 years)", "recommended": "residential"},
        {"id": 15000, "name": "15,000 Cycles", "description": "Extended residential (5-7 years)", "recommended": "residential"},
        {"id": 25000, "name": "25,000 Cycles", "description": "Light commercial (7-10 years)", "recommended": "commercial"},
        {"id": 50000, "name": "50,000 Cycles", "description": "Standard commercial (10+ years)", "recommended": "commercial"},
        {"id": 100000, "name": "100,000 Cycles", "description": "Heavy commercial/high cycle", "recommended": "commercial"},
    ]
    return {"success": True, "data": cycles}


@router.get("/drum-models")
async def get_drum_models():
    """Get available drum models with specifications"""
    from app.services.door_calculator_service import DRUM_TABLE

    drums = []
    for model, spec in DRUM_TABLE.items():
        drums.append({
            "model": model,
            "maxHeight": spec["max_height"],
            "maxWeight": spec["max_weight"],
            "offset": spec["offset"],
            "cableDiameters": spec["cables"],
            "liftType": spec["lift"],
            "radius": spec["radius"],
        })

    return {"success": True, "data": drums}


@router.get("/window-types")
async def get_commercial_window_types():
    """Get commercial window types with weights"""
    window_types = [
        {"id": "18x8", "name": "18\" x 8\" Thermopane", "section": "21\" or 24\""},
        {"id": "24x12", "name": "24\" x 12\" Thermopane", "section": "24\" only"},
        {"id": "34x16", "name": "34\" x 16\" Thermopane", "section": "24\" only"},
    ]
    return {"success": True, "data": window_types}


@router.post("/calculate-spring")
async def calculate_spring_only(
    door_weight: float,
    door_height: int,
    drum_model: str = "D525-216",
    target_cycles: int = 10000
):
    """
    Calculate spring specifications for a given door weight.

    Args:
        door_weight: Total door weight in lbs
        door_height: Door height in inches
        drum_model: Drum model to use
        target_cycles: Target spring cycles
    """
    try:
        from app.services.door_calculator_service import DRUM_TABLE

        if drum_model not in DRUM_TABLE:
            raise HTTPException(status_code=400, detail=f"Unknown drum model: {drum_model}")

        drum_spec = DRUM_TABLE[drum_model]

        # Create a mock drums object
        from app.services.door_calculator_service import DrumSelection
        drums = DrumSelection(
            model=drum_model,
            offset=drum_spec["offset"],
            cable_diameter=drum_spec["cables"][1] if door_weight > 600 else drum_spec["cables"][0],
            cable_length=door_height + 8
        )

        # Calculate springs
        springs = door_calculator._calculate_springs(
            door_weight=door_weight,
            height_inches=door_height,
            drums=drums,
            target_cycles=target_cycles
        )

        if springs is None:
            raise HTTPException(status_code=400, detail="Could not calculate springs for given specifications")

        return {
            "success": True,
            "data": {
                "quantity": springs.quantity,
                "coil_diameter": springs.coil_diameter,
                "wire_diameter": springs.wire_diameter,
                "length": springs.length,
                "cycles": springs.cycles,
                "turns": springs.turns,
                "galvanized": springs.galvanized,
            }
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error calculating springs: {e}")
        raise HTTPException(status_code=500, detail=str(e))
