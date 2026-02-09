"""
Quote Generation Service
Converts parsed email data into structured quotes with pricing

Uses the door configurator / part number service to get actual BC part numbers
instead of placeholder codes.
"""

import logging
from typing import List, Dict, Any, Optional
from decimal import Decimal
from datetime import datetime
from sqlalchemy.orm import Session

from app.db.models import QuoteRequest, QuoteItem, PricingRule, BCCustomer
from app.services.spring_calculator_service import spring_calculator
from app.services.part_number_service import (
    part_number_service,
    DoorConfiguration,
    PartSelection,
)

logger = logging.getLogger(__name__)


class QuoteGenerationService:
    """Service for generating quotes from parsed email data"""

    def __init__(self, db: Session):
        self.db = db

    def generate_quote(self, quote_request_id: int) -> Dict[str, Any]:
        """
        Generate a complete quote with line items and pricing

        Args:
            quote_request_id: ID of the quote request to generate quote for

        Returns:
            Dict with quote summary and line items
        """
        quote_request = self.db.query(QuoteRequest).filter(
            QuoteRequest.id == quote_request_id
        ).first()

        if not quote_request:
            raise ValueError(f"Quote request {quote_request_id} not found")

        if not quote_request.parsed_data:
            raise ValueError(f"Quote request {quote_request_id} has no parsed data")

        # Delete existing quote items if regenerating
        self.db.query(QuoteItem).filter(
            QuoteItem.quote_request_id == quote_request_id
        ).delete()

        parsed_data = quote_request.parsed_data
        line_items = []

        # Get customer for pricing tier
        customer = self._get_or_create_customer(parsed_data.get("customer", {}))

        # Generate door line items
        doors = parsed_data.get("doors", [])
        for door_spec in doors:
            door_items = self._generate_door_items(door_spec, customer)
            line_items.extend(door_items)

        # Calculate shipping/delivery if needed
        project = parsed_data.get("project", {})
        if project.get("delivery_date"):
            shipping_item = self._generate_shipping_item(line_items, project)
            if shipping_item:
                line_items.append(shipping_item)

        # Save line items to database
        for item_data in line_items:
            quote_item = QuoteItem(
                quote_request_id=quote_request_id,
                **item_data
            )
            self.db.add(quote_item)

        self.db.commit()

        # Calculate totals
        subtotal = Decimal(str(sum(item.get("total_price", 0) for item in line_items)))
        tax = subtotal * Decimal("0.05")  # 5% GST (example)
        total = subtotal + tax

        return {
            "quote_request_id": quote_request_id,
            "customer": {
                "name": quote_request.customer_name,
                "email": quote_request.contact_email,
                "phone": quote_request.contact_phone,
            },
            "line_items": line_items,
            "subtotal": float(subtotal),
            "tax": float(tax),
            "total": float(total),
            "created_at": datetime.utcnow().isoformat()
        }

    def _generate_door_items(self, door_spec: Dict[str, Any], customer: Optional[BCCustomer]) -> List[Dict[str, Any]]:
        """
        Generate line items for a door specification using the door configurator
        to get actual BC part numbers.

        Args:
            door_spec: Door specifications from AI-parsed email data
            customer: BC customer for pricing tier

        Returns:
            List of line item dicts with actual BC part numbers
        """
        items = []

        # Extract door specs from AI-parsed data
        model = door_spec.get("model")
        quantity = door_spec.get("quantity", 1) or 1
        width_ft = door_spec.get("width_ft", 0) or 0
        width_in = door_spec.get("width_in", 0) or 0
        height_ft = door_spec.get("height_ft", 0) or 0
        height_in = door_spec.get("height_in", 0) or 0
        color = door_spec.get("color")
        glazing = door_spec.get("glazing")
        track_type = door_spec.get("track_type", "2")

        if not model:
            logger.warning("Door spec missing model, skipping")
            return items

        # Convert dimensions to total inches
        door_width_inches = (width_ft * 12) + width_in
        door_height_inches = (height_ft * 12) + height_in

        # Default to common sizes if dimensions missing
        if door_width_inches == 0:
            door_width_inches = 96  # 8' default
            logger.warning(f"Door width missing, defaulting to {door_width_inches}\" (8')")
        if door_height_inches == 0:
            door_height_inches = 84  # 7' default
            logger.warning(f"Door height missing, defaulting to {door_height_inches}\" (7')")

        # Map AI-parsed model names to door series
        door_series = self._map_model_to_series(model)
        door_type = self._determine_door_type(model, door_width_inches, door_height_inches)

        # Map color to standard color code
        panel_color = self._map_color_to_code(color, door_series)

        # Create DoorConfiguration for the part number service
        try:
            config = DoorConfiguration(
                door_type=door_type,
                door_series=door_series,
                door_width=door_width_inches,
                door_height=door_height_inches,
                door_count=1,  # Parts are per-door, we multiply by quantity later
                panel_color=panel_color,
                panel_design="FLUSH" if door_type == "commercial" else "SHXL",  # Default designs
                window_insert=None,  # TODO: parse from glazing
                window_section=None,
                glazing_type=glazing.upper() if glazing else None,
                track_radius="15" if track_type == "2" else "12",
                track_thickness=track_type or "2",
                hardware={
                    "tracks": True,
                    "springs": True,
                    "shafts": True,
                    "struts": True,
                    "hardwareKits": True,
                    "weatherStripping": True,
                    "bottomRetainer": True,
                },
                operator=None,
                target_cycles=10000,
                spring_quantity=2,
            )

            # Get parts from the part number service
            parts: List[PartSelection] = part_number_service.get_parts_for_configuration(config)

            logger.info(f"Got {len(parts)} parts for door: {model} {door_width_inches}\"x{door_height_inches}\"")

            # Convert parts to quote line items
            size = f"{width_ft}'{width_in}\" x {height_ft}'{height_in}\""

            for part in parts:
                # Get pricing context
                context = {
                    "model": model,
                    "quantity": quantity,
                    "width_ft": width_ft,
                    "height_ft": height_ft,
                    "customer_tier": customer.pricing_tier if customer else "standard"
                }

                # Get unit price (use part price if available, otherwise calculate)
                if part.unit_price:
                    unit_price = Decimal(str(part.unit_price))
                else:
                    unit_price = self._get_part_price(part, config)

                # Apply pricing rules
                unit_price = self._apply_pricing_rules(unit_price, part.category, part.part_number, context)

                # Calculate total (quantity from part × door quantity)
                total_quantity = part.quantity * quantity
                total_price = unit_price * total_quantity

                items.append({
                    "item_type": part.category,
                    "product_code": part.part_number,
                    "description": part.description,
                    "quantity": total_quantity,
                    "unit_price": float(unit_price),
                    "total_price": float(total_price),
                    "item_metadata": {
                        "model": model,
                        "size": size,
                        "color": color,
                        "door_series": door_series,
                        "notes": part.notes,
                    }
                })

            logger.info(f"Generated {len(items)} line items for door with real BC part numbers")

        except Exception as e:
            logger.error(f"Error getting parts from door configurator: {e}")
            # Fall back to basic door item if part number service fails
            items.append({
                "item_type": "door",
                "product_code": f"DOOR-{model}",
                "description": f"{model} Overhead Door - {width_ft}'x{height_ft}'",
                "quantity": quantity,
                "unit_price": 0.0,
                "total_price": 0.0,
                "item_metadata": {
                    "model": model,
                    "error": str(e),
                    "needs_manual_review": True,
                }
            })

        return items

    def _map_model_to_series(self, model: str) -> str:
        """Map AI-parsed model names to standard door series codes"""
        if not model:
            return "KANATA"  # Default

        model_upper = model.upper()

        # Direct mappings
        series_map = {
            "TX450": "TX450",
            "TX500": "TX500",
            "TX450-20": "TX450-20",
            "TX500-20": "TX500-20",
            "THERMALEX": "TX450",  # Generic Thermalex → TX450
            "AL976": "AL976",
            "ALUMINUM": "AL976",
            "ALUMINIUM": "AL976",
            "KANATA": "KANATA",
            "CRAFT": "CRAFT",
            "SOLALITE": "AL976",  # Solalite is aluminum series
        }

        for key, series in series_map.items():
            if key in model_upper:
                return series

        # Default based on common patterns
        if "COMMERCIAL" in model_upper:
            return "TX450"

        return "KANATA"  # Default to residential

    def _determine_door_type(self, model: str, width_inches: int, height_inches: int) -> str:
        """Determine door type (residential/commercial) based on model and size"""
        if not model:
            return "residential"

        model_upper = model.upper()

        # Commercial models
        if any(x in model_upper for x in ["TX450", "TX500", "THERMALEX", "COMMERCIAL"]):
            return "commercial"

        # Aluminum
        if any(x in model_upper for x in ["AL976", "ALUMINUM", "ALUMINIUM", "SOLALITE"]):
            return "aluminium"

        # Size-based heuristic: very large doors are likely commercial
        sq_ft = (width_inches * height_inches) / 144
        if sq_ft > 200:  # Over 200 sq ft
            return "commercial"

        return "residential"

    def _map_color_to_code(self, color: Optional[str], series: str) -> str:
        """Map AI-parsed color names to standard color codes"""
        if not color:
            return "WHITE"  # Default

        color_upper = color.upper().replace(" ", "_")

        # Common color mappings
        color_map = {
            "WHITE": "WHITE",
            "BLACK": "BLACK",
            "BROWN": "NEW_BROWN",
            "NEW_BROWN": "NEW_BROWN",
            "ALMOND": "NEW_ALMOND",
            "SANDTONE": "SANDTONE",
            "SAND": "SANDTONE",
            "TAN": "SANDTONE",
            "BRONZE": "BRONZE",
            "GREY": "STEEL_GREY",
            "GRAY": "STEEL_GREY",
            "STEEL_GREY": "STEEL_GREY",
            "STEEL_GRAY": "STEEL_GREY",
            "WALNUT": "WALNUT",
            "IRON_ORE": "IRON_ORE",
            "HAZELWOOD": "HAZELWOOD",
            "ENGLISH_CHESTNUT": "ENGLISH_CHESTNUT",
            "CHESTNUT": "ENGLISH_CHESTNUT",
        }

        for key, code in color_map.items():
            if key in color_upper:
                return code

        return "WHITE"  # Default

    def _get_part_price(self, part: PartSelection, config: DoorConfiguration) -> Decimal:
        """Calculate price for a part based on category and specifications"""
        # Base prices by category (placeholder - would come from BC pricing in production)
        category_base_prices = {
            "panel": Decimal("150.00"),
            "track": Decimal("200.00"),
            "spring": Decimal("3.50"),  # Per inch
            "spring_accessory": Decimal("25.00"),
            "shaft": Decimal("75.00"),
            "strut": Decimal("45.00"),
            "hardware": Decimal("180.00"),
            "weather_stripping": Decimal("15.00"),
            "retainer": Decimal("20.00"),
            "astragal": Decimal("35.00"),
            "window": Decimal("120.00"),
            "operator": Decimal("350.00"),
        }

        base_price = category_base_prices.get(part.category, Decimal("50.00"))

        # Adjust based on door size for certain categories
        sq_ft = (config.door_width * config.door_height) / 144
        size_factor = Decimal(str(max(1.0, sq_ft / 56)))  # 56 sq ft = 8x7 baseline

        if part.category in ["panel", "track", "hardware"]:
            base_price = base_price * size_factor

        return base_price

    def _generate_shipping_item(self, line_items: List[Dict[str, Any]], project: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Generate shipping/delivery line item"""
        # Calculate shipping based on total weight/size
        # This is a placeholder - real logic would consider location, size, etc.

        total_doors = sum(
            item["quantity"] for item in line_items
            if item["item_type"] == "door"
        )

        if total_doors == 0:
            return None

        # Base shipping rate
        shipping_base = Decimal("150.00")  # Base delivery fee
        per_door_fee = Decimal("25.00")

        shipping_total = shipping_base + (per_door_fee * total_doors)

        return {
            "item_type": "delivery",
            "product_code": "DELIVERY",
            "description": f"Delivery ({total_doors} doors)",
            "quantity": 1,
            "unit_price": float(shipping_total),
            "total_price": float(shipping_total),
            "item_metadata": {
                "delivery_date": project.get("delivery_date"),
                "project_name": project.get("name")
            }
        }

    def _get_base_price(self, model: str, width: int, height: int) -> Decimal:
        """
        Get base price for a door model and size

        This is a placeholder - real implementation would:
        - Query pricing database
        - Calculate based on size tiers
        - Consider material costs
        """
        # Placeholder pricing logic
        base_prices = {
            "TX450": Decimal("1200.00"),
            "AL976": Decimal("1500.00"),
            "AL976-SWD": Decimal("1650.00"),
            "Solalite": Decimal("1800.00"),
            "Kanata": Decimal("1400.00"),
            "Craft": Decimal("1600.00"),
        }

        base_price = base_prices.get(model, Decimal("1000.00"))

        # Size multiplier (every foot over 10x10 adds 10%)
        base_size = 100  # 10x10 = 100 sq ft
        actual_size = width * height
        if actual_size > base_size:
            size_factor = Decimal(actual_size / base_size)
            base_price = base_price * size_factor

        return base_price

    def _get_hardware_price(self, track_type: str, width: int, height: int) -> Decimal:
        """Get price for track and hardware"""
        # 3" track is more expensive than 2"
        if track_type == "3":
            base = Decimal("300.00")
        else:
            base = Decimal("200.00")

        # Larger doors need more hardware
        size_factor = Decimal((width * height) / 100)
        return base * size_factor

    def _get_glazing_price(self, glazing_type: str, width: int, height: int) -> Decimal:
        """Get price for glazing/windows"""
        glazing_prices = {
            "thermopane": Decimal("400.00"),
            "single pane": Decimal("250.00"),
            "single glass": Decimal("250.00"),
            "polycarbonate": Decimal("300.00"),
        }

        base_price = glazing_prices.get(glazing_type.lower(), Decimal("200.00"))

        # More glazing for larger doors
        size_factor = Decimal((width * height) / 100)
        return base_price * size_factor

    def _generate_spring_item(
        self,
        door_spec: Dict[str, Any],
        quantity: int,
        context: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """
        Generate spring line item using Canimex spring calculator.

        Uses exact Canimex methodology:
        - IPPT = Multiplier × Door Weight
        - MIP per spring = (IPPT × Turns) / Spring Quantity
        - Active Coils = (Spring Quantity × Divider) / IPPT
        - Total Spring Length = Active Coils + Dead Coil Factor

        Args:
            door_spec: Door specifications from parsed data
            quantity: Number of doors
            context: Pricing context

        Returns:
            Spring line item dict or None if calculation fails
        """
        width_ft = door_spec.get("width_ft", 0)
        height_ft = door_spec.get("height_ft", 0)
        model = door_spec.get("model", "")

        if not width_ft or not height_ft:
            return None

        # Convert to inches
        width_inches = width_ft * 12
        height_inches = height_ft * 12

        # Estimate door weight based on model and size
        # Standard insulated doors: ~4 lbs/sq ft, commercial ~5.5 lbs/sq ft
        sq_ft = width_ft * height_ft
        door_weight = self._estimate_door_weight(model, sq_ft)

        # Get track radius from spec or default to 15"
        track_type = door_spec.get("track_type", "2")
        track_radius = 15 if track_type == "2" else 12  # Standard radius by track type

        # Calculate springs using Canimex methodology
        spring_qty = 2  # Standard residential = 2 springs
        target_cycles = 10000  # Default cycle life

        result = spring_calculator.calculate_spring(
            door_weight=door_weight,
            door_height=height_inches,
            track_radius=track_radius,
            spring_qty=spring_qty,
            target_cycles=target_cycles
        )

        if result is None:
            logger.warning(
                f"Spring calculator returned no result for {door_weight:.0f} lbs, "
                f"{height_inches}\" height"
            )
            return None

        # Calculate spring price based on wire diameter and length
        spring_price = self._get_spring_price(
            result.wire_diameter,
            result.coil_diameter,
            result.length
        )
        spring_price = self._apply_pricing_rules(spring_price, "spring", result.part_number, context)

        # Total price is per-spring price × spring quantity × door quantity
        unit_price = float(spring_price)
        total_price = float(spring_price * spring_qty * quantity)

        return {
            "item_type": "spring",
            "product_code": result.part_number,
            "description": (
                f"Torsion Spring - {result.wire_diameter}\" wire x "
                f"{result.coil_diameter}\" ID x {result.length}\" length"
            ),
            "quantity": spring_qty * quantity,  # 2 springs per door × door count
            "unit_price": unit_price,
            "total_price": total_price,
            "item_metadata": {
                "wire_diameter": result.wire_diameter,
                "coil_diameter": result.coil_diameter,
                "length": result.length,
                "ippt": result.ippt,
                "mip_per_spring": result.mip_per_spring,
                "turns": result.turns,
                "cycle_life": result.cycle_life,
                "drum_model": result.drum_model,
                "door_weight": door_weight,
                "door_height_inches": height_inches,
                "track_radius": track_radius
            }
        }

    def _estimate_door_weight(self, model: str, sq_ft: float) -> float:
        """
        Estimate door weight based on model and size.

        Weight factors (lbs per sq ft):
        - TX450: ~4.0 lbs/sq ft (standard insulated)
        - TX500: ~4.5 lbs/sq ft (thicker insulation)
        - AL976: ~3.5 lbs/sq ft (aluminum)
        - Kanata: ~4.2 lbs/sq ft (premium insulated)
        - Commercial: ~5.5 lbs/sq ft
        """
        weight_factors = {
            "TX450": 4.0,
            "TX450-20": 4.5,  # 20-gauge heavier
            "TX500": 4.5,
            "TX500-20": 5.0,
            "AL976": 3.5,
            "AL976-SWD": 4.0,
            "Kanata": 4.2,
            "KANATA": 4.2,
            "Craft": 4.0,
            "CRAFT": 4.0,
            "Solalite": 3.8,
        }

        # Get weight factor for model, default to standard insulated
        factor = weight_factors.get(model, 4.0)

        # Commercial doors are heavier
        if "commercial" in model.lower() or sq_ft > 150:
            factor = max(factor, 5.5)

        return sq_ft * factor

    def _get_spring_price(self, wire_diameter: float, coil_diameter: float, length: float) -> Decimal:
        """
        Calculate spring price based on specifications.

        Pricing factors:
        - Wire diameter: larger wire = more material = higher price
        - Coil diameter: larger ID = more expensive
        - Length: longer spring = more material = higher price
        """
        # Base price per inch of spring length
        base_price_per_inch = Decimal("3.50")

        # Wire diameter multiplier (0.250" = baseline)
        wire_factor = Decimal(str(wire_diameter / 0.250))

        # Coil diameter multiplier (2.0" = baseline)
        coil_factor = Decimal(str(coil_diameter / 2.0))

        # Calculate price
        spring_price = base_price_per_inch * Decimal(str(length)) * wire_factor * coil_factor

        # Minimum price floor
        return max(spring_price, Decimal("75.00"))

    def _apply_pricing_rules(self, base_price: Decimal, rule_type: str, entity: str, context: Dict[str, Any]) -> Decimal:
        """
        Apply pricing rules to a base price

        Args:
            base_price: Starting price
            rule_type: Type of rule to apply (base_price, hardware, glazing, etc.)
            entity: Specific entity (TX450, 2" track, etc.)
            context: Context for rule matching (quantity, customer_tier, etc.)

        Returns:
            Final price after rules applied
        """
        # Get applicable rules
        rules = self.db.query(PricingRule).filter(
            PricingRule.rule_type == rule_type,
            PricingRule.is_active == True
        ).order_by(PricingRule.priority.desc()).all()

        # Filter rules by entity
        applicable_rules = [
            rule for rule in rules
            if rule.entity is None or rule.entity == entity
        ]

        # Apply matching rules
        current_price = base_price
        for rule in applicable_rules:
            if rule.matches(context):
                current_price = Decimal(str(rule.apply(float(current_price))))
                logger.debug(f"Applied rule {rule.id}: {base_price} -> {current_price}")

        return current_price

    def _get_or_create_customer(self, customer_data: Dict[str, Any]) -> Optional[BCCustomer]:
        """
        Get existing BC customer or create placeholder

        In production, this would:
        - Look up customer in Business Central
        - Cache customer data locally
        - Update pricing tier
        """
        email = customer_data.get("email")
        if not email:
            return None

        # Check if customer exists in cache
        customer = self.db.query(BCCustomer).filter(
            BCCustomer.email == email
        ).first()

        if customer:
            return customer

        # Create placeholder customer (would normally sync from BC)
        company_name = customer_data.get("company_name")
        if not company_name:
            return None  # Can't create without company name

        customer = BCCustomer(
            bc_customer_id=f"TEMP-{email}",  # Placeholder - would get real ID from BC
            company_name=company_name,
            contact_name=customer_data.get("contact_name"),
            email=email,
            phone=customer_data.get("phone"),
            pricing_tier="standard",  # Default tier
            last_synced=None  # Not synced yet
        )

        self.db.add(customer)
        self.db.commit()

        logger.info(f"Created placeholder customer: {company_name}")
        return customer


def get_quote_service(db: Session) -> QuoteGenerationService:
    """Dependency injection helper"""
    return QuoteGenerationService(db)
