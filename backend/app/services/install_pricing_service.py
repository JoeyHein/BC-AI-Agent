"""
Install Pricing Service
Per-customer installation pricing for residential and commercial doors.

Residential: flat rates by door area tier (small/medium/large)
Commercial: base rate + per-sqft rate above 100 sqft
Travel: rate per km (round trip) from Medicine Hat, AB
"""

import json
import logging
from typing import Optional, Dict, Any

from sqlalchemy.orm import Session

from app.db.models import CustomerInstallPricing, AppSettings

logger = logging.getLogger(__name__)

TRAVEL_DISTANCES_KEY = "install_travel_distances"

# Default travel distances (km from Medicine Hat, AB)
DEFAULT_TRAVEL_DISTANCES = {
    "Swift Current": 290,
    "Regina": 590,
    "Saskatoon": 770,
    "Moose Jaw": 520,
    "Prince Albert": 900,
    "Yorkton": 790,
    "Estevan": 440,
    "Weyburn": 470,
    "North Battleford": 820,
    "Lloydminster": 640,
    "Humboldt": 770,
    "Melfort": 880,
    "Kindersley": 470,
    "Melville": 730,
    "Maple Creek": 165,
    "Lethbridge": 170,
    "Calgary": 300,
    "Red Deer": 470,
    "Edmonton": 590,
}


class InstallPricingService:
    """Calculate installation pricing for a door given customer-specific rates."""

    def get_travel_distances(self, db: Session) -> dict:
        """Load town distance lookup from AppSettings, or return defaults."""
        setting = db.query(AppSettings).filter(
            AppSettings.setting_key == TRAVEL_DISTANCES_KEY
        ).first()
        if setting and setting.setting_value:
            return setting.setting_value
        return DEFAULT_TRAVEL_DISTANCES.copy()

    def set_travel_distances(self, db: Session, distances: dict, updated_by: Optional[int] = None) -> dict:
        """Save town distance lookup to AppSettings (upsert)."""
        setting = db.query(AppSettings).filter(
            AppSettings.setting_key == TRAVEL_DISTANCES_KEY
        ).first()
        if setting:
            setting.setting_value = distances
            if updated_by:
                setting.updated_by = updated_by
        else:
            setting = AppSettings(
                setting_key=TRAVEL_DISTANCES_KEY,
                setting_value=distances,
                description="Town distances (km) from Medicine Hat, AB for install travel pricing",
                updated_by=updated_by,
            )
            db.add(setting)
        db.commit()
        return distances

    def get_customer_pricing(self, customer_id: int, db: Session) -> Optional[CustomerInstallPricing]:
        """Get install pricing record for a customer."""
        return db.query(CustomerInstallPricing).filter(
            CustomerInstallPricing.customer_id == customer_id
        ).first()

    def upsert_customer_pricing(
        self,
        customer_id: int,
        data: dict,
        db: Session,
    ) -> CustomerInstallPricing:
        """Create or update install pricing for a customer."""
        pricing = db.query(CustomerInstallPricing).filter(
            CustomerInstallPricing.customer_id == customer_id
        ).first()

        if pricing:
            for key in (
                "residential_small", "residential_medium", "residential_large",
                "commercial_base_rate", "commercial_sqft_rate",
                "max_auto_height", "travel_rate_per_km",
            ):
                if key in data:
                    setattr(pricing, key, data[key])
        else:
            pricing = CustomerInstallPricing(
                customer_id=customer_id,
                residential_small=data.get("residential_small"),
                residential_medium=data.get("residential_medium"),
                residential_large=data.get("residential_large"),
                commercial_base_rate=data.get("commercial_base_rate"),
                commercial_sqft_rate=data.get("commercial_sqft_rate"),
                max_auto_height=data.get("max_auto_height", 168),
                travel_rate_per_km=data.get("travel_rate_per_km"),
            )
            db.add(pricing)

        db.commit()
        db.refresh(pricing)
        return pricing

    def calculate_install_price(
        self,
        customer_id: int,
        door_width_inches: float,
        door_height_inches: float,
        door_type: str,
        db: Session,
        town: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Calculate installation price for a door.

        Returns dict with:
            install_price, travel_price, total, custom_quote_required,
            reason, breakdown
        """
        result = {
            "install_price": None,
            "travel_price": None,
            "total": None,
            "custom_quote_required": False,
            "reason": None,
            "breakdown": {
                "door_area_sqft": None,
                "rate_tier": None,
                "base_rate": None,
                "sqft_rate": None,
                "travel_distance_km": None,
                "travel_rate_per_km": None,
            },
        }

        # 1. Look up customer pricing
        pricing = self.get_customer_pricing(customer_id, db)
        if not pricing:
            result["custom_quote_required"] = True
            result["reason"] = "No install pricing configured"
            return result

        # 2. Calculate door area
        area_sqft = (door_width_inches * door_height_inches) / 144.0
        result["breakdown"]["door_area_sqft"] = round(area_sqft, 2)

        # 3. Check height limit
        max_height = pricing.max_auto_height or 168
        if door_height_inches > max_height:
            result["custom_quote_required"] = True
            result["reason"] = f"Door exceeds {max_height / 12:.0f}' height limit"
            return result

        # 4/5. Determine install price
        door_type_lower = (door_type or "residential").lower()
        install_price = None

        if door_type_lower == "residential" and area_sqft <= 150:
            if area_sqft <= 90:
                rate = float(pricing.residential_small) if pricing.residential_small is not None else None
                result["breakdown"]["rate_tier"] = "small"
                result["breakdown"]["base_rate"] = rate
                install_price = rate
            elif area_sqft <= 130:
                rate = float(pricing.residential_medium) if pricing.residential_medium is not None else None
                result["breakdown"]["rate_tier"] = "medium"
                result["breakdown"]["base_rate"] = rate
                install_price = rate
            else:  # 131-150
                rate = float(pricing.residential_large) if pricing.residential_large is not None else None
                result["breakdown"]["rate_tier"] = "large"
                result["breakdown"]["base_rate"] = rate
                install_price = rate
        else:
            # Commercial formula (or residential overflow > 150 sqft)
            result["breakdown"]["rate_tier"] = "commercial"
            base = float(pricing.commercial_base_rate) if pricing.commercial_base_rate is not None else None
            sqft_rate = float(pricing.commercial_sqft_rate) if pricing.commercial_sqft_rate is not None else None
            result["breakdown"]["base_rate"] = base
            result["breakdown"]["sqft_rate"] = sqft_rate

            if base is not None:
                if area_sqft <= 100:
                    install_price = base
                elif sqft_rate is not None:
                    install_price = base + (area_sqft - 100) * sqft_rate
                else:
                    # sqft_rate not set — can only price up to 100 sqft
                    result["custom_quote_required"] = True
                    result["reason"] = "Commercial per-sqft rate not configured"
                    return result
            else:
                result["custom_quote_required"] = True
                result["reason"] = "Commercial base rate not configured"
                return result

        if install_price is None:
            result["custom_quote_required"] = True
            result["reason"] = "Rate not configured for this door size"
            return result

        result["install_price"] = round(install_price, 2)

        # 6. Travel calculation
        if town and pricing.travel_rate_per_km is not None:
            distances = self.get_travel_distances(db)
            # Case-insensitive lookup
            distance_km = None
            town_lower = town.strip().lower()
            for t, d in distances.items():
                if t.lower() == town_lower:
                    distance_km = d
                    break

            if distance_km is not None:
                travel_rate = float(pricing.travel_rate_per_km)
                travel_price = distance_km * travel_rate * 2  # round trip
                result["travel_price"] = round(travel_price, 2)
                result["breakdown"]["travel_distance_km"] = distance_km
                result["breakdown"]["travel_rate_per_km"] = travel_rate

        # 7. Total
        total = result["install_price"] or 0
        if result["travel_price"]:
            total += result["travel_price"]
        result["total"] = round(total, 2)

        return result


# Module-level singleton
install_pricing_service = InstallPricingService()
