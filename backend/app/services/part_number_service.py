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
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass
from enum import Enum

from app.services.spring_calculator_service import spring_calculator
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
    window_frame_color: str = "BLACK"  # Commercial window frame color
    glazing_type: Optional[str] = None
    track_radius: str = "15"
    track_thickness: str = "2"
    hardware: Dict[str, bool] = None
    operator: Optional[str] = None
    door_weight: Optional[float] = None  # lbs - if not provided, will estimate
    target_cycles: int = 10000  # cycle life rating (10000, 15000, 25000, 50000, 100000)
    spring_quantity: int = 2  # number of springs (1 or 2)


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
        if config.window_insert and config.window_insert != "NONE":
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

    def _get_panel_parts(self, config: DoorConfiguration) -> List[PartSelection]:
        """Get panel part numbers using actual BC parts"""
        mapper = get_bc_mapper()

        # Map series string to DoorModel enum
        model_map = {
            "TX450": DoorModel.TX450,
            "TX500": DoorModel.TX450,  # TX500 uses similar pattern
            "KANATA": DoorModel.KANATA,
            "CRAFT": DoorModel.CRAFT,
        }
        door_model = model_map.get(config.door_series, DoorModel.TX450)

        # Determine end cap type based on door width (>16' typically uses DEC)
        door_width_feet = config.door_width / 12
        end_cap_type = EndCapType.DOUBLE if door_width_feet > 16 else EndCapType.SINGLE

        # Panel height (typical: 21" or 24")
        panel_height = 24  # Default commercial height
        if config.door_type == "residential":
            panel_height = 21

        # Get panel part number
        panel = mapper.get_panel_part_number(
            model=door_model,
            width_feet=door_width_feet,
            height_inches=panel_height,
            color=config.panel_color.replace("_", " "),
            end_cap_type=end_cap_type,
            stamp="UDC" if config.door_type == "commercial" else "STD"
        )

        panel_count = self._calculate_panel_count(config.door_height)

        # V130G replaces insulated sections — reduce panel count
        if config.window_insert == "V130G" and config.window_qty > 0:
            panel_count = max(1, panel_count - config.window_qty)

        return [PartSelection(
            part_number=panel.part_number,
            description=panel.description,
            quantity=panel_count,
            category="panel"
        )]

    def _calculate_panel_count(self, door_height: int) -> int:
        """Calculate number of panels based on door height"""
        if door_height <= 84:  # 7' or less
            return 4
        elif door_height <= 96:  # 8'
            return 4
        elif door_height <= 108:  # 9'
            return 5
        elif door_height <= 120:  # 10'
            return 5
        elif door_height <= 144:  # 12'
            return 6
        elif door_height <= 168:  # 14'
            return 7
        else:
            return 8

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
        num_sections = self._calculate_panel_count(door_height_in)

        # Determine section height based on door height
        # Standard residential (7', 8') uses 21" sections
        # Taller doors may use 24" sections
        if door_height_in <= 96:  # Up to 8'
            section_height = "21"
        elif door_height_in <= 120:  # 8' to 10'
            section_height = "24"
        else:
            section_height = "24"  # Default to 24" for tall doors

        # Get weight per linear foot for this section height
        weight_per_ft = model_weights.get(section_height, model_weights.get("21", 4.0))

        # Calculate panel weight
        panel_weight = weight_per_ft * door_width_ft * num_sections

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
        logger.info(
            f"Door weight calculation: {config.door_series} {door_width_ft}'x{door_height_in}\" "
            f"= {weight_per_ft} lbs/ft × {door_width_ft}' × {num_sections} sections + {hardware_weight} lbs ({hw_type} hw) "
            f"= {total_weight:.1f} lbs"
        )

        return total_weight

    def _get_track_parts(self, config: DoorConfiguration) -> List[PartSelection]:
        """Get track part numbers using actual BC parts"""
        mapper = get_bc_mapper()

        door_height_feet = config.door_height // 12
        track_size = int(config.track_thickness) if config.track_thickness else 2
        radius_inches = int(config.track_radius) if config.track_radius else 12

        # Determine lift type
        lift_type = LiftType.STANDARD  # Default to standard lift

        # Get track assembly
        track = mapper.get_track_assembly(
            door_height_feet=door_height_feet,
            track_size=track_size,
            lift_type=lift_type,
            mount_type=TrackMount.BRACKET,
            radius_inches=radius_inches
        )

        return [PartSelection(
            part_number=track.part_number,
            description=track.description,
            quantity=1,  # Track assembly is sold as a kit (pair)
            category="track"
        )]

    def _get_spring_parts(self, config: DoorConfiguration) -> List[PartSelection]:
        """
        Get spring part numbers using Canimex spring calculator + BC part number mapper.

        Uses exact Canimex methodology:
        - IPPT = Multiplier × Door Weight
        - MIP per spring = (IPPT × Turns) / Spring Quantity
        - Active Coils = (Spring Quantity × Divider) / IPPT
        - Total Spring Length = Active Coils + Dead Coil Factor

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

        # Calculate spring using Canimex methodology
        result = spring_calculator.calculate_spring(
            door_weight=door_weight,
            door_height=config.door_height,
            track_radius=track_radius,
            spring_qty=config.spring_quantity,
            target_cycles=config.target_cycles
        )

        if result is None:
            # Fallback to simplified rules if calculator fails
            logger.warning(
                f"Spring calculator returned no result for {door_weight:.0f} lbs, "
                f"{config.door_height}\" height - falling back to simplified rules"
            )
            # Use default spring specs
            wire_size = 0.234
            coil_id = 2.0
            spring_length = 29
        else:
            wire_size = result.wire_diameter
            coil_id = result.coil_diameter
            spring_length = int(result.length)

        # Get BC Part Number Mapper
        mapper = get_bc_mapper()

        # Get actual BC spring part numbers (LH and RH)
        spring_lh = mapper.get_spring_part_number(wire_size, coil_id, "LH")
        spring_rh = mapper.get_spring_part_number(wire_size, coil_id, "RH")

        # Springs are quoted by length (inches of spring)
        parts.append(PartSelection(
            part_number=spring_lh.part_number,
            description=spring_lh.description,
            quantity=spring_length,  # Spring length in inches
            category="spring",
            notes=f"Spring: {wire_size}\" x {coil_id}\" x {spring_length}\" LH"
        ))

        parts.append(PartSelection(
            part_number=spring_rh.part_number,
            description=spring_rh.description,
            quantity=spring_length,  # Spring length in inches
            category="spring",
            notes=f"Spring: {wire_size}\" x {coil_id}\" x {spring_length}\" RH"
        ))

        # Add winder/stationary sets
        winder_lh = mapper.get_winder_stationary_set(coil_id, 1.0, "LH")
        winder_rh = mapper.get_winder_stationary_set(coil_id, 1.0, "RH")

        parts.append(PartSelection(
            part_number=winder_lh.part_number,
            description=winder_lh.description,
            quantity=config.spring_quantity,
            category="spring_accessory"
        ))

        parts.append(PartSelection(
            part_number=winder_rh.part_number,
            description=winder_rh.description,
            quantity=config.spring_quantity,
            category="spring_accessory"
        ))

        return parts

    def _get_shaft_parts(self, config: DoorConfiguration) -> List[PartSelection]:
        """Get shaft part numbers using actual BC parts"""
        mapper = get_bc_mapper()

        door_width_feet = config.door_width // 12

        # Get shaft part number
        shaft = mapper.get_shaft(
            door_width_feet=door_width_feet,
            shaft_type="tube",  # Default to tube shaft for residential
            bore_size=1.0
        )

        return [PartSelection(
            part_number=shaft.part_number,
            description=shaft.description,
            quantity=1,
            category="shaft"
        )]

    def _get_strut_parts(self, config: DoorConfiguration) -> List[PartSelection]:
        """Get strut part numbers using actual BC parts"""
        mapper = get_bc_mapper()

        door_width_feet = config.door_width // 12
        gauge = 16 if config.door_type == "commercial" else 20

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
        is_commercial = config.door_type == "commercial"

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

        door_height_feet = config.door_height // 12
        door_width_feet = config.door_width // 12
        color = config.panel_color.replace("_", " ")
        is_commercial = config.door_type == "commercial"

        # Get weather strip for HEIGHT (sides) - quantity 2
        height_strip = mapper.get_weather_stripping(
            door_height_feet=door_height_feet,
            color=color,
            commercial=is_commercial
        )
        parts.append(PartSelection(
            part_number=height_strip.part_number,
            description=f"{height_strip.description} (SIDES)",
            quantity=2,  # Always 2 for left and right jambs
            category="weather_stripping"
        ))

        # Get weather strip for WIDTH (header) - quantity 1
        width_strip = mapper.get_weather_stripping(
            door_height_feet=door_width_feet,  # Using width here
            color=color,
            commercial=is_commercial
        )
        parts.append(PartSelection(
            part_number=width_strip.part_number,
            description=f"{width_strip.description} (HEADER)",
            quantity=1,  # Always 1 for header
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

        # Get retainer for top and bottom
        retainer = mapper.get_retainer()
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
        # Check if this door type requires top seal
        insulated_series = ["TX450-20", "TX500-20", "KANATA_EXECUTIVE"]
        if config.door_series not in insulated_series:
            return []

        mapper = get_bc_mapper()
        door_width_feet = config.door_width // 12

        # Top seal uses same weather stripping as header
        # but categorized separately for ordering
        color = config.panel_color.replace("_", " ")
        is_commercial = config.door_type == "commercial"

        top_seal = mapper.get_weather_stripping(
            door_height_feet=door_width_feet,  # Width for header
            color=color,
            commercial=is_commercial
        )

        return [PartSelection(
            part_number=top_seal.part_number,
            description=f"{top_seal.description} (TOP SEAL)",
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

    def _get_window_parts(self, config: DoorConfiguration) -> List[PartSelection]:
        """Get window/glass kit part numbers"""
        if not config.window_insert:
            return []

        # V130G: full-view aluminum section + glass (separate line items)
        if config.window_insert == "V130G":
            return self._get_v130g_parts(config)

        # Commercial thermopane windows (24x12, 34x16, 18x8)
        if config.window_insert in ("24X12_THERMOPANE", "34X16_THERMOPANE", "18X8_THERMOPANE"):
            return self._get_commercial_window_parts(config)

        # Residential window inserts (Stockton/Stockbridge)
        base_pn = None
        for style, inserts in self.window_rules.items():
            if style in ["glazing_suffix"]:
                continue
            if config.window_insert in inserts:
                base_pn = inserts[config.window_insert]
                break

        if not base_pn:
            base_pn = f"GK-{config.window_insert}"

        # Add glazing suffix
        glazing_suffix = self.window_rules.get("glazing_suffix", {}).get(config.glazing_type, "-CL")

        # Window quantity based on positions
        window_qty = config.window_count or max(1, config.door_width // 24)

        return [PartSelection(
            part_number=f"{base_pn}{glazing_suffix}",
            description=f"Window Insert {config.window_insert} - {config.glazing_type or 'Clear'}",
            quantity=window_qty,
            category="window",
            notes=f"For section {config.window_section or 1}"
        )]

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
        section_start = config.window_section or 1
        panel_count = self._calculate_panel_count(config.door_height)

        for i in range(v130g_qty):
            section_num = section_start + i
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
        # GL20-00300-01 = 3MM THERMO CLEAR/CLEAR (standard)
        # Quantity is in SQFT: (section_width × section_height) / 144 per section
        glass_pn = "GL20-00300-01"
        glass_desc = "GLASS, 3MM V130G THERMO CLEAR/CLEAR"

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
        """Get commercial thermopane window parts (24x12, 34x16, 18x8)"""
        window_sizes = {
            "24X12_THERMOPANE": {"width": 24, "height": 12, "desc": "24\" x 12\""},
            "34X16_THERMOPANE": {"width": 34, "height": 16, "desc": "34\" x 16\""},
            "18X8_THERMOPANE": {"width": 18, "height": 8, "desc": "18\" x 8\""},
        }
        ws = window_sizes.get(config.window_insert, {"width": 24, "height": 12, "desc": "24\" x 12\""})
        qty = config.window_qty or 1

        return [PartSelection(
            part_number=f"CW-{config.window_insert}",
            description=f"Commercial Window {ws['desc']} Thermopane",
            quantity=qty,
            category="commercial_window",
            notes=f"Section {config.window_section or 1}, {config.window_frame_color} frame"
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

def get_parts_for_door_config(config_dict: Dict[str, Any]) -> Dict[str, Any]:
    """
    Convenience function to get parts from a dictionary configuration.

    Args:
        config_dict: Dictionary with door configuration fields

    Returns:
        Dictionary with parts summary
    """
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
        window_count=config_dict.get("windowCount", 0),
        window_qty=config_dict.get("windowQty", 0),
        window_frame_color=config_dict.get("windowFrameColor", "BLACK"),
        glazing_type=config_dict.get("glazingType"),
        track_radius=config_dict.get("trackRadius", "15"),
        track_thickness=config_dict.get("trackThickness", "2"),
        hardware=config_dict.get("hardware", {}),
        operator=config_dict.get("operator"),
        target_cycles=config_dict.get("targetCycles", config_dict.get("target_cycles", 10000)),
    )

    parts = part_number_service.get_parts_for_configuration(config)
    return part_number_service.get_part_summary(parts)
