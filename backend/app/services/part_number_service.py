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
    quantity: int
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

# Pre-configured Door Package SKUs (complete door assemblies)
# These are for standard sizes that have pre-built packages in BC
PRECONFIGURED_DOORS = {
    "TX450": {
        # Format: (width_ft, height_ft) -> base_sku
        (8, 7): "TX450-0807",
        (9, 7): "TX450-0907",
        (10, 7): "TX450-1007",
        (12, 7): "TX450-1207",
        (16, 7): "TX450-1607",
        (8, 8): "TX450-0808",
        (9, 8): "TX450-0908",
        (10, 8): "TX450-1008",
        (12, 8): "TX450-1208",
        (16, 8): "TX450-1608",
        (10, 10): "TX450-1010",
        (12, 10): "TX450-1210",
        (14, 10): "TX450-1410",
        (12, 12): "TX450-1212",
        (14, 12): "TX450-1412",
        (16, 12): "TX450-1612",
        (14, 14): "TX450-1414",
        (16, 14): "TX450-1614",
    },
    "TX500": {
        (8, 7): "TX500-0807",
        (9, 7): "TX500-0907",
        (12, 7): "TX500-1207",
        (16, 7): "TX500-1607",
        (10, 10): "TX500-1010",
        (12, 12): "TX500-1212",
        (14, 14): "TX500-1414",
    },
}

# Color code suffix for pre-configured doors
DOOR_COLOR_SUFFIX = {
    "WHITE": "-01",
    "BRIGHT_WHITE": "-01",
    "NEW_BROWN": "-02",
    "BLACK": "-03",
    "STEEL_GREY": "-04",
    "ALMOND": "-05",
    "SANDTONE": "-06",
}

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
HARDWARE_RULES = {
    "kit": {
        # Based on door width ranges
        "small": {"max_width": 108, "part": "HK-SM"},   # Up to 9'
        "medium": {"max_width": 144, "part": "HK-MD"},  # Up to 12'
        "large": {"max_width": 192, "part": "HK-LG"},   # Up to 16'
        "xlarge": {"max_width": 288, "part": "HK-XL"},  # Up to 24'
    },
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
        self.preconfigured = PRECONFIGURED_DOORS
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
        """
        parts = []

        # 1. Check for pre-configured door package first
        preconfigured = self._get_preconfigured_door(config)
        if preconfigured:
            parts.append(preconfigured)
            # Pre-configured includes panels, so skip panel selection
        else:
            # 2. Get panel part numbers
            panel_parts = self._get_panel_parts(config)
            parts.extend(panel_parts)

        # 3. Get hardware if needed
        hardware = config.hardware or {}

        if hardware.get("tracks", True):
            track_parts = self._get_track_parts(config)
            parts.extend(track_parts)

        if hardware.get("springs", True):
            spring_parts = self._get_spring_parts(config)
            parts.extend(spring_parts)

        if hardware.get("shafts", True):
            shaft_parts = self._get_shaft_parts(config)
            parts.extend(shaft_parts)

        if hardware.get("struts", True):
            strut_parts = self._get_strut_parts(config)
            parts.extend(strut_parts)

        if hardware.get("hardwareKits", True):
            hw_parts = self._get_hardware_kit_parts(config)
            parts.extend(hw_parts)

        if hardware.get("weatherStripping", True):
            seal_parts = self._get_seal_parts(config)
            parts.extend(seal_parts)

        if hardware.get("bottomRetainer", True):
            retainer_parts = self._get_bottom_retainer_parts(config)
            parts.extend(retainer_parts)

        # 4. Get window/glass parts if configured
        if config.window_insert and config.window_insert != "NONE":
            window_parts = self._get_window_parts(config)
            parts.extend(window_parts)

        # 5. Get operator if selected
        if config.operator and config.operator != "NONE":
            operator_parts = self._get_operator_parts(config)
            parts.extend(operator_parts)

        # Apply quantity multiplier for door count
        for part in parts:
            if part.category != "operator":  # Operator usually shared
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

    def _get_preconfigured_door(self, config: DoorConfiguration) -> Optional[PartSelection]:
        """Check if this configuration matches a pre-configured door package"""
        series = config.door_series
        if series not in self.preconfigured:
            return None

        width_ft = config.door_width // 12
        height_ft = config.door_height // 12

        base_sku = self.preconfigured[series].get((width_ft, height_ft))
        if not base_sku:
            return None

        # Add color suffix
        color_suffix = DOOR_COLOR_SUFFIX.get(config.panel_color, "-01")
        full_sku = f"{base_sku}{color_suffix}"

        return PartSelection(
            part_number=full_sku,
            description=f"{series} {width_ft}'x{height_ft}' Door Package - {config.panel_color}",
            quantity=1,
            category="door_package",
            notes="Pre-configured door package includes panels"
        )

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

        # Get door weight - use provided weight or estimate from size
        door_weight = config.door_weight
        if door_weight is None:
            # Estimate weight: ~4 lbs/sq ft for standard insulated door
            sq_ft = (config.door_width * config.door_height) / 144
            if config.door_type == "commercial":
                door_weight = sq_ft * 5.5  # Commercial doors are heavier
            else:
                door_weight = sq_ft * 4.0  # Residential estimate

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
        """Get hardware kit part numbers"""
        width = config.door_width

        for size, spec in sorted(self.hardware_rules["kit"].items(), key=lambda x: x[1]["max_width"]):
            if width <= spec["max_width"]:
                return [PartSelection(
                    part_number=spec["part"],
                    description=f"Hardware Kit - {size.title()}",
                    quantity=1,
                    category="hardware"
                )]

        # Default to XL
        return [PartSelection(
            part_number="HK-XL",
            description="Hardware Kit - Extra Large",
            quantity=1,
            category="hardware"
        )]

    def _get_seal_parts(self, config: DoorConfiguration) -> List[PartSelection]:
        """Get weather stripping part numbers using actual BC parts"""
        mapper = get_bc_mapper()

        door_height_feet = config.door_height // 12

        # Get actual BC weather strip part number
        weather_strip = mapper.get_weather_stripping(
            door_height_feet=door_height_feet,
            color=config.panel_color.replace("_", " "),
            commercial=(config.door_type == "commercial")
        )

        # Quantity = number of panels (one per panel section)
        panel_count = self._calculate_panel_count(config.door_height)

        return [PartSelection(
            part_number=weather_strip.part_number,
            description=weather_strip.description,
            quantity=panel_count,
            category="weather_stripping"  # Specific category for ordering
        )]

    def _get_bottom_retainer_parts(self, config: DoorConfiguration) -> List[PartSelection]:
        """Get retainer and astragal part numbers using actual BC parts"""
        parts = []
        mapper = get_bc_mapper()

        door_width_feet = config.door_width / 12

        # Get retainer FIRST (comes before astragal in line order)
        retainer = mapper.get_retainer()
        parts.append(PartSelection(
            part_number=retainer.part_number,
            description=f"{retainer.description} (TOP)",
            quantity=1,
            category="retainer"  # Specific category for ordering
        ))
        parts.append(PartSelection(
            part_number=retainer.part_number,
            description=f"{retainer.description} (BOTTOM)",
            quantity=1,
            category="retainer"
        ))

        # Get astragal (bottom rubber) - comes after retainer
        astragal = mapper.get_astragal(door_width_feet)
        parts.append(PartSelection(
            part_number=astragal.part_number,
            description=astragal.description,
            quantity=1,  # One per door
            category="astragal"  # Specific category for ordering
        ))

        return parts

    def _get_window_parts(self, config: DoorConfiguration) -> List[PartSelection]:
        """Get window/glass kit part numbers"""
        if not config.window_insert:
            return []

        # Find the base window part number
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

        # Window quantity based on section width
        panels_wide = config.door_width // 24  # Approximate panels per section
        window_qty = max(1, panels_wide)

        return [PartSelection(
            part_number=f"{base_pn}{glazing_suffix}",
            description=f"Window Insert {config.window_insert} - {config.glazing_type or 'Clear'}",
            quantity=window_qty,
            category="window",
            notes=f"For section {config.window_section or 1}"
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
        glazing_type=config_dict.get("glazingType"),
        track_radius=config_dict.get("trackRadius", "15"),
        track_thickness=config_dict.get("trackThickness", "2"),
        hardware=config_dict.get("hardware", {}),
        operator=config_dict.get("operator"),
    )

    parts = part_number_service.get_parts_for_configuration(config)
    return part_number_service.get_part_summary(parts)
