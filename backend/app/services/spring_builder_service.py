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
from app.services.spring_calculator_service import SpringCalculatorService, SpringResult, calculate_spring_weight
from app.services.bc_part_number_mapper import BCPartNumberMapper

logger = logging.getLogger(__name__)

# Initialize the existing services
calculator = SpringCalculatorService()
mapper = BCPartNumberMapper()

# ============================================================================
# SHAFT FITMENT COMPONENT WIDTHS (inches, axial dimension on shaft)
# TODO: Replace estimates with verified Canimex dimensions
# ============================================================================
DRUM_WIDTHS = {
    "D400-96":    4.5,
    "D400-144":   4.5,
    "D525-216":   5.5,
    "D800-384":   7.0,
    "D400-54":    4.5,   # high-lift
    "D525-54":    5.5,   # high-lift
    "D575-120":   6.0,   # high-lift
    "D6375-164":  6.5,   # high-lift
    "D800-120":   7.0,   # high-lift
    "850-132":    5.5,   # vertical
    "1100-216":   6.5,   # vertical
    "1350-336":   7.5,   # vertical
}
DRUM_WIDTH_DEFAULT = 5.0

BEARING_END_PLATE_WIDTH = 2.5     # each side
CENTER_BEARING_PLATE_WIDTH = 2.5  # for 4+ spring setups
COUPLER_WIDTH = 3.5               # shaft coupler

WINDER_CONE_WIDTHS = {  # winder + stationary per coil size
    1.75:  2.5,
    2.0:   3.0,
    2.625: 3.5,
    3.75:  4.0,
    6.0:   5.0,
}
WINDER_CONE_WIDTH_DEFAULT = 3.0

CLEARANCE_PER_GAP = 0.25  # gap between components


class SpringBuilderService:
    """Spring builder with catalog integration."""

    def check_shaft_fitment(
        self,
        door_width: float,
        spring_length: float,
        spring_qty: int,
        coil_diameter: float,
        drum_model: str = None,
    ) -> dict:
        """
        Check if springs + shaft components fit within the door width.

        Shaft layout (2-spring):
          [end_plate | drum | winder | SPRING | winder | drum | end_plate]

        Shaft layout (4-spring, 2 shaft pieces):
          [end_plate | drum | winder | SPRING | SPRING | winder | coupler | winder | SPRING | SPRING | winder | drum | end_plate]

        Returns dict with fits (bool), available_width, required_width, breakdown.
        """
        drum_width = DRUM_WIDTHS.get(drum_model, DRUM_WIDTH_DEFAULT)
        winder_width = WINDER_CONE_WIDTHS.get(coil_diameter, WINDER_CONE_WIDTH_DEFAULT)

        # Springs per shaft side (springs are split L/R of center or across shaft pieces)
        # For standard 2-spring: 1 spring each side, no coupler
        # For 4+: springs grouped in pairs per shaft piece with couplers between
        num_couplers = max(0, (spring_qty // 2) - 1)
        num_winder_sets = spring_qty  # each spring needs a winder cone

        # Component widths
        drums_total = 2 * drum_width
        end_plates_total = 2 * BEARING_END_PLATE_WIDTH
        couplers_total = num_couplers * COUPLER_WIDTH
        center_plates_total = num_couplers * CENTER_BEARING_PLATE_WIDTH if num_couplers > 0 else 0
        winders_total = num_winder_sets * winder_width
        springs_total = spring_qty * spring_length

        # Gaps: between each component
        # Rough estimate: 2 end plates + 2 drums + N springs + N winders + couplers + center plates
        num_components = 2 + 2 + spring_qty + num_winder_sets + num_couplers
        gaps_total = num_components * CLEARANCE_PER_GAP

        required_width = (
            drums_total + end_plates_total + couplers_total +
            center_plates_total + winders_total + springs_total + gaps_total
        )

        fits = required_width <= door_width
        margin = door_width - required_width

        return {
            "fits": fits,
            "door_width": door_width,
            "required_width": round(required_width, 2),
            "margin": round(margin, 2),
            "breakdown": {
                "drums": round(drums_total, 2),
                "end_plates": round(end_plates_total, 2),
                "springs": round(springs_total, 2),
                "winder_cones": round(winders_total, 2),
                "couplers": round(couplers_total, 2),
                "center_plates": round(center_plates_total, 2),
                "clearance_gaps": round(gaps_total, 2),
            },
            "note": "Component widths are estimates — verify against Canimex specs" if not fits else None,
        }

    def calculate_and_match(
        self,
        db: Session,
        door_weight: float,
        door_height: int,
        door_width: float = None,
        track_radius: int = 15,
        spring_qty: int = 2,
        target_cycles: int = 10000,
        coil_diameter: float = 2.0,
        drum_model: str = None,
        high_lift_inches: int = 0,
        lift_type: str = "standard_15",
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

        # Cable length depends on lift type
        if lift_type == "vertical":
            cable_length = door_height * 2 + 8
        elif lift_type == "high_lift":
            cable_length = door_height + high_lift_inches + 8
        else:
            cable_length = door_height + 8

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
            "multiplier": result.multiplier,
            "weight": result.weight,
            "pitch": round(result.wire_diameter, 4),
            "cable_length": cable_length,
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
            "shaft_fitment": self.check_shaft_fitment(
                door_width=door_width,
                spring_length=result.length,
                spring_qty=result.spring_quantity,
                coil_diameter=result.coil_diameter,
                drum_model=result.drum_model,
            ) if door_width else None,
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

    def lookup_by_specs(
        self,
        db: Session,
        wire_diameter: float,
        coil_diameter: float,
        wind: str = "LH",
        spring_length: float = None,
    ) -> dict:
        """
        Look up a spring by direct specs (wire, coil, wind) without calculating from door params.
        Returns catalog match, cone sets, and alternatives.
        """
        lh_part = mapper.get_spring_part_number(wire_diameter, coil_diameter, "LH")
        rh_part = mapper.get_spring_part_number(wire_diameter, coil_diameter, "RH")

        lh_match = self._match_sku(db, lh_part.part_number)
        rh_match = self._match_sku(db, rh_part.part_number)

        # If no match, try stepping up wire
        if not lh_match:
            lh_match, stepped_pn = self._try_step_up_wire(db, wire_diameter, coil_diameter, "LH")
            if stepped_pn:
                lh_part.part_number = stepped_pn
        if not rh_match:
            rh_match, stepped_pn = self._try_step_up_wire(db, wire_diameter, coil_diameter, "RH")
            if stepped_pn:
                rh_part.part_number = stepped_pn

        special_order_needed = not lh_match and not rh_match
        cone_sets = self._resolve_cone_sets(coil_diameter)

        return {
            "success": True,
            "mode": "direct_entry",
            "specs": {
                "wire_diameter": wire_diameter,
                "coil_diameter": coil_diameter,
                "length": spring_length,
            },
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

    def convert_spring(
        self,
        db: Session,
        current_wire: float,
        current_coil: float,
        current_length: float,
        current_spring_qty: int = 1,
        replacement_spring_qty: int = 1,
        replacement_coil: float = None,
        replacement_wire: float = None,
    ) -> dict:
        """
        Convert current spring specs to replacement spring specs,
        with catalog matching for the replacement.
        """
        result = calculator.calculate_conversion(
            current_wire=current_wire,
            current_coil=current_coil,
            current_length=current_length,
            current_spring_qty=current_spring_qty,
            replacement_spring_qty=replacement_spring_qty,
            replacement_coil=replacement_coil,
            replacement_wire=replacement_wire,
        )

        if not result.get("success"):
            return result

        # Match replacement to catalog if we have a replacement
        repl = result.get("replacement")
        if repl:
            lh_part = mapper.get_spring_part_number(repl["wire_diameter"], repl["coil_diameter"], "LH")
            rh_part = mapper.get_spring_part_number(repl["wire_diameter"], repl["coil_diameter"], "RH")

            lh_match = self._match_sku(db, lh_part.part_number)
            rh_match = self._match_sku(db, rh_part.part_number)

            if not lh_match:
                lh_match, stepped_pn = self._try_step_up_wire(db, repl["wire_diameter"], repl["coil_diameter"], "LH")
                if stepped_pn:
                    lh_part.part_number = stepped_pn
            if not rh_match:
                rh_match, stepped_pn = self._try_step_up_wire(db, repl["wire_diameter"], repl["coil_diameter"], "RH")
                if stepped_pn:
                    rh_part.part_number = stepped_pn

            result["springs"] = {
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
            }
            result["cone_sets"] = self._resolve_cone_sets(repl["coil_diameter"])
            result["special_order_needed"] = not lh_match and not rh_match

        # Add catalog matching for duplex options
        duplex_options = result.get("duplex_options", [])
        for opt in duplex_options:
            outer = opt["outer"]
            inner = opt["inner"]

            # Match outer springs (6" coil)
            outer_lh = mapper.get_spring_part_number(outer["wire_diameter"], outer["coil_diameter"], "LH")
            outer_rh = mapper.get_spring_part_number(outer["wire_diameter"], outer["coil_diameter"], "RH")
            outer["lh_part"] = outer_lh.part_number
            outer["rh_part"] = outer_rh.part_number
            outer["in_stock"] = self._match_sku(db, outer_lh.part_number) is not None

            # Match inner springs (3.75" coil)
            inner_lh = mapper.get_spring_part_number(inner["wire_diameter"], inner["coil_diameter"], "LH")
            inner_rh = mapper.get_spring_part_number(inner["wire_diameter"], inner["coil_diameter"], "RH")
            inner["lh_part"] = inner_lh.part_number
            inner["rh_part"] = inner_rh.part_number
            inner["in_stock"] = self._match_sku(db, inner_lh.part_number) is not None

            # Cone sets for both coils
            opt["outer_cones"] = self._resolve_cone_sets(outer["coil_diameter"])
            opt["inner_cones"] = self._resolve_cone_sets(inner["coil_diameter"])
            opt["both_in_stock"] = outer["in_stock"] and inner["in_stock"]

        return result

    def get_drum_list(self, lift_type: str) -> list:
        """Return available drum models for a given lift type."""
        if lift_type in ("high_lift",):
            drums = list(calculator.hl_drum_multipliers.keys())
        elif lift_type in ("vertical",):
            drums = list(calculator.vl_drum_multipliers.keys())
        else:
            drums = list(calculator.drum_multipliers.keys())
        return sorted(drums)


# Global instance
spring_builder_service = SpringBuilderService()
