"""
Door Configurator API - Provides configuration options for building door quotes
Based on Upwardor brochure specifications (Residential 2025 & Commercial 2023)
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
import logging

from app.services.part_number_service import get_parts_for_door_config, part_number_service, DoorConfiguration
from app.services.door_calculator_service import door_calculator, calculate_door_from_config
from app.services.shop_drawing_service import calculate_shop_drawing_geometry
from app.services.spring_data_service import get_bc_spring_inventory
from app.services.pricing_service import calculate_selling_price, warm_bc_cost_cache
from app.services.quote_review_service import save_quote_snapshot
from app.services.freight_service import calculate_freight, get_freight_config
from app.integrations.bc.client import bc_client
from app.db.database import get_db
from app.db.models import BCCustomer

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/door-config", tags=["door-configurator"])


# ============================================================================
# CONFIGURATION DATA (from UPWARDOR_PORTAL_CONFIGURATION.md)
# ============================================================================

DOOR_TYPES = [
    {"id": "residential", "name": "Residential", "description": "Standard residential garage doors"},
    {"id": "commercial", "name": "Commercial", "description": "Heavy-duty commercial doors"},
    {"id": "aluminium", "name": "Aluminium", "description": "Full-view aluminum and glass doors"},
    # {"id": "executive", "name": "Executive", "description": "Premium wood overlay doors"},  # TODO: re-enable when built out
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
            "id": "TX380",
            "name": "Thermalex TX380",
            "description": "Commercial insulated door — max 16' wide × 16' tall",
            "specs": {
                "features": ["Commercial Grade Insulated"],
                "warranty": "10 Year Limited",
                "maxWidth": 192,
                "maxHeight": 192,
            }
        },
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
            "partPrefix": "PN97",
            "glazingType": "glass",
            "glazingTypes": [
                {"id": "glass", "name": "Glass"},
                {"id": "polycarbonate", "name": "Polycarbonate"},
            ],
            "glazingOptions": [
                {"id": "CLEAR", "name": "Clear"},
                {"id": "ETCHED", "name": "Etched"},
                {"id": "SUPER_GREY", "name": "Super Grey"},
            ],
            "polycarbonateOptions": [
                {"id": "CLEAR", "name": "Clear"},
                {"id": "LIGHT_BRONZE", "name": "Light Bronze"},
                {"id": "DARK_BRONZE", "name": "Dark Bronze"},
                {"id": "WHITE_OPAL", "name": "White Opal"},
            ],
            "paneTypes": [
                {"id": "INSULATED", "name": "Insulated (Thermal)"},
                {"id": "SINGLE", "name": "Single Pane"},
            ],
            "finishes": [
                {"id": "CLEAR_ANODIZED", "name": "Clear Anodized", "code": "0"},
                {"id": "WHITE", "name": "White", "code": "3"},
                {"id": "BLACK_ANODIZED", "name": "Black Anodized", "code": "8"},
            ],
            "specs": {
                "thickness": "1 3/4\" (44.5mm)",
                "material": "Extruded 6063-T6 Aluminum",
                "maxWidth": 240,  # 20' in inches
                "finishWarranty": "5 Year Limited",
                "workmanshipWarranty": "1 Year Limited"
            }
        },
        {
            "id": "PANORAMA",
            "name": "Panorama",
            "description": "Full-view aluminum door — polycarbonate panels",
            "categoryValue": "67f7c1c39cf0ed4a3b00baea",
            "partPrefix": "PN80",
            "glazingType": "polycarbonate",
            "glazingOptions": [
                {"id": "CLEAR", "name": "Clear"},
                {"id": "LIGHT_BRONZE", "name": "Light Bronze"},
                {"id": "DARK_BRONZE", "name": "Dark Bronze"},
                {"id": "WHITE_OPAL", "name": "White Opal"},
            ],
            "finishes": [
                {"id": "CLEAR_ANODIZED", "name": "Clear Anodized", "code": "00"},
            ],
            "customFinishNote": "Custom colors available — contact us directly for a quote.",
            "specs": {
                "thickness": "1 3/4\" (44.5mm)",
                "material": "Extruded Aluminum",
                "maxWidth": 240,  # 20' in inches
                "finishWarranty": "5 Year Limited",
                "workmanshipWarranty": "1 Year Limited"
            }
        },
        {
            "id": "SOLALITE",
            "name": "Solalite",
            "description": "Thermal-break aluminum door — polycarbonate panels",
            "categoryValue": "67f7c1c39cf0ed4a3b00baea",
            "partPrefix": "PN20",
            "glazingType": "polycarbonate",
            "glazingOptions": [
                {"id": "CLEAR", "name": "Clear"},
                {"id": "LIGHT_BRONZE", "name": "Light Bronze"},
                {"id": "DARK_BRONZE", "name": "Dark Bronze"},
                {"id": "WHITE_OPAL", "name": "White Opal"},
            ],
            "finishes": [
                {"id": "CLEAR_ANODIZED", "name": "Clear Anodized", "code": "0"},
            ],
            "customFinishNote": "Custom colors available — contact us directly for a quote.",
            "specs": {
                "thickness": "1 3/4\" (44.5mm)",
                "material": "Extruded Aluminum with Thermal Break",
                "maxWidth": 240,  # 20' in inches
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
    # Solid colors with RAL codes
    "KANATA": [
        # Solid Colors (RAL)
        {"id": "WHITE", "name": "White", "hex": "#F4F4F4", "ral": "RAL 9003", "type": "solid"},
        {"id": "BLACK", "name": "Black", "hex": "#282828", "ral": "RAL 9004", "type": "solid"},
        {"id": "NEW_BROWN", "name": "New Brown", "hex": "#4C4842", "ral": "RAL 7022", "type": "solid"},
        {"id": "HAZELWOOD", "name": "Hazelwood", "hex": "#756F61", "ral": "RAL 7006", "type": "solid"},
        {"id": "BRONZE", "name": "Bronze", "hex": "#6C6961", "ral": "RAL 7039", "type": "solid"},
        {"id": "STEEL_GREY", "name": "Steel Grey", "hex": "#7D7F7D", "ral": "RAL 7037", "type": "solid"},
        {"id": "SANDTONE", "name": "Sandtone", "hex": "#A4957D", "ral": "RAL 1019", "type": "solid"},
        {"id": "IRON_ORE", "name": "Iron Ore", "hex": "#2F3234", "ral": "RAL 7021", "type": "solid"},
        # Woodgrain finishes
        {"id": "WALNUT", "name": "Walnut", "hex": "#4A3728", "type": "woodgrain", "grain": ["#4A3728", "#5D432C", "#3D2B1F"]},
        {"id": "ENGLISH_CHESTNUT", "name": "English Chestnut", "hex": "#6B4423", "type": "woodgrain", "grain": ["#6B4423", "#8B5A2B", "#5C3317"]},
        {"id": "FRENCH_OAK", "name": "French Oak", "hex": "#C4A35A", "type": "woodgrain", "grain": ["#C4A35A", "#D4B56A", "#B49A4A"]},
    ],
    "CRAFT": [
        {"id": "WHITE", "name": "White", "hex": "#F4F4F4", "ral": "RAL 9003", "type": "solid"},
        {"id": "SANDTONE", "name": "Sandtone", "hex": "#A4957D", "ral": "RAL 1019", "type": "solid"},
        {"id": "WALNUT", "name": "Walnut", "hex": "#4A3728", "type": "woodgrain", "grain": ["#4A3728", "#5D432C", "#3D2B1F"], "note": "7' door only"},
        {"id": "ENGLISH_CHESTNUT", "name": "English Chestnut", "hex": "#6B4423", "type": "woodgrain", "grain": ["#6B4423", "#8B5A2B", "#5C3317"]},
        {"id": "IRON_ORE", "name": "Iron Ore", "hex": "#2F3234", "ral": "RAL 7021", "type": "solid"},
        {"id": "FRENCH_OAK", "name": "French Oak", "hex": "#C4A35A", "type": "woodgrain", "grain": ["#C4A35A", "#D4B56A", "#B49A4A"]},
    ],
    "COMMERCIAL": [
        {"id": "WHITE", "name": "White", "hex": "#F4F4F4", "ral": "RAL 9003", "type": "solid"},
        {"id": "BLACK", "name": "Black", "hex": "#282828", "ral": "RAL 9004", "type": "solid"},
        {"id": "NEW_BROWN", "name": "New Brown", "hex": "#4C4842", "ral": "RAL 7022", "type": "solid"},
        {"id": "STEEL_GREY", "name": "Steel Grey", "hex": "#7D7F7D", "ral": "RAL 7037", "type": "solid"},
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
        {"id": "SH", "code": "SH", "name": "Sheridan", "type": "Raised Panel (Short)"},
        {"id": "SHXL", "code": "SHXL", "name": "Sheridan XL", "type": "Raised Panel (Long)"},
        {"id": "BC", "code": "BC", "name": "Bronte Creek", "type": "Carriage House (Short)"},
        {"id": "BCXL", "code": "BCXL", "name": "Bronte Creek XL", "type": "Carriage House (Long)"},
        {"id": "TRAFALGAR", "code": "TRAFALGAR", "name": "Trafalgar", "type": "Ribbed Panel"},
        {"id": "FLUSH", "code": "FLUSH", "name": "Flush", "type": "Flush/Flat"},
    ],
    "CRAFT": [
        {"id": "MUSKOKA", "code": "MUSKOKA", "name": "Muskoka", "type": "X-Brace Barn Door"},
        {"id": "DENISON", "code": "DENISON", "name": "Denison", "type": "Raised Panel Grid"},
        {"id": "GRANVILLE", "code": "GRANVILLE", "name": "Granville", "type": "Raised Panels (Wide)"},
        {"id": "FLUSH", "code": "FLUSH", "name": "Flush", "type": "Flush/Flat"},
    ],
    "COMMERCIAL": [
        # Standard commercial (TX450, TX500): UDC only
        {"id": "UDC", "code": "UDC", "name": "UDC (Undercoated)", "type": "Commercial Standard"},
    ],
    "COMMERCIAL_20": [
        # TX450-20 and TX500-20: Flush and UDC designs
        {"id": "FLUSH", "code": "FLUSH", "name": "Flush", "type": "Flush/Flat"},
        {"id": "UDC", "code": "UDC", "name": "UDC (Undercoated)", "type": "Commercial Standard"},
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

WINDOW_INSERTS_LONG = {
    # Long window inserts — fit SHXL/BCXL stamps or span 2 short stamps
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

WINDOW_INSERTS_SHORT = {
    # Short window inserts — fit in a single SH/BC/TRAF/FLUSH stamp
    "STOCKTON": [
        {"id": "STOCKTON_SHORT", "name": "Stockton Short"},
        {"id": "STOCKTON_SHORT_ARCHED", "name": "Stockton Short Arched"},
    ],
}

# Combined for backward compatibility
WINDOW_INSERTS = WINDOW_INSERTS_LONG

# Commercial window sizes — no decorative inserts on commercial doors
# Frame colors: standard black, optional white. Inside always white.
COMMERCIAL_WINDOW_TYPES = {
    "THERMOPANE": [
        {"id": "24X12_THERMOPANE", "name": "24\" x 12\" Thermopane", "width": 24, "height": 12, "sectionType": "24\" section", "glassOptions": ["thermal"]},
        {"id": "34X16_THERMOPANE", "name": "34\" x 16\" Thermopane", "width": 34, "height": 16, "sectionType": "24\" section", "glassOptions": ["thermal"]},
        {"id": "18X8_THERMOPANE", "name": "18\" x 8\" Thermopane", "width": 18, "height": 8, "sectionType": "21\" or 24\" section", "glassOptions": ["thermal"]},
    ],
    "FULL VIEW": [
        {"id": "V130G", "name": "V130G Full View (Glass)", "width": "full", "height": "full", "sectionType": "Replaces insulated section", "glassOptions": ["single", "thermal"], "glassColors": ["CLEAR", "ETCHED", "SUPER_GREY"], "material": "AL976", "note": "Full aluminum/glass section", "series": ["TX450", "TX450-20"]},
        {"id": "PANORAMA", "name": "Panorama Full View (Polycarbonate)", "width": "full", "height": "full", "sectionType": "Replaces insulated section", "glazingType": "polycarbonate", "glassColors": ["CLEAR", "LIGHT_BRONZE", "DARK_BRONZE", "WHITE_OPAL"], "material": "PANORAMA", "note": "Full aluminum/polycarbonate section", "series": ["TX450", "TX450-20"]},
        {"id": "V230G", "name": "V230G Full View (Glass)", "width": "full", "height": "full", "sectionType": "Replaces insulated section", "glassOptions": ["single", "thermal"], "glassColors": ["CLEAR", "ETCHED", "SUPER_GREY"], "material": "AL976", "note": "Full aluminum/glass section (TX500)", "series": ["TX500", "TX500-20"]},
    ],
}

COMMERCIAL_WINDOW_FRAME_COLORS = [
    {"id": "BLACK", "name": "Black Frame", "hex": "#1a1a1a", "description": "Black outside, white inside", "default": True},
    {"id": "WHITE", "name": "White Frame", "hex": "#FFFFFF", "description": "White outside, white inside"},
]

# Commercial window sizes lookup for spacing calculator
COMMERCIAL_WINDOW_SIZES = {
    "24X12_THERMOPANE": {"width": 24, "height": 12},
    "34X16_THERMOPANE": {"width": 34, "height": 16},
    "18X8_THERMOPANE": {"width": 18, "height": 8},
}

GLAZING_OPTIONS = {
    "standard": [
        {"id": "CLEAR", "name": "Clear Glass"},
        {"id": "INSULATED", "name": "Insulated Glass"},
        {"id": "ETCHED", "name": "Etched Glass"},
        {"id": "TEMPERED", "name": "Tempered Glass"},
    ],
    "AL976": [
        {"id": "SINGLE", "name": "Single Glass"},
        {"id": "INSULATED", "name": "Insulated Glass"},
        {"id": "ETCHED", "name": "Etched Glass"},
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
        {"id": "12", "name": "12\" Radius (Standard Residential)", "minClearance": 12, "note": "2\" track only", "allowedThickness": ["2"]},
        {"id": "15", "name": "15\" Radius (Standard Commercial)", "minClearance": 15, "allowedThickness": ["2", "3"]},
        {"id": "20", "name": "20\" Radius (Craft Series)", "minClearance": 20, "allowedThickness": ["2", "3"]},
    ],
    "liftType": [
        {"id": "standard", "name": "Standard Lift", "description": "Standard radius track"},
        {"id": "low_headroom", "name": "Low Headroom (2\" Double Track)", "description": "2\" double track lowhead - for minimal headroom clearance", "forcedTrackSize": 2},
        {"id": "high_lift", "name": "High Lift", "description": "Extra vertical track above door — specify inches of high lift"},
        {"id": "vertical", "name": "Vertical Lift", "description": "Full vertical track — door lifts straight up, no horizontal"},
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
    {"id": "panels", "name": "Door Panels", "description": "Insulated door sections", "default": True},
    {"id": "tracks", "name": "Tracks", "description": "Vertical and horizontal track system", "default": True},
    {"id": "springs", "name": "Springs", "description": "Torsion spring assembly", "default": True},
    {"id": "struts", "name": "Struts", "description": "Reinforcing struts", "default": True},
    {"id": "hardwareKits", "name": "Hardware Kits", "description": "Hinges, rollers, brackets", "default": True},
    {"id": "weatherStripping", "name": "Weather Stripping", "description": "Perimeter seal", "default": True},
    {"id": "bottomRetainer", "name": "Bottom Retainer", "description": "PVC bottom seal", "default": True},
    {"id": "shafts", "name": "Shafts", "description": "Torsion shaft", "default": True},
]

from app.services.operator_service import get_operator_options as _get_op_options, get_all_operator_options


# ============================================================================
# PYDANTIC MODELS
# ============================================================================

class WindowPosition(BaseModel):
    """Position of a window within a stamp grid (section x column)"""
    section: int  # 1-based section number (1 = top)
    col: int  # 0-based column index (0 = left)

class DoorConfigRequest(BaseModel):
    doorType: str
    doorSeries: str
    doorWidth: int  # in inches
    doorHeight: int  # in inches
    doorCount: int = 1
    panelColor: str
    panelDesign: str
    hasWindows: bool = False
    windowInsert: Optional[str] = None
    windowSize: str = "long"  # 'short' (GK15-10xxx) or 'long' (GK15-11xxx)
    windowPositions: Optional[List[WindowPosition]] = []  # Multi-stamp window positions
    windowSection: Optional[int] = None  # Legacy: single section (for backward compatibility)
    windowQty: int = 0  # Commercial: V130G section count or window qty
    windowPanels: Optional[Dict[str, dict]] = None  # Per-panel window config: {"2": {"qty": 3}, "4": {"qty": 2}}
    windowFrameColor: str = "BLACK"  # Commercial window frame color
    glazingType: Optional[str] = None
    glassPaneType: Optional[str] = None  # 'INSULATED' or 'SINGLE'
    glassColor: Optional[str] = None     # 'CLEAR', 'ETCHED', 'SUPER_GREY'
    trackRadius: str = "15"
    trackThickness: str = "2"
    trackMount: str = "bracket"  # 'bracket' or 'angle'
    liftType: str = "standard"  # 'standard', 'low_headroom', 'high_lift', 'vertical'
    highLiftInches: Optional[int] = None
    hardware: Dict[str, bool] = {}
    operator: Optional[str] = None
    operatorAccessories: Optional[List[str]] = None
    notes: Optional[str] = None
    targetCycles: int = 10000
    shaftType: str = "auto"  # 'auto', 'single', 'split'
    includeTopSeal: bool = False  # optional upgrade for commercial doors


class QuoteGenerationRequest(BaseModel):
    doors: List[DoorConfigRequest]
    poNumber: Optional[str] = None
    tagName: Optional[str] = None
    customerId: Optional[str] = None
    deliveryType: str = "delivery"  # "delivery" or "pickup"


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
    highLiftInches: Optional[int] = None  # extra inches above door for high_lift
    doorType: str = "commercial"  # 'residential' or 'commercial'


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
        "TX450": "COMMERCIAL",
        "TX500": "COMMERCIAL",
        "TX450-20": "COMMERCIAL_20",
        "TX500-20": "COMMERCIAL_20",
    }
    design_key = design_map.get(series_id, "KANATA")
    designs = PANEL_DESIGNS.get(design_key, [])
    return {"success": True, "data": designs}


@router.get("/window-inserts")
async def get_window_inserts(door_type: Optional[str] = None):
    """Get available window insert styles. Commercial doors have no decorative inserts."""
    if door_type == "commercial":
        return {"success": True, "data": {}}
    return {"success": True, "data": WINDOW_INSERTS_LONG, "dataShort": WINDOW_INSERTS_SHORT}


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
    """Get operator options for door type, grouped by brand"""
    op_type = "commercial" if door_type == "commercial" else "residential"
    return {"success": True, "data": _get_op_options(op_type)}


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
            "windowInserts": WINDOW_INSERTS_LONG,
            "windowInsertsShort": WINDOW_INSERTS_SHORT,
            "commercialWindowTypes": COMMERCIAL_WINDOW_TYPES,
            "commercialWindowFrameColors": COMMERCIAL_WINDOW_FRAME_COLORS,
            "commercialWindowSizes": COMMERCIAL_WINDOW_SIZES,
            "glazingOptions": GLAZING_OPTIONS,
            "trackOptions": TRACK_OPTIONS,
            "hardwareOptions": HARDWARE_OPTIONS,
            "operatorOptions": get_all_operator_options(),
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

    # Determine lift type
    lift_type_raw = getattr(door, 'liftType', 'standard') or 'standard'
    if lift_type_raw == "low_headroom" or door.trackRadius == "12":
        lift_type = "LHR"
    elif lift_type_raw == "high_lift":
        lift_type = "HIGH LIFT"
    elif lift_type_raw == "vertical":
        lift_type = "VERTICAL"
    else:
        lift_type = "STD LIFT"

    # Format: (qty) WxH SERIES, COLOR, DESIGN, TRACK HW, LIFT
    return f"({door.doorCount}) {width_ft}x{height_ft} {door.doorSeries}, {door.panelColor}, {door.panelDesign}, {track_display}, {lift_type}"


# Define the standard line item ordering for BC quotes
# See docs/BC_QUOTE_FORMAT.md for full specification
# Categories must match those used in part_number_service.py (lowercase)
LINE_ORDER = [
    "comment",           # 1. Door description
    "panel",             # 2. Panels (PN45, PN46, PN65, PN95, etc.)
    "v130g_section",     # 2b. V130G full-view sections (right after panels)
    "v130g_glass",       # 2c. V130G glass (with sections)
    "aluminum_section",  # 2d. Aluminum sections (AL976/Panorama/Solalite)
    "aluminum_glazing",  # 2e. Aluminum polycarbonate glazing
    "aluminum_glass",    # 2e. Aluminum glass glazing
    "commercial_window", # 2f. Commercial thermopane windows
    "retainer",          # 3. Retainer (top/bottom)
    "astragal",          # 4. Astragal (bottom rubber)
    "top_seal",          # 5. Top seal (commercial/aluminium)
    "strut",             # 6. Struts
    "window",            # 7. Windows / inserts (residential)
    "track",             # 8. Track
    "highlift_track",    # 8b. Highlift track (if applicable)
    "hardware",          # 9. Hardware box
    "spring_comment",    # 9b. Spring info comment (door weight, drum, turns)
    "spring",            # 10. Springs
    "spring_accessory",  # 10b. Winders, plugs
    "shaft",             # 10c. Shaft
    "weather_stripping", # 11. Weather seal
    "accessory",         # 12. Accessories
    "operator",          # 13. Operator (if applicable)
]


def _sort_parts_by_category(parts: List[dict]) -> List[dict]:
    """Sort parts list according to BC quote line ordering standard."""
    def sort_key(part):
        category = part.get("category", "other").lower()
        try:
            return LINE_ORDER.index(category)
        except ValueError:
            return len(LINE_ORDER)  # Unknown categories go at end

    return sorted(parts, key=sort_key)


@router.post("/generate-quote")
async def generate_door_quote(request: QuoteGenerationRequest, db: Session = Depends(get_db)):
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
        # Load spring inventory from BC so quotes use stocked springs
        spring_inventory = get_bc_spring_inventory()

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
                "door_index": door_index,
                "is_door_desc": True,
            })

            # Get parts for this door configuration
            # Calculate window count from windowPositions array
            window_count = len(door.windowPositions) if door.windowPositions else (1 if door.windowSection else 0)

            config_dict = {
                "doorType": door.doorType,
                "doorSeries": door.doorSeries,
                "doorWidth": door.doorWidth,
                "doorHeight": door.doorHeight,
                "doorCount": door.doorCount,
                "panelColor": door.panelColor,
                "panelDesign": door.panelDesign,
                "windowInsert": door.windowInsert if door.hasWindows else None,
                "windowSize": door.windowSize or 'long',
                "windowPositions": [{"section": p.section, "col": p.col} for p in door.windowPositions] if door.windowPositions else [],
                "windowCount": window_count if door.hasWindows else 0,
                "windowSection": door.windowSection,
                "windowQty": door.windowQty if door.hasWindows else 0,
                "windowPanels": door.windowPanels,
                "windowFrameColor": door.windowFrameColor,
                "glazingType": door.glazingType,
                "glassPaneType": door.glassPaneType,
                "glassColor": door.glassColor,
                "trackRadius": door.trackRadius,
                "trackThickness": door.trackThickness,
                "trackMount": door.trackMount,
                "liftType": door.liftType,
                "highLiftInches": door.highLiftInches,
                "hardware": door.hardware,
                "operator": door.operator,
                "operatorAccessories": door.operatorAccessories or [],
                "targetCycles": door.targetCycles,
                "shaftType": door.shaftType,
                "includeTopSeal": getattr(door, 'includeTopSeal', False),
            }

            door_parts = get_parts_for_door_config(config_dict, spring_inventory=spring_inventory)
            parts_list = door_parts.get("parts_list", [])

            # Sort parts by standard line ordering
            sorted_parts = _sort_parts_by_category(parts_list)

            # Add door index and type to each part for tracking/pricing
            # For aluminum doors, use commercial pricing on everything EXCEPT
            # aluminum sections and glazing (which keep aluminium pricing)
            aluminum_panel_categories = {
                "aluminum_section", "aluminum_glazing", "aluminum_glass",
                "v130g_section", "v130g_glass",
            }
            window_note_emitted = False
            for part in sorted_parts:
                part["door_index"] = door_index
                if door.doorType == "aluminium" and part.get("category") not in aluminum_panel_categories:
                    part["door_type"] = "commercial"
                else:
                    part["door_type"] = door.doorType

                # Spring info comment → BC Comment line (not an item)
                if part.get("category") == "spring_comment":
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
                        "is_note": True,
                    })

            parts_by_door.append({
                "door_index": door_index,
                "door_description": door_desc,
                "parts": door_parts
            })

        # Step 2: Create BC Quote
        quote_data = {}

        # Set customer - use customerId if provided, otherwise use default
        pricing_tier = "retail"
        if request.customerId:
            quote_data["customerId"] = request.customerId
            # Look up pricing tier for this customer
            bc_customer = db.query(BCCustomer).filter(
                BCCustomer.bc_customer_id == request.customerId
            ).first()
            if bc_customer and bc_customer.pricing_tier:
                tier = bc_customer.pricing_tier.lower().strip()
                if tier in {"gold", "silver", "bronze", "retail"}:
                    pricing_tier = tier
            logger.info(f"Using pricing tier '{pricing_tier}' for customer {request.customerId}")
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

        # Warm the BC cost cache so pricing uses live production costs
        if request.customerId:
            item_pns = [l["part_number"] for l in all_lines if l.get("part_number")]
            warm_bc_cost_cache(item_pns)

        # Step 3: Validate part numbers against BC before sending
        # Find closest matches for any that don't exist
        part_warnings = []
        from app.services.bc_part_number_mapper import get_bc_mapper
        mapper = get_bc_mapper()

        for line in all_lines:
            if line.get("lineType") == "Comment" or not line.get("part_number"):
                continue
            pn = line["part_number"]
            if pn in mapper.bc_items:
                continue
            # Part doesn't exist in BC — find closest match
            prefix = pn.split("-")[0] if "-" in pn else pn[:4]
            candidates = [
                (bc_pn, item.get("displayName", ""))
                for bc_pn, item in mapper.bc_items.items()
                if bc_pn.startswith(prefix)
            ]
            candidates.sort(key=lambda x: abs(len(x[0]) - len(pn)))

            if candidates:
                closest_pn, closest_desc = candidates[0]
                part_warnings.append({
                    "original": pn,
                    "substituted": closest_pn,
                    "description": line.get("description", ""),
                    "message": f"Part {pn} not found in BC. Using closest match: {closest_pn}"
                })
                logger.warning(f"Part {pn} not in BC — substituting {closest_pn}")
                line["part_number"] = closest_pn
                line["_original_part_number"] = pn
            else:
                part_warnings.append({
                    "original": pn,
                    "substituted": None,
                    "description": line.get("description", ""),
                    "message": f"Part {pn} not found in BC and no close match. Will add as comment."
                })
                logger.warning(f"Part {pn} not in BC — no close match, will add as comment")

        # Step 4: Add line items to the quote in proper order
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

                added_line = bc_client.add_quote_line(bc_quote_id, line_data)
                lines_added += 1

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

                # BC's item price list overrides unitPrice on POST.
                # PATCH the line afterward to lock in the customer-tier price.
                if request.customerId and line.get("lineType") != "Comment":
                    part_num = line["part_number"]
                    door_tp = line.get("door_type", "residential")
                    selling_price = calculate_selling_price(
                        part_number=part_num,
                        door_type=door_tp,
                        tier=pricing_tier,
                        db=db,
                    )
                    logger.info(f"PRICING DEBUG [{part_num}]: tier={pricing_tier}, door_type={door_tp}, selling_price={selling_price}")
                    if selling_price is not None:
                        etag = added_line.get("@odata.etag", "*")
                        try:
                            bc_client.update_quote_line(
                                bc_quote_id,
                                added_line["id"],
                                etag,
                                {"unitPrice": selling_price},
                            )
                            logger.info(f"PRICING DEBUG [{part_num}]: PATCH SUCCESS unitPrice={selling_price}")
                        except Exception as patch_err:
                            logger.error(f"PRICING DEBUG [{part_num}]: PATCH FAILED: {patch_err}")
                    else:
                        logger.warning(f"PRICING DEBUG [{part_num}]: selling_price is None, SKIPPING PATCH")
                else:
                    logger.info(f"PRICING DEBUG: skip PATCH - customerId={request.customerId}, lineType={line.get('lineType')}")
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

        # Step 4: Fetch quote with pricing from BC
        pricing = None
        line_pricing = []
        try:
            # Get the quote with totals
            updated_quote = bc_client.get_sales_quote(bc_quote_id)

            # Get line items with pricing
            quote_lines = bc_client.get_quote_lines(bc_quote_id)

            subtotal = updated_quote.get("totalAmountExcludingTax", 0)
            total_with_tax = updated_quote.get("totalAmountIncludingTax", 0)
            tax_amount = total_with_tax - subtotal

            pricing = {
                "subtotal": round(subtotal, 2),
                "tax": round(tax_amount, 2),
                "total": round(total_with_tax, 2),
                "currency": "CAD"
            }

            # Build line-level pricing for display
            for line in quote_lines:
                if line.get("lineType") == "Item":
                    line_pricing.append({
                        "part_number": line.get("lineObjectNumber"),
                        "description": line.get("description", ""),
                        "quantity": line.get("quantity", 0),
                        "unit_price": line.get("unitPrice", 0),
                        "line_total": line.get("netAmount", 0)
                    })

            logger.info(f"Quote {bc_quote_number} total: ${total_with_tax:.2f}")

        except Exception as pricing_error:
            logger.warning(f"Could not fetch pricing for quote {bc_quote_number}: {pricing_error}")

        # Step 5: Add freight line if delivery
        freight_info = None
        if pricing:
            try:
                # Get customer province
                customer_province = None
                if request.customerId:
                    bc_cust = db.query(BCCustomer).filter(
                        BCCustomer.bc_customer_id == request.customerId
                    ).first()
                    if bc_cust and bc_cust.address:
                        customer_province = bc_cust.address.get("province")

                freight = calculate_freight(
                    product_subtotal=pricing["subtotal"],
                    province=customer_province,
                    delivery_type=request.deliveryType,
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
                        # PATCH unitPrice to the calculated freight amount
                        etag = added_freight.get("@odata.etag", "*")
                        bc_client.update_quote_line(
                            bc_quote_id,
                            added_freight["id"],
                            etag,
                            {"unitPrice": freight["amount"]},
                        )
                        freight_added = True
                        logger.info(f"Added freight line: ${freight['amount']:.2f} ({freight['description']})")

                        # Set Output=True so BC groups freight separately (not bundled with door package)
                        if added_freight.get("sequence"):
                            try:
                                bc_client.set_quote_line_output(
                                    bc_quote_number, added_freight["sequence"], output=True
                                )
                            except Exception as out_err:
                                logger.warning(f"Failed to set Output flag on freight line: {out_err}")
                    except Exception as freight_item_err:
                        logger.warning(f"Could not add freight as Item '{freight_item}': {freight_item_err}")

                        # Fallback to Comment line
                        if freight_config.get("fallback_to_comment", True):
                            try:
                                comment_data = {
                                    "lineType": "Comment",
                                    "description": f"{freight['description']}: ${freight['amount']:.2f}",
                                }
                                bc_client.add_quote_line(bc_quote_id, comment_data)
                                freight_added = True
                                logger.info(f"Added freight as comment fallback: ${freight['amount']:.2f}")
                            except Exception as comment_err:
                                logger.warning(f"Could not add freight as comment: {comment_err}")

                    # Re-fetch totals if freight was added as an Item
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

        # Save snapshot for quote review system
        try:
            door_configs_summary = [
                {
                    "series": d.doorSeries, "type": d.doorType,
                    "width": d.doorWidth, "height": d.doorHeight,
                    "count": d.doorCount, "color": d.panelColor,
                }
                for d in request.doors
            ]
            save_quote_snapshot(
                db=db,
                bc_quote_id=bc_quote_id,
                bc_quote_number=bc_quote_number,
                source="admin",
                all_lines=all_lines,
                line_pricing=line_pricing if line_pricing else None,
                pricing_totals=pricing,
                door_configs=door_configs_summary,
                bc_customer_id=request.customerId,
                pricing_tier=pricing_tier,
            )
        except Exception as snap_err:
            logger.warning(f"Could not save quote snapshot: {snap_err}")

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
                "parts_summary": [l for l in all_lines if l.get("lineType") != "Comment"],
                "pricing": pricing,
                "line_pricing": line_pricing if line_pricing else None,
                "freight": freight_info,
                "part_warnings": part_warnings if part_warnings else None,
            },
            "message": f"BC Quote {bc_quote_number} created with {lines_added} line items" + (
                f" ({len(part_warnings)} part(s) substituted — review in BC)" if part_warnings else ""
            )
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
async def get_part_numbers(config: DoorConfigRequest, db: Session = Depends(get_db)):
    """
    Get BC part numbers for a door configuration.

    Returns a list of part numbers needed to fulfill the door configuration,
    organized by category (panel, track, hardware, spring, etc.)
    """
    try:
        # Calculate window count from windowPositions array
        window_count = len(config.windowPositions) if config.windowPositions else (1 if config.windowSection else 0)

        # Convert request to dict for part number service
        config_dict = {
            "doorType": config.doorType,
            "doorSeries": config.doorSeries,
            "doorWidth": config.doorWidth,
            "doorHeight": config.doorHeight,
            "doorCount": config.doorCount,
            "panelColor": config.panelColor,
            "panelDesign": config.panelDesign,
            "windowInsert": config.windowInsert if config.hasWindows else None,
            "windowPositions": [{"section": p.section, "col": p.col} for p in config.windowPositions] if config.windowPositions else [],
            "windowCount": window_count if config.hasWindows else 0,
            "windowSection": config.windowSection,
            "windowQty": config.windowQty if config.hasWindows else 0,
            "windowPanels": config.windowPanels,
            "windowFrameColor": config.windowFrameColor,
            "glazingType": config.glazingType,
            "glassPaneType": config.glassPaneType,
            "glassColor": config.glassColor,
            "trackRadius": config.trackRadius,
            "trackThickness": config.trackThickness,
            "liftType": config.liftType,
            "highLiftInches": config.highLiftInches,
            "trackMount": config.trackMount,
            "shaftType": config.shaftType,
            "hardware": config.hardware,
            "operator": config.operator,
            "targetCycles": config.targetCycles,
            "includeTopSeal": getattr(config, 'includeTopSeal', False),
        }

        # Get parts from service (with BC spring inventory for consistency with specs tab)
        spring_inv = get_bc_spring_inventory()
        parts_summary = get_parts_for_door_config(config_dict, spring_inventory=spring_inv)

        return {
            "success": True,
            "data": parts_summary,
            "message": f"Found {parts_summary['total_parts']} part numbers"
        }

    except Exception as e:
        logger.error(f"Error getting part numbers: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/get-parts-for-quote")
async def get_parts_for_quote(request: QuoteGenerationRequest, db: Session = Depends(get_db)):
    """
    Get BC part numbers for an entire quote (multiple doors).

    Returns consolidated part list for all doors in the quote.
    """
    try:
        all_parts = []
        parts_by_door = []

        for i, door in enumerate(request.doors):
            # Calculate window count from windowPositions array
            window_count = len(door.windowPositions) if door.windowPositions else (1 if door.windowSection else 0)

            config_dict = {
                "doorType": door.doorType,
                "doorSeries": door.doorSeries,
                "doorWidth": door.doorWidth,
                "doorHeight": door.doorHeight,
                "doorCount": door.doorCount,
                "panelColor": door.panelColor,
                "panelDesign": door.panelDesign,
                "windowInsert": door.windowInsert if door.hasWindows else None,
                "windowPositions": [{"section": p.section, "col": p.col} for p in door.windowPositions] if door.windowPositions else [],
                "windowCount": window_count if door.hasWindows else 0,
                "windowSection": door.windowSection,
                "windowQty": door.windowQty if door.hasWindows else 0,
                "windowPanels": door.windowPanels,
                "windowFrameColor": door.windowFrameColor,
                "glazingType": door.glazingType,
                "glassPaneType": door.glassPaneType,
                "glassColor": door.glassColor,
                "trackRadius": door.trackRadius,
                "trackThickness": door.trackThickness,
                "trackMount": door.trackMount,
                "liftType": door.liftType,
                "highLiftInches": door.highLiftInches,
                "hardware": door.hardware,
                "operator": door.operator,
                "operatorAccessories": door.operatorAccessories or [],
                "targetCycles": door.targetCycles,
                "shaftType": door.shaftType,
                "includeTopSeal": getattr(door, 'includeTopSeal', False),
            }

            spring_inv = get_bc_spring_inventory()
            door_parts = get_parts_for_door_config(config_dict, spring_inventory=spring_inv)

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

        # Sort consolidated parts by standard line ordering
        sorted_consolidated = _sort_parts_by_category(list(consolidated.values()))

        return {
            "success": True,
            "data": {
                "total_doors": len(request.doors),
                "total_unique_parts": len(consolidated),
                "parts_by_door": parts_by_door,
                "consolidated_parts": sorted_consolidated
            },
            "message": f"Generated part list for {len(request.doors)} door(s)"
        }

    except Exception as e:
        logger.error(f"Error getting parts for quote: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/calculate-door")
async def calculate_door_specifications(request: DoorCalculationRequest, db: Session = Depends(get_db)):
    """
    Calculate complete door specifications including:
    - Panel configuration (sections, gauge)
    - Door weight breakdown
    - Spring selection (coil, wire, length, cycles) - filtered by stocked inventory
    - Drum selection with cable specifications
    - Shaft configuration
    - Track configuration
    - Hardware component list

    Based on Thermalex Door Weight Calculator formulas.
    Spring selection respects the spring inventory settings - only stocked springs
    will be selected. If no stocked 2-spring solution exists, falls back to 4 springs.
    """
    try:
        # Convert feet + inches to total inches
        width_inches = (request.widthFeet * 12) + request.widthInches
        height_inches = (request.heightFeet * 12) + request.heightInches

        if width_inches < 60 or width_inches > 360:
            raise HTTPException(status_code=400, detail="Door width must be between 60\" and 360\" (5' to 30')")
        if height_inches < 60 or height_inches > 288:
            raise HTTPException(status_code=400, detail="Door height must be between 60\" and 288\" (5' to 24')")

        # Load spring inventory from BC so we only select stocked springs
        spring_inventory = get_bc_spring_inventory()

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
            spring_inventory=spring_inventory,
            high_lift_inches=request.highLiftInches,
            door_type=request.doorType,
        )

        # Get summary
        summary = door_calculator.get_calculation_summary(calc)

        # Add top seal upgrade info for commercial doors
        commercial_auto_threshold = (
            request.doorType == "commercial"
            and width_inches >= 216
            and height_inches >= 120
        )
        summary["top_seal"] = {
            "available": request.doorType in ("commercial", "aluminium"),
            "auto_included": request.doorType == "aluminium" or commercial_auto_threshold,
            "is_upgrade": request.doorType == "commercial" and not commercial_auto_threshold,
            "description": "Top seal rubber weatherstrip" if request.doorType != "residential" else None,
        }

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
        {"id": "24X12_THERMOPANE", "name": "24\" x 12\" Thermopane", "width": 24, "height": 12, "section": "24\" only", "glassOptions": ["thermal"]},
        {"id": "34X16_THERMOPANE", "name": "34\" x 16\" Thermopane", "width": 34, "height": 16, "section": "24\" only", "glassOptions": ["thermal"]},
        {"id": "18X8_THERMOPANE", "name": "18\" x 8\" Thermopane", "width": 18, "height": 8, "section": "21\" or 24\"", "glassOptions": ["thermal"]},
        {"id": "V130G", "name": "V130G Full View Section", "width": "full", "height": "full", "section": "Replaces insulated section", "glassOptions": ["single", "thermal"], "material": "AL976", "series": ["TX450", "TX450-20"]},
        {"id": "V230G", "name": "V230G Full View Section", "width": "full", "height": "full", "section": "Replaces insulated section", "glassOptions": ["single", "thermal"], "material": "AL976", "series": ["TX500", "TX500-20"]},
    ]
    return {"success": True, "data": window_types}


class CommercialWindowSpacingRequest(BaseModel):
    """Request for commercial window spacing calculation"""
    doorWidthInches: int  # Total door width in inches
    windowType: str  # 24X12_THERMOPANE, 34X16_THERMOPANE, 18X8_THERMOPANE
    windowQty: int  # Number of windows


@router.post("/calculate-window-spacing")
async def calculate_commercial_window_spacing(request: CommercialWindowSpacingRequest):
    """
    Calculate window spacing for commercial doors.

    Based on COMMERCIAL WINDOW SPACING CALCULATOR spreadsheet:
    - Panel width = Door width in inches (full width)
    - Window Spaces = Window Qty + 1
    - Total Length of windows = Window Width × Qty
    - Space between = (Panel Width - Total Window Length) / Window Spaces
    """
    # Get window dimensions
    window_size = COMMERCIAL_WINDOW_SIZES.get(request.windowType)
    if not window_size:
        raise HTTPException(status_code=400, detail=f"Unknown window type: {request.windowType}")

    window_width = window_size["width"]
    window_height = window_size["height"]

    # Panel width = door width (matches spreadsheet exactly)
    panel_width = request.doorWidthInches

    # Calculate with requested quantity
    total_window_width = window_width * request.windowQty
    window_spaces = request.windowQty + 1  # Spaces on ends and between

    if total_window_width >= panel_width:
        # Too many windows
        max_windows = int((panel_width - 6) / (window_width + 3))  # Min 3" spacing
        return {
            "success": False,
            "error": "Too many windows for door width",
            "data": {
                "maxWindows": max_windows,
                "doorWidth": request.doorWidthInches,
                "windowType": request.windowType,
                "windowWidth": window_width,
            }
        }

    space_between = (panel_width - total_window_width) / window_spaces

    # Calculate recommended qty (target ~10" spacing)
    optimal_spacing = 10
    recommended_qty = int((panel_width - optimal_spacing) / (window_width + optimal_spacing))
    recommended_qty = max(1, recommended_qty)

    # Recalculate spacing for recommended qty
    rec_total_width = window_width * recommended_qty
    rec_spaces = recommended_qty + 1
    rec_spacing = (panel_width - rec_total_width) / rec_spaces

    return {
        "success": True,
        "data": {
            "doorWidth": request.doorWidthInches,
            "panelWidth": panel_width,
            "windowType": request.windowType,
            "windowWidth": window_width,
            "windowHeight": window_height,
            "requestedQty": request.windowQty,
            "spaceBetween": round(space_between, 2),
            "totalWindowWidth": total_window_width,
            "recommended": {
                "windowQty": recommended_qty,
                "spaceBetween": round(rec_spacing, 2),
            },
            "frameColors": COMMERCIAL_WINDOW_FRAME_COLORS,
        }
    }


@router.get("/calculate-default-windows/{door_width_inches}")
async def get_default_window_count(door_width_inches: int, window_type: str = "24X12_THERMOPANE"):
    """
    Get the default/recommended window count for a commercial door width.
    Uses same formula as the COMMERCIAL WINDOW SPACING CALCULATOR spreadsheet.
    """
    window_size = COMMERCIAL_WINDOW_SIZES.get(window_type)
    if not window_size:
        window_size = {"width": 24, "height": 12}  # Default to 24x12

    window_width = window_size["width"]
    panel_width = door_width_inches  # Full door width per spreadsheet

    # Calculate recommended quantity (target 8-12" spacing)
    optimal_spacing = 10
    recommended_qty = int((panel_width - optimal_spacing) / (window_width + optimal_spacing))
    recommended_qty = max(0, recommended_qty)

    # Calculate actual spacing
    if recommended_qty > 0:
        total_width = window_width * recommended_qty
        spaces = recommended_qty + 1
        spacing = (panel_width - total_width) / spaces
    else:
        spacing = panel_width

    return {
        "success": True,
        "data": {
            "doorWidth": door_width_inches,
            "windowType": window_type,
            "recommendedQty": recommended_qty,
            "spacing": round(spacing, 2),
        }
    }


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


# ============================================================================
# SHOP DRAWING GEOMETRY
# ============================================================================

@router.get("/shop-drawing-geometry")
def get_shop_drawing_geometry(
    widthFeet: int = 9,
    widthInches: int = 0,
    heightFeet: int = 8,
    heightInches: int = 0,
    trackSize: int = 2,
    trackRadius: int = 15,
    liftType: str = "standard",
    highLiftInches: int = 0,
    mountType: str = "bracket",
    frameType: str = "steel",
    doorType: str = "residential",
):
    """Calculate shop drawing geometry using Thermalex dimension formulas."""
    door_width = widthFeet * 12 + widthInches
    door_height = heightFeet * 12 + heightInches

    if door_width <= 0 or door_height <= 0:
        raise HTTPException(status_code=400, detail="Door dimensions must be positive")

    try:
        geometry = calculate_shop_drawing_geometry(
            door_height=door_height,
            door_width=door_width,
            track_size=trackSize,
            track_radius=trackRadius,
            lift_type=liftType,
            high_lift_inches=highLiftInches,
            mount_type=mountType,
            frame_type=frameType,
            door_type=doorType,
        )
        return geometry
    except Exception as e:
        logger.error(f"Error calculating shop drawing geometry: {e}")
        raise HTTPException(status_code=500, detail=str(e))
