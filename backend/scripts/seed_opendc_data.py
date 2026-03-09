"""
Seed OPENDC reference data: stocked inside diameters + system config keys.
Run: cd backend && python -m scripts.seed_opendc_data
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime
from app.db.database import SessionLocal
from app.db.models import StockedInsideDiameter, DrumType, AppSettings


def seed():
    db = SessionLocal()
    try:
        # --- Stocked Inside Diameters (4 fixed rows) ---
        existing = db.query(StockedInsideDiameter).count()
        if existing == 0:
            diameters = [
                StockedInsideDiameter(inside_diameter=2.0, description='2"', is_active=True, created_at=datetime.utcnow()),
                StockedInsideDiameter(inside_diameter=2.625, description='2-5/8"', is_active=True, created_at=datetime.utcnow()),
                StockedInsideDiameter(inside_diameter=3.75, description='3-3/4"', is_active=True, created_at=datetime.utcnow()),
                StockedInsideDiameter(inside_diameter=6.0, description='6"', is_active=True, created_at=datetime.utcnow()),
            ]
            db.add_all(diameters)
            print(f"Seeded {len(diameters)} stocked inside diameters")
        else:
            print(f"Stocked inside diameters already seeded ({existing} rows)")

        # --- Drum Types (from door_calculator_service.py data) ---
        existing_drums = db.query(DrumType).count()
        if existing_drums == 0:
            drums = [
                # Standard lift drums
                DrumType(drum_model="D400-96", radius_inches=2.0, lift_type="standard", max_door_height_inches=96, description="Standard 2\" radius, up to 8'", created_at=datetime.utcnow()),
                DrumType(drum_model="D400-144", radius_inches=2.0, lift_type="standard", max_door_height_inches=144, description="Standard 2\" radius, up to 12'", created_at=datetime.utcnow()),
                DrumType(drum_model="D525-216", radius_inches=2.625, lift_type="standard", max_door_height_inches=216, description="Standard 2-5/8\" radius, up to 18'", created_at=datetime.utcnow()),
                DrumType(drum_model="D800-384", radius_inches=4.0, lift_type="standard", max_door_height_inches=384, description="Standard 4\" radius, up to 32'", created_at=datetime.utcnow()),
                # High-lift drums
                DrumType(drum_model="D400-54", radius_inches=2.0, lift_type="high_lift", max_door_height_inches=54, description="High-lift 2\" radius", created_at=datetime.utcnow()),
                DrumType(drum_model="D525-54", radius_inches=2.625, lift_type="high_lift", max_door_height_inches=54, description="High-lift 2-5/8\" radius", created_at=datetime.utcnow()),
                DrumType(drum_model="D575-120", radius_inches=2.875, lift_type="high_lift", max_door_height_inches=120, description="High-lift 2-7/8\" radius", created_at=datetime.utcnow()),
                # Vertical lift drums
                DrumType(drum_model="850-132", radius_inches=4.25, lift_type="vertical", max_door_height_inches=132, description="Vertical 4-1/4\" radius", created_at=datetime.utcnow()),
                DrumType(drum_model="1100-216", radius_inches=5.5, lift_type="vertical", max_door_height_inches=216, description="Vertical 5-1/2\" radius", created_at=datetime.utcnow()),
                DrumType(drum_model="1350-336", radius_inches=6.75, lift_type="vertical", max_door_height_inches=336, description="Vertical 6-3/4\" radius", created_at=datetime.utcnow()),
            ]
            db.add_all(drums)
            print(f"Seeded {len(drums)} drum types")
        else:
            print(f"Drum types already seeded ({existing_drums} rows)")

        # --- System Config Keys in AppSettings ---
        config_keys = {
            "catalog_builder_enabled": {
                "value": False,
                "description": "Enable/disable nightly catalog builder agent sync"
            },
            "inventory_agent_enabled": {
                "value": False,
                "description": "Enable/disable inventory review agent (runs every 6 hours)"
            },
            "inventory_agent_observe_until": {
                "value": None,
                "description": "Observation period end date (ISO format). Agent only observes, no action until this date passes."
            },
            "po_agent_enabled": {
                "value": False,
                "description": "Enable/disable PO generation agent"
            },
            "po_agent_mode": {
                "value": "draft_only",
                "description": "PO agent mode: draft_only, pending_approval, auto_approve"
            },
            "po_agent_draft_only_until": {
                "value": None,
                "description": "30-day draft-only period end date (ISO format). No auto-approve before this."
            },
        }

        for key, cfg in config_keys.items():
            existing_setting = db.query(AppSettings).filter(AppSettings.setting_key == key).first()
            if not existing_setting:
                setting = AppSettings(
                    setting_key=key,
                    setting_value=cfg["value"],
                    description=cfg["description"],
                    updated_at=datetime.utcnow(),
                )
                db.add(setting)
                print(f"  Seeded config: {key} = {cfg['value']}")
            else:
                print(f"  Config already exists: {key}")

        db.commit()
        print("\nSeed complete!")

    except Exception as e:
        db.rollback()
        print(f"Error: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    seed()
