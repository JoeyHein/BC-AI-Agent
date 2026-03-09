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
    "TX450": {"18": 3.83, "21": 3.83, "24": 4.2656, "28": 5.0, "32": 5.5},
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

# Stocked spring coil diameters (inches) — these are the only coils we carry
STOCKED_COIL_DIAMETERS = [2.0, 2.625, 3.75, 6.0]

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

# Thermalex Strutting Chart (commercial doors only)
# 2D lookup: width breakpoints (rows) × height breakpoints (columns) → strut count
# Strut TYPE determined by height column:
#   Height ≤ 121" (10'-1") → 20 gauge hat struts
#   Height 145"-217" (12'-1" to 18'-1") → 16 gauge hat struts
#   Height ≥ 241" (20'-1") → Z struts
THERMALEX_STRUT_WIDTH_BREAKS = [98, 110, 122, 134, 146, 158, 170, 182, 194, 206, 218, 230, 242, 254, 266, 278, 290, 302, 314]
THERMALEX_STRUT_HEIGHT_BREAKS = [98, 121, 145, 169, 193, 217, 241, 265, 289, 313]
THERMALEX_STRUT_TABLE = [
    # 98  121  145  169  193  217  241  265  289  313   ← door height (inches)
    [  0,   0,   0,   0,   0,   0,   0,  12,  13,  14],  #  98" width (8'-2")
    [  0,   0,   0,   0,   0,   0,   0,  12,  13,  14],  # 110" (9'-2")
    [  0,   0,   0,   0,   0,   0,   0,  12,  13,  14],  # 122" (10'-2")
    [  0,   0,   0,   0,   0,   0,   0,  12,  13,  14],  # 134" (11'-2")
    [  0,   0,   0,   0,   0,   0,   0,  12,  13,  14],  # 146" (12'-2")
    [  0,   0,   0,   0,   0,   0,   0,  12,  13,  14],  # 158" (13'-2")
    [  0,   0,   0,   0,   0,   0,   0,  12,  13,  14],  # 170" (14'-2")
    [  0,   0,   0,   0,   5,   6,   7,  12,  13,  14],  # 182" (15'-2")
    [  0,   0,   0,   5,   5,   6,   7,  12,  13,  14],  # 194" (16'-2")
    [  3,   4,   4,   5,   5,   6,   7,  12,  13,  14],  # 206" (17'-2")
    [  3,   4,   4,   5,   5,   6,   7,  12,  13,  14],  # 218" (18'-2")
    [  3,   4,   4,   5,   5,   6,   7,  12,  13,  14],  # 230" (19'-2")
    [  3,   4,   4,   5,   5,   6,   7,  12,  13,  14],  # 242" (20'-2")
    [  4,   5,   6,   7,   8,   9,  10,  12,  13,  14],  # 254" (21'-2")
    [  4,   5,   6,   7,   8,   9,  10,  12,  13,  14],  # 266" (22'-2")
    [  4,   5,   6,   7,   8,   9,  10,  12,  13,  14],  # 278" (23'-2")
    [  4,   5,   6,   7,   8,   9,  10,  12,  13,  14],  # 290" (24'-2")
    [  5,   6,   7,   8,   9,  10,  11,  12,  13,  14],  # 302" (25'-2")
    [  5,   6,   7,   8,   9,  10,  11,  12,  13,  14],  # 314" (26'-2"+)
]
# Strut weight per foot by type
STRUT_WEIGHT_PER_FT = {
    "20ga": 0.79,
    "16ga": 1.05,
    "z": 0.8,
}

# Lift type configurations
# NOTE: 12" radius tracks are ONLY available in 2" track (not 3")
# Low headroom is a completely separate lift type: "2" double track lowhead"
LIFT_TYPES = {
    "standard_15": {"name": "Standard Lift 15'' Radius", "radius": 15, "type": "standard", "allowed_track_sizes": [2, 3]},
    "standard_12": {"name": "Standard Lift 12'' Radius", "radius": 12, "type": "standard", "allowed_track_sizes": [2]},
    "low_headroom": {"name": "Low Headroom (2'' Double Track)", "radius": 15, "type": "low_headroom", "allowed_track_sizes": [2]},
    "high_lift": {"name": "High Lift", "radius": 15, "type": "high", "allowed_track_sizes": [2, 3]},
    "vertical": {"name": "Vertical Lift", "radius": None, "type": "vertical", "allowed_track_sizes": [2, 3]},
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
    """Spring configuration

    For duplex springs: outer spring is on 6" coil, inner spring is on 3.75" coil,
    nested inside the outer spring. duplex_pairs indicates how many shaft positions
    have duplex springs (each pair = 1 outer + 1 inner).
    """
    quantity: int  # Total spring count (for duplex: duplex_pairs * 2)
    coil_diameter: float  # Outer coil diameter (or only coil for non-duplex)
    wire_diameter: float  # Outer wire diameter (or only wire for non-duplex)
    length: float  # Outer spring length
    cycles: int
    turns: float
    galvanized: bool = False
    is_duplex: bool = False
    inner_coil_diameter: Optional[float] = None  # 3.75" for duplex
    inner_wire_diameter: Optional[float] = None
    inner_length: Optional[float] = None
    duplex_pairs: int = 0  # Number of shaft positions with duplex (each has outer+inner)


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
    shaft_type: str = "solid"  # "tube", "solid", or "1-1/4"
    operator_length: float = None  # longer operator-side shaft (None = same as length)


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
    z_strut_lengths: Optional[List[int]] = None  # Z strut piece lengths per strut (inches), only for Z struts


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
        shaft_type: str = "auto",  # 'auto', 'single', 'split'
        spring_inventory: Optional[Dict[str, List[str]]] = None,  # stocked coil/wire combos
        high_lift_inches: Optional[int] = None,  # extra inches above door for high_lift
        door_type: str = "commercial",  # 'residential' or 'commercial'
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

        # Set correct steel gauge based on model
        # TX450-20 and TX500-20 are 20 gauge, all others are 24 gauge
        if door_model in ["TX450-20", "TX500-20"]:
            panel_config.gauge = 20
        else:
            panel_config.gauge = 24

        # 2. Calculate struts (before weight, since struts add to door weight)
        strut_count, strut_type = self._calculate_struts(
            door_model, width_inches, height_inches, panel_config.total_sections
        )

        # 3. Calculate door weight (including strut weight)
        weight = self._calculate_weight(
            door_model,
            dimensions,
            panel_config,
            track_size,
            window_type,
            window_qty,
            strut_count,
            strut_type
        )

        # 4. Calculate track configuration
        lift_config = LIFT_TYPES.get(lift_type, LIFT_TYPES["standard_15"])

        # Enforce track size constraints
        allowed_sizes = lift_config.get("allowed_track_sizes", [2, 3])
        if track_size not in allowed_sizes:
            old_track_size = track_size
            track_size = allowed_sizes[0]
            warnings.append(
                f"{lift_config['name']} only supports {'/'.join(str(s) for s in allowed_sizes)}\" track. "
                f"Changed from {old_track_size}\" to {track_size}\"."
            )

        # Compute effective height based on lift type
        lift_type_str = lift_config.get("type", "standard")
        if lift_type_str == "high" and high_lift_inches:
            effective_height = height_inches + high_lift_inches
        else:
            # Standard and vertical both use door height
            effective_height = height_inches

        track = self._calculate_track(dimensions, track_size, lift_config, effective_height=effective_height)

        # 5. Select drum
        drums = self._select_drum(height_inches, weight.total_weight, lift_config, effective_height=effective_height)
        if drums is None:
            warnings.append("No suitable drum found for door specifications")

        # 6. Calculate springs (inventory-aware, progressive scaling, duplex support)
        track_radius = lift_config.get("radius", 15)
        springs = self._calculate_springs(
            weight.total_weight,
            height_inches,
            width_inches,
            drums,
            target_cycles,
            track_radius=track_radius,
            spring_inventory=spring_inventory,
            high_lift_inches=high_lift_inches or 0,
        )

        # 7. Calculate shaft (spring count drives shaft count)
        is_residential = door_type == "residential"
        spring_count = springs.quantity if springs else 2
        shaft = self._calculate_shaft(width_inches, weight.total_weight, shaft_type, is_residential=is_residential, spring_count=spring_count)

        # 8. Calculate hardware list
        hardware = self._calculate_hardware(
            dimensions,
            panel_config,
            track_size,
            strut_count,
            strut_type,
            door_model
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
            gauge=24,  # Default to 24ga (standard), will be updated in calculate_door based on model
            end_caps=2 if double_end_caps else 1,
            heavy_duty_hinges=heavy_duty_hinges,
            note=config.get("note")
        )

    def _calculate_weight(
        self,
        door_model: str,
        dimensions: DoorDimensions,
        panel_config: PanelConfiguration,
        track_size: int,
        window_type: Optional[str],
        window_qty: int,
        strut_count: int = 0,
        strut_type: str = "16ga"
    ) -> WeightBreakdown:
        """Calculate door weight breakdown including strut weight and component hardware"""
        weight = WeightBreakdown()

        # Get model weight factors
        model_weights = self.model_weights.get(door_model, self.model_weights["TX450"])
        width_ft = dimensions.width_ft

        # Steel weight: section panels
        if panel_config.sections_21 > 0:
            weight.steel_weight += model_weights["21"] * width_ft * panel_config.sections_21
        if panel_config.sections_24 > 0:
            weight.steel_weight += model_weights["24"] * width_ft * panel_config.sections_24

        # Hardware weight: calculated from components (Thermalex methodology)
        hardware_grams = self._calculate_hardware_weight_grams(
            dimensions, panel_config, track_size, door_model
        )
        weight.hardware_weight = round(hardware_grams / 454)

        # Strut weight (using type from strutting chart)
        if strut_count > 0:
            strut_lbs_per_ft = STRUT_WEIGHT_PER_FT.get(strut_type, 1.05)
            weight.strut_weight = strut_count * width_ft * strut_lbs_per_ft

        # Window weight
        if window_type and window_qty > 0:
            window_weights = WINDOW_WEIGHTS.get(door_model, WINDOW_WEIGHTS["TX450"])
            cutout_weights = WINDOW_CUTOUT_WEIGHTS.get(door_model, WINDOW_CUTOUT_WEIGHTS["TX450"])
            gross_window_wt = window_weights.get(window_type, 0)
            cutout_wt = cutout_weights.get(window_type, 0)
            weight.glazing_weight = (gross_window_wt - cutout_wt) * window_qty

        weight.calculate_total()
        return weight

    def _calculate_hardware_weight_grams(
        self,
        dimensions: DoorDimensions,
        panel_config: PanelConfiguration,
        track_size: int,
        door_model: str,
    ) -> int:
        """
        Calculate total hardware weight in grams per Thermalex methodology.

        Hardware = hinges + top brackets + bottom brackets + L/S + S/S + step kit + tek screws.
        Calibrated against Thermalex calculator reference values:
          - 8'x10' TX450 3" track: 10903g → 24 lbs (K30)
          - 16'x8' TX450 3" track: ~9534g → 21 lbs (user-verified)

        Model: base_grams + per_section × sections + per_width_inch × width
        where base = fixed components (brackets, S/S, step kit).
        """
        sections = panel_config.total_sections

        if track_size == 3:
            # Fixed: 2×top(312) + 2×bottom(785) + 2×S/S(308) + step(605)
            base_grams = 3415
            # Per section: hinges + L/S at each section level
            per_section_grams = 1476
            # Per inch of width: tek screws and width-dependent items
            per_width_inch_grams = 1.12
        else:
            # 2" track: lighter brackets and hinges
            # Fixed: 2×top(207) + 2×bottom(785) + 2×S/S(158) + step(605)
            base_grams = 2905
            # Scale per-section by ~0.65 (lighter hinges and L/S)
            per_section_grams = 960
            per_width_inch_grams = 1.12

        total_grams = base_grams + per_section_grams * sections + per_width_inch_grams * dimensions.width
        return int(round(total_grams))

    def _calculate_track(
        self,
        dimensions: DoorDimensions,
        track_size: int,
        lift_config: Dict,
        effective_height: Optional[int] = None,
    ) -> TrackConfiguration:
        """Calculate track configuration"""

        lift_type = lift_config.get("type", "standard")
        eff_h = effective_height or dimensions.height

        # Vertical track length depends on lift type
        if lift_type == "high":
            # High lift: vertical track extends to effective height minus 8"
            vertical_length = eff_h - 8
        elif lift_type == "vertical":
            # Vertical lift: full vertical track = door height
            vertical_length = dimensions.height
        else:
            # Standard: vertical track = door height - 8"
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
        lift_config: Dict,
        effective_height: Optional[int] = None,
    ) -> Optional[DrumSelection]:
        """Select appropriate drum based on height and weight"""

        lift_type = lift_config.get("type", "standard")
        eff_h = effective_height or height_inches

        # Filter drums by lift type
        eligible_drums = [
            (name, spec) for name, spec in self.drum_table.items()
            if spec["lift"] == lift_type
        ]

        # Find smallest drum that can handle the effective height and weight
        # Sort by max_height ascending so we pick the smallest drum that fits
        for drum_name, spec in sorted(eligible_drums, key=lambda x: x[1]["max_height"]):
            if eff_h <= spec["max_height"] and door_weight <= spec["max_weight"]:
                # Select cable diameter based on weight
                cable_diam = spec["cables"][0] if door_weight < spec["max_weight"] * 0.6 else spec["cables"][1]

                # Cable length based on lift type
                if lift_type == "high":
                    cable_length = eff_h + 8
                elif lift_type == "vertical":
                    cable_length = height_inches + 8
                else:
                    cable_length = height_inches + 8

                return DrumSelection(
                    model=drum_name,
                    offset=spec["offset"],
                    cable_diameter=cable_diam,
                    cable_length=cable_length
                )

        # If no drum found, return largest available for lift type
        if eligible_drums:
            largest = max(eligible_drums, key=lambda x: x[1]["max_height"])
            if lift_type == "high":
                cable_length = eff_h + 8
            elif lift_type == "vertical":
                cable_length = height_inches + 8
            else:
                cable_length = height_inches + 8
            return DrumSelection(
                model=largest[0],
                offset=largest[1]["offset"],
                cable_diameter=largest[1]["cables"][1],
                cable_length=cable_length
            )

        return None

    def _calculate_springs(
        self,
        door_weight: float,
        height_inches: int,
        width_inches: int,
        drums: Optional[DrumSelection],
        target_cycles: int,
        track_radius: int = 15,
        spring_qty: int = 2,
        spring_inventory: Optional[Dict[str, List[str]]] = None,
        high_lift_inches: int = 0,
    ) -> Optional[SpringSelection]:
        """
        Calculate spring specifications using Canimex methodology.

        Uses the spring_calculator_service which implements exact Canimex formulas:
        - IPPT = Multiplier × Door Weight
        - MIP per spring = (IPPT × Turns) / Spring Quantity
        - Active Coils = (Spring Quantity × Divider) / IPPT
        - Total Spring Length = Active Coils + Dead Coil Factor

        Progressive scaling: tries 2 → 4 → 6 → 8 springs as door gets heavier.
        Duplex support: for narrow/tall doors, tries duplex springs (6" outer +
        3-3/4" inner nested) which provide more torque per shaft position.

        Args:
            door_weight: Door weight in lbs
            height_inches: Door height in inches
            width_inches: Door width in inches (used for duplex decision)
            drums: Drum selection (used for fallback if needed)
            target_cycles: Target cycle life (10000, 15000, 25000, 50000, 100000)
            track_radius: Track radius in inches (12 or 15, default 15)
            spring_qty: Number of springs (1 or 2, default 2)
            spring_inventory: Optional dict of stocked coil/wire combos
                e.g. {"2.0": ["0.2070", "0.2500"], "6.0": ["0.3750"]}
            high_lift_inches: Inches of high lift (for HL drum lookup)

        Returns:
            SpringSelection with complete spring specifications
        """
        if door_weight <= 0:
            logger.warning("Door weight must be greater than 0")
            return None

        drum_model = drums.model if drums else None

        if spring_inventory:
            result = self._calculate_springs_from_inventory(
                door_weight, height_inches, target_cycles,
                track_radius, spring_inventory, width_inches,
                drum_model=drum_model,
                starting_qty=spring_qty,
                high_lift_inches=high_lift_inches,
            )
            if result is not None:
                return result
            # If inventory search found nothing, fall through to unfiltered calculation
            logger.warning("No stocked spring found, falling back to unfiltered calculation")

        # Unfiltered calculation (no inventory, or inventory had no match)
        # Try stocked coil sizes in order of preference, scaling up spring count
        stocked_coils = STOCKED_COIL_DIAMETERS

        # Try requested qty first (usually 2), then scale up, then 1 as last resort
        unfiltered_progression = list(dict.fromkeys([spring_qty, 2, 4, 6, 8, 1]))
        for qty in unfiltered_progression:
            for coil_diam in stocked_coils:
                result = spring_calculator.calculate_spring(
                    door_weight=door_weight,
                    door_height=height_inches,
                    track_radius=track_radius,
                    spring_qty=qty,
                    coil_diameter=coil_diam,
                    target_cycles=target_cycles,
                    drum_model=drum_model,
                    high_lift_inches=high_lift_inches,
                )
                if result is not None:
                    return SpringSelection(
                        quantity=result.spring_quantity,
                        coil_diameter=result.coil_diameter,
                        wire_diameter=result.wire_diameter,
                        length=result.length,
                        cycles=result.cycle_life,
                        turns=result.turns,
                        galvanized=False
                    )

        logger.warning(
            f"No spring found for {door_weight} lbs, {height_inches}\" height, "
            f"{target_cycles} cycles"
        )
        return None

    def _calculate_springs_from_inventory(
        self,
        door_weight: float,
        height_inches: int,
        target_cycles: int,
        track_radius: int,
        inventory: Dict[str, List[str]],
        width_inches: int = 240,
        drum_model: Optional[str] = None,
        starting_qty: int = 2,
        high_lift_inches: int = 0,
    ) -> Optional[SpringSelection]:
        """
        Find the best spring from stocked inventory.

        Progressive scaling strategy:
        1. Try regular springs at starting_qty, then 2, 4, 6, 8
        2. Try duplex springs at 2 pairs, 4 pairs (for narrow/tall doors)
        3. Pick the most economical option:
           - Fewest total springs
           - For narrow doors (<=14'), prefer duplex over same-count regular
           - Shortest spring length

        Duplex springs: 6" outer coil with 3-3/4" inner coil nested inside,
        providing more torque per shaft position for narrow/tall doors.

        Returns:
            SpringSelection or None if nothing in inventory works
        """
        # Build list of stocked (coil, wire) pairs
        stocked_pairs = []
        for coil_str, wire_list in inventory.items():
            try:
                coil_diam = float(coil_str)
            except (ValueError, TypeError):
                continue
            for wire_str in wire_list:
                try:
                    wire_diam = float(wire_str)
                except (ValueError, TypeError):
                    continue
                stocked_pairs.append((coil_diam, wire_diam))

        if not stocked_pairs:
            return None

        # Sort by coil diameter (prefer smaller/cheaper coils first)
        stocked_pairs.sort(key=lambda x: (x[0], x[1]))

        all_candidates = []

        # Try regular springs: 1, 2, 4, 6, 8 (include 1-spring for lighter doors)
        qty_progression = list(dict.fromkeys([1, starting_qty, 2, 4, 6, 8]))  # deduplicated, order preserved
        for spring_qty in qty_progression:
            qty_candidates = []
            for coil_diam, wire_diam in stocked_pairs:
                result = spring_calculator.calculate_spring(
                    door_weight=door_weight,
                    door_height=height_inches,
                    track_radius=track_radius,
                    spring_qty=spring_qty,
                    wire_diameter=wire_diam,
                    coil_diameter=coil_diam,
                    target_cycles=target_cycles,
                    drum_model=drum_model,
                    high_lift_inches=high_lift_inches,
                )
                if result is not None:
                    # Verify MIP capacity is sufficient
                    mip_capacity = spring_calculator.get_mip_capacity(wire_diam, target_cycles)
                    if mip_capacity and mip_capacity >= result.mip_per_spring:
                        qty_candidates.append(result)

            if qty_candidates:
                # Pick best spring for this quantity: prefer smaller coil (cheaper), then shortest length
                best = min(qty_candidates, key=lambda r: (r.coil_diameter, r.length))
                all_candidates.append(SpringSelection(
                    quantity=best.spring_quantity,
                    coil_diameter=best.coil_diameter,
                    wire_diameter=best.wire_diameter,
                    length=best.length,
                    cycles=best.cycle_life,
                    turns=best.turns,
                    galvanized=False,
                    is_duplex=False,
                ))

            if spring_qty == 2 and not qty_candidates:
                logger.info(
                    f"No stocked 2-spring solution for {door_weight} lbs / "
                    f"{height_inches}\" height, trying more springs..."
                )

        # Try duplex springs: 2 pairs (4 total) and 4 pairs (8 total)
        for duplex_pairs in [2, 4]:
            duplex = self._calculate_duplex_springs(
                door_weight, height_inches, target_cycles,
                track_radius, inventory, duplex_pairs,
                drum_model=drum_model,
                high_lift_inches=high_lift_inches,
            )
            if duplex is not None:
                all_candidates.append(duplex)

        if not all_candidates:
            return None

        # Determine if this is a narrow door (duplex preferred for narrow/tall)
        is_narrow_tall = width_inches <= 168 and height_inches >= 192  # <=14' wide, >=16' tall

        # Pick best candidate
        # Max practical spring length is ~48" (4 feet) for handling/shipping
        MAX_PRACTICAL_LENGTH = 48.0

        # Single springs over 36" are impractical — penalize in sorting
        MAX_SINGLE_SPRING_LENGTH = 36.0

        def candidate_sort_key(c):
            is_reasonable = c.length <= MAX_PRACTICAL_LENGTH
            # Single spring too long? Treat like 2-spring for sorting purposes
            effective_qty = c.quantity
            if c.quantity == 1 and c.length > MAX_SINGLE_SPRING_LENGTH:
                effective_qty = 2  # Penalize long single springs

            # For narrow/tall doors prefer duplex; otherwise prefer regular
            duplex_pref = 0
            if is_narrow_tall:
                duplex_pref = 0 if c.is_duplex else 1
            else:
                duplex_pref = 1 if c.is_duplex else 0

            if is_reasonable:
                # Reasonable length: prefer fewer springs, then smaller coil, then shorter
                return (0, effective_qty, duplex_pref, c.coil_diameter, c.length)
            else:
                # Overlong: prefer shorter springs first (more practical), then fewer
                return (1, c.length, effective_qty, duplex_pref, c.coil_diameter)

        best = min(all_candidates, key=candidate_sort_key)

        logger.info(
            f"Selected {'duplex ' if best.is_duplex else ''}"
            f"spring: {best.quantity}x "
            f"{best.coil_diameter}\" coil / {best.wire_diameter}\" wire "
            f"({best.length}\" long)"
            f"{f' + inner {best.inner_coil_diameter}\"/{best.inner_wire_diameter}\"' if best.is_duplex else ''}"
            f" from inventory"
        )
        return best

    def _calculate_duplex_springs(
        self,
        door_weight: float,
        height_inches: int,
        target_cycles: int,
        track_radius: int,
        inventory: Dict[str, List[str]],
        duplex_pairs: int = 2,
        drum_model: Optional[str] = None,
        high_lift_inches: int = 0,
    ) -> Optional[SpringSelection]:
        """
        Calculate duplex spring configuration.

        Duplex springs have a 6" outer coil with a 3-3/4" inner coil nested inside.
        Each shaft position provides torque from both springs combined.

        For N duplex pairs: total_springs = N * 2 (N outer + N inner).
        The load is distributed across all springs equally using Canimex formulas.

        Args:
            door_weight: Door weight in lbs
            height_inches: Door height in inches
            target_cycles: Target cycle life
            track_radius: Track radius (12 or 15)
            inventory: Stocked coil/wire inventory
            duplex_pairs: Number of duplex pairs (2 = standard, 4 = heavy)

        Returns:
            SpringSelection with duplex fields populated, or None
        """
        total_qty = duplex_pairs * 2  # outer + inner at each position

        # Need both 6.0" and 3.75" coils in inventory
        outer_wires = inventory.get("6.0", [])
        inner_wires = inventory.get("3.75", [])
        if not outer_wires or not inner_wires:
            return None

        # Calculate what each spring needs to handle
        drum_data = spring_calculator.get_drum_data(height_inches, track_radius, drum_model, high_lift_inches=high_lift_inches)
        if drum_data is None:
            return None

        drum_model, multiplier, turns = drum_data
        ippt = spring_calculator.calculate_ippt(multiplier, door_weight)
        mip_per_spring = spring_calculator.calculate_mip(ippt, turns, total_qty)

        # Find viable outer springs (6" coil)
        outer_candidates = []
        for wire_str in outer_wires:
            try:
                wire_diam = float(wire_str)
            except (ValueError, TypeError):
                continue
            mip_cap = spring_calculator.get_mip_capacity(wire_diam, target_cycles)
            if mip_cap and mip_cap >= mip_per_spring:
                result = spring_calculator.calculate_spring(
                    door_weight=door_weight,
                    door_height=height_inches,
                    track_radius=track_radius,
                    spring_qty=total_qty,
                    wire_diameter=wire_diam,
                    coil_diameter=6.0,
                    target_cycles=target_cycles,
                    drum_model=drum_model,
                    high_lift_inches=high_lift_inches,
                )
                if result:
                    outer_candidates.append(result)

        # Find viable inner springs (3.75" coil)
        inner_candidates = []
        for wire_str in inner_wires:
            try:
                wire_diam = float(wire_str)
            except (ValueError, TypeError):
                continue
            mip_cap = spring_calculator.get_mip_capacity(wire_diam, target_cycles)
            if mip_cap and mip_cap >= mip_per_spring:
                result = spring_calculator.calculate_spring(
                    door_weight=door_weight,
                    door_height=height_inches,
                    track_radius=track_radius,
                    spring_qty=total_qty,
                    wire_diameter=wire_diam,
                    coil_diameter=3.75,
                    target_cycles=target_cycles,
                    drum_model=drum_model,
                    high_lift_inches=high_lift_inches,
                )
                if result:
                    inner_candidates.append(result)

        if not outer_candidates or not inner_candidates:
            return None

        # Pick best: smallest wire that works (shortest spring)
        best_outer = min(outer_candidates, key=lambda r: r.length)
        best_inner = min(inner_candidates, key=lambda r: r.length)

        logger.info(
            f"Duplex option: {duplex_pairs} pairs ({total_qty} total springs) - "
            f"Outer: {best_outer.wire_diameter}\" wire x 6\" coil ({best_outer.length}\") / "
            f"Inner: {best_inner.wire_diameter}\" wire x 3.75\" coil ({best_inner.length}\")"
        )

        return SpringSelection(
            quantity=total_qty,
            coil_diameter=best_outer.coil_diameter,
            wire_diameter=best_outer.wire_diameter,
            length=best_outer.length,
            cycles=target_cycles,
            turns=turns,
            galvanized=False,
            is_duplex=True,
            inner_coil_diameter=best_inner.coil_diameter,
            inner_wire_diameter=best_inner.wire_diameter,
            inner_length=best_inner.length,
            duplex_pairs=duplex_pairs,
        )

    def _calculate_shaft(
        self,
        width_inches: int,
        door_weight: float,
        shaft_type: str = "auto",
        is_residential: bool = False,
        spring_count: int = 2,
    ) -> ShaftConfiguration:
        """Calculate shaft configuration with asymmetric overhang.

        Overhang: 6" non-operator + 12" operator = door_width + 18" total.
        Shaft count N = max(ceil(spring_count / 2), width_minimum_shafts).
        For N >= 2: N-1 standard shafts + 1 longer operator shaft + N-1 couplers.

        Args:
            width_inches: Door width in inches
            door_weight: Door weight in lbs
            shaft_type: 'auto', 'single', or 'split'
            is_residential: Whether the door is residential
            spring_count: Number of springs (drives minimum shaft count)
        """

        # Shaft diameter and type based on weight and door type
        if door_weight > 2000:
            diameter = "1-1/4"
            shaft_material = "1-1/4"
        elif is_residential and door_weight <= 750:
            diameter = "1"
            shaft_material = "tube"
        else:
            diameter = "1"
            shaft_material = "solid"

        # Calculate shaft count N
        # Spring-driven: 2 springs per shaft section
        spring_driven = math.ceil(spring_count / 2)
        # Width-driven: single SH11 max 186" covers doors up to 170"
        width_minimum = 2 if width_inches > 170 else 1
        N = max(spring_driven, width_minimum)

        # Apply user overrides
        if shaft_type == "single":
            N = 1
        elif shaft_type == "split" and N < 2:
            N = 2

        if N == 1:
            # Single shaft: door_width + 18" total (6" non-op + 12" operator)
            shaft_length = width_inches + 18
            return ShaftConfiguration(
                diameter=diameter,
                length=round(shaft_length, 1),
                pieces=1,
                coupler_qty=0,
                shaft_type=shaft_material,
            )
        else:
            # Multi-shaft: total = door_width + 18"
            # N-1 standard shafts (shorter) + 1 operator shaft (longer)
            total_length = width_inches + 18
            base = total_length / N
            # Standard shafts: round DOWN to nearest 6" increment
            standard_length = math.floor(base / 6) * 6
            # Operator shaft gets the remainder
            operator_length = total_length - (standard_length * (N - 1))
            # Round operator UP to nearest 6"
            operator_length = math.ceil(operator_length / 6) * 6

            return ShaftConfiguration(
                diameter=diameter,
                length=round(standard_length, 1),
                pieces=N,
                coupler_qty=N - 1,
                shaft_type=shaft_material,
                operator_length=round(operator_length, 1),
            )

    def _calculate_struts(
        self,
        door_model: str,
        width_inches: int,
        height_inches: int,
        total_panels: int
    ) -> Tuple[int, str]:
        """
        Calculate number of struts and strut type.

        Residential doors (KANATA, CRAFT): always 1 x 20ga strut.
        Commercial doors: Thermalex Strutting Chart lookup (width × height).
        Strut type determined by height:
          ≤121" → 20ga, 145"-217" → 16ga, ≥241" → Z struts.

        Returns:
            (strut_count, strut_type) where strut_type is "20ga", "16ga", or "z"
        """
        is_residential = door_model.upper() in ["KANATA", "CRAFT"]

        if is_residential:
            return (1, "20ga")

        # Commercial: Thermalex strutting chart lookup
        import bisect

        # Find width row: largest breakpoint ≤ width (clamp to first/last)
        w_idx = bisect.bisect_right(THERMALEX_STRUT_WIDTH_BREAKS, width_inches) - 1
        w_idx = max(0, min(w_idx, len(THERMALEX_STRUT_WIDTH_BREAKS) - 1))

        # Find height column: largest breakpoint ≤ height (clamp to first/last)
        h_idx = bisect.bisect_right(THERMALEX_STRUT_HEIGHT_BREAKS, height_inches) - 1
        h_idx = max(0, min(h_idx, len(THERMALEX_STRUT_HEIGHT_BREAKS) - 1))

        strut_count = THERMALEX_STRUT_TABLE[w_idx][h_idx]

        # Determine strut type from height index
        if h_idx <= 1:      # ≤121" (10'-1")
            strut_type = "20ga"
        elif h_idx <= 5:    # 145"-217" (12'-1" to 18'-1")
            strut_type = "16ga"
        else:               # ≥241" (20'-1"+)
            strut_type = "z"

        return (strut_count, strut_type)

    def _calculate_z_strut_combo(self, width_inches: int) -> List[int]:
        """
        Calculate the best combination of Z strut pieces to span the door width.
        Z struts only come in 8' (96"), 10' (120"), and 12' (144") lengths.
        Returns list of piece lengths in inches, e.g. [120, 120, 96] for a 28' door.
        """
        target = width_inches
        best_combo = None
        best_waste = float('inf')
        best_count = float('inf')

        max_pieces = target // 96 + 1

        for n12 in range(max_pieces + 1):
            if n12 * 144 > target + 144:
                break
            for n10 in range(max_pieces + 1 - n12):
                covered = n12 * 144 + n10 * 120
                if covered > target + 144:
                    break
                if covered >= target:
                    combo = [144] * n12 + [120] * n10
                    waste = covered - target
                    count = n12 + n10
                else:
                    n8 = math.ceil((target - covered) / 96)
                    combo = [144] * n12 + [120] * n10 + [96] * n8
                    waste = (covered + n8 * 96) - target
                    count = n12 + n10 + n8

                if waste < best_waste or (waste == best_waste and count < best_count):
                    best_combo = combo
                    best_waste = waste
                    best_count = count

        return best_combo if best_combo else [144] * math.ceil(target / 144)

    def _calculate_hardware(
        self,
        dimensions: DoorDimensions,
        panel_config: PanelConfiguration,
        track_size: int,
        strut_count: int,
        strut_type: str,
        door_model: str = "TX450"
    ) -> HardwareList:
        """Calculate hardware component list"""

        hardware = HardwareList()
        sections = panel_config.total_sections

        # Hinges: (sections + 1) rows × hinges_per_row
        hinges_per_row = max(2, math.ceil(dimensions.width / 48))
        hinge_rows = sections + 1

        if panel_config.heavy_duty_hinges:
            hardware.hinges["#3 Hinge"] = hinge_rows * hinges_per_row
        else:
            hardware.hinges["#1 Hinge"] = hinge_rows * hinges_per_row

        # Brackets
        hardware.brackets[f"{track_size}'' Top Bracket"] = 2
        hardware.brackets["EZ123 Bottom Bracket"] = 2
        ls_count = (sections - 1) * 2
        hardware.brackets[f"{track_size}'' L/S"] = ls_count
        hardware.brackets[f"{track_size}'' S/S"] = 2

        # Tek screws (~2.2 per section per foot of width)
        tek_per_section = max(12, round(2.2 * dimensions.width_ft))
        hardware.bolts["Tek Screws"] = tek_per_section * sections

        # Struts
        if strut_count > 0:
            if strut_type == "z":
                z_combo = self._calculate_z_strut_combo(dimensions.width)
                hardware.z_strut_lengths = z_combo
                combo_desc = "+".join(f"{l // 12}'" for l in z_combo)
                hardware.struts[f"Z Strut ({combo_desc} per strut)"] = strut_count
            else:
                strut_label = "20ga Hat Strut" if strut_type == "20ga" else "16ga Hat Strut"
                hardware.struts[strut_label] = strut_count
            hardware.struts["Strut Clips"] = strut_count * 4

        # Other
        hardware.other["Step Kit"] = 1

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
                "is_duplex": calc.springs.is_duplex if calc.springs else False,
                "inner_coil_diameter": calc.springs.inner_coil_diameter if calc.springs else None,
                "inner_wire_diameter": calc.springs.inner_wire_diameter if calc.springs else None,
                "inner_length": calc.springs.inner_length if calc.springs else None,
                "duplex_pairs": calc.springs.duplex_pairs if calc.springs else 0,
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
                "shaft_type": calc.shaft.shaft_type if calc.shaft else None,
                "operator_length": calc.shaft.operator_length if calc.shaft else None,
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
                "other": calc.hardware.other if calc.hardware else {},
                "z_strut_lengths": calc.hardware.z_strut_lengths if calc.hardware else None,
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
        shaft_type=config.get("shaft_type", config.get("shaftType", "auto")),
        high_lift_inches=config.get("high_lift_inches", config.get("highLiftInches")),
        door_type=config.get("door_type", config.get("doorType", "commercial")),
    )

    return door_calculator.get_calculation_summary(calc)
