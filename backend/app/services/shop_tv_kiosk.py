"""Shop TV kiosk tokens.

The cast URL carries this secret instead of a staff JWT. A staff JWT can
open the rest of the portal. This token is stored as a SHA-256 hash, looked
up by its prefix, and accepted only by the board read. Revoking the row
rejects the next refresh. The plaintext is returned once and never stored.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from app.db.models import ShopTvKioskToken

SCOPE = "shop_tv:read"
_PREFIX_LEN = 12


def generate_plaintext() -> str:
    return "stv_" + secrets.token_urlsafe(32)


def hash_plaintext(plaintext: str) -> str:
    return hashlib.sha256(plaintext.encode("utf-8")).hexdigest()


def prefix_for(plaintext: str) -> str:
    return plaintext[:_PREFIX_LEN]


def create_token(
    db: Session,
    *,
    name: str,
    created_by_user_id: Optional[int],
) -> tuple[ShopTvKioskToken, str]:
    cleaned = (name or "").strip()
    if not cleaned:
        raise ValueError("Name is required")
    if len(cleaned) > 200:
        raise ValueError("Name is too long")
    plaintext = generate_plaintext()
    row = ShopTvKioskToken(
        name=cleaned,
        key_prefix=prefix_for(plaintext),
        key_hash=hash_plaintext(plaintext),
        scope=SCOPE,
        status="active",
        created_by_user_id=created_by_user_id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row, plaintext


def list_tokens(db: Session) -> list:
    return (
        db.query(ShopTvKioskToken)
        .order_by(ShopTvKioskToken.created_at.desc(), ShopTvKioskToken.id.desc())
        .all()
    )


def revoke_token(
    db: Session,
    *,
    token_id: int,
    revoked_by_user_id: Optional[int],
) -> Optional[ShopTvKioskToken]:
    row = db.query(ShopTvKioskToken).filter(ShopTvKioskToken.id == token_id).first()
    if row is None:
        return None
    if row.status != "revoked":
        row.status = "revoked"
        row.revoked_at = datetime.utcnow()
        row.revoked_by_user_id = revoked_by_user_id
        db.commit()
        db.refresh(row)
    return row


def authenticate(db: Session, plaintext: str) -> str:
    """Return ok, revoked, or invalid. Does not distinguish unknown from forged."""
    token = (plaintext or "").strip()
    if not token.startswith("stv_") or len(token) < 20:
        return "invalid"
    digest = hash_plaintext(token)
    rows = (
        db.query(ShopTvKioskToken)
        .filter(ShopTvKioskToken.key_prefix == prefix_for(token))
        .all()
    )
    match = None
    for row in rows:
        stored = row.key_hash or ""
        if len(stored) != len(digest):
            continue
        if hmac.compare_digest(stored, digest):
            match = row
            break
    if match is None or match.scope != SCOPE:
        return "invalid"
    if match.status != "active" or match.revoked_at is not None:
        return "revoked"
    if match.expires_at is not None and match.expires_at <= datetime.utcnow():
        return "revoked"
    try:
        match.last_used_at = datetime.utcnow()
        db.commit()
    except Exception:
        db.rollback()
    return "ok"


def public_row(row: ShopTvKioskToken) -> dict:
    return {
        "id": row.id,
        "name": row.name,
        "prefix": row.key_prefix,
        "scope": row.scope,
        "status": row.status,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "last_used_at": row.last_used_at.isoformat() if row.last_used_at else None,
        "revoked_at": row.revoked_at.isoformat() if row.revoked_at else None,
    }
