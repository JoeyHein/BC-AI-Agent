"""
BC Part Number Mapper Service

Maps door configurations and spring calculations to actual Business Central part numbers.
Based on analysis of 11,369 BC items and 891 quotes.

Part Number Patterns Discovered:
================================

SPRINGS (SP):
- SP10: Galvanized springs - SP10-{wire}{coil}-{wind}
- SP11: Oil Tempered springs - SP11-{wire}{coil}-{wind}
  - wire: 3 digits (218=0.218", 225=0.225", 234=0.234", 250=0.250", etc.)
  - coil: 2 digits (20=2", 25=2-5/8", 36=3-3/4", 60=6")
  - wind: 01=LH, 02=RH
- SP12: Spring accessories (winders, plugs, hardware)
  - SP12-00231-00 = 2" winder/stationary set LH
  - SP12-00232-00 = 2-5/8" winder/stationary set LH
  - SP12-00233-00 = 3-3/4" winder/stationary set LH
  - SP12-00234-00 = 6" winder/stationary set 1" bore LH
  - SP12-00236-00 = 6" winder/stationary set 1-1/4" bore LH
  - SP12-00237-00 = 2" winder/stationary set RH
  - etc.
- SP16: Pre-pick springs (cut to length) - SP16-{wire}{coil}-{length}{wind}

PANELS (PN):
- PN45: TX450 Single End Cap (SEC)
- PN46: TX450 Double End Cap (DEC)
- Format: PN{series}-{height}{stamp}{color}-{width}
  - height: 21=21", 24=24"
  - stamp: 4=UDC, 0=standard
  - color: 00=White, 01=Brown, 05=Black, 10=New Brown, etc.
  - width: 4 digits in inches (0900=9', 1600=16', 2000=20')

PLASTICS/WEATHER STRIPPING (PL):
- PL10-{length}203-{color}: Commercial weather stripping
  - length: 07=7', 08=8', 09=9', etc.
  - color: 00=White, 05=Black, 10=New Brown, etc.
- PL10-00005-01: Astragal 3" bottom rubber
- PL10-00005-02: Astragal 4" bottom rubber
- PL10-00005-03: Astragal 6.5" bottom rubber
- PL10-00141-00: Top/Bottom Retainer 1-3/4"

TRACKS (TR):
- TR02: 2" track assemblies
- TR03: 3" track assemblies
- TR02-STDBM-{height}{radius}: Standard lift bracket mount
- TR02-VLBM-{height}: Vertical lift bracket mount
- TR03-STDAM-{height}: Standard lift angle mount

SHAFTS (SH):
- SH11: 1" Solid shaft keyed
- SH12: 1" Tube shaft
- Format: SH12-1{height}10-00 (e.g., SH12-10810-00 = 1" Tube Shaft 8'-10")

HARDWARE (FH, HK):
- FH10: End caps
- FH12: Hinges, brackets
- FH15: Rollers
- FH17: Struts
- HK01-HK06: Complete hardware kits
"""

import json
import logging
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

logger = logging.getLogger(__name__)


class SpringType(Enum):
    GALVANIZED = "SP10"
    OIL_TEMPERED = "SP11"
    PRE_PICK = "SP16"


class WindDirection(Enum):
    LEFT = "LH"
    RIGHT = "RH"


class DoorModel(Enum):
    TX380 = "TX380"
    TX450 = "TX450"
    TX500 = "TX500"
    KANATA = "KANATA"
    CRAFT = "CRAFT"


class EndCapType(Enum):
    SINGLE = "SEC"  # Single End Cap
    DOUBLE = "DEC"  # Double End Cap


class LiftType(Enum):
    STANDARD = "STD"
    VERTICAL = "VL"
    HIGH_LIFT = "HL"
    LOW_HEADROOM = "LHR"


class TrackMount(Enum):
    BRACKET = "BM"  # Bracket Mount
    ANGLE = "AM"    # Angle Mount


@dataclass
class BCPartNumber:
    """Represents a BC part number with metadata"""
    part_number: str
    description: str
    category: str
    unit_price: Optional[float] = None
    bc_item_id: Optional[str] = None


@dataclass
class SpringPartNumbers:
    """Spring-related part numbers for a door"""
    spring_lh: BCPartNumber
    spring_rh: BCPartNumber
    winder_set_lh: BCPartNumber
    winder_set_rh: BCPartNumber
    spring_length_inches: int
    quantity_per_side: int
    notes: str = ""


@dataclass
class DoorPartNumbers:
    """All part numbers needed for a complete door"""
    panels: List[BCPartNumber]
    springs: SpringPartNumbers
    weather_stripping: BCPartNumber
    astragal: BCPartNumber
    retainer_top: BCPartNumber
    retainer_bottom: BCPartNumber
    track_assembly: BCPartNumber
    shaft: BCPartNumber
    hardware_kit: Optional[BCPartNumber] = None
    strut: Optional[BCPartNumber] = None
    end_caps: Optional[BCPartNumber] = None
    additional_items: List[BCPartNumber] = field(default_factory=list)


class BCPartNumberMapper:
    """Maps door configurations and spring calculations to BC part numbers"""

    # Wire size to BC code mapping (wire size in inches -> 3-digit code)
    WIRE_SIZE_CODES = {
        0.1875: "187",
        0.192: "192",
        0.207: "207",
        0.218: "218",
        0.225: "225",
        0.234: "234",
        0.243: "243",
        0.250: "250",
        0.262: "262",
        0.273: "273",
        0.283: "283",
        0.295: "295",
        0.306: "306",
        0.312: "312",
        0.319: "319",
        0.331: "331",
        0.343: "343",
        0.362: "362",
        0.375: "375",
        0.393: "393",
        0.406: "406",
        0.421: "421",
        0.437: "437",
        0.453: "453",
        0.469: "469",
        0.500: "500",
    }

    # Coil diameter to BC code mapping (coil ID in inches -> 2-digit code)
    COIL_SIZE_CODES = {
        1.75: "17",
        2.0: "20",
        2.625: "25",  # 2-5/8"
        3.75: "36",   # 3-3/4"
        6.0: "60",
    }

    # Winder/Stationary set part numbers by coil size and bore size
    WINDER_SETS = {
        # (coil_inches, bore_inches, wind) -> part_number
        (2.0, 1.0, "LH"): "SP12-00231-00",
        (2.0, 1.0, "RH"): "SP12-00237-00",
        (2.625, 1.0, "LH"): "SP12-00232-00",
        (2.625, 1.0, "RH"): "SP12-00238-00",
        (3.75, 1.0, "LH"): "SP12-00233-00",
        (3.75, 1.0, "RH"): "SP12-00239-00",
        (6.0, 1.0, "LH"): "SP12-00234-00",
        (6.0, 1.0, "RH"): "SP12-00240-00",
        (6.0, 1.25, "LH"): "SP12-00236-00",
        (6.0, 1.25, "RH"): "SP12-00242-00",
    }

    # Panel series codes by model
    # Width determines SEC (Single End Cap, ≤16') vs DEC (Double End Cap, >16')
    # KANATA and CRAFT use same series code regardless of width
    PANEL_SERIES_BY_MODEL = {
        DoorModel.KANATA: ("PN65", "PN65"),    # Same for all widths
        DoorModel.CRAFT: ("PN95", "PN95"),     # Same for all widths
        DoorModel.TX380: ("PN35", "PN35"),     # Max width 16', only SEC
        DoorModel.TX450: ("PN45", "PN46"),     # PN45 for ≤16', PN46 for >16'
        DoorModel.TX500: ("PN55", "PN56"),     # PN55 for ≤16', PN56 for >16'
    }

    # Legacy mapping for backwards compatibility
    PANEL_SERIES = {
        (DoorModel.TX450, EndCapType.SINGLE): "PN45",
        (DoorModel.TX450, EndCapType.DOUBLE): "PN46",
        (DoorModel.TX500, EndCapType.SINGLE): "PN55",
        (DoorModel.TX500, EndCapType.DOUBLE): "PN56",
        (DoorModel.TX380, EndCapType.SINGLE): "PN35",
        (DoorModel.KANATA, EndCapType.SINGLE): "PN65",
        (DoorModel.KANATA, EndCapType.DOUBLE): "PN65",
        (DoorModel.CRAFT, EndCapType.SINGLE): "PN95",
        (DoorModel.CRAFT, EndCapType.DOUBLE): "PN95",
    }

    # Color codes
    COLOR_CODES = {
        "WHITE": "00",
        "BROWN": "01",
        "ALMOND": "02",
        "SANDTONE": "04",
        "BLACK": "05",
        "BRONZE": "06",
        "NEW BROWN": "10",
        "STEEL GREY": "20",
        "IRON ORE": "25",
        "NEW ALMOND": "30",
        "HAZELWOOD": "40",
        "WALNUT": "51",
        "ENGLISH CHESTNUT": "55",
    }

    # Weather strip part numbers by length and color
    # Format: PL10-{length}203-{color}
    WEATHER_STRIP_LENGTHS = [7, 8, 9, 10, 12, 14, 16, 18]

    # Astragal sizes by door width (width in feet -> astragal inches)
    ASTRAGAL_BY_WIDTH = {
        # Doors up to 16' use 3" astragal
        # Doors over 16' use 4" astragal
        # Special cases use 6.5"
    }
    ASTRAGAL_PARTS = {
        3: "PL10-00005-01",    # 3" RESI/COMM bottom rubber
        4: "PL10-00005-02",    # 4" RESI/COMM bottom rubber
        6.5: "PL10-00005-03",  # 6.5" COMM bottom rubber
    }

    # Retainer part number
    RETAINER_1_75 = "PL10-00141-00"  # 1-3/4" Top/Bottom Retainer

    # Track assembly patterns
    # TR02-STDBM-{height}{radius} for 2" standard lift bracket mount
    # TR03-STDBM-{height} for 3" standard lift bracket mount

    # Shaft patterns
    # SH12-1{height}10-00 for 1" tube shaft

    def __init__(self, bc_data_path: Optional[str] = None):
        """Initialize with optional path to BC analysis data"""
        self.bc_items: Dict[str, dict] = {}
        self.spring_items: Dict[str, dict] = {}
        self.panel_items: Dict[str, dict] = {}
        self.hardware_items: Dict[str, dict] = {}

        if bc_data_path:
            self._load_bc_data(bc_data_path)

    def _load_bc_data(self, data_path: str):
        """Load BC analysis data from JSON files"""
        path = Path(data_path)

        # Load items
        items_file = path / "bc_items.json"
        if items_file.exists():
            with open(items_file, 'r') as f:
                items = json.load(f)
                for item in items:
                    self.bc_items[item.get('number', '')] = item

        # Load spring patterns
        spring_file = path / "spring_patterns.json"
        if spring_file.exists():
            with open(spring_file, 'r') as f:
                spring_data = json.load(f)
                for spring_type, springs in spring_data.get('by_type', {}).items():
                    for spring in springs:
                        self.spring_items[spring['number']] = spring

        # Load hardware patterns
        hw_file = path / "hardware_patterns.json"
        if hw_file.exists():
            with open(hw_file, 'r') as f:
                hw_data = json.load(f)
                for prefix, items in hw_data.get('by_prefix', {}).items():
                    for item in items:
                        self.hardware_items[item['number']] = item

        logger.info(f"Loaded {len(self.bc_items)} BC items, "
                   f"{len(self.spring_items)} springs, "
                   f"{len(self.hardware_items)} hardware items")

    def get_spring_part_number(
        self,
        wire_size: float,
        coil_id: float,
        wind: str,
        spring_type: SpringType = SpringType.OIL_TEMPERED
    ) -> BCPartNumber:
        """
        Get BC part number for a spring based on wire size, coil ID, and wind direction.

        Args:
            wire_size: Wire diameter in inches (e.g., 0.234)
            coil_id: Inside coil diameter in inches (e.g., 2.0)
            wind: Wind direction ("LH" or "RH")
            spring_type: Type of spring (galvanized, oil tempered, etc.)

        Returns:
            BCPartNumber with part number and description
        """
        # Find closest wire size code
        wire_code = self._get_closest_wire_code(wire_size)

        # Find closest coil size code
        coil_code = self._get_closest_coil_code(coil_id)

        # Wind code
        wind_code = "01" if wind.upper() == "LH" else "02"

        # Build part number
        prefix = spring_type.value
        part_number = f"{prefix}-{wire_code}{coil_code}-{wind_code}"

        # Get description from loaded data or generate
        description = self._get_spring_description(wire_size, coil_id, wind, spring_type)

        # Check if this exact part exists in BC
        if part_number in self.spring_items:
            bc_item = self.spring_items[part_number]
            return BCPartNumber(
                part_number=part_number,
                description=bc_item.get('displayName', description),
                category="SPRING",
                bc_item_id=bc_item.get('id')
            )

        return BCPartNumber(
            part_number=part_number,
            description=description,
            category="SPRING"
        )

    def _get_closest_wire_code(self, wire_size: float) -> str:
        """Find the closest BC wire size code for a given wire diameter"""
        if wire_size in self.WIRE_SIZE_CODES:
            return self.WIRE_SIZE_CODES[wire_size]

        # Find closest match
        closest = min(self.WIRE_SIZE_CODES.keys(), key=lambda x: abs(x - wire_size))
        return self.WIRE_SIZE_CODES[closest]

    def _get_closest_coil_code(self, coil_id: float) -> str:
        """Find the closest BC coil size code for a given coil diameter"""
        if coil_id in self.COIL_SIZE_CODES:
            return self.COIL_SIZE_CODES[coil_id]

        # Find closest match
        closest = min(self.COIL_SIZE_CODES.keys(), key=lambda x: abs(x - coil_id))
        return self.COIL_SIZE_CODES[closest]

    def _get_spring_description(
        self,
        wire_size: float,
        coil_id: float,
        wind: str,
        spring_type: SpringType
    ) -> str:
        """Generate spring description"""
        type_name = {
            SpringType.GALVANIZED: "GALVANIZED",
            SpringType.OIL_TEMPERED: "OIL TEMPERED",
            SpringType.PRE_PICK: "PRE-PICK"
        }.get(spring_type, "OIL TEMPERED")

        coil_str = self._format_coil_size(coil_id)
        wind_str = "LH" if wind.upper() == "LH" else "RH"

        return f"SPRINGS, {type_name}, .{int(wire_size * 1000)} X {coil_str}\"  {wind_str}"

    def _format_coil_size(self, coil_id: float) -> str:
        """Format coil size for description"""
        if coil_id == 2.0:
            return "2"
        elif coil_id == 2.625:
            return "2 5/8"
        elif coil_id == 3.75:
            return "3 3/4"
        elif coil_id == 6.0:
            return "6"
        else:
            return str(coil_id)

    def get_winder_stationary_set(
        self,
        coil_id: float,
        bore_size: float = 1.0,
        wind: str = "LH"
    ) -> BCPartNumber:
        """
        Get winder/stationary plug set part number.

        Args:
            coil_id: Inside coil diameter in inches
            bore_size: Shaft bore size (1.0" or 1.25")
            wind: Wind direction

        Returns:
            BCPartNumber for the winder/stationary set
        """
        # Find closest coil size
        closest_coil = min(self.COIL_SIZE_CODES.keys(), key=lambda x: abs(x - coil_id))

        # Look up part number
        key = (closest_coil, bore_size, wind.upper())
        if key in self.WINDER_SETS:
            part_number = self.WINDER_SETS[key]
            coil_str = self._format_coil_size(closest_coil)
            bore_str = '1"' if bore_size == 1.0 else '1-1/4"'

            return BCPartNumber(
                part_number=part_number,
                description=f"SPRING, WINDERS & STATIONARY PLUGS SET, {coil_str}\", {bore_str} BORE, {wind.upper()}",
                category="SPRING_ACCESSORY"
            )

        # Default to 2" set if not found
        default_key = (2.0, 1.0, wind.upper())
        part_number = self.WINDER_SETS[default_key]
        return BCPartNumber(
            part_number=part_number,
            description=f"SPRING, WINDERS & STATIONARY PLUGS SET, 2\", 1\" BORE, {wind.upper()}",
            category="SPRING_ACCESSORY"
        )

    def get_weather_stripping(
        self,
        door_height_feet: int,
        color: str = "WHITE",
        commercial: bool = True
    ) -> BCPartNumber:
        """
        Get weather stripping part number.

        Args:
            door_height_feet: Door height in feet
            color: Color name
            commercial: True for commercial, False for residential

        Returns:
            BCPartNumber for weather stripping
        """
        # Round height to available size
        available_heights = self.WEATHER_STRIP_LENGTHS
        height = min(available_heights, key=lambda x: abs(x - door_height_feet))

        # Get color code
        color_code = self.COLOR_CODES.get(color.upper(), "00")

        # Build part number: PL10-{height}203-{color}
        height_code = f"{height:02d}"
        part_number = f"PL10-{height_code}203-{color_code}"

        return BCPartNumber(
            part_number=part_number,
            description=f"PLASTICS, WEATHER STRIP, GALVANIZED STEEL/FLEXIBLE VINYL, {color.upper()}, {height:02d}'",
            category="WEATHER_STRIPPING"
        )

    def get_astragal(self, door_width_feet: float) -> BCPartNumber:
        """
        Get astragal (bottom rubber) part number based on door width.

        Args:
            door_width_feet: Door width in feet

        Returns:
            BCPartNumber for astragal
        """
        # Default rules: 3" for <=16', 4" for >16'
        if door_width_feet <= 16:
            size = 3
        else:
            size = 4

        part_number = self.ASTRAGAL_PARTS.get(size, self.ASTRAGAL_PARTS[3])

        return BCPartNumber(
            part_number=part_number,
            description=f"ASTRAGAL, {size}\" RESI/COMM BOTTOM RUBBER",
            category="ASTRAGAL"
        )

    def get_retainer(self, thickness: float = 1.75) -> BCPartNumber:
        """
        Get retainer part number.

        Args:
            thickness: Panel thickness (default 1.75" for commercial)

        Returns:
            BCPartNumber for retainer
        """
        return BCPartNumber(
            part_number=self.RETAINER_1_75,
            description="TOP/BOTTOM RETAINER, 1 3/4\"",
            category="RETAINER"
        )

    def get_track_assembly(
        self,
        door_height_feet: int,
        track_size: int = 2,
        lift_type: LiftType = LiftType.STANDARD,
        mount_type: TrackMount = TrackMount.BRACKET,
        radius_inches: int = 12
    ) -> BCPartNumber:
        """
        Get track assembly part number.

        Args:
            door_height_feet: Door height in feet
            track_size: Track size (2" or 3")
            lift_type: Type of lift
            mount_type: Mount type
            radius_inches: Radius in inches (for standard lift)

        Returns:
            BCPartNumber for track assembly
        """
        prefix = f"TR{track_size:02d}"

        if lift_type == LiftType.STANDARD:
            mount_code = "BM" if mount_type == TrackMount.BRACKET else "AM"
            height_code = f"{door_height_feet:02d}"

            if track_size == 2:
                # TR02-STDBM-{height}{radius}
                radius_code = f"{radius_inches:02d}"
                part_number = f"{prefix}-STD{mount_code}-{height_code}{radius_code}"
                desc = f"{track_size}\" STANDARD LIFT {'BRACKET' if mount_type == TrackMount.BRACKET else 'ANGLE'} MOUNT; {door_height_feet}' High,{radius_inches}\"Radius"
            else:
                # TR03-STDBM-{height}
                part_number = f"{prefix}-STD{mount_code}-{height_code}"
                desc = f"{track_size}\" STANDARD LIFT {'BRACKET' if mount_type == TrackMount.BRACKET else 'ANGLE'} MOUNT, {door_height_feet}' High"
        elif lift_type == LiftType.VERTICAL:
            mount_code = "BM" if mount_type == TrackMount.BRACKET else "AM"
            height_code = f"{door_height_feet:02d}"
            part_number = f"{prefix}-VL{mount_code}-{height_code}"
            desc = f"{door_height_feet}' HIGH, {track_size}\" VERTICAL LIFT - {'BRACKET' if mount_type == TrackMount.BRACKET else 'ANGLE'} MOUNT"
        elif lift_type == LiftType.LOW_HEADROOM:
            height_code = f"{door_height_feet:02d}"
            part_number = f"{prefix}-LHR-{height_code}"
            desc = f"{track_size}\" LOW HEAD ROOM KIT,{door_height_feet}'"
        else:
            # Default
            part_number = f"{prefix}-STDBM-{door_height_feet:02d}{radius_inches:02d}"
            desc = f"{track_size}\" STANDARD LIFT BRACKET MOUNT"

        return BCPartNumber(
            part_number=part_number,
            description=desc,
            category="TRACK"
        )

    def get_shaft(
        self,
        door_width_feet: int,
        shaft_type: str = "tube",
        bore_size: float = 1.0
    ) -> BCPartNumber:
        """
        Get shaft part number.

        Args:
            door_width_feet: Door width in feet (shaft is typically width - 10")
            shaft_type: "tube" or "solid"
            bore_size: Bore size in inches

        Returns:
            BCPartNumber for shaft
        """
        # Shaft length is typically door width + some extra for drums
        # Standard residential: width + 10" for tube shaft
        shaft_feet = door_width_feet

        if shaft_type == "tube":
            # SH12-1{height}10-00 format
            height_code = f"{shaft_feet:02d}"
            part_number = f"SH12-1{height_code}10-00"
            desc = f"1\" Tube Shaft {shaft_feet}'-10\""
        else:
            # SH11 for solid shaft
            height_code = f"{shaft_feet:02d}"
            part_number = f"SH11-1{height_code}06-00"
            desc = f"1\" Solid Shaft Keyed {shaft_feet}'-6\""

        return BCPartNumber(
            part_number=part_number,
            description=desc,
            category="SHAFT"
        )

    def get_panel_part_number(
        self,
        model: DoorModel,
        width_feet: float,
        height_inches: int,
        color: str = "WHITE",
        end_cap_type: EndCapType = EndCapType.SINGLE,
        stamp: str = "UDC"
    ) -> BCPartNumber:
        """
        Get panel part number.

        Args:
            model: Door model (TX450, TX500, TX380, KANATA, CRAFT)
            width_feet: Panel width in feet
            height_inches: Panel height in inches (21 or 24)
            color: Color name
            end_cap_type: Single or double end cap (auto-determined by width)
            stamp: Stamp type (UDC, standard, etc.)

        Returns:
            BCPartNumber for panel

        Panel Part Number Format:
            PN{series}-{height}{stamp}{color}-{width}
            Example: PN45-24400-0900 = TX450 24" white UDC 9' wide

        Panel Series by Model and Width:
            - KANATA: PN65 (all widths)
            - CRAFT: PN95 (all widths)
            - TX380: PN35 (max 16', no DEC)
            - TX450: PN45 (≤16') / PN46 (>16')
            - TX500: PN55 (≤16') / PN56 (>16')

        Width Format: FFII (feet + inches)
            0900 = 9'0"
            1600 = 16'0"
            2400 = 24'0"
        """
        # Determine panel series based on model and width
        # Width > 16' uses DEC (Double End Cap) variant for commercial doors
        is_wide_door = width_feet > 16

        if model in self.PANEL_SERIES_BY_MODEL:
            sec_prefix, dec_prefix = self.PANEL_SERIES_BY_MODEL[model]
            prefix = dec_prefix if is_wide_door else sec_prefix
        else:
            # Fallback to legacy lookup
            series_key = (model, EndCapType.DOUBLE if is_wide_door else EndCapType.SINGLE)
            prefix = self.PANEL_SERIES.get(series_key, "PN45")

        # Height code
        height_code = f"{height_inches:02d}"

        # Stamp code (4 = UDC, 0 = standard)
        stamp_code = "4" if stamp.upper() == "UDC" else "0"

        # Color code
        color_code = self.COLOR_CODES.get(color.upper(), "00")

        # Width code: FFII format (feet + inches)
        # E.g., 9' = 0900, 16' = 1600, 9'6" = 0906
        feet = int(width_feet)
        inches = int((width_feet % 1) * 12)
        width_code = f"{feet:02d}{inches:02d}"

        # Build part number: PN{series}-{height}{stamp}{color}-{width}
        part_number = f"{prefix}-{height_code}{stamp_code}{color_code}-{width_code}"

        # Build description
        model_name = model.value
        cap_name = "SEC" if end_cap_type == EndCapType.SINGLE else "DEC"
        width_str = f"{feet:02d}' {inches:02d}\""
        desc = f"SECTION, {model_name}, [{width_str}] X {height_inches}\", {stamp.upper()}, {color.upper()}, {cap_name}"

        return BCPartNumber(
            part_number=part_number,
            description=desc,
            category="PANEL"
        )

    def get_strut(self, door_width_feet: int, gauge: int = 20) -> BCPartNumber:
        """
        Get strut part number based on door width.

        Args:
            door_width_feet: Door width in feet
            gauge: Steel gauge (16 or 20)

        Returns:
            BCPartNumber for strut
        """
        # Map width to standard strut lengths
        strut_lengths = {8: 8, 9: 9, 10: 10, 12: 12, 14: 14, 16: 16, 18: 18,
                        20: 20, 22: 22, 24: 24, 26: 26, 28: 28}

        strut_length = strut_lengths.get(door_width_feet, door_width_feet)

        # Part number based on gauge and length
        if gauge == 16:
            if strut_length >= 24:
                part_number = f"FH17-00018-00"  # 24'
            elif strut_length >= 20:
                part_number = f"FH17-00036-00"  # 20'
            else:
                part_number = f"FH17-00035-00"  # 18'
        else:  # 20 gauge
            length_map = {
                8: "FH17-00028-00",
                9: "FH17-00029-00",
                10: "FH17-00030-00",
                12: "FH17-00001-00",
                14: "FH17-00002-00",
                16: "FH17-00003-00",
                18: "FH17-00004-00",
            }
            part_number = length_map.get(strut_length, "FH17-00003-00")

        return BCPartNumber(
            part_number=part_number,
            description=f"STRUT, {gauge} GA, {strut_length}'",
            category="STRUT"
        )

    def generate_door_parts(
        self,
        door_width_feet: float,
        door_height_feet: float,
        model: DoorModel = DoorModel.TX450,
        color: str = "WHITE",
        panel_height_inches: int = 24,
        end_cap_type: EndCapType = EndCapType.SINGLE,
        track_size: int = 2,
        lift_type: LiftType = LiftType.STANDARD,
        spring_wire_size: float = 0.234,
        spring_coil_id: float = 2.0,
        spring_length_inches: int = 29,
        spring_quantity_per_side: int = 1,
        include_hardware_kit: bool = True
    ) -> DoorPartNumbers:
        """
        Generate all part numbers needed for a complete door.

        This is the main entry point for the door configurator to get
        all BC part numbers for a door configuration.
        """
        # Calculate number of panels needed
        num_panels = int(door_height_feet * 12 / panel_height_inches)

        # Generate panel part numbers
        panels = []
        for _ in range(num_panels):
            panel = self.get_panel_part_number(
                model=model,
                width_feet=door_width_feet,
                height_inches=panel_height_inches,
                color=color,
                end_cap_type=end_cap_type
            )
            panels.append(panel)

        # Generate spring part numbers
        spring_lh = self.get_spring_part_number(
            wire_size=spring_wire_size,
            coil_id=spring_coil_id,
            wind="LH"
        )
        spring_rh = self.get_spring_part_number(
            wire_size=spring_wire_size,
            coil_id=spring_coil_id,
            wind="RH"
        )
        winder_lh = self.get_winder_stationary_set(spring_coil_id, 1.0, "LH")
        winder_rh = self.get_winder_stationary_set(spring_coil_id, 1.0, "RH")

        springs = SpringPartNumbers(
            spring_lh=spring_lh,
            spring_rh=spring_rh,
            winder_set_lh=winder_lh,
            winder_set_rh=winder_rh,
            spring_length_inches=spring_length_inches,
            quantity_per_side=spring_quantity_per_side,
            notes=f"Spring spec: {spring_wire_size}\" x {spring_coil_id}\" x {spring_length_inches}\""
        )

        # Generate other parts
        weather_strip = self.get_weather_stripping(
            door_height_feet=int(door_height_feet),
            color=color
        )

        astragal = self.get_astragal(door_width_feet)

        retainer_top = self.get_retainer()
        retainer_bottom = self.get_retainer()

        track = self.get_track_assembly(
            door_height_feet=int(door_height_feet),
            track_size=track_size,
            lift_type=lift_type
        )

        shaft = self.get_shaft(
            door_width_feet=int(door_width_feet),
            shaft_type="tube"
        )

        strut = self.get_strut(int(door_width_feet))

        return DoorPartNumbers(
            panels=panels,
            springs=springs,
            weather_stripping=weather_strip,
            astragal=astragal,
            retainer_top=retainer_top,
            retainer_bottom=retainer_bottom,
            track_assembly=track,
            shaft=shaft,
            strut=strut
        )

    def format_for_quote(
        self,
        door_parts: DoorPartNumbers,
        door_description: Optional[str] = None,
        door_index: int = 1
    ) -> List[dict]:
        """
        Format door parts as quote line items for BC.

        Line items are ordered according to BC Quote Format Specification:
        1. Comment (door description)
        2. Panels
        3. Retainer
        4. Astragal
        5. Struts
        6. Windows (if applicable)
        7. Track (and Highlift track if applicable)
        8. Hardware box
        9. Springs parts
        10. Weather seal
        11. Accessories

        Args:
            door_parts: DoorPartNumbers object with all parts
            door_description: Optional description for comment line
            door_index: Door number in multi-door quotes

        Returns:
            List of dictionaries ready to be sent to BC quote API
        """
        lines = []

        # 1. COMMENT - Door description (always first)
        if door_description:
            lines.append({
                "lineType": "Comment",
                "description": f"({door_index}) {door_description}",
                "category": "COMMENT"
            })

        # 2. PANELS
        if door_parts.panels:
            panel = door_parts.panels[0]
            lines.append({
                "part_number": panel.part_number,
                "description": panel.description,
                "quantity": len(door_parts.panels),
                "category": "PANEL"
            })

        # 3. RETAINER (top and bottom)
        lines.append({
            "part_number": door_parts.retainer_top.part_number,
            "description": door_parts.retainer_top.description,
            "quantity": 1,
            "category": "RETAINER"
        })
        lines.append({
            "part_number": door_parts.retainer_bottom.part_number,
            "description": door_parts.retainer_bottom.description,
            "quantity": 1,
            "category": "RETAINER"
        })

        # 4. ASTRAGAL
        lines.append({
            "part_number": door_parts.astragal.part_number,
            "description": door_parts.astragal.description,
            "quantity": 1,
            "category": "ASTRAGAL"
        })

        # 5. STRUTS
        if door_parts.strut:
            lines.append({
                "part_number": door_parts.strut.part_number,
                "description": door_parts.strut.description,
                "quantity": 1,
                "category": "STRUT"
            })

        # 6. WINDOWS (if applicable)
        for item in door_parts.additional_items:
            if item.category == "WINDOW":
                lines.append({
                    "part_number": item.part_number,
                    "description": item.description,
                    "quantity": 1,
                    "category": "WINDOW"
                })

        # 7. TRACK (and Highlift track if applicable)
        lines.append({
            "part_number": door_parts.track_assembly.part_number,
            "description": door_parts.track_assembly.description,
            "quantity": 1,
            "category": "TRACK"
        })
        # Add highlift track if present
        for item in door_parts.additional_items:
            if item.category == "HIGHLIFT_TRACK":
                lines.append({
                    "part_number": item.part_number,
                    "description": item.description,
                    "quantity": 1,
                    "category": "HIGHLIFT_TRACK"
                })

        # 8. HARDWARE BOX
        if door_parts.hardware_kit:
            lines.append({
                "part_number": door_parts.hardware_kit.part_number,
                "description": door_parts.hardware_kit.description,
                "quantity": 1,
                "category": "HARDWARE"
            })

        # 9. SPRINGS (springs, winders, shaft)
        springs = door_parts.springs
        lines.append({
            "part_number": springs.spring_lh.part_number,
            "description": springs.spring_lh.description,
            "quantity": springs.spring_length_inches,
            "category": "SPRING",
            "notes": f"Spring length: {springs.spring_length_inches}\""
        })
        lines.append({
            "part_number": springs.spring_rh.part_number,
            "description": springs.spring_rh.description,
            "quantity": springs.spring_length_inches,
            "category": "SPRING"
        })

        # Winder sets
        lines.append({
            "part_number": springs.winder_set_lh.part_number,
            "description": springs.winder_set_lh.description,
            "quantity": springs.quantity_per_side,
            "category": "SPRING_ACCESSORY"
        })
        lines.append({
            "part_number": springs.winder_set_rh.part_number,
            "description": springs.winder_set_rh.description,
            "quantity": springs.quantity_per_side,
            "category": "SPRING_ACCESSORY"
        })

        # Shaft
        lines.append({
            "part_number": door_parts.shaft.part_number,
            "description": door_parts.shaft.description,
            "quantity": 1,
            "category": "SHAFT"
        })

        # 10. WEATHER SEAL
        lines.append({
            "part_number": door_parts.weather_stripping.part_number,
            "description": door_parts.weather_stripping.description,
            "quantity": len(door_parts.panels),
            "category": "WEATHER_STRIPPING"
        })

        # 11. ACCESSORIES (pusher springs, bumper springs, etc.)
        for item in door_parts.additional_items:
            if item.category in ["ACCESSORY", "PUSHER_SPRING", "BUMPER_SPRING"]:
                lines.append({
                    "part_number": item.part_number,
                    "description": item.description,
                    "quantity": 1,
                    "category": item.category
                })

        return lines


# Module-level instance for easy access
_mapper_instance: Optional[BCPartNumberMapper] = None


def get_bc_mapper(data_path: Optional[str] = None) -> BCPartNumberMapper:
    """Get or create the BC Part Number Mapper singleton"""
    global _mapper_instance

    if _mapper_instance is None:
        # Default path to BC analysis data
        if data_path is None:
            data_path = str(Path(__file__).parent.parent.parent / "data" / "bc_analysis")

        _mapper_instance = BCPartNumberMapper(data_path)

    return _mapper_instance


# Convenience functions
def spring_to_bc_part(wire_size: float, coil_id: float, wind: str) -> str:
    """Quick conversion from spring specs to BC part number"""
    mapper = get_bc_mapper()
    part = mapper.get_spring_part_number(wire_size, coil_id, wind)
    return part.part_number


def door_to_bc_parts(
    width_feet: float,
    height_feet: float,
    model: str = "TX450",
    color: str = "WHITE",
    spring_wire: float = 0.234,
    spring_coil: float = 2.0,
    spring_length: int = 29
) -> List[dict]:
    """Quick conversion from door config to BC quote lines"""
    mapper = get_bc_mapper()

    door_model = DoorModel[model] if model in DoorModel.__members__ else DoorModel.TX450

    parts = mapper.generate_door_parts(
        door_width_feet=width_feet,
        door_height_feet=height_feet,
        model=door_model,
        color=color,
        spring_wire_size=spring_wire,
        spring_coil_id=spring_coil,
        spring_length_inches=spring_length
    )

    return mapper.format_for_quote(parts)
