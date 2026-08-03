"""
Install Pricing Service
Per-customer installation pricing for residential and commercial doors.

Residential: flat rates by door area tier (small/medium/large)
Commercial: base rate + per-sqft rate above 100 sqft
Travel: rate per km (round trip) from Medicine Hat, AB
"""

import json
import logging
import math
import re
from typing import Optional, Dict, Any, List, Tuple

import requests
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.config import settings
from app.db.models import CustomerInstallPricing, AppSettings

logger = logging.getLogger(__name__)

# Google Routes API (replaces the legacy Distance Matrix API).
# Install travel origin is our shop in Medicine Hat.
GOOGLE_ROUTES_URL = "https://routes.googleapis.com/directions/v2:computeRoutes"
TRAVEL_ORIGIN = "Medicine Hat, AB, Canada"
# Bias matching toward Canadian prairies so "Raymore" hits Raymore SK and not
# Raymore TX or Raymore-anything-else.
TRAVEL_DESTINATION_REGION_CODE = "CA"

TRAVEL_DISTANCES_KEY = "install_travel_distances"

# Builder-account installation defaults.
BUILDER_INSTALL_RATE_PER_SQFT = 4.50      # wood-mount $/sqft (default / fallback)

# Install $/sqft is set by the door's mount surface, uniform across all builder
# accounts (not a per-customer rate). Steel and concrete are harder mounts and
# carry a higher install rate; the door product price is unaffected by mount.
BUILDER_INSTALL_RATE_BY_MOUNT = {
    "wood": 4.50,
    "steel": 5.50,
    "concrete": 7.50,
}

BUILDER_RESIDENTIAL_SMALL_FLAT = 500.00   # flat FLOOR for residential < 90 sqft
BUILDER_RESIDENTIAL_MEDIUM_FLAT = 600.00  # flat FLOOR for residential 90 - 130 sqft
BUILDER_RESIDENTIAL_LARGE_THRESHOLD = 130 # > 130 sqft -> per-sqft model
BUILDER_RESIDENTIAL_SMALL_THRESHOLD = 90  # < 90 sqft -> small flat floor

BUILDER_TRAVEL_RATE_PER_KM = 1.00         # $/km, one-way from Medicine Hat
BUILDER_LIFT_BLOCK_SQFT = 400             # one charge per 400 sqft of qualifying door
BUILDER_LIFT_BLOCK_PRICE = 400.00         # $/block (when any door > 12' tall)
BUILDER_PER_DIEM_BLOCK_PRICE = 200.00     # $/block (when total > 400 sqft AND far)
BUILDER_PER_DIEM_MIN_KM = 200             # no per diem within 200 km of Medicine Hat
BUILDER_LIFT_HEIGHT_INCHES = 144          # 12' = 144"
BUILDER_OPERATOR_ADDON_PER_DOOR = 150.00  # flat $/door for any door with an operator

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

    def _google_distance_km(self, town: str) -> Optional[float]:
        """Query Google Routes API for road km from Medicine Hat to `town`.
        Returns None if no API key configured, no route found, or the API errors.

        Uses the modern Routes API (the legacy Distance Matrix API requires
        per-project enablement and is being deprecated). Routes returns a
        compact response gated by the X-Goog-FieldMask header, so we only ask
        for distanceMeters."""
        api_key = settings.GOOGLE_MAPS_API_KEY
        if not api_key:
            return None
        body = {
            "origin": {"address": TRAVEL_ORIGIN},
            "destination": {"address": town},
            "travelMode": "DRIVE",
            "routingPreference": "TRAFFIC_AWARE",
            "regionCode": TRAVEL_DESTINATION_REGION_CODE,
        }
        headers = {
            "Content-Type": "application/json",
            "X-Goog-Api-Key": api_key,
            "X-Goog-FieldMask": "routes.distanceMeters",
        }
        try:
            resp = requests.post(GOOGLE_ROUTES_URL, json=body, headers=headers, timeout=10)
            data = resp.json()
        except Exception as e:
            logger.warning(f"Google Routes request failed for {town!r}: {e}")
            return None
        if resp.status_code >= 400:
            err = (data.get("error") or {}).get("message") or data
            logger.warning(f"Google Routes HTTP {resp.status_code} for {town!r}: {err}")
            return None
        routes = data.get("routes") or []
        if not routes:
            logger.info(f"Google Routes returned no route for town {town!r}")
            return None
        meters = routes[0].get("distanceMeters")
        if meters is None:
            return None
        return round(meters / 1000.0, 1)

    def lookup_distance_km(self, town: str, db: Session) -> Tuple[Optional[float], str]:
        """
        Resolve a town name to road km from Medicine Hat. Returns
        (distance_km, source) where source is "static", "google", or "unknown".

        Cached results from Google are written back to the
        install_travel_distances AppSettings dict so each unique town is paid
        for at most once.
        """
        if not town or not town.strip():
            return None, "unknown"
        normalized = town.strip()
        distances = self.get_travel_distances(db)

        # 1. Case-insensitive match against the cached/static dict.
        for t, d in distances.items():
            if t.lower() == normalized.lower():
                return float(d), "static"

        # 2. Ask Google.
        km = self._google_distance_km(normalized)
        if km is None:
            return None, "unknown"

        # 3. Cache it (keyed by the canonical town name customer typed).
        try:
            cache_key = re.sub(r"\s+", " ", normalized).title()  # "raymore" -> "Raymore"
            distances[cache_key] = km
            self.set_travel_distances(db, distances)
            logger.info(f"Cached Google-resolved distance: {cache_key} -> {km} km")
        except Exception as cache_err:
            logger.warning(f"Could not cache distance for {normalized!r}: {cache_err}")
        return km, "google"

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


    def _install_for_single_door(self, area_sqft: float, door_type: str,
                                 mount_surface: str = "wood") -> Dict[str, Any]:
        """
        Install fee for one door under the builder model.

        The $/sqft rate is set by the mount surface (uniform across builders):
          wood $4.50, steel $5.50, concrete $7.50.

        Residential doors <= 130 sqft carry a flat FLOOR ($500 < 90 sqft,
        $600 for 90-130). We bill the HIGHER of that floor and the per-sqft
        amount, so a steel/concrete mount that exceeds the floor bills per sqft.
        Larger residential (> 130) and all commercial doors are always per-sqft.
        """
        rate = BUILDER_INSTALL_RATE_BY_MOUNT.get(
            (mount_surface or "wood").lower(), BUILDER_INSTALL_RATE_PER_SQFT
        )
        per_sqft_price = round(area_sqft * rate, 2)

        is_residential = (door_type or "").lower() == "residential"
        floor = None
        if is_residential and area_sqft < BUILDER_RESIDENTIAL_SMALL_THRESHOLD:
            floor = BUILDER_RESIDENTIAL_SMALL_FLAT
        elif is_residential and area_sqft <= BUILDER_RESIDENTIAL_LARGE_THRESHOLD:
            floor = BUILDER_RESIDENTIAL_MEDIUM_FLAT

        if floor is not None and floor >= per_sqft_price:
            return {"price": floor, "tier": "residential-flat-floor",
                    "rate": rate, "mount_surface": mount_surface}
        return {"price": per_sqft_price, "tier": "per-sqft",
                "rate": rate, "mount_surface": mount_surface}

    def calculate_total_install_price(
        self,
        customer_id: int,
        doors: List[Dict[str, Any]],
        town: Optional[str],
        db: Session,
    ) -> Dict[str, Any]:
        """
        Builder-account installation pricing — one total for the whole quote,
        not per door. Returns a structured result the caller can render as
        BC quote lines.

        Pricing model (builder accounts only):
          * Per-door install: residential tiers below 130 sqft are flat
            ($500 / $600), everything else is sqft_rate * area_sqft.
          * Lift fee: if ANY door height > 12', charge $400 for every full
            400 sqft block of TOTAL installed area (ceil math).
          * Per diem: if TOTAL installed area > 400 sqft AND the install town is
            more than 200 km from Medicine Hat (overnight trip), charge $200 for
            every 400 sqft block (ceil math). No per diem within 200 km.
          * Travel: $2/km one-way from Medicine Hat to the install town.

        Per-customer overrides on CustomerInstallPricing:
          * commercial_sqft_rate -> overrides BUILDER_INSTALL_RATE_PER_SQFT
          * travel_rate_per_km   -> overrides BUILDER_TRAVEL_RATE_PER_KM

        No height cap, no "custom quote required" branch — installation is
        always priced.
        """
        # Install $/sqft is driven by each door's mount surface, uniform across
        # builders. Only travel is a per-customer override (rarely set now).
        pricing = self.get_customer_pricing(customer_id, db)
        travel_rate = BUILDER_TRAVEL_RATE_PER_KM
        if pricing and pricing.travel_rate_per_km is not None:
            travel_rate = float(pricing.travel_rate_per_km)

        total_install = 0.0
        total_sqft = 0.0
        max_height_in = 0
        operator_doors = 0
        per_door: List[Dict[str, Any]] = []
        for d in doors:
            w = float(d.get("doorWidth") or 0)
            h = float(d.get("doorHeight") or 0)
            count = int(d.get("doorCount") or 1)
            door_type = d.get("doorType", "residential")
            mount_surface = str(d.get("mountSurface") or "wood").lower()
            operator = (d.get("operator") or "").upper()
            has_operator = operator not in ("", "NONE", "MANUAL")
            area = (w * h) / 144.0
            if h > max_height_in:
                max_height_in = h
            unit = self._install_for_single_door(area, door_type, mount_surface)
            line_total = round(unit["price"] * count, 2)
            total_install += line_total
            total_sqft += area * count
            if has_operator:
                operator_doors += count
            per_door.append({
                "door_width_in": w, "door_height_in": h, "door_count": count,
                "door_type": door_type, "mount_surface": mount_surface,
                "area_sqft": round(area, 2), "tier": unit["tier"],
                "install_rate_per_sqft": unit["rate"], "unit_install": unit["price"],
                "line_total": line_total, "has_operator": has_operator,
            })

        # Travel — one-way from Medicine Hat. Tries the cached/static dict
        # first, then falls back to Google Distance Matrix so any town works.
        # Resolved before per-diem because per-diem depends on the distance.
        travel_distance_km: Optional[float] = None
        travel_price = 0.0
        travel_source = "none"
        if town:
            km, source = self.lookup_distance_km(town, db)
            travel_source = source
            if km is not None:
                travel_distance_km = km
                travel_price = round(km * travel_rate, 2)

        # Lift and per-diem are block-based on total sqft.
        blocks = math.ceil(total_sqft / BUILDER_LIFT_BLOCK_SQFT) if total_sqft > 0 else 0
        needs_lift = max_height_in > BUILDER_LIFT_HEIGHT_INCHES
        lift_qty = blocks if needs_lift else 0
        lift_total = round(lift_qty * BUILDER_LIFT_BLOCK_PRICE, 2)
        # Per diem covers the crew staying overnight — only when the install is
        # far enough to not be a day trip. Within 200 km of Medicine Hat there is
        # no per diem, regardless of size. A per diem also needs > 400 sqft.
        per_diem_far = (travel_distance_km is not None
                        and travel_distance_km > BUILDER_PER_DIEM_MIN_KM)
        per_diem_qty = blocks if (total_sqft > BUILDER_LIFT_BLOCK_SQFT and per_diem_far) else 0
        per_diem_total = round(per_diem_qty * BUILDER_PER_DIEM_BLOCK_PRICE, 2)

        operator_addon_total = round(operator_doors * BUILDER_OPERATOR_ADDON_PER_DOOR, 2)
        grand_total = round(
            total_install + lift_total + per_diem_total + travel_price + operator_addon_total,
            2,
        )
        return {
            "town": town,
            "total_sqft": round(total_sqft, 2),
            "door_count_total": sum(p["door_count"] for p in per_door),
            "max_height_in": max_height_in,
            "install_rate_by_mount": dict(BUILDER_INSTALL_RATE_BY_MOUNT),
            "base_install_price": round(total_install, 2),
            "per_door": per_door,
            "needs_lift": needs_lift,
            "lift_block_sqft": BUILDER_LIFT_BLOCK_SQFT,
            "lift_qty": lift_qty,
            "lift_unit_price": BUILDER_LIFT_BLOCK_PRICE,
            "lift_total": lift_total,
            "per_diem_qty": per_diem_qty,
            "per_diem_unit_price": BUILDER_PER_DIEM_BLOCK_PRICE,
            "per_diem_total": per_diem_total,
            "per_diem_min_km": BUILDER_PER_DIEM_MIN_KM,
            "per_diem_applies": per_diem_far,
            "operator_addon_qty": operator_doors,
            "operator_addon_unit_price": BUILDER_OPERATOR_ADDON_PER_DOOR,
            "operator_addon_total": operator_addon_total,
            "travel_distance_km": travel_distance_km,
            "travel_rate_per_km": travel_rate,
            "travel_price": travel_price,
            "travel_source": travel_source,
            "grand_total": grand_total,
        }

    @staticmethod
    def build_install_description(install_result: Dict[str, Any]) -> str:
        """
        Human-readable INSTALLATION line description for the BC quote.

        Includes the door information (per-door square footage when the doors
        are a single size, otherwise the total) and flags when the price
        includes a lift. Kept short enough for BC's 100-char line limit.

        e.g. "Installation - Elkwater (2 doors @ 384 sqft, 768 total, incl. lift)"
        """
        sqft = install_result.get("total_sqft") or 0
        door_count = install_result.get("door_count_total") or 0
        town = install_result.get("town")
        per_door = install_result.get("per_door") or []

        door_word = "door" if door_count == 1 else "doors"
        # Single door size (one config, or all configs the same area) -> show per-door sqft
        areas = {round(p.get("area_sqft") or 0) for p in per_door}
        if len(areas) == 1 and door_count > 1:
            each = areas.pop()
            door_info = f"{door_count} {door_word} @ {each:.0f} sqft, {sqft:.0f} total"
        elif door_count == 1:
            door_info = f"1 door, {sqft:.0f} sqft"
        else:
            door_info = f"{door_count} {door_word}, {sqft:.0f} sqft total"

        if install_result.get("lift_qty"):
            door_info += ", incl. lift"

        prefix = f"Installation - {town} " if town else "Installation "
        return f"{prefix}({door_info})"


# Module-level singleton
install_pricing_service = InstallPricingService()
