"""Dump every input that goes into the legacy pricing formula, so we can
reverse-engineer the GNB multiplier grid from the same data the engine uses."""
import json
from app.db.database import SessionLocal
from app.db.models import AppSettings
from app.services.pricing_service import (
    TIER_MARGINS_KEY, COST_ADJUSTMENTS_KEY, PREFIX_MARGINS_KEY,
    BC_GROUP_MAPPING_KEY, get_default_tier_margins, get_default_cost_adjustments,
)


def show(db, key, default_fn=None):
    setting = db.query(AppSettings).filter(AppSettings.setting_key == key).first()
    is_custom = bool(setting and setting.setting_value)
    val = setting.setting_value if is_custom else (default_fn() if default_fn else None)
    label = "AppSettings (production override)" if is_custom else "code default"
    print(f"--- {key} [{label}] ---")
    print(json.dumps(val, indent=2, default=str))
    print()


def main():
    db = SessionLocal()
    try:
        show(db, TIER_MARGINS_KEY, get_default_tier_margins)
        show(db, COST_ADJUSTMENTS_KEY, get_default_cost_adjustments)
        show(db, PREFIX_MARGINS_KEY)
        show(db, BC_GROUP_MAPPING_KEY)
    finally:
        db.close()


if __name__ == "__main__":
    main()
