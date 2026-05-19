"""External API key service tests (SQB-03).

Exercises the pure helpers (generate / hash / prefix) without a DB,
then runs verify + create + revoke + rotate against an in-memory
SQLite session. The User FK is satisfied by inserting a dummy admin
row before each test that touches `created_by_user_id`.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.models import Base, ExternalApiKey, User, UserRole
from app.services.external_api_keys_service import (
    create_key,
    generate_plaintext,
    hash_plaintext,
    prefix_for,
    revoke_key,
    rotate_key,
    verify,
)


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def session():
    """Fresh in-memory SQLite session per test.

    Creates ONLY the tables the external-api-keys path touches. The
    full Base.metadata.create_all fails on SQLite because some other
    models in the codebase use Postgres-specific types (e.g. ARRAY on
    parse_examples). We don't need any of that for these tests.
    """
    engine = create_engine("sqlite://", future=True)
    User.__table__.create(engine, checkfirst=True)
    ExternalApiKey.__table__.create(engine, checkfirst=True)
    TestSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = TestSession()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture
def admin_user(session):
    user = User(
        email="admin@test.local",
        password_hash="x",  # unused — service is bcrypt-aware but tests don't auth
        role=UserRole.ADMIN,
        is_active=True,
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


# ─────────────────────────────────────────────────────────────────────────────
# Pure helpers
# ─────────────────────────────────────────────────────────────────────────────


class TestPureHelpers:
    def test_generate_plaintext_has_env_prefix(self):
        plaintext = generate_plaintext(environment="live")
        assert plaintext.startswith("sai_live_")
        assert len(plaintext) >= 30  # 8 prefix + ~24 random chars

    def test_generate_plaintext_test_environment(self):
        plaintext = generate_plaintext(environment="test")
        assert plaintext.startswith("sai_test_")

    def test_generate_plaintext_unique(self):
        a = generate_plaintext()
        b = generate_plaintext()
        assert a != b

    def test_prefix_is_first_12_chars(self):
        plaintext = "sai_live_AbCdEfGhIjKlMnOp"
        assert prefix_for(plaintext) == "sai_live_AbC"

    def test_hash_then_verify_locally(self):
        plaintext = generate_plaintext()
        h = hash_plaintext(plaintext)
        # Bcrypt prefix
        assert h.startswith("$2")
        assert len(h) > 30


# ─────────────────────────────────────────────────────────────────────────────
# create_key
# ─────────────────────────────────────────────────────────────────────────────


class TestCreateKey:
    def test_returns_row_and_plaintext(self, session, admin_user):
        row, plaintext = create_key(
            session,
            name="Elevated Doors prod",
            supplier_account_code="ED-001",
            created_by_user_id=admin_user.id,
        )
        assert row.id is not None
        assert row.status == "active"
        assert row.key_prefix == plaintext[:12]
        # Hash must not equal plaintext
        assert row.key_hash != plaintext
        # Plaintext format
        assert plaintext.startswith("sai_live_")

    def test_default_rate_limit_is_600(self, session, admin_user):
        row, _ = create_key(
            session,
            name="X",
            supplier_account_code="ED-001",
            created_by_user_id=admin_user.id,
        )
        assert row.rate_limit_rpm == 600

    def test_custom_rate_limit_persisted(self, session, admin_user):
        row, _ = create_key(
            session,
            name="X",
            supplier_account_code="ED-001",
            rate_limit_rpm=120,
            created_by_user_id=admin_user.id,
        )
        assert row.rate_limit_rpm == 120


# ─────────────────────────────────────────────────────────────────────────────
# verify
# ─────────────────────────────────────────────────────────────────────────────


class TestVerify:
    def test_returns_row_on_match(self, session, admin_user):
        row, plaintext = create_key(
            session, name="X", supplier_account_code="ED-001",
            created_by_user_id=admin_user.id,
        )
        result = verify(session, plaintext)
        assert result is not None
        assert result.id == row.id

    def test_returns_none_on_wrong_plaintext(self, session, admin_user):
        _row, _plaintext = create_key(
            session, name="X", supplier_account_code="ED-001",
            created_by_user_id=admin_user.id,
        )
        # Same prefix, different suffix — bcrypt verify must fail.
        forged = "sai_live_ZZZZZZZZZZZZZZZZZZZZZZZZZZ"
        assert verify(session, forged) is None

    def test_returns_none_for_revoked_key(self, session, admin_user):
        row, plaintext = create_key(
            session, name="X", supplier_account_code="ED-001",
            created_by_user_id=admin_user.id,
        )
        revoke_key(session, key_id=row.id, revoked_by_user_id=admin_user.id)
        assert verify(session, plaintext) is None

    def test_account_code_mismatch_returns_none(self, session, admin_user):
        _row, plaintext = create_key(
            session, name="X", supplier_account_code="ED-001",
            created_by_user_id=admin_user.id,
        )
        result = verify(session, plaintext, expected_account_code="SOMEONE-ELSE")
        assert result is None

    def test_account_code_match_returns_row(self, session, admin_user):
        _row, plaintext = create_key(
            session, name="X", supplier_account_code="ED-001",
            created_by_user_id=admin_user.id,
        )
        result = verify(session, plaintext, expected_account_code="ED-001")
        assert result is not None

    def test_updates_last_used_at(self, session, admin_user):
        row, plaintext = create_key(
            session, name="X", supplier_account_code="ED-001",
            created_by_user_id=admin_user.id,
        )
        assert row.last_used_at is None
        verify(session, plaintext)
        session.refresh(row)
        assert row.last_used_at is not None

    def test_empty_plaintext_returns_none(self, session):
        assert verify(session, "") is None
        assert verify(session, "x") is None  # too short to even have a prefix

    def test_unknown_prefix_returns_none(self, session):
        # No key in DB at all — verifier should still cope.
        assert verify(session, "sai_live_NOPENOPENOPENOPENOPENOPE") is None


# ─────────────────────────────────────────────────────────────────────────────
# revoke_key
# ─────────────────────────────────────────────────────────────────────────────


class TestRevokeKey:
    def test_marks_status_revoked(self, session, admin_user):
        row, _ = create_key(
            session, name="X", supplier_account_code="ED-001",
            created_by_user_id=admin_user.id,
        )
        revoked = revoke_key(session, key_id=row.id, revoked_by_user_id=admin_user.id)
        assert revoked is not None
        assert revoked.status == "revoked"
        assert revoked.revoked_at is not None
        assert revoked.revoked_by_user_id == admin_user.id

    def test_idempotent(self, session, admin_user):
        row, _ = create_key(
            session, name="X", supplier_account_code="ED-001",
            created_by_user_id=admin_user.id,
        )
        first = revoke_key(session, key_id=row.id, revoked_by_user_id=admin_user.id)
        second = revoke_key(session, key_id=row.id, revoked_by_user_id=admin_user.id)
        assert first is not None and second is not None
        # revoked_at should not have moved on the second call.
        assert first.revoked_at == second.revoked_at

    def test_unknown_id_returns_none(self, session):
        assert revoke_key(session, key_id=99_999) is None


# ─────────────────────────────────────────────────────────────────────────────
# rotate_key
# ─────────────────────────────────────────────────────────────────────────────


class TestRotateKey:
    def test_returns_old_new_and_new_plaintext(self, session, admin_user):
        row, _orig_plaintext = create_key(
            session, name="X", supplier_account_code="ED-001", rate_limit_rpm=300,
            created_by_user_id=admin_user.id,
        )
        result = rotate_key(session, key_id=row.id, rotated_by_user_id=admin_user.id)
        assert result is not None
        old, new, plaintext = result
        assert old.status == "revoked"
        assert new.status == "active"
        assert new.id != old.id
        assert new.name == old.name
        assert new.supplier_account_code == old.supplier_account_code
        assert new.rate_limit_rpm == old.rate_limit_rpm
        assert plaintext.startswith("sai_live_")

    def test_old_plaintext_no_longer_verifies(self, session, admin_user):
        row, orig_plaintext = create_key(
            session, name="X", supplier_account_code="ED-001",
            created_by_user_id=admin_user.id,
        )
        result = rotate_key(session, key_id=row.id, rotated_by_user_id=admin_user.id)
        assert result is not None
        _old, _new, new_plaintext = result
        assert verify(session, orig_plaintext) is None
        assert verify(session, new_plaintext) is not None

    def test_unknown_id_returns_none(self, session):
        assert rotate_key(session, key_id=99_999) is None
