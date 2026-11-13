"""Switches for the quote-inbox follow-ups. Each one defaults to off.

off leaves today's behaviour. shadow logs what would happen and does not
create a draft, a quote, or a convert-to-SO row. on does the work and
still never sends mail on its own.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

MODES = ("off", "shadow", "on")

ATTACHMENT_READING = "email_attachment_reading"
MISSING_INFO_REPLY = "missing_info_reply"
QUOTE_SEND_DRAFT = "quote_send_draft"
CUSTOMER_APPROVAL = "customer_approval_detection"
QUOTE_PO_AUTO_CONVERT = "quote_po_auto_convert"
WINDOW_PATTERNS = "quote_window_patterns"
OPENER_MAPPING = "quote_opener_mapping"
STRUTS_PER_SECTION = "quote_struts_per_section"
CRATING_HISTORY = "quote_crating_history"
KANATA_SERIES_HISTORY = "quote_kanata_series_history"
ADJUSTABLE_PREP = "quote_adjustable_prep"
SERIES_FALLBACK = "quote_series_fallback"

INBOX_SETTING_KEYS = (
    ATTACHMENT_READING,
    MISSING_INFO_REPLY,
    QUOTE_SEND_DRAFT,
    CUSTOMER_APPROVAL,
    QUOTE_PO_AUTO_CONVERT,
    WINDOW_PATTERNS,
    OPENER_MAPPING,
    STRUTS_PER_SECTION,
    CRATING_HISTORY,
    KANATA_SERIES_HISTORY,
    ADJUSTABLE_PREP,
    SERIES_FALLBACK,
)

_DESCRIPTIONS = {
    ATTACHMENT_READING: "Read PDF and drawing attachments on a quote email. Off, shadow, or on.",
    MISSING_INFO_REPLY: "Draft one reply listing what a quote email still needs. Off, shadow, or on.",
    QUOTE_SEND_DRAFT: "Draft a threaded reply with the SQ PDF. Off, shadow, or on.",
    CUSTOMER_APPROVAL: "Queue a convert-to-SO when a customer approves a quote. Off, shadow, or on.",
    QUOTE_PO_AUTO_CONVERT: "Convert the matching open quote when a customer emails a purchase order. Off, shadow, or on.",
    WINDOW_PATTERNS: "Turn a window count or staggered pattern into glass kits per section. Off, shadow, or on.",
    OPENER_MAPPING: "Map opener and keypad wording to catalog part numbers. Off, shadow, or on.",
    STRUTS_PER_SECTION: "Put a strut on every section when the email or profile asks. Off, shadow, or on.",
    CRATING_HISTORY: "Add crating from the email or the customer's history, and record pickup versus freight. Off, shadow, or on.",
    KANATA_SERIES_HISTORY: "Count Kanata PN65 panels in the series history. Off, shadow, or on.",
    ADJUSTABLE_PREP: "Record adjustable or opener prep when the email asks. Off, shadow, or on.",
    SERIES_FALLBACK: "When the asked series cannot be built in that colour and design, use the closest series that can. Off, shadow, or on.",
}


def inbox_mode(db: Optional[Session], key: str) -> str:
    """Missing setting, missing table, or a bad value is off.

    The read uses a savepoint. ``inspect().has_table`` commits the SQLite
    connection and would drop an email row that has been flushed but not
    committed yet.
    """
    if db is None or key not in INBOX_SETTING_KEYS:
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


def inbox_modes(db: Optional[Session]) -> dict:
    return {key: inbox_mode(db, key) for key in INBOX_SETTING_KEYS}


def set_inbox_mode(db: Session, key: str, mode: str, user_id: Optional[int] = None) -> str:
    from app.db.models import AppSettings
    if key not in INBOX_SETTING_KEYS:
        raise ValueError(f"Unknown inbox setting {key}")
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
