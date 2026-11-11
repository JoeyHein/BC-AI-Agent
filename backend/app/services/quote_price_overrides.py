"""Quote price overrides. Both default to off.

``quote_replacement_section_pricing``
    Section-only orders (portal Door Face Only / Panels Only, and the same
    hardware scope on an emailed door) sell each steel section at the BC
    item-card list price (``unitPrice``), not the customer's price list.
    A missing or zero list price is flagged and left as Business Central
    priced it. A complete door keeps the customer's price list. The old
    ``quote_replacement_panel_margin`` key is retired and is not read.

``quote_flat_residential_windows``
    Glass kits and inserts on a door whose doorType is residential use one
    rate per window. Default long is $165.00 and short is $120.00, CAD.
    When a GL17, GL18, or GL19 insert shares the door with a GK15 kit of
    the same size, the kit carries that rate and the insert is a fixed
    $0.00 (included in the flat window rate). An insert with no matching
    kit keeps the per-window rate. Commercial doors, including TX450 and
    TX500, stay on the price list even if the part generator emits a GK15.
    A size that is not long or short is flagged and left on the price list.

off does nothing. shadow logs the price it would set and does not change
the quote. on writes a fixed unit price and a note on the quote.

How a replacement-panel request is identified
---------------------------------------------
1. Email. ``map_email_to_configurator`` sets ``request_kind`` to
   ``parts_request`` for replacement parts. The prompt's examples are
   "need 2 replacement panels", "bottom section", "torsion springs", and
   "new struts". ``email_monitor`` then marks the request
   ``needs_manual_pricing`` and does not build a quote, because that
   mapping has no section lines. Springs and struts are parts requests
   and are not section orders. Text is a section request only when it
   says replacement panel(s) or section(s), bottom section, panels only,
   sections only, or loose section(s).
2. Portal and configurator. Hardware scope, shared with
   ``_format_scope_label``: Panels Only (panels on, bottom retainer off,
   no tracks, springs, struts, hardware kits, weather seal, or shafts)
   or Door Face Only (the same, with the bottom retainer on). The
   builder presets post exactly those maps. Empty hardware defaults to
   a complete door.
3. ``part_number_service``. Turning ``panels`` off is an operator-only,
   parts-only, or loose-hardware order and produces no section lines.
   Section lines are category ``panel`` or a steel section prefix
   (PN35, PN36, PN45, PN46, PN47, PN48, PN55, PN56, PN57, PN58, PN65,
   PN75, PN76, PN95). Aluminum full-view sections are not in that list.

Residential window size, from the part number
----------------------------------------------
Long:
    GK15-11xxx-xx  Kanata long (size code 11)
    GK15-55xxx-xx  Craft long (size code 55)
    GL18-          decorative long insert
    GL17-          Craft insert
    A GK15 that does not match GK15-#####-## and whose description says LONG
Short:
    GK15-10xxx-xx  Kanata short (size code 10)
    GL19-          short insert
    A GK15 that does not match GK15-#####-## and whose description says SHORT
Unknown, flagged, not overridden:
    GK15-SSxxx-xx where SS is not 10, 11, or 55
    A GK15 that does not match the pattern and does not say LONG or SHORT
Left unchanged:
    Any window on a door whose doorType is not residential, including a
    GK15 the generator emits for a commercial TX450 or TX500
    GK16-  commercial thermopane
    GK17- and GK19-  aluminum and full-view kits
    Any window on an aluminum door
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Callable, Optional

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

SECTION_PRICING_KEY = "quote_replacement_section_pricing"
FINDER_KEY = "quote_section_finder"
FLAT_WINDOWS_KEY = "quote_flat_residential_windows"
# Retired. A stored value is left in app_settings and is not applied.
RETIRED_MARGIN_KEY = "quote_replacement_panel_margin"

DEFAULT_LONG_PRICE = 165.00
DEFAULT_SHORT_PRICE = 120.00
MODES = ("off", "shadow", "on")
INCLUDED_IN_FLAT_RATE = "included in flat window rate"

# Steel insulated sections. Aluminum full-view (PN10, PN12, PN97) is absent.
STEEL_SECTION_PREFIXES = (
    "PN35-", "PN36-",
    "PN45-", "PN46-", "PN47-", "PN48-",
    "PN55-", "PN56-", "PN57-", "PN58-",
    "PN65-",
    "PN75-", "PN76-",
    "PN95-",
)

_GK15 = re.compile(r"^GK15-(\d{2})\d{3}-\d{2}$", re.I)
_SECTION_TEXT = re.compile(
    r"\b("
    r"replacement\s+(?:panels?|sections?)"
    r"|bottom\s+sections?"
    r"|(?:panels?|sections?)\s+only"
    r"|loose\s+sections?"
    r"|section-only"
    r")\b",
    re.I,
)
_WORD_LONG = re.compile(r"\bLONG\b")
_WORD_SHORT = re.compile(r"\bSHORT\b")

@dataclass(frozen=True)
class PriceOverrideSettings:
    panel_mode: str = "off"
    finder_mode: str = "off"
    window_mode: str = "off"
    long_price: float = DEFAULT_LONG_PRICE
    short_price: float = DEFAULT_SHORT_PRICE

    def as_api(self) -> dict:
        return {
            SECTION_PRICING_KEY: {"mode": self.panel_mode},
            FINDER_KEY: {"mode": self.finder_mode},
            FLAT_WINDOWS_KEY: {
                "mode": self.window_mode,
                "long_price": self.long_price,
                "short_price": self.short_price,
            },
        }


def _mode(value: Any) -> str:
    if isinstance(value, dict):
        value = value.get("mode") or value.get("value") or ""
    mode = str(value or "").strip().lower()
    return mode if mode in MODES else "off"


def _number(value: Any, default: float, *, low: float, high: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if number < low or number > high:
        return default
    return number


def _parse_mode_value(raw: Any) -> str:
    if isinstance(raw, dict):
        return _mode(raw)
    return _mode(raw)


def _parse_windows(raw: Any) -> tuple[str, float, float]:
    if not isinstance(raw, dict):
        return _mode(raw), DEFAULT_LONG_PRICE, DEFAULT_SHORT_PRICE
    return (
        _mode(raw),
        _number(raw.get("long_price"), DEFAULT_LONG_PRICE, low=0.01, high=100000.0),
        _number(raw.get("short_price"), DEFAULT_SHORT_PRICE, low=0.01, high=100000.0),
    )


def _read_setting(db: Optional[Session], key: str) -> Any:
    """Read one AppSettings value. A failure is a missing setting."""
    if db is None:
        return None
    nested = None
    try:
        from app.db.models import AppSettings
        nested = db.begin_nested()
        row = db.query(AppSettings).filter(AppSettings.setting_key == key).first()
        value = None if row is None else row.setting_value
        nested.commit()
        return value
    except Exception:
        logger.warning("Could not read %s; using defaults", key, exc_info=True)
        if nested is not None:
            try:
                nested.rollback()
            except Exception:
                pass
        return None


def load_price_overrides(db: Optional[Session]) -> PriceOverrideSettings:
    panel_mode = _parse_mode_value(_read_setting(db, SECTION_PRICING_KEY))
    finder_mode = _parse_mode_value(_read_setting(db, FINDER_KEY))
    window_mode, long_price, short_price = _parse_windows(_read_setting(db, FLAT_WINDOWS_KEY))
    return PriceOverrideSettings(
        panel_mode=panel_mode,
        finder_mode=finder_mode,
        window_mode=window_mode,
        long_price=long_price,
        short_price=short_price,
    )


def _write_setting(db: Session, key: str, value: dict, description: str, user_id: Optional[int]) -> None:
    from app.db.models import AppSettings
    row = db.query(AppSettings).filter(AppSettings.setting_key == key).first()
    if row is None:
        db.add(AppSettings(
            setting_key=key,
            setting_value=value,
            description=description,
            updated_by=user_id,
        ))
    else:
        row.setting_value = value
        row.description = description
        row.updated_by = user_id
        row.updated_at = datetime.utcnow()
    db.flush()


def save_price_overrides(
    db: Session,
    *,
    user_id: Optional[int] = None,
    panel_mode: Optional[str] = None,
    finder_mode: Optional[str] = None,
    window_mode: Optional[str] = None,
    long_price: Optional[float] = None,
    short_price: Optional[float] = None,
) -> PriceOverrideSettings:
    """Update whichever fields were sent. Omitted fields stay as stored."""
    current = load_price_overrides(db)
    if panel_mode is not None:
        cleaned = str(panel_mode).strip().lower()
        if cleaned not in MODES:
            raise ValueError(f"mode must be one of {MODES}")
        panel_mode = cleaned
    else:
        panel_mode = current.panel_mode
    if finder_mode is not None:
        cleaned = str(finder_mode).strip().lower()
        if cleaned not in MODES:
            raise ValueError(f"mode must be one of {MODES}")
        finder_mode = cleaned
    else:
        finder_mode = current.finder_mode
    if window_mode is not None:
        cleaned = str(window_mode).strip().lower()
        if cleaned not in MODES:
            raise ValueError(f"mode must be one of {MODES}")
        window_mode = cleaned
    else:
        window_mode = current.window_mode
    if long_price is not None:
        long_price = float(long_price)
        if long_price <= 0:
            raise ValueError("long window price must be greater than 0")
    else:
        long_price = current.long_price
    if short_price is not None:
        short_price = float(short_price)
        if short_price <= 0:
            raise ValueError("short window price must be greater than 0")
    else:
        short_price = current.short_price

    _write_setting(
        db,
        SECTION_PRICING_KEY,
        {"mode": panel_mode},
        "Replacement sections use the item-card list price. Off, shadow, or on.",
        user_id,
    )
    _write_setting(
        db,
        FINDER_KEY,
        {"mode": finder_mode},
        "Customer portal replacement section finder. Off, shadow, or on.",
        user_id,
    )
    _write_setting(
        db,
        FLAT_WINDOWS_KEY,
        {"mode": window_mode, "long_price": long_price, "short_price": short_price},
        "Flat price per residential window. Off, shadow, or on.",
        user_id,
    )
    return PriceOverrideSettings(
        panel_mode=panel_mode,
        finder_mode=finder_mode,
        window_mode=window_mode,
        long_price=long_price,
        short_price=short_price,
    )


def replacement_request_kind(text: str) -> str:
    """``section`` or ``other_parts``.

    Email ``parts_request`` covers panels, sections, springs, and struts.
    Only the section phrases are a replacement-panel request.
    """
    if _SECTION_TEXT.search(text or ""):
        return "section"
    return "other_parts"


def note_parts_request(db: Optional[Session], subject: str, body: str) -> None:
    """Log the margin policy for an email parts request.

    The email still has no section lines, so the status is unchanged in
    every mode. off does not log.
    """
    settings = load_price_overrides(db)
    if settings.panel_mode == "off":
        return
    kind = replacement_request_kind(f"{subject or ''}\n{body or ''}")
    label = (
        "a replacement panel or section"
        if kind == "section"
        else "other parts, not a section"
    )
    prefix = "SHADOW " if settings.panel_mode == "shadow" else ""
    logger.info(
        "%s%s: email parts request is %s. "
        "Section lines on a panels-only or door-face-only quote would use "
        "the item-card list price. This email has no section lines, so it "
        "stays in manual pricing.",
        prefix,
        SECTION_PRICING_KEY,
        label,
    )


def section_only_scope(hardware: Optional[dict], door_type: str = "") -> Optional[str]:
    """PANELS ONLY or DOOR FACE ONLY. A complete door and NO DOOR FACE are None.

    Uses the configurator's ``_format_scope_label`` so the two cannot drift.
    A missing hardware key means that component is included, so an empty
    map is a complete door.
    """
    from app.api.door_configurator import _format_scope_label
    label = _format_scope_label(hardware or {}, door_type or "")
    if label in ("PANELS ONLY", "DOOR FACE ONLY"):
        return label
    return None


def _residential_door(door_type: str, door_series: str = "") -> bool:
    """Flat window rates apply only when doorType is residential.

    Series is not a fallback. A commercial TX450 or TX500 stays on the
    price list even when the part generator emits a GK15.
    """
    del door_series
    return (door_type or "").strip().lower() == "residential"


def classify_residential_window(
    part_number: str,
    description: str = "",
    category: str = "",
    door_type: str = "",
    door_series: str = "",
) -> Optional[str]:
    """``long``, ``short``, ``unknown``, or None when the line is not one of these windows."""
    if not _residential_door(door_type, door_series):
        return None
    pn = (part_number or "").strip().upper()
    if pn.startswith(("GK16-", "GK17-", "GK19-")):
        return None
    cat = (category or "").strip().lower()
    if cat in {
        "commercial_window",
        "aluminum_section", "aluminum_glazing", "aluminum_glass",
        "v130g_section", "v130g_glass",
    }:
        return None
    desc = (description or "").upper()
    if pn.startswith("GL19-"):
        return "short"
    if pn.startswith(("GL17-", "GL18-")):
        return "long"
    if not pn.startswith("GK15-"):
        return None
    match = _GK15.match(pn)
    if match is None:
        if _WORD_SHORT.search(desc) and not _WORD_LONG.search(desc):
            return "short"
        if _WORD_LONG.search(desc):
            return "long"
        return "unknown"
    size = match.group(1)
    if size == "10":
        return "short"
    if size in {"11", "55"}:
        return "long"
    return "unknown"


def is_section_panel_line(part: dict) -> bool:
    """A steel section line. Aluminum full-view sections are not included."""
    if not isinstance(part, dict):
        return False
    if part.get("lineType") == "Comment" or part.get("is_note") or part.get("is_door_desc"):
        return False
    cat = (part.get("category") or "").strip().lower()
    if cat in {
        "aluminum_section", "aluminum_glazing", "aluminum_glass",
        "v130g_section", "v130g_glass", "comment",
    }:
        return False
    pn = (part.get("part_number") or "").strip().upper()
    if cat == "panel":
        return True
    return pn.startswith(STEEL_SECTION_PREFIXES)


def _positive_price(raw: Any) -> Optional[float]:
    if raw is None or raw == "":
        return None
    try:
        price = Decimal(str(raw)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except Exception:
        return None
    if price <= 0:
        return None
    return float(price)


def card_list_price(part_number: str) -> Optional[float]:
    """Item-card ``unitPrice``.

    A live Business Central item is used when the fetch succeeds. A zero
    price on that live card is missing. When Business Central cannot be
    reached, the card price in the local item export is the list price.
    """
    import time

    live_item = None
    live_down = False
    try:
        import app.services.pricing_service as pricing
        if time.time() < pricing._cache_expiry and part_number in pricing._bc_cost_cache:
            live_item = pricing._bc_cost_cache.get(part_number)
        else:
            from app.integrations.bc.client import bc_client
            items = bc_client.get_items_by_numbers([part_number]) or {}
            live_item = items.get(part_number)
            if live_item:
                pricing._bc_cost_cache[part_number] = live_item
    except Exception:
        logger.warning("Live list price unavailable for %s", part_number, exc_info=True)
        live_down = True
        live_item = None

    if live_item is not None and not live_down:
        return _positive_price(live_item.get("unitPrice"))
    try:
        from app.services.bc_part_number_mapper import get_bc_mapper
        exported = get_bc_mapper().bc_items.get(part_number) or {}
    except Exception:
        logger.warning("Item-card export unreadable for %s", part_number, exc_info=True)
        return None
    return _positive_price(exported.get("unitPrice"))


def _money(value: float) -> str:
    return f"{float(value):.2f}"


def _matching_kit_sizes(parts: list, door_type: str, door_series: str) -> set:
    """Long/short sizes that have a GK15 kit on this door."""
    sizes = set()
    for part in parts:
        if not isinstance(part, dict):
            continue
        pn = (part.get("part_number") or "").strip().upper()
        if not pn.startswith("GK15-"):
            continue
        kind = classify_residential_window(
            pn,
            part.get("description") or "",
            part.get("category") or "",
            door_type,
            door_series,
        )
        if kind in ("long", "short"):
            sizes.add(kind)
    return sizes


def _insert_included_in_kit(part_number: str, window: str, kit_sizes: set) -> bool:
    """True when this insert shares the door with a GK15 of the same size."""
    pn = (part_number or "").strip().upper()
    if not pn.startswith(("GL17-", "GL18-", "GL19-")):
        return False
    return window in kit_sizes


def _comment(text: str) -> dict:
    return {
        "lineType": "Comment",
        "description": text,
        "category": "COMMENT",
        "is_note": True,
        "pricing_note": True,
    }


def apply_price_overrides(
    parts: list,
    *,
    hardware: Optional[dict],
    door_type: str,
    door_series: str,
    settings: PriceOverrideSettings,
    list_lookup: Optional[Callable[[str], Optional[float]]] = None,
    emit_notes: bool = True,
) -> list:
    """Apply whichever overrides are shadow or on. The list is mutated.

    Quantity is the window or section count already on the line. The unit
    price is the each rate, so one line for six windows is 6 x the rate.
    """
    if settings.panel_mode == "off" and settings.window_mode == "off":
        return parts
    if not isinstance(parts, list):
        return parts

    scope = section_only_scope(hardware, door_type)
    lookup = list_lookup or card_list_price
    kit_sizes = _matching_kit_sizes(parts, door_type, door_series)
    rewritten: list = []

    for part in parts:
        rewritten.append(part)
        if not isinstance(part, dict) or part.get("lineType") == "Comment":
            continue
        if part.get("fixed_unit_price") is not None:
            continue
        pn = part.get("part_number") or ""
        try:
            qty = float(part.get("quantity") or 0)
        except (TypeError, ValueError):
            qty = 0.0

        window = None
        if settings.window_mode != "off":
            window = classify_residential_window(
                pn,
                part.get("description") or "",
                part.get("category") or "",
                door_type,
                door_series,
            )
        if window == "long" or window == "short":
            included = _insert_included_in_kit(pn, window, kit_sizes)
            if included:
                rate = 0.0
                note = f"PRICE NOTE: {pn} {INCLUDED_IN_FLAT_RATE}"
                size_label = INCLUDED_IN_FLAT_RATE
            else:
                rate = settings.long_price if window == "long" else settings.short_price
                note = (
                    f"PRICE NOTE: {pn} flat {window} residential window "
                    f"${_money(rate)} each (qty {qty:g})"
                )
                size_label = window
            if settings.window_mode == "shadow":
                logger.info(
                    "SHADOW %s: %s qty %s would be $%s each (%s); quote unchanged",
                    FLAT_WINDOWS_KEY, pn, qty, _money(rate), size_label,
                )
            else:
                part["fixed_unit_price"] = float(rate)
                part["pricing_override"] = note
                logger.info(
                    "%s: %s qty %s fixed at $%s each (%s)",
                    FLAT_WINDOWS_KEY, pn, qty, _money(rate), size_label,
                )
                if emit_notes:
                    rewritten.append(_comment(note))
            continue
        if window == "unknown":
            flag = f"FLAG: {pn} residential window size unknown; list price kept"
            if settings.window_mode == "shadow":
                logger.info(
                    "SHADOW %s: %s size unknown; would flag and keep the list price",
                    FLAT_WINDOWS_KEY, pn,
                )
            else:
                part["pricing_flag"] = flag
                logger.info("%s: %s", FLAT_WINDOWS_KEY, flag)
                if emit_notes:
                    rewritten.append(_comment(flag))
            continue

        if settings.panel_mode == "off" or not scope or not is_section_panel_line(part):
            continue
        try:
            price = lookup(pn)
        except Exception:
            logger.warning("List price lookup failed for %s", pn, exc_info=True)
            price = None
        if price is None or price <= 0:
            flag = (
                f"FLAG: {pn} replacement section list price missing or zero; "
                "customer price list kept"
            )
            if settings.panel_mode == "shadow":
                logger.info(
                    "SHADOW %s: %s list price missing or zero; would flag and keep the customer price",
                    SECTION_PRICING_KEY, pn,
                )
            else:
                part["pricing_flag"] = flag
                logger.info("%s: %s", SECTION_PRICING_KEY, flag)
                if emit_notes:
                    rewritten.append(_comment(flag))
            continue
        note = (
            f"PRICE NOTE: {pn} replacement section at list price ${_money(price)}"
        )
        if settings.panel_mode == "shadow":
            logger.info(
                "SHADOW %s: %s would be list price $%s; quote unchanged",
                SECTION_PRICING_KEY, pn, _money(price),
            )
        else:
            part["fixed_unit_price"] = price
            part["pricing_override"] = note
            logger.info(
                "%s: %s fixed at list price $%s",
                SECTION_PRICING_KEY, pn, _money(price),
            )
            if emit_notes:
                rewritten.append(_comment(note))

    if emit_notes:
        parts[:] = rewritten
    return parts


def apply_door_price_overrides(
    parts: list,
    door: Any,
    settings: PriceOverrideSettings,
    *,
    list_lookup: Optional[Callable[[str], Optional[float]]] = None,
    emit_notes: bool = True,
) -> list:
    """Read hardware and series off a configurator model or a portal dict."""
    if isinstance(door, dict):
        hardware = door.get("hardware") or {}
        door_type = door.get("doorType") or ""
        door_series = door.get("doorSeries") or ""
    else:
        hardware = getattr(door, "hardware", None) or {}
        door_type = getattr(door, "doorType", "") or ""
        door_series = getattr(door, "doorSeries", "") or ""
    return apply_price_overrides(
        parts,
        hardware=hardware,
        door_type=door_type,
        door_series=door_series,
        settings=settings,
        list_lookup=list_lookup,
        emit_notes=emit_notes,
    )
