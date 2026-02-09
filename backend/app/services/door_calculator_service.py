"""
Door Calculator Service
Calculates door weight, panel configuration, springs, struts, drums, cables, and hardware
Based on Thermalex Door Weight Calculator Excel data

This service provides accurate calculations for:
- Door weight based on model, dimensions, and options
- Panel section configuration (21" vs 24" sections)
- Hinge layout and quantities
- Spring selection (coil, wire, cycles)
- Drum selection based on weight and lift type
- Strut quantities based on door size
- Cable lengths and diameters
- Hardware kit components
"""

import logging
import math
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum

from app.services.spring_calculator_service import (
    spring_calculator,
    SpringCalculatorService,
    SpringResult
)

logger = logging.getLogger(__name__)


# ============================================================================
# CONSTANTS FROM THERMALEX CALCULATOR
# ============================================================================

# Door Model Weight per Foot (lbs/ft) by section height
DOOR_MODEL_WEIGHTS = {
    # Commercial models
    "TX380": {"18": 3.4991, "21": 3.4991, "24": 3.933, "28": 4.5, "32": 5.0},
    "TX450": {"18": 3.83, "21": 3.83, "24": 4.38, "28": 5.0, "32": 5.5},
    "TX450-20": {"18": 5.18, "21": 5.18, "24": 5.6813, "28": 6.2, "32": 6.8},
    "TX500": {"18": 4.002, "21": 4.002, "24": 4.57, "28": 5.2, "32": 5.7},
    "TX500-20": {"18": 5.2865, "21": 5.2865, "24": 5.63, "28": 6.1, "32": 6.6},
    # Residential models (Kanata/Craft use same weights)
    "KANATA": {"18": 3.7655, "21": 4.1875, "24": 4.6392, "28": 5.1363, "32": 6.1875},
    "CRAFT": {"18": 3.7655, "21": 4.1875, "24": 4.6392, "28": 5.1363, "32": 6.1875},
}

# Multiplier factors for door models (converts to standard weight calculation)
DOOR_MODEL_MULTIPLIERS = {
    "TX380": 1.0,
    "TX450": 1.0,
    "TX450-20": 0.94,  # 20-gauge premium
    "TX500": 1.0225,
    "TX500-20": 1.0,
}

# Section height combinations table (Height in inches -> {21" sections, 24" sections, total})
SECTION_HEIGHT_TABLE = {
    63: {"21": 3, "24": 0, "total": 3},
    66: {"21": 2, "24": 1, "total": 3},
    69: {"21": 1, "24": 2, "total": 3},
    72: {"21": 0, "24": 3, "total": 3},
    75: {"21": 4, "24": 0, "total": 4, "note": "21\" to 12\" for top"},
    78: {"21": 4, "24": 0, "total": 4, "note": "21\" to 15\" for top"},
    81: {"21": 4, "24": 0, "total": 4, "note": "21\" to 18\" for top"},
    84: {"21": 4, "24": 0, "total": 4},
    87: {"21": 3, "24": 1, "total": 4},
    90: {"21": 2, "24": 2, "total": 4},
    93: {"21": 1, "24": 3, "total": 4},
    96: {"21": 0, "24": 4, "total": 4},
    99: {"21": 5, "24": 0, "total": 5, "note": "21\" to 15\" for top"},
    102: {"21": 5, "24": 0, "total": 5, "note": "21\" to 18\" for top"},
    105: {"21": 5, "24": 0, "total": 5},
    108: {"21": 4, "24": 1, "total": 5},
    111: {"21": 3, "24": 2, "total": 5},
    114: {"21": 2, "24": 3, "total": 5},
    117: {"21": 1, "24": 4, "total": 5},
    120: {"21": 0, "24": 5, "total": 5},
    123: {"21": 6, "24": 0, "total": 6, "note": "21\" to 18\" for top"},
    126: {"21": 6, "24": 0, "total": 6},
    129: {"21": 5, "24": 1, "total": 6},
    132: {"21": 4, "24": 2, "total": 6},
    135: {"21": 3, "24": 3, "total": 6},
    138: {"21": 2, "24": 4, "total": 6},
    141: {"21": 1, "24": 5, "total": 6},
    144: {"21": 0, "24": 6, "total": 6},
    147: {"21": 7, "24": 0, "total": 7},
    150: {"21": 6, "24": 1, "total": 7},
    153: {"21": 5, "24": 2, "total": 7},
    156: {"21": 4, "24": 3, "total": 7},
    159: {"21": 3, "24": 4, "total": 7},
    162: {"21": 2, "24": 5, "total": 7},
    165: {"21": 1, "24": 6, "total": 7},
    168: {"21": 0, "24": 7, "total": 7},
    171: {"21": 7, "24": 1, "total": 8},
    174: {"21": 6, "24": 2, "total": 8},
    177: {"21": 5, "24": 3, "total": 8},
    180: {"21": 4, "24": 4, "total": 8},
    183: {"21": 3, "24": 5, "total": 8},
    186: {"21": 2, "24": 6, "total": 8},
    189: {"21": 1, "24": 7, "total": 8},
    192: {"21": 0, "24": 8, "total": 8},
    195: {"21": 7, "24": 2, "total": 9},
    198: {"21": 6, "24": 3, "total": 9},
    201: {"21": 5, "24": 4, "total": 9},
    204: {"21": 4, "24": 5, "total": 9},
    207: {"21": 3, "24": 6, "total": 9},
    210: {"21": 2, "24": 7, "total": 9},
    213: {"21": 1, "24": 8, "total": 9},
    216: {"21": 0, "24": 9, "total": 9},
    219: {"21": 7, "24": 3, "total": 10},
    222: {"21": 6, "24": 4, "total": 10},
    225: {"21": 5, "24": 5, "total": 10},
    228: {"21": 4, "24": 6, "total": 10},
    231: {"21": 3, "24": 7, "total": 10},
    234: {"21": 2, "24": 8, "total": 10},
    237: {"21": 1, "24": 9, "total": 10},
    240: {"21": 0, "24": 10, "total": 10},
}

# Panel weights by model, end caps, gauge, and section height (in grams)
PANEL_WEIGHTS_GRAMS = {
    "TX380": {
        (1, 20, 21): 572, (1, 20, 24): 648,
        (1, 16, 21): None, (1, 16, 24): None,  # Not available in 16ga for TX380 single
        (2, 20, 21): 738, (2, 20, 24): 890,
        (2, 16, 21): None, (2, 16, 24): None,
    },
    "TX450": {
        (1, 20, 21): 556, (1, 20, 24): 638,
        (1, 16, 21): 894, (1, 16, 24): 1046,
        (2, 20, 21): 752, (2, 20, 24): 860,
        (2, 16, 21): 1194, (2, 16, 24): 1382,
        (3, 20, 21): 1308, (3, 20, 24): 1498,
        (3, 16, 21): 2088, (3, 16, 24): 2428,
    },
    "TX450-20": {
        (1, 20, 21): 556, (1, 20, 24): 638,
        (1, 16, 21): 894, (1, 16, 24): 1046,
        (2, 20, 21): 752, (2, 20, 24): 860,
        (2, 16, 21): 1194, (2, 16, 24): 1382,
        (3, 20, 21): 1308, (3, 20, 24): 1498,
        (3, 16, 21): 2088, (3, 16, 24): 2428,
    },
    "TX500": {
        (1, 20, 21): 581, (1, 20, 24): 665,
        (1, 16, 21): 894, (1, 16, 24): 1046,
        (2, 20, 21): 768, (2, 20, 24): 870,
        (2, 16, 21): 1280, (2, 16, 24): 1462,
        (3, 20, 21): 1349, (3, 20, 24): 1535,
        (3, 16, 21): 2174, (3, 16, 24): 2508,
    },
    "TX500-20": {
        (1, 20, 21): 581, (1, 20, 24): 665,
        (1, 16, 21): 894, (1, 16, 24): 1046,
        (2, 20, 21): 768, (2, 20, 24): 914,
        (2, 16, 21): 1280, (2, 16, 24): 1462,
        (3, 20, 21): 1349, (3, 20, 24): 1579,
        (3, 16, 21): 2174, (3, 16, 24): 2508,
    },
}

# Hinge weights (in grams)
HINGE_WEIGHTS_GRAMS = {
    "#1": 834,   # Standard hinge
    "#3": 1296,  # Heavy duty
    "#4": 1356,  # Heavy duty commercial
    "#5": 1392,  # Extra heavy
}

# Hardware component weights (lbs/ea or lbs/ft)
HARDWARE_WEIGHTS = {
    "3'' Top Bracket": {"qty_base": 4, "weight_grams": 1248},
    "EZ123 Bottom Bracket": {"qty_base": 2, "weight_grams": 1570},
    "3'' L/S": {"qty_base": 8, "weight_grams": 2904},  # Long side
    "3'' S/S": {"qty_base": 2, "weight_grams": 616},   # Short side
    "Step Kit": {"qty_base": 1, "weight_grams": 605},
    "Tek Screws": {"qty_per_panel": 27, "weight_grams_each": 6},  # 108 for 4 panels
}

# Bracket weights (lbs)
BRACKET_WEIGHTS_LBS = {
    "#5 Angle Bracket": 2,
    "#6 Angle Bracket": 2,
    "#7 Angle Bracket": 2,
}

# Aluminum profile weights (lbs/ft)
ALUMINUM_PROFILE_WEIGHTS = {
    "1.5\" Center Rail": 1.488,
    "2\" Center Rail": 2.64,
    "2\" End Rail": 3.13,
    "3\" End Rail": 3.6,
    "Double End Rail": 5.85,
    "2\" Top & Bottom Rail": 2.6875,
    "3\" Top & Bottom Rail": 3.135,
    "Double Top & Bottom Rail": 5.26,
    "Male Rail": 1.25,
    "Female Rail": 1.25,
    "Female Rail with Strut": 1.25,
    "Built-Up Rail": 2.25,
}

# Component weights (lbs/ft)
COMPONENT_WEIGHTS_LBS_FT = {
    "Bottom Retainer 1-3/8\"": 0.1824,
    "Bottom Retainer 1-3/4\"": 0.175,
    "Bottom Retainer 2\"": 0.1513,
    "Bottom Astragal Black": 0.2282,
    "Top Astragal Black": 0.1427,
    "End Cap Seal 24\"": 0.0441,
    "End Cap Seal 21\"": 0.0379,
    "T-Bar": 0.529104,
    "V-Strut": 0.8,
    "Hat Strut GA 20": 0.79,
    "Hat Strut GA 16": 1.05,
    "Lynx Hat Strut GA 16": 1.23,
}

# Window weights by model and size (lbs)
WINDOW_WEIGHTS = {
    "TX380": {"18x8": 5.25, "24x12": 7.375, "34x16": 15.5},
    "TX450": {"18x8": 5.35, "24x12": 8.125, "34x16": 15.5},
    "TX450-20": {"18x8": 5.35, "24x12": 8.125, "34x16": 15.5},
    "TX500": {"18x8": 5.5, "24x12": 8.375, "34x16": 15.5},
    "TX500-20": {"18x8": 5.5, "24x12": 8.375, "34x16": 15.5},
}

# Window cutout weight reduction (lbs)
WINDOW_CUTOUT_WEIGHTS = {
    "TX380": {"18x8": 1.76, "24x12": 2.375, "34x16": 6.5},
    "TX450": {"18x8": 2.85, "24x12": 2.968, "34x16": 5.73},
    "TX450-20": {"18x8": 2.9, "24x12": 3.13, "34x16": 6.5},
    "TX500": {"18x8": 3.0, "24x12": 3.375, "34x16": 6.5},
    "TX500-20": {"18x8": 3.2, "24x12": 3.5, "34x16": 6.5},
}

# Net window weight (window weight - cutout weight)
# Pre-calculated for convenience

# Drum selection table
# Format: {drum_model: {max_height: int, max_weight: int, offset: float, cable_diameters: [small, large]}}
DRUM_TABLE = {
    # Standard Lift Drums
    "D400-96": {"max_height": 96, "max_weight": 530, "offset": 3.375, "cables": [0.125, 0.125], "lift": "standard", "radius": 12},
    "D400-144": {"max_height": 144, "max_weight": 750, "offset": 3.375, "cables": [0.125, 0.15625], "lift": "standard", "radius": 12},
    "D525-216": {"max_height": 216, "max_weight": 1500, "offset": 4.375, "cables": [0.15625, 0.1875], "lift": "standard", "radius": 15},
    "D800-384": {"max_height": 384, "max_weight": 2200, "offset": 5.0, "cables": [0.1875, 0.25], "lift": "standard", "radius": 15},
    # High Lift Drums
    "D400-54": {"max_height": 174, "max_weight": 550, "offset": 4.375, "cables": [0.125, 0.15625], "lift": "high", "radius": 12},
    "D525-54": {"max_height": 234, "max_weight": 1000, "offset": 4.375, "cables": [0.15625, 0.1875], "lift": "high", "radius": 15},
    "D575-120": {"max_height": 264, "max_weight": 1000, "offset": 5.0, "cables": [0.15625, 0.1875], "lift": "high", "radius": 15},
    "D6375-164": {"max_height": 393, "max_weight": 1600, "offset": 6.0, "cables": [0.1875, 0.25], "lift": "high", "radius": 15},
    "D800-120": {"max_height": 384, "max_weight": 2200, "offset": 6.0, "cables": [0.1875, 0.25], "lift": "high", "radius": 15},
    # Vertical Lift Drums
    "850-132": {"max_height": 132, "max_weight": 850, "offset": 5.0, "cables": [0.15625, 0.1875], "lift": "vertical", "radius": 15},
    "1100-216": {"max_height": 216, "max_weight": 1000, "offset": 6.0, "cables": [0.15625, 0.1875], "lift": "vertical", "radius": 15},
    "1350-336": {"max_height": 336, "max_weight": 2200, "offset": 7.0, "cables": [0.1875, 0.25], "lift": "vertical", "radius": 15},
}

# Spring Maximum Inch Pound (MIP) Capacity Table
# Format: wire_diameter -> {cycles: MIP_capacity}
SPRING_MIP_TABLE = {
    0.218: {10000: 247, 15000: 229, 25000: 206, 50000: 177, 100000: 153},
    0.225: {10000: 268, 15000: 249, 25000: 224, 50000: 193, 100000: 166},
    0.234: {10000: 298, 15000: 276, 25000: 249, 50000: 214, 100000: 184},
    0.243: {10000: 337, 15000: 309, 25000: 279, 50000: 240, 100000: 206},
    0.250: {10000: 358, 15000: 332, 25000: 300, 50000: 257, 100000: 222},
    0.262: {10000: 411, 15000: 381, 25000: 343, 50000: 295, 100000: 254},
    0.273: {10000: 458, 15000: 425, 25000: 383, 50000: 329, 100000: 283},
    0.283: {10000: 506, 15000: 470, 25000: 424, 50000: 364, 100000: 313},
    0.295: {10000: 569, 15000: 527, 25000: 476, 50000: 408, 100000: 352},
    0.306: {10000: 633, 15000: 587, 25000: 529, 50000: 454, 100000: 391},
    0.312: {10000: 668, 15000: 619, 25000: 559, 50000: 480, 100000: 413},
    0.319: {10000: 710, 15000: 659, 25000: 594, 50000: 510, 100000: 439},
    0.331: {10000: 784, 15000: 727, 25000: 656, 50000: 563, 100000: 485},
    0.343: {10000: 871, 15000: 808, 25000: 729, 50000: 626, 100000: 538},
    0.362: {10000: 1011, 15000: 937, 25000: 845, 50000: 726, 100000: 625},
    0.375: {10000: 1111, 15000: 1030, 25000: 929, 50000: 798, 100000: 687},
    0.393: {10000: 1273, 15000: 1181, 25000: 1065, 50000: 914, 100000: 787},
    0.406: {10000: 1388, 15000: 1287, 25000: 1161, 50000: 997, 100000: 858},
    0.437: {10000: 1708, 15000: 1584, 25000: 1428, 50000: 1227, 100000: 1056},
}

# Spring coil diameters and their corresponding cycle counts
COIL_CYCLES = {
    2.0: {10000: 1, 15000: 2},
    2.625: {10000: 2, 15000: 2, 25000: 3, 50000: 4},
    3.75: {10000: 3, 15000: 3, 25000: 4, 50000: 4, 100000: 6},
    6.0: {25000: 4, 50000: 4, 100000: 8},
}

# Dead coil factors for spring calculation
DEAD_COIL_FACTORS = {
    # Coil diameter -> Factor 1 (< 3.5"), Factor 2 (>= 3.5")
    2.0: (1.09, 0.66),
    2.625: (1.13, 0.68),
    3.75: (1.17, 0.70),
    6.0: (1.22, 0.73),
}

# Strut schedule tables (door width x height -> number of struts)
# Format: {door_width_range: {height_range: strut_count}}
STRUT_SCHEDULE_20GA = {
    # TX380 (20ga struts)
    "TX380": {
        # (min_width, max_width): {(min_height, max_height): strut_count}
        (0, 121): {(0, 193): 0, (193, 217): 0, (217, 241): 0, (241, 265): 0, (265, 289): 12, (289, 313): 13},
        (121, 145): {(0, 193): 0, (193, 217): 0, (217, 241): 0, (241, 265): 0, (265, 289): 12, (289, 313): 13},
        (145, 169): {(0, 193): 0, (193, 217): 0, (217, 241): 0, (241, 265): 0, (265, 289): 12, (289, 313): 13},
        (169, 193): {(0, 193): 0, (193, 217): 0, (217, 241): 0, (241, 265): 0, (265, 289): 12, (289, 313): 13},
        (193, 217): {(0, 193): 0, (193, 217): 5, (217, 241): 6, (241, 265): 7, (265, 289): 12, (289, 313): 13},
        (217, 289): {(0, 193): 0, (193, 217): 5, (217, 241): 6, (241, 265): 7, (265, 289): 12, (289, 313): 14},
    },
}

STRUT_SCHEDULE_16GA = {
    # TX450/TX500 (16ga struts)
    "TX450": {
        (0, 97): {(0, 193): 0, (193, 265): 0, (265, 313): 12},
        (97, 121): {(0, 193): 0, (193, 265): 0, (265, 313): 12},
        (121, 145): {(0, 193): 0, (193, 265): 0, (265, 313): 12},
        (145, 169): {(0, 193): 0, (193, 265): 0, (265, 313): 12},
        (169, 193): {(0, 265): 0, (265, 313): 12},
        (193, 217): {(0, 193): 0, (193, 217): 5, (217, 241): 6, (241, 265): 7, (265, 289): 12, (289, 313): 14},
        (217, 241): {(0, 193): 3, (193, 217): 5, (217, 241): 6, (241, 265): 7, (265, 289): 12, (289, 313): 14},
        (241, 265): {(0, 193): 4, (193, 217): 5, (217, 241): 6, (241, 265): 7, (265, 289): 12, (289, 313): 14},
        (265, 289): {(0, 193): 4, (193, 217): 6, (217, 241): 7, (241, 265): 8, (265, 289): 12, (289, 313): 14},
        (289, 313): {(0, 193): 5, (193, 217): 7, (217, 241): 8, (241, 265): 9, (265, 289): 12, (289, 313): 14},
        (313, 337): {(0, 193): 8, (193, 217): 10, (217, 241): 12, (241, 265): 14, (265, 289): 16, (289, 313): 18},
    },
}

# Lift type configurations
LIFT_TYPES = {
    "standard_15": {"name": "Standard Lift 15'' Radius", "radius": 15, "type": "standard"},
    "standard_12": {"name": "Standard Lift 12'' Radius", "radius": 12, "type": "standard"},
    "lhr_front": {"name": "Low Head Room Front Mount", "radius": 15, "type": "low_headroom"},
    "lhr_rear": {"name": "Low Head Room Rear Mount", "radius": 15, "type": "low_headroom"},
    "high_lift": {"name": "High Lift", "radius": 15, "type": "high"},
    "vertical": {"name": "Vertical Lift", "radius": None, "type": "vertical"},
}


# ============================================================================
# DATA CLASSES
# ============================================================================

@dataclass
class DoorDimensions:
    """Door dimensions in inches"""
    width: int
    height: int

    @property
    def width_ft(self) -> float:
        return self.width / 12

    @property
    def height_ft(self) -> float:
        return self.height / 12

    @property
    def area_sqft(self) -> float:
        return (self.width * self.height) / 144


@dataclass
class PanelConfiguration:
    """Panel/section configuration"""
    total_sections: int
    sections_21: int
    sections_24: int
    gauge: int = 20  # 20 or 16
    end_caps: int = 1  # 1 = single, 2 = double
    heavy_duty_hinges: bool = False
    note: Optional[str] = None


@dataclass
class WeightBreakdown:
    """Door weight breakdown in lbs"""
    steel_weight: float = 0.0
    aluminum_weight: float = 0.0
    glazing_weight: float = 0.0
    hardware_weight: float = 0.0
    strut_weight: float = 0.0
    total_weight: float = 0.0

    def calculate_total(self):
        self.total_weight = (
            self.steel_weight +
            self.aluminum_weight +
            self.glazing_weight +
            self.hardware_weight +
            self.strut_weight
        )


@dataclass
class SpringSelection:
    """Spring configuration"""
    quantity: int
    coil_diameter: float
    wire_diameter: float
    length: float
    cycles: int
    turns: float
    galvanized: bool = False


@dataclass
class DrumSelection:
    """Drum configuration"""
    model: str
    offset: float
    cable_diameter: float
    cable_length: float


@dataclass
class ShaftConfiguration:
    """Shaft configuration"""
    diameter: str  # "1" or "1-1/4"
    length: float
    pieces: int = 2
    coupler_qty: int = 1


@dataclass
class TrackConfiguration:
    """Track configuration"""
    size: int  # 2 or 3 inches
    vertical_length: float
    horizontal_length: float
    radius: int  # 12 or 15 degrees
    lift_type: str


@dataclass
class HardwareList:
    """Hardware component list"""
    hinges: Dict[str, int] = field(default_factory=dict)
    brackets: Dict[str, int] = field(default_factory=dict)
    bolts: Dict[str, int] = field(default_factory=dict)
    struts: Dict[str, int] = field(default_factory=dict)
    other: Dict[str, int] = field(default_factory=dict)


@dataclass
class DoorCalculation:
    """Complete door calculation result"""
    dimensions: DoorDimensions
    panel_config: PanelConfiguration
    weight: WeightBreakdown
    springs: Optional[SpringSelection] = None
    drums: Optional[DrumSelection] = None
    shaft: Optional[ShaftConfiguration] = None
    track: Optional[TrackConfiguration] = None
    hardware: Optional[HardwareList] = None
    warnings: List[str] = field(default_factory=list)


# ============================================================================
# DOOR CALCULATOR SERVICE
# ============================================================================

class DoorCalculatorService:
    """
    Comprehensive door calculation service.
    Calculates all door components based on Thermalex formulas.
    """

    def __init__(self):
        self.model_weights = DOOR_MODEL_WEIGHTS
        self.section_table = SECTION_HEIGHT_TABLE
        self.drum_table = DRUM_TABLE
        self.spring_mip = SPRING_MIP_TABLE

    def calculate_door(
        self,
        door_model: str,
        width_inches: int,
        height_inches: int,
        lift_type: str = "standard_15",
        track_size: int = 3,
        window_type: Optional[str] = None,
        window_qty: int = 0,
        double_end_caps: bool = False,
        heavy_duty_hinges: bool = False,
        target_cycles: int = 10000,
    ) -> DoorCalculation:
        """
        Calculate complete door configuration.

        Args:
            door_model: TX380, TX450, TX450-20, TX500, TX500-20
            width_inches: Door width in inches
            height_inches: Door height in inches
            lift_type: standard_15, standard_12, lhr_front, lhr_rear, high_lift, vertical
            track_size: 2 or 3 inches
            window_type: "18x8", "24x12", "34x16" or None
            window_qty: Number of windows
            double_end_caps: Use double end caps/hinges
            heavy_duty_hinges: Use heavy duty hinges
            target_cycles: Spring cycle count (10000, 15000, 25000, 50000, 100000)

        Returns:
            DoorCalculation with all calculated components
        """
        dimensions = DoorDimensions(width=width_inches, height=height_inches)
        warnings = []

        # Normalize door model
        door_model = door_model.upper().replace(" ", "-")
        if door_model not in self.model_weights:
            warnings.append(f"Unknown door model '{door_model}', using TX450 defaults")
            door_model = "TX450"

        # 1. Calculate panel configuration
        panel_config = self._calculate_panel_config(
            height_inches,
            double_end_caps,
            heavy_duty_hinges
        )

        # 2. Calculate door weight
        weight = self._calculate_weight(
            door_model,
            dimensions,
            panel_config,
            window_type,
            window_qty
        )

        # 3. Calculate track configuration
        lift_config = LIFT_TYPES.get(lift_type, LIFT_TYPES["standard_15"])
        track = self._calculate_track(dimensions, track_size, lift_config)

        # 4. Select drum
        drums = self._select_drum(height_inches, weight.total_weight, lift_config)
        if drums is None:
            warnings.append("No suitable drum found for door specifications")

        # 5. Calculate springs
        springs = self._calculate_springs(
            weight.total_weight,
            height_inches,
            drums,
            target_cycles
        )

        # 6. Calculate shaft
        shaft = self._calculate_shaft(width_inches, weight.total_weight)

        # 7. Calculate struts
        strut_count = self._calculate_struts(door_model, width_inches, height_inches)

        # 8. Calculate hardware list
        hardware = self._calculate_hardware(
            dimensions,
            panel_config,
            track_size,
            strut_count
        )

        return DoorCalculation(
            dimensions=dimensions,
            panel_config=panel_config,
            weight=weight,
            springs=springs,
            drums=drums,
            shaft=shaft,
            track=track,
            hardware=hardware,
            warnings=warnings
        )

    def _calculate_panel_config(
        self,
        height_inches: int,
        double_end_caps: bool,
        heavy_duty_hinges: bool
    ) -> PanelConfiguration:
        """Calculate panel/section configuration based on door height"""

        # Find closest height in table
        closest_height = min(
            self.section_table.keys(),
            key=lambda h: abs(h - height_inches)
        )

        config = self.section_table.get(closest_height, {
            "21": 0, "24": 4, "total": 4
        })

        return PanelConfiguration(
            total_sections=config["total"],
            sections_21=config["21"],
            sections_24=config["24"],
            gauge=20,  # Default to 20ga
            end_caps=2 if double_end_caps else 1,
            heavy_duty_hinges=heavy_duty_hinges,
            note=config.get("note")
        )

    def _calculate_weight(
        self,
        door_model: str,
        dimensions: DoorDimensions,
        panel_config: PanelConfiguration,
        window_type: Optional[str],
        window_qty: int
    ) -> WeightBreakdown:
        """Calculate door weight breakdown"""
        weight = WeightBreakdown()

        # Get model weight factors
        model_weights = self.model_weights.get(door_model, self.model_weights["TX450"])

        # Calculate steel weight based on sections
        width_ft = dimensions.width_ft

        # Weight for 21" sections
        if panel_config.sections_21 > 0:
            weight_21 = model_weights["21"] * width_ft * panel_config.sections_21
            weight.steel_weight += weight_21

        # Weight for 24" sections
        if panel_config.sections_24 > 0:
            weight_24 = model_weights["24"] * width_ft * panel_config.sections_24
            weight.steel_weight += weight_24

        # Hardware weight
        # Commercial 3" hardware: 27 lbs (includes brackets, hinges, rollers, screws, step kit)
        # Residential 2" hardware: 17 lbs
        is_commercial = door_model.upper().startswith("TX")
        weight.hardware_weight = 27.0 if is_commercial else 17.0

        # Window weight
        if window_type and window_qty > 0:
            window_weights = WINDOW_WEIGHTS.get(door_model, WINDOW_WEIGHTS["TX450"])
            cutout_weights = WINDOW_CUTOUT_WEIGHTS.get(door_model, WINDOW_CUTOUT_WEIGHTS["TX450"])

            gross_window_wt = window_weights.get(window_type, 0)
            cutout_wt = cutout_weights.get(window_type, 0)
            net_window_wt = (gross_window_wt - cutout_wt) * window_qty

            weight.glazing_weight = net_window_wt

        weight.calculate_total()
        return weight

    def _calculate_track(
        self,
        dimensions: DoorDimensions,
        track_size: int,
        lift_config: Dict
    ) -> TrackConfiguration:
        """Calculate track configuration"""

        # Vertical track length = door height - 8"
        vertical_length = dimensions.height - 8

        # Horizontal track length = door width (minimum 8')
        horizontal_length = max(dimensions.width, 96)

        radius = lift_config.get("radius", 15)

        return TrackConfiguration(
            size=track_size,
            vertical_length=vertical_length,
            horizontal_length=horizontal_length,
            radius=radius,
            lift_type=lift_config["name"]
        )

    def _select_drum(
        self,
        height_inches: int,
        door_weight: float,
        lift_config: Dict
    ) -> Optional[DrumSelection]:
        """Select appropriate drum based on height and weight"""

        lift_type = lift_config.get("type", "standard")

        # Filter drums by lift type
        eligible_drums = [
            (name, spec) for name, spec in self.drum_table.items()
            if spec["lift"] == lift_type
        ]

        # Find smallest drum that can handle the height and weight
        for drum_name, spec in sorted(eligible_drums, key=lambda x: x[1]["max_height"]):
            if height_inches <= spec["max_height"] and door_weight <= spec["max_weight"]:
                # Select cable diameter based on weight
                cable_diam = spec["cables"][0] if door_weight < spec["max_weight"] * 0.6 else spec["cables"][1]

                # Calculate cable length
                if lift_type == "standard":
                    cable_length = height_inches + 8
                elif lift_type == "high":
                    cable_length = height_inches + 63  # Add high lift offset
                else:  # vertical
                    cable_length = height_inches + 143

                return DrumSelection(
                    model=drum_name,
                    offset=spec["offset"],
                    cable_diameter=cable_diam,
                    cable_length=cable_length
                )

        # If no drum found, return largest available for lift type
        if eligible_drums:
            largest = max(eligible_drums, key=lambda x: x[1]["max_height"])
            return DrumSelection(
                model=largest[0],
                offset=largest[1]["offset"],
                cable_diameter=largest[1]["cables"][1],
                cable_length=height_inches + 8
            )

        return None

    def _calculate_springs(
        self,
        door_weight: float,
        height_inches: int,
        drums: Optional[DrumSelection],
        target_cycles: int,
        track_radius: int = 15,
        spring_qty: int = 2
    ) -> Optional[SpringSelection]:
        """
        Calculate spring specifications using Canimex methodology.

        Uses the spring_calculator_service which implements exact Canimex formulas:
        - IPPT = Multiplier × Door Weight
        - MIP per spring = (IPPT × Turns) / Spring Quantity
        - Active Coils = (Spring Quantity × Divider) / IPPT
        - Total Spring Length = Active Coils + Dead Coil Factor

        Args:
            door_weight: Door weight in lbs
            height_inches: Door height in inches
            drums: Drum selection (used for fallback if needed)
            target_cycles: Target cycle life (10000, 15000, 25000, 50000, 100000)
            track_radius: Track radius in inches (12 or 15, default 15)
            spring_qty: Number of springs (1 or 2, default 2)

        Returns:
            SpringSelection with complete spring specifications
        """
        if door_weight <= 0:
            logger.warning("Door weight must be greater than 0")
            return None

        # Use the Canimex spring calculator
        result = spring_calculator.calculate_spring(
            door_weight=door_weight,
            door_height=height_inches,
            track_radius=track_radius,
            spring_qty=spring_qty,
            target_cycles=target_cycles
        )

        if result is None:
            # Fallback: try with different coil diameters
            for coil_diam in [2.0, 2.625, 3.75, 6.0]:
                result = spring_calculator.calculate_spring(
                    door_weight=door_weight,
                    door_height=height_inches,
                    track_radius=track_radius,
                    spring_qty=spring_qty,
                    coil_diameter=coil_diam,
                    target_cycles=target_cycles
                )
                if result is not None:
                    break

        if result is None:
            logger.warning(
                f"No spring found for {door_weight} lbs, {height_inches}\" height, "
                f"{target_cycles} cycles"
            )
            return None

        return SpringSelection(
            quantity=result.spring_quantity,
            coil_diameter=result.coil_diameter,
            wire_diameter=result.wire_diameter,
            length=result.length,
            cycles=result.cycle_life,
            turns=result.turns,
            galvanized=False
        )

    def _calculate_shaft(
        self,
        width_inches: int,
        door_weight: float
    ) -> ShaftConfiguration:
        """Calculate shaft configuration"""

        # Shaft diameter based on width and weight
        if width_inches <= 144 and door_weight < 600:  # Up to 12' and light
            diameter = "1"
        else:
            diameter = "1-1/4"

        # Shaft length = door width + extra for drums
        # Typically 2 pieces with coupler
        shaft_length_each = (width_inches / 2) + 6  # 6" extra each end

        return ShaftConfiguration(
            diameter=diameter,
            length=round(shaft_length_each, 1),
            pieces=2,
            coupler_qty=1
        )

    def _calculate_struts(
        self,
        door_model: str,
        width_inches: int,
        height_inches: int
    ) -> int:
        """Calculate number of struts needed"""

        # Simplified strut calculation
        # Based on door area and model

        area_sqft = (width_inches * height_inches) / 144

        if door_model in ["TX380"]:
            # 20ga struts for TX380
            if area_sqft < 80:
                return 0
            elif area_sqft < 120:
                return 2
            elif area_sqft < 180:
                return 3
            else:
                return 4
        else:
            # 16ga struts for TX450/TX500
            if width_inches <= 192:  # Up to 16'
                if height_inches <= 168:  # Up to 14'
                    return 0
                elif height_inches <= 240:
                    return 2
                else:
                    return 3
            elif width_inches <= 288:  # Up to 24'
                if height_inches <= 144:
                    return 2
                elif height_inches <= 192:
                    return 3
                else:
                    return 4
            else:  # Over 24'
                return 5

    def _calculate_hardware(
        self,
        dimensions: DoorDimensions,
        panel_config: PanelConfiguration,
        track_size: int,
        strut_count: int
    ) -> HardwareList:
        """Calculate hardware component list"""

        hardware = HardwareList()

        # Hinges (based on panel count)
        # Each panel typically has 2-4 hinges depending on width
        panels_wide = max(2, dimensions.width // 48)  # 1 hinge per ~4 feet

        if panel_config.heavy_duty_hinges:
            hardware.hinges["#3 Hinge"] = panel_config.total_sections * panels_wide
        else:
            hardware.hinges["#1 Hinge"] = panel_config.total_sections * panels_wide

        # Brackets
        hardware.brackets[f"{track_size}'' Top Bracket"] = 4
        hardware.brackets["EZ123 Bottom Bracket"] = 2
        hardware.brackets[f"{track_size}'' L/S"] = 8
        hardware.brackets[f"{track_size}'' S/S"] = 2
        hardware.brackets["#5 Angle Bracket"] = 2
        hardware.brackets["#6 Angle Bracket"] = 2
        hardware.brackets["#7 Angle Bracket"] = 2

        # Bolts and screws
        hardware.bolts["1/4 x 3/4'' Carriage Bolt"] = 27
        hardware.bolts["1/4 x 3/4'' Track Bolt"] = 12
        hardware.bolts["1/4'' Hex Washer Nut"] = 39
        hardware.bolts["5/16 x 1-5/8'' Washer Lag Screw"] = 22
        hardware.bolts["#14 x 1-1/4'' Washer Lag Screw"] = 21
        hardware.bolts["Tek Screws"] = 27 * panel_config.total_sections

        # Struts
        if strut_count > 0:
            strut_type = "16ga Hat Strut" if dimensions.width > 120 else "20ga Hat Strut"
            hardware.struts[strut_type] = strut_count
            hardware.struts["Strut Clips"] = strut_count * 4

        # Other
        hardware.other["Step Kit"] = 1
        hardware.other["Pull Rope #10"] = 5 if dimensions.width <= 144 else 0
        hardware.other["3 Slot Splice Angle"] = 2

        return hardware

    def get_calculation_summary(self, calc: DoorCalculation) -> Dict[str, Any]:
        """Get a summary dict for API response"""
        return {
            "dimensions": {
                "width_inches": calc.dimensions.width,
                "height_inches": calc.dimensions.height,
                "width_ft": calc.dimensions.width_ft,
                "height_ft": calc.dimensions.height_ft,
                "area_sqft": round(calc.dimensions.area_sqft, 2)
            },
            "panels": {
                "total_sections": calc.panel_config.total_sections,
                "sections_21_inch": calc.panel_config.sections_21,
                "sections_24_inch": calc.panel_config.sections_24,
                "gauge": calc.panel_config.gauge,
                "end_caps": calc.panel_config.end_caps,
                "heavy_duty_hinges": calc.panel_config.heavy_duty_hinges,
                "note": calc.panel_config.note
            },
            "weight": {
                "steel_lbs": round(calc.weight.steel_weight, 2),
                "aluminum_lbs": round(calc.weight.aluminum_weight, 2),
                "glazing_lbs": round(calc.weight.glazing_weight, 2),
                "hardware_lbs": round(calc.weight.hardware_weight, 2),
                "strut_lbs": round(calc.weight.strut_weight, 2),
                "total_lbs": round(calc.weight.total_weight, 2)
            },
            "springs": {
                "quantity": calc.springs.quantity if calc.springs else None,
                "coil_diameter": calc.springs.coil_diameter if calc.springs else None,
                "wire_diameter": calc.springs.wire_diameter if calc.springs else None,
                "length": calc.springs.length if calc.springs else None,
                "cycles": calc.springs.cycles if calc.springs else None,
                "turns": calc.springs.turns if calc.springs else None,
            } if calc.springs else None,
            "drum": {
                "model": calc.drums.model if calc.drums else None,
                "offset": calc.drums.offset if calc.drums else None,
                "cable_diameter": calc.drums.cable_diameter if calc.drums else None,
                "cable_length": calc.drums.cable_length if calc.drums else None,
            } if calc.drums else None,
            "shaft": {
                "diameter": calc.shaft.diameter if calc.shaft else None,
                "length_each": calc.shaft.length if calc.shaft else None,
                "pieces": calc.shaft.pieces if calc.shaft else None,
                "couplers": calc.shaft.coupler_qty if calc.shaft else None,
            } if calc.shaft else None,
            "track": {
                "size_inches": calc.track.size if calc.track else None,
                "vertical_length": calc.track.vertical_length if calc.track else None,
                "horizontal_length": calc.track.horizontal_length if calc.track else None,
                "radius": calc.track.radius if calc.track else None,
                "lift_type": calc.track.lift_type if calc.track else None,
            } if calc.track else None,
            "hardware": {
                "hinges": calc.hardware.hinges if calc.hardware else {},
                "brackets": calc.hardware.brackets if calc.hardware else {},
                "bolts": calc.hardware.bolts if calc.hardware else {},
                "struts": calc.hardware.struts if calc.hardware else {},
                "other": calc.hardware.other if calc.hardware else {}
            } if calc.hardware else None,
            "warnings": calc.warnings
        }


# Global instance
door_calculator = DoorCalculatorService()


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def calculate_door_from_config(config: Dict[str, Any]) -> Dict[str, Any]:
    """
    Calculate door specifications from a configuration dictionary.

    Args:
        config: Dictionary with door configuration:
            - door_model: str (TX380, TX450, TX450-20, TX500, TX500-20)
            - width: int (inches) or dict with {feet: int, inches: int}
            - height: int (inches) or dict with {feet: int, inches: int}
            - lift_type: str (optional, default "standard_15")
            - track_size: int (optional, default 3)
            - window_type: str (optional, "18x8", "24x12", "34x16")
            - window_qty: int (optional, default 0)
            - double_end_caps: bool (optional, default False)
            - heavy_duty_hinges: bool (optional, default False)
            - target_cycles: int (optional, default 10000)

    Returns:
        Dictionary with complete calculation results
    """
    # Parse dimensions
    if isinstance(config.get("width"), dict):
        width = config["width"].get("feet", 0) * 12 + config["width"].get("inches", 0)
    else:
        width = config.get("width", 120)

    if isinstance(config.get("height"), dict):
        height = config["height"].get("feet", 0) * 12 + config["height"].get("inches", 0)
    else:
        height = config.get("height", 84)

    calc = door_calculator.calculate_door(
        door_model=config.get("door_model", config.get("doorModel", "TX450")),
        width_inches=width,
        height_inches=height,
        lift_type=config.get("lift_type", config.get("liftType", "standard_15")),
        track_size=config.get("track_size", config.get("trackSize", 3)),
        window_type=config.get("window_type", config.get("windowType")),
        window_qty=config.get("window_qty", config.get("windowQty", 0)),
        double_end_caps=config.get("double_end_caps", config.get("doubleEndCaps", False)),
        heavy_duty_hinges=config.get("heavy_duty_hinges", config.get("heavyDutyHinges", False)),
        target_cycles=config.get("target_cycles", config.get("targetCycles", 10000)),
    )

    return door_calculator.get_calculation_summary(calc)
