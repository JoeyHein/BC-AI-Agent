"""Staff service API keys.

Scheduled jobs call the staff portal with a long-lived key instead of a
person's login JWT. The plaintext (``osk_live_...``) is returned once.
Verification checks the bcrypt hash, then an allow-list of routes. Anything
not on that list is denied, including user management and settings changes.

Human JWTs do not start with ``osk_`` and never enter this module.
"""
from __future__ import annotations

import json
import logging
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import bcrypt
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import StaffServiceKey, StaffServiceKeyAudit, User, UserRole

logger = logging.getLogger(__name__)

_BCRYPT_MAX_BYTES = 72
_PREFIX_LEN = 12
_RANDOM_SUFFIX_BYTES = 32  # token_urlsafe(32) is ~43 chars; well under bcrypt's 72

# Reserved login. Password login is rejected. Existing staff permission
# checks see this user as an active admin; the scope list is what actually
# limits a key. Revoke the key to stop access.
SERVICE_USER_EMAIL = "automation@keys.opendc.internal"
SERVICE_USER_NAME = "Automation"

# The hourly PO job's allow-list. A key stores a subset of these names.
# "automation" is a preset that expands to all of them; it is not stored.
ORDERS_READ = "orders:read"
INVENTORY_READ = "inventory:read"
PURCHASING_READ = "purchasing:read"
DRAFT_PO_LINES = "purchasing:draft_po_lines"
GENERATE_PO = "purchasing:generate_po"
REVIEW_DRAFT = "purchasing:review_draft"
VENDOR_ACKS_RUN = "vendor_acks:run"
QUOTES_READ = "quotes:read"

AUTOMATION_SCOPES = [
    ORDERS_READ,
    INVENTORY_READ,
    PURCHASING_READ,
    DRAFT_PO_LINES,
    GENERATE_PO,
    REVIEW_DRAFT,
    VENDOR_ACKS_RUN,
    QUOTES_READ,
]

_KNOWN_SCOPES = set(AUTOMATION_SCOPES)
_PRESETS = {"automation": list(AUTOMATION_SCOPES)}

# (method, path regex, scope, extra check)
# extra == "generate_po" requires the body to skip the Outlook review draft
# (send_email false, or create_review_draft false). Review drafts are a
# separate route.
_GENERATE_PO_PATH = "/api/admin/purchasing/generate-po"

_RULES: list[tuple[str, re.Pattern[str], str, Optional[str]]] = [
    # Sales orders — reads only. Ship, post, and convert stay denied.
    ("GET", re.compile(r"^/api/orders$"), ORDERS_READ, None),
    ("GET", re.compile(r"^/api/orders/legacy$"), ORDERS_READ, None),
    ("GET", re.compile(r"^/api/orders/stats/pipeline$"), ORDERS_READ, None),
    ("GET", re.compile(r"^/api/orders/\d+$"), ORDERS_READ, None),
    ("GET", re.compile(r"^/api/orders/\d+/production-orders$"), ORDERS_READ, None),
    ("GET", re.compile(r"^/api/orders/\d+/spring-production-orders$"), ORDERS_READ, None),
    ("GET", re.compile(r"^/api/orders/\d+/shipments$"), ORDERS_READ, None),
    ("GET", re.compile(r"^/api/orders/\d+/invoices$"), ORDERS_READ, None),
    ("GET", re.compile(r"^/api/orders/bc/orders$"), ORDERS_READ, None),
    # Inventory and catalog items. /api/inventory is the portal path
    # (nginx only forwards /api/). /inventory is the original mount.
    ("GET", re.compile(r"^(/api)?/inventory/levels$"), INVENTORY_READ, None),
    ("GET", re.compile(r"^(/api)?/inventory/item/[^/]+$"), INVENTORY_READ, None),
    ("GET", re.compile(r"^(/api)?/inventory/item/[^/]+/movements$"), INVENTORY_READ, None),
    ("GET", re.compile(r"^(/api)?/inventory/categories$"), INVENTORY_READ, None),
    ("GET", re.compile(r"^(/api)?/inventory/locations$"), INVENTORY_READ, None),
    ("POST", re.compile(r"^(/api)?/inventory/check-availability$"), INVENTORY_READ, None),
    ("GET", re.compile(r"^/api/admin/catalog/parts$"), INVENTORY_READ, None),
    # Purchasing reads: requirements, SO–PO links, draft PO list/validate/pdf.
    ("GET", re.compile(r"^/api/admin/purchasing/requirements$"), PURCHASING_READ, None),
    ("GET", re.compile(r"^/api/admin/purchasing/so-po-links$"), PURCHASING_READ, None),
    ("GET", re.compile(r"^/api/admin/purchasing/draft-pos$"), PURCHASING_READ, None),
    ("GET", re.compile(r"^/api/admin/purchasing/draft-pos/validate$"), PURCHASING_READ, None),
    ("GET", re.compile(r"^/api/admin/purchasing/draft-pos/[^/]+/validate$"), PURCHASING_READ, None),
    ("GET", re.compile(r"^/api/admin/purchasing/draft-pos/[^/]+/pdf$"), PURCHASING_READ, None),
    # Read-only look at a new sales order's lines, and the vendor list.
    # Creating the PO (POST so-complete-po) stays denied: that writes a
    # Draft and can save an Outlook review draft.
    ("GET", re.compile(r"^/api/admin/purchasing/so-complete-po/preview$"), PURCHASING_READ, None),
    ("GET", re.compile(r"^/api/admin/purchasing/vendors$"), PURCHASING_READ, None),
    # Draft PO lines: read, edit, add, delete, reorder, normalize-order.
    ("GET", re.compile(r"^/api/admin/purchasing/draft-pos/[^/]+/lines$"), DRAFT_PO_LINES, None),
    ("PATCH", re.compile(r"^/api/admin/purchasing/draft-pos/[^/]+/lines/[^/]+$"), DRAFT_PO_LINES, None),
    ("DELETE", re.compile(r"^/api/admin/purchasing/draft-pos/[^/]+/lines/[^/]+$"), DRAFT_PO_LINES, None),
    ("POST", re.compile(r"^/api/admin/purchasing/draft-pos/[^/]+/lines$"), DRAFT_PO_LINES, None),
    ("POST", re.compile(r"^/api/admin/purchasing/draft-pos/[^/]+/lines/reorder$"), DRAFT_PO_LINES, None),
    ("POST", re.compile(r"^/api/admin/purchasing/draft-pos/[^/]+/lines/normalize-order$"), DRAFT_PO_LINES, None),
    ("POST", re.compile(r"^/api/admin/purchasing/generate-po$"), GENERATE_PO, "generate_po"),
    ("POST", re.compile(r"^/api/admin/purchasing/draft-pos/[^/]+/review-draft$"), REVIEW_DRAFT, None),
    # Vendor acknowledgement intake.
    ("GET", re.compile(r"^/api/admin/vendor-acks$"), VENDOR_ACKS_RUN, None),
    ("POST", re.compile(r"^/api/admin/vendor-acks/run$"), VENDOR_ACKS_RUN, None),
    # Quote and review reads. Approve / reject / create-in-BC stay denied.
    ("GET", re.compile(r"^/api/quotes/pending-review$"), QUOTES_READ, None),
    ("GET", re.compile(r"^/api/quotes/stats/summary$"), QUOTES_READ, None),
    ("GET", re.compile(r"^/api/quotes/\d+$"), QUOTES_READ, None),
    ("GET", re.compile(r"^/api/quotes/\d+/pdf$"), QUOTES_READ, None),
    ("GET", re.compile(r"^/api/orders/bc/quotes$"), QUOTES_READ, None),
    ("GET", re.compile(r"^/api/admin/quotes$"), QUOTES_READ, None),
    ("GET", re.compile(r"^/api/admin/quotes/by-number/[^/]+/pdf$"), QUOTES_READ, None),
    ("GET", re.compile(r"^/api/admin/quote-review/snapshots$"), QUOTES_READ, None),
    ("GET", re.compile(r"^/api/admin/quote-review/reviews$"), QUOTES_READ, None),
    ("GET", re.compile(r"^/api/admin/quote-review/reviews/\d+$"), QUOTES_READ, None),
]


@dataclass
class KeyDecision:
    """Result of checking one presented key against one request."""

    ok: bool
    status_code: int
    detail: str
    outcome: str
    user: Optional[User] = None
    key_id: Optional[int] = None
    key_name: Optional[str] = None
    key_prefix: Optional[str] = None


def new_session():
    """Session for the request gate. Tests replace this with sqlite."""
    from app.db.database import SessionLocal

    return SessionLocal()


def _to_bcrypt_bytes(plaintext: str) -> bytes:
    return plaintext.encode("utf-8")[:_BCRYPT_MAX_BYTES]


def _naive_utc(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    if value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def normalize_path(path: str) -> str:
    path = (path or "").split("?", 1)[0]
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/")
    return path


def is_staff_service_key(token: Optional[str]) -> bool:
    """True only for keys this module minted. JWTs start with ``eyJ``."""
    return isinstance(token, str) and token.startswith("osk_") and len(token) >= 20


def generate_plaintext(environment: str = "live") -> str:
    suffix = secrets.token_urlsafe(_RANDOM_SUFFIX_BYTES)
    return f"osk_{environment}_{suffix}"


def hash_plaintext(plaintext: str) -> str:
    return bcrypt.hashpw(_to_bcrypt_bytes(plaintext), bcrypt.gensalt()).decode("ascii")


def prefix_for(plaintext: str) -> str:
    return plaintext[:_PREFIX_LEN]


def normalize_scopes(scopes: Optional[list[str]]) -> list[str]:
    """Expand presets and reject unknown names.

    ``None`` or an empty list means the automation preset (every scope
    the hourly job uses). An explicit list is stored as given, after
    ``automation`` is expanded.
    """
    if not scopes:
        return list(AUTOMATION_SCOPES)
    expanded: list[str] = []
    for raw in scopes:
        name = (raw or "").strip()
        if name in _PRESETS:
            expanded.extend(_PRESETS[name])
        elif name in _KNOWN_SCOPES:
            expanded.append(name)
        else:
            known = ", ".join(["automation", *AUTOMATION_SCOPES])
            raise ValueError(f"Unknown scope '{name}'. Use one of: {known}")
    seen: set[str] = set()
    out: list[str] = []
    for name in expanded:
        if name not in seen:
            seen.add(name)
            out.append(name)
    if not out:
        raise ValueError("Pick at least one scope")
    return out


def _scopes_of(row: StaffServiceKey) -> set[str]:
    raw = row.scopes or []
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return set()
    if not isinstance(raw, list):
        return set()
    return {str(item) for item in raw}


def _generate_po_skips_draft(body: bytes) -> bool:
    """True only when generate-po will not save an Outlook review draft.

    Matches ``review_draft_requested`` in the purchasing route:
    ``create_review_draft`` wins when it is present, otherwise ``send_email``.
    When both are omitted the purchasing screen saves a draft, so a service
    key must say so explicitly. Only a JSON boolean ``false`` counts.
    """
    try:
        data = json.loads(body.decode("utf-8") if body else "")
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError):
        return False
    if not isinstance(data, dict):
        return False
    if "create_review_draft" in data and data["create_review_draft"] is not None:
        return data["create_review_draft"] is False
    if "send_email" in data and data["send_email"] is not None:
        return data["send_email"] is False
    return False


def route_allowed(method: str, path: str, body: bytes, granted: set[str]) -> tuple[bool, str]:
    """Default deny. A route is allowed only when a rule matches and the key has that scope."""
    method = (method or "").upper()
    path = normalize_path(path)
    saw_rule = False
    for rule_method, pattern, scope, extra in _RULES:
        if rule_method != method or pattern.match(path) is None:
            continue
        saw_rule = True
        if scope not in granted:
            continue
        if extra == "generate_po" and not _generate_po_skips_draft(body):
            return (
                False,
                "generate-po is allowed only when send_email is false "
                "(that skips the Outlook draft). Use review-draft when you want a draft.",
            )
        return True, "allowed"
    if saw_rule:
        return False, "This service key does not include permission for this route."
    return False, "This service key is not allowed to call this route."


def _identity_for(row: User) -> User:
    """Detached copy. Safe to use after the session that loaded ``row`` closes."""
    return User(
        id=row.id,
        email=row.email,
        name=row.name,
        role=row.role,
        is_active=True,
        user_type="SERVICE",
        password_hash="-",
    )


def get_or_create_service_user(db: Session) -> User:
    """The user row staff permission checks accept for a valid key."""
    user = db.query(User).filter(User.email == SERVICE_USER_EMAIL).first()
    if user is None:
        user = User(
            email=SERVICE_USER_EMAIL,
            password_hash=bcrypt.hashpw(secrets.token_bytes(32), bcrypt.gensalt()).decode("ascii"),
            name=SERVICE_USER_NAME,
            role=UserRole.ADMIN,
            is_active=True,
            user_type="SERVICE",
            is_customer_admin=False,
        )
        db.add(user)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            user = db.query(User).filter(User.email == SERVICE_USER_EMAIL).one()
        else:
            db.refresh(user)
    changed = False
    if user.role != UserRole.ADMIN:
        user.role = UserRole.ADMIN
        changed = True
    if not user.is_active:
        user.is_active = True
        changed = True
    if user.user_type != "SERVICE":
        user.user_type = "SERVICE"
        changed = True
    if changed:
        db.commit()
        db.refresh(user)
    return user


def _touch_last_used(db: Session, row: StaffServiceKey) -> None:
    try:
        row.last_used_at = datetime.utcnow()
        db.commit()
    except Exception:
        db.rollback()
        logger.warning("Failed to update last_used_at on staff service key id=%s", row.id)


def evaluate(
    db: Session,
    plaintext: str,
    method: str,
    path: str,
    body: bytes = b"",
) -> KeyDecision:
    """Verify a key and decide whether this request is in scope.

    Revoked, expired, and unknown keys are rejected here. There is no cache,
    so revoke and expiry apply on the next request.
    """
    presented_prefix = prefix_for(plaintext) if plaintext else None
    if not is_staff_service_key(plaintext):
        return KeyDecision(
            ok=False,
            status_code=401,
            detail="Invalid API key",
            outcome="invalid",
            key_prefix=presented_prefix,
        )

    candidates = (
        db.query(StaffServiceKey)
        .filter(StaffServiceKey.key_prefix == presented_prefix)
        .all()
    )
    for row in candidates:
        try:
            ok = bcrypt.checkpw(_to_bcrypt_bytes(plaintext), row.key_hash.encode("ascii"))
        except (ValueError, TypeError):
            logger.warning("Bcrypt verification raised on staff service key id=%s", row.id)
            continue
        if not ok:
            continue

        key_id = row.id
        key_name = row.name
        key_prefix = row.key_prefix
        status = row.status
        revoked_at = row.revoked_at
        expires_at = _naive_utc(row.expires_at)
        granted = _scopes_of(row)
        _touch_last_used(db, row)

        if status == "revoked" or revoked_at is not None:
            return KeyDecision(
                ok=False,
                status_code=401,
                detail="API key has been revoked",
                outcome="revoked",
                key_id=key_id,
                key_name=key_name,
                key_prefix=key_prefix,
            )
        if expires_at is not None and expires_at <= datetime.utcnow():
            return KeyDecision(
                ok=False,
                status_code=401,
                detail="API key has expired",
                outcome="expired",
                key_id=key_id,
                key_name=key_name,
                key_prefix=key_prefix,
            )

        allowed, reason = route_allowed(method, path, body, granted)
        if not allowed:
            return KeyDecision(
                ok=False,
                status_code=403,
                detail=reason,
                outcome="denied",
                key_id=key_id,
                key_name=key_name,
                key_prefix=key_prefix,
            )

        identity = _identity_for(get_or_create_service_user(db))
        return KeyDecision(
            ok=True,
            status_code=200,
            detail="allowed",
            outcome="allowed",
            user=identity,
            key_id=key_id,
            key_name=key_name,
            key_prefix=key_prefix,
        )

    return KeyDecision(
        ok=False,
        status_code=401,
        detail="Invalid API key",
        outcome="invalid",
        key_prefix=presented_prefix,
    )


def create_key(
    db: Session,
    *,
    name: str,
    created_by_user_id: Optional[int],
    scopes: Optional[list[str]] = None,
    expires_at: Optional[datetime] = None,
    environment: str = "live",
) -> tuple[StaffServiceKey, str]:
    """Create a key. Returns ``(row, plaintext)``. Plaintext is not stored."""
    cleaned_name = (name or "").strip()
    if not cleaned_name:
        raise ValueError("Name is required")
    if len(cleaned_name) > 200:
        raise ValueError("Name is too long")
    stored_scopes = normalize_scopes(scopes)
    exp = _naive_utc(expires_at)
    if exp is not None and exp <= datetime.utcnow():
        raise ValueError("expires_at must be in the future")

    plaintext = generate_plaintext(environment=environment)
    row = StaffServiceKey(
        name=cleaned_name,
        key_prefix=prefix_for(plaintext),
        key_hash=hash_plaintext(plaintext),
        scopes=stored_scopes,
        status="active",
        created_by_user_id=created_by_user_id,
        expires_at=exp,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row, plaintext


def revoke_key(
    db: Session,
    *,
    key_id: int,
    revoked_by_user_id: Optional[int] = None,
) -> Optional[StaffServiceKey]:
    """Mark a key revoked. Idempotent. Takes effect on the next request."""
    row = db.query(StaffServiceKey).filter(StaffServiceKey.id == key_id).first()
    if row is None:
        return None
    if row.status == "revoked":
        return row
    row.status = "revoked"
    row.revoked_at = datetime.utcnow()
    row.revoked_by_user_id = revoked_by_user_id
    db.commit()
    db.refresh(row)
    return row


def write_audit(
    db: Session,
    *,
    key_id: Optional[int],
    key_name: Optional[str],
    key_prefix: Optional[str],
    method: str,
    path: str,
    decision: str,
    status_code: int,
) -> None:
    db.add(
        StaffServiceKeyAudit(
            key_id=key_id,
            key_name=(key_name or None),
            key_prefix=(key_prefix[:_PREFIX_LEN] if key_prefix else None),
            method=(method or "")[:10],
            path=normalize_path(path)[:300],
            decision=(decision or "")[:20],
            status_code=int(status_code),
        )
    )
    db.commit()
