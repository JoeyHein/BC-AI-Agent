"""
Spring Calculator Service
Calculates torsion spring specifications using exact Canimex methodology.

Based on Canimex Cable Drum Catalog formulas:
- IPPT = Multiplier × Door Weight
- MIP per spring = (IPPT × Turns) / Spring Quantity
- Active Coils = (Spring Quantity × Divider) / IPPT
- Total Spring Length = Active Coils + Dead Coil Factor

Reference: Canimex Cable Drum Catalog DT0008-R02EN, Appendix 2 (Page 96)
"""

import os
import json
import logging
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

# ============================================================================
# DATA PATHS
# ============================================================================

# Data directory - look for spring-calculator data
# __file__ is backend/app/services/spring_calculator_service.py
SERVICES_DIR = Path(__file__).parent  # -> backend/app/services/
BACKEND_DIR = SERVICES_DIR.parent.parent  # -> backend/
BASE_DIR = BACKEND_DIR.parent  # -> bc-ai-agent/
# Priority 1: Bundled with service code (survives Docker volume mounts on /app/data)
BUNDLED_DATA = SERVICES_DIR / "spring_calc_data"
# Priority 2: Sibling spring-calculator project
SPRING_CALC_DATA = BASE_DIR.parent / "spring-calculator" / "data"
# Priority 3: backend/data/spring-calculator (may be hidden by Docker volume)
LOCAL_DATA = BACKEND_DIR / "data" / "spring-calculator"

def get_data_path() -> Path:
    """Get the path to spring calculator data files."""
    if BUNDLED_DATA.exists():
        return BUNDLED_DATA
    elif SPRING_CALC_DATA.exists():
        return SPRING_CALC_DATA
    elif LOCAL_DATA.exists():
        return LOCAL_DATA
    else:
        raise FileNotFoundError(
            f"Spring calculator data not found at {BUNDLED_DATA}, {SPRING_CALC_DATA}, or {LOCAL_DATA}"
        )


# ============================================================================
# CANIMEX APPENDIX 2 - DIVIDER AND DEAD COIL FACTOR TABLE
# Exact values from Page 96 of Canimex Cable Drum Catalog
# ============================================================================

CANIMEX_DIVIDERS = {
    # Wire Diameter -> {Coil Diameter -> Divider Value}
    0.1480: {1.75: 110.3},
    0.1620: {1.75: 172.0},
    0.1770: {1.75: 265.7},
    0.1875: {1.75: 352.5, 2.0: 312.7},  # 2.0 extrapolated for non-Canimex suppliers
    0.1920: {1.75: 395.9, 2.0: 350.8, 2.5: 285.6},
    0.2070: {1.75: 572.3, 2.0: 507.5, 2.5: 413.7},
    0.2187: {1.75: 748.9, 2.0: 664.5, 2.5: 542.3},
    0.2253: {1.75: 866.1, 2.0: 768.8, 2.5: 627.7, 2.625: 600.2, 3.375: 475.2},
    0.2344: {1.75: 1050.8, 2.0: 933.3, 2.5: 762.6, 2.625: 729.3, 3.375: 577.7},
    0.2375: {1.75: 1120.4, 2.0: 995.2, 2.5: 813.5, 2.625: 777.9, 3.375: 616.4},
    0.2437: {1.75: 1270.5, 2.0: 1129.0, 2.5: 923.2, 2.625: 883.0, 3.375: 700.0},
    0.2500: {1.75: 1438.9, 2.0: 1279.1, 2.5: 1046.5, 2.625: 1001.0, 3.375: 793.9, 3.5: 767.4, 3.625: 742.7, 3.75: 719.5},
    0.2625: {1.75: 1825.1, 2.0: 1623.4, 2.5: 1329.6, 2.625: 1272.0, 3.375: 1009.8, 3.5: 976.2, 3.625: 944.8, 3.75: 915.4},
    0.2730: {1.75: 2209.0, 2.0: 1966.0, 2.5: 1611.5, 2.625: 1542.0, 3.375: 1225.0, 3.5: 1184.4, 3.625: 1146.4, 3.75: 1110.8},
    0.2812: {1.75: 2550.9, 2.0: 2271.4, 2.5: 1863.0, 2.625: 1782.9, 3.375: 1417.2, 3.5: 1370.3, 3.625: 1326.5, 3.75: 1285.3},
    0.2830: {1.75: 2631.3, 2.0: 2343.1, 2.5: 1922.2, 2.625: 1839.5, 3.375: 1462.4, 3.5: 1414.1, 3.625: 1368.8, 3.75: 1326.4},
    0.2890: {1.75: 2913.7, 2.0: 2595.5, 2.5: 2130.2, 2.625: 2038.8, 3.375: 1621.5, 3.5: 1568.0, 3.625: 1517.9, 3.75: 1470.9, 4.5: 1240.6, 5.25: 1072.6, 5.875: 963.8, 6.0: 944.7, 7.625: 750.7},
    0.2950: {1.75: 3219.5, 2.0: 2868.8, 2.5: 2355.6, 2.625: 2254.8, 3.375: 1794.0, 3.5: 1734.9, 3.625: 1679.6, 3.75: 1627.7, 4.5: 1373.1, 5.25: 1187.4, 5.875: 1067.1, 6.0: 1045.9, 7.625: 831.3},
    0.2970: {2.5: 2434.8, 2.625: 2330.6, 3.375: 1854.6, 3.5: 1793.6, 3.625: 1736.4, 3.75: 1682.8, 4.5: 1419.7, 5.25: 1227.7, 5.875: 1103.4, 6.0: 1081.5, 7.625: 859.6},
    0.3065: {2.5: 2840.3, 2.625: 2719.2, 3.375: 2165.2, 3.5: 2094.1, 3.625: 2027.5, 3.75: 1965.1, 4.5: 1658.4, 5.25: 1434.6, 5.875: 1289.5, 6.0: 1264.0, 7.625: 1005.0},
    0.3125: {2.5: 3122.7, 2.625: 2989.8, 3.375: 2381.7, 3.5: 2303.6, 3.625: 2230.5, 3.75: 2161.9, 4.5: 1825.0, 5.25: 1578.9, 5.875: 1419.4, 6.0: 1391.3, 7.625: 1106.5},
    0.3195: {2.5: 3479.8, 2.625: 3332.1, 3.375: 2655.7, 3.5: 2568.7, 3.625: 2487.3, 3.75: 2410.9, 4.5: 2035.8, 5.25: 1761.6, 5.875: 1583.9, 6.0: 1552.5, 7.625: 1235.0},
    0.3310: {2.5: 4135.9, 2.625: 3961.0, 3.375: 3159.4, 3.5: 3056.3, 3.625: 2959.8, 3.75: 2869.1, 4.5: 2423.7, 5.25: 2098.0, 5.875: 1886.7, 6.0: 1849.4, 7.625: 1471.7},
    0.3437: {3.375: 3800.8, 3.5: 3677.2, 3.625: 3561.4, 3.75: 3452.7, 4.5: 2918.1, 5.25: 2526.8, 5.875: 2272.9, 6.0: 2228.1, 7.625: 1773.7},
    0.3625: {3.375: 4935.5, 3.5: 4775.8, 3.625: 4626.1, 3.75: 4485.5, 4.5: 3793.6, 5.25: 3286.7, 5.875: 2957.4, 6.0: 2899.3, 7.625: 2309.4},
    0.3750: {3.375: 5827.7, 3.5: 5639.7, 3.625: 5463.5, 3.75: 5297.9, 4.5: 4482.9, 5.25: 3885.1, 5.875: 3496.6, 6.0: 3428.1, 7.625: 2731.7},
    0.3875: {3.375: 6843.1, 3.5: 6623.1, 3.625: 6416.8, 3.75: 6222.9, 4.5: 5268.0, 5.25: 4567.2, 5.875: 4111.3, 6.0: 4030.9, 7.625: 3213.4},
    0.3938: {3.375: 7405.4, 3.5: 7167.7, 3.625: 6944.7, 3.75: 6735.2, 4.5: 5703.0, 5.25: 4945.2, 5.875: 4452.1, 6.0: 4365.1, 7.625: 3480.5},
    0.4062: {3.375: 8618.7, 3.5: 8342.9, 3.625: 8084.2, 3.75: 7841.1, 4.5: 6642.4, 5.25: 5761.7, 5.875: 5188.4, 6.0: 5087.1, 7.625: 4057.8},
    0.4218: {5.25: 6937.2, 5.875: 6248.7, 6.0: 6127.0, 7.625: 4889.7},
    0.4305: {5.25: 7671.0, 5.875: 6910.7, 6.0: 6776.3, 7.625: 5409.4},
    0.4375: {5.25: 8305.1, 5.875: 7482.8, 6.0: 7337.5, 7.625: 5858.6},
    0.4531: {5.875: 8893.5, 7.625: 6966.8},
    0.4615: {5.875: 9736.0, 7.625: 7629.1},
    0.4687: {5.875: 10507.7, 7.625: 8235.7},
    0.4844: {5.875: 12358.8, 7.625: 9691.8},
    0.4900: {5.875: 13078.4, 7.625: 10258.1},
    0.5000: {5.875: 14445.9, 7.625: 11334.4},
}

# Dead Coil Factors by Wire Diameter
# Factor 1: Use when coil diameter < 3.5"
# Factor 2: Use when coil diameter >= 3.5"
CANIMEX_DEAD_COIL_FACTORS = {
    0.1480: (0.74, 0.44), 0.1620: (0.81, 0.49), 0.1770: (0.89, 0.53),
    0.1875: (0.94, 0.56), 0.1920: (0.96, 0.58), 0.2070: (1.04, 0.62),
    0.2187: (1.09, 0.66), 0.2253: (1.13, 0.68), 0.2344: (1.17, 0.70),
    0.2375: (1.19, 0.71), 0.2437: (1.22, 0.73), 0.2500: (1.25, 0.75),
    0.2625: (1.31, 0.79), 0.2730: (1.37, 0.82), 0.2812: (1.41, 0.84),
    0.2830: (1.42, 0.85), 0.2890: (1.45, 0.87), 0.2950: (1.48, 0.89),
    0.2970: (1.49, 0.89), 0.3065: (1.53, 0.92), 0.3125: (1.56, 0.94),
    0.3195: (1.60, 0.96), 0.3310: (1.66, 0.99), 0.3437: (1.72, 1.03),
    0.3625: (1.81, 1.09), 0.3750: (1.88, 1.13), 0.3875: (1.94, 1.16),
    0.3938: (1.97, 1.18), 0.4062: (2.03, 1.22), 0.4218: (2.11, 1.27),
    0.4305: (2.15, 1.29), 0.4375: (2.19, 1.31), 0.4531: (2.27, 1.36),
    0.4615: (2.31, 1.38), 0.4687: (2.34, 1.41), 0.4844: (2.42, 1.45),
    0.4900: (2.45, 1.47), 0.5000: (2.50, 1.50),
}

# MIP Capacity Table (Appendix 1)
# Wire Diameter -> {Cycle Life -> MIP Capacity}
CANIMEX_MIP_CAPACITY = {
    0.1480: {10000: 83, 15000: 77, 25000: 69, 50000: 60, 100000: 51},
    0.1620: {10000: 107, 15000: 99, 25000: 89, 50000: 77, 100000: 66},
    0.1770: {10000: 137, 15000: 127, 25000: 114, 50000: 98, 100000: 85},
    0.1875: {10000: 161, 15000: 149, 25000: 134, 50000: 115, 100000: 99},
    0.1920: {10000: 172, 15000: 159, 25000: 143, 50000: 123, 100000: 106},
    0.2070: {10000: 212, 15000: 196, 25000: 177, 50000: 152, 100000: 131},
    0.2187: {10000: 247, 15000: 229, 25000: 206, 50000: 177, 100000: 153},
    0.2253: {10000: 268, 15000: 249, 25000: 224, 50000: 193, 100000: 166},
    0.2344: {10000: 298, 15000: 276, 25000: 249, 50000: 214, 100000: 184},
    0.2375: {10000: 311, 15000: 288, 25000: 260, 50000: 223, 100000: 192},
    0.2437: {10000: 337, 15000: 309, 25000: 279, 50000: 240, 100000: 206},
    0.2500: {10000: 358, 15000: 332, 25000: 300, 50000: 257, 100000: 222},
    0.2625: {10000: 411, 15000: 381, 25000: 343, 50000: 295, 100000: 254},
    0.2730: {10000: 458, 15000: 425, 25000: 383, 50000: 329, 100000: 283},
    0.2812: {10000: 506, 15000: 470, 25000: 424, 50000: 364, 100000: 313},
    0.2830: {10000: 506, 15000: 470, 25000: 424, 50000: 364, 100000: 313},
    0.2890: {10000: 537, 15000: 498, 25000: 449, 50000: 386, 100000: 332},
    0.2950: {10000: 569, 15000: 527, 25000: 476, 50000: 408, 100000: 352},
    0.2970: {10000: 580, 15000: 537, 25000: 485, 50000: 416, 100000: 358},
    0.3065: {10000: 633, 15000: 587, 25000: 529, 50000: 454, 100000: 391},
    0.3125: {10000: 668, 15000: 619, 25000: 559, 50000: 480, 100000: 413},
    0.3195: {10000: 710, 15000: 659, 25000: 594, 50000: 510, 100000: 439},
    0.3310: {10000: 784, 15000: 727, 25000: 656, 50000: 563, 100000: 485},
    0.3437: {10000: 871, 15000: 808, 25000: 729, 50000: 626, 100000: 538},
    0.3625: {10000: 1011, 15000: 937, 25000: 845, 50000: 726, 100000: 625},
    0.3750: {10000: 1111, 15000: 1030, 25000: 929, 50000: 798, 100000: 687},
    0.3875: {10000: 1200, 15000: 1113, 25000: 1004, 50000: 862, 100000: 742},
    0.3938: {10000: 1273, 15000: 1181, 25000: 1065, 50000: 914, 100000: 787},
    0.4062: {10000: 1388, 15000: 1287, 25000: 1161, 50000: 997, 100000: 858},
    0.4218: {10000: 1542, 15000: 1430, 25000: 1290, 50000: 1108, 100000: 953},
    0.4305: {10000: 1633, 15000: 1514, 25000: 1366, 50000: 1173, 100000: 1009},
    0.4375: {10000: 1708, 15000: 1584, 25000: 1428, 50000: 1227, 100000: 1056},
    0.4531: {10000: 1883, 15000: 1746, 25000: 1575, 50000: 1352, 100000: 1164},
    0.4615: {10000: 1982, 15000: 1838, 25000: 1658, 50000: 1424, 100000: 1225},
    0.4687: {10000: 2070, 15000: 1919, 25000: 1731, 50000: 1486, 100000: 1279},
    0.4844: {10000: 2269, 15000: 2104, 25000: 1898, 50000: 1630, 100000: 1403},
    0.4900: {10000: 2343, 15000: 2173, 25000: 1960, 50000: 1683, 100000: 1448},
    0.5000: {10000: 2479, 15000: 2299, 25000: 2073, 50000: 1780, 100000: 1532},
}


# ============================================================================
# DRUM MULTIPLIER TABLE LOADER
# Loads exact Canimex data from JSON files extracted from Cable Drum Catalog PDFs
# ============================================================================

def _find_drum_dir(lift_type: str) -> Optional[Path]:
    """Find drum data directory, checking bundled path first."""
    for base in [BUNDLED_DATA, LOCAL_DATA, SPRING_CALC_DATA]:
        d = base / "drums" / lift_type
        if d.exists():
            return d
    return None


def _load_standard_lift_drums() -> dict:
    """Load standard-lift drum multiplier data from JSON files."""
    data_dir = _find_drum_dir("standard-lift")
    if not data_dir:
        logger.warning(f"Standard-lift drum data directory not found")
        return {}

    drums = {}
    for json_file in sorted(data_dir.glob("*.json")):
        drum_name = json_file.stem  # e.g., "D400-96"
        with open(json_file) as f:
            raw = json.load(f)

        # Convert JSON format to internal format:
        # {height_int: {radius_int: (multi, turns)}}
        table = {}
        for height_str, radius_data in raw.get("table", {}).items():
            height = int(height_str)
            table[height] = {}
            for key, value in radius_data.items():
                if key == "lhr" or key == "pitch_factor":
                    continue  # Skip LHR and pitch for now
                radius = int(key)
                table[height][radius] = (value[0], value[1])

        drums[drum_name] = {
            "type": "standard-lift",
            "min_height": raw.get("min_height", 0),
            "max_height": raw.get("max_height", 0),
            "table": table
        }
        logger.debug(f"Loaded standard drum {drum_name}: {len(table)} heights")

    return drums


def _load_high_lift_drums() -> dict:
    """Load high-lift drum multiplier data from JSON files."""
    data_dir = _find_drum_dir("high-lift")
    if not data_dir:
        logger.warning(f"High-lift drum data directory not found")
        return {}

    drums = {}
    for json_file in sorted(data_dir.glob("*.json")):
        drum_name = json_file.stem  # e.g., "D400-54"
        with open(json_file) as f:
            raw = json.load(f)

        if raw.get("type") != "high-lift":
            continue

        # Convert JSON format to internal format:
        # {hl_int: {height_int: (multi, turns)}}
        table = {}
        for hl_str, height_data in raw.get("table", {}).items():
            hl = int(hl_str)
            table[hl] = {}
            for height_str, value in height_data.items():
                height = int(height_str)
                table[hl][height] = (value[0], value[1])

        drums[drum_name] = {
            "type": "high-lift",
            "min_height": raw.get("min_height", 0),
            "max_height": raw.get("max_height", 0),
            "max_hi_lift": raw.get("max_hi_lift", 0),
            "table": table
        }
        logger.debug(f"Loaded HL drum {drum_name}: {len(table)} HL rows")

    return drums


def _load_vertical_lift_drums() -> dict:
    """Load vertical-lift drum multiplier data from JSON files."""
    data_dir = _find_drum_dir("vertical-lift")
    if not data_dir:
        logger.warning(f"Vertical-lift drum data directory not found")
        return {}

    drums = {}
    for json_file in sorted(data_dir.glob("*.json")):
        with open(json_file) as f:
            raw = json.load(f)

        if raw.get("type") != "vertical-lift":
            continue

        # VL drums: door_calculator uses names without "D" prefix (e.g., "850-132")
        model = raw.get("model", json_file.stem)
        drum_name = model.lstrip("D") if model.startswith("D") else model

        # Convert array format to internal dict format:
        # {height_int: (multi, turns)}
        table = {}
        for entry in raw.get("multiplierTable", []):
            height = entry["doorHeight"]
            table[height] = (entry["multiplier"], entry["turns"])

        drums[drum_name] = {
            "type": "vertical-lift",
            "min_height": raw.get("minDoorHeight", 0),
            "max_height": raw.get("maxDoorHeight", 0),
            "table": table
        }
        logger.debug(f"Loaded VL drum {drum_name}: {len(table)} heights")

    return drums


# Load all drum data from JSON files
DRUM_MULTIPLIERS = _load_standard_lift_drums()
HIGH_LIFT_DRUM_MULTIPLIERS = _load_high_lift_drums()
VERTICAL_LIFT_DRUM_MULTIPLIERS = _load_vertical_lift_drums()

# Log what was loaded
_std_count = len(DRUM_MULTIPLIERS)
_hl_count = len(HIGH_LIFT_DRUM_MULTIPLIERS)
_vl_count = len(VERTICAL_LIFT_DRUM_MULTIPLIERS)
logger.info(f"Loaded drum data: {_std_count} standard, {_hl_count} high-lift, {_vl_count} vertical-lift")

# Fallback: if no JSON files found, use minimal hardcoded data
if not DRUM_MULTIPLIERS:
    logger.warning("No standard drum JSON files found, using empty tables")



# ============================================================================
# DATA CLASSES
# ============================================================================

@dataclass
class SpringResult:
    """Result of spring calculation."""
    wire_diameter: float
    coil_diameter: float
    length: float
    active_coils: float
    dead_coil_factor: float
    ippt: float
    mip_per_spring: float
    turns: float
    spring_quantity: int
    cycle_life: int
    drum_model: str
    multiplier: float
    part_number: str = ""

    def __post_init__(self):
        """Generate part number after initialization."""
        if not self.part_number:
            self.part_number = self._generate_part_number()

    def _generate_part_number(self) -> str:
        """Generate BC part number for spring."""
        # Format: SP-{wire_code}-{coil_code}-{length}
        wire_code = f"{int(self.wire_diameter * 1000):03d}"
        coil_code = f"{int(self.coil_diameter)}"
        length_code = f"{int(self.length)}"
        return f"SP-{wire_code}-{coil_code}-{length_code}"


@dataclass
class SpringOptions:
    """Multiple spring options for a door configuration."""
    door_weight: float
    door_height: int
    track_radius: int
    spring_quantity: int
    target_cycles: int
    drum_model: str
    ippt: float
    mip_required: float
    options: List[SpringResult]
    recommended: Optional[SpringResult] = None
    warnings: List[str] = None

    def __post_init__(self):
        if self.warnings is None:
            self.warnings = []


# ============================================================================
# SPRING CALCULATOR SERVICE
# ============================================================================

class SpringCalculatorService:
    """
    Spring calculator using exact Canimex methodology.
    """

    def __init__(self):
        self.dividers = CANIMEX_DIVIDERS
        self.dead_coil_factors = CANIMEX_DEAD_COIL_FACTORS
        self.mip_capacity = CANIMEX_MIP_CAPACITY
        self.drum_multipliers = DRUM_MULTIPLIERS
        self.hl_drum_multipliers = HIGH_LIFT_DRUM_MULTIPLIERS
        self.vl_drum_multipliers = VERTICAL_LIFT_DRUM_MULTIPLIERS

    def calculate_ippt(self, multiplier: float, door_weight: float) -> float:
        """
        Calculate IPPT (Inch Pounds Per Turn).
        Formula: IPPT = Multiplier × Door Weight
        """
        return multiplier * door_weight

    def calculate_mip(self, ippt: float, turns: float, spring_qty: int) -> float:
        """
        Calculate MIP (Maximum Inch Pounds) per spring.
        Formula: MIP = (IPPT × Turns) / Spring Quantity
        """
        return (ippt * turns) / spring_qty

    def calculate_active_coils(self, spring_qty: int, divider: float, ippt: float) -> float:
        """
        Calculate number of active coils.
        Formula: Active Coils = (Spring Quantity × Divider) / IPPT
        """
        if ippt == 0:
            raise ValueError("IPPT cannot be zero")
        return (spring_qty * divider) / ippt

    def calculate_spring_length(self, active_coils: float, dead_coil_factor: float) -> float:
        """
        Calculate total spring length.
        Formula: Total Length = Active Coils + Dead Coil Factor
        """
        return active_coils + dead_coil_factor

    def get_divider(self, wire_diameter: float, coil_diameter: float) -> Optional[float]:
        """Get divider value for wire/coil combination."""
        wire_dividers = self.dividers.get(wire_diameter)
        if wire_dividers is None:
            # Try to find closest wire diameter
            # Tolerance 0.005 accommodates BC inventory wire sizes (e.g. 0.272)
            # matching Canimex engineering sizes (e.g. 0.2730)
            closest_wire = min(self.dividers.keys(), key=lambda w: abs(w - wire_diameter))
            if abs(closest_wire - wire_diameter) <= 0.005:
                wire_dividers = self.dividers[closest_wire]
            else:
                return None

        divider = wire_dividers.get(coil_diameter)
        if divider is None:
            # Try to find closest coil diameter
            available_coils = list(wire_dividers.keys())
            if not available_coils:
                return None
            closest_coil = min(available_coils, key=lambda c: abs(c - coil_diameter))
            if abs(closest_coil - coil_diameter) < 0.01:
                divider = wire_dividers[closest_coil]

        return divider

    def get_dead_coil_factor(self, wire_diameter: float, coil_diameter: float) -> float:
        """Get dead coil factor for wire/coil combination."""
        factors = self.dead_coil_factors.get(wire_diameter)
        if factors is None:
            # Try closest wire
            closest_wire = min(self.dead_coil_factors.keys(), key=lambda w: abs(w - wire_diameter))
            factors = self.dead_coil_factors[closest_wire]

        # Factor 1 for coil < 3.5", Factor 2 for >= 3.5"
        return factors[0] if coil_diameter < 3.5 else factors[1]

    def get_mip_capacity(self, wire_diameter: float, cycle_life: int) -> Optional[float]:
        """Get MIP capacity for wire at given cycle life."""
        mip_table = self.mip_capacity.get(wire_diameter)
        if mip_table is None:
            # Tolerance 0.005 to match BC inventory wire sizes to Canimex sizes
            closest_wire = min(self.mip_capacity.keys(), key=lambda w: abs(w - wire_diameter))
            if abs(closest_wire - wire_diameter) <= 0.005:
                mip_table = self.mip_capacity[closest_wire]
            else:
                return None
        return mip_table.get(cycle_life)

    def select_drum(self, door_height: int, lift_type: str = "standard") -> Optional[str]:
        """Select appropriate drum model for door height."""
        # Standard drums
        for drum_model, drum_data in self.drum_multipliers.items():
            if drum_data["type"] == f"{lift_type}-lift":
                if drum_data["min_height"] <= door_height <= drum_data["max_height"]:
                    return drum_model
        # High-lift drums
        if lift_type == "high":
            for drum_model, drum_data in self.hl_drum_multipliers.items():
                if drum_data["min_height"] <= door_height <= drum_data["max_height"]:
                    return drum_model
        # Vertical-lift drums
        if lift_type == "vertical":
            for drum_model, drum_data in self.vl_drum_multipliers.items():
                if drum_data["min_height"] <= door_height <= drum_data["max_height"]:
                    return drum_model
        return None

    def get_drum_data(self, door_height: int, track_radius: int, drum_model: str = None, high_lift_inches: int = 0) -> Optional[Tuple[str, float, float]]:
        """
        Get drum multiplier and turns for door height and track radius.

        Args:
            door_height: Door height in inches
            track_radius: Track radius (12 or 15 inches)
            drum_model: Specific drum model (optional, will auto-select if None)
            high_lift_inches: Inches of high lift (0 for standard/vertical)

        Returns: (drum_model, multiplier, turns) or None
        """
        if drum_model is None:
            drum_model = self.select_drum(door_height)

        # Check standard drums
        if drum_model and drum_model in self.drum_multipliers:
            drum_data = self.drum_multipliers[drum_model]
            table = drum_data["table"]
            closest_height = min(table.keys(), key=lambda h: abs(h - door_height))
            radius_data = table[closest_height].get(track_radius)
            if radius_data is None:
                radius_data = table[closest_height].get(15)
            if radius_data is None:
                return None
            multiplier, turns = radius_data
            return (drum_model, multiplier, turns)

        # Check high-lift drums
        if drum_model and drum_model in self.hl_drum_multipliers:
            return self._get_hl_drum_data(drum_model, door_height, high_lift_inches)

        # Check vertical-lift drums
        if drum_model and drum_model in self.vl_drum_multipliers:
            return self._get_vl_drum_data(drum_model, door_height)

        return None

    def _get_hl_drum_data(self, drum_model: str, door_height: int, high_lift_inches: int) -> Optional[Tuple[str, float, float]]:
        """Look up high-lift drum multiplier: HL inches -> door height -> (mult, turns)."""
        drum_data = self.hl_drum_multipliers[drum_model]
        table = drum_data["table"]

        # Find closest high-lift row
        hl_keys = sorted(table.keys())
        closest_hl = min(hl_keys, key=lambda hl: abs(hl - high_lift_inches))

        height_table = table[closest_hl]
        if not height_table:
            return None

        # Find closest door height in that HL row
        closest_height = min(height_table.keys(), key=lambda h: abs(h - door_height))
        result = height_table[closest_height]
        if result is None:
            return None

        multiplier, turns = result
        return (drum_model, multiplier, turns)

    def _get_vl_drum_data(self, drum_model: str, door_height: int) -> Optional[Tuple[str, float, float]]:
        """Look up vertical-lift drum multiplier: door height -> (mult, turns)."""
        drum_data = self.vl_drum_multipliers[drum_model]
        table = drum_data["table"]

        closest_height = min(table.keys(), key=lambda h: abs(h - door_height))
        multiplier, turns = table[closest_height]
        return (drum_model, multiplier, turns)

    def calculate_spring(
        self,
        door_weight: float,
        door_height: int,
        track_radius: int = 15,
        spring_qty: int = 2,
        wire_diameter: float = None,
        coil_diameter: float = 2.0,
        target_cycles: int = 10000,
        drum_model: str = None,
        high_lift_inches: int = 0
    ) -> Optional[SpringResult]:
        """
        Calculate spring specifications for a door.

        Args:
            door_weight: Door weight in lbs
            door_height: Door height in inches
            track_radius: Track radius (12 or 15 inches)
            spring_qty: Number of springs (1 or 2)
            wire_diameter: Wire diameter (optional, will auto-select if None)
            coil_diameter: Coil inside diameter (default 2.0")
            target_cycles: Target cycle life (10000, 15000, 25000, 50000, 100000)
            drum_model: Specific drum model (optional, will auto-select if None)
            high_lift_inches: Inches of high lift (for HL drum lookup)

        Returns:
            SpringResult with complete spring specifications
        """
        # Get drum data
        drum_data = self.get_drum_data(door_height, track_radius, drum_model, high_lift_inches=high_lift_inches)
        if drum_data is None:
            logger.warning(f"No drum found for height {door_height}\"")
            return None

        selected_drum, multiplier, turns = drum_data

        # Calculate IPPT and MIP
        ippt = self.calculate_ippt(multiplier, door_weight)
        mip_required = self.calculate_mip(ippt, turns, spring_qty)

        # Auto-select wire diameter if not specified
        if wire_diameter is None:
            wire_diameter = self._select_wire_for_mip(mip_required, coil_diameter, target_cycles)
            if wire_diameter is None:
                # Try larger coil diameters for heavy doors
                logger.info(f"MIP {mip_required:.1f} exceeds {coil_diameter}\" coil capacity, trying larger coils...")
                result = self._select_wire_and_coil_for_mip(mip_required, target_cycles, coil_diameter)
                if result is None:
                    logger.warning(f"No wire/coil combination found for MIP {mip_required:.1f} at {target_cycles} cycles")
                    return None
                wire_diameter, coil_diameter = result
                logger.info(f"Selected {wire_diameter}\" wire with {coil_diameter}\" coil for heavy door")

        # Get divider
        divider = self.get_divider(wire_diameter, coil_diameter)
        if divider is None:
            logger.warning(f"No divider for {wire_diameter}\" wire at {coil_diameter}\" coil")
            return None

        # Calculate active coils and length
        active_coils = self.calculate_active_coils(spring_qty, divider, ippt)
        dead_coil_factor = self.get_dead_coil_factor(wire_diameter, coil_diameter)
        length = self.calculate_spring_length(active_coils, dead_coil_factor)

        return SpringResult(
            wire_diameter=wire_diameter,
            coil_diameter=coil_diameter,
            length=round(length, 2),
            active_coils=round(active_coils, 2),
            dead_coil_factor=dead_coil_factor,
            ippt=round(ippt, 2),
            mip_per_spring=round(mip_required, 2),
            turns=turns,
            spring_quantity=spring_qty,
            cycle_life=target_cycles,
            drum_model=selected_drum,
            multiplier=multiplier
        )

    def calculate_spring_options(
        self,
        door_weight: float,
        door_height: int,
        track_radius: int = 15,
        spring_qty: int = 2,
        target_cycles: int = 10000,
        drum_model: str = None,
        high_lift_inches: int = 0
    ) -> SpringOptions:
        """
        Calculate multiple spring options for a door configuration.

        Returns multiple wire/coil combinations that work for the door,
        sorted by spring length (shortest first).
        """
        # Get drum data
        drum_data = self.get_drum_data(door_height, track_radius, drum_model, high_lift_inches=high_lift_inches)
        if drum_data is None:
            return SpringOptions(
                door_weight=door_weight,
                door_height=door_height,
                track_radius=track_radius,
                spring_quantity=spring_qty,
                target_cycles=target_cycles,
                drum_model="NONE",
                ippt=0,
                mip_required=0,
                options=[],
                warnings=[f"No drum found for height {door_height}\""]
            )

        selected_drum, multiplier, turns = drum_data
        ippt = self.calculate_ippt(multiplier, door_weight)
        mip_required = self.calculate_mip(ippt, turns, spring_qty)

        options = []
        warnings = []

        # Try common coil diameters (including larger sizes for commercial doors)
        coil_diameters = [1.75, 2.0, 2.625, 3.75, 5.25, 6.0]

        for coil_diam in coil_diameters:
            # Find wire diameters that work with this coil
            for wire_diam in sorted(self.dividers.keys()):
                if coil_diam not in self.dividers.get(wire_diam, {}):
                    continue

                # Check MIP capacity
                mip_capacity = self.get_mip_capacity(wire_diam, target_cycles)
                if mip_capacity is None or mip_capacity < mip_required:
                    continue

                # Calculate spring
                result = self.calculate_spring(
                    door_weight=door_weight,
                    door_height=door_height,
                    track_radius=track_radius,
                    spring_qty=spring_qty,
                    wire_diameter=wire_diam,
                    coil_diameter=coil_diam,
                    target_cycles=target_cycles,
                    drum_model=selected_drum,
                    high_lift_inches=high_lift_inches
                )

                if result:
                    options.append(result)

        # Sort by length (shortest first)
        options.sort(key=lambda x: x.length)

        # Select recommended option (shortest spring that fits common dimensions)
        recommended = None
        for opt in options:
            # Prefer springs under 36" for ease of handling
            if opt.length <= 36:
                recommended = opt
                break

        if recommended is None and options:
            recommended = options[0]

        return SpringOptions(
            door_weight=door_weight,
            door_height=door_height,
            track_radius=track_radius,
            spring_quantity=spring_qty,
            target_cycles=target_cycles,
            drum_model=selected_drum,
            ippt=round(ippt, 2),
            mip_required=round(mip_required, 2),
            options=options,
            recommended=recommended,
            warnings=warnings
        )

    def _select_wire_for_mip(
        self,
        mip_required: float,
        coil_diameter: float,
        target_cycles: int
    ) -> Optional[float]:
        """Select smallest wire diameter that can handle required MIP."""
        for wire_diam in sorted(self.mip_capacity.keys()):
            # Check if wire/coil combination exists
            if coil_diameter not in self.dividers.get(wire_diam, {}):
                continue

            # Check MIP capacity
            mip_capacity = self.get_mip_capacity(wire_diam, target_cycles)
            if mip_capacity and mip_capacity >= mip_required:
                return wire_diam

        return None

    def _select_wire_and_coil_for_mip(
        self,
        mip_required: float,
        target_cycles: int,
        preferred_coil: float = 2.0
    ) -> Optional[Tuple[float, float]]:
        """
        Select wire diameter and coil diameter that can handle required MIP.

        For heavy doors, the standard 2" coil may not work, so we try
        progressively larger coil diameters.

        Returns: (wire_diameter, coil_diameter) or None
        """
        # Coil diameters to try, in order of preference (smaller is better for installation)
        coil_diameters_to_try = [preferred_coil, 2.0, 2.5, 2.625, 3.75, 4.5, 5.25, 5.875, 6.0, 7.625]
        # Remove duplicates while preserving order
        seen = set()
        coil_diameters_to_try = [x for x in coil_diameters_to_try if not (x in seen or seen.add(x))]

        for coil_diam in coil_diameters_to_try:
            for wire_diam in sorted(self.mip_capacity.keys()):
                # Check if wire/coil combination exists in dividers
                if coil_diam not in self.dividers.get(wire_diam, {}):
                    continue

                # Check MIP capacity
                mip_capacity = self.get_mip_capacity(wire_diam, target_cycles)
                if mip_capacity and mip_capacity >= mip_required:
                    return (wire_diam, coil_diam)

        return None


# Global instance
spring_calculator = SpringCalculatorService()


def normalize_wire_diameter(wire: float) -> float:
    """
    Normalize a wire diameter to the nearest Canimex engineering value.

    BC inventory and part numbers use rounded wire sizes (e.g. 0.272, 0.293, 0.348)
    while Canimex tables use precise values (0.2730, 0.2950, 0.3437). This function
    maps any input wire to the closest Canimex value within tolerance.

    Returns the original value if no close match is found.
    """
    if wire in CANIMEX_DIVIDERS:
        return wire
    closest = min(CANIMEX_DIVIDERS.keys(), key=lambda w: abs(w - wire))
    if abs(closest - wire) <= 0.005:
        return closest
    return wire


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def calculate_spring_for_door(
    door_weight: float,
    door_height: int,
    track_radius: int = 15,
    spring_qty: int = 2,
    target_cycles: int = 10000
) -> Optional[Dict[str, Any]]:
    """
    Calculate spring specifications for a door.

    Convenience function that returns a dictionary for API responses.
    """
    result = spring_calculator.calculate_spring(
        door_weight=door_weight,
        door_height=door_height,
        track_radius=track_radius,
        spring_qty=spring_qty,
        target_cycles=target_cycles
    )

    if result is None:
        return None

    return {
        "wire_diameter": result.wire_diameter,
        "coil_diameter": result.coil_diameter,
        "length": result.length,
        "active_coils": result.active_coils,
        "dead_coil_factor": result.dead_coil_factor,
        "ippt": result.ippt,
        "mip_per_spring": result.mip_per_spring,
        "turns": result.turns,
        "spring_quantity": result.spring_quantity,
        "cycle_life": result.cycle_life,
        "drum_model": result.drum_model,
        "multiplier": result.multiplier,
        "part_number": result.part_number
    }


def get_spring_options_for_door(
    door_weight: float,
    door_height: int,
    track_radius: int = 15,
    spring_qty: int = 2,
    target_cycles: int = 10000
) -> Dict[str, Any]:
    """
    Get multiple spring options for a door.

    Returns all viable wire/coil combinations sorted by length.
    """
    options = spring_calculator.calculate_spring_options(
        door_weight=door_weight,
        door_height=door_height,
        track_radius=track_radius,
        spring_qty=spring_qty,
        target_cycles=target_cycles
    )

    return {
        "door_weight": options.door_weight,
        "door_height": options.door_height,
        "track_radius": options.track_radius,
        "spring_quantity": options.spring_quantity,
        "target_cycles": options.target_cycles,
        "drum_model": options.drum_model,
        "ippt": options.ippt,
        "mip_required": options.mip_required,
        "options": [
            {
                "wire_diameter": opt.wire_diameter,
                "coil_diameter": opt.coil_diameter,
                "length": opt.length,
                "part_number": opt.part_number
            }
            for opt in options.options
        ],
        "recommended": {
            "wire_diameter": options.recommended.wire_diameter,
            "coil_diameter": options.recommended.coil_diameter,
            "length": options.recommended.length,
            "part_number": options.recommended.part_number
        } if options.recommended else None,
        "warnings": options.warnings
    }
