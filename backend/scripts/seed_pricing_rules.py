"""
Seed pricing rules for quote generation
Run this to populate the database with sample pricing rules
"""

import sys
from pathlib import Path

# Add backend directory to path
backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

from app.db.database import SessionLocal
from app.db.models import PricingRule
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def seed_pricing_rules():
    """Seed the database with sample pricing rules"""
    db = SessionLocal()

    try:
        # Clear existing rules
        existing_count = db.query(PricingRule).count()
        if existing_count > 0:
            logger.info(f"Clearing {existing_count} existing pricing rules...")
            db.query(PricingRule).delete()
            db.commit()

        rules = [
            # ============================================================================
            # BASE PRICING RULES - Door Models
            # ============================================================================
            {
                "rule_type": "base_price",
                "entity": "TX450",
                "condition": None,  # Always applies
                "action": {"price": 1200.00},
                "priority": 10,
                "description": "Base price for TX450 model (10x10)"
            },
            {
                "rule_type": "base_price",
                "entity": "AL976",
                "condition": None,
                "action": {"price": 1500.00},
                "priority": 10,
                "description": "Base price for AL976 model (10x10)"
            },
            {
                "rule_type": "base_price",
                "entity": "AL976-SWD",
                "condition": None,
                "action": {"price": 1650.00},
                "priority": 10,
                "description": "Base price for AL976-SWD model (10x10)"
            },
            {
                "rule_type": "base_price",
                "entity": "Solalite",
                "condition": None,
                "action": {"price": 1800.00},
                "priority": 10,
                "description": "Base price for Solalite model (10x10)"
            },
            {
                "rule_type": "base_price",
                "entity": "Kanata",
                "condition": None,
                "action": {"price": 1400.00},
                "priority": 10,
                "description": "Base price for Kanata model (10x10)"
            },
            {
                "rule_type": "base_price",
                "entity": "Craft",
                "condition": None,
                "action": {"price": 1600.00},
                "priority": 10,
                "description": "Base price for Craft model (10x10)"
            },

            # ============================================================================
            # VOLUME DISCOUNTS
            # ============================================================================
            {
                "rule_type": "base_price",
                "entity": None,  # Applies to all models
                "condition": {"min_qty": 5, "max_qty": 9},
                "action": {"discount_percent": 5},
                "priority": 20,
                "description": "5% discount for 5-9 doors"
            },
            {
                "rule_type": "base_price",
                "entity": None,
                "condition": {"min_qty": 10, "max_qty": 19},
                "action": {"discount_percent": 10},
                "priority": 20,
                "description": "10% discount for 10-19 doors"
            },
            {
                "rule_type": "base_price",
                "entity": None,
                "condition": {"min_qty": 20},
                "action": {"discount_percent": 15},
                "priority": 20,
                "description": "15% discount for 20+ doors"
            },

            # ============================================================================
            # CUSTOMER TIER DISCOUNTS
            # ============================================================================
            {
                "rule_type": "base_price",
                "entity": None,
                "condition": {"customer_tier": "preferred"},
                "action": {"discount_percent": 7},
                "priority": 15,
                "description": "7% discount for preferred customers"
            },
            {
                "rule_type": "base_price",
                "entity": None,
                "condition": {"customer_tier": "wholesale"},
                "action": {"discount_percent": 12},
                "priority": 15,
                "description": "12% discount for wholesale customers"
            },
            {
                "rule_type": "base_price",
                "entity": None,
                "condition": {"customer_tier": "contractor"},
                "action": {"discount_percent": 10},
                "priority": 15,
                "description": "10% discount for contractor accounts"
            },

            # ============================================================================
            # HARDWARE PRICING
            # ============================================================================
            {
                "rule_type": "hardware",
                "entity": "2",  # 2" track
                "condition": None,
                "action": {"price": 200.00},
                "priority": 10,
                "description": "Base price for 2\" track (10x10)"
            },
            {
                "rule_type": "hardware",
                "entity": "3",  # 3" track
                "condition": None,
                "action": {"price": 300.00},
                "priority": 10,
                "description": "Base price for 3\" track (10x10)"
            },

            # ============================================================================
            # GLAZING PRICING
            # ============================================================================
            {
                "rule_type": "glazing",
                "entity": "thermopane",
                "condition": None,
                "action": {"price": 400.00},
                "priority": 10,
                "description": "Thermopane glazing price (10x10)"
            },
            {
                "rule_type": "glazing",
                "entity": "single pane",
                "condition": None,
                "action": {"price": 250.00},
                "priority": 10,
                "description": "Single pane glazing price (10x10)"
            },
            {
                "rule_type": "glazing",
                "entity": "single glass",
                "condition": None,
                "action": {"price": 250.00},
                "priority": 10,
                "description": "Single glass glazing price (10x10)"
            },
            {
                "rule_type": "glazing",
                "entity": "polycarbonate",
                "condition": None,
                "action": {"price": 300.00},
                "priority": 10,
                "description": "Polycarbonate glazing price (10x10)"
            },
        ]

        # Insert rules
        for rule_data in rules:
            rule = PricingRule(**rule_data)
            db.add(rule)

        db.commit()

        logger.info(f"✅ Successfully seeded {len(rules)} pricing rules")

        # Display summary
        logger.info("\n" + "="*60)
        logger.info("PRICING RULES SUMMARY")
        logger.info("="*60)

        by_type = {}
        for rule_data in rules:
            rule_type = rule_data["rule_type"]
            by_type[rule_type] = by_type.get(rule_type, 0) + 1

        for rule_type, count in by_type.items():
            logger.info(f"  {rule_type}: {count} rules")

        logger.info("="*60 + "\n")

    except Exception as e:
        logger.error(f"❌ Error seeding pricing rules: {e}")
        db.rollback()
        raise

    finally:
        db.close()


if __name__ == "__main__":
    logger.info("Starting pricing rules seed...")
    seed_pricing_rules()
    logger.info("Pricing rules seed complete!")
