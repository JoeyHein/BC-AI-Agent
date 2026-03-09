"""
Spring Builder Service
Wraps existing spring calculator with catalog integration:
SKU matching, cone set lookup, special order handling.
"""

import logging
from datetime import datetime
from typing import Optional, List, Dict, Any

from sqlalchemy.orm import Session

from app.db.models import Part, SpecialOrderRequest, User
from app.services.spring_calculator_service import SpringCalculatorService, SpringResult
from app.services.bc_part_number_mapper import BCPartNumberMapper

logger = logging.getLogger(__name__)

# Initialize the existing services
calculator = SpringCalculatorService()
mapper = BCPartNumberMapper()


class SpringBuilderService:
    """Spring builder with catalog integration."""

    def calculate_and_match(
        self,
        db: Session,
        door_weight: float,
        door_height: int,
        track_radius: int = 15,
        spring_qty: int = 2,
        target_cycles: int = 10000,
        coil_diameter: float = 2.0,
        drum_model: str = None,
        high_lift_inches: int = 0,
    ) -> dict:
        """
        Calculate spring specs and match to catalog SKUs.

        Returns calculation results with:
        - spring specs (wire, coil, length, etc.)
        - matched SKU from parts table (or None)
        - cone set part numbers
        - special_order flag if no match found
        """
        # Run the existing calculator
        result = calculator.calculate_spring(
            door_weight=door_weight,
            door_height=door_height,
            track_radius=track_radius,
            spring_qty=spring_qty,
            coil_diameter=coil_diameter,
            target_cycles=target_cycles,
            drum_model=drum_model,
            high_lift_inches=high_lift_inches,
        )

        if result is None:
            return {
                "success": False,
                "error": "No spring configuration found for these door specifications.",
                "calculation": None,
                "matched_sku": None,
                "cone_sets": None,
                "special_order_needed": False,
            }

        # Build SKU pattern using the mapper
        lh_part = mapper.get_spring_part_number(
            result.wire_diameter, result.coil_diameter, "LH"
        )
        rh_part = mapper.get_spring_part_number(
            result.wire_diameter, result.coil_diameter, "RH"
        )

        # Try to match in parts table
        lh_match = self._match_sku(db, lh_part.part_number)
        rh_match = self._match_sku(db, rh_part.part_number)

        # If no match, try stepping up wire size
        if not lh_match:
            lh_match, stepped_pn = self._try_step_up_wire(db, result.wire_diameter, result.coil_diameter, "LH")
            if stepped_pn:
                lh_part.part_number = stepped_pn
        if not rh_match:
            rh_match, stepped_pn = self._try_step_up_wire(db, result.wire_diameter, result.coil_diameter, "RH")
            if stepped_pn:
                rh_part.part_number = stepped_pn

        special_order_needed = not lh_match and not rh_match

        # Resolve cone sets
        cone_sets = self._resolve_cone_sets(result.coil_diameter)

        # Build response
        calc_data = {
            "wire_diameter": result.wire_diameter,
            "coil_diameter": result.coil_diameter,
            "length": result.length,
            "active_coils": result.active_coils,
            "ippt": result.ippt,
            "mip_per_spring": result.mip_per_spring,
            "turns": result.turns,
            "spring_quantity": result.spring_quantity,
            "cycle_life": result.cycle_life,
            "drum_model": result.drum_model,
        }

        return {
            "success": True,
            "calculation": calc_data,
            "springs": {
                "lh": {
                    "part_number": lh_part.part_number,
                    "description": lh_part.description,
                    "matched": lh_match is not None,
                    "catalog_id": lh_match.id if lh_match else None,
                    "price": float(lh_match.retail_price) if lh_match and lh_match.retail_price else None,
                },
                "rh": {
                    "part_number": rh_part.part_number,
                    "description": rh_part.description,
                    "matched": rh_match is not None,
                    "catalog_id": rh_match.id if rh_match else None,
                    "price": float(rh_match.retail_price) if rh_match and rh_match.retail_price else None,
                },
            },
            "cone_sets": cone_sets,
            "special_order_needed": special_order_needed,
        }

    def _match_sku(self, db: Session, part_number: str) -> Optional[Part]:
        """Match a part number in the catalog."""
        return db.query(Part).filter(
            Part.bc_item_number == part_number,
            Part.catalog_status.in_(["active", "pending_review"]),
        ).first()

    def _try_step_up_wire(self, db: Session, wire_diameter: float,
                           coil_diameter: float, wind: str):
        """Try next wire size up if exact match not found."""
        wire_sizes = sorted(mapper.WIRE_SIZE_CODES.keys())
        current_idx = None
        for i, ws in enumerate(wire_sizes):
            if ws >= wire_diameter:
                current_idx = i
                break

        if current_idx is None:
            return None, None

        # Try up to 3 sizes up
        for offset in range(1, 4):
            idx = current_idx + offset
            if idx >= len(wire_sizes):
                break
            next_wire = wire_sizes[idx]
            part = mapper.get_spring_part_number(next_wire, coil_diameter, wind)
            match = self._match_sku(db, part.part_number)
            if match:
                logger.info(f"Stepped up wire {wire_diameter} -> {next_wire} for SKU match: {part.part_number}")
                return match, part.part_number

        return None, None

    def _resolve_cone_sets(self, coil_diameter: float) -> dict:
        """Look up cone/winder set part numbers by coil diameter."""
        lh_winder = mapper.get_winder_stationary_set(coil_diameter, bore_size=1.0, wind="LH")
        rh_winder = mapper.get_winder_stationary_set(coil_diameter, bore_size=1.0, wind="RH")

        return {
            "lh": {
                "part_number": lh_winder.part_number,
                "description": lh_winder.description,
            },
            "rh": {
                "part_number": rh_winder.part_number,
                "description": rh_winder.description,
            },
        }

    def submit_special_order(
        self,
        db: Session,
        user: User,
        wire_diameter: float,
        coil_diameter: float,
        spring_length: float,
        wind_direction: str,
        quantity: int = 1,
        spring_type: str = "SP11",
        door_width: float = None,
        door_height: float = None,
        door_weight: float = None,
        calculation_data: dict = None,
    ) -> SpecialOrderRequest:
        """Create a special order request for a spring that can't be fulfilled from catalog."""
        order = SpecialOrderRequest(
            customer_user_id=user.id,
            bc_customer_id=user.bc_customer_id,
            wire_diameter=wire_diameter,
            coil_diameter=coil_diameter,
            spring_length=spring_length,
            wind_direction=wind_direction,
            quantity=quantity,
            spring_type=spring_type,
            door_width=door_width,
            door_height=door_height,
            door_weight=door_weight,
            calculation_data=calculation_data,
            status="pending",
            created_at=datetime.utcnow(),
        )
        db.add(order)
        db.flush()
        logger.info(f"Special order created: id={order.id}, wire={wire_diameter}, coil={coil_diameter}")
        return order

    def get_customer_special_orders(
        self, db: Session, user_id: int, skip: int = 0, limit: int = 50
    ) -> List[SpecialOrderRequest]:
        """Get special orders for a customer."""
        return (
            db.query(SpecialOrderRequest)
            .filter(SpecialOrderRequest.customer_user_id == user_id)
            .order_by(SpecialOrderRequest.created_at.desc())
            .offset(skip)
            .limit(limit)
            .all()
        )

    def get_spring_alternatives(
        self,
        db: Session,
        coil_diameter: float,
        wire_diameter: float,
        limit: int = 10,
    ) -> List[dict]:
        """Query nearby wire sizes on the same coil diameter."""
        # Get wire sizes close to requested
        wire_sizes = sorted(mapper.WIRE_SIZE_CODES.keys())
        nearby = [ws for ws in wire_sizes if abs(ws - wire_diameter) <= 0.05]

        alternatives = []
        for ws in nearby:
            for wind in ["LH", "RH"]:
                part = mapper.get_spring_part_number(ws, coil_diameter, wind)
                match = self._match_sku(db, part.part_number)
                if match:
                    alternatives.append({
                        "part_number": part.part_number,
                        "wire_diameter": ws,
                        "coil_diameter": coil_diameter,
                        "wind_direction": wind,
                        "price": float(match.retail_price) if match.retail_price else None,
                        "in_catalog": True,
                    })

        return alternatives[:limit]


# Global instance
spring_builder_service = SpringBuilderService()
