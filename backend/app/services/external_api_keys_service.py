"""
External API key service (SQB-03).

The plaintext key is generated server-side and returned ONCE in the
create-key response. After that, only the bcrypt hash + the 12-char
prefix live in the DB. Verification iterates active keys whose prefix
matches and bcrypt-checks the candidate — bcrypt's comparison is
constant-time per-row.

The verifier returns the row (so callers can read supplier_account_code
+ rate_limit_rpm) and updates last_used_at. A None return means "no
match" — callers map this to 401 UNAUTHORIZED without leaking which
side of the check failed.
"""
from __future__ import annotations

import logging
import secrets
from datetime import datetime
from typing import Optional

import bcrypt
from sqlalchemy.orm import Session

from app.db.models import ExternalApiKey

logger = logging.getLogger(__name__)

# We call bcrypt directly rather than via passlib's CryptContext. passlib
# 1.7.4 runs a backend self-test that hashes a 73-byte probe password on
# first use; bcrypt >= 4.1 raises "password cannot be longer than 72 bytes"
# instead of truncating, which breaks passlib init under newer bcrypt. The
# output format ($2b$...) is identical, so hashes minted either way verify
# interchangeably — existing stored hashes keep working.
_BCRYPT_MAX_BYTES = 72  # bcrypt only considers the first 72 bytes


def _to_bcrypt_bytes(plaintext: str) -> bytes:
    """Encode and clamp to bcrypt's 72-byte ceiling (our keys are ~41 bytes)."""
    return plaintext.encode("utf-8")[:_BCRYPT_MAX_BYTES]

# Plaintext format: `sai_<env>_<32 random url-safe chars>`. The env
# label is informational only (verification ignores it); production
# keys use 'live', dev keys use 'test'. Total length: 8 + 32 = 40 chars.
_PLAINTEXT_PREFIX_LEN = 12
_RANDOM_SUFFIX_BYTES = 24  # token_urlsafe(24) → ~32 chars


def generate_plaintext(environment: str = "live") -> str:
    """Generate a fresh plaintext API key. Returned ONCE on create."""
    suffix = secrets.token_urlsafe(_RANDOM_SUFFIX_BYTES)
    return f"sai_{environment}_{suffix}"


def hash_plaintext(plaintext: str) -> str:
    """Bcrypt-hash the plaintext for storage. Returns a standard $2b$ string."""
    return bcrypt.hashpw(_to_bcrypt_bytes(plaintext), bcrypt.gensalt()).decode("ascii")


def prefix_for(plaintext: str) -> str:
    """First 12 chars of the plaintext — stored for admin display."""
    return plaintext[:_PLAINTEXT_PREFIX_LEN]


def verify(
    db: Session,
    plaintext: str,
    *,
    expected_account_code: Optional[str] = None,
) -> Optional[ExternalApiKey]:
    """Verify a plaintext API key.

    Returns the active `ExternalApiKey` row when the plaintext matches.
    When `expected_account_code` is provided, the row's
    supplier_account_code MUST match — mismatches return None so
    callers report 404 NOT_FOUND for cross-key probes (per the
    Service.AI cross-tenant rule: don't leak existence).

    Side-effect on success: updates `last_used_at`. Best-effort —
    failures here log a warning but don't fail the request.
    """
    if not plaintext or len(plaintext) < _PLAINTEXT_PREFIX_LEN + 1:
        return None

    prefix = prefix_for(plaintext)
    # Narrow by prefix first (indexed). With 12 url-safe chars there are
    # ~64^12 ≈ 4.7e21 possible prefixes; collisions across a tenant's
    # key set are negligible. We still bcrypt-verify every candidate.
    candidates = (
        db.query(ExternalApiKey)
        .filter(
            ExternalApiKey.key_prefix == prefix,
            ExternalApiKey.status == "active",
        )
        .all()
    )

    for row in candidates:
        try:
            ok = bcrypt.checkpw(_to_bcrypt_bytes(plaintext), row.key_hash.encode("ascii"))
        except (ValueError, TypeError):  # pragma: no cover — malformed stored hash
            logger.warning("Bcrypt verification raised on key id=%s", row.id)
            continue
        if not ok:
            continue
        if (
            expected_account_code is not None
            and row.supplier_account_code != expected_account_code
        ):
            return None
        # Best-effort last-used update.
        try:
            row.last_used_at = datetime.utcnow()
            db.commit()
        except Exception:
            db.rollback()
            logger.warning("Failed to update last_used_at on key id=%s", row.id)
        return row

    return None


def create_key(
    db: Session,
    *,
    name: str,
    supplier_account_code: str,
    rate_limit_rpm: int = 600,
    notes: Optional[str] = None,
    created_by_user_id: Optional[int] = None,
    environment: str = "live",
) -> tuple[ExternalApiKey, str]:
    """Create a new key. Returns (row, plaintext). Plaintext is shown
    to the caller ONCE — the DB only holds the hash + prefix."""
    plaintext = generate_plaintext(environment=environment)
    row = ExternalApiKey(
        name=name,
        key_prefix=prefix_for(plaintext),
        key_hash=hash_plaintext(plaintext),
        supplier_account_code=supplier_account_code,
        status="active",
        rate_limit_rpm=rate_limit_rpm,
        notes=notes,
        created_by_user_id=created_by_user_id,
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
) -> Optional[ExternalApiKey]:
    """Mark a key revoked. Idempotent — re-revoking is a no-op."""
    row = db.query(ExternalApiKey).filter(ExternalApiKey.id == key_id).first()
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


def rotate_key(
    db: Session,
    *,
    key_id: int,
    rotated_by_user_id: Optional[int] = None,
) -> Optional[tuple[ExternalApiKey, ExternalApiKey, str]]:
    """Rotate a key: revokes the old row and creates a new active one
    with the same name + account_code + rate limit. Returns
    (old_row, new_row, new_plaintext) or None if key_id is unknown."""
    old = db.query(ExternalApiKey).filter(ExternalApiKey.id == key_id).first()
    if old is None:
        return None
    new_row, plaintext = create_key(
        db,
        name=old.name,
        supplier_account_code=old.supplier_account_code,
        rate_limit_rpm=old.rate_limit_rpm,
        notes=old.notes,
        created_by_user_id=rotated_by_user_id,
    )
    revoked = revoke_key(db, key_id=old.id, revoked_by_user_id=rotated_by_user_id)
    assert revoked is not None
    return revoked, new_row, plaintext
