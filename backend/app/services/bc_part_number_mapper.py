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
    TX450_20 = "TX450-20"
    TX500 = "TX500"
    TX500_20 = "TX500-20"
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

    # Panel series codes by model: (SEC_prefix, DEC_prefix)
    # SEC = Single End Cap, DEC = Double End Cap
    # KANATA and CRAFT use same series code regardless of end cap type
    PANEL_SERIES_BY_MODEL = {
        DoorModel.KANATA: ("PN65", "PN65"),      # Same for all widths
        DoorModel.CRAFT: ("PN95", "PN95"),       # Same for all widths
        DoorModel.TX380: ("PN35", "PN35"),       # Max width 16', only SEC
        DoorModel.TX450: ("PN45", "PN46"),       # PN45=SEC, PN46=DEC
        DoorModel.TX450_20: ("PN47", "PN48"),    # PN47=SEC, PN48=DEC (20-gauge)
        DoorModel.TX500: ("PN55", "PN56"),       # PN55=SEC, PN56=DEC
        DoorModel.TX500_20: ("PN57", "PN58"),    # PN57=SEC, PN58=DEC (20-gauge)
    }

    # Legacy mapping for backwards compatibility
    PANEL_SERIES = {
        (DoorModel.TX450, EndCapType.SINGLE): "PN45",
        (DoorModel.TX450, EndCapType.DOUBLE): "PN46",
        (DoorModel.TX450_20, EndCapType.SINGLE): "PN47",
        (DoorModel.TX450_20, EndCapType.DOUBLE): "PN48",
        (DoorModel.TX500, EndCapType.SINGLE): "PN55",
        (DoorModel.TX500, EndCapType.DOUBLE): "PN56",
        (DoorModel.TX500_20, EndCapType.SINGLE): "PN57",
        (DoorModel.TX500_20, EndCapType.DOUBLE): "PN58",
        (DoorModel.TX380, EndCapType.SINGLE): "PN35",
        (DoorModel.KANATA, EndCapType.SINGLE): "PN65",
        (DoorModel.KANATA, EndCapType.DOUBLE): "PN65",
        (DoorModel.CRAFT, EndCapType.SINGLE): "PN95",
        (DoorModel.CRAFT, EndCapType.DOUBLE): "PN95",
    }

    # Color codes
    COLOR_CODES = {
        "WHITE": "00",
        "BRIGHT WHITE": "00",
        "BROWN": "01",
        "ALMOND": "03",
        "SANDTONE": "04",
        "BLACK": "05",
        "BRONZE": "06",
        "NEW BROWN": "10",
        "ONYX BLACK": "15",
        "STEEL GREY": "20",
        "IRON ORE": "25",
        "NEW ALMOND": "30",
        "FRENCH OAK": "35",
        "HAZELWOOD": "40",
        "CANYON": "45",
        "WALNUT": "51",
        "ENGLISH CHESTNUT": "55",
    }

    # Weather strip part numbers by length and color
    # PL10 format: PL10-{height}203-{color} (galvanized steel/flexible vinyl)
    # PL11 format: PL11-{1|2}2{height}2-{color} (dual fin, alum/vinyl)
    #   1 = residential, 2 = commercial
    WEATHER_STRIP_LENGTHS = [7, 8, 9, 10, 12, 14, 16, 18, 20]

    # Colors that use PL11 (dual fin) instead of PL10
    PL11_COLOR_CODES = {"25", "30", "40", "55"}  # Iron Ore, New Almond, Hazelwood, English Chestnut

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

    # Retainer part number (commercial — sold by the roll, cut on site)
    RETAINER_1_75 = "PL10-00141-00"  # 1-3/4" Top/Bottom Retainer

    # Residential retainer — pre-cut rigid retainer by width
    RESI_RETAINER = {
        7:  "PL10-00145-01",  # 7'
        8:  "PL10-00145-01",  # 8'
        9:  "PL10-00146-02",  # 9'
        10: "PL10-00146-00",  # 10'
        11: "PL10-00149-00",  # 11'
        12: "PL10-00149-00",  # 12'
        13: "PL10-00146-01",  # 13'
        14: "PL10-00146-01",  # 14'
        15: "PL10-00146-01",  # 15'
        16: "PL10-00146-01",  # 16'
        18: "PL10-00150-00",  # 18'
        20: "PL10-00150-00",  # 20'
    }

    # Top seal part number (distinct from weather strip)
    TOP_SEAL = "PL10-00127-00"  # TOP SEAL RUBBER (FS-1864 Die # 206)

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
        """Find the matching BC wire size code for a given wire diameter.

        First checks for an exact match, then tries closest BC size within
        tolerance (handles Canimex values like 0.3625 mapping to BC's 0.362).
        Falls back to next-size-up for a stronger spring spec.
        """
        if wire_size in self.WIRE_SIZE_CODES:
            return self.WIRE_SIZE_CODES[wire_size]

        # Try closest BC wire within tolerance (Canimex ↔ BC rounding differences)
        closest = min(self.WIRE_SIZE_CODES.keys(), key=lambda w: abs(w - wire_size))
        if abs(closest - wire_size) <= 0.005:
            return self.WIRE_SIZE_CODES[closest]

        # Find next size up (smallest available >= requested)
        sizes_above = [s for s in self.WIRE_SIZE_CODES.keys() if s >= wire_size]
        if sizes_above:
            next_size = min(sizes_above)
        else:
            # Requested is larger than all available — use largest
            next_size = max(self.WIRE_SIZE_CODES.keys())
        return self.WIRE_SIZE_CODES[next_size]

    def _get_closest_coil_code(self, coil_id: float) -> str:
        """Find the next-size-up BC coil size code for a given coil diameter.
        Returns the smallest available coil size >= coil_id.
        """
        if coil_id in self.COIL_SIZE_CODES:
            return self.COIL_SIZE_CODES[coil_id]

        # Find next size up (smallest available >= requested)
        sizes_above = [s for s in self.COIL_SIZE_CODES.keys() if s >= coil_id]
        if sizes_above:
            next_size = min(sizes_above)
        else:
            # Requested is larger than all available — use largest
            next_size = max(self.COIL_SIZE_CODES.keys())
        return self.COIL_SIZE_CODES[next_size]

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
        # Round up to the next available strip length (smallest available >= requested)
        available_heights = self.WEATHER_STRIP_LENGTHS
        heights_at_or_above = [h for h in available_heights if h >= door_height_feet]
        if heights_at_or_above:
            height = min(heights_at_or_above)
        else:
            # Door is taller than all available strips — use the largest
            height = max(available_heights)

        # Get color code
        color_code = self.COLOR_CODES.get(color.upper(), "00")

        # Specialty colors (woodgrain finishes) use PL11 dual fin strips
        if color_code in self.PL11_COLOR_CODES:
            resi_comm = "2" if commercial else "1"
            part_number = f"PL11-{resi_comm}2{height:02d}2-{color_code}"
            desc = f"WEATHER STRIP, DUAL FIN, {height:02d}' 2\", {color.upper()}"
        else:
            part_number = f"PL10-{height:02d}203-{color_code}"
            desc = f"PLASTICS, WEATHER STRIP, GALVANIZED STEEL/FLEXIBLE VINYL, {color.upper()}, {height:02d}'"

        return BCPartNumber(
            part_number=part_number,
            description=desc,
            category="WEATHER_STRIPPING"
        )

    def get_astragal(self, door_width_feet: float, door_height_inches: int = 0, door_type: str = "residential") -> BCPartNumber:
        """
        Get astragal (bottom rubber) part number based on door width and type.

        Args:
            door_width_feet: Door width in feet
            door_height_inches: Door height in inches (unused, kept for compat)
            door_type: "residential", "commercial", or "aluminium"

        Returns:
            BCPartNumber for astragal
        """
        # Commercial doors 12' or wider get 4" astragal
        if door_type in ("commercial", "aluminium") and door_width_feet >= 12:
            size = 4
        elif door_width_feet > 16:
            size = 4
        else:
            size = 3

        part_number = self.ASTRAGAL_PARTS.get(size, self.ASTRAGAL_PARTS[3])

        return BCPartNumber(
            part_number=part_number,
            description=f"ASTRAGAL, {size}\" RESI/COMM BOTTOM RUBBER",
            category="ASTRAGAL"
        )

    def get_retainer(self, thickness: float = 1.75, residential: bool = False, door_width_feet: int = 0) -> BCPartNumber:
        """
        Get retainer part number.

        Args:
            thickness: Panel thickness (default 1.75" for commercial)
            residential: If True, use pre-cut rigid residential retainer
            door_width_feet: Door width in feet (for residential size selection)

        Returns:
            BCPartNumber for retainer
        """
        if residential and door_width_feet > 0:
            # Find the smallest available length >= door width
            available = sorted(self.RESI_RETAINER.keys())
            for length in available:
                if length >= door_width_feet:
                    return BCPartNumber(
                        part_number=self.RESI_RETAINER[length],
                        description=f"BOTTOM RETAINER, 1 3/4\" RESI RIGID BLACK {length}'-0\"",
                        category="RETAINER"
                    )
            # Wider than largest available — use largest
            largest = available[-1]
            return BCPartNumber(
                part_number=self.RESI_RETAINER[largest],
                description=f"BOTTOM RETAINER, 1 3/4\" RESI RIGID BLACK {largest}'-0\"",
                category="RETAINER"
            )

        return BCPartNumber(
            part_number=self.RETAINER_1_75,
            description="TOP/BOTTOM RETAINER, 1 3/4\"",
            category="RETAINER"
        )

    def get_top_seal(self) -> BCPartNumber:
        """Get top seal rubber part number (distinct from weather strip)."""
        return BCPartNumber(
            part_number=self.TOP_SEAL,
            description="TOP SEAL RUBBER (FS-1864 Die # 206)",
            category="TOP_SEAL"
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
        elif lift_type == LiftType.HIGH_LIFT:
            # High lift uses the same standard track assembly (STDBM)
            # The extension kit is a separate line item handled by _get_highlift_parts()
            mount_code = "BM" if mount_type == TrackMount.BRACKET else "AM"
            height_code = f"{door_height_feet:02d}"

            if track_size == 2:
                radius_code = f"{radius_inches:02d}"
                part_number = f"{prefix}-STD{mount_code}-{height_code}{radius_code}"
                desc = f"{track_size}\" STANDARD LIFT {'BRACKET' if mount_type == TrackMount.BRACKET else 'ANGLE'} MOUNT; {door_height_feet}' High,{radius_inches}\"Radius"
            else:
                part_number = f"{prefix}-STD{mount_code}-{height_code}"
                desc = f"{track_size}\" STANDARD LIFT {'BRACKET' if mount_type == TrackMount.BRACKET else 'ANGLE'} MOUNT, {door_height_feet}' High"
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
            door_width_feet: Door width in feet
            shaft_type: "tube" (SH12, 1" tube), "solid" (SH11, 1" solid keyed),
                        or "1-1/4" (SH10, 1-1/4" keyed — for heavy doors >2000 lbs)
            bore_size: Bore size in inches

        Returns:
            BCPartNumber for shaft, selecting next-size-up from BC catalog
        """
        # Heavy doors (>2000 lbs) use the single 1-1/4" keyed shaft part
        if shaft_type == "1-1/4":
            part_number = "SH10-00002-00"
            item = self.bc_items.get(part_number, {})
            desc = item.get("displayName", "SOLID 1-1/4\" KEYED SHAFT")
            return BCPartNumber(
                part_number=part_number,
                description=desc,
                category="SHAFT"
            )

        # 1" tube (SH12) or solid keyed (SH11)
        if shaft_type == "solid":
            prefix = "SH11"
            ext_code = "06"
            shaft_name = "1\" Solid Shaft Keyed"
            ext_desc = "6\""
        else:  # tube (default)
            prefix = "SH12"
            ext_code = "10"
            shaft_name = "1\" Tube Shaft"
            ext_desc = "10\""

        # Find available lengths from the BC catalog (part format: PREFIX-1FF{ext}-00)
        # e.g. SH12-10710-00 → 7' tube shaft, SH12-11210-00 → 12' tube shaft
        available_lengths = []
        for pn, item in self.bc_items.items():
            if (pn.startswith(f"{prefix}-1") and
                    len(pn) == 13 and
                    pn[8:10] == ext_code and
                    pn.endswith("-00")):
                try:
                    available_lengths.append(int(pn[6:8]))
                except ValueError:
                    pass

        if available_lengths:
            # Pick smallest available length >= requested (next size up)
            sizes_above = [l for l in available_lengths if l >= door_width_feet]
            shaft_feet = min(sizes_above) if sizes_above else max(available_lengths)
        else:
            # BC data not loaded — use requested value directly
            shaft_feet = door_width_feet

        height_code = f"{shaft_feet:02d}"
        part_number = f"{prefix}-1{height_code}{ext_code}-00"
        desc = f"{shaft_name} {shaft_feet}'-{ext_desc}"

        return BCPartNumber(
            part_number=part_number,
            description=desc,
            category="SHAFT"
        )

    def get_shaft_coupler(self, bore_size: float = 1.0) -> BCPartNumber:
        """
        Get shaft coupler for split-shaft configuration.

        Args:
            bore_size: 1.0 → SP12-00160-00 (1\" bore), 1.25 → SP12-00161-00 (1-1/4\" bore)
        """
        if bore_size > 1.0:
            part_number = "SP12-00161-00"
        else:
            part_number = "SP12-00160-00"

        item = self.bc_items.get(part_number, {})
        desc = item.get("displayName", "SPRING ASSY CAST IRON COUPLER BLACK CANIMEX, 1\" BORE")

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

        Panel Series by Model and End Cap:
            - KANATA: PN65 (all widths)
            - CRAFT: PN95 (all widths)
            - TX380: PN35 (max 16', SEC only)
            - TX450: PN45 (SEC) / PN46 (DEC)
            - TX450-20: PN47 (SEC) / PN48 (DEC)
            - TX500: PN55 (SEC) / PN56 (DEC)
            - TX500-20: PN57 (SEC) / PN58 (DEC)

        Width Format: FFII (feet + inches)
            0900 = 9'0"
            1600 = 16'0"
            2400 = 24'0"
        """
        # Determine panel series based on model and end cap type
        # SEC/DEC determines the panel prefix (e.g. PN45=SEC, PN46=DEC for TX450)
        use_dec = end_cap_type == EndCapType.DOUBLE

        if model in self.PANEL_SERIES_BY_MODEL:
            sec_prefix, dec_prefix = self.PANEL_SERIES_BY_MODEL[model]
            prefix = dec_prefix if use_dec else sec_prefix
        else:
            # Fallback to legacy lookup
            series_key = (model, end_cap_type)
            prefix = self.PANEL_SERIES.get(series_key, "PN45")

        # Height code
        height_code = f"{height_inches:02d}"

        # Stamp code — varies by series
        # Residential Kanata (PN65): 0=FLUSH, 1=SH, 2=BC, 3=TRAF, 4=SHXL, 5=BCXL
        # Commercial (PN45/PN30/etc.): 4=UDC, 0=standard
        KANATA_STAMP_CODES = {
            "FLUSH": "0",
            "SH": "1",
            "BC": "2", "SHCH": "2",
            "TRAF": "3", "TRAFALGAR": "3", "RIB": "3",
            "SHXL": "4",
            "BCXL": "5", "LNCH": "5", "LNXL": "5",
        }
        COMMERCIAL_STAMP_CODES = {
            "UDC": "4",
            "FLUSH": "0",
        }
        is_residential = prefix.startswith("PN65") or prefix.startswith("PN95")
        stamp_upper = stamp.upper()
        if is_residential:
            stamp_code = KANATA_STAMP_CODES.get(stamp_upper, "0")
        else:
            stamp_code = COMMERCIAL_STAMP_CODES.get(stamp_upper, "0")

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
                15: "FH17-00003-00",
                16: "FH17-00003-00",
                18: "FH17-00004-00",
                20: "FH17-00036-00",
            }
            part_number = length_map.get(strut_length, "FH17-00003-00")

        return BCPartNumber(
            part_number=part_number,
            description=f"STRUT, {gauge} GA, {strut_length}'",
            category="STRUT"
        )

    def get_hardware_box(
        self,
        door_width_feet: int,
        door_height_feet: int,
        num_sections: int = 4,
        commercial: bool = False,
        lift_type: str = "standard",  # "standard", "high", or "vertical"
        high_lift_inches: int = 0  # Additional high lift in inches (for high lift only)
    ) -> BCPartNumber:
        """
        Get hardware box part number based on door size and type.

        BC part number patterns (updated Jan 2026):

        Standard Lift:
        - HK02: Standard Lift 2" Track (Residential) - HK02-WWHH0-RC
        - HK03: Standard Lift 3" Track (Commercial) - HK03-WWHH0-RC or HK03-WWHH1-RC

        High Lift:
        - HK12: High Lift 2" Track - HK12-WWHH0SS-RC (SS = high lift feet)
        - HK13: High Lift 3" Track - HK13-WWHH0SS-RC

        Commercial Hardware Boxes:
        - HW: Commercial boxes - HWww-hhhhh-00

        Width codes (WW):
        - 11 = 6'-11'2" (up to ~11')
        - 14 = 11'3"-14'2" (up to ~14')
        - 16 = 14'3"-16'2" (up to ~16')
        - 18 = 16'3"-18'2" (up to ~18')
        - 20 = 18'3"-20'2" (up to ~20')
        - 22 = 20'1"-22'0"
        - 24 = 22'1"-24'0"
        - 26 = 24'1"-26'2"
        - 28 = 26'3"-28'0"
        - 29 = 28'1"-29'

        Height codes (HH0):
        - 080 = 6'-8'2" (up to ~8')
        - 100 = 8'3"-10'2" (up to ~10')
        - 120 = 10'3"-12'2" (up to ~12')
        - 140 = 12'3"-14'2" (up to ~14')
        - 160 = 14'3"-16'2" (up to ~16')
        - 180 = 16'3"-18'2" (up to ~18')
        - 200 = 18'3"-20'2"
        - 210 = 20'3"-21'2"
        - 220 = 21'3"-22'2"
        - 240 = 22'3"-24'2"
        - 260 = 24'3"-26'2"

        Args:
            door_width_feet: Door width in feet
            door_height_feet: Door height in feet
            num_sections: Number of panel sections (typically 4)
            commercial: True for commercial (3" track), False for residential (2" track)
            lift_type: "standard" or "high" lift
            high_lift_inches: Additional inches for high lift (converted to feet code)

        Returns:
            BCPartNumber for hardware box
        """
        # Width code mapping (WW)
        def get_width_code(width_ft: int) -> str:
            if width_ft <= 11:
                return "11"
            elif width_ft <= 14:
                return "14"
            elif width_ft <= 16:
                return "16"
            elif width_ft <= 18:
                return "18"
            elif width_ft <= 20:
                return "20"
            elif width_ft <= 22:
                return "22"
            elif width_ft <= 24:
                return "24"
            elif width_ft <= 26:
                return "26"
            elif width_ft <= 28:
                return "28"
            else:
                return "29"  # Max width code

        # Height code mapping (HH0)
        def get_height_code(height_ft: int) -> str:
            if height_ft <= 8:
                return "080"
            elif height_ft <= 10:
                return "100"
            elif height_ft <= 12:
                return "120"
            elif height_ft <= 14:
                return "140"
            elif height_ft <= 16:
                return "160"
            elif height_ft <= 18:
                return "180"
            elif height_ft <= 20:
                return "200"
            elif height_ft <= 21:
                return "210"
            elif height_ft <= 22:
                return "220"
            elif height_ft <= 24:
                return "240"
            else:
                return "260"  # Max height code

        # Get width and height codes
        width_code = get_width_code(door_width_feet)
        height_code = get_height_code(door_height_feet)

        if lift_type == "high":
            # High Lift hardware kits
            # Format: HK12-WWHHSSS-RC (2") or HK13-WWHHSSS-RC (3")
            # WW = width code (11, 14, 16, 18)
            # HH = height code (08, 10, 12, 14, 16, 18, 20, 21, 22, 24, 26) - 2 digits, not 3
            # SSS = high lift feet (002-004 for 2", 002-013 for 3")

            # Height code for high lift is 2 digits (not 3 like standard lift)
            def get_high_lift_height_code(height_ft: int) -> str:
                if height_ft <= 8:
                    return "08"
                elif height_ft <= 10:
                    return "10"
                elif height_ft <= 12:
                    return "12"
                elif height_ft <= 14:
                    return "14"
                elif height_ft <= 16:
                    return "16"
                elif height_ft <= 18:
                    return "18"
                elif height_ft <= 20:
                    return "20"
                elif height_ft <= 21:
                    return "21"
                elif height_ft <= 22:
                    return "22"
                elif height_ft <= 24:
                    return "24"
                else:
                    return "26"

            hl_height_code = get_high_lift_height_code(door_height_feet)

            if commercial:
                # HK13 - High Lift 3" Track (high lift 2-13 feet)
                high_lift_feet = max(2, min(13, (high_lift_inches + 6) // 12 + 2))
                high_lift_code = f"{high_lift_feet:03d}"
                part_number = f"HK13-{width_code}{hl_height_code}{high_lift_code}-RC"
                description = f"HARDWARE KIT, HIGH LIFT 3\", {door_width_feet}'x{door_height_feet}', +{high_lift_feet}' HL"
            else:
                # HK12 - High Lift 2" Track (high lift only 2-4 feet)
                high_lift_feet = max(2, min(4, (high_lift_inches + 6) // 12 + 2))
                high_lift_code = f"{high_lift_feet:03d}"
                part_number = f"HK12-{width_code}{hl_height_code}{high_lift_code}-RC"
                description = f"HARDWARE KIT, HIGH LIFT 2\", {door_width_feet}'x{door_height_feet}', +{high_lift_feet}' HL"

        else:
            # Standard Lift hardware kits
            if commercial:
                # Always use HK03 for commercial standard lift (not HW boxes)
                # HK03 format: HK03-WWHHX-RC where X is 0 or 1 variant
                variant = "1" if door_width_feet > 14 else "0"
                part_number = f"HK03-{width_code}{height_code[:-1]}{variant}-RC"
                description = f"HARDWARE KIT, STD LIFT 3\", {door_width_feet}'x{door_height_feet}'"
            else:
                # Residential 2" Track - Check for premade HK10 boxes first
                # HK10 premade boxes are more cost-effective for standard sizes:
                # - HK10-00704-0809: 7' height, 8'-10' width, 4 sections
                # - HK10-00704-1316: 7' height, 12'-18' width, 4 sections
                # - HK10-00804-0809: 8' height, 8'-10' width, 4 sections
                # - HK10-00804-1316: 8' height, 12'-18' width, 4 sections

                # Check if door fits premade HK10 box dimensions
                hk10_available = False
                hk10_part = None
                hk10_desc = None

                if door_height_feet == 7 and num_sections == 4:
                    if 8 <= door_width_feet <= 10:
                        hk10_part = "HK10-00704-0809"
                        hk10_desc = "PURCHASED HARDWARE BOX, 2R 8'-10' X 7', STANDARD, 4S3HW, 4 SECTIONS"
                        hk10_available = True
                    elif 12 <= door_width_feet <= 18:
                        hk10_part = "HK10-00704-1316"
                        hk10_desc = "PURCHASED HARDWARE BOX, 2R 12'-18' X 7', STANDARD, 4S5HW, 4 SECTIONS"
                        hk10_available = True
                elif door_height_feet == 8 and num_sections == 4:
                    if 8 <= door_width_feet <= 10:
                        hk10_part = "HK10-00804-0809"
                        hk10_desc = "PURCHASED HARDWARE BOX, 2R 8'-10' X 8', STANDARD, 4S3HW, 4 SECTIONS"
                        hk10_available = True
                    elif 12 <= door_width_feet <= 18:
                        hk10_part = "HK10-00804-1316"
                        hk10_desc = "PURCHASED HARDWARE BOX, 2R 12'-18' X 8', STANDARD, 4S5HW, 4 SECTIONS"
                        hk10_available = True

                if hk10_available:
                    # Use premade HK10 box (more cost-effective)
                    part_number = hk10_part
                    description = hk10_desc
                else:
                    # Fall back to HK02 for non-standard sizes
                    part_number = f"HK02-{width_code}{height_code}-RC"
                    description = f"HARDWARE KIT, STD LIFT 2\", {door_width_feet}'x{door_height_feet}'"

        return BCPartNumber(
            part_number=part_number,
            description=description,
            category="HARDWARE"
        )

    def get_glass_kit(
        self,
        constructed_pn: str,
        door_type: str = "residential"
    ) -> Optional[BCPartNumber]:
        """
        Validate a constructed GK15/GK16 part number against BC items.

        Falls back to searching by description prefix if exact match fails.

        Args:
            constructed_pn: The constructed part number (e.g., GK15-11200-00)
            door_type: 'residential' (GK15) or 'commercial' (GK16)

        Returns:
            BCPartNumber if found in BC items, None otherwise
        """
        # Check exact match in loaded BC items
        if constructed_pn in self.bc_items:
            item = self.bc_items[constructed_pn]
            return BCPartNumber(
                part_number=constructed_pn,
                description=item.get('displayName', item.get('description', '')),
                category="GLASS_KIT",
                bc_item_id=item.get('id')
            )

        # Try prefix search: look for items starting with GK15- or GK16-
        prefix = "GK15-" if door_type == "residential" else "GK16-"
        for item_number, item in self.bc_items.items():
            if item_number == constructed_pn:
                return BCPartNumber(
                    part_number=item_number,
                    description=item.get('displayName', item.get('description', '')),
                    category="GLASS_KIT",
                    bc_item_id=item.get('id')
                )

        # No match found — caller will use the constructed PN with a generated description
        logger.debug(f"Glass kit {constructed_pn} not found in BC items, using constructed PN")
        return None

    def get_frame_insert(self, insert_style: str, panel_color: str) -> Optional["BCPartNumber"]:
        """
        Look up a GL18 decorative frame insert for LONG residential windows.

        Searches bc_items for GL18 parts matching insert style + panel color.
        Falls back to any matching style if no color match found.

        Args:
            insert_style: Frontend insert ID (e.g. STOCKTON_STANDARD, STOCKBRIDGE_ARCHED)
            panel_color:  Panel color name (e.g. WHITE, BLACK, IRON_ORE)

        Returns:
            BCPartNumber for GL18 frame insert, or None if not found
        """
        # Map frontend insert ID to the BC displayName phrase
        style_phrases = {
            "STOCKTON_STANDARD":       "STOCKTON (1PC)",
            "STOCKTON_EIGHT_SQUARE":   "STOCKTON (1PC)",
            "STOCKTON_TEN_SQUARE_XL":  "STOCKTON (1PC)",
            "STOCKTON_ARCHED":         "ARCHED STOCKTON",
            "STOCKTON_ARCHED_XL":      "ARCHED STOCKTON",
            "STOCKBRIDGE_STRAIGHT":    "STRAIGHT STOCKBRIDGE",
            "STOCKBRIDGE_STRAIGHT_XL": "STRAIGHT STOCKBRIDGE",
            "STOCKBRIDGE_ARCHED":      "ARCHED STOCKBRIDGE",
            "STOCKBRIDGE_ARCHED_XL":   "ARCHED STOCKBRIDGE",
        }
        style_phrase = style_phrases.get(insert_style)
        if not style_phrase:
            return None

        # Map panel color to BC color keyword
        color_normalized = panel_color.replace("_", " ").upper()
        color_aliases = {
            "NEW BROWN": "NEW BROWN",
            "BROWN": "WALNUT",
            "SANDTONE": "SANDTONE",
            "WHITE": "WHITE",
            "BLACK": "BLACK",
            "STEEL GREY": "STEEL GREY",
            "NEW ALMOND": "NEW ALMOND",
            "IRON ORE": "IRON ORE",
            "HAZELWOOD": "HAZELWOOD",
            "WALNUT": "WALNUT",
            "ENGLISH CHESTNUT": "ENGLISH CHESTNUT",
        }
        color_kw = color_aliases.get(color_normalized, color_normalized)

        # Two-pass: prefer exact color match, then fall back to any match
        best_match = None
        for pn, item in self.bc_items.items():
            if not pn.startswith("GL18-"):
                continue
            display = item.get("displayName", "").upper()
            if style_phrase.upper() not in display:
                continue
            if color_kw and color_kw.upper() in display:
                return BCPartNumber(
                    part_number=pn,
                    description=item["displayName"],
                    category="WINDOW_INSERT"
                )
            if best_match is None:
                best_match = BCPartNumber(
                    part_number=pn,
                    description=item["displayName"],
                    category="WINDOW_INSERT"
                )

        return best_match

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
