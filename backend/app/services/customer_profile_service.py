"""Customer ordering profiles.

A profile is keyed by BC customer id. History seeding reads order and
invoice lines (read-only) and records, for each field, the value, how
often it appeared, and a one-line evidence string. A staff edit locks
that field. Locked values are not replaced by a later seed, and when a
quote leaves the field blank the lock wins over the email-mapper default.

Quoting calls ``apply_customer_profile`` after the AI mapper. Each field
is tagged email, profile, or default. Conflicts with a lock, silent
bracket-to-angle substitutions, and unstocked colour swaps are appended
to the quote's deviations list.
"""
from __future__ import annotations

import logging
import re
from collections import Counter
from datetime import datetime
from difflib import SequenceMatcher
from typing import Any, Dict, Iterable, List, Optional, Sequence

from sqlalchemy.orm import Session

from app.db.models import BCCustomer, CustomerProfile

logger = logging.getLogger(__name__)

# off: today's quote path. Nothing in this module changes a live quote.
# shadow: compute the profile result, store it, and log it. The quote
#         that goes to Business Central is unchanged.
# on: the profile, the wider customer match, and quote-number lookup
#     are what the quote and the conversion use.
QUOTING_MODE_KEY = "customer_profile_quoting"
QUOTING_MODES = ("off", "shadow", "on")


def quoting_mode(db: Optional[Session]) -> str:
    """Current switch. Missing setting, missing table, or a bad value is off.

    Production stays on the old path until someone sets this to shadow or
    on. A database that has not been migrated yet also stays off, so a
    flag flip before ``alembic upgrade`` cannot take quoting down.
    """
    if db is None:
        return "off"
    try:
        from sqlalchemy import inspect
        bind = db.get_bind()
        if bind is None or not inspect(bind).has_table("app_settings"):
            return "off"
        from app.db.models import AppSettings
        row = (
            db.query(AppSettings)
            .filter(AppSettings.setting_key == QUOTING_MODE_KEY)
            .first()
        )
    except Exception:
        logger.warning("Could not read %s; treating it as off", QUOTING_MODE_KEY, exc_info=True)
        return "off"
    if row is None or row.setting_value in (None, ""):
        return "off"
    raw = row.setting_value
    if isinstance(raw, dict):
        raw = raw.get("mode") or raw.get("value") or ""
    mode = str(raw).strip().lower()
    if mode not in QUOTING_MODES:
        return "off"
    if mode == "off":
        return "off"
    try:
        from sqlalchemy import inspect
        if not inspect(db.get_bind()).has_table("customer_profiles"):
            logger.error(
                "%s is %s but customer_profiles does not exist yet; staying off",
                QUOTING_MODE_KEY, mode,
            )
            return "off"
    except Exception:
        return "off"
    return mode


def set_quoting_mode(db: Session, mode: str, user_id: Optional[int] = None) -> str:
    """Persist the switch. Unknown values are rejected by the caller."""
    from app.db.models import AppSettings
    cleaned = str(mode).strip().lower()
    if cleaned not in QUOTING_MODES:
        raise ValueError(f"mode must be one of {QUOTING_MODES}")
    row = (
        db.query(AppSettings)
        .filter(AppSettings.setting_key == QUOTING_MODE_KEY)
        .first()
    )
    if row is None:
        row = AppSettings(
            setting_key=QUOTING_MODE_KEY,
            setting_value=cleaned,
            description="Customer profile quoting: off, shadow, or on. Default off.",
            updated_by=user_id,
        )
        db.add(row)
    else:
        row.setting_value = cleaned
        row.updated_by = user_id
        row.updated_at = datetime.utcnow()
    db.flush()
    return cleaned


def legacy_customer_id(db: Session, email: Optional[str], company_name: Optional[str]) -> Optional[str]:
    """Exact email, then exact company name. No match means retail pricing."""
    email_text = (email or "").strip()
    name = (company_name or "").strip()
    match = None
    if email_text:
        match = db.query(BCCustomer).filter(BCCustomer.email.ilike(email_text)).first()
    if match is None and name:
        match = db.query(BCCustomer).filter(BCCustomer.company_name.ilike(name)).first()
    return match.bc_customer_id if match else None

# Fields the profile stores, in the order the staff editor shows them.
FIELD_SPECS = (
    ("track_mount", "Track mount", ("bracket", "angle")),
    ("track_size", "Track size", ("2", "3")),
    ("track_radius", "Track radius", ("12", "15", "20")),
    ("lift_type", "Lift", ("standard", "low_headroom", "high_lift", "vertical")),
    ("door_series", "Series", ()),
    ("panel_color", "Colour", ()),
    ("panel_design", "Panel design", ()),
    ("windows", "Windows", ("yes", "no")),
    ("glass", "Glass", ()),
    ("operator", "Operator", ()),
    ("accessories", "Accessories", ()),
    ("delivery_type", "Pickup / delivery", ("pickup", "delivery")),
)

# Profile key -> configurator door key. delivery_type is quote-level.
DOOR_KEYS = {
    "track_mount": "trackMount",
    "track_size": "trackThickness",
    "track_radius": "trackRadius",
    "lift_type": "liftType",
    "door_series": "doorSeries",
    "panel_color": "panelColor",
    "panel_design": "panelDesign",
    "windows": "hasWindows",
    "glass": "glazingType",
    "operator": "operator",
    "accessories": "operatorAccessories",
}

# Inferred values are applied only once the same choice shows up on most
# of at least two orders. A lock applies immediately.
MIN_SUPPORT = 2
MIN_CONFIDENCE = 0.6

FREE_MAIL_DOMAINS = frozenset({
    "gmail.com", "googlemail.com", "outlook.com", "hotmail.com", "live.com",
    "live.ca", "yahoo.com", "yahoo.ca", "icloud.com", "me.com", "aol.com",
    "msn.com", "proton.me", "protonmail.com", "pm.me", "gmx.com", "mail.com",
})

_NAME_STOP = frozenset({
    "inc", "ltd", "llc", "co", "corp", "corporation", "company", "the",
    "and", "limited", "incorporated",
})

_TRACK_RE = re.compile(
    r"^TR(?P<size>02|03|25)-(?P<kind>STD|VL|LHR|HL|EXT)(?P<mount>BM|AM)?",
    re.IGNORECASE,
)
_ANGLE_RE = re.compile(
    r"\bangle(?:\s*|-)?mount(?:ed)?\b|\bcontinuous\s+angle\b|\bmount(?:ed)?\s*(?:is|:)?\s*angle\b",
    re.IGNORECASE,
)
_BRACKET_RE = re.compile(
    r"\bbracket(?:\s*|-)?mount(?:ed)?\b|\bmount(?:ed)?\s*(?:is|:)?\s*brackets?\b",
    re.IGNORECASE,
)
_BARE_ANGLE_RE = re.compile(r"\bangle\b", re.IGNORECASE)
_BARE_BRACKET_RE = re.compile(r"\bbrackets?\b", re.IGNORECASE)
_PICKUP_RE = re.compile(r"\bpick[\s-]?up\b|\bwill\s+call\b|\bcustomer\s+pick", re.IGNORECASE)
_DELIVERY_RE = re.compile(r"\bdeliver(?:y|ed|ing)?\b|\bship\s+to\b", re.IGNORECASE)
_TRACK3_RE = re.compile(
    r"""\b3\s*(?:"|''|inch|in\.?)\s*track\b|\btrack\s*(?:size|thickness)?\s*[:=]?\s*3\b""",
    re.IGNORECASE,
)
_TRACK2_RE = re.compile(
    r"""\b2\s*(?:"|''|inch|in\.?)\s*track\b|\btrack\s*(?:size|thickness)?\s*[:=]?\s*2\b""",
    re.IGNORECASE,
)
_RADIUS_RE = re.compile(r"\b(12|15|20)\s*(?:\"|''|inch)\s*radius\b", re.IGNORECASE)
_LIFT_RES = (
    ("low_headroom", re.compile(r"\blow\s*head\s*room\b|\blow\s*headroom\b|\blhr\b", re.I)),
    ("high_lift", re.compile(r"\bhigh\s*lift\b", re.I)),
    ("vertical", re.compile(r"\bvertical\s*lift\b", re.I)),
    ("standard", re.compile(r"\bstandard\s*lift\b", re.I)),
)
_SERIES_RE = re.compile(
    r"\b(TX450-20|TX500-20|TX450|TX500|TX380|TX760|KANATA|CRAFT|AL976|PANORAMA|SOLALITE|SWD)\b",
    re.IGNORECASE,
)
_FREIGHT_NUMBERS = frozenset({"FREIGHT", "SHIPPING", "FREIGHT-OUT"})
_SERIES_PREFIX = {
    "PN40": "TX380",
    "PN45": "TX450",
    "PN46": "TX450",
    "PN50": "TX500",
    "PN51": "TX500",
    "PN80": "PANORAMA",
    "PN97": "AL976",
}
_COLOUR_WORDS = (
    "CLEAR ANODIZED", "FRENCH OAK", "ENGLISH CHESTNUT", "STEEL GREY", "IRON ORE",
    "NEW BROWN", "NEW ALMOND", "SANDTONE", "HAZELWOOD", "WALNUT", "BRONZE",
    "WHITE", "BLACK", "BROWN", "ALMOND",
)
_DESIGN_WORDS = ("FLUSH", "UDC", "SHXL", "BCXL", "TRAFALGAR", "MUSKOKA")
_LIFT_FROM_KIND = {
    "STD": "standard",
    "VL": "vertical",
    "LHR": "low_headroom",
    "HL": "high_lift",
    "EXT": "high_lift",
}


def field_catalog() -> List[dict]:
    """Editor metadata: key, label, and the closed set of choices when there is one."""
    return [
        {"key": key, "label": label, "choices": list(choices)}
        for key, label, choices in FIELD_SPECS
    ]


def _label(value: Any) -> str:
    if value is None:
        return "unset"
    text = str(value).strip()
    if text in {"2", "3"}:
        return f'{text}"'
    return text.replace("_", " ")


def _norm(value: Any) -> str:
    if isinstance(value, bool):
        return "yes" if value else "no"
    if value is None:
        return ""
    return str(value).strip().lower().replace("_", " ")


def _same(a: Any, b: Any) -> bool:
    return _norm(a) == _norm(b)


def is_applicable(field: Optional[dict]) -> bool:
    """A lock always applies. History applies once it is the usual choice."""
    if not field or field.get("value") in (None, "", []):
        return False
    if field.get("locked"):
        return True
    try:
        total = int(field.get("total") or 0)
        confidence = float(field.get("confidence") or 0)
    except (TypeError, ValueError):
        return False
    return total >= MIN_SUPPORT and confidence >= MIN_CONFIDENCE


def _blank_profile(bc_customer_id: str, customer_number: Optional[str] = None) -> CustomerProfile:
    return CustomerProfile(
        bc_customer_id=bc_customer_id,
        customer_number=customer_number,
        fields={},
        contacts=[],
        email_domains=[],
        ship_to=None,
        contacts_locked=False,
        domains_locked=False,
        ship_to_locked=False,
        documents_seen=0,
        created_at=datetime.utcnow(),
    )


def get_profile(db: Session, bc_customer_id: str) -> Optional[CustomerProfile]:
    if not bc_customer_id:
        return None
    return (
        db.query(CustomerProfile)
        .filter(CustomerProfile.bc_customer_id == bc_customer_id)
        .first()
    )


def get_or_create_profile(
    db: Session,
    bc_customer_id: str,
    customer_number: Optional[str] = None,
) -> CustomerProfile:
    row = get_profile(db, bc_customer_id)
    if row:
        if customer_number and not row.customer_number:
            row.customer_number = customer_number
        return row
    row = _blank_profile(bc_customer_id, customer_number)
    db.add(row)
    db.flush()
    return row


def profile_to_dict(row: Optional[CustomerProfile], customer: Optional[BCCustomer] = None) -> dict:
    """API shape. Missing profiles still return the field catalog so the editor can start one."""
    fields = {}
    if row and isinstance(row.fields, dict):
        fields = row.fields
    number = None
    if row and row.customer_number:
        number = row.customer_number
    elif customer and isinstance(customer.customer_metadata, dict):
        number = customer.customer_metadata.get("number")
    return {
        "bc_customer_id": (row.bc_customer_id if row else (customer.bc_customer_id if customer else None)),
        "customer_number": number,
        "company_name": customer.company_name if customer else None,
        "price_group": customer.bc_price_group if customer else None,
        "fields": fields,
        "contacts": list(row.contacts or []) if row else [],
        "email_domains": list(row.email_domains or []) if row else [],
        "ship_to": row.ship_to if row else None,
        "contacts_locked": bool(row.contacts_locked) if row else False,
        "domains_locked": bool(row.domains_locked) if row else False,
        "ship_to_locked": bool(row.ship_to_locked) if row else False,
        "documents_seen": row.documents_seen if row else 0,
        "last_seeded_at": row.last_seeded_at.isoformat() if row and row.last_seeded_at else None,
        "catalog": field_catalog(),
    }


def apply_staff_edit(
    db: Session,
    bc_customer_id: str,
    payload: dict,
    staff_name: Optional[str] = None,
) -> CustomerProfile:
    """Save a staff edit. Changing a value locks that field."""
    customer = (
        db.query(BCCustomer).filter(BCCustomer.bc_customer_id == bc_customer_id).first()
    )
    number = None
    if customer and isinstance(customer.customer_metadata, dict):
        number = customer.customer_metadata.get("number")
    row = get_or_create_profile(db, bc_customer_id, number)
    previous = dict(row.fields or {})
    incoming = payload.get("fields") or {}
    merged: Dict[str, Any] = {}
    now = datetime.utcnow().isoformat()
    known = {key for key, _label, _choices in FIELD_SPECS}

    for key in known:
        old = previous.get(key) or {}
        if key not in incoming:
            if old:
                merged[key] = old
            continue
        edit = incoming[key] or {}
        value = edit.get("value")
        if isinstance(value, str):
            value = value.strip()
        locked = bool(edit.get("locked"))
        changed = not _same(value, old.get("value"))
        if changed:
            # A staff edit locks the field so the next seed cannot undo it.
            locked = True
            merged[key] = {
                "value": value if value not in ("", None) else None,
                "locked": locked and value not in ("", None),
                "confidence": 1.0 if value not in ("", None) else 0.0,
                "support": old.get("support"),
                "total": old.get("total"),
                "evidence": "Set by staff" if value not in ("", None) else old.get("evidence"),
                "counts": old.get("counts") or {},
                "source": "staff",
                "locked_by": staff_name,
                "locked_at": now,
            }
            if not merged[key]["locked"]:
                merged[key]["source"] = old.get("source") or "staff"
        else:
            updated = dict(old) if old else {
                "value": value,
                "confidence": 1.0 if value not in ("", None) else 0.0,
                "support": None,
                "total": None,
                "evidence": "Set by staff" if locked else None,
                "counts": {},
                "source": "staff" if locked else "bc_history",
            }
            updated["value"] = value if value not in ("", None) else old.get("value")
            updated["locked"] = locked and updated.get("value") not in (None, "")
            if locked and not old.get("locked"):
                updated["locked_by"] = staff_name
                updated["locked_at"] = now
                updated["source"] = old.get("source") or "staff"
            if not locked:
                updated["locked_by"] = None
                updated["locked_at"] = None
            merged[key] = updated

    # Drop empty unlocked placeholders so a blank editor row does not count as a value.
    row.fields = {
        key: spec for key, spec in merged.items()
        if spec and spec.get("value") not in (None, "")
    }

    # A staff save may change contacts even when the list is locked against
    # the history seed. The lock flag itself is updated just below.
    if "contacts" in payload:
        row.contacts = _clean_contacts(payload.get("contacts") or [])
    if "email_domains" in payload:
        row.email_domains = _clean_domains(payload.get("email_domains") or [])
    if "ship_to" in payload:
        row.ship_to = _clean_ship_to(payload.get("ship_to"), staff_name if payload.get("ship_to_locked") else None)
    if "contacts_locked" in payload:
        row.contacts_locked = bool(payload.get("contacts_locked"))
    if "domains_locked" in payload:
        row.domains_locked = bool(payload.get("domains_locked"))
    if "ship_to_locked" in payload:
        row.ship_to_locked = bool(payload.get("ship_to_locked"))
        if row.ship_to and isinstance(row.ship_to, dict):
            ship = dict(row.ship_to)
            ship["locked"] = row.ship_to_locked
            row.ship_to = ship
    row.updated_at = datetime.utcnow()
    db.flush()
    return row


def _clean_contacts(raw: Iterable[dict]) -> List[dict]:
    cleaned = []
    seen = set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        email = (item.get("email") or "").strip().lower()
        if not email or "@" not in email or email in seen:
            continue
        seen.add(email)
        role = (item.get("role") or "quote").strip().lower()
        if role not in {"quote", "po", "both"}:
            role = "quote"
        cleaned.append({
            "name": (item.get("name") or "").strip() or None,
            "email": email,
            "role": role,
        })
    return cleaned


def _clean_domains(raw: Iterable[Any]) -> List[str]:
    domains = []
    seen = set()
    for item in raw:
        text = item.get("domain") if isinstance(item, dict) else item
        domain = (text or "").strip().lower().lstrip("@")
        if not domain or "." not in domain or domain in FREE_MAIL_DOMAINS or domain in seen:
            continue
        seen.add(domain)
        domains.append(domain)
    return domains


def _clean_ship_to(raw: Any, staff_name: Optional[str]) -> Optional[dict]:
    if not raw:
        return None
    if isinstance(raw, dict) and "value" in raw and isinstance(raw.get("value"), dict):
        value = raw["value"]
        locked = bool(raw.get("locked"))
    elif isinstance(raw, dict):
        value = raw
        locked = bool(raw.get("locked"))
    else:
        return None
    address = {
        "name": (value.get("name") or "").strip() or None,
        "address": (value.get("address") or value.get("street") or "").strip() or None,
        "city": (value.get("city") or "").strip() or None,
        "state": (value.get("state") or value.get("province") or "").strip() or None,
        "postal": (value.get("postal") or value.get("postalCode") or "").strip() or None,
    }
    if not any(address.values()):
        return None
    return {
        "value": address,
        "locked": locked,
        "source": "staff" if staff_name else (raw.get("source") if isinstance(raw, dict) else "staff"),
        "evidence": (raw.get("evidence") if isinstance(raw, dict) else None) or "Set by staff",
        "locked_by": staff_name,
    }


# ---------------------------------------------------------------------------
# History seed
# ---------------------------------------------------------------------------

def _line_number(line: dict) -> str:
    for key in ("number", "lineObjectNumber", "itemNumber", "No"):
        value = line.get(key)
        if value:
            return str(value).strip().upper()
    return ""


def _line_description(line: dict) -> str:
    return str(line.get("description") or line.get("displayName") or "")


def parse_history_line(line: dict) -> dict:
    """Signals one BC line contributes to a customer profile. Pure function."""
    number = _line_number(line)
    description = _line_description(line)
    upper_desc = description.upper()
    signals: Dict[str, Any] = {}

    track = _TRACK_RE.match(number)
    if track and track.group("kind").upper() != "EXT":
        size = "2" if track.group("size") in {"02", "25"} else "3"
        signals["track_size"] = size
        kind = track.group("kind").upper()
        if kind in _LIFT_FROM_KIND:
            signals["lift_type"] = _LIFT_FROM_KIND[kind]
        mount = (track.group("mount") or "").upper()
        if mount == "AM":
            signals["track_mount"] = "angle"
        elif mount == "BM":
            signals["track_mount"] = "bracket"
        if size == "2":
            suffix = number.split("-")[-1]
            if len(suffix) == 4 and suffix[2:] in {"12", "15", "20"}:
                signals["track_radius"] = suffix[2:]
            elif track.group("size") == "25":
                signals["track_radius"] = "20"
                signals.setdefault("door_series", "CRAFT")
    elif track and track.group("kind").upper() == "EXT":
        signals["lift_type"] = "high_lift"

    if number in _FREIGHT_NUMBERS or number.startswith("FREIGHT"):
        signals["freight"] = True

    prefix = number.split("-", 1)[0]
    if prefix in _SERIES_PREFIX:
        signals["door_series"] = _SERIES_PREFIX[prefix]

    if number.startswith("GK"):
        signals["windows"] = "yes"
        if "POLY" in upper_desc:
            signals["glass"] = "polycarbonate"
        elif "SINGLE" in upper_desc:
            signals["glass"] = "single"
        elif "THERM" in upper_desc or "INSUL" in upper_desc:
            signals["glass"] = "insulated"

    for colour in _COLOUR_WORDS:
        if colour in upper_desc:
            signals["panel_color"] = colour.replace(" ", "_")
            break
    for design in _DESIGN_WORDS:
        if re.search(rf"\b{design}\b", upper_desc):
            signals["panel_design"] = design
            break

    if number.startswith("OP") or "OPERATOR" in upper_desc or "OPENER" in upper_desc:
        if number.startswith("OP"):
            signals["operator"] = number
        elif "OPERATOR" in upper_desc or "OPENER" in upper_desc:
            signals["operator"] = description.strip()[:80] or "operator"

    return signals


def _observations_from_document(document: dict) -> dict:
    """Collapse a document's lines into one vote per field, plus freight."""
    votes: Dict[str, Any] = {}
    saw_track = False
    saw_freight = False
    for line in document.get("lines") or []:
        if not isinstance(line, dict):
            continue
        if str(line.get("lineType") or "Item").lower() == "comment":
            continue
        signals = parse_history_line(line)
        saw_freight = saw_freight or bool(signals.pop("freight", False))
        if "track_mount" in signals or "track_size" in signals:
            saw_track = True
        for key, value in signals.items():
            # First signal on the document wins so one order is one vote.
            votes.setdefault(key, value)
    if saw_freight:
        votes["delivery_type"] = "delivery"
    elif saw_track:
        votes["delivery_type"] = "pickup"
    return votes


def _tally_field(counts: Counter) -> Optional[dict]:
    if not counts:
        return None
    value, support = counts.most_common(1)[0]
    total = int(sum(counts.values()))
    confidence = support / total if total else 0.0
    return {
        "value": value,
        "locked": False,
        "confidence": round(confidence, 4),
        "support": support,
        "total": total,
        "evidence": f"{_label(value)} on {support} of {total} orders",
        "counts": {str(k): int(v) for k, v in counts.items()},
        "source": "bc_history",
        "locked_by": None,
        "locked_at": None,
    }


def _email_domain(email: Optional[str]) -> Optional[str]:
    if not email or "@" not in email:
        return None
    domain = email.rsplit("@", 1)[1].strip().lower()
    if not domain or "." not in domain or domain in FREE_MAIL_DOMAINS:
        return None
    return domain


def _ship_key(address: dict) -> str:
    parts = [
        address.get("address") or "",
        address.get("city") or "",
        address.get("state") or "",
        address.get("postal") or "",
    ]
    return "|".join(p.strip().lower() for p in parts if p and str(p).strip())


def seed_profiles_from_documents(db: Session, documents: Sequence[dict]) -> dict:
    """Recompute inferred profile values from the documents in this run.

    Locked fields, locked contacts, locked domains, and a locked ship-to
    are left as staff set them. Running the seed again with the same
    history produces the same inferred values (it replaces counts; it does
    not add them to the previous run).
    """
    grouped: Dict[str, List[dict]] = {}
    for document in documents:
        customer_id = (
            document.get("customer_id")
            or document.get("customerId")
            or document.get("bc_customer_id")
        )
        if not customer_id:
            continue
        grouped.setdefault(str(customer_id), []).append(document)

    updated = []
    for customer_id, docs in grouped.items():
        customer = (
            db.query(BCCustomer).filter(BCCustomer.bc_customer_id == customer_id).first()
        )
        number = None
        if customer and isinstance(customer.customer_metadata, dict):
            number = customer.customer_metadata.get("number")
        number = number or docs[0].get("customer_number")
        row = get_or_create_profile(db, customer_id, number)

        tallies: Dict[str, Counter] = {key: Counter() for key, _l, _c in FIELD_SPECS}
        contacts: Dict[str, dict] = {}
        domains = set()
        ship_counts: Counter = Counter()
        ship_values: Dict[str, dict] = {}

        for document in docs:
            votes = _observations_from_document(document)
            for key, value in votes.items():
                if key in tallies and value not in (None, ""):
                    tallies[key][value] += 1
            email = (document.get("email") or "").strip().lower()
            if email and "@" in email:
                contacts.setdefault(email, {
                    "name": document.get("contact_name") or None,
                    "email": email,
                    "role": "quote",
                })
                domain = _email_domain(email)
                if domain:
                    domains.add(domain)
            ship = document.get("ship_to") or {}
            if isinstance(ship, dict):
                address = {
                    "name": ship.get("name") or None,
                    "address": ship.get("address") or ship.get("addressLine1") or None,
                    "city": ship.get("city") or None,
                    "state": ship.get("state") or ship.get("province") or None,
                    "postal": ship.get("postal") or ship.get("postalCode") or None,
                }
                key = _ship_key(address)
                if key:
                    ship_counts[key] += 1
                    ship_values[key] = address

        previous = dict(row.fields or {})
        fields = {}
        for key, _label, _choices in FIELD_SPECS:
            fresh = _tally_field(tallies[key])
            old = previous.get(key) or {}
            if old.get("locked"):
                kept = dict(old)
                if fresh:
                    kept["history_evidence"] = fresh["evidence"]
                    kept["counts"] = fresh["counts"]
                    kept["support"] = fresh["support"]
                    kept["total"] = fresh["total"]
                fields[key] = kept
            elif fresh:
                fields[key] = fresh
        row.fields = fields

        if not row.contacts_locked:
            # Keep staff-added contacts that this history did not mention,
            # and union the emails we just saw.
            merged_contacts = {c["email"]: c for c in _clean_contacts(row.contacts or [])}
            merged_contacts.update(contacts)
            row.contacts = list(merged_contacts.values())
        if not row.domains_locked:
            merged_domains = set(_clean_domains(row.email_domains or []))
            merged_domains.update(domains)
            row.email_domains = sorted(merged_domains)
        if not row.ship_to_locked and ship_counts:
            best_key, support = ship_counts.most_common(1)[0]
            total = int(sum(ship_counts.values()))
            row.ship_to = {
                "value": ship_values[best_key],
                "locked": False,
                "source": "bc_history",
                "confidence": round(support / total, 4) if total else 0,
                "evidence": f"ship-to on {support} of {total} orders",
            }

        row.documents_seen = len(docs)
        row.last_seeded_at = datetime.utcnow()
        row.updated_at = datetime.utcnow()
        updated.append(customer_id)

    db.flush()
    return {"customers": len(updated), "bc_customer_ids": updated, "documents": len(documents)}


def documents_from_bc(client, bc_customer_id: str, top: int = 80) -> List[dict]:
    """Read one customer's posted invoices and open orders. Does not write to BC."""
    documents = []
    invoices = client.get_customer_invoices(bc_customer_id, top=top) or []
    for header in invoices:
        documents.append(_bc_document(client, header, "invoice", bc_customer_id))
    orders = client.get_customer_orders(bc_customer_id, top=top) or []
    for header in orders:
        documents.append(_bc_document(client, header, "order", bc_customer_id))
    return documents


def _bc_document(client, header: dict, kind: str, bc_customer_id: str) -> dict:
    doc_id = header.get("id")
    lines: List[dict] = []
    if doc_id:
        try:
            if kind == "invoice" and hasattr(client, "get_sales_invoice_lines"):
                lines = client.get_sales_invoice_lines(doc_id) or []
            elif hasattr(client, "get_order_lines"):
                lines = client.get_order_lines(doc_id) or []
        except Exception as exc:
            logger.warning("Could not read %s lines for %s: %s", kind, header.get("number"), exc)
            lines = []
    return {
        "id": doc_id,
        "number": header.get("number"),
        "kind": kind,
        "customer_id": header.get("customerId") or bc_customer_id,
        "customer_number": header.get("customerNumber"),
        "customer_name": header.get("customerName"),
        "email": header.get("email"),
        "ship_to": {
            "name": header.get("shipToName"),
            "address": header.get("shipToAddressLine1"),
            "city": header.get("shipToCity"),
            "state": header.get("shipToState"),
            "postal": header.get("shipToPostCode"),
        },
        "lines": lines,
    }


def seed_profiles(
    db: Session,
    *,
    bc_customer_id: Optional[str] = None,
    documents: Optional[Sequence[dict]] = None,
    client=None,
    top: int = 80,
) -> dict:
    """Re-runnable seed. Pass ``documents`` to avoid BC; otherwise read BC."""
    errors = []
    if documents is None:
        if client is None:
            from app.integrations.bc.client import bc_client
            client = bc_client
        if bc_customer_id:
            ids = [bc_customer_id]
        else:
            ids = [
                row[0]
                for row in db.query(BCCustomer.bc_customer_id)
                .filter(~BCCustomer.bc_customer_id.like("TEMP-%"))
                .all()
            ]
        documents = []
        for cid in ids:
            try:
                documents.extend(documents_from_bc(client, cid, top=top))
            except Exception as exc:
                logger.warning("Profile seed skipped %s: %s", cid, exc)
                errors.append({"bc_customer_id": cid, "error": str(exc)})
    stats = seed_profiles_from_documents(db, documents)
    stats["errors"] = errors
    return stats


# ---------------------------------------------------------------------------
# Apply profile to a quote
# ---------------------------------------------------------------------------

def detect_explicit_fields(email_text: str, parsed_door: Optional[dict] = None) -> Dict[str, Any]:
    """Values the email actually stated, keyed by configurator field name.

    The mapper fills every field, including defaults. This is how quoting
    tells a silent email from one that asked for bracket mount.
    """
    text = email_text or ""
    parsed = parsed_door or {}
    explicit: Dict[str, Any] = {}

    angle = bool(_ANGLE_RE.search(text))
    bracket = bool(_BRACKET_RE.search(text))
    if not angle and not bracket:
        # "bracket" or "angle" on its own still counts when the other word is absent.
        if _BARE_BRACKET_RE.search(text) and not _BARE_ANGLE_RE.search(text):
            bracket = True
        elif _BARE_ANGLE_RE.search(text) and not _BARE_BRACKET_RE.search(text):
            angle = True
    parsed_mount = parsed.get("track_mount") or parsed.get("trackMount") or parsed.get("mount")
    if parsed_mount:
        token = str(parsed_mount).lower()
        if "angle" in token:
            angle, bracket = True, False
        elif "bracket" in token:
            bracket, angle = True, False
    if angle and not bracket:
        explicit["trackMount"] = "angle"
    elif bracket and not angle:
        explicit["trackMount"] = "bracket"

    if _TRACK3_RE.search(text) and not _TRACK2_RE.search(text):
        explicit["trackThickness"] = "3"
    elif _TRACK2_RE.search(text) and not _TRACK3_RE.search(text):
        explicit["trackThickness"] = "2"
    radius = _RADIUS_RE.search(text)
    if radius:
        explicit["trackRadius"] = radius.group(1)

    for lift, pattern in _LIFT_RES:
        if pattern.search(text):
            explicit["liftType"] = lift
            break
    parsed_lift = parsed.get("lift") or parsed.get("lift_type") or parsed.get("liftType")
    if parsed_lift and "liftType" not in explicit:
        explicit["liftType"] = str(parsed_lift)

    series = _SERIES_RE.search(text)
    if series:
        explicit["doorSeries"] = series.group(1).upper()
    elif parsed.get("model") or parsed.get("series"):
        explicit["doorSeries"] = str(parsed.get("model") or parsed.get("series")).upper()

    if parsed.get("color") or parsed.get("colour") or parsed.get("panel_color"):
        explicit["panelColor"] = str(parsed.get("color") or parsed.get("colour") or parsed.get("panel_color"))
    if parsed.get("panel_design") or parsed.get("design") or parsed.get("stamp"):
        explicit["panelDesign"] = str(parsed.get("panel_design") or parsed.get("design") or parsed.get("stamp"))

    if parsed.get("glazing") or parsed.get("glass"):
        explicit["glazingType"] = parsed.get("glazing") or parsed.get("glass")
    if parsed.get("has_windows") is True or re.search(r"\bwith\s+windows\b|\bwindows\b", text, re.I):
        if not re.search(r"\bno\s+windows\b|\bwithout\s+windows\b", text, re.I):
            explicit["hasWindows"] = True
    if re.search(r"\bno\s+windows\b|\bwithout\s+windows\b", text, re.I):
        explicit["hasWindows"] = False

    if parsed.get("operator") or parsed.get("opener"):
        explicit["operator"] = parsed.get("operator") or parsed.get("opener")

    pickup = bool(_PICKUP_RE.search(text))
    delivery = bool(_DELIVERY_RE.search(text))
    if pickup and not delivery:
        explicit["deliveryType"] = "pickup"
    elif delivery and not pickup:
        explicit["deliveryType"] = "delivery"

    return explicit


def _system_default(door_key: str, door: dict) -> Any:
    from app.services.track_defaults import default_track_thickness, is_aluminum_door

    series = door.get("doorSeries")
    door_type = door.get("doorType")
    if door_key == "trackMount":
        return "bracket"
    if door_key == "trackThickness":
        return default_track_thickness(series, door_type)
    if door_key == "trackRadius":
        thickness = str(door.get("trackThickness") or default_track_thickness(series, door_type))
        return "12" if thickness == "3" else "15"
    if door_key == "liftType":
        return "standard"
    if door_key == "doorSeries":
        dtype = (door_type or "commercial").lower()
        if dtype == "residential":
            return "KANATA"
        if dtype in {"aluminium", "aluminum"}:
            return "AL976"
        return "TX450"
    if door_key == "panelColor":
        return "WHITE"
    if door_key == "panelDesign":
        dtype = (door_type or "commercial").lower()
        return "SHXL" if dtype == "residential" else "FLUSH"
    if door_key == "hasWindows":
        return False
    if door_key == "glazingType":
        return None
    if door_key == "operator":
        return None
    if door_key == "operatorAccessories":
        return None
    return None


def _profile_value_for_door(profile_key: str, spec: dict) -> Any:
    value = spec.get("value")
    if profile_key == "windows":
        return str(value).lower() in {"yes", "true", "1"}
    if profile_key == "track_size":
        return str(value)
    if profile_key == "accessories" and isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    return value


def _source_entry(value: Any, source: str, spec: Optional[dict] = None) -> dict:
    entry = {"value": value, "source": source}
    if spec:
        entry["locked"] = bool(spec.get("locked"))
        if spec.get("evidence"):
            entry["evidence"] = spec["evidence"]
        if spec.get("confidence") is not None:
            entry["confidence"] = spec["confidence"]
    return entry


def apply_customer_profile(
    doors: List[dict],
    *,
    profile: Optional[CustomerProfile] = None,
    email_text: str = "",
    parsed_doors: Optional[Sequence[dict]] = None,
    delivery_type: str = "delivery",
    delivery_explicit: bool = False,
    explicit_fields: Optional[Sequence[Optional[Iterable[str]]]] = None,
    explicit_complete: bool = False,
) -> dict:
    """Fill silent door fields from the profile and tag every source.

    ``explicit_fields`` is per door. ``None`` for a door means "only values
    that still equal the system default are silent" (portal and staff
    configurator, which always post a full door). A list, even an empty
    one, is the email path: the mapper's defaults are not treated as the
    customer having asked for them.

    A locked profile value replaces a conflicting explicit email value and
    records a deviation. An unlocked profile value does not override
    something the email stated.
    """
    fields = (profile.fields or {}) if profile else {}
    sources_doors = []
    deviations = []
    updated_doors = []

    for index, door in enumerate(doors):
        door = dict(door or {})
        parsed = {}
        if parsed_doors and index < len(parsed_doors) and isinstance(parsed_doors[index], dict):
            parsed = parsed_doors[index]
        detected = detect_explicit_fields(email_text, parsed) if email_text or parsed else {}
        provided = None
        if explicit_fields is not None and index < len(explicit_fields):
            provided = explicit_fields[index]
        # Email passes a complete list of what the message stated, so an
        # AI default is still silent. A portal touch-list only marks the
        # controls the person changed; every other non-default stays.
        complete = explicit_complete or bool(email_text) or bool(parsed)
        explicit_names = set(provided or [])
        explicit_names.update(k for k in detected if k != "deliveryType")

        door_sources = {}
        for profile_key, door_key in DOOR_KEYS.items():
            spec = fields.get(profile_key) if isinstance(fields.get(profile_key), dict) else None
            applicable = is_applicable(spec)
            current = door.get(door_key)
            default = _system_default(door_key, door)
            stated = door_key in explicit_names
            if complete:
                silent = not stated
            else:
                silent = (not stated) and _same(current, default)

            # Aluminum / Panorama 3" track stays the rule when the email
            # is silent, unless staff locked a different size.
            if (
                door_key == "trackThickness"
                and silent
                and not (spec and spec.get("locked"))
            ):
                from app.services.track_defaults import is_aluminum_door
                if is_aluminum_door(door.get("doorSeries"), door.get("doorType")):
                    door["trackThickness"] = "3"
                    door_sources[door_key] = _source_entry("3", "default")
                    continue

            if stated and applicable and spec.get("locked"):
                wanted = detected.get(door_key, current)
                profile_value = _profile_value_for_door(profile_key, spec)
                if not _same(wanted, profile_value):
                    door[door_key] = profile_value
                    door_sources[door_key] = _source_entry(profile_value, "profile", spec)
                    deviations.append({
                        "kind": "locked_rule",
                        "field": door_key,
                        "door_index": index + 1,
                        "email_value": wanted,
                        "applied_value": profile_value,
                        "reason": (
                            f"Email asked for {_label(wanted)}. "
                            f"Locked customer rule is {_label(profile_value)}."
                        ),
                        "evidence": spec.get("evidence"),
                    })
                    continue
            if silent and applicable:
                profile_value = _profile_value_for_door(profile_key, spec)
                door[door_key] = profile_value
                door_sources[door_key] = _source_entry(profile_value, "profile", spec)
                continue
            if stated:
                if door_key in detected:
                    door[door_key] = detected[door_key]
                door_sources[door_key] = _source_entry(door.get(door_key), "email")
                continue
            # Still the system default (or an AI fill the email did not state,
            # which we leave in place and tag as default when it matches).
            if _same(current, default) or current in (None, "", []):
                if door_key == "trackThickness":
                    door[door_key] = default
                door_sources[door_key] = _source_entry(door.get(door_key, default), "default")
            else:
                # Portal posted a non-default the user picked.
                door_sources[door_key] = _source_entry(current, "email")
        sources_doors.append(door_sources)
        updated_doors.append(door)

    delivery_source = _resolve_delivery(
        fields.get("delivery_type") if isinstance(fields.get("delivery_type"), dict) else None,
        email_text,
        delivery_type,
        delivery_explicit,
        deviations,
    )
    ship = None
    if profile and profile.ship_to and delivery_source["value"] == "delivery":
        ship = profile.ship_to

    return {
        "doors": updated_doors,
        "delivery_type": delivery_source["value"],
        "field_sources": {
            "deliveryType": delivery_source,
            "shipTo": ship,
            "doors": sources_doors,
        },
        "deviations": deviations,
    }


def _resolve_delivery(spec, email_text, delivery_type, delivery_explicit, deviations) -> dict:
    detected = detect_explicit_fields(email_text or "", None)
    email_choice = detected.get("deliveryType")
    applicable = is_applicable(spec)
    current = (delivery_type or "delivery").lower()

    if email_choice and applicable and spec.get("locked") and not _same(email_choice, spec.get("value")):
        deviations.append({
            "kind": "locked_rule",
            "field": "deliveryType",
            "door_index": None,
            "email_value": email_choice,
            "applied_value": spec.get("value"),
            "reason": (
                f"Email asked for {_label(email_choice)}. "
                f"Locked customer rule is {_label(spec.get('value'))}."
            ),
            "evidence": spec.get("evidence"),
        })
        return _source_entry(spec.get("value"), "profile", spec)

    if email_choice:
        return _source_entry(email_choice, "email")
    if delivery_explicit:
        return _source_entry(current, "email")
    if applicable and _same(current, "delivery"):
        # The email path used to hardcode delivery. A pickup profile replaces that.
        return _source_entry(spec.get("value"), "profile", spec)
    if applicable and not delivery_explicit and current in ("", None):
        return _source_entry(spec.get("value"), "profile", spec)
    if not _same(current, "delivery") and not delivery_explicit and not email_choice:
        # Already pickup from an earlier apply. Keep it and say where it came from
        # when the profile agrees.
        if applicable and _same(current, spec.get("value")):
            return _source_entry(current, "profile", spec)
        return _source_entry(current, "email")
    return _source_entry(current or "delivery", "default")


def apply_profile_for_customer(
    db: Session,
    bc_customer_id: Optional[str],
    doors: List[dict],
    delivery_type: str = "delivery",
    **kwargs,
) -> dict:
    profile = get_profile(db, bc_customer_id) if bc_customer_id else None
    return apply_customer_profile(doors, profile=profile, delivery_type=delivery_type, **kwargs)


def merge_part_deviations(existing: Optional[List[dict]], part_deviations: Optional[List[dict]]) -> List[dict]:
    """Append part-number substitutions (bracket fallback, colour swaps)."""
    merged = list(existing or [])
    for item in part_deviations or []:
        if isinstance(item, dict):
            merged.append(item)
    return merged


# ---------------------------------------------------------------------------
# Customer matching
# ---------------------------------------------------------------------------

class CustomerMatch:
    def __init__(self, bc_customer_id: Optional[str], method: str, confident: bool, reason: str, score: float = 0.0):
        self.bc_customer_id = bc_customer_id
        self.method = method
        self.confident = confident
        self.reason = reason
        self.score = score

    def as_dict(self) -> dict:
        return {
            "bc_customer_id": self.bc_customer_id,
            "method": self.method,
            "confident": self.confident,
            "reason": self.reason,
            "score": round(self.score, 3),
        }


def _norm_company(name: Optional[str]) -> str:
    text = re.sub(r"[^a-z0-9\s]", " ", (name or "").lower())
    tokens = [tok for tok in text.split() if tok and tok not in _NAME_STOP]
    return " ".join(tokens)


def _fuzzy_score(query: str, candidate: str) -> float:
    left, right = _norm_company(query), _norm_company(candidate)
    if not left or not right:
        return 0.0
    if left == right:
        return 1.0
    left_tokens, right_tokens = set(left.split()), set(right.split())
    if left_tokens and (left_tokens <= right_tokens or right_tokens <= left_tokens):
        return 0.93
    return SequenceMatcher(None, left, right).ratio()


def match_bc_customer(
    db: Session,
    *,
    email: Optional[str] = None,
    company_name: Optional[str] = None,
) -> CustomerMatch:
    """Match an inbound quote to a BC customer.

    Confident matches: exact email, a profile contact, exact company name,
    one customer on that email's domain (free-mail domains are ignored),
    or one clearly best fuzzy company name. Anything else is not confident
    and the quote is held instead of priced at retail.
    """
    email_norm = (email or "").strip().lower()
    name = (company_name or "").strip()

    if email_norm:
        exact = (
            db.query(BCCustomer)
            .filter(BCCustomer.email.ilike(email_norm))
            .all()
        )
        if len(exact) == 1:
            row = exact[0]
            return CustomerMatch(
                row.bc_customer_id, "exact_email", True,
                f"Exact email match to {row.company_name or row.bc_customer_id}",
                1.0,
            )
        if len(exact) > 1:
            return CustomerMatch(
                None, "ambiguous_email", False,
                f"{len(exact)} customers share {email_norm}",
                0.0,
            )

        contact_hits = []
        for profile in db.query(CustomerProfile).all():
            for contact in profile.contacts or []:
                if not isinstance(contact, dict):
                    continue
                if (contact.get("email") or "").strip().lower() == email_norm:
                    contact_hits.append(profile.bc_customer_id)
        contact_hits = list(dict.fromkeys(contact_hits))
        if len(contact_hits) == 1:
            return CustomerMatch(
                contact_hits[0], "contact", True,
                f"Email is a known contact on customer {contact_hits[0]}",
                0.98,
            )
        if len(contact_hits) > 1:
            return CustomerMatch(
                None, "ambiguous_contact", False,
                f"{email_norm} is listed on more than one customer",
                0.0,
            )

    if name:
        normalized = _norm_company(name)
        exact_names = []
        for row in db.query(BCCustomer).filter(BCCustomer.company_name.isnot(None)).all():
            if (row.company_name or "").strip().lower() == name.lower() or (
                normalized and _norm_company(row.company_name) == normalized
            ):
                exact_names.append(row)
        if len(exact_names) == 1:
            row = exact_names[0]
            return CustomerMatch(
                row.bc_customer_id, "exact_name", True,
                f"Exact company name match to {row.company_name}",
                1.0,
            )
        if len(exact_names) > 1:
            return CustomerMatch(
                None, "ambiguous_name", False,
                f"{len(exact_names)} customers are named {name}",
                0.0,
            )

    domain = _email_domain(email_norm)
    if domain:
        hits = {}
        for row in db.query(BCCustomer).filter(BCCustomer.email.ilike(f"%@{domain}")).all():
            if _email_domain(row.email) == domain:
                hits[row.bc_customer_id] = row.company_name
        for profile in db.query(CustomerProfile).all():
            for stored in profile.email_domains or []:
                stored_domain = stored.get("domain") if isinstance(stored, dict) else stored
                if (stored_domain or "").strip().lower() == domain:
                    hits.setdefault(profile.bc_customer_id, profile.bc_customer_id)
        if len(hits) == 1:
            cid, label = next(iter(hits.items()))
            return CustomerMatch(
                cid, "domain", True,
                f"Email domain @{domain} matches {label}",
                0.9,
            )
        if len(hits) > 1:
            return CustomerMatch(
                None, "ambiguous_domain", False,
                f"@{domain} is used by {len(hits)} customers",
                0.0,
            )

    if name:
        scored = []
        for row in db.query(BCCustomer).filter(BCCustomer.company_name.isnot(None)).all():
            score = _fuzzy_score(name, row.company_name or "")
            if score >= 0.8:
                scored.append((score, row))
        scored.sort(key=lambda item: item[0], reverse=True)
        if scored:
            best_score, best = scored[0]
            second = scored[1][0] if len(scored) > 1 else 0.0
            if best_score >= 0.88 and (best_score - second) >= 0.05:
                return CustomerMatch(
                    best.bc_customer_id, "fuzzy_name", True,
                    f"Company name '{name}' matches {best.company_name} ({best_score:.0%})",
                    best_score,
                )
            return CustomerMatch(
                None, "ambiguous_fuzzy", False,
                f"Company name '{name}' is close to more than one customer",
                best_score,
            )

    return CustomerMatch(
        None, "none", False,
        "No confident customer match; held for review instead of retail pricing",
        0.0,
    )
