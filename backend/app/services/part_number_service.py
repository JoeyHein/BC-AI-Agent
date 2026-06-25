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

import json
import logging
import math
import os
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
    TX760 = "TX760"
    AL976 = "AL976"
    SWD = "SWD"
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
    # Scale the calculated unit price by this ratio when adding to BC.
    # Used by weather stripping when we substitute the next-biggest SKU
    # for an unstocked size: ratio = requested_ft / sku_ft, so the
    # customer pays a per-foot rate instead of the full bigger strip.
    length_adjustment_ratio: Optional[float] = None


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
    window_positions: Optional[List[dict]] = None  # Residential: [{section, col}, ...]
    window_qty: int = 0  # Commercial: number of windows per section, or V130G section count
    window_panels: Optional[Dict[int, dict]] = None  # Per-panel window config: {2: {"qty": 3}, 4: {"qty": 2}}
    window_frame_color: str = "BLACK"  # Commercial window frame color
    glazing_type: Optional[str] = None
    glass_pane_type: Optional[str] = None  # 'INSULATED' or 'SINGLE'
    glass_type: Optional[str] = "ANNEALED"  # 'ANNEALED' or 'TEMPERED' (safety)
    glass_color: Optional[str] = None      # 'CLEAR', 'ETCHED', 'SUPER_GREY'
    track_radius: str = "15"
    track_thickness: str = "2"
    hardware: Dict[str, bool] = None
    operator: Optional[str] = None
    operator_accessories: Optional[List[str]] = None  # list of accessory part numbers
    door_weight: Optional[float] = None  # lbs - if not provided, will estimate
    target_cycles: int = 10000  # cycle life rating (10000, 15000, 25000, 50000, 100000)
    spring_quantity: int = 2  # number of springs (1 or 2)
    shaft_preference: str = 'auto'  # 'auto', 'single', or 'split'
    track_mount: str = 'bracket'  # 'bracket' or 'angle'
    lift_type: str = 'standard'  # 'standard', 'low_headroom', 'high_lift', 'vertical'
    high_lift_inches: Optional[int] = None
    end_cap_type: str = 'auto'  # 'auto', 'SEC', 'DEC'
    window_size: str = 'long'  # 'short' (GK15-10xxx) or 'long' (GK15-11xxx)
    glass_pockets_per_section: int = 1  # Number of glass pockets per V130G/V230G section
    spring_inventory: Optional[Dict[str, list]] = None  # stocked coil/wire combos from settings
    include_top_seal: Optional[bool] = None  # None=auto (apply rules), True=force include, False=exclude

    def __post_init__(self):
        # Enforce minimum 10,000 cycle standard on all springs
        if self.target_cycles < 10000:
            self.target_cycles = 10000
    include_pusher_springs: bool = False  # Upgrade: adds TR13-00031-00 + TR13-00032-00
    # ─── Additional optional extras (mirror configurator checklist) ───
    # BC item codes for each of these are configured in OPTIONAL_EXTRA_PARTS
    # below. When the flag is on but the BC code hasn't been filled in,
    # a warning is logged and the line is skipped.
    include_man_door: bool = False
    man_door_spec: str = ""        # free-text spec carried into BC line description
    include_interior_lock: bool = False
    include_bumper_spring: bool = False
    include_track_guards: bool = False
    include_exhaust_port: bool = False
    # Manual hand-chain hoist for motor-less commercial doors. One per door.
    # None/'none' = no hoist, 'shaft' = SP12-00084-00, 'wall' = FH12-00190-00.
    chain_hoist: Optional[str] = None


# BC item codes for the optional extras above. Each flag maps to a LIST
# of (item_code, description, qty) tuples — supports single-SKU options
# as well as LH/RH pairs (like pushers) and pair-quantity SKUs.
#
# Codes resolved by scanning BC Production via search_items_by_name on
# 2026-04-25; man-door SKU still pending — the configurator option
# carries a free-text spec, so it likely should map to the kit + a
# manual line or the install SKU.
OPTIONAL_EXTRA_PARTS = {
    # flag_name -> [(item_code, description, qty), ...]
    # Man door — SKU varies by door type. The emit loop below special-cases
    # this flag and picks MI24-00000-00 for steel/residential/commercial
    # overhead doors or MI24-00000-02 for aluminum overhead doors. Both
    # represent a man door being installed INTO the overhead door panel.
    "include_man_door": [
        ("__VARIES__", "MANDOOR INSTALLATION", 1),  # see emit loop
    ],
    # Side lock — one matching SKU in BC.
    "include_interior_lock": [
        ("FH13-00009-00", "SIDE LOCK, 3\"", 1),
    ],
    # Leaf bumper spring pair (LH + RH).
    "include_bumper_spring": [
        ("TR13-00029-00", "TRACK HARDWARE, SPRING, LEAF BUMPER SPRING, LH", 1),
        ("TR13-00030-00", "TRACK HARDWARE, SPRING, LEAF BUMPER SPRING, RH", 1),
    ],
    # Track guards: pair-per-unit, qty 1 ships both guards.
    "include_track_guards": [
        ("TRACKGUARD60", "TRACK GUARDS (PAIR), 60\", SAFETY YELLOW", 1),
    ],
    "include_exhaust_port": [
        ("FH11-00003-00", "EXHAUST PORT RINGS/COVER SET", 1),
    ],
}


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

# Operator part numbers now come from operator_service (CSV catalog with real BC part numbers)


# ============================================================================
# DOOR WEIGHT REFERENCE DATA (from Thermalex Door Weight Calculator)
# ============================================================================

# End cap weight in grams per cap — keyed by (model, section_height_inches)
# Standard: single end cap, 20ga (most common commercial configuration)
# End cap weight in LBS per cap (from BC Items with Weights — FH10 UNIVERSAL singles)
END_CAP_WEIGHT_LBS = {
    ("TX380", 21): 1.30,  ("TX380", 24): 1.48,   # 1-1/2" 20ga
    ("TX450", 21): 1.26,  ("TX450", 24): 1.45,    # 1-3/4" 20ga SGL
    ("TX450-20", 21): 1.26, ("TX450-20", 24): 1.45,
    ("TX500", 21): 1.32,  ("TX500", 24): 1.51,    # 2" 20ga SGL
    ("TX500-20", 21): 1.32, ("TX500-20", 24): 1.51,
    ("TX760", 21): 1.518, ("TX760", 24): 1.7365,  # 3" — TX500 +15% (interim est.)
    # Residential — lighter construction
    ("KANATA", 21): 1.05,  ("KANATA", 24): 1.20,
    ("CRAFT", 21): 1.05,   ("CRAFT", 24): 1.20,
}

# Retainer weight (lbs per linear foot) by model
RETAINER_LBS_PER_FT = {
    "TX380": 0.1824,      # 1-3/8" retainer
    "TX450": 0.175,       # 1-3/4" retainer
    "TX450-20": 0.175,
    "TX500": 0.1513,      # 2" retainer
    "TX500-20": 0.1513,
    "TX760": 0.174,       # 3" retainer (PL10-00136-00) — TX500 +15% (interim est.)
    "KANATA": 0.15,       # residential retainer
    "CRAFT": 0.15,
}

# Astragal weights (lbs per linear foot)
BOTTOM_ASTRAGAL_LBS_PER_FT = 0.2282
TOP_ASTRAGAL_LBS_PER_FT = 0.1427
TOP_ASTRAGAL_MIN_WIDTH_IN = 216  # 18' — top astragal/retainer only on wide doors

# End cap seal weights (lbs per seal piece)
SEAL_WEIGHT_21 = 0.0379
SEAL_WEIGHT_24 = 0.0441

# Strut weight (lbs per linear foot of door width per strut)
STRUT_WEIGHT_PER_FT = {
    "20ga": 0.8025,   # from BC: FH17-00003-00 (16') = 12.84 lbs / 16 = 0.8025
    "16ga": 1.0594,   # from BC: FH17-00018-00 (24') = 25.425 lbs / 24 = 1.05938
    "z": 2.446,
}

# Thermalex Strutting Chart — lookup table for strut requirements
# Rows = door width brackets, Columns = door height brackets
# Value = number of struts; type determined by height column group
STRUT_WIDTH_BRACKETS = [98, 110, 122, 134, 146, 158, 170, 182, 194, 206, 218, 230, 242, 254, 266, 278, 290, 302, 314]
STRUT_HEIGHT_BRACKETS = [98, 121, 145, 169, 193, 217, 241, 265, 289, 313]
# Height bracket index → strut type: 0-1=20ga, 2-5=16ga, 6-9=z
STRUT_HEIGHT_TYPE = ["20ga", "20ga", "16ga", "16ga", "16ga", "16ga", "z", "z", "z", "z"]
# Chart data: STRUT_CHART[width_idx][height_idx] = count
STRUT_CHART = [
    #  8'2  10'1  12'1  14'1  16'1  18'1  20'1  22'1  24'1  26'1   (heights)
    [  0,    0,    0,    0,    0,    0,    0,   12,   13,   14],  # 8'2  width
    [  0,    0,    0,    0,    0,    0,    0,   12,   13,   14],  # 9'2
    [  0,    0,    0,    0,    0,    0,    0,   12,   13,   14],  # 10'2
    [  0,    0,    0,    0,    0,    0,    0,   12,   13,   14],  # 11'2
    [  0,    0,    0,    0,    0,    0,    0,   12,   13,   14],  # 12'2
    [  0,    0,    0,    0,    0,    0,    0,   12,   13,   14],  # 13'2
    [  0,    0,    0,    0,    0,    0,    0,   12,   13,   14],  # 14'2
    [  0,    0,    0,    0,    5,    6,    7,   12,   13,   14],  # 15'2
    [  0,    0,    0,    5,    5,    6,    7,   12,   13,   14],  # 16'2
    [  3,    4,    4,    5,    5,    6,    7,   12,   13,   14],  # 17'2
    [  3,    4,    4,    5,    5,    6,    7,   12,   13,   14],  # 18'2
    [  3,    4,    4,    5,    5,    6,    7,   12,   13,   14],  # 19'2
    [  3,    4,    4,    5,    5,    6,    7,   12,   13,   14],  # 20'2
    [  4,    5,    6,    7,    8,    9,   10,   12,   13,   14],  # 21'2
    [  4,    5,    6,    7,    8,    9,   10,   12,   13,   14],  # 22'2
    [  4,    5,    6,    7,    8,    9,   10,   12,   13,   14],  # 23'2
    [  4,    5,    6,    7,    8,    9,   10,   12,   13,   14],  # 24'2
    [  5,    6,    7,    8,    9,   10,   11,   12,   13,   14],  # 25'2
    [  5,    6,    7,    8,    9,   10,   11,   12,   13,   14],  # 26'2+
]

# Hardware kit weights (lbs) — loaded from BC Items with Weights spreadsheet
_HK_WEIGHTS_PATH = os.path.join(os.path.dirname(__file__), "hardware_kit_weights.json")
with open(_HK_WEIGHTS_PATH, "r") as _f:
    HK_WEIGHTS = json.load(_f)


def _get_hk_weight(door_width_in: int, door_height_in: int, commercial: bool) -> float:
    """Look up hardware kit weight by generating the HK part number.

    Uses the same width/height code logic as bc_part_number_mapper.get_hardware_box().
    Returns weight in lbs, or 0.0 if not found.
    """
    door_width_feet = round(door_width_in / 12)
    door_height_feet = round(door_height_in / 12)

    # Width code (must match get_hardware_box in bc_part_number_mapper)
    if commercial:
        # Commercial width codes: 11, 14, 16, 17, 19, 20, 22, 24, 26, 28, 29
        if door_width_feet <= 11:
            wc = "11"
        elif door_width_feet <= 14:
            wc = "14"
        elif door_width_feet <= 16:
            wc = "16"
        elif door_width_feet <= 17:
            wc = "17"
        elif door_width_feet <= 19:
            wc = "19"
        elif door_width_feet <= 20:
            wc = "20"
        elif door_width_feet <= 22:
            wc = "22"
        elif door_width_feet <= 24:
            wc = "24"
        elif door_width_feet <= 26:
            wc = "26"
        elif door_width_feet <= 28:
            wc = "28"
        else:
            wc = "29"
    else:
        # Residential width codes: 11, 14, 16, 18, 20
        if door_width_feet <= 11:
            wc = "11"
        elif door_width_feet <= 14:
            wc = "14"
        elif door_width_feet <= 16:
            wc = "16"
        elif door_width_feet <= 18:
            wc = "18"
        elif door_width_feet <= 20:
            wc = "20"
        else:
            wc = "20"

    # Height code (same as get_hardware_box)
    if door_height_feet <= 8:
        hc = "080"
    elif door_height_feet <= 10:
        hc = "100"
    elif door_height_feet <= 12:
        hc = "120"
    elif door_height_feet <= 14:
        hc = "140"
    elif door_height_feet <= 16:
        hc = "160"
    elif door_height_feet <= 18:
        hc = "180"
    elif door_height_feet <= 20:
        hc = "200"
    elif door_height_feet <= 21:
        hc = "210"
    elif door_height_feet <= 22:
        hc = "220"
    elif door_height_feet <= 24:
        hc = "240"
    else:
        hc = "260"

    if commercial:
        # HK03 format: HK03-WWHHX-RC where X is 0 (SEC) or 1 (DEC)
        # Try SEC first, then DEC
        pn_sec = f"HK03-{wc}{hc[:-1]}0-RC"
        pn_dec = f"HK03-{wc}{hc[:-1]}1-RC"
        pn = pn_sec if HK_WEIGHTS.get(pn_sec, 0.0) > 0 else pn_dec
    else:
        # HK02 format: HK02-WWHH0-RC
        pn = f"HK02-{wc}{hc}-RC"

    weight = HK_WEIGHTS.get(pn, 0.0)
    if weight == 0.0:
        logger.warning(f"Hardware kit weight not found for {pn} — excluded from door weight")
    else:
        logger.info(f"Hardware kit weight: {pn} = {weight} lbs")
    return weight


# ============================================================================
# PART NUMBER SERVICE
# ============================================================================

    # Residential Kanata window count tables from rulebook
    # Maps door_width_feet -> window count for each stamp group
RESI_WINDOW_COUNT = {
    # SH short stamps (Sheridan, short frame)
    "SH_SHORT": {6:3, 7:3, 8:4, 9:4, 10:5, 11:5, 12:6, 13:6, 14:7, 15:7, 16:8, 17:8, 18:9, 19:9, 20:10},
    # SH/SHXL/BCXL/FLUSH/TRAF long stamps
    "SH_LONG": {6:1, 7:1, 8:2, 9:2, 10:2, 11:2, 12:3, 13:3, 14:3, 15:3, 16:4, 17:4, 18:4, 19:4, 20:5},
    # BC/FLUSH/TRAF short stamps (Bronte Creek short)
    "BC_SHORT": {6:3, 7:3, 8:4, 9:4, 10:4, 11:4, 12:6, 13:6, 14:6, 15:6, 16:8, 17:8, 18:8, 19:8, 20:10},
    # BC long stamps (Bronte Creek long)
    "BC_LONG": {6:1, 7:1, 8:2, 9:2, 10:2, 11:2, 12:3, 13:3, 14:3, 15:3, 16:4, 17:4, 18:4, 19:4, 20:5},
    # SHXL/BCXL/FLUSH/TRAF long stamps (same as SH_LONG for these designs)
    "LONG": {7:2, 8:2, 9:2, 10:2, 11:2, 12:3, 13:3, 14:3, 15:3, 16:4, 17:4, 18:4, 19:4, 20:5},
    # CRAFT series — fixed widths only (8, 9, 12, 16), windows always in top flush panel
    "CRAFT": {8:2, 9:2, 12:3, 16:4},
}


def get_resi_window_count(door_width_feet: int, panel_design: str, window_size: str = 'long', door_series: str = '') -> int:
    """Look up expected window count from the rulebook tables."""
    design_upper = (panel_design or '').upper()

    # CRAFT series has its own fixed table
    if door_series == 'CRAFT':
        table = RESI_WINDOW_COUNT["CRAFT"]
        return table.get(door_width_feet, 2)

    if window_size == 'short' or design_upper in ('SH',):
        # Short stamps — use SH_SHORT or BC_SHORT
        if design_upper in ('BC',):
            table = RESI_WINDOW_COUNT["BC_SHORT"]
        else:
            table = RESI_WINDOW_COUNT["SH_SHORT"]
    else:
        # Long stamps — SHXL, BCXL, FLUSH, TRAF, or SH with long frame
        if design_upper in ('BC',):
            table = RESI_WINDOW_COUNT["BC_LONG"]
        else:
            table = RESI_WINDOW_COUNT["SH_LONG"]

    return table.get(door_width_feet, table.get(max(k for k in table if k <= door_width_feet), 2))


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

        # 0. ALUMINUM AUTO-UPGRADE: 2" → 3" track if door weight > 750 lbs
        if config.door_type == "aluminium" and config.track_thickness == '2':
            al_weight = self._calculate_aluminum_door_weight(config)
            if al_weight > 750:
                config.track_thickness = '3'
                logger.info(f"AL976 auto-upgrade to 3\" track: weight {al_weight:.0f} lbs > 750 lbs threshold")

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

        # Scope of order — reflect partial hardware selections so the BC comment
        # shows PANELS ONLY / DOOR FACE ONLY / NO DOOR FACE instead of always
        # describing a complete door. Aluminum doors always ship their sections,
        # so panels is implicitly on. The bottom retainer is part of the face
        # (it bolts to the bottom panel), so it does NOT count as "hardware".
        panels_on = config.door_type == "aluminium" or hardware.get("panels", True)
        retainer_on = hardware.get("bottomRetainer", True)
        operating_hw = (
            hardware.get("tracks", True),
            hardware.get("springs", True),
            hardware.get("struts", True),
            hardware.get("hardwareKits", True),
            hardware.get("weatherStripping", True),
            hardware.get("shafts", True),
        )
        any_operating_hw = any(operating_hw)

        scope_label = None
        if panels_on and not any_operating_hw:
            scope_label = "DOOR FACE ONLY" if retainer_on else "PANELS ONLY"
        elif not panels_on and (any_operating_hw or retainer_on):
            scope_label = "NO DOOR FACE"

        if scope_label:
            comment_desc += f" | {scope_label}"

        # Track/mount + lift only matter when the door ships with operating
        # hardware. A face/panels-only order has no tracks, so omit those details.
        face_only = scope_label in ("DOOR FACE ONLY", "PANELS ONLY")
        if not face_only:
            track_size = int(config.track_thickness) if config.track_thickness else 2
            mount_label = "ANGLE MOUNT" if config.track_mount == 'angle' else "BRACKET MOUNT"
            comment_desc += f" | {track_size}\" {mount_label}"

            # Add lift type details
            if config.lift_type == 'high_lift' and config.high_lift_inches:
                comment_desc += f" | HIGH LIFT {config.high_lift_inches}\""
            elif config.lift_type == 'vertical':
                comment_desc += " | VERTICAL LIFT"
            elif config.lift_type == 'low_headroom':
                comment_desc += " | LOW HEADROOM"

        parts.append(PartSelection(
            part_number="",  # Comment line has no part number
            description=comment_desc,
            quantity=1,
            category="comment"
        ))

        # 2. PANELS (and aluminum sections/glass — treated as panels for aluminum doors)
        if config.door_type == "aluminium":
            # Aluminum doors use aluminum sections instead of regular panels
            aluminum_parts = self._get_aluminum_section_parts(config)
            parts.extend(aluminum_parts)
        elif hardware.get("panels", True):
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

        # 5. TOP SEAL
        #    Residential: never
        #    Commercial ≥ 18'W AND ≥ 10'H: always included (auto, can't remove)
        #    Commercial below threshold: optional upgrade (include_top_seal=True)
        #    Aluminum: always
        commercial_auto_top_seal = (
            config.door_type == "commercial"
            and config.door_width >= 216
            and config.door_height >= 120
        )
        include_top_seal = (
            config.door_type == "aluminium"
            or commercial_auto_top_seal
            or (config.door_type == "commercial" and config.include_top_seal is True)
        )
        if include_top_seal:
            top_seal_parts = self._get_top_seal_parts(config)
            parts.extend(top_seal_parts)

        # 6. STRUTS
        if hardware.get("struts", True):
            strut_parts = self._get_strut_parts(config)
            parts.extend(strut_parts)

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

        # 8a. PUSHER SPRINGS (optional upgrade)
        if config.include_pusher_springs:
            parts.append(PartSelection(
                part_number="TR13-00031-00",
                description="TRACK HARDWARE, SPRING, PUSHER SPRING, LH",
                quantity=1,
                category="accessory",
            ))
            parts.append(PartSelection(
                part_number="TR13-00032-00",
                description="TRACK HARDWARE, SPRING, PUSHER SPRING, RH",
                quantity=1,
                category="accessory",
            ))

        # 8b. OPTIONAL EXTRAS — man door, side lock, specialty springs,
        # track guards, exhaust port. BC item codes live in
        # OPTIONAL_EXTRA_PARTS at the top of this module.
        for flag_name, items in OPTIONAL_EXTRA_PARTS.items():
            if not getattr(config, flag_name, False):
                continue

            # Special-case: man door SKU varies by overhead-door type.
            if flag_name == "include_man_door":
                is_aluminum = (config.door_type or "").lower() in ("aluminium", "aluminum")
                item_code = "MI24-00000-02" if is_aluminum else "MI24-00000-00"
                desc = ("MANDOOR INSTALLATION - ALUMINUM" if is_aluminum
                        else "MANDOOR INSTALLATION")
                if config.man_door_spec:
                    desc = f"{desc} — {config.man_door_spec}"
                parts.append(PartSelection(
                    part_number=item_code,
                    description=desc,
                    quantity=1,
                    category="accessory",
                ))
                continue

            for item_code, base_desc, qty in items:
                if item_code is None:
                    logger.warning(
                        "Optional extra '%s' line '%s' has no BC item code "
                        "configured — skipped. Edit OPTIONAL_EXTRA_PARTS in "
                        "part_number_service.py once the code is known.",
                        flag_name, base_desc,
                    )
                    continue
                parts.append(PartSelection(
                    part_number=item_code,
                    description=base_desc,
                    quantity=qty,
                    category="accessory",
                ))

        # 8b. DECORATIVE HARDWARE (residential only, if selected)
        if config.door_type == "residential" and hardware.get("decorativeHardware", False):
            parts.append(PartSelection(
                part_number="FH12-00003-00",
                description="SPADE HINGES (SET OF 4)",
                quantity=1,
                category="decorative_hardware"
            ))
            parts.append(PartSelection(
                part_number="FH13-00006-00",
                description="SPADE PULL HANDLES (SET OF 2)",
                quantity=1,
                category="decorative_hardware"
            ))

        # 9. SPRINGS (computed before shafts — spring count drives shaft count)
        spring_parts = []
        spring_count = 2  # default (number of individual springs, NOT inches)
        is_tandem = False
        if hardware.get("springs", True):
            spring_parts, spring_count, is_tandem = self._get_spring_parts(config)
            parts.extend(spring_parts)

        # 10. SHAFT (uses spring_count to determine shaft count). When the
        # spring picker fell back to a tandem assembly (second shaft coupled
        # to the primary), the shaft picker doubles its shaft + coupler
        # quantities to physically support that.
        if hardware.get("shafts", True):
            shaft_parts = self._get_shaft_parts(config, spring_count=spring_count, is_tandem=is_tandem)
            parts.extend(shaft_parts)

        # 11. WEATHER SEAL (sides and header)
        if hardware.get("weatherStripping", True):
            seal_parts = self._get_seal_parts(config)
            parts.extend(seal_parts)

        # 12. WINDOWS (non-aluminum doors only — aluminum sections already added above)
        if config.door_type != "aluminium":
            has_windows = (config.window_count > 0) or (config.window_insert and config.window_insert not in (None, "NONE"))
            if has_windows:
                window_parts = self._get_window_parts(config)
                parts.extend(window_parts)

        # Also runs for motor-less commercial doors that opt into a manual
        # chain hoist — _get_operator_parts emits the hoist when operator is NONE.
        has_operator = config.operator and config.operator != "NONE"
        wants_chain_hoist = (config.chain_hoist or "").lower() in self.CHAIN_HOISTS
        if has_operator or wants_chain_hoist:
            operator_parts = self._get_operator_parts(config)
            parts.extend(operator_parts)

        # 13. OVERLAY (residential wood overlay, if selected)
        overlay = hardware.get("overlay") if hardware else None
        if overlay and config.door_type == "residential":
            overlay_parts = self._get_overlay_parts(config, overlay)
            parts.extend(overlay_parts)

        # Apply quantity multiplier for door count (skip comment lines only)
        for part in parts:
            if part.category != "comment":
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

        # Fallback algorithm for heights not in the table — packs the door
        # height with as many 24" panels as possible and swaps in 21"
        # panels (each saving 3") to absorb the remainder. Works for any
        # door height ≥ 63" (3 × 21").
        # SECTION_HEIGHT_TABLE covers 63"–240" exactly; this branch handles
        # anything outside that range (e.g. 28' = 336" tall industrial doors).
        panel_count = max(3, -(-door_height // 24))  # ceil(door_height / 24)
        diff = panel_count * 24 - door_height
        # diff is in [0, 24); each 24"→21" swap saves 3", so n21 = diff/3.
        # Clamp to [0, panel_count] in case of edge cases.
        n21 = max(0, min(panel_count, diff // 3))
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
            "TX380": DoorModel.TX380,
            "TX450": DoorModel.TX450,
            "TX450-20": DoorModel.TX450_20,
            "TX500": DoorModel.TX500,
            "TX500-20": DoorModel.TX500_20,
            "TX760": DoorModel.TX760,
            "KANATA": DoorModel.KANATA,
            "CRAFT": DoorModel.CRAFT,
        }
        door_model = model_map.get(config.door_series, DoorModel.TX450)

        # Actual door width — keep precise value for part number and description.
        # Panel part numbers use FFII format (e.g. 1402 = 14'2"), so we pass
        # the exact fractional feet to the mapper. Do NOT round up to the next
        # whole foot — that generates a wrong width code (e.g. 1500 instead of 1402).
        actual_width_in = config.door_width          # e.g., 170 for 14'2"
        actual_width_feet = actual_width_in / 12     # e.g., 14.1667
        panel_width_feet = actual_width_feet          # exact — mapper formats FFII

        # Determine end cap type — user override or width-based auto
        if config.end_cap_type == 'SEC':
            end_cap_type = EndCapType.SINGLE
        elif config.end_cap_type == 'DEC':
            end_cap_type = EndCapType.DOUBLE
        else:
            end_cap_type = EndCapType.DOUBLE if panel_width_feet > 16 else EndCapType.SINGLE

        # Build display string showing the customer's actual requested width
        actual_ft = actual_width_in // 12
        actual_in_rem = actual_width_in % 12
        width_display = f"{actual_ft:02d}' {actual_in_rem:02d}\""   # e.g., "12' 06\""
        cap_name = "DEC" if end_cap_type == EndCapType.DOUBLE else "SEC"
        color_str = config.panel_color.replace("_", " ").upper()
        if config.door_type == "commercial":
            stamp_str = config.panel_design or "UDC"
        else:
            stamp_str = config.panel_design or "SHXL"
        is_craft = config.door_series == "CRAFT"

        # CRAFT series: always 3 panels at 28" (7' door) or 32" (8' door)
        # 1st panel = FLUSH, 2nd/3rd = chosen stamp (Muskoka splits to Intermediate + Bottom)
        if is_craft:
            craft_h = 28 if config.door_height <= 84 else 32
            craft_panels = []
            # Panel 1: always FLUSH
            p1 = mapper.get_panel_part_number(
                model=door_model, width_feet=panel_width_feet, height_inches=craft_h,
                color=config.panel_color.replace("_", " "), end_cap_type=end_cap_type, stamp="FLUSH"
            )
            craft_panels.append(PartSelection(
                part_number=p1.part_number,
                description=f"SECTION, {door_model.value}, [{width_display}] X {craft_h}\", FLUSH, {color_str}, {cap_name}",
                quantity=1, category="panel"
            ))

            if stamp_str.upper() == "MUSKOKA":
                # Panel 2: Muskoka Intermediate
                p2 = mapper.get_panel_part_number(
                    model=door_model, width_feet=panel_width_feet, height_inches=craft_h,
                    color=config.panel_color.replace("_", " "), end_cap_type=end_cap_type, stamp="MUSKOKA_INTERMEDIATE"
                )
                craft_panels.append(PartSelection(
                    part_number=p2.part_number,
                    description=f"SECTION, {door_model.value}, [{width_display}] X {craft_h}\", MUSKOKA INTERMEDIATE, {color_str}, {cap_name}",
                    quantity=1, category="panel"
                ))
                # Panel 3: Muskoka Bottom
                p3 = mapper.get_panel_part_number(
                    model=door_model, width_feet=panel_width_feet, height_inches=craft_h,
                    color=config.panel_color.replace("_", " "), end_cap_type=end_cap_type, stamp="MUSKOKA_BOTTOM"
                )
                craft_panels.append(PartSelection(
                    part_number=p3.part_number,
                    description=f"SECTION, {door_model.value}, [{width_display}] X {craft_h}\", MUSKOKA BOTTOM, {color_str}, {cap_name}",
                    quantity=1, category="panel"
                ))
            else:
                # Panels 2 & 3: same stamp (Denison, Granville, or Flush)
                p2 = mapper.get_panel_part_number(
                    model=door_model, width_feet=panel_width_feet, height_inches=craft_h,
                    color=config.panel_color.replace("_", " "), end_cap_type=end_cap_type, stamp=stamp_str
                )
                craft_panels.append(PartSelection(
                    part_number=p2.part_number,
                    description=f"SECTION, {door_model.value}, [{width_display}] X {craft_h}\", {stamp_str}, {color_str}, {cap_name}",
                    quantity=2, category="panel"
                ))

            return craft_panels

        # Get mixed-height breakdown
        breakdown = self._get_section_breakdown(config.door_height)

        # V130G/V230G/PANORAMA replace insulated sections — subtract from 24" first, then 21".
        # Count panels with a full-view type, supporting mixed-type windowPanels
        # (e.g. some panels Panorama, others thermopane).
        FULL_VIEW = {"V130G", "V230G", "PANORAMA"}
        v130g_reduction = 0
        if config.window_panels:
            for entry in config.window_panels.values():
                if self._resolve_panel_type(entry, config.window_insert) in FULL_VIEW:
                    v130g_reduction += 1
        elif config.window_insert in FULL_VIEW and config.window_qty > 0:
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
        Calculate door weight for spring sizing.

        Weight = panel_weight + end_cap_weight + retainer_weight + astragal_weight
                 + seal_weight + strut_weight + hardware_kit_weight
        """
        # Panel weight per linear foot by section height (BULK panels, from BC item weights)
        MODEL_WEIGHTS = {
            # Commercial models (from BC Items with Weights — PN40/PN50 BULK)
            "TX380": {"18": 3.4991, "21": 3.4992, "24": 3.9331, "28": 4.5, "32": 5.0},
            "TX450": {"18": 3.812, "21": 3.812, "24": 3.978, "28": 5.0, "32": 5.5},
            "TX450-20": {"18": 5.18, "21": 5.18, "24": 5.6813, "28": 6.2, "32": 6.8},
            "TX500": {"18": 4.002, "21": 4.002, "24": 4.570, "28": 5.2, "32": 5.7},
            "TX500-20": {"18": 5.2865, "21": 5.2865, "24": 5.63, "28": 6.1, "32": 6.6},
            # TX760 (3"): TX500 +15% interim estimate — BC API exposes no panel weights.
            # TODO: replace with exact PN74 BULK lbs/ft when the weights export is available.
            "TX760": {"18": 4.6023, "21": 4.6023, "24": 5.2555, "28": 5.98, "32": 6.555},
            # Residential models (Kanata/Craft)
            "KANATA": {"18": 3.7655, "21": 4.1875, "24": 4.6392, "28": 5.1363, "32": 6.1875},
            "CRAFT": {"18": 3.7655, "21": 4.1875, "24": 4.6392, "28": 5.1363, "32": 6.1875},
        }

        door_width_ft = config.door_width / 12
        door_height_in = config.door_height
        series = config.door_series.upper()

        # Aluminum doors: separate weight model
        if config.door_type == "aluminium":
            return self._calculate_aluminum_door_weight(config)

        model_weights = MODEL_WEIGHTS.get(config.door_series, MODEL_WEIGHTS["KANATA"])

        # Section breakdown (21"/24" mix)
        breakdown = self._get_section_breakdown(door_height_in)
        n21 = breakdown["21"]
        n24 = breakdown["24"]
        num_sections = breakdown["total"]

        # 1. Panel weight
        panel_weight = 0.0
        for h in ["21", "24"]:
            count = breakdown[h]
            if count > 0:
                weight_per_ft = model_weights.get(h, model_weights.get("21", 4.0))
                panel_weight += weight_per_ft * door_width_ft * count

        # 2. End cap weight (2 caps per section — left + right)
        ec_lbs_21 = END_CAP_WEIGHT_LBS.get((series, 21), END_CAP_WEIGHT_LBS.get(("TX450", 21), 1.26))
        ec_lbs_24 = END_CAP_WEIGHT_LBS.get((series, 24), END_CAP_WEIGHT_LBS.get(("TX450", 24), 1.45))
        end_cap_weight = ec_lbs_21 * 2 * n21 + ec_lbs_24 * 2 * n24

        # 3. Retainer weight (bottom always; top only for doors >= 18' wide)
        retainer_per_ft = RETAINER_LBS_PER_FT.get(series, 0.175)
        retainer_count = 1
        if config.door_width >= TOP_ASTRAGAL_MIN_WIDTH_IN:
            retainer_count = 2  # add top retainer for wide doors
        retainer_weight = retainer_count * door_width_ft * retainer_per_ft

        # 4. Astragal weight (bottom always; top for doors >= 18' wide)
        astragal_weight = door_width_ft * BOTTOM_ASTRAGAL_LBS_PER_FT
        if config.door_width >= TOP_ASTRAGAL_MIN_WIDTH_IN:
            astragal_weight += door_width_ft * TOP_ASTRAGAL_LBS_PER_FT

        # 5. End cap seals
        seal_weight = (n21 * 2 * SEAL_WEIGHT_21) + (n24 * 2 * SEAL_WEIGHT_24)

        # 6. Strut weight (from Thermalex strutting chart). All strut types
        # (20ga, 16ga, Z) hang from the springs as part of the physical
        # door, so all are included in the spring balance weight. The
        # earlier Thermalex-derived exclusion of Z struts undersized
        # springs on the very heavy 28'+ doors that need them.
        strut_info = self._get_strut_requirements(config.door_width, config.door_height)
        strut_weight = 0.0
        if strut_info["count"] > 0:
            strut_weight = strut_info["count"] * door_width_ft * strut_info["weight_per_ft"]

        # 7. Hardware kit weight (HK02 residential / HK03 commercial)
        commercial = config.door_type in ("commercial",)
        hardware_weight = _get_hk_weight(config.door_width, config.door_height, commercial)

        # 8. Top seal weight — matches part inclusion logic
        TOP_SEAL_LBS_PER_INCH = 0.025  # 0.3 lbs per linear foot
        commercial_auto_ts = (config.door_type == "commercial" and config.door_width >= 216 and config.door_height >= 120)
        has_top_seal = (
            config.door_type == "aluminium"
            or commercial_auto_ts
            or (config.door_type == "commercial" and config.include_top_seal is True)
        )
        top_seal_weight = config.door_width * TOP_SEAL_LBS_PER_INCH if has_top_seal else 0

        # 9. Window weight (residential + commercial)
        RESI_WINDOW_WEIGHTS = {
            "KANATA": {"short": 4.0, "long": 7.0},
            "CRAFT": {"short": 10.0, "long": 10.0},
        }
        COMM_WINDOW_WEIGHTS = {
            "TX380": {"18x8": 3.49, "24x12": 5.0, "34x16": 9.0},
            "TX450": {"18x8": 2.5, "24x12": 5.16, "34x16": 9.77},
            "TX450-20": {"18x8": 2.45, "24x12": 5.0, "34x16": 9.0},
            "TX500": {"18x8": 2.5, "24x12": 5.0, "34x16": 9.0},
            "TX500-20": {"18x8": 2.3, "24x12": 4.88, "34x16": 9.0},
        }
        FULL_VIEW_INSERTS = {"V130G", "V230G", "PANORAMA"}
        THERMOPANE_INSERTS = {"24X12_THERMOPANE", "34X16_THERMOPANE", "18X8_THERMOPANE"}
        window_weight = 0.0
        panel_credit = 0.0  # weight removed when full-view sections replace steel panels

        def full_view_section_weight(t: str, area_sqft: float) -> float:
            if t == "PANORAMA":
                # Aluminum frame + multiwall polycarbonate: 1.5 lbs/ft²
                return area_sqft * 1.5
            # V130G/V230G: aluminum frame (1.39 lbs/ft²) + insulated glass
            # (3.32 lbs/ft² over ~85% of section area, frame takes the rest)
            return area_sqft * 1.39 + area_sqft * 0.85 * 3.32

        if series in RESI_WINDOW_WEIGHTS and config.window_count > 0:
            win_size = config.window_size or "long"
            wt_per = RESI_WINDOW_WEIGHTS[series].get(win_size, 7.0)
            window_weight = wt_per * config.window_count
        elif config.window_panels:
            # Per-panel walk: each panel may carry its own type (mixed configs).
            # Allocate section heights from the breakdown in 24"-first order so
            # the credit matches _get_panel_parts subtraction.
            remaining_h = {24: breakdown["24"], 21: breakdown["21"]}
            full_view_panels = []  # [(panel_num, type)]
            thermopane_qty = 0
            for panel_num, entry in config.window_panels.items():
                t = self._resolve_panel_type(entry, config.window_insert)
                if t in FULL_VIEW_INSERTS:
                    full_view_panels.append((panel_num, t))
                elif t in THERMOPANE_INSERTS or (t and series in COMM_WINDOW_WEIGHTS):
                    # Treat any non-full-view commercial type as a thermopane window cut
                    thermopane_qty += int((entry or {}).get("qty", 1))
            for _, t in full_view_panels:
                # Take a 24" section if any remain, else a 21"
                h = 24 if remaining_h[24] > 0 else 21
                if remaining_h[h] <= 0:
                    break  # more replacements than panels — defensive
                remaining_h[h] -= 1
                weight_per_ft = model_weights.get(str(h), model_weights.get("21", 4.0))
                panel_credit += weight_per_ft * door_width_ft
                section_area = door_width_ft * (h / 12)
                window_weight += full_view_section_weight(t, section_area)
            if thermopane_qty > 0 and series in COMM_WINDOW_WEIGHTS:
                wt_per = COMM_WINDOW_WEIGHTS[series].get("24x12", 5.0)
                window_weight += wt_per * thermopane_qty
        elif config.window_insert in FULL_VIEW_INSERTS and config.window_qty > 0:
            # Legacy door-level full-view insert (no per-panel windowPanels)
            remaining = config.window_qty
            for h in (24, 21):
                if remaining <= 0:
                    break
                avail = breakdown[str(h)]
                take = min(remaining, avail)
                if take > 0:
                    weight_per_ft = model_weights.get(str(h), model_weights.get("21", 4.0))
                    panel_credit += weight_per_ft * door_width_ft * take
                    section_area = door_width_ft * (h / 12)
                    window_weight += full_view_section_weight(config.window_insert, section_area) * take
                    remaining -= take
        elif series in COMM_WINDOW_WEIGHTS and config.window_qty > 0:
            # Small thermopane windows cut into the panel — keep panel weight,
            # add the window weight on top.
            wt_per = COMM_WINDOW_WEIGHTS[series].get("24x12", 5.0)
            window_weight = wt_per * config.window_qty

        # Apply panel credit (steel panels removed by V130G/V230G/PANORAMA replacements)
        panel_weight -= panel_credit

        total_weight = panel_weight + end_cap_weight + retainer_weight + astragal_weight + seal_weight + strut_weight + hardware_weight + top_seal_weight + window_weight

        breakdown_str = " + ".join(
            f"{breakdown[h]}x{h}\"" for h in ["24", "21"] if breakdown[h] > 0
        )
        extras = end_cap_weight + retainer_weight + astragal_weight + seal_weight + strut_weight + hardware_weight + top_seal_weight + window_weight
        credit_str = f", panel_credit=-{panel_credit:.1f}" if panel_credit > 0 else ""
        logger.info(
            f"Door weight: {series} {door_width_ft:.1f}'x{door_height_in}\" "
            f"= [{breakdown_str}] panels={panel_weight:.1f}{credit_str} + extras={extras:.1f} "
            f"(endcaps={end_cap_weight:.1f}, retainer={retainer_weight:.1f}, "
            f"astragal={astragal_weight:.1f}, struts={strut_weight:.1f}, "
            f"hardware={hardware_weight:.1f}, top_seal={top_seal_weight:.1f}, "
            f"windows={window_weight:.1f}) = {total_weight:.1f} lbs"
        )

        return total_weight

    def _calculate_aluminum_door_weight(self, config: DoorConfiguration) -> float:
        """
        Calculate weight for aluminum full-view doors (AL976, Panorama, Solalite).

        Based on OpenDC All Door Weight Calculator spreadsheet:
        - Panorama / Solalite: 1.5 lbs/ft² of total panel area
        - AL976: aluminum frame weight + glazing weight (varies by glass type)
          Frame: ~1.39 lbs/ft² of door area (derived from spreadsheet build-up)
          Glazing varies significantly by material type

        All types add: hardware (~25 lbs) + strut weight + top seal
        """
        series = config.door_series.upper()
        door_width_ft = config.door_width / 12
        door_height_ft = config.door_height / 12
        door_area_sqft = door_width_ft * door_height_ft

        if series in ("PANORAMA", "SOLALITE"):
            # Simple: 1.5 lbs/ft² of panel area
            panel_weight = door_area_sqft * 1.5
        else:
            # AL976: aluminum frame + glazing
            # Frame weight: ~1.39 lbs/ft² (from spreadsheet 18'x8' = 200 lbs / 144 sqft)
            AL976_FRAME_LBS_PER_SQFT = 1.39
            frame_weight = door_area_sqft * AL976_FRAME_LBS_PER_SQFT

            # Glazing weight per sqft — varies by glass/polycarbonate type
            # From spreadsheet gram/in² converted to lbs/ft²
            glazing_type = (config.glazing_type or "glass").lower()
            glass_color = (config.glass_color or "CLEAR").upper()
            pane_type = (config.glass_pane_type or "INSULATED").upper()

            if glazing_type == "polycarbonate":
                glazing_lbs_per_sqft = 0.54  # 5/8" Polycarbonate
            elif pane_type == "SINGLE":
                glazing_lbs_per_sqft = 1.59  # 3mm Single Tempered
            else:
                # Insulated / thermal glass (default)
                glazing_lbs_per_sqft = 3.32  # 1/2" Sealed Standard Glass

            # Glazing area is slightly less than door area (frame takes some space)
            # From spreadsheet: glazing ~85% of door area
            glazing_area_sqft = door_area_sqft * 0.85
            glazing_weight = glazing_area_sqft * glazing_lbs_per_sqft

            panel_weight = frame_weight + glazing_weight

        # Hardware weight — use same commercial HK weight lookup
        hardware_weight = _get_hk_weight(config.door_width, config.door_height, commercial=True)

        # Strut weight
        strut_info = self._get_strut_requirements(config.door_width, config.door_height)
        strut_weight = 0.0
        if strut_info["count"] > 0 and strut_info["type"] != "z":
            strut_weight = strut_info["count"] * door_width_ft * strut_info["weight_per_ft"]

        # Top seal (aluminum doors always get top seal)
        TOP_SEAL_LBS_PER_INCH = 0.025
        top_seal_weight = config.door_width * TOP_SEAL_LBS_PER_INCH

        total_weight = panel_weight + hardware_weight + strut_weight + top_seal_weight

        logger.info(
            f"Aluminum door weight: {series} {door_width_ft:.0f}'x{door_height_ft:.0f}' "
            f"panel={panel_weight:.1f} + hw={hardware_weight:.1f} + struts={strut_weight:.1f} "
            f"+ top_seal={top_seal_weight:.1f} = {total_weight:.1f} lbs"
        )

        return total_weight

    @staticmethod
    def _calculate_al976_glass_sqft_per_section(
        door_width_in: int, door_height_in: int,
        section_height_in: int, num_sections: int
    ) -> float:
        """
        Calculate actual glass square footage per section for AL976 aluminum doors.

        Based on OpenDC PN Generator - Aluminum Panels spreadsheet (GLASS CALC sheet).
        Accounts for aluminum frame rails, stiles, and build-up components that reduce
        the actual glass area from the full door area.

        Constants (inches):
          End stile (3"):     3.6
          Center stile (2"):  2.64
          Top rail (3"):      3.135
          Bottom rail (3"):   3.135
          Male rail:          1.25
          Female rail:        1.25
          Glass width add:    +0.4545 (per pane)
          Glass height sub:   -0.431 (per section)
        """
        # Glass panels per section based on door width
        if door_width_in <= 98:
            panels = 2
        elif door_width_in <= 146:
            panels = 3
        elif door_width_in <= 170:
            panels = 4
        elif door_width_in <= 206:
            panels = 5
        elif door_width_in <= 242:
            panels = 6
        elif door_width_in <= 291:
            panels = 7
        else:
            panels = 8

        # Frame constants
        END_STILE = 3.6
        CENTER_STILE = 2.64
        TOP_RAIL = 3.135
        BOTTOM_RAIL = 3.135
        MALE_RAIL = 1.25
        FEMALE_RAIL = 1.25
        GLASS_W_CONSTANT = 0.4545
        GLASS_H_CONSTANT = 0.431

        # Glass width per pane
        glass_width = ((door_width_in - (END_STILE * 2) - (CENTER_STILE * (panels - 1))) / panels) + GLASS_W_CONSTANT

        # Glass height per section
        glass_height = ((door_height_in - TOP_RAIL - BOTTOM_RAIL - ((MALE_RAIL + FEMALE_RAIL) * (num_sections - 1))) / num_sections) - GLASS_H_CONSTANT

        # Total glass area for one section (all panes in that section)
        glass_sqft_per_section = (glass_width * glass_height * panels) / 144

        return max(glass_sqft_per_section, 0)

    @staticmethod
    def _get_strut_requirements(door_width_in: int, door_height_in: int) -> dict:
        """Look up strut requirements from the Thermalex strutting chart.

        Returns: {"count": int, "type": str, "weight_per_ft": float}
        """
        # Find nearest width bracket (round up to next bracket)
        w_idx = -1
        for i, w in enumerate(STRUT_WIDTH_BRACKETS):
            if door_width_in <= w:
                w_idx = i
                break
        if w_idx == -1:
            w_idx = len(STRUT_WIDTH_BRACKETS) - 1  # use last row for oversized

        # Find nearest height bracket (round up to next bracket)
        h_idx = -1
        for i, h in enumerate(STRUT_HEIGHT_BRACKETS):
            if door_height_in <= h:
                h_idx = i
                break

        # Door height below minimum chart height → no struts needed
        if h_idx == -1:
            # Height exceeds chart → use last column
            h_idx = len(STRUT_HEIGHT_BRACKETS) - 1
        # Door width below minimum chart width → use first row
        if door_width_in < STRUT_WIDTH_BRACKETS[0]:
            # Small door below chart → likely 0 struts (use first row)
            w_idx = 0

        count = STRUT_CHART[w_idx][h_idx]
        strut_type = STRUT_HEIGHT_TYPE[h_idx]

        # Strut type determined entirely by width
        if door_width_in >= 336:      # ≥28' wide → Z struts
            strut_type = "z"
        elif door_width_in > 216:     # >18' wide → 16ga
            strut_type = "16ga"
        else:                         # ≤18' wide → 20ga
            strut_type = "20ga"

        weight_per_ft = STRUT_WEIGHT_PER_FT[strut_type]

        return {"count": count, "type": strut_type, "weight_per_ft": weight_per_ft}

    # Available track heights in BC by track size and mount type
    TRACK_AVAILABILITY = {
        (3, "BM"): [8, 10, 12, 14, 16],
        (3, "AM"): [10, 14, 18, 20, 22, 24],
        (2, "BM"): [7, 8, 9, 10, 12, 14],
        (2, "AM"): [8],
    }

    def _get_track_parts(self, config: DoorConfiguration) -> List[PartSelection]:
        """Get track part numbers using actual BC parts.

        Respects the user's mount type selection. If the exact height isn't
        available, steps up to the next available size.  If no larger size
        exists in the requested mount type, falls back to angle mount.
        Doors >= 16' (192") always get angle mount.
        CRAFT series uses TR25 20" radius tracks exclusively.
        """
        mapper = get_bc_mapper()

        # CRAFT series: always TR25 20" radius tracks per rulebook
        if config.door_series == "CRAFT":
            door_height_feet = math.ceil(config.door_height / 12)
            craft_tracks = {
                7: ("TR25-00001-00", 'COMPLETE STANDARD 2" TRACK KIT, 20" RADIUS, 7\' HIGH, BRACKET MOUNT'),
                8: ("TR25-00003-00", 'COMPLETE STANDARD 2" TRACK KIT, 20" RADIUS, 8\' HIGH, BRACKET MOUNT'),
            }
            part_key = 7 if door_height_feet <= 7 else 8
            pn, desc = craft_tracks[part_key]
            return [PartSelection(
                part_number=pn, description=desc, quantity=1, category="track"
            )]

        # Round UP to next whole foot for BC part number (track must cover full door height)
        door_height_feet = math.ceil(config.door_height / 12)
        track_size = int(config.track_thickness) if config.track_thickness else 2
        radius_inches = int(config.track_radius) if config.track_radius else 12

        # Commercial: 2" track only allowed if height ≤14' AND width ≤18' per rulebook
        if config.door_type == "commercial" and track_size == 2:
            if config.door_height > 168 or config.door_width > 216:  # >14' or >18'
                track_size = 3
                radius_inches = 12  # 3" tracks don't use radius

        # Determine lift type and mount type
        # HIGH LIFT uses STANDARD LIFT track assemblies — the extension kits
        # (TR02-EXT4, TR03-EXT4/EXT6) are added separately by _get_highlift_parts().
        # BC has no dedicated high-lift track part numbers.
        lift_type_map = {
            'standard': LiftType.STANDARD,
            'low_headroom': LiftType.LOW_HEADROOM,
            'high_lift': LiftType.STANDARD,   # ← standard track + extension kit
            'vertical': LiftType.VERTICAL,
        }
        lift_type = lift_type_map.get(config.lift_type, LiftType.STANDARD)
        mount_type = TrackMount.ANGLE if config.track_mount == 'angle' else TrackMount.BRACKET

        # Resolve actual part: find the smallest available height >= requested
        mount_code = "BM" if mount_type == TrackMount.BRACKET else "AM"
        available = self.TRACK_AVAILABILITY.get((track_size, mount_code), [])
        valid_heights = [h for h in available if h >= door_height_feet]

        if valid_heights:
            # Use the smallest available height that fits
            part_height = min(valid_heights)
        else:
            # No bracket mount large enough — fall back to angle mount
            if mount_type == TrackMount.BRACKET:
                mount_type = TrackMount.ANGLE
                mount_code = "AM"
                available = self.TRACK_AVAILABILITY.get((track_size, "AM"), [])
                valid_heights = [h for h in available if h >= door_height_feet]
                part_height = min(valid_heights) if valid_heights else door_height_feet
            else:
                part_height = door_height_feet

        mount_label = "ANGLE MOUNT" if mount_type == TrackMount.ANGLE else "BRACKET MOUNT"

        # Get track assembly part number using the resolved height
        track = mapper.get_track_assembly(
            door_height_feet=part_height,
            track_size=track_size,
            lift_type=lift_type,
            mount_type=mount_type,
            radius_inches=radius_inches
        )

        # Build description showing the actual door height and resolved part info
        actual_ft = config.door_height // 12
        actual_in = config.door_height % 12
        if actual_in > 0:
            height_display = f"{actual_ft}'{actual_in}\""
        else:
            height_display = f"{actual_ft}'"
        lift_label_map = {
            'standard': 'STANDARD LIFT',
            'low_headroom': 'LOW HEADROOM',
            'high_lift': 'STANDARD LIFT',  # track is standard; extension kit is separate
            'vertical': 'VERTICAL LIFT',
        }
        lift_label = lift_label_map.get(config.lift_type, 'STANDARD LIFT')
        if config.lift_type == 'vertical':
            track_desc = (
                f"{track_size}\" {lift_label} {mount_label}; {height_display} High"
            )
        else:
            track_desc = (
                f"{track_size}\" {lift_label} {mount_label}; {height_display} High,"
                f"{radius_inches}\"Radius"
            )

        parts = [PartSelection(
            part_number=track.part_number,
            description=track_desc,
            quantity=1,  # Track assembly is sold as a kit (pair)
            category="track"
        )]

        # LHR doors need standard track assembly + LHR conversion kit
        if lift_type == LiftType.LOW_HEADROOM:
            std_track = mapper.get_track_assembly(
                door_height_feet=part_height,
                track_size=track_size,
                lift_type=LiftType.STANDARD,
                mount_type=mount_type,
                radius_inches=radius_inches
            )
            parts.insert(0, PartSelection(
                part_number=std_track.part_number,
                description=f"{track_size}\" STANDARD LIFT {mount_label}; {height_display} High, {radius_inches}\"Radius",
                quantity=1,
                category="track"
            ))

        return parts

    def _get_spring_parts(self, config: DoorConfiguration) -> Tuple[List[PartSelection], int, bool]:
        """
        Get spring part numbers using door_calculator for spring selection + BC part number mapper.

        Uses door_calculator._calculate_springs() as the single source of truth —
        same progressive qty scaling (2→4→6→8), duplex support, and Canimex methodology
        used by the Door Specifications tab.

        Then maps to actual BC part numbers:
        - SP11-{wire}{coil}-{wind} for oil tempered springs
        - SP12-{code} for winder/stationary sets

        Returns (parts_list, spring_qty) where spring_qty is the number of individual
        springs (e.g. 2, 4, 6, 8) — NOT inches of spring wire.
        """
        parts = []

        # Get door weight - use provided weight or calculate from linear foot weights
        door_weight = config.door_weight
        if door_weight is None:
            door_weight = self._calculate_door_weight(config)

        # Parse track radius (handle string format)
        track_radius = int(config.track_radius) if config.track_radius else 15

        # Map lift type to door_calculator's lift config for correct drum selection
        # Without this, VL/HL doors get a standard drum → wrong spring calculation
        lift_type_map = {
            'standard': 'standard',
            'low_headroom': 'standard',
            'high_lift': 'high',
            'vertical': 'vertical',
        }
        dc_lift_type = lift_type_map.get(config.lift_type, 'standard')
        lift_config = {"type": dc_lift_type, "radius": track_radius}

        # Select the correct drum for this lift type
        # 3" track forces D525-216 minimum (no D400 drums)
        track_size = int(config.track_thickness) if config.track_thickness else 2
        high_lift_inches = config.high_lift_inches or 0
        effective_height = config.door_height + high_lift_inches if dc_lift_type == 'high' else config.door_height
        drums = door_calculator._select_drum(
            config.door_height, door_weight, lift_config,
            effective_height=effective_height,
            track_size=track_size,
        )

        # Use door_calculator._calculate_springs() — same engine as specs tab
        spring_result = door_calculator._calculate_springs(
            door_weight=door_weight,
            height_inches=config.door_height,
            width_inches=config.door_width,
            drums=drums,
            target_cycles=config.target_cycles,
            track_radius=track_radius,
            spring_inventory=config.spring_inventory,
            high_lift_inches=high_lift_inches,
        )

        if spring_result is None:
            # No standard spring fits this door at the requested cycle life.
            # Common above 25K cycles on big high-lift doors. The quote
            # still generates with everything else priced out — but a
            # prominent comment line tells the customer (and the office
            # reviewing the quote) that engineering has to size and price
            # the springs before this quote can be approved.
            logger.warning(
                f"Spring calculator returned no result for {door_weight:.0f} lbs, "
                f"{config.door_height}\" height, {config.target_cycles} cycles "
                f"— flagged for office review"
            )
            parts.append(PartSelection(
                part_number="",
                description=(
                    f"** OFFICE REVIEW REQUIRED — SPRINGS: "
                    f"{door_weight:.0f} lbs door at {config.target_cycles:,} cycles "
                    f"exceeds standard spring sizing. Engineering must spec and "
                    f"price the spring assembly before this quote is approved. **"
                ),
                quantity=0,
                category="spring_warning",
                notes="spring_office_review_required",
            ))
            # Return spring_qty=2 (the default) so downstream shaft count and
            # cone-set logic still emits sensible defaults; the office will
            # finalize spring details when they review the quote.
            return parts, 2, False
        else:
            wire_size = spring_result.wire_diameter
            coil_id = spring_result.coil_diameter
            spring_length = math.ceil(spring_result.length)
            spring_qty = spring_result.quantity
            is_duplex = spring_result.is_duplex

        # Validate spring is physically practical
        spring_warnings = []
        MAX_SPRING_LENGTH = 60  # inches — longer than this won't fit most shafts
        MAX_WIRE_SIZE = 0.625   # inches — thicker than this needs special equipment

        if spring_length > MAX_SPRING_LENGTH:
            spring_warnings.append(
                f"Spring length ({spring_length}\") exceeds maximum practical length ({MAX_SPRING_LENGTH}\"). "
                f"Consider reducing cycle life or contact office for custom quote."
            )

        if wire_size > MAX_WIRE_SIZE:
            spring_warnings.append(
                f"Wire size ({wire_size}\") exceeds maximum standard size ({MAX_WIRE_SIZE}\"). "
                f"Contact office for custom spring quote."
            )

        if spring_warnings:
            for warning in spring_warnings:
                parts.append(PartSelection(
                    part_number="",
                    description=f"** SPRING WARNING: {warning} **",
                    quantity=0,
                    category="spring_warning",
                    notes="spring_validation_warning",
                ))

        # Residential doors: if wire < .218 with 2+ springs, retry with 1 spring
        # BC minimum wire is .218 — anything smaller has no BC part number
        if wire_size < 0.218 and config.door_type == "residential" and spring_qty >= 2:
            single_result = door_calculator._calculate_springs(
                door_weight=door_weight,
                height_inches=config.door_height,
                width_inches=config.door_width,
                drums=drums,
                target_cycles=config.target_cycles,
                track_radius=track_radius,
                spring_qty=1,
                spring_inventory=config.spring_inventory,
                high_lift_inches=high_lift_inches,
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

        # Spring info comment line — door weight, drum, and turns. When the
        # picker had to fall back to a tandem shaft (second shaft coupled
        # to the primary to fit the spring count), call that out so the
        # office knows extra hardware is required.
        drum_model = drums.model if drums else "N/A"
        spring_turns = spring_result.turns if spring_result else 0
        is_tandem = bool(getattr(spring_result, "is_tandem", False)) if spring_result else False
        info_desc = f"Door Weight: {door_weight:.0f} lbs | Drum: {drum_model} | Turns: {spring_turns:.1f}"
        if is_tandem:
            info_desc += " | TANDEM SHAFT REQUIRED"
        parts.append(PartSelection(
            part_number="",
            description=info_desc,
            quantity=0,
            category="spring_comment",
            notes="spring_info_comment",
        ))

        # LH/RH counts. Standard pairs use 1 LH + 1 RH each; an odd
        # spring_qty (almost always 1 — small residential doors) means a
        # single LH spring with NO RH counterpart. The previous floor of
        # max(1, spring_qty // 2) emitted both windings for a 1-spring
        # door, which doubled the spring lines on the quote.
        if spring_qty <= 1:
            lh_count = 1
            rh_count = 0
            pairs = 1   # legacy alias still referenced below
        else:
            pairs = spring_qty // 2
            lh_count = pairs
            rh_count = pairs

        # Outer springs (LH and RH)
        spring_lh = mapper.get_spring_part_number(wire_size, coil_id, "LH")
        spring_rh = mapper.get_spring_part_number(wire_size, coil_id, "RH")

        # Validate spring exists in BC — uses shared resolver that tries:
        # same wire/coil → step up wire → next coil up → step up wire at next coil
        spring_found_in_bc = spring_lh.part_number in mapper.spring_items
        if not spring_found_in_bc:
            found, resolved_wire, resolved_coil = mapper.resolve_spring_in_bc(wire_size, coil_id)
            if found:
                if resolved_wire != wire_size or resolved_coil != coil_id:
                    logger.info(
                        f"Spring {wire_size}\" x {coil_id}\" not in BC — "
                        f"resolved to {resolved_wire}\" x {resolved_coil}\""
                    )
                wire_size = resolved_wire
                coil_id = resolved_coil
                spring_lh = mapper.get_spring_part_number(wire_size, coil_id, "LH")
                spring_rh = mapper.get_spring_part_number(wire_size, coil_id, "RH")
                spring_found_in_bc = True

        # If no BC part number found after step-up, warn but still include the calculated specs
        # so the line can be edited in BC with the correct part number
        if not spring_found_in_bc:
            logger.warning(
                f"No BC spring part number for {wire_size}\" wire x {coil_id}\" coil — "
                f"no step-up available"
            )
            parts.append(PartSelection(
                part_number="",
                description=(
                    f"** SPRING — EDIT IN BC: Calculated {wire_size}\" wire x {coil_id}\" ID x {spring_length}\" "
                    f"not in standard inventory for {config.target_cycles:,} cycles. "
                    f"Update spring part number in BC quote. **"
                ),
                quantity=0,
                category="spring_warning",
                notes="spring_not_in_inventory",
            ))

        # Spring detail comment: wire, ID, length, qty per hand
        if is_duplex and spring_result:
            inner_wire_c = spring_result.inner_wire_diameter
            inner_coil_c = spring_result.inner_coil_diameter
            inner_length_c = math.ceil(spring_result.inner_length)
            duplex_pairs_c = spring_result.duplex_pairs
            specs = (
                f"Springs: Outer {wire_size}\" wire x {coil_id}\" ID x {spring_length}\""
                f" | Inner {inner_wire_c}\" wire x {inner_coil_c}\" ID x {inner_length_c}\""
            )
            if config.door_count > 1:
                total_lh = lh_count * config.door_count
                total_rh = rh_count * config.door_count
                total_springs = spring_qty * config.door_count
                if total_rh > 0:
                    spring_detail_desc = f"{specs} | {total_lh} LH + {total_rh} RH ({total_springs} total)"
                else:
                    spring_detail_desc = f"{specs} | {total_lh} LH ({total_springs} total)"
            else:
                if rh_count > 0:
                    spring_detail_desc = f"{specs} | {lh_count} LH + {rh_count} RH ({spring_qty} total)"
                else:
                    spring_detail_desc = f"{specs} | {lh_count} LH ({spring_qty} total)"
        else:
            base = f"Springs: {wire_size}\" wire x {coil_id}\" ID x {spring_length}\" long"
            if config.door_count > 1:
                total_lh = lh_count * config.door_count
                total_rh = rh_count * config.door_count
                total_springs = spring_qty * config.door_count
                if total_rh > 0:
                    spring_detail_desc = f"{base} | {total_lh} LH + {total_rh} RH ({total_springs} total)"
                else:
                    spring_detail_desc = f"{base} | {total_lh} LH ({total_springs} total)"
            else:
                if rh_count > 0:
                    spring_detail_desc = f"{base} | {lh_count} LH + {rh_count} RH ({spring_qty} total)"
                else:
                    spring_detail_desc = f"{base} | {lh_count} LH ({spring_qty} total)"
        parts.append(PartSelection(
            part_number="",
            description=spring_detail_desc,
            quantity=0,
            category="spring_comment",
            notes="spring_detail_comment",
        ))

        # Springs are quoted by length (inches of spring) × number of that wind.
        # rh_count is 0 on single-spring residential doors — skip that line.
        if lh_count > 0:
            parts.append(PartSelection(
                part_number=spring_lh.part_number,
                description=spring_lh.description,
                quantity=spring_length * lh_count,
                category="spring",
                notes=f"Spring: {wire_size}\" x {coil_id}\" x {spring_length}\" LH × {lh_count}"
            ))

        if rh_count > 0:
            parts.append(PartSelection(
                part_number=spring_rh.part_number,
                description=spring_rh.description,
                quantity=spring_length * rh_count,
                category="spring",
                notes=f"Spring: {wire_size}\" x {coil_id}\" x {spring_length}\" RH × {rh_count}"
            ))

        # 6" non-duplex springs need a PVC tube inside each spring, sized to
        # the spring length. Total tube length = spring_length × spring_qty
        # (covers LH + RH). Duplex assemblies skip this — the inner spring
        # already fills the 6" outer.
        if coil_id == 6.0 and not is_duplex:
            parts.append(PartSelection(
                part_number="PK14-00003-00",
                description=f"PVC TUBE FOR 6\" SPRING, {spring_length}\" LONG",
                quantity=spring_length * spring_qty,
                category="spring_accessory",
                notes=f"PVC tube: {spring_length}\" × {spring_qty} springs",
            ))

        # If duplex, also add inner springs
        if is_duplex and spring_result:
            inner_wire = spring_result.inner_wire_diameter
            inner_coil = spring_result.inner_coil_diameter
            inner_length = math.ceil(spring_result.inner_length)
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

            # Winder/stationary sets for inner coil size — universal
            inner_winder = mapper.get_winder_stationary_set(inner_coil, 1.0)
            parts.append(PartSelection(
                part_number=inner_winder.part_number,
                description=inner_winder.description,
                quantity=spring_qty,
                category="spring_accessory"
            ))

        # Add winder/stationary cone sets — universal parts (work for both LH/RH)
        winder_universal = mapper.get_winder_stationary_set(coil_id, 1.0)
        parts.append(PartSelection(
            part_number=winder_universal.part_number,
            description=winder_universal.description,
            quantity=spring_qty,  # one set per spring
            category="spring_accessory"
        ))

        return parts, spring_qty, is_tandem

    def _get_shaft_parts(self, config: DoorConfiguration, spring_count: int = 2, is_tandem: bool = False) -> List[PartSelection]:
        """Get shaft part numbers using actual BC parts.

        Shaft type selection:
        - Residential + weight <= 750 lbs  → 1\" tube shaft (SH12)
        - Residential + weight >  750 lbs  → 1\" solid keyed shaft (SH11)
        - Commercial (any weight <= 2000)   → 1\" solid keyed shaft (SH11)
        - Any door   + weight >  2000 lbs  → 1-1/4\" keyed shaft (SH10-00002-00)

        Asymmetric overhang: 6\" non-operator + 12\" operator = door_width + 18\".
        Shaft count N = max(ceil(spring_count / 2), width_minimum_shafts).
        For N >= 2: N-1 standard shafts (round DOWN) + 1 operator shaft (round UP) + N-1 couplers.
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

        if is_residential:
            door_width_feet = config.door_width // 12

            # 20' residential doors use split solid keyed shafts per rulebook
            if door_width_feet >= 20:
                return [
                    PartSelection(
                        part_number="SH11-11006-00",
                        description="1\" Solid Shaft Keyed 10'-6\"",
                        quantity=1,
                        category="shaft"
                    ),
                    PartSelection(
                        part_number="SH11-11106-00",
                        description="1\" Solid Shaft Keyed 11'-6\"",
                        quantity=1,
                        category="shaft"
                    ),
                ]

            # 8'-18' residential — 1" tube shaft (SH12) per rulebook
            shaft = mapper.get_shaft(door_width_feet=door_width_feet, shaft_type="tube")
            return [PartSelection(
                part_number=shaft.part_number,
                description=shaft.description,
                quantity=1,
                category="shaft"
            )]

        # Heavy residential OR any commercial — 1" solid keyed shaft (SH11)
        # Calculate shaft count N
        spring_driven = math.ceil(spring_count / 2)
        width_minimum = 2 if config.door_width > 170 else 1
        N = max(spring_driven, width_minimum)

        # Apply user overrides
        if config.shaft_preference == 'single':
            N = 1
        elif config.shaft_preference == 'split' and N < 2:
            N = 2

        # Get all available SH11 sizes (FF values) from BC catalog
        available_sh11 = []
        for pn in mapper.bc_items:
            if (pn.startswith("SH11-1") and len(pn) == 13 and
                    pn[8:10] == "06" and pn.endswith("-00")):
                try:
                    available_sh11.append(int(pn[6:8]))
                except ValueError:
                    pass
        available_sh11.sort()
        if not available_sh11:
            available_sh11 = [7, 8, 9, 10, 11, 12, 13, 14, 15]

        # Convert FF values to physical lengths (inches)
        sh11_lengths = [(ff, ff * 12 + 6) for ff in available_sh11]

        if N == 1:
            # Single solid shaft: FF*12+6 >= door_width+18 → FF >= (door_width+12)/12
            required_ff = math.ceil((config.door_width + 12) / 12)
            shaft = mapper.get_shaft(door_width_feet=required_ff, shaft_type="solid")

            selected_ff = int(shaft.part_number[6:8])
            physical_length = selected_ff * 12 + 6
            needed = config.door_width + 18
            if physical_length < needed:
                logger.warning(
                    f"No solid shaft long enough for {width_display} door "
                    f"(need {needed}\", max available {physical_length}\"): "
                    f"using {shaft.part_number}"
                )

            return [PartSelection(
                part_number=shaft.part_number,
                description=shaft.description,
                quantity=1,
                category="shaft"
            )]
        else:
            # Multi-shaft: N-1 standard shafts + 1 operator shaft + N-1 couplers
            total_needed = config.door_width + 18
            base = total_needed / N

            # Standard shaft: largest available SH11 <= base (round DOWN)
            std_ff = available_sh11[0]  # fallback to smallest
            for ff, length in sh11_lengths:
                if length <= base:
                    std_ff = ff
                else:
                    break
            std_length = std_ff * 12 + 6

            # Operator shaft: remainder rounded UP to nearest available SH11
            op_remainder = total_needed - (std_length * (N - 1))
            op_ff = available_sh11[-1]  # fallback to largest
            for ff, length in sh11_lengths:
                if length >= op_remainder:
                    op_ff = ff
                    break

            shaft_std = mapper.get_shaft(door_width_feet=std_ff, shaft_type="solid")
            shaft_op = mapper.get_shaft(door_width_feet=op_ff, shaft_type="solid")
            coupler = mapper.get_shaft_coupler(bore_size=1.0)

            op_length = op_ff * 12 + 6
            total_actual = std_length * (N - 1) + op_length
            if total_actual < total_needed:
                logger.warning(
                    f"Multi-shaft total {total_actual}\" short for {width_display} door "
                    f"(need {total_needed}\"): {N-1}× {shaft_std.part_number} + {shaft_op.part_number}"
                )

            # Tandem assembly: a second shaft coupled to the primary to
            # carry additional spring positions. Doubles every shaft &
            # coupler in this section. The connector that ties the two
            # shafts together is a custom OPENDC SKU still being created;
            # for now a comment line surfaces the requirement to the
            # office reviewing the quote.
            shaft_multiplier = 2 if is_tandem else 1

            parts = []
            if is_tandem:
                parts.append(PartSelection(
                    part_number="",
                    description=(
                        "** TANDEM SHAFT ASSEMBLY: 2x shafts + 2x couplers below. "
                        "Tandem connector SKU pending — office to add when assigned. **"
                    ),
                    quantity=0,
                    category="shaft_comment",
                    notes="tandem_shaft_required",
                ))
            # N-1 standard (non-operator) shafts
            if N - 1 > 0:
                parts.append(PartSelection(
                    part_number=shaft_std.part_number,
                    description=shaft_std.description,
                    quantity=(N - 1) * shaft_multiplier,
                    category="shaft"
                ))
            # 1 operator shaft per shaft assembly (1 single, 2 tandem)
            parts.append(PartSelection(
                part_number=shaft_op.part_number,
                description=shaft_op.description,
                quantity=1 * shaft_multiplier,
                category="shaft"
            ))
            # N-1 couplers per assembly
            parts.append(PartSelection(
                part_number=coupler.part_number,
                description=coupler.description,
                quantity=(N - 1) * shaft_multiplier,
                category="shaft"
            ))
            return parts

    def _get_strut_parts(self, config: DoorConfiguration) -> List[PartSelection]:
        """Get strut part numbers using Thermalex strutting chart.

        The chart determines both the quantity and gauge of struts based on
        door width and height. Small doors may need zero struts.
        CRAFT series: 0 struts without windows (except 16'=1), 1 strut with windows.
        """
        # AL976 panels have struts built into the extrusion — no separate
        # strut line. Every other series (incl. Panorama, Solalite, SWD)
        # defaults to the Thermalex commercial chart unless overridden
        # below.
        series = (config.door_series or "").upper()
        if series == "AL976":
            return []

        # Residential doors (KANATA & CRAFT): always 1 x 20ga strut
        if config.door_type == "residential" and config.door_series in ("KANATA", "CRAFT"):
            door_width_feet = config.door_width // 12
            mapper = get_bc_mapper()
            strut = mapper.get_strut(door_width_feet, 20)
            return [PartSelection(
                part_number=strut.part_number,
                description=strut.description,
                quantity=1,
                category="strut"
            )]

        # Commercial doors: use Thermalex strutting chart
        strut_info = self._get_strut_requirements(config.door_width, config.door_height)
        strut_count = strut_info["count"]
        strut_type = strut_info["type"]

        if strut_count == 0:
            return []

        mapper = get_bc_mapper()
        door_width_feet = config.door_width // 12

        # Map strutting chart type to gauge for BC part number
        if strut_type == "16ga":
            gauge = 16
        else:
            # Both 20ga and z-struts use 20ga BC parts
            # (z-struts are a different assembly but use the same part series)
            gauge = 20

        strut = mapper.get_strut(door_width_feet, gauge)

        return [PartSelection(
            part_number=strut.part_number,
            description=strut.description,
            quantity=strut_count,
            category="strut"
        )]

    def _get_hardware_kit_parts(self, config: DoorConfiguration) -> List[PartSelection]:
        """Get hardware box part numbers using actual BC part numbers.

        Selection order:
        - Residential KANATA/CRAFT, std lift, ≤8' tall, ≤18' wide → HK10 prebuilt box
        - CRAFT (other sizes) → HK02-xxxxx-CR per rulebook
        - Everything else → bc_part_number_mapper (HK02/03/12/13/22/23/32/33)
        """
        mapper = get_bc_mapper()

        door_width_feet = int(config.door_width / 12)
        door_height_feet = int(config.door_height / 12)

        # HK10 prebuilt residential boxes: KANATA & CRAFT, std lift, 2" track,
        # height ≤ 8', width ≤ 18'. Outside that envelope, fall through to the
        # per-size HK02 / CRAFT-specific kits below.
        if (
            (config.door_type or "").lower() == "residential"
            and config.door_series in ("KANATA", "CRAFT")
            and (config.lift_type or "standard") == "standard"
            and config.door_height <= 96
            and door_width_feet <= 18
        ):
            hh = "07" if config.door_height <= 84 else "08"
            ww = "0809" if door_width_feet <= 11 else "1316"
            pn = f"HK10-0{hh}04-{ww}"
            desc = mapper.bc_items.get(pn, {}).get("displayName") \
                or f"HARDWARE BOX, 2R, {door_width_feet}'W x {hh}'H, STANDARD"
            return [PartSelection(
                part_number=pn,
                description=desc,
                quantity=1,
                category="hardware",
            )]

        # CRAFT series: specific hardware kits per rulebook
        if config.door_series == "CRAFT":
            craft_hw = {
                (8, 7): "HK02-10070-CR", (9, 7): "HK02-10070-CR",
                (8, 8): "HK02-10080-CR", (9, 8): "HK02-10080-CR",
                (12, 7): "HK02-18070-CR", (12, 8): "HK02-18080-CR",
                (16, 7): "HK02-18070-CR", (16, 8): "HK02-18080-CR",
            }
            h_key = 7 if door_height_feet <= 7 else 8
            pn = craft_hw.get((door_width_feet, h_key), craft_hw.get((12, h_key), "HK02-10080-CR"))
            return [PartSelection(
                part_number=pn,
                description=f"CRAFT HARDWARE KIT, {door_width_feet}'W x {h_key}'H",
                quantity=1,
                category="hardware"
            )]
        # Hardware box family by track thickness — 3" → commercial (HK03/13/
        # 23/33), 2" → residential (HK02/12/22/32). Aluminum doors override
        # to a generic -AL kit inside the mapper.
        is_commercial = config.track_thickness == '3'
        # Map config.lift_type → the mapper's lift_type vocabulary so all
        # four families (standard / high / vertical / low-headroom) can pick
        # the right HK prefix.
        lift_map = {
            'standard':     'standard',
            'high_lift':    'high',
            'vertical':     'vertical',
            'low_headroom': 'low_headroom',
        }
        mapper_lift = lift_map.get(config.lift_type, 'standard')

        num_sections = self._calculate_panel_count(config.door_height)

        hardware = mapper.get_hardware_box(
            door_width_feet=door_width_feet,
            door_height_feet=door_height_feet,
            num_sections=num_sections,
            commercial=is_commercial,
            lift_type=mapper_lift,
            high_lift_inches=config.high_lift_inches or 0,
            door_type=config.door_type or "commercial",
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

        # Weather strip covers +2" beyond stated length (e.g. 12' strip covers 12'2")
        # Only round up if remainder exceeds 2"
        def _strip_feet(inches: int) -> int:
            feet = inches // 12
            remainder = inches % 12
            return feet if remainder <= 2 else feet + 1

        door_height_feet = _strip_feet(config.door_height)
        door_width_feet = _strip_feet(config.door_width)
        # Resolve the seal color up front so both the part lookup and the
        # human-readable description reflect any substitution (e.g. a French
        # Oak panel seals in New Almond, which is the stocked strip color).
        color = mapper.resolve_weather_strip_color(config.panel_color.replace("_", " "))
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
            commercial=is_commercial,
            door_type=config.door_type,
            door_series=config.door_series or "",
        )
        parts.append(PartSelection(
            part_number=height_strip.part_number,
            description=(
                f"PLASTICS, WEATHER STRIP, GALVANIZED STEEL/FLEXIBLE VINYL,"
                f" {color_upper}, {actual_h_display} (SIDES)"
            ),
            quantity=2,  # Always 2 for left and right jambs
            category="weather_stripping",
            length_adjustment_ratio=height_strip.length_adjustment_ratio,
        ))

        # Get weather strip for WIDTH (header)
        # Max available strip length is 18'. For wider doors, split into 2 pieces.
        if door_width_feet > 18:
            half_feet = math.ceil(door_width_feet / 2)
            width_strip = mapper.get_weather_stripping(
                door_height_feet=half_feet,
                color=color,
                commercial=is_commercial,
                door_type=config.door_type,
                door_series=config.door_series or "",
            )
            parts.append(PartSelection(
                part_number=width_strip.part_number,
                description=(
                    f"PLASTICS, WEATHER STRIP, GALVANIZED STEEL/FLEXIBLE VINYL,"
                    f" {color_upper}, {actual_w_display} (HEADER - SPLIT 2PCS)"
                ),
                quantity=2,
                category="weather_stripping",
                length_adjustment_ratio=width_strip.length_adjustment_ratio,
            ))
        else:
            width_strip = mapper.get_weather_stripping(
                door_height_feet=door_width_feet,
                color=color,
                commercial=is_commercial,
                door_type=config.door_type,
                door_series=config.door_series or "",
            )
            parts.append(PartSelection(
                part_number=width_strip.part_number,
                description=(
                    f"PLASTICS, WEATHER STRIP, GALVANIZED STEEL/FLEXIBLE VINYL,"
                    f" {color_upper}, {actual_w_display} (HEADER)"
                ),
                quantity=1,
                category="weather_stripping",
                length_adjustment_ratio=width_strip.length_adjustment_ratio,
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
        if config.door_type == "aluminium":
            return []  # Aluminum doors don't use retainers

        parts = []
        mapper = get_bc_mapper()
        is_residential = config.door_type == "residential"
        door_width_feet = math.ceil(config.door_width / 12)

        # Commercial gets top + bottom retainer (same roll part);
        # residential gets bottom only (pre-cut rigid retainer by width)
        # Quantity = door width in inches (retainer sold by the inch)
        if not is_residential:
            # Commercial retainer — select by panel series per rulebook.
            # Sold by the inch; one TOP and one BOTTOM run, each = door
            # width. The previous *2 multiplier on wide doors was a holdover
            # from when this emitted a single combined line and double-
            # counted once the TOP/BOTTOM split was added (SQ-002448).
            series = config.door_series or "TX450"
            retainer_info = mapper.COMMERCIAL_RETAINER.get(series, mapper.COMMERCIAL_RETAINER["TX450"])
            retainer_pn, retainer_desc = retainer_info
            retainer_qty = config.door_width

            parts.append(PartSelection(
                part_number=retainer_pn,
                description=f"{retainer_desc} (TOP)",
                quantity=retainer_qty,
                category="retainer"
            ))
            parts.append(PartSelection(
                part_number=retainer_pn,
                description=f"{retainer_desc} (BOTTOM)",
                quantity=retainer_qty,
                category="retainer"
            ))
        else:
            # Residential retainers are pre-cut to size — qty is 1 each
            retainer = mapper.get_retainer(residential=True, door_width_feet=door_width_feet)
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

        astragal = mapper.get_astragal(door_width_feet, door_height_inches=config.door_height, door_type=config.door_type)
        return [PartSelection(
            part_number=astragal.part_number,
            description=astragal.description,
            quantity=config.door_width,
            category="astragal"
        )]

    def _get_top_seal_parts(self, config: DoorConfiguration) -> List[PartSelection]:
        """Get top seal parts (for insulated doors or when explicitly needed)

        Top seal is typically used on:
        - Insulated doors (TX450-20, TX500-20)
        - Doors with weather seal requirements

        Uses a distinct top seal rubber part (PL10-00127-00), NOT the same as weather strip.
        """
        # Top seal on all door types (residential, commercial, aluminium)

        mapper = get_bc_mapper()
        top_seal = mapper.get_top_seal()

        return [PartSelection(
            part_number=top_seal.part_number,
            description=top_seal.description,
            quantity=config.door_width,
            category="top_seal"
        )]

    def _get_highlift_parts(self, config: DoorConfiguration) -> List[PartSelection]:
        """Get high lift extension track kit parts.

        Extension kits are ADDITIONAL line items on top of the standard track assembly.
        Each kit is sized to the exact high lift footage:
        - 2" track: TR02-EXT{feet}-00 (1' through 12')
        - 3" track: TR03-EXT{feet}-00 (2' through 20')
        Round up HL inches to next whole foot. Qty is always 1.
        """
        if config.lift_type != 'high_lift':
            return []

        # Default to minimum HL if lift type is high_lift but inches not specified
        hl_inches = config.high_lift_inches or 24  # default 2' (24") if not set
        hl_feet = math.ceil(hl_inches / 12)
        track_size = int(config.track_thickness) if config.track_thickness else 3

        if track_size == 2:
            hl_feet = max(1, min(hl_feet, 12))  # 2" kits: 1'-12'
            part_number = f"TR02-EXT{hl_feet}-00"
            description = f"TRACK ASSEMBLY, 2\" HIGH LIFT EXTENSION {hl_feet}' KIT"
        else:
            hl_feet = max(2, min(hl_feet, 20))  # 3" kits: 2'-20'
            part_number = f"TR03-EXT{hl_feet}-00"
            description = f"TRACK ASSEMBLY, 3\" HIGH LIFT EXTENSION {hl_feet}' KIT"

        hl_ft_exact = hl_inches / 12
        hl_display = f"{hl_inches}\" ({hl_ft_exact:.1f}')" if hl_inches % 12 != 0 else f"{hl_inches}\" ({hl_feet}')"

        return [
            PartSelection(
                part_number="",
                description=f"HIGH LIFT: {hl_display} requested → {hl_feet}' extension kit selected",
                quantity=0,
                category="highlift_comment",
            ),
            PartSelection(
                part_number=part_number,
                description=description,
                quantity=1,
                category="highlift_track",
            ),
        ]

    def _consolidate_parts(self, parts: List[PartSelection]) -> List[PartSelection]:
        """Merge parts with the same part_number into a single line with summed quantity.

        Preserves order of first occurrence. Glazing/glass parts (sqft-based) are
        already consolidated and left untouched.
        """
        seen: Dict[str, int] = {}  # part_number -> index in result
        result: List[PartSelection] = []
        for p in parts:
            if not p.part_number:
                # Comment lines — keep as-is
                result.append(p)
                continue
            if p.part_number in seen:
                result[seen[p.part_number]].quantity += p.quantity
            else:
                seen[p.part_number] = len(result)
                result.append(p)
        return result

    def _get_aluminum_section_parts(self, config: DoorConfiguration) -> List[PartSelection]:
        """Get aluminum door section parts (PN97, PN80, PN20, PN70) + glass for all panels.

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

        AL-SWD (PN70): PN70-{hh}{www}{f}{p}{s}-{wwww}
          hh  = section height (21 or 24)
          www = width group (100=6'-8'2", 200=8'3"-10'2", 300=10'3"-16'2", 400=16'3"-18'2", 500=18'3"-21'2")
          f   = finish (0=Clear Ano, 1=Mill, 3=White, 8=Black Ano)
          p   = position (1=TOP SEF, 2=INT SEF, 3=BOT SEF, 4=TOP DEF, 5=INT DEF, 6=BOT DEF)
          s   = option (0=NO OPT for SEF; DEF: TOP=5, INT=2, BOT=1)
          wwww = door width + 2" (e.g. 0802=8'2")
          SEF only below 14'2" (170"), DEF available at 14'2"+
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
            # PN80: simpler encoding. WHITE Panorama (PN80-xx110-xxxx) is blocked
            # in BC — fall back to CLEAR ANODIZED so the line goes in as an Item.
            finish_map = {"CLEAR_ANODIZED": "00", "MILL": "20", "BLACK_ANODIZED": "30"}
            ff = finish_map.get(finish_color, "00")
            finish_name = {"00": "CLEAR ANODIZED", "20": "MILL", "30": "BLACK ANODIZED"}.get(ff, "CLEAR ANODIZED")

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
            finish_map = {"CLEAR_ANODIZED": "0", "MILL": "1", "WHITE": "3", "BLACK_ANODIZED": "8", "BLACK": "8"}
            finish_names = {"0": "CLEAR ANO", "1": "MILL", "3": "WHITE", "8": "BLACK ANODIZED"}
            f = finish_map.get(finish_color, "0")
            finish_name = finish_names.get(f, "CLEAR ANO")

            # Determine if DEF needed (>12' uses DEF)
            use_def = door_width_feet > 12

            # Thermal break option
            hw = config.hardware or {}
            has_therm = hw.get("thermalBreak", False)

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
                    if has_therm:
                        s = "3"  # THERM Y
                        opt_label = "THERM Y"
                    else:
                        s = "1"  # DOUBLE
                        opt_label = "DOUBLE"
                    end_label = "DEF"
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

        elif series in ("AL-SWD", "AL_SWD", "ALSWD", "SWD"):
            # PN70: PN70-{hh}{www}{f}{p}{s}-{wwww}
            # Width groups (different from AL976):
            #   1 (100): 6'-8'2" (72-98")
            #   2 (200): 8'3"-10'2" (99-122")
            #   3 (300): 10'3"-16'2" (123-194")
            #   4 (400): 16'3"-18'2" (195-218")
            #   5 (500): 18'3"-21'2" (219-254")
            door_width_in = config.door_width
            if door_width_in <= 98:
                www = "100"
            elif door_width_in <= 122:
                www = "200"
            elif door_width_in <= 194:
                www = "300"
            elif door_width_in <= 218:
                www = "400"
            else:
                www = "500"

            finish_map = {"CLEAR_ANODIZED": "0", "MILL": "1", "WHITE": "3", "BLACK_ANODIZED": "8", "BLACK": "8"}
            finish_names = {"0": "CLEAR ANO", "1": "MILL", "3": "WHITE", "8": "BLACK ANODIZED"}
            f = finish_map.get(finish_color, "0")
            finish_name = finish_names.get(f, "CLEAR ANO")

            # DEF for doors >= 14'2" (170"), SEF only below that
            use_def = door_width_in >= 170

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

                pn = f"PN70-{hh}{www}{f}{p}{s}-{wwww}"
                parts.append(PartSelection(
                    part_number=pn,
                    description=f"SECTION, AL-SWD, [{width_ft:02d}' {width_extra:02d}\"] X {section_height}\", {pos_label} {end_label}, {opt_label}, {finish_name}",
                    quantity=1,
                    category="aluminum_section",
                    notes=f"AL-SWD section {section_num} of {panel_count}"
                ))

        # Wrapping — covers all aluminum panels (sold per sqft)
        wrap_sqft = round((config.door_width * section_height * panel_count) / 144, 2)
        parts.append(PartSelection(
            part_number="WRAPALU",
            description="WRAPPING - ALUMINUM PANELS",
            quantity=wrap_sqft,
            category="aluminum_wrapping",
            notes=f"Wrapping for {panel_count} sections ({config.door_width / 12:.0f}' x {section_height}\" each)"
        ))

        # Glazing — GK17 glass for AL976, GK17 polycarbonate for Panorama/Solalite
        # Glass sqft calculated from actual window opening dimensions per PN Generator spreadsheet
        glazing_sqft_per_section = self._calculate_al976_glass_sqft_per_section(
            config.door_width, config.door_height, section_height, panel_count
        )
        total_glazing_sqft = round(glazing_sqft_per_section * panel_count, 2)

        glazing_type = (config.glazing_type or "").lower()
        is_polycarbonate = glazing_type == "polycarbonate" or series in ("PANORAMA", "SOLALITE")

        if is_polycarbonate:
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
            # AL976 / SWD — GK17 aluminum glazing kits
            # Three independent axes: color × pane (insulated/single) × glass
            # type (annealed/tempered). Lookup is keyed (color, pane, glass).
            glass_color = (config.glass_color or "CLEAR").upper()
            pane_type = (config.glass_pane_type or "INSULATED").upper()
            glass_treatment = (getattr(config, "glass_type", None) or "ANNEALED").upper()

            gk17_glass_map = {
                # INSULATED + ANNEALED
                ("CLEAR",      "INSULATED", "ANNEALED"): ("GK17-11400-00", "GLAZING KIT, ALUM, THERM, CLEAR/CLEAR"),
                ("ETCHED",     "INSULATED", "ANNEALED"): ("GK17-11700-00", "GLAZING KIT, ALUM, THERM, ETCHED/CLEAR"),
                ("SUPER_GREY", "INSULATED", "ANNEALED"): ("GK17-12400-00", "GLAZING KIT, ALUM, THERM, SUPER GREY/CLEAR"),
                # INSULATED + TEMPERED
                ("CLEAR",      "INSULATED", "TEMPERED"): ("GK17-11500-00", "GLAZING KIT, ALUM, THERM, TEMP/CLEAR"),
                ("ETCHED",     "INSULATED", "TEMPERED"): ("GK17-13120-00", "GLAZING KIT, ALUM, THERM, TEMPERED/ETCHED"),
                # SINGLE + ANNEALED
                ("CLEAR",      "SINGLE",    "ANNEALED"): ("GK17-10100-00", "GLAZING KIT, ALUM, SINGLE (3MM), CLEAR"),
                ("ETCHED",     "SINGLE",    "ANNEALED"): ("GK17-10300-00", "GLAZING KIT, ALUM, SINGLE 3MM, ETCHED"),
                # SINGLE + TEMPERED
                ("CLEAR",      "SINGLE",    "TEMPERED"): ("GK17-10200-00", "GLAZING KIT, ALUM, SINGLE (3MM), TEMP"),
                # Combinations not yet stocked in BC fall through to the
                # default below — the warning surfaces on the quote so the
                # office can swap to an in-stock SKU if needed.
            }
            glass_pn, glass_desc = gk17_glass_map.get(
                (glass_color, pane_type, glass_treatment),
                ("GK17-11400-00", "GLAZING KIT, ALUM, THERM, CLEAR/CLEAR"),
            )

            parts.append(PartSelection(
                part_number=glass_pn,
                description=glass_desc,
                quantity=total_glazing_sqft,
                category="aluminum_glass",
                notes=f"Glass for {panel_count} sections ({glazing_sqft_per_section:.2f} sqft each)"
            ))

        return self._consolidate_parts(parts)

    @staticmethod
    def _resolve_panel_type(entry: dict, default_type: Optional[str]) -> str:
        """Effective window type for a panel entry — falls back to door-level windowInsert."""
        return ((entry or {}).get("type") or default_type or "").upper()

    def _split_panels_by_type(self, config: DoorConfiguration) -> Dict[str, Dict[int, dict]]:
        """Group windowPanels by effective type. Returns {} when no per-panel config.

        Each panel entry inherits the door-level windowInsert when it has no explicit
        `type` field (back-compat with older saved quotes).
        """
        if not config.window_panels:
            return {}
        by_type: Dict[str, Dict[int, dict]] = {}
        for panel_num, entry in config.window_panels.items():
            t = self._resolve_panel_type(entry, config.window_insert)
            if not t:
                continue
            by_type.setdefault(t, {})[panel_num] = entry
        return by_type

    def _build_window_placement_note(self, config: DoorConfiguration) -> Optional[str]:
        """Build a human-readable note describing where windows should be placed.

        Panel numbering: 1 = top panel, counting down.
        """
        num_sections = self._calculate_panel_count(config.door_height)

        def panel_label(num):
            if num == 1:
                return "TOP"
            elif num >= num_sections:
                return "BOTTOM"
            else:
                return f"{num} FROM TOP"

        if config.window_panels:
            # Per-panel config: e.g. {1: {"qty": 3, "type": "24X12_THERMOPANE"}, 3: {"qty": 1, "type": "PANORAMA"}}
            panel_descs = []
            for panel_num in sorted(config.window_panels.keys()):
                entry = config.window_panels[panel_num] or {}
                qty = entry.get("qty", 1)
                ptype = self._resolve_panel_type(entry, config.window_insert)
                label = panel_label(panel_num)
                # Include type when it differs from the door-level default so mixed
                # configurations are explicit on the quote
                door_default = (config.window_insert or "").upper()
                type_suffix = f" — {ptype}" if ptype and ptype != door_default else ""
                panel_descs.append(f"{label} PANEL ({qty} window{'s' if qty > 1 else ''}{type_suffix})")
            return "WINDOW PLACEMENT: " + ", ".join(panel_descs)
        elif config.window_positions:
            # Residential stamp-based positions: group by section
            from collections import defaultdict
            by_section = defaultdict(list)
            for pos in config.window_positions:
                by_section[pos.get("section", 1)].append(pos.get("col", 0) + 1)
            section_descs = []
            for section_num in sorted(by_section.keys()):
                cols = sorted(by_section[section_num])
                label = panel_label(section_num)
                section_descs.append(f"{label} PANEL (positions {','.join(str(c) for c in cols)})")
            return f"WINDOW PLACEMENT: {len(config.window_positions)} windows — " + ", ".join(section_descs)
        elif config.window_count > 0:
            section = config.window_section or 1
            label = panel_label(section)
            return f"WINDOW PLACEMENT: {config.window_count} windows in {label} PANEL"
        return None

    def _get_window_parts(self, config: DoorConfiguration) -> List[PartSelection]:
        """Get window/glass kit part numbers using GK15 (residential) or GK16 (commercial).

        For residential KANATA doors:
          SHORT windows (GK15-10xxx): fit one short stamp on SH/BC designs.
            No decorative frame inserts are offered — BC's GL19 short-insert
            catalog is too sparse to price/fulfill (no arched short SKU; only a
            handful of colors). Short inserts are not selectable in either
            configurator, so config.window_insert is never a short-insert id.
          LONG windows (GK15-11xxx): fit one long stamp on SHXL/BCXL, or span 2
            short stamps on SH/BC.  Decorative GL18 frame inserts are available.

        Mixed-type windowPanels (e.g. 1 row Panorama + 1 row 24x12 thermopane on
        the same commercial door) are dispatched by recursing once per type with
        a sub-config so each generator only sees panels of its own type.
        """
        import dataclasses
        panels_by_type = self._split_panels_by_type(config)
        if len(panels_by_type) > 1:
            # Mixed: dispatch each type as its own sub-config and concatenate
            parts: List[PartSelection] = []
            for ptype, panels in panels_by_type.items():
                sub_qty = sum((p or {}).get("qty", 1) for p in panels.values())
                sub = dataclasses.replace(
                    config,
                    window_insert=ptype,
                    window_panels=panels,
                    window_qty=sub_qty,
                )
                parts.extend(self._get_window_parts(sub))
            return self._consolidate_parts(parts)

        # Single-type path: if the only type came from per-panel `type` fields
        # rather than the door-level windowInsert, normalize before dispatch.
        if len(panels_by_type) == 1:
            only_type = next(iter(panels_by_type))
            if only_type != (config.window_insert or "").upper():
                config = dataclasses.replace(config, window_insert=only_type)

        # V130G/V230G: full-view aluminum section + glass (separate line items)
        if config.window_insert in ("V130G", "V230G"):
            return self._get_v130g_parts(config)

        # Panorama: full-view polycarbonate section on commercial door
        if config.window_insert == "PANORAMA":
            return self._get_panorama_section_parts(config)

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
            # Constructed combo isn't a real BC SKU — substitute the nearest
            # existing GK15 so BC SalesPriceLists can resolve a real price.
            # Without this, BC silently prices the unknown PN at 0 / item-card
            # default and the quote shows fabricated pricing.
            substitute = mapper.find_closest_glass_kit(gk15_pn)
            if substitute:
                part_number = substitute.part_number
                description = substitute.description
            else:
                part_number = gk15_pn
                glass_label = {"1": "SINGLE", "2": "THERM-CLEAR", "4": "THERM-ETCHED", "9": "SUPER GREY"}.get(g, "THERM-CLEAR")
                size_label = "SHORT" if is_short else "LONG"
                description = f"GLASS KIT, 1-3/4\" KANATA, {size_label}, {glass_label}, {panel_color_normalized}"

        # Window quantity: use actual window count from positions, or estimate from door width
        window_qty = config.window_count if config.window_count > 0 else max(1, config.door_width // 24)

        # Build window placement note
        window_note = self._build_window_placement_note(config)

        parts = [PartSelection(
            part_number=part_number,
            description=description,
            quantity=window_qty,
            category="window",
            notes=window_note,
        )]

        # Add frame insert for decorative windows. Only LONG (GL18) and Craft
        # (GL17) inserts are offered — short (GL19) inserts were pulled because
        # the BC catalog can't price/fulfill them correctly. A short-insert id
        # on a legacy saved quote is intentionally ignored (no insert line)
        # rather than silently shipping free or in the wrong color.
        decorative_inserts = {
            "STOCKTON_STANDARD", "STOCKTON_EIGHT_SQUARE", "STOCKTON_TEN_SQUARE_XL",
            "STOCKTON_ARCHED", "STOCKTON_ARCHED_XL",
            "STOCKBRIDGE_STRAIGHT", "STOCKBRIDGE_STRAIGHT_XL",
            "STOCKBRIDGE_ARCHED", "STOCKBRIDGE_ARCHED_XL",
        }
        if config.window_insert in decorative_inserts and not is_short:
            if series_upper == "CRAFT":
                # Craft uses GL17 inserts per rulebook
                insert_prefix = "GL17"
            else:
                insert_prefix = "GL18"

            frame_insert = mapper.get_frame_insert(config.window_insert, config.panel_color, insert_prefix=insert_prefix)
            if frame_insert:
                parts.append(PartSelection(
                    part_number=frame_insert.part_number,
                    description=frame_insert.description,
                    quantity=window_qty,
                    category="window"
                ))

        return parts

    @staticmethod
    def _wwww_to_inches(wwww: str) -> int:
        """Convert a 'FFII' section width code (e.g. '0802' = 8'2\") to total inches."""
        return int(wwww[:2]) * 12 + int(wwww[2:])

    def _find_stocked_section(
        self, mapper, prefix: str, hh: str, fff: str, pp: str, target_wwww: str
    ) -> Optional[str]:
        """
        Find the smallest stocked full-view section >= the requested width.

        Matches BC items of the form {prefix}-{hh}{w}{fff}{pp}-{wwww} on height (hh),
        finish (fff) and position (pp), wildcarding the width-group digit (w) and
        accepting whatever width bucket BC actually stocks. Returns the part number of
        the smallest section whose width code is >= target_wwww (an exact match wins,
        since it is the smallest qualifying size), or None if nothing qualifies.

        PN10/PN12 (V130G/V230G) and PN97 (AL976) share this body+width encoding, so the
        same search resolves both the same-family "next size up" and the AL976 substitute.
        """
        try:
            target_in = self._wwww_to_inches(target_wwww)
        except ValueError:
            return None
        best = None
        best_in = None
        for num in mapper.bc_items:
            if not num.startswith(prefix + "-"):
                continue
            segs = num.split("-")
            if len(segs) != 3:
                continue
            body, ww = segs[1], segs[2]
            if len(body) < 8 or len(ww) < 4:
                continue
            if body[:2] != hh or body[3:6] != fff or body[6:8] != pp:
                continue
            try:
                cand_in = self._wwww_to_inches(ww)
            except ValueError:
                continue
            if cand_in >= target_in and (best_in is None or cand_in < best_in):
                best_in, best = cand_in, num
        return best

    def _resolve_full_view_section_pn(
        self, mapper, pn_prefix: str, hh: str, w: str, fff: str, pp: str, wwww: str
    ):
        """
        Resolve a V130G/V230G full-view section against the live BC catalog, with a
        fallback chain that mirrors the spring / track "next size up" resolvers:

          1. Exact V130G/V230G part, if stocked.
          2. Next-bigger stocked size in the same V130G/V230G family.
          3. AL976 (PN97) equivalent at the same size. PN10/PN12 and PN97 share an
             identical body+width encoding, so the substitute is a prefix swap. This
             covers finishes BC does not carry as V130G — notably BLACK (fff=008),
             which is stocked as AL976 but not as V130G.
          4. Next-bigger stocked AL976 size.
          5. The original part number (no substitute found) — caller flags for review.

        Returns (resolved_pn, used_al976: bool, size_bumped: bool).
        """
        desired = f"{pn_prefix}-{hh}{w}{fff}{pp}-{wwww}"

        # Candidate positions in order of physical preference: the requested
        # position, then INT. BC stops stocking TOP/BOT full-view sections past
        # ~20' wide (only INT is carried at 22'+), and TOP/BOT can also be absent
        # in some finishes. The INT section at the exact width is the canonical
        # full-view section and a far better substitute than a wider TOP/BOT, so
        # try INT at the requested size before bumping size.
        int_pp = {"10": "20", "20": "20", "30": "20",   # SEF: 20 = INT
                  "45": "52", "52": "52", "61": "52"}.get(pp, pp)  # DEF: 52 = INT
        positions = [pp] if pp == int_pp else [pp, int_pp]

        # 1. Exact V130G/V230G part (requested position, then INT) at the requested size.
        for cand_pp in positions:
            cand = f"{pn_prefix}-{hh}{w}{fff}{cand_pp}-{wwww}"
            if cand in mapper.bc_items:
                return cand, False, False

        # 2. Next bigger size in the same family (requested position, then INT).
        for cand_pp in positions:
            alt = self._find_stocked_section(mapper, pn_prefix, hh, fff, cand_pp, wwww)
            if alt:
                return alt, False, True

        # 3. AL976 substitute (identical body encoding → prefix swap), requested then INT.
        for cand_pp in positions:
            al_exact = f"PN97-{hh}{w}{fff}{cand_pp}-{wwww}"
            if al_exact in mapper.bc_items:
                return al_exact, True, False

        # 4. Next bigger AL976 size (requested position, then INT).
        for cand_pp in positions:
            alt97 = self._find_stocked_section(mapper, "PN97", hh, fff, cand_pp, wwww)
            if alt97:
                return alt97, True, alt97 != f"PN97-{hh}{w}{fff}{cand_pp}-{wwww}"

        # 5. Nothing stocked — emit the original and let the caller flag it.
        return desired, False, False

    def _get_v130g_parts(self, config: DoorConfiguration) -> List[PartSelection]:
        """
        Get V130G/V230G full-view section parts using real BC part numbers.

        V130G (TX450/TX450-20): PN10 prefix
        V230G (TX500/TX500-20): PN12 prefix

        BC part number format: PN{xx}-{hh}{w}{fff}{pp}-{wwww}
          hh  = section height (21 or 24)
          w   = width group (2=8', 3=10', 4=12'-14', 5=16', 6=18'+)
          fff = finish (000=Clear Ano, 001=Mill, 003=White, 008=Black)
          pp  = position (SEF: 10=TOP, 20=INT, 30=BOT | DEF: 45=TOP, 52=INT, 61=BOT)
          wwww = section width (0802=8'2", 1602=16'2", 2200=22'0", etc.)

        Glass is separate: GK17-xxxxx-xx
        """
        parts = []
        mapper = get_bc_mapper()
        v130g_qty = config.window_qty or 1

        # Determine prefix and model name based on window_insert or door series
        is_v230 = config.window_insert == "V230G"
        pn_prefix = "PN12" if is_v230 else "PN10"
        model_name = "V230G" if is_v230 else "V130G"

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
            resolved_pn, used_al976, size_bumped = self._resolve_full_view_section_pn(
                mapper, pn_prefix, hh, w, fff, pp, wwww
            )

            # Detect a position fallback (e.g. TOP/BOT → INT): BC does not stock
            # TOP/BOT full-view sections at every width, so the resolver may have
            # substituted the INT section. Reflect the actual part in the label/note.
            pos_label_by_code = {"10": "TOP", "20": "INT", "30": "BOT",
                                 "45": "TOP", "52": "INT", "61": "BOT"}
            resolved_segs = resolved_pn.split("-")
            resolved_pp = resolved_segs[1][6:8] if len(resolved_segs) == 3 and len(resolved_segs[1]) >= 8 else pp
            position_substituted = resolved_pp != pp
            actual_position = pos_label_by_code.get(resolved_pp, position)

            section_model = "AL976" if used_al976 else model_name
            note = f"Full view aluminum section - replaces insulated panel at section {section_num}"
            if position_substituted:
                note += (f" | {position} {end_cap_label} not stocked at this width — "
                         f"substituted {actual_position} {end_cap_label} section {resolved_pn}")
                logger.info(
                    f"V130G fallback: {pn_prefix}-{hh}{w}{fff}{pp}-{wwww} ({position} {end_cap_label}) "
                    f"not stocked, substituting {actual_position} {end_cap_label} {resolved_pn}"
                )
            if used_al976:
                note += f" | {model_name} {finish_name} not stocked in BC — substituted AL976 equivalent {resolved_pn}"
                logger.info(
                    f"V130G fallback: {pn_prefix}-{hh}{w}{fff}{pp}-{wwww} ({model_name} {finish_name}) "
                    f"not stocked, substituting AL976 {resolved_pn}"
                )
            if size_bumped:
                note += f" | requested size unavailable — stepped up to next stocked size {resolved_pn}"
                logger.info(
                    f"V130G fallback: {section_model} size {wwww} not stocked, stepped up to {resolved_pn}"
                )

            parts.append(PartSelection(
                part_number=resolved_pn,
                description=f"{section_model} FULL VIEW SECTION, {section_height}\" x {width_ft}'{width_extra}\", {actual_position} {end_cap_label}, {finish_name}",
                quantity=1,
                category="v130g_section",
                notes=note
            ))

        # V130G Glass (GK17 aluminum glazing kits, separate from section frame)
        glass_color = (config.glass_color or "CLEAR").upper()
        pane_type = (config.glass_pane_type or "INSULATED").upper()

        gk17_glass_map = {
            ("CLEAR", "INSULATED"):      ("GK17-11400-00", "GLAZING KIT, ALUM, THERM, CLEAR/CLEAR"),
            ("CLEAR", "SINGLE"):         ("GK17-10100-00", "GLAZING KIT, ALUM, SINGLE (3MM), CLEAR"),
            ("ETCHED", "INSULATED"):     ("GK17-11700-00", "GLAZING KIT, ALUM, THERM, ETCHED/CLEAR"),
            ("ETCHED", "SINGLE"):        ("GK17-10300-00", "GLAZING KIT, ALUM, SINGLE 3MM, ETCHED"),
            ("SUPER_GREY", "INSULATED"): ("GK17-12300-00", "GLAZING KIT, ALUM, THERM, TINTED GR/CLEAR"),
            ("SUPER_GREY", "SINGLE"):    ("GK17-12300-00", "GLAZING KIT, ALUM, THERM, TINTED GR/CLEAR"),
        }
        glass_pn, glass_desc = gk17_glass_map.get(
            (glass_color, pane_type),
            ("GK17-11400-00", "GLAZING KIT, ALUM, THERM, CLEAR/CLEAR")
        )

        # Calculate glass square footage per section using actual window opening dimensions
        panel_count = self._calculate_panel_count(config.door_height)
        glass_sqft_per_section = self._calculate_al976_glass_sqft_per_section(
            config.door_width, config.door_height, section_height, panel_count
        )
        total_glass_sqft = round(glass_sqft_per_section * v130g_qty, 2)

        parts.append(PartSelection(
            part_number=glass_pn,
            description=glass_desc,
            quantity=total_glass_sqft,
            category="v130g_glass",
            notes=f"Thermopane glass for {v130g_qty} {model_name} section(s), {config.glass_pockets_per_section} pockets per section ({glass_sqft_per_section:.2f} sqft each)"
        ))

        return self._consolidate_parts(parts)

    def _get_panorama_section_parts(self, config: DoorConfiguration) -> List[PartSelection]:
        """
        Get Panorama full-view polycarbonate section parts for commercial doors.

        Uses PN80 prefix for aluminum frame sections + GK17 polycarbonate glazing.
        Same panel replacement logic as V130G but with polycarbonate instead of glass.
        """
        parts = []
        panorama_qty = config.window_qty or 1

        section_height = 21 if config.door_type == "residential" or config.door_height <= 84 else 24
        hh = str(section_height)

        # Width code: door width + 2" overhang
        width_ft = config.door_width // 12
        width_extra = config.door_width % 12 + 2
        if width_extra >= 12:
            width_ft += 1
            width_extra -= 12
        wwww = f"{width_ft:02d}{width_extra:02d}"

        # Finish code — Panorama uses PN80 finish map.
        # WHITE PN80 SKUs are blocked in BC (not stocked) so we default
        # to CLEAR ANODIZED when the panel color isn't a stocked frame finish.
        # Allow an explicit override via config.panorama_frame_color.
        raw = getattr(config, "panorama_frame_color", None) or config.panel_color or "CLEAR_ANODIZED"
        finish_color = raw.upper().replace(" ", "_")
        finish_map = {"CLEAR_ANODIZED": "00", "MILL": "20", "BLACK_ANODIZED": "30"}
        ff = finish_map.get(finish_color, "00")
        finish_name = {"00": "CLEAR ANODIZED", "20": "MILL", "30": "BLACK ANODIZED"}.get(ff, "CLEAR ANODIZED")

        panel_count = self._calculate_panel_count(config.door_height)

        # Build list of section numbers
        if config.window_panels:
            section_numbers = sorted(config.window_panels.keys())
            panorama_qty = len(section_numbers)
        else:
            section_start = config.window_section or 1
            section_numbers = [section_start + i for i in range(panorama_qty)]

        for section_num in section_numbers:
            if section_num >= panel_count:
                s = "2"   # BOT SEF
                pos_label = "BOTTOM SEF"
            else:
                s = "1"   # TOP/INT SEF
                pos_label = "TOP/INTERMEDIATE SEF"

            pn = f"PN80-{hh}{s}{ff}-{wwww}"
            parts.append(PartSelection(
                part_number=pn,
                description=f"SECTION, PANORAMA, [{width_ft:02d}' {width_extra:02d}\"] X {section_height}\", {pos_label}, {finish_name}",
                quantity=1,
                category="v130g_section",
                notes=f"Panorama polycarbonate section - replaces insulated panel at section {section_num}"
            ))

        # Polycarbonate glazing (GK17)
        glass_color = (config.glass_color or "CLEAR").upper()
        gk17_map = {
            "CLEAR":        ("GK17-12500-00", "GLAZING KIT, ALUM, POLYCARBONATE, CLEAR"),
            "LIGHT_BRONZE": ("GK17-12600-00", "GLAZING KIT, ALUM, POLYCARBONATE, LIGHT BRONZE"),
            "DARK_BRONZE":  ("GK17-12700-00", "GLAZING KIT, ALUM, POLYCARBONATE, DARK BRONZE"),
            "WHITE_OPAL":   ("GK17-12800-00", "GLAZING KIT, ALUM, POLYCARBONATE, WHITE OPAL"),
        }
        poly_pn, poly_desc = gk17_map.get(glass_color, ("GK17-12500-00", "GLAZING KIT, ALUM, POLYCARBONATE, CLEAR"))

        panel_count = self._calculate_panel_count(config.door_height)
        glazing_sqft_per_section = self._calculate_al976_glass_sqft_per_section(
            config.door_width, config.door_height, section_height, panel_count
        )
        total_glazing_sqft = round(glazing_sqft_per_section * panorama_qty, 2)

        parts.append(PartSelection(
            part_number=poly_pn,
            description=poly_desc,
            quantity=total_glazing_sqft,
            category="v130g_glass",
            notes=f"Polycarbonate for {panorama_qty} Panorama section(s) ({glazing_sqft_per_section:.2f} sqft each)"
        ))

        return self._consolidate_parts(parts)

    def _get_commercial_window_parts(self, config: DoorConfiguration) -> List[PartSelection]:
        """Get commercial thermopane window parts using GK16 part numbers.

        GK16 format: GK16-{S}3{G}{CC}-{VV}
          S  = Series: 2=TX450 (1-3/4"), 4=TX500 (2")
          G  = Glass type: 2=THERM-CLEAR
          CC = Color: 00=WHITE, 05=BLACK
          VV = Variant: 00=24x12, 01=24x8
        """
        mapper = get_bc_mapper()

        # S: Series digit per rulebook
        series_upper = config.door_series.upper()
        if series_upper.startswith("TX500"):
            s = "4"
        elif series_upper.startswith("TX380"):
            s = "3"
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
            # Constructed combo isn't a real BC SKU — substitute the nearest
            # existing GK16 so BC SalesPriceLists resolves a real price rather
            # than the portal letting BC default to fabricated pricing.
            substitute = mapper.find_closest_glass_kit(gk16_pn)
            if substitute:
                part_number = substitute.part_number
                description = substitute.description
            else:
                part_number = gk16_pn
                description = f"GLASS KIT, COMMERCIAL, THERM-CLEAR, {ws['desc']}, {frame_color}"

        # Per-panel window generation: if windowPanels is provided, emit one GK16 line per panel
        window_desc = ws["desc"]  # e.g. "24" x 12""
        num_sections = self._calculate_panel_count(config.door_height)

        def _panel_label(num):
            if num == 1: return "TOP"
            elif num >= num_sections: return "BOTTOM"
            else: return f"{num} FROM TOP"

        if config.window_panels:
            parts = []
            for panel_num in sorted(config.window_panels.keys()):
                panel_info = config.window_panels[panel_num]
                qty = panel_info.get("qty", 1)
                if qty > 0:
                    label = _panel_label(panel_num)
                    parts.append(PartSelection(
                        part_number=part_number,
                        description=description,
                        quantity=qty,
                        category="commercial_window",
                        notes=f"{window_desc} THERMOPANE, {label} PANEL, {frame_color} FRAME"
                    ))
            return parts if parts else [PartSelection(
                part_number=part_number,
                description=description,
                quantity=config.window_qty or 1,
                category="commercial_window",
                notes=f"{window_desc} THERMOPANE, {_panel_label(config.window_section or 1)} PANEL, {frame_color} FRAME"
            )]

        qty = config.window_qty or 1
        label = _panel_label(config.window_section or 1)

        return [PartSelection(
            part_number=part_number,
            description=description,
            quantity=qty,
            category="commercial_window",
            notes=f"{window_desc} THERMOPANE, {label} PANEL, {frame_color} FRAME"
        )]

    # Rail part numbers by type and door height (feet)
    CHAIN_RAILS = {7: "OP19-02004-00", 8: "OP19-02005-00", 10: "OP19-02006-00"}
    BELT_RAILS = {7: "OP19-02001-00", 8: "OP19-02002-00", 10: "OP19-02003-00"}

    # Manual hand-chain hoist (commercial, motor-less doors). One per door.
    CHAIN_HOISTS = {
        "shaft": ("SP12-00084-00", "CHAIN HOIST SHAFT MOUNT 1\" BORE"),
        "wall": ("FH12-00190-00", "CHAIN HOIST WALL MOUNT 1\" BORE"),
    }

    def _get_operator_parts(self, config: DoorConfiguration) -> List[PartSelection]:
        """Get operator and accessory part numbers using real BC part numbers from catalog."""
        parts = []
        accessory_pns = set()  # Track which accessories are already included

        # Main operator
        if config.operator and config.operator != "NONE":
            from app.services.operator_service import get_operator_part_number, get_operator_display_name

            part_number = get_operator_part_number(config.operator)
            if part_number:
                display_name = get_operator_display_name(config.operator)
                parts.append(PartSelection(
                    part_number=part_number,
                    description=display_name,
                    quantity=1,
                    category="operator"
                ))

        # Operator accessories (user-selected)
        accessories = getattr(config, 'operator_accessories', None) or []
        if accessories:
            from app.services.operator_service import get_operator_part_number, get_operator_display_name

            for acc_id in accessories:
                acc_pn = get_operator_part_number(acc_id)
                if acc_pn:
                    acc_name = get_operator_display_name(acc_id)
                    parts.append(PartSelection(
                        part_number=acc_pn,
                        description=acc_name,
                        quantity=1,
                        category="operator"
                    ))
                    accessory_pns.add(acc_pn)

        # Auto-include rail for chain/belt drive operators (if not already in accessories)
        if config.operator and config.operator != "NONE":
            from app.services.operator_service import get_operator_display_name
            op_name = get_operator_display_name(config.operator).upper()

            # Determine rail size based on door HEIGHT
            door_height_ft = config.door_height // 12
            if door_height_ft <= 7:
                rail_size = 7
            elif door_height_ft <= 8:
                rail_size = 8
            else:
                rail_size = 10

            rail_pn = None
            if "CHAIN DRIVE" in op_name or "CHAIN DR" in op_name:
                rail_pn = self.CHAIN_RAILS.get(rail_size)
            elif "BELT DRIVE" in op_name or "BELT DR" in op_name:
                rail_pn = self.BELT_RAILS.get(rail_size)

            if rail_pn and rail_pn not in accessory_pns:
                rail_name = get_operator_display_name(rail_pn)
                parts.append(PartSelection(
                    part_number=rail_pn,
                    description=rail_name,
                    quantity=1,
                    category="operator"
                ))

        # Manual hand-chain hoist — commercial, motor-less doors only, one per
        # door. A chain hoist IS the manual operation method, so it's mutually
        # exclusive with an electric operator (guard against double-emit if a
        # caller sends both). Mount type is the user's choice (shaft vs wall).
        hoist_choice = (config.chain_hoist or "").lower()
        has_operator = bool(config.operator) and config.operator != "NONE"
        if (
            hoist_choice in self.CHAIN_HOISTS
            and config.door_type == "commercial"
            and not has_operator
        ):
            hoist_pn, hoist_desc = self.CHAIN_HOISTS[hoist_choice]
            parts.append(PartSelection(
                part_number=hoist_pn,
                description=hoist_desc,
                quantity=1,
                category="operator",
            ))

        return parts

    def _get_overlay_parts(self, config: DoorConfiguration, overlay: dict) -> List[PartSelection]:
        """Get wood overlay parts (OL, OG, OS) per rulebook.

        overlay dict expected keys:
            woodType: 'RG' (Red Grandis) or 'CC' (Clear Cedar)
            stamp: 'TG' (Tongue & Groove) or 'FL' (Flush)
            design: 'UD01'-'UD06'
            arched: 'A' (arched) or 'S' (straight)
            glassType: 1-3 (optional, for glass overlay)
            stain: 'DRKW'|'MHGN'|'MDOK'|'NTRL'|'SLGR' (optional)
        """
        parts = []
        sq_ft = (config.door_width / 12) * (config.door_height / 12)
        sq_ft_rounded = round(sq_ft)

        wood = overlay.get("woodType", "RG")
        stamp = overlay.get("stamp", "TG")
        design = overlay.get("design", "UD01")
        arched = overlay.get("arched", "S")

        # OL — Overlay panel
        ol_part = f"OL-{wood}{stamp}-{design}{arched}"
        parts.append(PartSelection(
            part_number=ol_part,
            description=f"OVERLAY, {wood} {'TONGUE & GROOVE' if stamp == 'TG' else 'FLUSH'}, {design}, {'ARCHED' if arched == 'A' else 'STRAIGHT'}",
            quantity=sq_ft_rounded,
            category="overlay"
        ))

        # OG — Overlay glass (if glass type specified)
        glass_type = overlay.get("glassType")
        if glass_type:
            glass_names = {1: "THERMAL CLEAR/CLEAR", 2: "THERMAL CLEAR/ACID ETCHED", 3: "THERMAL CLEAR/SUPER GREY"}
            og_part = f"OG-{wood}{stamp}-{glass_type}"
            parts.append(PartSelection(
                part_number=og_part,
                description=f"OVERLAY GLASS, {wood}, {glass_names.get(glass_type, '')}",
                quantity=sq_ft_rounded,
                category="overlay"
            ))

        # OS — Overlay stain (if stain specified)
        stain = overlay.get("stain")
        if stain:
            stain_names = {"DRKW": "DARK WALNUT", "MHGN": "MAHOGANY", "MDOK": "MED OAK", "NTRL": "NATURAL", "SLGR": "SLATE DARK GREY"}
            os_part = f"OS-{stain}"
            parts.append(PartSelection(
                part_number=os_part,
                description=f"OVERLAY STAIN, {stain_names.get(stain, stain)}",
                quantity=1,
                category="overlay"
            ))

        return parts

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
                "notes": part.notes,
                "length_adjustment_ratio": part.length_adjustment_ratio,
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


def _default_glass_pockets(door_width_inches: int) -> int:
    """Default glass pockets per AL976/V130G section based on door width.

    16' (192") = 5 pockets, scales by ~38" per pocket.
    """
    door_width_feet = door_width_inches / 12
    if door_width_feet <= 8:
        return 2
    elif door_width_feet <= 10:
        return 3
    elif door_width_feet <= 12:
        return 4
    elif door_width_feet <= 18:
        return 5
    elif door_width_feet <= 20:
        return 6
    else:
        return 7


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
        window_insert=config_dict.get("windowInsert") if config_dict.get("hasWindows", True) else None,
        window_section=config_dict.get("windowSection"),
        window_qty=config_dict.get("windowQty", 0) if config_dict.get("hasWindows", True) else 0,
        window_panels=_parse_window_panels(config_dict.get("windowPanels")),
        window_frame_color=config_dict.get("windowFrameColor", "BLACK"),
        glazing_type=config_dict.get("glazingType"),
        glass_pane_type=config_dict.get("glassPaneType"),
        glass_type=(config_dict.get("glassType") or "ANNEALED").upper(),
        glass_color=config_dict.get("glassColor"),
        track_radius=config_dict.get("trackRadius", "15"),
        track_thickness=config_dict.get("trackThickness", "2"),
        track_mount=config_dict.get("trackMount", "bracket"),
        lift_type=config_dict.get("liftType", "standard"),
        high_lift_inches=config_dict.get("highLiftInches"),
        end_cap_type=config_dict.get("endCapType", "auto"),
        hardware=config_dict.get("hardware", {}),
        operator=config_dict.get("operator"),
        operator_accessories=config_dict.get("operatorAccessories", []),
        chain_hoist=config_dict.get("chainHoist"),
        target_cycles=config_dict.get("targetCycles", config_dict.get("target_cycles", 10000)),
        shaft_preference=config_dict.get("shaftType", "auto"),
        window_size=config_dict.get("windowSize", "long"),
        glass_pockets_per_section=config_dict.get("glassPocketsPerSection") or _default_glass_pockets(config_dict.get("doorWidth", 96)),
        window_count=(len(config_dict.get("windowPositions", [])) or config_dict.get("windowCount", 0)) if config_dict.get("hasWindows", True) else 0,
        window_positions=config_dict.get("windowPositions") if config_dict.get("hasWindows", True) else None,
        spring_inventory=spring_inventory,
        include_top_seal=config_dict.get("includeTopSeal"),
        include_pusher_springs=bool(config_dict.get("includePusherSprings", False)
                                    or config_dict.get("pusherSpring", False)),
        include_man_door=bool(config_dict.get("manDoor", False)),
        man_door_spec=str(config_dict.get("manDoorSpec") or ""),
        include_interior_lock=bool(config_dict.get("interiorLock", False)),
        include_bumper_spring=bool(config_dict.get("bumperSpring", False)),
        include_track_guards=bool(config_dict.get("trackGuards", False)),
        include_exhaust_port=bool(config_dict.get("exhaustPort", False)),
    )

    parts = part_number_service.get_parts_for_configuration(config)
    return part_number_service.get_part_summary(parts)
