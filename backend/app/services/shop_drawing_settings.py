"""Shop-drawing switches. Each one defaults to off.

off leaves today's drawing. on uses the supplier profile. The value lives
in app_settings, and a missing row is off, so turning the switch on does
not need a migration.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

MODES = ("off", "on")

REAL_PROFILES = "shop_drawing_real_profiles"

SHOP_DRAWING_SETTING_KEYS = (REAL_PROFILES,)

_DESCRIPTIONS = {
    REAL_PROFILES: "Draw Upwardor panel profiles and jamb sideroom on shop drawings. Off or on.",
}


def shop_drawing_mode(db: Optional[Session], key: str) -> str:
    """Missing setting, missing table, or a bad value is off.

    The read uses a savepoint. ``inspect().has_table`` commits the SQLite
    connection and would drop a row that has been flushed but not committed.
    """
    if db is None or key not in SHOP_DRAWING_SETTING_KEYS:
        return "off"
    nested = None
    try:
        from app.db.models import AppSettings
        nested = db.begin_nested()
        row = db.query(AppSettings).filter(AppSettings.setting_key == key).first()
        nested.commit()
    except Exception:
        logger.warning("Could not read %s; treating it as off", key, exc_info=True)
        if nested is not None:
            try:
                nested.rollback()
            except Exception:
                pass
        return "off"
    if row is None or row.setting_value in (None, ""):
        return "off"
    raw = row.setting_value
    if isinstance(raw, dict):
        raw = raw.get("mode") or raw.get("value") or ""
    mode = str(raw).strip().lower()
    return mode if mode in MODES else "off"


def shop_drawing_modes(db: Optional[Session]) -> dict:
    return {key: shop_drawing_mode(db, key) for key in SHOP_DRAWING_SETTING_KEYS}


def real_profiles_enabled(db: Optional[Session]) -> bool:
    return shop_drawing_mode(db, REAL_PROFILES) == "on"


def set_shop_drawing_mode(db: Session, key: str, mode: str, user_id: Optional[int] = None) -> str:
    from app.db.models import AppSettings
    if key not in SHOP_DRAWING_SETTING_KEYS:
        raise ValueError(f"Unknown shop drawing setting {key}")
    cleaned = str(mode).strip().lower()
    if cleaned not in MODES:
        raise ValueError(f"mode must be one of {MODES}")
    row = db.query(AppSettings).filter(AppSettings.setting_key == key).first()
    if row is None:
        row = AppSettings(
            setting_key=key,
            setting_value=cleaned,
            description=_DESCRIPTIONS[key],
            updated_by=user_id,
        )
        db.add(row)
    else:
        row.setting_value = cleaned
        row.updated_by = user_id
        row.updated_at = datetime.utcnow()
    db.flush()
    return cleaned
