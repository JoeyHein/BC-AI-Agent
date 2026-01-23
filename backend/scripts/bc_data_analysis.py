"""
BC Data Extraction and Part Number Analysis Script

Pulls all items and quotes from Business Central, analyzes part number patterns,
and creates a memory database for the door configurator.

Run with: python -m scripts.bc_data_analysis
"""

import os
import sys
import json
import re
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
from collections import defaultdict

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.integrations.bc.client import BusinessCentralClient

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Output directory for analysis results
OUTPUT_DIR = Path(__file__).parent.parent / "data" / "bc_analysis"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


class BCDataAnalyzer:
    """Extracts and analyzes BC data to understand part number patterns"""

    def __init__(self):
        self.client = BusinessCentralClient()
        self.items: List[Dict] = []
        self.quotes: List[Dict] = []
        self.quote_lines: Dict[str, List[Dict]] = {}

        # Analysis results
        self.part_number_patterns: Dict[str, Dict] = {}
        self.door_configurations: List[Dict] = []
        self.spring_patterns: Dict[str, Dict] = {}
        self.panel_patterns: Dict[str, Dict] = {}
        self.hardware_patterns: Dict[str, Dict] = {}

    def extract_all_items(self, batch_size: int = 500) -> List[Dict]:
        """Extract all items from BC with pagination"""
        logger.info("Starting item extraction...")
        all_items = []
        skip = 0

        while True:
            try:
                # BC API uses $skip for pagination
                endpoint = f"companies({self.client.company_id})/items?$top={batch_size}&$skip={skip}"
                result = self.client._make_request("GET", endpoint)
                items = result.get("value", [])

                if not items:
                    break

                all_items.extend(items)
                logger.info(f"  Fetched {len(all_items)} items so far...")
                skip += batch_size

                # Check for @odata.nextLink for more pages
                if "@odata.nextLink" not in result and len(items) < batch_size:
                    break

            except Exception as e:
                logger.error(f"Error fetching items at skip={skip}: {e}")
                break

        self.items = all_items
        logger.info(f"Total items extracted: {len(all_items)}")
        return all_items

    def extract_all_quotes(self, batch_size: int = 100, max_quotes: int = 1000) -> List[Dict]:
        """Extract sales quotes from BC with pagination"""
        logger.info("Starting quote extraction...")
        all_quotes = []
        skip = 0

        while len(all_quotes) < max_quotes:
            try:
                endpoint = f"companies({self.client.company_id})/salesQuotes?$top={batch_size}&$skip={skip}&$orderby=documentDate desc"
                result = self.client._make_request("GET", endpoint)
                quotes = result.get("value", [])

                if not quotes:
                    break

                all_quotes.extend(quotes)
                logger.info(f"  Fetched {len(all_quotes)} quotes so far...")
                skip += batch_size

                if len(quotes) < batch_size:
                    break

            except Exception as e:
                logger.error(f"Error fetching quotes at skip={skip}: {e}")
                break

        self.quotes = all_quotes[:max_quotes]
        logger.info(f"Total quotes extracted: {len(self.quotes)}")
        return self.quotes

    def extract_quote_lines(self, quote_ids: List[str] = None) -> Dict[str, List[Dict]]:
        """Extract line items for quotes"""
        if quote_ids is None:
            quote_ids = [q.get("id") for q in self.quotes if q.get("id")]

        logger.info(f"Extracting lines for {len(quote_ids)} quotes...")

        for i, quote_id in enumerate(quote_ids):
            try:
                lines = self.client.get_quote_lines(quote_id)
                self.quote_lines[quote_id] = lines

                if (i + 1) % 50 == 0:
                    logger.info(f"  Processed {i + 1}/{len(quote_ids)} quotes...")

            except Exception as e:
                logger.error(f"Error fetching lines for quote {quote_id}: {e}")

        logger.info(f"Total quote lines extracted: {sum(len(v) for v in self.quote_lines.values())}")
        return self.quote_lines

    def analyze_part_numbers(self):
        """Analyze part number patterns from items"""
        logger.info("Analyzing part number patterns...")

        # Group items by prefix
        prefix_groups = defaultdict(list)

        for item in self.items:
            number = item.get("number", "")
            display_name = item.get("displayName", "")

            # Extract prefix (e.g., PN45, SP11, PL10)
            match = re.match(r'^([A-Z]{2,3}\d{0,2})', number)
            if match:
                prefix = match.group(1)
                prefix_groups[prefix].append({
                    "number": number,
                    "displayName": display_name,
                    "unitPrice": item.get("unitPrice"),
                    "inventory": item.get("inventory"),
                    "type": item.get("type"),
                    "baseUnitOfMeasure": item.get("baseUnitOfMeasure"),
                })

        # Analyze each prefix group
        for prefix, items in prefix_groups.items():
            pattern_info = self._analyze_prefix_pattern(prefix, items)
            self.part_number_patterns[prefix] = pattern_info

        logger.info(f"Identified {len(self.part_number_patterns)} part number prefixes")

    def _analyze_prefix_pattern(self, prefix: str, items: List[Dict]) -> Dict:
        """Analyze pattern for a specific prefix"""
        # Collect all part numbers for this prefix
        numbers = [item["number"] for item in items]

        # Find common structure
        # Example: PN45-24400-0900 -> prefix-code1-code2
        structures = defaultdict(int)
        code_values = defaultdict(set)

        for num in numbers:
            # Split by dash
            parts = num.split("-")
            structure = f"{len(parts)} parts"
            structures[structure] += 1

            # Collect unique values for each position
            for i, part in enumerate(parts):
                code_values[f"part_{i}"].add(part)

        return {
            "prefix": prefix,
            "count": len(items),
            "structures": dict(structures),
            "sample_numbers": numbers[:20],  # First 20 examples
            "sample_items": items[:10],  # First 10 full items
            "code_positions": {k: list(v)[:50] for k, v in code_values.items()},
        }

    def analyze_panels(self):
        """Analyze panel part numbers (PN prefix)"""
        logger.info("Analyzing panel patterns...")

        panel_items = [
            item for item in self.items
            if item.get("number", "").startswith("PN")
        ]

        panel_analysis = {
            "total_count": len(panel_items),
            "by_series": defaultdict(list),
            "width_codes": set(),
            "height_codes": set(),
            "color_patterns": defaultdict(int),
        }

        for item in panel_items:
            number = item.get("number", "")
            parts = number.split("-")

            if len(parts) >= 3:
                # PN45-24400-0900 format
                series_code = parts[0]  # PN45

                # Determine series from prefix
                if series_code == "PN45":
                    series = "TX450"
                elif series_code == "PN46":
                    series = "TX450-DoubleEndCap"
                elif series_code == "PN50":
                    series = "TX500"
                else:
                    series = series_code

                panel_analysis["by_series"][series].append({
                    "number": number,
                    "displayName": item.get("displayName", ""),
                    "parts": parts,
                })

                # Extract width code (last part)
                if len(parts) >= 3:
                    width_code = parts[-1]
                    panel_analysis["width_codes"].add(width_code)

                # Extract middle code (height/style)
                if len(parts) >= 2:
                    height_code = parts[1]
                    panel_analysis["height_codes"].add(height_code)

        self.panel_patterns = {
            "total_count": panel_analysis["total_count"],
            "by_series": {k: v for k, v in panel_analysis["by_series"].items()},
            "width_codes": sorted(list(panel_analysis["width_codes"])),
            "height_codes": sorted(list(panel_analysis["height_codes"])),
        }

        logger.info(f"Found {len(panel_items)} panel items across {len(panel_analysis['by_series'])} series")

    def analyze_springs(self):
        """Analyze spring part numbers (SP prefix)"""
        logger.info("Analyzing spring patterns...")

        spring_items = [
            item for item in self.items
            if item.get("number", "").startswith("SP")
        ]

        spring_analysis = {
            "total_count": len(spring_items),
            "by_type": defaultdict(list),
            "wire_codes": set(),
            "wind_codes": defaultdict(int),  # 01=left, 02=right
        }

        for item in spring_items:
            number = item.get("number", "")
            display_name = item.get("displayName", "")
            parts = number.split("-")

            # Determine spring type from prefix
            prefix = parts[0] if parts else ""

            spring_analysis["by_type"][prefix].append({
                "number": number,
                "displayName": display_name,
                "parts": parts,
            })

            # Extract wire code (middle part for SP11 format)
            if len(parts) >= 2:
                wire_code = parts[1]
                spring_analysis["wire_codes"].add(wire_code)

            # Extract wind direction (last part)
            if len(parts) >= 3:
                wind_code = parts[-1]
                spring_analysis["wind_codes"][wind_code] += 1

        self.spring_patterns = {
            "total_count": spring_analysis["total_count"],
            "by_type": {k: v for k, v in spring_analysis["by_type"].items()},
            "wire_codes": sorted(list(spring_analysis["wire_codes"])),
            "wind_codes": dict(spring_analysis["wind_codes"]),
        }

        logger.info(f"Found {len(spring_items)} spring items across {len(spring_analysis['by_type'])} types")

    def analyze_hardware(self):
        """Analyze hardware part numbers (PL, HK, TR, SH prefixes)"""
        logger.info("Analyzing hardware patterns...")

        hardware_prefixes = ["PL", "HK", "TR", "SH", "FH"]
        hardware_items = [
            item for item in self.items
            if any(item.get("number", "").startswith(p) for p in hardware_prefixes)
        ]

        hardware_analysis = {
            "total_count": len(hardware_items),
            "by_prefix": defaultdict(list),
        }

        for item in hardware_items:
            number = item.get("number", "")

            # Get prefix
            for prefix in hardware_prefixes:
                if number.startswith(prefix):
                    hardware_analysis["by_prefix"][prefix].append({
                        "number": number,
                        "displayName": item.get("displayName", ""),
                    })
                    break

        self.hardware_patterns = {
            "total_count": hardware_analysis["total_count"],
            "by_prefix": {k: v for k, v in hardware_analysis["by_prefix"].items()},
        }

        logger.info(f"Found {len(hardware_items)} hardware items")

    def analyze_quote_patterns(self):
        """Analyze door configurations from quote line items"""
        logger.info("Analyzing quote patterns for door configurations...")

        door_configs = []

        for quote_id, lines in self.quote_lines.items():
            # Find the quote
            quote = next((q for q in self.quotes if q.get("id") == quote_id), {})

            # Group lines by type
            config = {
                "quote_id": quote_id,
                "quote_number": quote.get("number"),
                "customer": quote.get("customerName"),
                "date": quote.get("documentDate"),
                "panels": [],
                "springs": [],
                "hardware": [],
                "total_amount": quote.get("totalAmountIncludingTax"),
            }

            for line in lines:
                item_id = line.get("itemId")
                description = line.get("description", "")
                quantity = line.get("quantity")
                unit_price = line.get("unitPrice")

                # Categorize by description/item
                line_info = {
                    "itemId": item_id,
                    "description": description,
                    "quantity": quantity,
                    "unitPrice": unit_price,
                    "lineAmount": line.get("lineAmount"),
                }

                desc_lower = description.lower()
                if "panel" in desc_lower or "section" in desc_lower:
                    config["panels"].append(line_info)
                elif "spring" in desc_lower or "torsion" in desc_lower:
                    config["springs"].append(line_info)
                elif any(x in desc_lower for x in ["track", "hinge", "roller", "shaft", "drum", "cable"]):
                    config["hardware"].append(line_info)
                else:
                    # Categorize by part number prefix if available
                    if "PN" in description:
                        config["panels"].append(line_info)
                    elif "SP" in description:
                        config["springs"].append(line_info)
                    else:
                        config["hardware"].append(line_info)

            if config["panels"] or config["springs"]:
                door_configs.append(config)

        self.door_configurations = door_configs
        logger.info(f"Analyzed {len(door_configs)} door configurations from quotes")

    def create_memory_database(self) -> Dict:
        """Create structured memory database for door configurator"""
        logger.info("Creating memory database...")

        memory_db = {
            "metadata": {
                "created_at": datetime.now().isoformat(),
                "items_count": len(self.items),
                "quotes_count": len(self.quotes),
                "quote_lines_count": sum(len(v) for v in self.quote_lines.values()),
            },
            "part_number_rules": self._generate_part_number_rules(),
            "panels": self._generate_panel_database(),
            "springs": self._generate_spring_database(),
            "hardware": self._generate_hardware_database(),
            "door_templates": self._generate_door_templates(),
            "pricing": self._generate_pricing_data(),
        }

        return memory_db

    def _generate_part_number_rules(self) -> Dict:
        """Generate part number rules from analysis"""
        rules = {
            "panels": {
                "format": "PN{series_code}-{height_style}-{width_code}",
                "series_codes": {
                    "45": "TX450 standard",
                    "46": "TX450 double end cap",
                    "50": "TX500",
                },
                "examples": [],
            },
            "springs": {
                "format": "SP{type}-{wire_coil}-{wind}",
                "type_codes": {
                    "11": "Standard torsion spring",
                    "12": "Winding hardware",
                },
                "wind_codes": {
                    "01": "Left hand wind",
                    "02": "Right hand wind",
                },
                "examples": [],
            },
            "plastics": {
                "format": "PL{type}-{code}-{variant}",
                "type_codes": {
                    "10": "Weather stripping, seals, retainers",
                },
                "examples": [],
            },
        }

        # Add examples from analysis
        for prefix, data in self.part_number_patterns.items():
            if prefix.startswith("PN"):
                rules["panels"]["examples"].extend(data.get("sample_numbers", [])[:5])
            elif prefix.startswith("SP"):
                rules["springs"]["examples"].extend(data.get("sample_numbers", [])[:5])
            elif prefix.startswith("PL"):
                rules["plastics"]["examples"].extend(data.get("sample_numbers", [])[:5])

        return rules

    def _generate_panel_database(self) -> Dict:
        """Generate panel lookup database"""
        panels = {
            "by_series": {},
            "by_size": {},
            "all_items": [],
        }

        for series, items in self.panel_patterns.get("by_series", {}).items():
            panels["by_series"][series] = items

        # Build size index
        for item in self.items:
            number = item.get("number", "")
            if number.startswith("PN"):
                panels["all_items"].append({
                    "number": number,
                    "displayName": item.get("displayName"),
                    "unitPrice": item.get("unitPrice"),
                })

        return panels

    def _generate_spring_database(self) -> Dict:
        """Generate spring lookup database"""
        springs = {
            "by_type": {},
            "wire_sizes": {},
            "all_items": [],
        }

        for spring_type, items in self.spring_patterns.get("by_type", {}).items():
            springs["by_type"][spring_type] = items

        # Build wire size index
        for item in self.items:
            number = item.get("number", "")
            if number.startswith("SP"):
                springs["all_items"].append({
                    "number": number,
                    "displayName": item.get("displayName"),
                    "unitPrice": item.get("unitPrice"),
                })

                # Extract wire size from number if possible
                parts = number.split("-")
                if len(parts) >= 2:
                    wire_code = parts[1]
                    if wire_code not in springs["wire_sizes"]:
                        springs["wire_sizes"][wire_code] = []
                    springs["wire_sizes"][wire_code].append(number)

        return springs

    def _generate_hardware_database(self) -> Dict:
        """Generate hardware lookup database"""
        hardware = {
            "weather_stripping": [],
            "retainers": [],
            "astragal": [],
            "tracks": [],
            "shafts": [],
            "struts": [],
            "winding_hardware": [],
        }

        for item in self.items:
            number = item.get("number", "")
            display_name = item.get("displayName", "").lower()

            item_data = {
                "number": number,
                "displayName": item.get("displayName"),
                "unitPrice": item.get("unitPrice"),
            }

            if "weather" in display_name or number.startswith("PL10-072"):
                hardware["weather_stripping"].append(item_data)
            elif "retainer" in display_name or number == "PL10-00141-00":
                hardware["retainers"].append(item_data)
            elif "astragal" in display_name or number.startswith("PL10-00005"):
                hardware["astragal"].append(item_data)
            elif number.startswith("TR"):
                hardware["tracks"].append(item_data)
            elif number.startswith("SH"):
                hardware["shafts"].append(item_data)
            elif number.startswith("FH"):
                hardware["struts"].append(item_data)
            elif number.startswith("SP12"):
                hardware["winding_hardware"].append(item_data)

        return hardware

    def _generate_door_templates(self) -> List[Dict]:
        """Generate door configuration templates from quotes"""
        templates = []

        # Analyze common configurations
        config_counts = defaultdict(int)

        for config in self.door_configurations:
            # Create a key for this configuration
            panel_types = tuple(sorted(set(p.get("description", "")[:20] for p in config["panels"])))
            spring_types = tuple(sorted(set(s.get("description", "")[:20] for s in config["springs"])))

            key = (panel_types, spring_types)
            config_counts[key] += 1

        # Get most common configurations
        common_configs = sorted(config_counts.items(), key=lambda x: -x[1])[:50]

        for (panel_types, spring_types), count in common_configs:
            templates.append({
                "panel_types": list(panel_types),
                "spring_types": list(spring_types),
                "frequency": count,
            })

        return templates

    def _generate_pricing_data(self) -> Dict:
        """Generate pricing reference data"""
        pricing = {
            "panels": {},
            "springs": {},
            "hardware": {},
        }

        for item in self.items:
            number = item.get("number", "")
            price = item.get("unitPrice")

            if price is None:
                continue

            if number.startswith("PN"):
                pricing["panels"][number] = price
            elif number.startswith("SP"):
                pricing["springs"][number] = price
            elif any(number.startswith(p) for p in ["PL", "TR", "SH", "FH", "HK"]):
                pricing["hardware"][number] = price

        return pricing

    def save_results(self):
        """Save all analysis results to files"""
        logger.info("Saving results...")

        # Save raw items
        with open(OUTPUT_DIR / "bc_items.json", "w") as f:
            json.dump(self.items, f, indent=2, default=str)
        logger.info(f"  Saved {len(self.items)} items to bc_items.json")

        # Save raw quotes
        with open(OUTPUT_DIR / "bc_quotes.json", "w") as f:
            json.dump(self.quotes, f, indent=2, default=str)
        logger.info(f"  Saved {len(self.quotes)} quotes to bc_quotes.json")

        # Save quote lines
        with open(OUTPUT_DIR / "bc_quote_lines.json", "w") as f:
            json.dump(self.quote_lines, f, indent=2, default=str)
        logger.info(f"  Saved quote lines to bc_quote_lines.json")

        # Save part number patterns
        with open(OUTPUT_DIR / "part_number_patterns.json", "w") as f:
            json.dump(self.part_number_patterns, f, indent=2, default=str)
        logger.info(f"  Saved part number patterns")

        # Save panel analysis
        with open(OUTPUT_DIR / "panel_patterns.json", "w") as f:
            json.dump(self.panel_patterns, f, indent=2, default=str)
        logger.info(f"  Saved panel patterns")

        # Save spring analysis
        with open(OUTPUT_DIR / "spring_patterns.json", "w") as f:
            json.dump(self.spring_patterns, f, indent=2, default=str)
        logger.info(f"  Saved spring patterns")

        # Save hardware analysis
        with open(OUTPUT_DIR / "hardware_patterns.json", "w") as f:
            json.dump(self.hardware_patterns, f, indent=2, default=str)
        logger.info(f"  Saved hardware patterns")

        # Save door configurations
        with open(OUTPUT_DIR / "door_configurations.json", "w") as f:
            json.dump(self.door_configurations, f, indent=2, default=str)
        logger.info(f"  Saved door configurations")

        # Create and save memory database
        memory_db = self.create_memory_database()
        with open(OUTPUT_DIR / "door_memory_database.json", "w") as f:
            json.dump(memory_db, f, indent=2, default=str)
        logger.info(f"  Saved memory database")

        logger.info(f"All results saved to {OUTPUT_DIR}")

    def run_full_analysis(self):
        """Run complete analysis pipeline"""
        logger.info("=" * 60)
        logger.info("BC DATA EXTRACTION AND ANALYSIS")
        logger.info("=" * 60)

        # Extract data
        self.extract_all_items()
        self.extract_all_quotes(max_quotes=1000)  # Get up to 1000 quotes
        self.extract_quote_lines()

        # Analyze patterns
        self.analyze_part_numbers()
        self.analyze_panels()
        self.analyze_springs()
        self.analyze_hardware()
        self.analyze_quote_patterns()

        # Save results
        self.save_results()

        # Print summary
        logger.info("=" * 60)
        logger.info("ANALYSIS COMPLETE")
        logger.info("=" * 60)
        logger.info(f"Items extracted: {len(self.items)}")
        logger.info(f"Quotes extracted: {len(self.quotes)}")
        logger.info(f"Quote lines extracted: {sum(len(v) for v in self.quote_lines.values())}")
        logger.info(f"Part number prefixes identified: {len(self.part_number_patterns)}")
        logger.info(f"Panel series identified: {len(self.panel_patterns.get('by_series', {}))}")
        logger.info(f"Spring types identified: {len(self.spring_patterns.get('by_type', {}))}")
        logger.info(f"Door configurations analyzed: {len(self.door_configurations)}")
        logger.info(f"Results saved to: {OUTPUT_DIR}")


if __name__ == "__main__":
    analyzer = BCDataAnalyzer()
    analyzer.run_full_analysis()
