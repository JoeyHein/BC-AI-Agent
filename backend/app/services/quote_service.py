"""
Quote Generation Service
Converts parsed email data into structured quotes with pricing
"""

import logging
from typing import List, Dict, Any, Optional
from decimal import Decimal
from datetime import datetime
from sqlalchemy.orm import Session

from app.db.models import QuoteRequest, QuoteItem, PricingRule, BCCustomer

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
        Generate line items for a door specification

        Args:
            door_spec: Door specifications from parsed data
            customer: BC customer for pricing tier

        Returns:
            List of line item dicts
        """
        items = []
        model = door_spec.get("model")
        quantity = door_spec.get("quantity", 1)
        width_ft = door_spec.get("width_ft", 0)
        height_ft = door_spec.get("height_ft", 0)

        if not model:
            logger.warning("Door spec missing model, skipping")
            return items

        # Calculate door size
        size = f"{width_ft}' x {height_ft}'"

        # Get base price for door model
        base_price = self._get_base_price(model, width_ft, height_ft)

        # Apply pricing rules
        context = {
            "model": model,
            "quantity": quantity,
            "width_ft": width_ft,
            "height_ft": height_ft,
            "customer_tier": customer.pricing_tier if customer else "standard"
        }

        door_price = self._apply_pricing_rules(base_price, "base_price", model, context)

        # Main door item
        items.append({
            "item_type": "door",
            "product_code": f"DOOR-{model}",
            "description": f"{model} Overhead Door - {size}",
            "quantity": quantity,
            "unit_price": float(door_price),
            "total_price": float(door_price * quantity),
            "item_metadata": {
                "model": model,
                "size": size,
                "color": door_spec.get("color"),
                "panel_config": door_spec.get("panel_config"),
            }
        })

        # Hardware item (track type)
        track_type = door_spec.get("track_type")
        if track_type:
            hardware_price = self._get_hardware_price(track_type, width_ft, height_ft)
            hardware_price = self._apply_pricing_rules(hardware_price, "hardware", track_type, context)

            items.append({
                "item_type": "hardware",
                "product_code": f"TRACK-{track_type}",
                "description": f"{track_type}\" Track and Hardware",
                "quantity": quantity,
                "unit_price": float(hardware_price),
                "total_price": float(hardware_price * quantity),
                "item_metadata": {
                    "track_type": track_type,
                    "size": size
                }
            })

        # Glazing item (windows)
        glazing = door_spec.get("glazing")
        if glazing:
            glazing_price = self._get_glazing_price(glazing, width_ft, height_ft)
            glazing_price = self._apply_pricing_rules(glazing_price, "glazing", glazing, context)

            items.append({
                "item_type": "glazing",
                "product_code": f"GLASS-{glazing.upper().replace(' ', '_')}",
                "description": f"{glazing.title()} Glazing",
                "quantity": quantity,
                "unit_price": float(glazing_price),
                "total_price": float(glazing_price * quantity),
                "item_metadata": {
                    "glazing_type": glazing
                }
            })

        return items

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
