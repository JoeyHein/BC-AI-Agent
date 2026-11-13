"""Freight estimator switch and the editable rating numbers.

``freight_estimator`` is off or on. A missing row is off, so turning the
tool on does not need a migration. Fuel, the LONG charge, the density
factor, and the crate and operator constants live in
``freight_estimator_config``. Missing keys keep the defaults.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

MODES = ("off", "on")
FLAG_KEY = "freight_estimator"
CONFIG_KEY = "freight_estimator_config"

DEFAULT_CONFIG = {
    "fuel_percent": 68.80,
    # Per long piece. Manitoulin has not confirmed whether FLT is once per
    # shipment. Do not change this to a single shipment charge until they do.
    "long_charge": 75,
    "long_min_length_in": 96,
    "density_lb_per_cuft": 10,
    "gst_percent": 5,
}

_FLAG_DESCRIPTION = "Ship-weight and Manitoulin freight estimator. Off or on."
_CONFIG_DESCRIPTION = "Fuel percent, LONG charge, density, and crate and operator overrides for the freight estimator."


def _read(db: Optional[Session], key: str):
    if db is None:
        return None
    nested = None
    try:
        from app.db.models import AppSettings
        nested = db.begin_nested()
        row = db.query(AppSettings).filter(AppSettings.setting_key == key).first()
        nested.commit()
        return row
    except Exception:
        logger.warning("Could not read %s; treating the freight estimator as off", key, exc_info=True)
        if nested is not None:
            try:
                nested.rollback()
            except Exception:
                pass
        return None


def freight_estimator_mode(db: Optional[Session]) -> str:
    row = _read(db, FLAG_KEY)
    if row is None or row.setting_value in (None, ""):
        return "off"
    raw = row.setting_value
    if isinstance(raw, dict):
        raw = raw.get("mode") or raw.get("value") or ""
    mode = str(raw).strip().lower()
    return mode if mode in MODES else "off"


def freight_estimator_enabled(db: Optional[Session]) -> bool:
    return freight_estimator_mode(db) == "on"


def set_freight_estimator_mode(db: Session, mode: str, user_id: Optional[int] = None) -> str:
    from app.db.models import AppSettings
    cleaned = str(mode).strip().lower()
    if cleaned not in MODES:
        raise ValueError("mode must be off or on")
    row = db.query(AppSettings).filter(AppSettings.setting_key == FLAG_KEY).first()
    if row is None:
        row = AppSettings(
            setting_key=FLAG_KEY,
            setting_value=cleaned,
            description=_FLAG_DESCRIPTION,
            updated_by=user_id,
        )
        db.add(row)
    else:
        row.setting_value = cleaned
        row.updated_by = user_id
        row.updated_at = datetime.utcnow()
    db.flush()
    return cleaned


def freight_estimator_config(db: Optional[Session]) -> dict:
    config = dict(DEFAULT_CONFIG)
    row = _read(db, CONFIG_KEY)
    stored = row.setting_value if row is not None else None
    if isinstance(stored, dict):
        for key in DEFAULT_CONFIG:
            if stored.get(key) is not None:
                config[key] = stored[key]
        for key in ("crate", "operator_lb", "shaft_lb_per_ft", "drum_lb_each"):
            if isinstance(stored.get(key), dict):
                config[key] = stored[key]
        for key in ("bearing_lb_each", "winding_cone_lb_each", "stationary_cone_lb_each", "coupler_lb_each"):
            if stored.get(key) is not None:
                config[key] = stored[key]
    return config


def set_freight_estimator_config(db: Session, updates: dict, user_id: Optional[int] = None) -> dict:
    from app.db.models import AppSettings
    current = freight_estimator_config(db)
    for key, value in (updates or {}).items():
        if value is None:
            continue
        current[key] = value
    row = db.query(AppSettings).filter(AppSettings.setting_key == CONFIG_KEY).first()
    if row is None:
        row = AppSettings(
            setting_key=CONFIG_KEY,
            setting_value=current,
            description=_CONFIG_DESCRIPTION,
            updated_by=user_id,
        )
        db.add(row)
    else:
        row.setting_value = current
        row.updated_by = user_id
        row.updated_at = datetime.utcnow()
    db.flush()
    return freight_estimator_config(db)
