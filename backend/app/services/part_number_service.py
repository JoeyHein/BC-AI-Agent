"""
Part Number Selection Service
Maps door configurations to BC part numbers based on business rules

=============================================================================
BC PART NUMBER PATTERNS (from analysis of 11,369 items and 891 quotes):
=============================================================================

SPRINGS (SP):
- SP10: Galvanized - SP10-{wire}{coil}-{wind} (e.g., SP10-25020-01)
- SP11: Oil Tempered - SP11-{wire}{coil}-{wind} (e.g., SP11-23420-01)
  - wire: 3 digits (218=0.218", 234=0.234", 250=0.250")
  - coil: 2 digits (20=2", 25=2-5/8", 36=3-3/4", 60=6")
  - wind: 01=LH, 02=RH
- SP12: Accessories (winders, plugs)
  - SP12-00231-00 = 2" winder/stationary set LH
  - SP12-00237-00 = 2" winder/stationary set RH
- SP16: Pre-pick springs (cut to length)

PANELS (PN):
- PN45: TX450 Single End Cap (SEC)
- PN46: TX450 Double End Cap (DEC)
- Format: PN{series}-{height}{stamp}{color}-{width}
  - Example: PN45-24400-0900 = TX450 24" white UDC 9' wide

PLASTICS/WEATHER STRIPPING (PL):
- PL10-{length}203-{color}: Commercial weather stripping
  - Example: PL10-07203-00 = 7' white weather strip
- PL10-00005-01/02/03: Astragal 3"/4"/6.5"
- PL10-00141-00: Retainer 1-3/4"

TRACKS (TR):
- TR02-STDBM-{height}{radius}: 2" standard lift bracket mount
- TR03-STDBM-{height}: 3" standard lift bracket mount

SHAFTS (SH):
- SH12-1{width}10-00: Tube shaft
- SH11-1{width}06-00: Solid keyed shaft

STRUTS (FH):
- FH17-{code}-00: Struts by length

HARDWARE (HK):
- HK01-HK06: Complete hardware kits
"""

import logging
import math
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass
from enum import Enum

from app.services.spring_calculator_service import spring_calculator
from app.services.door_calculator_service import SECTION_HEIGHT_TABLE, door_calculator
from app.services.bc_part_number_mapper import (
    BCPartNumberMapper,
    get_bc_mapper,
    SpringType,
    DoorModel,
    EndCapType,
    LiftType,
    TrackMount,
)

logger = logging.getLogger(__name__)


# ============================================================================
# ENUMS AND DATA CLASSES
# ============================================================================

class DoorSeries(Enum):
    KANATA = "KANATA"
    CRAFT = "CRAFT"
    TX450 = "TX450"
    TX500 = "TX500"
    TX450_20 = "TX450-20"
    TX500_20 = "TX500-20"
    AL976 = "AL976"
    KANATA_EXECUTIVE = "KANATA_EXECUTIVE"


@dataclass
class PartSelection:
    """Represents a selected part with metadata"""
    part_number: str
    description: str
    quantity: float  # int for count-based, float for sqft (e.g. glass)
    category: str  # panel, track, hardware, spring, etc.
    unit_price: Optional[float] = None
    notes: Optional[str] = None


@dataclass
class DoorConfiguration:
    """Input configuration for part number selection"""
    door_type: str  # residential, commercial, aluminium, executive
    door_series: str
    door_width: int  # inches
    door_height: int  # inches
    door_count: int
    panel_color: str
    panel_design: str  # stamp pattern
    window_insert: Optional[str] = None
    window_section: Optional[int] = None
    window_count: int = 0  # Number of windows (calculated from windowPositions)
    window_qty: int = 0  # Commercial: number of windows per section, or V130G section count
    window_panels: Optional[Dict[int, dict]] = None  # Per-panel window config: {2: {"qty": 3}, 4: {"qty": 2}}
    window_frame_color: str = "BLACK"  # Commercial window frame color
    glazing_type: Optional[str] = None
    glass_pane_type: Optional[str] = None  # 'INSULATED' or 'SINGLE'
    glass_color: Optional[str] = None      # 'CLEAR', 'ETCHED', 'SUPER_GREY'
    track_radius: str = "15"
    track_thickness: str = "2"
    hardware: Dict[str, bool] = None
    operator: Optional[str] = None
    door_weight: Optional[float] = None  # lbs - if not provided, will estimate
    target_cycles: int = 10000  # cycle life rating (10000, 15000, 25000, 50000, 100000)
    spring_quantity: int = 2  # number of springs (1 or 2)
    shaft_preference: str = 'auto'  # 'auto', 'single', or 'split'
    track_mount: str = 'bracket'  # 'bracket' or 'angle'
    window_size: str = 'long'  # 'short' (GK15-10xxx) or 'long' (GK15-11xxx)
    spring_inventory: Optional[Dict[str, list]] = None  # stocked coil/wire combos from settings


# ============================================================================
# PART NUMBER RULES - CONFIGURE THESE WITH DOMAIN KNOWLEDGE
# ============================================================================

# Panel Part Number Rules
# Format: PN-{SERIES}-{WIDTH}-{HEIGHT}-{COLOR}-{DESIGN}
PANEL_RULES = {
    # KANATA Series Panels
    "KANATA": {
        "prefix": "PN",
        "pattern": "PN-KAN-{width_code}-{height_code}-{color_code}-{design_code}",
        "colors": {
            "WHITE": "WH",
            "NEW_ALMOND": "AL",
            "BLACK": "BK",
            "WALNUT": "WN",
            "IRON_ORE": "IO",
            "SANDTONE": "ST",
            "NEW_BROWN": "BR",
            "BRONZE": "BZ",
            "STEEL_GREY": "SG",
            "HAZELWOOD": "HZ",
            "ENGLISH_CHESTNUT": "EC",
        },
        "designs": {
            "SHXL": "SH",  # Sheridan
            "LNXL": "LN",  # Sheridan XL
            "SHCH": "BC",  # Bronte Creek
            "LNCH": "BX",  # Bronte Creek XL
            "RIB": "RB",   # Trafalgar/Ribbed
            "FLUSH": "FL", # Flush
        },
    },
    # CRAFT Series Panels
    "CRAFT": {
        "prefix": "PN",
        "pattern": "PN-CRF-{width_code}-{height_code}-{color_code}-{design_code}",
        "colors": {
            "WHITE": "WH",
            "SANDTONE": "ST",
            "WALNUT": "WN",
            "ENGLISH_CHESTNUT": "EC",
            "IRON_ORE": "IO",
        },
        "designs": {
            "MUSKOKA": "MK",
            "DENISON": "DN",
            "GRANVILLE": "GV",
        },
    },
    # Commercial TX Series Panels
    "TX450": {
        "prefix": "PN",
        "pattern": "PN-TX4-{width_code}-{height_code}-{color_code}",
        "colors": {
            "BRIGHT_WHITE": "WH",
            "NEW_BROWN": "BR",
            "BLACK": "BK",
            "STEEL_GREY": "SG",
        },
    },
    "TX500": {
        "prefix": "PN",
        "pattern": "PN-TX5-{width_code}-{height_code}-{color_code}",
        "colors": {
            "BRIGHT_WHITE": "WH",
            "NEW_BROWN": "BR",
            "BLACK": "BK",
            "STEEL_GREY": "SG",
        },
    },
}

# NOTE: Pre-configured door packages (TX450-0907-01, etc.) have been removed.
# Always use individual panel part numbers (PN45, PN46, PN65, PN95, etc.)

# Track Part Numbers
TRACK_RULES = {
    "vertical": {
        "2": {  # 2" track
            "standard": "TR-V2-STD",
            "heavy": "TR-V2-HD",
        },
        "3": {  # 3" track
            "standard": "TR-V3-STD",
            "heavy": "TR-V3-HD",
        },
    },
    "horizontal": {
        "2": {
            "12": "TR-H2-12",  # 12" radius
            "15": "TR-H2-15",  # 15" radius
            "20": "TR-H2-20",  # 20" radius
        },
        "3": {
            "12": "TR-H3-12",
            "15": "TR-H3-15",
            "20": "TR-H3-20",
        },
    },
    # Track length by door height
    "length_by_height": {
        84: "7FT",   # 7'
        90: "7FT6",  # 7'6"
        96: "8FT",   # 8'
        108: "9FT",  # 9'
        120: "10FT", # 10'
        144: "12FT", # 12'
        168: "14FT", # 14'
    },
}

# Hardware Kit Part Numbers
# NOTE: Actual hardware box part numbers are now generated via bc_part_number_mapper
# - Residential 2" track: HK10-0HHSS-WWWW pattern
# - Commercial 3" track: HWww-hhhhh-00 pattern
# Future: HK02, HK03, HK12, HK13, HK22, HK23, HK32, HK33 for extended sizes
HARDWARE_RULES = {
    "hinges": {
        "residential": "HW-HNG-RES",
        "commercial": "HW-HNG-COM",
    },
    "rollers": {
        "nylon": "HW-ROL-NYL",
        "steel": "HW-ROL-STL",
    },
}

# Spring Part Numbers (based on door weight calculation)
SPRING_RULES = {
    # Simplified: actual spring selection requires weight calculation
    # Format: SP-{wire_size}-{ID}-{length}
    "residential": {
        "light": "SP-225-2-26",   # Light doors (single car)
        "medium": "SP-234-2-30",  # Medium (double car)
        "heavy": "SP-243-2-34",   # Heavy (insulated double)
    },
    "commercial": {
        "light": "SP-262-2-36",
        "medium": "SP-273-2-42",
        "heavy": "SP-284-2-48",
    },
}

# Shaft Part Numbers
SHAFT_RULES = {
    # By door width
    "1_inch": {"max_width": 144, "part": "SH-1-"},  # + length code
    "1.25_inch": {"max_width": 288, "part": "SH-125-"},
}

# Strut Part Numbers
STRUT_RULES = {
    "residential": {
        "2_inch": "FH-2-",  # + length code
    },
    "commercial": {
        "2_inch": "FH-2-HD-",  # + length code (heavy duty)
    },
}

# Window/Glass Kit Part Numbers
WINDOW_RULES = {
    "STOCKTON": {
        "STOCKTON_STANDARD": "GK-STK-STD",
        "STOCKTON_TEN_SQUARE_XL": "GK-STK-10SQ",
        "STOCKTON_ARCHED_XL": "GK-STK-ARCH",
        "STOCKTON_EIGHT_SQUARE": "GK-STK-8SQ",
        "STOCKTON_ARCHED": "GK-STK-ARCH",
    },
    "STOCKBRIDGE": {
        "STOCKBRIDGE_STRAIGHT": "GK-STB-STR",
        "STOCKBRIDGE_STRAIGHT_XL": "GK-STB-STRXL",
        "STOCKBRIDGE_ARCHED_XL": "GK-STB-ARCHXL",
        "STOCKBRIDGE_ARCHED": "GK-STB-ARCH",
    },
    # By glazing type suffix
    "glazing_suffix": {
        "CLEAR": "-CL",
        "INSULATED": "-INS",
        "TINTED": "-TN",
        "TEMPERED": "-TMP",
        "ACID_ETCHED": "-AE",
    },
}

# Weather Stripping / Seals Part Numbers
SEAL_RULES = {
    "bottom_astragal": {
        "standard": "PL-AST-",  # + width code
        "heavy": "PL-AST-HD-",
    },
    "weather_strip": {
        "jamb": "PL-WS-JMB",
        "header": "PL-WS-HDR",
        "kit": "PL-WS-KIT-",  # + door size code
    },
    "bottom_retainer": {
        "pvc": "PL-BR-PVC-",  # + width code
        "aluminum": "PL-BR-AL-",
    },
}

# Operator Part Numbers
OPERATOR_RULES = {
    "residential": {
        "LIFTMASTER_BASIC": "OP-LM-BASIC",
        "LIFTMASTER_MYQ": "OP-LM-MYQ",
        "LIFTMASTER_BATTERY": "OP-LM-BATT",
    },
    "commercial": {
        "PDC500": "OP-PDC-500",
        "PDC750_100": "OP-PDC-750-100",
        "PDC750_125": "OP-PDC-750-125",
        "PDC1000": "OP-PDC-1000",
        "PDC2000": "OP-PDC-2000",
        "PA15": "OP-PA-15",
        "PA17": "OP-PA-17",
    },
}


# ============================================================================
# PART NUMBER SERVICE
# ============================================================================

class PartNumberService:
    """
    Service to select appropriate part numbers based on door configuration.

    Usage:
        service = PartNumberService()
        parts = service.get_parts_for_configuration(config)
    """

    def __init__(self):
        self.panel_rules = PANEL_RULES
        self.track_rules = TRACK_RULES
        self.hardware_rules = HARDWARE_RULES
        self.spring_rules = SPRING_RULES
        self.shaft_rules = SHAFT_RULES
        self.strut_rules = STRUT_RULES
        self.window_rules = WINDOW_RULES
        self.seal_rules = SEAL_RULES
        self.operator_rules = OPERATOR_RULES

    def get_parts_for_configuration(self, config: DoorConfiguration) -> List[PartSelection]:
        """
        Get all part numbers needed for a door configuration.

        Returns list of PartSelection objects with part numbers and quantities.

        ORDER (per business requirements):
        1. Comment (door description)
        2. Panels
        3. Retainer
        4. Astragal
        5. Struts
        6. Top seal (if applicable)
        7. Tracks
        8. Highlift/lowheadroom (if applicable)
        9. Hardware
        10. Shaft
        11. Springs
        12. Weather seal
        13. Extras (windows, operator)
        """
        parts = []
        hardware = config.hardware or {}

        # 1. COMMENT - Door description line
        door_width_ft = config.door_width // 12
        door_width_in = config.door_width % 12
        door_height_ft = config.door_height // 12
        door_height_in = config.door_height % 12

        width_str = f"{door_width_ft}'" if door_width_in == 0 else f"{door_width_ft}'{door_width_in}\""
        height_str = f"{door_height_ft}'" if door_height_in == 0 else f"{door_height_ft}'{door_height_in}\""

        comment_desc = f"{config.door_series} {width_str} x {height_str} {config.panel_color.replace('_', ' ').title()}"
        if config.panel_design:
            comment_desc += f" {config.panel_design}"

        parts.append(PartSelection(
            part_number="",  # Comment line has no part number
            description=comment_desc,
            quantity=1,
            category="comment"
        ))

        # 2. PANELS
        if hardware.get("panels", True):
            panel_parts = self._get_panel_parts(config)
            parts.extend(panel_parts)

        # 3. RETAINER (from bottom retainer parts - just retainer, not astragal)
        if hardware.get("bottomRetainer", True):
            retainer_parts = self._get_retainer_only_parts(config)
            parts.extend(retainer_parts)

        # 4. ASTRAGAL (bottom rubber)
        if hardware.get("bottomRetainer", True):
            astragal_parts = self._get_astragal_only_parts(config)
            parts.extend(astragal_parts)

        # 5. STRUTS (right after astragal, before tracks)
        if hardware.get("struts", True):
            strut_parts = self._get_strut_parts(config)
            parts.extend(strut_parts)

        # 6. TOP SEAL (if applicable - for insulated doors)
        top_seal_parts = self._get_top_seal_parts(config)
        parts.extend(top_seal_parts)

        # 7. TRACKS
        if hardware.get("tracks", True):
            track_parts = self._get_track_parts(config)
            parts.extend(track_parts)

        # 7. HIGHLIFT/LOWHEADROOM (if applicable)
        highlift_parts = self._get_highlift_parts(config)
        parts.extend(highlift_parts)

        # 8. HARDWARE
        if hardware.get("hardwareKits", True):
            hw_parts = self._get_hardware_kit_parts(config)
            parts.extend(hw_parts)

        # 9. SHAFT
        if hardware.get("shafts", True):
            shaft_parts = self._get_shaft_parts(config)
            parts.extend(shaft_parts)

        # 10. SPRINGS
        if hardware.get("springs", True):
            spring_parts = self._get_spring_parts(config)
            parts.extend(spring_parts)

        # 11. WEATHER SEAL (sides and header)
        if hardware.get("weatherStripping", True):
            seal_parts = self._get_seal_parts(config)
            parts.extend(seal_parts)

        # 12. EXTRAS (windows, operator)
        # Aluminum doors: sections are the panels — generate PN97/PN80/PN20 parts + glass
        if config.door_type == "aluminium":
            aluminum_parts = self._get_aluminum_section_parts(config)
            parts.extend(aluminum_parts)
        else:
            has_windows = (config.window_count > 0) or (config.window_insert and config.window_insert not in (None, "NONE"))
            if has_windows:
                window_parts = self._get_window_parts(config)
                parts.extend(window_parts)

        if config.operator and config.operator != "NONE":
            operator_parts = self._get_operator_parts(config)
            parts.extend(operator_parts)

        # Apply quantity multiplier for door count (skip comment and operator)
        for part in parts:
            if part.category not in ["operator", "comment"]:
                part.quantity *= config.door_count

        return parts

    def _get_width_code(self, width_inches: int) -> str:
        """Convert width in inches to code (feet or inches)"""
        feet = width_inches // 12
        inches = width_inches % 12
        if inches == 0:
            return f"{feet:02d}"
        return f"{feet:02d}{inches:02d}"

    def _get_height_code(self, height_inches: int) -> str:
        """Convert height in inches to code"""
        feet = height_inches // 12
        inches = height_inches % 12
        if inches == 0:
            return f"{feet:02d}"
        elif inches == 6:
            return f"{feet:02d}6"
        return f"{feet:02d}{inches:02d}"

    def _get_section_breakdown(self, door_height: int) -> Dict[str, int]:
        """Get the 21"/24" section breakdown for a given door height.

        Uses SECTION_HEIGHT_TABLE from door_calculator_service. Falls back to
        an algorithm if the height isn't in the table: start with all 24" panels,
        swap to 21" as needed (diff = panel_count * 24 - door_height, n21 = diff // 3).

        Returns: {"21": count, "24": count, "total": count}
        """
        if door_height in SECTION_HEIGHT_TABLE:
            entry = SECTION_HEIGHT_TABLE[door_height]
            return {"21": entry["21"], "24": entry["24"], "total": entry["total"]}

        # Fallback algorithm for heights not in the table
        if door_height <= 72:
            panel_count = 3
        elif door_height <= 96:
            panel_count = 4
        elif door_height <= 120:
            panel_count = 5
        elif door_height <= 144:
            panel_count = 6
        elif door_height <= 168:
            panel_count = 7
        elif door_height <= 192:
            panel_count = 8
        elif door_height <= 216:
            panel_count = 9
        else:
            panel_count = 10

        diff = panel_count * 24 - door_height
        n21 = diff // 3
        n24 = panel_count - n21
        return {"21": n21, "24": n24, "total": panel_count}

    def _get_panel_parts(self, config: DoorConfiguration) -> List[PartSelection]:
        """Get panel part numbers using actual BC parts.

        Uses mixed 21"/24" panel heights from SECTION_HEIGHT_TABLE to fill
        the exact door height (e.g. 9' = 1x24" + 4x21").
        """
        mapper = get_bc_mapper()
        parts = []

        # Map series string to DoorModel enum
        model_map = {
            "TX450": DoorModel.TX450,
            "TX500": DoorModel.TX450,  # TX500 uses similar pattern
            "KANATA": DoorModel.KANATA,
            "CRAFT": DoorModel.CRAFT,
        }
        door_model = model_map.get(config.door_series, DoorModel.TX450)

        # Actual door width — keep precise value for description
        actual_width_in = config.door_width          # e.g., 150 for 12'6"
        actual_width_feet = actual_width_in / 12     # e.g., 12.5

        # Round UP to next whole foot for BC part number (no panel exists for fractional widths)
        panel_width_feet = math.ceil(actual_width_feet)   # e.g., 13

        # Determine end cap type based on rounded panel width
        end_cap_type = EndCapType.DOUBLE if panel_width_feet > 16 else EndCapType.SINGLE

        # Build display string showing the customer's actual requested width
        actual_ft = actual_width_in // 12
        actual_in_rem = actual_width_in % 12
        width_display = f"{actual_ft:02d}' {actual_in_rem:02d}\""   # e.g., "12' 06\""
        cap_name = "DEC" if end_cap_type == EndCapType.DOUBLE else "SEC"
        color_str = config.panel_color.replace("_", " ").upper()
        stamp_str = "UDC" if config.door_type == "commercial" else "STD"

        # Get mixed-height breakdown
        breakdown = self._get_section_breakdown(config.door_height)

        # V130G replaces insulated sections — subtract from 24" first, then 21"
        v130g_reduction = 0
        if config.window_insert == "V130G" and config.window_qty > 0:
            v130g_reduction = config.window_qty

        # Build part selections for each height (24" first since they're top sections)
        for h in [24, 21]:
            count = breakdown[str(h)]
            if count <= 0:
                continue

            # Apply V130G reduction (24" panels first)
            if v130g_reduction > 0:
                reduce = min(v130g_reduction, count)
                count -= reduce
                v130g_reduction -= reduce
                if count <= 0:
                    continue

            # Use rounded-up width for part number; actual width in description
            panel = mapper.get_panel_part_number(
                model=door_model,
                width_feet=panel_width_feet,
                height_inches=h,
                color=config.panel_color.replace("_", " "),
                end_cap_type=end_cap_type,
                stamp=stamp_str
            )

            # Description shows the customer's actual requested dimensions
            actual_desc = (
                f"SECTION, {door_model.value}, [{width_display}] X {h}\","
                f" {stamp_str}, {color_str}, {cap_name}"
            )

            parts.append(PartSelection(
                part_number=panel.part_number,
                description=actual_desc,
                quantity=count,
                category="panel"
            ))

        return parts

    def _calculate_panel_count(self, door_height: int) -> int:
        """Calculate number of panels based on door height"""
        return self._get_section_breakdown(door_height)["total"]

    def _calculate_door_weight(self, config: DoorConfiguration) -> float:
        """
        Calculate door weight using linear foot weights per section.

        Weight = (lbs_per_linear_ft × door_width_ft × num_sections) + hardware_weight

        Panel weights (lbs per linear foot):
        - 18" panels: 3.7655
        - 21" panels: 4.1875
        - 24" panels: 4.6392
        - 28" panels: 5.1363
        - 32" panels: 6.1875
        """
        # Weight per linear foot by section height
        MODEL_WEIGHTS = {
            # Commercial models
            "TX380": {"18": 3.4991, "21": 3.4991, "24": 3.933, "28": 4.5, "32": 5.0},
            "TX450": {"18": 3.83, "21": 3.83, "24": 4.38, "28": 5.0, "32": 5.5},
            "TX450-20": {"18": 5.18, "21": 5.18, "24": 5.6813, "28": 6.2, "32": 6.8},
            "TX500": {"18": 4.002, "21": 4.002, "24": 4.57, "28": 5.2, "32": 5.7},
            "TX500-20": {"18": 5.2865, "21": 5.2865, "24": 5.63, "28": 6.1, "32": 6.6},
            # Residential models (Kanata/Craft)
            "KANATA": {"18": 3.7655, "21": 4.1875, "24": 4.6392, "28": 5.1363, "32": 6.1875},
            "CRAFT": {"18": 3.7655, "21": 4.1875, "24": 4.6392, "28": 5.1363, "32": 6.1875},
        }

        # Get model weights (default to KANATA if not found)
        model_weights = MODEL_WEIGHTS.get(config.door_series, MODEL_WEIGHTS["KANATA"])

        door_width_ft = config.door_width / 12
        door_height_in = config.door_height

        # Use mixed-height breakdown for accurate per-section weight
        breakdown = self._get_section_breakdown(door_height_in)
        num_sections = breakdown["total"]

        # Calculate panel weight using correct weight for each section height
        panel_weight = 0.0
        for h in ["21", "24"]:
            count = breakdown[h]
            if count > 0:
                weight_per_ft = model_weights.get(h, model_weights.get("21", 4.0))
                panel_weight += weight_per_ft * door_width_ft * count

        # Add hardware weight - different for residential vs commercial
        # Residential (2" hinges, lighter brackets): ~15-18 lbs
        # Commercial (3" hinges, heavier brackets): ~27-35 lbs
        is_residential = config.door_series.upper() in ["KANATA", "CRAFT", "KANATA_EXECUTIVE"]
        if is_residential:
            # Residential hardware weight (2" hinges, smaller rollers, lighter brackets)
            # Based on typical residential hardware box contents
            hardware_weight = 17.0
        else:
            # Commercial hardware weight (3" hinges, heavy-duty brackets)
            hardware_weight = 27.0

        total_weight = panel_weight + hardware_weight

        hw_type = "residential 2\"" if is_residential else "commercial 3\""
        breakdown_str = " + ".join(
            f"{breakdown[h]}x{h}\"" for h in ["24", "21"] if breakdown[h] > 0
        )
        logger.info(
            f"Door weight calculation: {config.door_series} {door_width_ft}'x{door_height_in}\" "
            f"= [{breakdown_str}] sections × {door_width_ft}' + {hardware_weight} lbs ({hw_type} hw) "
            f"= {total_weight:.1f} lbs"
        )

        return total_weight

    def _get_track_parts(self, config: DoorConfiguration) -> List[PartSelection]:
        """Get track part numbers using actual BC parts"""
        mapper = get_bc_mapper()

        # Round UP to next whole foot for BC part number (track must cover full door height)
        door_height_feet = math.ceil(config.door_height / 12)
        track_size = int(config.track_thickness) if config.track_thickness else 2
        radius_inches = int(config.track_radius) if config.track_radius else 12

        # Determine lift type and mount type
        lift_type = LiftType.STANDARD  # Default to standard lift
        mount_type = TrackMount.ANGLE if config.track_mount == 'angle' else TrackMount.BRACKET
        mount_label = "ANGLE MOUNT" if config.track_mount == 'angle' else "BRACKET MOUNT"

        # Get track assembly part number using the rounded-up height
        track = mapper.get_track_assembly(
            door_height_feet=door_height_feet,
            track_size=track_size,
            lift_type=lift_type,
            mount_type=mount_type,
            radius_inches=radius_inches
        )

        # Build description showing the customer's actual requested door height
        actual_ft = config.door_height // 12
        actual_in = config.door_height % 12
        if actual_in > 0:
            height_display = f"{actual_ft}'{actual_in}\""
        else:
            height_display = f"{actual_ft}'"
        track_desc = (
            f"{track_size}\" STANDARD LIFT {mount_label}; {height_display} High,"
            f"{radius_inches}\"Radius"
        )

        return [PartSelection(
            part_number=track.part_number,
            description=track_desc,
            quantity=1,  # Track assembly is sold as a kit (pair)
            category="track"
        )]

    def _get_spring_parts(self, config: DoorConfiguration) -> List[PartSelection]:
        """
        Get spring part numbers using door_calculator for spring selection + BC part number mapper.

        Uses door_calculator._calculate_springs() as the single source of truth —
        same progressive qty scaling (2→4→6→8), duplex support, and Canimex methodology
        used by the Door Specifications tab.

        Then maps to actual BC part numbers:
        - SP11-{wire}{coil}-{wind} for oil tempered springs
        - SP12-{code} for winder/stationary sets
        """
        parts = []

        # Get door weight - use provided weight or calculate from linear foot weights
        door_weight = config.door_weight
        if door_weight is None:
            door_weight = self._calculate_door_weight(config)

        # Parse track radius (handle string format)
        track_radius = int(config.track_radius) if config.track_radius else 15

        # Use door_calculator._calculate_springs() — same engine as specs tab
        spring_result = door_calculator._calculate_springs(
            door_weight=door_weight,
            height_inches=config.door_height,
            width_inches=config.door_width,
            drums=None,  # Let calculator auto-select drum for torque calculation
            target_cycles=config.target_cycles,
            track_radius=track_radius,
            spring_inventory=config.spring_inventory,
        )

        if spring_result is None:
            # Fallback to simplified rules if calculator fails
            logger.warning(
                f"Spring calculator returned no result for {door_weight:.0f} lbs, "
                f"{config.door_height}\" height - falling back to simplified rules"
            )
            wire_size = 0.234
            coil_id = 2.0
            spring_length = 29
            spring_qty = 2
            is_duplex = False
        else:
            wire_size = spring_result.wire_diameter
            coil_id = spring_result.coil_diameter
            spring_length = int(spring_result.length)
            spring_qty = spring_result.quantity
            is_duplex = spring_result.is_duplex

        # Residential doors: if wire < .218 with 2+ springs, retry with 1 spring
        # BC minimum wire is .218 — anything smaller has no BC part number
        if wire_size < 0.218 and config.door_type == "residential" and spring_qty >= 2:
            # Parse track radius (handle string format)
            retry_track_radius = int(config.track_radius) if config.track_radius else 15
            single_result = door_calculator._calculate_springs(
                door_weight=door_weight,
                height_inches=config.door_height,
                width_inches=config.door_width,
                drums=None,
                target_cycles=config.target_cycles,
                track_radius=retry_track_radius,
                spring_qty=1,
                spring_inventory=config.spring_inventory,
            )
            if single_result and single_result.wire_diameter >= 0.218:
                wire_size = single_result.wire_diameter
                coil_id = single_result.coil_diameter
                spring_length = int(single_result.length)
                spring_qty = single_result.quantity
                is_duplex = single_result.is_duplex
                logger.info(
                    f"Residential door: reduced to 1 spring with {wire_size}\" wire "
                    f"(original had <.218\" wire with {spring_result.quantity} springs)"
                )
            else:
                # Force minimum .218 wire — mapper's next-size-up handles rounding
                wire_size = 0.218
                logger.warning(
                    f"Residential door: forced wire to .218 minimum "
                    f"(1-spring retry still gave <.218\" wire)"
                )

        # Get BC Part Number Mapper
        mapper = get_bc_mapper()

        # How many LH/RH pairs (each pair = 1 LH + 1 RH)
        pairs = spring_qty // 2

        # Outer springs (LH and RH)
        spring_lh = mapper.get_spring_part_number(wire_size, coil_id, "LH")
        spring_rh = mapper.get_spring_part_number(wire_size, coil_id, "RH")

        # Validate spring exists in BC — if not, step up wire until we find one
        if spring_lh.part_number not in mapper.spring_items:
            for bc_wire in sorted(mapper.WIRE_SIZE_CODES.keys()):
                if bc_wire >= wire_size:
                    test_lh = mapper.get_spring_part_number(bc_wire, coil_id, "LH")
                    if test_lh.part_number in mapper.spring_items:
                        logger.info(
                            f"Spring {spring_lh.part_number} not in BC — "
                            f"stepped up wire from {wire_size}\" to {bc_wire}\""
                        )
                        wire_size = bc_wire
                        spring_lh = test_lh
                        spring_rh = mapper.get_spring_part_number(bc_wire, coil_id, "RH")
                        break

        # Springs are quoted by length (inches of spring) × number of that wind
        parts.append(PartSelection(
            part_number=spring_lh.part_number,
            description=spring_lh.description,
            quantity=spring_length * pairs,
            category="spring",
            notes=f"Spring: {wire_size}\" x {coil_id}\" x {spring_length}\" LH × {pairs}"
        ))

        parts.append(PartSelection(
            part_number=spring_rh.part_number,
            description=spring_rh.description,
            quantity=spring_length * pairs,
            category="spring",
            notes=f"Spring: {wire_size}\" x {coil_id}\" x {spring_length}\" RH × {pairs}"
        ))

        # If duplex, also add inner springs
        if is_duplex and spring_result:
            inner_wire = spring_result.inner_wire_diameter
            inner_coil = spring_result.inner_coil_diameter
            inner_length = int(spring_result.inner_length)
            duplex_pairs = spring_result.duplex_pairs

            inner_lh = mapper.get_spring_part_number(inner_wire, inner_coil, "LH")
            inner_rh = mapper.get_spring_part_number(inner_wire, inner_coil, "RH")

            parts.append(PartSelection(
                part_number=inner_lh.part_number,
                description=inner_lh.description,
                quantity=inner_length * duplex_pairs,
                category="spring",
                notes=f"Inner spring: {inner_wire}\" x {inner_coil}\" x {inner_length}\" LH × {duplex_pairs}"
            ))
            parts.append(PartSelection(
                part_number=inner_rh.part_number,
                description=inner_rh.description,
                quantity=inner_length * duplex_pairs,
                category="spring",
                notes=f"Inner spring: {inner_wire}\" x {inner_coil}\" x {inner_length}\" RH × {duplex_pairs}"
            ))

            # Winder/stationary sets for inner coil size
            inner_winder_lh = mapper.get_winder_stationary_set(inner_coil, 1.0, "LH")
            inner_winder_rh = mapper.get_winder_stationary_set(inner_coil, 1.0, "RH")
            parts.append(PartSelection(
                part_number=inner_winder_lh.part_number,
                description=inner_winder_lh.description,
                quantity=1,
                category="spring_accessory"
            ))
            parts.append(PartSelection(
                part_number=inner_winder_rh.part_number,
                description=inner_winder_rh.description,
                quantity=1,
                category="spring_accessory"
            ))

        # Add winder/stationary sets for outer coil
        winder_lh = mapper.get_winder_stationary_set(coil_id, 1.0, "LH")
        winder_rh = mapper.get_winder_stationary_set(coil_id, 1.0, "RH")

        parts.append(PartSelection(
            part_number=winder_lh.part_number,
            description=winder_lh.description,
            quantity=1,
            category="spring_accessory"
        ))

        parts.append(PartSelection(
            part_number=winder_rh.part_number,
            description=winder_rh.description,
            quantity=1,
            category="spring_accessory"
        ))

        return parts

    def _get_shaft_parts(self, config: DoorConfiguration) -> List[PartSelection]:
        """Get shaft part numbers using actual BC parts.

        Shaft type selection:
        - Residential + weight <= 750 lbs  → 1\" tube shaft (SH12)
        - Residential + weight >  750 lbs  → 1\" solid keyed shaft (SH11)
        - Commercial (any weight <= 2000)   → 1\" solid keyed shaft (SH11)
        - Any door   + weight >  2000 lbs  → 1-1/4\" keyed shaft (SH10-00002-00)

        Solid shaft sizing (single):
          Physical length of SH11-1FF06 = FF*12 + 6 inches.
          Must cover door_width + 16". Rearranging: FF >= (door_width + 10) / 12.
          required_ff = ceil((door_width_in + 10) / 12)
          Max SH11 = 15'-6" (186"). Single shaft works for doors up to 170" (14'2").

        Split shaft sizing (2× SH11 + coupler):
          Each half covers (door_width + 16) / 2.
          FF*12+6 >= (door_width+16)/2 → FF >= (door_width + 4) / 24.
          required_ff_each = ceil((door_width_in + 4) / 24)
          Triggered automatically when door_width > 170" or when shaft_preference == 'split'.
        """
        mapper = get_bc_mapper()

        # Calculate door weight to determine shaft type
        door_weight = config.door_weight
        if door_weight is None:
            door_weight = self._calculate_door_weight(config)

        is_residential = config.door_type == "residential"

        # Convenience helpers for the description
        actual_ft = config.door_width // 12
        actual_in = config.door_width % 12
        width_display = f"{actual_ft}'{actual_in}\"" if actual_in else f"{actual_ft}'"

        if door_weight > 2000:
            # Very heavy door — 1-1/4" keyed shaft regardless of type
            shaft = mapper.get_shaft(door_width_feet=0, shaft_type="1-1/4")
            return [PartSelection(
                part_number=shaft.part_number,
                description=shaft.description,
                quantity=1,
                category="shaft"
            )]

        if is_residential and door_weight <= 750:
            # Light residential — 1" tube shaft (no split needed, max SH12 is 18'-10")
            door_width_feet = math.ceil(config.door_width / 12)
            shaft = mapper.get_shaft(door_width_feet=door_width_feet, shaft_type="tube")
            return [PartSelection(
                part_number=shaft.part_number,
                description=f"1\" Tube Shaft {width_display} door width",
                quantity=1,
                category="shaft"
            )]

        # Heavy residential OR any commercial — 1" solid keyed shaft (SH11)
        # Determine whether to use split shaft:
        #   - auto: split when door_width > 170" (max single SH11 covers 170" door)
        #   - split: always split
        #   - single: always single (warn if too wide)
        use_split = (
            config.shaft_preference == 'split' or
            (config.shaft_preference == 'auto' and config.door_width > 170)
        )

        if use_split:
            # Two SH11 shafts (offset sizes) + one coupler
            # Total combined length must be >= door_width + 16"
            # Use offset pair (one shorter, one longer) to minimize total overhang
            needed = config.door_width + 16
            coupler = mapper.get_shaft_coupler(bore_size=1.0)

            # Get all available SH11 sizes from the mapper
            available_sh11 = []
            for pn, item in mapper.bc_items.items():
                if (pn.startswith("SH11-1") and len(pn) == 13 and
                        pn[8:10] == "06" and pn.endswith("-00")):
                    try:
                        ff = int(pn[6:8])
                        available_sh11.append(ff)
                    except ValueError:
                        pass
            available_sh11.sort()

            if not available_sh11:
                # Fallback: typical SH11 sizes (7'6" through 15'6")
                available_sh11 = [7, 8, 9, 10, 11, 12, 13, 14, 15]

            # Find best offset pair: two different sizes whose combined length >= needed
            # minimizing total overhang
            best_pair = None
            best_overhang = float('inf')
            for i, ff_a in enumerate(available_sh11):
                len_a = ff_a * 12 + 6
                for ff_b in available_sh11[i:]:
                    len_b = ff_b * 12 + 6
                    total = len_a + len_b
                    if total >= needed:
                        overhang = total - needed
                        if overhang < best_overhang:
                            best_overhang = overhang
                            best_pair = (ff_a, ff_b)

            if best_pair is None:
                # Use two of the largest available
                best_pair = (available_sh11[-1], available_sh11[-1])

            ff_a, ff_b = best_pair
            shaft_a = mapper.get_shaft(door_width_feet=ff_a, shaft_type="solid")
            shaft_b = mapper.get_shaft(door_width_feet=ff_b, shaft_type="solid")

            total_length = (ff_a * 12 + 6) + (ff_b * 12 + 6)
            if total_length < needed:
                logger.warning(
                    f"Split shaft total {total_length}\" still short for {width_display} door "
                    f"(need {needed}\"): using {shaft_a.part_number} + {shaft_b.part_number}"
                )

            parts = []
            if ff_a == ff_b:
                # Same size — qty 2
                parts.append(PartSelection(
                    part_number=shaft_a.part_number,
                    description=f"1\" Solid Shaft Keyed {width_display} door width (split)",
                    quantity=2,
                    category="shaft"
                ))
            else:
                # Offset pair — qty 1 each
                parts.append(PartSelection(
                    part_number=shaft_a.part_number,
                    description=f"1\" Solid Shaft Keyed {width_display} door width (split - short side)",
                    quantity=1,
                    category="shaft"
                ))
                parts.append(PartSelection(
                    part_number=shaft_b.part_number,
                    description=f"1\" Solid Shaft Keyed {width_display} door width (split - long side)",
                    quantity=1,
                    category="shaft"
                ))
            parts.append(PartSelection(
                part_number=coupler.part_number,
                description=coupler.description,
                quantity=1,
                category="shaft"
            ))
            return parts

        else:
            # Single solid shaft
            # FF*12+6 >= door_width+16 → FF >= (door_width+10)/12
            required_ff = math.ceil((config.door_width + 10) / 12)
            shaft = mapper.get_shaft(door_width_feet=required_ff, shaft_type="solid")

            selected_ff = int(shaft.part_number[6:8])
            physical_length = selected_ff * 12 + 6
            needed = config.door_width + 16
            if physical_length < needed:
                logger.warning(
                    f"No solid shaft long enough for {width_display} door "
                    f"(need {needed}\", max available {physical_length}\"): "
                    f"using {shaft.part_number}"
                )

            return [PartSelection(
                part_number=shaft.part_number,
                description=f"1\" Solid Shaft Keyed {width_display} door width",
                quantity=1,
                category="shaft"
            )]

    def _get_strut_parts(self, config: DoorConfiguration) -> List[PartSelection]:
        """Get strut part numbers using actual BC parts"""
        mapper = get_bc_mapper()

        door_width_feet = config.door_width // 12
        # Commercial doors >16' wide get 16ga struts; all others get 20ga
        if config.door_type == "commercial" and config.door_width > 192:
            gauge = 16
        else:
            gauge = 20

        # Get strut part number
        strut = mapper.get_strut(door_width_feet, gauge)

        # Strut quantity based on door size
        if config.door_width <= 108:  # Up to 9'
            strut_count = 1
        elif config.door_width <= 192:  # Up to 16'
            strut_count = 2
        else:
            strut_count = 3

        return [PartSelection(
            part_number=strut.part_number,
            description=strut.description,
            quantity=strut_count,
            category="strut"
        )]

    def _get_hardware_kit_parts(self, config: DoorConfiguration) -> List[PartSelection]:
        """Get hardware box part numbers using actual BC part numbers.

        Uses bc_part_number_mapper to generate correct part numbers:
        - Residential (2" track): HK10-0HHSS-WWWW pattern
        - Commercial (3" track): HWww-hhhhh-00 pattern
        """
        mapper = get_bc_mapper()

        door_width_feet = int(config.door_width / 12)
        door_height_feet = int(config.door_height / 12)
        # Hardware box type follows track thickness, not door type
        # 3" track → commercial HW box (HK03/HW), 2" track → residential HW box (HK02/HK10)
        is_commercial = config.track_thickness == '3'

        # Calculate number of sections based on door height
        num_sections = self._calculate_panel_count(config.door_height)

        hardware = mapper.get_hardware_box(
            door_width_feet=door_width_feet,
            door_height_feet=door_height_feet,
            num_sections=num_sections,
            commercial=is_commercial
        )

        return [PartSelection(
            part_number=hardware.part_number,
            description=hardware.description,
            quantity=1,
            category="hardware"
        )]

    def _get_seal_parts(self, config: DoorConfiguration) -> List[PartSelection]:
        """
        Get weather stripping part numbers using actual BC parts.

        Weather stripping rules:
        - 2 pieces for the height (one per side - left and right jambs)
        - 1 piece for the width (header/top)

        Example: 16x7 door = 2x 7' strips (sides) + 1x 16' strip (header)
        """
        parts = []
        mapper = get_bc_mapper()

        # Round UP to next available strip length (strips must cover the full dimension)
        door_height_feet = math.ceil(config.door_height / 12)
        door_width_feet = math.ceil(config.door_width / 12)
        color = config.panel_color.replace("_", " ")
        is_commercial = config.door_type == "commercial"

        # Helper to format actual dimension display string (e.g. 90" → "7'6\"")
        def _dim_display(total_inches: int) -> str:
            ft = total_inches // 12
            inches = total_inches % 12
            return f"{ft}'{inches}\"" if inches else f"{ft}'"

        actual_h_display = _dim_display(config.door_height)
        actual_w_display = _dim_display(config.door_width)
        color_upper = color.upper()

        # Get weather strip for HEIGHT (sides) - quantity 2
        height_strip = mapper.get_weather_stripping(
            door_height_feet=door_height_feet,
            color=color,
            commercial=is_commercial
        )
        parts.append(PartSelection(
            part_number=height_strip.part_number,
            description=(
                f"PLASTICS, WEATHER STRIP, GALVANIZED STEEL/FLEXIBLE VINYL,"
                f" {color_upper}, {actual_h_display} (SIDES)"
            ),
            quantity=2,  # Always 2 for left and right jambs
            category="weather_stripping"
        ))

        # Get weather strip for WIDTH (header)
        # Max available strip length is 18'. For wider doors, split into 2 pieces.
        if door_width_feet > 18:
            half_feet = math.ceil(door_width_feet / 2)
            width_strip = mapper.get_weather_stripping(
                door_height_feet=half_feet,
                color=color,
                commercial=is_commercial
            )
            parts.append(PartSelection(
                part_number=width_strip.part_number,
                description=(
                    f"PLASTICS, WEATHER STRIP, GALVANIZED STEEL/FLEXIBLE VINYL,"
                    f" {color_upper}, {actual_w_display} (HEADER - SPLIT 2PCS)"
                ),
                quantity=2,
                category="weather_stripping"
            ))
        else:
            width_strip = mapper.get_weather_stripping(
                door_height_feet=door_width_feet,
                color=color,
                commercial=is_commercial
            )
            parts.append(PartSelection(
                part_number=width_strip.part_number,
                description=(
                    f"PLASTICS, WEATHER STRIP, GALVANIZED STEEL/FLEXIBLE VINYL,"
                    f" {color_upper}, {actual_w_display} (HEADER)"
                ),
                quantity=1,
                category="weather_stripping"
            ))

        return parts

    def _get_bottom_retainer_parts(self, config: DoorConfiguration) -> List[PartSelection]:
        """Get retainer and astragal part numbers using actual BC parts (legacy method)"""
        parts = []
        parts.extend(self._get_retainer_only_parts(config))
        parts.extend(self._get_astragal_only_parts(config))
        return parts

    def _get_retainer_only_parts(self, config: DoorConfiguration) -> List[PartSelection]:
        """Get retainer part numbers only (without astragal)"""
        parts = []
        mapper = get_bc_mapper()

        # Commercial gets top + bottom retainer; residential gets bottom only
        retainer = mapper.get_retainer()
        if config.door_type != "residential":
            parts.append(PartSelection(
                part_number=retainer.part_number,
                description=f"{retainer.description} (TOP)",
                quantity=1,
                category="retainer"
            ))
        parts.append(PartSelection(
            part_number=retainer.part_number,
            description=f"{retainer.description} (BOTTOM)",
            quantity=1,
            category="retainer"
        ))

        return parts

    def _get_astragal_only_parts(self, config: DoorConfiguration) -> List[PartSelection]:
        """Get astragal (bottom rubber) part numbers only"""
        mapper = get_bc_mapper()
        door_width_feet = config.door_width / 12

        astragal = mapper.get_astragal(door_width_feet)
        return [PartSelection(
            part_number=astragal.part_number,
            description=astragal.description,
            quantity=1,
            category="astragal"
        )]

    def _get_top_seal_parts(self, config: DoorConfiguration) -> List[PartSelection]:
        """Get top seal parts (for insulated doors or when explicitly needed)

        Top seal is typically used on:
        - Insulated doors (TX450-20, TX500-20)
        - Doors with weather seal requirements
        """
        # Top seal on all commercial and aluminium doors
        if config.door_type not in ("commercial", "aluminium"):
            return []

        mapper = get_bc_mapper()
        # Round UP to next available strip length
        door_width_feet = math.ceil(config.door_width / 12)

        # Top seal uses same weather stripping as header
        # but categorized separately for ordering
        color = config.panel_color.replace("_", " ")
        is_commercial = config.door_type == "commercial"

        top_seal = mapper.get_weather_stripping(
            door_height_feet=door_width_feet,  # Width for header
            color=color,
            commercial=is_commercial
        )

        # Description shows the customer's actual requested door width
        actual_ft = config.door_width // 12
        actual_in = config.door_width % 12
        w_display = f"{actual_ft}'{actual_in}\"" if actual_in else f"{actual_ft}'"
        color_upper = color.upper()

        return [PartSelection(
            part_number=top_seal.part_number,
            description=(
                f"PLASTICS, WEATHER STRIP, GALVANIZED STEEL/FLEXIBLE VINYL,"
                f" {color_upper}, {w_display} (TOP SEAL)"
            ),
            quantity=1,
            category="top_seal"
        )]

    def _get_highlift_parts(self, config: DoorConfiguration) -> List[PartSelection]:
        """Get highlift or lowheadroom track parts if applicable

        Highlift/lowheadroom is determined by:
        - Explicit configuration (future: add to DoorConfiguration)
        - Track radius requirements
        - Ceiling height constraints

        For now, returns empty list - can be extended when highlift
        configuration is added to the door configurator.
        """
        # TODO: Add highlift/lowheadroom detection when config supports it
        # Example conditions:
        # - config.lift_type == "highlift"
        # - config.lift_type == "lowheadroom"
        # - config.headroom < standard_headroom

        # Currently no highlift parts - return empty
        return []

    def _get_aluminum_section_parts(self, config: DoorConfiguration) -> List[PartSelection]:
        """Get aluminum door section parts (PN97, PN80, PN20) + glass for all panels.

        AL976 (PN97): PN97-{hh}{www}{f}{p}{s}-{wwww}
          hh  = section height (21 or 24)
          www = width group (200=8'-9', 300=10', 400=12'-14', 500=16', 600=18'-20')
          f   = finish (0=Clear Ano, 1=Mill, 3=White, 8=Black Ano)
          p   = position (1=TOP SEF, 2=INT SEF, 3=BOT SEF, 4=TOP DEF, 5=INT DEF, 6=BOT DEF)
          s   = option (0=NO OPT for SEF; DEF: TOP=5, INT=2, BOT=1)
          wwww = door width + 2" overhang (e.g. 0802=8'2")

        Panorama (PN80): PN80-{hh}{s}{ff}-{wwww}
          hh = 21 or 24, s = 1(TOP/INT) or 2(BOT), ff = 00/10/20/30
          wwww = door width + 2"

        Solalite (PN20): PN20-{hh}00{f}{p}{s}-{wwww}
          hh = 21 or 24, f = 0(Clear Ano) or 1(Mill)
          p = 1-6 (same as PN97), s = 0(NO OPT), 1(DOUBLE), 3(THERM Y)
          wwww = door width + 2"
        """
        parts = []
        series = config.door_series.upper()
        panel_count = self._calculate_panel_count(config.door_height)

        # Section height: 21" for ≤7' doors, 24" for 8'+ doors
        section_height = 21 if config.door_height <= 84 else 24
        hh = str(section_height)

        # Width code: door width + 2" overhang
        width_ft = config.door_width // 12
        width_extra = config.door_width % 12 + 2
        if width_extra >= 12:
            width_ft += 1
            width_extra -= 12
        wwww = f"{width_ft:02d}{width_extra:02d}"

        # Finish code from panel_color
        finish_color = (config.panel_color or "CLEAR_ANODIZED").upper().replace(" ", "_")

        # Determine if door needs DEF sections (wider doors)
        door_width_feet = config.door_width / 12

        if series == "AL976":
            # PN97 width groups
            if door_width_feet <= 9:
                www = "200"
            elif door_width_feet <= 10:
                www = "300"
            elif door_width_feet <= 14:
                www = "400"
            elif door_width_feet <= 16:
                www = "500"
            else:
                www = "600"

            # Finish digit
            finish_map = {"CLEAR_ANODIZED": "0", "MILL": "1", "WHITE": "3", "BLACK_ANODIZED": "8"}
            f = finish_map.get(finish_color, "0")
            finish_name = {"0": "CLEAR ANO", "1": "MILL", "3": "WHITE", "8": "BLACK ANODIZED"}.get(f, "CLEAR ANO")

            # 600 group (18'+) only has DEF sections
            use_def = www == "600" or door_width_feet > 16

            for section_num in range(1, panel_count + 1):
                if section_num == 1:
                    pos_label = "TOP"
                elif section_num == panel_count:
                    pos_label = "BOT"
                else:
                    pos_label = "INT"

                if use_def:
                    p_map = {"TOP": "4", "INT": "5", "BOT": "6"}
                    s_map = {"TOP": "5", "INT": "2", "BOT": "1"}  # TOP=DOUBLE&FR, INT=FR, BOT=DOUBLE
                    p = p_map[pos_label]
                    s = s_map[pos_label]
                    end_label = "DEF"
                    opt_map = {"5": "DOUBLE & FR", "2": "FR", "1": "DOUBLE"}
                    opt_label = opt_map.get(s, "")
                else:
                    p_map = {"TOP": "1", "INT": "2", "BOT": "3"}
                    p = p_map[pos_label]
                    s = "0"
                    end_label = "SEF"
                    opt_label = "NO OPT."

                pn = f"PN97-{hh}{www}{f}{p}{s}-{wwww}"
                parts.append(PartSelection(
                    part_number=pn,
                    description=f"SECTION, AL976, [{width_ft:02d}' {width_extra:02d}\"] X {section_height}\", {pos_label} {end_label}, {opt_label}, {finish_name}",
                    quantity=1,
                    category="aluminum_section",
                    notes=f"AL976 section {section_num} of {panel_count}"
                ))

        elif series == "PANORAMA":
            # PN80: simpler encoding
            finish_map = {"CLEAR_ANODIZED": "00", "WHITE": "10", "MILL": "20", "BLACK_ANODIZED": "30"}
            ff = finish_map.get(finish_color, "00")
            finish_name = {"00": "CLEAR ANODIZED", "10": "WHITE", "20": "MILL", "30": "BLACK ANODIZED"}.get(ff, "CLEAR ANODIZED")

            for section_num in range(1, panel_count + 1):
                if section_num == panel_count:
                    s = "2"  # BOT SEF
                    pos_label = "BOTTOM SEF"
                else:
                    s = "1"  # TOP/INT SEF
                    pos_label = "TOP/INTERMEDIATE SEF"

                pn = f"PN80-{hh}{s}{ff}-{wwww}"
                parts.append(PartSelection(
                    part_number=pn,
                    description=f"SECTION, PANORAMA, [{width_ft:02d}' {width_extra:02d}\"] X {section_height}\", {pos_label}, {finish_name}",
                    quantity=1,
                    category="aluminum_section",
                    notes=f"Panorama section {section_num} of {panel_count}"
                ))

        elif series == "SOLALITE":
            # PN20: {hh}00{f}{p}{s}-{wwww}
            finish_map = {"CLEAR_ANODIZED": "0", "MILL": "1"}
            f = finish_map.get(finish_color, "0")
            finish_name = "CLEAR ANO" if f == "0" else "MILL"

            # Determine if DEF needed (>12' uses DEF)
            use_def = door_width_feet > 12

            for section_num in range(1, panel_count + 1):
                if section_num == 1:
                    pos_label = "TOP"
                elif section_num == panel_count:
                    pos_label = "BOT"
                else:
                    pos_label = "INT"

                if use_def:
                    p_map = {"TOP": "4", "INT": "5", "BOT": "6"}
                    p = p_map[pos_label]
                    s = "1"  # DOUBLE for DEF
                    end_label = "DEF"
                    opt_label = "DOUBLE"
                else:
                    p_map = {"TOP": "1", "INT": "2", "BOT": "3"}
                    p = p_map[pos_label]
                    s = "0"
                    end_label = "SEF"
                    opt_label = "NO OPT."

                pn = f"PN20-{hh}00{f}{p}{s}-{wwww}"
                parts.append(PartSelection(
                    part_number=pn,
                    description=f"SECTION, SOLALITE, [{width_ft:02d}' {width_extra:02d}\"] X {section_height}\", {pos_label} {end_label}, {opt_label}, {finish_name}",
                    quantity=1,
                    category="aluminum_section",
                    notes=f"Solalite section {section_num} of {panel_count}"
                ))

        # Glazing — GL20 glass for AL976, GK17 polycarbonate for Panorama/Solalite
        glazing_sqft_per_section = (config.door_width * section_height) / 144
        total_glazing_sqft = round(glazing_sqft_per_section * panel_count, 2)

        if series in ("PANORAMA", "SOLALITE"):
            # Polycarbonate glazing kits
            glass_color = (config.glass_color or "CLEAR").upper()
            gk17_map = {
                "CLEAR":        ("GK17-12500-00", "GLAZING KIT, ALUM, POLYCARBONATE, CLEAR"),
                "LIGHT_BRONZE": ("GK17-12600-00", "GLAZING KIT, ALUM, POLYCARBONATE, LIGHT BRONZE"),
                "DARK_BRONZE":  ("GK17-12700-00", "GLAZING KIT, ALUM, POLYCARBONATE, DARK BRONZE"),
                "WHITE_OPAL":   ("GK17-12800-00", "GLAZING KIT, ALUM, POLYCARBONATE, WHITE OPAL"),
            }
            poly_pn, poly_desc = gk17_map.get(glass_color, ("GK17-12500-00", "GLAZING KIT, ALUM, POLYCARBONATE, CLEAR"))

            parts.append(PartSelection(
                part_number=poly_pn,
                description=poly_desc,
                quantity=total_glazing_sqft,
                category="aluminum_glazing",
                notes=f"Polycarbonate for {panel_count} sections ({glazing_sqft_per_section:.2f} sqft each)"
            ))
        else:
            # AL976 — GL20 glass
            glass_color = (config.glass_color or "CLEAR").upper()
            pane_type = (config.glass_pane_type or "INSULATED").upper()

            gl20_map = {
                ("CLEAR", "INSULATED"):      ("GL20-00300-01", "GLASS, 3MM THERMO CLEAR/CLEAR"),
                ("CLEAR", "SINGLE"):         ("GL20-00100-01", "GLASS, 3MM SINGLE CLEAR"),
                ("ETCHED", "INSULATED"):     ("GL20-00300-02", "GLASS, 3MM THERMO CLEAR/ETCHED"),
                ("ETCHED", "SINGLE"):        ("GL20-00100-02", "GLASS, 3MM SINGLE ETCHED"),
                ("SUPER_GREY", "INSULATED"): ("GL20-00300-03", "GLASS, 3MM THERMO SUPER GREY"),
                ("SUPER_GREY", "SINGLE"):    ("GL20-00100-03", "GLASS, 3MM SINGLE SUPER GREY"),
            }
            glass_pn, glass_desc = gl20_map.get(
                (glass_color, pane_type),
                ("GL20-00300-01", "GLASS, 3MM THERMO CLEAR/CLEAR")
            )

            parts.append(PartSelection(
                part_number=glass_pn,
                description=glass_desc,
                quantity=total_glazing_sqft,
                category="aluminum_glass",
                notes=f"Glass for {panel_count} sections ({glazing_sqft_per_section:.2f} sqft each)"
            ))

        return parts

    def _build_window_placement_note(self, config: DoorConfiguration) -> Optional[str]:
        """Build a human-readable note describing where windows should be placed."""
        if config.window_panels:
            # Per-panel config: e.g. {1: {"qty": 3}, 3: {"qty": 2}}
            panel_descs = []
            for panel_num in sorted(config.window_panels.keys()):
                qty = config.window_panels[panel_num].get("qty", 1)
                panel_descs.append(f"Panel {panel_num}: {qty} window{'s' if qty > 1 else ''}")
            return "WINDOWS: " + ", ".join(panel_descs)
        elif config.window_count > 0:
            section = config.window_section or 1
            return f"WINDOWS: Section {section}, {config.window_count} per panel"
        return None

    def _get_window_parts(self, config: DoorConfiguration) -> List[PartSelection]:
        """Get window/glass kit part numbers using GK15 (residential) or GK16 (commercial).

        For residential KANATA doors:
          SHORT windows (GK15-10xxx): fit one short stamp on SH/BC designs.
            No decorative frame inserts available (BC catalog has none for short).
          LONG windows (GK15-11xxx): fit one long stamp on SHXL/BCXL, or span 2
            short stamps on SH/BC.  Decorative GL18 frame inserts are available.
        """
        # V130G: full-view aluminum section + glass (separate line items)
        if config.window_insert == "V130G":
            return self._get_v130g_parts(config)

        # Commercial thermopane windows (24x12, 34x16, 18x8)
        if config.window_insert in ("24X12_THERMOPANE", "34X16_THERMOPANE", "18X8_THERMOPANE"):
            return self._get_commercial_window_parts(config)

        # Residential window glass kits — build GK15 part number
        mapper = get_bc_mapper()

        # SS: determined by window_size field ('short' → GK15-10xxx, 'long' → GK15-11xxx)
        # PLAIN_SHORT / PLAIN_LONG are sentinels sent when no decorative insert is selected.
        effective_size = config.window_size or 'long'
        if config.window_insert == 'PLAIN_SHORT':
            effective_size = 'short'
        elif config.window_insert == 'PLAIN_LONG':
            effective_size = 'long'

        is_short = effective_size == 'short'

        series_upper = config.door_series.upper()
        if series_upper in ("KANATA", "KANATA_EXECUTIVE"):
            ss = "10" if is_short else "11"  # KANATA SHORT / KANATA LONG
        elif series_upper == "CRAFT":
            ss = "55"  # CRAFT LONG (Craft sections are 28"/32", always LONG)
        else:
            ss = "11"  # Default to KANATA LONG

        # G: Glass type digit
        glass_type_map = {
            ("SINGLE", None): "1",
            ("SINGLE", "CLEAR"): "1",
            ("INSULATED", None): "2",
            ("INSULATED", "CLEAR"): "2",
            ("INSULATED", "ETCHED"): "4",
            ("INSULATED", "SUPER_GREY"): "9",
        }
        pane = (config.glass_pane_type or "INSULATED").upper()
        color = (config.glass_color or "CLEAR").upper()
        g = glass_type_map.get((pane, color), glass_type_map.get((pane, None), "2"))

        # CC: Color code (reuse mapper's COLOR_CODES)
        panel_color_normalized = config.panel_color.replace("_", " ").upper()
        cc = mapper.COLOR_CODES.get(panel_color_normalized, "00")

        # Build GK15 part number
        gk15_pn = f"GK15-{ss}{g}{cc}-00"

        # Validate against BC items
        validated = mapper.get_glass_kit(gk15_pn, "residential")
        if validated:
            part_number = validated.part_number
            description = validated.description
        else:
            part_number = gk15_pn
            glass_label = {"1": "SINGLE", "2": "THERM-CLEAR", "4": "THERM-ETCHED", "9": "SUPER GREY"}.get(g, "THERM-CLEAR")
            size_label = "SHORT" if is_short else "LONG"
            description = f"GLASS KIT, 1-3/4\" KANATA, {size_label}, {glass_label}, {panel_color_normalized}"

        # Window quantity: use actual window count from positions, or estimate from door width
        window_qty = config.window_count or max(1, config.door_width // 24)

        # Build window placement note
        window_note = self._build_window_placement_note(config)

        parts = [PartSelection(
            part_number=part_number,
            description=description,
            quantity=window_qty,
            category="window",
            notes=window_note,
        )]

        # Add GL18 frame insert for decorative LONG windows (no inserts for SHORT)
        decorative_inserts = {
            "STOCKTON_STANDARD", "STOCKTON_EIGHT_SQUARE", "STOCKTON_TEN_SQUARE_XL",
            "STOCKTON_ARCHED", "STOCKTON_ARCHED_XL",
            "STOCKBRIDGE_STRAIGHT", "STOCKBRIDGE_STRAIGHT_XL",
            "STOCKBRIDGE_ARCHED", "STOCKBRIDGE_ARCHED_XL",
        }
        if not is_short and config.window_insert in decorative_inserts:
            frame_insert = mapper.get_frame_insert(config.window_insert, config.panel_color)
            if frame_insert:
                parts.append(PartSelection(
                    part_number=frame_insert.part_number,
                    description=frame_insert.description,
                    quantity=window_qty,
                    category="window"
                ))

        return parts

    def _get_v130g_parts(self, config: DoorConfiguration) -> List[PartSelection]:
        """
        Get V130G full-view section parts using real BC PN10 part numbers.

        BC part number format: PN10-{hh}{w}{fff}{pp}-{wwww}
          hh  = section height (21 or 24)
          w   = width group (2=8', 3=10', 4=12'-14', 5=16', 6=18'+)
          fff = finish (000=Clear Ano, 001=Mill, 003=White, 008=Black)
          pp  = position (SEF: 10=TOP, 20=INT, 30=BOT | DEF: 45=TOP, 52=INT, 61=BOT)
          wwww = section width (0802=8'2", 1602=16'2", 2200=22'0", etc.)

        Glass is separate: GL20-xxxxx-xx
        """
        parts = []
        v130g_qty = config.window_qty or 1

        # Section height: 21" for residential/7' doors, 24" for commercial/8'+ doors
        section_height = 21 if config.door_type == "residential" or config.door_height <= 84 else 24
        hh = str(section_height)

        # Width group
        door_width_feet = config.door_width / 12
        if door_width_feet <= 9:
            w = "2"
        elif door_width_feet <= 10:
            w = "3"
        elif door_width_feet <= 14:
            w = "4"
        elif door_width_feet <= 16:
            w = "5"
        else:
            w = "6"

        # Finish code based on door color
        finish_map = {
            "WHITE": ("003", "WHITE"),
            "BRIGHT_WHITE": ("003", "WHITE"),
            "BLACK": ("008", "BLACK"),
            "STEEL_GREY": ("000", "CLEAR ANO"),
        }
        fff, finish_name = finish_map.get(config.panel_color, ("000", "CLEAR ANO"))

        # SEC vs DEC: match the door's end cap type (>16' uses DEC)
        is_dec = door_width_feet > 16

        # Position codes
        sef_positions = {"TOP": "10", "INT": "20", "BOT": "30"}
        def_positions = {"TOP": "45", "INT": "52", "BOT": "61"}
        pos_codes = def_positions if is_dec else sef_positions
        end_cap_label = "DEF" if is_dec else "SEF"

        # Width code: door width + 2" overhang (exception: 22' = 2200)
        width_ft = config.door_width // 12
        width_extra = config.door_width % 12 + 2
        if width_extra >= 12:
            width_ft += 1
            width_extra -= 12
        # Special case: 22' doors use 2200 not 2202
        if config.door_width == 264:  # 22'
            wwww = "2200"
        else:
            wwww = f"{width_ft:02d}{width_extra:02d}"

        # Determine position for each V130G section
        panel_count = self._calculate_panel_count(config.door_height)

        # Build list of section numbers to generate
        if config.window_panels:
            section_numbers = sorted(config.window_panels.keys())
            v130g_qty = len(section_numbers)
        else:
            section_start = config.window_section or 1
            section_numbers = [section_start + i for i in range(v130g_qty)]

        for section_num in section_numbers:
            if section_num == 1:
                position = "TOP"
            elif section_num >= panel_count:
                position = "BOT"
            else:
                position = "INT"

            pp = pos_codes[position]
            pn = f"PN10-{hh}{w}{fff}{pp}-{wwww}"

            parts.append(PartSelection(
                part_number=pn,
                description=f"V130G FULL VIEW SECTION, {section_height}\" x {width_ft}'{width_extra}\", {position} {end_cap_label}, {finish_name}",
                quantity=1,
                category="v130g_section",
                notes=f"Full view aluminum section - replaces insulated panel at section {section_num}"
            ))

        # V130G Glass (GL20 series, separate from section frame)
        # Map glass color + pane type to GL20 part number
        glass_color = (config.glass_color or "CLEAR").upper()
        pane_type = (config.glass_pane_type or "INSULATED").upper()

        gl20_map = {
            ("CLEAR", "INSULATED"):    ("GL20-00300-01", "GLASS, 3MM V130G THERMO CLEAR/CLEAR"),
            ("CLEAR", "SINGLE"):       ("GL20-00100-01", "GLASS, 3MM V130G SINGLE CLEAR"),
            ("ETCHED", "INSULATED"):   ("GL20-00300-02", "GLASS, 3MM V130G THERMO CLEAR/ETCHED"),
            ("ETCHED", "SINGLE"):      ("GL20-00100-02", "GLASS, 3MM V130G SINGLE ETCHED"),
            ("SUPER_GREY", "INSULATED"): ("GL20-00300-03", "GLASS, 3MM V130G THERMO SUPER GREY"),
            ("SUPER_GREY", "SINGLE"):  ("GL20-00100-03", "GLASS, 3MM V130G SINGLE SUPER GREY"),
        }
        glass_pn, glass_desc = gl20_map.get(
            (glass_color, pane_type),
            ("GL20-00300-01", "GLASS, 3MM V130G THERMO CLEAR/CLEAR")
        )

        # Calculate glass square footage per section, then multiply by number of sections
        glass_sqft_per_section = (config.door_width * section_height) / 144
        total_glass_sqft = round(glass_sqft_per_section * v130g_qty, 2)

        parts.append(PartSelection(
            part_number=glass_pn,
            description=glass_desc,
            quantity=total_glass_sqft,
            category="v130g_glass",
            notes=f"Thermopane glass for {v130g_qty} V130G section(s) ({glass_sqft_per_section:.2f} sqft each)"
        ))

        return parts

    def _get_commercial_window_parts(self, config: DoorConfiguration) -> List[PartSelection]:
        """Get commercial thermopane window parts using GK16 part numbers.

        GK16 format: GK16-{S}3{G}{CC}-{VV}
          S  = Series: 2=TX450 (1-3/4"), 4=TX500 (2")
          G  = Glass type: 2=THERM-CLEAR
          CC = Color: 00=WHITE, 05=BLACK
          VV = Variant: 00=24x12, 01=24x8
        """
        mapper = get_bc_mapper()

        # S: Series digit
        series_upper = config.door_series.upper()
        if series_upper.startswith("TX500"):
            s = "4"
        else:
            s = "2"  # TX450 or default

        # G: Glass type (always THERM for commercial)
        g = "2"

        # CC: Frame color
        frame_color = config.window_frame_color.upper()
        if frame_color == "BLACK":
            cc = "05"
        else:
            cc = "00"  # WHITE or default

        # VV: Window size variant
        window_sizes = {
            "24X12_THERMOPANE": {"vv": "00", "desc": "24\" x 12\""},
            "18X8_THERMOPANE": {"vv": "01", "desc": "24\" x 8\""},
            "34X16_THERMOPANE": {"vv": "00", "desc": "34\" x 16\""},  # Uses same variant as 24x12
        }
        ws = window_sizes.get(config.window_insert, {"vv": "00", "desc": "24\" x 12\""})
        vv = ws["vv"]

        # Build GK16 part number
        gk16_pn = f"GK16-{s}3{g}{cc}-{vv}"

        # Validate against BC items
        validated = mapper.get_glass_kit(gk16_pn, "commercial")
        if validated:
            part_number = validated.part_number
            description = validated.description
        else:
            part_number = gk16_pn
            description = f"GLASS KIT, COMMERCIAL, THERM-CLEAR, {ws['desc']}, {frame_color}"

        # Per-panel window generation: if windowPanels is provided, emit one GK16 line per panel
        if config.window_panels:
            parts = []
            for panel_num in sorted(config.window_panels.keys()):
                panel_info = config.window_panels[panel_num]
                qty = panel_info.get("qty", 1)
                if qty > 0:
                    parts.append(PartSelection(
                        part_number=part_number,
                        description=description,
                        quantity=qty,
                        category="commercial_window",
                        notes=f"GK16 glass kit, panel {panel_num}, {frame_color} frame"
                    ))
            return parts if parts else [PartSelection(
                part_number=part_number,
                description=description,
                quantity=config.window_qty or 1,
                category="commercial_window",
                notes=f"GK16 glass kit, section {config.window_section or 1}, {frame_color} frame"
            )]

        qty = config.window_qty or 1

        return [PartSelection(
            part_number=part_number,
            description=description,
            quantity=qty,
            category="commercial_window",
            notes=f"GK16 glass kit, section {config.window_section or 1}, {frame_color} frame"
        )]

    def _get_operator_parts(self, config: DoorConfiguration) -> List[PartSelection]:
        """Get operator part numbers"""
        if not config.operator or config.operator == "NONE":
            return []

        op_type = "commercial" if config.door_type == "commercial" else "residential"
        op_pn = self.operator_rules.get(op_type, {}).get(config.operator, f"OP-{config.operator}")

        return [PartSelection(
            part_number=op_pn,
            description=f"Door Operator - {config.operator}",
            quantity=1,
            category="operator"
        )]

    def get_part_summary(self, parts: List[PartSelection]) -> Dict[str, Any]:
        """Get summary of parts by category"""
        summary = {
            "total_parts": len(parts),
            "by_category": {},
            "parts_list": []
        }

        for part in parts:
            if part.category not in summary["by_category"]:
                summary["by_category"][part.category] = []

            summary["by_category"][part.category].append({
                "part_number": part.part_number,
                "description": part.description,
                "quantity": part.quantity,
                "notes": part.notes
            })

            summary["parts_list"].append({
                "part_number": part.part_number,
                "description": part.description,
                "quantity": part.quantity,
                "category": part.category,
                "notes": part.notes
            })

        return summary


# Global instance
part_number_service = PartNumberService()


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def _parse_window_panels(raw) -> Optional[Dict[int, dict]]:
    """Convert windowPanels from JSON (string keys) to int keys."""
    if not raw or not isinstance(raw, dict):
        return None
    return {int(k): v for k, v in raw.items()}


def get_parts_for_door_config(config_dict: Dict[str, Any], spring_inventory: Optional[Dict[str, list]] = None) -> Dict[str, Any]:
    """
    Convenience function to get parts from a dictionary configuration.

    Args:
        config_dict: Dictionary with door configuration fields
        spring_inventory: Optional stocked coil/wire combos from settings

    Returns:
        Dictionary with parts summary
    """
    # Filter spring inventory to only include wire sizes that exist as BC part numbers
    # BC minimum spring wire is .218 — exclude .192, .207, etc. that Canimex tables list
    # but BC doesn't stock as actual items
    if spring_inventory:
        filtered = {}
        for coil_str, wire_list in spring_inventory.items():
            valid_wires = [w for w in wire_list if float(w) >= 0.218]
            if valid_wires:
                filtered[coil_str] = valid_wires
        spring_inventory = filtered if filtered else None

    config = DoorConfiguration(
        door_type=config_dict.get("doorType", "residential"),
        door_series=config_dict.get("doorSeries", "KANATA"),
        door_width=config_dict.get("doorWidth", 96),
        door_height=config_dict.get("doorHeight", 84),
        door_count=config_dict.get("doorCount", 1),
        panel_color=config_dict.get("panelColor", "WHITE"),
        panel_design=config_dict.get("panelDesign", "SHXL"),
        window_insert=config_dict.get("windowInsert"),
        window_section=config_dict.get("windowSection"),
        window_qty=config_dict.get("windowQty", 0),
        window_panels=_parse_window_panels(config_dict.get("windowPanels")),
        window_frame_color=config_dict.get("windowFrameColor", "BLACK"),
        glazing_type=config_dict.get("glazingType"),
        glass_pane_type=config_dict.get("glassPaneType"),
        glass_color=config_dict.get("glassColor"),
        track_radius=config_dict.get("trackRadius", "15"),
        track_thickness=config_dict.get("trackThickness", "2"),
        track_mount=config_dict.get("trackMount", "bracket"),
        hardware=config_dict.get("hardware", {}),
        operator=config_dict.get("operator"),
        target_cycles=config_dict.get("targetCycles", config_dict.get("target_cycles", 10000)),
        shaft_preference=config_dict.get("shaftType", "auto"),
        window_size=config_dict.get("windowSize", "long"),
        window_count=len(config_dict.get("windowPositions", [])) or config_dict.get("windowCount", 0),
        spring_inventory=spring_inventory,
    )

    parts = part_number_service.get_parts_for_configuration(config)
    return part_number_service.get_part_summary(parts)
