"""Creator tags for door-configurator sales quotes.

A tag is ``<SHORTNAME>-<NNNN>`` (or ``EMAIL-<NNNN>`` for the unattended
email auto-quote path). It is written to the BC sales quote Your Reference
field on every generate, and used as External Document No. only when the
operator left PO / Reference blank.

``NNNN`` is that creator's own running count, stored in
``configurator_quote_counters`` and advanced with a single upsert so two
overlapping Generate clicks cannot take the same number. Regenerating an
existing BC quote reuses the tag already stored on its snapshot.
"""

from __future__ import annotations

import re
from typing import Optional, Tuple

from sqlalchemy.orm import Session

from app.db.models import ConfiguratorQuoteCounter, QuoteSnapshot

# BC sales header "Your Reference" and External Document No. are both 35.
BC_REFERENCE_MAX = 35
_EMAIL_COUNTER_KEY = "email"
_ALNUM = re.compile(r"[^A-Za-z0-9]")


def shortname_from_email(email: Optional[str]) -> str:
    """Uppercase A-Z0-9 local-part. ``mpadda@upwardor.com`` -> ``MPADDA``."""
    raw = (email or "").strip()
    local = raw.split("@", 1)[0] if raw else ""
    cleaned = _ALNUM.sub("", local).upper()
    return cleaned or "USER"


def format_creator_tag(prefix: str, sequence: int) -> str:
    """``PREFIX-0001``, shortened so the whole tag fits in 35 characters.

    The sequence is zero-padded to at least 4 digits and grows past 9999
    rather than wrapping. The prefix is what gets truncated.
    """
    cleaned = _ALNUM.sub("", (prefix or "").upper()) or "USER"
    number = f"{max(int(sequence), 1):04d}"
    suffix = f"-{number}"
    if len(suffix) >= BC_REFERENCE_MAX:
        return suffix[-BC_REFERENCE_MAX:]
    room = BC_REFERENCE_MAX - len(suffix)
    return f"{cleaned[:room]}{suffix}"


def external_document_number(typed_po: Optional[str], creator_tag: str) -> str:
    """Keep a typed PO exactly. A blank field gets the creator tag."""
    if typed_po is not None and str(typed_po).strip() != "":
        return typed_po
    return creator_tag


def _counter_key(user) -> str:
    if user is None:
        return _EMAIL_COUNTER_KEY
    user_id = getattr(user, "id", None)
    if user_id is not None:
        return f"user:{user_id}"
    email = (getattr(user, "email", None) or "").strip().lower()
    return f"email-user:{email or 'unknown'}"


def _next_sequence(db: Session, counter_key: str) -> int:
    """Atomically take the next number for this creator.

    One INSERT .. ON CONFLICT DO UPDATE statement. PostgreSQL and SQLite
    both hold the row lock until the surrounding transaction commits, so
    a second click blocks and then sees the incremented value.
    """
    bind = db.get_bind()
    dialect = bind.dialect.name
    if dialect == "postgresql":
        from sqlalchemy.dialects.postgresql import insert as dialect_insert
    else:
        from sqlalchemy.dialects.sqlite import insert as dialect_insert

    table = ConfiguratorQuoteCounter.__table__
    stmt = dialect_insert(table).values(counter_key=counter_key, last_issued=1)
    stmt = stmt.on_conflict_do_update(
        index_elements=["counter_key"],
        set_={"last_issued": table.c.last_issued + 1},
    ).returning(table.c.last_issued)
    issued = db.execute(stmt).scalar_one()
    db.flush()
    return int(issued)


def allocate_creator_tag(
    db: Session,
    user,
) -> Tuple[str, Optional[int], Optional[str]]:
    """Reserve the next tag for this staff user, or for the email counter."""
    if user is None:
        sequence = _next_sequence(db, _EMAIL_COUNTER_KEY)
        return format_creator_tag("EMAIL", sequence), None, None

    sequence = _next_sequence(db, _counter_key(user))
    email = getattr(user, "email", None)
    user_id = getattr(user, "id", None)
    return format_creator_tag(shortname_from_email(email), sequence), user_id, email


def resolve_creator_tag(
    db: Session,
    user,
    bc_quote_id: Optional[str] = None,
) -> Tuple[str, Optional[int], Optional[str]]:
    """Reuse the tag already saved for this BC quote, otherwise allocate one."""
    if bc_quote_id:
        existing = (
            db.query(QuoteSnapshot)
            .filter(QuoteSnapshot.bc_quote_id == bc_quote_id)
            .first()
        )
        if existing is not None and existing.creator_tag:
            return existing.creator_tag, existing.creator_user_id, existing.creator_email
    return allocate_creator_tag(db, user)
